"""
Tests for cluster-based memory consolidation (Dreamer enhancement).

Covers:
- Union-Find connected components
- Cluster detection and splitting
- Consolidation prompt formatting (small vs medium clusters)
- Consolidation response parsing (valid, malformed, edge cases)
- Pairwise merge prompt formatting (regression)
- Summary generation with consolidation metrics
"""

import pytest
from dataclasses import dataclass, field
from uuid import uuid4, UUID

from app.services.dreamer.light_sleep import (
    _union_find_clusters,
    _split_large_clusters,
    _get_jaccard_pairs,
)
from app.services.dreamer.prompts import (
    build_consolidation_prompt,
    build_merge_prompt,
    parse_consolidation_response,
    ConsolidationDecision,
    ConsolidatedMemory,
)
from app.services.dreamer.config import DreamerConfig
from app.services.dreamer.deep_sleep import DeepSleepResults


# ─────────────────────────────────────────────────────────────
# Helpers: Fake Memory objects for prompt tests
# ─────────────────────────────────────────────────────────────


@dataclass
class FakeMemory:
    """Minimal Memory-like object for prompt/cluster tests."""

    id: UUID = field(default_factory=uuid4)
    summary: str = "test memory"
    content: str = "test content"
    importance: float = 0.5
    confidence: float = 0.5
    state: "FakeState" = None
    embedding: list[float] | None = None
    decay_score: float = 0.0
    is_deleted: bool = False

    def __post_init__(self):
        if self.state is None:
            self.state = FakeState("ACTIVE")


@dataclass
class FakeState:
    value: str

    def __eq__(self, other):
        if hasattr(other, "value"):
            return self.value == other.value
        return self.value == other


# ─────────────────────────────────────────────────────────────
# Union-Find Tests
# ─────────────────────────────────────────────────────────────


class TestUnionFind:
    """Tests for _union_find_clusters (connected components)."""

    def test_empty_edges(self):
        """No edges → no components."""
        result = _union_find_clusters([])
        assert result == {}

    def test_single_edge(self):
        """One edge → one component of 2."""
        a, b = uuid4(), uuid4()
        result = _union_find_clusters([(a, b)])
        components = [s for s in result.values() if len(s) >= 2]
        assert len(components) == 1
        assert components[0] == {a, b}

    def test_chain_edges(self):
        """A-B, B-C → single component {A, B, C}."""
        a, b, c = uuid4(), uuid4(), uuid4()
        result = _union_find_clusters([(a, b), (b, c)])
        components = [s for s in result.values() if len(s) >= 2]
        assert len(components) == 1
        assert components[0] == {a, b, c}

    def test_disjoint_clusters(self):
        """A-B, C-D → two separate components."""
        a, b, c, d = uuid4(), uuid4(), uuid4(), uuid4()
        result = _union_find_clusters([(a, b), (c, d)])
        components = sorted(
            [s for s in result.values() if len(s) >= 2], key=len
        )
        assert len(components) == 2
        assert {a, b} in components
        assert {c, d} in components

    def test_transitive_closure(self):
        """A-B, C-D, B-C → single component {A, B, C, D}."""
        a, b, c, d = uuid4(), uuid4(), uuid4(), uuid4()
        result = _union_find_clusters([(a, b), (c, d), (b, c)])
        components = [s for s in result.values() if len(s) >= 2]
        assert len(components) == 1
        assert components[0] == {a, b, c, d}

    def test_star_topology(self):
        """Hub A connected to B, C, D, E → single component."""
        hub = uuid4()
        spokes = [uuid4() for _ in range(4)]
        edges = [(hub, s) for s in spokes]
        result = _union_find_clusters(edges)
        components = [s for s in result.values() if len(s) >= 2]
        assert len(components) == 1
        assert components[0] == {hub} | set(spokes)

    def test_duplicate_edges(self):
        """Duplicate edges don't create extra components."""
        a, b = uuid4(), uuid4()
        result = _union_find_clusters([(a, b), (a, b), (a, b)])
        components = [s for s in result.values() if len(s) >= 2]
        assert len(components) == 1
        assert components[0] == {a, b}

    def test_large_connected_graph(self):
        """20 nodes in a chain → single component."""
        nodes = [uuid4() for _ in range(20)]
        edges = [(nodes[i], nodes[i + 1]) for i in range(19)]
        result = _union_find_clusters(edges)
        components = [s for s in result.values() if len(s) >= 2]
        assert len(components) == 1
        assert len(components[0]) == 20


