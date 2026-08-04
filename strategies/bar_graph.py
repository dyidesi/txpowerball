"""Bar Graph balance strategy.

PawnPower bar graphs show winners are NOT all lowest-activity numbers. Shorter
bars catch up over time, but real drawings mix activity tiers. Prefer a
balanced spread across cold / mid / hot frequency bands — and optionally bias
by sorted position ranges.
"""

from __future__ import annotations

from strategies.base import Strategy, PickResult, pick_powerball
from utils.data_loader import WHITE_MAX, WHITE_MIN, white_frequency


class BarGraphStrategy(Strategy):
    name = "Bar Graph Balance"
    description = (
        "Mirrors bar-graph distributions: mix cold, mid, and hot frequency bands "
        "instead of stacking only the shortest bars."
    )

    def _bands(self) -> tuple[list[int], list[int], list[int], dict[int, int]]:
        freq = white_frequency(self.drawings)
        ranked = sorted(range(WHITE_MIN, WHITE_MAX + 1), key=lambda n: (freq[n], n))
        third = len(ranked) // 3
        cold = ranked[:third]
        mid = ranked[third : 2 * third]
        hot = ranked[2 * third :]
        return cold, mid, hot, freq

    def _position_bias(self) -> list[dict[int, float]]:
        """For each sorted white slot (0..4), historical frequency of values."""
        slot_freq = [{n: 0.0 for n in range(WHITE_MIN, WHITE_MAX + 1)} for _ in range(5)]
        for d in self.drawings:
            for i, w in enumerate(d.whites):
                if WHITE_MIN <= w <= WHITE_MAX:
                    slot_freq[i][w] += 1.0
        # smooth
        for i in range(5):
            for n in slot_freq[i]:
                slot_freq[i][n] += 0.5
        return slot_freq

    def generate(self, n_picks: int = 5) -> PickResult:
        cold, mid, hot, freq = self._bands()
        slot_bias = self._position_bias()

        raw = []
        for _ in range(n_picks):
            # Typical mix: 2 cold, 2 mid, 1 hot (varies slightly)
            mix = self.rng.choice(
                [
                    (2, 2, 1),
                    (2, 1, 2),
                    (1, 3, 1),
                    (3, 1, 1),
                    (1, 2, 2),
                ]
            )
            chosen: list[int] = []
            pools = [cold, mid, hot]
            for pool, count in zip(pools, mix):
                available = [n for n in pool if n not in chosen]
                if len(available) < count:
                    available = [n for n in range(WHITE_MIN, WHITE_MAX + 1) if n not in chosen]
                picks = self.rng.sample(available, k=min(count, len(available)))
                chosen.extend(picks)

            while len(chosen) < 5:
                n = self.rng.randint(WHITE_MIN, WHITE_MAX)
                if n not in chosen:
                    chosen.append(n)

            # Light reordering toward position-typical ranges via swap search
            chosen = sorted(chosen)
            for i in range(5):
                best_j = i
                best_s = slot_bias[i].get(chosen[i], 0)
                for j in range(i, 5):
                    s = slot_bias[i].get(chosen[j], 0)
                    if s > best_s:
                        best_s = s
                        best_j = j
                if best_j != i:
                    chosen[i], chosen[best_j] = chosen[best_j], chosen[i]
            chosen = sorted(chosen)

            pb = pick_powerball(self.drawings, self.rng, mode="hot")
            notes = [
                f"Activity mix cold/mid/hot: {mix}",
                f"Frequencies: {[freq[n] for n in chosen]}",
                "Balanced bars — not an all-shortest-bar ticket",
            ]
            # Score: reward diversity of frequency ranks
            ranks = [sorted(freq.values()).index(freq[n]) if freq[n] in sorted(freq.values()) else 0 for n in chosen]
            score = float(len(set(mix))) + 0.01 * sum(freq[n] for n in chosen)
            raw.append((chosen, pb, notes, score))

        analysis = {
            "cold_band_sample": cold[:8],
            "mid_band_sample": mid[:8],
            "hot_band_sample": hot[:8],
            "idea": (
                "Bar graphs show shorter bars catch up eventually, but winners span "
                "activity levels. Balanced tickets match that visual layout."
            ),
        }
        explanation = (
            "Bar Graph Balance builds each ticket from cold, mid, and hot frequency "
            "bands so your lines look like real drawings on a frequency bar chart — "
            "not a pile of only the shortest bars."
        )
        return self._finalize(raw, explanation, analysis, n_picks=n_picks)
