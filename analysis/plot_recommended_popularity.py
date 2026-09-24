"""Create platform-specific popularity-bias plots for recommendation weeks.

The script reads the cleaned Spotify and YouTube song tables. It compares each
recommendation week with the 30-song final balanced playlist and keeps the two
platform metrics separate:

* Spotify: primary-artist monthly listeners
* YouTube: exact recommended-video view count

Raw popularity is shown on log10(value + 1) scales. Normalized plots use the
percentile and tier calculated against the frozen 83-song candidate pool that
was used to construct the balanced playlist. The script discovers all
recommendation weeks in the clean tables unless ``--weeks`` is supplied.

Examples:
    python3 analysis/plot_recommended_popularity.py
    python3 analysis/plot_recommended_popularity.py --weeks 3 4 5 6
    python3 analysis/plot_recommended_popularity.py --platform Spotify
"""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
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
from matplotlib.lines import Line2D
from matplotlib.ticker import PercentFormatter
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = ROOT / "analysis_results" / "popularity_bias" / "clean_platform_tables"
DEFAULT_OUTPUT_DIR = ROOT / "analysis_results" / "popularity_bias" / "platform_popularity_plots"

PLATFORM_CONFIG = {
    "Spotify": {
        "filename": "spotify_weeks3_6_song_popularity_clean.csv",
        "slug": "spotify",
        "metric": "primary-artist monthly listeners",
        "short_metric": "monthly listeners",
        "color": "#16833f",
    },
    "YouTube": {
        "filename": "youtube_weeks3_6_song_popularity_clean.csv",
        "slug": "youtube",
        "metric": "exact recommended-video views",
        "short_metric": "video views",
        "color": "#c7352d",
    },
}

TIER_ORDER = ["Low", "Buffer", "Middle", "High"]
TIER_COLORS = {
    "Low": "#9ecae1",
    "Buffer": "#d9d9d9",
    "Middle": "#74c476",
    "High": "#ef8a62",
}
REQUIRED_COLUMNS = {
    "row_type",
    "week_number",
    "user_number",
    "popularity_value",
    "original_candidate_pool_percentile_83",
    "original_candidate_pool_rank_tier_83",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--platform",
        action="append",
        choices=tuple(PLATFORM_CONFIG),
        help="Platform to render. Repeat for both; default is both.",
    )
    parser.add_argument(
        "--weeks",
        nargs="+",
        type=int,
        help="Recommendation weeks to include. Default: every week in the clean table.",
    )
    parser.add_argument("--dpi", type=int, default=220)
    return parser.parse_args()


def read_table(path: Path, platform: str) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"{platform} clean table does not exist: {path}")

    df = pd.read_csv(path, encoding="utf-8-sig")
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"{path} is missing required columns: {sorted(missing)}")

    for column in (
        "week_number",
        "user_number",
        "popularity_value",
        "original_candidate_pool_percentile_83",
    ):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["platform"] = platform
    return df


