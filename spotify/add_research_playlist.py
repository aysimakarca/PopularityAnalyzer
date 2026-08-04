"""Add the validated research tracks to an existing Spotify playlist.

The operation is idempotent: tracks already present in the destination are
not added again.  A separate OAuth cache is used because the analysis scripts
only request read permissions.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import spotipy
from spotipy.oauth2 import SpotifyOAuth


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
AUTH_DIR = HERE / "auth"
DEFAULT_CONFIG = AUTH_DIR / "spotify_config.json"
DEFAULT_TRACKS = ROOT / "experiment_setup" / "final_balanced_playlist.csv"
DEFAULT_CACHE = AUTH_DIR / ".spotify_playlist_write_cache"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playlist-name", default="MCT Research")
    parser.add_argument("--tracks", type=Path, default=DEFAULT_TRACKS)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args()


def spotify_client(config_path: Path) -> spotipy.Spotify:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    auth = SpotifyOAuth(
        client_id=config["client_id"],
        client_secret=config["client_secret"],
        redirect_uri=config["redirect_uri"],
        scope=(
            "playlist-read-private playlist-read-collaborative "
            "playlist-modify-private playlist-modify-public"
        ),
        cache_path=str(DEFAULT_CACHE),
        open_browser=True,
    )
    return spotipy.Spotify(auth_manager=auth, requests_timeout=20, retries=3)


def target_track_ids(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    ids = [row.get("spotify_track_id", "").strip() for row in rows]
    if len(ids) != 30 or any(not track_id for track_id in ids):
        raise RuntimeError(f"Expected 30 non-empty Spotify track IDs in {path}")
    if len(set(ids)) != len(ids):
        raise RuntimeError(f"Duplicate Spotify track IDs found in {path}")
    return ids


def find_playlist(sp: spotipy.Spotify, name: str) -> dict:
    matches: list[dict] = []
    page = sp.current_user_playlists(limit=50)
    while page:
        matches.extend(item for item in page["items"] if item.get("name") == name)
        page = sp.next(page) if page.get("next") else None
    if not matches:
        raise RuntimeError(f'No playlist named "{name}" was found in this account')
    if len(matches) > 1:
        ids = ", ".join(item["id"] for item in matches)
        raise RuntimeError(f'Multiple playlists named "{name}" were found: {ids}')
    return matches[0]


def existing_track_ids(sp: spotipy.Spotify, playlist_id: str) -> set[str]:
    found: set[str] = set()
    page = sp.playlist_items(playlist_id, limit=100)
    while page:
        for wrapper in page["items"]:
            # Spotify's current endpoint calls the nested media object
            # ``item``. Older playlist responses and Spotipy releases used
            # ``track``, so accept both shapes.
            track = wrapper.get("item") or wrapper.get("track") or {}
            if track.get("id"):
                found.add(track["id"])
        page = sp.next(page) if page.get("next") else None
    return found


def main() -> int:
    args = parse_args()
    desired = target_track_ids(args.tracks)
    sp = spotify_client(args.config)
    playlist = find_playlist(sp, args.playlist_name)
    existing = existing_track_ids(sp, playlist["id"])
    missing = [track_id for track_id in desired if track_id not in existing]

    for start in range(0, len(missing), 100):
        sp.playlist_add_items(playlist["id"], missing[start : start + 100])

    verified = existing_track_ids(sp, playlist["id"])
    unresolved = [track_id for track_id in desired if track_id not in verified]
    if unresolved:
        raise RuntimeError(f"Spotify did not retain {len(unresolved)} requested tracks")

    print(f'Playlist: {playlist["name"]}')
    print(f'URL: {playlist["external_urls"]["spotify"]}')
    print(f"Already present: {len(desired) - len(missing)}")
    print(f"Added: {len(missing)}")
    print(f"Verified research tracks present: {len(desired)}/{len(desired)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
