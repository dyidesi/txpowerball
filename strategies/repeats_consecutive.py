"""Repeats & Consecutive Numbers strategy / filter.

PawnPower Piano Roll insights:
- Two consecutive numbers in one drawing are common; 3+ consecutive is rare — avoid.
- One shared number with the previous drawing is OK; multiple shared numbers less so.
- Avoid sequences that are near-duplicates of recent winners.
"""

from __future__ import annotations

from strategies.base import (
    Strategy,
    PickResult,
    consecutive_pair_count,
    max_consecutive_run,
    pick_powerball,
)
from utils.data_loader import WHITE_MAX, WHITE_MIN, last_seen, white_frequency


class RepeatsConsecutiveStrategy(Strategy):
    name = "Repeats & Consecutive Filter"
    description = (
        "Constructs tickets that allow at most one consecutive pair, at most one "
        "repeat from the previous draw, and avoid recent multi-overlap clones."
    )

    def generate(self, n_picks: int = 5) -> PickResult:
        prev = self.drawings[-1] if self.drawings else None
        prev_set = set(prev.whites) if prev else set()
        recent_sets = [set(d.whites) for d in self.drawings[-10:]]
        freq = white_frequency(self.drawings)
        cold = last_seen(self.drawings)

        raw = []
        attempts_total = 0
        while len(raw) < n_picks and attempts_total < n_picks * 80:
            attempts_total += 1
            # mild due bias
            pool = list(range(WHITE_MIN, WHITE_MAX + 1))
            weights = [1.0 + cold[n] / 15.0 + max(0, 30 - freq[n]) / 20.0 for n in pool]
            chosen = set(self.rng.choices(pool, weights=weights, k=1))
            while len(chosen) < 5:
                n = self.rng.choices(pool, weights=weights, k=1)[0]
                if n not in chosen:
                    chosen.add(n)
            whites = sorted(chosen)

            # constraints
            if max_consecutive_run(whites) > 2:
                continue
            if consecutive_pair_count(whites) > 1:
                continue
            overlap_prev = len(set(whites) & prev_set)
            if overlap_prev > 1:
                continue
            # avoid sharing 3+ with any of last 10 drawings
            if any(len(set(whites) & rs) >= 3 for rs in recent_sets):
                continue

            pb = pick_powerball(self.drawings, self.rng, mode="random")
            # lightly avoid same PB as last draw
            if prev and pb == prev.powerball and self.rng.random() < 0.7:
                pb = pick_powerball(self.drawings, self.rng, mode="due")

            notes = [
                f"Consecutive pairs: {consecutive_pair_count(whites)} (max allowed 1)",
                f"Max consecutive run: {max_consecutive_run(whites)}",
                f"Overlap with last draw: {overlap_prev} number(s)",
            ]
            if prev:
                notes.append(f"Last draw whites: {list(prev.whites)}")
            score = 10.0 - consecutive_pair_count(whites) - overlap_prev
            raw.append((whites, pb, notes, score))

        analysis = {
            "rules": [
                "At most one consecutive pair (e.g. 14-15 OK; 14-15-16 not)",
                "At most one number shared with the immediately previous drawing",
                "No 3+ overlap with any of the last 10 drawings",
                "Avoids building on rare triple-consecutive / multi-repeat structures",
            ],
            "last_draw": list(prev.whites) if prev else None,
        }
        explanation = (
            "Repeats & Consecutive Filter applies Piano Roll rules: pairs of consecutive "
            "numbers are fine; triples are not. Light carry-over from the prior draw is "
            "allowed (one number), but multi-repeat clones of recent results are rejected."
        )
        return self._finalize(raw, explanation, analysis, n_picks=n_picks)
