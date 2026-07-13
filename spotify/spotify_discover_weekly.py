"""
Spotify Discover Weekly Playlist Fetcher

Prerequisites:
1. Create a Spotify Developer App at https://developer.spotify.com/dashboard
2. Fill in your credentials in auth/spotify_config.json
3. Install spotipy: pip install spotipy

Spotify Web API note:
- Spotify does not expose exact song listener counts, song stream counts, or
  artist monthly listeners through the public Web API.
- This script fetches the closest official fields: track popularity, artist
  popularity, and artist follower totals.
- Spotify Development Mode apps may not receive those deprecated popularity
  and follower fields. In that case, the script will show Unknown.
"""

import json
import logging
from pathlib import Path
import warnings

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")
logging.getLogger("spotipy.client").setLevel(logging.CRITICAL)

import spotipy
from spotipy.exceptions import SpotifyException, SpotifyOauthError
from spotipy.oauth2 import SpotifyOAuth


AUTH_DIR = "auth"
CACHE_FILE = ".spotify_cache"
CONFIG_FILE = "spotify_config.json"
DEFAULT_PLAYLIST_NAME = "Discover Weekly Copy"
DEFAULT_OUTPUT_FILE = "output_songs.txt"
SPOTIFY_MARKET = "from_token"


def load_config():
    """Load Spotify credentials from config file."""
    config_path = Path(__file__).parent / AUTH_DIR / CONFIG_FILE
    
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            "Please create spotify/auth/spotify_config.json with your credentials."
        )
    
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def create_spotify_client(config):
    """Create an authenticated Spotify client."""
    cache_path = Path(__file__).parent / AUTH_DIR / CACHE_FILE

    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=config["client_id"],
        client_secret=config["client_secret"],
        redirect_uri=config["redirect_uri"],
        scope="playlist-read-private playlist-read-collaborative user-library-read",
        cache_path=str(cache_path)
    ))


def print_oauth_error_help(error):
    """Print next steps for common Spotify OAuth credential/cache failures."""
    cache_path = Path(__file__).parent / AUTH_DIR / CACHE_FILE

    print(f"Spotify authentication failed: {error}")
    print()
    print("This usually means one of these is true:")
    print("1. The client_id or client_secret in auth/spotify_config.json is incorrect.")
    print("2. The Spotify app's client secret was rotated in the Developer Dashboard.")
    print("3. .spotify_cache was created with old or different Spotify app credentials.")
    print()
    print("Fix:")
    print("1. Check auth/spotify_config.json against your Spotify Developer Dashboard.")
    print(f"2. Delete the cached OAuth token: {cache_path}")
    print("3. Run this script again and complete the Spotify browser login.")


def get_all_playlist_items(sp, playlist_id):
    """Fetch every item in a playlist, following Spotify pagination."""
    results = sp.playlist_items(playlist_id, market=SPOTIFY_MARKET)
    items = results["items"]

    while results.get("next"):
        results = sp.next(results)
        items.extend(results["items"])

    return items


def fetch_tracks_by_id(sp, track_ids):
    """Fetch full track objects keyed by track ID."""
    tracks_by_id = {}
    blocked_lookup = False

    # Spotify Development Mode can block bulk catalog endpoints, so fetch
    # tracks individually instead of calling GET /tracks?ids=...
    for track_id in track_ids:
        try:
            track = sp.track(track_id)
        except SpotifyException as e:
            if e.http_status == 403:
                blocked_lookup = True
                continue
            raise

        if track:
            tracks_by_id[track["id"]] = track

    if blocked_lookup:
        print(
            "Spotify blocked one or more individual track lookups. "
            "Those tracks will use data from the playlist response."
        )

    return tracks_by_id


def fetch_artists_by_id(sp, artist_ids):
    """Fetch artist objects keyed by artist ID."""
    artists_by_id = {}
    blocked_lookup = False

    # Spotify Development Mode can block bulk catalog endpoints, so fetch
    # artists individually instead of calling GET /artists?ids=...
    for artist_id in artist_ids:
        try:
            artist = sp.artist(artist_id)
        except SpotifyException as e:
            if e.http_status == 403:
                blocked_lookup = True
                continue
            raise

        if artist:
            artists_by_id[artist["id"]] = artist

    if blocked_lookup:
        print(
            "Spotify blocked one or more individual artist lookups. "
            "Those artist popularity/follower fields will be shown as Unknown."
        )

    return artists_by_id


