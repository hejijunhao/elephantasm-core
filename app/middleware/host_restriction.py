"""
Host-based path restriction middleware.

Restricts api.elephantasm.com to SDK-only endpoints while allowing
full access via elephantasm.fly.dev (internal/dashboard use).

On the SDK domain, /docs and /redoc serve filtered API docs showing
only SDK endpoints. /api/openapi.json is intercepted and filtered.
"""

import copy

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import re

# Paths allowed on public SDK domain (api.elephantasm.com)
SDK_ALLOWED_PATTERNS = [
    r"^/api/health$",
    r"^/api/events$",
    r"^/api/animas$",
    r"^/api/animas/[^/]+$",
    r"^/api/animas/[^/]+/memory-packs/latest$",
    r"^/api/subscriptions/usage$",
]

# Compile patterns for performance
_SDK_PATTERNS = [re.compile(p) for p in SDK_ALLOWED_PATTERNS]

# Docs paths served on SDK domain (pass through to FastAPI)
_DOCS_PATHS = {"/docs", "/redoc", "/docs/oauth2-redirect"}

SDK_HOST = "api.elephantasm.com"


class HostRestrictionMiddleware(BaseHTTPMiddleware):
    """Restrict public SDK domain to allowlisted endpoints only."""

    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        self._filtered_spec_cache = None

    async def dispatch(self, request: Request, call_next):
        host = request.headers.get("host", "")
        path = request.url.path

        if SDK_HOST not in host:
            return await call_next(request)

        # Serve filtered OpenAPI spec on SDK domain
        if path == "/api/openapi.json":
            spec = self._get_filtered_spec(request)
            return JSONResponse(content=spec)

        # Allow docs UI (fetches filtered openapi.json above)
        if path in _DOCS_PATHS:
            return await call_next(request)

        # SDK endpoint allowlist
        if not self._is_sdk_path(path):
            return JSONResponse(
                status_code=404,
                content={"detail": "Not found"},
            )

        return await call_next(request)

    def _get_filtered_spec(self, request: Request) -> dict:
        """Return OpenAPI spec filtered to SDK-only paths."""
        if self._filtered_spec_cache is not None:
            return self._filtered_spec_cache

        full_spec = copy.deepcopy(request.app.openapi())

        # Filter paths to SDK-only
        filtered_paths = {}
        for path, operations in full_spec.get("paths", {}).items():
            if self._is_sdk_path(path):
                filtered_paths[path] = operations

        full_spec["paths"] = filtered_paths
        full_spec["info"]["title"] = "Elephantasm SDK API"
        full_spec["info"]["description"] = (
            "Public SDK endpoints for Elephantasm Long-Term Agentic Memory."
        )

        # Prune unused schemas from components
        used_refs = set()
        self._collect_refs(filtered_paths, used_refs)
        if "components" in full_spec and "schemas" in full_spec["components"]:
            full_spec["components"]["schemas"] = {
                name: schema
                for name, schema in full_spec["components"]["schemas"].items()
                if name in used_refs
            }
            # Second pass: schemas may reference other schemas
            self._collect_refs(full_spec["components"]["schemas"], used_refs)
            full_spec["components"]["schemas"] = {
                name: schema
                for name, schema in full_spec["components"]["schemas"].items()
                if name in used_refs
            }

        # Prune unused tags
        sdk_tags = set()
        for operations in filtered_paths.values():
            for op in operations.values():
                if isinstance(op, dict):
                    sdk_tags.update(op.get("tags", []))
        if "tags" in full_spec:
            full_spec["tags"] = [
                t for t in full_spec["tags"] if t.get("name") in sdk_tags
            ]

        self._filtered_spec_cache = full_spec
        return full_spec

    @staticmethod
    def _collect_refs(obj, refs: set):
        """Recursively collect $ref schema names."""
        if isinstance(obj, dict):
            if "$ref" in obj:
                ref = obj["$ref"]
                if ref.startswith("#/components/schemas/"):
                    refs.add(ref.split("/")[-1])
            for v in obj.values():
                HostRestrictionMiddleware._collect_refs(v, refs)
        elif isinstance(obj, list):
            for item in obj:
                HostRestrictionMiddleware._collect_refs(item, refs)

    @staticmethod
    def _is_sdk_path(path: str) -> bool:
        """Check if path matches allowed SDK patterns."""
        path = path.rstrip("/")
        return any(pattern.match(path) for pattern in _SDK_PATTERNS)
