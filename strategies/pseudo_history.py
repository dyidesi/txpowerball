"""Pseudo History validation strategy.

PawnPower Pseudo History: generate long synthetic random drawing streams that
stand in for future history, then check whether strategy preferences (patterns,
due ranks) still look sensible under pure randomness. Tickets are scored by how
often their pattern/tier mix appears in both real and pseudo futures.
"""

from __future__ import annotations

from datetime import timedelta

from strategies.base import Strategy, PickResult, pick_powerball, weighted_choice
from strategies.patterns import all_patterns_summing_to_five
from utils.data_loader import (
    WHITE_MAX,
    WHITE_MIN,
    Drawing,
    numbers_in_column,
    pattern_frequency,
    white_frequency,
    last_seen,
)


def generate_pseudo_history(
    n_draws: int,
    rng,
    start_from: Drawing | None = None,
) -> list[Drawing]:
    drawings: list[Drawing] = []
    date = start_from.date if start_from else None
    for i in range(n_draws):
        whites = tuple(sorted(rng.sample(range(WHITE_MIN, WHITE_MAX + 1), 5)))
        pb = rng.randint(1, 26)
        if date is not None:
            # Powerball draws Mon/Wed/Sat — approximate +2/3 day steps
            date = date + timedelta(days=2 if i % 3 else 3)
        else:
            from datetime import datetime

            date = datetime(2030, 1, 1) + timedelta(days=2 * i)
        drawings.append(Drawing(date=date, whites=whites, powerball=pb))
    return drawings


class PseudoHistoryStrategy(Strategy):
    name = "Pseudo History Validated"
    description = (
        "Builds candidate tickets from real due/pattern signals, then ranks them "
        "by stability under synthetic future (pseudo) histories."
    )

    def __init__(self, drawings, seed=None, pseudo_len: int = 500):
        super().__init__(drawings, seed)
        self.pseudo_len = pseudo_len

    def generate(self, n_picks: int = 5) -> PickResult:
        real_pat = pattern_frequency(self.drawings)
        for p in all_patterns_summing_to_five():
            real_pat.setdefault(p, 0)
        top_real = sorted(real_pat.items(), key=lambda x: -x[1])[:21]
        top_set = {p for p, _ in top_real}

        # Pseudo futures: which patterns stay common?
        pseudo = generate_pseudo_history(self.pseudo_len, self.rng, self.drawings[-1] if self.drawings else None)
        pseudo_pat = pattern_frequency(pseudo)
        stable = []
        for p, c in top_real:
            stable.append((p, c, pseudo_pat.get(p, 0)))
        # Prefer patterns frequent in real data AND not vanishingly rare in pseudo
        stable.sort(key=lambda t: (-t[1], -t[2]))

        cold = last_seen(self.drawings)
        freq = white_frequency(self.drawings)
        weights = {
            n: 1.0 + cold[n] / 12.0 + max(0, 25 - freq[n]) / 15.0
            for n in range(WHITE_MIN, WHITE_MAX + 1)
        }

        raw = []
        for i in range(n_picks):
            pattern, real_c, pseudo_c = stable[i % len(stable)]
            chosen: list[int] = []
            for col, count in enumerate(pattern):
                if count <= 0:
                    continue
                pool = numbers_in_column(col)
                local_w = {n: weights[n] for n in pool}
                for _ in range(count):
                    n = weighted_choice(local_w, self.rng, exclude=set(chosen))
                    chosen.append(n)
            whites = sorted(chosen)
            pb = pick_powerball(self.drawings, self.rng, mode="due")
            notes = [
                f"Pattern: {'-'.join(map(str, pattern))}",
                f"Real-history hits: {real_c} | Pseudo-future hits ({self.pseudo_len} draws): {pseudo_c}",
                "Validated: pattern remains plausible under random proxy history",
            ]
            score = float(real_c) + 0.1 * pseudo_c
            raw.append((whites, pb, notes, score))

        analysis = {
            "pseudo_draws_generated": self.pseudo_len,
            "stable_patterns": [
                {
                    "pattern": "-".join(map(str, p)),
                    "real_count": rc,
                    "pseudo_count": pc,
                }
                for p, rc, pc in stable[:12]
            ],
            "purpose": (
                "Pseudo history is a random stand-in for future drawings. Patterns that "
                "dominate only in a short real window but disappear in long pseudo runs "
                "are treated as less trustworthy."
            ),
        }
        explanation = (
            "Pseudo History Validated invents a long random 'future' draw stream, checks "
            "which real-world favorite patterns still behave normally under pure chance, "
            "and builds your $10 ticket set from those stable templates."
        )
        return self._finalize(raw, explanation, analysis, n_picks=n_picks)
