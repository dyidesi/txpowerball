"""Load and cache Powerball historical drawing data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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

DATA_URL = (
    "https://data.ny.gov/api/v3/views/d6yy-54nr/export.csv?accessType=DOWNLOAD"
)
DEFAULT_CSV = Path(__file__).resolve().parent.parent / "data" / "powerball_history.csv"


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


def load_local(path: Path | str = DEFAULT_CSV) -> list[Drawing]:
    path = Path(path)
    if not path.exists():
        return []
    df = pd.read_csv(path)
    return _parse_frame(df)


def fetch_remote(url: str = DATA_URL, save_to: Path | None = DEFAULT_CSV) -> list[Drawing]:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    from io import StringIO

    df = pd.read_csv(StringIO(resp.text))
    if save_to is not None:
        save_to.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(save_to, index=False)
    return _parse_frame(df)


def load_drawings(
    prefer_remote: bool = False,
    modern_only: bool = True,
    local_path: Path | str = DEFAULT_CSV,
) -> list[Drawing]:
    """Load history. Prefer remote if requested or local file missing."""
    drawings: list[Drawing] = []
    if prefer_remote:
        try:
            drawings = fetch_remote()
        except Exception:
            drawings = load_local(local_path)
    else:
        drawings = load_local(local_path)
        if not drawings:
            drawings = fetch_remote(save_to=Path(local_path))

    if modern_only:
        drawings = [
            d
            for d in drawings
            if d.date >= MODERN_ERA_START
            and all(WHITE_MIN <= w <= WHITE_MAX for w in d.whites)
            and PB_MIN <= d.powerball <= PB_MAX
        ]
    return drawings


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
