"""Guardrails for Streamlit Community Cloud deploy files.

packages.txt is fed to apt-get with no comment support. A single
comment line can take down production (see incident: Cloud treated
'# Streamlit Community Cloud …' as package names).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_deploy import validate_packages_txt, validate_requirements_txt  # noqa: E402


def test_packages_txt_present_and_valid():
    path = ROOT / "packages.txt"
    assert path.is_file(), "packages.txt required for Cloud OCR (libGL, tesseract)"
    errors = validate_packages_txt(path)
    assert errors == [], errors


def test_packages_txt_rejects_comments(tmp_path: Path):
    bad = tmp_path / "packages.txt"
    bad.write_text(
        textwrap.dedent(
            """\
            # Streamlit Community Cloud (Debian apt) — required for OCR
            libgl1
            tesseract-ocr
            """
        ),
        encoding="utf-8",
    )
    errors = validate_packages_txt(bad)
    assert any("comments are NOT allowed" in e for e in errors), errors


def test_packages_txt_rejects_multi_token_prose(tmp_path: Path):
    bad = tmp_path / "packages.txt"
    bad.write_text("libgl1 extra stuff\n", encoding="utf-8")
    errors = validate_packages_txt(bad)
    assert any("exactly one package" in e for e in errors), errors


def test_packages_txt_rejects_invalid_name(tmp_path: Path):
    bad = tmp_path / "packages.txt"
    bad.write_text("NotAPackage!\n", encoding="utf-8")
    errors = validate_packages_txt(bad)
    assert errors, "expected invalid package name to fail"


def test_packages_txt_accepts_clean_list(tmp_path: Path):
    good = tmp_path / "packages.txt"
    good.write_text("libgl1\nlibglib2.0-0\ntesseract-ocr\n", encoding="utf-8")
    assert validate_packages_txt(good) == []


def test_requirements_txt_valid():
    errors = validate_requirements_txt(ROOT / "requirements.txt")
    assert errors == [], errors


def test_requirements_rejects_full_opencv(tmp_path: Path):
    bad = tmp_path / "requirements.txt"
    bad.write_text("streamlit>=1\nopencv-python>=4\n", encoding="utf-8")
    errors = validate_requirements_txt(bad)
    assert any("opencv-python-headless" in e for e in errors), errors


def test_validate_deploy_script_exits_zero():
    script = ROOT / "scripts" / "validate_deploy.py"
    r = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr or r.stdout
