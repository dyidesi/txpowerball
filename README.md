# TxPowerball

Streamlit app that generates Powerball tickets using selection strategies described at
[PawnPower — Strategies](https://pawnpower.net/Home/Strategies).

**Live app:** [https://txpowerball.streamlit.app](https://txpowerball.streamlit.app)  
**Repo:** [github.com/dyidesi/txpowerball](https://github.com/dyidesi/txpowerball)

**Default bankroll:** $10 per session → **5 plays** at $2 each.

## Deploy (Streamlit Community Cloud)

1. Open [share.streamlit.io/deploy](https://share.streamlit.io/deploy) and sign in with GitHub (`dyidesi`).
2. Repository: `dyidesi/txpowerball` · Branch: `main` · Main file: `app.py`
3. App URL / custom subdomain: **`txpowerball`** → `https://txpowerball.streamlit.app`
4. Click **Deploy**

## Strategies

| Strategy | Idea |
|---|---|
| **Unpopular (Anti-Share)** | Avoid birthday/sequence/popular sets → lower jackpot split risk (same hit odds) |
| **Wheel ($10 Coverage)** | 7-number pool → 5 covering lines via greedy pair coverage |
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

## Check ticket (OCR)

On the **Check ticket** tab:

1. Upload a clear photo of your Powerball ticket (or paste the numbers).
2. The app OCRs the **draw date** and each **5 whites + Powerball** play.
3. It looks up that date in official history and reports white hits, Powerball match, and standard prize tier.

OCR uses **RapidOCR** (pip-only, no system Tesseract required). You can edit misread numbers before matching.

## Data

- Bundled CSV: `data/powerball_history.csv` (NY Open Data export)
- Sidebar **Refresh history** re-downloads from data.ny.gov
- Stats use modern matrix only (2015-10-07+): whites 1–69, Powerball 1–26

## Disclaimer

These strategies organize number selection; they do not beat lottery odds.
Never wager money you cannot afford to lose.
