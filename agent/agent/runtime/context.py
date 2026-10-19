"""Project guarded source records into bounded, nonduplicated model views."""
import json
from dataclasses import dataclass, field
from agent.config.settings import settings


def evidence_key(item: dict) -> tuple:
    return tuple(item.get(key) for key in
                 ("source_type", "source_scope", "doc_id", "chunk_id", "version_id", "source_version", "content_hash", "evidence_ref"))


@dataclass
class EvidencePool:
    evidence: list[dict] = field(default_factory=list)
    catalog: dict[str, dict] = field(default_factory=dict)
    documents: dict[str, dict] = field(default_factory=dict)
    actions: list[dict] = field(default_factory=list)

    def add(self, name: str, arguments: dict, result) -> None:
        self.actions.append({"tool": name, "arguments": arguments, "success": result.success,
                             "error": result.error_message if not result.success else ""})
        if not result.success:
            return
        existing = {evidence_key(item): i for i, item in enumerate(self.evidence)}
        for value in result.evidence:
            if value.score < settings.MIN_RETRIEVAL_SCORE:
                continue
            item = value.model_dump()
            key = evidence_key(item)
            if key not in existing:
                existing[key] = len(self.evidence)
                self.evidence.append(item)
        data = result.data or {}
        if name == "find_documents":
            for item in data.get("documents", []):
                if item.get("doc_id"):
                    self.catalog[item["doc_id"]] = {key: item.get(key) for key in
                        ("doc_id", "title", "match_summary", "source_version")}
            if data.get("next_offset") is not None:
                self.actions[-1]["next_offset"] = data["next_offset"]
        if name == "get_document":
            for item in data.get("documents", []):
                if item.get("doc_id"):
                    self.documents[item["doc_id"]] = item

    def view(self, max_chars: int) -> tuple[str, list[dict]]:
        """Include whole documents once or whole excerpts; never truncate text.

        The complete pool/lineage stays server-side. A full read projection
        includes source locators into the one body instead of duplicating chunks.
        Noncontiguous chunks that cannot be mapped exactly remain separate views.
        """
        selected, represented = [], set()
        payload = {"documents": [], "excerpts": [], "catalog": [], "actions": [], "omitted_count": 0}

        def append(kind, entry):
            payload[kind].append(entry)
            # Reserve room for growth of the omission counter itself.
            if len(json.dumps(payload, ensure_ascii=False)) <= max_chars - 16:
                return True
            payload[kind].pop()
            payload["omitted_count"] += 1
            return False

        # Bound navigation metadata too. Never truncate source prose to fit.
        for action in self.actions[-8:]:
            append("actions", action)
        for doc_id, document in self.documents.items():
            body = document.get("content", "")
            if not isinstance(body, str) or not body:
                continue
            refs, accepted = [], []
            for item in self.evidence:
                if item["doc_id"] != doc_id:
                    continue
                start = body.find(item["content"])
                reference = {"citation_id": len(selected)+len(accepted)+1, "chunk_id": item["chunk_id"]}
                if start >= 0:
                    reference.update(start=start, end=start+len(item["content"]))
                else:
                    # Parsers can join noncontiguous sections. Keep their exact
                    # citation scope rather than inventing offsets into the body.
                    reference["quote_scope"] = item["content"]
                refs.append(reference)
                accepted.append(item)
            entry = {"doc_id": doc_id, "title": document.get("title", ""),
                     "content": body, "references": refs}
            if not append("documents", entry):
                continue
            selected.extend(accepted)
            represented.update(evidence_key(item) for item in accepted)
        for item in self.evidence:
            if evidence_key(item) in represented:
                continue
            entry = {"citation_id": len(selected)+1, "doc_id": item["doc_id"],
                     "chunk_id": item["chunk_id"], "title": item.get("title", ""),
                     "source_type": item["source_type"],
                     "content": item["content"]}
            if not append("excerpts", entry):
                continue
            selected.append(item)
        for item in self.catalog.values():
            append("catalog", item)
        return json.dumps(payload, ensure_ascii=False), selected
