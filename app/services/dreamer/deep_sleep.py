"""
Deep Sleep Phase - LLM-Powered Memory Curation

Intelligent operations using the Anima's identity as lens:
- Merge redundant memories into coherent wholes
- Split conflated memories into distinct concepts
- Refine summaries for clarity and alignment
- Adjust importance/confidence scores
- Remove noise that doesn't serve the Anima's purpose

All operations maintain full audit trail via DreamerOperations.

Uses sync LLM clients — this code runs in a thread pool
(via asyncio.to_thread or Starlette BackgroundTasks), so
blocking calls are safe and avoid event loop lifecycle issues.
"""

import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlmodel import Session, select

from app.domain.dreamer_operations import DreamerOperations
from app.models.database.dreams import DreamPhase, DreamSession
from app.models.database.memories import Memory, MemoryState
from app.services.dreamer.config import DreamerConfig
from app.services.dreamer.embeddings import regenerate_embedding
from app.services.dreamer.gather import DreamContext
from app.services.dreamer.light_sleep import LightSleepResults
from app.services.dreamer.prompts import (
    MergeDecision,
    ReviewDecision,
    build_merge_prompt,
    build_review_prompt,
    parse_merge_response,
    parse_review_response,
)

logger = logging.getLogger(__name__)


@dataclass
class DeepSleepResults:
    """Results from Deep Sleep phase."""

    merges_attempted: int = 0
    """Number of merge groups processed."""

    merges_completed: int = 0
    """Number of successful merges."""

    reviews_attempted: int = 0
    """Number of memories reviewed."""

    updates_completed: int = 0
    """Number of memories updated (summary/scores refined)."""

    splits_completed: int = 0
    """Number of memories split into multiple."""

    deletions_completed: int = 0
    """Number of memories deleted as noise."""

    errors: list[str] = field(default_factory=list)
    """Non-fatal errors encountered during processing."""


def run_deep_sleep(
    session: Session,
    dream_session: DreamSession,
    context: DreamContext,
    light_results: LightSleepResults,
    config: DreamerConfig,
) -> DeepSleepResults:
    """
    Execute Deep Sleep phase using sync LLM calls.

    LLM-powered operations:
    1. Process merge candidates from Light Sleep
    2. Review flagged memories through identity lens
    3. Apply curation decisions (update/split/delete)

    Args:
        session: Database session
        dream_session: Parent dream session
        context: Gathered context from gather phase
        light_results: Results from Light Sleep phase
        config: Dreamer configuration

    Returns:
        DeepSleepResults with metrics and errors
    """
    # Lazy import to avoid circular dependency (LLM clients import workflow configs)
    from app.services.llm import get_llm_client

    results = DeepSleepResults()

    # Get LLM client using Dreamer's own config (not synthesis defaults)
    try:
        llm_client = get_llm_client(
            provider=config.llm_provider,
            model=config.llm_model,
        )
    except ValueError as e:
        logger.error(f"Failed to initialize LLM client: {e}")
        results.errors.append(f"LLM client initialization failed: {e}")
        return results

    # 1. Process merge candidates from Light Sleep
    if light_results.merge_candidates:
        logger.info(
            f"Processing {len(light_results.merge_candidates)} merge candidate groups"
        )
        for merge_group in light_results.merge_candidates:
            results.merges_attempted += 1
            try:
                merged = _process_merge_group(
                    session,
                    dream_session,
                    merge_group,
                    context,
                    llm_client,
                    config,
                )
                if merged:
                    results.merges_completed += 1
            except Exception as e:
                error_msg = f"Merge failed for group {merge_group}: {e}"
                logger.warning(error_msg)
                results.errors.append(error_msg)

    # Reload active memories after merges (bulk query instead of N refreshes)
    if light_results.merge_candidates:
        memory_ids = [m.id for m in context.memories]
        context.memories = list(
            session.exec(
                select(Memory).where(
                    Memory.id.in_(memory_ids), Memory.is_deleted == False
                )
            ).all()
        )

    # 2. Review flagged memories in batches
    review_ids = light_results.review_candidates
    if review_ids:
        # Filter to memories that still exist and are active
        # (some may have been merged in step 1)
        memories_to_review = [
            m
            for m in context.memories
            if m.id in review_ids and not m.is_deleted and m.state == MemoryState.ACTIVE
        ]

        # Exclude memories that were part of merge groups (already processed)
        merged_ids = set()
        for group in light_results.merge_candidates:
            merged_ids.update(group)
        memories_to_review = [m for m in memories_to_review if m.id not in merged_ids]

        if memories_to_review:
            logger.info(f"Reviewing {len(memories_to_review)} flagged memories")
            review_results = _process_review_batch(
                session,
                dream_session,
                memories_to_review,
                context,
                llm_client,
                config,
            )
            results.reviews_attempted += review_results["attempted"]
            results.updates_completed += review_results["updates"]
            results.splits_completed += review_results["splits"]
            results.deletions_completed += review_results["deletions"]
            results.errors.extend(review_results["errors"])

    logger.info(
        f"Deep Sleep complete: {results.merges_completed}/{results.merges_attempted} merges, "
        f"{results.updates_completed} updates, {results.splits_completed} splits, "
        f"{results.deletions_completed} deletions"
    )

    return results


