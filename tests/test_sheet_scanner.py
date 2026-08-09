"""Unit tests for multi-ticket sheet scanner pure paths (no invented numbers)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.sheet_scanner import (  # noqa: E402
    detect_ticket_regions,
    enhance_sheet,
    enhance_ticket_crop,
    plays_from_ocr_text,
    validate_play_numbers,
)


# --- validate_play_numbers ---


def test_validate_accepts_legal_play():
    ok, msg = validate_play_numbers([7, 20, 34, 49, 60], 3)
    assert ok is True
    assert msg == ""


def test_validate_rejects_wrong_count():
    ok, msg = validate_play_numbers([1, 2, 3, 4], 5)
    assert ok is False
    assert "5 whites" in msg


def test_validate_rejects_duplicate_whites():
    ok, _ = validate_play_numbers([1, 2, 3, 4, 4], 5)
    assert ok is False


def test_validate_rejects_white_out_of_range():
    ok, _ = validate_play_numbers([1, 2, 3, 4, 70], 5)
    assert ok is False


def test_validate_rejects_pb_out_of_range():
    ok, _ = validate_play_numbers([1, 2, 3, 4, 5], 27)
    assert ok is False


def test_validate_rejects_pb_zero():
    ok, _ = validate_play_numbers([1, 2, 3, 4, 5], 0)
    assert ok is False


# --- plays_from_ocr_text (drives real ticket_ocr extractors) ---


def test_plays_from_texas_compact_ocr_text():
    # Synthetic Texas-style OCR (same shapes ticket_ocr already handles)
    text = """
    TEXAS LOTTERY POWERBALL
    WED AUG 05 2026
    A 0720344960
    B 1113354956
    C 0815496266
    D 0312172944
    E 0209183341
    03
    22
    06
    20
    19
    """
    # PB column as separate crop text
    pb = "03\n22\n06\n20\n19\n"
    plays = plays_from_ocr_text(text, pb_column_text=pb, engine="test", ticket_id="r00c00")
    assert len(plays) >= 3, plays
    for p in plays:
        assert len(p.whites) == 5
        assert all(1 <= w <= 69 for w in p.whites)
        assert 1 <= p.powerball <= 26
        assert p.ticket_id == "r00c00"
    # First labeled play should match A row if present
    by_label = {p.play_label: p for p in plays if p.play_label}
    if "A" in by_label:
        assert by_label["A"].whites == [7, 20, 34, 49, 60]
        assert by_label["A"].powerball == 3


def test_plays_from_spaced_six_numbers():
    text = "Play 1: 05 12 23 45 61 PB 14"
    plays = plays_from_ocr_text(text, engine="test")
    assert len(plays) == 1
    assert plays[0].whites == [5, 12, 23, 45, 61]
    assert plays[0].powerball == 14


def test_plays_rejects_garbage_and_does_not_invent():
    # Incomplete / invalid — must return empty, not fabricated plays
    text = "POWERBALL jackpot $100,000,000 odds 1:292 serial 1234567890"
    plays = plays_from_ocr_text(text)
    assert plays == []


def test_plays_rejects_out_of_range_in_text():
    text = "A 01 02 03 04 99  05"  # 99 invalid white
    plays = plays_from_ocr_text(text)
    # Either empty or only valid complete plays — never includes 99
    for p in plays:
        assert 99 not in p.whites
        assert all(1 <= w <= 69 for w in p.whites)


def test_empty_ocr_text_returns_no_plays():
    assert plays_from_ocr_text("") == []
    assert plays_from_ocr_text("   ") == []


# --- enhance is not a no-op ---


def test_enhance_sheet_increases_resolution():
    img = Image.fromarray(
        np.random.randint(0, 255, (64, 48, 3), dtype=np.uint8), mode="RGB"
    )
    out = enhance_sheet(img, scale=4.0)
    assert out.size == (192, 256)
    assert out.mode == "RGB"


def test_enhance_ticket_crop_upsizes_small_crop():
    img = Image.fromarray(
        np.random.randint(100, 220, (40, 36, 3), dtype=np.uint8), mode="RGB"
    )
    out = enhance_ticket_crop(img, min_side=200)
    assert max(out.size) >= 200


# --- detection on synthetic sheet ---


def test_detect_ticket_regions_on_synthetic_grid():
    # White tickets on dark floor: 3x2 grid
    w, h = 300, 200
    arr = np.full((h, w, 3), 40, dtype=np.uint8)
    # 2 rows x 3 cols white rectangles
    for r in range(2):
        for c in range(3):
            x0 = 20 + c * 90
            y0 = 20 + r * 90
            arr[y0 : y0 + 70, x0 : x0 + 70] = 220
    img = Image.fromarray(arr, mode="RGB")
    regions = detect_ticket_regions(img, work_scale=1.0, cols=3, rows=2, min_fill=0.5)
    assert len(regions) >= 4  # most cells should pass
    ids = {r.ticket_id for r in regions}
    assert any(i.startswith("r00") for i in ids)


def test_real_sheet_image_exists_and_detects_multiple_tickets():
    path = ROOT / "Powerball-2026-08-08.jpg"
    assert path.is_file(), "expected Powerball-2026-08-08.jpg in project root"
    img = Image.open(path).convert("RGB")
    assert img.size[0] > 0 and img.size[1] > 0
    # Light enhance for detection
    work = enhance_sheet(img, scale=2.0, contrast=1.4, sharpness=1.4)
    regions = detect_ticket_regions(work, work_scale=2.0)
    assert len(regions) > 1, f"expected multi-ticket grid, got {len(regions)}"
