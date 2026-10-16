"""BM25 must use consistent lexical rules or report an actionable failure."""
import builtins
import importlib.util
import json
import pickle

import pytest

from retrieval import english_analyzer
from retrieval.bm25_index import BM25Index
from retrieval.english_analyzer import EnglishAnalyzer


@pytest.mark.parametrize("module,package", [("nltk", "nltk"), ("sklearn", "scikit-learn")])
def test_missing_dependency_is_lazy_and_never_creates_a_fallback_analyzer(monkeypatch, module, package):
    original_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == module or name.startswith(module + "."):
            raise ModuleNotFoundError(f"blocked test dependency: {name}", name=name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    spec = importlib.util.spec_from_file_location("isolated_english_analyzer", english_analyzer.__file__)
    isolated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(isolated)
    for create in (isolated.EnglishAnalyzer, BM25Index):
        with pytest.raises(RuntimeError, match=package) as error:
            create()
        assert "python -m pip install -r requirements.txt" in str(error.value)
        assert isinstance(error.value.__cause__, ImportError)


def test_english_rules_preserve_stemming_stop_words_and_numeric_values():
    assert EnglishAnalyzer().analyze("The configured policies cost 1,000.50 and 3.5.") == [
        "configur", "polici", "cost", "1000.50", "3.5",
    ]


@pytest.mark.parametrize("analyzer_id", ["english_regex_snowball_sklearn_stopwords_v1", None])
def test_legacy_index_is_rejected_without_rewriting_it(tmp_path, analyzer_id):
    path = tmp_path / "old-index.pkl"
    payload = {"tokenized_corpus": [["untrusted-fallback"]], "chunk_meta": []}
    if analyzer_id is not None:
        payload["analyzer_id"] = analyzer_id
    path.write_bytes(pickle.dumps(payload))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="rebuild the BM25 index"):
        BM25Index.load_from_file(str(path))
    assert path.read_bytes() == before


def test_current_index_roundtrip_uses_identical_query_and_document_rules(tmp_path):
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "policy.json").write_text(json.dumps({"chunks": [
        {"index": 0, "chunk_id": "configured", "text": "Configured policies cost 1,000."},
        {"index": 1, "chunk_id": "budget", "text": "Budget estimates and expenses."},
        {"index": 2, "chunk_id": "meeting", "text": "Meeting minutes and delivery."},
    ]}), encoding="utf-8")
    index = BM25Index()
    index.build_from_documents(str(documents))
    path = tmp_path / "current-index.pkl"
    index.save(str(path))
    restored = BM25Index.load_from_file(str(path))
    assert restored.search("configuring", top_k=1)[0]["chunk_id"] == "configured"
    assert restored.search("configuring") == index.search("configuring")
