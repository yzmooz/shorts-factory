from shorts_factory.queue import QueueStore


def test_topic_fingerprint_is_normalized(tmp_path):
    queue = QueueStore(tmp_path / "queue.db")
    queue.add("Почему  НЕБО синее", tmp_path / "one")
    assert queue.exists("  почему небо   СИНЕЕ ")


def test_new_queue_has_no_rows(tmp_path):
    queue = QueueStore(tmp_path / "queue.db")
    assert queue.rows() == []
