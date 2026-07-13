"""
YouTube Music Discover Mix metadata fetcher.

Prerequisites:
1. Open the YouTube Music folder: cd youtube_music
2. Install ytmusicapi: pip install -r requirements_youtube_music.txt
3. Create auth headers once:
   python3 youtube_music_discover_mix.py --setup-auth
4. If the script cannot find Discover Mix in your library, paste the playlist
   URL or playlist id into youtube_music_config.json under "playlist_id".

YouTube Music API note:
- ytmusicapi uses YouTube Music's internal web API, not an official public API.
- YouTube Music does not expose a clean per-song listener count. This script
  fetches YouTube view counts for each song when available, plus artist channel
  views/subscribers when YouTube Music returns them.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
import warnings

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")
logging.getLogger("ytmusicapi").setLevel(logging.CRITICAL)

try:
    from ytmusicapi import YTMusic, setup as setup_ytmusic_headers
except ModuleNotFoundError as e:
    raise SystemExit(
        "ytmusicapi is not installed. Run: "
        "pip install -r requirements_youtube_music.txt"
    ) from e

from youtube_auth_profiles import PROFILE_IDS, profile_auth_path, resolve_auth_path


CONFIG_FILE = "youtube_music_config.json"
DEFAULT_AUTH_FILE = "auth/ytmusic_auth.json"
DEFAULT_PLAYLIST_NAME = "Discover Mix"
DEFAULT_TRACK_LIMIT = 30
DEFAULT_OUTPUT_FILE = "youtube_music_discover_mix_songs.txt"
DEFAULT_JSON_OUTPUT_FILE = "youtube_music_discover_mix_songs.json"


def script_command() -> str:
    """Return a command that runs this script from the current directory."""
    script_path = Path(__file__).resolve()
    try:
        display_path = script_path.relative_to(Path.cwd().resolve())
    except ValueError:
        display_path = script_path
    return f"python3 {display_path}"


def project_path(path_value: str | Path) -> Path:
    """Resolve relative paths from this script's directory."""
    path = Path(path_value)
    if path.is_absolute():
        return path
    return Path(__file__).parent / path


def load_config(config_file: str) -> dict[str, Any]:
    """Load YouTube Music settings, falling back to sensible defaults."""
    config_path = project_path(config_file)
    defaults = {
        "auth_file": DEFAULT_AUTH_FILE,
        "profile": "",
        "playlist_name": DEFAULT_PLAYLIST_NAME,
        "playlist_id": "",
        "track_limit": DEFAULT_TRACK_LIMIT,
        "output_file": DEFAULT_OUTPUT_FILE,
        "json_output_file": DEFAULT_JSON_OUTPUT_FILE,
        "search_library": True,
        "allow_public_search": False,
    }

    if not config_path.exists():
        return defaults

    with open(config_path, "r", encoding="utf-8") as f:
        loaded = json.load(f)

    return {**defaults, **loaded}


