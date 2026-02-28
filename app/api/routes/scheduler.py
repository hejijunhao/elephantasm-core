"""
Unified Scheduler API

Endpoints for all workflows.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field

from app.core.auth import require_current_user_id
from app.services.scheduler import get_scheduler_orchestrator, get_memory_synthesis_scheduler, get_dreamer_scheduler

router = APIRouter(prefix="/scheduler", tags=["Scheduler"])


class TriggerRequest(BaseModel):
    """Request model for manual workflow trigger."""
    anima_id: Optional[UUID] = Field(None, description="Single anima UUID (null = all animas)")


@router.get("/status")
async def get_scheduler_status(
    user_id: UUID = Depends(require_current_user_id),
) -> Dict[str, Any]:
    """
    Get status of all workflows and scheduler infrastructure.

    Returns unified view of:
    - Scheduler running state
    - All registered jobs
    - Per-workflow statistics
    """
    scheduler = get_scheduler_orchestrator()
    memory_synthesis = get_memory_synthesis_scheduler()
    dreamer = get_dreamer_scheduler()

    return {
        "scheduler": scheduler.get_status(),
        "workflows": {
            "memory_synthesis": memory_synthesis.get_status(),
            "dreamer": dreamer.get_status(),
            # Future workflows:
            # "lesson_extraction": lessons.get_status(),
            # "knowledge_consolidation": knowledge.get_status(),
            # "identity_evolution": identity.get_status(),
        }
    }


@router.post("/workflows/{workflow_name}/trigger")
async def trigger_workflow(
    workflow_name: str,
    request: TriggerRequest,
    user_id: UUID = Depends(require_current_user_id),
) -> Dict[str, Any]:
    """
    Manually trigger workflow execution.

    **Available workflows:**
    - `memory_synthesis`: Transform events → memories via LLM
    - `dreamer`: Memory curation (Light Sleep + Deep Sleep)

    **Trigger modes:**
    - `anima_id` provided: Single anima execution
    - `anima_id` null: All animas (parallel)
    """
    if workflow_name == "memory_synthesis":
        workflow_scheduler = get_memory_synthesis_scheduler()
    elif workflow_name == "dreamer":
        workflow_scheduler = get_dreamer_scheduler()
    else:
        raise HTTPException(status_code=404, detail=f"Unknown workflow: {workflow_name}")

    result = await workflow_scheduler.trigger_manual(request.anima_id)

    return {
        "workflow": workflow_name,
        "anima_id": str(request.anima_id) if request.anima_id else None,
        "result": result,
    }
