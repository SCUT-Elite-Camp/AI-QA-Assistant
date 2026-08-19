import re

from agent.schemas.query_plan import SourceIntent, SourceIntentMode, SourceKind


_NON_RETRIEVAL_PRODUCT_LANGUAGE = re.compile(
    r"(如何|怎么|设计|实现|开发|创建).{0,16}(页面|按钮|功能|界面|菜单)|"
    r"(page|button|ui|feature).{0,16}(design|implement|build)",
    re.IGNORECASE,
)
_IMPLICIT_PERSONAL = re.compile(
    r"我(?:上周|最近|之前|刚刚|曾经)?(?:上传|保存|添加|导入)的|"
    r"我(?:的|签的)?(?:劳动)?合同|"
    r"另(?:外)?一个用户的资料库|"
    r"(?:contract|file|document)\s+i\s+(?:uploaded|saved)",
    re.IGNORECASE,
)


def heuristic_source_intent(
    query: str,
    *,
    enterprise_default: bool = True,
) -> SourceIntent:
    """One-release deterministic fallback for structured source planning."""
    normalized = query.casefold().strip()
    if not normalized:
        return SourceIntent()
    if _NON_RETRIEVAL_PRODUCT_LANGUAGE.search(normalized):
        return SourceIntent()

    sources: list[SourceKind] = []
    explicit = False
    attachment_markers = (
        "刚上传", "刚刚上传", "这个附件", "这份附件", "当前附件",
        "uploaded pdf", "this attachment", "attached file",
    )
    personal_markers = (
        "我的资料库", "个人资料库", "我的文件", "个人文件", "我保存的",
        "my library", "my files", "personal library",
    )
    enterprise_markers = (
        "公司", "企业知识库", "公司制度", "公司政策", "corporate policy",
        "company policy", "enterprise knowledge",
    )
    if any(marker in normalized for marker in attachment_markers):
        sources.append(SourceKind.CONVERSATION_ATTACHMENT)
        explicit = True
    if any(marker in normalized for marker in personal_markers):
        sources.append(SourceKind.PERSONAL_LIBRARY)
        explicit = True
    elif _IMPLICIT_PERSONAL.search(normalized):
        sources.append(SourceKind.PERSONAL_LIBRARY)
    if any(marker in normalized for marker in enterprise_markers):
        sources.append(SourceKind.ENTERPRISE_KB)
        explicit = True
    if not sources and enterprise_default:
        sources.append(SourceKind.ENTERPRISE_KB)
    return SourceIntent(
        sources=sources,
        mode=SourceIntentMode.EXPLICIT if explicit else SourceIntentMode.INFERRED,
        confidence=0.75 if sources else None,
    )
