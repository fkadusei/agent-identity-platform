#!/usr/bin/env python3
"""Render a template with ${VAR} placeholders from the environment.

Used to render the Keycloak realm at deploy time so client secrets never live in
the repository. Fails loudly on a missing variable (no silent empty secrets).
"""
import os
import string
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: render.py <template>", file=sys.stderr)
        return 2
    with open(sys.argv[1], encoding="utf-8") as handle:
        template = string.Template(handle.read())
    try:
        sys.stdout.write(template.substitute(os.environ))
    except KeyError as exc:
        print(f"render.py: missing environment variable {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
