from datetime import datetime, timedelta, timezone

from stc_framework.sentinel.auth import VirtualKeyManager


def test_issue_and_authorize():
    m = VirtualKeyManager(rotation_days=1)
    key = m.issue("stalwart", scopes=["llm:call"])
    assert m.authorize(key.key_id, "llm:call")
    assert not m.authorize(key.key_id, "routing:write")


def test_rotate_issues_new_key():
    m = VirtualKeyManager(rotation_days=1)
    k1 = m.issue("stalwart", scopes=["llm:call"])
    k2 = m.rotate("stalwart")
    assert k2 is not None
    assert k1.key_id != k2.key_id


def test_env_placeholder_expansion(monkeypatch):
    m = VirtualKeyManager()
    monkeypatch.setenv("THEKEY", "super-secret")
    expanded = m.resolve_env_placeholder("sk-stalwart-${THEKEY}")
    assert expanded == "sk-stalwart-super-secret"


def test_expired_key_denied():
    m = VirtualKeyManager(rotation_days=0)
    key = m.issue("stalwart", scopes=["*"])
    key.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert not m.authorize(key.key_id, "anything")
