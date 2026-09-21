"""The deploy-time renderer (scripts/render.py) and its conditional blocks.

It lives under app/tests because pytest collects `app` (see pytest.ini) and the
tool is small enough not to deserve its own harness — but the template it renders
decides which KeyManager SPIRE starts with, so the conditional logic is worth a
test rather than a manual run.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RENDER = Path(__file__).resolve().parents[2] / "scripts" / "render.py"
_spec = importlib.util.spec_from_file_location("render", RENDER)
render = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render)


def test_if_block_kept_when_the_flag_is_trueish():
    for value in ("1", "true", "yes", "on", "TRUE"):
        out = render.resolve_conditionals("{{#if F}}kept{{/if}}", {"F": value})
        assert out == "kept", value


def test_if_block_dropped_when_the_flag_is_absent_or_false():
    for env in ({}, {"F": ""}, {"F": "0"}, {"F": "false"}, {"F": "no"}):
        out = render.resolve_conditionals("{{#if F}}dropped{{/if}}", env)
        assert out == "", env


def test_unless_is_the_inverse():
    assert render.resolve_conditionals("{{#unless F}}kept{{/unless}}", {}) == "kept"
    assert render.resolve_conditionals("{{#unless F}}x{{/unless}}", {"F": "1"}) == ""


def test_nested_blocks_resolve_innermost_first():
    text = "{{#if A}}a{{#if B}}b{{/if}}{{/if}}"
    assert render.resolve_conditionals(text, {"A": "1", "B": "1"}) == "ab"
    assert render.resolve_conditionals(text, {"A": "1"}) == "a"
    assert render.resolve_conditionals(text, {"B": "1"}) == ""


def test_unbalanced_block_is_an_error_not_silent_junk():
    with pytest.raises(ValueError):
        render.resolve_conditionals("{{#if A}}no closing tag", {"A": "1"})


def test_substitution_happens_after_conditionals():
    """A `${VAR}` inside a kept block is still substituted; inside a dropped one it
    is never demanded — which is what lets one template describe both modes."""
    kept = render.resolve_conditionals("{{#if A}}${VALUE}{{/if}}", {"A": "1"})
    assert kept == "${VALUE}"
    assert render.resolve_conditionals("{{#if A}}${VALUE}{{/if}}", {}) == ""
