# Agent rules — TxPowerball (Streamlit Cloud)

## Deploy config is production-critical

This app runs on **Streamlit Community Cloud** (`txpowerball.streamlit.app`).
Broken `packages.txt` or `requirements.txt` takes the whole site down at **boot**, not at first OCR click.

### `packages.txt` (hard rules)

Streamlit Cloud runs something equivalent to `apt-get install` on every line.
**There is no comment syntax.**

- **Never** put `#` comments, prose, or multi-word lines in `packages.txt`
- **Exactly one** Debian package name per non-empty line
- **Only leaf packages** we need — currently exactly:
  - `libgl1` (libGL for RapidOCR)
  - `tesseract-ocr` (OCR fallback)
- **Never pin transitive libs**: `libglib2.0-0`, `libsm6`, `libxext6`, `libxrender1`, `libffi7`, …
  Apt resolves those. Pinning old names breaks Debian **trixie** (`libglib2.0-0` vs `libglib2.0-0t64`).
- Document purpose in **README.md**, not in `packages.txt`
- To add a package: prove Cloud rebuild works, then add it to `ALLOWED_PACKAGES` in
  `scripts/validate_deploy.py` **and** to `packages.txt`

### Production incidents (do not repeat)

| Failure | Cause |
|--------|--------|
| `Unable to locate package Streamlit/Community/…` | Comment line in `packages.txt` |
| `libglib2.0-0` vs `libglib2.0-0t64` / held broken packages | Pinned `libglib2.0-0` + X11 libs with `tesseract-ocr` on trixie |

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
