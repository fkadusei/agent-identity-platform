#!/usr/bin/env python3
"""Render a template with ${VAR} placeholders from the environment.

Used to render the Keycloak realm and the SPIRE server config at deploy time, so
client secrets and database passwords never live in the repository. Fails loudly
on a missing variable (no silent empty secrets).

Two passes, in this order:

1. **Conditional blocks** — `{{#if VAR}}...{{/if}}` and `{{#unless VAR}}...{{/unless}}`
   are kept or dropped based on whether VAR is set to a true-ish value
   (`1`, `true`, `yes`, `on`). This exists so one template can describe two
   deployments — here, the SPIRE KeyManager, which is the disk plugin on kind and
   AWS KMS when a KMS is configured — without a second copy of the file drifting
   out of sync.
2. **`${VAR}` substitution**, exactly as before (strict: a missing variable is an
   error).

Conditionals are resolved *before* substitution on purpose: it means a `${VAR}`
inside a kept block is still substituted, and a `${VAR}` inside a dropped block is
never demanded.
"""
import os
import re
import string
import sys

# Innermost blocks first, so nested conditionals resolve correctly: a body may not
# contain another opening marker.
INNERMOST = re.compile(
    r"\{\{#(if|unless)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\}\}"
    r"((?:(?!\{\{#(?:if|unless)\s).)*?)"
    r"\{\{/\1\}\}",
    re.DOTALL,
)
UNCLOSED = "{{#"
TRUEISH = ("1", "true", "yes", "on")


def truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in TRUEISH


def resolve_conditionals(text: str, environ) -> str:
    """Keep or drop `{{#if}}`/`{{#unless}}` blocks, innermost first."""
    while True:
        match = INNERMOST.search(text)
        if match is None:
            break
        kind, var, body = match.group(1), match.group(2), match.group(3)
        keep = truthy(environ.get(var))
        if kind == "unless":
            keep = not keep
        text = text[: match.start()] + (body if keep else "") + text[match.end() :]
    if UNCLOSED in text:
        where = text.index(UNCLOSED)
        raise ValueError(
            "unbalanced or malformed conditional block near "
            f"{text[max(0, where - 40):where + 40]!r}"
        )
    return text


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: render.py <template>", file=sys.stderr)
        return 2
    with open(sys.argv[1], encoding="utf-8") as handle:
        raw = handle.read()
    try:
        template = string.Template(resolve_conditionals(raw, os.environ))
        sys.stdout.write(template.substitute(os.environ))
    except ValueError as exc:
        print(f"render.py: {exc}", file=sys.stderr)
        return 1
    except KeyError as exc:
        print(f"render.py: missing environment variable {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
