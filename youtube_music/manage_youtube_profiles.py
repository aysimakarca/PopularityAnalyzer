"""Create, import, list, and identify isolated YouTube Music auth profiles."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import shlex
import shutil
import sys
from pathlib import Path

from ytmusicapi import YTMusic, setup as setup_ytmusic_headers

from youtube_auth_profiles import (
    LEGACY_AUTH_PATH,
    PROFILE_IDS,
    REGISTRY_PATH,
    account_name,
    load_registry,
    profile_auth_path,
)


def save_account_name(profile: str, name: str) -> None:
    registry = load_registry()
    registry["profiles"][profile]["account_name"] = name
    REGISTRY_PATH.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def list_profiles() -> int:
    registry = load_registry()
    print("Profile   Auth status   Account label")
    print("--------- ------------- ------------------------------")
    for profile in PROFILE_IDS:
        entry = registry["profiles"][profile]
        status = "ready" if profile_auth_path(profile).is_file() else "missing"
        name = entry.get("account_name") or entry.get("label") or ""
        print(f"{profile:<9} {status:<13} {name}")
    return 0


def setup_profile(profile: str) -> int:
    path = profile_auth_path(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Creating browser-header auth for {profile}.")
    print("Paste headers copied while signed into the intended YouTube Music account.")
    setup_ytmusic_headers(filepath=str(path))
    path.chmod(0o600)
    print(f"Saved auth for {profile}. Credential contents were not printed.")
    return 0


def import_auth(profile: str, source: Path) -> int:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Auth file not found: {source}")
    destination = profile_auth_path(profile)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    destination.chmod(0o600)
    print(f"Imported existing auth into {profile}. Credential contents were not printed.")
    return 0


def set_request_headers(profile: str, source: Path) -> int:
    """Convert copied browser request headers into one isolated auth file."""
    if str(source) == "-":
        headers_raw = sys.stdin.read()
        if not headers_raw.strip():
            raise ValueError("No request headers were received on standard input.")
    else:
        source = source.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Request-header file not found: {source}")
        headers_raw = source.read_text(encoding="utf-8")

    if headers_raw.lstrip().startswith("curl "):
        tokens = shlex.split(headers_raw)
        extracted: list[str] = []
        index = 0
        while index < len(tokens):
            token = tokens[index].strip()
            if token in ("-H", "--header") and index + 1 < len(tokens):
                extracted.append(tokens[index + 1])
                index += 2
                continue
            if token in ("-b", "--cookie") and index + 1 < len(tokens):
                extracted.append(f"cookie: {tokens[index + 1]}")
                index += 2
                continue
            index += 1
        headers_raw = "\n".join(extracted)

    lowered_original = headers_raw.casefold()
    if "cookie:" not in lowered_original or "authorization:" not in lowered_original:
        # Chrome's request-header pane may copy names and values on alternating
        # lines. Stop before its optional "Decoded" client-data diagnostics.
        lines = [line.strip() for line in headers_raw.splitlines() if line.strip()]
        normalized: list[str] = []
        index = 0
        while index + 1 < len(lines):
            name = lines[index]
            if name.casefold().rstrip(":") == "decoded":
                break
            value = lines[index + 1]
            if not name.startswith(":"):
                normalized.append(f"{name}: {value}")
            index += 2
        if not any(line.casefold().startswith("x-goog-authuser:") for line in normalized):
            # Account index 0 is YouTube's normal default when this header is
            # omitted from the copied request. Validation below confirms the
            # resulting session before it is used for operations.
            normalized.append("x-goog-authuser: 0")
        headers_raw = "\n".join(normalized)

    lowered = headers_raw.casefold()
    missing = [
        header
        for header in ("cookie", "authorization")
        if f"{header}:" not in lowered
    ]
    if missing:
        raise ValueError(
            "Copied request headers are missing required fields: " + ", ".join(missing)
        )

    destination = profile_auth_path(profile)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(".auth.pending.json")
    try:
        setup_ytmusic_headers(filepath=str(temporary), headers_raw=headers_raw)
        parsed = json.loads(temporary.read_text(encoding="utf-8"))
        if not parsed.get("cookie") or not parsed.get("authorization"):
            raise ValueError("ytmusicapi did not produce usable cookie and authorization fields.")

        if destination.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = destination.with_name(f"auth.backup-{stamp}.json")
            shutil.copy2(destination, backup)
            backup.chmod(0o600)
            print(f"Previous {profile} auth preserved as {backup.name}.")

        os.replace(temporary, destination)
        destination.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()

    print(f"Installed new request-header auth for {profile}.")
    print("Credential contents were validated but not printed.")
    return 0


def identify_profile(profile: str, save: bool) -> int:
    path = profile_auth_path(profile)
    if not path.is_file():
        raise FileNotFoundError(
            f"No auth for {profile}. Run: python3 youtube_music/manage_youtube_profiles.py setup {profile}"
        )
    ytmusic = YTMusic(str(path))
    name = None
    try:
        name = account_name(ytmusic.get_account_info())
    except (KeyError, TypeError, ValueError):
        # YouTube occasionally changes the account-menu response shape. An
        # owned/library playlist can still expose the same channel name.
        pass

    if not name:
        try:
            playlists = ytmusic.get_library_playlists(limit=100)
        except (KeyError, TypeError, ValueError):
            playlists = []
        ordered = sorted(
            playlists,
            key=lambda item: item.get("title") != "MCT Research",
        )
        for playlist_summary in ordered:
            playlist_id = playlist_summary.get("playlistId")
            if not playlist_id:
                continue
            playlist = ytmusic.get_playlist(playlist_id, limit=1)
            author = playlist.get("author")
            if isinstance(author, str) and author:
                name = author
            elif isinstance(author, dict):
                name = author.get("name") or author.get("title")
            if name:
                break
    if not name:
        raise RuntimeError(
            "The saved headers did not expose an authenticated account display name. "
            "They may be expired; refresh this profile with the setup command."
        )
    if save:
        save_account_name(profile, name)
    print(f"{profile}: {name}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List all ten profiles without printing secrets.")

    setup_parser = subparsers.add_parser("setup", help="Interactively create auth for a profile.")
    setup_parser.add_argument("profile", choices=PROFILE_IDS)

    import_parser = subparsers.add_parser("import", help="Copy an existing auth file into a profile.")
    import_parser.add_argument("profile", choices=PROFILE_IDS)
    import_parser.add_argument("--source", type=Path, default=LEGACY_AUTH_PATH)

    headers_parser = subparsers.add_parser(
        "set-headers",
        help="Convert copied YouTube Music request headers into profile auth.",
    )
    headers_parser.add_argument("profile", choices=PROFILE_IDS)
    headers_parser.add_argument("--source", type=Path, required=True)

    whoami_parser = subparsers.add_parser("whoami", help="Show the authenticated account display name.")
    whoami_parser.add_argument("profile", choices=PROFILE_IDS)
    whoami_parser.add_argument("--save", action="store_true", help="Save the display name in the non-secret registry.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "list":
        return list_profiles()
    if args.command == "setup":
        return setup_profile(args.profile)
    if args.command == "import":
        return import_auth(args.profile, args.source)
    if args.command == "set-headers":
        return set_request_headers(args.profile, args.source)
    if args.command == "whoami":
        return identify_profile(args.profile, args.save)
    raise RuntimeError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from None
