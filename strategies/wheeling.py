"""Abbreviated number wheel for a fixed multi-ticket budget.

A wheel does not raise the odds of any single line. It spreads a chosen pool
of white numbers across several tickets so partial hits cover more prize tiers
with less accidental overlap than independent random tickets.

Default design for $10 (5 × $2): pool of 7 whites → 5 covering 5-number lines
chosen by greedy pair-coverage.
"""

from __future__ import annotations

from itertools import combinations

from strategies.base import Strategy, Pick, PickResult, is_historical_match
from strategies.unpopular import (
    unpopular_ok,
    unpopular_score,
    pick_unpopular_powerball,
    count_low,
    is_arithmetic,
    POPULAR_LUCKY,
)
from utils.data_loader import (
    WHITE_MAX,
    WHITE_MIN,
    white_frequency,
    last_seen,
    historical_white_sets,
)


def pool_size_for_plays(n_plays: int) -> int:
    """Map ticket count to a practical pool size for abbreviated wheels."""
    if n_plays <= 2:
        return 6
    if n_plays <= 5:
        return 7
    if n_plays <= 8:
        return 8
    return min(10, 5 + n_plays // 3)


def all_five_subsets(pool: list[int]) -> list[tuple[int, ...]]:
    return [tuple(sorted(c)) for c in combinations(sorted(pool), 5)]


def pair_set(combo: tuple[int, ...]) -> set[tuple[int, int]]:
    return set(combinations(combo, 2))


def select_covering_lines(
    pool: list[int],
    n_lines: int,
    rng,
) -> list[tuple[int, ...]]:
    """Greedy abbreviated wheel: maximize newly covered pairs each step."""
    combos = all_five_subsets(pool)
    if not combos:
        return []
    if len(combos) <= n_lines:
        rng.shuffle(combos)
        return combos

    remaining = combos[:]
    rng.shuffle(remaining)
    selected: list[tuple[int, ...]] = []
    covered: set[tuple[int, int]] = set()

    for _ in range(n_lines):
        best = None
        best_new = -1
        best_tie = -1.0
        for combo in remaining:
            pairs = pair_set(combo)
            new = len(pairs - covered)
            # Tie-break: prefer higher average number (mild anti-share)
            tie = sum(combo) / 5.0
            if new > best_new or (new == best_new and tie > best_tie):
                best_new = new
                best_tie = tie
                best = combo
        if best is None:
            break
        selected.append(best)
        covered |= pair_set(best)
        remaining.remove(best)

    return selected


def coverage_stats(pool: list[int], lines: list[tuple[int, ...]]) -> dict:
    all_pairs = set(combinations(sorted(pool), 2))
    covered = set()
    for line in lines:
        covered |= pair_set(line)
    # How many pool numbers appear at least once
    used = set()
    for line in lines:
        used |= set(line)
    # Triple coverage (for lower-tier intuition)
    all_triples = set(combinations(sorted(pool), 3))
    covered_t = set()
    for line in lines:
        covered_t |= set(combinations(line, 3))
    return {
        "pool_size": len(pool),
        "lines": len(lines),
        "pairs_total": len(all_pairs),
        "pairs_covered": len(covered),
        "pair_coverage_pct": round(100.0 * len(covered) / max(len(all_pairs), 1), 1),
        "triples_total": len(all_triples),
        "triples_covered": len(covered_t),
        "triple_coverage_pct": round(100.0 * len(covered_t) / max(len(all_triples), 1), 1),
        "pool_numbers_used": len(used),
        "full_wheel_lines": len(all_five_subsets(pool)),
    }


class WheelingStrategy(Strategy):
    name = "Wheel ($10 Coverage)"
    description = (
        "Abbreviated wheel for a multi-ticket budget: builds an unpopular-leaning "
        "pool of white numbers, then spreads them across your plays with greedy "
        "pair coverage. Optimizes structure of $10 (or your budget), not prediction."
    )

    def _build_pool(self, size: int) -> list[int]:
        """Unpopular-leaning pool: mostly high numbers, some due/cold spice."""
        freq = white_frequency(self.drawings)
        cold = last_seen(self.drawings)
        n_draws = max(len(self.drawings), 1)
        expected = (n_draws * 5) / 69.0

        high = list(range(32, WHITE_MAX + 1))
        low = list(range(WHITE_MIN, 32))

        # Score candidates: high + overdue + not overplayed lucky
        def score(n: int) -> float:
            s = 0.0
            if n > 31:
                s += 4.0
            if n > 50:
                s += 1.5
            if n in POPULAR_LUCKY:
                s -= 2.5
            s += max(0.0, expected - freq[n]) * 0.15
            s += cold[n] * 0.05
            s += self.rng.random() * 0.8  # jitter so pool rotates
            return s

        # Target mix: ~5 high + rest low for pool of 7
        n_high = min(size, max(4, size - 2))
        n_low = size - n_high

        high_ranked = sorted(high, key=score, reverse=True)
        low_ranked = sorted(low, key=score, reverse=True)

        pool = high_ranked[:n_high] + low_ranked[:n_low]
        # Ensure uniqueness and fill if short
        pool = list(dict.fromkeys(pool))
        candidates = sorted(range(WHITE_MIN, WHITE_MAX + 1), key=score, reverse=True)
        for n in candidates:
            if len(pool) >= size:
                break
            if n not in pool:
                pool.append(n)

        # Prefer pools that are not birthday-heavy overall
        for _ in range(40):
            if count_low(pool) <= max(2, size // 3) and not is_arithmetic(sorted(pool)[:5]):
                break
            # swap a low for a high
            lows_in = [n for n in pool if n <= 31]
            highs_out = [n for n in high if n not in pool]
            if not lows_in or not highs_out:
                break
            pool.remove(self.rng.choice(lows_in))
            pool.append(self.rng.choice(highs_out))

        return sorted(pool[:size])

    def generate(self, n_picks: int = 5) -> PickResult:
        size = pool_size_for_plays(n_picks)
        # Prefer a pool that admits at least one unpopular 5-set
        pool = self._build_pool(size)
        for _ in range(25):
            subsets = all_five_subsets(pool)
            good = [c for c in subsets if unpopular_ok(list(c), self.drawings, max_low=3)]
            if len(good) >= n_picks or len(subsets) <= n_picks:
                break
            pool = self._build_pool(size)

        lines = select_covering_lines(pool, n_picks, self.rng)
        # Prefer lines that pass anti-share when possible, but keep coverage order
        ranked = sorted(
            lines,
            key=lambda c: (
                1 if unpopular_ok(list(c), self.drawings, max_low=3) else 0,
                unpopular_score(list(c)),
            ),
            reverse=True,
        )
        # Re-run coverage on full set (ranked only for PB/notes preference later)
        lines = select_covering_lines(pool, n_picks, self.rng)

        hist = historical_white_sets(self.drawings)
        # Distinct Powerballs across lines when possible
        pbs_used: set[int] = set()
        picks: list[Pick] = []
        stats = coverage_stats(pool, lines)

        for i, combo in enumerate(lines):
            whites = list(combo)
            # Skip exact historical full white sets if possible by swapping within pool
            if is_historical_match(whites, self.drawings):
                for alt in all_five_subsets(pool):
                    if alt not in lines and not is_historical_match(list(alt), self.drawings):
                        # only swap if we still have room — rare
                        whites = list(alt)
                        break

            pb = pick_unpopular_powerball(self.rng)
            for _ in range(15):
                if pb not in pbs_used or len(pbs_used) >= 26:
                    break
                pb = pick_unpopular_powerball(self.rng)
            pbs_used.add(pb)

            anti = unpopular_ok(whites, self.drawings, max_low=3)
            notes = [
                f"Wheel pool ({size}): {' '.join(f'{n:02d}' for n in pool)}",
                f"Abbreviated coverage line {i+1}/{len(lines)} "
                f"(full wheel would be {stats['full_wheel_lines']} lines)",
                f"Pair coverage so far target: {stats['pair_coverage_pct']}% of pool pairs",
                "Anti-share friendly line" if anti else "Coverage priority over strict anti-share",
                "Wheeling does not change jackpot odds — it structures multi-ticket spend",
            ]
            picks.append(
                Pick(
                    whites=tuple(sorted(whites)),
                    powerball=pb,
                    strategy=self.name,
                    notes=notes,
                    score=float(stats["pair_coverage_pct"]) + unpopular_score(whites) * 0.1,
                )
            )

        # Fill if pool too small edge case
        while len(picks) < n_picks:
            filler = sorted(self.rng.sample(range(WHITE_MIN, WHITE_MAX + 1), 5))
            if frozenset(filler) in hist:
                continue
            picks.append(
                Pick(
                    whites=tuple(filler),
                    powerball=pick_unpopular_powerball(self.rng),
                    strategy=self.name,
                    notes=["Fallback line outside wheel"],
                    score=0.0,
                )
            )

        analysis = {
            "rules": [
                f"Build a {size}-number white pool (unpopular-leaning: mostly >31)",
                f"Play {n_picks} of C({size},5)={stats['full_wheel_lines']} possible 5-sets",
                "Greedy selection maximizes new pool-pairs covered each line",
                "Rotate Powerballs across tickets",
                "Same per-line odds as any ticket; better structured coverage of the pool",
            ],
            "pool": pool,
            "coverage": stats,
            "why_this_matters": (
                "If several of your pool numbers hit, an abbreviated wheel is more likely "
                "to produce multiple lower-tier wins than 5 disjoint random tickets. "
                "It does not make the jackpot more likely per dollar spent."
            ),
            "budget_note": (
                f"{n_picks} plays × $2 = ${n_picks * 2:.0f}. "
                f"A full wheel of this pool needs {stats['full_wheel_lines']} lines "
                f"(${stats['full_wheel_lines'] * 2:.0f})."
            ),
        }
        explanation = (
            f"Wheel ($10 Coverage) picks a {size}-number pool "
            f"[{' '.join(f'{n:02d}' for n in pool)}] and spreads it across "
            f"{len(picks)} tickets with greedy pair coverage "
            f"({stats['pair_coverage_pct']}% of pool pairs, "
            f"{stats['triple_coverage_pct']}% of pool triples). "
            f"Full wheel would need {stats['full_wheel_lines']} lines."
        )
        return PickResult(
            picks=picks[:n_picks],
            strategy_name=self.name,
            explanation=explanation,
            analysis=analysis,
            cost_usd=n_picks * 2.0,
            plays=n_picks,
        )
