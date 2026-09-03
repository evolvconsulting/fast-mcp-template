#!/usr/bin/env python3
r"""Static anchor checker for the mutation and amputation harnesses.

WHY THIS EXISTS. Every harness in `scripts/` anchors on SOURCE TEXT: it
finds a literal string in a file under `src/` and replaces it. Any
reformatting can invalidate an anchor, and *a mutation that applies to
nothing tests nothing*. B49b reflowed 1608 lines, broke U3's M8, and CI
noticed only because that one step happened to grep for `COULD NOT
APPLY` - after a multi-minute harness run. Reading the anchors and
grepping the target file takes milliseconds, which is what you want on
the sweep commit itself.

WHAT IT CHECKS. For every anchor: the target file exists, and the anchor
occurs in it EXACTLY ONCE. Zero hits is a stale anchor; two or more is
the `ANCHOR NOT UNIQUE` failure the harnesses themselves raise, and both
mean the row silently tests nothing.

HOW IT FINDS ANCHORS, and why nothing here is a hand-kept list. A
hand-kept list beside its container is blind to the member nobody added,
so the anchor positions are DERIVED, never tabulated:

  Shape A, the shell helpers. The helper's own `local id="$1" file="$2"
  old="$3"` line names its parameters, so the file argument is whichever
  position is called `file` and the anchor is whichever is called `old`.
  U5's helper takes an extra `selector` and needs no special case,
  because its `local` line says so. A helper that takes no `file` names
  its target in its own `python3 - "..."` invocation, and that is read
  from the helper too.

  Shape B, the inline Python heredocs. WHICH heredocs are parsed is
  read off the line that opens them - a `python3 -` invocation - and
  never off the body's own text. The body is parsed with `ast`, and a
  string literal - directly, or through a name bound once in the same
  heredoc - yields an anchor wherever the row locates its cut by one:
  `str.replace`, `re.sub`, `re.subn`, and the `.index`/`.find`/`.count`
  a slice-splice row uses to find the position it cuts at. A literal
  the same heredoc has already contributed is not counted twice.

  The `.index(x, start)` form is the one weaker case, and it is called
  `py-scan` rather than being folded in silently: the row searches
  forward from a position it already holds, so it needs the text to
  occur AT LEAST once and not exactly once. Row M of
  check-u1-boot-amputation.sh ends its cut at `"    )\n"`, which occurs
  four times in `__main__.py` and is correct.

  Shape C, the `@@`-delimited spec tables. Which field is the anchor is
  read off the loop's own `NAME="${...@@...}"` assignments, in source
  order: the one called `OLD`.

  Shape D, the `sed -i` command strings. U0's harness passes its
  mutation to `eval` as a shell command, so its anchors are sed
  PATTERNS, not string literals. Every double-quoted argument
  containing `sed -i` is tokenised, its `s///` and `/addr/d` commands
  are scanned out, and each pattern is translated from POSIX BRE to a
  Python regex and matched line-wise against the single file operand.
  The mutation is found by its CONTENT, not by a parameter name: U0's
  helper calls its argument `mutate`, and matching on that word would
  be a hand-kept list of one.

COMPLETENESS, checked rather than assumed. A parser that silently skips
a call site is exactly the defect this checker exists to catch, one
level up. So it counts the call sites it *could* see independently of
the ones it parsed, and `--self-check` reports both. An unparseable
heredoc is an error, not a skip, and a harness that edits files by a
mechanism no shape can read is NAMED on every run rather than passing as
a clean zero.

Exit codes:
  0  every anchor resolves uniquely
  1  an anchor is stale or ambiguous, or the count is below --floor
  2  the checker could not parse a harness (a parser gap, not a defect)
"""

from __future__ import annotations

import argparse
import ast
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"

