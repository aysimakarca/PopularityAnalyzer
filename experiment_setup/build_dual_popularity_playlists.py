"""Build rank-based and magnitude-based cross-platform research playlists.

Rank tiers use the existing buffered percentile definition. Magnitude tiers are
optimal contiguous three-cluster partitions of log10(popularity + 1), with at
least ten observations in each cluster. The clustering objective minimizes
weighted within-cluster squared error and never splits tied raw values.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from select_balanced_playlist import TIERS


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
# Closest feasible allocation to the preregistered diagonal/adjacent design
# that also permits exact 5/5 heavy/power balance in every marginal platform
# tier under both popularity definitions.
COMMON_ALLOCATION = [[9, 1, 0], [1, 7, 2], [0, 2, 8]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spotify",
        type=Path,
        default=ROOT / "spotify" / "spotify_popularity_results.csv",
    )
    parser.add_argument(
        "--youtube",
        type=Path,
        default=ROOT / "youtube_music" / "youtube_popularity_results.csv",
    )
    parser.add_argument("--min-cluster-size", type=int, default=10)
    parser.add_argument("--max-per-country", type=int, default=2)
    parser.add_argument(
        "--rank-output", type=Path, default=HERE / "final_rank_based_playlist.csv"
    )
    parser.add_argument(
        "--magnitude-output",
        type=Path,
        default=HERE / "final_magnitude_based_playlist.csv",
    )
    parser.add_argument(
        "--spotify-evaluation",
        type=Path,
        default=ROOT / "spotify" / "spotify_dual_popularity_results.csv",
    )
    parser.add_argument(
        "--youtube-evaluation",
        type=Path,
        default=ROOT / "youtube_music" / "youtube_dual_popularity_results.csv",
    )
    return parser.parse_args()


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def optimal_log_clusters(
    rows: list[dict[str, str]], value_field: str, min_size: int
) -> tuple[dict[str, dict[str, float | str]], list[dict[str, float | int | str]]]:
    """Return exact minimum-SSE clusters for grouped, sorted log values."""
    grouped: dict[int, list[str]] = {}
    for row in rows:
        value = int(row[value_field])
        grouped.setdefault(value, []).append(row["candidate_id"])

    values = sorted(grouped)
    logs = [math.log10(value + 1) for value in values]
    weights = [len(grouped[value]) for value in values]
    m = len(values)

    prefix_w = [0]
    prefix_wx = [0.0]
    prefix_wx2 = [0.0]
    for weight, log_value in zip(weights, logs):
        prefix_w.append(prefix_w[-1] + weight)
        prefix_wx.append(prefix_wx[-1] + weight * log_value)
        prefix_wx2.append(prefix_wx2[-1] + weight * log_value * log_value)

    def size(start: int, end: int) -> int:
        return prefix_w[end] - prefix_w[start]

    def sse(start: int, end: int) -> float:
        weight = size(start, end)
        total = prefix_wx[end] - prefix_wx[start]
        squares = prefix_wx2[end] - prefix_wx2[start]
        return squares - total * total / weight

    k = 3
    infinity = float("inf")
    dp = [[infinity] * (m + 1) for _ in range(k + 1)]
    previous: list[list[int | None]] = [[None] * (m + 1) for _ in range(k + 1)]
    dp[0][0] = 0.0

    for cluster_count in range(1, k + 1):
        for end in range(1, m + 1):
            if prefix_w[end] < cluster_count * min_size:
                continue
            for start in range(cluster_count - 1, end):
                if dp[cluster_count - 1][start] == infinity:
                    continue
                if size(start, end) < min_size:
                    continue
                score = dp[cluster_count - 1][start] + sse(start, end)
                if score < dp[cluster_count][end]:
                    dp[cluster_count][end] = score
                    previous[cluster_count][end] = start

    if previous[k][m] is None:
        raise RuntimeError(
            f"Cannot form three magnitude clusters with minimum size {min_size}"
        )

    partitions: list[tuple[int, int]] = []
    end = m
    for cluster_count in range(k, 0, -1):
        start = previous[cluster_count][end]
        assert start is not None
        partitions.append((start, end))
        end = start
    partitions.reverse()

    assignments: dict[str, dict[str, float | str]] = {}
    summaries: list[dict[str, float | int | str]] = []
    for tier_name, (start, end) in zip(TIERS, partitions):
        cluster_weight = size(start, end)
        center = (prefix_wx[end] - prefix_wx[start]) / cluster_weight
        for value in values[start:end]:
            log_value = math.log10(value + 1)
            for candidate_id in grouped[value]:
                assignments[candidate_id] = {
                    "log10_popularity": log_value,
                    "magnitude_tier": tier_name,
                    "magnitude_cluster_center": center,
                    "magnitude_distance_to_center": abs(log_value - center),
                }
        summaries.append(
            {
                "tier": tier_name,
                "count": cluster_weight,
                "raw_min": values[start],
                "raw_max": values[end - 1],
                "log_center": center,
            }
        )
    return assignments, summaries


def enrich(
    rows: list[dict[str, str]], assignments: dict[str, dict[str, float | str]], prefix: str
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        values = assignments[row["candidate_id"]]
        enriched.append(
            {
                **row,
                f"{prefix}_log10_popularity": f'{values["log10_popularity"]:.6f}',
                f"{prefix}_magnitude_tier": values["magnitude_tier"],
                f"{prefix}_magnitude_cluster_center": (
                    f'{values["magnitude_cluster_center"]:.6f}'
                ),
                f"{prefix}_magnitude_distance_to_center": (
                    f'{values["magnitude_distance_to_center"]:.6f}'
                ),
            }
        )
    return enriched


def selection_distance(row: dict[str, Any], method: str) -> float:
    if method == "rank":
        centers = {"Low": 10.0, "Middle": 50.0, "High": 90.0}
        return abs(float(row["spotify_percentile"]) - centers[row["spotify_selected_tier"]]) + abs(
            float(row["youtube_percentile"]) - centers[row["youtube_selected_tier"]]
        )
    return float(row["spotify_magnitude_distance_to_center"]) + float(
        row["youtube_magnitude_distance_to_center"]
    )


def select_playlist(
    spotify: list[dict[str, Any]],
    youtube: list[dict[str, Any]],
    method: str,
    max_per_country: int,
) -> tuple[list[dict[str, Any]], list[list[int]]]:
    sp_index = {row["candidate_id"]: row for row in spotify}
    yt_index = {row["candidate_id"]: row for row in youtube}
    cells: list[list[list[dict[str, Any]]]] = [[[] for _ in TIERS] for _ in TIERS]

    for candidate_id in sorted(set(sp_index) & set(yt_index)):
        sp = sp_index[candidate_id]
        yt = yt_index[candidate_id]
        if sp.get("validation_status") != "OK" or yt.get("validation_status") != "OK":
            continue
        sp_tier = sp["spotify_tier"] if method == "rank" else sp["spotify_magnitude_tier"]
        yt_tier = yt["youtube_tier"] if method == "rank" else yt["youtube_magnitude_tier"]
        if sp_tier not in TIERS or yt_tier not in TIERS:
            continue
        row = {**yt, **sp}
        # Restore YouTube fields overwritten by the Spotify-first merge.
        for field in (
            "youtube_video_id", "youtube_url", "view_count", "youtube_percentile",
            "youtube_tier", "youtube_log10_popularity", "youtube_magnitude_tier",
            "youtube_magnitude_cluster_center", "youtube_magnitude_distance_to_center",
        ):
            row[field] = yt.get(field, "")
        row["spotify_rank_tier"] = sp["spotify_tier"]
        row["youtube_rank_tier"] = yt["youtube_tier"]
        row["spotify_selected_tier"] = sp_tier
        row["youtube_selected_tier"] = yt_tier
        row["selection_method"] = method
        row["selection_note"] = ""
        cells[TIERS.index(sp_tier)][TIERS.index(yt_tier)].append(row)

    available = [[len(cells[row][col]) for col in range(3)] for row in range(3)]
    allocation = [row[:] for row in COMMON_ALLOCATION]
    if any(
        allocation[row][col] > available[row][col]
        for row in range(3)
        for col in range(3)
    ):
        raise RuntimeError(
            f"The common cross-platform allocation is unavailable for {method}; cells={available}"
        )

    candidates = [candidate for row in cells for cell in row for candidate in cell]
    constraints: list[list[float]] = []
    lower: list[float] = []
    upper: list[float] = []

    def add_constraint(predicate: Any, minimum: float, maximum: float) -> None:
        constraints.append([1.0 if predicate(candidate) else 0.0 for candidate in candidates])
        lower.append(minimum)
        upper.append(maximum)

    # Preserve the same cross-platform design in both playlist variants.
    for row_index, spotify_tier in enumerate(TIERS):
        for col_index, youtube_tier in enumerate(TIERS):
            required = allocation[row_index][col_index]
            add_constraint(
                lambda candidate, sp=spotify_tier, yt=youtube_tier: (
                    candidate["spotify_selected_tier"] == sp
                    and candidate["youtube_selected_tier"] == yt
                ),
                required,
                required,
            )

    # Keep genre exactly balanced inside every platform-specific tier.
    styles = sorted({candidate["style"] for candidate in candidates})
    if styles != ["heavy metal", "power metal"]:
        raise RuntimeError(f"Unexpected style labels: {styles}")
    for platform_field in ("spotify_selected_tier", "youtube_selected_tier"):
        for tier_name in TIERS:
            for style in styles:
                add_constraint(
                    lambda candidate, field=platform_field, tier=tier_name, style=style: (
                        candidate[field] == tier and candidate["style"] == style
                    ),
                    5,
                    5,
                )

    for country in sorted({candidate["country"] for candidate in candidates}):
        add_constraint(
            lambda candidate, country=country: candidate["country"] == country,
            0,
            max_per_country,
        )

    # A tiny ID-based term makes otherwise equal solutions deterministic.
    objective = np.array(
        [
            selection_distance(candidate, method) + index * 1e-9
            for index, candidate in enumerate(candidates)
        ]
    )
    result = milp(
        objective,
        integrality=np.ones(len(candidates)),
        bounds=Bounds(0, 1),
        constraints=LinearConstraint(
            np.array(constraints), np.array(lower), np.array(upper)
        ),
    )
    if not result.success:
        raise RuntimeError(f"No optimized {method} selection: {result.message}")

    selected = [
        candidate for candidate, chosen in zip(candidates, result.x) if chosen > 0.5
    ]
    selected.sort(
        key=lambda row: (
            TIERS.index(row["spotify_selected_tier"]),
            TIERS.index(row["youtube_selected_tier"]),
            selection_distance(row, method),
            row["candidate_id"],
        )
    )

    if len(selected) != 30 or len({row["candidate_id"] for row in selected}) != 30:
        raise RuntimeError(f"Invalid {method} selection size or duplicate candidate")
    return selected, allocation


OUTPUT_FIELDS = [
    "candidate_id", "artist", "title", "country", "expected_year", "style",
    "spotify_track_id", "spotify_url", "spotify_isrc", "spotify_metric",
    "spotify_metric_value", "artist_monthly_listeners",
    "artist_monthly_listeners_captured_at", "spotify_percentile", "spotify_rank_tier",
    "spotify_log10_popularity", "spotify_magnitude_tier",
    "spotify_magnitude_cluster_center", "youtube_video_id", "youtube_url", "view_count",
    "captured_at_utc", "youtube_percentile", "youtube_rank_tier",
    "youtube_log10_popularity", "youtube_magnitude_tier",
    "youtube_magnitude_cluster_center", "spotify_selected_tier", "youtube_selected_tier",
    "selection_method", "selection_note",
]


def print_summary(platform: str, summaries: list[dict[str, float | int | str]]) -> None:
    print(f"{platform} magnitude clusters:")
    for summary in summaries:
        print(
            f"  {summary['tier']:6} n={summary['count']:2} "
            f"raw={summary['raw_min']:,}..{summary['raw_max']:,} "
            f"log-center={summary['log_center']:.3f}"
        )


def main() -> int:
    args = parse_args()
    spotify = read_rows(args.spotify)
    youtube = read_rows(args.youtube)
    if {row["candidate_id"] for row in spotify} != {row["candidate_id"] for row in youtube}:
        raise RuntimeError("Spotify and YouTube candidate IDs do not match")

    spotify_assignments, spotify_summary = optimal_log_clusters(
        spotify, "spotify_metric_value", args.min_cluster_size
    )
    youtube_assignments, youtube_summary = optimal_log_clusters(
        youtube, "view_count", args.min_cluster_size
    )
    spotify_enriched = enrich(spotify, spotify_assignments, "spotify")
    youtube_enriched = enrich(youtube, youtube_assignments, "youtube")
    write_rows(args.spotify_evaluation, spotify_enriched)
    write_rows(args.youtube_evaluation, youtube_enriched)

    rank_rows, rank_allocation = select_playlist(
        spotify_enriched, youtube_enriched, "rank", args.max_per_country
    )
    magnitude_rows, magnitude_allocation = select_playlist(
        spotify_enriched, youtube_enriched, "magnitude", args.max_per_country
    )
    write_rows(args.rank_output, rank_rows, OUTPUT_FIELDS)
    write_rows(args.magnitude_output, magnitude_rows, OUTPUT_FIELDS)

    print_summary("Spotify", spotify_summary)
    print_summary("YouTube", youtube_summary)
    print(f"Rank allocation: {rank_allocation}")
    print(f"Magnitude allocation: {magnitude_allocation}")
    print(f"Rank playlist: {args.rank_output}")
    print(f"Magnitude playlist: {args.magnitude_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
