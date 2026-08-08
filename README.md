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

Repo root includes:
- `requirements.txt` — Python deps (RapidOCR, headless OpenCV, …)
- `packages.txt` — apt leaf packages only: `libgl1` + `tesseract-ocr` (nothing else)

**`packages.txt` format (strict):**
- One Debian package name per line. **No comments, no prose, no spaces.**
- **Only leaf packages** — never pin `libglib2.0-0`, `libsm*`, `libx*` (breaks Debian trixie / t64).
- Allowlist enforced by `scripts/validate_deploy.py` (CI).

Validate before push:

```bash
python scripts/validate_deploy.py
python -m pytest tests/test_streamlit_cloud_config.py -v
```

After changing either file, **reboot the app** (or let Cloud rebuild) so system libraries install.

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

OCR prefers **RapidOCR** (`opencv-python-headless` + ONNX). On Streamlit Cloud, `packages.txt` installs `libgl1` (fixes `libGL.so.1` import errors) and **Tesseract** as a fallback. You can edit misread numbers before matching.

## Data

- Bundled CSV: `data/powerball_history.csv` (merged history)
- **Primary:** [NY Open Data](https://data.ny.gov/Government-Finance/Lottery-Powerball-Winning-Numbers-Beginning-2010/d6yy-54nr) full export
- **Secondary:** [Texas Lottery](https://www.texaslottery.com/export/sites/lottery/Games/Powerball/Winning_Numbers/powerball.csv) winning-numbers CSV (often posts the latest draw sooner)
- Sources are merged by draw date; NY wins on conflicts, Texas fills missing nights
- Sidebar **Refresh history** re-downloads both sources
- Stats use modern matrix only (2015-10-07+): whites 1–69, Powerball 1–26

## Disclaimer

These strategies organize number selection; they do not beat lottery odds.
Never wager money you cannot afford to lose.