# A heredoc opened with a QUOTED delimiter, which is the only form used
# here and the only form in which the body is literal rather than
# shell-expanded.
HEREDOC_RE = re.compile(
    r"<<'(?P<tag>[A-Za-z_][A-Za-z0-9_]*)'\n(?P<body>.*?)\n(?P=tag)\n", re.S
)
# `python3 - "<path expression>"` - the file the heredoc, or the helper,
# edits.
PY_INVOKE_RE = re.compile(r'python3\s+-\s+"(?P<path>[^"]+)"')
ASSIGN_RE = re.compile(r"^(?P<var>[A-Za-z_][A-Za-z0-9_]*)=(?P<val>.+)$", re.M)
VAR_REF_RE = re.compile(
    r"\$\{(?P<a>[A-Za-z_][A-Za-z0-9_]*)\}|\$(?P<b>[A-Za-z_][A-Za-z0-9_]*)"
)
# `name() {` AND `name () {` - the space is legal, two harnesses use it,
# and a regex without it returned a silent zero for both.
FUNCDEF_RE = re.compile(r"^(?P<name>[a-z_][a-z0-9_]*)\s*\(\)\s*\{", re.M)
LOCAL_RE = re.compile(r"^\s*local\s+(?P<decls>.+)$", re.M)
LOCAL_ARG_RE = re.compile(r'(?P<name>[a-z_][a-z0-9_]*)="\$(?P<pos>\d+)"')


@dataclass
class Anchor:
    """One anchor: where it is declared, and what it must match."""

    harness: str
    line: int
    shape: str
    target: str
    text: str


class ParseError(Exception):
    """A shape this checker cannot read. Never swallowed as a skip."""


def _resolve_vars(src: str) -> dict[str, str]:
    """Expand the script-level `VAR=value` assignments against others.

    A value produced by a command substitution - `$(mktemp -d)`, or
    `$(cd .. && pwd)` - is a path that only exists at runtime, so it
    resolves to the empty string. Every target path in these harnesses
    is written relative to one of those (`"$REPO/scripts/..."`,
    `"$TREE/$GATE_REL"`), so emptying them leaves the repo-relative path
    this checker needs, after a leading-slash strip.
    """
    raw: dict[str, str] = {}
    runtime: set[str] = set()
    for m in ASSIGN_RE.finditer(src):
        var, val = m.group("var"), m.group("val").strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if "$(" in val or "`" in val:
            runtime.add(var)
            val = ""
        raw.setdefault(var, val)

    # Only the command substitution itself is emptied, never the
    # variables built on it. Emptying those TRANSITIVELY was tried and
    # is wrong in one direction while right in the other:
    # `SCRIPT="$REPO/scripts/check-suite-floor.sh"` over a `REPO=$(cd ..
    # && pwd)` needs its literal tail KEPT, while `TREE="$WORK/tree"`
    # over an `mktemp -d` needs its literal tail DROPPED. The difference
    # is not visible in the assignment, so it is not decided here -
    # `_expand_path` decides it against the filesystem, which can tell
    # them apart.
    del runtime
    resolved: dict[str, str] = {}

    def expand(name: str, seen: frozenset[str]) -> str:
        if name in resolved:
            return resolved[name]
        if name in seen or name not in raw:
            return ""
        out = VAR_REF_RE.sub(
            lambda mm: expand(mm.group("a") or mm.group("b"), seen | {name}), raw[name]
        )
        resolved[name] = out
        return out

    for key in raw:
        expand(key, frozenset())
    return resolved


def _expand_path(expr: str, variables: dict[str, str]) -> str:
    """Expand a quoted shell path expression to a repo-relative path.

    A harness that mutates a COPY of the tree writes the copy's own
    layout into the path - `"$WORK/C/$GATE_REL"` - so an emptied runtime
    prefix can still leave a scratch segment in front. Leading segments
    are dropped one at a time until the path names a file that exists,
    and the FIRST such path wins; if none does, the expanded path is
    returned unchanged and reported as unresolved, which is a finding
    rather than a silent pass.
    """
    out = VAR_REF_RE.sub(
        lambda mm: variables.get(mm.group("a") or mm.group("b"), ""), expr
    )
    out = re.sub(r"/{2,}", "/", out).lstrip("/")
    parts = out.split("/")
    for i in range(len(parts)):
        candidate = "/".join(parts[i:])
        if (REPO_ROOT / candidate).is_file():
            return candidate
    return out


def _helper_signatures(src: str) -> dict[str, tuple[dict[str, int], str]]:
    """Map each helper name to its parameters and body, from `local`.

    Parameters come back as {name: 1-based positional index}. Only
    helpers taking one called `old` can carry an anchor; the rest are
    returned too, and the caller ignores them. The body comes back
    because a helper that does NOT take the target as a parameter names
    it in its own `python3 - "..."` invocation instead, and that is
    where the target is read from - derived from the helper, never from
    a table kept beside it.
    """
    sigs: dict[str, tuple[dict[str, int], str]] = {}
    for fm in FUNCDEF_RE.finditer(src):
        body = src[fm.end() :]
        end = body.find("\n}")
        body = body[: end if end != -1 else len(body)]
        params: dict[str, int] = {}
        for lm in LOCAL_RE.finditer(body):
            for am in LOCAL_ARG_RE.finditer(lm.group("decls")):
                params[am.group("name")] = int(am.group("pos"))
        if params:
            sigs[fm.group("name")] = (params, body)
    return sigs


