"""The evaluation suite, run stubbed so CI covers the pipeline without a model."""
from __future__ import annotations

from app.agent.evals import run_stubbed


def test_every_case_passes():
    results = run_stubbed()
    failures = [(name, detail) for name, ok, detail in results if not ok]
    assert not failures, failures


def test_the_suite_covers_the_refusal_paths():
    names = {name for name, _, _ in run_stubbed()}
    # If these disappear, the suite has quietly stopped testing what matters.
    assert "PII is refused for a support rep" in names
    assert "an injection attempt is refused before the model" in names
    assert "a required argument is missing" in names