def prepare_platform(
    df: pd.DataFrame,
    requested_weeks: set[int] | None,
) -> tuple[pd.DataFrame, list[int], list[int]]:
    df = df.copy()
    df["_is_baseline"] = (
        df["row_type"].astype(str).str.casefold().eq("final_balanced_baseline")
        | df["week_number"].eq(0)
    )
    df["_log10_plus1"] = np.where(
        df["popularity_value"].ge(0),
        np.log10(df["popularity_value"] + 1),
        np.nan,
    )
    df["_candidate_percentile"] = pd.to_numeric(
        df["original_candidate_pool_percentile_83"], errors="coerce"
    )
    df["_candidate_tier"] = (
        df["original_candidate_pool_rank_tier_83"]
        .astype("string")
        .str.strip()
        .replace({"": pd.NA, "nan": pd.NA})
    )

    baseline = df.loc[df["_is_baseline"] & df["popularity_value"].notna()]
    if baseline.empty:
        raise ValueError("The clean table has no usable final balanced-playlist values.")

    baseline_median = float(baseline["popularity_value"].median())
    baseline_max = float(baseline["popularity_value"].max())
    df["_above_balanced_median"] = df["popularity_value"] > baseline_median
    df["_above_balanced_max"] = df["popularity_value"] > baseline_max
    df["_log10_delta"] = df["_log10_plus1"] - math.log10(baseline_median + 1)

    available_weeks = sorted(
        int(week)
        for week in df.loc[~df["_is_baseline"], "week_number"].dropna().unique()
    )
    if requested_weeks is not None:
        weeks = [week for week in available_weeks if week in requested_weeks]
        missing_weeks = sorted(requested_weeks - set(available_weeks))
        if missing_weeks:
            raise ValueError(
                "Requested recommendation weeks are absent from the clean table: "
                + ", ".join(map(str, missing_weeks))
            )
        df = df.loc[df["_is_baseline"] | df["week_number"].isin(weeks)].copy()
    else:
        weeks = available_weeks

    users = sorted(
        int(user)
        for user in df.loc[~df["_is_baseline"], "user_number"].dropna().unique()
    )
    return df, weeks, users


def safe_median(values: Iterable[float]) -> float:
    clean = pd.Series(values, dtype=float).dropna()
    return float(clean.median()) if len(clean) else np.nan


def geometric_mean_from_log(values: pd.Series) -> float:
    clean = values.dropna()
    return float(10 ** clean.mean() - 1) if len(clean) else np.nan


def bootstrap_mean_ci(
    values: Iterable[float],
    seed: int,
    confidence: float = 0.95,
    samples: int = 5000,
) -> tuple[float, float]:
    clean = pd.Series(values, dtype=float).dropna().to_numpy()
    if not len(clean):
        return np.nan, np.nan
    if len(clean) == 1:
        return float(clean[0]), float(clean[0])
    rng = np.random.default_rng(seed)
    draws = rng.choice(clean, size=(samples, len(clean)), replace=True).mean(axis=1)
    alpha = (1 - confidence) / 2
    return tuple(np.quantile(draws, [alpha, 1 - alpha]).astype(float))


def holm_adjust(p_values: pd.Series) -> pd.Series:
    adjusted = pd.Series(np.nan, index=p_values.index, dtype=float)
    valid = p_values.dropna().sort_values()
    running_max = 0.0
    count = len(valid)
    for rank, (index, value) in enumerate(valid.items()):
        candidate = min(1.0, float(value) * (count - rank))
        running_max = max(running_max, candidate)
        adjusted.loc[index] = running_max
    return adjusted


def rank_biserial_from_differences(values: pd.Series) -> float:
    clean = values.dropna()
    clean = clean.loc[clean.ne(0)]
    if clean.empty:
        return 0.0
    ranks = clean.abs().rank(method="average")
    positive = float(ranks.loc[clean.gt(0)].sum())
    negative = float(ranks.loc[clean.lt(0)].sum())
    return (positive - negative) / (positive + negative)


