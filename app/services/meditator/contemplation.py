"""
Contemplation Phase - LLM-Powered Knowledge Curation

Three-tier processing (mirror of Dreamer's Deep Sleep):
1. Cluster Phase — process similarity clusters (merge pairs, consolidate 3+)
2. Review Phase — curate flagged knowledge (KEEP/UPDATE/RECLASSIFY/SPLIT/DELETE)
3. Embedding Regeneration — regenerate embeddings after mutations

Uses sync LLM clients — this code runs in a thread pool
(via BackgroundTasks), so blocking calls are safe.
"""

import logging
import time
from dataclasses import dataclass, field
from uuid import UUID

from sqlmodel import Session, select

from app.domain.meditator_operations import MeditatorOperations
from app.models.database.knowledge import Knowledge, KnowledgeType
from app.models.database.meditations import MeditationSession
from app.services.meditator.config import MeditatorConfig
from app.services.meditator.embeddings import regenerate_knowledge_embedding
from app.services.meditator.gather import MeditationContext
from app.services.meditator.prompts import (
    KnowledgeMergeDecision,
    KnowledgeReviewDecision,
    build_knowledge_consolidation_prompt,
    build_knowledge_merge_prompt,
    build_knowledge_review_prompt,
    parse_knowledge_consolidation_response,
    parse_knowledge_merge_response,
    parse_knowledge_review_response,
)
from app.services.meditator.reflection import ReflectionResults

logger = logging.getLogger(__name__)


@dataclass
class ContemplationResults:
    """Results from Contemplation phase."""

    merges_attempted: int = 0
    merges_completed: int = 0
    clusters_processed: int = 0
    knowledge_consolidated_from: int = 0
    knowledge_consolidated_into: int = 0
    reviews_attempted: int = 0
    updates_completed: int = 0
    reclassifications_completed: int = 0
    splits_completed: int = 0
    deletions_completed: int = 0
    clusters_deferred: int = 0
    reviews_deferred: int = 0
    errors: list[str] = field(default_factory=list)


