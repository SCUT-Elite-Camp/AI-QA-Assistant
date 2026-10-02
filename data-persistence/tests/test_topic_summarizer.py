import pytest

from data_persistence.topics import TopicArtifactRepository


@pytest.fixture
def topics_root(tmp_path):
    root = tmp_path / "topics"
    root.mkdir()
    return root, TopicArtifactRepository(root)


@pytest.mark.parametrize("topic_id", [
    "550e8400-e29b-41d4-a716-446655440000",
    "topic-1",
    "topic_中文 2",
])
def test_repository_persists_safe_single_component_topic_ids(topics_root, topic_id):
    root, repository = topics_root
    repository.save_summary(
        topic_id,
        title="测试话题",
        description="话题摘要",
        soul_content="# 测试话题",
        tags=["测试"],
        existing_info={},
    )

    topic_dir = root / topic_id
    assert (topic_dir / "soul.md").is_file()
    assert (topic_dir / "topic_info.json").is_file()
    assert (topic_dir / "documents").is_dir()


@pytest.mark.parametrize("topic_id", [
    "", "../escape", r"..\escape", "/absolute", r"C:\escape",
    ".", "..", "embedded\x00nul", None,
])
def test_repository_rejects_unsafe_topic_ids_before_writing(topics_root, topic_id):
    root, repository = topics_root
    with pytest.raises(ValueError):
        repository.save_summary(
            topic_id,
            title="测试话题",
            description="话题摘要",
            soul_content="# 测试话题",
            tags=["测试"],
            existing_info={},
        )

    assert list(root.iterdir()) == []
    assert not (root.parent / "escape").exists()


def test_repository_rejects_symlink_topic_directory(topics_root, tmp_path):
    root, repository = topics_root
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "topic-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(ValueError, match="symbolic link"):
        repository.save_summary(
            "topic-link",
            title="测试话题",
            description="话题摘要",
            soul_content="# 测试话题",
            tags=["测试"],
            existing_info={},
        )

    assert list(outside.iterdir()) == []
