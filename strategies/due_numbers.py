"""Due Numbers strategy — long-term under-frequency + short-term activity counters.

From PawnPower: numbers that have not been drawn as frequently are "due", but
analysis should consider both short-term AND long-term activity. Don't load a
single ticket with ALL best picks — typically only 1 (rarely 2) of the hottest
due numbers appear in a real winning set.
"""

from __future__ import annotations

from strategies.base import Strategy, PickResult, pick_powerball, weighted_choice
from utils.data_loader import (
    WHITE_MAX,
    WHITE_MIN,
    last_seen,
    short_term_activity,
    white_frequency,
)


class DueNumbersStrategy(Strategy):
    name = "Due Numbers"
    description = (
        "Combines long-term frequency (underdrawn = higher weight) with a short-term "
        "activity counter. Each ticket embeds only 1–2 top 'due' numbers so picks "
        "mirror real drawings rather than packing every cold ball together."
    )

    def __init__(self, drawings, seed=None, short_window: int = 20):
        super().__init__(drawings, seed)
        self.short_window = short_window

    def _weights(self) -> dict[int, float]:
        freq = white_frequency(self.drawings)
        cold = last_seen(self.drawings)
        short = short_term_activity(self.drawings, self.short_window)
        n_draws = max(len(self.drawings), 1)
        expected = (n_draws * 5) / 69  # expected hits per ball

        weights: dict[int, float] = {}
        for n in range(WHITE_MIN, WHITE_MAX + 1):
            # Long-term due: below expected frequency
            long_due = max(0.0, expected - freq[n]) + 1.0
            # Gaps since last seen (normalize)
            gap_score = 1.0 + cold[n] / 10.0
            # Short-term activity: lightly down-weight very recent hits, but don't ban
            short_penalty = 1.0 / (1.0 + short.get(n, 0) * 0.35)
            weights[n] = long_due * gap_score * short_penalty
        return weights

    def generate(self, n_picks: int = 5) -> PickResult:
        weights = self._weights()
        ranked = sorted(weights, key=weights.get, reverse=True)
        top_due = ranked[:12]
        mid = ranked[12:40]

        raw = []
        for i in range(n_picks):
            # 1 (sometimes 2) of the strongest due numbers
            n_elite = 2 if self.rng.random() < 0.25 else 1
            elite = self.rng.sample(top_due, k=min(n_elite, len(top_due)))
            chosen = set(elite)
            notes = [f"Elite due seeds: {sorted(elite)}"]

            while len(chosen) < 5:
                # Prefer mid-tier due so we don't stack all cold numbers
                pool_w = {
                    n: (weights[n] if n in mid else weights[n] * 0.4)
                    for n in range(WHITE_MIN, WHITE_MAX + 1)
                    if n not in chosen
                }
                chosen.add(weighted_choice(pool_w, self.rng, exclude=chosen))

            pb = pick_powerball(self.drawings, self.rng, mode="due")
            score = sum(weights[n] for n in chosen)
            notes.append(
                f"Long-term underdrawn + short-window ({self.short_window}) activity mix"
            )
            raw.append((sorted(chosen), pb, notes, score))

        analysis = {
            "top_due_whites": top_due[:10],
            "short_window": self.short_window,
            "weight_snapshot": {n: round(weights[n], 2) for n in top_due[:10]},
        }
        explanation = (
            "Due Numbers blends long-term under-frequency with short-term activity "
            "counters (PawnPower-style). Each $2 line uses only 1–2 of the strongest "
            "due balls; the rest are mid-weight so the ticket isn't a pure cold stack."
        )
        return self._finalize(raw, explanation, analysis, n_picks=n_picks)
