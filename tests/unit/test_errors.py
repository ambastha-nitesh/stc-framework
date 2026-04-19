from stc_framework.errors import (
    BulkheadFull,
    CircuitBreakerOpen,
    DataSovereigntyViolation,
    GuardrailBlocked,
    LLMRateLimited,
    LLMTimeout,
    STCError,
    VectorStoreUnavailable,
    http_status_for,
)


def test_base_stc_error_str_includes_downstream():
    err = STCError(message="boom", downstream="litellm", trace_id="abc")
    rendered = str(err)
    assert "boom" in rendered
    assert "downstream=litellm" in rendered
    assert "trace=abc" in rendered


def test_llm_rate_limited_is_retryable_by_default():
    err = LLMRateLimited(message="slow down")
    assert err.retryable is True


def test_guardrail_blocked_not_retryable():
    err = GuardrailBlocked(message="blocked")
    assert err.retryable is False


def test_http_status_mapping_uses_mro():
    assert http_status_for(LLMTimeout(message="t")) == 504
    assert http_status_for(LLMRateLimited(message="r")) == 429
    assert http_status_for(CircuitBreakerOpen(message="c")) == 503
    assert http_status_for(VectorStoreUnavailable(message="v")) == 503
    assert http_status_for(DataSovereigntyViolation(message="d")) == 403
    assert http_status_for(BulkheadFull(message="b")) == 503


def test_http_status_falls_back_to_500():
    class Unknown(STCError):
        pass

    assert http_status_for(Unknown(message="x")) == 500
