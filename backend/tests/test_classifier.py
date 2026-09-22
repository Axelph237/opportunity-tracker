"""classifier.py: normalization and batch-classification fallback, no real claude calls."""

from __future__ import annotations

import json

import classifier


def test_normalize_result_fills_defaults_for_missing_fields():
    result = classifier.normalize_result({}, "https://example.com/jobs/1", source_name="Acme Careers")
    assert result["url"] == "https://example.com/jobs/1"
    assert result["title"] == "Untitled listing"
    assert result["organization"] == "Acme Careers"
    assert result["type"] == "other"
    assert result["experience_level"] == "any"
    assert result["strong_match"] is False


def test_normalize_result_clamps_score_and_sets_strong_match():
    result = classifier.normalize_result({"relevance_score": 15}, "https://example.com/jobs/1")
    assert result["relevance_score"] == 10.0
    assert result["strong_match"] is True  # >= STRONG_MATCH_THRESHOLD


def test_normalize_result_rejects_invalid_type_and_level():
    result = classifier.normalize_result(
        {"type": "not-a-type", "experience_level": "not-a-level"}, "https://example.com/jobs/1"
    )
    assert result["type"] == "other"
    assert result["experience_level"] == "any"


def test_normalize_result_deduplicates_skill_matches():
    result = classifier.normalize_result(
        {"skill_matches": ["Python", "python", "Python", "Qiskit"]}, "https://example.com/jobs/1"
    )
    # _clean_str/_clean_list preserve case but drop exact duplicates.
    assert result["skill_matches"].count("Python") == 1
    assert "Qiskit" in result["skill_matches"]


def test_clean_score_handles_garbage_input():
    assert classifier._clean_score("not a number") == 0.0
    assert classifier._clean_score(-5) == 0.0
    assert classifier._clean_score(1000) == 10.0


def test_clean_bool_variants():
    assert classifier._clean_bool(True) is True
    assert classifier._clean_bool("yes") is True
    assert classifier._clean_bool("remote") is True
    assert classifier._clean_bool("no") is False
    assert classifier._clean_bool(0) is False


def test_clean_str_treats_placeholder_words_as_none():
    assert classifier._clean_str("null") is None
    assert classifier._clean_str("N/A") is None
    assert classifier._clean_str("unknown") is None
    assert classifier._clean_str("Real value") == "Real value"


def test_classify_opportunity_empty_listing_never_calls_claude():
    result = classifier.classify_opportunity("   ", "https://example.com/jobs/1", "Acme", None)
    assert result["error"] == "empty listing text"
    assert result["relevance_score"] == 0.0


def test_classify_opportunity_uses_mocked_claude_response(monkeypatch):
    monkeypatch.setattr(
        classifier, "run_claude",
        lambda *a, **kw: json.dumps({
            "title": "Quantum Intern", "organization": "IonQ", "type": "internship",
            "relevance_score": 8.5, "experience_level": "student",
        }),
    )
    result = classifier.classify_opportunity("Some listing text", "https://example.com/jobs/1", "IonQ", "resume text")
    assert result["title"] == "Quantum Intern"
    assert result["strong_match"] is True


def test_classify_opportunity_claude_failure_returns_failed_result(monkeypatch):
    def _boom(*_a, **_kw):
        raise classifier.ClaudeCallError("simulated failure")

    monkeypatch.setattr(classifier, "run_claude", _boom)
    result = classifier.classify_opportunity("Some listing text", "https://example.com/jobs/1", "IonQ", None)
    assert result["error"] == "simulated failure"
    assert result["relevance_score"] == 0.0


def test_classify_batch_empty_returns_empty():
    assert classifier.classify_batch([], None) == []


def test_classify_batch_single_item_delegates_to_classify_opportunity(monkeypatch):
    monkeypatch.setattr(
        classifier, "run_claude",
        lambda *a, **kw: json.dumps({"title": "Solo Listing", "organization": "Acme", "type": "job"}),
    )
    results = classifier.classify_batch([{"url": "https://example.com/1", "text": "text"}], None)
    assert len(results) == 1
    assert results[0]["title"] == "Solo Listing"


def test_classify_batch_parses_indexed_array_response(monkeypatch):
    def _fake_run_claude(*_a, **_kw):
        return json.dumps([
            {"index": 1, "title": "Second Listing", "organization": "Acme", "type": "job"},
            {"index": 0, "title": "First Listing", "organization": "Acme", "type": "internship"},
        ])

    monkeypatch.setattr(classifier, "run_claude", _fake_run_claude)
    items = [
        {"url": "https://example.com/0", "text": "first"},
        {"url": "https://example.com/1", "text": "second"},
    ]
    results = classifier.classify_batch(items, None, source_name="Acme")
    assert results[0]["title"] == "First Listing"
    assert results[1]["title"] == "Second Listing"


def test_classify_batch_missing_index_becomes_failed_result(monkeypatch):
    monkeypatch.setattr(
        classifier, "run_claude",
        lambda *a, **kw: json.dumps([{"index": 0, "title": "Only First", "organization": "Acme", "type": "job"}]),
    )
    items = [
        {"url": "https://example.com/0", "text": "first"},
        {"url": "https://example.com/1", "text": "second"},
    ]
    results = classifier.classify_batch(items, None)
    assert results[0]["title"] == "Only First"
    assert results[1]["error"] == "missing from batch response"


def test_classify_batch_falls_back_to_per_item_on_claude_failure(monkeypatch):
    calls = {"batch": 0}

    def _boom(prompt, system=None, **kwargs):
        calls["batch"] += 1
        if system is classifier.BATCH_SYSTEM_PROMPT:
            raise classifier.ClaudeCallError("batch failed")
        return json.dumps({"title": "Fallback", "organization": "Acme", "type": "job"})

    monkeypatch.setattr(classifier, "run_claude", _boom)
    items = [
        {"url": "https://example.com/0", "text": "first"},
        {"url": "https://example.com/1", "text": "second"},
    ]
    results = classifier.classify_batch(items, None)
    assert len(results) == 2
    assert all(r["title"] == "Fallback" for r in results)