def _split_call(src: str, start: int) -> tuple[list[str], int]:
    r"""Tokenize one shell call, honouring '', "" and backslash-newline.

    Starts at `start` and returns (argv, index just past the call).
    Written by hand rather than with `shlex` because shlex's POSIX mode
    discards the distinction between a literal single-quoted anchor and
    a double-quoted one that shell would expand, and an anchor is
    exactly the thing that must not be re-quoted.
    """
    argv: list[str] = []
    cur = ""
    started = False
    i = start
    n = len(src)
    while i < n:
        c = src[i]
        if c == "\\" and i + 1 < n and src[i + 1] == "\n":
            i += 2
            continue
        if c == "\n":
            i += 1
            break
        if c in " \t":
            if started:
                argv.append(cur)
                cur = ""
                started = False
            i += 1
            continue
        if c == "'":
            j = src.find("'", i + 1)
            if j == -1:
                raise ParseError("unterminated single quote")
            cur += src[i + 1 : j]
            started = True
            i = j + 1
            continue
        if c == '"':
            j = i + 1
            buf = ""
            while j < n and src[j] != '"':
                if src[j] == "\\" and j + 1 < n:
                    buf += src[j : j + 2]
                    j += 2
                    continue
                buf += src[j]
                j += 1
            if j >= n:
                raise ParseError("unterminated double quote")
            cur += buf
            started = True
            i = j + 1
            continue
        cur += c
        started = True
        i += 1
    if started:
        argv.append(cur)
    return argv, i


def _shape_a(
    name: str,
    src: str,
    sigs: dict[str, tuple[dict[str, int], str]],
    variables: dict[str, str],
) -> tuple[list[Anchor], int]:
    """Read anchors passed as arguments to a shell helper.

    Returns (anchors, number of call sites seen).
    """
    carriers = {h: pb for h, pb in sigs.items() if "old" in pb[0]}
    if not carriers:
        return [], 0
    # `(?!\s*\(\))` excludes the helper's own DEFINITION line: `amputate
    # () {` also begins with the name and a space, and counting it as a
    # call site produced a phantom row whose "anchor" was `{`.
    call_re = re.compile(
        r"^(?P<name>" + "|".join(map(re.escape, carriers)) + r")[ \t]+(?!\(\))", re.M
    )
    anchors: list[Anchor] = []
    seen = 0
    for m in call_re.finditer(src):
        seen += 1
        lineno = src.count("\n", 0, m.start()) + 1
        argv, _ = _split_call(src, m.start())
        params, body = carriers[m.group("name")]
        if "file" in params:
            need = max(params["file"], params["old"])
            if len(argv) <= need:
                raise ParseError(
                    f"{name}: call to {m.group('name')} at line {lineno} "
                    f"has {len(argv) - 1} args, needs {need}"
                )
            target = _expand_path(argv[params["file"]], variables)
        else:
            # No `file` parameter, so the helper edits a path it names
            # itself.
            inv = PY_INVOKE_RE.search(body)
            if inv is None:
                raise ParseError(
                    f"{name}: helper {m.group('name')} takes an `old` "
                    "anchor but names no target - neither a `file` "
                    'parameter nor a `python3 - "..."` invocation'
                )
            target = _expand_path(inv.group("path"), variables)
            if len(argv) <= params["old"]:
                raise ParseError(
                    f"{name}: call to {m.group('name')} at line {lineno} "
                    f"has {len(argv) - 1} args, needs {params['old']}"
                )
        anchors.append(Anchor(name, lineno, "shell-arg", target, argv[params["old"]]))
    return anchors, seen