def run_contemplation(
    session: Session,
    meditation_session: MeditationSession,
    context: MeditationContext,
    reflection_results: ReflectionResults,
    config: MeditatorConfig,
) -> ContemplationResults:
    """
    Execute Contemplation phase using sync LLM calls.

    1. Process similarity clusters from Reflection
    2. Review flagged knowledge through identity lens
    3. Regenerate embeddings for mutated items
    """
    from app.services.llm import get_llm_client

    results = ContemplationResults()

    try:
        merge_llm = get_llm_client(
            provider=config.merge_llm_provider,
            model=config.merge_llm_model,
        )
        consolidation_llm = get_llm_client(
            provider=config.consolidation_llm_provider,
            model=config.consolidation_llm_model,
        )
        review_llm = get_llm_client(
            provider=config.review_llm_provider,
            model=config.review_llm_model,
        )
    except ValueError as e:
        logger.error(f"Failed to initialize LLM client: {e}")
        results.errors.append(f"LLM client initialization failed: {e}")
        return results

    # ── Cluster Processing Phase ──────────────────────────────
    all_merged_source_ids: set[UUID] = set()

    if reflection_results.clusters:
        total_clusters = len(reflection_results.clusters)
        cap = config.max_clusters_per_session
        clusters_to_process = reflection_results.clusters[:cap]
        deferred = total_clusters - len(clusters_to_process)
        results.clusters_deferred = deferred

        if deferred > 0:
            logger.info(
                f"Processing {len(clusters_to_process)}/{total_clusters} "
                f"similarity clusters (capped, {deferred} deferred)"
            )
        else:
            logger.info(
                f"Processing {total_clusters} similarity clusters"
            )

        for cluster_ids in clusters_to_process:
            try:
                if len(cluster_ids) == 2:
                    results.merges_attempted += 1
                    merged = _process_merge_pair(
                        session, meditation_session, cluster_ids,
                        context, merge_llm, config,
                    )
                    if merged:
                        results.merges_completed += 1
                        all_merged_source_ids.update(cluster_ids)
                else:
                    new_items = _process_cluster(
                        session, meditation_session, cluster_ids,
                        context, consolidation_llm, config,
                    )
                    if new_items:
                        results.clusters_processed += 1
                        results.knowledge_consolidated_from += len(cluster_ids)
                        results.knowledge_consolidated_into += len(new_items)
                        all_merged_source_ids.update(cluster_ids)

            except Exception as e:
                error_msg = (
                    f"{'Merge' if len(cluster_ids) == 2 else 'Consolidation'} "
                    f"failed for cluster of {len(cluster_ids)}: "
                    f"{type(e).__name__}: {e}"
                )
                logger.warning(error_msg, exc_info=True)
                results.errors.append(error_msg)

            # Yield CPU between LLM calls so health checks can respond
            time.sleep(config.yield_interval_seconds)

    # Reload knowledge after merges/consolidations
    if all_merged_source_ids:
        context.knowledge = list(
            session.execute(
                select(Knowledge).where(
                    Knowledge.anima_id == context.anima_id,
                    Knowledge.is_deleted.is_(False),
                )
            ).scalars().all()
        )

    # ── Review Phase ──────────────────────────────────────────
    review_ids = reflection_results.review_candidates
    if review_ids:
        items_to_review = [
            k for k in context.knowledge
            if k.id in review_ids
            and not k.is_deleted
            and k.id not in all_merged_source_ids
        ]

        # Cap review candidates to prevent runaway Opus sessions
        review_cap = config.max_review_candidates
        if len(items_to_review) > review_cap:
            results.reviews_deferred = len(items_to_review) - review_cap
            logger.info(
                f"Capping review from {len(items_to_review)} to "
                f"{review_cap} items (deferred {results.reviews_deferred})"
            )
            items_to_review = items_to_review[:review_cap]

        if items_to_review:
            logger.info(f"Reviewing {len(items_to_review)} flagged knowledge items")
            review_results = _process_review_batch(
                session, meditation_session, items_to_review,
                context, review_llm, config,
            )
            results.reviews_attempted += review_results["attempted"]
            results.updates_completed += review_results["updates"]
            results.reclassifications_completed += review_results["reclassifications"]
            results.splits_completed += review_results["splits"]
            results.deletions_completed += review_results["deletions"]
            results.errors.extend(review_results["errors"])

    # ── Summary Log ───────────────────────────────────────────
    parts = []
    if results.merges_attempted:
        parts.append(f"{results.merges_completed}/{results.merges_attempted} pair merges")
    if results.clusters_processed:
        parts.append(
            f"{results.knowledge_consolidated_from}→{results.knowledge_consolidated_into} "
            f"across {results.clusters_processed} clusters"
        )
    if results.updates_completed:
        parts.append(f"{results.updates_completed} updates")
    if results.reclassifications_completed:
        parts.append(f"{results.reclassifications_completed} reclassifications")
    if results.splits_completed:
        parts.append(f"{results.splits_completed} splits")
    if results.deletions_completed:
        parts.append(f"{results.deletions_completed} deletions")
    if results.clusters_deferred or results.reviews_deferred:
        deferred_parts = []
        if results.clusters_deferred:
            deferred_parts.append(f"{results.clusters_deferred} clusters")
        if results.reviews_deferred:
            deferred_parts.append(f"{results.reviews_deferred} reviews")
        parts.append(f"deferred {', '.join(deferred_parts)}")
    logger.info(f"Contemplation complete: {', '.join(parts) or 'no actions taken'}")

    return results


