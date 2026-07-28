"""Fetch Spotify metadata and artist monthly listeners for weekly user playlists.

Example:
    python3 spotify/fetch_weekly_playlist_metadata.py 2 Week2_28July

The script looks for playlists named Week2_User1 ... Week2_User10 by default,
creates User1 ... User10 folders under
experiment_results/Week2_28July/Spotify, and writes per-user CSV/JSON files
plus combined CSV and summary files.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
import warnings

import requests
import spotipy
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyOAuth


warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_CONFIG = HERE / "auth" / "spotify_config.json"
DEFAULT_CACHE = HERE / "auth" / ".spotify_cache"
DEFAULT_MARKET = "from_token"


FIELDNAMES = [
    "snapshot_label", "captured_at_utc", "platform",
    "source_account_display_name", "source_account_id",
    "requested_playlist_name", "playlist_name", "playlist_id", "playlist_uri",
    "playlist_url", "playlist_description", "playlist_owner_id",
    "playlist_owner_display_name", "playlist_public", "playlist_collaborative",
    "playlist_followers_total", "playlist_snapshot_id", "playlist_total_tracks",
    "playlist_position", "playlist_added_at", "playlist_added_by_id",
    "popularity_metric", "popularity_metric_value", "popularity_metric_display",
    "popularity_metric_source", "popularity_metric_is_approx",
    "popularity_metric_fetch_error",
    "spotify_track_id", "spotify_uri", "spotify_url", "track_name",
    "track_type", "track_number", "disc_number", "duration_ms",
    "duration_seconds", "explicit", "is_local", "is_playable", "preview_url",
    "track_href", "track_api_href", "track_api_popularity", "track_lookup_error",
    "isrc", "ean", "upc",
    "album_id", "album_uri", "album_url", "album_name", "album_type",
    "album_group", "album_total_tracks", "album_release_date",
    "album_release_date_precision", "album_label", "album_copyrights",
    "album_genres", "album_image_url", "album_lookup_error",
    "primary_artist_id", "primary_artist_name", "primary_artist_uri",
    "primary_artist_url", "primary_artist_genres",
    "primary_artist_spotify_api_popularity", "primary_artist_followers_total",
    "primary_artist_monthly_listeners",
    "primary_artist_monthly_listeners_display",
    "primary_artist_monthly_listeners_is_approx",
    "primary_artist_monthly_listeners_source",
    "primary_artist_monthly_listeners_fetch_error",
    "primary_artist_image_url", "primary_artist_lookup_error",
    "artist_ids", "artist_names", "artist_urls",
    "artist_monthly_listeners_json", "artists_json",
    "available_markets_count", "available_markets",
    "external_urls_json", "restrictions_json",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "week_x",
        nargs="?",
        help="Week number or prefix, e.g. 2 or Week2.",
    )
    parser.add_argument(
        "experiment_folder",
        nargs="?",
        help="Experiment result folder name, e.g. Week2_28July.",
    )
    parser.add_argument(
        "--week",
        default="",
        help="Week number or prefix used in playlist names, e.g. 2 or Week2.",
    )
    parser.add_argument(
        "--experiment-folder",
        dest="experiment_folder_flag",
        default="",
        help="Experiment result folder name under experiment_results, e.g. Week2_28July.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help=(
            "Folder where User1/User2/... output folders will be created. "
            "Defaults to experiment_results/<experiment-folder>/Spotify."
        ),
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--market", default=DEFAULT_MARKET)
    parser.add_argument("--start-user", type=int, default=1)
    parser.add_argument("--end-user", type=int, default=10)
    parser.add_argument(
        "--snapshot-label",
        default="",
        help="Optional label stored in the output. Defaults to a slug from the experiment folder.",
    )
    parser.add_argument(
        "--no-json",
        action="store_true",
        help="Only write CSV files; skip per-user JSON files.",
    )
    parser.add_argument(
        "--strict-playlist-names",
        action="store_true",
        help="Require exact playlist names instead of allowing whitespace variants.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve playlist names but do not fetch tracks or write output.",
    )
    return parser.parse_args()


def slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_")
    return cleaned or "spotify"


def normalize_week(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise RuntimeError("Provide a week number/prefix, e.g. 2 or Week2.")
    if cleaned.isdigit():
        return f"Week{cleaned}"
    return cleaned


def canonical_playlist_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").casefold())


def user_from_name(name: str) -> str:
    match = re.search(r"user\s*(\d+)", name or "", flags=re.IGNORECASE)
    return f"User{int(match.group(1))}" if match else ""


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def create_spotify_client(config_path: Path, cache_path: Path) -> spotipy.Spotify:
    config = load_config(config_path)
    auth = SpotifyOAuth(
        client_id=config["client_id"],
        client_secret=config["client_secret"],
        redirect_uri=config["redirect_uri"],
        scope="playlist-read-private playlist-read-collaborative user-library-read",
        cache_path=str(cache_path),
        open_browser=False,
    )
    return spotipy.Spotify(auth_manager=auth, requests_timeout=25, retries=3)


def compact_to_int(raw: str) -> int | None:
    cleaned = (
        (raw or "")
        .strip()
        .upper()
        .replace(",", "")
        .replace(" ", "")
        .replace("\u00a0", "")
    )
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KMB]?)", cleaned)
    if not match:
        return None
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    return round(float(match.group(1)) * multiplier[match.group(2)])


def fetch_monthly_listeners(
    session: requests.Session,
    artist_url: str,
    cache: dict[str, dict[str, str]],
) -> dict[str, str]:
    if not artist_url:
        return {
            "artist_monthly_listeners": "",
            "artist_monthly_listeners_display": "",
            "artist_monthly_listeners_is_approx": "",
            "artist_monthly_listeners_source": "Spotify public artist page",
            "artist_monthly_listeners_fetch_error": "missing artist URL",
        }
    if artist_url in cache:
        return cache[artist_url]

    result = {
        "artist_monthly_listeners": "",
        "artist_monthly_listeners_display": "",
        "artist_monthly_listeners_is_approx": "",
        "artist_monthly_listeners_source": "Spotify public artist page",
        "artist_monthly_listeners_fetch_error": "",
    }
    try:
        response = session.get(artist_url, timeout=25)
        response.raise_for_status()
    except requests.RequestException as error:
        result["artist_monthly_listeners_fetch_error"] = str(error)
        cache[artist_url] = result
        return result

    exact = re.search(
        r'data-testid=["\']monthly-listeners-label["\'][^>]*>\s*'
        r"([0-9][0-9, .\u00a0]*)\s+monthly listeners",
        response.text,
        flags=re.IGNORECASE,
    )
    if exact:
        display = exact.group(1).replace("\u00a0", " ").strip()
        value = compact_to_int(display)
        if value is not None:
            result.update({
                "artist_monthly_listeners": str(value),
                "artist_monthly_listeners_display": display,
                "artist_monthly_listeners_is_approx": "false",
            })
            cache[artist_url] = result
            return result

    compact = re.search(
        r"(?:Artist\s*(?:·|&middot;|\\u00B7)\s*)?"
        r"([0-9]+(?:\.[0-9]+)?\s*[KMB]?)\s+monthly listeners",
        response.text,
        flags=re.IGNORECASE,
    )
    if compact:
        display = compact.group(1).replace(" ", "")
        value = compact_to_int(display)
        if value is not None:
            result.update({
                "artist_monthly_listeners": str(value),
                "artist_monthly_listeners_display": display,
                "artist_monthly_listeners_is_approx": (
                    "true" if re.search(r"[KMB]", display, re.IGNORECASE) else "false"
                ),
            })
            cache[artist_url] = result
            return result

    result["artist_monthly_listeners_fetch_error"] = "monthly-listener text not found"
    cache[artist_url] = result
    return result


def all_user_playlists(sp: spotipy.Spotify) -> list[dict[str, Any]]:
    playlists: list[dict[str, Any]] = []
    page = sp.current_user_playlists(limit=50)
    while page:
        playlists.extend(item for item in page.get("items", []) if item)
        page = sp.next(page) if page.get("next") else None
    return playlists


def resolve_playlists(
    playlists: list[dict[str, Any]],
    week: str,
    start_user: int,
    end_user: int,
    strict: bool,
) -> list[tuple[int, str, dict[str, Any]]]:
    exact = {}
    canonical = {}
    for playlist in playlists:
        name = playlist.get("name", "")
        exact.setdefault(name, []).append(playlist)
        canonical.setdefault(canonical_playlist_name(name), []).append(playlist)

    resolved = []
    missing = []
    duplicates = []
    for user_num in range(start_user, end_user + 1):
        requested = f"{week}_User{user_num}"
        matches = exact.get(requested, [])
        if not strict and not matches:
            matches = canonical.get(canonical_playlist_name(requested), [])
            matches = [
                playlist
                for playlist in matches
                if user_from_name(playlist.get("name", "")) == f"User{user_num}"
            ] or matches
        if not matches:
            missing.append(requested)
            continue
        if len(matches) > 1:
            duplicates.append((requested, matches))
            continue
        resolved.append((user_num, requested, matches[0]))

    if missing or duplicates:
        messages = []
        if missing:
            messages.append(f"Missing playlists: {', '.join(missing)}")
        for requested, matches in duplicates:
            details = ", ".join(f"{m.get('name')} ({m.get('id')})" for m in matches)
            messages.append(f"Multiple playlists for {requested}: {details}")
        raise RuntimeError("\n".join(messages))
    return resolved


def image_url(images: list[dict[str, Any]] | None, index: int = 0) -> str:
    if not images or index >= len(images):
        return ""
    return images[index].get("url", "") or ""


def copyrights(album: dict[str, Any] | None) -> str:
    return "; ".join(
        f"{item.get('type', '')}: {item.get('text', '')}"
        for item in (album or {}).get("copyrights", []) or []
    )


class SpotifyMetadataFetcher:
    def __init__(self, sp: spotipy.Spotify, market: str) -> None:
        self.sp = sp
        self.market = market
        self.track_cache: dict[str, dict[str, Any]] = {}
        self.album_cache: dict[str, dict[str, Any]] = {}
        self.artist_cache: dict[str, dict[str, Any]] = {}
        self.listener_cache: dict[str, dict[str, str]] = {}
        self.web = requests.Session()
        self.web.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 Safari/605.1.15"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        })

    def get_track(self, track_id: str, fallback: dict[str, Any]) -> dict[str, Any]:
        if track_id in self.track_cache:
            return self.track_cache[track_id]
        try:
            track = self.sp.track(track_id, market=self.market)
            if track:
                self.track_cache[track_id] = track
                return track
        except SpotifyException as error:
            fallback["_track_lookup_error"] = f"SpotifyException {error.http_status}: {error.msg}"
        except Exception as error:  # noqa: BLE001 - preserve fetch diagnostics in output.
            fallback["_track_lookup_error"] = f"{type(error).__name__}: {error}"
        self.track_cache[track_id] = fallback
        return fallback

    def get_album(self, album_id: str) -> dict[str, Any]:
        if not album_id:
            return {}
        if album_id in self.album_cache:
            return self.album_cache[album_id]
        try:
            self.album_cache[album_id] = self.sp.album(album_id, market=self.market) or {}
        except Exception as error:  # noqa: BLE001
            self.album_cache[album_id] = {"_album_lookup_error": f"{type(error).__name__}: {error}"}
        return self.album_cache[album_id]

    def get_artist(self, artist_id: str) -> dict[str, Any]:
        if not artist_id:
            return {}
        if artist_id in self.artist_cache:
            return self.artist_cache[artist_id]
        try:
            self.artist_cache[artist_id] = self.sp.artist(artist_id) or {}
        except Exception as error:  # noqa: BLE001
            self.artist_cache[artist_id] = {"_artist_lookup_error": f"{type(error).__name__}: {error}"}
        return self.artist_cache[artist_id]

    def artist_summary(self, artist_stub: dict[str, Any]) -> dict[str, str]:
        artist_id = artist_stub.get("id", "")
        artist = self.get_artist(artist_id)
        artist_url = (
            artist_stub.get("external_urls", {}).get("spotify", "")
            or artist.get("external_urls", {}).get("spotify", "")
        )
        listeners = fetch_monthly_listeners(self.web, artist_url, self.listener_cache)
        followers = artist.get("followers") if isinstance(artist.get("followers"), dict) else {}
        return {
            "artist_id": artist_id,
            "artist_name": artist_stub.get("name") or artist.get("name", ""),
            "artist_uri": artist_stub.get("uri", "") or artist.get("uri", ""),
            "artist_url": artist_url,
            "artist_type": artist.get("type", ""),
            "artist_genres": "; ".join(artist.get("genres", []) or []),
            "artist_spotify_api_popularity": (
                "" if artist.get("popularity") is None else str(artist.get("popularity"))
            ),
            "artist_followers_total": (
                "" if followers.get("total") is None else str(followers.get("total"))
            ),
            "artist_image_url": image_url(artist.get("images")),
            "artist_lookup_error": artist.get("_artist_lookup_error", ""),
            **listeners,
        }


def playlist_items(sp: spotipy.Spotify, playlist_id: str, market: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = sp.playlist_items(
        playlist_id,
        limit=100,
        market=market,
        additional_types=("track",),
    )
    while page:
        items.extend(page.get("items", []))
        page = sp.next(page) if page.get("next") else None
    return items


def build_row(
    fetcher: SpotifyMetadataFetcher,
    wrapper: dict[str, Any],
    playlist: dict[str, Any],
    requested_name: str,
    position: int,
    captured_at: str,
    snapshot_label: str,
    source_user: dict[str, Any],
) -> dict[str, str]:
    fallback_track = wrapper.get("track") or wrapper.get("item") or {}
    track_id = fallback_track.get("id", "")
    track = fetcher.get_track(track_id, fallback_track) if track_id else fallback_track
    album_stub = track.get("album") or {}
    album = fetcher.get_album(album_stub.get("id", ""))
    artists = [fetcher.artist_summary(artist) for artist in track.get("artists", [])]
    primary = artists[0] if artists else {}
    external_ids = track.get("external_ids") or {}
    markets = track.get("available_markets") or []

    return {
        "snapshot_label": snapshot_label,
        "captured_at_utc": captured_at,
        "platform": "Spotify",
        "source_account_display_name": source_user.get("display_name", ""),
        "source_account_id": source_user.get("id", ""),
        "requested_playlist_name": requested_name,
        "playlist_name": playlist.get("name", requested_name),
        "playlist_id": playlist.get("id", ""),
        "playlist_uri": playlist.get("uri", ""),
        "playlist_url": playlist.get("external_urls", {}).get("spotify", ""),
        "playlist_description": playlist.get("description", ""),
        "playlist_owner_id": playlist.get("owner", {}).get("id", ""),
        "playlist_owner_display_name": playlist.get("owner", {}).get("display_name", ""),
        "playlist_public": str(playlist.get("public", "")),
        "playlist_collaborative": str(playlist.get("collaborative", "")),
        "playlist_followers_total": str((playlist.get("followers") or {}).get("total", "")),
        "playlist_snapshot_id": playlist.get("snapshot_id", ""),
        "playlist_total_tracks": str((playlist.get("tracks") or {}).get("total", "")),
        "playlist_position": str(position),
        "playlist_added_at": wrapper.get("added_at", ""),
        "playlist_added_by_id": (wrapper.get("added_by") or {}).get("id", ""),
        "popularity_metric": "primary_artist_monthly_listeners",
        "popularity_metric_value": primary.get("artist_monthly_listeners", ""),
        "popularity_metric_display": primary.get("artist_monthly_listeners_display", ""),
        "popularity_metric_source": primary.get("artist_monthly_listeners_source", ""),
        "popularity_metric_is_approx": primary.get("artist_monthly_listeners_is_approx", ""),
        "popularity_metric_fetch_error": primary.get("artist_monthly_listeners_fetch_error", ""),
        "spotify_track_id": track.get("id", ""),
        "spotify_uri": track.get("uri", ""),
        "spotify_url": track.get("external_urls", {}).get("spotify", ""),
        "track_name": track.get("name", ""),
        "track_type": track.get("type", ""),
        "track_number": str(track.get("track_number", "")),
        "disc_number": str(track.get("disc_number", "")),
        "duration_ms": str(track.get("duration_ms", "")),
        "duration_seconds": (
            f"{(track.get('duration_ms') or 0) / 1000:.3f}"
            if track.get("duration_ms")
            else ""
        ),
        "explicit": str(track.get("explicit", "")),
        "is_local": str(track.get("is_local", "")),
        "is_playable": str(track.get("is_playable", "")),
        "preview_url": track.get("preview_url") or "",
        "track_href": track.get("href", ""),
        "track_api_href": track.get("href", ""),
        "track_api_popularity": "" if track.get("popularity") is None else str(track.get("popularity")),
        "track_lookup_error": track.get("_track_lookup_error", ""),
        "isrc": external_ids.get("isrc", ""),
        "ean": external_ids.get("ean", ""),
        "upc": external_ids.get("upc", ""),
        "album_id": album_stub.get("id", ""),
        "album_uri": album_stub.get("uri", ""),
        "album_url": album_stub.get("external_urls", {}).get("spotify", ""),
        "album_name": album_stub.get("name", ""),
        "album_type": album_stub.get("album_type", ""),
        "album_group": album_stub.get("album_group", ""),
        "album_total_tracks": str(album_stub.get("total_tracks", "")),
        "album_release_date": album_stub.get("release_date", ""),
        "album_release_date_precision": album_stub.get("release_date_precision", ""),
        "album_label": album.get("label", ""),
        "album_copyrights": copyrights(album),
        "album_genres": "; ".join(album.get("genres", []) or []),
        "album_image_url": image_url(album_stub.get("images")),
        "album_lookup_error": album.get("_album_lookup_error", ""),
        "primary_artist_id": primary.get("artist_id", ""),
        "primary_artist_name": primary.get("artist_name", ""),
        "primary_artist_uri": primary.get("artist_uri", ""),
        "primary_artist_url": primary.get("artist_url", ""),
        "primary_artist_genres": primary.get("artist_genres", ""),
        "primary_artist_spotify_api_popularity": primary.get("artist_spotify_api_popularity", ""),
        "primary_artist_followers_total": primary.get("artist_followers_total", ""),
        "primary_artist_monthly_listeners": primary.get("artist_monthly_listeners", ""),
        "primary_artist_monthly_listeners_display": primary.get("artist_monthly_listeners_display", ""),
        "primary_artist_monthly_listeners_is_approx": primary.get("artist_monthly_listeners_is_approx", ""),
        "primary_artist_monthly_listeners_source": primary.get("artist_monthly_listeners_source", ""),
        "primary_artist_monthly_listeners_fetch_error": primary.get("artist_monthly_listeners_fetch_error", ""),
        "primary_artist_image_url": primary.get("artist_image_url", ""),
        "primary_artist_lookup_error": primary.get("artist_lookup_error", ""),
        "artist_ids": "; ".join(artist.get("artist_id", "") for artist in artists if artist.get("artist_id")),
        "artist_names": "; ".join(artist.get("artist_name", "") for artist in artists if artist.get("artist_name")),
        "artist_urls": "; ".join(artist.get("artist_url", "") for artist in artists if artist.get("artist_url")),
        "artist_monthly_listeners_json": json.dumps([
            {
                "artist_id": artist.get("artist_id", ""),
                "artist_name": artist.get("artist_name", ""),
                "artist_url": artist.get("artist_url", ""),
                "monthly_listeners": artist.get("artist_monthly_listeners", ""),
                "monthly_listeners_display": artist.get("artist_monthly_listeners_display", ""),
                "is_approx": artist.get("artist_monthly_listeners_is_approx", ""),
                "fetch_error": artist.get("artist_monthly_listeners_fetch_error", ""),
            }
            for artist in artists
        ], ensure_ascii=False),
        "artists_json": json.dumps(artists, ensure_ascii=False),
        "available_markets_count": str(len(markets)),
        "available_markets": "; ".join(markets),
        "external_urls_json": json.dumps(track.get("external_urls", {}), ensure_ascii=False),
        "restrictions_json": json.dumps(track.get("restrictions", {}), ensure_ascii=False),
    }


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)


def main() -> int:
    args = parse_args()
    if args.start_user > args.end_user:
        raise RuntimeError("--start-user cannot be greater than --end-user")

    week = normalize_week(args.week or args.week_x or "")
    experiment_folder = args.experiment_folder_flag or args.experiment_folder or ""
    if not experiment_folder:
        raise RuntimeError("Provide an experiment folder, e.g. Week2_28July.")
    output_root = (
        args.output_root.expanduser().resolve()
        if args.output_root is not None
        else (ROOT / "experiment_results" / experiment_folder / "Spotify")
    )

    sp = create_spotify_client(args.config, args.cache)
    source_user = sp.current_user()
    resolved = resolve_playlists(
        all_user_playlists(sp),
        week,
        args.start_user,
        args.end_user,
        args.strict_playlist_names,
    )

    print(f"Spotify account: {source_user.get('display_name')} ({source_user.get('id')})")
    print("Resolved playlists:")
    for user_num, requested, playlist in resolved:
        print(
            f"  User{user_num}: requested={requested!r}, "
            f"actual={playlist.get('name')!r}, id={playlist.get('id')}"
        )
    if args.dry_run:
        return 0

    snapshot_label = args.snapshot_label or slug(experiment_folder).casefold()
    captured_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    fetcher = SpotifyMetadataFetcher(sp, args.market)
    output_root = output_root.resolve()
    all_rows: list[dict[str, str]] = []
    summary_rows: list[dict[str, str]] = []

    for user_num, requested, playlist_stub in resolved:
        user_label = f"User{user_num}"
        playlist = sp.playlist(playlist_stub["id"], market=args.market)
        items = playlist_items(sp, playlist["id"], args.market)
        rows = []
        position = 0
        print(f"\nFetching {user_label}: {playlist.get('name')} ({playlist.get('id')})")

        for wrapper in items:
            fallback_track = wrapper.get("track") or wrapper.get("item") or {}
            if not fallback_track or fallback_track.get("type") != "track":
                continue
            position += 1
            row = build_row(
                fetcher,
                wrapper,
                playlist,
                requested,
                position,
                captured_at,
                snapshot_label,
                source_user,
            )
            rows.append(row)
            all_rows.append(row)
            print(
                f"  {position:02d}. {row['artist_names']} - {row['track_name']} | "
                f"{row['popularity_metric_display'] or row['popularity_metric_value'] or 'listeners missing'}"
            )
            time.sleep(0.03)

        user_dir = output_root / user_label
        csv_path = user_dir / f"{slug(week)}_{user_label}_spotify_metadata.csv"
        json_path = user_dir / f"{slug(week)}_{user_label}_spotify_metadata.json"
        write_csv(csv_path, rows, FIELDNAMES)
        if not args.no_json:
            write_json(json_path, rows)

        monthly_count = sum(1 for row in rows if row.get("primary_artist_monthly_listeners"))
        summary_rows.append({
            "user": user_label,
            "requested_playlist_name": requested,
            "actual_playlist_name": playlist.get("name", requested),
            "playlist_id": playlist.get("id", ""),
            "playlist_url": playlist.get("external_urls", {}).get("spotify", ""),
            "tracks": str(len(rows)),
            "tracks_with_primary_artist_monthly_listeners": str(monthly_count),
            "csv_path": str(csv_path),
            "json_path": "" if args.no_json else str(json_path),
        })
        print(f"Wrote {csv_path}")

    week_slug = slug(week)
    combined_path = output_root / f"{week_slug}_users{args.start_user}-{args.end_user}_spotify_metadata.csv"
    summary_path = output_root / f"{week_slug}_users{args.start_user}-{args.end_user}_fetch_summary.csv"
    write_csv(combined_path, all_rows, FIELDNAMES)
    write_csv(summary_path, summary_rows, list(summary_rows[0].keys()))

    monthly_total = sum(1 for row in all_rows if row.get("primary_artist_monthly_listeners"))
    print(f"\nCombined CSV: {combined_path}")
    print(f"Summary CSV: {summary_path}")
    print(f"Total rows: {len(all_rows)}")
    print(f"Rows with primary artist monthly listeners: {monthly_total}/{len(all_rows)}")
    print(f"Unique artist page lookups: {len(fetcher.listener_cache)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:  # noqa: BLE001
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
