"""Domain-layer exceptions.

These replace HTTPException in domain code, keeping the domain layer
free of HTTP awareness. Global exception handlers in main.py map
these to the appropriate HTTP status codes.
"""


class EntityNotFoundError(Exception):
    """Entity not found (or soft-deleted). Maps to HTTP 404."""

    def __init__(self, entity: str, entity_id=None):
        self.entity = entity
        self.entity_id = entity_id
        msg = f"{entity} {entity_id} not found" if entity_id else f"{entity} not found"
        super().__init__(msg)


class EntityDeletedError(Exception):
    """Entity exists but is soft-deleted. Maps to HTTP 410."""

    def __init__(self, entity: str, entity_id=None):
        self.entity = entity
        self.entity_id = entity_id
        msg = f"{entity} {entity_id} is deleted" if entity_id else f"{entity} is deleted"
        super().__init__(msg)


class DuplicateEntityError(Exception):
    """Duplicate entity or constraint violation. Maps to HTTP 409."""

    def __init__(self, entity: str, detail: str = ""):
        self.entity = entity
        self.detail = detail
        msg = f"Duplicate {entity}: {detail}" if detail else f"Duplicate {entity}"
        super().__init__(msg)


class DomainValidationError(Exception):
    """Business-rule validation failure. Maps to HTTP 400."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)