def _shape_b(
    name: str, src: str, variables: dict[str, str]
) -> tuple[list[Anchor], int]:
    """Read anchors out of an inline `python3 -` heredoc with `ast`."""
    anchors: list[Anchor] = []
    seen = 0
    for m in HEREDOC_RE.finditer(src):
        body = m.group("body")
        line = src.count("\n", 0, m.start()) + 1
        # The heredoc's target file: the $VAR on the `python3 -` line
        # that opened it.
        head = src[: m.start()].rsplit("\n", 1)[-1]
        # WHICH HEREDOCS ARE OPENED IS DERIVED FROM THE INVOCATION, not
        # from the body's prose. This used to read `if ".replace(" not
        # in body and "re.sub(" not in body: continue`, and a predicate
        # over the body's TEXT is a predicate the body's text decides:
        # it skipped the heredoc WHOLE - every site in it, of every kind
        # - and it skipped it before the `seen` tally could count
        # anything, so the completeness check came out clean on both
        # sides. Measured at 22c9873: three live anchors in
        # check-u1-boot-amputation.sh (rows H, K and M) were invisible
        # that way, and `--self-check` reported no gap. The line that
        # opens a heredoc says whether it is Python; that is what is
        # read now. A `@@` spec table has no `python3` on its opening
        # line, and under the old rule a spec row whose OLD text
        # happened to contain `.replace(` would have been handed to
        # `ast.parse` and reported as a parser gap.
        if "python3" not in head:
            continue
        inv = PY_INVOKE_RE.search(head)
        try:
            tree = ast.parse(body)
        except SyntaxError as exc:  # a parser gap, never a silent skip
            raise ParseError(
                f"{name}: heredoc at line {line} does not parse: {exc}"
            ) from exc
        # Anchors are not always written inline. Half of U1's rows bind
        # one to a local first - `anchor = "..."` then
        # `s.replace(anchor, ...)` - so an inline-literals-only parser
        # skips them WITHOUT ERRORING, which is the very defect this
        # checker exists to catch, one level up. Measured: it saw 2 of
        # U1's 7 and 14 of the controls' 20 before this resolution
        # existed. Only single-assignment string constants are resolved;
        # a name bound twice is left unresolved rather than guessed at.
        assigned: dict[str, str | None] = {}
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                # NOT `name`: that is this function's harness-name
                # parameter, and binding it here renamed every anchor
                # reported after the first assignment in a heredoc.
                bound_name = node.targets[0].id
                value = (
                    node.value.value
                    if isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                    else None
                )
                assigned[bound_name] = None if bound_name in assigned else value

        def literal(
            node: ast.expr, bound: dict[str, str | None] = assigned
        ) -> str | None:
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            if isinstance(node, ast.Name):
                return bound.get(node.id)
            return None

        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "replace"
                # `>= 2`, not `== 2`. `s.replace(old, new, 1)` is the
                # bounded form three harnesses use, and an exact-arity
                # test dropped it without counting it as seen - a
                # literal anchor in that form would have vanished at
                # exit 0. Today all three pass `old` as a parameter, so
                # no anchor was actually lost; that is a measurement,
                # not a reason to leave the selector arity-bound.
                and len(node.args) >= 2
            ):
                continue
            seen += 1
            anchor_text = literal(node.args[0])
            if anchor_text is None:
                continue  # the generic helper: `s.replace(old, new)` over parameters
            if inv is None:
                raise ParseError(
                    f"{name}: literal .replace() at line {line} but no "
                    '`python3 - "..."` '
                    "on the opening line; the target file cannot be resolved"
                )
            anchors.append(
                Anchor(
                    name,
                    line + node.lineno,
                    "py-heredoc",
                    _expand_path(inv.group("path"), variables),
                    anchor_text,
                )
            )

        # `re.sub(pattern, repl, s, flags=re.S)`. U15's amputation
        # harness anchors ENTIRELY this way and, uniquely among the
        # harnesses, has no vocabulary for reporting that a row did not
        # apply - `re.sub` that matches nothing returns the string
        # unchanged and raises nothing, so the row runs, prints a
        # result, and tested an INTACT tree. A regex anchor is still an
        # anchor; it is checked with `re.search` instead of `str.count`,
        # with the call's own flags.
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                # `subn` AS WELL AS `sub`. Matching only `sub` made row
                # H of check-u1-boot-amputation.sh invisible at 22c9873,
                # and worse than invisible: `re.subn` is the SAFER
                # idiom, because it returns the substitution count and
                # lets the row assert that it landed. A selector that
                # sees `re.sub` and not `re.subn` charges an anchor for
                # using the construct this project wants, which is how a
                # gate ends up shaping code away from the better form.
                and node.func.attr in ("sub", "subn")
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "re"
                and node.args
            ):
                continue
            seen += 1
            pattern = literal(node.args[0])
            if pattern is None:
                continue
            if inv is None:
                raise ParseError(
                    f"{name}: literal re.sub() at line {line} but no "
                    '`python3 - "..."` on the opening line'
                )
            anchors.append(
                Anchor(
                    name,
                    line + node.lineno,
                    "py-regex",
                    _expand_path(inv.group("path"), variables),
                    pattern,
                )
            )

        # `s[:start] + NEW + s[end:]`, the index-and-slice rows. These
        # are anchored just as hard as a `.replace()` - rows K and M of
        # check-u1-boot-amputation.sh locate their cut with
        # `s.index("    _loguru.remove()")` and
        # `s.index("    logging.basicConfig(")` - but the splice is an
        # operator, not a call, so no call-shaped selector reached them
        # and their anchors were invisible at 22c9873.
        #
        # The anchor is not the splice: it is the LITERAL the row looks
        # the position up by. So the search calls are what is read -
        # `.index`, `.find` and `.count` - and the rule matches what the
        # row itself requires:
        #
        #   one argument   the row scans the whole file for it, and
        #                  these rows assert `s.count(anchor) == 1`,
        #                  so it must occur EXACTLY once. Same rule as
        #                  a `.replace()` anchor, same shape name.
        #   with an offset the row scans FORWARD from a position it
        #                  already has, so file-wide uniqueness is not
        #                  what it needs and demanding it would report a
        #                  live row as stale: row M's end anchor
        #                  `"    )\n"` occurs 4 times in __main__.py and
        #                  is perfectly correct. These get their own
        #                  shape and a WEAKER rule - at least one hit -
        #                  which is stated here rather than hidden,
        #                  because a weaker check that looks like the
        #                  strong one is worse than no check.
        #
        # A text this heredoc has already contributed is not counted
        # twice: `assert s.count(a) == 1` beside `s.replace(a, ...)` is
        # one anchor written two ways, and counting both would inflate
        # the floor with slack - the #91 defect, in the instrument.
        already = {a.text for a in anchors if a.line >= line}
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("index", "find", "count")
                and node.args
            ):
                continue
            seen += 1
            text = literal(node.args[0])
            if text is None or text in already:
                continue
            if inv is None:
                raise ParseError(
                    f"{name}: literal .{node.func.attr}() at line {line} "
                    'but no `python3 - "..."` on the opening line'
                )
            already.add(text)
            anchors.append(
                Anchor(
                    name,
                    line + node.lineno,
                    "py-heredoc" if len(node.args) == 1 else "py-scan",
                    _expand_path(inv.group("path"), variables),
                    text,
                )
            )
    return anchors, seen


