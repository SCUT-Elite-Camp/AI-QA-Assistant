import os
from openai import OpenAI


def _build_client() -> OpenAI:
    """根据环境变量构建 OpenAI 兼容客户端"""
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL")
    if not api_key:
        raise RuntimeError("环境变量 OPENAI_API_KEY 未设置")

    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def embed_texts(texts: list[str], model: str = "text-embedding-3-small") -> list[list[float]]:
    """
    批量文本向量化。

    Args:
        texts: 待向量化的文本列表
        model: 嵌入模型名称，默认 text-embedding-3-small（1536 维）

    Returns:
        向量列表，每个向量为 1536 维 float 列表
    """
    if not texts:
        return []

    client = _build_client()
    response = client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]