def apply_cli_overrides(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """Apply command-line values over config-file values."""
    if args.playlist_id:
        config["playlist_id"] = args.playlist_id
    if args.playlist_name:
        config["playlist_name"] = args.playlist_name
    if args.limit:
        config["track_limit"] = args.limit
    if args.output:
        config["output_file"] = args.output
    if args.json_output:
        config["json_output_file"] = args.json_output
    if args.auth_file:
        config["auth_file"] = args.auth_file
        config["profile"] = ""
    if args.profile:
        config["profile"] = args.profile
        config["auth_file"] = ""
    if args.public_search:
        config["allow_public_search"] = True

    return config


def setup_auth_file(auth_file: str) -> Path:
    """Create a ytmusicapi browser-header auth file."""
    auth_path = project_path(auth_file)
    auth_path.parent.mkdir(parents=True, exist_ok=True)

    print("This will create YouTube Music browser-header auth for ytmusicapi.")
    print("When prompted, paste request headers copied from music.youtube.com.")
    print(f"Auth file: {auth_path}")
    setup_ytmusic_headers(filepath=str(auth_path))

    return auth_path


def create_ytmusic_client(config: dict[str, Any]) -> tuple[YTMusic, bool, Path]:
    """Create a YouTube Music client, authenticated when an auth file exists."""
    profile = config.get("profile") or None
    configured_auth = config.get("auth_file") or None
    if configured_auth and not Path(configured_auth).is_absolute():
        configured_auth = project_path(configured_auth)

    try:
        auth_path, _selected_profile = resolve_auth_path(
            profile=profile,
            auth_path=configured_auth,
        )
    except FileNotFoundError:
        if profile or configured_auth:
            raise
        auth_path = project_path(DEFAULT_AUTH_FILE)

    if auth_path.exists():
        return YTMusic(str(auth_path)), True, auth_path

    print(f"Auth file not found: {auth_path}")
    print("Using an anonymous YouTube Music client.")
    print(
        "Personalized/library playlists usually need auth. "
        f"Run: {script_command()} --setup-auth"
    )
    print()
    return YTMusic(), False, auth_path


def normalize_playlist_id(value: str | None) -> str | None:
    """Accept a raw playlist id or a YouTube Music playlist/watch URL."""
    if not value:
        return None

    value = value.strip()
    if not value:
        return None

    parsed = urlparse(value)
    query = parse_qs(parsed.query)
    if "list" in query and query["list"]:
        return query["list"][0]

    return value


def first_present(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first non-empty value from a dict."""
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def playlist_title(playlist: dict[str, Any]) -> str:
    """Return a playlist title from common ytmusicapi result shapes."""
    return str(first_present(playlist, ("title", "name")) or "")


def playlist_id(playlist: dict[str, Any]) -> str | None:
    """Return a playlist id from common ytmusicapi result shapes."""
    return first_present(playlist, ("playlistId", "browseId", "id"))


def choose_playlist_by_name(playlists: list[dict[str, Any]], playlist_name: str) -> dict[str, Any] | None:
    """Choose an exact title match first, then a contains match."""
    wanted = playlist_name.casefold()
    exact_matches = [p for p in playlists if playlist_title(p).casefold() == wanted]
    if exact_matches:
        return exact_matches[0]

    contains_matches = [p for p in playlists if wanted in playlist_title(p).casefold()]
    if contains_matches:
        return contains_matches[0]

    return None


def find_playlist_by_name(
    ytmusic: YTMusic,
    playlist_name: str,
    search_library: bool,
    allow_public_search: bool,
) -> tuple[str | None, str | None]:
    """Find a playlist id by title in the authenticated library or public search."""
    errors: list[str] = []

    if search_library:
        try:
            library_playlists = ytmusic.get_library_playlists(limit=None)
            match = choose_playlist_by_name(library_playlists, playlist_name)
            if match and playlist_id(match):
                return playlist_id(match), playlist_title(match)
        except Exception as e:
            errors.append(f"library playlist lookup failed: {e}")

        try:
            library_results = ytmusic.search(
                playlist_name,
                filter="playlists",
                scope="library",
                limit=10,
                ignore_spelling=True,
            )
            match = choose_playlist_by_name(library_results, playlist_name)
            if match and playlist_id(match):
                return playlist_id(match), playlist_title(match)
        except Exception as e:
            errors.append(f"library playlist search failed: {e}")

    if allow_public_search:
        try:
            public_results = ytmusic.search(
                playlist_name,
                filter="playlists",
                limit=10,
                ignore_spelling=True,
            )
            match = choose_playlist_by_name(public_results, playlist_name)
            if match and playlist_id(match):
                return playlist_id(match), playlist_title(match)
        except Exception as e:
            errors.append(f"public playlist search failed: {e}")

    if errors:
        print("Playlist lookup notes:")
        for error in errors:
            print(f"  - {error}")
        print()

    return None, None


def int_or_none(value: Any) -> int | None:
    """Convert a number-like value into int when possible."""
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).replace(",", "").strip())
    except ValueError:
        return None


def format_number(value: Any) -> str:
    """Format numeric values with commas while preserving compact strings."""
    numeric_value = int_or_none(value)
    if numeric_value is not None:
        return f"{numeric_value:,}"
    if value:
        return str(value)
    return "Unknown"


def format_duration(duration_seconds: int | None, fallback: str | None = None) -> str:
    """Format a duration in seconds as m:ss or h:mm:ss."""
    if duration_seconds is None:
        return fallback or "Unknown"

    hours, remainder = divmod(duration_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def safe_get_song(ytmusic: YTMusic, video_id: str) -> tuple[dict[str, Any], str | None]:
    """Fetch song details while keeping one bad track from stopping the run."""
    try:
        return ytmusic.get_song(video_id), None
    except Exception as e:
        return {}, str(e)


def fetch_artists_by_id(ytmusic: YTMusic, artist_ids: set[str]) -> dict[str, dict[str, Any]]:
    """Fetch artist/channel metadata keyed by artist id."""
    artists_by_id: dict[str, dict[str, Any]] = {}

    for artist_id in sorted(artist_ids):
        try:
            artists_by_id[artist_id] = ytmusic.get_artist(artist_id)
        except Exception as e:
            artists_by_id[artist_id] = {"error": str(e)}

    return artists_by_id


def build_artist_summary(
    track_artists: list[dict[str, Any]],
    artists_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build artist detail objects for one track."""
    artist_summaries = []

    for artist in track_artists:
        artist_id = artist.get("id")
        artist_data = artists_by_id.get(artist_id or "", {})
        artist_summaries.append(
            {
                "id": artist_id,
                "name": artist.get("name") or artist_data.get("name") or "Unknown artist",
                "subscribers": artist_data.get("subscribers"),
                "views": artist_data.get("views"),
                "url": f"https://music.youtube.com/channel/{artist_id}" if artist_id else None,
                "lookup_error": artist_data.get("error"),
            }
        )

    return artist_summaries


def build_track_summary(
    number: int,
    playlist_track: dict[str, Any],
    song_data: dict[str, Any],
    song_error: str | None,
    artists_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build one normalized track metadata object."""
    video_id = playlist_track.get("videoId")
    video_details = song_data.get("videoDetails", {})
    track_artists = playlist_track.get("artists") or []
    artist_details = build_artist_summary(track_artists, artists_by_id)
    duration_seconds = int_or_none(
        first_present(playlist_track, ("duration_seconds",))
        or video_details.get("lengthSeconds")
    )
    album = playlist_track.get("album") or {}

    return {
        "number": number,
        "video_id": video_id,
        "name": playlist_track.get("title") or video_details.get("title") or "Unknown title",
        "artists": ", ".join(artist["name"] for artist in artist_details) or video_details.get("author"),
        "artist_details": artist_details,
        "album": album.get("name") if isinstance(album, dict) else None,
        "duration": format_duration(duration_seconds, playlist_track.get("duration")),
        "duration_seconds": duration_seconds,
        "view_count": int_or_none(video_details.get("viewCount")),
        "view_count_raw": video_details.get("viewCount"),
        "video_type": playlist_track.get("videoType") or video_details.get("musicVideoType"),
        "is_available": playlist_track.get("isAvailable"),
        "is_explicit": playlist_track.get("isExplicit"),
        "like_status": playlist_track.get("likeStatus"),
        "url": f"https://music.youtube.com/watch?v={video_id}" if video_id else None,
        "song_lookup_error": song_error,
    }


def fetch_playlist_tracks(
    ytmusic: YTMusic,
    playlist_id_value: str,
    limit: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fetch a playlist and enrich its first N tracks."""
    playlist = ytmusic.get_playlist(playlist_id_value, limit=limit)
    playlist_tracks = (playlist.get("tracks") or [])[:limit]
    artist_ids = {
        artist.get("id")
        for track in playlist_tracks
        for artist in track.get("artists", [])
        if artist.get("id")
    }

    artists_by_id = fetch_artists_by_id(ytmusic, artist_ids)
    tracks = []

    for number, playlist_track in enumerate(playlist_tracks, 1):
        video_id = playlist_track.get("videoId")
        song_data: dict[str, Any] = {}
        song_error = None

        if video_id:
            song_data, song_error = safe_get_song(ytmusic, video_id)
        else:
            song_error = "Playlist item did not include a videoId."

        tracks.append(
            build_track_summary(
                number,
                playlist_track,
                song_data,
                song_error,
                artists_by_id,
            )
        )

    return playlist, tracks


def print_tracks(tracks: list[dict[str, Any]], playlist_title_value: str) -> None:
    """Print a concise console report."""
    print("=" * 60)
    print(f"{playlist_title_value} - first {len(tracks)} tracks")
    print("Popularity data: YouTube views, artist channel views/subscribers")
    print("=" * 60)
    print()

    for track in tracks:
        print(f"{track['number']:2}. {track['name']}")
        print(f"    Artist(s): {track['artists'] or 'Unknown'}")
        print(f"    Album: {track['album'] or 'Unknown'}")
        print(f"    Duration: {track['duration']}")
        print(f"    YouTube Views: {format_number(track['view_count_raw'] or track['view_count'])}")

        for artist in track["artist_details"]:
            print(
                "    Artist Stats: "
                f"{artist['name']} - "
                f"{format_number(artist['subscribers'])} subscribers, "
                f"{format_number(artist['views'])} channel views"
            )

        if track["song_lookup_error"]:
            print(f"    Song lookup warning: {track['song_lookup_error']}")
        print(f"    URL: {track['url'] or 'Unknown'}")
        print()


def save_text_report(
    tracks: list[dict[str, Any]],
    playlist: dict[str, Any],
    output_file: str,
) -> Path:
    """Save a readable text report."""
    output_path = project_path(output_file)
    title = playlist.get("title") or DEFAULT_PLAYLIST_NAME

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"{title} - YouTube Music Songs\n")
        f.write("=" * 60 + "\n\n")
        f.write("YouTube Music does not expose a clean per-song listener count.\n")
        f.write("This report uses YouTube view counts when available, plus artist ")
        f.write("channel views/subscribers when YouTube Music returns them.\n\n")

        for track in tracks:
            f.write(f"{track['number']}. {track['name']}\n")
            f.write(f"   Artist(s): {track['artists'] or 'Unknown'}\n")
            f.write(f"   Album: {track['album'] or 'Unknown'}\n")
            f.write(f"   Duration: {track['duration']}\n")
            f.write(f"   YouTube Views: {format_number(track['view_count_raw'] or track['view_count'])}\n")
            for artist in track["artist_details"]:
                f.write(
                    "   Artist Stats: "
                    f"{artist['name']} - "
                    f"{format_number(artist['subscribers'])} subscribers, "
                    f"{format_number(artist['views'])} channel views\n"
                )
            if track["song_lookup_error"]:
                f.write(f"   Song lookup warning: {track['song_lookup_error']}\n")
            f.write(f"   URL: {track['url'] or 'Unknown'}\n\n")

        f.write("=" * 60 + "\n")
        f.write(f"Total tracks: {len(tracks)}\n")

    return output_path


def save_json_report(
    tracks: list[dict[str, Any]],
    playlist: dict[str, Any],
    output_file: str,
) -> Path:
    """Save the normalized metadata as JSON."""
    output_path = project_path(output_file)
    payload = {
        "playlist": {
            "id": playlist.get("id"),
            "title": playlist.get("title"),
            "author": playlist.get("author"),
            "track_count": playlist.get("trackCount"),
            "duration": playlist.get("duration"),
            "duration_seconds": playlist.get("duration_seconds"),
        },
        "tracks": tracks,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return output_path


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Fetch the first 30 songs from YouTube Music Discover Mix with metadata."
    )
    parser.add_argument("--config", default=CONFIG_FILE, help="Config JSON file path.")
    parser.add_argument("--setup-auth", action="store_true", help="Create the ytmusicapi auth file.")
    auth_group = parser.add_mutually_exclusive_group()
    auth_group.add_argument("--auth-file", help="Override auth file path.")
    auth_group.add_argument("--profile", choices=PROFILE_IDS, help="Use one isolated auth profile.")
    parser.add_argument("--playlist-id", help="Playlist id or YouTube Music playlist URL.")
    parser.add_argument("--playlist-name", help="Playlist name to find in your library.")
    parser.add_argument("--limit", type=int, help="Number of tracks to fetch. Default: 30.")
    parser.add_argument("--output", help="Text report output path.")
    parser.add_argument("--json-output", help="JSON report output path.")
    parser.add_argument(
        "--public-search",
        action="store_true",
        help="Allow public playlist search if the playlist is not found in your library.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the Discover Mix metadata fetcher."""
    args = parse_args()
    config = apply_cli_overrides(load_config(args.config), args)

    if args.setup_auth:
        if config.get("profile"):
            auth_path = profile_auth_path(config["profile"])
            auth_path.parent.mkdir(parents=True, exist_ok=True)
            print(f"Creating browser-header auth for {config['profile']}.")
            setup_ytmusic_headers(filepath=str(auth_path))
            auth_path.chmod(0o600)
        else:
            auth_path = setup_auth_file(config.get("auth_file") or DEFAULT_AUTH_FILE)
        print(f"Auth saved to: {auth_path}")
        return 0

    limit = int(config.get("track_limit") or DEFAULT_TRACK_LIMIT)
    if limit < 1:
        raise ValueError("track_limit must be at least 1.")

    ytmusic, authenticated, _auth_path = create_ytmusic_client(config)
    configured_playlist_id = normalize_playlist_id(config.get("playlist_id"))
    found_playlist_title = None

    if configured_playlist_id:
        selected_playlist_id = configured_playlist_id
    else:
        selected_playlist_id, found_playlist_title = find_playlist_by_name(
            ytmusic,
            config.get("playlist_name") or DEFAULT_PLAYLIST_NAME,
            bool(config.get("search_library", True)),
            bool(config.get("allow_public_search", False)),
        )

    if not selected_playlist_id:
        print(f"Could not find playlist: {config.get('playlist_name') or DEFAULT_PLAYLIST_NAME}")
        print()
        if not authenticated:
            print("Create auth first:")
            print(f"  {script_command()} --setup-auth")
            print()
        print("Then paste the Discover Mix playlist URL into youtube_music_config.json:")
        print('  "playlist_id": "https://music.youtube.com/playlist?list=..."')
        return 1

    playlist, tracks = fetch_playlist_tracks(ytmusic, selected_playlist_id, limit)
    playlist_title_value = playlist.get("title") or found_playlist_title or config.get("playlist_name")

    print_tracks(tracks, playlist_title_value or DEFAULT_PLAYLIST_NAME)
    text_path = save_text_report(tracks, playlist, config.get("output_file") or DEFAULT_OUTPUT_FILE)
    json_path = save_json_report(tracks, playlist, config.get("json_output_file") or DEFAULT_JSON_OUTPUT_FILE)

    print("=" * 60)
    print(f"Total tracks retrieved: {len(tracks)}")
    print(f"Text report saved to: {text_path}")
    print(f"JSON report saved to: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
