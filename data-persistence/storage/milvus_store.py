import os

from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

from storage.filtering import (
    build_milvus_filter_expression,
    normalize_filters,
    validate_embedding_dimension,
)

class MilvusStore:
    
    def __init__(
        self,
        host: str = "localhost",
        port: str = "19530",
        collection_name: str | None = None,
    ):
        self.host = host
        self.port = port
        self.collection_name = collection_name or os.getenv(
            "MILVUS_COLLECTION",
            "doc_chunks",
        )
        self._connected = False

    def connect(self) -> None:
        if not self._connected:
            connections.connect("default", host=self.host, port=self.port, timeout=0.5)
            self._connected = True

    def init_collection(
        self,
        collection_name: str | None = None,
        dim: int = 1024,
    ) -> Collection:
        self.connect()
        collection_name = collection_name or self.collection_name
       
        if utility.has_collection(collection_name):
            self.collection = Collection(collection_name)
            self._validate_embedding_dimension(self.collection, dim)
        else:
            # Fields: generated id, embedding, chunk metadata, and source URL.
            fields = [
                FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
                FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=256),
                FieldSchema(name="chunk_text", dtype=DataType.VARCHAR, max_length=65535),
                FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="chunk_index", dtype=DataType.INT32),
                FieldSchema(name="source_url", dtype=DataType.VARCHAR, max_length=512),
                FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=512),
                FieldSchema(name="space", dtype=DataType.VARCHAR, max_length=256),
                FieldSchema(name="doc_type", dtype=DataType.VARCHAR, max_length=64),
            ]
            schema = CollectionSchema(fields, description="RAGent document chunks vector store")
            self.collection = Collection(collection_name, schema)
            
            # 创建向量索引，默认使用 HNSW 算法和内积度量(IP)
            index_params = {
                "metric_type": "IP",
                "index_type": "HNSW",
                "params": {"M": 16, "efConstruction": 200}
            }
            self.collection.create_index("embedding", index_params)
        
        # 将 collection 加载至内存，保证可供检索
        self.collection.load()
        return self.collection

    def insert_chunks(
        self,
        embeddings: list,
        chunk_ids: list,
        chunk_texts: list,
        doc_ids: list,
        chunk_indices: list,
        source_urls: list = None,
        titles: list | None = None,
        spaces: list | None = None,
        doc_types: list | None = None,
        collection_name: str | None = None,
    ):
        self.connect()
        if not embeddings:
            return None

        # 动态检测向量维度
        dim = len(embeddings[0])
        self.init_collection(collection_name, dim=dim)
            
        if source_urls is None:
            source_urls = [""] * len(embeddings)
        if titles is None:
            titles = [""] * len(embeddings)
        if spaces is None:
            spaces = [""] * len(embeddings)
        if doc_types is None:
            doc_types = [""] * len(embeddings)

        expected = len(embeddings)
        columns = (
            chunk_ids,
            chunk_texts,
            doc_ids,
            chunk_indices,
            source_urls,
            titles,
            spaces,
            doc_types,
        )
        if any(len(column) != expected for column in columns):
            raise ValueError("all Milvus insert columns must have equal lengths")

        data = [
            embeddings,      # float 向量列表
            chunk_ids,       # 全局分块ID 列表
            chunk_texts,     # 文本列表
            doc_ids,         # 文档 ID 列表
            chunk_indices,   # 分块序号列表
            [str(value or "")[:512] for value in source_urls],
            [str(value or "")[:512] for value in titles],
            [str(value or "")[:256] for value in spaces],
            [
                str(value or "").removeprefix(".").lower()[:64]
                for value in doc_types
            ],
        ]
        
        insert_result = self.collection.insert(data)
        self.collection.flush()
        return insert_result

    def search_similar(
        self,
        query_vector: list,
        top_k: int = 5,
        doc_ids_filter: list = None,
        filters: dict | None = None,
        collection_name: str | None = None,
        timeout_seconds: float = 2.0,
    ):
        self.connect()
  
        dim = len(query_vector)
        self.init_collection(collection_name, dim=dim)
            
        combined_filters = dict(filters or {})
        if (
            doc_ids_filter
            and "doc_id" not in combined_filters
            and "doc_ids" not in combined_filters
        ):
            combined_filters["doc_ids"] = doc_ids_filter
        normalized_filters = normalize_filters(combined_filters)
        available_fields = self._field_names(self.collection)
        required_fields = set(normalized_filters) - {"doc_ids"}
        if normalized_filters.get("doc_ids"):
            required_fields.add("doc_id")
        missing_fields = required_fields - available_fields
        if missing_fields:
            raise ValueError(
                "Milvus collection does not support filters: "
                + ", ".join(sorted(missing_fields))
            )
        expr = build_milvus_filter_expression(normalized_filters)

        output_fields = [
            field
            for field in (
                "chunk_id",
                "chunk_text",
                "doc_id",
                "chunk_index",
                "source_url",
                "title",
                "space",
                "doc_type",
            )
            if field in available_fields
        ]
            
        results = self.collection.search(
            data=[query_vector],
            anns_field="embedding",
            param={"metric_type": "IP", "params": {"nprobe": 10}},
            limit=top_k,
            expr=expr,
            output_fields=output_fields,
            timeout=timeout_seconds,
        )
        return results[0] if results else []

    def delete_collection(self, collection_name: str | None = None) -> None:
        self.connect()
        collection_name = collection_name or self.collection_name
 
        if utility.has_collection(collection_name):
            utility.drop_collection(collection_name)
            if hasattr(self, 'collection') and self.collection.name == collection_name:
                delattr(self, 'collection')

    @staticmethod
    def _field_names(collection: Collection) -> set[str]:
        return {field.name for field in collection.schema.fields}

    @staticmethod
    def _validate_embedding_dimension(collection: Collection, expected: int) -> None:
        embedding_field = next(
            (field for field in collection.schema.fields if field.name == "embedding"),
            None,
        )
        if embedding_field is None:
            raise ValueError("Milvus collection is missing the embedding field")
        actual = int(embedding_field.params.get("dim", 0))
        if actual:
            validate_embedding_dimension(actual, expected)
