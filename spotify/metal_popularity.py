"""Resolve candidate recordings and calculate Spotify-only popularity tiers.

Spotify removed the public track ``popularity`` field from Development Mode
responses in February 2026.  The official Web API also does not expose public
cumulative stream counts.  This script therefore does two reproducible jobs:

1. Resolve and validate the exact Spotify recording (including ISRC).
2. Fetch and rank public artist monthly-listener counts, or optionally rank
   manually transcribed/licensed cumulative track stream counts.

The generated ``spotify_stream_counts.csv`` template is deliberately separate
from API metadata.  Enter the count shown for the exact album track in the
Spotify desktop client, or a licensed provider's count, and record the capture
date and source in the same row.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import math
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth


HERE = Path(__file__).resolve().parent
AUTH_DIR = HERE / "auth"
DEFAULT_CANDIDATES = HERE.parent / "experiment_setup" / "metal_candidates.csv"
DEFAULT_CONFIG = AUTH_DIR / "spotify_config.json"
DEFAULT_CACHE = AUTH_DIR / ".spotify_cache"
DEFAULT_COUNTS = HERE / "spotify_stream_counts.csv"
DEFAULT_LISTENER_CACHE = HERE / "spotify_artist_monthly_listeners.csv"
DEFAULT_OUTPUT = HERE / "spotify_popularity_results.csv"
YEAR_MIN = 2010
YEAR_MAX = 2022


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--counts", type=Path, default=DEFAULT_COUNTS)
    parser.add_argument("--listener-cache", type=Path, default=DEFAULT_LISTENER_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--metric",
        choices=("artist_monthly_listeners", "track_stream_count"),
        default="artist_monthly_listeners",
        help="Spotify popularity proxy to rank (default: artist monthly listeners).",
    )
    parser.add_argument(
        "--refresh-listeners",
        action="store_true",
        help="Refresh public artist-page counts instead of using the local snapshot cache.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Do not call Spotify; use Spotify IDs/metadata already in the counts file.",
    )
    return parser.parse_args()


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def spotify_client(config_path: Path) -> spotipy.Spotify:
    config = load_config(config_path)
    auth = SpotifyOAuth(
        client_id=config["client_id"],
        client_secret=config["client_secret"],
        redirect_uri=config["redirect_uri"],
        scope="playlist-read-private",
        cache_path=str(DEFAULT_CACHE),
    )
    return spotipy.Spotify(auth_manager=auth, requests_timeout=20, retries=3)


def result_score(candidate: dict[str, str], track: dict[str, Any]) -> float:
    wanted_artist = normalize(candidate["artist"])
    wanted_title = normalize(candidate["title"])
    actual_artists = " ".join(normalize(a.get("name", "")) for a in track.get("artists", []))
    actual_title = normalize(track.get("name", ""))
    score = 0.0

    if wanted_artist == actual_artists:
        score += 55
    elif wanted_artist in actual_artists or actual_artists in wanted_artist:
        score += 38
    if wanted_title == actual_title:
        score += 55
    elif wanted_title in actual_title or actual_title in wanted_title:
        score += 38

    expected_year = int(candidate["expected_year"])
    release_date = track.get("album", {}).get("release_date", "")
    try:
        actual_year = int(release_date[:4])
        difference = abs(actual_year - expected_year)
        score += max(0, 18 - 6 * difference)
    except (TypeError, ValueError):
        pass

    suspicious = (r"\blive\b", r"\bkaraoke\b", r"\btribute\b", r"\binstrumental version\b")
    combined = f"{track.get('name', '')} {track.get('album', {}).get('name', '')}".casefold()
    if any(re.search(pattern, combined) for pattern in suspicious):
        score -= 50
    return score


def resolve_track(sp: spotipy.Spotify, candidate: dict[str, str]) -> dict[str, Any] | None:
    query = f'track:"{candidate["title"]}" artist:"{candidate["artist"]}"'
    response = sp.search(q=query, type="track", limit=10)
    items = response.get("tracks", {}).get("items", [])
    if not items:
        response = sp.search(q=f'{candidate["artist"]} {candidate["title"]}', type="track", limit=10)
        items = response.get("tracks", {}).get("items", [])
    if not items:
        return None
    return max(items, key=lambda item: result_score(candidate, item))


def track_metadata(candidate: dict[str, str], track: dict[str, Any] | None) -> dict[str, str]:
    if track is None:
        return {
            "spotify_track_id": "",
            "primary_artist_id": "",
            "primary_artist_url": "",
            "spotify_url": "",
            "spotify_title": "",
            "spotify_artists": "",
            "spotify_album": "",
            "spotify_release_date": "",
            "spotify_isrc": "",
            "spotify_duration_ms": "",
            "spotify_api_popularity": "",
            "validation_status": "NOT_FOUND",
            "validation_notes": "No Spotify search result",
        }

    artists = "; ".join(a.get("name", "") for a in track.get("artists", []))
    primary_artist = (track.get("artists") or [{}])[0]
    release_date = track.get("album", {}).get("release_date", "")
    notes: list[str] = []
    status = "OK"
    if normalize(candidate["artist"]) not in normalize(artists):
        notes.append("artist mismatch")
    if normalize(candidate["title"]) not in normalize(track.get("name", "")):
        notes.append("title/version mismatch")
    try:
        year = int(release_date[:4])
        if not YEAR_MIN <= year <= YEAR_MAX:
            notes.append("release outside 2010-2022")
    except (TypeError, ValueError):
        notes.append("missing release year")
    if len(track.get("artists", [])) != 1:
        notes.append("multiple credited artists")
    suspicious = (r"\blive\b", r"\bkaraoke\b", r"\btribute\b", r"\binstrumental version\b")
    combined = f"{track.get('name', '')} {track.get('album', {}).get('name', '')}".casefold()
    if any(re.search(pattern, combined) for pattern in suspicious):
        notes.append("possible non-studio version")
    if notes:
        status = "REVIEW"

    return {
        "spotify_track_id": track.get("id", ""),
        "primary_artist_id": primary_artist.get("id", ""),
        "primary_artist_url": primary_artist.get("external_urls", {}).get("spotify", ""),
        "spotify_url": track.get("external_urls", {}).get("spotify", ""),
        "spotify_title": track.get("name", ""),
        "spotify_artists": artists,
        "spotify_album": track.get("album", {}).get("name", ""),
        "spotify_release_date": release_date,
        "spotify_isrc": track.get("external_ids", {}).get("isrc", ""),
        "spotify_duration_ms": str(track.get("duration_ms", "")),
        "spotify_api_popularity": str(track.get("popularity", "")),
        "validation_status": status,
        "validation_notes": "; ".join(notes),
    }


def parse_compact_number(raw: str) -> int | None:
    cleaned = (raw or "").strip().upper().replace(",", "").replace(" ", "")
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KMB]?)", cleaned)
    if not match:
        return None
    value = float(match.group(1))
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[match.group(2)]
    return round(value * multiplier)


def fetch_monthly_listeners(session: requests.Session, artist_url: str) -> tuple[int | None, str]:
    """Read the exact public count from a Spotify artist page.

    This is public webpage metadata, not a Spotify Web API field.  The parser
    first uses Spotify's semantic test id, then falls back to the page's public
    description metadata.
    """
    if not artist_url:
        return None, "missing artist URL"
    try:
        response = session.get(artist_url, timeout=25)
        response.raise_for_status()
    except requests.RequestException as error:
        return None, str(error)

    exact = re.search(
        r'data-testid=["\']monthly-listeners-label["\'][^>]*>\s*([0-9][0-9, .\u00a0]*)\s+monthly listeners',
        response.text,
        flags=re.IGNORECASE,
    )
    if exact:
        value = parse_compact_number(exact.group(1).replace("\u00a0", ""))
        if value is not None:
            return value, ""

    compact = re.search(
        r'(?:Artist\s*(?:·|&middot;|\\u00B7)\s*)?([0-9]+(?:\.[0-9]+)?[KMB]?)\s+monthly listeners',
        response.text,
        flags=re.IGNORECASE,
    )
    if compact:
        value = parse_compact_number(compact.group(1))
        if value is not None:
            return value, ""
    return None, "monthly-listener text not found"


def parse_count(raw: str) -> tuple[int | None, bool]:
    cleaned = (raw or "").strip().replace(",", "").replace(" ", "")
    if not cleaned:
        return None, False
    censored = cleaned.startswith("<")
    cleaned = cleaned.lstrip("<")
    try:
        value = int(cleaned)
    except ValueError:
        return None, False
    # Spotify commonly displays <1000.  Rank it at its documented upper bound
    # and preserve the censoring flag so it is never reported as an exact count.
    return max(0, value - 1) if censored else value, censored


def percentile_ranks(values: dict[str, int]) -> dict[str, float]:
    """Return midranks on a 0-100 scale, averaging tied observations."""
    ordered = sorted(values.items(), key=lambda item: item[1])
    n = len(ordered)
    result: dict[str, float] = {}
    index = 0
    while index < n:
        end = index + 1
        while end < n and ordered[end][1] == ordered[index][1]:
            end += 1
        average_rank = ((index + 1) + end) / 2
        percentile = 100 * (average_rank - 0.5) / n
        for tied_index in range(index, end):
            result[ordered[tied_index][0]] = percentile
        index = end
    return result


def tier(percentile: float | None) -> str:
    if percentile is None or math.isnan(percentile):
        return "Missing"
    if percentile <= 25:
        return "Low"
    if 37.5 <= percentile <= 62.5:
        return "Middle"
    if percentile >= 75:
        return "High"
    return "Buffer"


def existing_counts(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    return {row["candidate_id"]: row for row in load_csv(path)}


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    candidates = load_csv(args.candidates)
    saved_counts = existing_counts(args.counts)
    saved_listeners = existing_counts(args.listener_cache)
    saved_results = existing_counts(args.output) if args.output.exists() else {}
    sp = None if args.offline else spotify_client(args.config)
    web_session = requests.Session()
    web_session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; academic popularity study)",
        "Accept-Language": "en-US,en;q=0.9",
    })
    snapshot_time = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rows: list[dict[str, Any]] = []
    listener_rows: list[dict[str, Any]] = []

    for number, candidate in enumerate(candidates, start=1):
        print(f"[{number:02d}/{len(candidates)}] {candidate['artist']} - {candidate['title']}")
        old = saved_counts.get(candidate["candidate_id"], {})
        old_result = saved_results.get(candidate["candidate_id"], {})
        if sp is not None:
            metadata = track_metadata(candidate, resolve_track(sp, candidate))
        else:
            metadata = {key: old_result.get(key, old.get(key, "")) for key in (
                "spotify_track_id", "primary_artist_id", "primary_artist_url",
                "spotify_url", "spotify_title", "spotify_artists",
                "spotify_album", "spotify_release_date", "spotify_isrc",
                "spotify_duration_ms", "spotify_api_popularity", "validation_status",
                "validation_notes",
            )}

        listener_cache = saved_listeners.get(candidate["candidate_id"], {})
        cache_matches_artist = (
            listener_cache.get("primary_artist_id", "") == metadata.get("primary_artist_id", "")
        )
        monthly_listeners = listener_cache.get("artist_monthly_listeners", "") if cache_matches_artist else ""
        listener_captured_at = listener_cache.get("captured_at_utc", "") if cache_matches_artist else ""
        listener_error = listener_cache.get("fetch_error", "") if cache_matches_artist else ""
        if (
            args.metric == "artist_monthly_listeners"
            and not args.offline
            and (args.refresh_listeners or not monthly_listeners)
        ):
            value, listener_error = fetch_monthly_listeners(
                web_session, metadata.get("primary_artist_url", "")
            )
            monthly_listeners = str(value) if value is not None else ""
            listener_captured_at = snapshot_time

        row = {
            **candidate,
            **metadata,
            "artist_monthly_listeners": monthly_listeners,
            "artist_monthly_listeners_captured_at": listener_captured_at,
            "artist_monthly_listeners_source": "Spotify public artist page",
            "artist_monthly_listeners_fetch_error": listener_error,
            "stream_count": old.get("stream_count", ""),
            "captured_at": old.get("captured_at", ""),
            "source_note": old.get("source_note", "Spotify desktop album page"),
        }
        rows.append(row)
        listener_rows.append({
            "candidate_id": candidate["candidate_id"],
            "artist": candidate["artist"],
            "primary_artist_id": metadata.get("primary_artist_id", ""),
            "primary_artist_url": metadata.get("primary_artist_url", ""),
            "artist_monthly_listeners": monthly_listeners,
            "captured_at_utc": listener_captured_at,
            "source": "Spotify public artist page",
            "fetch_error": listener_error,
        })

    metric_values: dict[str, int] = {}
    censored: dict[str, bool] = {}
    for row in rows:
        if args.metric == "artist_monthly_listeners":
            value = parse_compact_number(str(row["artist_monthly_listeners"]))
            is_censored = False
        else:
            value, is_censored = parse_count(str(row["stream_count"]))
        if value is not None:
            metric_values[row["candidate_id"]] = value
            censored[row["candidate_id"]] = is_censored
    percentiles = percentile_ranks(metric_values) if metric_values else {}

    for row in rows:
        candidate_id = row["candidate_id"]
        percentile = percentiles.get(candidate_id)
        row["stream_count_censored"] = "yes" if censored.get(candidate_id) else "no"
        row["spotify_metric"] = args.metric
        row["spotify_metric_value"] = str(metric_values.get(candidate_id, ""))
        row["spotify_percentile"] = f"{percentile:.2f}" if percentile is not None else ""
        row["spotify_tier"] = tier(percentile)

    count_fields = [
        "candidate_id", "artist", "title", "spotify_track_id", "primary_artist_id",
        "primary_artist_url", "spotify_url", "spotify_isrc", "stream_count",
        "captured_at", "source_note",
    ]
    write_csv(args.counts, rows, count_fields)
    listener_fields = [
        "candidate_id", "artist", "primary_artist_id", "primary_artist_url",
        "artist_monthly_listeners", "captured_at_utc", "source", "fetch_error",
    ]
    write_csv(args.listener_cache, listener_rows, listener_fields)
    output_fields = list(rows[0].keys()) if rows else []
    write_csv(args.output, rows, output_fields)

    resolved = sum(bool(row["spotify_track_id"]) for row in rows)
    api_popularity = sum(bool(row["spotify_api_popularity"]) for row in rows)
    listener_values = sum(bool(row["artist_monthly_listeners"]) for row in rows)
    print(f"\nResolved Spotify recordings: {resolved}/{len(rows)}")
    print(f"Rows with artist monthly listeners: {listener_values}/{len(rows)}")
    print(f"Rows with manually supplied stream counts: {sum(bool(row['stream_count']) for row in rows)}/{len(rows)}")
    print(f"Rows with Spotify API popularity: {api_popularity}/{len(rows)}")
    print(f"Ranked metric: {args.metric} ({len(metric_values)}/{len(rows)} values)")
    print(f"Monthly-listener snapshot: {args.listener_cache}")
    print(f"Stream-count template: {args.counts}")
    print(f"Full results: {args.output}")
    if not metric_values:
        print("No values were available for the selected metric.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
