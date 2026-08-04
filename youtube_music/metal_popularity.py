"""Resolve official YouTube Music Art Tracks and calculate YouTube-only tiers.

Select isolated browser-header credentials with ``--profile user_01`` through
``--profile user_10``. For a published/repeated study, set ``YOUTUBE_API_KEY``
to verify final video IDs through the official YouTube Data API v3; this script
automatically prefers that source when the key is present.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import math
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ytmusicapi import YTMusic

from youtube_auth_profiles import PROFILE_IDS, resolve_auth_path


HERE = Path(__file__).resolve().parent
DEFAULT_CANDIDATES = HERE.parent / "experiment_setup" / "metal_candidates.csv"
DEFAULT_OUTPUT = HERE / "youtube_popularity_results.csv"
YEAR_MIN = 2010
YEAR_MAX = 2022
ART_TRACK_TYPE = "MUSIC_VIDEO_TYPE_ATV"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    auth_group = parser.add_mutually_exclusive_group()
    auth_group.add_argument("--profile", choices=PROFILE_IDS)
    auth_group.add_argument("--auth", type=Path, help="Explicit auth file; bypasses the profile registry.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--api-key",
        default=os.getenv("YOUTUBE_API_KEY", ""),
        help="YouTube Data API v3 key; defaults to YOUTUBE_API_KEY.",
    )
    return parser.parse_args()


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def artists_text(result: dict[str, Any]) -> str:
    return "; ".join(artist.get("name", "") for artist in result.get("artists") or [])


def search_score(candidate: dict[str, str], result: dict[str, Any]) -> float:
    wanted_artist = normalize(candidate.get("youtube_artist_name") or candidate["artist"])
    wanted_title = normalize(candidate["title"])
    actual_artist = normalize(artists_text(result))
    actual_title = normalize(result.get("title", ""))
    score = 0.0

    if wanted_artist == actual_artist:
        score += 60
    elif wanted_artist in actual_artist or actual_artist in wanted_artist:
        score += 40
    if wanted_title == actual_title:
        score += 60
    elif wanted_title in actual_title or actual_title in wanted_title:
        score += 40
    if result.get("videoType") == ART_TRACK_TYPE:
        score += 30
    album_name = (result.get("album") or {}).get("name", "")
    suspicious = (r"\blive\b", r"\bkaraoke\b", r"\btribute\b", r"\binstrumental version\b")
    combined = f"{result.get('title', '')} {album_name}".casefold()
    if any(re.search(pattern, combined) for pattern in suspicious):
        score -= 80
    return score


def resolve_art_track(ytmusic: YTMusic, candidate: dict[str, str]) -> dict[str, Any] | None:
    query_artist = candidate.get("youtube_artist_name") or candidate["artist"]
    query = f'{query_artist} {candidate["title"]}'
    results = ytmusic.search(query, filter="songs", limit=20, ignore_spelling=True)
    if not results:
        return None
    return max(results, key=lambda result: search_score(candidate, result))


def album_year(ytmusic: YTMusic, album_id: str, cache: dict[str, str]) -> str:
    if not album_id:
        return ""
    if album_id not in cache:
        try:
            album = ytmusic.get_album(album_id)
            cache[album_id] = str(album.get("year") or "")
        except Exception:
            cache[album_id] = ""
    return cache[album_id]


def song_details(ytmusic: YTMusic, video_id: str) -> tuple[dict[str, Any], str]:
    try:
        response = ytmusic.get_song(video_id)
    except Exception as error:
        return {}, str(error)
    return response, ""


def int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).replace(",", "").strip())
    except ValueError:
        return None


def official_video_statistics(api_key: str, video_ids: list[str]) -> dict[str, dict[str, str]]:
    """Fetch public statistics from the official API, in batches of 50 IDs."""
    results: dict[str, dict[str, str]] = {}
    for start in range(0, len(video_ids), 50):
        batch = video_ids[start : start + 50]
        params = urllib.parse.urlencode({
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(batch),
            "key": api_key,
        })
        url = f"https://www.googleapis.com/youtube/v3/videos?{params}"
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = json.load(response)
        for item in payload.get("items", []):
            statistics = item.get("statistics", {})
            snippet = item.get("snippet", {})
            results[item["id"]] = {
                "view_count": statistics.get("viewCount", ""),
                "like_count": statistics.get("likeCount", ""),
                "comment_count": statistics.get("commentCount", ""),
                "published_at": snippet.get("publishedAt", ""),
                "channel_id": snippet.get("channelId", ""),
                "channel_title": snippet.get("channelTitle", ""),
            }
    return results


def percentile_ranks(values: dict[str, int]) -> dict[str, float]:
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


def validate(candidate: dict[str, str], result: dict[str, Any], year: str) -> tuple[str, str]:
    notes: list[str] = []
    wanted_artist = candidate.get("youtube_artist_name") or candidate["artist"]
    if normalize(wanted_artist) not in normalize(artists_text(result)):
        notes.append("artist mismatch")
    if normalize(candidate["title"]) not in normalize(result.get("title", "")):
        notes.append("title/version mismatch")
    if result.get("videoType") != ART_TRACK_TYPE:
        notes.append("not an Art Track")
    if len(result.get("artists") or []) != 1:
        notes.append("multiple credited artists")
    try:
        numeric_year = int(year)
        if not YEAR_MIN <= numeric_year <= YEAR_MAX:
            notes.append("release outside 2010-2022")
    except (TypeError, ValueError):
        notes.append("missing album year")
    suspicious = (r"\blive\b", r"\bkaraoke\b", r"\btribute\b", r"\binstrumental version\b")
    album_name = (result.get("album") or {}).get("name", "")
    combined = f"{result.get('title', '')} {album_name}".casefold()
    if any(re.search(pattern, combined) for pattern in suspicious):
        notes.append("possible non-studio version")
    return ("REVIEW", "; ".join(notes)) if notes else ("OK", "")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    candidates = load_csv(args.candidates)
    try:
        auth_path, selected_profile = resolve_auth_path(
            profile=args.profile,
            auth_path=args.auth,
        )
        ytmusic = YTMusic(str(auth_path))
    except FileNotFoundError:
        if args.profile or args.auth:
            raise
        selected_profile = None
        ytmusic = YTMusic()
    captured_at_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    album_year_cache: dict[str, str] = {}
    rows: list[dict[str, Any]] = []

    for number, candidate in enumerate(candidates, start=1):
        print(f"[{number:02d}/{len(candidates)}] {candidate['artist']} - {candidate['title']}")
        result = resolve_art_track(ytmusic, candidate)
        if not result:
            rows.append({
                **candidate,
                "youtube_video_id": "",
                "youtube_url": "",
                "youtube_title": "",
                "youtube_artists": "",
                "youtube_album": "",
                "youtube_album_year": "",
                "youtube_video_type": "",
                "view_count": "",
                "like_count": "",
                "comment_count": "",
                "published_at": "",
                "data_source": "",
                "captured_at_utc": captured_at_utc,
                "validation_status": "NOT_FOUND",
                "validation_notes": "No YouTube Music song result",
            })
            continue

        video_id = result.get("videoId", "")
        album = result.get("album") or {}
        year = album_year(ytmusic, album.get("id", ""), album_year_cache)
        details, lookup_error = song_details(ytmusic, video_id)
        video_details = details.get("videoDetails", {})
        status, notes = validate(candidate, result, year)
        if lookup_error:
            status = "REVIEW"
            notes = "; ".join(part for part in (notes, f"song lookup failed: {lookup_error}") if part)
        rows.append({
            **candidate,
            "youtube_video_id": video_id,
            "youtube_url": f"https://music.youtube.com/watch?v={video_id}" if video_id else "",
            "youtube_title": result.get("title", ""),
            "youtube_artists": artists_text(result),
            "youtube_album": album.get("name", ""),
            "youtube_album_year": year,
            "youtube_video_type": result.get("videoType", ""),
            "view_count": video_details.get("viewCount", ""),
            "like_count": "",
            "comment_count": "",
            "published_at": "",
            "data_source": "ytmusicapi player response",
            "captured_at_utc": captured_at_utc,
            "validation_status": status,
            "validation_notes": notes,
        })

    if args.api_key:
        ids = [row["youtube_video_id"] for row in rows if row["youtube_video_id"]]
        official = official_video_statistics(args.api_key, ids)
        for row in rows:
            statistics = official.get(row["youtube_video_id"])
            if not statistics:
                continue
            row.update(statistics)
            row["data_source"] = "YouTube Data API v3"

    counts = {
        row["candidate_id"]: count
        for row in rows
        if (count := int_or_none(row["view_count"])) is not None
    }
    percentiles = percentile_ranks(counts) if counts else {}
    for row in rows:
        percentile = percentiles.get(row["candidate_id"])
        row["youtube_percentile"] = f"{percentile:.2f}" if percentile is not None else ""
        row["youtube_tier"] = tier(percentile)

    write_csv(args.output, rows)
    art_tracks = sum(row["youtube_video_type"] == ART_TRACK_TYPE for row in rows)
    ok_rows = sum(row["validation_status"] == "OK" for row in rows)
    print(f"\nResolved Art Tracks: {art_tracks}/{len(rows)}")
    print(f"Rows passing automatic validation: {ok_rows}/{len(rows)}")
    print(f"Rows with view counts: {len(counts)}/{len(rows)}")
    print(f"Data source: {'YouTube Data API v3' if args.api_key else 'ytmusicapi player response'}")
    print(f"Auth profile: {selected_profile or 'anonymous/legacy fallback'}")
    print(f"Results: {args.output}")
    if not args.api_key:
        print("For official verification, set YOUTUBE_API_KEY and rerun.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