def _process_merge_pair(
    session: Session,
    meditation_session: MeditationSession,
    knowledge_ids: list[UUID],
    context: MeditationContext,
    llm_client,
    config: MeditatorConfig,
) -> Knowledge | None:
    """Process a pair of potentially redundant knowledge items."""
    items = [
        k for k in context.knowledge
        if k.id in knowledge_ids and not k.is_deleted
    ]

    if len(items) < 2:
        return None

    prompt = build_knowledge_merge_prompt(
        knowledge_items=items,
        identity=context.identity,
        memories=context.memories,
    )

    response_text = llm_client.call_sync(
        prompt, temperature=config.llm_temperature, max_tokens=1024,
    )

    try:
        response_dict = llm_client.parse_json_response(response_text)
        decision = parse_knowledge_merge_response(response_dict)
    except (ValueError, KeyError, TypeError) as e:
        raise ValueError(f"Failed to parse merge response: {e}") from e

    if not decision.should_merge:
        logger.debug(f"LLM decided not to merge: {decision.reasoning}")
        return None

    new_items = MeditatorOperations.merge_knowledge(
        session,
        meditation_session=meditation_session,
        source_knowledge_ids=knowledge_ids,
        merged_definitions=[{
            "content": decision.merged_content,
            "summary": decision.merged_summary,
            "knowledge_type": decision.knowledge_type,
            "topic": decision.topic,
            "confidence": decision.confidence,
        }],
        reasoning=decision.reasoning,
    )

    merged = new_items[0]

    if config.regenerate_embeddings:
        regenerate_knowledge_embedding(session, merged, config.embedding_model)

    logger.info(
        f"Merged {len(items)} knowledge items into {merged.id}: {decision.reasoning}"
    )
    return merged


def _process_cluster(
    session: Session,
    meditation_session: MeditationSession,
    cluster_ids: list[UUID],
    context: MeditationContext,
    llm_client,
    config: MeditatorConfig,
) -> list[Knowledge] | None:
    """Consolidate a cluster of 3+ related knowledge items."""
    items = [
        k for k in context.knowledge
        if k.id in cluster_ids and not k.is_deleted
    ]

    if len(items) < 3:
        return None

    summaries_only = len(items) > 15
    prompt = build_knowledge_consolidation_prompt(
        knowledge_items=items,
        identity=context.identity,
        memories=context.memories,
        summaries_only=summaries_only,
    )

    response_text = llm_client.call_sync(
        prompt, temperature=config.llm_temperature,
        max_tokens=config.consolidation_max_tokens,
    )

    try:
        response_dict = llm_client.parse_json_response(response_text)
        decision = parse_knowledge_consolidation_response(
            response_dict, num_source_items=len(items)
        )
    except (ValueError, KeyError, TypeError) as e:
        raise ValueError(
            f"Failed to parse consolidation response for cluster of "
            f"{len(items)}: {e}"
        ) from e

    merged_definitions = [
        {
            "content": ck.content,
            "summary": ck.summary,
            "knowledge_type": ck.knowledge_type,
            "topic": ck.topic,
            "confidence": ck.confidence,
        }
        for ck in decision.consolidated_knowledge
    ]

    source_ids = [k.id for k in items]
    new_items = MeditatorOperations.merge_knowledge(
        session,
        meditation_session=meditation_session,
        source_knowledge_ids=source_ids,
        merged_definitions=merged_definitions,
        reasoning=decision.reasoning,
    )

    if config.regenerate_embeddings:
        for k in new_items:
            regenerate_knowledge_embedding(session, k, config.embedding_model)

    logger.info(
        f"Consolidated {len(items)} knowledge items into {len(new_items)}: "
        f"{decision.reasoning}"
    )
    return new_items


def _process_review_batch(
    session: Session,
    meditation_session: MeditationSession,
    items: list[Knowledge],
    context: MeditationContext,
    llm_client,
    config: MeditatorConfig,
) -> dict:
    """Review and curate a batch of knowledge items. Processes in batches."""
    results = {
        "attempted": 0,
        "updates": 0,
        "reclassifications": 0,
        "splits": 0,
        "deletions": 0,
        "errors": [],
    }

    batch_size = config.curation_batch_size

    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        results["attempted"] += len(batch)

        try:
            batch_results = _review_knowledge_batch(
                session, meditation_session, batch,
                context, llm_client, config,
            )
            results["updates"] += batch_results["updates"]
            results["reclassifications"] += batch_results["reclassifications"]
            results["splits"] += batch_results["splits"]
            results["deletions"] += batch_results["deletions"]
            results["errors"].extend(batch_results["errors"])
        except Exception as e:
            error_msg = f"Batch review failed: {type(e).__name__}: {e}"
            logger.warning(error_msg, exc_info=True)
            results["errors"].append(error_msg)

        # Yield CPU between review batches
        time.sleep(config.yield_interval_seconds)

    return results