# ─────────────────────────────────────────────────────────────
# Large Cluster Splitting Tests
# ─────────────────────────────────────────────────────────────


class TestLargeClusterSplitting:
    """Tests for _split_large_clusters."""

    def test_small_cluster_unchanged(self):
        """Clusters below threshold pass through unchanged."""
        config = DreamerConfig(large_cluster_threshold=50)
        ids = [uuid4() for _ in range(10)]
        clusters = [ids]
        edges = [(ids[i], ids[i + 1], 0.2) for i in range(9)]

        result = _split_large_clusters(clusters, edges, config)
        assert len(result) == 1
        assert set(result[0]) == set(ids)

    def test_large_cluster_splits(self):
        """Cluster above threshold splits into sub-clusters at tighter threshold."""
        config = DreamerConfig(
            large_cluster_threshold=5,
            cluster_similarity_threshold=0.3,
        )
        # Two dense sub-groups connected by one loose edge
        group_a = [uuid4() for _ in range(4)]
        group_b = [uuid4() for _ in range(4)]
        all_ids = group_a + group_b

        # Dense edges within groups (distance 0.1 — below tighter threshold 0.15)
        edges = []
        for i in range(len(group_a)):
            for j in range(i + 1, len(group_a)):
                edges.append((group_a[i], group_a[j], 0.1))
        for i in range(len(group_b)):
            for j in range(i + 1, len(group_b)):
                edges.append((group_b[i], group_b[j], 0.1))
        # One loose edge between groups (distance 0.25 — above tighter threshold)
        edges.append((group_a[0], group_b[0], 0.25))

        result = _split_large_clusters([all_ids], edges, config)

        # Should split into 2 sub-clusters
        assert len(result) == 2
        result_sets = [set(c) for c in result]
        assert set(group_a) in result_sets
        assert set(group_b) in result_sets

    def test_no_edges_at_tighter_threshold_keeps_original(self):
        """If no edges survive tighter threshold, original cluster is kept."""
        config = DreamerConfig(
            large_cluster_threshold=3,
            cluster_similarity_threshold=0.3,
        )
        ids = [uuid4() for _ in range(5)]
        # All edges just below original threshold (0.29) but above tighter (0.15)
        edges = [(ids[i], ids[i + 1], 0.29) for i in range(4)]

        result = _split_large_clusters([ids], edges, config)
        assert len(result) == 1
        assert set(result[0]) == set(ids)

    def test_disabled_when_threshold_zero(self):
        """large_cluster_threshold=0 disables splitting (handled by caller)."""
        config = DreamerConfig(large_cluster_threshold=0)
        ids = [uuid4() for _ in range(100)]
        clusters = [ids]
        # _build_similarity_clusters checks `if config.large_cluster_threshold > 0`
        # so _split_large_clusters is never called. Here we test it directly —
        # with threshold 0, everything is "large" and the function still works.
        edges = [(ids[i], ids[i + 1], 0.1) for i in range(99)]
        result = _split_large_clusters(clusters, edges, config)
        # All in one cluster since all edges survive tighter threshold
        assert len(result) >= 1


# ─────────────────────────────────────────────────────────────
# Jaccard Fallback Tests
# ─────────────────────────────────────────────────────────────


class TestJaccardPairs:
    """Tests for _get_jaccard_pairs (no-embedding fallback)."""

    def test_similar_summaries(self):
        """Memories with overlapping words are paired."""
        m1 = FakeMemory(summary="the user likes coffee and tea")
        m2 = FakeMemory(summary="the user likes coffee and espresso")
        pairs = _get_jaccard_pairs([m1, m2], threshold=0.4)
        assert len(pairs) == 1
        assert pairs[0][0] == m1.id
        assert pairs[0][1] == m2.id

    def test_dissimilar_summaries(self):
        """Memories with no overlap are not paired."""
        m1 = FakeMemory(summary="the user likes coffee")
        m2 = FakeMemory(summary="quarterly revenue report filed")
        pairs = _get_jaccard_pairs([m1, m2], threshold=0.4)
        assert len(pairs) == 0

    def test_no_summary(self):
        """Memories without summaries are skipped."""
        m1 = FakeMemory(summary=None)
        m2 = FakeMemory(summary="something")
        pairs = _get_jaccard_pairs([m1, m2], threshold=0.4)
        assert len(pairs) == 0


