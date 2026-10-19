"""Structural source preferences shared by both execution modes; never grants."""
from agent.schemas.query_plan import SourceKind


def selected_sources(request, plan=None):
    explicit = getattr(request, "retrieval_sources", None)
    if explicit is not None:
        sources = list(dict.fromkeys(SourceKind(value) for value in explicit))
    elif plan is not None and plan.source_intent.sources:
        sources = list(dict.fromkeys(plan.source_intent.sources))
    else:
        sources = [SourceKind.ENTERPRISE_KB] if request.knowledge_base_retrieval_enabled else []
        if request.knowledge_base_retrieval_enabled and getattr(request, "personal_library_context", None) is not None:
            sources.append(SourceKind.PERSONAL_LIBRARY)
        context = getattr(request, "attachment_context", None)
        if context is not None and context.allowed_attachment_ids:
            sources.append(SourceKind.CONVERSATION_ATTACHMENT)
    context = getattr(request, "attachment_context", None)
    if context is not None and context.selected_attachment_ids and SourceKind.CONVERSATION_ATTACHMENT not in sources:
        sources.append(SourceKind.CONVERSATION_ATTACHMENT)
    if not request.knowledge_base_retrieval_enabled:
        sources = [source for source in sources if source == SourceKind.CONVERSATION_ATTACHMENT]
    return sources
