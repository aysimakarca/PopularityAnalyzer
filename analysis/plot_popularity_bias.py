"""Standardize weekly playlist popularity data and regenerate comparison plots.

The script scans experiment result folders such as ``Week1_21July`` and
``Week2_28July``. For each Spotify and YouTube user playlist it writes a
compact, standardized track table, compares every track against the
``final_balanced_playlist`` baseline, and renders plots that can be rerun when
new weeks are added.

Examples:
    python3 analysis/plot_popularity_bias.py
    python3 analysis/plot_popularity_bias.py --week Week2_28July
    python3 analysis/plot_popularity_bias.py --platform Spotify --platform Youtube
"""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Iterable

os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "popularity_analyzer_matplotlib"),
)
os.environ.setdefault(
    "XDG_CACHE_HOME",
    str(Path(tempfile.gettempdir()) / "popularity_analyzer_cache"),
)

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_ROOT = ROOT / "experiment_results"
DEFAULT_BASELINE = ROOT / "experiment_setup" / "final_balanced_playlist.csv"
DEFAULT_OUTPUT_DIR = ROOT / "analysis_results" / "popularity_bias"
STANDARD_TRACKS_NAME = "standardized_playlist_tracks.csv"
SUMMARY_NAME = "playlist_popularity_summary.csv"
BASELINE_REFERENCE_NAME = "baseline_popularity_reference.csv"
PLATFORM_ORDER = ("Spotify", "Youtube")
USER_RE = re.compile(r"user\s*0*([0-9]+)", flags=re.IGNORECASE)
WEEK_RE = re.compile(r"week\s*[_-]?\s*([0-9]+)", flags=re.IGNORECASE)
COLORS = {
    "Spotify": "#1DB954",
    "Youtube": "#D93025",
    "baseline": "#70757A",
    "zero": "#202124",
}


STANDARD_COLUMNS = [
    "source_type",
    "playlist_kind",
    "week_folder",
    "week_number",
    "platform",
    "user_folder",
    "user_number",
    "playlist_file",
    "playlist_name",
    "playlist_id",
    "playlist_url",
    "playlist_position",
    "track_id",
    "track_url",
    "track_name",
    "artist_name",
    "primary_artist_id",
    "album_name",
    "release_date",
    "duration_seconds",
    "explicit",
    "popularity_metric",
    "popularity_value",
    "popularity_display",
    "popularity_log10",
    "selection_tier",
    "baseline_empirical_percentile",
    "baseline_empirical_band",
    "baseline_range_band",
    "baseline_median_value",
    "baseline_median_log10",
    "ratio_vs_baseline_median",
    "log10_delta_vs_baseline_median",
    "style",
    "country",
    "expected_year",
    "secondary_metric",
    "secondary_value",
    "secondary_display",
    "available_country_count",
    "video_or_track_type",
    "captured_at_utc",
    "source_account_or_profile",
    "metadata_error",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--week",
        action="append",
        default=[],
        help="Week folder or week label to include, e.g. Week2_28July or Week2. Can be repeated.",
    )
    parser.add_argument(
        "--platform",
        action="append",
        default=[],
        help="Platform to include: Spotify or Youtube. Can be repeated.",
    )
    parser.add_argument("--no-plots", action="store_true", help="Only write standardized CSV files.")
    return parser.parse_args()


def slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", str(value).strip()).strip("_")
    return cleaned or "value"


def relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def normalize_platform(value: str) -> str:
    lowered = value.casefold()
    if lowered.startswith("spot"):
        return "Spotify"
    if lowered.startswith("you"):
        return "Youtube"
    return value


def parse_week_number(value: str) -> int | None:
    match = WEEK_RE.search(value or "")
    return int(match.group(1)) if match else None


def parse_user_number(value: str) -> int | None:
    match = USER_RE.search(value or "")
    return int(match.group(1)) if match else None


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False)


def first_existing(df: pd.DataFrame, columns: Iterable[str]) -> pd.Series:
    result = pd.Series([""] * len(df), index=df.index, dtype=object)
    for column in columns:
        if column not in df.columns:
            continue
        values = df[column].fillna("").astype(str)
        result = result.mask(result.eq("") & values.ne(""), values)
    return result


def numeric(series: pd.Series) -> pd.Series:
    cleaned = series.fillna("").astype(str).str.replace(",", "", regex=False)
    return pd.to_numeric(cleaned, errors="coerce")


def with_standard_columns(df: pd.DataFrame) -> pd.DataFrame:
    for column in STANDARD_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    return df[STANDARD_COLUMNS]


def sorted_week_dirs(results_root: Path, requested_weeks: list[str]) -> list[Path]:
    requested = {item.casefold() for item in requested_weeks}
    requested_numbers = {
        parse_week_number(item)
        for item in requested_weeks
        if parse_week_number(item) is not None
    }
    weeks = []
    for path in sorted(results_root.iterdir()):
        if not path.is_dir() or parse_week_number(path.name) is None:
            continue
        if requested:
            number = parse_week_number(path.name)
            if path.name.casefold() not in requested and f"week{number}" not in requested:
                if number not in requested_numbers:
                    continue
        weeks.append(path)
    return sorted(weeks, key=lambda item: (parse_week_number(item.name) or 0, item.name))


