#!/usr/bin/env python3
"""Validate Streamlit Community Cloud deploy config before push.

Streamlit Cloud feeds packages.txt to apt-get with NO comment support:
every whitespace-separated token becomes a package name. A header like
  # Streamlit Community Cloud ...
installs as packages "Streamlit", "Community", "Cloud", etc. and fails deploy.

Exit 0 if OK, 1 with a clear error message otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Debian package name: starts with alnum, then alnum / + / - / . / _
_PACKAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9+._-]*$")


def validate_packages_txt(path: Path) -> list[str]:
    """Return list of error strings (empty if valid)."""
    errors: list[str] = []
    if not path.is_file():
        # Optional: only require when OCR/system deps are intended
        return errors

    text = path.read_text(encoding="utf-8")
    if not text.strip():
        errors.append(f"{path.name}: file is empty (remove it or list packages)")
        return errors

    # BOM or non-UTF8 would already fail; catch common Cloud footguns
    if text.startswith("\ufeff"):
        errors.append(f"{path.name}: remove UTF-8 BOM")

    packages: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue

        # Cloud does not support comments — any # is a deploy bug
        if line.startswith("#") or "#" in line:
            errors.append(
                f"{path.name}:{lineno}: comments are NOT allowed "
                f"(Streamlit Cloud passes every token to apt-get). "
                f"Got: {raw!r}"
            )
            continue

        # One package per line only
        tokens = line.split()
        if len(tokens) != 1:
            errors.append(
                f"{path.name}:{lineno}: exactly one package name per line "
                f"(no spaces, no prose). Got: {raw!r}"
            )
            continue

        name = tokens[0]
        if not _PACKAGE_NAME.match(name):
            errors.append(
                f"{path.name}:{lineno}: invalid Debian package name {name!r} "
                f"(use lowercase alnum, +, -, ., _ only)"
            )
            continue

        # Reject tokens that look like English prose, not packages
        if name[0].isupper() or name in {
            "Streamlit",
            "Community",
            "Cloud",
            "required",
            "for",
            "OCR",
        }:
            errors.append(
                f"{path.name}:{lineno}: looks like prose, not a package: {name!r}"
            )
            continue

        packages.append(name)

    if not packages and not errors:
        errors.append(f"{path.name}: no packages listed")

    # Duplicates
    seen: set[str] = set()
    for p in packages:
        if p in seen:
            errors.append(f"{path.name}: duplicate package {p!r}")
        seen.add(p)

    return errors


def validate_requirements_txt(path: Path) -> list[str]:
    """Light sanity check for requirements.txt."""
    errors: list[str] = []
    if not path.is_file():
        errors.append("requirements.txt: missing (required for Streamlit Cloud)")
        return errors

    text = path.read_text(encoding="utf-8")
    if not text.strip():
        errors.append("requirements.txt: empty")
        return errors

    has_streamlit = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # strip env markers
        req = line.split(";")[0].strip()
        name = re.split(r"[=<>!~\[]", req, maxsplit=1)[0].strip().lower()
        if name == "streamlit":
            has_streamlit = True
        # opencv: prefer headless on Cloud (GUI build pulls libGL)
        if name == "opencv-python":
            errors.append(
                f"requirements.txt:{lineno}: use opencv-python-headless "
                f"(not opencv-python) for Streamlit Cloud / headless servers"
            )

    if not has_streamlit:
        errors.append("requirements.txt: must include streamlit")

    return errors


def main() -> int:
    errors: list[str] = []
    errors.extend(validate_packages_txt(ROOT / "packages.txt"))
    errors.extend(validate_requirements_txt(ROOT / "requirements.txt"))

    if errors:
        print("Streamlit Cloud deploy validation FAILED:\n", file=sys.stderr)
        for e in errors:
            print(f"  • {e}", file=sys.stderr)
        print(
            "\nFix packages.txt: one Debian package per line, no comments, no prose.\n"
            "See scripts/validate_deploy.py and README Deploy section.",
            file=sys.stderr,
        )
        return 1

    print("Deploy config OK (packages.txt + requirements.txt).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
