from stc_framework.sentinel.classifier import DataClassifier


def test_classifier_returns_public_for_innocuous_text(minimal_spec):
    classifier = DataClassifier(minimal_spec, presidio_enabled=False)
    assert classifier.classify("What was revenue?") == "public"


def test_classifier_uses_custom_pattern(financial_spec):
    classifier = DataClassifier(financial_spec, presidio_enabled=False)
    # 'client portfolio' keyword hits a restricted pattern in the example spec
    assert classifier.classify("Show me the client holdings") == "restricted"


def test_classifier_handles_regex_patterns(financial_spec):
    classifier = DataClassifier(financial_spec, presidio_enabled=False)
    # account number regex: "\b\d{3}-\d{7}\b"
    assert classifier.classify("account 123-4567890") == "restricted"
