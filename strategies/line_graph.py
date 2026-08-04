"""Line Graph momentum strategy.

PawnPower line graphs: short-term activity lines reverse direction within two
drawings ~88% of the time and within one drawing ~62%. If a number's recent
hit streak is rising for 2+ drawings, prefer numbers that would produce a
falling next step (i.e. cooler / not just hit).
"""

from __future__ import annotations

from strategies.base import Strategy, PickResult, pick_powerball, weighted_choice
from utils.data_loader import WHITE_MAX, WHITE_MIN, white_frequency


class LineGraphStrategy(Strategy):
    name = "Line Graph Momentum"
    description = (
        "Tracks short-term hit momentum per ball. Prefers numbers whose recent "
        "activity line is falling or flat (mean-reversion after rises)."
    )

    def __init__(self, drawings, seed=None, lookback: int = 6):
        super().__init__(drawings, seed)
        self.lookback = lookback

    def _momentum_scores(self) -> dict[int, float]:
        """Positive score = good to pick next (falling / overdue short-term)."""
        lb = min(self.lookback, len(self.drawings))
        recent = self.drawings[-lb:] if lb else []
        # per-draw hit indicator series for each number
        scores: dict[int, float] = {}
        for n in range(WHITE_MIN, WHITE_MAX + 1):
            series = [1 if n in d.whites else 0 for d in recent]
            if len(series) < 2:
                scores[n] = 1.0
                continue
            # slope of last few points (simple diff sum)
            diffs = [series[i] - series[i - 1] for i in range(1, len(series))]
            trend = sum(diffs[-2:]) if len(diffs) >= 2 else sum(diffs)
            last = series[-1]
            # Rising hard → down-weight; falling / zero → up-weight
            if trend >= 2 or (trend >= 1 and last == 1):
                momentum_pref = 0.35  # expect mean reversion down
            elif trend <= -1:
                momentum_pref = 1.6  # already falling; still eligible / due bounce later
            else:
                momentum_pref = 1.1
            # slight long-term due blend
            scores[n] = momentum_pref
        # blend with inverse long-term frequency lightly
        freq = white_frequency(self.drawings)
        max_f = max(freq.values()) or 1
        for n in scores:
            due = 1.0 + (max_f - freq[n]) / max_f
            scores[n] *= due
        return scores

    def generate(self, n_picks: int = 5) -> PickResult:
        scores = self._momentum_scores()
        ranked = sorted(scores, key=scores.get, reverse=True)

        raw = []
        for _ in range(n_picks):
            chosen: set[int] = set()
            # take 2–3 from strong falling/flat candidates
            elite = ranked[:18]
            k_elite = self.rng.randint(2, 3)
            for n in self.rng.sample(elite, k=min(k_elite, len(elite))):
                chosen.add(n)
            while len(chosen) < 5:
                chosen.add(weighted_choice(scores, self.rng, exclude=chosen))

            pb = pick_powerball(self.drawings, self.rng, mode="due")
            notes = [
                f"Lookback drawings: {self.lookback}",
                f"Momentum-favored seeds: {sorted(list(chosen)[:3])}",
                "Bias: reverse rising short-term lines (~88% reverse within 2 draws)",
            ]
            score = sum(scores[n] for n in chosen)
            raw.append((sorted(chosen), pb, notes, score))

        analysis = {
            "top_momentum_numbers": [
                {"number": n, "score": round(scores[n], 3)} for n in ranked[:15]
            ],
            "lookback": self.lookback,
            "rule": (
                "If a line has risen for 2+ drawings, prefer picks that create a falling "
                "next point. Lines reverse within 2 draws ~88% / 1 draw ~62% (PawnPower)."
            ),
        }
        explanation = (
            "Line Graph Momentum scores each white ball by recent hit direction. "
            "Numbers on a short-term rise are de-emphasized; falling/flat and longer-term "
            "due numbers are preferred for the next drawing."
        )
        return self._finalize(raw, explanation, analysis, n_picks=n_picks)
