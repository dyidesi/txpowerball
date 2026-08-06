"""Load and cache Powerball historical drawing data.

Primary source: New York Open Data CSV (full history, free API).
Secondary source: Texas Lottery powerball.csv (often updates faster after a draw).
Sources are merged by draw date for ticket checks and strategy stats.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

# Current Powerball matrix (in effect since 2015-10-07)
WHITE_MIN, WHITE_MAX = 1, 69
PB_MIN, PB_MAX = 1, 26
WHITE_COUNT = 5
MODERN_ERA_START = datetime(2015, 10, 7)

# 5-column layout for pattern strategy (numbers 1–69 split as evenly as possible)
COLUMN_BOUNDS = [(1, 14), (15, 28), (29, 41), (42, 55), (56, 69)]

# Primary: NY Open Data (Socrata export)
NY_DATA_URL = (
    "https://data.ny.gov/api/v3/views/d6yy-54nr/export.csv?accessType=DOWNLOAD"
)
# Back-compat alias
DATA_URL = NY_DATA_URL

# Secondary: Texas Lottery official download (winning numbers only; often fresher)
TX_CSV_URL = (
    "https://www.texaslottery.com/export/sites/lottery/Games/Powerball/"
    "Winning_Numbers/powerball.csv"
)

DEFAULT_CSV = Path(__file__).resolve().parent.parent / "data" / "powerball_history.csv"

_HTTP_HEADERS = {
    "User-Agent": "txpowerball/1.0 (+https://txpowerball.streamlit.app; history loader)",
    "Accept": "text/csv,application/csv,text/plain,*/*",
}


@dataclass(frozen=True)
class Drawing:
    date: datetime
    whites: tuple[int, ...]  # sorted ascending
    powerball: int
    multiplier: int | None = None

    @property
    def as_set(self) -> frozenset[int]:
        return frozenset(self.whites)

    def pattern(self) -> tuple[int, int, int, int, int]:
        """Column hit counts for the 5 white balls (PawnPower pattern)."""
        counts = [0, 0, 0, 0, 0]
        for n in self.whites:
            for i, (lo, hi) in enumerate(COLUMN_BOUNDS):
                if lo <= n <= hi:
                    counts[i] += 1
                    break
        return tuple(counts)  # type: ignore[return-value]

    def consecutive_pairs(self) -> int:
        return sum(
            1 for a, b in zip(self.whites, self.whites[1:]) if b == a + 1
        )


def column_for(n: int) -> int:
    for i, (lo, hi) in enumerate(COLUMN_BOUNDS):
        if lo <= n <= hi:
            return i
    raise ValueError(f"Number {n} outside 1–69")


def numbers_in_column(col: int) -> list[int]:
    lo, hi = COLUMN_BOUNDS[col]
    return list(range(lo, hi + 1))


def parse_winning_numbers(raw: str) -> tuple[tuple[int, ...], int]:
    parts = [int(x) for x in str(raw).strip().split()]
    if len(parts) != 6:
        raise ValueError(f"Expected 6 numbers, got {parts!r}")
    whites = tuple(sorted(parts[:5]))
    return whites, parts[5]


def _date_key(d: datetime) -> datetime:
    """Normalize to midnight for merge keys."""
    return datetime(d.year, d.month, d.day)


def _parse_frame(df: pd.DataFrame) -> list[Drawing]:
    drawings: list[Drawing] = []
    for _, row in df.iterrows():
        try:
            date = pd.to_datetime(row["Draw Date"]).to_pydatetime()
            whites, pb = parse_winning_numbers(row["Winning Numbers"])
            mult = row.get("Multiplier")
            mult_i = int(mult) if pd.notna(mult) and str(mult).strip() != "" else None
            drawings.append(Drawing(date=date, whites=whites, powerball=pb, multiplier=mult_i))
        except Exception:
            continue
    drawings.sort(key=lambda d: d.date)
    return drawings


def drawings_to_dataframe(drawings: list[Drawing]) -> pd.DataFrame:
    """Serialize drawings in NY Open Data column layout."""
    rows = []
    for d in drawings:
        nums = " ".join(str(n) for n in (*d.whites, d.powerball))
        rows.append(
            {
                "Draw Date": d.date.strftime("%Y-%m-%d"),
                "Winning Numbers": nums,
                "Multiplier": d.multiplier if d.multiplier is not None else "",
            }
        )
    return pd.DataFrame(rows, columns=["Draw Date", "Winning Numbers", "Multiplier"])


def save_drawings(drawings: list[Drawing], path: Path | str = DEFAULT_CSV) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    drawings_to_dataframe(drawings).to_csv(path, index=False)


def load_local(path: Path | str = DEFAULT_CSV) -> list[Drawing]:
    path = Path(path)
    if not path.exists():
        return []
    df = pd.read_csv(path)
    return _parse_frame(df)


def fetch_ny_open_data(
    url: str = NY_DATA_URL,
    *,
    timeout: float = 60,
) -> list[Drawing]:
    """Primary history: New York State open data export."""
    resp = requests.get(url, headers=_HTTP_HEADERS, timeout=timeout)
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text))
    return _parse_frame(df)


def fetch_remote(url: str = NY_DATA_URL, save_to: Path | None = DEFAULT_CSV) -> list[Drawing]:
    """Back-compat: fetch NY open data and optionally write local CSV."""
    drawings = fetch_ny_open_data(url)
    if save_to is not None:
        save_drawings(drawings, save_to)
    return drawings


def fetch_texas_lottery(
    url: str = TX_CSV_URL,
    *,
    timeout: float = 45,
) -> list[Drawing]:
    """
    Secondary history: Texas Lottery Powerball CSV.

    Format (no header row):
      Powerball,month,day,year,w1,w2,w3,w4,w5,powerball,power_play
    """
    resp = requests.get(url, headers=_HTTP_HEADERS, timeout=timeout)
    resp.raise_for_status()
    text = resp.text.strip()
    if not text:
        return []

    drawings: list[Drawing] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 10:
            continue
        # Optional leading game name
        if parts[0].lower().startswith("powerball") and not parts[0].isdigit():
            parts = parts[1:]
        if len(parts) < 9:
            continue
        try:
            month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
            whites_raw = [int(parts[i]) for i in range(3, 8)]
            pb = int(parts[8])
            mult = int(parts[9]) if len(parts) > 9 and parts[9] != "" else None
        except (TypeError, ValueError):
            continue
        if not (1 <= month <= 12 and 1 <= day <= 31 and year >= 1992):
            continue
        if len(set(whites_raw)) != 5:
            continue
        date = datetime(year, month, day)
        drawings.append(
            Drawing(
                date=date,
                whites=tuple(sorted(whites_raw)),
                powerball=pb,
                multiplier=mult,
            )
        )
    drawings.sort(key=lambda d: d.date)
    return drawings


def merge_drawings(
    primary: list[Drawing],
    secondary: list[Drawing],
) -> list[Drawing]:
    """
    Merge by calendar date.

    Primary wins on conflicts (same date, different numbers). Secondary only
    fills dates missing from primary — so Texas can supply tonight's draw while
    NY open data is still catching up.
    """
    by_date: dict[datetime, Drawing] = {}
    for d in primary:
        by_date[_date_key(d.date)] = d
    for d in secondary:
        key = _date_key(d.date)
        if key not in by_date:
            by_date[key] = d
    return [by_date[k] for k in sorted(by_date)]


def _filter_modern(drawings: list[Drawing], modern_only: bool) -> list[Drawing]:
    if not modern_only:
        return drawings
    return [
        d
        for d in drawings
        if d.date >= MODERN_ERA_START
        and all(WHITE_MIN <= w <= WHITE_MAX for w in d.whites)
        and PB_MIN <= d.powerball <= PB_MAX
    ]


def load_drawings(
    prefer_remote: bool = False,
    modern_only: bool = True,
    local_path: Path | str = DEFAULT_CSV,
    *,
    supplement_texas: bool = True,
) -> list[Drawing]:
    """
    Load history from NY open data (primary) and Texas Lottery (secondary).

    - prefer_remote: re-download NY open data (and always try Texas when
      supplement_texas is True).
    - supplement_texas: merge Texas CSV so recent draws missing from NY still
      appear for ticket checks.
    """
    local_path = Path(local_path)
    drawings: list[Drawing] = []
    ny_ok = False

    if prefer_remote:
        try:
            drawings = fetch_ny_open_data()
            ny_ok = True
        except Exception:
            drawings = load_local(local_path)
    else:
        drawings = load_local(local_path)
        if not drawings:
            try:
                drawings = fetch_ny_open_data()
                ny_ok = True
            except Exception:
                drawings = []

    texas: list[Drawing] = []
    if supplement_texas:
        try:
            texas = fetch_texas_lottery()
        except Exception:
            texas = []

    if texas:
        before = len(drawings)
        drawings = merge_drawings(drawings, texas)
        # Persist when we pulled NY or Texas filled gaps
        if ny_ok or len(drawings) > before or prefer_remote:
            try:
                save_drawings(drawings, local_path)
            except Exception:
                pass
    elif ny_ok:
        try:
            save_drawings(drawings, local_path)
        except Exception:
            pass

    # Last resort: local only already tried; if still empty and Texas worked
    if not drawings and texas:
        drawings = texas
        try:
            save_drawings(drawings, local_path)
        except Exception:
            pass

    return _filter_modern(drawings, modern_only)


def white_frequency(drawings: Iterable[Drawing]) -> dict[int, int]:
    freq = {n: 0 for n in range(WHITE_MIN, WHITE_MAX + 1)}
    for d in drawings:
        for w in d.whites:
            if WHITE_MIN <= w <= WHITE_MAX:
                freq[w] += 1
    return freq


def powerball_frequency(drawings: Iterable[Drawing]) -> dict[int, int]:
    freq = {n: 0 for n in range(PB_MIN, PB_MAX + 1)}
    for d in drawings:
        if PB_MIN <= d.powerball <= PB_MAX:
            freq[d.powerball] += 1
    return freq


def last_seen(drawings: list[Drawing]) -> dict[int, int]:
    """Draws since each white ball last appeared (large = colder / more due)."""
    seen: dict[int, int] = {n: len(drawings) for n in range(WHITE_MIN, WHITE_MAX + 1)}
    for i, d in enumerate(drawings):
        for w in d.whites:
            if WHITE_MIN <= w <= WHITE_MAX:
                seen[w] = len(drawings) - 1 - i
    return seen


def short_term_activity(drawings: list[Drawing], window: int = 20) -> dict[int, int]:
    """Hit counts in the most recent `window` drawings."""
    recent = drawings[-window:] if window > 0 else drawings
    return white_frequency(recent)


def pattern_frequency(drawings: Iterable[Drawing]) -> dict[tuple[int, ...], int]:
    freq: dict[tuple[int, ...], int] = {}
    for d in drawings:
        p = d.pattern()
        freq[p] = freq.get(p, 0) + 1
    return freq


def historical_white_sets(drawings: Iterable[Drawing]) -> set[frozenset[int]]:
    return {d.as_set for d in drawings}
