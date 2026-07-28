from __future__ import annotations

import csv
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest


YOUTUBE_MUSIC_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(YOUTUBE_MUSIC_DIR))

import fetch_discover_mix_snapshot as snapshot  # noqa: E402


class OutputPathTests(unittest.TestCase):
    def test_positional_week_and_experiment_folder_use_new_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(
                output=None,
                output_root=Path(directory),
                profile="user_02",
                user_folder=None,
                week_x="2",
                week="",
                week_label="",
                experiment_folder="Week2_28July",
                experiment_folder_flag="",
                week_folder="Week1_21July",
                date_label="",
                platform_folder="Youtube",
            )
            self.assertEqual(
                snapshot.output_path(args),
                Path(directory).resolve()
                / "Week2_28July"
                / "Youtube"
                / "User2"
                / "Week2_User2_28.07.csv",
            )

    def test_flag_week_and_experiment_folder_use_new_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(
                output=None,
                output_root=Path(directory),
                profile="user_10",
                user_folder=None,
                week_x=None,
                week="3",
                week_label="",
                experiment_folder=None,
                experiment_folder_flag="Week3_04August",
                week_folder="Week1_21July",
                date_label="",
                platform_folder="Youtube",
            )
            self.assertEqual(
                snapshot.output_path(args),
                Path(directory).resolve()
                / "Week3_04August"
                / "Youtube"
                / "User10"
                / "Week3_User10_04.08.csv",
            )


class OriginalPoolBandTests(unittest.TestCase):
    def test_all_fixed_band_boundaries(self) -> None:
        cases = {
            0: ("Low", "Low"),
            7_505: ("Low", "Low"),
            7_506: ("Lower buffer", "Buffer"),
            19_756: ("Lower buffer", "Buffer"),
            19_757: ("Middle", "Middle"),
            243_792: ("Middle", "Middle"),
            243_793: ("Upper buffer", "Buffer"),
            1_223_809: ("Upper buffer", "Buffer"),
            1_223_810: ("High", "High"),
            500_000_000: ("High", "High"),
        }
        for views, expected in cases.items():
            with self.subTest(views=views):
                self.assertEqual(snapshot.original_pool_popularity_band(views), expected)

    def test_negative_views_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            snapshot.original_pool_popularity_band(-1)


class PopularityMetricTests(unittest.TestCase):
    def test_analysis_fields_use_exact_views_and_log10(self) -> None:
        row = {"view_count": 100_000, "video_type": "MUSIC_VIDEO_TYPE_ATV"}
        snapshot.add_popularity_fields(row)
        self.assertEqual(row["popularity_value_view_count"], 100_000)
        self.assertAlmostEqual(row["popularity_log10_view_count"], 5.0)
        self.assertEqual(row["popularity_original_pool_fixed_band"], "Middle")
        self.assertEqual(row["popularity_original_pool_fixed_tier"], "Middle")
        self.assertIn("Do not use", row["popularity_comparison_note"])
        self.assertIn("ATV", row["popularity_video_version_note"])

    def test_missing_views_are_explicit(self) -> None:
        row = {"view_count": "", "video_type": ""}
        snapshot.add_popularity_fields(row)
        self.assertEqual(row["popularity_value_view_count"], "")
        self.assertEqual(row["popularity_log10_view_count"], "")
        self.assertEqual(row["popularity_original_pool_fixed_band"], "Missing")
        self.assertEqual(row["popularity_original_pool_fixed_tier"], "Missing")

    def test_local_ranks_handle_ties_but_fixed_tiers_use_raw_views(self) -> None:
        rows = [
            {"view_count": 100, "video_type": "MUSIC_VIDEO_TYPE_ATV"},
            {"view_count": 100, "video_type": "MUSIC_VIDEO_TYPE_OMV"},
            {"view_count": 1_223_810, "video_type": "MUSIC_VIDEO_TYPE_ATV"},
        ]
        snapshot.add_view_metrics(rows)
        self.assertEqual(rows[0]["view_rank_within_discover_mix_desc"], 2.5)
        self.assertEqual(rows[1]["view_rank_within_discover_mix_desc"], 2.5)
        self.assertAlmostEqual(rows[0]["log10_view_count"], math.log10(100))
        self.assertEqual(rows[0]["popularity_original_pool_fixed_tier"], "Low")
        self.assertEqual(rows[2]["popularity_original_pool_fixed_tier"], "High")


class CsvSafetyTests(unittest.TestCase):
    def test_csv_contains_analysis_fields_and_no_credentials(self) -> None:
        row = {"video_id": "abc", "view_count": 20_000, "video_type": "MUSIC_VIDEO_TYPE_ATV"}
        snapshot.add_view_metrics([row])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.csv"
            snapshot.write_csv(path, [row])
            with path.open(encoding="utf-8-sig", newline="") as handle:
                saved = next(csv.DictReader(handle))
        self.assertEqual(saved["popularity_value_view_count"], "20000")
        self.assertEqual(saved["popularity_original_pool_fixed_tier"], "Middle")
        self.assertFalse(any(term in key.casefold() for key in saved for term in ("cookie", "authorization", "token")))

    def test_credential_like_columns_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.csv"
            with self.assertRaises(ValueError):
                snapshot.write_csv(path, [{"view_count": 1, "authorization": "secret"}])
            self.assertFalse(path.exists())

    def test_empty_results_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.csv"
            with self.assertRaises(ValueError):
                snapshot.write_csv(path, [])
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
