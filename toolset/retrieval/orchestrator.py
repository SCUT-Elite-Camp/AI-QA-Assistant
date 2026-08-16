import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from threading import BoundedSemaphore
from typing import Callable, Dict, List, Optional

from retrieval.fusion import (
    RetrievalPath,
    chunk_key,
    weighted_rrf_with_reserves,
)
from retrieval.query_rewriter import contains_cjk
from retrieval.query_router import QueryRouter


ChannelSearch = Callable[[str, int, str, Dict], List[Dict]]


class RetrievalCapacityError(RuntimeError):
    """Raised when optional retrieval work exceeds the shared capacity bound."""


class _BoundedExecutor:
    def __init__(self, max_workers: int, max_pending: int) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="retrieval-extension",
        )
        self._capacity = BoundedSemaphore(max_workers + max_pending)

    def submit(self, function, /, *args, **kwargs) -> Future:
        if not self._capacity.acquire(blocking=False):
            raise RetrievalCapacityError("retrieval extension capacity exhausted")
        try:
            future = self._executor.submit(function, *args, **kwargs)
        except Exception:
            self._capacity.release()
            raise
        future.add_done_callback(lambda _future: self._capacity.release())
        return future


_SHARED_EXECUTOR = _BoundedExecutor(max_workers=8, max_pending=16)


@dataclass(frozen=True)
class RetrievalOrchestratorConfig:
    rewrite_timeout_ms: int = 1200
    rewrite_max_variants: int = 2
    total_budget_ms: int = 2000
    fusion_candidate_limit: int = 20
    original_candidate_reserve: int = 5
    variant_unique_reserve: int = 2
    cross_language_enabled: bool = False
    retrieval_expansion_enabled: bool = True

    def __post_init__(self) -> None:
        if self.rewrite_timeout_ms <= 0 or self.total_budget_ms <= 0:
            raise ValueError("retrieval timeouts must be positive")
        if not 0 <= self.rewrite_max_variants <= 2:
            raise ValueError("rewrite_max_variants must be from 0 to 2")
        if not 1 <= self.fusion_candidate_limit <= 100:
            raise ValueError("fusion_candidate_limit must be from 1 to 100")
        for name, value in (
            ("original_candidate_reserve", self.original_candidate_reserve),
            ("variant_unique_reserve", self.variant_unique_reserve),
        ):
            if not 0 <= value <= self.fusion_candidate_limit:
                raise ValueError(f"{name} must be from 0 to candidate limit")


@dataclass
class RetrievalObservation:
    rewrite_status: str = "disabled"
    rewrite_latency_ms: int = 0
    query_count: int = 1
    selected_route: str = "legacy"
    retriever_paths: List[str] = field(default_factory=list)
    candidate_count_by_path: Dict[str, int] = field(default_factory=dict)
    unique_candidate_count: int = 0
    fallback_reason: str = "none"
    rerank_used: bool = False
    protected_original_count: int = 0
    protected_variant_unique_count: int = 0
    preferred_rerank_query: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


def default_observation(mode: str) -> Dict:
    observation = RetrievalObservation(selected_route=f"legacy_{mode}")
    return observation.to_dict()


