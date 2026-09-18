from __future__ import annotations

from eval.runner import run


def test_deterministic_evaluation_gate_passes_without_external_dependencies():
    report = run("deterministic")
    assert report["deterministic_gate"] == "PASS"
    assert report["routing"]["status"] == "PASS"
    assert report["planning"]["status"] == "PASS"
    assert report["safety"]["status"] == "PASS"
    assert report["execution"]["status"] == "NOT_RUN"
    assert report["rag"]["status"] == "NOT_RUN"


def test_rag_without_ranked_results_is_not_reported_as_pass():
    report = run("rag")
    assert report["rag"]["status"] == "NOT_RUN"
    assert report["rag"]["metrics"]["hit_rate_at_k"] is None
