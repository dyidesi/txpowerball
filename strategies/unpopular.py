"""Unpopular / anti-share number selection.

Does not change jackpot odds. Reduces the chance of splitting a jackpot by
avoiding combinations humans over-pick: birthday ranges (1–31), arithmetic
sequences, visual clusters, same last digits, and "lucky" low sets.
"""

from __future__ import annotations

from collections import Counter

from strategies.base import (
    Strategy,
    Pick,
    PickResult,
    consecutive_pair_count,
    max_consecutive_run,
    is_historical_match,
    spread_ok,
)
from utils.data_loader import WHITE_MAX, WHITE_MIN, PB_MAX, PB_MIN, historical_white_sets


# Numbers players over-choose as "lucky" / calendar defaults (soft avoid as a set).
POPULAR_LUCKY = {3, 7, 11, 13, 17, 21, 22, 23, 27}


def count_low(whites: list[int], cutoff: int = 31) -> int:
    return sum(1 for n in whites if n <= cutoff)


def is_arithmetic(whites: list[int]) -> bool:
    s = sorted(whites)
    if len(s) < 3:
        return False
    d = s[1] - s[0]
    if d <= 0:
        return False
    return all(s[i + 1] - s[i] == d for i in range(len(s) - 1))


def max_same_ending(whites: list[int]) -> int:
    return max(Counter(n % 10 for n in whites).values())


def is_multiples_cluster(whites: list[int]) -> bool:
    """All multiples of 5 or 10 — common visual playslip patterns."""
    if all(n % 10 == 0 for n in whites):
        return True
    if all(n % 5 == 0 for n in whites):
        return True
    return False


def popular_lucky_count(whites: list[int]) -> int:
    return sum(1 for n in whites if n in POPULAR_LUCKY)


def unpopular_ok(
    whites: list[int],
    history,
    *,
    max_low: int = 2,
    max_ending: int = 2,
    max_lucky: int = 2,
    max_pairs: int = 1,
    max_run: int = 2,
) -> bool:
    s = sorted(whites)
    if len(set(s)) != 5:
        return False
    if count_low(s) > max_low:
        return False
    if is_arithmetic(s):
        return False
    if max_same_ending(s) > max_ending:
        return False
    if is_multiples_cluster(s):
        return False
    if popular_lucky_count(s) > max_lucky:
        return False
    if consecutive_pair_count(s) > max_pairs:
        return False
    if max_consecutive_run(s) > max_run:
        return False
    if not spread_ok(s, min_span=25):
        return False
    if is_historical_match(s, history):
        return False
    return True


def unpopular_score(whites: list[int]) -> float:
    """Higher = less likely to be a popular human pick (heuristic)."""
    s = sorted(whites)
    high = sum(1 for n in s if n > 31)
    very_high = sum(1 for n in s if n > 50)
    endings = len({n % 10 for n in s})
    span = s[-1] - s[0]
    lucky_pen = popular_lucky_count(s) * 2.0
    low_pen = count_low(s) * 1.5
    return high * 3.0 + very_high * 1.5 + endings * 1.2 + span * 0.05 - lucky_pen - low_pen


def pick_unpopular_powerball(rng) -> int:
    """Prefer mid/high PB; still full 1–26 range for fairness."""
    # Weight: slight tilt away from single-digit "favorite" balls.
    weights = []
    nums = list(range(PB_MIN, PB_MAX + 1))
    for n in nums:
        w = 1.0
        if n <= 9:
            w = 0.55
        elif n in (11, 13, 17, 21):
            w = 0.7
        else:
            w = 1.25
        weights.append(w)
    return rng.choices(nums, weights=weights, k=1)[0]


