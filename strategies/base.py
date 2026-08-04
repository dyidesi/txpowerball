"""Shared types and helpers for pick generation."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Sequence

from utils.data_loader import (
    PB_MAX,
    PB_MIN,
    WHITE_MAX,
    WHITE_MIN,
    Drawing,
    column_for,
    historical_white_sets,
    powerball_frequency,
)


@dataclass
class Pick:
    whites: tuple[int, ...]  # sorted
    powerball: int
    strategy: str
    notes: list[str] = field(default_factory=list)
    score: float = 0.0

    def display(self) -> str:
        w = "  ".join(f"{n:02d}" for n in self.whites)
        return f"{w}  |  PB {self.powerball:02d}"

    def as_set(self) -> frozenset[int]:
        return frozenset(self.whites)


@dataclass
class PickResult:
    picks: list[Pick]
    strategy_name: str
    explanation: str
    analysis: dict = field(default_factory=dict)
    cost_usd: float = 10.0
    plays: int = 5


def consecutive_pair_count(whites: Sequence[int]) -> int:
    s = sorted(whites)
    return sum(1 for a, b in zip(s, s[1:]) if b == a + 1)


def max_consecutive_run(whites: Sequence[int]) -> int:
    s = sorted(whites)
    if not s:
        return 0
    best = cur = 1
    for a, b in zip(s, s[1:]):
        if b == a + 1:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best


def spread_ok(whites: Sequence[int], min_span: int = 20) -> bool:
    s = sorted(whites)
    return (s[-1] - s[0]) >= min_span


def odd_even_count(whites: Sequence[int]) -> tuple[int, int]:
    odds = sum(1 for n in whites if n % 2)
    return odds, len(whites) - odds


def high_low_count(whites: Sequence[int], midpoint: int = 35) -> tuple[int, int]:
    low = sum(1 for n in whites if n <= midpoint)
    return low, len(whites) - low


def is_historical_match(whites: Sequence[int], history: list[Drawing]) -> bool:
    s = frozenset(whites)
    return s in historical_white_sets(history)


def weighted_choice(weights: dict[int, float], rng: random.Random, exclude: set[int] | None = None) -> int:
    exclude = exclude or set()
    items = [(k, max(w, 0.0)) for k, w in weights.items() if k not in exclude and w > 0]
    if not items:
        pool = [k for k in weights if k not in exclude]
        if not pool:
            pool = list(range(WHITE_MIN, WHITE_MAX + 1))
            pool = [k for k in pool if k not in exclude]
        return rng.choice(pool)
    nums, ws = zip(*items)
    return rng.choices(list(nums), weights=list(ws), k=1)[0]


def pick_powerball(
    drawings: list[Drawing],
    rng: random.Random,
    mode: str = "due",
) -> int:
    """Pick a Powerball: due (cold), hot, or pure random."""
    freq = powerball_frequency(drawings)
    total = max(sum(freq.values()), 1)
    if mode == "random":
        return rng.randint(PB_MIN, PB_MAX)
    if mode == "hot":
        weights = {n: freq[n] + 1 for n in range(PB_MIN, PB_MAX + 1)}
    else:  # due / cold
        weights = {n: (total - freq[n] + 1) for n in range(PB_MIN, PB_MAX + 1)}
    return weighted_choice(weights, rng)


def enforce_constraints(
    whites: list[int],
    history: list[Drawing],
    rng: random.Random,
    max_consec_run: int = 2,
    max_pairs: int = 2,
    avoid_history: bool = True,
    max_attempts: int = 50,
) -> list[int]:
    """Repair a 5-number set until constraints hold or attempts exhausted."""
    candidate = sorted(set(whites))
    # pad if short
    while len(candidate) < 5:
        n = rng.randint(WHITE_MIN, WHITE_MAX)
        if n not in candidate:
            candidate.append(n)
            candidate.sort()
    candidate = candidate[:5]

    for _ in range(max_attempts):
        ok = (
            max_consecutive_run(candidate) <= max_consec_run
            and consecutive_pair_count(candidate) <= max_pairs
            and len(set(candidate)) == 5
            and (not avoid_history or not is_historical_match(candidate, history))
            and spread_ok(candidate, min_span=15)
        )
        if ok:
            return sorted(candidate)
        # mutate one number
        idx = rng.randrange(5)
        for __ in range(20):
            n = rng.randint(WHITE_MIN, WHITE_MAX)
            if n not in candidate:
                candidate[idx] = n
                candidate = sorted(candidate)
                break
    return sorted(candidate)


class Strategy(ABC):
    name: str = "Base"
    description: str = ""

    def __init__(self, drawings: list[Drawing], seed: int | None = None):
        self.drawings = drawings
        self.rng = random.Random(seed)

    @abstractmethod
    def generate(self, n_picks: int = 5) -> PickResult:
        ...

    def _finalize(
        self,
        raw_picks: list[tuple[list[int], int, list[str], float]],
        explanation: str,
        analysis: dict | None = None,
        n_picks: int = 5,
    ) -> PickResult:
        picks: list[Pick] = []
        used: set[frozenset[int]] = set()
        for whites, pb, notes, score in raw_picks:
            fixed = enforce_constraints(whites, self.drawings, self.rng)
            key = frozenset(fixed)
            if key in used:
                # reshuffle slightly for uniqueness among this batch
                for _ in range(30):
                    alt = list(fixed)
                    i = self.rng.randrange(5)
                    for __ in range(20):
                        n = self.rng.randint(WHITE_MIN, WHITE_MAX)
                        if n not in alt:
                            alt[i] = n
                            break
                    alt = enforce_constraints(alt, self.drawings, self.rng)
                    if frozenset(alt) not in used:
                        fixed = alt
                        break
            used.add(frozenset(fixed))
            picks.append(
                Pick(
                    whites=tuple(sorted(fixed)),
                    powerball=pb,
                    strategy=self.name,
                    notes=notes,
                    score=score,
                )
            )
            if len(picks) >= n_picks:
                break

        while len(picks) < n_picks:
            whites = sorted(self.rng.sample(range(WHITE_MIN, WHITE_MAX + 1), 5))
            whites = enforce_constraints(whites, self.drawings, self.rng)
            if frozenset(whites) in used:
                continue
            used.add(frozenset(whites))
            picks.append(
                Pick(
                    whites=tuple(whites),
                    powerball=pick_powerball(self.drawings, self.rng),
                    strategy=self.name,
                    notes=["Fallback fill to reach ticket count"],
                    score=0.0,
                )
            )

        return PickResult(
            picks=picks[:n_picks],
            strategy_name=self.name,
            explanation=explanation,
            analysis=analysis or {},
            cost_usd=n_picks * 2.0,
            plays=n_picks,
        )
