#!/usr/bin/env python3
"""Build a static site in docs/ for GitHub Pages."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
DASHBOARD_SRC = ROOT / "dashboard"
STATS_SRC = ROOT / "data" / "stats"
PROFILES_SRC = ROOT / "data" / "steam_profiles.json"
CUSTOM_DOMAIN = "chattrak.goodvibes.gg"


def build(output_dir: Path = DOCS) -> None:
    if not STATS_SRC.exists():
        raise FileNotFoundError(
            f"Missing {STATS_SRC}. Run: python analyze_chat_stats.py"
        )

    if output_dir.exists():
        shutil.rmtree(output_dir)

    output_dir.mkdir(parents=True)
    stats_dst = output_dir / "data" / "stats"
    profiles_dst = output_dir / "data" / "steam_profiles.json"

    for item in DASHBOARD_SRC.iterdir():
        if item.is_file():
            shutil.copy2(item, output_dir / item.name)

    shutil.copytree(STATS_SRC, stats_dst)

    if PROFILES_SRC.exists():
        profiles_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROFILES_SRC, profiles_dst)

    (output_dir / "CNAME").write_text(f"{CUSTOM_DOMAIN}\n", encoding="utf-8")

    print(f"Built GitHub Pages site at {output_dir}")
    print(f"  https://{CUSTOM_DOMAIN}/")
    print("  index.html, app.js, styles.css - dashboard UI at site root")
    print("  data/stats/ - leaderboard JSON")
    if profiles_dst.exists():
        print("  data/steam_profiles.json - avatars and names")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DOCS,
        help="Output directory (default: docs/)",
    )
    args = parser.parse_args()

    try:
        build(args.output_dir)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