def _review_knowledge_batch(
    session: Session,
    meditation_session: MeditationSession,
    items: list[Knowledge],
    context: MeditationContext,
    llm_client,
    config: MeditatorConfig,
) -> dict:
    """Review a single batch of knowledge items."""
    results = {"updates": 0, "reclassifications": 0, "splits": 0, "deletions": 0, "errors": []}

    prompt = build_knowledge_review_prompt(
        knowledge_items=items,
        identity=context.identity,
        memories=context.memories,
    )

    response_text = llm_client.call_sync(
        prompt, temperature=config.llm_temperature, max_tokens=2048,
    )

    try:
        response_list = llm_client.parse_json_response(response_text)
        if not isinstance(response_list, list):
            if "decisions" in response_list:
                response_list = response_list["decisions"]
            else:
                response_list = [response_list]
        decisions = parse_knowledge_review_response(response_list)
    except (ValueError, KeyError, TypeError) as e:
        error_msg = f"Failed to parse review response: {e}"
        logger.warning(error_msg)
        results["errors"].append(error_msg)
        return results

    for decision in decisions:
        if decision.index >= len(items):
            logger.warning(f"Decision index {decision.index} out of bounds")
            continue

        knowledge = items[decision.index]

        try:
            _apply_review_decision(
                session, meditation_session, knowledge, decision, config,
            )

            if decision.action == "UPDATE":
                results["updates"] += 1
            elif decision.action == "RECLASSIFY":
                results["reclassifications"] += 1
            elif decision.action == "SPLIT":
                results["splits"] += 1
            elif decision.action == "DELETE":
                results["deletions"] += 1

        except Exception as e:
            error_msg = f"Failed to apply {decision.action} to knowledge {knowledge.id}: {e}"
            logger.warning(error_msg)
            results["errors"].append(error_msg)

    return results


def _apply_review_decision(
    session: Session,
    meditation_session: MeditationSession,
    knowledge: Knowledge,
    decision: KnowledgeReviewDecision,
    config: MeditatorConfig,
) -> None:
    """Apply a single review decision to a knowledge item."""
    from app.models.database.meditations import MeditationPhase

    if decision.action == "KEEP":
        return

    elif decision.action == "UPDATE":
        updates = {}
        if decision.new_content:
            updates["content"] = decision.new_content
        if decision.new_summary:
            updates["summary"] = decision.new_summary
        if decision.new_confidence is not None:
            updates["confidence"] = decision.new_confidence

        if updates:
            updated = MeditatorOperations.update_knowledge(
                session,
                meditation_session=meditation_session,
                knowledge_id=knowledge.id,
                updates=updates,
                phase=MeditationPhase.CONTEMPLATION,
                reasoning=decision.reasoning,
            )

            if "content" in updates and config.regenerate_embeddings:
                regenerate_knowledge_embedding(session, updated, config.embedding_model)

    elif decision.action == "RECLASSIFY":
        new_type = None
        if decision.new_knowledge_type:
            try:
                new_type = KnowledgeType(decision.new_knowledge_type)
            except ValueError:
                logger.warning(f"Invalid knowledge_type: {decision.new_knowledge_type}")
                return

        MeditatorOperations.reclassify_knowledge(
            session,
            meditation_session=meditation_session,
            knowledge_id=knowledge.id,
            new_type=new_type,
            new_topic=decision.new_topic,
            reasoning=decision.reasoning,
        )

    elif decision.action == "SPLIT":
        if decision.split_into and len(decision.split_into) >= 2:
            split_defs = []
            for item in decision.split_into:
                if isinstance(item, dict) and item.get("content"):
                    split_defs.append(item)
                elif isinstance(item, str):
                    split_defs.append({"content": item})

            if len(split_defs) >= 2:
                new_items = MeditatorOperations.split_knowledge(
                    session,
                    meditation_session=meditation_session,
                    source_knowledge_id=knowledge.id,
                    split_definitions=split_defs,
                    reasoning=decision.reasoning,
                )

                if config.regenerate_embeddings:
                    for new_k in new_items:
                        regenerate_knowledge_embedding(session, new_k, config.embedding_model)

    elif decision.action == "DELETE":
        MeditatorOperations.delete_knowledge(
            session,
            meditation_session=meditation_session,
            knowledge_id=knowledge.id,
            phase=MeditationPhase.CONTEMPLATION,
            reasoning=decision.reasoning,
        )
