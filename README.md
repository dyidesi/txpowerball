# Powerball Strategy Number Picker

Streamlit app that generates Powerball tickets using selection strategies described at
[PawnPower — Strategies](https://pawnpower.net/Home/Strategies).

**Default bankroll:** $10 per session → **5 plays** at $2 each.

## Strategies

| Strategy | Idea |
|---|---|
| Due Numbers | Long-term cold + short-term activity; 1–2 elite due balls per line |
| Patterns (5-Column) | Frequent column hit templates (e.g. `1-1-0-1-2`) |
| Bar Graph Balance | Mix cold / mid / hot frequency bands |
| Line Graph Momentum | Prefer falling/flat short-term hit momentum |
| Repeats & Consecutive Filter | Cap consecutive runs and prior-draw repeats |
| Random (Pattern-Constrained) | Quick-pick style with pattern + history filters |
| Pseudo History Validated | Rank patterns under synthetic future draws |
| Automated (All Strategies) | Full pipeline combining all of the above |

## Setup

```bash
cd Powerball
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
streamlit run app.py
```

## Data

- Bundled CSV: `data/powerball_history.csv` (NY Open Data export)
- Sidebar **Refresh history** re-downloads from data.ny.gov
- Stats use modern matrix only (2015-10-07+): whites 1–69, Powerball 1–26

## Disclaimer

These strategies organize number selection; they do not beat lottery odds.
Never wager money you cannot afford to lose.
