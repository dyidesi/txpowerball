"""
Powerball Number Picker — Streamlit app
Strategies inspired by https://pawnpower.net/Home/Strategies

Default bankroll assumption: $10 per session → 5 plays @ $2 each.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies import STRATEGY_REGISTRY
from utils.data_loader import (
    COLUMN_BOUNDS,
    load_drawings,
    pattern_frequency,
    powerball_frequency,
    short_term_activity,
    white_frequency,
    last_seen,
)

PLAY_COST = 2.0
DEFAULT_BUDGET = 10.0


def plays_for_budget(budget: float, power_play: bool) -> int:
    unit = 3.0 if power_play else 2.0
    return max(1, int(budget // unit))


@st.cache_data(show_spinner="Loading Powerball history…")
def get_drawings(refresh: bool = False):
    return load_drawings(prefer_remote=refresh, modern_only=True)


def ticket_table(picks) -> pd.DataFrame:
    rows = []
    for i, p in enumerate(picks, 1):
        rows.append(
            {
                "Play": i,
                "White 1": f"{p.whites[0]:02d}",
                "White 2": f"{p.whites[1]:02d}",
                "White 3": f"{p.whites[2]:02d}",
                "White 4": f"{p.whites[3]:02d}",
                "White 5": f"{p.whites[4]:02d}",
                "Powerball": f"{p.powerball:02d}",
                "Score": round(p.score, 2),
            }
        )
    return pd.DataFrame(rows)


def main():
    st.set_page_config(
        page_title="Powerball Strategy Picker",
        page_icon="🎱",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("🎱 Powerball Strategy Number Picker")
    st.caption(
        "Strategies adapted from "
        "[PawnPower Number Selection Strategies](https://pawnpower.net/Home/Strategies). "
        f"Default stake: **${DEFAULT_BUDGET:.0f}** → "
        f"**{int(DEFAULT_BUDGET // PLAY_COST)} plays** at ${PLAY_COST:.0f} each."
    )

    with st.sidebar:
        st.header("Session")
        budget = st.number_input(
            "Bankroll this session ($)",
            min_value=2.0,
            max_value=200.0,
            value=DEFAULT_BUDGET,
            step=2.0,
            help="Always assume $10 unless you change it. Base play = $2.",
        )
        power_play = st.checkbox(
            "Include Power Play (+$1/play)",
            value=False,
            help="Power Play multiplies non-jackpot prizes; costs $1 extra per play.",
        )
        n_plays = plays_for_budget(budget, power_play)
        unit = 3.0 if power_play else 2.0
        spent = n_plays * unit
        st.metric("Plays this session", n_plays)
        st.write(f"Cost: **${spent:.0f}** (${unit:.0f} × {n_plays})" + (" with Power Play" if power_play else ""))
        if spent < budget:
            st.caption(f"${budget - spent:.0f} unspent (not enough for another play).")

        st.divider()
        strategy_name = st.selectbox(
            "Strategy",
            options=list(STRATEGY_REGISTRY.keys()),
            index=list(STRATEGY_REGISTRY.keys()).index("Automated (All Strategies)"),
        )
        seed = st.number_input(
            "Random seed (optional)",
            min_value=0,
            max_value=10_000_000,
            value=0,
            help="Set non-zero for reproducible picks.",
        )
        use_seed = seed if seed != 0 else None

        refresh = st.button("Refresh history from data.ny.gov")
        generate = st.button("Generate picks", type="primary", use_container_width=True)

        st.divider()
        st.markdown(
            """
**Responsible play**
- Don't bet money you can't afford to lose
- Lottery odds remain extreme; strategies organize numbers, they don't beat math
- One session = your budget above — stick to it
"""
        )

    try:
        drawings = get_drawings(refresh=bool(refresh))
    except Exception as e:
        st.error(f"Could not load history: {e}")
        return

    if not drawings:
        st.error("No drawings loaded.")
        return

    last = drawings[-1]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Drawings analyzed", f"{len(drawings):,}")
    c2.metric("Latest draw", last.date.strftime("%Y-%m-%d"))
    c3.metric(
        "Latest whites",
        " ".join(f"{n:02d}" for n in last.whites),
    )
    c4.metric("Latest Powerball", f"{last.powerball:02d}")

    tab_pick, tab_strategy, tab_data, tab_about = st.tabs(
        ["Your tickets", "Strategy detail", "History & stats", "About strategies"]
    )

    with tab_pick:
        cls = STRATEGY_REGISTRY[strategy_name]
        strat = cls(drawings, seed=use_seed)
        st.subheader(strategy_name)
        st.write(getattr(strat, "description", ""))

        if generate or "last_result" not in st.session_state:
            result = strat.generate(n_picks=n_plays)
            st.session_state["last_result"] = result
            st.session_state["last_strategy"] = strategy_name
            st.session_state["last_budget"] = spent
        else:
            # regenerate if strategy or play count changed
            prev = st.session_state.get("last_result")
            if (
                st.session_state.get("last_strategy") != strategy_name
                or prev is None
                or len(prev.picks) != n_plays
            ):
                result = strat.generate(n_picks=n_plays)
                st.session_state["last_result"] = result
                st.session_state["last_strategy"] = strategy_name
                st.session_state["last_budget"] = spent
            else:
                result = prev

        st.info(result.explanation)

        st.markdown(f"### Tickets — **${st.session_state.get('last_budget', spent):.0f}** session")
        df = ticket_table(result.picks)
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Pretty card view
        cols = st.columns(min(5, len(result.picks)))
        for i, (col, pick) in enumerate(zip(cols, result.picks)):
            with col:
                st.markdown(
                    f"""
