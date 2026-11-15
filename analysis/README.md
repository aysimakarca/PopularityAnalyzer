# Popularity Bias Plots

## Recommended songs compared with the balanced playlist

Run the complete platform-specific analysis with:

```bash
python3 analysis/plot_recommended_popularity.py
```

The script reads the two clean song tables in:

```text
analysis_results/popularity_bias/clean_platform_tables/
```

It discovers every recommendation week in those tables and always uses the
30-song final balanced playlist as the reference. To select weeks or one
platform explicitly:

```bash
python3 analysis/plot_recommended_popularity.py --weeks 3 4 5 6
python3 analysis/plot_recommended_popularity.py --platform Spotify
python3 analysis/plot_recommended_popularity.py --platform YouTube
```

Outputs are kept separate by platform:

```text
analysis_results/popularity_bias/platform_popularity_plots/spotify/
analysis_results/popularity_bias/platform_popularity_plots/youtube/
```

Each platform folder contains six figures:

- `01_song_popularity_by_user_and_week.png`: all song values for the balanced
  list and Users 1-10, shown separately for each recommendation week. The raw
  platform metric uses `log10(value + 1)` because popularity is highly skewed.
- `02_weekly_popularity_ecdf.png`: pooled song-popularity distributions for the
  balanced list and every recommendation week. Tick labels show raw counts on
  a logarithmic axis; the dashed line is the transformed raw baseline median.
- `03_user_popularity_trajectories.png`: all ten users' weekly median
  original-pool percentiles and shares above the balanced-list median.
- `04_weekly_bias_summary.png`: means across the ten user playlists with 95%
  bootstrap confidence intervals.
- `05_original_pool_tier_composition.png`: Low, Lower Buffer, Middle, Upper Buffer,
  and High shares using the frozen 83-recording calibration. Lower Buffer covers
  percentiles strictly between 25 and 37.5; Upper Buffer covers those strictly
  between 62.5 and 75. Source tables retain the original combined Buffer labels;
  the plotting script derives the split from stored percentiles. Summary tables
  include both split shares and the combined Buffer share for compatibility.
  Every valid item remains in the denominator, including both buffer bands.
- `06_user_week_percentile_heatmap.png`: user-by-week median percentile. An
  asterisk marks a user-week with less than 80% popularity coverage.

Each folder also contains:

- `weekly_popularity_summary.csv`: pooled weekly values, user-level means, 95%
  confidence intervals, tier shares, ratios, and missing-data counts.
- `user_week_popularity_summary.csv`: one row for every user and recommendation
  week, including median, arithmetic mean, geometric mean, percentile, tier
  shares, and popularity coverage.
- `popularity_bias_tests.csv`: two-sided Wilcoxon signed-rank tests over the ten
  user-playlist median log-popularity shifts, Holm-adjusted p-values, and
  rank-biserial effect sizes.

Spotify and YouTube are never combined in a plot or calculation. Spotify uses
primary-artist monthly listeners. YouTube uses the exact recommended video's
view count. The same analysis structure is applied to both, but their raw
values remain platform-specific.

The normalized percentile and tier fields use each platform's original frozen
83-song candidate pool. This preserves the calibration used to build the final
balanced playlist. Missing popularity values are excluded from calculations
and retained in the coverage columns; they are never converted to zero.
User-weeks below 80% popularity coverage remain visible and are marked in the
plots, but are excluded from user-level means, confidence intervals, and
significance tests. Pooled song summaries continue to use every observed value.

## Supplementary thesis results audit

After the main plots, reproduce the additional Weeks 3-6 checks with:

```bash
python3 analysis/review_recommendation_results.py --weeks 3 4 5 6
```

This is an audit of the completed ten-account experiment, not a new collector.
It reads the clean tables, frozen candidate results, realized baseline, and
combined listening-history tables. It makes no network requests and does not
modify these inputs. Input/output directories can be selected with
`--input-dir` and `--output-dir`; candidate and history sources remain relative
to the repository root. At least three distinct weeks are required for the
Friedman comparison.

Each platform receives the following additional outputs:

- `07_account_popularity_and_low_counts.png`: every user-week's raw median
  ratio alongside its Low count out of 30. The baseline references are 1x and
  ten Low items. Median-ratio colours are logarithmic.
- `08_user_week_popularity_groups.png`: four weekly panels, each showing a
  separate 30-item bar for User1 through User10 alongside the fixed baseline.
  All five popularity groups remain visible. Every non-zero segment is
  labelled, including groups with one or two items. A missing segment means
  zero items in that group. This prevents combined weekly shares from hiding
  differences between users.
- `user_week_popularity_comparison.csv`: 40 user-week rows per platform, with
  raw medians, baseline-adjusted median ratios, counts in all five groups,
  very-low counts, shares above the baseline median and maximum, coverage,
  and baseline reference values. It is the compact source for the thesis's
  per-user tables. Counts in the five groups must sum to 30 in every row.
- `low_popularity_user_week_summary.csv`: user summaries plus counts in all
  five groups and exploratory very-low appearance counts.
- `low_popularity_weekly_summary.csv`: pooled counts and medians by week.
- `temporal_popularity_test.csv`: the Friedman statistic, approximate p-value,
  and Kendall's W. The chi-squared approximation is limited with ten accounts
  and four weeks; a non-significant result is not evidence of equivalence.

The output root also receives `recommendation_review_results.json`. This records
the checked numerical results, including all 40 user-week comparisons for each
platform, within-week median ranges and High-majority counts, five-band totals,
distinct-item comparisons, later-measurement sensitivity, and the history audit.
The distinct-item check retains the first value stored for an identifier in
the clean table. The timing check excludes an entire affected account-week
rather than leaving an incomplete playlist. Neither changes the primary
appearance-based analysis or reconstructs historical popularity values.

User-week comparisons are descriptive. No extra per-user significance tests
treat the 30 songs as independent users. The combined weekly summaries and
existing weekly tests remain separate from the individual-list comparisons.

Low limits are taken from the highest frozen candidate classified as Low and
checked against stored recommendation tiers. The exploratory very-low limit
is the median of the ten baseline Low values; it is a subset of Low, not a
sixth popularity tier. Both Buffer bands remain in every relevant denominator.

To update the thesis, copy the corresponding verified figures into its
`figures/popularity/spotify` and `figures/popularity/youtube` folders. Rerunning
either script does not automatically update the thesis directory or its text.

The canonical baseline is the realized 30-track `Heavy Metal MCT` playlist
actually installed on the experiment accounts. It contains `Digital Slavery`
by Emerald and `Brand New Me` by Shaman; the earlier planned tracks `World on
Fire` by Firewind and `Starbreaker` by Traveler are not part of the analysis
baseline. Popularity values remain frozen at the pre-experiment measurement
date. To synchronize the canonical CSV and all derived baseline tables after a
source change, run:

```bash
python3 analysis/sync_realized_balanced_playlist.py
python3 analysis/plot_recommended_popularity.py
```
