"""5-column Activity Patterns strategy (PawnPower Patterns module).

White balls 1–69 are laid into five columns. A drawing yields a pattern such as
(1,1,0,1,2). Historically ~17% of the 126 possible patterns capture a large
share of winners — use frequent patterns as templates; avoid rare ones.
"""

from __future__ import annotations

from strategies.base import Strategy, PickResult, pick_powerball
from utils.data_loader import (
    COLUMN_BOUNDS,
    numbers_in_column,
    pattern_frequency,
    white_frequency,
)


def all_patterns_summing_to_five() -> list[tuple[int, ...]]:
    """All non-negative integer 5-tuples summing to 5 (126 patterns)."""
    out = []
    for a in range(6):
        for b in range(6 - a):
            for c in range(6 - a - b):
                for d in range(6 - a - b - c):
                    e = 5 - a - b - c - d
                    out.append((a, b, c, d, e))
    return out


class PatternsStrategy(Strategy):
    name = "Patterns (5-Column)"
    description = (
        "Builds tickets from historically frequent 5-column patterns "
        "(e.g. 1-1-0-1-2). Avoids the rare pattern majority that almost never wins."
    )

    def top_patterns(self, k: int = 21) -> list[tuple[tuple[int, ...], int]]:
        freq = pattern_frequency(self.drawings)
        # Ensure zero-count patterns exist for ranking context
        for p in all_patterns_summing_to_five():
            freq.setdefault(p, 0)
        ranked = sorted(freq.items(), key=lambda x: (-x[1], x[0]))
        return ranked[:k]

    def _fill_pattern(self, pattern: tuple[int, ...], freq: dict[int, int]) -> list[int]:
        chosen: list[int] = []
        for col, count in enumerate(pattern):
            if count <= 0:
                continue
            pool = numbers_in_column(col)
            # Prefer slightly underdrawn numbers within the column
            pool_sorted = sorted(pool, key=lambda n: (freq.get(n, 0), n))
            # sample with mild randomness among colder half of column
            cold_half = pool_sorted[: max(3, len(pool_sorted) // 2)]
            picks_here = []
            candidates = list(cold_half)
            self.rng.shuffle(candidates)
            for n in candidates:
                if n not in chosen and n not in picks_here:
                    picks_here.append(n)
                if len(picks_here) >= count:
                    break
            # fallback pure random in column
            while len(picks_here) < count:
                n = self.rng.choice(pool)
                if n not in chosen and n not in picks_here:
                    picks_here.append(n)
            chosen.extend(picks_here)
        return sorted(chosen)

    def generate(self, n_picks: int = 5) -> PickResult:
        top = self.top_patterns(21)
        # weight by historical frequency
        patterns = [p for p, _ in top]
        weights = [max(c, 1) for _, c in top]
        freq = white_frequency(self.drawings)

        raw = []
        for i in range(n_picks):
            pattern = self.rng.choices(patterns, weights=weights, k=1)[0]
            whites = self._fill_pattern(pattern, freq)
            # rare edge: couldn't fill
            while len(set(whites)) < 5:
                whites = self._fill_pattern(pattern, freq)
            pb = pick_powerball(self.drawings, self.rng, mode="due")
            hist_count = dict(top).get(pattern, 0)
            notes = [
                f"Pattern template: {'-'.join(map(str, pattern))}",
                f"Historical hits for this pattern: {hist_count}",
                f"Columns: {[f'{lo}-{hi}' for lo, hi in COLUMN_BOUNDS]}",
            ]
            score = float(hist_count)
            raw.append((whites, pb, notes, score))

        analysis = {
            "top_21_patterns": [
                {"pattern": "-".join(map(str, p)), "count": c} for p, c in top
            ],
            "column_bounds": COLUMN_BOUNDS,
            "note": (
                "PawnPower: ~17% of patterns (21/126) capture a large share of activity. "
                "Building picks on those templates avoids the long tail of rare patterns."
            ),
        }
        explanation = (
            "Patterns strategy maps 1–69 into five columns and uses frequent hit-count "
            "templates (e.g. 1-1-0-1-2). Tickets are filled column-by-column from those "
            "templates so you stay in historically common layouts."
        )
        return self._finalize(raw, explanation, analysis, n_picks=n_picks)