<div style="border:2px solid #1f4e79;border-radius:12px;padding:12px;text-align:center;
background:linear-gradient(180deg,#0b1e33,#132a45);color:#f5f7fa;">
<div style="font-size:0.75rem;opacity:0.8;">PLAY {i+1}</div>
<div style="font-size:1.25rem;font-weight:700;letter-spacing:0.08em;margin:8px 0;">
{"&nbsp;".join(f"{n:02d}" for n in pick.whites)}
</div>
<div style="display:inline-block;background:#c41e3a;color:white;border-radius:50%;
width:42px;height:42px;line-height:42px;font-weight:700;">{pick.powerball:02d}</div>
<div style="font-size:0.7rem;margin-top:8px;opacity:0.7;">Powerball</div>
</div>
""",
                    unsafe_allow_html=True,
                )

        with st.expander("Per-ticket notes"):
            for i, pick in enumerate(result.picks, 1):
                st.markdown(f"**Play {i}** — `{pick.display()}`")
                for note in pick.notes:
                    st.caption(f"• {note}")

        # Export
        csv = df.to_csv(index=False)
        st.download_button(
            "Download tickets CSV",
            data=csv,
            file_name="powerball_picks.csv",
            mime="text/csv",
        )

        # Quick match check vs last draw (for after-draw review of saved numbers — demo)
        st.markdown("#### Compare a ticket to the latest drawing")
        st.caption("Useful after the draw to see matches against the most recent result.")
        match_rows = []
        for i, pick in enumerate(result.picks, 1):
            w_hits = len(set(pick.whites) & set(last.whites))
            pb_hit = pick.powerball == last.powerball
            match_rows.append(
                {
                    "Play": i,
                    "White matches": w_hits,
                    "Powerball match": "Yes" if pb_hit else "No",
                }
            )
        st.dataframe(pd.DataFrame(match_rows), hide_index=True, use_container_width=True)

    with tab_strategy:
        result = st.session_state.get("last_result")
        if not result:
            st.write("Generate picks to see strategy analysis.")
        else:
            st.subheader(f"Analysis — {result.strategy_name}")
            analysis = result.analysis or {}
            if "pipeline" in analysis:
                st.markdown("**Pipeline**")
                for step in analysis["pipeline"]:
                    st.write(f"- {step}")
            if "top_due" in analysis:
                st.markdown("**Top due white balls**")
                st.write(", ".join(f"{n:02d}" for n in analysis["top_due"]))
            if "top_due_whites" in analysis:
                st.markdown("**Top due white balls**")
                st.write(", ".join(f"{n:02d}" for n in analysis["top_due_whites"]))
            if "top_21_patterns" in analysis:
                st.markdown("**Top patterns (5-column hit counts)**")
                st.dataframe(pd.DataFrame(analysis["top_21_patterns"]), hide_index=True)
            if "top_patterns" in analysis:
                st.markdown("**Top patterns used**")
                st.dataframe(pd.DataFrame(analysis["top_patterns"]), hide_index=True)
            if "stable_patterns" in analysis:
                st.markdown("**Pseudo-history stable patterns**")
                st.dataframe(pd.DataFrame(analysis["stable_patterns"]), hide_index=True)
            if "top_momentum_numbers" in analysis:
                st.markdown("**Momentum-favored numbers**")
                st.dataframe(pd.DataFrame(analysis["top_momentum_numbers"]), hide_index=True)
            if "filter_rejects" in analysis:
                st.markdown("**Filter rejections while building**")
                st.json(analysis["filter_rejects"])
            if "rules" in analysis:
                st.markdown("**Rules**")
                for r in analysis["rules"]:
                    st.write(f"- {r}")
            if "column_bounds" in analysis or strategy_name.startswith("Patterns"):
                st.markdown("**Column layout (1–69)**")
                st.write(
                    " | ".join(
                        f"Col{i+1}: {lo}–{hi}" for i, (lo, hi) in enumerate(COLUMN_BOUNDS)
                    )
                )
            # dump remainder
            skip = {
                "pipeline",
                "top_due",
                "top_due_whites",
                "top_21_patterns",
                "top_patterns",
                "stable_patterns",
                "top_momentum_numbers",
                "filter_rejects",
                "rules",
                "column_bounds",
            }
            extra = {k: v for k, v in analysis.items() if k not in skip}
            if extra:
                with st.expander("Raw analysis dict"):
                    st.json(extra)

    with tab_data:
        st.subheader("Recent drawings")
        recent_n = st.slider("Show last N draws", 5, 50, 15)
        rows = []
        for d in drawings[-recent_n:][::-1]:
            rows.append(
                {
                    "Date": d.date.strftime("%Y-%m-%d"),
                    "Whites": " ".join(f"{n:02d}" for n in d.whites),
                    "PB": f"{d.powerball:02d}",
                    "Pattern": "-".join(map(str, d.pattern())),
                    "Multiplier": d.multiplier,
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

        st.subheader("White ball frequency (modern era)")
        wf = white_frequency(drawings)
        freq_df = pd.DataFrame(
            {"number": list(wf.keys()), "hits": list(wf.values())}
        ).sort_values("number")
        st.bar_chart(freq_df.set_index("number"))

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Coldest (longest since hit)**")
            cold = last_seen(drawings)
            cold_sorted = sorted(cold.items(), key=lambda x: -x[1])[:15]
            st.dataframe(
                pd.DataFrame(cold_sorted, columns=["Number", "Draws since hit"]),
                hide_index=True,
            )
        with col_b:
            st.markdown("**Hottest (most hits, all-time modern)**")
            hot = sorted(wf.items(), key=lambda x: -x[1])[:15]
            st.dataframe(
                pd.DataFrame(hot, columns=["Number", "Hits"]),
                hide_index=True,
            )

        st.subheader("Powerball frequency")
        pbf = powerball_frequency(drawings)
        pb_df = pd.DataFrame({"PB": list(pbf.keys()), "hits": list(pbf.values())})
        st.bar_chart(pb_df.set_index("PB"))

        st.subheader("Top 5-column patterns")
        pf = pattern_frequency(drawings)
        top_p = sorted(pf.items(), key=lambda x: -x[1])[:21]
        st.dataframe(
            pd.DataFrame(
                [{"pattern": "-".join(map(str, p)), "count": c} for p, c in top_p]
            ),
            hide_index=True,
        )
        st.caption(
            f"Columns: "
            + ", ".join(f"{i+1}=[{lo}-{hi}]" for i, (lo, hi) in enumerate(COLUMN_BOUNDS))
        )

        st.subheader("Short-term activity (last 20 draws)")
        st.dataframe(
            pd.DataFrame(
                sorted(short_term_activity(drawings, 20).items(), key=lambda x: -x[1])[:20],
                columns=["Number", "Hits in last 20"],
            ),
            hide_index=True,
        )

    with tab_about:
        st.markdown(
            """
## Strategies (from PawnPower)

Source: [pawnpower.net/Home/Strategies](https://pawnpower.net/Home/Strategies)

| Strategy | What we implement |
|---|---|
| **Due Numbers** | Long-term under-frequency + short-term activity counters; only 1–2 elite due balls per ticket |
| **Repeats & Consecutive** | Allow ≤1 consecutive pair; ≤1 overlap with previous draw; block 3+ consecutive runs |
| **Patterns** | Map 1–69 into 5 columns; use historically frequent hit-count templates (~top 21 of 126) |
| **Bar Graphs** | Mix cold / mid / hot frequency bands so tickets aren't all "short bars" |
| **Line Graphs** | Prefer numbers whose short-term hit momentum is flat/falling (mean reversion) |
| **Pseudo History** | Generate synthetic future draws; prefer patterns that stay plausible under randomness |
| **Random Picks** | RNG constrained to good patterns + history de-dup (veto bad Quick Picks) |
| **Automated** | Full pipeline combining all of the above |

### Bankroll
- Powerball base play is **$2**
- This app defaults to **$10 → 5 plays**
- Optional Power Play: **$3/play** → 3 plays on a $10 budget

### Data
- Historical draws from [NY Open Data — Powerball beginning 2010](https://data.ny.gov/Government-Finance/Lottery-Powerball-Winning-Numbers-Beginning-2010/d6yy-54nr)
- Analysis uses the **modern matrix only** (since 2015-10-07): whites **1–69**, Powerball **1–26**

### Disclaimer
Lottery drawings are random. These tools organize selection the way analysis software does;
they do **not** improve mathematical odds of winning the jackpot. Play only with money you can afford to lose.
"""
        )


if __name__ == "__main__":
    main()
