#!/usr/bin/env python3
"""Fetch in-game chat messages from cstracker.gg player profiles."""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, TextIO
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag
from curl_cffi import requests
from curl_cffi.requests.errors import RequestsError
from curl_cffi.requests.exceptions import HTTPError

CSTTRACKER_BASE = "https://cstracker.gg"
STEAM_ID_RE = re.compile(r"^\d{17}$")
CHAT_LINK_RE = re.compile(
    r"^/matches/(?P<match_id>\d+)#timeline-chat-(?P<chat_id>\d+)$"
)
RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
NOT_ON_CSTRACKER_MESSAGE = "Player not indexed on cstracker.gg"
STEAM_ID_XML_RE = re.compile(r"<steamID64>(\d{17})</steamID64>")
STEAM_COMMUNITY_HOSTS = {"steamcommunity.com", "www.steamcommunity.com"}


@dataclass(frozen=True)
class ChatMessage:
    message: str
    match_id: str
    chat_id: str
    map_name: str | None
    match_url: str
    chat_url: str
    round_label: str | None
    match_time: str | None
    played_at: str | None


@dataclass(frozen=True)
class PlayerChatResult:
    player: str
    player_url: str
    steam_id: str | None
    status: str
    message_count: int
    messages: list[ChatMessage]
    error: str | None = None
    attempts: int = 1


def log(message: str) -> None:
    print(message, file=sys.stderr)


def is_steam_community_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    return host in STEAM_COMMUNITY_HOSTS and (
        parsed.path.startswith("/id/") or parsed.path.startswith("/profiles/")
    )