class UnpopularStrategy(Strategy):
    name = "Unpopular (Anti-Share)"
    description = (
        "Picks combinations people tend to avoid: at least 3 whites above 31, "
        "no arithmetic sequences, diverse last digits, no all-multiples patterns. "
        "Same win odds — lower chance of splitting a jackpot if you hit."
    )

    def generate(self, n_picks: int = 5) -> PickResult:
        hist = historical_white_sets(self.drawings)
        # Prefer sampling from the full range but bias toward >31.
        high_pool = list(range(32, WHITE_MAX + 1))  # 32–69
        low_pool = list(range(WHITE_MIN, 32))  # 1–31
        # Soft de-weight popular lucky lows
        low_weights = [0.4 if n in POPULAR_LUCKY else 1.0 for n in low_pool]
        high_weights = [1.0 + (0.3 if n > 50 else 0.0) for n in high_pool]

        raw_picks: list[Pick] = []
        used: set[frozenset[int]] = set()
        attempts = 0
        max_attempts = n_picks * 200

        while len(raw_picks) < n_picks and attempts < max_attempts:
            attempts += 1
            # 3–4 highs, rest lows (birthday-light)
            n_high = self.rng.choice([3, 3, 4, 4, 5])
            n_low = 5 - n_high
            if n_high > len(high_pool):
                n_high = 5
                n_low = 0
            highs = self.rng.choices(high_pool, weights=high_weights, k=n_high * 3)
            highs = list(dict.fromkeys(highs))[:n_high]
            while len(highs) < n_high:
                c = self.rng.choice(high_pool)
                if c not in highs:
                    highs.append(c)
            lows: list[int] = []
            if n_low:
                lows = self.rng.choices(low_pool, weights=low_weights, k=n_low * 4)
                lows = [x for x in dict.fromkeys(lows) if x not in highs][:n_low]
                while len(lows) < n_low:
                    c = self.rng.choices(low_pool, weights=low_weights, k=1)[0]
                    if c not in lows and c not in highs:
                        lows.append(c)
            whites = sorted(highs + lows)
            if len(set(whites)) != 5:
                continue
            if frozenset(whites) in used:
                continue
            if not unpopular_ok(whites, self.drawings):
                continue
            pb = pick_unpopular_powerball(self.rng)
            score = unpopular_score(whites)
            notes = [
                "Anti-share filters: ≤2 numbers from 1–31 (birthday range)",
                "Rejected arithmetic sequences, multiples clusters, exact past white sets",
                f"Highs (>31): {sum(1 for n in whites if n > 31)}/5 · "
                f"distinct endings: {len({n % 10 for n in whites})} · span {whites[-1]-whites[0]}",
                "Same jackpot odds as any ticket; lowers co-winner risk if you hit",
            ]
            used.add(frozenset(whites))
            raw_picks.append(
                Pick(
                    whites=tuple(whites),
                    powerball=pb,
                    strategy=self.name,
                    notes=notes,
                    score=score,
                )
            )

        # Fallback: pure high-biased sample with relaxed filters
        while len(raw_picks) < n_picks:
            n_high = min(4, 5)
            highs = self.rng.sample(high_pool, n_high)
            lows = self.rng.sample(low_pool, 5 - n_high) if n_high < 5 else []
            whites = sorted(highs + lows)
            if frozenset(whites) in used or frozenset(whites) in hist:
                continue
            if is_arithmetic(whites) or count_low(whites) > 2:
                continue
            used.add(frozenset(whites))
            raw_picks.append(
                Pick(
                    whites=tuple(whites),
                    powerball=pick_unpopular_powerball(self.rng),
                    strategy=self.name,
                    notes=["Relaxed anti-share fallback"],
                    score=unpopular_score(whites),
                )
            )

        analysis = {
            "rules": [
                "At most 2 white balls from 1–31 (calendar/birthday band)",
                "At least 3 whites from 32–69",
                "No constant-step arithmetic sequences (e.g. 5-10-15-20-25)",
                "No all multiples of 5 or 10 (visual playslip patterns)",
                "Max 2 balls sharing the same last digit",
                "Max 2 'lucky' popular numbers (3,7,11,13,17,21–23,27)",
                "≤1 consecutive pair; span ≥25; never exact historical white set",
                "Powerball tilted away from single-digit favorites",
            ],
            "why_this_matters": (
                "Does not improve odds of winning. If you win the jackpot, uncommon "
                "combinations are less likely to be shared with other players who "
                "picked birthdays or simple sequences."
            ),
            "max_low_allowed": 2,
            "attempts_used": attempts,
        }
        explanation = (
            "Unpopular (Anti-Share) builds tickets people rarely choose: mostly "
            "numbers above 31, no birthday-heavy sets, no arithmetic sequences or "
            "visual multiples patterns. Odds of hitting are unchanged; expected "
            "share of a jackpot improves if you do hit."
        )
        return PickResult(
            picks=raw_picks[:n_picks],
            strategy_name=self.name,
            explanation=explanation,
            analysis=analysis,
            cost_usd=n_picks * 2.0,
            plays=n_picks,
        )