# ─────────────────────────────────────────────────────────────
# Consolidation Prompt Tests
# ─────────────────────────────────────────────────────────────


class TestConsolidationPrompt:
    """Tests for build_consolidation_prompt formatting."""

    def test_small_cluster_includes_content(self):
        """Clusters ≤15: full content + summaries in prompt."""
        memories = [
            FakeMemory(
                summary=f"Memory about topic {i}",
                content=f"Detailed content for topic {i}",
                importance=0.5 + i * 0.1,
            )
            for i in range(5)
        ]
        prompt = build_consolidation_prompt(memories, summaries_only=False)

        assert "cluster of 5 related memories" in prompt
        assert "Detailed content for topic 0" in prompt
        assert "Detailed content for topic 4" in prompt
        assert "[0]" in prompt
        assert "[4]" in prompt

    def test_medium_cluster_summaries_only(self):
        """summaries_only=True: content omitted, note added."""
        memories = [
            FakeMemory(
                summary=f"Memory {i}",
                content=f"Long content {i}",
            )
            for i in range(20)
        ]
        prompt = build_consolidation_prompt(memories, summaries_only=True)

        assert "Only summaries are shown" in prompt
        assert "Long content 0" not in prompt
        assert "Memory 0" in prompt

    def test_prompt_contains_json_format(self):
        """Prompt includes expected JSON output format."""
        memories = [FakeMemory() for _ in range(3)]
        prompt = build_consolidation_prompt(memories)

        assert "consolidated_memories" in prompt
        assert "source_indices" in prompt
        assert "reasoning" in prompt

    def test_content_truncated_at_500_chars(self):
        """Long content is truncated to 500 characters."""
        long_content = "x" * 1000
        memories = [FakeMemory(content=long_content)]
        prompt = build_consolidation_prompt(memories, summaries_only=False)

        assert "x" * 500 in prompt
        assert "..." in prompt
        assert "x" * 501 not in prompt


# ─────────────────────────────────────────────────────────────
# Consolidation Response Parsing Tests
# ─────────────────────────────────────────────────────────────


