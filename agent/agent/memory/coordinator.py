"""Prepare the single trusted Memory view consumed by one Agent turn."""

from collections.abc import Callable
from dataclasses import dataclass

from agent.config.settings import settings
from agent.memory.context_resolver import ContextResolver
from agent.memory.fact_visibility import current_time_ms
from agent.memory.memory_response_policy import MemoryResponsePolicy
from agent.memory.persistent_models import PersistentMemoryContext
from agent.schemas.chat import (
    ChatRequest,
    ContextArtifact,
    MemoryContextInput,
    MemoryMessage,
    MemoryRecall,
)


@dataclass(frozen=True)
class MemoryView:
    """Immutable projection of trusted Memory for one request."""

    history: tuple[MemoryMessage, ...] = ()
    context_artifact: ContextArtifact | None = None
    recall: MemoryRecall | None = None

    @property
    def has_prior_messages(self) -> bool:
        return any(message.role != "system" for message in self.history)

    def history_for_model(self) -> list[dict[str, str]]:
        return [
            {"role": message.role, "content": message.content}
            for message in self.history
        ]


class MemoryCoordinator:
    """Own turn-level resolution of trusted persistent Memory."""

    def __init__(
        self,
        *,
        context_resolver: ContextResolver | None = None,
        response_policy: MemoryResponsePolicy | None = None,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._context_resolver = context_resolver or ContextResolver()
        self._response_policy = response_policy or MemoryResponsePolicy()
        self._now_ms = now_ms or current_time_ms

    def prepare(self, request: ChatRequest) -> MemoryView:
        """Resolve caller-supplied trusted context once; never recover by session ID."""
        memory_context = getattr(request, "memory_context", None)
        if (
            not settings.PERSISTENT_MEMORY_ENABLED
            or not isinstance(memory_context, MemoryContextInput)
        ):
            return MemoryView()

        persistent_context = PersistentMemoryContext.from_input(memory_context)
        if not persistent_context.actor_authenticated:
            return MemoryView()

        visibility_cutoff_ms = self._now_ms()
        artifact = self._context_resolver.resolve(
            persistent_context,
            visibility_cutoff_ms=visibility_cutoff_ms,
        )
        if artifact is None:
            return MemoryView()

        recall = self._response_policy.resolve(
            request.query,
            persistent_context.facts,
            visibility_cutoff_ms=visibility_cutoff_ms,
        )
        return MemoryView(
            history=tuple(artifact.model_history),
            context_artifact=artifact,
            recall=recall,
        )