def platform_dirs(week_dir: Path, requested_platforms: list[str]) -> list[tuple[str, Path]]:
    requested = {normalize_platform(item) for item in requested_platforms}
    found = []
    for path in sorted(week_dir.iterdir()):
        if not path.is_dir():
            continue
        platform = normalize_platform(path.name)
        if platform not in PLATFORM_ORDER:
            continue
        if requested and platform not in requested:
            continue
        found.append((platform, path))
    return sorted(found, key=lambda item: PLATFORM_ORDER.index(item[0]))


def user_playlist_files(platform_dir: Path) -> list[tuple[str, int, Path]]:
    files = []
    for user_dir in sorted(platform_dir.iterdir()):
        if not user_dir.is_dir():
            continue
        user_number = parse_user_number(user_dir.name)
        if user_number is None:
            continue
        csvs = sorted(user_dir.glob("*.csv"))
        for csv_path in csvs:
            files.append((f"User{user_number}", user_number, csv_path))
    return sorted(files, key=lambda item: (item[1], item[2].name))


def normalize_spotify_playlist(
    path: Path,
    df: pd.DataFrame,
    week_folder: str,
    week_number: int,
    user_folder: str,
    user_number: int,
) -> pd.DataFrame:
    value = first_existing(
        df,
        [
            "popularity_metric_value",
            "primary_artist_monthly_listeners",
            "artist_monthly_listeners",
        ],
    )
    display = first_existing(
        df,
        [
            "popularity_metric_display",
            "primary_artist_monthly_listeners_display",
            "artist_monthly_listeners_display",
        ],
    )
    metadata_error = first_existing(
        df,
        [
            "popularity_metric_fetch_error",
            "primary_artist_monthly_listeners_fetch_error",
            "track_lookup_error",
            "album_lookup_error",
            "primary_artist_lookup_error",
        ],
    )
    account = first_existing(df, ["source_account_display_name", "source_account_id"])
    out = pd.DataFrame(
        {
            "source_type": "recommended",
            "playlist_kind": "weekly_recommendation",
            "week_folder": week_folder,
            "week_number": week_number,
            "platform": "Spotify",
            "user_folder": user_folder,
            "user_number": user_number,
            "playlist_file": relative_path(path),
            "playlist_name": first_existing(df, ["playlist_name", "requested_playlist_name"]),
            "playlist_id": first_existing(df, ["playlist_id"]),
            "playlist_url": first_existing(df, ["playlist_url"]),
            "playlist_position": first_existing(df, ["playlist_position"]),
            "track_id": first_existing(df, ["spotify_track_id"]),
            "track_url": first_existing(df, ["spotify_url"]),
            "track_name": first_existing(df, ["track_name", "spotify_title"]),
            "artist_name": first_existing(df, ["primary_artist_name", "artist_names", "spotify_artists"]),
            "primary_artist_id": first_existing(df, ["primary_artist_id"]),
            "album_name": first_existing(df, ["album_name"]),
            "release_date": first_existing(df, ["album_release_date"]),
            "duration_seconds": first_existing(df, ["duration_seconds"]),
            "explicit": first_existing(df, ["explicit"]),
            "popularity_metric": "spotify_artist_monthly_listeners",
            "popularity_value": value,
            "popularity_display": display,
            "selection_tier": "",
            "style": "",
            "country": "",
            "expected_year": "",
            "secondary_metric": "spotify_track_api_popularity",
            "secondary_value": first_existing(df, ["track_api_popularity"]),
            "secondary_display": first_existing(df, ["track_api_popularity"]),
            "available_country_count": first_existing(df, ["available_markets_count"]),
            "video_or_track_type": first_existing(df, ["track_type"]),
            "captured_at_utc": first_existing(df, ["captured_at_utc"]),
            "source_account_or_profile": account,
            "metadata_error": metadata_error,
        }
    )
    return with_standard_columns(out)