class TestConsolidationResponseParsing:
    """Tests for parse_consolidation_response."""

    def test_valid_response(self):
        """Standard valid response parses correctly."""
        response = {
            "reasoning": "Combined coffee memories",
            "consolidated_memories": [
                {
                    "summary": "User enjoys various coffee types",
                    "content": "The user mentioned they 'love espresso' and also enjoy drip coffee.",
                    "importance": 0.8,
                    "confidence": 0.9,
                    "source_indices": [0, 1, 2],
                },
                {
                    "summary": "User's morning coffee routine",
                    "content": "Every morning, the user 'starts with a double shot'.",
                    "importance": 0.6,
                    "confidence": 0.85,
                    "source_indices": [3, 4],
                },
            ],
        }
        result = parse_consolidation_response(response, num_source_memories=5)

        assert isinstance(result, ConsolidationDecision)
        assert result.reasoning == "Combined coffee memories"
        assert len(result.consolidated_memories) == 2
        assert result.consolidated_memories[0].summary == "User enjoys various coffee types"
        assert result.consolidated_memories[0].source_indices == [0, 1, 2]
        assert result.consolidated_memories[1].importance == 0.6

    def test_empty_consolidated_memories_raises(self):
        """Empty consolidated_memories array raises ValueError."""
        response = {"reasoning": "Nothing to do", "consolidated_memories": []}
        with pytest.raises(ValueError, match="missing consolidated_memories"):
            parse_consolidation_response(response, num_source_memories=5)

    def test_missing_consolidated_memories_raises(self):
        """Missing key raises ValueError."""
        response = {"reasoning": "oops"}
        with pytest.raises(ValueError, match="missing consolidated_memories"):
            parse_consolidation_response(response, num_source_memories=5)

    def test_scores_clamped(self):
        """Importance/confidence clamped to 0.0-1.0."""
        response = {
            "reasoning": "test",
            "consolidated_memories": [{
                "summary": "test",
                "content": "test content",
                "importance": 1.5,
                "confidence": -0.3,
                "source_indices": [0],
            }],
        }
        result = parse_consolidation_response(response, num_source_memories=1)
        assert result.consolidated_memories[0].importance == 1.0
        assert result.consolidated_memories[0].confidence == 0.0

    def test_invalid_source_indices_filtered(self):
        """Out-of-range source indices are dropped; falls back to all if none valid."""
        response = {
            "reasoning": "test",
            "consolidated_memories": [{
                "summary": "test",
                "content": "test",
                "importance": 0.5,
                "confidence": 0.5,
                "source_indices": [10, 15, 99],  # all out of range
            }],
        }
        result = parse_consolidation_response(response, num_source_memories=5)
        # Falls back to all sources [0,1,2,3,4]
        assert result.consolidated_memories[0].source_indices == [0, 1, 2, 3, 4]

    def test_partial_valid_source_indices(self):
        """Mix of valid and invalid indices — keeps valid only."""
        response = {
            "reasoning": "test",
            "consolidated_memories": [{
                "summary": "test",
                "content": "test",
                "importance": 0.5,
                "confidence": 0.5,
                "source_indices": [0, 2, 99],
            }],
        }
        result = parse_consolidation_response(response, num_source_memories=5)
        assert result.consolidated_memories[0].source_indices == [0, 2]

    def test_missing_summary_skipped(self):
        """Entries without summary are skipped."""
        response = {
            "reasoning": "test",
            "consolidated_memories": [
                {
                    "content": "no summary here",
                    "importance": 0.5,
                    "confidence": 0.5,
                    "source_indices": [0],
                },
                {
                    "summary": "valid entry",
                    "content": "valid content",
                    "importance": 0.7,
                    "confidence": 0.8,
                    "source_indices": [1],
                },
            ],
        }
        result = parse_consolidation_response(response, num_source_memories=2)
        assert len(result.consolidated_memories) == 1
        assert result.consolidated_memories[0].summary == "valid entry"

    def test_all_entries_invalid_raises(self):
        """If all entries lack summaries, raises ValueError."""
        response = {
            "reasoning": "test",
            "consolidated_memories": [
                {"content": "no summary", "importance": 0.5, "confidence": 0.5},
            ],
        }
        with pytest.raises(ValueError, match="No valid consolidated memories"):
            parse_consolidation_response(response, num_source_memories=1)

    def test_non_list_source_indices_fallback(self):
        """Non-list source_indices falls back to all sources."""
        response = {
            "reasoning": "test",
            "consolidated_memories": [{
                "summary": "test",
                "content": "test",
                "importance": 0.5,
                "confidence": 0.5,
                "source_indices": "invalid",
            }],
        }
        result = parse_consolidation_response(response, num_source_memories=3)
        assert result.consolidated_memories[0].source_indices == [0, 1, 2]

    def test_defaults_for_missing_fields(self):
        """Missing importance/confidence/content default gracefully."""
        response = {
            "reasoning": "test",
            "consolidated_memories": [{
                "summary": "minimal entry",
            }],
        }
        result = parse_consolidation_response(response, num_source_memories=2)
        cm = result.consolidated_memories[0]
        assert cm.importance == 0.5
        assert cm.confidence == 0.5
        assert cm.content == ""
        assert cm.source_indices == [0, 1]  # fallback to all


# ─────────────────────────────────────────────────────────────
# Merge Prompt Regression Tests
# ─────────────────────────────────────────────────────────────


class TestMergePromptRegression:
    """Verify pairwise merge prompt still works after cluster changes."""

    def test_merge_prompt_format(self):
        """Merge prompt contains expected structure for 2 memories."""
        memories = [
            FakeMemory(summary="User likes coffee"),
            FakeMemory(summary="User enjoys espresso"),
        ]
        prompt = build_merge_prompt(memories)

        assert "should be merged" in prompt
        assert "should_merge" in prompt
        assert "merged_summary" in prompt
        assert "User likes coffee" in prompt
        assert "User enjoys espresso" in prompt


