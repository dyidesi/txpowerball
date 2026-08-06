"""OCR lottery tickets and match plays against official Powerball drawings."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from typing import BinaryIO, Sequence

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from utils.data_loader import PB_MAX, PB_MIN, WHITE_MAX, WHITE_MIN, Drawing

# Standard Powerball prize table (no Power Play applied)
PRIZE_TABLE: dict[tuple[int, bool], str] = {
    (5, True): "Jackpot",
    (5, False): "$1,000,000",
    (4, True): "$50,000",
    (4, False): "$100",
    (3, True): "$100",
    (3, False): "$7",
    (2, True): "$7",
    (1, True): "$4",
    (0, True): "$4",
    (2, False): "$0",
    (1, False): "$0",
    (0, False): "$0",
}


@dataclass(frozen=True)
class TicketPlay:
    whites: tuple[int, ...]
    powerball: int
    label: str = ""
    source_line: str = ""

    def display(self) -> str:
        w = "  ".join(f"{n:02d}" for n in self.whites)
        return f"{w}  |  PB {self.powerball:02d}"


@dataclass
class TicketParseResult:
    raw_text: str
    draw_date: date | None
    plays: list[TicketPlay]
    confidence_note: str = ""
    engine: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class PlayMatchResult:
    play: TicketPlay
    white_hits: int
    powerball_hit: bool
    matched_whites: tuple[int, ...]
    prize: str
    tier_label: str


@dataclass
class TicketCheckResult:
    parse: TicketParseResult
    drawing: Drawing | None
    date_status: str  # exact | nearest | missing | future | not_found
    matches: list[PlayMatchResult]
    summary: str


@dataclass
class _OcrToken:
    text: str
    cx: float
    cy: float
    score: float = 1.0


_MONTHS = (
    "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|"
    "January|February|March|April|June|July|August|September|October|November|December"
)

_DATE_PATTERNS = [
    # Draw Date: 08/03/2026  |  8-3-26  |  Aug 3, 2026
    re.compile(
        r"(?:draw\s*date|drawing|for|date|printed\s*on)\s*[:\-]?\s*"
        r"(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})",
        re.I,
    ),
    re.compile(
        r"(?:draw\s*date|drawing|for|date|printed\s*on)\s*[:\-]?\s*"
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{2,4})",
        re.I,
    ),
    # Texas Lottery: WED AUG05 2026 / WED AUG 05 2026 / AUG05 2026
    re.compile(
        rf"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+"
        rf"((?:{_MONTHS})[a-z]*\.?\s*\d{{1,2}},?\s*\d{{2,4}})",
        re.I,
    ),
    re.compile(
        rf"\b((?:{_MONTHS})[a-z]*\.?\s*\d{{1,2}},?\s*\d{{2,4}})\b",
        re.I,
    ),
    re.compile(r"\b(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})\b"),
]


def prize_for(white_hits: int, pb_hit: bool) -> tuple[str, str]:
    prize = PRIZE_TABLE.get((white_hits, pb_hit), "$0")
    if white_hits == 5 and pb_hit:
        tier = "5 + Powerball"
    elif white_hits == 5:
        tier = "5 whites"
    elif pb_hit:
        tier = f"{white_hits} + Powerball"
    else:
        tier = f"{white_hits} whites"
    return prize, tier


def _parse_date_token(token: str) -> date | None:
    token = token.strip()
    # "AUG05 2026" / "AUG052026" → "AUG 05 2026"
    m = re.match(
        r"^([A-Za-z]+)\s*(\d{1,2})[,\s/.-]*(\d{2,4})$",
        token.replace(",", " "),
    )
    if m:
        mon, day, year = m.group(1), m.group(2), m.group(3)
        token = f"{mon} {int(day)} {year}"
    else:
        token = token.replace("-", "/").replace(".", "/")

    candidates = [token, token.replace(",", "")]
    formats = (
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%b %d %Y",
        "%B %d %Y",
        "%b %d, %Y",
        "%B %d, %Y",
    )
    for cand in candidates:
        for fmt in formats:
            try:
                return datetime.strptime(cand, fmt).date()
            except ValueError:
                continue
    token2 = token.replace("/", " ")
    for fmt in ("%b %d %Y", "%B %d %Y"):
        try:
            return datetime.strptime(token2, fmt).date()
        except ValueError:
            continue
    return None


def extract_draw_dates(text: str) -> list[date]:
    # Normalize glued tokens common in OCR: AUG052026 → AUG 05 2026
    text = re.sub(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*(\d{2})(\d{4})\b",
        r"\1 \2 \3",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*(\d{1})(\d{4})\b",
        r"\1 \2 \3",
        text,
        flags=re.I,
    )
    found: list[date] = []
    seen: set[date] = set()
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text):
            d = _parse_date_token(m.group(1))
            if d is None or d in seen:
                continue
            if d.year < 2015 or d.year > 2100:
                continue
            seen.add(d)
            found.append(d)
    return found


def _ints_from_line(line: str) -> list[int]:
    tokens = re.findall(r"\b(\d{1,2})\b", line)
    return [int(t) for t in tokens]


def _pair_digits(blob: str) -> list[int] | None:
    """Split a digit-only blob into 1–2 digit lottery numbers (prefer pairs)."""
    digits = re.sub(r"\D", "", blob)
    if not digits:
        return None
    # Prefer even-length pairing: 0720344960 → 07 20 34 49 60
    if len(digits) % 2 == 0 and 2 <= len(digits) <= 12:
        pairs = [int(digits[i : i + 2]) for i in range(0, len(digits), 2)]
        if all(0 <= n <= 69 for n in pairs):
            return pairs
    # Fallback: sequential 1–2 digit greedy parse left-to-right max 2 digits if ≤69
    out: list[int] = []
    i = 0
    while i < len(digits):
        if i + 1 < len(digits):
            two = int(digits[i : i + 2])
            if WHITE_MIN <= two <= WHITE_MAX or PB_MIN <= two <= PB_MAX:
                # Prefer two digits when valid lottery range
                one = int(digits[i])
                # Prefer two if remaining length stays sensible
                out.append(two)
                i += 2
                continue
        out.append(int(digits[i]))
        i += 1
    return out or None


def _valid_whites(nums: Sequence[int]) -> bool:
    if len(nums) != 5:
        return False
    if len(set(nums)) != 5:
        return False
    return all(WHITE_MIN <= n <= WHITE_MAX for n in nums)


def _valid_pb(n: int) -> bool:
    return PB_MIN <= n <= PB_MAX


def _play_from_six(nums: Sequence[int], label: str, source: str) -> TicketPlay | None:
    if len(nums) != 6:
        return None
    whites = tuple(sorted(nums[:5]))
    pb = nums[5]
    if _valid_whites(whites) and _valid_pb(pb):
        return TicketPlay(whites=whites, powerball=pb, label=label, source_line=source)
    return None


def _play_from_compact(
    blob: str, pb: int | None, label: str, source: str
) -> TicketPlay | None:
    pairs = _pair_digits(blob)
    if not pairs:
        return None
    if len(pairs) == 6 and pb is None:
        return _play_from_six(pairs, label, source)
    if len(pairs) == 5 and pb is not None and _valid_pb(pb) and _valid_whites(pairs):
        return TicketPlay(
            whites=tuple(sorted(pairs)),
            powerball=pb,
            label=label,
            source_line=source,
        )
    if len(pairs) >= 6:
        return _play_from_six(pairs[:6], label, source)
    return None


def extract_labeled_whites(text: str) -> list[tuple[str, tuple[int, ...], str]]:
    """
    Find lettered play rows (A–E) with 5 white balls.
    Handles Texas compact OCR like 'A 0720344960' and 'C.1113354956'.
    """
    found: list[tuple[str, tuple[int, ...], str]] = []
    seen_labels: set[str] = set()

    patterns = [
        # A. 07 20 34 49 60
        re.compile(
            r"\b([A-Ea-e])\s*[.\-:]?\s*"
            r"(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\b",
            re.I,
        ),
        # A 0720344960 / C.1113354956
        re.compile(r"\b([A-Ea-e])\s*[.\-:]?\s*(\d{10})\b", re.I),
        # Label on its own line then compact digits (joined with space from OCR merge)
        re.compile(r"\b([A-Ea-e])\s+(\d{10})\b", re.I),
    ]

    # Also handle OCR where label and digits are on consecutive lines: "A\n0720344960"
    text_join = re.sub(r"([A-Ea-e])\s*[.\-]?\s*\n\s*(\d{10})", r"\1 \2", text)

    for pat in patterns:
        for m in pat.finditer(text_join):
            label = m.group(1).upper()
            if label in seen_labels:
                continue
            if m.lastindex == 2 and len(m.group(2)) == 10:
                pairs = _pair_digits(m.group(2)) or []
            else:
                pairs = [int(m.group(i)) for i in range(2, 7)]
            if len(pairs) != 5 or not _valid_whites(pairs):
                continue
            seen_labels.add(label)
            found.append((label, tuple(sorted(pairs)), m.group(0)))

    # Preserve ticket order A→E
    found.sort(key=lambda x: x[0])
    return found


def extract_pb_column(text: str) -> list[int]:
    """
    Ordered Powerball numbers from a right-column OCR crop or ticket section.
    Prefers clean 1–2 digit tokens in range 1–26.
    """
    pbs: list[int] = []
    # Prefer short tokens only (avoid jackpot odds / serials)
    for line in text.replace("\r", "\n").split("\n"):
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if any(
            k in low
            for k in (
                "powerball",
                "power play",
                "grand",
                "odds",
                "draw",
                "cash",
                "printed",
                "texas",
                "lottery",
            )
        ):
            # Still allow a lone number on a POWERBALL header line
            if re.fullmatch(r"(?i)powerball", line):
                continue
        # Single PB per line (column crop)
        if re.fullmatch(r"\d{1,2}", line):
            n = int(line)
            if _valid_pb(n):
                pbs.append(n)
            continue
        # Spaced list: 03 22 06 20 19
        if re.fullmatch(r"(?:\d{1,2}\s+){1,9}\d{1,2}", line):
            for t in line.split():
                n = int(t)
                if _valid_pb(n):
                    pbs.append(n)
            continue
    # Fallback: all standalone 1–2 digit tokens in PB range (reading order)
    if len(pbs) < 3:
        pbs = []
        for m in re.finditer(r"\b(\d{1,2})\b", text):
            n = int(m.group(1))
            if _valid_pb(n):
                pbs.append(n)
    return pbs


def extract_texas_plays(main_text: str, pb_text: str = "") -> list[TicketPlay]:
    """
    Texas Lottery style: rows A–E of 5 whites + vertical Powerball column.
    Zip labeled whites with ordered PBs from the column crop when available.
    """
    whites_rows = extract_labeled_whites(main_text)
    if not whites_rows:
        return []

    pbs = extract_pb_column(pb_text) if pb_text.strip() else []
    # If column crop empty, try numbers that appear after a POWERBALL header in main text
    if len(pbs) < len(whites_rows):
        # From full ticket gray OCR, PBs often sit as short tokens near the play block
        # Collect candidates that are NOT part of the 10-digit white blobs
        stripped = main_text
        for _, _, src in whites_rows:
            stripped = stripped.replace(src, " ")
        for blob in re.findall(r"\d{8,12}", stripped):
            stripped = stripped.replace(blob, " ")
        # Remove known non-play numbers (draw #, prices)
        stripped = re.sub(r"\$[\d,]+", " ", stripped)
        stripped = re.sub(r"\bDRAW\s*#?\s*\d+\b", " ", stripped, flags=re.I)
        stripped = re.sub(r"\bRET#?\s*[\d-]+\b", " ", stripped, flags=re.I)
        col = extract_pb_column(stripped)
        if len(col) >= len(pbs):
            pbs = col

    plays: list[TicketPlay] = []
    for i, (label, whites, src) in enumerate(whites_rows):
        pb = pbs[i] if i < len(pbs) else None
        if pb is None or not _valid_pb(pb):
            continue
        plays.append(
            TicketPlay(
                whites=whites,
                powerball=pb,
                label=label,
                source_line=f"{src} | PB {pb:02d}",
            )
        )
    return plays


def extract_plays(text: str) -> list[TicketPlay]:
    """Pull Powerball plays (5 whites + PB) from OCR / pasted ticket text."""
    plays: list[TicketPlay] = []
    seen: set[tuple[tuple[int, ...], int]] = set()

    def add(play: TicketPlay | None) -> None:
        if play is None:
            return
        key = (play.whites, play.powerball)
        if key in seen:
            return
        seen.add(key)
        plays.append(play)

    # Texas A–E compact rows first (best signal for state tickets)
    for p in extract_texas_plays(text):
        add(p)
    if len(plays) >= 3:
        return plays

    # Normalize glued letter+digits: C.1113354956 / E.0815496266
    text_n = re.sub(
        r"\b([A-Ea-e])[.\s]*(\d{8,12})\b",
        r"\1. \2",
        text,
    )

    def _space_pairs(m: re.Match[str]) -> str:
        d = m.group(0)
        if len(d) >= 8 and len(d) % 2 == 0:
            return " ".join(d[i : i + 2] for i in range(0, len(d), 2))
        return d

    text_spaced = re.sub(r"\b\d{8,12}\b", _space_pairs, text_n)
    lines = text_spaced.replace("\r", "\n").split("\n")
    label_re = re.compile(r"^\s*([A-Ea-e]|[1-5]|Play\s*\d+)\s*[:.\-]?\s*", re.I)

    # Explicit: 5 whites + PB on one line
    for raw_line in lines:
        line = raw_line.strip()
        if not line or len(line) < 5:
            continue
        low = line.lower()
        if any(
            k in low
            for k in (
                "jackpot",
                "ticket #",
                "serial",
                "retailer",
                "power play",
                "double play",
                "total",
                "price",
                "tax",
                "www.",
                "http",
                "grand prize",
                "cash value",
                "printed",
            )
        ):
            if len(_ints_from_line(line)) < 6:
                continue

        label = ""
        lm = label_re.match(line)
        if lm:
            label = lm.group(1).upper().replace("PLAY", "P").strip()
            work = line[lm.end() :]
        else:
            work = line

        for pat in (
            re.compile(
                r"(?P<w>(?:\d{1,2}\s+){4}\d{1,2})\s*(?:PB|POWERBALL|P/?B|#)?\s*(?P<pb>\d{1,2})\b",
                re.I,
            ),
            re.compile(
                r"(?P<w>\d{1,2}(?:[,\s|/]+\d{1,2}){4})\s*(?:[-|]|PB|POWERBALL)?\s*(?P<pb>\d{1,2})\b",
                re.I,
            ),
        ):
            for m in pat.finditer(work):
                w_nums = [int(x) for x in re.findall(r"\d{1,2}", m.group("w"))]
                pb = int(m.group("pb"))
                if _valid_whites(w_nums) and _valid_pb(pb):
                    add(
                        TicketPlay(
                            whites=tuple(sorted(w_nums)),
                            powerball=pb,
                            label=label,
                            source_line=line,
                        )
                    )

        # Compact 10-digit + trailing PB only (no sliding windows — those invent garbage)
        for blob in re.findall(r"\b\d{10}\b", work):
            trailing = re.findall(r"\b(\d{1,2})\b", work.split(blob, 1)[-1])
            pb = int(trailing[0]) if trailing else None
            if pb is not None:
                add(_play_from_compact(blob, pb, label, line))

        nums = _ints_from_line(work)
        # Only take a full 6-number line (not every sliding window)
        if len(nums) == 6:
            add(_play_from_six(nums, label, line))
        elif len(nums) > 6:
            # single non-overlapping chunks only
            for i in range(0, len(nums) - 5, 6):
                add(_play_from_six(nums[i : i + 6], label, line))

    if not plays:
        all_nums = _ints_from_line(text_spaced)
        for i in range(0, len(all_nums) - 5, 6):
            add(_play_from_six(all_nums[i : i + 6], f"#{len(plays) + 1}", "bulk"))

    return plays


def extract_plays_from_tokens(tokens: list[_OcrToken]) -> list[TicketPlay]:
    """Layout-aware fallback: band tokens and pair left whites with right PB."""
    if not tokens:
        return []

    plays: list[TicketPlay] = []
    seen: set[tuple[tuple[int, ...], int]] = set()

    def add(play: TicketPlay | None) -> None:
        if play is None:
            return
        key = (play.whites, play.powerball)
        if key in seen:
            return
        seen.add(key)
        plays.append(play)

    xs = [t.cx for t in tokens]
    if not xs:
        return []
    x_min, x_max = min(xs), max(xs)
    x_span = max(x_max - x_min, 1.0)
    pb_x_cut = x_min + 0.72 * x_span

    ordered = sorted(tokens, key=lambda t: t.cy)
    bands: list[list[_OcrToken]] = []
    for tok in ordered:
        if not bands:
            bands.append([tok])
            continue
        if abs(tok.cy - bands[-1][0].cy) <= 28:
            bands[-1].append(tok)
        else:
            bands.append([tok])

    label_pat = re.compile(r"^([A-Ea-e])\.?$")
    for band in bands:
        band = sorted(band, key=lambda t: t.cx)
        label = ""
        left_parts: list[str] = []
        right_pbs: list[int] = []
        for tok in band:
            t = tok.text.strip()
            lm = label_pat.match(t)
            if lm and not label:
                label = lm.group(1).upper()
                continue
            cm = re.match(r"^([A-Ea-e])[.\s]*(\d{6,12})$", t, re.I)
            if cm:
                label = label or cm.group(1).upper()
                left_parts.append(cm.group(2))
                continue
            if tok.cx >= pb_x_cut:
                for n in re.findall(r"\b(\d{1,2})\b", t):
                    v = int(n)
                    if _valid_pb(v):
                        right_pbs.append(v)
            else:
                left_parts.append(t)

        nums: list[int] = []
        for part in left_parts:
            if re.fullmatch(r"\d{8,12}", part):
                nums.extend(_pair_digits(part) or [])
            else:
                nums.extend(_ints_from_line(part))

        pb = right_pbs[0] if right_pbs else None
        if len(nums) >= 5 and pb is not None:
            whites = nums[:5]
            if _valid_whites(whites) and _valid_pb(pb):
                add(
                    TicketPlay(
                        whites=tuple(sorted(whites)),
                        powerball=pb,
                        label=label,
                        source_line=f"{label} {' '.join(left_parts)} | {pb}".strip(),
                    )
                )
        elif len(nums) == 6:
            add(_play_from_six(nums, label, " ".join(left_parts)))

    return plays


def preprocess_image(img: Image.Image) -> Image.Image:
    """Enhance a photo/scan for OCR of printed lottery tickets."""
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    max_side = 2200
    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    if max(img.size) < 1000:
        img = img.resize((img.size[0] * 2, img.size[1] * 2), Image.Resampling.LANCZOS)

    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray)
    gray = ImageEnhance.Contrast(gray).enhance(1.8)
    gray = ImageEnhance.Sharpness(gray).enhance(1.5)
    return gray


def _image_variants(img: Image.Image) -> list[tuple[str, Image.Image]]:
    """Generate OCR variants; thermal tickets often read better in grayscale."""
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    # Cap huge camera photos
    max_side = 2400
    w, h = img.size
    base = img
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        base = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

    rgb = base.convert("RGB")
    gray = ImageOps.grayscale(base)
    auto = ImageOps.autocontrast(gray)
    contrast = ImageEnhance.Contrast(auto).enhance(2.0)
    sharp = ImageEnhance.Sharpness(contrast).enhance(1.6)

    variants: list[tuple[str, Image.Image]] = [
        ("rgb", rgb),
        ("gray", gray),
        ("auto", auto),
        ("contrast", sharp),
        ("pre", preprocess_image(base)),
    ]

    # Mid-ticket crop (plays + draw date area) upscaled — helps phone photos
    bw, bh = base.size
    play_box = (int(bw * 0.05), int(bh * 0.35), int(bw * 0.98), int(bh * 0.62))
    play = base.crop(play_box)
    play2 = play.resize((play.size[0] * 2, play.size[1] * 2), Image.Resampling.LANCZOS)
    variants.append(("play_x2", ImageEnhance.Contrast(ImageOps.autocontrast(play2.convert("L"))).enhance(2.0)))

    # Right column (Powerball numbers) heavy upscale
    pb_box = (int(bw * 0.55), int(bh * 0.38), int(bw * 0.98), int(bh * 0.58))
    pb = base.crop(pb_box)
    pb3 = pb.resize((pb.size[0] * 3, pb.size[1] * 3), Image.Resampling.LANCZOS)
    variants.append(("pb_x3", ImageOps.autocontrast(pb3.convert("L"))))

    return variants


@lru_cache(maxsize=1)
def _get_rapid_ocr():
    # Prefer headless OpenCV on Streamlit Cloud (no desktop GUI / libGL).
    # Import order matters: load headless cv2 before RapidOCR pulls opencv-python.
    try:
        import cv2  # noqa: F401 — provided by opencv-python-headless when installed
    except ImportError:
        pass
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def _tokens_from_rapid(result) -> list[_OcrToken]:
    tokens: list[_OcrToken] = []
    if not result:
        return tokens
    for item in result:
        if not item or len(item) < 2:
            continue
        box, text = item[0], item[1]
        if not text or not str(text).strip():
            continue
        score = float(item[2]) if len(item) > 2 else 1.0
        try:
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        except Exception:
            cx, cy = 0.0, 0.0
        tokens.append(_OcrToken(text=str(text).strip(), cx=cx, cy=cy, score=score))
    return tokens


def ocr_image(
    image_bytes: bytes | BinaryIO,
) -> tuple[str, str, list[_OcrToken], str]:
    """
    Run OCR on a ticket image.
    Returns (text, engine_name, layout_tokens, pb_column_text).
    """
    if hasattr(image_bytes, "read"):
        data = image_bytes.read()
    else:
        data = image_bytes

    img = Image.open(io.BytesIO(data))
    img.load()
    # Honor EXIF orientation from phone cameras
    img = ImageOps.exif_transpose(img)

    texts: list[str] = []
    text_by_name: dict[str, str] = {}
    best_tokens: list[_OcrToken] = []
    engine = "none"
    errors: list[str] = []

    # RapidOCR — pure Python, works on Streamlit Cloud without apt packages
    try:
        ocr = _get_rapid_ocr()
        for name, variant in _image_variants(img):
            try:
                arr = np.asarray(variant.convert("RGB"))
                result, _ = ocr(arr)
            except Exception as exc:  # per-variant failure
                errors.append(f"{name}: {exc}")
                continue
            tokens = _tokens_from_rapid(result)
            if not tokens:
                continue
            lines = [t.text for t in tokens]
            blob = "\n".join(lines)
            texts.append(blob)
            text_by_name[name] = blob
            engine = "rapidocr"
            # Prefer full-frame tokens (not crops) for layout
            if name in ("gray", "auto", "rgb", "contrast", "pre"):
                if sum(c.isdigit() for c in blob) >= sum(
                    c.isdigit() for t in best_tokens for c in t.text
                ):
                    best_tokens = tokens
    except Exception as exc:
        errors.append(f"rapidocr: {exc}")

    # Optional Tesseract if installed locally
    if not texts:
        try:
            import pytesseract

            for name, variant in _image_variants(img)[:5]:
                t = pytesseract.image_to_string(variant)
                if t and t.strip():
                    texts.append(t)
                    text_by_name[name] = t
                    engine = "tesseract"
        except Exception as exc:
            errors.append(f"tesseract: {exc}")

    if not texts:
        detail = "; ".join(errors[:3]) if errors else "no text detected"
        raise RuntimeError(
            "OCR failed. Install rapidocr-onnxruntime (pip) or system tesseract, "
            f"and ensure the image is a clear, well-lit photo of the ticket. ({detail})"
        )

    def score_text(s: str) -> tuple[int, int, int]:
        labeled = len(extract_labeled_whites(s))
        plays = len(extract_plays(s))
        digits = len(re.findall(r"\d", s))
        return (labeled, plays, digits)

    best = max(texts, key=score_text)
    # Prefer gray/auto when they expose A–E compact rows
    for preferred in ("gray", "auto", "rgb"):
        if preferred in text_by_name and score_text(text_by_name[preferred]) >= score_text(best):
            best = text_by_name[preferred]
            break

    pb_column_text = text_by_name.get("pb_x3", "") or text_by_name.get("play_x2", "")
    return best, engine, best_tokens, pb_column_text


def parse_ticket_text(text: str, engine: str = "manual") -> TicketParseResult:
    text = (text or "").strip()
    dates = extract_draw_dates(text)
    plays = extract_plays(text)
    warnings: list[str] = []
    if not dates:
        warnings.append("No draw date found on the ticket text.")
    if not plays:
        warnings.append(
            "No complete plays found (need 5 white balls 1–69 + Powerball 1–26)."
        )
    draw_date = None
    if dates:
        draw_date = dates[0]
        # Prefer weekday+month style draw date (Texas tickets) over numeric only
        m = re.search(
            r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+"
            r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*\d{1,2}\s*\d{2,4})",
            text,
            re.I,
        )
        if m:
            d2 = _parse_date_token(m.group(1))
            if d2:
                draw_date = d2
        else:
            m2 = re.search(
                r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*\d{1,2}\s*\d{2,4})\b",
                text,
                re.I,
            )
            if m2:
                d2 = _parse_date_token(m2.group(1))
                if d2:
                    draw_date = d2

    note = (
        f"Parsed {len(plays)} play(s)"
        + (f" for draw date {draw_date.isoformat()}" if draw_date else " (date unknown)")
    )
    return TicketParseResult(
        raw_text=text,
        draw_date=draw_date,
        plays=plays,
        confidence_note=note,
        engine=engine,
        warnings=warnings,
    )


def parse_ticket_image(image_bytes: bytes | BinaryIO) -> TicketParseResult:
    text, engine, tokens, pb_text = ocr_image(image_bytes)
    parse = parse_ticket_text(text, engine=engine)

    # Texas zip: labeled whites from full ticket + PB column crop (most reliable)
    texas = extract_texas_plays(text, pb_text)
    if len(texas) >= 3:
        parse.plays = texas
    else:
        layout_plays = extract_plays_from_tokens(tokens)
        if layout_plays and len(layout_plays) > len(parse.plays):
            parse.plays = layout_plays
        elif texas and len(texas) > len(parse.plays):
            parse.plays = texas

    # Stable A–E order
    parse.plays.sort(
        key=lambda p: (0, p.label) if p.label in "ABCDE" else (1, p.label or "Z")
    )
    parse.confidence_note = (
        f"Parsed {len(parse.plays)} play(s)"
        + (
            f" for draw date {parse.draw_date.isoformat()}"
            if parse.draw_date
            else " (date unknown)"
        )
    )
    parse.warnings = [
        w
        for w in parse.warnings
        if "No complete plays" not in w and "No draw date" not in w
    ]
    if not parse.draw_date:
        parse.warnings.append("No draw date found on the ticket text.")
    if not parse.plays:
        parse.warnings.append(
            "No complete plays found (need 5 white balls 1–69 + Powerball 1–26)."
        )

    return parse


def find_drawing_for_date(
    drawings: Sequence[Drawing],
    target: date,
    *,
    max_day_slack: int = 3,
) -> tuple[Drawing | None, str]:
    """
    Locate the official drawing for a ticket draw date.
    Returns (drawing, status) where status is exact | nearest | future | not_found.
    """
    if not drawings:
        return None, "not_found"

    normalized: dict[date, Drawing] = {}
    for d in drawings:
        dd = d.date.date() if isinstance(d.date, datetime) else d.date
        normalized[dd] = d

    if target in normalized:
        return normalized[target], "exact"

    nearest: Drawing | None = None
    best_delta = None
    for dd, drawing in normalized.items():
        delta = abs((dd - target).days)
        if best_delta is None or delta < best_delta:
            best_delta = delta
            nearest = drawing

    last_date = max(normalized)
    # Ticket for a draw not yet in history — do not score against an older night
    if target > last_date:
        return None, "future"

    if nearest is not None and best_delta is not None and best_delta <= max_day_slack:
        return nearest, "nearest"
    return None, "not_found"


def match_play(play: TicketPlay, drawing: Drawing) -> PlayMatchResult:
    white_set = set(play.whites)
    draw_set = set(drawing.whites)
    matched = tuple(sorted(white_set & draw_set))
    white_hits = len(matched)
    pb_hit = play.powerball == drawing.powerball
    prize, tier = prize_for(white_hits, pb_hit)
    return PlayMatchResult(
        play=play,
        white_hits=white_hits,
        powerball_hit=pb_hit,
        matched_whites=matched,
        prize=prize,
        tier_label=tier,
    )


def check_ticket(
    parse: TicketParseResult,
    drawings: Sequence[Drawing],
    *,
    override_date: date | None = None,
) -> TicketCheckResult:
    target = override_date or parse.draw_date
    if target is None:
        return TicketCheckResult(
            parse=parse,
            drawing=None,
            date_status="missing",
            matches=[],
            summary="Could not determine the draw date. Enter it manually and re-check.",
        )

    drawing, status = find_drawing_for_date(drawings, target)
    if drawing is None:
        if status == "future":
            summary = (
                f"Draw date {target.isoformat()} is not in history yet "
                "(drawing may not have happened or data not refreshed)."
            )
        else:
            summary = f"No official drawing found near {target.isoformat()}."
        return TicketCheckResult(
            parse=parse,
            drawing=None,
            date_status=status,
            matches=[],
            summary=summary,
        )

    matches = [match_play(p, drawing) for p in parse.plays]
    if not matches:
        summary = (
            f"Found official draw for {drawing.date.strftime('%Y-%m-%d')} "
            f"but no plays were parsed from the ticket."
        )
    else:
        winners = [m for m in matches if m.prize != "$0"]
        jackpots = [m for m in matches if m.prize == "Jackpot"]
        if jackpots:
            summary = "🎉 JACKPOT match on at least one play!"
        elif winners:
            best = max(winners, key=lambda m: (m.white_hits, m.powerball_hit))
            summary = (
                f"Winning play(s) found — best tier: {best.tier_label} → {best.prize} "
                f"(draw {drawing.date.strftime('%Y-%m-%d')})."
            )
        else:
            best = max(matches, key=lambda m: (m.white_hits, m.powerball_hit))
            summary = (
                f"No prize on this ticket. Closest: {best.tier_label} "
                f"({best.white_hits} white"
                f"{' + PB' if best.powerball_hit else ''}) on "
                f"{drawing.date.strftime('%Y-%m-%d')}."
            )
        if status == "nearest":
            summary += (
                f" Note: ticket date {target.isoformat()} matched nearest draw "
                f"{drawing.date.strftime('%Y-%m-%d')}."
            )

    return TicketCheckResult(
        parse=parse,
        drawing=drawing,
        date_status=status,
        matches=matches,
        summary=summary,
    )
