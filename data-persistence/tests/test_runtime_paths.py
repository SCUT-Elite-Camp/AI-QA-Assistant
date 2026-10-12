from data_persistence._paths import topics_dir


def test_topic_artifacts_can_share_web_directory_when_data_index_changes(monkeypatch, tmp_path):
    documents_data = tmp_path / 'current-data'
    web_topics = tmp_path / 'web-topics'
    monkeypatch.setenv('AI_QA_DATA_DIR', str(documents_data))
    monkeypatch.setenv('TOPICS_DATA_DIR', str(web_topics))
    assert topics_dir() == web_topics.resolve()