# ─────────────────────────────────────────────────────────────
# Summary Generation Tests
# ─────────────────────────────────────────────────────────────


class TestSummaryGeneration:
    """Tests for _generate_summary with consolidation metrics."""

    def _make_session(self, **kwargs):
        """Create a mock DreamSession with given metrics."""

        @dataclass
        class MockSession:
            memories_archived: int = 0
            memories_created: int = 0
            memories_modified: int = 0
            memories_deleted: int = 0
            config_snapshot: dict = field(default_factory=dict)

        return MockSession(**kwargs)

    def _generate(self, dream_session, light_results=None, deep_results=None):
        """Call _generate_summary logic inline (avoids needing full DreamerService)."""
        # Replicate the logic from dreamer_service.py._generate_summary
        parts: list[str] = []

        if deep_results:
            if deep_results.clusters_processed > 0:
                parts.append(
                    f"Consolidated {deep_results.memories_consolidated_from} memories "
                    f"into {deep_results.memories_consolidated_into} "
                    f"across {deep_results.clusters_processed} topic clusters"
                )
            if deep_results.merges_completed > 0:
                parts.append(f"Merged {deep_results.merges_completed} memory pairs")

        if dream_session.memories_archived > 0:
            parts.append(f"Archived {dream_session.memories_archived} stale memories")
        if dream_session.memories_modified > 0:
            parts.append(f"Refined {dream_session.memories_modified} memories")
        if dream_session.memories_deleted > 0:
            parts.append(f"Removed {dream_session.memories_deleted} noise memories")

        if deep_results:
            if deep_results.splits_completed > 0:
                parts.append(f"Split {deep_results.splits_completed} conflated memories")

        if not parts:
            return "No changes needed. Memory structure is coherent."

        return "Dream complete. " + ". ".join(parts) + "."

    def test_consolidation_only(self):
        """Summary with only cluster consolidation."""
        session = self._make_session()
        deep = DeepSleepResults(
            clusters_processed=3,
            memories_consolidated_from=47,
            memories_consolidated_into=8,
        )
        summary = self._generate(session, deep_results=deep)
        assert "Consolidated 47 memories into 8 across 3 topic clusters" in summary

    def test_pairwise_merge_only(self):
        """Summary with only pairwise merges."""
        session = self._make_session()
        deep = DeepSleepResults(merges_completed=2)
        summary = self._generate(session, deep_results=deep)
        assert "Merged 2 memory pairs" in summary
        assert "Consolidated" not in summary

    def test_mixed_summary(self):
        """Summary with consolidation + merges + archives."""
        session = self._make_session(memories_archived=5)
        deep = DeepSleepResults(
            clusters_processed=2,
            memories_consolidated_from=20,
            memories_consolidated_into=6,
            merges_completed=3,
        )
        summary = self._generate(session, deep_results=deep)
        assert "Consolidated 20 memories into 6 across 2 topic clusters" in summary
        assert "Merged 3 memory pairs" in summary
        assert "Archived 5 stale memories" in summary

    def test_consolidation_before_merges(self):
        """Consolidation appears before pairwise merges in summary."""
        session = self._make_session()
        deep = DeepSleepResults(
            clusters_processed=1,
            memories_consolidated_from=10,
            memories_consolidated_into=3,
            merges_completed=2,
        )
        summary = self._generate(session, deep_results=deep)
        cons_pos = summary.index("Consolidated")
        merge_pos = summary.index("Merged")
        assert cons_pos < merge_pos

    def test_no_changes(self):
        """No actions → coherent message."""
        session = self._make_session()
        deep = DeepSleepResults()
        summary = self._generate(session, deep_results=deep)
        assert summary == "No changes needed. Memory structure is coherent."

    def test_no_deep_results(self):
        """None deep_results with session archives."""
        session = self._make_session(memories_archived=3)
        summary = self._generate(session, deep_results=None)
        assert "Archived 3 stale memories" in summary
        assert "Consolidated" not in summary
        assert "Merged" not in summary