def normalize_youtube_playlist(
    path: Path,
    df: pd.DataFrame,
    week_folder: str,
    week_number: int,
    user_folder: str,
    user_number: int,
) -> pd.DataFrame:
    value = first_existing(df, ["popularity_value_view_count", "view_count"])
    account = first_existing(df, ["auth_profile", "verified_account_name"])
    metadata_error = first_existing(df, ["song_lookup_error", "artist_lookup_error", "album_lookup_error"])
    out = pd.DataFrame(
        {
            "source_type": "recommended",
            "playlist_kind": "weekly_recommendation",
            "week_folder": week_folder,
            "week_number": week_number,
            "platform": "Youtube",
            "user_folder": user_folder,
            "user_number": user_number,
            "playlist_file": relative_path(path),
            "playlist_name": first_existing(df, ["playlist_name"]),
            "playlist_id": first_existing(df, ["playlist_id"]),
            "playlist_url": first_existing(df, ["playlist_url"]),
            "playlist_position": first_existing(df, ["playlist_position"]),
            "track_id": first_existing(df, ["video_id"]),
            "track_url": first_existing(df, ["youtube_music_url", "youtube_url"]),
            "track_name": first_existing(df, ["title", "youtube_title"]),
            "artist_name": first_existing(df, ["primary_artist_name", "artists", "youtube_artists"]),
            "primary_artist_id": first_existing(df, ["primary_artist_id"]),
            "album_name": first_existing(df, ["album_name"]),
            "release_date": first_existing(df, ["publish_date", "upload_date"]),
            "duration_seconds": first_existing(df, ["duration_seconds"]),
            "explicit": first_existing(df, ["is_explicit_track"]),
            "popularity_metric": "youtube_video_view_count",
            "popularity_value": value,
            "popularity_display": value,
            "selection_tier": first_existing(df, ["popularity_original_pool_fixed_tier"]),
            "style": "",
            "country": "",
            "expected_year": "",
            "secondary_metric": "youtube_artist_subscribers",
            "secondary_value": first_existing(df, ["artist_subscribers_approx"]),
            "secondary_display": first_existing(df, ["artist_subscribers_display"]),
            "available_country_count": first_existing(df, ["available_country_count"]),
            "video_or_track_type": first_existing(df, ["video_type"]),
            "captured_at_utc": first_existing(df, ["captured_at_utc"]),
            "source_account_or_profile": account,
            "metadata_error": metadata_error,
        }
    )
    return with_standard_columns(out)


def normalize_baseline(path: Path) -> pd.DataFrame:
    df = read_csv(path)
    position = pd.Series(range(1, len(df) + 1), index=df.index)
    common = {
        "source_type": "baseline",
        "playlist_kind": "final_balanced_playlist",
        "week_folder": "FinalBalanced",
        "week_number": 0,
        "user_folder": "FinalBalanced",
        "user_number": 0,
        "playlist_file": relative_path(path),
        "playlist_name": "final_balanced_playlist",
        "playlist_id": "",
        "playlist_url": "",
        "playlist_position": position,
        "album_name": "",
        "duration_seconds": "",
        "explicit": "",
        "secondary_metric": "",
        "secondary_value": "",
        "secondary_display": "",
        "available_country_count": "",
        "video_or_track_type": "",
        "captured_at_utc": first_existing(
            df,
            ["artist_monthly_listeners_captured_at", "captured_at_utc"],
        ),
        "source_account_or_profile": "experiment_setup",
        "metadata_error": "",
    }
    spotify = pd.DataFrame(
        {
            **common,
            "platform": "Spotify",
            "track_id": first_existing(df, ["spotify_track_id"]),
            "track_url": first_existing(df, ["spotify_url"]),
            "track_name": first_existing(df, ["title"]),
            "artist_name": first_existing(df, ["artist"]),
            "primary_artist_id": "",
            "release_date": first_existing(df, ["expected_year"]),
            "popularity_metric": "spotify_artist_monthly_listeners",
            "popularity_value": first_existing(df, ["spotify_metric_value", "artist_monthly_listeners"]),
            "popularity_display": first_existing(df, ["spotify_metric_value", "artist_monthly_listeners"]),
            "selection_tier": first_existing(df, ["spotify_tier", "spotify_selected_tier"]),
            "style": first_existing(df, ["style"]),
            "country": first_existing(df, ["country"]),
            "expected_year": first_existing(df, ["expected_year"]),
        }
    )
    youtube = pd.DataFrame(
        {
            **common,
            "platform": "Youtube",
            "track_id": first_existing(df, ["youtube_video_id"]),
            "track_url": first_existing(df, ["youtube_url"]),
            "track_name": first_existing(df, ["title"]),
            "artist_name": first_existing(df, ["artist"]),
            "primary_artist_id": "",
            "release_date": first_existing(df, ["expected_year"]),
            "popularity_metric": "youtube_video_view_count",
            "popularity_value": first_existing(df, ["view_count"]),
            "popularity_display": first_existing(df, ["view_count"]),
            "selection_tier": first_existing(df, ["youtube_tier", "youtube_selected_tier"]),
            "style": first_existing(df, ["style"]),
            "country": first_existing(df, ["country"]),
            "expected_year": first_existing(df, ["expected_year"]),
        }
    )
    return with_standard_columns(pd.concat([spotify, youtube], ignore_index=True))