def _shape_c(
    name: str, src: str, variables: dict[str, str]
) -> tuple[list[Anchor], int]:
    """Read anchors out of a `@@`-delimited spec here-document.

    U15's control harness declares its rows as `label@@OLD@@NEW@@test`
    lines and splits them with parameter expansion. WHICH field is the
    anchor is not guessed: the loop's own `NAME="${...@@...}"`
    assignments are read in source order, and the field whose variable
    is called `OLD` is the anchor - the same derive-don't-tabulate rule
    the shell helpers use.
    """
    field_re = re.compile(
        r'^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)="'
        r'\$\{[a-z_]+(?:%%|#\*)[^}]*@@[^}]*\}"',
        re.M,
    )
    order = [m.group("name") for m in field_re.finditer(src)]
    if "OLD" not in order:
        return [], 0
    idx = order.index("OLD")
    anchors: list[Anchor] = []
    seen = 0
    for m in HEREDOC_RE.finditer(src):
        body = m.group("body")
        if "@@" not in body:
            continue
        head = src[: m.start()].rsplit("\n", 1)[-1]
        # The loop that consumes the spec is what edits the file, so the
        # target comes from the `python3 - "..."` inside that loop, not
        # from the spec.
        inv = PY_INVOKE_RE.search(src[m.end() :])
        if inv is None:
            raise ParseError(
                f"{name}: an @@ spec here-document has no "
                '`python3 - "..."` consumer after it'
            )
        target = _expand_path(inv.group("path"), variables)
        base = src.count("\n", 0, m.start()) + 1
        for offset, row in enumerate(body.splitlines(), start=1):
            if not row.strip() or "@@" not in row:
                continue
            seen += 1
            fields = row.split("@@")
            if len(fields) <= idx:
                raise ParseError(
                    f"{name}: spec row at line {base + offset} has "
                    f"{len(fields)} fields, needs at least {idx + 1}"
                )
            try:
                text = ast.literal_eval(fields[idx])
            except (ValueError, SyntaxError) as exc:
                raise ParseError(
                    f"{name}: spec row at line {base + offset} carries an "
                    f"anchor that is not a Python literal: {exc}"
                ) from exc
            if not isinstance(text, str) or not text:
                continue
            anchors.append(Anchor(name, base + offset, "spec-row", target, text))
        del head
    return anchors, seen


