"""Shared YouTube Music authentication-profile utilities.

Authentication files contain live browser cookies and must never be committed.
The registry stores only profile labels and paths, not credential contents.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
AUTH_DIR = HERE / "auth"
REGISTRY_PATH = AUTH_DIR / "youtube_auth_profiles.json"
LEGACY_AUTH_PATH = AUTH_DIR / "ytmusic_auth.json"
STANDARD_PROFILE_IDS = tuple(f"user_{number:02d}" for number in range(1, 11))
PROFILE_IDS = (*STANDARD_PROFILE_IDS, "user_aysima_original")


def load_registry() -> dict[str, Any]:
    """Load and validate the experimental and preserved-profile registry."""
    with REGISTRY_PATH.open(encoding="utf-8") as handle:
        registry = json.load(handle)

    profiles = registry.get("profiles")
    if not isinstance(profiles, dict) or set(profiles) != set(PROFILE_IDS):
        raise RuntimeError(
            f"{REGISTRY_PATH} must define exactly: {', '.join(PROFILE_IDS)}"
        )
    return registry


def profile_auth_path(profile: str) -> Path:
    """Return the configured auth path for one named profile."""
    registry = load_registry()
    if profile not in registry["profiles"]:
        raise ValueError(f"Unknown YouTube Music profile: {profile}")
    configured = Path(registry["profiles"][profile]["auth_file"])
    return configured if configured.is_absolute() else AUTH_DIR / configured


def resolve_auth_path(
    *,
    profile: str | None = None,
    auth_path: str | Path | None = None,
    require_exists: bool = True,
) -> tuple[Path, str | None]:
    """Resolve an explicit auth file, named profile, environment profile, or legacy file.

    Resolution order is explicit ``auth_path``, explicit ``profile``, the
    ``YTMUSIC_PROFILE`` environment variable, then the legacy auth file.
    """
    if profile and auth_path:
        raise ValueError("Use either --profile or --auth/--auth-file, not both.")

    selected_profile = profile or (None if auth_path else os.getenv("YTMUSIC_PROFILE")) or None
    if auth_path:
        path = Path(auth_path).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
    elif selected_profile:
        path = profile_auth_path(selected_profile)
    else:
        path = LEGACY_AUTH_PATH

    path = path.resolve()
    if require_exists and not path.is_file():
        if selected_profile:
            setup_hint = (
                "python3 youtube_music/manage_youtube_profiles.py "
                f"setup {selected_profile}"
            )
        else:
            setup_hint = "select a profile with --profile or create its auth first"
        raise FileNotFoundError(f"YouTube Music auth not found: {path}. To create it: {setup_hint}")
    return path, selected_profile


def account_name(account_info: dict[str, Any] | None) -> str | None:
    """Extract a display name from known ytmusicapi account-info shapes."""
    if not isinstance(account_info, dict):
        return None
    for key in ("accountName", "name", "title"):
        value = account_info.get(key)
        if value:
            return str(value)
    account = account_info.get("account")
    if isinstance(account, dict):
        for key in ("name", "accountName", "title"):
            value = account.get(key)
            if value:
                return str(value)
    return None