def steam_id_from_steam_url(steam_url: str, *, timeout: float = 20.0) -> str:
    parsed = urlparse(steam_url.strip().rstrip("/"))
    host = parsed.netloc.lower()
    if host not in STEAM_COMMUNITY_HOSTS:
        raise ValueError(f"Not a Steam Community URL: {steam_url}")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "profiles" and STEAM_ID_RE.fullmatch(parts[1]):
        return parts[1]

    if len(parts) >= 2 and parts[0] == "id":
        xml_url = f"https://{host}/id/{parts[1]}/?xml=1"
        response = requests.get(
            xml_url,
            impersonate="chrome",
            timeout=timeout,
            headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        response.raise_for_status()
        match = STEAM_ID_XML_RE.search(response.text)
        if not match:
            raise ValueError(f"Could not resolve Steam ID for {steam_url}")
        return match.group(1)

    raise ValueError(f"Unsupported Steam Community URL format: {steam_url}")


def normalize_player_url(
    player: str,
    *,
    timeout: float = 20.0,
    steam_id_cache: dict[str, str] | None = None,
) -> str:
    player = player.strip()
    cache = steam_id_cache if steam_id_cache is not None else {}

    if player.startswith("http://") or player.startswith("https://"):
        parsed = urlparse(player)
        if parsed.netloc.endswith("cstracker.gg") and parsed.path.startswith("/players/"):
            return f"{CSTTRACKER_BASE}{parsed.path.rstrip('/')}"

        if is_steam_community_url(player):
            cache_key = player.strip().rstrip("/").lower()
            if cache_key not in cache:
                cache[cache_key] = steam_id_from_steam_url(player, timeout=timeout)
            return f"{CSTTRACKER_BASE}/players/{cache[cache_key]}"

        raise ValueError(f"Unsupported player URL: {player}")

    if STEAM_ID_RE.fullmatch(player):
        return f"{CSTTRACKER_BASE}/players/{player}"

    if player.startswith("/players/"):
        return f"{CSTTRACKER_BASE}{player.rstrip('/')}"

    raise ValueError(
        "Expected a Steam Community URL, 17-digit Steam ID, or cstracker player URL "
        f"(got {player!r})"
    )


def steam_id_from_url(player_url: str) -> str | None:
    parsed = urlparse(player_url)
    steam_id = parsed.path.removeprefix("/players/").strip("/")
    return steam_id if STEAM_ID_RE.fullmatch(steam_id) else None


def read_player_links(
    *,
    players: list[str],
    links_file: Path | None,
    read_stdin: bool,
) -> list[str]:
    links: list[str] = []

    for player in players:
        player = player.strip()
        if player:
            links.append(player)

    if links_file is not None:
        for line in links_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            links.append(line)

    if read_stdin:
        for line in sys.stdin:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            links.append(line)

    if not links:
        raise ValueError("No player links provided")

    return links


def fetch_player_html(
    player_url: str,
    *,
    timeout: float = 30.0,
) -> str:
    response = requests.get(
        player_url,
        impersonate="chrome",
        timeout=timeout,
        headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    response.raise_for_status()
    return response.text


def fetch_player_html_with_retries(
    player_url: str,
    *,
    timeout: float,
    retry_max: int,
    retry_base_delay: float,
    retry_backoff: float,
) -> tuple[str, int]:
    last_error: Exception | None = None

    for attempt in range(1, retry_max + 2):
        try:
            return fetch_player_html(player_url, timeout=timeout), attempt
        except HTTPError as exc:
            last_error = exc
            status = exc.response.status_code if exc.response is not None else None
            if status not in RETRYABLE_STATUS_CODES or attempt > retry_max:
                raise
        except RequestsError as exc:
            last_error = exc
            if attempt > retry_max:
                raise

        wait = retry_base_delay * (retry_backoff ** (attempt - 1))
        wait += random.uniform(0, retry_base_delay * 0.25)
        log(
            f"Retry {attempt}/{retry_max} for {player_url} after error: "
            f"{last_error}; sleeping {wait:.1f}s"
        )
        time.sleep(wait)

    raise RuntimeError(f"Failed to fetch {player_url}: {last_error}")


def _section_match_meta(section: Tag) -> tuple[str | None, str | None, str | None]:
    map_link = section.select_one('a[href^="/matches/"]')
    map_name = map_link.get_text(strip=True) if map_link else None
    match_href = map_link["href"] if map_link else None
    match_id = match_href.removeprefix("/matches/") if match_href else None

    played = section.select_one("[title^='played ']")
    played_at = played.get("title").removeprefix("played ") if played else None

    return map_name, match_id, played_at


def _parse_round_and_time(raw: str) -> tuple[str | None, str | None]:
    text = raw.strip()
    if not text:
        return None, None

    if "·" in text:
        round_label, match_time = text.split("·", 1)
        return round_label.strip() or None, match_time.strip() or None

    return text, None


def parse_chat_messages(html: str) -> list[ChatMessage]:
    soup = BeautifulSoup(html, "html.parser")
    chat_root = soup.select_one("div.mt-4.max-h-\\[50vh\\].overflow-y-auto.space-y-3")
    if chat_root is None:
        return []

    messages: list[ChatMessage] = []
    for section in chat_root.select(":scope > section"):
        map_name, default_match_id, played_at = _section_match_meta(section)

        for link in section.select('a[href*="timeline-chat-"]'):
            href = link.get("href", "")
            match = CHAT_LINK_RE.match(href)
            if not match:
                continue

            cols = link.select("div")
            if len(cols) < 2:
                continue

            round_label, match_time = _parse_round_and_time(cols[0].get_text(" ", strip=True))
            message = cols[1].get_text(strip=True)
            match_id = match.group("match_id") or default_match_id
            if not match_id:
                continue

            chat_id = match.group("chat_id")
            messages.append(
                ChatMessage(
                    message=message,
                    match_id=match_id,
                    chat_id=chat_id,
                    map_name=map_name,
                    match_url=f"{CSTTRACKER_BASE}/matches/{match_id}",
                    chat_url=f"{CSTTRACKER_BASE}{href}",
                    round_label=round_label,
                    match_time=match_time,
                    played_at=played_at,
                )
            )

    return messages


def filter_messages(
    messages: Iterable[ChatMessage],
    message_filter: str | None,
) -> list[ChatMessage]:
    if not message_filter:
        return list(messages)

    needle = message_filter.casefold()
    return [m for m in messages if needle in m.message.casefold()]


def classify_fetch_failure(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        if status == 404:
            return "not_on_cstracker", NOT_ON_CSTRACKER_MESSAGE
    return "error", str(exc)


def fetch_player_chat(
    player: str,
    *,
    timeout: float,
    retry_max: int,
    retry_base_delay: float,
    retry_backoff: float,
    message_filter: str | None,
    steam_id_cache: dict[str, str] | None = None,
) -> PlayerChatResult:
    try:
        player_url = normalize_player_url(
            player,
            timeout=timeout,
            steam_id_cache=steam_id_cache,
        )
        html, attempts = fetch_player_html_with_retries(
            player_url,
            timeout=timeout,
            retry_max=retry_max,
            retry_base_delay=retry_base_delay,
            retry_backoff=retry_backoff,
        )
        messages = filter_messages(parse_chat_messages(html), message_filter)
        return PlayerChatResult(
            player=player,
            player_url=player_url,
            steam_id=steam_id_from_url(player_url),
            status="ok",
            message_count=len(messages),
            messages=messages,
            attempts=attempts,
        )
    except Exception as exc:
        try:
            player_url = normalize_player_url(
                player,
                timeout=timeout,
                steam_id_cache=steam_id_cache,
            )
            steam_id = steam_id_from_url(player_url)
        except ValueError:
            player_url = player
            steam_id = None

        status, message = classify_fetch_failure(exc)
        return PlayerChatResult(
            player=player,
            player_url=player_url,
            steam_id=steam_id,
            status=status,
            message_count=0,
            messages=[],
            error=message,
        )


def sleep_between_requests(delay: float, jitter: float) -> None:
    if delay <= 0:
        return
    wait = delay + random.uniform(0, max(jitter, 0))
    log(f"Waiting {wait:.1f}s before next request")
    time.sleep(wait)


def print_messages(player_url: str, messages: Iterable[ChatMessage]) -> None:
    message_list = list(messages)
    print(f"Found {len(message_list)} chat message(s) from {player_url}\n")
    for item in message_list:
        when = []
        if item.map_name:
            when.append(item.map_name)
        if item.round_label:
            when.append(item.round_label)
        if item.match_time:
            when.append(item.match_time)
        if item.played_at:
            when.append(f"played {item.played_at}")

        context = " · ".join(when)
        print(f"{context}\n  {item.message}\n  {item.chat_url}\n")


def result_to_dict(result: PlayerChatResult) -> dict:
    return {
        "player": result.player,
        "player_url": result.player_url,
        "steam_id": result.steam_id,
        "status": result.status,
        "message_count": result.message_count,
        "attempts": result.attempts,
        "error": result.error,
        "messages": [asdict(message) for message in result.messages],
    }


def write_dashboard_outputs(results: list[PlayerChatResult], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    by_player = [result_to_dict(result) for result in results]
    flat_messages = []
    for result in results:
        for message in result.messages:
            flat_messages.append(
                {
                    "steam_url": result.player,
                    "steam_id": result.steam_id,
                    "cstracker_url": result.player_url,
                    **asdict(message),
                }
            )

    summary = {
        "player_count": len(results),
        "fetched_ok": sum(1 for r in results if r.status == "ok"),
        "not_on_cstracker": sum(1 for r in results if r.status == "not_on_cstracker"),
        "no_chat": sum(1 for r in results if r.status == "ok" and r.message_count == 0),
        "errors": sum(1 for r in results if r.status == "error"),
        "players_with_messages": sum(1 for r in results if r.message_count > 0),
        "total_messages": sum(r.message_count for r in results),
        "players": [
            {
                "steam_url": result.player,
                "steam_id": result.steam_id,
                "cstracker_url": result.player_url,
                "status": result.status,
                "message_count": result.message_count,
                "error": result.error,
            }
            for result in results
        ],
    }

    (output_dir / "chat_history_by_player.json").write_text(
        json.dumps(by_player, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "chat_messages_flat.json").write_text(
        json.dumps(flat_messages, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "fetch_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )


def write_json_output(
    results: list[PlayerChatResult],
    *,
    output: TextIO,
    flat: bool,
) -> None:
    if flat:
        payload = []
        for result in results:
            for message in result.messages:
                payload.append(
                    {
                        "player": result.player,
                        "player_url": result.player_url,
                        "steam_id": result.steam_id,
                        **asdict(message),
                    }
                )
    else:
        payload = []
        for result in results:
            payload.append(
                {
                    "player": result.player,
                    "player_url": result.player_url,
                    "steam_id": result.steam_id,
                    "status": result.status,
                    "message_count": result.message_count,
                    "attempts": result.attempts,
                    "error": result.error,
                    "messages": [asdict(message) for message in result.messages],
                }
            )

    json.dump(payload, output, indent=2)
    output.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch chat messages from one or more cstracker.gg player profiles.",
    )
    parser.add_argument(
        "players",
        nargs="*",
        help="Steam ID(s) or cstracker player URL(s)",
    )
    parser.add_argument(
        "--links-file",
        type=Path,
        help="Text file with one Steam ID or player URL per line (# comments allowed)",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read additional player links from stdin (one per line)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print results as JSON",
    )
    parser.add_argument(
        "--flat-json",
        action="store_true",
        help="With --json, emit one object per chat message instead of grouping by player",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON output to this file instead of stdout",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Write dashboard files (by-player, flat messages, summary) to this directory",
    )
    parser.add_argument(
        "--message",
        dest="message_filter",
        help="Only include messages whose text contains this substring (case-insensitive)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Seconds to wait between player requests (default: 2.0)",
    )
    parser.add_argument(
        "--jitter",
        type=float,
        default=0.75,
        help="Random extra seconds added to --delay (default: 0.75)",
    )
    parser.add_argument(
        "--retry-max",
        type=int,
        default=3,
        help="Max retries per player on timeout/rate-limit/server errors (default: 3)",
    )
    parser.add_argument(
        "--retry-base-delay",
        type=float,
        default=5.0,
        help="Initial retry wait in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=2.0,
        help="Retry wait multiplier after each failure (default: 2.0)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds (default: 30.0)",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Keep processing remaining links if one player fails",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        links = read_player_links(
            players=args.players,
            links_file=args.links_file,
            read_stdin=args.stdin,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    results: list[PlayerChatResult] = []
    steam_id_cache: dict[str, str] = {}
    total = len(links)

    for index, player in enumerate(links, start=1):
        log(f"[{index}/{total}] Fetching chat history for {player}")
        result = fetch_player_chat(
            player,
            timeout=args.timeout,
            retry_max=args.retry_max,
            retry_base_delay=args.retry_base_delay,
            retry_backoff=args.retry_backoff,
            message_filter=args.message_filter,
            steam_id_cache=steam_id_cache,
        )
        results.append(result)

        if result.status == "ok":
            log(
                f"[{index}/{total}] OK: {result.message_count} message(s) "
                f"from {result.player_url}"
            )
        elif result.status == "not_on_cstracker":
            log(f"[{index}/{total}] NOT ON CSTRACKER: {result.player_url}")
        else:
            log(f"[{index}/{total}] ERROR: {result.error}")
            if not args.continue_on_error:
                break

        if args.output_dir is not None:
            write_dashboard_outputs(results, args.output_dir)

        if index < total:
            sleep_between_requests(args.delay, args.jitter)

    failures = [result for result in results if result.status == "error"]
    single_player = len(links) == 1 and not args.links_file and not args.stdin

    if args.output_dir is not None:
        write_dashboard_outputs(results, args.output_dir)
        log(f"Wrote dashboard data to {args.output_dir}")

    if args.json or args.output:
        output = args.output.open("w", encoding="utf-8") if args.output else sys.stdout
        try:
            write_json_output(results, output=output, flat=args.flat_json)
        finally:
            if args.output is not None:
                output.close()
                log(f"Wrote JSON to {args.output}")
    elif single_player and results and results[0].status == "ok":
        print_messages(results[0].player_url, results[0].messages)
    else:
        for result in results:
            print(f"\n=== {result.player_url} ===")
            if result.status == "ok":
                print_messages(result.player_url, result.messages)
            elif result.status == "not_on_cstracker":
                print(f"NOT ON CSTRACKER: {result.error}")
            else:
                print(f"ERROR: {result.error}")

    if failures and not args.continue_on_error:
        return 1
    if failures:
        return 1 if len(failures) == len(results) else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
