import pytest

from stc_framework.errors import DataSovereigntyViolation
from stc_framework.sentinel.redaction import PIIRedactor


def test_redactor_masks_fallback_email(minimal_spec):
    redactor = PIIRedactor(minimal_spec, presidio_enabled=False)
    result = redactor.redact("reach me at alice@example.com please")
    assert "alice@example.com" not in result.text
    assert "EMAIL_ADDRESS" in result.entity_counts


def test_redactor_blocks_credit_card(minimal_spec):
    redactor = PIIRedactor(minimal_spec, presidio_enabled=False)
    with pytest.raises(DataSovereigntyViolation):
        redactor.redact("card 4111 1111 1111 1111")


def test_redactor_no_op_when_text_clean(minimal_spec):
    redactor = PIIRedactor(minimal_spec, presidio_enabled=False)
    result = redactor.redact("what was Q4 revenue?")
    assert result.text == "what was Q4 revenue?"
    assert result.redactions == []