def load_weekly_tracks(
    results_root: Path,
    requested_weeks: list[str],
    requested_platforms: list[str],
) -> pd.DataFrame:
    frames = []
    for week_dir in sorted_week_dirs(results_root, requested_weeks):
        week_number = parse_week_number(week_dir.name)
        if week_number is None:
            continue
        for platform, platform_dir in platform_dirs(week_dir, requested_platforms):
            for user_folder, user_number, csv_path in user_playlist_files(platform_dir):
                df = read_csv(csv_path)
                if df.empty:
                    continue
                if platform == "Spotify":
                    frames.append(
                        normalize_spotify_playlist(
                            csv_path, df, week_dir.name, week_number, user_folder, user_number
                        )
                    )
                else:
                    frames.append(
                        normalize_youtube_playlist(
                            csv_path, df, week_dir.name, week_number, user_folder, user_number
                        )
                    )
    if not frames:
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def empirical_percentile(values: np.ndarray, value: float) -> float:
    if not np.isfinite(value) or len(values) == 0:
        return math.nan
    less = np.sum(values < value)
    equal = np.sum(values == value)
    return float(100 * (less + 0.5 * equal) / len(values))


def empirical_band(percentile: float) -> str:
    if not np.isfinite(percentile):
        return ""
    if percentile <= 33.333333:
        return "bottom_third_vs_final_balanced"
    if percentile <= 66.666667:
        return "middle_third_vs_final_balanced"
    return "top_third_vs_final_balanced"


def range_band(value: float, baseline_values: np.ndarray, tier_ranges: dict[str, tuple[float, float]]) -> str:
    if not np.isfinite(value) or len(baseline_values) == 0:
        return ""
    if value < np.nanmin(baseline_values):
        return "below_final_balanced_min"
    if value > np.nanmax(baseline_values):
        return "above_final_balanced_max"
    for tier in ("Low", "Middle", "High"):
        if tier not in tier_ranges:
            continue
        low, high = tier_ranges[tier]
        if low <= value <= high:
            return f"within_final_balanced_{tier.casefold()}_range"
    return "between_final_balanced_tier_ranges"