def summarize_user_weeks(
    df: pd.DataFrame,
    weeks: list[int],
    users: list[int],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    recommendation = df.loc[~df["_is_baseline"]]
    baseline = df.loc[df["_is_baseline"] & df["popularity_value"].notna()]
    baseline_median = float(baseline["popularity_value"].median())

    for week in weeks:
        for user in users:
            all_rows = recommendation.loc[
                recommendation["week_number"].eq(week)
                & recommendation["user_number"].eq(user)
            ]
            valid = all_rows.loc[all_rows["popularity_value"].notna()]
            tiers = valid["_candidate_tier"]
            rows.append(
                {
                    "platform": str(df["platform"].iloc[0]),
                    "week_number": week,
                    "user_number": user,
                    "playlist_song_count": len(all_rows),
                    "valid_popularity_count": len(valid),
                    "missing_popularity_count": len(all_rows) - len(valid),
                    "popularity_coverage": len(valid) / len(all_rows) if len(all_rows) else 0.0,
                    "median_popularity": safe_median(valid["popularity_value"]),
                    "mean_popularity": float(valid["popularity_value"].mean())
                    if len(valid)
                    else np.nan,
                    "geometric_mean_popularity": geometric_mean_from_log(
                        valid["_log10_plus1"]
                    ),
                    "median_log10_plus1": safe_median(valid["_log10_plus1"]),
                    "median_log10_delta_vs_balanced": safe_median(valid["_log10_delta"]),
                    "median_ratio_vs_balanced": (
                        (safe_median(valid["popularity_value"]) + 1)
                        / (baseline_median + 1)
                        if len(valid)
                        else np.nan
                    ),
                    "median_original_pool_percentile": safe_median(
                        valid["_candidate_percentile"]
                    ),
                    "mean_original_pool_percentile": float(
                        valid["_candidate_percentile"].mean()
                    )
                    if len(valid)
                    else np.nan,
                    "share_above_balanced_median": float(
                        valid["_above_balanced_median"].mean()
                    )
                    if len(valid)
                    else np.nan,
                    "share_above_balanced_max": float(valid["_above_balanced_max"].mean())
                    if len(valid)
                    else np.nan,
                    **{
                        f"share_{tier.casefold()}_tier": float((tiers == tier).mean())
                        if len(tiers)
                        else np.nan
                        for tier in TIER_ORDER
                    },
                }
            )
    return pd.DataFrame(rows)


def summarize_weeks(
    df: pd.DataFrame,
    weeks: list[int],
    user_summary: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    baseline = df.loc[df["_is_baseline"]]
    baseline_valid = baseline.loc[baseline["popularity_value"].notna()]
    baseline_median = float(baseline_valid["popularity_value"].median())
    baseline_percentile = safe_median(baseline_valid["_candidate_percentile"])

    groups = [(0, baseline)] + [
        (
            week,
            df.loc[(~df["_is_baseline"]) & df["week_number"].eq(week)],
        )
        for week in weeks
    ]
    for week, all_rows in groups:
        valid = all_rows.loc[all_rows["popularity_value"].notna()]
        tiers = valid["_candidate_tier"]
        if week == 0:
            week_users = pd.DataFrame()
            all_week_users = pd.DataFrame()
            percentile_mean = baseline_percentile
            percentile_ci = (baseline_percentile, baseline_percentile)
            above_mean = 0.5
            above_ci = (0.5, 0.5)
        else:
            all_week_users = user_summary.loc[user_summary["week_number"].eq(week)]
            week_users = all_week_users.loc[
                all_week_users["popularity_coverage"].ge(0.8)
            ]
            percentile_mean = float(
                week_users["median_original_pool_percentile"].mean()
            )
            percentile_ci = bootstrap_mean_ci(
                week_users["median_original_pool_percentile"], 1000 + week
            )
            above_mean = float(week_users["share_above_balanced_median"].mean())
            above_ci = bootstrap_mean_ci(
                week_users["share_above_balanced_median"], 2000 + week
            )

        rows.append(
            {
                "platform": str(df["platform"].iloc[0]),
                "week_number": week,
                "week_label": "Balanced playlist" if week == 0 else f"Week {week}",
                "is_balanced_reference": week == 0,
                "user_playlist_count": 1
                if week == 0
                else int(all_week_users["user_number"].nunique()),
                "user_playlist_count_meeting_coverage": 1
                if week == 0
                else int(week_users["user_number"].nunique()),
                "user_playlist_count_excluded_low_coverage": 0
                if week == 0
                else int(
                    all_week_users["user_number"].nunique()
                    - week_users["user_number"].nunique()
                ),
                "song_count": len(all_rows),
                "valid_popularity_count": len(valid),
                "missing_popularity_count": len(all_rows) - len(valid),
                "popularity_coverage": len(valid) / len(all_rows) if len(all_rows) else 0.0,
                "pooled_median_popularity": safe_median(valid["popularity_value"]),
                "pooled_mean_popularity": float(valid["popularity_value"].mean())
                if len(valid)
                else np.nan,
                "pooled_geometric_mean_popularity": geometric_mean_from_log(
                    valid["_log10_plus1"]
                ),
                "pooled_median_ratio_vs_balanced": (
                    (safe_median(valid["popularity_value"]) + 1) / (baseline_median + 1)
                    if len(valid)
                    else np.nan
                ),
                "pooled_median_original_pool_percentile": safe_median(
                    valid["_candidate_percentile"]
                ),
                "mean_user_median_original_pool_percentile": percentile_mean,
                "mean_user_median_percentile_ci95_low": percentile_ci[0],
                "mean_user_median_percentile_ci95_high": percentile_ci[1],
                "pooled_share_above_balanced_median": float(
                    valid["_above_balanced_median"].mean()
                )
                if len(valid)
                else np.nan,
                "mean_user_share_above_balanced_median": above_mean,
                "mean_user_share_above_median_ci95_low": above_ci[0],
                "mean_user_share_above_median_ci95_high": above_ci[1],
                "pooled_share_above_balanced_max": float(
                    valid["_above_balanced_max"].mean()
                )
                if len(valid)
                else np.nan,
                **{
                    f"pooled_share_{tier.casefold()}_tier": float((tiers == tier).mean())
                    if len(tiers)
                    else np.nan
                    for tier in TIER_ORDER
                },
            }
        )
    return pd.DataFrame(rows)


def bias_tests(user_summary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for week, group in user_summary.groupby("week_number", sort=True):
        included = group.loc[group["popularity_coverage"].ge(0.8)]
        deltas = included["median_log10_delta_vs_balanced"].dropna()
        statistic = np.nan
        p_value = np.nan
        if len(deltas) >= 5 and deltas.ne(0).any():
            try:
                from scipy.stats import wilcoxon

                result = wilcoxon(deltas, alternative="two-sided", method="auto")
                statistic = float(result.statistic)
                p_value = float(result.pvalue)
            except (ImportError, ValueError):
                pass
        ratio_ci = bootstrap_mean_ci(
            included["median_ratio_vs_balanced"], 3000 + int(week)
        )
        rows.append(
            {
                "platform": str(group["platform"].iloc[0]),
                "week_number": int(week),
                "user_playlist_count": len(group),
                "user_playlist_count_in_test": len(included),
                "excluded_low_coverage_user_count": len(group) - len(included),
                "median_user_log10_delta": safe_median(deltas),
                "median_user_popularity_ratio_vs_balanced": safe_median(
                    included["median_ratio_vs_balanced"]
                ),
                "mean_user_popularity_ratio_vs_balanced": float(
                    included["median_ratio_vs_balanced"].mean()
                ),
                "mean_user_ratio_ci95_low": ratio_ci[0],
                "mean_user_ratio_ci95_high": ratio_ci[1],
                "wilcoxon_statistic_two_sided": statistic,
                "wilcoxon_p_value_two_sided": p_value,
                "rank_biserial_effect_size": rank_biserial_from_differences(deltas),
                "direction": "higher popularity"
                if safe_median(deltas) > 0
                else "lower popularity"
                if safe_median(deltas) < 0
                else "no median shift",
            }
        )
    result = pd.DataFrame(rows)
    result["wilcoxon_p_value_holm"] = holm_adjust(
        result["wilcoxon_p_value_two_sided"]
    )
    return result


def ecdf(values: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    clean = np.sort(values.dropna().to_numpy(dtype=float))
    return clean, np.arange(1, len(clean) + 1) / len(clean)


def save_figure(fig: plt.Figure, path: Path, dpi: int) -> None:
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_song_values_by_user_week(
    df: pd.DataFrame,
    weeks: list[int],
    users: list[int],
    config: dict[str, str],
    output_dir: Path,
    dpi: int,
) -> None:
    columns = 2
    rows = math.ceil(len(weeks) / columns)
    fig, axes = plt.subplots(
        rows,
        columns,
        figsize=(14, 4.8 * rows),
        sharey=True,
        constrained_layout=True,
    )
    axes = np.atleast_1d(axes).ravel()
    baseline_values = df.loc[df["_is_baseline"], "_log10_plus1"].dropna()
    rng = np.random.default_rng(42)

    for ax, week in zip(axes, weeks):
        week_data = df.loc[(~df["_is_baseline"]) & df["week_number"].eq(week)]
        groups = [baseline_values] + [
            week_data.loc[week_data["user_number"].eq(user), "_log10_plus1"].dropna()
            for user in users
        ]
        positions = np.arange(len(groups))
        boxes = ax.boxplot(
            groups,
            positions=positions,
            widths=0.62,
            patch_artist=True,
            showfliers=False,
            medianprops={"color": "#111111", "linewidth": 1.4},
            whiskerprops={"color": "#666666", "linewidth": 0.8},
            capprops={"color": "#666666", "linewidth": 0.8},
        )
        boxes["boxes"][0].set_facecolor("#bdbdbd")
        for box in boxes["boxes"][1:]:
            box.set_facecolor(config["color"])
            box.set_alpha(0.45)

        for position, values in zip(positions, groups):
            jitter = rng.uniform(-0.2, 0.2, len(values))
            color = "#4d4d4d" if position == 0 else config["color"]
            ax.scatter(
                position + jitter,
                values,
                s=10,
                color=color,
                alpha=0.48,
                edgecolor="none",
                zorder=3,
            )

        missing = int(week_data["popularity_value"].isna().sum())
        missing_note = f"; {missing} missing" if missing else ""
        ax.set_title(f"Week {week} ({len(week_data) - missing} values{missing_note})")
        ax.set_xlabel("Balanced playlist and user number")
        ax.set_xticks(positions, ["Balanced"] + [str(user) for user in users], rotation=40)
        ax.grid(axis="y", alpha=0.22)

    for ax in axes[len(weeks):]:
        ax.set_visible(False)
    for ax in axes[::columns]:
        ax.set_ylabel(f"log10({config['short_metric']} + 1)")
    fig.suptitle(
        f"{df['platform'].iloc[0]} song popularity by user and recommendation week"
    )
    save_figure(fig, output_dir / "01_song_popularity_by_user_and_week.png", dpi)


def plot_weekly_ecdf(
    df: pd.DataFrame,
    weeks: list[int],
    config: dict[str, str],
    output_dir: Path,
    dpi: int,
) -> None:
    fig, ax = plt.subplots(figsize=(9.5, 6), constrained_layout=True)
    baseline = df.loc[df["_is_baseline"], "_log10_plus1"]
    x, y = ecdf(baseline)
    ax.step(x, y, where="post", color="#333333", linewidth=3, label="Balanced playlist")
    colors = plt.cm.viridis(np.linspace(0.15, 0.85, max(len(weeks), 1)))
    for color, week in zip(colors, weeks):
        values = df.loc[
            (~df["_is_baseline"]) & df["week_number"].eq(week), "_log10_plus1"
        ]
        x, y = ecdf(values)
        if len(x):
            ax.step(x, y, where="post", color=color, linewidth=2, label=f"Week {week}")
    ax.axvline(
        baseline.median(),
        color="#333333",
        linestyle="--",
        linewidth=1.2,
        label="Balanced median",
    )
    ax.set_title(f"{df['platform'].iloc[0]} popularity distributions")
    ax.set_xlabel(f"log10({config['short_metric']} + 1)")
    ax.set_ylabel("Cumulative share of songs")
    ax.set_ylim(0, 1.02)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.grid(alpha=0.22)
    ax.legend(frameon=False, ncol=2)
    save_figure(fig, output_dir / "02_weekly_popularity_ecdf.png", dpi)


def plot_user_trajectories(
    df: pd.DataFrame,
    weeks: list[int],
    users: list[int],
    user_summary: pd.DataFrame,
    output_dir: Path,
    dpi: int,
) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(10.5, 9), sharex=True, constrained_layout=True)
    colors = plt.cm.tab10(np.linspace(0, 1, max(len(users), 1)))
    baseline_percentile = safe_median(
        df.loc[df["_is_baseline"], "_candidate_percentile"]
    )

    for color, user in zip(colors, users):
        data = user_summary.loc[user_summary["user_number"].eq(user)].sort_values(
            "week_number"
        )
        axes[0].plot(
            data["week_number"],
            data["median_original_pool_percentile"],
            marker="o",
            linewidth=1.35,
            color=color,
            alpha=0.88,
            label=f"User {user}",
        )
        axes[1].plot(
            data["week_number"],
            data["share_above_balanced_median"],
            marker="o",
            linewidth=1.35,
            color=color,
            alpha=0.88,
        )
        low_coverage = data.loc[data["popularity_coverage"].lt(0.8)]
        if not low_coverage.empty:
            axes[0].scatter(
                low_coverage["week_number"],
                low_coverage["median_original_pool_percentile"],
                s=85,
                facecolors="none",
                edgecolors=color,
                linewidths=2,
                zorder=5,
            )
            axes[1].scatter(
                low_coverage["week_number"],
                low_coverage["share_above_balanced_median"],
                s=85,
                facecolors="none",
                edgecolors=color,
                linewidths=2,
                zorder=5,
            )

    pooled = user_summary.loc[user_summary["popularity_coverage"].ge(0.8)].groupby(
        "week_number", as_index=False
    ).agg(
        median_percentile=("median_original_pool_percentile", "median"),
        mean_share=("share_above_balanced_median", "mean"),
    )
    axes[0].plot(
        pooled["week_number"],
        pooled["median_percentile"],
        color="#111111",
        marker="D",
        linewidth=3,
        label="Median across users",
        zorder=6,
    )
    axes[1].plot(
        pooled["week_number"],
        pooled["mean_share"],
        color="#111111",
        marker="D",
        linewidth=3,
        zorder=6,
    )
    axes[0].axhline(
        baseline_percentile,
        color="#555555",
        linestyle="--",
        linewidth=1.2,
        label="Balanced-list median",
    )
    axes[1].axhline(0.5, color="#555555", linestyle="--", linewidth=1.2)
    axes[0].set_title("Median popularity percentile for each user playlist")
    axes[0].set_ylabel("Percentile in original 83-song pool")
    axes[0].set_ylim(0, 100)
    axes[0].yaxis.set_major_formatter(PercentFormatter(100))
    axes[1].set_title("Share of songs above the balanced-playlist median")
    axes[1].set_ylabel("Share of songs")
    axes[1].set_xlabel("Recommendation week")
    axes[1].set_ylim(0, 1.02)
    axes[1].yaxis.set_major_formatter(PercentFormatter(1.0))
    axes[1].set_xticks(weeks)
    for ax in axes:
        ax.grid(axis="y", alpha=0.22)
    axes[0].legend(frameon=False, ncol=4, fontsize=8, loc="upper center")
    fig.suptitle(f"{df['platform'].iloc[0]} user-level popularity trajectories")
    save_figure(fig, output_dir / "03_user_popularity_trajectories.png", dpi)


def plot_weekly_summary(
    df: pd.DataFrame,
    weekly_summary: pd.DataFrame,
    config: dict[str, str],
    output_dir: Path,
    dpi: int,
) -> None:
    recommendation = weekly_summary.loc[~weekly_summary["is_balanced_reference"]]
    weeks = recommendation["week_number"].to_numpy()
    baseline_percentile = safe_median(
        df.loc[df["_is_baseline"], "_candidate_percentile"]
    )
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2), constrained_layout=True)

    percentile = recommendation["mean_user_median_original_pool_percentile"].to_numpy()
    percentile_yerr = np.vstack(
        [
            percentile
            - recommendation["mean_user_median_percentile_ci95_low"].to_numpy(),
            recommendation["mean_user_median_percentile_ci95_high"].to_numpy()
            - percentile,
        ]
    )
    axes[0].errorbar(
        weeks,
        percentile,
        yerr=percentile_yerr,
        color=config["color"],
        marker="o",
        linewidth=2.4,
        capsize=5,
    )
    axes[0].axhline(
        baseline_percentile,
        color="#555555",
        linestyle="--",
        linewidth=1.2,
        label=f"Balanced median ({baseline_percentile:.1f})",
    )
    axes[0].set_title("Mean user-playlist median percentile")
    axes[0].set_ylabel("Percentile in original 83-song pool")
    axes[0].set_ylim(0, 100)
    axes[0].yaxis.set_major_formatter(PercentFormatter(100))

    above = recommendation["mean_user_share_above_balanced_median"].to_numpy()
    above_yerr = np.vstack(
        [
            above - recommendation["mean_user_share_above_median_ci95_low"].to_numpy(),
            recommendation["mean_user_share_above_median_ci95_high"].to_numpy() - above,
        ]
    )
    axes[1].errorbar(
        weeks,
        above,
        yerr=above_yerr,
        color=config["color"],
        marker="o",
        linewidth=2.4,
        capsize=5,
    )
    axes[1].axhline(
        0.5,
        color="#555555",
        linestyle="--",
        linewidth=1.2,
        label="Balanced reference (50%)",
    )
    axes[1].set_title("Mean share above balanced median")
    axes[1].set_ylabel("Share of songs")
    axes[1].set_ylim(0, 1.02)
    axes[1].yaxis.set_major_formatter(PercentFormatter(1.0))

    for ax in axes:
        ax.set_xlabel("Recommendation week")
        ax.set_xticks(weeks)
        ax.grid(axis="y", alpha=0.22)
        ax.legend(frameon=False)
    fig.suptitle(
        f"{df['platform'].iloc[0]} weekly popularity-bias estimates (95% bootstrap CI)"
    )
    save_figure(fig, output_dir / "04_weekly_bias_summary.png", dpi)


def plot_tier_composition(
    df: pd.DataFrame,
    weekly_summary: pd.DataFrame,
    output_dir: Path,
    dpi: int,
) -> None:
    data = weekly_summary.sort_values("week_number")
    x = np.arange(len(data))
    fig, ax = plt.subplots(figsize=(9.5, 6), constrained_layout=True)
    bottom = np.zeros(len(data))
    for tier in TIER_ORDER:
        values = data[f"pooled_share_{tier.casefold()}_tier"].fillna(0).to_numpy()
        ax.bar(
            x,
            values,
            bottom=bottom,
            color=TIER_COLORS[tier],
            label=tier,
            width=0.68,
        )
        bottom += values

    for position, (_, row) in enumerate(data.iterrows()):
        label = f"n={int(row['valid_popularity_count'])}"
        if row["missing_popularity_count"]:
            label += f"/{int(row['song_count'])}"
        ax.text(position, min(bottom[position] + 0.025, 1.04), label, ha="center", fontsize=8)
    ax.set_title(
        f"{df['platform'].iloc[0]} popularity tiers using the original 83-song pool"
    )
    ax.set_ylabel("Share of songs with a popularity value")
    ax.set_ylim(0, 1.08)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_xticks(x, data["week_label"])
    ax.grid(axis="y", alpha=0.2)
    ax.legend(title="Original-pool tier", frameon=False, ncol=4)
    save_figure(fig, output_dir / "05_original_pool_tier_composition.png", dpi)


def plot_user_heatmap(
    df: pd.DataFrame,
    weeks: list[int],
    users: list[int],
    user_summary: pd.DataFrame,
    output_dir: Path,
    dpi: int,
) -> None:
    values = user_summary.pivot(
        index="user_number",
        columns="week_number",
        values="median_original_pool_percentile",
    ).reindex(index=users, columns=weeks)
    coverage = user_summary.pivot(
        index="user_number",
        columns="week_number",
        values="popularity_coverage",
    ).reindex(index=users, columns=weeks)
    fig, ax = plt.subplots(figsize=(8.5, 7), constrained_layout=True)
    image = ax.imshow(values.to_numpy(dtype=float), cmap="RdYlBu_r", vmin=0, vmax=100, aspect="auto")
    baseline_percentile = safe_median(
        df.loc[df["_is_baseline"], "_candidate_percentile"]
    )
    for row in range(values.shape[0]):
        for column in range(values.shape[1]):
            value = values.iloc[row, column]
            if pd.notna(value):
                suffix = "*" if coverage.iloc[row, column] < 0.8 else ""
                ax.text(column, row, f"{value:.0f}{suffix}", ha="center", va="center", fontsize=9)
    ax.set_title(
        f"{df['platform'].iloc[0]} median original-pool percentile by user and week"
    )
    ax.set_xlabel("Recommendation week")
    ax.set_ylabel("User")
    ax.set_xticks(np.arange(len(weeks)), [str(week) for week in weeks])
    ax.set_yticks(np.arange(len(users)), [str(user) for user in users])
    colorbar = fig.colorbar(image, ax=ax, shrink=0.9)
    colorbar.set_label("Median percentile in original 83-song pool")
    ax.text(
        0,
        -0.1,
        f"Balanced-playlist median: {baseline_percentile:.1f}. * Less than 80% popularity coverage.",
        transform=ax.transAxes,
        fontsize=9,
        va="top",
    )
    save_figure(fig, output_dir / "06_user_week_percentile_heatmap.png", dpi)


def render_platform(
    platform: str,
    args: argparse.Namespace,
    requested_weeks: set[int] | None,
) -> None:
    config = PLATFORM_CONFIG[platform]
    df = read_table(args.input_dir / config["filename"], platform)
    df, weeks, users = prepare_platform(df, requested_weeks)
    if not weeks:
        raise ValueError(f"No recommendation weeks are available for {platform}.")
    if users != list(range(1, 11)):
        print(f"Warning: {platform} users found in clean data: {users}; expected 1-10.")

    output_dir = args.output_dir / config["slug"]
    output_dir.mkdir(parents=True, exist_ok=True)
    user_summary = summarize_user_weeks(df, weeks, users)
    weekly_summary = summarize_weeks(df, weeks, user_summary)
    tests = bias_tests(user_summary)

    weekly_summary.to_csv(output_dir / "weekly_popularity_summary.csv", index=False)
    user_summary.to_csv(output_dir / "user_week_popularity_summary.csv", index=False)
    tests.to_csv(output_dir / "popularity_bias_tests.csv", index=False)

    plot_song_values_by_user_week(df, weeks, users, config, output_dir, args.dpi)
    plot_weekly_ecdf(df, weeks, config, output_dir, args.dpi)
    plot_user_trajectories(df, weeks, users, user_summary, output_dir, args.dpi)
    plot_weekly_summary(df, weekly_summary, config, output_dir, args.dpi)
    plot_tier_composition(df, weekly_summary, output_dir, args.dpi)
    plot_user_heatmap(df, weeks, users, user_summary, output_dir, args.dpi)

    print(f"\n{platform}: wrote plots and tables to {output_dir}")
    print(
        weekly_summary[
            [
                "week_label",
                "valid_popularity_count",
                "missing_popularity_count",
                "pooled_median_ratio_vs_balanced",
                "pooled_median_original_pool_percentile",
                "pooled_share_above_balanced_median",
            ]
        ].to_string(index=False)
    )


def main() -> None:
    args = parse_args()
    platforms = args.platform or list(PLATFORM_CONFIG)
    requested_weeks = set(args.weeks) if args.weeks is not None else None
    for platform in platforms:
        render_platform(platform, args, requested_weeks)


if __name__ == "__main__":
    main()
