"""
Knowledge Synthesis API Routes

Endpoints for triggering Knowledge extraction from Memories via LLM workflow.
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.rls_dependencies import get_db_with_rls
from app.domain.memory_operations import MemoryOperations
from app.workflows.knowledge_synthesis import get_knowledge_synthesis_graph


router = APIRouter(prefix="/knowledge/synthesize", tags=["knowledge-synthesis"])


# ============================================================================
# Response Models
# ============================================================================

from pydantic import BaseModel, Field


class KnowledgeSynthesisResponse(BaseModel):
    """Response from knowledge synthesis workflow."""

    memory_id: str = Field(..., description="Memory UUID that was processed")
    knowledge_ids: List[str] = Field(default_factory=list, description="Created Knowledge UUIDs (may be empty)")
    deleted_count: int = Field(default=0, description="Number of previous Knowledge items replaced (deduplication)")
    created_count: int = Field(default=0, description="Number of new Knowledge items created")
    skip_reason: Optional[str] = Field(None, description="Why synthesis was skipped (if applicable)")
    error: Optional[str] = Field(None, description="Error message (if failed)")
    success: bool = Field(..., description="Whether synthesis completed successfully")


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/{memory_id}", response_model=KnowledgeSynthesisResponse, status_code=status.HTTP_200_OK)
async def synthesize_knowledge_from_memory(
    memory_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> KnowledgeSynthesisResponse:
    """
    Trigger knowledge synthesis for a Memory.

    **Workflow**:
    1. Fetch Memory by ID (with RLS context)
    2. Call LLM to extract Knowledge items
    3. Persist Knowledge to database with audit logs
    4. Return created Knowledge IDs

    **Deduplication**:
    - Default strategy: "replace" (deletes existing Knowledge with source_id=memory_id)
    - Can be configured via DEDUPLICATION_STRATEGY env var

    **Empty Extractions**:
    - If Memory contains no extractable knowledge (e.g., "Hello"), returns empty array
    - This is not an error - skip_reason will be "no_extractions"

    **Error Handling**:
    - Memory not found → 404 Not Found
    - LLM failure → 200 OK with error field populated
    - DB write failure → 200 OK with error field populated
    - Workflow always completes (errors captured in response)

    **Parameters**:
    - memory_id: UUID of Memory to process

    **Returns**:
    - knowledge_ids: List of created Knowledge UUIDs (may be empty)
    - deleted_count: Number of previous Knowledge items replaced
    - created_count: Number of new Knowledge items created
    - skip_reason: "no_extractions" | "invalid_memory" | None
    - error: Error message if failed
    - success: True if workflow completed without errors

    **Example Response** (success):
    ```json
    {
      "memory_id": "123e4567-e89b-12d3-a456-426614174000",
      "knowledge_ids": ["uuid1", "uuid2", "uuid3"],
      "deleted_count": 0,
      "created_count": 3,
      "skip_reason": null,
      "error": null,
      "success": true
    }
    ```

    **Example Response** (no extractions):
    ```json
    {
      "memory_id": "123e4567-e89b-12d3-a456-426614174000",
      "knowledge_ids": [],
      "deleted_count": 0,
      "created_count": 0,
      "skip_reason": "no_extractions",
      "error": null,
      "success": true
    }
    ```

    **Example Response** (error):
    ```json
    {
      "memory_id": "123e4567-e89b-12d3-a456-426614174000",
      "knowledge_ids": [],
      "deleted_count": 0,
      "created_count": 0,
      "skip_reason": "invalid_memory",
      "error": "Memory not found or deleted",
      "success": false
    }
    ```
    """
    # Validate Memory exists (RLS will enforce ownership)
    memory = MemoryOperations.get_by_id(db, memory_id, include_deleted=False)

    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory {memory_id} not found or deleted"
        )

    # Get workflow graph (singleton)
    graph = await get_knowledge_synthesis_graph()

    # Invoke workflow
    # Thread ID format: "knowledge-{memory_id}" (isolated checkpointing per Memory)
    result = await graph.ainvoke(
        {"memory_id": str(memory_id)},
        config={"configurable": {"thread_id": f"knowledge-{memory_id}"}}
    )

    # Extract results from state
    knowledge_ids = result.get("knowledge_ids", [])
    deleted_count = result.get("deleted_count", 0)
    created_count = result.get("created_count", 0)
    skip_reason = result.get("skip_reason")
    error = result.get("error")

    # Determine success (no error field populated)
    success = error is None

    return KnowledgeSynthesisResponse(
        memory_id=str(memory_id),
        knowledge_ids=knowledge_ids,
        deleted_count=deleted_count,
        created_count=created_count,
        skip_reason=skip_reason,
        error=error,
        success=success,
    )


@router.get("/status/{memory_id}", response_model=dict)
async def get_synthesis_status(
    memory_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> dict:
    """
    Get synthesis status for a Memory (future enhancement).

    **Not Yet Implemented**:
    - Query checkpoint state to see if synthesis in progress
    - Return progress percentage (which node currently executing)
    - Useful for long-running syntheses

    **Current Behavior**:
    - Returns placeholder response
    - Will be implemented in Phase 6 or 7

    **Parameters**:
    - memory_id: UUID of Memory

    **Returns**:
    - status: "not_started" | "in_progress" | "completed" | "failed"
    - current_node: Which node currently executing (if in_progress)
    - progress_percent: 0-100
    """
    return {
        "status": "not_implemented",
        "message": "Synthesis status tracking not yet implemented. Use POST /{memory_id} to trigger synthesis.",
    }