def format_number(value):
    """Format a number for human-readable output."""
    if value is None:
        return "Unknown"
    return f"{value:,}"


def format_score(value):
    """Format Spotify's 0-100 popularity score."""
    if value is None:
        return "Unknown"
    return f"{value}/100"


def format_duration(duration_ms):
    """Format a track duration as m:ss."""
    duration_min = duration_ms // 60000
    duration_sec = (duration_ms % 60000) // 1000
    return f"{duration_min}:{duration_sec:02d}"


def build_artist_summary(track_artists, artists_by_id):
    """Build artist popularity/follower details for a track."""
    artist_summaries = []

    for artist in track_artists:
        artist_id = artist.get("id")
        full_artist = artists_by_id.get(artist_id, {})
        followers = full_artist.get("followers", {}).get("total")

        artist_summaries.append({
            "id": artist_id,
            "name": artist.get("name", "Unknown artist"),
            "url": artist.get("external_urls", {}).get("spotify", ""),
            "popularity": full_artist.get("popularity"),
            "followers": followers
        })

    return artist_summaries


def get_missing_popularity_fields(tracks_by_id, artists_by_id):
    """Return Spotify popularity-style fields that were not returned."""
    missing_fields = []

    if not any(track.get("popularity") is not None for track in tracks_by_id.values()):
        missing_fields.append("track popularity")

    if not any(artist.get("popularity") is not None for artist in artists_by_id.values()):
        missing_fields.append("artist popularity")

    if not any(
        artist.get("followers", {}).get("total") is not None
        for artist in artists_by_id.values()
    ):
        missing_fields.append("artist followers")

    return missing_fields


def print_popularity_field_notice(missing_fields):
    """Explain missing popularity-style fields in the console output."""
    if not missing_fields:
        return

    print("Spotify did not return these fields for this app/account:")
    print(f"  {', '.join(missing_fields)}")
    print(
        "This matches Spotify's Development Mode API changes for deprecated "
        "popularity/follower fields. Values below will be shown as Unknown."
    )
    print()


