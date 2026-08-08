#!/usr/bin/env python3
"""Validate Streamlit Community Cloud deploy config before push.

Streamlit Cloud feeds packages.txt to apt-get with NO comment support and
installs every listed name. Failures here take down the live app at boot.

Rules learned from production outages:
1. No comments / multi-token lines (Cloud installs words as package names).
2. List only top-level leaf packages; never pin transitive libs
   (e.g. libglib2.0-0 conflicts with libglib2.0-0t64 on Debian trixie).
3. packages.txt is an allowlist — only names we have verified on Cloud.

Exit 0 if OK, 1 with a clear error message otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Debian package name: starts with alnum, then alnum / + / - / . / _
_PACKAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9+._-]*$")

# Only packages we deliberately need and have verified. Expand this list
# only after a successful Streamlit Cloud rebuild with the new package.
# Prefer leaf packages (tesseract-ocr, libgl1); let apt pull dependencies.
ALLOWED_PACKAGES: frozenset[str] = frozenset(
    {
        "libgl1",  # libGL.so.1 for RapidOCR / residual OpenCV needs
        "tesseract-ocr",  # OCR fallback binary
    }
)

# Known footguns if someone bypasses the allowlist later
_FORBIDDEN_REASON: dict[str, str] = {
    "libglib2.0-0": (
        "conflicts with libglib2.0-0t64 on Debian trixie (Cloud); "
        "do not pin glib — let tesseract-ocr pull the correct package"
    ),
    "libgl1-mesa-glx": "transitional/removed on modern Debian; use libgl1",
    "libsm6": "transitive X11 dep — do not pin; use opencv-python-headless",
    "libxext6": "transitive X11 dep — do not pin; use opencv-python-headless",
    "libxrender1": "transitive X11 dep — do not pin; use opencv-python-headless",
    "libffi7": "old bullseye-era package; not installable on trixie",
    "libpcre3": "old package; not installable on trixie",
}


def validate_packages_txt(path: Path) -> list[str]:
    """Return list of error strings (empty if valid)."""
    errors: list[str] = []
    if not path.is_file():
        return errors

    text = path.read_text(encoding="utf-8")
    if not text.strip():
        errors.append(f"{path.name}: file is empty (remove it or list packages)")
        return errors

    if text.startswith("\ufeff"):
        errors.append(f"{path.name}: remove UTF-8 BOM")

    packages: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue

        if line.startswith("#") or "#" in line:
            errors.append(
                f"{path.name}:{lineno}: comments are NOT allowed "
                f"(Streamlit Cloud passes every token to apt-get). "
                f"Got: {raw!r}"
            )
            continue

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

        if name[0].isupper():
            errors.append(
                f"{path.name}:{lineno}: looks like prose, not a package: {name!r}"
            )
            continue

        if name in _FORBIDDEN_REASON:
            errors.append(
                f"{path.name}:{lineno}: forbidden package {name!r}: "
                f"{_FORBIDDEN_REASON[name]}"
            )
            continue

        if name not in ALLOWED_PACKAGES:
            errors.append(
                f"{path.name}:{lineno}: {name!r} is not in ALLOWED_PACKAGES. "
                f"Only list verified leaf packages: {sorted(ALLOWED_PACKAGES)}. "
                f"Do not pin transitive libs (glib/X11). Update "
                f"scripts/validate_deploy.py ALLOWED_PACKAGES only after a "
                f"successful Cloud rebuild."
            )
            continue

        packages.append(name)

    if not packages and not errors:
        errors.append(f"{path.name}: no packages listed")

    seen: set[str] = set()
    for p in packages:
        if p in seen:
            errors.append(f"{path.name}: duplicate package {p!r}")
        seen.add(p)

    # Soft requirement: if OCR is part of the app, both leaf packages should exist
    required = {"libgl1", "tesseract-ocr"}
    missing = required - set(packages)
    if packages and missing and not errors:
        errors.append(
            f"{path.name}: missing required OCR packages {sorted(missing)} "
            f"(need libgl1 for RapidOCR, tesseract-ocr for fallback)"
        )

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
        req = line.split(";")[0].strip()
        name = re.split(r"[=<>!~\[]", req, maxsplit=1)[0].strip().lower()
        if name == "streamlit":
            has_streamlit = True
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
            "\nFix packages.txt: only verified leaf packages "
            f"{sorted(ALLOWED_PACKAGES)}, no comments, no transitive libs.\n"
            "See scripts/validate_deploy.py and README Deploy section.",
            file=sys.stderr,
        )
        return 1

    print("Deploy config OK (packages.txt + requirements.txt).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
