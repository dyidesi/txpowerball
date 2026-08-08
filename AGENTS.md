# Agent rules — TxPowerball (Streamlit Cloud)

## Deploy config is production-critical

This app runs on **Streamlit Community Cloud** (`txpowerball.streamlit.app`).
Broken `packages.txt` or `requirements.txt` takes the whole site down at **boot**, not at first OCR click.

### `packages.txt` (hard rules)

Streamlit Cloud runs something equivalent to `apt-get install $(cat packages.txt)`.
**There is no comment syntax.**

- **Never** put `#` comments, prose, or multi-word lines in `packages.txt`
- **Exactly one** Debian package name per non-empty line
- Valid names only: lowercase `a-z0-9+._-` (e.g. `libgl1`, `libglib2.0-0`, `tesseract-ocr`)
- Document purpose in **README.md**, not in `packages.txt`

A comment like `# Streamlit Cloud OCR` was once shipped and Cloud failed with:
`Unable to locate package Streamlit` / `Community` / `Cloud` / …

### `requirements.txt`

- Prefer **`opencv-python-headless`**, never `opencv-python` (pulls libGL / GUI deps)
- Keep OCR stack installable on Linux Cloud: RapidOCR + onnxruntime + headless OpenCV

### Before every push that touches deploy files

```bash
python scripts/validate_deploy.py
python -m pytest tests/test_streamlit_cloud_config.py -v
```

CI (`.github/workflows/ci.yml`) runs the same checks on `main` / PRs. Do not merge if CI fails.

### After Cloud-related pushes

Remind the user to **Manage app → Reboot** so apt packages reinstall. Reboot is not optional for `packages.txt` changes.
