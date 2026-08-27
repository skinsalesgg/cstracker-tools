#!/usr/bin/env python3
"""Compare Discord users with Steam URLs against steam_links.txt."""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DISCORD_CSV = ROOT / "discord_users.csv"
STEAM_LINKS = ROOT / "steam_links.txt"
PROFILES = ROOT / "data" / "steam_profiles.json"
SUMMARY = ROOT / "data" / "fetch_summary.json"

STEAM_ID_RE = re.compile(r"/profiles/(\d{17})")
VANITY_RE = re.compile(r"/id/([^/\s|?]+)", re.I)

BOT_NAMES = {
    "Carl-bot",
    "Dyno",
    "kitten",
    "Minecraft Server Status",
}


def normalize_url(url: str) -> str:
    return url.strip().rstrip("/").lower()


def extract_urls(cell: str) -> list[str]:
    if not cell:
        return []
    out = []
    for part in cell.split("|"):
        part = part.strip().split()[0] if part.strip() else ""
        if part.startswith("http"):
            out.append(normalize_url(part.split("?")[0]))
    return out


def build_resolvers() -> tuple[dict[str, str], dict[str, str]]:
    """url/path -> steam_id, vanity lower -> steam_id"""
    url_to_id: dict[str, str] = {}
    vanity_to_id: dict[str, str] = {}

    if PROFILES.exists():
        for sid, prof in json.load(open(PROFILES))["profiles"].items():
            sid = str(sid)
            for key in ("profile_url",):
                u = prof.get(key)
                if u:
                    url_to_id[normalize_url(u)] = sid
            cu = prof.get("custom_url")
            if cu:
                vanity_to_id[cu.lower()] = sid

    if SUMMARY.exists():
        for player in json.load(open(SUMMARY)).get("players", []):
            sid = player.get("steam_id")
            u = player.get("steam_url")
            if sid and u:
                url_to_id[normalize_url(u)] = str(sid)

    if STEAM_LINKS.exists():
        for line in STEAM_LINKS.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            u = normalize_url(line)
            m = STEAM_ID_RE.search(u)
            if m:
                url_to_id[u] = m.group(1)
            else:
                m = VANITY_RE.search(u)
                if m:
                    vanity_to_id.setdefault(m.group(1).lower(), "")

    return url_to_id, vanity_to_id


def resolve_ids(urls: list[str], url_to_id: dict[str, str], vanity_to_id: dict[str, str]) -> set[str]:
    ids: set[str] = set()
    for url in urls:
        m = STEAM_ID_RE.search(url)
        if m:
            ids.add(m.group(1))
            continue
        if url in url_to_id and url_to_id[url]:
            ids.add(url_to_id[url])
            continue
        m = VANITY_RE.search(url)
        if m:
            vanity = m.group(1).lower()
            sid = vanity_to_id.get(vanity)
            if sid:
                ids.add(sid)
            elif url in url_to_id and url_to_id[url]:
                ids.add(url_to_id[url])
    return ids


def main() -> None:
    url_to_id, vanity_to_id = build_resolvers()

    tracked_urls = []
    for line in STEAM_LINKS.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            tracked_urls.append(normalize_url(line))
    tracked_ids = resolve_ids(tracked_urls, url_to_id, vanity_to_id)
    # Also add direct profile IDs from links file
    for u in tracked_urls:
        m = STEAM_ID_RE.search(u)
        if m:
            tracked_ids.add(m.group(1))

    discord_with_steam: list[dict] = []
    seen_ids: set[str] = set()

    with open(DISCORD_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("discord_display_name") or "").strip()
            if not name or name in BOT_NAMES:
                continue
            urls = extract_urls(row.get("steam_profile_url") or "")
            if not urls:
                continue
            steam_linked = row.get("steam_linked", "").lower() == "true"
            ids = resolve_ids(urls, url_to_id, vanity_to_id)
            for u in urls:
                m = STEAM_ID_RE.search(u)
                if m:
                    ids.add(m.group(1))
            if not ids:
                discord_with_steam.append(
                    {
                        "name": name,
                        "urls": urls,
                        "ids": set(),
                        "steam_linked": steam_linked,
                        "unresolved": True,
                    }
                )
                continue
            for sid in ids:
                if sid in seen_ids:
                    continue
                seen_ids.add(sid)
                discord_with_steam.append(
                    {
                        "name": name,
                        "urls": urls,
                        "ids": ids,
                        "steam_linked": steam_linked,
                        "unresolved": False,
                    }
                )

    missed = []
    already = []
    for entry in discord_with_steam:
        ids = entry["ids"]
        if entry["unresolved"]:
            missed.append({**entry, "reason": "unresolved vanity/id"})
            continue
        if ids & tracked_ids:
            already.append(entry)
        else:
            missed.append({**entry, "reason": "not in steam_links.txt"})

    linked_count = sum(1 for e in discord_with_steam if e["steam_linked"])
    print(f"Discord users with Steam URL (unique IDs): {len(discord_with_steam)}")
    print(f"  steam_linked=true: {linked_count}")
    print(f"  steam_linked=false (URL present): {len(discord_with_steam) - linked_count}")
    print(f"In steam_links.txt already: {len(already)}")
    print(f"MISSING from steam_links.txt: {len(missed)}")
    print()
    for entry in sorted(missed, key=lambda x: x["name"].lower()):
        sid = next(iter(entry["ids"]), "?")
        url = entry["urls"][0] if entry["urls"] else ""
        linked = "linked" if entry["steam_linked"] else "not linked"
        print(f"- {entry['name']} ({linked})")
        print(f"  {url}")
        if sid != "?":
            print(f"  steam_id: {sid}")
        if entry.get("reason"):
            print(f"  ({entry['reason']})")


if __name__ == "__main__":
    main()