class RetrievalOrchestrator:
    """Coordinate optional rewrite, routing, fallback, and rank fusion."""

    def __init__(
        self,
        query_rewriter,
        query_router: QueryRouter,
        config: Optional[RetrievalOrchestratorConfig] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.query_rewriter = query_rewriter
        self.query_router = query_router
        self.config = config or RetrievalOrchestratorConfig()
        self.logger = logger or logging.getLogger(__name__)

    def search(
        self,
        query: str,
        candidate_k: int,
        requested_top_k: int,
        mode: str,
        filters: Dict,
        started: float,
        trace_id: str,
        channel_search: ChannelSearch,
    ) -> tuple[List[Dict], Dict]:
        decision = self.query_router.route(query, mode)
        cross_language = (
            self.config.cross_language_enabled
            and mode in {"hybrid", "bm25"}
            and contains_cjk(query)
        )
        retrievers = decision.retrievers
        if cross_language and mode == "hybrid":
            retrievers = ("vector",)
        exact_profile = decision.exact if mode == "hybrid" else None
        observation = RetrievalObservation(selected_route=decision.selected_route)
        pending: List[Future] = []
        paths: List[RetrievalPath] = []
        errors = []

        should_rewrite = self.config.retrieval_expansion_enabled or cross_language
        rewrite_future = None
        if should_rewrite:
            rewrite_future = self._submit_optional(
                pending,
                self._rewrite_with_status,
                query,
                cross_language,
                trace_id=trace_id,
            )
        auxiliary = {}
        for retriever in retrievers[1:]:
            future = self._submit_optional(
                pending,
                channel_search,
                query,
                candidate_k,
                retriever,
                filters,
                trace_id=trace_id,
            )
            if future is not None:
                auxiliary[future] = ("q0", retriever, 1.0)

        primary_retriever = retrievers[0]
        try:
            original_rows = channel_search(
                query, candidate_k, primary_retriever, filters
            )
            paths.append(
                self._make_path(
                    "q0", primary_retriever, 1.0, original_rows, exact_profile
                )
            )
        except Exception as exc:
            errors.append((f"q0:{primary_retriever}", exc))

        variants = (
            self._collect_rewrite(rewrite_future, observation, started)
            if should_rewrite
            else []
        )
        queries = [("q0", query, 1.0)] + [
            (f"q{index}", variant, 0.8)
            for index, variant in enumerate(variants, start=1)
        ]
        observation.query_count = len(queries)
        if cross_language and variants:
            observation.preferred_rerank_query = variants[0]

        extension_futures = dict(auxiliary)
        for query_id, variant, query_weight in queries[1:]:
            variant_retrievers = ("bm25",) if cross_language else retrievers
            for retriever in variant_retrievers:
                if self._remaining_seconds(started) <= 0:
                    break
                future = self._submit_optional(
                    pending,
                    channel_search,
                    variant,
                    candidate_k,
                    retriever,
                    filters,
                    trace_id=trace_id,
                )
                if future is not None:
                    extension_futures[future] = (
                        query_id,
                        retriever,
                        query_weight,
                    )
        self._collect_paths(
            extension_futures,
            paths,
            errors,
            exact_profile,
            self._remaining_seconds(started),
        )

        if mode == "hybrid" and not decision.exact and not cross_language:
            fallback_reason = self._fallback_reason(
                paths, errors, requested_top_k, bool(variants)
            )
            if fallback_reason:
                observation.fallback_reason = fallback_reason
                fallback_futures = {}
                for query_id, variant, query_weight in queries:
                    if self._remaining_seconds(started) <= 0:
                        break
                    future = self._submit_optional(
                        pending,
                        channel_search,
                        variant,
                        candidate_k,
                        "bm25",
                        filters,
                        trace_id=trace_id,
                    )
                    if future is not None:
                        fallback_futures[future] = (
                            query_id,
                            "bm25",
                            query_weight,
                        )
                self._collect_paths(
                    fallback_futures,
                    paths,
                    errors,
                    False,
                    self._remaining_seconds(started),
                )

        self._cancel_unfinished(pending, trace_id)
        if not paths:
            if errors:
                raise errors[0][1]
            return [], observation.to_dict()

        observation.retriever_paths = [path.path_id for path in paths]
        observation.candidate_count_by_path = {
            path.path_id: len(path.rows) for path in paths
        }
        original_path = next(
            (
                path
                for path in paths
                if path.query_id == "q0"
                and path.retriever == primary_retriever
            ),
            None,
        )
        successful_extensions = [
            path
            for path in paths
            if path is not original_path and path.rows
        ]
        if original_path is not None and not successful_extensions:
            observation.protected_original_count = len(original_path.rows)
            observation.unique_candidate_count = len(
                {chunk_key(row) for row in original_path.rows}
            )
            return list(original_path.rows), observation.to_dict()

        fused, reserves = weighted_rrf_with_reserves(
            paths,
            self.config.fusion_candidate_limit,
            self.config.original_candidate_reserve,
            self.config.variant_unique_reserve,
        )
        observation.protected_original_count = reserves["original"]
        observation.protected_variant_unique_count = reserves["variant_unique"]
        observation.unique_candidate_count = len(fused)
        return fused, observation.to_dict()

    def _submit_optional(
        self,
        pending: List[Future],
        function,
        *args,
        trace_id: str,
    ) -> Optional[Future]:
        try:
            future = _SHARED_EXECUTOR.submit(function, *args)
        except RetrievalCapacityError:
            self.logger.warning(
                "[RETRIEVAL_CAPACITY_EXHAUSTED] trace_id=%s", trace_id
            )
            return None
        pending.append(future)
        return future

    def _collect_rewrite(
        self,
        future: Optional[Future],
        observation: RetrievalObservation,
        started: float,
    ) -> List[str]:
        if future is None:
            observation.rewrite_status = "capacity_limited"
            return []
        timeout = min(
            self._remaining_seconds(started),
            max(
                0.0,
                self.config.rewrite_timeout_ms / 1000.0
                - (time.perf_counter() - started),
            ),
        )
        done, _ = wait({future}, timeout=timeout)
        if future not in done:
            future.cancel()
            observation.rewrite_status = "timeout"
            observation.rewrite_latency_ms = self.config.rewrite_timeout_ms
            return []
        variants, status, latency_ms = future.result()
        observation.rewrite_latency_ms = latency_ms
        if latency_ms > self.config.rewrite_timeout_ms:
            observation.rewrite_status = "timeout"
            return []
        observation.rewrite_status = status
        return variants

    def _rewrite_with_status(
        self,
        query: str,
        cross_language: bool,
    ) -> tuple[List[str], str, int]:
        started = time.perf_counter()
        try:
            if hasattr(self.query_rewriter, "rewrite_with_context"):
                variants, status = self.query_rewriter.rewrite_with_context(
                    query,
                    self.config.rewrite_max_variants,
                    cross_language,
                )
            elif hasattr(self.query_rewriter, "rewrite_with_status"):
                variants, status = self.query_rewriter.rewrite_with_status(
                    query, self.config.rewrite_max_variants
                )
            else:
                variants = self.query_rewriter.rewrite(
                    query, self.config.rewrite_max_variants
                )
                status = "success" if variants else "empty"
        except Exception as exc:
            self.logger.warning("[QUERY_REWRITE_FALLBACK] error=%s", exc)
            variants, status = [], "error"
        latency_ms = int((time.perf_counter() - started) * 1000)
        return list(variants[: self.config.rewrite_max_variants]), status, latency_ms

    @staticmethod
    def _collect_paths(
        futures: Dict[Future, tuple],
        paths: List[RetrievalPath],
        errors: list,
        exact: Optional[bool],
        timeout: float,
    ) -> None:
        if not futures or timeout <= 0:
            return
        done, _ = wait(set(futures), timeout=timeout)
        for future in done:
            query_id, retriever, query_weight = futures[future]
            try:
                rows = future.result()
                paths.append(
                    RetrievalOrchestrator._make_path(
                        query_id, retriever, query_weight, rows, exact
                    )
                )
            except Exception as exc:
                errors.append((f"{query_id}:{retriever}", exc))

    @staticmethod
    def _make_path(
        query_id: str,
        retriever: str,
        query_weight: float,
        rows: List[Dict],
        exact: Optional[bool],
    ) -> RetrievalPath:
        if exact is None:
            retriever_weight = 1.0
        elif exact:
            retriever_weight = 0.4 if retriever == "vector" else 0.6
        else:
            retriever_weight = 0.8 if retriever == "vector" else 0.2
        return RetrievalPath(
            query_id=query_id,
            retriever=retriever,
            query_weight=query_weight,
            retriever_weight=retriever_weight,
            rows=rows,
        )

    @staticmethod
    def _fallback_reason(
        paths: List[RetrievalPath],
        errors: list,
        top_k: int,
        has_variants: bool,
    ) -> Optional[str]:
        original = next(
            (
                path
                for path in paths
                if path.query_id == "q0" and path.retriever == "vector"
            ),
            None,
        )
        if original is None or not original.rows:
            return "original_no_candidates"
        if len(original.rows) < top_k:
            return "insufficient_candidates"
        if errors:
            return "retriever_error"
        if has_variants:
            vector_paths = [path for path in paths if path.retriever == "vector"]
            original_set = set(map(chunk_key, original.rows))
            rewritten_set = {
                key
                for path in vector_paths
                if path.query_id != "q0"
                for key in map(chunk_key, path.rows)
            }
            if rewritten_set and original_set.isdisjoint(rewritten_set):
                return "vector_rewrite_disjoint"
            result_sets = [set(map(chunk_key, path.rows)) for path in vector_paths]
            if not any(
                left & right
                for index, left in enumerate(result_sets)
                for right in result_sets[index + 1 :]
            ):
                return "no_multi_query_overlap"
        return None

    def _remaining_seconds(self, started: float) -> float:
        elapsed = time.perf_counter() - started
        return max(0.0, self.config.total_budget_ms / 1000.0 - elapsed)

    def _cancel_unfinished(self, pending: List[Future], trace_id: str) -> None:
        unfinished = [future for future in pending if not future.done()]
        if unfinished:
            self.logger.warning(
                "[RETRIEVAL_BUDGET_EXHAUSTED] trace_id=%s pending_tasks=%s",
                trace_id,
                len(unfinished),
            )
        for future in unfinished:
            future.cancel()
