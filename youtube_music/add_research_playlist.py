"""Add the validated research Art Tracks to an existing YouTube Music playlist.

Tracks already present are skipped, so the command is safe to rerun.
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
import time
from typing import Any

from ytmusicapi import YTMusic

from youtube_auth_profiles import PROFILE_IDS, resolve_auth_path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_TRACKS = ROOT / "final_balanced_playlist.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playlist-name", default="MCT Research")
    parser.add_argument(
        "--create",
        action="store_true",
        help="Create the playlist if it does not already exist.",
    )
    parser.add_argument(
        "--description",
        default="30-song Heavy Metal MCT research playlist.",
    )
    parser.add_argument(
        "--privacy-status",
        choices=("PRIVATE", "PUBLIC", "UNLISTED"),
        default="PRIVATE",
    )
    auth_group = parser.add_mutually_exclusive_group()
    auth_group.add_argument("--profile", choices=PROFILE_IDS)
    auth_group.add_argument("--auth", type=Path, help="Explicit auth file; bypasses the profile registry.")
    parser.add_argument("--tracks", type=Path, default=DEFAULT_TRACKS)
    return parser.parse_args()


def target_video_ids(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    ids = [row.get("youtube_video_id", "").strip() for row in rows]
    if len(ids) != 30 or any(not video_id for video_id in ids):
        raise RuntimeError(f"Expected 30 non-empty YouTube video IDs in {path}")
    if len(set(ids)) != len(ids):
        raise RuntimeError(f"Duplicate YouTube video IDs found in {path}")
    return ids


def find_playlist(ytmusic: YTMusic, name: str) -> dict[str, Any] | None:
    playlists = ytmusic.get_library_playlists(limit=None)
    matches = [playlist for playlist in playlists if playlist.get("title") == name]
    if not matches:
        return None
    if len(matches) > 1:
        ids = ", ".join(playlist.get("playlistId", "") for playlist in matches)
        raise RuntimeError(f'Multiple library playlists named "{name}" were found: {ids}')
    return matches[0]


def playlist_video_ids(ytmusic: YTMusic, playlist_id: str) -> set[str]:
    """Read playlist IDs, tolerating propagation and newer response layouts."""
    for attempt in range(3):
        try:
            playlist = ytmusic.get_playlist(playlist_id, limit=None)
            return {
                track["videoId"]
                for track in playlist.get("tracks") or []
                if track and track.get("videoId")
            }
        except (KeyError, TypeError):
            browse_id = playlist_id if playlist_id.startswith("VL") else f"VL{playlist_id}"
            response = ytmusic._send_request("browse", {"browseId": browse_id})

            def collect_video_ids(value: Any) -> set[str]:
                if isinstance(value, dict):
                    found = {str(value["videoId"])} if value.get("videoId") else set()
                    for child in value.values():
                        found.update(collect_video_ids(child))
                    return found
                if isinstance(value, list):
                    found: set[str] = set()
                    for child in value:
                        found.update(collect_video_ids(child))
                    return found
                return set()

            found = collect_video_ids(response)
            if found:
                return found
            if attempt < 2:
                time.sleep(2)
    return set()


def main() -> int:
    args = parse_args()
    if not args.profile and not args.auth and not os.getenv("YTMUSIC_PROFILE"):
        raise SystemExit(
            "Select the intended account with --profile user_01..user_10 "
            "(or set YTMUSIC_PROFILE) before changing a playlist."
        )
    desired = target_video_ids(args.tracks)
    auth_path, selected_profile = resolve_auth_path(profile=args.profile, auth_path=args.auth)
    ytmusic = YTMusic(str(auth_path))
    playlist = find_playlist(ytmusic, args.playlist_name)
    created = False
    if playlist is None:
        if not args.create:
            raise RuntimeError(
                f'No library playlist named "{args.playlist_name}" was found. '
                "Use --create to create it."
            )
        result = ytmusic.create_playlist(
            args.playlist_name,
            args.description,
            privacy_status=args.privacy_status,
            video_ids=desired,
        )
        playlist_id = result if isinstance(result, str) else result.get("playlistId")
        if not playlist_id:
            raise RuntimeError("YouTube Music did not return an ID for the created playlist")
        playlist = {"title": args.playlist_name, "playlistId": playlist_id}
        created = True
    else:
        playlist_id = playlist["playlistId"]
    existing = playlist_video_ids(ytmusic, playlist_id)
    missing = [video_id for video_id in desired if video_id not in existing]

    if missing:
        result = ytmusic.add_playlist_items(playlist_id, missing, duplicates=False)
        status = result.get("status") if isinstance(result, dict) else None
        if status and status != "STATUS_SUCCEEDED":
            raise RuntimeError(f"YouTube Music add operation returned {status}")

    verified = playlist_video_ids(ytmusic, playlist_id)
    unresolved = [video_id for video_id in desired if video_id not in verified]
    if unresolved:
        raise RuntimeError(f"YouTube Music did not retain {len(unresolved)} requested tracks")

    print(f'Playlist: {playlist.get("title", args.playlist_name)}')
    print(f"Auth profile: {selected_profile or 'explicit/legacy auth file'}")
    print(f"Created: {'yes' if created else 'no; existing playlist reused'}")
    print(f"Privacy: {args.privacy_status}")
    print(f"URL: https://music.youtube.com/playlist?list={playlist_id}")
    print(f"Already present: {len(desired) - len(missing)}")
    print(f"Added: {len(missing)}")
    print(f"Verified research tracks present: {len(desired)}/{len(desired)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
