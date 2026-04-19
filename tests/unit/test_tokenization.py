import pytest

from stc_framework.errors import TokenizationError
from stc_framework.sentinel.token_store import InMemoryTokenStore
from stc_framework.sentinel.tokenization import Tokenizer


def test_tokenize_is_deterministic():
    store = InMemoryTokenStore()
    t = Tokenizer(store)
    a = t.tokenize("alice@example.com")
    b = t.tokenize("alice@example.com")
    assert a == b
    assert a.startswith("STC_TOK_")


def test_detokenize_roundtrips():
    store = InMemoryTokenStore()
    t = Tokenizer(store)
    token = t.tokenize("secret")
    assert t.detokenize(token) == "secret"


def test_detokenize_unknown_raises():
    t = Tokenizer(InMemoryTokenStore())
    with pytest.raises(TokenizationError):
        t.detokenize("STC_TOK_000000000000")


def test_detokenize_text_replaces_known_tokens():
    store = InMemoryTokenStore()
    t = Tokenizer(store)
    token = t.tokenize("Alice")
    text = f"Hello {token}, welcome."
    assert t.detokenize_text(text) == "Hello Alice, welcome."
