"""Compare weekly recommendation popularity distributions with the original playlist.

Spotify and YouTube are deliberately analysed separately because their
popularity constructs differ. Spotify uses primary-artist monthly listeners;
YouTube uses cumulative views of the exact recommended video.

Week1 and Week2 recommendations are excluded by default. The original playlist
is still loaded and included as the reference in every plot.

Examples:
    python3 analysis/plot_weekly_popularity_distributions.py spotify
    python3 analysis/plot_weekly_popularity_distributions.py youtube --user 4
    python3 analysis/plot_weekly_popularity_distributions.py spotify --include-first-two-weeks
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Iterable, Sequence


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
from matplotlib.ticker import FuncFormatter
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_ROOT = ROOT / "experiment_results"
DEFAULT_OUTPUT_ROOT = ROOT / "initial_data_analysis"
WEEK_RE = re.compile(r"week\s*[_-]?\s*0*([0-9]+)", flags=re.IGNORECASE)
USER_RE = re.compile(r"user\s*[_-]?\s*0*([0-9]+)", flags=re.IGNORECASE)


@dataclass(frozen=True)
class PlatformConfig:
    key: str
    directory_names: tuple[str, ...]
    display_name: str
    metric_name: str
    metric_title: str
    metric_columns: tuple[str, ...]
    original_metric_columns: tuple[str, ...]
    track_id_columns: tuple[str, ...]
    track_name_columns: tuple[str, ...]
    artist_columns: tuple[str, ...]
    video_type_columns: tuple[str, ...]
    error_columns: tuple[str, ...]
    base_color: str


PLATFORMS = {
    "spotify": PlatformConfig(
        key="spotify",
        directory_names=("spotify",),
        display_name="Spotify",
        metric_name="spotify_artist_monthly_listeners",
        metric_title="primary artist monthly listeners",
        metric_columns=(
            "popularity_metric_value",
            "primary_artist_monthly_listeners",
            "artist_monthly_listeners",
        ),
        original_metric_columns=(
            "artist_monthly_listeners",
            "popularity_metric_value",
            "primary_artist_monthly_listeners",
        ),
        track_id_columns=("spotify_track_id", "track_id"),
        track_name_columns=("track_name", "spotify_title", "title"),
        artist_columns=(
            "primary_artist_name",
            "artist_names",
            "spotify_artists",
            "research_artist",
        ),
        video_type_columns=("track_type",),
        error_columns=(
            "popularity_metric_fetch_error",
            "primary_artist_monthly_listeners_fetch_error",
            "artist_monthly_listeners_fetch_error",
            "track_lookup_error",
        ),
        base_color="#1DB954",
    ),
    "youtube": PlatformConfig(
        key="youtube",
        directory_names=("youtube", "youtube music", "youtube_music"),
        display_name="YouTube",
        metric_name="youtube_exact_video_view_count",
        metric_title="exact recommended-video view count",
        metric_columns=("popularity_value_view_count", "view_count"),
        original_metric_columns=("view_count", "popularity_value_view_count"),
        track_id_columns=("video_id", "youtube_video_id"),
        track_name_columns=("title", "youtube_title", "track_name"),
        artist_columns=(
            "primary_artist_name",
            "artists",
            "youtube_artists",
            "research_artist",
        ),
        video_type_columns=("video_type",),
        error_columns=("song_lookup_error", "song_fetch_error", "watch_fetch_error"),
        base_color="#D93025",
    ),
}

PLATFORM_ALIASES = {
    "spotify": "spotify",
    "youtube": "youtube",
    "youtube_music": "youtube",
    "youtube-music": "youtube",
    "youtubemusic": "youtube",
}

TRACK_COLUMNS = [
    "source_type",
    "platform",
    "week_folder",
    "week_number",
    "user_folder",
    "user_number",
    "playlist_file",
    "playlist_name",
    "playlist_position",
    "track_id",
    "track_name",
    "artist_name",
    "popularity_metric",
    "popularity_value",
    "popularity_log10",
    "percentile_within_original_distribution",
    "ratio_to_original_median",
    "log10_delta_from_original_median",
    "captured_at_utc",
    "video_or_track_type",
    "metadata_error",
]


def platform_argument(value: str) -> str:
    key = PLATFORM_ALIASES.get(value.strip().casefold())
    if key is None:
        accepted = ", ".join(sorted(PLATFORM_ALIASES))
        raise argparse.ArgumentTypeError(f"unknown platform {value!r}; use one of: {accepted}")
    return key


def user_argument(value: str) -> int:
    match = USER_RE.fullmatch(value.strip())
    if match:
        return int(match.group(1))
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("user must be a number such as 4 or User4") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("user must be at least 1")
    return number


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "platform",
        type=platform_argument,
        help="Platform to analyse (lower-case spotify or youtube).",
    )
    parser.add_argument(
        "--user",
        type=user_argument,
        help="Only analyse and plot this user, e.g. --user 4 or --user User4.",
    )
    parser.add_argument(
        "--include-first-two-weeks",
        "--include-weeks-1-2",
        action="store_true",
        help="Include Week1 and Week2 recommendations (excluded by default).",
    )
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--original-playlist",
        type=Path,
        help="Optional explicit original_playlist_popularity.csv path.",
    )
    parser.add_argument("--dpi", type=int, default=180, help="PNG resolution (default: 180).")
    return parser.parse_args(argv)


def parse_week_number(value: str) -> int | None:
    match = WEEK_RE.search(value or "")
    return int(match.group(1)) if match else None


def parse_user_number(value: str) -> int | None:
    match = USER_RE.search(value or "")
    return int(match.group(1)) if match else None


def normalize_directory_name(value: str) -> str:
    return re.sub(r"[-_]+", " ", value.strip().casefold())


def relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False)


def first_existing(df: pd.DataFrame, columns: Iterable[str]) -> pd.Series:
    values = pd.Series([""] * len(df), index=df.index, dtype=object)
    for column in columns:
        if column not in df.columns:
            continue
        candidate = df[column].fillna("").astype(str).str.strip()
        values = values.mask(values.eq("") & candidate.ne(""), candidate)
    return values


def numeric_values(df: pd.DataFrame, columns: Iterable[str]) -> pd.Series:
    raw = first_existing(df, columns).str.replace(",", "", regex=False)
    return pd.to_numeric(raw, errors="coerce")


def matching_platform_dir(week_dir: Path, config: PlatformConfig) -> Path | None:
    accepted = {normalize_directory_name(name) for name in config.directory_names}
    for candidate in sorted(week_dir.iterdir()):
        if candidate.is_dir() and normalize_directory_name(candidate.name) in accepted:
            return candidate
    return None


def sorted_week_dirs(results_root: Path, include_first_two_weeks: bool) -> list[Path]:
    if not results_root.is_dir():
        raise FileNotFoundError(f"experiment results directory does not exist: {results_root}")
    weeks = []
    for path in results_root.iterdir():
        if not path.is_dir():
            continue
        week_number = parse_week_number(path.name)
        if week_number is None or (not include_first_two_weeks and week_number <= 2):
            continue
        weeks.append(path)
    return sorted(weeks, key=lambda path: (parse_week_number(path.name) or 0, path.name))


def find_original_playlist(
    results_root: Path,
    config: PlatformConfig,
    explicit_path: Path | None,
) -> Path:
    if explicit_path is not None:
        if not explicit_path.is_file():
            raise FileNotFoundError(f"original playlist CSV does not exist: {explicit_path}")
        return explicit_path

    accepted = {normalize_directory_name(name) for name in config.directory_names}
    candidates = []
    for path in results_root.rglob("original_playlist_popularity.csv"):
        if not path.is_file() or normalize_directory_name(path.parent.name) not in accepted:
            continue
        week_number = next(
            (
                parse_week_number(parent.name)
                for parent in path.parents
                if parse_week_number(parent.name) is not None
            ),
            math.inf,
        )
        candidates.append((week_number, str(path), path))
    if not candidates:
        raise FileNotFoundError(
            f"no {config.display_name} original_playlist_popularity.csv found under {results_root}"
        )
    return sorted(candidates, key=lambda item: (item[0], item[1]))[0][2]


def normalize_playlist(
    path: Path,
    config: PlatformConfig,
    *,
    source_type: str,
    metric_columns: Iterable[str],
    week_folder: str,
    week_number: int,
    user_folder: str,
    user_number: int | None,
) -> pd.DataFrame:
    df = read_csv(path)
    if df.empty:
        return pd.DataFrame(columns=TRACK_COLUMNS)

    position = first_existing(df, ("playlist_position", "position"))
    fallback = pd.Series(range(1, len(df) + 1), index=df.index, dtype=object)
    position = position.mask(position.eq(""), fallback)
    values = numeric_values(df, metric_columns)
    output = pd.DataFrame(
        {
            "source_type": source_type,
            "platform": config.key,
            "week_folder": week_folder,
            "week_number": week_number,
            "user_folder": user_folder,
            "user_number": user_number if user_number is not None else pd.NA,
            "playlist_file": relative_path(path),
            "playlist_name": first_existing(df, ("playlist_name", "requested_playlist_name")),
            "playlist_position": position,
            "track_id": first_existing(df, config.track_id_columns),
            "track_name": first_existing(df, config.track_name_columns),
            "artist_name": first_existing(df, config.artist_columns),
            "popularity_metric": config.metric_name,
            "popularity_value": values,
            "popularity_log10": np.where(values > 0, np.log10(values), np.nan),
            "percentile_within_original_distribution": np.nan,
            "ratio_to_original_median": np.nan,
            "log10_delta_from_original_median": np.nan,
            "captured_at_utc": first_existing(df, ("captured_at_utc",)),
            "video_or_track_type": first_existing(df, config.video_type_columns),
            "metadata_error": first_existing(df, config.error_columns),
        }
    )
    output["week_number"] = pd.to_numeric(output["week_number"], errors="coerce").astype("Int64")
    output["user_number"] = pd.to_numeric(output["user_number"], errors="coerce").astype("Int64")
    return output[TRACK_COLUMNS]


def load_tracks(
    results_root: Path,
    config: PlatformConfig,
    include_first_two_weeks: bool,
    selected_user: int | None,
    original_path: Path,
) -> pd.DataFrame:
    frames = [
        normalize_playlist(
            original_path,
            config,
            source_type="original",
            metric_columns=config.original_metric_columns,
            week_folder="Original playlist",
            week_number=0,
            user_folder="Original playlist",
            user_number=None,
        )
    ]
    available_users: set[int] = set()
    for week_dir in sorted_week_dirs(results_root, include_first_two_weeks):
        week_number = parse_week_number(week_dir.name)
        platform_dir = matching_platform_dir(week_dir, config)
        if week_number is None or platform_dir is None:
            continue
        user_dirs = sorted(
            (
                path
                for path in platform_dir.iterdir()
                if path.is_dir() and parse_user_number(path.name) is not None
            ),
            key=lambda path: (parse_user_number(path.name) or 0, path.name),
        )
        for user_dir in user_dirs:
            user_number = parse_user_number(user_dir.name)
            if user_number is None:
                continue
            available_users.add(user_number)
            if selected_user is not None and user_number != selected_user:
                continue
            for csv_path in sorted(user_dir.glob("*.csv")):
                normalized = normalize_playlist(
                    csv_path,
                    config,
                    source_type="recommended",
                    metric_columns=config.metric_columns,
                    week_folder=week_dir.name,
                    week_number=week_number,
                    user_folder=f"User{user_number}",
                    user_number=user_number,
                )
                if not normalized.empty:
                    frames.append(normalized)

    if selected_user is not None and selected_user not in available_users:
        found = ", ".join(str(number) for number in sorted(available_users)) or "none"
        raise ValueError(
            f"User{selected_user} has no {config.display_name} playlist in the selected weeks; "
            f"available users: {found}"
        )

    tracks = pd.concat(frames, ignore_index=True)
    original = tracks[tracks["source_type"] == "original"]
    recommended = tracks[tracks["source_type"] == "recommended"]
    if original["popularity_value"].notna().sum() == 0:
        raise ValueError(
            f"the original playlist has no values for {config.metric_name}: {original_path}"
        )
    if recommended.empty:
        week_rule = "all weeks" if include_first_two_weeks else "Week3 and later"
        raise ValueError(f"no {config.display_name} user playlist CSVs were found for {week_rule}")
    return add_original_comparisons(tracks)


def empirical_percentile(reference: np.ndarray, value: float) -> float:
    if not np.isfinite(value) or len(reference) == 0:
        return math.nan
    less = np.sum(reference < value)
    equal = np.sum(reference == value)
    return float(100.0 * (less + 0.5 * equal) / len(reference))


def add_original_comparisons(tracks: pd.DataFrame) -> pd.DataFrame:
    tracks = tracks.copy()
    reference = (
        tracks.loc[tracks["source_type"] == "original", "popularity_value"]
        .dropna()
        .to_numpy(dtype=float)
    )
    reference_median = float(np.median(reference))
    reference_log_median = math.log10(reference_median) if reference_median > 0 else math.nan
    values = pd.to_numeric(tracks["popularity_value"], errors="coerce").to_numpy(dtype=float)
    logs = pd.to_numeric(tracks["popularity_log10"], errors="coerce").to_numpy(dtype=float)
    tracks["percentile_within_original_distribution"] = [
        empirical_percentile(reference, value) for value in values
    ]
    tracks["ratio_to_original_median"] = (
        values / reference_median if reference_median > 0 else np.full(len(values), np.nan)
    )
    tracks["log10_delta_from_original_median"] = logs - reference_log_median
    return tracks[TRACK_COLUMNS]


def ks_distance(first: np.ndarray, second: np.ndarray) -> float:
    """Return the two-sample Kolmogorov-Smirnov distance without a p-value."""
    first = np.sort(first[np.isfinite(first)])
    second = np.sort(second[np.isfinite(second)])
    if len(first) == 0 or len(second) == 0:
        return math.nan
    points = np.sort(np.unique(np.concatenate([first, second])))
    first_cdf = np.searchsorted(first, points, side="right") / len(first)
    second_cdf = np.searchsorted(second, points, side="right") / len(second)
    return float(np.max(np.abs(first_cdf - second_cdf)))


def summarize_tracks(tracks: pd.DataFrame) -> pd.DataFrame:
    reference = (
        tracks.loc[tracks["source_type"] == "original", "popularity_value"]
        .dropna()
        .to_numpy(dtype=float)
    )
    reference_median = float(np.median(reference))
    reference_log_median = math.log10(reference_median) if reference_median > 0 else math.nan
    group_columns = [
        "source_type",
        "week_folder",
        "week_number",
        "user_folder",
        "user_number",
        "playlist_file",
        "playlist_name",
    ]
    rows = []
    for keys, group in tracks.groupby(group_columns, dropna=False, sort=False):
        row = dict(zip(group_columns, keys))
        values = group["popularity_value"].dropna().to_numpy(dtype=float)
        logs = group["popularity_log10"].dropna().to_numpy(dtype=float)
        is_original = row["source_type"] == "original"
        median = float(np.median(values)) if len(values) else math.nan
        row.update(
            {
                "platform": group["platform"].iloc[0],
                "popularity_metric": group["popularity_metric"].iloc[0],
                "track_count": len(group),
                "tracks_with_popularity": len(values),
                "tracks_missing_popularity": len(group) - len(values),
                "minimum": float(np.min(values)) if len(values) else math.nan,
                "q25": float(np.quantile(values, 0.25)) if len(values) else math.nan,
                "median": median,
                "mean": float(np.mean(values)) if len(values) else math.nan,
                "q75": float(np.quantile(values, 0.75)) if len(values) else math.nan,
                "maximum": float(np.max(values)) if len(values) else math.nan,
                "mean_log10": float(np.mean(logs)) if len(logs) else math.nan,
                "sd_log10": float(np.std(logs, ddof=1)) if len(logs) > 1 else math.nan,
                "geometric_mean": float(10 ** np.mean(logs)) if len(logs) else math.nan,
                "median_ratio_vs_original": (
                    1.0 if is_original else median / reference_median
                    if len(values) and reference_median > 0 else math.nan
                ),
                "median_log10_delta_vs_original": (
                    0.0 if is_original else math.log10(median) - reference_log_median
                    if len(values) and median > 0 else math.nan
                ),
                "share_above_original_median": (
                    float(np.mean(values > reference_median)) if len(values) else math.nan
                ),
                "ks_distance_vs_original": 0.0 if is_original else ks_distance(values, reference),
                "first_capture_utc": min(
                    (value for value in group["captured_at_utc"] if value), default=""
                ),
                "last_capture_utc": max(
                    (value for value in group["captured_at_utc"] if value), default=""
                ),
            }
        )
        rows.append(row)

    summary = pd.DataFrame(rows)
    summary["week_number"] = pd.to_numeric(summary["week_number"], errors="coerce").astype("Int64")
    summary["user_number"] = pd.to_numeric(summary["user_number"], errors="coerce").astype("Int64")
    summary["_source_order"] = summary["source_type"].map({"original": 0, "recommended": 1})
    return summary.sort_values(
        ["_source_order", "user_number", "week_number", "playlist_file"],
        na_position="first",
    ).drop(columns="_source_order")


def format_count(value: float, _position: int | None = None) -> str:
    if not np.isfinite(value):
        return ""
    absolute = abs(value)
    for divisor, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if absolute >= divisor:
            scaled = value / divisor
            return f"{scaled:.0f}{suffix}" if scaled >= 10 else f"{scaled:.1f}{suffix}"
    return f"{value:.0f}"


def ecdf(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    values = np.sort(values[np.isfinite(values) & (values > 0)])
    return values, np.arange(1, len(values) + 1, dtype=float) / len(values)


def playlist_datasets_for_user(
    tracks: pd.DataFrame,
    user_number: int,
) -> list[tuple[str, np.ndarray]]:
    original = tracks[tracks["source_type"] == "original"]
    datasets = [
        (
            "Original playlist",
            original["popularity_value"].dropna().to_numpy(dtype=float),
        )
    ]
    user_tracks = tracks[
        (tracks["source_type"] == "recommended") & (tracks["user_number"] == user_number)
    ]
    grouped = list(
        user_tracks.groupby(
            ["week_number", "week_folder", "playlist_file"], dropna=False, sort=False
        )
    )
    grouped.sort(key=lambda item: (int(item[0][0]), str(item[0][2])))
    week_counts: dict[int, int] = {}
    for (week_number, _week_folder, _playlist_file), group in grouped:
        number = int(week_number)
        week_counts[number] = week_counts.get(number, 0) + 1
        suffix = f".{week_counts[number]}" if week_counts[number] > 1 else ""
        datasets.append(
            (f"Week {number}{suffix}", group["popularity_value"].dropna().to_numpy(dtype=float))
        )
    return datasets


def plot_user_distribution(
    tracks: pd.DataFrame,
    config: PlatformConfig,
    user_number: int,
    output_path: Path,
    dpi: int,
) -> None:
    datasets = playlist_datasets_for_user(tracks, user_number)
    palette = plt.get_cmap("tab10")
    weekly_colors = (
        [config.base_color]
        if len(datasets) == 2
        else [palette(index % 10) for index in range(len(datasets) - 1)]
    )
    colors = ["#4B5563", *weekly_colors]

    fig, (ecdf_ax, box_ax) = plt.subplots(1, 2, figsize=(13.5, 6.2))
    for index, ((label, values), color) in enumerate(zip(datasets, colors)):
        x, y = ecdf(values)
        if len(x) == 0:
            continue
        ecdf_ax.step(
            x,
            y,
            where="post",
            label=f"{label} (n={len(x)})",
            color=color,
            linewidth=2.2 if index == 0 else 1.8,
            linestyle="--" if index == 0 else "-",
        )
    ecdf_ax.set_xscale("log")
    ecdf_ax.xaxis.set_major_formatter(FuncFormatter(format_count))
    ecdf_ax.set_xlabel(f"{config.metric_title.capitalize()} (log scale)")
    ecdf_ax.set_ylabel("Cumulative share of playlist tracks")
    ecdf_ax.set_title("Empirical cumulative distributions")
    ecdf_ax.set_ylim(0, 1.02)
    ecdf_ax.grid(True, which="major", alpha=0.22)
    ecdf_ax.legend(frameon=False, fontsize=9, loc="lower right")

    labels = [label for label, _values in datasets]
    positive_values = [values[np.isfinite(values) & (values > 0)] for _label, values in datasets]
    try:
        box = box_ax.boxplot(
            positive_values,
            tick_labels=labels,
            vert=False,
            patch_artist=True,
            showfliers=False,
            widths=0.56,
        )
    except TypeError:
        box = box_ax.boxplot(
            positive_values,
            labels=labels,
            vert=False,
            patch_artist=True,
            showfliers=False,
            widths=0.56,
        )
    for patch, color in zip(box["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.20)
        patch.set_edgecolor(color)
        patch.set_linewidth(1.4)
    for index, (values, color) in enumerate(zip(positive_values, colors), start=1):
        if len(values) == 0:
            continue
        jitter = np.linspace(-0.16, 0.16, len(values))
        box_ax.scatter(values, np.full(len(values), index) + jitter, s=17, color=color, alpha=0.55)
        median = float(np.median(values))
        box_ax.scatter(
            [median], [index], marker="D", s=32, color=color, edgecolor="white", linewidth=0.6
        )
    box_ax.set_xscale("log")
    box_ax.xaxis.set_major_formatter(FuncFormatter(format_count))
    box_ax.set_xlabel(f"{config.metric_title.capitalize()} (log scale)")
    box_ax.set_title("Playlist medians, spread, and individual tracks")
    box_ax.grid(True, axis="x", which="major", alpha=0.22)

    included_weeks = ", ".join(label for label, _values in datasets[1:])
    fig.suptitle(
        f"{config.display_name} popularity distributions — User {user_number}",
        fontsize=15,
        fontweight="bold",
        y=0.985,
    )
    fig.text(
        0.5,
        0.935,
        f"Original playlist compared with {included_weeks}",
        ha="center",
        fontsize=10,
        color="#4B5563",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def output_directory(args: argparse.Namespace, config: PlatformConfig) -> Path:
    audience = f"user_{args.user:02d}" if args.user is not None else "all_users"
    week_scope = "all_weeks" if args.include_first_two_weeks else "from_week3"
    return args.output_root / config.key / "popularity_distributions" / f"{audience}_{week_scope}"


def write_notes(
    path: Path,
    config: PlatformConfig,
    tracks: pd.DataFrame,
    args: argparse.Namespace,
) -> None:
    weeks = sorted(
        int(value)
        for value in tracks.loc[
            tracks["source_type"] == "recommended", "week_number"
        ].dropna().unique()
    )
    users = sorted(
        int(value)
        for value in tracks.loc[
            tracks["source_type"] == "recommended", "user_number"
        ].dropna().unique()
    )
    construct_note = (
        "Spotify popularity is an artist-level reach proxy, not track popularity."
        if config.key == "spotify"
        else "YouTube popularity is the cumulative view count of the exact recommended video; "
        "video type is retained because recommendations can be Art Tracks or official music videos."
    )
    text = f"""# {config.display_name} weekly popularity distributions

