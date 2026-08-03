from pymilvus import connections, utility, Collection, CollectionSchema, FieldSchema, DataType

class MilvusStore:
    
    def __init__(self, host: str = "localhost", port: str = "19530"):
        self.host = host
        self.port = port
        self._connected = False

    def connect(self) -> None:
        if not self._connected:
            connections.connect("default", host=self.host, port=self.port)
            self._connected = True

    def init_collection(self, collection_name: str = "doc_chunks", dim: int = 1024) -> Collection:
        self.connect()

        if utility.has_collection(collection_name):
            self.collection = Collection(collection_name)

            # ─── 兼容：已有集合缺少标量索引则补齐 ──────
            existing_indexes = {idx.field_name for idx in self.collection.indexes}
            if "doc_id" not in existing_indexes:
                try:
                    self.collection.create_index(
                        "doc_id",
                        {"index_type": "INVERTED"},
                    )
                except Exception:
                    pass
        else:
            # 字段定义：id(自增), embedding(向量), chunk_id, chunk_text,
            #           doc_id, chunk_index, source_url, space
            fields = [
                FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
                FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=256),
                FieldSchema(name="chunk_text", dtype=DataType.VARCHAR, max_length=65535),
                FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="chunk_index", dtype=DataType.INT32),
                FieldSchema(name="source_url", dtype=DataType.VARCHAR, max_length=512),
                FieldSchema(name="space", dtype=DataType.VARCHAR, max_length=256),
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

            # ─── 为过滤字段创建标量索引 ─────────────────
            # doc_id: 最常用的过滤字段
            # space:  按来源空间过滤
            for idx_field in ("doc_id", "space"):
                try:
                    self.collection.create_index(
                        idx_field,
                        {"index_type": "INVERTED"},
                    )
                except Exception:
                    pass  # 某些版本的 Milvus 可能不支持

        # 将 collection 加载至内存，保证可供检索
        self.collection.load()
        return self.collection

    def _has_space_field(self) -> bool:
        """检查当前 collection 是否包含 space 字段（兼容旧集合）"""
        try:
            if hasattr(self, "collection") and self.collection is not None:
                schema = self.collection.schema
                field_names = {f.name for f in schema.fields}
                return "space" in field_names
        except Exception:
            pass
        return False

    def insert_chunks(
        self,
        embeddings: list,
        chunk_ids: list,
        chunk_texts: list,
        doc_ids: list,
        chunk_indices: list,
        source_urls: list = None,
        spaces: list = None,
        collection_name: str = "doc_chunks",
    ):
        self.connect()
        if not embeddings:
            return None

        # 动态检测向量维度
        dim = len(embeddings[0])
        self.init_collection(collection_name, dim=dim)

        if source_urls is None:
            source_urls = [""] * len(embeddings)
        if spaces is None:
            spaces = [""] * len(embeddings)

        # ─── 兼容旧集合：无 space 字段时跳过该列 ────
        if self._has_space_field():
            data = [
                embeddings,
                chunk_ids,
                chunk_texts,
                doc_ids,
                chunk_indices,
                source_urls,
                spaces,
            ]
        else:
            data = [
                embeddings,
                chunk_ids,
                chunk_texts,
                doc_ids,
                chunk_indices,
                source_urls,
            ]

        insert_result = self.collection.insert(data)
        self.collection.flush()
        return insert_result

    def search_similar(self, query_vector: list, top_k: int = 5, doc_ids_filter: list = None, collection_name: str = "doc_chunks"):
        self.connect()
  
        dim = len(query_vector)
        self.init_collection(collection_name, dim=dim)
            
        expr = None
        if doc_ids_filter:
            ids_str = ", ".join([f"'{did}'" for did in doc_ids_filter])
            expr = f"doc_id in [{ids_str}]"
            
        results = self.collection.search(
            data=[query_vector],
            anns_field="embedding",
            param={"metric_type": "IP", "params": {"nprobe": 10}},
            limit=top_k,
            expr=expr,
            output_fields=(
                ["chunk_id", "chunk_text", "doc_id", "chunk_index", "source_url", "space"]
                if self._has_space_field()
                else ["chunk_id", "chunk_text", "doc_id", "chunk_index", "source_url"]
            )
        )
        return results[0] if results else []

    def delete_collection(self, collection_name: str = "doc_chunks") -> None:
        self.connect()
 
        if utility.has_collection(collection_name):
            utility.drop_collection(collection_name)
            if hasattr(self, 'collection') and self.collection.name == collection_name:
                delattr(self, 'collection')
