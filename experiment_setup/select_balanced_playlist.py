"""Write the realized 30-song playlist with balanced platform tiers.

By default, the song IDs and order come from the Week 1 Spotify snapshot of the
Heavy Metal MCT playlist that was actually installed on the experiment users.
Popularity measurements and tiers come from the frozen platform result files.
Use ``--ignore-realized-playlist`` only to reproduce the earlier algorithmic
selection instead of the experimental treatment.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TIERS = ("Low", "Middle", "High")
PREFERRED = tuple(tuple(6 if row == col else 2 for col in range(3)) for row in range(3))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spotify", type=Path, default=ROOT / "spotify" / "spotify_popularity_results.csv"
    )
    parser.add_argument(
        "--youtube", type=Path, default=ROOT / "youtube_music" / "youtube_popularity_results.csv"
    )
    parser.add_argument("--output", type=Path, default=HERE / "final_balanced_playlist.csv")
    parser.add_argument("--max-per-country", type=int, default=2)
    parser.add_argument(
        "--realized-playlist",
        type=Path,
        default=ROOT / "experiment_results" / "Week1_21July" / "Spotify"
        / "original_playlist_popularity.csv",
        help="Snapshot containing the candidate IDs and order actually used in Heavy Metal MCT.",
    )
    parser.add_argument(
        "--ignore-realized-playlist",
        action="store_true",
        help="Re-run the original allocation algorithm instead of using the realized playlist.",
    )
    return parser.parse_args()


def read_index(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["candidate_id"]: row for row in csv.DictReader(handle)}


def feasible_allocation(available: list[list[int]]) -> list[list[int]] | None:
    """Enumerate all 3x3 tables with row/column totals ten."""
    best: tuple[int, int, list[list[int]]] | None = None
    for a in range(11):
        for b in range(11 - a):
            c = 10 - a - b
            for d in range(11):
                for e in range(11 - d):
                    f = 10 - d - e
                    g = 10 - a - d
                    h = 10 - b - e
                    i = 10 - g - h
                    matrix = [[a, b, c], [d, e, f], [g, h, i]]
                    if any(value < 0 for row in matrix for value in row):
                        continue
                    if any(matrix[row][col] > available[row][col] for row in range(3) for col in range(3)):
                        continue
                    distance = sum(
                        (matrix[row][col] - PREFERRED[row][col]) ** 2
                        for row in range(3)
                        for col in range(3)
                    )
                    # On equal distance, prefer more platform-concordant tracks.
                    diagonal = sum(matrix[index][index] for index in range(3))
                    candidate = (distance, -diagonal, matrix)
                    if best is None or candidate[:2] < best[:2]:
                        best = candidate
    return best[2] if best else None


def percentile_distance(row: dict[str, Any]) -> float:
    centers = {"Low": 10.0, "Middle": 50.0, "High": 90.0}
    return abs(float(row["spotify_percentile"]) - centers[row["spotify_tier"]]) + abs(
        float(row["youtube_percentile"]) - centers[row["youtube_tier"]]
    )


def select_rows(
    cells: list[list[list[dict[str, Any]]]],
    allocation: list[list[int]],
    max_per_country: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    country_counts: Counter[str] = Counter()
    tasks = sorted(
        ((len(cells[row][col]), row, col) for row in range(3) for col in range(3)),
        key=lambda item: item[0],
    )
    for _, row_index, col_index in tasks:
        needed = allocation[row_index][col_index]
        candidates = sorted(cells[row_index][col_index], key=percentile_distance)
        chosen: list[dict[str, Any]] = []
        for candidate in candidates:
            country = candidate["country"]
            if country_counts[country] >= max_per_country:
                continue
            chosen.append(candidate)
            country_counts[country] += 1
            if len(chosen) == needed:
                break
        # If the country cap makes the exact table impossible, fill the cell
        # and make the relaxation visible in the output rather than failing.
        if len(chosen) < needed:
            chosen_ids = {item["candidate_id"] for item in chosen}
            for candidate in candidates:
                if candidate["candidate_id"] in chosen_ids:
                    continue
                candidate["selection_note"] = "country cap relaxed"
                chosen.append(candidate)
                country_counts[candidate["country"]] += 1
                if len(chosen) == needed:
                    break
        selected.extend(chosen)
    return selected


def write_output(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "candidate_id", "artist", "title", "country", "expected_year", "style",
        "spotify_track_id", "spotify_url", "spotify_isrc", "spotify_metric",
        "spotify_metric_value", "artist_monthly_listeners",
        "artist_monthly_listeners_captured_at", "stream_count",
        "spotify_percentile", "spotify_tier", "youtube_video_id", "youtube_url",
        "view_count", "youtube_percentile", "youtube_tier", "selection_note",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def realized_candidate_ids(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = sorted(csv.DictReader(handle), key=lambda row: int(row["playlist_position"]))
    candidate_ids = [row["candidate_id"] for row in rows]
    if len(candidate_ids) != 30 or len(set(candidate_ids)) != 30:
        raise ValueError(f"Realized playlist must contain 30 unique candidate IDs: {path}")
    return candidate_ids


def main() -> int:
    args = parse_args()
    spotify = read_index(args.spotify)
    youtube = read_index(args.youtube)
    common_ids = sorted(set(spotify) & set(youtube))
    cells: list[list[list[dict[str, Any]]]] = [[[] for _ in TIERS] for _ in TIERS]
    rows_by_id: dict[str, dict[str, Any]] = {}

    missing_spotify = 0
    for candidate_id in common_ids:
        sp = spotify[candidate_id]
        yt = youtube[candidate_id]
        if sp.get("spotify_tier") == "Missing":
            missing_spotify += 1
            continue
        if sp.get("validation_status") != "OK" or yt.get("validation_status") != "OK":
            continue
        if sp.get("spotify_tier") not in TIERS or yt.get("youtube_tier") not in TIERS:
            continue
        row = {**yt, **sp}
        row["youtube_video_id"] = yt.get("youtube_video_id", "")
        row["youtube_url"] = yt.get("youtube_url", "")
        row["view_count"] = yt.get("view_count", "")
        row["youtube_percentile"] = yt.get("youtube_percentile", "")
        row["youtube_tier"] = yt.get("youtube_tier", "")
        row["selection_note"] = ""
        rows_by_id[candidate_id] = row
        cells[TIERS.index(sp["spotify_tier"])][TIERS.index(yt["youtube_tier"])].append(row)

    if missing_spotify:
        print(f"Cannot select yet: {missing_spotify} candidates have no Spotify tier.")
        print("Run the Spotify popularity collector:")
        print("  python3 spotify/metal_popularity.py --refresh-listeners")
        return 2

    if not args.ignore_realized_playlist:
        realized_ids = realized_candidate_ids(args.realized_playlist)
        missing = [candidate_id for candidate_id in realized_ids if candidate_id not in rows_by_id]
        if missing:
            raise ValueError(
                "Realized playlist candidates are missing valid frozen metadata: "
                + ", ".join(missing)
            )
        selected = [dict(rows_by_id[candidate_id]) for candidate_id in realized_ids]
        replacement_notes = {
            "M076": "Realized Heavy Metal MCT track; replaces planned M055 Traveler - Starbreaker.",
            "M034": "Realized Heavy Metal MCT track; replaces planned M041 Firewind - World on Fire.",
        }
        for row in selected:
            row["selection_note"] = replacement_notes.get(row["candidate_id"], "")
        spotify_counts = Counter(row["spotify_tier"] for row in selected)
        youtube_counts = Counter(row["youtube_tier"] for row in selected)
        expected = Counter({tier: 10 for tier in TIERS})
        if spotify_counts != expected or youtube_counts != expected:
            raise ValueError(
                f"Realized playlist is not tier-balanced: Spotify={spotify_counts}, "
                f"YouTube={youtube_counts}"
            )
        write_output(args.output, selected)
        print(f"Used realized playlist order from: {args.realized_playlist}")
        print(f"Countries represented: {len({row['country'] for row in selected})}")
        print(f"Output: {args.output}")
        return 0

    available = [[len(cells[row][col]) for col in range(3)] for row in range(3)]
    allocation = feasible_allocation(available)
    if allocation is None:
        print("No 30-song table with ten songs per tier on both platforms is feasible.")
        print("Available cell counts (Spotify rows x YouTube columns):")
        for tier_name, row in zip(TIERS, available):
            print(f"  {tier_name:6}: {row}")
        return 3

    selected = select_rows(cells, allocation, args.max_per_country)
    write_output(args.output, selected)
    print("Selected allocation (Spotify rows x YouTube columns):")
    for tier_name, row in zip(TIERS, allocation):
        print(f"  {tier_name:6}: {row}")
    print(f"Countries represented: {len({row['country'] for row in selected})}")
    print(f"Output: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
