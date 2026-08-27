#!/usr/bin/env python3
"""Analyze chat messages against configurable category rules and write leaderboard files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_INPUT = Path("data/chat_messages_flat.json")
DEFAULT_CONFIG = Path("configs/chat_categories.json")
DEFAULT_OUTPUT_DIR = Path("data/stats")


@dataclass(frozen=True)
class CategoryConfig:
    id: str
    label: str
    description: str
    match_type: str
    whole_word: bool
    case_sensitive: bool
    terms: list[str]
    patterns: list[re.Pattern[str]]


@dataclass
class PlayerStats:
    steam_id: str | None
    steam_url: str
    cstracker_url: str | None
    total_messages: int = 0
    match_count: int = 0
    matched_messages: list[dict[str, Any]] | None = None

    @property
    def rate_per_message(self) -> float:
        if self.total_messages == 0:
            return 0.0
        return self.match_count / self.total_messages


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def compile_category(raw: dict[str, Any]) -> CategoryConfig:
    category_id = raw["id"]
    label = raw.get("label", category_id)
    description = raw.get("description", "")
    match_type = raw.get("match_type", "terms")
    whole_word = bool(raw.get("whole_word", True))
    case_sensitive = bool(raw.get("case_sensitive", False))
    flags = 0 if case_sensitive else re.IGNORECASE

    patterns: list[re.Pattern[str]] = []
    terms = [str(term) for term in raw.get("terms", [])]

    if match_type == "terms":
        for term in terms:
            escaped = re.escape(term)
            body = rf"\b{escaped}\b" if whole_word else escaped
            patterns.append(re.compile(body, flags))
    elif match_type == "regex":
        for pattern in raw.get("patterns", []):
            patterns.append(re.compile(str(pattern), flags))
    else:
        raise ValueError(f"Unsupported match_type {match_type!r} for category {category_id}")

    if not patterns:
        raise ValueError(f"Category {category_id} has no terms or patterns configured")

    return CategoryConfig(
        id=category_id,
        label=label,
        description=description,
        match_type=match_type,
        whole_word=whole_word,
        case_sensitive=case_sensitive,
        terms=terms,
        patterns=patterns,
    )


def count_matches(text: str, patterns: list[re.Pattern[str]]) -> int:
    total = 0
    for pattern in patterns:
        total += len(pattern.findall(text))
    return total


def player_key(message: dict[str, Any]) -> str:
    return str(message.get("steam_id") or message.get("steam_url") or "unknown")


def analyze_category(
    messages: list[dict[str, Any]],
    category: CategoryConfig,
    *,
    include_examples: bool,
    example_limit: int,
) -> dict[str, Any]:
    players: dict[str, PlayerStats] = {}

    for row in messages:
        key = player_key(row)
        if key not in players:
            players[key] = PlayerStats(
                steam_id=row.get("steam_id"),
                steam_url=row.get("steam_url", key),
                cstracker_url=row.get("cstracker_url"),
                matched_messages=[] if include_examples else None,
            )

        player = players[key]
        player.total_messages += 1

        text = str(row.get("message", ""))
        hits = count_matches(text, category.patterns)
        if hits == 0:
            continue

        player.match_count += hits
        if include_examples and player.matched_messages is not None:
            if len(player.matched_messages) < example_limit:
                player.matched_messages.append(
                    {
                        "message": text,
                        "hits": hits,
                        "map_name": row.get("map_name"),
                        "played_at": row.get("played_at"),
                        "chat_url": row.get("chat_url"),
                    }
                )

    leaderboard = []
    for player in players.values():
        entry = {
            "steam_id": player.steam_id,
            "steam_url": player.steam_url,
            "cstracker_url": player.cstracker_url,
            "total_messages": player.total_messages,
            "match_count": player.match_count,
            "rate_per_message": round(player.rate_per_message, 6),
        }
        if include_examples and player.matched_messages is not None:
            entry["examples"] = player.matched_messages
        leaderboard.append(entry)

    leaderboard.sort(key=lambda row: (-row["match_count"], -row["rate_per_message"]))
    players_with_matches = sum(1 for row in leaderboard if row["match_count"] > 0)

    return {
        "category_id": category.id,
        "category_label": category.label,
        "description": category.description,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_message_count": len(messages),
        "player_count": len(leaderboard),
        "players_with_matches": players_with_matches,
        "total_matches": sum(row["match_count"] for row in leaderboard),
        "leaderboard": leaderboard,
    }


def write_outputs(
    *,
    results: list[dict[str, Any]],
    config_path: Path,
    input_path: Path,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    for result in results:
        out_path = output_dir / f"{result['category_id']}.json"
        out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    index = {
        "generated_at": datetime.now(UTC).isoformat(),
        "input_file": str(input_path),
        "config_file": str(config_path),
        "categories": [
            {
                "id": result["category_id"],
                "label": result["category_label"],
                "description": result["description"],
                "file": f"{result['category_id']}.json",
                "player_count": result["player_count"],
                "players_with_matches": result["players_with_matches"],
                "total_matches": result["total_matches"],
            }
            for result in results
        ],
    }
    (output_dir / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--include-examples",
        action="store_true",
        help="Include sample matched messages per player in category output files",
    )
    parser.add_argument(
        "--example-limit",
        type=int,
        default=5,
        help="Max example messages per player when --include-examples is set",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.input.exists():
        print(f"Input file not found: {args.input}", file=sys.stderr)
        return 1
    if not args.config.exists():
        print(f"Config file not found: {args.config}", file=sys.stderr)
        return 1

    messages = load_json(args.input)
    if not isinstance(messages, list):
        print("Input JSON must be a list of chat messages", file=sys.stderr)
        return 1

    config = load_json(args.config)
    categories = [compile_category(raw) for raw in config.get("categories", [])]
    if not categories:
        print("No categories configured", file=sys.stderr)
        return 1

    results = [
        analyze_category(
            messages,
            category,
            include_examples=args.include_examples,
            example_limit=args.example_limit,
        )
        for category in categories
    ]
    write_outputs(
        results=results,
        config_path=args.config,
        input_path=args.input,
        output_dir=args.output_dir,
    )

    for result in results:
        print(
            f"{result['category_label']}: "
            f"{result['total_matches']} matches · "
            f"{result['players_with_matches']}/{result['player_count']} players"
        )
    print(f"Wrote stats to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