def _process_merge_group(
    session: Session,
    dream_session: DreamSession,
    memory_ids: list[UUID],
    context: DreamContext,
    llm_client,
    config: DreamerConfig,
) -> Memory | None:
    """
    Process a group of potentially redundant memories.

    Uses LLM to:
    1. Confirm they should merge
    2. Generate unified summary
    3. Calculate combined importance/confidence

    Args:
        session: Database session
        dream_session: Parent dream session
        memory_ids: IDs of memories to potentially merge
        context: Dream context with identity/knowledge
        llm_client: LLM client instance
        config: Dreamer configuration

    Returns:
        Merged Memory if successful, None if no merge performed
    """
    # Fetch memories, filtering out deleted ones
    memories = [
        m
        for m in context.memories
        if m.id in memory_ids and not m.is_deleted
    ]

    if len(memories) < 2:
        logger.debug(f"Merge group has <2 valid memories, skipping")
        return None

    # Build prompt
    prompt = build_merge_prompt(
        memories=memories,
        identity=context.identity,
        knowledge=context.knowledge,
    )

    # Call LLM (sync)
    response_text = llm_client.call_sync(
        prompt,
        temperature=config.llm_temperature,
        max_tokens=1024,
    )

    # Parse response
    try:
        response_dict = llm_client.parse_json_response(response_text)
        decision = parse_merge_response(response_dict)
    except (ValueError, KeyError) as e:
        logger.warning(f"Failed to parse merge response: {e}")
        return None

    if not decision.should_merge:
        logger.debug(f"LLM decided not to merge: {decision.reasoning}")
        return None

    # Execute merge
    merged = DreamerOperations.merge_memories(
        session,
        dream_session=dream_session,
        source_memory_ids=memory_ids,
        merged_summary=decision.merged_summary,
        merged_importance=decision.importance,
        merged_confidence=decision.confidence,
        reasoning=decision.reasoning,
    )

    # Regenerate embedding for merged memory
    if config.regenerate_embeddings:
        regenerate_embedding(session, merged, config.embedding_model)

    logger.info(
        f"Merged {len(memories)} memories into {merged.id}: {decision.reasoning}"
    )

    return merged


def _process_review_batch(
    session: Session,
    dream_session: DreamSession,
    memories: list[Memory],
    context: DreamContext,
    llm_client,
    config: DreamerConfig,
) -> dict:
    """
    Review and curate a batch of memories through the identity lens.

    Processes memories in batches to manage context size and API limits.

    Returns:
        Dict with counts: attempted, updates, splits, deletions, errors
    """
    results = {
        "attempted": 0,
        "updates": 0,
        "splits": 0,
        "deletions": 0,
        "errors": [],
    }

    # Process in batches
    batch_size = config.curation_batch_size

    for i in range(0, len(memories), batch_size):
        batch = memories[i : i + batch_size]
        results["attempted"] += len(batch)

        try:
            batch_results = _review_memory_batch(
                session,
                dream_session,
                batch,
                context,
                llm_client,
                config,
            )
            results["updates"] += batch_results["updates"]
            results["splits"] += batch_results["splits"]
            results["deletions"] += batch_results["deletions"]
            results["errors"].extend(batch_results["errors"])
        except Exception as e:
            error_msg = f"Batch review failed: {e}"
            logger.warning(error_msg)
            results["errors"].append(error_msg)

    return results


