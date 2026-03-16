"""
Deep Sleep Phase - LLM-Powered Memory Curation

Intelligent operations using the Anima's identity as lens:
- Consolidate clusters of related memories (3+) into essential set (N→M)
- Merge redundant memory pairs (2) into coherent wholes (N→1)
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
    build_consolidation_prompt,
    build_merge_prompt,
    build_review_prompt,
    parse_consolidation_response,
    parse_merge_response,
    parse_review_response,
)

logger = logging.getLogger(__name__)


@dataclass
class DeepSleepResults:
    """Results from Deep Sleep phase."""

    merges_attempted: int = 0
    """Number of pairwise merge groups (2-memory clusters) processed."""

    merges_completed: int = 0
    """Number of successful pairwise merges."""

    clusters_processed: int = 0
    """Number of clusters (3+ memories) consolidated."""

    memories_consolidated_from: int = 0
    """Total source memories that were consolidated."""

    memories_consolidated_into: int = 0
    """Total new memories created from consolidation."""

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
    1. Process similarity clusters from Light Sleep
       - 2-memory clusters → pairwise merge (fast, cheap)
       - 3+ memory clusters → consolidation (N→M, stronger model)
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

    # Get LLM clients — merge, consolidation, and review use different models
    try:
        merge_llm_client = get_llm_client(
            provider=config.merge_llm_provider,
            model=config.merge_llm_model,
        )
        consolidation_llm_client = get_llm_client(
            provider=config.consolidation_llm_provider,
            model=config.consolidation_llm_model,
        )
        review_llm_client = get_llm_client(
            provider=config.review_llm_provider,
            model=config.review_llm_model,
        )
    except ValueError as e:
        logger.error(f"Failed to initialize LLM client: {e}")
        results.errors.append(f"LLM client initialization failed: {e}")
        return results

    # ── Cluster Processing Phase ──────────────────────────────
    all_merged_source_ids: set[UUID] = set()

    if light_results.clusters:
        logger.info(
            f"Processing {len(light_results.clusters)} similarity clusters"
        )
        for cluster_ids in light_results.clusters:
            try:
                if len(cluster_ids) == 2:
                    # Pair tier: pairwise merge (fast, cheap)
                    results.merges_attempted += 1
                    merged = _process_merge_group(
                        session, dream_session, cluster_ids,
                        context, merge_llm_client, config,
                    )
                    if merged:
                        results.merges_completed += 1
                        all_merged_source_ids.update(cluster_ids)
                else:
                    # Cluster tier: consolidation (N→M, stronger model)
                    new_memories = _process_cluster(
                        session, dream_session, cluster_ids,
                        context, consolidation_llm_client, config,
                    )
                    if new_memories:
                        results.clusters_processed += 1
                        results.memories_consolidated_from += len(cluster_ids)
                        results.memories_consolidated_into += len(new_memories)
                        all_merged_source_ids.update(cluster_ids)

            except Exception as e:
                error_msg = (
                    f"{'Merge' if len(cluster_ids) == 2 else 'Consolidation'} "
                    f"failed for cluster of {len(cluster_ids)}: "
                    f"{type(e).__name__}: {e}"
                )
                logger.warning(error_msg, exc_info=True)
                results.errors.append(error_msg)

    # Reload active memories after all merges/consolidations
    if all_merged_source_ids:
        context.memories = list(
            session.execute(
                select(Memory).where(
                    Memory.anima_id == context.anima_id,
                    Memory.is_deleted.is_(False),
                )
            ).scalars().all()
        )

    # ── Review Phase ──────────────────────────────────────────
    review_ids = light_results.review_candidates
    if review_ids:
        # Filter to memories that still exist and are active
        # (some may have been merged/consolidated in cluster phase)
        memories_to_review = [
            m
            for m in context.memories
            if m.id in review_ids
            and not m.is_deleted
            and m.state == MemoryState.ACTIVE
            and m.id not in all_merged_source_ids
        ]

        if memories_to_review:
            logger.info(f"Reviewing {len(memories_to_review)} flagged memories")
            review_results = _process_review_batch(
                session,
                dream_session,
                memories_to_review,
                context,
                review_llm_client,
                config,
            )
            results.reviews_attempted += review_results["attempted"]
            results.updates_completed += review_results["updates"]
            results.splits_completed += review_results["splits"]
            results.deletions_completed += review_results["deletions"]
            results.errors.extend(review_results["errors"])

    # ── Summary Log ───────────────────────────────────────────
    parts = []
    if results.merges_attempted:
        parts.append(f"{results.merges_completed}/{results.merges_attempted} pair merges")
    if results.clusters_processed:
        parts.append(
            f"{results.memories_consolidated_from}→{results.memories_consolidated_into} "
            f"across {results.clusters_processed} clusters"
        )
    if results.updates_completed:
        parts.append(f"{results.updates_completed} updates")
    if results.splits_completed:
        parts.append(f"{results.splits_completed} splits")
    if results.deletions_completed:
        parts.append(f"{results.deletions_completed} deletions")
    logger.info(f"Deep Sleep complete: {', '.join(parts) or 'no actions taken'}")

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

    # Execute merge (wrap single result into definitions list)
    new_memories = DreamerOperations.merge_memories(
        session,
        dream_session=dream_session,
        source_memory_ids=memory_ids,
        merged_definitions=[{
            "summary": decision.merged_summary,
            "importance": decision.importance,
            "confidence": decision.confidence,
        }],
        reasoning=decision.reasoning,
    )

    merged = new_memories[0]

    # Regenerate embedding for merged memory
    if config.regenerate_embeddings:
        regenerate_embedding(session, merged, config.embedding_model)

    logger.info(
        f"Merged {len(memories)} memories into {merged.id}: {decision.reasoning}"
    )

    return merged


def _process_cluster(
    session: Session,
    dream_session: DreamSession,
    cluster_ids: list[UUID],
    context: DreamContext,
    llm_client,
    config: DreamerConfig,
) -> list[Memory] | None:
    """
    Consolidate a cluster of 3+ related memories via LLM.

    Uses the consolidation prompt to ask the LLM to distill N memories
    into M essential memories (M << N). Each output is a self-contained
    memory with verbatim quotes from sources.

    Args:
        session: Database session
        dream_session: Parent dream session
        cluster_ids: IDs of memories in the cluster
        context: Dream context with identity/knowledge
        llm_client: LLM client instance (consolidation model)
        config: Dreamer configuration

    Returns:
        List of newly created Memory objects, or None if consolidation failed
    """
    # Fetch memories, filtering out deleted ones
    memories = [
        m for m in context.memories
        if m.id in cluster_ids and not m.is_deleted
    ]

    if len(memories) < 3:
        logger.debug(f"Cluster has <3 valid memories, skipping consolidation")
        return None

    # Build prompt — summaries_only for medium clusters (16-50)
    summaries_only = len(memories) > 15
    prompt = build_consolidation_prompt(
        memories=memories,
        identity=context.identity,
        knowledge=context.knowledge,
        summaries_only=summaries_only,
    )

    # Call LLM (sync)
    response_text = llm_client.call_sync(
        prompt,
        temperature=config.llm_temperature,
        max_tokens=config.consolidation_max_tokens,
    )

    # Parse response
    try:
        response_dict = llm_client.parse_json_response(response_text)
        decision = parse_consolidation_response(
            response_dict, num_source_memories=len(memories)
        )
    except (ValueError, KeyError, TypeError) as e:
        logger.warning(
            f"Failed to parse consolidation response for cluster of "
            f"{len(memories)}: {e}"
        )
        return None

    # Build merged_definitions from consolidation decision
    merged_definitions = [
        {
            "summary": cm.summary,
            "content": cm.content,
            "importance": cm.importance,
            "confidence": cm.confidence,
            "source_indices": cm.source_indices,
        }
        for cm in decision.consolidated_memories
    ]

    # Execute via generalized merge_memories (N→M)
    source_ids = [m.id for m in memories]
    new_memories = DreamerOperations.merge_memories(
        session,
        dream_session=dream_session,
        source_memory_ids=source_ids,
        merged_definitions=merged_definitions,
        reasoning=decision.reasoning,
    )

    # Regenerate embeddings for all new memories
    if config.regenerate_embeddings:
        for mem in new_memories:
            regenerate_embedding(session, mem, config.embedding_model)

    logger.info(
        f"Consolidated {len(memories)} memories into {len(new_memories)}: "
        f"{decision.reasoning}"
    )

    return new_memories


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
            error_msg = f"Batch review failed: {type(e).__name__}: {e}"
            logger.warning(error_msg, exc_info=True)
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