Metric: `{config.metric_name}` ({config.metric_title}).

Included recommendation weeks: {', '.join(f'Week{week}' for week in weeks)}.
Included users: {', '.join(f'User{user}' for user in users)}.
Week1 and Week2 recommendations included: {'yes' if args.include_first_two_weeks else 'no'}.
The original playlist is included in every figure regardless of the week setting.

{construct_note}

Files:

- `popularity_tracks.csv`: normalized track-level data and comparisons with the original distribution.
- `playlist_popularity_summary.csv`: descriptive statistics, median shifts, and the two-sample KS distance for every weekly playlist.
- `plots/user_XX_popularity_distributions.png`: original-versus-weekly ECDF and box/strip plots for one user only.
- `run_metadata.json`: inputs and run settings used to create this directory.

The count axes are logarithmic because popularity spans orders of magnitude. Raw counts remain in both CSV files.
"""
    path.write_text(text, encoding="utf-8")


def run(args: argparse.Namespace) -> Path:
    config = PLATFORMS[args.platform]
    original_path = find_original_playlist(args.results_root, config, args.original_playlist)
    tracks = load_tracks(
        args.results_root,
        config,
        args.include_first_two_weeks,
        args.user,
        original_path,
    )
    summary = summarize_tracks(tracks)

    destination = output_directory(args, config)
    plots_dir = destination / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    tracks.to_csv(destination / "popularity_tracks.csv", index=False, float_format="%.8g")
    summary.to_csv(destination / "playlist_popularity_summary.csv", index=False, float_format="%.8g")

    users = sorted(
        int(value)
        for value in tracks.loc[
            tracks["source_type"] == "recommended", "user_number"
        ].dropna().unique()
    )
    generated_plots = []
    for user_number in users:
        plot_path = plots_dir / f"user_{user_number:02d}_popularity_distributions.png"
        plot_user_distribution(tracks, config, user_number, plot_path, args.dpi)
        generated_plots.append(relative_path(plot_path))

    write_notes(destination / "README.md", config, tracks, args)
    weeks = sorted(
        int(value)
        for value in tracks.loc[
            tracks["source_type"] == "recommended", "week_number"
        ].dropna().unique()
    )
    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": config.key,
        "platform_display_name": config.display_name,
        "popularity_metric": config.metric_name,
        "metric_description": config.metric_title,
        "results_root": relative_path(args.results_root),
        "original_playlist_file": relative_path(original_path),
        "include_first_two_weeks": args.include_first_two_weeks,
        "included_weeks": weeks,
        "selected_user": args.user,
        "included_users": users,
        "recommended_track_rows": int((tracks["source_type"] == "recommended").sum()),
        "original_track_rows": int((tracks["source_type"] == "original").sum()),
        "generated_plots": generated_plots,
    }
    (destination / "run_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )

    print(f"Platform: {config.display_name}")
    print(f"Metric: {config.metric_title}")
    print(f"Weeks: {', '.join(f'Week{week}' for week in weeks)}")
    print(f"Users: {', '.join(f'User{user}' for user in users)}")
    print(f"Wrote: {destination}")
    return destination


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        run(args)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"error: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
