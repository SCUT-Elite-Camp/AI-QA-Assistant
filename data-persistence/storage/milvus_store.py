import json

from pymilvus import connections, utility, Collection, CollectionSchema, FieldSchema, DataType

class MilvusStore:
    PROVENANCE_FIELDS = (
        "chunk_type",
        "block_id",
        "table_id",
        "page_number",
        "bbox_json",
        "metadata_json",
    )
    REQUIRED_FIELD_DEFINITIONS = {
        "embedding": (DataType.FLOAT_VECTOR, None),
        "chunk_id": (DataType.VARCHAR, 256),
        "chunk_text": (DataType.VARCHAR, 65535),
        "doc_id": (DataType.VARCHAR, 128),
        "chunk_index": (DataType.INT32, None),
        "source_url": (DataType.VARCHAR, 512),
        "chunk_type": (DataType.VARCHAR, 64),
        "block_id": (DataType.VARCHAR, 1024),
        "table_id": (DataType.VARCHAR, 1024),
        "page_number": (DataType.INT64, None),
        "bbox_json": (DataType.VARCHAR, 256),
        "metadata_json": (DataType.VARCHAR, 65535),
    }
    OPTIONAL_FIELD_DEFINITIONS = {"space": (DataType.VARCHAR, 256)}
    
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

            self.validate_chunk_schema(collection_name)

            vector_field = next(
                (field for field in self.collection.schema.fields if field.name == "embedding"),
                None,
            )
            existing_dim = (vector_field.params or {}).get("dim") if vector_field else None
            if existing_dim is not None and int(existing_dim) != int(dim):
                raise ValueError(
                    f"Collection '{collection_name}' uses {existing_dim} dimensions, "
                    f"but the current embedding model produced {dim}. "
                    "Use a separate collection or rebuild the index."
                )

            # ─── 兼容：已有集合缺少标量索引则补齐 ──────
            existing_indexes = {idx.field_name for idx in self.collection.indexes}
            if "doc_id" not in existing_indexes:
                try:
                    self.collection.create_index(
                        "doc_id",
                        {"index_type": "Trie"},
                    )
                except Exception:
                    pass
        else:
            # 字段定义：向量、兼容字段，以及 PDF 来源追踪字段。
            fields = [
                FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
                FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=256),
                FieldSchema(name="chunk_text", dtype=DataType.VARCHAR, max_length=65535),
                FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="chunk_index", dtype=DataType.INT32),
                FieldSchema(name="source_url", dtype=DataType.VARCHAR, max_length=512),
                FieldSchema(name="space", dtype=DataType.VARCHAR, max_length=256),
                FieldSchema(name="chunk_type", dtype=DataType.VARCHAR, max_length=64),
                FieldSchema(name="block_id", dtype=DataType.VARCHAR, max_length=1024),
                FieldSchema(name="table_id", dtype=DataType.VARCHAR, max_length=1024),
                FieldSchema(name="page_number", dtype=DataType.INT64),
                FieldSchema(name="bbox_json", dtype=DataType.VARCHAR, max_length=256),
                FieldSchema(name="metadata_json", dtype=DataType.VARCHAR, max_length=65535),
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
                        {"index_type": "Trie"},
                    )
                except Exception:
                    pass  # 某些版本的 Milvus 可能不支持

        # 将 collection 加载至内存，保证可供检索
        self.collection.load()
        return self.collection

    def validate_chunk_schema(self, collection_name: str = "doc_chunks") -> None:
        """Reject collections that cannot retain structured chunk provenance."""
        if not hasattr(self, "collection") or self.collection is None:
            raise ValueError("Initialize a Milvus collection before validating its schema.")
        fields = {field.name: field for field in self.collection.schema.fields}
        issues = []
        definitions = dict(self.REQUIRED_FIELD_DEFINITIONS)
        definitions.update({
            name: definition
            for name, definition in self.OPTIONAL_FIELD_DEFINITIONS.items()
            if name in fields
        })
        for name, (expected_dtype, minimum_length) in definitions.items():
            field = fields.get(name)
            if field is None:
                issues.append(f"{name} (missing)")
                continue
            if getattr(field, "dtype", None) != expected_dtype:
                issues.append(f"{name} (expected {expected_dtype.name})")
                continue
            if minimum_length is not None:
                params = getattr(field, "params", None) or {}
                try:
                    actual_length = int(params.get("max_length", 0))
                except (TypeError, ValueError):
                    actual_length = 0
                if actual_length < minimum_length:
                    issues.append(f"{name} (max_length must be at least {minimum_length})")
        if issues:
            raise ValueError(
                f"{collection_name} schema is missing PDF provenance fields or has "
                f"incompatible definitions: {', '.join(issues)}. "
                "Run scripts/safe_reindex.py for a dry run, then execute it with "
                "--execute --confirm REBUILD. Legacy destructive entry: scripts/reindex.py."
            )

    @staticmethod
    def _in_expr(field_name: str, values: list[str]) -> str:
        if not values:
            raise ValueError("values must not be empty")
        return f"{field_name} in [{', '.join(json.dumps(str(value)) for value in values)}]"

    def _existing_collection(self, collection_name: str) -> Collection | None:
        self.connect()
        if not utility.has_collection(collection_name):
            return None
        self.collection = Collection(collection_name)
        self.collection.load()
        return self.collection

    def get_existing_collection(self, collection_name: str) -> Collection | None:
        """Get an existing collection without inferring or creating a dimension."""
        return self._existing_collection(collection_name)

    def get_chunk_ids_by_doc_ids(
        self,
        doc_ids: list[str],
        collection_name: str = "doc_chunks",
        limit: int = 16384,
    ) -> list[str]:
        """Return stored chunk IDs for documents without creating a collection."""
        if not doc_ids:
            return []
        collection = self._existing_collection(collection_name)
        if collection is None:
            return []
        rows = collection.query(
            expr=self._in_expr("doc_id", doc_ids),
            output_fields=["chunk_id"],
            limit=limit,
        )
        return [row["chunk_id"] for row in rows if row.get("chunk_id")]

    def delete_by_doc_ids(
        self,
        doc_ids: list[str],
        collection_name: str = "doc_chunks",
    ) -> int:
        """Delete all vectors for logical documents before re-ingestion."""
        if not doc_ids:
            return 0
        collection = self._existing_collection(collection_name)
        if collection is None:
            return 0
        result = collection.delete(expr=self._in_expr("doc_id", doc_ids))
        collection.flush()
        return int(getattr(result, "delete_count", 0) or 0)

    def delete_by_chunk_ids(
        self,
        chunk_ids: list[str],
        collection_name: str = "doc_chunks",
    ) -> int:
        """Delete selected vectors by their stable application-level IDs."""
        if not chunk_ids:
            return 0
        collection = self._existing_collection(collection_name)
        if collection is None:
            return 0
        result = collection.delete(expr=self._in_expr("chunk_id", chunk_ids))
        collection.flush()
        return int(getattr(result, "delete_count", 0) or 0)

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
        chunk_types: list = None,
        block_ids: list = None,
        table_ids: list = None,
        page_numbers: list = None,
        bbox_jsons: list = None,
        metadata_jsons: list = None,
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

        row_count = len(embeddings)
        defaults = {
            "chunk_types": (chunk_types, ""),
            "block_ids": (block_ids, ""),
            "table_ids": (table_ids, ""),
            "page_numbers": (page_numbers, 0),
            "bbox_jsons": (bbox_jsons, ""),
            "metadata_jsons": (metadata_jsons, ""),
        }
        resolved = {
            name: (
                [default] * row_count
                if values is None
                else [default if value is None else value for value in values]
            )
            for name, (values, default) in defaults.items()
        }
        columns = {
            "chunk_ids": chunk_ids,
            "chunk_texts": chunk_texts,
            "doc_ids": doc_ids,
            "chunk_indices": chunk_indices,
            "source_urls": source_urls,
            "spaces": spaces,
            **resolved,
        }
        for name, values in columns.items():
            if len(values) != row_count:
                raise ValueError(
                    f"{name} length {len(values)} does not match embeddings length {row_count}"
                )

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
                resolved["chunk_types"],
                resolved["block_ids"],
                resolved["table_ids"],
                resolved["page_numbers"],
                resolved["bbox_jsons"],
                resolved["metadata_jsons"],
            ]
        else:
            data = [
                embeddings,
                chunk_ids,
                chunk_texts,
                doc_ids,
                chunk_indices,
                source_urls,
                resolved["chunk_types"],
                resolved["block_ids"],
                resolved["table_ids"],
                resolved["page_numbers"],
                resolved["bbox_jsons"],
                resolved["metadata_jsons"],
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
                ["chunk_id", "chunk_text", "doc_id", "chunk_index", "source_url"]
                + (["space"] if self._has_space_field() else [])
                + list(self.PROVENANCE_FIELDS)
            )
        )
        return results[0] if results else []

    def delete_collection(self, collection_name: str = "doc_chunks") -> None:
        self.connect()
 
        if utility.has_collection(collection_name):
            utility.drop_collection(collection_name)
            if hasattr(self, 'collection') and self.collection.name == collection_name:
                delattr(self, 'collection')