def add_popularity_comparisons(tracks: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    tracks = tracks.copy()
    values = numeric(tracks["popularity_value"])
    tracks["popularity_value"] = values
    tracks["popularity_log10"] = np.where(values > 0, np.log10(values), np.nan)

    reference_rows = []
    for platform in PLATFORM_ORDER:
        baseline = tracks[(tracks["source_type"] == "baseline") & (tracks["platform"] == platform)]
        baseline_values = baseline["popularity_value"].dropna().to_numpy(dtype=float)
        baseline_logs = baseline["popularity_log10"].dropna().to_numpy(dtype=float)
        if len(baseline_values) == 0:
            continue
        median_value = float(np.nanmedian(baseline_values))
        median_log = float(np.nanmedian(baseline_logs))
        q25 = float(np.nanpercentile(baseline_values, 25))
        q75 = float(np.nanpercentile(baseline_values, 75))
        tier_ranges = {}
        for tier, tier_group in baseline.groupby("selection_tier"):
            if not tier:
                continue
            tier_values = tier_group["popularity_value"].dropna().to_numpy(dtype=float)
            if len(tier_values):
                tier_ranges[str(tier)] = (float(np.nanmin(tier_values)), float(np.nanmax(tier_values)))
                reference_rows.append(
                    {
                        "platform": platform,
                        "reference_type": f"final_balanced_{tier}_selection_range",
                        "track_count": len(tier_values),
                        "min_popularity_value": float(np.nanmin(tier_values)),
                        "q25_popularity_value": "",
                        "median_popularity_value": float(np.nanmedian(tier_values)),
                        "q75_popularity_value": "",
                        "max_popularity_value": float(np.nanmax(tier_values)),
                        "median_log10_popularity": float(np.nanmedian(np.log10(tier_values[tier_values > 0]))),
                    }
                )
        reference_rows.append(
            {
                "platform": platform,
                "reference_type": "final_balanced_all",
                "track_count": len(baseline_values),
                "min_popularity_value": float(np.nanmin(baseline_values)),
                "q25_popularity_value": q25,
                "median_popularity_value": median_value,
                "q75_popularity_value": q75,
                "max_popularity_value": float(np.nanmax(baseline_values)),
                "median_log10_popularity": median_log,
            }
        )

        mask = tracks["platform"] == platform
        platform_values = tracks.loc[mask, "popularity_value"].to_numpy(dtype=float)
        platform_logs = tracks.loc[mask, "popularity_log10"].to_numpy(dtype=float)
        percentiles = np.array(
            [empirical_percentile(baseline_values, value) for value in platform_values]
        )
        tracks.loc[mask, "baseline_empirical_percentile"] = percentiles
        tracks.loc[mask, "baseline_empirical_band"] = [
            empirical_band(percentile) for percentile in percentiles
        ]
        tracks.loc[mask, "baseline_range_band"] = [
            range_band(value, baseline_values, tier_ranges) for value in platform_values
        ]
        tracks.loc[mask, "baseline_median_value"] = median_value
        tracks.loc[mask, "baseline_median_log10"] = median_log
        tracks.loc[mask, "ratio_vs_baseline_median"] = np.where(
            median_value > 0,
            platform_values / median_value,
            np.nan,
        )
        tracks.loc[mask, "log10_delta_vs_baseline_median"] = platform_logs - median_log

    return tracks[STANDARD_COLUMNS], pd.DataFrame(reference_rows)


def summarize_tracks(tracks: pd.DataFrame) -> pd.DataFrame:
    rows = []
    group_cols = [
        "source_type",
        "playlist_kind",
        "week_folder",
        "week_number",
        "platform",
        "user_folder",
        "user_number",
        "playlist_name",
    ]
    for keys, group in tracks.groupby(group_cols, dropna=False, sort=True):
        values = group["popularity_value"].dropna().to_numpy(dtype=float)
        logs = group["popularity_log10"].dropna().to_numpy(dtype=float)
        deltas = group["log10_delta_vs_baseline_median"].dropna().to_numpy(dtype=float)
        ratios = group["ratio_vs_baseline_median"].dropna().to_numpy(dtype=float)
        baseline_percentiles = pd.to_numeric(
            group["baseline_empirical_percentile"], errors="coerce"
        ).dropna().to_numpy(dtype=float)
        bands = group["baseline_empirical_band"].fillna("")
        row = dict(zip(group_cols, keys))
        row.update(
            {
                "track_count": len(group),
                "tracks_with_popularity": len(values),
                "min_popularity_value": float(np.nanmin(values)) if len(values) else "",
                "median_popularity_value": float(np.nanmedian(values)) if len(values) else "",
                "mean_popularity_value": float(np.nanmean(values)) if len(values) else "",
                "max_popularity_value": float(np.nanmax(values)) if len(values) else "",
                "median_log10_popularity": float(np.nanmedian(logs)) if len(logs) else "",
                "mean_log10_popularity": float(np.nanmean(logs)) if len(logs) else "",
                "median_log10_delta_vs_final_balanced": (
                    float(np.nanmedian(deltas)) if len(deltas) else ""
                ),
                "mean_log10_delta_vs_final_balanced": (
                    float(np.nanmean(deltas)) if len(deltas) else ""
                ),
                "median_ratio_vs_final_balanced": float(np.nanmedian(ratios)) if len(ratios) else "",
                "median_baseline_empirical_percentile": (
                    float(np.nanmedian(baseline_percentiles)) if len(baseline_percentiles) else ""
                ),
                "mean_baseline_empirical_percentile": (
                    float(np.nanmean(baseline_percentiles)) if len(baseline_percentiles) else ""
                ),
                "share_above_final_balanced_median": (
                    float(np.nanmean(deltas > 0)) if len(deltas) else ""
                ),
                "share_top_third_vs_final_balanced": (
                    float(np.mean(bands == "top_third_vs_final_balanced")) if len(group) else ""
                ),
                "share_above_final_balanced_max": (
                    float(np.mean(group["baseline_range_band"] == "above_final_balanced_max"))
                    if len(group)
                    else ""
                ),
            }
        )
        rows.append(row)
    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary
    return summary.sort_values(["platform", "week_number", "user_number", "source_type"])


def metric_label(platform: str) -> str:
    if platform == "Spotify":
        return "log10 Spotify artist monthly listeners"
    return "log10 YouTube exact video view count"


def metric_title(platform: str) -> str:
    if platform == "Spotify":
        return "Spotify artist monthly listeners"
    return "YouTube exact video view count"


def delta_label(platform: str) -> str:
    if platform == "Spotify":
        return "Median log10 monthly-listener delta vs Spotify final-balanced baseline"
    return "Median log10 view-count delta vs YouTube final-balanced baseline"


def set_common_style() -> None:
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.titlesize": 11,
            "axes.labelsize": 10,
            "xtick.labelsize": 8,
            "ytick.labelsize": 9,
            "figure.dpi": 130,
            "savefig.dpi": 180,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def plot_week_positions(tracks: pd.DataFrame, plots_dir: Path) -> list[Path]:
    outputs = []
    recommended = tracks[tracks["source_type"] == "recommended"]
    for (week_folder, platform), group in recommended.groupby(["week_folder", "platform"], sort=True):
        baseline = tracks[(tracks["source_type"] == "baseline") & (tracks["platform"] == platform)]
        if baseline.empty or group.empty:
            continue
        users = sorted(group["user_number"].dropna().unique())
        ncols = 2
        nrows = math.ceil(len(users) / ncols)
        fig, axes = plt.subplots(nrows, ncols, figsize=(13, max(3.2, nrows * 2.6)), sharex=True, sharey=True)
        axes_arr = np.atleast_1d(axes).ravel()
        y_values = pd.concat([group["popularity_log10"], baseline["popularity_log10"]]).dropna()
        ymin = float(y_values.min()) - 0.25
        ymax = float(y_values.max()) + 0.25
        baseline_sorted = baseline.sort_values("playlist_position")
        for ax, user_number in zip(axes_arr, users):
            user_group = group[group["user_number"] == user_number].sort_values("playlist_position")
            ax.plot(
                baseline_sorted["playlist_position"],
                baseline_sorted["popularity_log10"],
                color=COLORS["baseline"],
                marker="o",
                markersize=3,
                linewidth=1,
                alpha=0.55,
                label=f"Final balanced {platform} baseline",
            )
            ax.scatter(
                user_group["playlist_position"],
                user_group["popularity_log10"],
                color=COLORS[platform],
                s=24,
                alpha=0.9,
                label=f"User{int(user_number)}",
            )
            ax.plot(
                user_group["playlist_position"],
                user_group["popularity_log10"],
                color=COLORS[platform],
                linewidth=0.8,
                alpha=0.35,
            )
            ax.axhline(
                float(baseline["baseline_median_log10"].dropna().iloc[0]),
                color=COLORS["zero"],
                linestyle=":",
                linewidth=1,
                alpha=0.65,
            )
            ax.set_title(f"User{int(user_number)}")
            ax.set_ylim(ymin, ymax)
            ax.grid(axis="y", color="#E8EAED", linewidth=0.8)
            if ax is axes_arr[0]:
                ax.legend(loc="upper right", frameon=False, fontsize=8)
        for ax in axes_arr[len(users) :]:
            ax.set_visible(False)
        fig.suptitle(f"{week_folder} {platform}: {metric_title(platform)} by playlist position", y=0.995)
        fig.supxlabel("Playlist position")
        fig.supylabel(metric_label(platform))
        fig.tight_layout()
        output = plots_dir / f"{slug(week_folder)}_{platform}_playlist_positions.png"
        fig.savefig(output, bbox_inches="tight")
        plt.close(fig)
        outputs.append(output)
    return outputs


def plot_week_distributions(tracks: pd.DataFrame, plots_dir: Path) -> list[Path]:
    outputs = []
    recommended = tracks[tracks["source_type"] == "recommended"]
    for (week_folder, platform), group in recommended.groupby(["week_folder", "platform"], sort=True):
        baseline = tracks[(tracks["source_type"] == "baseline") & (tracks["platform"] == platform)]
        if baseline.empty or group.empty:
            continue
        labels = ["Final balanced"]
        datasets = [baseline["popularity_log10"].dropna().to_numpy(dtype=float)]
        users = sorted(group["user_number"].dropna().unique())
        for user_number in users:
            user_logs = group[group["user_number"] == user_number]["popularity_log10"].dropna()
            labels.append(f"User{int(user_number)}")
            datasets.append(user_logs.to_numpy(dtype=float))

        fig, ax = plt.subplots(figsize=(max(11, len(labels) * 0.85), 6))
        try:
            box = ax.boxplot(datasets, tick_labels=labels, patch_artist=True, showfliers=False)
        except TypeError:
            box = ax.boxplot(datasets, labels=labels, patch_artist=True, showfliers=False)
        for index, patch in enumerate(box["boxes"]):
            patch.set_facecolor("#F1F3F4" if index == 0 else COLORS[platform])
            patch.set_alpha(0.55 if index == 0 else 0.38)
            patch.set_edgecolor("#5F6368")
        rng = np.random.default_rng(42)
        for index, data in enumerate(datasets, start=1):
            jitter = rng.normal(0, 0.035, size=len(data))
            color = COLORS["baseline"] if index == 1 else COLORS[platform]
            ax.scatter(np.full(len(data), index) + jitter, data, s=15, color=color, alpha=0.55)
        baseline_median = float(baseline["baseline_median_log10"].dropna().iloc[0])
        ax.axhline(baseline_median, color=COLORS["zero"], linestyle=":", linewidth=1.2)
        ax.set_title(f"{week_folder} {platform}: {metric_title(platform)} distribution vs own final-balanced baseline")
        ax.set_ylabel(metric_label(platform))
        ax.tick_params(axis="x", rotation=35)
        ax.grid(axis="y", color="#E8EAED", linewidth=0.8)
        fig.tight_layout()
        output = plots_dir / f"{slug(week_folder)}_{platform}_distributions.png"
        fig.savefig(output, bbox_inches="tight")
        plt.close(fig)
        outputs.append(output)
    return outputs


def plot_week_delta_bars(summary: pd.DataFrame, plots_dir: Path) -> list[Path]:
    outputs = []
    recommended = summary[summary["source_type"] == "recommended"].copy()
    if recommended.empty:
        return outputs
    recommended["median_log10_delta_vs_final_balanced"] = pd.to_numeric(
        recommended["median_log10_delta_vs_final_balanced"], errors="coerce"
    )
    for (week_folder, platform), group in recommended.groupby(["week_folder", "platform"], sort=True):
        group = group.sort_values("user_number")
        fig, ax = plt.subplots(figsize=(10.5, 4.8))
        values = group["median_log10_delta_vs_final_balanced"].to_numpy(dtype=float)
        labels = group["user_folder"].tolist()
        colors = [COLORS[platform] if value >= 0 else "#8AB4F8" for value in values]
        ax.bar(labels, values, color=colors, alpha=0.8)
        ax.axhline(0, color=COLORS["zero"], linewidth=1)
        ax.set_title(f"{week_folder} {platform}: median shift in {metric_title(platform)}")
        ax.set_ylabel(delta_label(platform))
        ax.tick_params(axis="x", rotation=35)
        ax.grid(axis="y", color="#E8EAED", linewidth=0.8)
        for index, value in enumerate(values):
            if np.isfinite(value):
                ax.text(index, value, f"{value:+.2f}", ha="center", va="bottom" if value >= 0 else "top", fontsize=8)
        fig.tight_layout()
        output = plots_dir / f"{slug(week_folder)}_{platform}_median_delta_bars.png"
        fig.savefig(output, bbox_inches="tight")
        plt.close(fig)
        outputs.append(output)
    return outputs


def plot_heatmaps(summary: pd.DataFrame, plots_dir: Path) -> list[Path]:
    outputs = []
    recommended = summary[summary["source_type"] == "recommended"].copy()
    if recommended.empty:
        return outputs
    recommended["median_log10_delta_vs_final_balanced"] = pd.to_numeric(
        recommended["median_log10_delta_vs_final_balanced"], errors="coerce"
    )
    for platform, group in recommended.groupby("platform", sort=True):
        pivot = group.pivot_table(
            index="user_folder",
            columns="week_folder",
            values="median_log10_delta_vs_final_balanced",
            aggfunc="mean",
        )
        if pivot.empty:
            continue
        pivot = pivot.reindex(sorted(pivot.index, key=lambda value: parse_user_number(value) or 0))
        columns = sorted(pivot.columns, key=lambda value: (parse_week_number(value) or 0, value))
        pivot = pivot[columns]
        data = pivot.to_numpy(dtype=float)
        finite = data[np.isfinite(data)]
        scale = max(0.05, float(np.nanmax(np.abs(finite))) if len(finite) else 0.05)
        fig, ax = plt.subplots(figsize=(max(6, len(columns) * 1.4), max(5, len(pivot.index) * 0.42)))
        image = ax.imshow(data, cmap="coolwarm", vmin=-scale, vmax=scale, aspect="auto")
        ax.set_xticks(np.arange(len(columns)), columns, rotation=35, ha="right")
        ax.set_yticks(np.arange(len(pivot.index)), pivot.index)
        ax.set_title(f"{platform}: median shift in {metric_title(platform)} by week/user")
        for row in range(data.shape[0]):
            for col in range(data.shape[1]):
                value = data[row, col]
                if np.isfinite(value):
                    ax.text(col, row, f"{value:+.2f}", ha="center", va="center", fontsize=8)
        cbar = fig.colorbar(image, ax=ax)
        cbar.set_label(delta_label(platform))
        fig.tight_layout()
        output = plots_dir / f"{platform}_weekly_user_median_delta_heatmap.png"
        fig.savefig(output, bbox_inches="tight")
        plt.close(fig)
        outputs.append(output)
    return outputs


def plot_week_percentile_bars(summary: pd.DataFrame, plots_dir: Path) -> list[Path]:
    """Compare platforms on a shared 0-100 within-platform baseline scale."""
    outputs = []
    recommended = summary[summary["source_type"] == "recommended"].copy()
    if recommended.empty:
        return outputs
    recommended["median_baseline_empirical_percentile"] = pd.to_numeric(
        recommended["median_baseline_empirical_percentile"], errors="coerce"
    )
    for week_folder, group in recommended.groupby("week_folder", sort=True):
        users = sorted(group["user_folder"].unique(), key=lambda value: parse_user_number(value) or 0)
        x = np.arange(len(users))
        width = 0.36
        fig, ax = plt.subplots(figsize=(max(10.5, len(users) * 0.9), 5.2))
        for offset, platform in [(-width / 2, "Spotify"), (width / 2, "Youtube")]:
            platform_group = group[group["platform"] == platform].set_index("user_folder")
            values = [
                platform_group.loc[user, "median_baseline_empirical_percentile"]
                if user in platform_group.index
                else np.nan
                for user in users
            ]
            ax.bar(
                x + offset,
                values,
                width=width,
                label=f"{platform} vs own baseline",
                color=COLORS[platform],
                alpha=0.78,
            )
        ax.axhline(50, color=COLORS["zero"], linestyle=":", linewidth=1.2, label="Final-balanced median")
        ax.axhspan(0, 33.333333, color="#E8F0FE", alpha=0.35, zorder=0)
        ax.axhspan(66.666667, 100, color="#FCE8E6", alpha=0.35, zorder=0)
        ax.set_ylim(0, 100)
        ax.set_xticks(x, users, rotation=35, ha="right")
        ax.set_ylabel("Median percentile within own platform final-balanced baseline")
        ax.set_title(f"{week_folder}: normalized popularity bias by user and platform")
        ax.grid(axis="y", color="#E8EAED", linewidth=0.8)
        ax.legend(frameon=False, loc="upper left")
        for container in ax.containers:
            ax.bar_label(container, fmt="%.0f", padding=2, fontsize=8)
        fig.tight_layout()
        output = plots_dir / f"{slug(week_folder)}_normalized_baseline_percentile_bars.png"
        fig.savefig(output, bbox_inches="tight")
        plt.close(fig)
        outputs.append(output)
    return outputs


def plot_percentile_heatmaps(summary: pd.DataFrame, plots_dir: Path) -> list[Path]:
    outputs = []
    recommended = summary[summary["source_type"] == "recommended"].copy()
    if recommended.empty:
        return outputs
    recommended["median_baseline_empirical_percentile"] = pd.to_numeric(
        recommended["median_baseline_empirical_percentile"], errors="coerce"
    )
    for platform, group in recommended.groupby("platform", sort=True):
        pivot = group.pivot_table(
            index="user_folder",
            columns="week_folder",
            values="median_baseline_empirical_percentile",
            aggfunc="mean",
        )
        if pivot.empty:
            continue
        pivot = pivot.reindex(sorted(pivot.index, key=lambda value: parse_user_number(value) or 0))
        columns = sorted(pivot.columns, key=lambda value: (parse_week_number(value) or 0, value))
        pivot = pivot[columns]
        data = pivot.to_numpy(dtype=float)
        fig, ax = plt.subplots(figsize=(max(6, len(columns) * 1.4), max(5, len(pivot.index) * 0.42)))
        image = ax.imshow(data, cmap="YlOrRd", vmin=0, vmax=100, aspect="auto")
        ax.set_xticks(np.arange(len(columns)), columns, rotation=35, ha="right")
        ax.set_yticks(np.arange(len(pivot.index)), pivot.index)
        ax.set_title(f"{platform}: median percentile within own final-balanced baseline")
        for row in range(data.shape[0]):
            for col in range(data.shape[1]):
                value = data[row, col]
                if np.isfinite(value):
                    ax.text(col, row, f"{value:.0f}", ha="center", va="center", fontsize=8)
        cbar = fig.colorbar(image, ax=ax)
        cbar.set_label("Median baseline percentile (0=less popular, 100=more popular)")
        fig.tight_layout()
        output = plots_dir / f"{platform}_weekly_user_baseline_percentile_heatmap.png"
        fig.savefig(output, bbox_inches="tight")
        plt.close(fig)
        outputs.append(output)
    return outputs


def write_outputs(
    tracks: pd.DataFrame,
    summary: pd.DataFrame,
    baseline_reference: pd.DataFrame,
    output_dir: Path,
) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    tracks_path = output_dir / STANDARD_TRACKS_NAME
    summary_path = output_dir / SUMMARY_NAME
    baseline_path = output_dir / BASELINE_REFERENCE_NAME
    tracks.to_csv(tracks_path, index=False)
    summary.to_csv(summary_path, index=False)
    baseline_reference.to_csv(baseline_path, index=False)
    return tracks_path, summary_path, baseline_path


def main() -> int:
    args = parse_args()
    results_root = args.results_root.expanduser().resolve()
    baseline_path = args.baseline.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if not results_root.is_dir():
        raise FileNotFoundError(f"Experiment results folder not found: {results_root}")
    if not baseline_path.is_file():
        raise FileNotFoundError(f"Baseline playlist not found: {baseline_path}")

    requested_platforms = [normalize_platform(item) for item in args.platform]
    weekly = load_weekly_tracks(results_root, args.week, requested_platforms)
    baseline = normalize_baseline(baseline_path)
    if requested_platforms:
        baseline = baseline[baseline["platform"].isin(requested_platforms)]
    tracks = pd.concat([baseline, weekly], ignore_index=True)
    tracks, baseline_reference = add_popularity_comparisons(tracks)
    summary = summarize_tracks(tracks)
    tracks_path, summary_path, baseline_path_out = write_outputs(
        tracks, summary, baseline_reference, output_dir
    )

    plot_paths: list[Path] = []
    if not args.no_plots:
        set_common_style()
        plots_dir = output_dir / "plots"
        plots_dir.mkdir(parents=True, exist_ok=True)
        plot_paths.extend(plot_week_positions(tracks, plots_dir))
        plot_paths.extend(plot_week_distributions(tracks, plots_dir))
        plot_paths.extend(plot_week_delta_bars(summary, plots_dir))
        plot_paths.extend(plot_heatmaps(summary, plots_dir))
        plot_paths.extend(plot_week_percentile_bars(summary, plots_dir))
        plot_paths.extend(plot_percentile_heatmaps(summary, plots_dir))

    print(f"Standardized tracks: {tracks_path}")
    print(f"Playlist summary: {summary_path}")
    print(f"Baseline reference: {baseline_path_out}")
    print(f"Plots written: {len(plot_paths)}")
    for path in plot_paths:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