# A double-quoted shell argument that invokes `sed -i`. The body honours
# backslash escapes so an embedded `\"` does not terminate the match.
SED_ARG_RE = re.compile(r'"(?P<cmd>(?:[^"\\]|\\.)*?\bsed\s+-i\b(?:[^"\\]|\\.)*?)"')
# Double-quote removal, as the shell performs it: a backslash is literal
# EXCEPT before one of $ ` " \ and newline.
DQ_ESCAPE_RE = re.compile(r'\\([$`"\\\n])')


def _sed_commands(script: str, where: str) -> list[str]:
    r"""Scan the patterns out of one sed script.

    Reads `s<delim>PAT<delim>REPL<delim>FLAGS` and `/PAT/d`, separated
    by `;` or newlines, and returns the PAT of each. Splitting the
    script on `;` first would be wrong and silently so: U0 carries
    `s|# transitive prerelease; must be named or resolution fails||`,
    whose pattern contains the separator. So the script is SCANNED
    left to right and each command consumes its own delimiters.

    Anything this cannot read is a ParseError, never a skip - an
    unreadable row that vanishes from the count is the exact defect
    this checker exists to catch, one level up.
    """

    def read_field(text: str, i: int, delim: str) -> tuple[str, int]:
        """Consume to the next UNESCAPED delim.

        Returns (field, index just past the delimiter).
        """
        out: list[str] = []
        while i < len(text):
            c = text[i]
            if c == "\\" and i + 1 < len(text):
                if text[i + 1] == delim:
                    # `\<delim>` inside a field is a literal delimiter.
                    out.append(delim)
                else:
                    out.append(text[i : i + 2])
                i += 2
                continue
            if c == delim:
                return "".join(out), i + 1
            out.append(c)
            i += 1
        raise ParseError(f"{where}: unterminated sed field (delimiter {delim!r})")

    pats: list[str] = []
    i, n = 0, len(script)
    while i < n:
        while i < n and script[i] in " \t\n;":
            i += 1
        if i >= n:
            break
        c = script[i]
        if c == "s":
            if i + 1 >= n:
                raise ParseError(f"{where}: `s` with no delimiter")
            delim = script[i + 1]
            if delim.isalnum() or delim in " \\\n":
                raise ParseError(f"{where}: bad `s` delimiter {delim!r}")
            pat, i = read_field(script, i + 2, delim)
            _repl, i = read_field(script, i, delim)
            while i < n and script[i] not in " \t\n;":  # flags: g, i, digits
                i += 1
            pats.append(pat)
        elif c == "/":
            pat, i = read_field(script, i + 1, "/")
            while i < n and script[i] in " \t":
                i += 1
            if i >= n or script[i] != "d":
                got = script[i] if i < n else "end of script"
                raise ParseError(
                    f"{where}: address /{pat}/ is followed by {got!r}; only "
                    "`d` is read by this checker"
                )
            i += 1
            pats.append(pat)
        else:
            raise ParseError(
                f"{where}: sed command {c!r} is not one this checker reads "
                "(`s///` and `/addr/d` only)"
            )
    return pats


