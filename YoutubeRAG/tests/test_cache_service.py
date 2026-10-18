from __future__ import annotations

from dataclasses import replace

from backend import cache_service


def test_sqlite_chat_history_is_keyed_and_limited(monkeypatch, tmp_path):
    settings = replace(
        cache_service.get_settings(),
        chat_history_db_path=tmp_path / "history.sqlite3",
        max_history_messages=2,
    )
    monkeypatch.setattr(cache_service, "get_settings", lambda: settings)

    cache_service.append_chat_message("session-1", "user", "old", "J5_-l7WIO_w")
    cache_service.append_chat_message("session-1", "user", "latest-1", "J5_-l7WIO_w")
    cache_service.append_chat_message("session-1", "assistant", "latest-2", "J5_-l7WIO_w")
    cache_service.append_chat_message("session-1", "user", "other video", "D5KhiCDM9XQ")

    history = cache_service.get_chat_history("session-1", "J5_-l7WIO_w")
    assert [message.content for message in history] == ["latest-1", "latest-2"]
    assert [message.content for message in cache_service.get_chat_history("session-1", "D5KhiCDM9XQ")] == [
        "other video"
    ]

    cache_service.clear_chat_history("session-1", "J5_-l7WIO_w")
    assert cache_service.get_chat_history("session-1", "J5_-l7WIO_w") == []
    assert len(cache_service.get_chat_history("session-1", "D5KhiCDM9XQ")) == 1
