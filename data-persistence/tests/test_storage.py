import os
import random
import pytest
from pymilvus import connections
from storage.document_store import save_document, load_document, delete_document
from storage.milvus_store import MilvusStore

# 测试用的测试数据
TEST_DOC_ID = "test_doc_001"
TEST_DOC_DATA = {
    "doc_id": TEST_DOC_ID,
    "title": "测试文档-Milvus与JSON集成",
    "content": "这是一个用于端到端测试的文档全文。包含两个不同的文本分块。",
    "space": "测试空间",
    "address": "./data/documents/测试空间",
    "last_updated": "2026-06-08T12:00:00",
    "chunks": [
        {"index": 0, "text": "这是一个用于端到端测试的文档全文。"},
        {"index": 1, "text": "包含两个不同的文本分块。"}
    ]
}

# 动态探测本地 Milvus 是否可用
MILVUS_AVAILABLE = False
try:
    # 尝试连接，超时设为 2 秒
    connections.connect("test_detect", host="localhost", port="19530", timeout=2.0)
    connections.disconnect("test_detect")
    MILVUS_AVAILABLE = True
except Exception:
    MILVUS_AVAILABLE = False


def test_document_store():
    """
    测试本地 JSON 文档存储的读、写和删除功能。
    """
    # 1. 写入文档
    save_document(TEST_DOC_ID, TEST_DOC_DATA)
    
    # 2. 读取并验证
    loaded_data = load_document(TEST_DOC_ID)
    assert loaded_data is not None
    assert loaded_data["doc_id"] == TEST_DOC_ID
    assert loaded_data["title"] == TEST_DOC_DATA["title"]
    assert len(loaded_data["chunks"]) == 2
    assert loaded_data["chunks"][0]["text"] == TEST_DOC_DATA["chunks"][0]["text"]
    
    # 3. 删除验证
    delete_document(TEST_DOC_ID)
    assert load_document(TEST_DOC_ID) is None


@pytest.mark.skipif(not MILVUS_AVAILABLE, reason="本地 Milvus 服务未运行，跳过向量存储测试")
def test_milvus_store():
    """
    测试 Milvus 向量存储的创建 Collection、插入、向量检索与过滤功能。
    """
    store = MilvusStore()
    collection_name = "test_doc_chunks"
    dim = 1536
    
    # 清理历史可能残留的 Collection
    store.delete_collection(collection_name)
    
    try:
        # 1. 初始化 Collection
        collection = store.init_collection(collection_name, dim=dim)
        assert collection is not None
        
        # 2. 插入测试向量与文本
        random.seed(42)
        # 生成 2 个 1536 维的随机向量（对应 2 个 chunk）
        embeddings = [[random.uniform(-1, 1) for _ in range(dim)] for _ in range(2)]
        chunk_texts = [TEST_DOC_DATA["chunks"][0]["text"], TEST_DOC_DATA["chunks"][1]["text"]]
        doc_ids = [TEST_DOC_ID, TEST_DOC_ID]
        chunk_indices = [0, 1]
        
        mr = store.insert_chunks(
            embeddings=embeddings,
            chunk_texts=chunk_texts,
            doc_ids=doc_ids,
            chunk_indices=chunk_indices,
            collection_name=collection_name
        )
        assert mr is not None
        assert mr.insert_count == 2
        
        # 3. 向量相似度检索
        query_vector = embeddings[0]
        results = store.search_similar(query_vector, top_k=2, collection_name=collection_name)
        
        assert len(results) > 0
        # 相似度最高的应该是第一条（对应的就是该 chunk 自己）
        assert results[0].entity.get("doc_id") == TEST_DOC_ID
        assert results[0].entity.get("chunk_index") == 0
        assert results[0].entity.get("chunk_text") == chunk_texts[0]
        
        # 4. 按 doc_id 过滤的检索
        results_filtered = store.search_similar(
            query_vector=query_vector,
            top_k=2,
            doc_ids_filter=[TEST_DOC_ID],
            collection_name=collection_name
        )
        assert len(results_filtered) > 0
        assert results_filtered[0].entity.get("doc_id") == TEST_DOC_ID
        
        # 5. 过滤不存在的 doc_id，期望返回空
        results_empty = store.search_similar(
            query_vector=query_vector,
            top_k=2,
            doc_ids_filter=["non_existent_doc_id"],
            collection_name=collection_name
        )
        assert len(results_empty) == 0
        
    finally:
        # 清理 Collection
        store.delete_collection(collection_name)


@pytest.mark.skipif(not MILVUS_AVAILABLE, reason="本地 Milvus 服务未运行，跳过端到端存储集成测试")
def test_storage_integration():
    """
    测试端到端持久化流程：
    写入文档到 JSON 文件 -> 插入向量与分块到 Milvus -> 从 Milvus 检索拿到 doc_id -> 从 JSON 文件读取完整文档
    """
    store = MilvusStore()
    collection_name = "test_integration_chunks"
    dim = 1536
    
    store.delete_collection(collection_name)
    
    try:
        # 1. 写入本地文档 JSON 文件
        save_document(TEST_DOC_ID, TEST_DOC_DATA)
        
        # 2. 插入向量至 Milvus
        random.seed(100)
        embeddings = [[random.uniform(-1, 1) for _ in range(dim)] for _ in range(2)]
        chunk_texts = [TEST_DOC_DATA["chunks"][0]["text"], TEST_DOC_DATA["chunks"][1]["text"]]
        doc_ids = [TEST_DOC_ID, TEST_DOC_ID]
        chunk_indices = [0, 1]
        
        store.insert_chunks(
            embeddings=embeddings,
            chunk_texts=chunk_texts,
            doc_ids=doc_ids,
            chunk_indices=chunk_indices,
            collection_name=collection_name
        )
        
        # 3. 模拟检索：利用第二个分块的向量去 Milvus 检索
        query_vector = embeddings[1]
        results = store.search_similar(query_vector, top_k=1, collection_name=collection_name)
        assert len(results) == 1
        
        retrieved_doc_id = results[0].entity.get("doc_id")
        assert retrieved_doc_id == TEST_DOC_ID
        
        # 4. 根据检索到的 doc_id 从本地 JSON 文件加载完整文档
        loaded_doc = load_document(retrieved_doc_id)
        assert loaded_doc is not None
        assert loaded_doc["title"] == TEST_DOC_DATA["title"]
        assert loaded_doc["chunks"][1]["text"] == results[0].entity.get("chunk_text")
        
    finally:
        # 清除测试数据
        delete_document(TEST_DOC_ID)
        store.delete_collection(collection_name)