def _bre_to_python(pat: str, where: str) -> str:
    r"""Translate a POSIX/GNU BRE to the equivalent Python regex.

    This is not cosmetic. In a BRE `(`, `)`, `{`, `}`, `|`, `+` and `?`
    are ORDINARY characters and `\(` is the group - the exact opposite
    of Python. Passing a sed pattern to `re` unchanged would turn
    `"mcp==2.1.1"` into a working regex by luck and the next pattern
    with a paren in it into a silent mismatch reported as a stale
    anchor. `^` and `$` are anchors only at the ends, and a leading `*`
    is literal.
    """
    out: list[str] = []
    i, n = 0, len(pat)
    while i < n:
        c = pat[i]
        if c == "\\":
            if i + 1 >= n:
                raise ParseError(f"{where}: pattern ends in a backslash")
            nxt = pat[i + 1]
            if nxt in "(){}|+?":  # GNU BRE: escaped form is the METAcharacter
                out.append(nxt)
            elif nxt == "/":
                out.append("/")
            else:
                out.append("\\" + nxt)
            i += 2
            continue
        if c == "[":
            j = i + 1
            if j < n and pat[j] == "^":
                j += 1
            if j < n and pat[j] == "]":
                j += 1
            while j < n and pat[j] != "]":
                j += 1
            if j >= n:
                raise ParseError(f"{where}: unterminated bracket expression")
            out.append(pat[i : j + 1])
            i = j + 1
            continue
        if c in "(){}|+?":  # BRE: ordinary
            out.append(re.escape(c))
        elif c == "^" and i != 0:
            out.append("\\^")
        elif c == "$" and i != n - 1:
            out.append("\\$")
        elif c == "*" and (i == 0 or (i == 1 and pat[0] == "^")):
            out.append("\\*")
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _shape_d(
    name: str, src: str, variables: dict[str, str]
) -> tuple[list[Anchor], int]:
    """Read anchors out of `sed -i` command strings."""
    anchors: list[Anchor] = []
    seen = 0
    for m in SED_ARG_RE.finditer(src):
        line = src.count("\n", 0, m.start()) + 1
        where = f"{name}:{line}"
        cmd = DQ_ESCAPE_RE.sub(r"\1", m.group("cmd"))
        try:
            argv = shlex.split(cmd)
        except ValueError as exc:
            raise ParseError(
                f"{where}: cannot tokenise the sed command: {exc}"
            ) from exc
        if not argv or argv[0] != "sed":
            continue
        seen += 1
        scripts_: list[str] = []
        operands: list[str] = []
        j = 1
        while j < len(argv):
            a = argv[j]
            if a == "-e":
                if j + 1 >= len(argv):
                    raise ParseError(f"{where}: `-e` with no expression")
                scripts_.append(argv[j + 1])
                j += 2
                continue
            if a.startswith("-"):  # -i, -i.bak, -E, -r, -n, bundles
                j += 1
                continue
            operands.append(a)
            j += 1
        if not scripts_:
            if not operands:
                raise ParseError(f"{where}: sed invocation has no script")
            scripts_.append(operands.pop(0))
        if len(operands) != 1:
            raise ParseError(
                f"{where}: expected exactly one file operand, got {operands!r}"
            )
        target = _expand_path(operands[0], variables)
        for script in scripts_:
            for pat in _sed_commands(script, where):
                if not pat:
                    continue
                anchors.append(
                    Anchor(name, line, "sed-bre", target, _bre_to_python(pat, where))
                )
    return anchors, seen


