import json
import os
import math

from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

from storage.filtering import (
    build_milvus_filter_expression,
    normalize_filters,
    validate_embedding_dimension,
)

class MilvusStore:
    @staticmethod
    def load_timeout_seconds() -> float:
        try:
            value = float(os.getenv('MILVUS_LOAD_TIMEOUT_SECONDS', '10'))
        except ValueError:
            return 10.0
        return value if math.isfinite(value) and value > 0 else 10.0

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


    def __init__(
        self,
        host: str | None = None,
        port: str | None = None,
        collection_name: str | None = None,
    ):
        self.host = host or os.getenv("MILVUS_HOST", "localhost")
        self.port = str(port or os.getenv("MILVUS_PORT", "19530"))
        self.collection_name = collection_name or os.getenv(
            "MILVUS_COLLECTION",
            "doc_chunks",
        )
        self._connected = False

    def connect(self) -> None:
        if not self._connected:
            try:
                timeout = float(os.getenv("MILVUS_CONNECT_TIMEOUT_SECONDS", "5"))
            except ValueError:
                timeout = 5.0
            if timeout <= 0:
                timeout = 5.0
            connections.connect("default", host=self.host, port=self.port, timeout=timeout)
            self._connected = True

    def delete_document_chunks(self, doc_id: str) -> None:
        """Remove one document without creating a missing collection."""
        self.delete_documents_chunks([doc_id])

    def delete_documents_chunks(self, doc_ids: list[str]) -> None:
        """Remove a batch of documents with one safely quoted Milvus filter."""
        if not isinstance(doc_ids, list):
            raise ValueError("doc_ids must be a list")
        if any(not isinstance(doc_id, str) or not doc_id or len(doc_id) > 128 for doc_id in doc_ids):
            raise ValueError("invalid Milvus document ID")
        normalized_ids = list(dict.fromkeys(doc_ids))
        if not normalized_ids:
            return

        self.connect()
        if not utility.has_collection(self.collection_name):
            return
        collection = Collection(self.collection_name)
        values = ", ".join(
            json.dumps(doc_id, ensure_ascii=False) for doc_id in normalized_ids
        )
        collection.delete(expr=f"doc_id in [{values}]")
        collection.flush()

    def init_collection(
        self,
        collection_name: str | None = None,
        dim: int = 384,
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
            for field_name in ("doc_id", "space", "doc_type"):
                try:
                    self.collection.create_index(field_name, {"index_type": "Trie"})
                except Exception:
                    # Filtering still applies without the optional scalar index.
                    pass

        # 将 collection 加载至内存，保证可供检索
        self.collection.load(timeout=self.load_timeout_seconds())
        return self.collection

    def validate_chunk_schema(self, collection_name: str | None = None) -> None:
        """Reject collections that cannot retain structured chunk provenance."""
        if not hasattr(self, "collection") or self.collection is None:
            raise ValueError("Initialize a Milvus collection before validating its schema.")
        collection_name = collection_name or self.collection_name
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
                "Plan a rebuild into separate collections with scripts/safe_reindex.py. "
                "See docs/DATA_PIPELINE.md; scripts/reindex.py requires explicit confirmation."
            )

    @staticmethod
    def _in_expr(field_name: str, values: list[str]) -> str:
        if not values:
            raise ValueError("values must not be empty")
        return f"{field_name} in [{', '.join(json.dumps(str(value)) for value in values)}]"

    def _existing_collection(self, collection_name: str) -> Collection | None:
        self.connect()
        collection_name = collection_name or self.collection_name
        if not utility.has_collection(collection_name):
            return None
        self.collection = Collection(collection_name)
        self.collection.load(timeout=self.load_timeout_seconds())
        return self.collection

    def get_existing_collection(self, collection_name: str) -> Collection | None:
        """Get an existing collection without inferring or creating a dimension."""
        return self._existing_collection(collection_name)

    def get_chunk_ids_by_doc_ids(
        self,
        doc_ids: list[str],
        collection_name: str | None = None,
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
        collection_name: str | None = None,
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
        collection_name: str | None = None,
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
        chunk_types: list | None = None,
        block_ids: list | None = None,
        table_ids: list | None = None,
        page_numbers: list | None = None,
        bbox_jsons: list | None = None,
        metadata_jsons: list | None = None,
    ):
        if not embeddings:
            return None

        # 动态检测向量维度
        dim = len(embeddings[0])
        collection = self.init_collection(collection_name, dim=dim)

        if source_urls is None:
            source_urls = [""] * len(embeddings)
        if titles is None:
            titles = [""] * len(embeddings)
        if spaces is None:
            spaces = [""] * len(embeddings)
        if doc_types is None:
            doc_types = [""] * len(embeddings)

        columns = {
            "embedding": embeddings,
            "chunk_id": chunk_ids,
            "chunk_text": chunk_texts,
            "doc_id": doc_ids,
            "chunk_index": chunk_indices,
            "source_url": [str(value or "")[:512] for value in source_urls],
            "title": [str(value or "")[:512] for value in titles],
            "space": [str(value or "")[:256] for value in spaces],
            "doc_type": [
                self._normalize_doc_type(value)[:64] for value in doc_types
            ],
        }
        provenance = {
            "chunk_type": (chunk_types, ""),
            "block_id": (block_ids, ""),
            "table_id": (table_ids, ""),
            "page_number": (page_numbers, 0),
            "bbox_json": (bbox_jsons, ""),
            "metadata_json": (metadata_jsons, ""),
        }
        if any(values is not None for values, _ in provenance.values()):
            self.validate_chunk_schema(collection_name)
        columns.update({
            name: [default] * len(embeddings) if values is None else [
                default if value is None else value for value in values
            ]
            for name, (values, default) in provenance.items()
        })
        expected = len(embeddings)
        if any(len(column) != expected for column in columns.values()):
            mismatched = next(name for name, values in columns.items() if len(values) != expected)
            raise ValueError(f"{mismatched} length {len(columns[mismatched])} does not match embeddings length {expected}")

        writable_fields = [
            field.name
            for field in collection.schema.fields
            if not (getattr(field, "is_primary", False) and getattr(field, "auto_id", False))
        ]
        unsupported = set(writable_fields) - set(columns)
        if unsupported:
            raise ValueError(
                "Milvus collection has unsupported required fields: "
                + ", ".join(sorted(unsupported))
            )
        data = [columns[name] for name in writable_fields]

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
        dim = len(query_vector)
        combined_filters = dict(filters or {})
        if doc_ids_filter is not None:
            alias = "doc_id" if "doc_ids" in combined_filters else "doc_ids"
            combined_filters[alias] = doc_ids_filter
        normalized_filters = normalize_filters(combined_filters)
        if normalized_filters.get("doc_ids") == []:
            return []
        collection = self.init_collection(collection_name, dim=dim)
        available_fields = self._field_names(collection)
        required_fields = set(normalized_filters) - {"doc_ids", "chunk_ids"}
        if "doc_ids" in normalized_filters:
            required_fields.add("doc_id")
        if normalized_filters.get("chunk_ids"):
            required_fields.add("chunk_id")
        missing_fields = required_fields - available_fields
        if missing_fields:
            raise ValueError(
                "Milvus collection does not support filters; rebuild it with fields: "
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
                *self.PROVENANCE_FIELDS,
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

    @staticmethod
    def _normalize_doc_type(value) -> str:
        candidate = str(value or "").strip().lower()
        if "/" in candidate:
            candidate = candidate.rsplit("/", 1)[-1]
        return candidate.removeprefix(".")
