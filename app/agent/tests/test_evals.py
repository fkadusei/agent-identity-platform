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
    assert "a forbidden tool is refused even with an argument missing" in names


def test_the_suite_covers_the_asking_path():
    # The one case that is not a refusal. It used to be one — a missing argument
    # ended the run — and was rewritten deliberately when the agent learned to
    # ask instead (S18), not adjusted until it passed.
    names = {name for name, _, _ in run_stubbed()}
    assert "a required argument is asked for, not guessed" in names
