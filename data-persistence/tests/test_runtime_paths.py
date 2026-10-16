from data_persistence._paths import chat_history_db_path, documents_dir, topics_dir


def test_topic_artifacts_can_share_web_directory_when_data_index_changes(monkeypatch, tmp_path):
    documents_data = tmp_path / 'current-data'
    web_topics = tmp_path / 'web-topics'
    monkeypatch.setenv('AI_QA_DATA_DIR', str(documents_data))
    monkeypatch.setenv('TOPICS_DATA_DIR', str(web_topics))
    assert topics_dir() == web_topics.resolve()


def test_projection_switch_does_not_move_chat_database(monkeypatch, tmp_path):
    data = tmp_path / 'existing-data'
    projections = tmp_path / 'verified-index' / 'documents'
    monkeypatch.setenv('AI_QA_DATA_DIR', str(data))
    monkeypatch.setenv('RESEARCH_DOCUMENTS_DIR', str(projections))
    assert documents_dir() == projections.resolve()
    assert chat_history_db_path() == data.resolve() / 'chat_history.db'


def test_projection_directory_falls_back_to_shared_data(monkeypatch, tmp_path):
    monkeypatch.setenv('AI_QA_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('RESEARCH_DOCUMENTS_DIR', raising=False)
    assert documents_dir() == tmp_path.resolve() / 'documents'
