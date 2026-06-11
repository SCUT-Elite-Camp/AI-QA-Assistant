from pymilvus import connections, utility, Collection, CollectionSchema, FieldSchema, DataType

class MilvusStore:
    
    def __init__(self, host: str = "localhost", port: str = "19530"):
       
        self.host = host
        self.port = port
        self.connect()

    def connect(self) -> None:
        
        connections.connect("default", host=self.host, port=self.port)

    def init_collection(self, collection_name: str = "doc_chunks", dim: int = 1536) -> Collection:
       
        if utility.has_collection(collection_name):
            self.collection = Collection(collection_name)
        else:
            # 字段定义：id(自增), embedding(向量), chunk_id(全局分块ID), chunk_text(原始文本), doc_id(文档ID), chunk_index(分块序号), source_url(链接)
            fields = [
                FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
                FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=256),
                FieldSchema(name="chunk_text", dtype=DataType.VARCHAR, max_length=65535),
                FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="chunk_index", dtype=DataType.INT32),
                FieldSchema(name="source_url", dtype=DataType.VARCHAR, max_length=512)
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

    def insert_chunks(self, embeddings: list, chunk_ids: list, chunk_texts: list, doc_ids: list, chunk_indices: list, source_urls: list = None, collection_name: str = "doc_chunks"):
     
        if not embeddings:
            return None

        # 动态检测向量维度
        dim = len(embeddings[0])
        self.init_collection(collection_name, dim=dim)
            
        if source_urls is None:
            source_urls = [""] * len(embeddings)

        data = [
            embeddings,      # float 向量列表
            chunk_ids,       # 全局分块ID 列表
            chunk_texts,     # 文本列表
            doc_ids,         # 文档 ID 列表
            chunk_indices,   # 分块序号列表
            source_urls      # 源链接列表
        ]
        
        insert_result = self.collection.insert(data)
        self.collection.flush()
        return insert_result

    def search_similar(self, query_vector: list, top_k: int = 5, doc_ids_filter: list = None, collection_name: str = "doc_chunks"):
  
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
            output_fields=["chunk_id", "chunk_text", "doc_id", "chunk_index", "source_url"]
        )
        return results[0] if results else []

    def delete_collection(self, collection_name: str = "doc_chunks") -> None:
 
        if utility.has_collection(collection_name):
            utility.drop_collection(collection_name)
            if hasattr(self, 'collection') and self.collection.name == collection_name:
                delattr(self, 'collection')
