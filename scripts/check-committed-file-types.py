#!/usr/bin/env python3
"""Committed-file-type gate. DESIGN.md:1717-1724.

WHY THIS EXISTS, stated because a control nobody understands gets
disabled the first time it is inconvenient: a CONFIDENTIAL vendor PDF
and an unlicensed RAML reached two public remotes on this project.
Rewriting history was not enough - the blob stayed fetchable by commit
SHA, and closing the exposure meant making both repositories private,
then deleting and recreating them.

A secret scanner cannot see either file. A PDF has no high-entropy token
and matches no credential regex, so it passes every secret scanner
cleanly. This gate is the other half.

WHAT IT DOES NOT DO, from the design's own admission at
DESIGN.md:1722-1724: it stops a FILE of the wrong type entering the
repository. It does nothing about confidential prose pasted into
Markdown. Of the two files that actually leaked here, the `.raml` is
refused by rule 2 (unknown extension) and the `.pdf` by rules 1 and 3 -
but a reader who trusts this gate to prevent "the incident" in general
is trusting it for something it cannot do.

THE FIVE RULES, in the order they are applied to each staged file:

  0. EXCEPTION. A path listed in `.file-type-allowlist` is skipped. The
     allowlist is read FROM THE INDEX, not the working tree, so an
     exception is usable only once it is staged - i.e. only when it
     appears in the same commit's diff, where a reviewer sees it
     (DESIGN.md:1720-1721).
  1. EXTENSION DENYLIST. The incident classes, refused by name so the
     message says what happened rather than "unknown type".
  2. ALLOWLIST-FIRST. Anything whose extension or basename is not on the
     allowlist is REFUSED, not permitted. This is the rule that catches
     a file type nobody anticipated, which is every interesting case.
  3. MAGIC NUMBER. The decision is not made on the extension alone. A
     file called `notes.md` whose bytes begin `%PDF-` is a PDF.
  4. NUL BACKSTOP. A file containing a NUL byte is binary whatever it is
     called and whatever its first bytes are.

FAIL-CLOSED. Every error path exits non-zero. A control that fails open
is worse than no control, because it is trusted. Exit 1 = a file was
refused, exit 2 = the gate itself could not run. Both block the commit.

Usage:
  scripts/check-committed-file-types.py # the staged set (pre-commit)
  scripts/check-committed-file-types.py --all # every tracked file (CI)
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ALLOWLIST_FILE = ".file-type-allowlist"

# Rule 2. Allowlist-first: an extension absent from here is REFUSED.
ALLOWED_EXTENSIONS = frozenset(
    {
        ".cfg",
        ".css",
        ".example",
        ".html",
        ".ini",
        ".js",
        ".json",
        ".lock",
        ".md",
        ".py",
        ".pyi",
        ".sh",
        ".sql",
        ".toml",
        ".ts",
        ".txt",
        ".yaml",
        ".yml",
    }
)

# Extension-less files and dotfiles, which carry the project's licence
# and tooling config. Matched on the whole basename.
ALLOWED_BASENAMES = frozenset(
    {
        ".dockerignore",
        ".editorconfig",
        ".file-type-allowlist",
        ".gitattributes",
        ".gitignore",
        ".python-version",
        # The secret gate's audited baseline. Without this entry the two
        # gates shipped in .pre-commit-config.yaml refuse each other:
        # detect-secrets needs .secrets.baseline committed, and
        # `.baseline` is not an extension anyone would think to
        # allowlist. Measured, not assumed.
        ".secrets.baseline",
        "CODEOWNERS",
        "Dockerfile",
        "LICENSE",
        "Makefile",
        "NOTICE",
    }
)

# Rule 1. Redundant with rule 2 today and deliberately so: these are the
# classes that actually leaked, plus credential material, and they get a
# message naming the incident rather than the generic refusal.
# Redundancy is also what keeps them refused if someone later widens the
# allowlist without thinking.
DENIED_EXTENSIONS = {
    ".7z": "archive",
    ".crt": "credential material",
    ".der": "credential material",
    ".doc": "vendor document",
    ".docx": "vendor document",
    ".gz": "archive",
    ".jks": "credential material",
    ".key": "credential material",
    ".p12": "credential material",
    ".pdf": "vendor document - THIS IS THE CLASS THAT LEAKED",
    ".pem": "credential material",
    ".pfx": "credential material",
    ".ppt": "vendor document",
    ".pptx": "vendor document",
    ".raml": "vendor API description - THIS IS THE CLASS THAT LEAKED",
    ".rar": "archive",
    ".tar": "archive",
    ".xls": "vendor document",
    ".xlsx": "vendor document",
    ".zip": "archive",
}

# Rule 3. Leading bytes that mean "this is not the text file it claims
# to be".
MAGIC = (
    (b"%PDF-", "PDF"),
    (b"PK\x03\x04", "ZIP container (zip, docx, xlsx, pptx, jar)"),
    (b"PK\x05\x06", "empty ZIP container"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
    (b"BM", "BMP"),
    (b"\x7fELF", "ELF executable"),
    (b"MZ", "DOS/PE executable"),
    (b"\x1f\x8b", "gzip"),
    (b"\xfd7zXZ\x00", "xz"),
    (b"BZh", "bzip2"),
    (b"7z\xbc\xaf\x27\x1c", "7-zip"),
    (b"Rar!\x1a\x07", "RAR"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "OLE compound file (legacy doc/xls/ppt)"),
    (b"{\\rtf", "RTF"),
    (b"%!PS", "PostScript"),
    (b"\x00\x01\x00\x00\x00", "TrueType font"),
    (b"OTTO", "OpenType font"),
    (b"SQLite format 3\x00", "SQLite database"),
    (b"\xca\xfe\xba\xbe", "Java class / Mach-O fat binary"),
)


class GateError(Exception):
    """The gate could not complete a check.

    Always fatal - see fail-closed.
    """


def git(*args: str) -> bytes:
    """Run git, raising rather than returning a value nobody checked."""
    try:
        proc = subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            capture_output=True,
            check=False,
        )
    except OSError as exc:  # git absent, not executable, ...
        raise GateError(f"could not run git {' '.join(args)}: {exc}") from exc
    if proc.returncode != 0:
        raise GateError(
            f"git {' '.join(args)} exited {proc.returncode}: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return proc.stdout


def staged_paths() -> list[str]:
    """Paths added/copied/modified/renamed in the index.

    Deletions cannot leak.
    """
    out = git("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR")
    return [p for p in out.decode("utf-8", "surrogateescape").split("\0") if p]


def tracked_paths() -> list[str]:
    out = git("ls-files", "-z")
    return [p for p in out.decode("utf-8", "surrogateescape").split("\0") if p]


def staged_blob(path: str) -> bytes:
    return git("show", f":{path}")


def worktree_blob(path: str) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise GateError(f"could not read {path}: {exc}") from exc


def load_allowlist(read: Callable[[str], bytes]) -> set[str]:
    """Read the exception list through the SAME reader as its files.

    In staged mode that is the index, so an exception the author has
    edited but not staged does not apply. That is the whole of
    "overrides only via an allowlist entry in the same commit".
    """
    try:
        raw = read(ALLOWLIST_FILE)
    except GateError:
        return set()  # no allowlist is the normal case, not an error
    entries = set()
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            entries.add(line)
    return entries


def classify(path: str, data: bytes) -> str | None:
    """Return a refusal reason, or None if the file may be committed."""
    name = Path(path).name
    # A dotfile with no further dot ('.gitignore') is a basename, not an
    # extension.
    suffix = (
        "" if (name.startswith(".") and name.count(".") == 1) else Path(name).suffix
    )
    lowered = suffix.lower()

    if lowered in DENIED_EXTENSIONS:  # rule 1
        return f"denylisted extension {lowered} ({DENIED_EXTENSIONS[lowered]})"

    if lowered not in ALLOWED_EXTENSIONS and name not in ALLOWED_BASENAMES:  # rule 2
        shown = lowered if lowered else f"basename {name!r}"
        return (
            f"{shown} is not on the allowlist (allowlist-first: unknown means refused)"
        )

    for signature, label in MAGIC:  # rule 3
        if data.startswith(signature):
            return f"content is a {label}, whatever the {lowered or 'name'} says"

    nul = data.find(b"\x00")  # rule 4
    if nul != -1:
        return f"contains a NUL byte at offset {nul}; this is a binary file"

    return None


def main(argv: list[str]) -> int:
    check_all = "--all" in argv[1:]
    unknown = [a for a in argv[1:] if a != "--all"]
    if unknown:
        print(
            f"check-committed-file-types: unknown argument(s): {unknown}",
            file=sys.stderr,
        )
        return 2

    reader = worktree_blob if check_all else staged_blob
    paths = tracked_paths() if check_all else staged_paths()
    allowed_paths = load_allowlist(reader)

    refusals: list[tuple[str, str]] = []
    excepted: list[str] = []
    for path in sorted(paths):
        if path in allowed_paths:  # rule 0
            excepted.append(path)
            continue
        reason = classify(path, reader(path))
        if reason:
            refusals.append((path, reason))

    for path in excepted:
        print(f"  exception: {path} is listed in {ALLOWLIST_FILE}")

    if refusals:
        print("")
        print("COMMIT REFUSED by the committed-file-type gate (DESIGN.md:1717-1724).")
        print("A CONFIDENTIAL vendor PDF and an unlicensed RAML reached public remotes")
        print("on this project once already. History rewriting did not close it.")
        print("")
        for path, reason in refusals:
            print(f"  {path}: {reason}")
        print("")
        print(f"If a file genuinely belongs here, add its path to {ALLOWLIST_FILE}")
        print(
            "AND STAGE THAT FILE IN THE SAME COMMIT, so the exception is in the diff."
        )
        return 1

    scope = "whole tree" if check_all else "staged set"
    print(
        f"committed-file-type gate [{scope}]: {len(paths)} file(s) checked, "
        "none refused."
    )
    # A STAGED RUN THAT CHECKED NOTHING MUST NOT LOOK LIKE THE CI
    # GATE PASSING. Run bare on a clean tree this prints a green
    # having opened zero files, and at the exit code that is
    # indistinguishable from `--all` passing over the whole repo.
    # It is how a `.log` committed at e4f568d kept the trunk red for
    # 127 commits while every local check said 0: the gate was never
    # asked the question CI asks.
    if not check_all and not paths:
        print("")
        print("NOTHING WAS STAGED, so this gate examined NO files and this")
        print("green means nothing about the repository. CI runs the whole-")
        print("tree form and it is the one that can fail:")
        print("")
        print("    scripts/check-committed-file-types.py --all")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except GateError as exc:
        # FAIL CLOSED. The gate could not answer, so the answer is no.
        print(f"committed-file-type gate FAILED TO RUN: {exc}", file=sys.stderr)
        print("Failing closed: the commit is blocked.", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:  # noqa: BLE001 - deliberate: any bug here blocks
        print(f"committed-file-type gate CRASHED: {exc!r}", file=sys.stderr)
        print("Failing closed: the commit is blocked.", file=sys.stderr)
        sys.exit(2)
