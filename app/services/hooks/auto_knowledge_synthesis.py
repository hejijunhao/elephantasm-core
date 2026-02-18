"""
Auto Knowledge Synthesis Hook.

Fire-and-forget trigger that automatically invokes Knowledge Synthesis
workflow when a Memory is created via Memory Synthesis.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def _trigger_auto_knowledge_synthesis_async(memory_id: str) -> None:
    """
    Internal async function to trigger Knowledge Synthesis (fire-and-forget).

    This function is designed to be called via asyncio.create_task()
    and will not raise exceptions to the caller.

    Args:
        memory_id: UUID of Memory to synthesize Knowledge from

    Returns:
        None (fire-and-forget pattern)
    """
    try:
        from app.workflows.knowledge_synthesis import get_knowledge_synthesis_graph

        # Log trigger
        logger.info(f"🧠 Triggering Knowledge Synthesis for Memory {memory_id}")

        # Get workflow graph (singleton)
        graph = await get_knowledge_synthesis_graph()

        # Invoke workflow (await completion)
        result = await graph.ainvoke(
            {"memory_id": memory_id},
            config={"configurable": {"thread_id": f"knowledge-{memory_id}"}},
        )

        # Log results
        knowledge_ids = result.get("knowledge_ids", [])
        created_count = result.get("created_count", 0)
        skip_reason = result.get("skip_reason")
        error = result.get("error")

        if error:
            logger.warning(
                f"❌ Knowledge Synthesis failed for Memory {memory_id}: {error}"
            )
        elif skip_reason:
            logger.info(
                f"⊘ Knowledge Synthesis skipped for Memory {memory_id}: {skip_reason}"
            )
        else:
            # Show first 3 IDs for brevity
            ids_preview = knowledge_ids[:3] if len(knowledge_ids) > 3 else knowledge_ids
            logger.info(
                f"✅ Created {created_count} Knowledge items for Memory {memory_id} (IDs: {ids_preview}{'...' if len(knowledge_ids) > 3 else ''})"
            )

    except Exception as e:
        # Log error but don't raise (fire-and-forget)
        logger.error(
            f"❌ Unexpected error in Knowledge Synthesis trigger for Memory {memory_id}: {str(e)}",
            exc_info=True,
        )


def trigger_auto_knowledge_synthesis(memory_id: str) -> asyncio.Task | None:
    """
    Automatically trigger Knowledge Synthesis for a Memory (fire-and-forget).

    Creates an async task that runs independently of the caller.
    Safe to call from any async context. Returns None when background jobs are disabled.

    Args:
        memory_id: UUID of Memory to synthesize Knowledge from

    Returns:
        asyncio.Task for the background synthesis workflow, or None if disabled
    """
    from app.core.config import settings

    if not settings.ENABLE_BACKGROUND_JOBS:
        logger.debug(f"Knowledge Synthesis skipped for Memory {memory_id} (background jobs disabled)")
        return None

    task = asyncio.create_task(_trigger_auto_knowledge_synthesis_async(memory_id))
    return task
