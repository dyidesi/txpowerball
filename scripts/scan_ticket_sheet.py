#!/usr/bin/env python3
"""
Local CLI: scan every Powerball ticket region in a sheet photo.

Does not invent numbers — only reports plays validated from OCR text
(5 whites in 1–69 + Powerball in 1–26). Unreadable tickets are marked failed.

Example:
  python scripts/scan_ticket_sheet.py
  python scripts/scan_ticket_sheet.py Powerball-2026-08-08.jpg --out-dir ./scan_out
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from repo root or scripts/
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.sheet_scanner import scan_sheet, write_results  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="OCR all Powerball tickets on a multi-ticket sheet photo (no invented numbers)."
    )
    parser.add_argument(
        "image",
        nargs="?",
        default=str(ROOT / "Powerball-2026-08-08.jpg"),
        help="Path to sheet photo (default: Powerball-2026-08-08.jpg in project root)",
    )
    parser.add_argument(
        "--out-dir",
        default="",
        help="Directory for JSON/CSV/crops (default: <image_stem>_scan next to image)",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=4.0,
        help="Sheet upscale factor before detection/OCR (default: 4)",
    )
    parser.add_argument(
        "--cols",
        type=int,
        default=None,
        help="Force grid column count (default: auto)",
    )
    parser.add_argument(
        "--rows",
        type=int,
        default=None,
        help="Force grid row count (default: auto)",
    )
    parser.add_argument(
        "--max-tickets",
        type=int,
        default=None,
        help="Optional cap for debugging",
    )
    parser.add_argument(
        "--no-crops",
        action="store_true",
        help="Do not write per-ticket crop PNGs",
    )
    args = parser.parse_args(argv)

    image_path = Path(args.image)
    if not image_path.is_file():
        print(f"ERROR: image not found: {image_path}", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir) if args.out_dir else image_path.with_name(
        image_path.stem + "_scan"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    crop_dir = None if args.no_crops else out_dir / "crops"

    print(f"Image: {image_path.resolve()}")
    print(f"Enhance scale: {args.scale}")
    print(f"Output: {out_dir.resolve()}")

    summary = scan_sheet(
        image_path,
        enhance_scale=args.scale,
        save_crop_dir=crop_dir,
        cols=args.cols,
        rows=args.rows,
        max_tickets=args.max_tickets,
    )

    json_path = out_dir / "multi_ticket_results.json"
    csv_path = out_dir / "multi_ticket_results.csv"
    write_results(summary, json_path=json_path, csv_path=csv_path)

    print("--- summary ---")
    print(f"image_size: {summary.image_size[0]}x{summary.image_size[1]}")
    print(f"tickets_detected: {summary.tickets_detected}")
    print(f"tickets_ok: {summary.tickets_ok}")
    print(f"tickets_failed: {summary.tickets_failed}")
    print(f"plays_extracted: {summary.plays_extracted}")
    print(f"json: {json_path}")
    print(f"csv: {csv_path}")

    if summary.plays_extracted:
        print("--- plays ---")
        for r in summary.results:
            for p in r.plays:
                w = " ".join(f"{n:02d}" for n in p.whites)
                print(
                    f"{r.ticket_id} {p.play_label or '-':2s}  {w}  PB {p.powerball:02d}"
                )
    else:
        print(
            "No complete plays extracted. Low-resolution sheets often yield "
            "ocr_empty_or_failed / ocr_no_digits — tickets are listed as failed, "
            "not filled with invented numbers."
        )
        # show failure breakdown
        reasons: dict[str, int] = {}
        for r in summary.results:
            reasons[r.failure_reason or r.status] = (
                reasons.get(r.failure_reason or r.status, 0) + 1
            )
        print("failure_reasons:", reasons)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
