"""Multi-ticket Powerball sheet: detect, enhance, OCR, strict parse (no invented plays)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from utils.data_loader import PB_MAX, PB_MIN, WHITE_MAX, WHITE_MIN
from utils.ticket_ocr import (
    TicketPlay,
    extract_plays,
    extract_texas_plays,
)


@dataclass(frozen=True)
class TicketRegion:
    """Axis-aligned ticket crop in original (or working) image coordinates."""

    ticket_id: str
    row: int
    col: int
    x: int
    y: int
    w: int
    h: int
    # scale factor of the working image relative to the original file
    work_scale: float = 1.0

    @property
    def box(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.x + self.w, self.y + self.h)

    def to_original(self) -> tuple[int, int, int, int]:
        s = self.work_scale or 1.0
        return (
            int(round(self.x / s)),
            int(round(self.y / s)),
            int(round(self.w / s)),
            int(round(self.h / s)),
        )


@dataclass
class PlayRecord:
    ticket_id: str
    play_label: str
    whites: list[int]
    powerball: int
    source_line: str
    engine: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TicketScanResult:
    ticket_id: str
    row: int
    col: int
    box_original: tuple[int, int, int, int]
    status: str  # ok | failed | empty
    plays: list[PlayRecord] = field(default_factory=list)
    failure_reason: str = ""
    raw_ocr_snippet: str = ""
    crop_path: str = ""
    engine: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "row": self.row,
            "col": self.col,
            "box_original": list(self.box_original),
            "status": self.status,
            "plays": [p.as_dict() for p in self.plays],
            "failure_reason": self.failure_reason,
            "raw_ocr_snippet": self.raw_ocr_snippet[:500],
            "crop_path": self.crop_path,
            "engine": self.engine,
        }


@dataclass
class SheetScanSummary:
    image_path: str
    image_size: tuple[int, int]
    enhance_scale: float
    tickets_detected: int
    tickets_ok: int
    tickets_failed: int
    plays_extracted: int
    results: list[TicketScanResult] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "image_path": self.image_path,
            "image_size": list(self.image_size),
            "enhance_scale": self.enhance_scale,
            "tickets_detected": self.tickets_detected,
            "tickets_ok": self.tickets_ok,
            "tickets_failed": self.tickets_failed,
            "plays_extracted": self.plays_extracted,
            "results": [r.as_dict() for r in self.results],
        }


def enhance_sheet(
    img: Image.Image,
    *,
    scale: float = 4.0,
    contrast: float = 1.7,
    sharpness: float = 1.8,
) -> Image.Image:
    """
    Increase usable detail for OCR: high-quality upscale + contrast/sharpen.
    Not a no-op; always resamples when scale != 1.
    """
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img = ImageOps.exif_transpose(img)
    w, h = img.size
    if scale != 1.0:
        nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    # Mild denoise then restore edge detail
    img = img.filter(ImageFilter.MedianFilter(size=3))
    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Contrast(img).enhance(contrast)
    img = ImageEnhance.Sharpness(img).enhance(sharpness)
    return img.convert("RGB")


def enhance_ticket_crop(
    crop: Image.Image,
    *,
    min_side: int = 700,
    contrast: float = 2.0,
    sharpness: float = 2.0,
) -> Image.Image:
    """Per-ticket prep: ensure large enough for OCR engines, boost print contrast."""
    if crop.mode not in ("RGB", "L"):
        crop = crop.convert("RGB")
    w, h = crop.size
    m = max(w, h)
    if m < min_side:
        s = min_side / max(m, 1)
        crop = crop.resize(
            (max(1, int(w * s)), max(1, int(h * s))), Image.Resampling.LANCZOS
        )
    gray = ImageOps.grayscale(crop)
    gray = ImageOps.autocontrast(gray, cutoff=2)
    gray = ImageEnhance.Contrast(gray).enhance(contrast)
    gray = ImageEnhance.Sharpness(gray).enhance(sharpness)
    # Unsharp-ish: blend with edge-enhanced version
    gray = gray.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
    return gray.convert("RGB")


def _paper_mask(gray: np.ndarray, thresh: int = 155) -> np.ndarray:
    return gray > thresh


def find_paper_bbox(img: Image.Image) -> tuple[int, int, int, int]:
    """Return (x0, y0, x1, y1) of the main white paper mass (ticket sheet)."""
    gray = np.asarray(ImageOps.grayscale(img))
    paper = _paper_mask(gray)
    # require continuous high-density rows/cols
    row_frac = paper.mean(axis=1)
    col_frac = paper.mean(axis=0)

    def largest_run(frac: np.ndarray, thr: float = 0.25, min_len: int = 20):
        active = frac > thr
        best = (0, 0, 0)
        i, n = 0, len(active)
        while i < n:
            if active[i]:
                j = i
                while j < n and active[j]:
                    j += 1
                if j - i > best[2]:
                    best = (i, j, j - i)
                i = j
            else:
                i += 1
        return best[0], best[1]

    y0, y1 = largest_run(row_frac)
    x0, x1 = largest_run(col_frac)
    if y1 <= y0 or x1 <= x0:
        h, w = gray.shape
        return 0, 0, w, h
    return int(x0), int(y0), int(x1), int(y1)


def estimate_grid(
    img: Image.Image,
    *,
    cols_range: range = range(9, 12),
    rows_range: range = range(9, 12),
    inset: int = 12,
    min_cell_frac: float = 1.0 / 14.0,
) -> tuple[int, int, tuple[int, int, int, int]]:
    """
    Score candidate grids by paper-fill consistency; return (cols, rows, bbox).

    Prefer cell sizes large enough to be whole tickets (not sub-ticket noise).
    Dense Texas sheets in this project are typically ~10×10 tickets.
    """
    gray = np.asarray(ImageOps.grayscale(img))
    paper = _paper_mask(gray)
    x0, y0, x1, y1 = find_paper_bbox(img)
    x0 += inset
    y0 += inset
    x1 -= inset
    y1 -= inset
    if x1 <= x0 or y1 <= y0:
        x0, y0, x1, y1 = find_paper_bbox(img)

    sheet_w = max(1, x1 - x0)
    sheet_h = max(1, y1 - y0)
    min_cell_w = sheet_w * min_cell_frac
    min_cell_h = sheet_h * min_cell_frac

    best: tuple[float, int, int] | None = None
    for nx in cols_range:
        for ny in rows_range:
            cell_w = sheet_w / nx
            cell_h = sheet_h / ny
            if cell_w < min_cell_w or cell_h < min_cell_h:
                continue
            aspect = cell_w / max(cell_h, 1.0)
            if aspect < 0.55 or aspect > 1.45:
                continue
            xs = np.linspace(x0, x1, nx + 1).astype(int)
            ys = np.linspace(y0, y1, ny + 1).astype(int)
            fills: list[float] = []
            for r in range(ny):
                for c in range(nx):
                    cell = paper[ys[r] : ys[r + 1], xs[c] : xs[c + 1]]
                    fills.append(float(cell.mean()) if cell.size else 0.0)
            mean_f = float(np.mean(fills))
            min_f = float(np.min(fills))
            std = float(np.std(fills))
            # Prefer high fill, low std, ticket-like aspect, ~10×10 density
            aspect_score = 1.0 - min(abs(aspect - 0.95), 0.5)
            density_target = abs(nx - 10) + abs(ny - 10)
            score = (
                mean_f
                - 0.5 * std
                + 0.2 * min_f
                + 0.12 * aspect_score
                - 0.01 * density_target
            )
            if best is None or score > best[0]:
                best = (score, nx, ny)

    if best is None:
        return 10, 10, (x0, y0, x1, y1)
    _, nx, ny = best
    return nx, ny, (x0, y0, x1, y1)


def detect_ticket_regions(
    img: Image.Image,
    *,
    work_scale: float = 1.0,
    cols: int | None = None,
    rows: int | None = None,
    min_fill: float = 0.28,
) -> list[TicketRegion]:
    """
    Detect individual ticket rectangles on an enhanced sheet image.
    Uses a scored regular grid over the paper bbox (tickets are abutted).
    Cells with too little paper fill are dropped (floor / missing).
    """
    gray = np.asarray(ImageOps.grayscale(img))
    paper = _paper_mask(gray)

    if cols is None or rows is None:
        nx, ny, bbox = estimate_grid(img)
    else:
        nx, ny = cols, rows
        bbox = find_paper_bbox(img)
        inset = 12
        x0, y0, x1, y1 = bbox
        bbox = (x0 + inset, y0 + inset, x1 - inset, y1 - inset)

    x0, y0, x1, y1 = bbox
    xs = np.linspace(x0, x1, nx + 1).astype(int)
    ys = np.linspace(y0, y1, ny + 1).astype(int)

    regions: list[TicketRegion] = []
    for r in range(ny):
        for c in range(nx):
            xa, xb = int(xs[c]), int(xs[c + 1])
            ya, yb = int(ys[r]), int(ys[r + 1])
            # inset a few percent so borders don't steal the next ticket
            pad_x = max(1, int((xb - xa) * 0.03))
            pad_y = max(1, int((yb - ya) * 0.03))
            xa2, xb2 = xa + pad_x, xb - pad_x
            ya2, yb2 = ya + pad_y, yb - pad_y
            if xb2 <= xa2 or yb2 <= ya2:
                continue
            cell = paper[ya2:yb2, xa2:xb2]
            fill = float(cell.mean()) if cell.size else 0.0
            if fill < min_fill:
                continue
            tid = f"r{r:02d}c{c:02d}"
            regions.append(
                TicketRegion(
                    ticket_id=tid,
                    row=r,
                    col=c,
                    x=xa2,
                    y=ya2,
                    w=xb2 - xa2,
                    h=yb2 - ya2,
                    work_scale=work_scale,
                )
            )
    return regions


def validate_play_numbers(
    whites: Sequence[int], powerball: int
) -> tuple[bool, str]:
    """Strict range/uniqueness check — rejects incomplete or out-of-range sets."""
    w = list(whites)
    if len(w) != 5:
        return False, f"need 5 whites, got {len(w)}"
    if len(set(w)) != 5:
        return False, "duplicate white balls"
    if not all(WHITE_MIN <= n <= WHITE_MAX for n in w):
        return False, f"whites must be {WHITE_MIN}–{WHITE_MAX}"
    if not (PB_MIN <= powerball <= PB_MAX):
        return False, f"powerball must be {PB_MIN}–{PB_MAX}"
    return True, ""


def plays_from_ocr_text(
    text: str,
    *,
    pb_column_text: str = "",
    engine: str = "",
    ticket_id: str = "",
) -> list[PlayRecord]:
    """
    Deterministic parse of OCR text into plays. Never invents numbers:
    only accepted TicketPlay objects from ticket_ocr extractors + validation.
    """
    text = (text or "").strip()
    if not text:
        return []

    candidates: list[TicketPlay] = []
    texas = extract_texas_plays(text, pb_column_text)
    candidates.extend(texas)
    if len(candidates) < 3:
        for p in extract_plays(text):
            if p not in candidates:
                candidates.append(p)

    out: list[PlayRecord] = []
    seen: set[tuple[tuple[int, ...], int]] = set()
    for p in candidates:
        ok, _ = validate_play_numbers(p.whites, p.powerball)
        if not ok:
            continue
        key = (tuple(p.whites), p.powerball)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            PlayRecord(
                ticket_id=ticket_id,
                play_label=p.label or "",
                whites=list(p.whites),
                powerball=int(p.powerball),
                source_line=p.source_line,
                engine=engine,
            )
        )
    # Stable A–E then others
    out.sort(
        key=lambda r: (
            0 if r.play_label in "ABCDE" else 1,
            r.play_label or "Z",
        )
    )
    return out


_RAPID_OCR = None


def _get_sheet_rapid_ocr():
    global _RAPID_OCR
    if _RAPID_OCR is None:
        try:
            import cv2  # noqa: F401
        except ImportError:
            pass
        from rapidocr_onnxruntime import RapidOCR

        _RAPID_OCR = RapidOCR()
    return _RAPID_OCR


def _ocr_crop_fast(crop: Image.Image) -> tuple[str, str, str]:
    """
    Fast per-ticket OCR for sheet scans (few variants, not full ticket_ocr stack).
    Returns (text, engine, pb_column_text). Empty text on failure — never invents digits.
    """
    variants: list[tuple[str, Image.Image]] = [
        ("rgb", crop.convert("RGB")),
        (
            "contrast",
            ImageEnhance.Contrast(
                ImageOps.autocontrast(ImageOps.grayscale(crop))
            )
            .enhance(2.2)
            .convert("RGB"),
        ),
        (
            "sharp",
            ImageEnhance.Sharpness(
                ImageEnhance.Contrast(
                    ImageOps.autocontrast(ImageOps.grayscale(crop))
                ).enhance(2.0)
            )
            .enhance(2.0)
            .convert("RGB"),
        ),
    ]
    # Right ~30% strip often holds Powerball column on TX tickets
    w, h = crop.size
    pb_strip = crop.crop((int(w * 0.62), int(h * 0.30), w, int(h * 0.75)))
    if max(pb_strip.size) < 200:
        pb_strip = pb_strip.resize(
            (pb_strip.size[0] * 3, pb_strip.size[1] * 3), Image.Resampling.LANCZOS
        )
    variants.append(
        (
            "pb_col",
            ImageOps.autocontrast(ImageOps.grayscale(pb_strip)).convert("RGB"),
        )
    )

    texts: list[str] = []
    pb_text = ""
    engine = "none"
    errors: list[str] = []

    try:
        ocr = _get_sheet_rapid_ocr()
        for name, variant in variants:
            try:
                arr = np.asarray(variant.convert("RGB"))
                result, _ = ocr(arr)
            except Exception as exc:
                errors.append(f"{name}:{exc}")
                continue
            if not result:
                continue
            lines = [str(item[1]).strip() for item in result if item and len(item) > 1]
            blob = "\n".join(t for t in lines if t)
            if not blob:
                continue
            engine = "rapidocr"
            if name == "pb_col":
                pb_text = blob
            else:
                texts.append(blob)
    except Exception as exc:
        errors.append(f"rapidocr:{exc}")

    # Optional tesseract fallback when rapidocr yields nothing
    if not texts:
        try:
            import pytesseract

            for name, variant in variants[:3]:
                t = pytesseract.image_to_string(variant)
                if t and t.strip():
                    texts.append(t)
                    engine = "tesseract"
        except Exception as exc:
            errors.append(f"tesseract:{exc}")

    if not texts:
        return "", engine if engine != "none" else "none", pb_text

    def _score(s: str) -> tuple[int, int]:
        return (len(re.findall(r"\d", s)), len(s))

    best = max(texts, key=_score)
    return best, engine, pb_text


def _ocr_crop_bytes(crop: Image.Image) -> tuple[str, str, str]:
    """
    OCR a ticket crop using the fast multi-variant RapidOCR path.

    Sheet scans intentionally skip the full single-ticket ocr_image() stack
    (many heavy variants × 100 tickets is multi-hour). Callers that need the
    deep single-ticket pipeline should use utils.ticket_ocr.parse_ticket_image.
    """
    return _ocr_crop_fast(crop)


def scan_ticket_region(
    work_img: Image.Image,
    region: TicketRegion,
    *,
    save_crop_dir: Path | None = None,
) -> TicketScanResult:
    """OCR one ticket region; mark failed if no valid plays (no invented numbers)."""
    box = region.box
    crop = work_img.crop(box)
    enhanced = enhance_ticket_crop(crop)
    ox, oy, ow, oh = region.to_original()

    crop_path = ""
    if save_crop_dir is not None:
        save_crop_dir.mkdir(parents=True, exist_ok=True)
        dest = save_crop_dir / f"{region.ticket_id}.png"
        enhanced.save(dest)
        crop_path = str(dest)

    text, engine, pb_text = _ocr_crop_bytes(enhanced)
    snippet = re.sub(r"\s+", " ", text).strip()[:200]
    plays = plays_from_ocr_text(
        text, pb_column_text=pb_text, engine=engine, ticket_id=region.ticket_id
    )

    if plays:
        return TicketScanResult(
            ticket_id=region.ticket_id,
            row=region.row,
            col=region.col,
            box_original=(ox, oy, ow, oh),
            status="ok",
            plays=plays,
            failure_reason="",
            raw_ocr_snippet=snippet,
            crop_path=crop_path,
            engine=engine,
        )

    reason = "no_valid_plays"
    if not text.strip():
        reason = "ocr_empty_or_failed"
    elif not any(c.isdigit() for c in text):
        reason = "ocr_no_digits"
    else:
        reason = "ocr_digits_but_no_valid_5plus_pb"

    return TicketScanResult(
        ticket_id=region.ticket_id,
        row=region.row,
        col=region.col,
        box_original=(ox, oy, ow, oh),
        status="failed",
        plays=[],
        failure_reason=reason,
        raw_ocr_snippet=snippet,
        crop_path=crop_path,
        engine=engine,
    )


def scan_sheet(
    image_path: str | Path,
    *,
    enhance_scale: float = 4.0,
    save_crop_dir: Path | None = None,
    cols: int | None = None,
    rows: int | None = None,
    max_tickets: int | None = None,
) -> SheetScanSummary:
    """
    Full pipeline: load → enhance/upscale sheet → detect tickets → per-crop OCR → strict parse.
    """
    path = Path(image_path)
    original = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    work = enhance_sheet(original, scale=enhance_scale)
    regions = detect_ticket_regions(
        work, work_scale=enhance_scale, cols=cols, rows=rows
    )
    if max_tickets is not None:
        regions = regions[: max_tickets]

    results: list[TicketScanResult] = []
    for reg in regions:
        results.append(
            scan_ticket_region(work, reg, save_crop_dir=save_crop_dir)
        )

    ok = [r for r in results if r.status == "ok"]
    failed = [r for r in results if r.status != "ok"]
    plays_n = sum(len(r.plays) for r in results)

    return SheetScanSummary(
        image_path=str(path.resolve()),
        image_size=original.size,
        enhance_scale=enhance_scale,
        tickets_detected=len(results),
        tickets_ok=len(ok),
        tickets_failed=len(failed),
        plays_extracted=plays_n,
        results=results,
    )


def write_results(
    summary: SheetScanSummary,
    *,
    json_path: Path,
    csv_path: Path | None = None,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(summary.as_dict(), indent=2), encoding="utf-8"
    )
    if csv_path is not None:
        lines = [
            "ticket_id,row,col,status,play_label,w1,w2,w3,w4,w5,powerball,failure_reason,engine"
        ]
        for r in summary.results:
            if r.plays:
                for p in r.plays:
                    w = p.whites
                    lines.append(
                        f"{r.ticket_id},{r.row},{r.col},{r.status},"
                        f"{p.play_label},{w[0]},{w[1]},{w[2]},{w[3]},{w[4]},"
                        f"{p.powerball},,{p.engine}"
                    )
            else:
                lines.append(
                    f"{r.ticket_id},{r.row},{r.col},{r.status},,,,,,,"
                    f",{r.failure_reason},{r.engine}"
                )
        csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
