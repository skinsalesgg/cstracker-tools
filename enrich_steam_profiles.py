#!/usr/bin/env python3
"""Fetch Steam persona names and avatars for profiles in fetch_summary.json."""

from __future__ import annotations

import argparse
import html
import json
import random
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from curl_cffi import requests
from curl_cffi.requests.errors import RequestsError
from curl_cffi.requests.exceptions import HTTPError

DEFAULT_SUMMARY = Path("data/fetch_summary.json")
DEFAULT_OUTPUT = Path("data/steam_profiles.json")


def log(message: str) -> None:
    print(message, file=sys.stderr)


def xml_text(root: ET.Element, tag: str) -> str | None:
    element = root.find(tag)
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def profile_url_from_parts(steam_id: str, custom_url: str | None) -> str:
    if custom_url:
        return f"https://steamcommunity.com/id/{custom_url}"
    return f"https://steamcommunity.com/profiles/{steam_id}"


def fetch_profile_xml(steam_id: str, *, timeout: float) -> str:
    response = requests.get(
        f"https://steamcommunity.com/profiles/{steam_id}/?xml=1",
        impersonate="chrome",
        timeout=timeout,
        headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    response.raise_for_status()
    return response.text


def parse_profile_xml(steam_id: str, xml_body: str) -> dict:
    root = ET.fromstring(xml_body)
    custom_url = xml_text(root, "customURL")
    persona_name = xml_text(root, "steamID")
    return {
        "steam_id": steam_id,
        "persona_name": html.unescape(persona_name) if persona_name else None,
        "avatar_url": xml_text(root, "avatarFull") or xml_text(root, "avatarMedium"),
        "avatar_medium_url": xml_text(root, "avatarMedium") or xml_text(root, "avatarIcon"),
        "custom_url": html.unescape(custom_url) if custom_url else None,
        "profile_url": profile_url_from_parts(steam_id, custom_url),
        "online_state": xml_text(root, "onlineState"),
        "status": "ok",
        "error": None,
    }


def fetch_steam_profile(steam_id: str, *, timeout: float) -> dict:
    try:
        xml_body = fetch_profile_xml(steam_id, timeout=timeout)
        return parse_profile_xml(steam_id, xml_body)
    except HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status == 404:
            return {
                "steam_id": steam_id,
                "persona_name": None,
                "avatar_url": None,
                "avatar_medium_url": None,
                "custom_url": None,
                "profile_url": f"https://steamcommunity.com/profiles/{steam_id}",
                "online_state": None,
                "status": "not_found",
                "error": "Steam profile not found",
            }
        return {
            "steam_id": steam_id,
            "persona_name": None,
            "avatar_url": None,
            "avatar_medium_url": None,
            "custom_url": None,
            "profile_url": f"https://steamcommunity.com/profiles/{steam_id}",
            "online_state": None,
            "status": "error",
            "error": str(exc),
        }
    except (RequestsError, ET.ParseError, ValueError) as exc:
        return {
            "steam_id": steam_id,
            "persona_name": None,
            "avatar_url": None,
            "avatar_medium_url": None,
            "custom_url": None,
            "profile_url": f"https://steamcommunity.com/profiles/{steam_id}",
            "online_state": None,
            "status": "error",
            "error": str(exc),
        }


def load_steam_ids(summary_path: Path) -> list[str]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    steam_ids: list[str] = []
    seen: set[str] = set()
    for player in summary.get("players", []):
        steam_id = player.get("steam_id")
        if not steam_id or steam_id in seen:
            continue
        seen.add(steam_id)
        steam_ids.append(steam_id)
    return steam_ids


def write_output(profiles: dict[str, dict], output_path: Path) -> None:
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "profile_count": len(profiles),
        "profiles": profiles,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--jitter", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.summary.exists():
        log(f"Summary file not found: {args.summary}")
        return 1

    steam_ids = load_steam_ids(args.summary)
    if not steam_ids:
        log("No Steam IDs found in summary")
        return 1

    profiles: dict[str, dict] = {}
    total = len(steam_ids)

    for index, steam_id in enumerate(steam_ids, start=1):
        log(f"[{index}/{total}] Fetching Steam profile for {steam_id}")
        profile = fetch_steam_profile(steam_id, timeout=args.timeout)
        profiles[steam_id] = profile
        write_output(profiles, args.output)

        if profile["status"] == "ok":
            log(f"[{index}/{total}] OK: {profile['persona_name']}")
        else:
            log(f"[{index}/{total}] {profile['status'].upper()}: {profile['error']}")

        if index < total:
            wait = args.delay + random.uniform(0, max(args.jitter, 0))
            time.sleep(wait)

    ok = sum(1 for profile in profiles.values() if profile["status"] == "ok")
    log(f"Wrote {len(profiles)} profiles ({ok} ok) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
