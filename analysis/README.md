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
  balanced list and every recommendation week.
- `03_user_popularity_trajectories.png`: all ten users' weekly median
  original-pool percentiles and shares above the balanced-list median.
- `04_weekly_bias_summary.png`: means across the ten user playlists with 95%
  bootstrap confidence intervals.
- `05_original_pool_tier_composition.png`: Low, Buffer, Middle, and High tier
  shares using the same frozen 83-song calibration used to create the balanced
  playlist.
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
