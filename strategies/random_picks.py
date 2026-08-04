"""Random Picks with optional pattern constraint and history de-dup.

PawnPower Random module: pure RNG is fine (drawings are random), but you can
filter for pattern quality, consecutives, and never replaying an exact past
winning white set. Better mode: constrain RNG to a frequent 5-column pattern.
"""

from __future__ import annotations

from strategies.base import Strategy, PickResult, pick_powerball, consecutive_pair_count
from strategies.patterns import all_patterns_summing_to_five
from utils.data_loader import (
    WHITE_MAX,
    WHITE_MIN,
    numbers_in_column,
    pattern_frequency,
    historical_white_sets,
)


class RandomPicksStrategy(Strategy):
    name = "Random (Pattern-Constrained)"
    description = (
        "Slot-machine style random generation constrained to historically frequent "
        "5-column patterns, with consecutive and history filters."
    )

    def generate(self, n_picks: int = 5) -> PickResult:
        freq = pattern_frequency(self.drawings)
        for p in all_patterns_summing_to_five():
            freq.setdefault(p, 0)
        # Use top ~21 patterns as templates (PawnPower 17% insight)
        top = sorted(freq.items(), key=lambda x: -x[1])[:21]
        patterns = [p for p, c in top if c > 0] or [p for p, _ in top]
        pweights = [max(freq[p], 1) for p in patterns]
        hist = historical_white_sets(self.drawings)

        raw = []
        for _ in range(n_picks * 40):
            if len(raw) >= n_picks:
                break
            pattern = self.rng.choices(patterns, weights=pweights, k=1)[0]
            chosen: list[int] = []
            for col, count in enumerate(pattern):
                if count <= 0:
                    continue
                pool = [n for n in numbers_in_column(col) if n not in chosen]
                if len(pool) < count:
                    continue
                chosen.extend(self.rng.sample(pool, count))
            if len(chosen) != 5:
                continue
            whites = sorted(chosen)
            if consecutive_pair_count(whites) > 1:
                continue
            if frozenset(whites) in hist:
                continue
            pb = pick_powerball(self.drawings, self.rng, mode="random")
            notes = [
                "Random draw with pattern template constraint",
                f"Pattern: {'-'.join(map(str, pattern))}",
                "Rejected if exact historical white set or >1 consecutive pair",
            ]
            raw.append((whites, pb, notes, float(freq.get(pattern, 0))))

        # pure random fallback if needed
        while len(raw) < n_picks:
            whites = sorted(self.rng.sample(range(WHITE_MIN, WHITE_MAX + 1), 5))
            if frozenset(whites) in hist:
                continue
            pb = self.rng.randint(1, 26)
            raw.append((whites, pb, ["Pure random fallback"], 0.0))

        analysis = {
            "mode": "pattern-constrained random",
            "templates_used": ["-".join(map(str, p)) for p in patterns[:10]],
            "advantage_vs_retail_qp": (
                "You can reject sequences that look wrong (bad patterns, tight clusters, "
                "exact past winners) before spending — retail Quick Picks give no veto."
            ),
        }
        explanation = (
            "Random (Pattern-Constrained) spins numbers like a Quick Pick but forces "
            "common 5-column patterns and discards exact historical white sets and "
            "overly consecutive lines."
        )
        return self._finalize(raw, explanation, analysis, n_picks=n_picks)
