"""Automated Pick Numbers Selection — combines all PawnPower-inspired strategies.

Flexible pipeline:
1. Choose frequent 5-column patterns (Patterns)
2. Seed with due numbers / line-graph momentum (Due + Line)
3. Enforce bar-graph activity mix (Bar Graph)
4. Filter repeats/consecutives + history collisions
5. Optional pseudo-history pattern stability check
6. Powerball from due distribution
"""

from __future__ import annotations

from strategies.base import (
    Strategy,
    PickResult,
    consecutive_pair_count,
    max_consecutive_run,
    pick_powerball,
    is_historical_match,
)
from strategies.patterns import all_patterns_summing_to_five
from strategies.pseudo_history import generate_pseudo_history
from utils.data_loader import (
    WHITE_MAX,
    WHITE_MIN,
    last_seen,
    numbers_in_column,
    pattern_frequency,
    short_term_activity,
    white_frequency,
)


class AutomatedStrategy(Strategy):
    name = "Automated (All Strategies)"
    description = (
        "Full pipeline: top patterns + due/momentum seeds + bar-band mix + "
        "repeat/consecutive filters + pseudo-history stability + history de-dup."
    )

    def generate(self, n_picks: int = 5) -> PickResult:
        drawings = self.drawings
        freq = white_frequency(drawings)
        cold = last_seen(drawings)
        short = short_term_activity(drawings, 20)

        # --- Patterns ---
        pfreq = pattern_frequency(drawings)
        for p in all_patterns_summing_to_five():
            pfreq.setdefault(p, 0)
        top_patterns = sorted(pfreq.items(), key=lambda x: -x[1])[:21]
        patterns = [p for p, c in top_patterns]
        pweights = [max(c, 1) for _, c in top_patterns]

        # --- Pseudo stability boost ---
        pseudo = generate_pseudo_history(300, self.rng, drawings[-1] if drawings else None)
        pp = pattern_frequency(pseudo)
        stability = {p: pfreq[p] + 0.05 * pp.get(p, 0) for p in patterns}
        pweights = [max(stability[p], 1) for p in patterns]

        # --- Due + momentum composite weights ---
        n_draws = max(len(drawings), 1)
        expected = (n_draws * 5) / 69
        due_w: dict[int, float] = {}
        for n in range(WHITE_MIN, WHITE_MAX + 1):
            long_due = max(0.0, expected - freq[n]) + 1.0
            gap = 1.0 + cold[n] / 10.0
            short_pen = 1.0 / (1.0 + short.get(n, 0) * 0.3)
            # momentum: if hit in last draw and previous, downweight
            recent = drawings[-3:] if len(drawings) >= 3 else drawings
            hits = sum(1 for d in recent if n in d.whites)
            mom = 0.5 if hits >= 2 else (0.85 if hits == 1 else 1.15)
            due_w[n] = long_due * gap * short_pen * mom

        ranked_due = sorted(due_w, key=due_w.get, reverse=True)
        cold_band = ranked_due[:23]
        mid_band = ranked_due[23:46]
        hot_band = ranked_due[46:]

        prev_set = set(drawings[-1].whites) if drawings else set()
        recent_sets = [set(d.whites) for d in drawings[-10:]]

        raw = []
        rejected = {"consec": 0, "repeat": 0, "history": 0, "overlap": 0}
        for _ in range(n_picks * 100):
            if len(raw) >= n_picks:
                break
            pattern = self.rng.choices(patterns, weights=pweights, k=1)[0]

            # Fill columns preferring due weights; inject 1 elite due if column allows
            elite = ranked_due[0]
            chosen: list[int] = []
            elite_placed = False
            for col, count in enumerate(pattern):
                if count <= 0:
                    continue
                pool = numbers_in_column(col)
                local = []
                # try place one elite due in matching column once per ticket
                if not elite_placed and elite in pool and count >= 1 and self.rng.random() < 0.7:
                    local.append(elite)
                    elite_placed = True
                while len(local) < count:
                    candidates = [n for n in pool if n not in chosen and n not in local]
                    if not candidates:
                        break
                    weights = [due_w[n] for n in candidates]
                    pick = self.rng.choices(candidates, weights=weights, k=1)[0]
                    local.append(pick)
                chosen.extend(local)

            if len(set(chosen)) != 5:
                continue
            whites = sorted(set(chosen))
            if len(whites) != 5:
                continue

            # Bar-graph mix check: not all from same band
            bands = []
            for n in whites:
                if n in cold_band:
                    bands.append("C")
                elif n in mid_band:
                    bands.append("M")
                else:
                    bands.append("H")
            if len(set(bands)) < 2:
                # re-roll bias: skip mono-band tickets
                if self.rng.random() < 0.85:
                    continue

            # Repeats & consecutive filters
            if max_consecutive_run(whites) > 2:
                rejected["consec"] += 1
                continue
            if consecutive_pair_count(whites) > 1:
                rejected["consec"] += 1
                continue
            overlap_prev = len(set(whites) & prev_set)
            if overlap_prev > 1:
                rejected["repeat"] += 1
                continue
            if any(len(set(whites) & rs) >= 3 for rs in recent_sets):
                rejected["overlap"] += 1
                continue
            if is_historical_match(whites, drawings):
                rejected["history"] += 1
                continue

            # Avoid duplicate tickets in this batch
            if any(tuple(whites) == tuple(r[0]) for r in raw):
                continue

            pb = pick_powerball(drawings, self.rng, mode="due")
            notes = [
                f"Pattern: {'-'.join(map(str, pattern))} (top-21 template)",
                f"Activity bands: {''.join(bands)} (C=cold M=mid H=hot due-rank)",
                f"Elite due seed used: {elite_placed} (#{elite})",
                f"Prev-draw overlap: {overlap_prev}",
                f"Consec pairs: {consecutive_pair_count(whites)}",
                "Pipeline: Patterns → Due/Momentum → Bar mix → Filters → Pseudo weights",
            ]
            score = (
                stability.get(pattern, 0)
                + sum(due_w[n] for n in whites)
                - consecutive_pair_count(whites)
            )
            raw.append((whites, pb, notes, score))

        analysis = {
            "top_patterns": [
                {"pattern": "-".join(map(str, p)), "count": c} for p, c in top_patterns[:10]
            ],
            "top_due": ranked_due[:10],
            "filter_rejects": rejected,
            "pipeline": [
                "1. Select frequent 5-column pattern (Patterns)",
                "2. Fill columns with due + short-term momentum weights (Due + Line Graph)",
                "3. Require multi-band activity mix (Bar Graph)",
                "4. Filter consecutives / multi-repeats / history clones (Piano Roll)",
                "5. Weight patterns by pseudo-history stability (Pseudo History)",
                "6. Powerball from due distribution; $2 × 5 plays = $10",
            ],
        }
        explanation = (
            "Automated mode runs the full PawnPower-inspired stack for you: common "
            "column patterns, due/momentum number weights, bar-graph band balance, "
            "repeat/consecutive filters, and pseudo-history pattern checks. "
            "Default stake: $10 → 5 plays at $2 each."
        )
        return self._finalize(raw, explanation, analysis, n_picks=n_picks)
