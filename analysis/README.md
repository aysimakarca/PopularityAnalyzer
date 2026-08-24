# Popularity Bias Plots

## Weekly distributions against the original playlist

Run the platform-specific weekly distribution analysis with a lower-case
platform name:

```bash
python3 analysis/plot_weekly_popularity_distributions.py spotify
python3 analysis/plot_weekly_popularity_distributions.py youtube
```

Week1 and Week2 recommendations are excluded by default. Include them with:

```bash
python3 analysis/plot_weekly_popularity_distributions.py spotify --include-first-two-weeks
```

Select one user so that the exported data and plot contain only that user's
weekly playlists (plus the original playlist reference):

```bash
python3 analysis/plot_weekly_popularity_distributions.py youtube --user 4
```

Outputs are kept separate under
`initial_data_analysis/<platform>/popularity_distributions/`. Each run writes
normalized track data, playlist-level comparison statistics, run metadata, and
one ECDF plus box/strip distribution figure per included user. Every figure
includes the platform's captured `original_playlist_popularity.csv`.

The Spotify analysis uses primary-artist monthly listeners. The YouTube
analysis uses cumulative views of the exact recommended video. Both raw counts
and log-scaled visualizations are retained; the platforms are not combined in
one distribution because the constructs differ.

## Final-balanced baseline analysis

Regenerate standardized popularity tables and plots with:

```bash
python3 analysis/plot_popularity_bias.py
```

Useful filters:

```bash
python3 analysis/plot_popularity_bias.py --week Week4
python3 analysis/plot_popularity_bias.py --platform Spotify
python3 analysis/plot_popularity_bias.py --week Week4 --platform Youtube
```

Default outputs are written under:

```text
analysis_results/popularity_bias/
```

Key files:

- `standardized_playlist_tracks.csv`: one row per song, using shared column names for Spotify, YouTube, weekly recommendations, and the final balanced baseline.
- `playlist_popularity_summary.csv`: one row per playlist/user/platform with median popularity shifts, baseline percentiles, and shares above the final balanced baseline.
- `baseline_popularity_reference.csv`: final balanced baseline ranges and medians used for comparisons.
- `plots/*_playlist_positions.png`: per-song platform-specific metric by playlist position, with the same-platform final balanced baseline overlaid.
- `plots/*_distributions.png`: distribution of platform-specific log10 popularity for each user playlist against the same-platform final balanced playlist.
- `plots/*_median_delta_bars.png`: median log10 shift for each user playlist relative to the same-platform final balanced median.
- `plots/*_weekly_user_median_delta_heatmap.png`: cross-week heatmap of user-level median log10 shifts.
- `plots/*_normalized_baseline_percentile_bars.png`: week-level normalized comparison of Spotify and YouTube using each platform's own final balanced baseline percentile.
- `plots/*_weekly_user_baseline_percentile_heatmap.png`: cross-week heatmap of normalized 0-100 baseline percentile by platform.

Metric interpretation:

- Spotify popularity is artist monthly listeners, so Spotify plots compare recommendation artist monthly-listener counts against the Spotify fields in `final_balanced_playlist.csv`.
- YouTube popularity is exact video view count, so YouTube plots compare recommendation video views against the YouTube fields in `final_balanced_playlist.csv`.
- The normalized percentile plots are the safest cross-platform visual comparison: values above 50 mean the playlist median is more popular than the median song in that platform's own final balanced baseline.
