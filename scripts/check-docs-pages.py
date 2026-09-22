#!/usr/bin/env python3
"""Keep the navigable pages in docs/site honest as the code moves under them.

These pages quote real code and link to their own sections, which means they can
rot in ways prose cannot: a renamed function leaves a snippet that no longer
exists, and a deleted section leaves a nav link that goes nowhere. Both are
invisible when you open the page and obvious when you grep for it — so this
checks for them the way a reader would, mechanically.

What it verifies, per page in docs/site/:

  1. every href="#x" resolves to an element with id="x"
  2. every <section id> is reachable from the nav
  3. every relative link (index.html, ...) exists on disk
  4. tags balance
  5. every quoted code block matches its source file, line for line

Rule 5 is the one that matters. A block is checked when its caption names a file
that exists in the repository; a block whose caption does not is required to say
it is *illustrative* (shown for shape, not present in the tree) or that it holds
*commands*. That way a reader can always tell quoted code from a sketch, and a
sketch cannot quietly pretend to be code.

Usage:  python3 scripts/check-docs-pages.py
Exit:   0 all pages check out, 1 with one line per problem.
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "docs" / "site"

# Elements that never take a closing tag — HTML plus the SVG primitives the
# diagrams use.
VOID = {
    "br", "hr", "img", "input", "meta", "link", "source", "area", "col", "embed",
    "param", "track", "wbr", "circle", "rect", "path", "line", "marker", "polyline",
    "polygon", "ellipse", "use", "stop",
}

PATH_RE = re.compile(r"[\w./-]+\.(?:py|rego|sh|ya?ml|json|ts|js|go)\b")
MARKERS = ("illustrative", "reconstructed", "commands")


def tag_balance(page: str, text: str, problems: list[str]) -> None:
    stack: list[str] = []
    for close, name, selfclose in re.findall(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)\b[^>]*?(/?)>", text):
        n = name.lower()
        if n in VOID or selfclose == "1":
            continue
        if close:
            if not stack or stack[-1] != n:
                problems.append(f"{page}: stray </{n}>")
                return
            stack.pop()
        else:
            stack.append(n)
    if stack:
        problems.append(f"{page}: unclosed {stack}")


def source_lines(path: Path) -> set[str]:
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines()}


def check_code(page: str, text: str, problems: list[str]) -> int:
    """Verify every quoted block against the file its caption names."""
    checked = 0
    blocks = re.findall(
        r'<div class="codeblock">.*?<p class="cap">(.*?)</p>\s*<pre>(.*?)</pre>',
        text,
        re.S,
    )
    for caption, body in blocks:
        cap = html.unescape(re.sub(r"<[^>]+>", "", caption)).strip()
        match = PATH_RE.search(cap)
        if not match:
            if not any(m in cap.lower() for m in MARKERS):
                problems.append(
                    f'{page}: code block "{cap}" names no source file — caption it '
                    f'with the file, or say it is illustrative/commands'
                )
            continue
        path = ROOT / match.group(0)
        if not path.exists():
            problems.append(f'{page}: caption names {match.group(0)}, which does not exist')
            continue
        known = source_lines(path)
        for line in html.unescape(body).splitlines():
            t = line.strip()
            if not t:
                continue
            checked += 1
            if t not in known:
                problems.append(f'{page}: not in {match.group(0)}: {t[:88]}')
    # ASCII blocks carry their claim in the note that follows them.
    for body, note in re.findall(
        r'<pre class="ascii">(.*?)</pre>\s*<p class="mono"[^>]*>(.*?)</p>', text, re.S
    ):
        match = PATH_RE.search(html.unescape(re.sub(r"<[^>]+>", "", note)))
        if not match:
            continue
        path = ROOT / match.group(0)
        if not path.exists():
            problems.append(f'{page}: diagram claims {match.group(0)}, which does not exist')
            continue
        known = source_lines(path)
        for line in html.unescape(body).splitlines():
            t = line.strip()
            if not t:
                continue
            checked += 1
            if t not in known:
                problems.append(f'{page}: diagram line not in {match.group(0)}: {t[:88]}')
    return checked


def check_page(path: Path) -> tuple[list[str], int]:
    page = path.name
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []

    ids = set(re.findall(r'\bid="([^"]+)"', text))
    hrefs = re.findall(r'href="#([^"]+)"', text)
    for h in hrefs:
        if h not in ids:
            problems.append(f'{page}: href="#{h}" goes nowhere')

    nav = re.search(r"<nav\b.*?</nav>", text, re.S)
    nav_targets = set(re.findall(r'href="#([^"]+)"', nav.group(0))) if nav else set()
    for section in re.findall(r'<section[^>]*\bid="([^"]+)"', text):
        if section not in nav_targets:
            problems.append(f"{page}: section #{section} is not in the nav")

    for rel in set(re.findall(r'href="([^"#][^"]*)"', text)):
        if rel.startswith(("http://", "https://", "mailto:")):
            continue
        if not (path.parent / rel).exists():
            problems.append(f"{page}: link to {rel} is broken")

    tag_balance(page, text, problems)
    return problems, check_code(page, text, problems)


def main() -> int:
    pages = sorted(SITE.glob("*.html"))
    if not pages:
        print(f"no pages under {SITE.relative_to(ROOT)}", file=sys.stderr)
        return 1
    problems: list[str] = []
    quoted = 0
    for page in pages:
        found, checked = check_page(page)
        problems += found
        quoted += checked
        mark = "ok" if not found else f"{len(found)} problem(s)"
        print(f"  {page.name:<22} {mark}")
    if problems:
        print()
        for p in problems:
            print(f"  {p}")
        print(f"\n{len(problems)} problem(s) across {len(pages)} page(s).")
        return 1
    print(f"\n{len(pages)} page(s) consistent; {quoted} quoted lines match their sources.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