def _review_memory_batch(
    session: Session,
    dream_session: DreamSession,
    memories: list[Memory],
    context: DreamContext,
    llm_client,
    config: DreamerConfig,
) -> dict:
    """
    Review a single batch of memories.

    Returns:
        Dict with counts: updates, splits, deletions, errors
    """
    results = {"updates": 0, "splits": 0, "deletions": 0, "errors": []}

    # Build prompt
    prompt = build_review_prompt(
        memories=memories,
        identity=context.identity,
        knowledge=context.knowledge,
    )

    # Call LLM (sync)
    response_text = llm_client.call_sync(
        prompt,
        temperature=config.llm_temperature,
        max_tokens=2048,  # Larger for batch responses
    )

    # Parse response
    try:
        response_list = llm_client.parse_json_response(response_text)
        if not isinstance(response_list, list):
            # Single response wrapped - try to extract
            if "decisions" in response_list:
                response_list = response_list["decisions"]
            else:
                response_list = [response_list]
        decisions = parse_review_response(response_list)
    except (ValueError, KeyError, TypeError) as e:
        error_msg = f"Failed to parse review response: {e}"
        logger.warning(error_msg)
        results["errors"].append(error_msg)
        return results

    # Apply decisions
    for decision in decisions:
        if decision.index >= len(memories):
            logger.warning(f"Decision index {decision.index} out of bounds")
            continue

        memory = memories[decision.index]

        try:
            _apply_review_decision(
                session,
                dream_session,
                memory,
                decision,
                config,
            )

            if decision.action == "UPDATE":
                results["updates"] += 1
            elif decision.action == "SPLIT":
                results["splits"] += 1
            elif decision.action == "DELETE":
                results["deletions"] += 1
            # KEEP = no action

        except Exception as e:
            error_msg = f"Failed to apply {decision.action} to memory {memory.id}: {e}"
            logger.warning(error_msg)
            results["errors"].append(error_msg)

    return results


def _apply_review_decision(
    session: Session,
    dream_session: DreamSession,
    memory: Memory,
    decision: ReviewDecision,
    config: DreamerConfig,
) -> None:
    """
    Apply a single review decision to a memory.

    Args:
        session: Database session
        dream_session: Parent dream session
        memory: Memory to apply decision to
        decision: ReviewDecision from LLM
        config: Dreamer configuration
    """
    if decision.action == "KEEP":
        # No action needed
        return

    elif decision.action == "UPDATE":
        updates = {}
        if decision.new_summary:
            updates["summary"] = decision.new_summary
        if decision.new_importance is not None:
            updates["importance"] = decision.new_importance
        if decision.new_confidence is not None:
            updates["confidence"] = decision.new_confidence

        if updates:
            updated = DreamerOperations.update_memory(
                session,
                dream_session=dream_session,
                memory_id=memory.id,
                updates=updates,
                phase=DreamPhase.DEEP_SLEEP,
                reasoning=decision.reasoning,
            )

            # Regenerate embedding if summary changed
            if "summary" in updates and config.regenerate_embeddings:
                regenerate_embedding(session, updated, config.embedding_model)

    elif decision.action == "SPLIT":
        if decision.split_into and len(decision.split_into) >= 2:
            new_memories = DreamerOperations.split_memory(
                session,
                dream_session=dream_session,
                source_memory_id=memory.id,
                split_summaries=decision.split_into,
                reasoning=decision.reasoning,
            )

            # Regenerate embeddings for new memories
            if config.regenerate_embeddings:
                for new_mem in new_memories:
                    regenerate_embedding(session, new_mem, config.embedding_model)

    elif decision.action == "DELETE":
        DreamerOperations.delete_memory(
            session,
            dream_session=dream_session,
            memory_id=memory.id,
            phase=DreamPhase.DEEP_SLEEP,
            reasoning=decision.reasoning,
        )
