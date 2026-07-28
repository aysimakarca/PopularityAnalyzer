"""Create a reproducible 30-song YouTube Music Discover Mix snapshot.

The command can optionally import Chrome "Copy as cURL" output into one of
the isolated auth profiles before collecting the user's personalized mix.
Credential values are never written to the result CSV or printed.

Example:
    python3 youtube_music/fetch_discover_mix_snapshot.py \
      --profile user_02 \
      2 Week2_28July

This writes by default to:
    experiment_results/Week2_28July/Youtube/User2/Week2_User2_28.07.csv

Each run refreshes the selected profile's auth.json from that profile's
curl_out file before creating a short-lived authorization. You can still pass
--headers-source to use a specific copied cURL file, and --playlist-id to
select a specific Discover Mix playlist URL.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import math
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from ytmusicapi import YTMusic
from ytmusicapi.auth.browser import get_authorization, sapisid_from_cookie

from manage_youtube_profiles import set_request_headers
from youtube_auth_profiles import PROFILE_IDS, account_name, profile_auth_path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_OUTPUT_ROOT = ROOT / "experiment_results"
DEFAULT_WEEK_FOLDER = "Week1_21July"
DEFAULT_WEEK_LABEL = "Week1"
DEFAULT_PLATFORM_FOLDER = "Youtube"
DEFAULT_LIMIT = 30
DEFAULT_PLAYLIST_NAME = "Discover Mix"
CONFIG_PATH = HERE / "youtube_music_config.json"
DEFAULT_CURL_OUT_NAME = "curl_out"

# Frozen reference bands from the 83-song YouTube candidate pool captured on
# 2026-06-29. Heavy Metal MCT was selected with the rank method: ten songs from
# each of Low, Middle, and High, while both transition ranges were buffers.
ORIGINAL_POOL_SIZE = 83
ORIGINAL_POOL_CAPTURED_AT = "2026-06-29T19:44:09+00:00"
ORIGINAL_POOL_BANDS = (
    ("Low", "Low", None, 7_505),
    ("Lower buffer", "Buffer", 7_506, 19_756),
    ("Middle", "Middle", 19_757, 243_792),
    ("Upper buffer", "Buffer", 243_793, 1_223_809),
    ("High", "High", 1_223_810, None),
)
POPULARITY_MEASURE = "cumulative views of the exact recommended YouTube video"
POPULARITY_COMPARISON_NOTE = (
    "Use view_count or popularity_log10_view_count for comparisons across users, weeks, and the "
    "original playlist. Do not use the within-Discover-Mix rank or percentile for cross-playlist "
    "comparisons because those are recalculated separately inside every 30-song mix."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("week_x", nargs="?", help="Week number or prefix, e.g. 2 or Week2.")
    parser.add_argument("experiment_folder", nargs="?", help="Experiment folder name, e.g. Week2_28July.")
    parser.add_argument("--profile", required=True, choices=PROFILE_IDS)
    parser.add_argument(
        "--headers-source",
        type=Path,
        help="Optional Chrome Copy-as-cURL/request-header text file to install for this profile first.",
    )
    parser.add_argument("--playlist-id", help="Discover Mix playlist ID or URL. Auto-detected when possible.")
    parser.add_argument("--playlist-name", default=DEFAULT_PLAYLIST_NAME)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--experiment-folder",
        dest="experiment_folder_flag",
        default="",
        help="Experiment folder name under --output-root, e.g. Week2_28July.",
    )
    parser.add_argument("--week-folder", default=DEFAULT_WEEK_FOLDER, help="Backward-compatible alias for --experiment-folder.")
    parser.add_argument("--week-label", default="", help="Output week label, e.g. Week2. Defaults from x or folder name.")
    parser.add_argument("--week", default="", help="Week number or prefix, e.g. 2 or Week2. Overrides positional x.")
    parser.add_argument("--date-label", default="", help="Filename date label, e.g. 28.07. Defaults from folder name or today.")
    parser.add_argument("--platform-folder", default=DEFAULT_PLATFORM_FOLDER, help="Platform folder under the experiment folder.")
    parser.add_argument("--user-folder", help="Default is User1, User2, etc. from the profile number.")
    parser.add_argument("--output", type=Path, help="Explicit CSV output path; overrides folder/name defaults.")
    parser.add_argument(
        "--use-existing-auth",
        action="store_true",
        help="Skip the default curl_out import and use the current profile auth.json.",
    )
    return parser.parse_args()


def normalized_playlist_id(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    parsed = urlparse(value)
    query = parse_qs(parsed.query)
    if query.get("list"):
        return query["list"][0]
    return value.removeprefix("VL")


def profile_user_folder(profile: str) -> str:
    match = re.fullmatch(r"user_0*([1-9][0-9]*)", profile)
    if not match:
        raise ValueError("Automatic user folders require user_01 through user_10; use --user-folder.")
    return f"User{int(match.group(1))}"


def profile_curl_out_path(profile: str) -> Path:
    return profile_auth_path(profile).parent / DEFAULT_CURL_OUT_NAME


def refresh_profile_auth(profile: str, headers_source: Path | None, use_existing_auth: bool) -> Path | None:
    """Install profile auth from curl_out unless explicitly told not to.

    ``auth.json`` carries a generated Authorization header that can expire. The
    saved ``curl_out`` contains the browser cookie, so importing it before each
    run lets ``temporary_current_auth`` regenerate a fresh SAPISIDHASH value.
    """
    if headers_source:
        set_request_headers(profile, headers_source)
        return headers_source.expanduser().resolve()
    if use_existing_auth:
        return None

    source = profile_curl_out_path(profile)
    if not source.is_file():
        raise FileNotFoundError(
            f"No {DEFAULT_CURL_OUT_NAME} file found for {profile}: {source}. "
            "Save a fresh Chrome Copy-as-cURL dump there, pass --headers-source, "
            "or pass --use-existing-auth to use auth.json as-is."
        )
    set_request_headers(profile, source)
    return source


MONTHS = {
    "january": "01",
    "february": "02",
    "march": "03",
    "april": "04",
    "may": "05",
    "june": "06",
    "july": "07",
    "august": "08",
    "september": "09",
    "october": "10",
    "november": "11",
    "december": "12",
}


def normalize_week_label(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    if cleaned.isdigit():
        return f"Week{cleaned}"
    return cleaned


def infer_week_label_from_folder(folder: str) -> str:
    match = re.search(r"week\s*[_-]?\s*(\d+)", folder or "", flags=re.IGNORECASE)
    return f"Week{int(match.group(1))}" if match else ""


def infer_date_label_from_folder(folder: str) -> str:
    match = re.search(r"(?:^|[_-])(\d{1,2})([A-Za-z]+)(?:$|[_-])", folder or "")
    if not match:
        return ""
    month = MONTHS.get(match.group(2).casefold())
    if not month:
        return ""
    return f"{int(match.group(1)):02d}.{month}"


def resolved_experiment_folder(args: argparse.Namespace) -> str:
    return args.experiment_folder_flag or args.experiment_folder or args.week_folder


def resolved_week_label(args: argparse.Namespace) -> str:
    folder = resolved_experiment_folder(args)
    return (
        normalize_week_label(args.week)
        or normalize_week_label(args.week_x or "")
        or normalize_week_label(args.week_label)
        or infer_week_label_from_folder(folder)
        or DEFAULT_WEEK_LABEL
    )


def resolved_date_label(args: argparse.Namespace) -> str:
    folder = resolved_experiment_folder(args)
    return args.date_label or infer_date_label_from_folder(folder) or datetime.now().strftime("%d.%m")


def output_path(args: argparse.Namespace) -> Path:
    if args.output:
        return args.output.expanduser().resolve()
    user_folder = args.user_folder or profile_user_folder(args.profile)
    week_label = resolved_week_label(args)
    date_label = resolved_date_label(args)
    filename = f"{week_label}_{user_folder}_{date_label}.csv"
    return (
        args.output_root
        / resolved_experiment_folder(args)
        / args.platform_folder
        / user_folder
        / filename
    ).resolve()


def temporary_current_auth(profile: str) -> tuple[Path, tempfile.TemporaryDirectory[str]]:
    """Rebuild the short-lived SAPISIDHASH from the stored long-lived cookie."""
    source = profile_auth_path(profile)
    data = json.loads(source.read_text(encoding="utf-8"))
    cookie = data.get("cookie", "")
    if not cookie:
        raise RuntimeError(f"{profile} auth has no cookie field; import fresh cURL headers.")
    try:
        data["authorization"] = get_authorization(sapisid_from_cookie(cookie))
    except Exception as error:
        raise RuntimeError(f"Could not regenerate {profile} authorization from its cookie: {error}") from error
    directory: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory(prefix="ytmusic-auth-")
    path = Path(directory.name) / "auth.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    path.chmod(0o600)
    return path, directory


def identify_account(ytmusic: YTMusic) -> str:
    try:
        name = account_name(ytmusic.get_account_info())
    except Exception:
        name = None
    if not name:
        raise RuntimeError(
            "The profile is not authenticated. Import a fresh music.youtube.com Copy-as-cURL file "
            "with --headers-source and run again."
        )
    return name


def title_of(item: dict[str, Any]) -> str:
    return str(item.get("title") or item.get("name") or "")


def id_of(item: dict[str, Any]) -> str | None:
    return item.get("playlistId") or item.get("id") or item.get("browseId")


def recursive_playlist_match(value: Any, wanted: str) -> str | None:
    if isinstance(value, dict):
        title = title_of(value)
        candidate = id_of(value)
        if title.casefold() == wanted.casefold() and candidate:
            return normalized_playlist_id(str(candidate))
        for child in value.values():
            found = recursive_playlist_match(child, wanted)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = recursive_playlist_match(child, wanted)
            if found:
                return found
    return None


def configured_playlist_id(profile: str) -> str | None:
    if not CONFIG_PATH.is_file():
        return None
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if config.get("profile") != profile:
        return None
    return normalized_playlist_id(config.get("playlist_id"))


def find_discover_mix(ytmusic: YTMusic, profile: str, playlist_name: str) -> str:
    errors: list[str] = []
    try:
        library = ytmusic.get_library_playlists(limit=None)
        exact = [item for item in library if title_of(item).casefold() == playlist_name.casefold()]
        if len(exact) == 1 and id_of(exact[0]):
            return normalized_playlist_id(str(id_of(exact[0]))) or ""
    except Exception as error:
        errors.append(f"library: {error}")
    try:
        results = ytmusic.search(
            playlist_name,
            filter="playlists",
            scope="library",
            limit=10,
            ignore_spelling=True,
        )
        exact = [item for item in results if title_of(item).casefold() == playlist_name.casefold()]
        if len(exact) == 1 and id_of(exact[0]):
            return normalized_playlist_id(str(id_of(exact[0]))) or ""
    except Exception as error:
        errors.append(f"library search: {error}")
    try:
        home = ytmusic.get_home(limit=10)
        found = recursive_playlist_match(home, playlist_name)
        if found:
            return found
    except Exception as error:
        errors.append(f"home: {error}")
    configured = configured_playlist_id(profile)
    if configured:
        return configured
    note = "; ".join(errors)
    raise RuntimeError(
        f'Could not locate "{playlist_name}" for {profile}. Pass --playlist-id with its playlist URL or ID.'
        + (f" Lookup notes: {note}" if note else "")
    )


def retry(call: Callable[..., Any], *args: Any) -> tuple[Any, str]:
    last_error = ""
    for attempt in range(3):
        try:
            return call(*args), ""
        except Exception as error:
            last_error = str(error)
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    return {}, last_error


def int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value
    match = re.search(r"-?[\d,]+", str(value))
    return int(match.group().replace(",", "")) if match else None


def approximate_count(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = re.sub(r"\s+subscribers?$", "", str(value), flags=re.I).strip().upper()
    match = re.fullmatch(r"([\d,.]+)\s*([KMB]?)", text)
    if not match:
        return int_or_none(value)
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[match.group(2)]
    return round(float(match.group(1).replace(",", "")) * multiplier)


def shelf_count(artist: dict[str, Any], key: str) -> int:
    return len((artist.get(key) or {}).get("results") or [])


def artist_summary(reference: dict[str, Any], details: dict[str, Any], error: str) -> dict[str, Any]:
    subscribers = details.get("subscribers", "")
    return {
        "id": reference.get("id", ""),
        "name": reference.get("name") or details.get("name", ""),
        "subscribers_display": subscribers,
        "subscribers_approx": approximate_count(subscribers),
        "channel_views": int_or_none(details.get("views")),
        "description": details.get("description", ""),
        "song_shelf_count": shelf_count(details, "songs"),
        "album_shelf_count": shelf_count(details, "albums"),
        "single_shelf_count": shelf_count(details, "singles"),
        "video_shelf_count": shelf_count(details, "videos"),
        "lookup_error": error,
    }


def original_pool_popularity_band(view_count: int) -> tuple[str, str]:
    """Classify views using the frozen rank bands used for the original selection."""
    if view_count < 0:
        raise ValueError("view_count cannot be negative")
    for band, tier, minimum, maximum in ORIGINAL_POOL_BANDS:
        if (minimum is None or view_count >= minimum) and (maximum is None or view_count <= maximum):
            return band, tier
    raise AssertionError(f"No original-pool band configured for {view_count} views")


def add_popularity_fields(row: dict[str, Any]) -> None:
    """Add explicit, analysis-ready fields based on the original YouTube method."""
    value = int_or_none(row.get("view_count"))
    row["popularity_measure"] = POPULARITY_MEASURE
    row["popularity_value_view_count"] = value if value is not None else ""
    row["popularity_log10_view_count"] = round(math.log10(value), 9) if value and value > 0 else ""
    if value is None:
        band, tier = "Missing", "Missing"
    else:
        band, tier = original_pool_popularity_band(value)
    row["popularity_original_pool_fixed_band"] = band
    row["popularity_original_pool_fixed_tier"] = tier
    row["popularity_tier_reference"] = (
        f"Frozen {ORIGINAL_POOL_SIZE}-song candidate pool captured {ORIGINAL_POOL_CAPTURED_AT}; "
        "Low <=7,505; lower buffer 7,506-19,756; Middle 19,757-243,792; "
        "upper buffer 243,793-1,223,809; High >=1,223,810 views."
    )
    row["popularity_comparison_note"] = POPULARITY_COMPARISON_NOTE
    video_type = str(row.get("video_type") or "")
    row["popularity_video_version_note"] = (
        "Popularity is for the exact recommended video ID. Report or control video_type because "
        f"this item is {video_type or 'of unknown type'}; ATV denotes an Art Track and OMV an official music video."
    )


def add_view_metrics(rows: list[dict[str, Any]]) -> None:
    observations = sorted(
        [(index, int(row["view_count"])) for index, row in enumerate(rows) if row.get("view_count") not in (None, "")],
        key=lambda item: item[1],
    )
    n = len(observations)
    cursor = 0
    while cursor < n:
        end = cursor + 1
        while end < n and observations[end][1] == observations[cursor][1]:
            end += 1
        average_ascending_rank = ((cursor + 1) + end) / 2
        for tied in range(cursor, end):
            row = rows[observations[tied][0]]
            row["view_rank_within_discover_mix_desc"] = n + 1 - average_ascending_rank
            row["view_percentile_within_discover_mix"] = round(
                100 * (average_ascending_rank - 0.5) / n, 6
            )
            row["log10_view_count"] = round(math.log10(int(row["view_count"])), 9)
        cursor = end
    for row in rows:
        row.setdefault("view_rank_within_discover_mix_desc", "")
        row.setdefault("view_percentile_within_discover_mix", "")
        row.setdefault("log10_view_count", "")
        add_popularity_fields(row)


def assert_safe_output_schema(rows: list[dict[str, Any]]) -> None:
    """Refuse to serialize credential-like fields into a research result."""
    forbidden = ("authorization", "cookie", "token")
    unsafe = sorted({key for row in rows for key in row if any(term in key.casefold() for term in forbidden)})
    if unsafe:
        raise ValueError(f"Credential-like fields are not allowed in result CSVs: {', '.join(unsafe)}")


def collect(
    ytmusic: YTMusic,
    profile: str,
    verified_account: str,
    playlist_id: str,
    limit: int,
    captured_at: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    playlist = ytmusic.get_playlist(playlist_id, limit=limit)
    tracks = (playlist.get("tracks") or [])[:limit]
    if len(tracks) != limit:
        raise RuntimeError(f"Expected {limit} Discover Mix tracks, received {len(tracks)}.")
    if any(not track.get("videoId") for track in tracks):
        raise RuntimeError("At least one Discover Mix item has no videoId; no partial file was written.")

    artist_ids = list(dict.fromkeys(
        artist["id"]
        for track in tracks
        for artist in (track.get("artists") or [])
        if artist.get("id")
    ))
    album_ids = list(dict.fromkeys(
        (track.get("album") or {}).get("id")
        for track in tracks
        if (track.get("album") or {}).get("id")
    ))
    artists: dict[str, tuple[dict[str, Any], str]] = {
        artist_id: retry(ytmusic.get_artist, artist_id) for artist_id in artist_ids
    }
    albums: dict[str, tuple[dict[str, Any], str]] = {
        album_id: retry(ytmusic.get_album, album_id) for album_id in album_ids
    }

    rows: list[dict[str, Any]] = []
    for position, track in enumerate(tracks, 1):
        video_id = track["videoId"]
        print(f"[{position:02d}/{limit}] {track.get('title', 'Unknown')}" )
        song, song_error = retry(ytmusic.get_song, video_id)
        video = song.get("videoDetails") or {}
        micro = (song.get("microformat") or {}).get("microformatDataRenderer") or {}
        playability = song.get("playabilityStatus") or {}
        artist_refs = track.get("artists") or []
        artist_objects = [
            artist_summary(ref, *artists.get(ref.get("id", ""), ({}, "missing artist id")))
            for ref in artist_refs
        ]
        primary = artist_objects[0] if artist_objects else {}
        album_ref = track.get("album") or {}
        album, album_error = albums.get(album_ref.get("id", ""), ({}, "missing album browse id"))
        owner = micro.get("pageOwnerDetails") or {}
        countries = micro.get("availableCountries") or []
        views = int_or_none(video.get("viewCount") or micro.get("viewCount"))
        thumbnail_list = track.get("thumbnails") or []
        micro_thumbnails = (micro.get("thumbnail") or {}).get("thumbnails") or []
        rows.append({
            "captured_at_utc": captured_at,
            "auth_profile": profile,
            "verified_account_name": verified_account,
            "playlist_name": playlist.get("title") or DEFAULT_PLAYLIST_NAME,
            "playlist_id": playlist.get("id") or playlist_id,
            "playlist_url": f"https://music.youtube.com/playlist?list={playlist_id}",
            "playlist_author": json.dumps(playlist.get("author"), ensure_ascii=False) if isinstance(playlist.get("author"), (dict, list)) else playlist.get("author", ""),
            "playlist_track_count_reported": playlist.get("trackCount", ""),
            "playlist_duration": playlist.get("duration", ""),
            "playlist_duration_seconds": playlist.get("duration_seconds", ""),
            "playlist_description": playlist.get("description", ""),
            "playlist_position": position,
            "video_id": video_id,
            "youtube_music_url": f"https://music.youtube.com/watch?v={video_id}",
            "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
            "title": track.get("title") or video.get("title", ""),
            "artists": "; ".join(item.get("name", "") for item in artist_refs) or video.get("author", ""),
            "artist_ids": ";".join(item.get("id", "") for item in artist_refs),
            "artist_details_json": json.dumps(artist_objects, ensure_ascii=False),
            "primary_artist_id": primary.get("id", ""),
            "primary_artist_name": primary.get("name", ""),
            "artist_subscribers_display": primary.get("subscribers_display", ""),
            "artist_subscribers_approx": primary.get("subscribers_approx") or "",
            "artist_channel_views": primary.get("channel_views") or "",
            "artist_description": primary.get("description", ""),
            "artist_song_shelf_count": primary.get("song_shelf_count", ""),
            "artist_album_shelf_count": primary.get("album_shelf_count", ""),
            "artist_single_shelf_count": primary.get("single_shelf_count", ""),
            "artist_video_shelf_count": primary.get("video_shelf_count", ""),
            "album_browse_id": album_ref.get("id", ""),
            "album_name": album_ref.get("name") or album.get("title", ""),
            "album_type": album.get("type", ""),
            "album_year": album.get("year", ""),
            "album_track_count": album.get("trackCount", ""),
            "album_duration": album.get("duration", ""),
            "album_duration_seconds": album.get("duration_seconds", ""),
            "album_audio_playlist_id": album.get("audioPlaylistId", ""),
            "album_artists": "; ".join(item.get("name", "") for item in album.get("artists") or []),
            "album_description": album.get("description", ""),
            "duration": track.get("duration", ""),
            "duration_seconds": int_or_none(track.get("duration_seconds") or video.get("lengthSeconds")) or "",
            "video_type": track.get("videoType") or video.get("musicVideoType", ""),
            "view_count": views if views is not None else "",
            "playlist_view_display": track.get("views", ""),
            "view_count_source": "ytmusicapi player response videoDetails.viewCount",
            "like_count": "",
            "comment_count": "",
            "like_comment_note": "Not exposed by this YouTube Music endpoint; official YouTube Data API credentials are required.",
            "category": micro.get("category", ""),
            "upload_date": micro.get("uploadDate", ""),
            "publish_date": micro.get("publishDate", ""),
            "topic_channel_owner": owner.get("name", ""),
            "topic_channel_id": owner.get("externalChannelId", ""),
            "topic_channel_url": owner.get("youtubeProfileUrl", ""),
            "available_country_count": len(countries),
            "available_country_codes": ";".join(countries),
            "available_countries_note": "Distribution availability, not artist nationality or audience geography.",
            "tags": "; ".join(micro.get("tags") or []),
            "canonical_url": micro.get("urlCanonical", ""),
            "family_safe": micro.get("familySafe", ""),
            "unlisted": micro.get("unlisted", ""),
            "paid": micro.get("paid", ""),
            "allow_ratings": video.get("allowRatings", ""),
            "is_live_content": video.get("isLiveContent", ""),
            "is_private": video.get("isPrivate", ""),
            "is_crawlable": video.get("isCrawlable", ""),
            "is_available": track.get("isAvailable", ""),
            "is_explicit_track": track.get("isExplicit", ""),
            "is_explicit_album": album.get("isExplicit", ""),
            "playability_status": playability.get("status", ""),
            "playable_in_embed": playability.get("playableInEmbed", ""),
            "profile_like_status": track.get("likeStatus", ""),
            "profile_in_library": track.get("inLibrary", ""),
            "thumbnail_url": (micro_thumbnails[-1] if micro_thumbnails else (thumbnail_list[-1] if thumbnail_list else {})).get("url", ""),
            "track_thumbnails_json": json.dumps(thumbnail_list, ensure_ascii=False),
            "song_lookup_error": song_error,
            "artist_lookup_error": "; ".join(item.get("lookup_error", "") for item in artist_objects if item.get("lookup_error")),
            "album_lookup_error": album_error,
            "source_note": "YouTube Music internal web API via ytmusicapi; personalized playlist fetched with named auth profile.",
        })
    add_view_metrics(rows)
    return playlist, rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("Cannot write an empty Discover Mix result.")
    assert_safe_output_schema(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".pending")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def main() -> int:
    args = parse_args()
    if args.limit != 30:
        raise ValueError("This research collector requires exactly --limit 30.")
    auth_refresh_source = refresh_profile_auth(
        args.profile,
        args.headers_source,
        args.use_existing_auth,
    )
    auth_path, temporary_directory = temporary_current_auth(args.profile)
    try:
        ytmusic = YTMusic(str(auth_path))
        verified_account = identify_account(ytmusic)
        playlist_id = normalized_playlist_id(args.playlist_id) or find_discover_mix(
            ytmusic, args.profile, args.playlist_name
        )
        captured_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        playlist, rows = collect(
            ytmusic,
            args.profile,
            verified_account,
            playlist_id,
            args.limit,
            captured_at,
        )
        destination = output_path(args)
        write_csv(destination, rows)
    finally:
        temporary_directory.cleanup()

    print()
    print(f"Auth profile: {args.profile}")
    print(f"Auth refreshed from: {auth_refresh_source or 'existing auth.json'}")
    print(f"Verified account: {verified_account}")
    print(f"Playlist: {playlist.get('title') or args.playlist_name}")
    print(f"Playlist ID: {playlist_id}")
    print(f"Rows: {len(rows)}")
    print(f"Rows with views: {sum(row['view_count'] != '' for row in rows)}/{len(rows)}")
    print(f"Rows with artist subscribers: {sum(row['artist_subscribers_display'] != '' for row in rows)}/{len(rows)}")
    print(f"Output: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
