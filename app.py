"""
TxPowerball — Streamlit Powerball strategy picker.

Strategies inspired by https://pawnpower.net/Home/Strategies
Default bankroll: $10/session → 5 plays @ $2 each.
"""

from __future__ import annotations

import html
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
from utils.ticket_ocr import (
    TicketParseResult,
    check_ticket,
    parse_ticket_image,
    parse_ticket_text,
)

PLAY_COST = 2.0
DEFAULT_BUDGET = 10.0
DEFAULT_STRATEGY = "Unpopular (Anti-Share)"

# Keys skipped when dumping residual analysis dict
_ANALYSIS_SKIP = frozenset(
    {
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
        "pool",
        "coverage",
        "why_this_matters",
        "budget_note",
    }
)


def plays_for_budget(budget: float, power_play: bool) -> int:
    unit = 3.0 if power_play else 2.0
    return max(1, int(budget // unit))


@st.cache_data(show_spinner="Loading Powerball history…")
def get_drawings(refresh: bool = False):
    return load_drawings(prefer_remote=refresh, modern_only=True)


def is_dark_theme() -> bool:
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return True


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


def render_ticket_board(picks) -> None:
    """Premium responsive lottery ticket cards (wraps on narrow screens)."""
    dark = is_dark_theme()
    if dark:
        card_bg = "linear-gradient(160deg, #151E2E 0%, #0F172A 55%, #1A1020 100%)"
        card_border = "rgba(225, 29, 72, 0.35)"
        white_ball = "linear-gradient(145deg, #F8FAFC 0%, #E2E8F0 100%)"
        white_text = "#0F172A"
        white_shadow = "0 2px 8px rgba(0,0,0,0.35)"
        label = "rgba(241,245,249,0.55)"
        score_c = "rgba(148,163,184,0.95)"
        pb_ball = "linear-gradient(145deg, #FB7185 0%, #E11D48 45%, #9F1239 100%)"
        play_c = "#FB7185"
    else:
        card_bg = "linear-gradient(160deg, #FFFFFF 0%, #F8FAFC 60%, #FFF1F2 100%)"
        card_border = "rgba(190, 18, 60, 0.22)"
        white_ball = "linear-gradient(145deg, #FFFFFF 0%, #F1F5F9 100%)"
        white_text = "#0F172A"
        white_shadow = "0 2px 8px rgba(15,23,42,0.12)"
        label = "rgba(15,23,42,0.45)"
        score_c = "rgba(100,116,139,0.95)"
        pb_ball = "linear-gradient(145deg, #FB7185 0%, #E11D48 45%, #9F1239 100%)"
        play_c = "#BE123C"

    cards = []
    for i, pick in enumerate(picks, 1):
        whites_html = "".join(
            f'<span class="tx-ball tx-white">{n:02d}</span>' for n in pick.whites
        )
        cards.append(
            f"""
<div class="tx-card">
  <div class="tx-play">Play {i}</div>
  <div class="tx-row">
    {whites_html}
    <span class="tx-ball tx-pb">{pick.powerball:02d}</span>
  </div>
  <div class="tx-score">Score {pick.score:.2f}</div>
</div>
"""
        )

    board = f"""
<style>
  .tx-board {{
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    width: 100%;
    margin: 4px 0 8px 0;
  }}
  .tx-card {{
    flex: 1 1 168px;
    min-width: min(100%, 156px);
    max-width: 320px;
    background: {card_bg};
    border: 1px solid {card_border};
    border-radius: 16px;
    padding: 14px 12px 12px;
    box-sizing: border-box;
    box-shadow: 0 8px 24px rgba(0,0,0,0.12);
  }}
  .tx-play {{
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: {play_c};
    margin-bottom: 10px;
  }}
  .tx-row {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: 6px;
  }}
  .tx-ball {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: clamp(34px, 8vw, 42px);
    height: clamp(34px, 8vw, 42px);
    border-radius: 50%;
    font-weight: 800;
    font-size: clamp(0.78rem, 2.4vw, 0.95rem);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
    line-height: 1;
    user-select: none;
  }}
  .tx-white {{
    background: {white_ball};
    color: {white_text};
    box-shadow: {white_shadow};
    border: 1px solid rgba(15,23,42,0.06);
  }}
  .tx-pb {{
    background: {pb_ball};
    color: #FFFFFF;
    box-shadow: 0 3px 10px rgba(225, 29, 72, 0.45);
    margin-left: 2px;
  }}
  .tx-score {{
    margin-top: 10px;
    text-align: center;
    font-size: 0.72rem;
    color: {score_c};
    font-variant-numeric: tabular-nums;
  }}
  @media (max-width: 480px) {{
    .tx-card {{
      flex: 1 1 100%;
      max-width: 100%;
    }}
    .tx-ball {{
      width: 40px;
      height: 40px;
      font-size: 0.9rem;
    }}
  }}
</style>
<div class="tx-board">
  {"".join(cards)}
</div>
"""
    st.html(board)


def ensure_result(strategy_name: str, n_plays: int, spent: float, use_seed, drawings):
    """Generate or reuse picks when strategy / play count changes."""
    cls = STRATEGY_REGISTRY[strategy_name]
    strat = cls(drawings, seed=use_seed)
    force = st.session_state.pop("force_generate", False)
    prev = st.session_state.get("last_result")
    need = (
        force
        or prev is None
        or st.session_state.get("last_strategy") != strategy_name
        or len(prev.picks) != n_plays
        or st.session_state.get("last_seed") != use_seed
    )
    if need:
        result = strat.generate(n_picks=n_plays)
        st.session_state["last_result"] = result
        st.session_state["last_strategy"] = strategy_name
        st.session_state["last_budget"] = spent
        st.session_state["last_seed"] = use_seed
    else:
        result = prev
    return strat, result


def render_analysis(result, strategy_name: str) -> None:
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
        st.dataframe(
            pd.DataFrame(analysis["top_21_patterns"]),
            hide_index=True,
            width="stretch",
        )
    if "top_patterns" in analysis:
        st.markdown("**Top patterns used**")
        st.dataframe(
            pd.DataFrame(analysis["top_patterns"]),
            hide_index=True,
            width="stretch",
        )
    if "stable_patterns" in analysis:
        st.markdown("**Pseudo-history stable patterns**")
        st.dataframe(
            pd.DataFrame(analysis["stable_patterns"]),
            hide_index=True,
            width="stretch",
        )
    if "top_momentum_numbers" in analysis:
        st.markdown("**Momentum-favored numbers**")
        st.dataframe(
            pd.DataFrame(analysis["top_momentum_numbers"]),
            hide_index=True,
            width="stretch",
        )
    if "filter_rejects" in analysis:
        st.markdown("**Filter rejections while building**")
        st.json(analysis["filter_rejects"])
    if "rules" in analysis:
        st.markdown("**Rules**")
        for r in analysis["rules"]:
            st.write(f"- {r}")
    if "pool" in analysis:
        pool = analysis["pool"]
        st.markdown("**Wheel pool (white balls)**")
        st.write(" ".join(f"{n:02d}" for n in pool))
    if "coverage" in analysis:
        st.markdown("**Coverage stats**")
        st.json(analysis["coverage"])
    if "why_this_matters" in analysis:
        st.markdown("**Why this matters**")
        st.write(analysis["why_this_matters"])
    if "budget_note" in analysis:
        st.caption(analysis["budget_note"])
    if "column_bounds" in analysis or strategy_name.startswith("Patterns"):
        st.markdown("**Column layout (1–69)**")
        st.write(
            " | ".join(
                f"Col{i + 1}: {lo}–{hi}" for i, (lo, hi) in enumerate(COLUMN_BOUNDS)
            )
        )
    extra = {k: v for k, v in analysis.items() if k not in _ANALYSIS_SKIP}
    if extra:
        with st.expander("Raw analysis dict", icon=":material/data_object:"):
            st.json(extra)


def render_ticket_check_tab(drawings) -> None:
    """Upload / OCR a physical ticket and match against official draw history."""
    with st.container(border=True):
        st.markdown("#### Scan your ticket")
        st.caption(
            "Upload a clear photo of your Powerball ticket. We OCR the draw date and "
            "each play, then compare them to the official drawing for that date."
        )

        uploaded = st.file_uploader(
            "Ticket image",
            type=["png", "jpg", "jpeg", "webp", "bmp"],
            help="Phone photos work best when the ticket fills the frame, is flat, and well lit.",
            key="ticket_image_upload",
        )

        with st.expander("Or paste ticket text", icon=":material/content_paste:"):
            pasted = st.text_area(
                "OCR / ticket text",
                height=140,
                placeholder=(
                    "DRAW DATE 08/03/2026\n"
                    "A  08 30 41 48 54  04\n"
                    "B  06 17 27 48 50  05"
                ),
                key="ticket_text_paste",
                label_visibility="collapsed",
            )

        col_run, col_date = st.columns([1, 1], vertical_alignment="bottom")
        with col_date:
            override = st.date_input(
                "Draw date override (optional)",
                value=None,
                help="Use if OCR misread the date, or the ticket date is hard to read.",
                key="ticket_date_override",
            )
        with col_run:
            run = st.button(
                "Check ticket",
                type="primary",
                icon=":material/document_scanner:",
                width="stretch",
                key="ticket_check_btn",
            )

    if not run and "ticket_check_result" not in st.session_state:
        with st.container(border=True):
            st.markdown("##### How it works")
            st.markdown(
                """
1. Upload a photo of your ticket (or paste the numbers).
2. We read the **draw date** and every **5 whites + Powerball** line.
3. We look up that date in official history and score each play
   (white hits, Powerball hit, standard prize tier).

**Tips:** Good lighting, no glare, ticket flat and in focus. If OCR is messy, paste the numbers manually.
                """
            )
        return

    parse: TicketParseResult | None = None
    err: str | None = None

    if run:
        with st.spinner("Reading ticket…"):
            try:
                if uploaded is not None:
                    parse = parse_ticket_image(uploaded.getvalue())
                elif pasted and pasted.strip():
                    parse = parse_ticket_text(pasted, engine="manual")
                else:
                    err = "Upload a ticket image or paste the ticket text first."
            except Exception as exc:
                err = f"Could not read the ticket: {exc}"

        if err:
            st.error(err, icon=":material/error:")
            return

        assert parse is not None
        # Allow editing OCR before final match stored
        st.session_state["ticket_parse_raw"] = parse.raw_text
        st.session_state["ticket_parse_engine"] = parse.engine
        st.session_state["ticket_parse_date"] = parse.draw_date
        st.session_state["ticket_parse_plays"] = [
            {
                "label": p.label,
                "whites": list(p.whites),
                "powerball": p.powerball,
                "source_line": p.source_line,
            }
            for p in parse.plays
        ]
        st.session_state["ticket_parse_warnings"] = list(parse.warnings)

    # Rebuild parse from session (supports re-check after manual edits)
    raw = st.session_state.get("ticket_parse_raw", "")
    if not raw and not st.session_state.get("ticket_parse_plays"):
        return

    engine = st.session_state.get("ticket_parse_engine", "unknown")
    stored_plays = st.session_state.get("ticket_parse_plays") or []
    stored_date = st.session_state.get("ticket_parse_date")
    warnings = st.session_state.get("ticket_parse_warnings") or []

    with st.container(border=True):
        st.markdown("#### OCR result")
        st.caption(f"Engine: `{engine}` · edit anything below if the scan misread a number")

        with st.expander("Raw OCR text", expanded=False, icon=":material/notes:"):
            edited_raw = st.text_area(
                "Raw text",
                value=raw,
                height=160,
                key="ticket_raw_edit",
                label_visibility="collapsed",
            )
            if st.button("Re-parse from edited text", icon=":material/restart_alt:"):
                reparsed = parse_ticket_text(edited_raw, engine=f"{engine}+edit")
                st.session_state["ticket_parse_raw"] = reparsed.raw_text
                st.session_state["ticket_parse_engine"] = reparsed.engine
                st.session_state["ticket_parse_date"] = reparsed.draw_date
                st.session_state["ticket_parse_plays"] = [
                    {
                        "label": p.label,
                        "whites": list(p.whites),
                        "powerball": p.powerball,
                        "source_line": p.source_line,
                    }
                    for p in reparsed.plays
                ]
                st.session_state["ticket_parse_warnings"] = list(reparsed.warnings)
                st.rerun()

        for w in warnings:
            st.warning(w, icon=":material/warning:")

        default_date = override or stored_date
        final_date = st.date_input(
            "Draw date used for matching",
            value=default_date,
            key="ticket_final_date",
        )

        # Editable plays table
        if stored_plays:
            edit_df = pd.DataFrame(
                [
                    {
                        "Play": p.get("label") or str(i + 1),
                        "W1": p["whites"][0] if len(p["whites"]) > 0 else None,
                        "W2": p["whites"][1] if len(p["whites"]) > 1 else None,
                        "W3": p["whites"][2] if len(p["whites"]) > 2 else None,
                        "W4": p["whites"][3] if len(p["whites"]) > 3 else None,
                        "W5": p["whites"][4] if len(p["whites"]) > 4 else None,
                        "PB": p["powerball"],
                    }
                    for i, p in enumerate(stored_plays)
                ]
            )
        else:
            edit_df = pd.DataFrame(
                columns=["Play", "W1", "W2", "W3", "W4", "W5", "PB"]
            )

        st.markdown("##### Plays on ticket")
        edited = st.data_editor(
            edit_df,
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            column_config={
                "Play": st.column_config.TextColumn("Play", width="small"),
                "W1": st.column_config.NumberColumn("W1", min_value=1, max_value=69, step=1),
                "W2": st.column_config.NumberColumn("W2", min_value=1, max_value=69, step=1),
                "W3": st.column_config.NumberColumn("W3", min_value=1, max_value=69, step=1),
                "W4": st.column_config.NumberColumn("W4", min_value=1, max_value=69, step=1),
                "W5": st.column_config.NumberColumn("W5", min_value=1, max_value=69, step=1),
                "PB": st.column_config.NumberColumn("PB", min_value=1, max_value=26, step=1),
            },
            key="ticket_plays_editor",
        )

        if st.button(
            "Match against official drawing",
            type="primary",
            icon=":material/verified:",
            key="ticket_match_btn",
        ):
            from utils.ticket_ocr import TicketPlay

            plays = []
            for _, row in edited.iterrows():
                try:
                    whites = sorted(
                        int(row[c])
                        for c in ("W1", "W2", "W3", "W4", "W5")
                        if pd.notna(row[c])
                    )
                    pb = int(row["PB"])
                    if len(whites) != 5 or len(set(whites)) != 5:
                        continue
                    if not all(1 <= w <= 69 for w in whites):
                        continue
                    if not (1 <= pb <= 26):
                        continue
                    plays.append(
                        TicketPlay(
                            whites=tuple(whites),
                            powerball=pb,
                            label=str(row.get("Play") or ""),
                        )
                    )
                except (TypeError, ValueError):
                    continue

            rebuilt = TicketParseResult(
                raw_text=st.session_state.get("ticket_raw_edit", raw),
                draw_date=final_date,
                plays=plays,
                confidence_note=f"{len(plays)} play(s) ready to match",
                engine=engine,
                warnings=[],
            )
            result = check_ticket(rebuilt, drawings, override_date=final_date)
            st.session_state["ticket_check_result"] = result

    result = st.session_state.get("ticket_check_result")
    if not result:
        return

    with st.container(border=True):
        st.markdown("#### Match result")
        st.markdown(f"**{result.summary}**")

        if result.drawing is not None:
            d = result.drawing
            draw_label = (
                d.date.strftime("%A, %B %d, %Y")
                if hasattr(d.date, "strftime")
                else str(d.date)
            )
            st.caption(
                f"Official drawing · {draw_label} "
                f"· Whites **{' '.join(f'{n:02d}' for n in d.whites)}** · "
                f"Powerball **{d.powerball:02d}**"
                + (f" · Power Play ×{d.multiplier}" if d.multiplier else "")
            )
            if result.date_status == "nearest":
                st.info(
                    "Matched the nearest official draw date (ticket date was close but not exact).",
                    icon=":material/info:",
                )
            elif result.date_status == "exact":
                st.success("Draw date matches official history exactly.", icon=":material/check_circle:")

        if result.matches:
            rows = []
            for i, m in enumerate(result.matches, 1):
                rows.append(
                    {
                        "Play": m.play.label or str(i),
                        "Your numbers": m.play.display(),
                        "White hits": m.white_hits,
                        "Matched whites": " ".join(f"{n:02d}" for n in m.matched_whites)
                        or "—",
                        "Powerball": "Yes" if m.powerball_hit else "No",
                        "Tier": m.tier_label,
                        "Prize": m.prize,
                    }
                )
            st.dataframe(
                pd.DataFrame(rows),
                hide_index=True,
                width="stretch",
                column_config={
                    "White hits": st.column_config.ProgressColumn(
                        "White hits",
                        min_value=0,
                        max_value=5,
                        format="%d",
                    ),
                    "Prize": st.column_config.TextColumn("Prize", width="medium"),
                },
            )

            any_win = any(m.prize != "$0" for m in result.matches)
            if any_win:
                st.balloons()
            st.caption(
                "Prize amounts are standard Powerball tiers without Power Play multiplier. "
                "Confirm with the official lottery site before claiming."
            )
        elif result.drawing is not None:
            st.warning("No plays available to score.", icon=":material/warning:")


def main():
    st.set_page_config(
        page_title="TxPowerball",
        page_icon=":material/casino:",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # —— Sidebar: session controls only ————————————————————————————————
    with st.sidebar:
        st.markdown("### TxPowerball")
        st.caption("Strategy picks · $10 sessions by default")

        budget = st.number_input(
            "Bankroll this session ($)",
            min_value=2.0,
            max_value=200.0,
            value=DEFAULT_BUDGET,
            step=2.0,
            help="Always assume $10 unless you change it. Base play = $2.",
            key="budget",
        )
        power_play = st.checkbox(
            "Include Power Play (+$1/play)",
            value=False,
            help="Power Play multiplies non-jackpot prizes; costs $1 extra per play.",
            key="power_play",
        )
        n_plays = plays_for_budget(budget, power_play)
        unit = 3.0 if power_play else 2.0
        spent = n_plays * unit

        with st.container(horizontal=True, gap="small"):
            st.metric("Plays", n_plays, border=True)
            st.metric("Cost", f"${spent:.0f}", border=True)

        if spent < budget:
            st.caption(f"${budget - spent:.0f} unspent (not enough for another play).")
        if power_play:
            st.caption(f"${unit:.0f} × {n_plays} with Power Play")
        else:
            st.caption(f"${unit:.0f} × {n_plays} base plays")

        strategy_keys = list(STRATEGY_REGISTRY.keys())
        default_idx = (
            strategy_keys.index(DEFAULT_STRATEGY)
            if DEFAULT_STRATEGY in strategy_keys
            else 0
        )
        strategy_name = st.selectbox(
            "Strategy",
            options=strategy_keys,
            index=default_idx,
            help="Start with Unpopular (anti-share) or Wheel for practical multi-ticket play.",
            key="strategy_name",
        )
        seed = st.number_input(
            "Random seed (optional)",
            min_value=0,
            max_value=10_000_000,
            value=0,
            help="Set non-zero for reproducible picks.",
            key="seed",
        )
        use_seed = seed if seed != 0 else None

        st.space("small")
        generate = st.button(
            "Generate picks",
            type="primary",
            width="stretch",
            icon=":material/auto_awesome:",
        )
        refresh = st.button(
            "Refresh history",
            width="stretch",
            icon=":material/cloud_sync:",
            help="Pull latest draws from NY Open Data + Texas Lottery",
        )

        st.space("medium")
        with st.expander("Responsible play", icon=":material/shield:"):
            st.markdown(
                """
- Don't bet money you can't afford to lose
- Lottery odds remain extreme; strategies organize numbers, they don't beat math
- One session = your budget above — stick to it
"""
            )
        st.caption("Data · NY Open Data + Texas Lottery · modern matrix")

    # —— Load history ————————————————————————————————————————————————
    try:
        drawings = get_drawings(refresh=bool(refresh))
    except Exception as e:
        st.error(f"Could not load history: {e}", icon=":material/error:")
        return

    if not drawings:
        st.error("No drawings loaded.", icon=":material/error:")
        return

    if generate:
        st.session_state["force_generate"] = True

    last = drawings[-1]
    strat, result = ensure_result(strategy_name, n_plays, spent, use_seed, drawings)

    # —— Header ——————————————————————————————————————————————————————
    st.markdown("## TxPowerball")
    st.caption(
        "Powerball strategy number picker · adapted from "
        "[PawnPower strategies](https://pawnpower.net/Home/Strategies) · "
        f"default **${DEFAULT_BUDGET:.0f}** → "
        f"**{int(DEFAULT_BUDGET // PLAY_COST)} plays** @ ${PLAY_COST:.0f}"
    )

    with st.container(horizontal=True, gap="small"):
        st.metric(
            "Drawings analyzed",
            f"{len(drawings):,}",
            border=True,
            icon=":material/database:",
        )
        st.metric(
            "Latest draw",
            last.date.strftime("%Y-%m-%d"),
            border=True,
            icon=":material/calendar_today:",
        )
        st.metric(
            "Latest whites",
            " ".join(f"{n:02d}" for n in last.whites),
            border=True,
            icon=":material/filter_5:",
        )
        st.metric(
            "Latest Powerball",
            f"{last.powerball:02d}",
            border=True,
            icon=":material/circle:",
        )

    st.space("small")

    tab_pick, tab_check, tab_strategy, tab_data, tab_about = st.tabs(
        [
            ":material/confirmation_number: Your tickets",
            ":material/document_scanner: Check ticket",
            ":material/analytics: Strategy detail",
            ":material/bar_chart: History & stats",
            ":material/menu_book: About strategies",
        ],
        key="main_tabs",
        on_change="rerun",
    )

    # —— Tab: Your tickets ———————————————————————————————————————————
    with tab_pick:
        if tab_pick.open:
            with st.container(border=True):
                head_l, head_r = st.columns([3, 1], vertical_alignment="center")
                with head_l:
                    st.markdown(f"#### {strategy_name}")
                    st.caption(getattr(strat, "description", "") or "")
                with head_r:
                    st.badge(
                        f"${st.session_state.get('last_budget', spent):.0f} session",
                        icon=":material/payments:",
                        color="red",
                    )

                st.caption(result.explanation)

                st.markdown("##### Ticket board")
                render_ticket_board(result.picks)

                st.markdown("##### Spreadsheet view")
                df = ticket_table(result.picks)
                st.dataframe(
                    df,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Play": st.column_config.NumberColumn("Play", width="small"),
                        "Score": st.column_config.NumberColumn(
                            "Score", format="%.2f", width="small"
                        ),
                        "Powerball": st.column_config.TextColumn(
                            "Powerball", width="small"
                        ),
                    },
                )

                with st.container(horizontal=True, gap="small"):
                    csv = df.to_csv(index=False)
                    st.download_button(
                        "Download tickets CSV",
                        data=csv,
                        file_name="txpowerball_picks.csv",
                        mime="text/csv",
                        icon=":material/download:",
                    )
                    if st.button(
                        "Regenerate",
                        icon=":material/refresh:",
                        help="New picks with the current settings",
                    ):
                        st.session_state["force_generate"] = True
                        st.rerun()

            st.space("small")

            with st.expander(
                "Per-ticket notes",
                icon=":material/notes:",
                expanded=False,
            ):
                for i, pick in enumerate(result.picks, 1):
                    st.markdown(f"**Play {i}** — `{html.escape(pick.display())}`")
                    if pick.notes:
                        for note in pick.notes:
                            st.caption(f"• {note}")
                    else:
                        st.caption("• No extra notes for this play.")

            with st.container(border=True):
                st.markdown("##### Compare to latest drawing")
                st.caption(
                    "After the draw, use this to see how your saved numbers matched."
                )
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
                st.dataframe(
                    pd.DataFrame(match_rows),
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "Play": st.column_config.NumberColumn(width="small"),
                        "White matches": st.column_config.ProgressColumn(
                            "White matches",
                            min_value=0,
                            max_value=5,
                            format="%d",
                        ),
                    },
                )

    # —— Tab: Check ticket (OCR) ————————————————————————————————————
    with tab_check:
        if tab_check.open:
            render_ticket_check_tab(drawings)

    # —— Tab: Strategy detail ————————————————————————————————————————
    with tab_strategy:
        if tab_strategy.open:
            with st.container(border=True):
                st.markdown(f"#### Analysis — {result.strategy_name}")
                if not result.analysis:
                    st.caption("This strategy did not return structured analysis.")
                else:
                    render_analysis(result, strategy_name)

    # —— Tab: History & stats ————————————————————————————————————————
    with tab_data:
        if tab_data.open:
            with st.container(border=True):
                st.markdown("#### Recent drawings")
                recent_n = st.slider("Show last N draws", 5, 50, 15, key="recent_n")
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
                st.dataframe(
                    pd.DataFrame(rows),
                    hide_index=True,
                    width="stretch",
                )

            st.space("small")

            with st.container(border=True):
                st.markdown("#### White ball frequency (modern era)")
                wf = white_frequency(drawings)
                freq_df = pd.DataFrame(
                    {"number": list(wf.keys()), "hits": list(wf.values())}
                ).sort_values("number")
                st.bar_chart(freq_df.set_index("number"), color="#E11D48")

            st.space("small")

            # Horizontal wrap → stacks cleanly on phones
            with st.container(horizontal=True, gap="medium"):
                with st.container(border=True):
                    st.markdown("**Coldest (longest since hit)**")
                    cold = last_seen(drawings)
                    cold_sorted = sorted(cold.items(), key=lambda x: -x[1])[:15]
                    st.dataframe(
                        pd.DataFrame(
                            cold_sorted, columns=["Number", "Draws since hit"]
                        ),
                        hide_index=True,
                        width="stretch",
                    )
                with st.container(border=True):
                    st.markdown("**Hottest (most hits, modern era)**")
                    hot = sorted(wf.items(), key=lambda x: -x[1])[:15]
                    st.dataframe(
                        pd.DataFrame(hot, columns=["Number", "Hits"]),
                        hide_index=True,
                        width="stretch",
                    )

            st.space("small")

            with st.container(border=True):
                st.markdown("#### Powerball frequency")
                pbf = powerball_frequency(drawings)
                pb_df = pd.DataFrame(
                    {"PB": list(pbf.keys()), "hits": list(pbf.values())}
                ).sort_values("PB")
                st.bar_chart(pb_df.set_index("PB"), color="#38BDF8")

            st.space("small")

            with st.container(border=True):
                st.markdown("#### Top 5-column patterns")
                pf = pattern_frequency(drawings)
                top_p = sorted(pf.items(), key=lambda x: -x[1])[:21]
                st.dataframe(
                    pd.DataFrame(
                        [
                            {"pattern": "-".join(map(str, p)), "count": c}
                            for p, c in top_p
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )
                st.caption(
                    "Columns: "
                    + ", ".join(
                        f"{i + 1}=[{lo}-{hi}]"
                        for i, (lo, hi) in enumerate(COLUMN_BOUNDS)
                    )
                )

            st.space("small")

            with st.container(border=True):
                st.markdown("#### Short-term activity (last 20 draws)")
                st.dataframe(
                    pd.DataFrame(
                        sorted(
                            short_term_activity(drawings, 20).items(),
                            key=lambda x: -x[1],
                        )[:20],
                        columns=["Number", "Hits in last 20"],
                    ),
                    hide_index=True,
                    width="stretch",
                )

    # —— Tab: About ——————————————————————————————————————————————————
    with tab_about:
        if tab_about.open:
            with st.container(border=True):
                st.markdown(
                    """
### Practical strategies (math-backed structure / share risk)

| Strategy | What we implement |
|---|---|
| **Unpopular (Anti-Share)** | Mostly numbers >31; ban birthday-heavy sets, arithmetic sequences, multiples clusters; diverse endings. Same hit odds; lower jackpot split risk |
| **Wheel ($10 Coverage)** | Unpopular-leaning pool of 7 whites (for 5 plays) spread across tickets via greedy pair coverage. Structures multi-ticket spend; does not raise jackpot odds |

### Strategies (from PawnPower)

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
