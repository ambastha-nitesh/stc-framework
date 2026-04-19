"""Copy the hardened v0.2.0 codebase from the session working directory
into this repo, excluding build / runtime / test artifacts.

Intentionally explicit about what gets copied. Run once during the
v0.2.0 migration; keep for reference so the migration is reproducible.
"""

from __future__ import annotations

import shutil
from pathlib import Path

SRC = Path("C:/Nitesh/projects/STCFramework")
DST = Path("C:/Projects/stc-framework")

EXCLUDE_DIRS = {
    "__pycache__",
    ".stc",              # audit artifacts from test runs
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "htmlcov",
    ".git",              # never copy git state across repos
    "experimental",      # the dst already has this; never read from src's
    "mnt",               # legacy artifact
}
EXCLUDE_FILES = {
    ".coverage",
    ".coverage.xml",
    "coverage.xml",
    "files.zip",
    ".DS_Store",
    "Thumbs.db",
}


def _ignore(_dir: str, entries: list[str]) -> list[str]:
    return [
        e for e in entries
        if e in EXCLUDE_DIRS
        or e in EXCLUDE_FILES
        or e.endswith(".pyc")
        or e.endswith(".pyo")
    ]


# These are top-level items we want copied as a whole tree.
COPY_DIRS = ["src", "tests", ".github", "config", "spec-examples"]

# These are top-level files to overwrite.
COPY_FILES = [
    "pyproject.toml",
    ".gitignore",
    ".pre-commit-config.yaml",
    "CHANGELOG.md",
    "SECURITY.md",
    "README.md",
    "CONTRIBUTING.md",
    "docker-compose.yaml",
]


def main() -> None:
    for name in COPY_DIRS:
        src = SRC / name
        dst = DST / name
        if not src.exists():
            print(f"skip missing dir: {name}")
            continue
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=_ignore)
        print(f"copied dir: {name}")

    for name in COPY_FILES:
        src = SRC / name
        if not src.exists():
            print(f"skip missing file: {name}")
            continue
        dst = DST / name
        shutil.copy2(src, dst)
        print(f"copied file: {name}")

    # Docs: merge additively. Never delete what's already in dst (the
    # existing .docx files + tracked subdirs are load-bearing).
    src_docs = SRC / "docs"
    dst_docs = DST / "docs"
    for item in src_docs.iterdir():
        if item.name in EXCLUDE_DIRS or item.name in EXCLUDE_FILES:
            continue
        target = dst_docs / item.name
        if item.is_dir():
            if target.exists():
                # Merge directories (shallow); add new files, overwrite .md.
                for child in item.rglob("*"):
                    if any(p in EXCLUDE_DIRS for p in child.parts):
                        continue
                    rel = child.relative_to(item)
                    out = target / rel
                    if child.is_dir():
                        out.mkdir(parents=True, exist_ok=True)
                    else:
                        out.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(child, out)
            else:
                shutil.copytree(item, target, ignore=_ignore)
            print(f"merged docs dir: {item.name}")
        else:
            shutil.copy2(item, target)
            print(f"copied doc file: {item.name}")

    # The canonical showcase HTML is at the root; replace it with the
    # freshly updated one produced this session.
    new_showcase = SRC / "docs" / "showcase" / "STC_Framework_Showcase.html"
    if new_showcase.exists():
        shutil.copy2(new_showcase, DST / "STC_Framework_Showcase.html")
        print("updated root-level STC_Framework_Showcase.html")


if __name__ == "__main__":
    main()
