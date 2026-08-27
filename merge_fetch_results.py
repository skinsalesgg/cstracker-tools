#!/usr/bin/env python3
"""Merge incremental fetch output into data/."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def player_key(entry: dict) -> str:
    return str(entry.get("steam_id") or entry.get("player") or entry.get("steam_url") or "")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def merge_incremental(incremental_dir: Path) -> None:
    by_player_path = DATA / "chat_history_by_player.json"
    flat_path = DATA / "chat_messages_flat.json"
    summary_path = DATA / "fetch_summary.json"

    for path in (by_player_path, flat_path, summary_path):
        if not path.exists():
            raise FileNotFoundError(f"Missing existing data file: {path}")

    inc_by_player = load_json(incremental_dir / "chat_history_by_player.json")
    inc_flat = load_json(incremental_dir / "chat_messages_flat.json")
    inc_summary = load_json(incremental_dir / "fetch_summary.json")

    by_player = {player_key(p): p for p in load_json(by_player_path)}
    replace_keys = {player_key(p) for p in inc_by_player}
    for player in inc_by_player:
        by_player[player_key(player)] = player

    flat = [m for m in load_json(flat_path) if player_key(m) not in replace_keys]
    flat.extend(inc_flat)

    players = {player_key(p): p for p in load_json(summary_path)["players"]}
    for player in inc_summary["players"]:
        players[player_key(player)] = player
    merged_players = list(players.values())

    summary = {
        "player_count": len(merged_players),
        "fetched_ok": sum(1 for p in merged_players if p.get("status") == "ok"),
        "not_on_cstracker": sum(
            1 for p in merged_players if p.get("status") == "not_on_cstracker"
        ),
        "no_chat": sum(
            1
            for p in merged_players
            if p.get("status") == "ok" and p.get("message_count", 0) == 0
        ),
        "errors": sum(1 for p in merged_players if p.get("status") == "error"),
        "players_with_messages": sum(
            1 for p in merged_players if p.get("message_count", 0) > 0
        ),
        "total_messages": sum(p.get("message_count", 0) for p in merged_players),
        "players": merged_players,
    }

    by_player_path.write_text(json.dumps(list(by_player.values()), indent=2) + "\n", encoding="utf-8")
    flat_path.write_text(json.dumps(flat, indent=2) + "\n", encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(
        f"Merged {len(inc_by_player)} player(s): "
        f"{summary['player_count']} total, "
        f"{summary['total_messages']} messages"
    )


def main() -> int:
    incremental_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DATA / "new_fetch_temp"
    if not incremental_dir.exists():
        print(f"Missing incremental dir: {incremental_dir}", file=sys.stderr)
        return 1
    merge_incremental(incremental_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
