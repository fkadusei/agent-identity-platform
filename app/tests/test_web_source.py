"""Guards the way I broke the UI: regex fragments pasted into markup.

While adding a facts row to the result card I generated the JSX from a script, and wrote
the regex quantifier meant to match whitespace into the output as literal text. It
compiled, it typechecked, and it rendered ``[]*`` on screen — the build, the typecheck
and the class-coverage check all passed, and none of them can see rendered text.

A test that reads the source can.
"""
from __future__ import annotations

from pathlib import Path

import pytest

SOURCES = sorted(Path(__file__).resolve().parents[1].joinpath("web/src").glob("*.ts*"))

# Regex quantifiers over whitespace: meaningful to a regex, meaningless in JSX/TS, and
# never legitimately present in this app's sources.
FOREIGN = ("[ \\t]*", "[ \\t]+", "[ ]*", "[ ]+")


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_regex_fragment_pasted_into_source(path: Path) -> None:
    text = path.read_text()
    for fragment in FOREIGN:
        assert fragment not in text, (
            f"{path.name} contains the literal {fragment!r} — a regex fragment that "
            "will render as text"
        )


def test_the_sources_were_actually_found() -> None:
    # A guard on the guard: a wrong glob would make the test above vacuous.
    assert SOURCES, "no web sources found — check the path"
