from hypothesis import HealthCheck, given, settings, strategies as st

from stc_framework.sentinel.classifier import DataClassifier


_TIER_ORDER = {"public": 0, "internal": 1, "restricted": 2}


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=25)
@given(prefix=st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=40))
def test_appending_restricted_pattern_never_downgrades(prefix: str, financial_spec):
    classifier = DataClassifier(financial_spec, presidio_enabled=False)
    baseline = classifier.classify(prefix or "no pii here")
    augmented = classifier.classify((prefix or "") + " account 123-4567890")
    assert _TIER_ORDER[augmented] >= _TIER_ORDER[baseline]
