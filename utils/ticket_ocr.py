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


_DATE_PATTERNS = [
    # Draw Date: 08/03/2026  |  8-3-26  |  Aug 3, 2026
    re.compile(
        r"(?:draw\s*date|drawing|for|date)\s*[:\-]?\s*"
        r"(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})",
        re.I,
    ),
    re.compile(
        r"(?:draw\s*date|drawing|for|date)\s*[:\-]?\s*"
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{2,4})",
        re.I,
    ),
    re.compile(r"\b(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})\b"),
    re.compile(
        r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{2,4})\b",
        re.I,
    ),
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
    token = token.strip().replace("-", "/").replace(".", "/")
    # Normalize "Aug 3, 2026" style kept with spaces for strptime
    candidates = [
        token,
        token.replace(",", ""),
    ]
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
    # Restore month-name tokens that used slashes incorrectly
    token2 = token.replace("/", " ")
    for fmt in ("%b %d %Y", "%B %d %Y"):
        try:
            return datetime.strptime(token2, fmt).date()
        except ValueError:
            continue
    return None


def extract_draw_dates(text: str) -> list[date]:
    found: list[date] = []
    seen: set[date] = set()
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text):
            d = _parse_date_token(m.group(1))
            if d is None or d in seen:
                continue
            # Sanity: Powerball modern era window
            if d.year < 2015 or d.year > 2100:
                continue
            seen.add(d)
            found.append(d)
    return found


def _ints_from_line(line: str) -> list[int]:
    # Prefer spaced 1–2 digit tokens; avoid long serials
    tokens = re.findall(r"\b(\d{1,2})\b", line)
    return [int(t) for t in tokens]


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
    # Sometimes OCR reorders; try last as PB, else try if exactly one in 1–26 range among remaining
    if _valid_whites(whites) and _valid_pb(pb):
        return TicketPlay(whites=whites, powerball=pb, label=label, source_line=source)
    # All six sorted, last might not be PB — require original order with last as PB only
    return None


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

    lines = text.replace("\r", "\n").split("\n")
    label_re = re.compile(r"^\s*([A-Ea-e]|[1-5]|Play\s*\d+)\s*[:.\-]?\s+", re.I)

    for raw_line in lines:
        line = raw_line.strip()
        if not line or len(line) < 5:
            continue
        # Skip pure date / price / jackpot lines
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
            )
        ):
            # Still may contain numbers — only skip if no 6-number combo likely
            if len(_ints_from_line(line)) < 6:
                continue

        label = ""
        lm = label_re.match(line)
        if lm:
            label = lm.group(1).upper().replace("PLAY", "P").strip()
            work = line[lm.end() :]
        else:
            work = line

        # Explicit Powerball markers
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

        nums = _ints_from_line(work)
        # Sliding window of 6 consecutive ints
        for i in range(0, max(0, len(nums) - 5)):
            window = nums[i : i + 6]
            add(_play_from_six(window, label, line))

        # 5 whites only lines are incomplete — skip unless PB on same line already handled

    # Whole-text fallback: all ints in reading order, chunk into groups of 6
    if not plays:
        all_nums = _ints_from_line(text)
        for i in range(0, len(all_nums) - 5, 6):
            add(_play_from_six(all_nums[i : i + 6], f"#{len(plays) + 1}", "bulk"))

    return plays


def preprocess_image(img: Image.Image) -> Image.Image:
    """Enhance a photo/scan for OCR of printed lottery tickets."""
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    # Cap huge camera photos
    max_side = 2200
    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    # Upscale small images
    if max(img.size) < 1000:
        img = img.resize((img.size[0] * 2, img.size[1] * 2), Image.Resampling.LANCZOS)

    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray)
    gray = ImageEnhance.Contrast(gray).enhance(1.6)
    gray = ImageEnhance.Sharpness(gray).enhance(1.4)
    gray = gray.filter(ImageFilter.MedianFilter(size=3))
    # Binary-ish for print
    arr = np.asarray(gray).astype(np.float32)
    thr = float(np.median(arr) * 0.92)
    bin_arr = np.where(arr > thr, 255, 0).astype(np.uint8)
    return Image.fromarray(bin_arr, mode="L")


@lru_cache(maxsize=1)
def _get_rapid_ocr():
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def ocr_image(image_bytes: bytes | BinaryIO) -> tuple[str, str]:
    """
    Run OCR on a ticket image.
    Returns (text, engine_name).
    """
    if hasattr(image_bytes, "read"):
        data = image_bytes.read()
    else:
        data = image_bytes

    img = Image.open(io.BytesIO(data))
    img.load()
    variants = [img.convert("RGB"), preprocess_image(img)]

    texts: list[str] = []
    engine = "none"

    # RapidOCR — pure Python, works on Streamlit Cloud without apt packages
    try:
        ocr = _get_rapid_ocr()
        for variant in variants:
            arr = np.asarray(variant.convert("RGB"))
            result, _ = ocr(arr)
            if not result:
                continue
            # result: list of [box, text, score]
            lines = [item[1] for item in result if item and len(item) >= 2 and item[1]]
            if lines:
                texts.append("\n".join(lines))
                engine = "rapidocr"
    except Exception:
        pass

    # Optional Tesseract if installed locally
    if not texts:
        try:
            import pytesseract

            for variant in variants:
                t = pytesseract.image_to_string(variant)
                if t and t.strip():
                    texts.append(t)
                    engine = "tesseract"
        except Exception:
            pass

    if not texts:
        raise RuntimeError(
            "OCR failed. Install rapidocr-onnxruntime (pip) or system tesseract, "
            "and ensure the image is a clear, well-lit photo of the ticket."
        )

    # Prefer the longest extraction (usually most complete)
    best = max(texts, key=lambda s: len(re.findall(r"\d", s)))
    return best, engine


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
    draw_date = dates[0] if dates else None
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
    text, engine = ocr_image(image_bytes)
    return parse_ticket_text(text, engine=engine)


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

    # Ticket might list a slightly off date; pick nearest draw within slack
    nearest: Drawing | None = None
    best_delta = None
    for dd, drawing in normalized.items():
        delta = abs((dd - target).days)
        if best_delta is None or delta < best_delta:
            best_delta = delta
            nearest = drawing

    last_date = max(normalized)
    if target > last_date:
        # Future draw not in history yet
        if nearest and best_delta is not None and best_delta <= max_day_slack:
            return nearest, "nearest"
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