def get_discover_weekly():
    """Fetch and display the user's Discover Weekly playlist."""
    
    # Load config and initialize Spotify client
    config = load_config()
    sp = create_spotify_client(config)
    
    # Get current user info
    try:
        user = sp.current_user()
    except SpotifyOauthError as e:
        print_oauth_error_help(e)
        return None

    print(f"Logged in as: {user['display_name']}\n")
    
    # Playlist name to search for (or playlist ID if provided)
    playlist_name = config.get("playlist_name", DEFAULT_PLAYLIST_NAME)
    playlist_id = config.get("playlist_id")
    
    # If no ID provided, search by name
    if not playlist_id:
        playlists = sp.current_user_playlists(limit=50)
        while playlists:
            for p in playlists['items']:
                if p and p['name'] == playlist_name:
                    playlist_id = p['id']
                    break
            if playlist_id or not playlists['next']:
                break
            playlists = sp.next(playlists)
        
        if not playlist_id:
            print(f"Playlist '{playlist_name}' not found in your library.")
            return None
    
    discover_weekly_id = playlist_id
    
    try:
        # Try fetching with market parameter
        discover_weekly = sp.playlist(discover_weekly_id, market=SPOTIFY_MARKET)
    except Exception as e:
        print(f"Cannot access Discover Weekly via API: {e}")
        print("\n" + "="*60)
        print("SPOTIFY API LIMITATION")
        print("="*60)
        print("\nDiscover Weekly is an algorithmic playlist that Spotify")
        print("restricts from API access (confirmed bug since 2017).")
        print("\nWORKAROUND: Copy the playlist to your own library:")
        print("1. Open Discover Weekly in Spotify")
        print("2. Click ⋯ (three dots) → 'Add to other playlist'")
        print("3. Create a new playlist (e.g., 'My Discover Weekly Copy')")
        print("4. Update auth/spotify_config.json with the new playlist ID")
        print("5. Run this script again")
        return None
    
    playlist_items = get_all_playlist_items(sp, playlist_id)
    playlist_tracks = []
    track_ids = []

    for item in playlist_items:
        track = item.get("track") or item.get("item")
        if track and track.get("type") == "track" and track.get("id"):
            playlist_tracks.append(track)
            track_ids.append(track["id"])

    playlist_total = discover_weekly.get("tracks", {}).get("total") or len(playlist_tracks)
    print(f"{'='*60}")
    print(f"🎵 {playlist_name} - {playlist_total} tracks")
    print("Popularity data: track popularity, artist popularity, artist followers")
    print(f"{'='*60}\n")

    full_tracks_by_id = fetch_tracks_by_id(sp, track_ids)
    artist_ids = sorted({
        artist["id"]
        for track in playlist_tracks
        for artist in track.get("artists", [])
        if artist.get("id")
    })
    artists_by_id = fetch_artists_by_id(sp, artist_ids)
    missing_fields = get_missing_popularity_fields(full_tracks_by_id, artists_by_id)
    print_popularity_field_notice(missing_fields)

    tracks_data = []

    for idx, playlist_track in enumerate(playlist_tracks, 1):
        track = full_tracks_by_id.get(playlist_track["id"], playlist_track)
        if track:
            artists = build_artist_summary(track.get("artists", []), artists_by_id)
            track_info = {
                "number": idx,
                "id": track["id"],
                "name": track["name"],
                "artists": ", ".join(artist["name"] for artist in artists),
                "artist_details": artists,
                "album": track["album"]["name"],
                "duration_ms": track["duration_ms"],
                "popularity": track.get("popularity"),
                "url": track["external_urls"].get("spotify", "")
            }
            tracks_data.append(track_info)
            
            print(f"{idx:2}. {track_info['name']}")
            print(f"    Artist(s): {track_info['artists']}")
            print(f"    Album: {track_info['album']}")
            print(f"    Duration: {format_duration(track_info['duration_ms'])}")
            print(f"    Track Popularity: {format_score(track_info['popularity'])}")
            for artist in artists:
                print(
                    "    Artist Popularity: "
                    f"{artist['name']} - {format_score(artist['popularity'])}, "
                    f"{format_number(artist['followers'])} followers"
                )
            print()
    
    return tracks_data


def save_to_file(tracks, playlist_name, output_file=DEFAULT_OUTPUT_FILE):
    """Save tracks to a text file."""
    output_path = Path(__file__).parent / output_file
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"{playlist_name} - Playlist Songs\n")
        f.write("=" * 60 + "\n\n")
        f.write("Spotify Web API does not provide exact song listener counts, ")
        f.write("song stream counts, or artist monthly listeners.\n")
        f.write("Closest available fields shown below: track popularity, ")
        f.write("artist popularity, and artist follower totals.\n\n")
        f.write("If a value is Unknown, Spotify did not return that field. ")
        f.write("Development Mode apps may not receive deprecated popularity ")
        f.write("or follower fields.\n\n")
        
        for track in tracks:
            f.write(f"{track['number']}. {track['name']}\n")
            f.write(f"   Artist(s): {track['artists']}\n")
            f.write(f"   Album: {track['album']}\n")
            f.write(f"   Duration: {format_duration(track['duration_ms'])}\n")
            f.write(f"   Track Popularity: {format_score(track['popularity'])}\n")
            for artist in track["artist_details"]:
                f.write(
                    "   Artist Popularity: "
                    f"{artist['name']} - {format_score(artist['popularity'])}, "
                    f"{format_number(artist['followers'])} followers\n"
                )
            f.write(f"   URL: {track['url']}\n\n")
        
        f.write("=" * 60 + "\n")
        f.write(f"Total tracks: {len(tracks)}\n")
    
    return output_path


if __name__ == "__main__":
    config = load_config()
    playlist_name = config.get("playlist_name", DEFAULT_PLAYLIST_NAME)
    
    tracks = get_discover_weekly()
    
    if tracks:
        print(f"\n{'='*60}")
        print(f"Total tracks retrieved: {len(tracks)}")
        
        output_path = save_to_file(tracks, playlist_name)
        print(f"\nSongs saved to: {output_path}")