def collect(path: Path) -> tuple[list[Anchor], dict[str, int]]:
    src = path.read_text()
    variables = _resolve_vars(src)
    sigs = _helper_signatures(src)
    a_anchors, a_seen = _shape_a(path.name, src, sigs, variables)
    b_anchors, b_seen = _shape_b(path.name, src, variables)
    c_anchors, c_seen = _shape_c(path.name, src, variables)
    d_anchors, d_seen = _shape_d(path.name, src, variables)
    return (
        a_anchors + b_anchors + c_anchors + d_anchors,
        {
            "shell call sites": a_seen,
            "python edits": b_seen,
            "spec rows": c_seen,
            "sed commands": d_seen,
        },
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--self-check",
        action="store_true",
        help="print the per-harness tally of call sites seen against anchors parsed",
    )
    ap.add_argument(
        "--quiet", action="store_true", help="print only failures and the verdict"
    )
    ap.add_argument(
        "--floor",
        type=int,
        default=0,
        metavar="N",
        help="fail if fewer than N anchors were resolved. If a "
        "parser shape stops matching, the count drops and "
        "every row it covered goes unchecked WITH THE RUN "
        "STILL GREEN. The floor lives in ci.yml, the one "
        "place the suite floor lives, and lowering it is a "
        "visible diff that has to be defended.",
    )
    args = ap.parse_args()

    # THIS CHECKER'S OWN CONTROL HARNESS IS NOT A HARNESS OF THE
    # PRODUCT. It anchors into a throwaway copy of the tree, so its
    # targets are runtime paths that resolve to nothing and its rows
    # arrive as findings about files that do not exist. Found by that
    # control harness on its first run, as a positive control that was
    # passing for the wrong reason.
    #
    # Matched on the FILENAME, derived from this file's own stem. The
    # first attempt excluded any script whose TEXT mentioned this
    # checker, and a comment added to check-u15-gate-amputation.sh - a
    # real harness with four live anchors - then excluded it silently,
    # dropping the count from 154 to 150. A predicate over prose is a
    # predicate any prose can trip.
    stem = Path(__file__).stem
    harnesses = [
        h for h in sorted(SCRIPTS.glob("check-*.sh")) if not h.name.startswith(stem)
    ]
    if not harnesses:
        print(f"ERROR: no harnesses found under {SCRIPTS} - is the path right?")
        return 2

    total = 0
    stale: list[tuple[Anchor, str]] = []
    unread: list[tuple[str, str]] = []

    # A harness that edits a file by a mechanism this parser cannot read
    # yields a clean zero, which is indistinguishable from a harness
    # that anchors on nothing - and a clean zero that explains itself is
    # the dangerous kind. So the mechanisms are detected independently
    # of the parse, and any harness that performs edits while
    # contributing no anchors is NAMED on every run.
    mechanisms = {
        "sed -i": "in-place `sed -i` expressions",
        ".replace(": "Python `str.replace`",
        "re.sub(": "Python `re.sub`",
        "@@": "an `@@`-delimited spec table",
    }

    for h in harnesses:
        try:
            anchors, tally = collect(h)
        except ParseError as exc:
            print(f"PARSER GAP: {exc}")
            return 2
        if not anchors:
            src = h.read_text()
            found = sorted({d for k, d in mechanisms.items() if k in src})
            if found:
                unread.append((h.name, ", ".join(found)))
        if args.self_check:
            counts = ", ".join(f"{k}={v}" for k, v in tally.items())
            print(f"  {h.name:36s} anchors={len(anchors):3d}  ({counts})")
        for a in anchors:
            total += 1
            target = REPO_ROOT / a.target
            if not target.is_file():
                stale.append((a, f"target file does not exist: {a.target}"))
                continue
            text = target.read_text()
            if a.shape == "py-regex":
                # DOTALL, because every re.sub anchor here passes
                # flags=re.S and the patterns span lines. Checking one
                # without it would report a live anchor as stale, which
                # is the loudest possible way to be wrong and the reason
                # it is stated here rather than defaulted.
                hits = len(re.findall(a.text, text, re.S))
            elif a.shape == "sed-bre":
                # MULTILINE, not DOTALL: sed matches one line at a time,
                # so `^` and `$` in these patterns mean line start and
                # line end. Under the default flags `^JOBVITE_API_KEY=`
                # would be tested against the start of the FILE and
                # reported stale while the row is perfectly live.
                hits = len(re.findall(a.text, text, re.M))
            else:
                hits = text.count(a.text)
            if a.shape == "py-scan":
                # An anchor the row searches for FROM a position it
                # already holds. Zero hits still breaks the row; more
                # than one does not, so uniqueness is not required and
                # is not claimed.
                if hits < 1:
                    stale.append((a, f"0 hits in {a.target} (need at least 1)"))
            elif hits != 1:
                stale.append((a, f"{hits} hits in {a.target} (need exactly 1)"))

    if not args.quiet:
        print(f"harnesses scanned: {len(harnesses)}")
        print(f"anchors resolved: {total}")

    if unread:
        print(
            f"UNREAD MUTATION MECHANISMS ({len(unread)}) - these "
            "harnesses edit files by a"
        )
        print("means this checker cannot read, so their rows are NOT covered below:")
        for scriptname, mechanism in unread:
            print(f"  {scriptname}: {mechanism}")

    for a, why in stale:
        print(f"STALE ANCHOR  {a.harness}:{a.line} [{a.shape}]  {why}")
        print(
            f"    anchor: {a.text.splitlines()[0][:100]!r}"
            + (" ..." if len(a.text.splitlines()) > 1 else "")
        )

    if stale:
        print(f"FAIL: {len(stale)} of {total} anchors do not resolve uniquely.")
        return 1
    if total < args.floor:
        print(
            f"FAIL: only {total} anchors were resolved, below the "
            f"floor of {args.floor}. "
            "A parser shape has stopped matching, so the rows it covered are now "
            "unchecked - and every one of them would still report OK."
        )
        return 1
    print(
        f"OK: all {total} anchors resolve in their target file "
        "(exactly one hit, or at least one for a `py-scan` anchor read "
        "forward from a position the row already holds)"
        + (f" (floor {args.floor})." if args.floor else ".")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
