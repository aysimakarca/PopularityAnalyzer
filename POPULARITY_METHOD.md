# Cross-platform metal playlist methodology

## Scope

The candidate pool contains male-fronted heavy- and power-metal studio tracks
released from 2010 through 2022. It contains one track per artist and resolves
the exact album recording independently on Spotify and YouTube Music.

The final playlist has 30 tracks. Each platform independently has ten Low, ten
Middle, and ten High popularity tracks. A track is allowed to occupy different
tiers on Spotify and YouTube; this is a feature of the design.

## Files

- `experiment_setup/metal_candidates.csv`: 83 screened candidates from 38 countries.
- `spotify/metal_popularity.py`: resolves Spotify tracks and calculates
  Spotify-only percentiles from artist monthly listeners by default.
- `spotify/spotify_artist_monthly_listeners.csv`: timestamped public
  artist-page monthly-listener snapshot.
- `spotify/spotify_stream_counts.csv`: generated data-entry worksheet.
- `spotify/spotify_popularity_results.csv`: Spotify metadata and tier output.
- `youtube_music/metal_popularity.py`: resolves YouTube Music Art Tracks,
  collects view counts, and calculates YouTube-only percentiles.
- `youtube_music/youtube_popularity_results.csv`: YouTube output.
- `experiment_setup/select_balanced_playlist.py`: selects a feasible 30-song cross-platform
  table after both result files contain tiers.
- `experiment_setup/final_balanced_playlist.csv`: selected 30-song study playlist.
- `experiment_setup/build_dual_popularity_playlists.py`: recomputes both buffered rank tiers and
  log-magnitude clusters, then optimizes comparable 30-song playlists.
- `spotify/spotify_dual_popularity_results.csv`: all Spotify candidates with
  both rank and magnitude assignments.
- `youtube_music/youtube_dual_popularity_results.csv`: all YouTube candidates
  with both rank and magnitude assignments.
- `experiment_setup/final_rank_based_playlist.csv`: final playlist under buffered percentiles.
- `experiment_setup/final_magnitude_based_playlist.csv`: final playlist under natural
  log-magnitude clusters.

## Popularity calculation

Popularity is calculated inside this fixed candidate pool, separately for each
platform. Spotify artist monthly listeners and YouTube Art Track views are
ranked within their platforms rather than compared as raw counts.

For `N` candidates, tied values receive their average rank. The percentile is:

```text
percentile = 100 * (average_rank - 0.5) / N
```

The quartile-based bands deliberately leave 12.5-percentile buffers between
experimental groups. They provide 21 eligible candidates per tier in the
83-song pool while maintaining separation between groups:

```text
Low:     percentile <= 25
Middle:  37.5 <= percentile <= 62.5
High:    percentile >= 75
Buffer:  every other candidate (not eligible for the final playlist)
```

## Magnitude-based calculation

The alternative calculation retains numerical separation rather than only
ordinal position. For raw popularity value `x`, it first computes:

```text
log_value = log10(x + 1)
```

Spotify uses artist monthly listeners for `x`; YouTube uses exact Art Track
views. The `+1` makes the transform defined for zero. A difference of one unit
on this scale represents approximately a tenfold difference in raw popularity.

For each platform independently, the sorted log values are divided into three
contiguous clusters. The partition is the exact solution that minimizes total
within-cluster squared error:

```text
sum((log_value - cluster_mean)^2)
```

Each cluster must contain at least ten candidates, and equal raw values are
never split across clusters. This is a deterministic one-dimensional natural-
breaks calculation, not an equal-size rank split.

On the frozen 2026-06-29 snapshot, it produced:

```text
Spotify monthly listeners
Low:       13 candidates,        105 .. 2,218
Middle:    34 candidates,      3,073 .. 82,719
High:      36 candidates,    107,557 .. 32,848,505

YouTube Art Track views
Low:       19 candidates,        126 .. 4,548
Middle:    35 candidates,      6,895 .. 274,741
High:      29 candidates,    343,913 .. 258,826,110
```

These ranges are properties of this frozen candidate pool and snapshot. They
must be recalculated if the pool or measurement date changes.

Generate both evaluations and playlists with:

```bash
python3 experiment_setup/build_dual_popularity_playlists.py
```

The optimizer applies identical non-popularity controls to both methods:

- exactly ten Low, ten Middle, and ten High songs on each platform;
- exactly five heavy-metal and five power-metal songs within every platform
  tier;
- no more than two songs from one country;
- 24 cross-platform tier-concordant songs and six adjacent-tier-discordant
  songs, using the common Spotify-row x YouTube-column allocation below.

```text
                         YouTube
                   Low  Middle  High
Spotify Low          9      1      0
Spotify Middle       1      7      2
Spotify High         0      2      8
```

Within those constraints, the rank method selects songs closest to percentile
centres 10, 50, and 90. The magnitude method selects songs closest to their
platform-specific log-cluster means.

The final selector enforces row and column totals of ten in the Spotify-tier x
YouTube-tier table. It prefers this allocation when the observations allow it:

```text
                         YouTube
                   Low  Middle  High
Spotify Low          6      2      2
Spotify Middle       2      6      2
Spotify High         2      2      6
```

If these exact cells are unavailable, the selector finds the closest feasible
3x3 allocation while preserving ten songs in every marginal tier. The current
snapshot produced 8/2/0, 2/6/2, and 0/2/8 across the three rows: 22 concordant
and eight adjacent-tier-discordant tracks.

## Spotify procedure

Run:

```bash
python3 spotify/metal_popularity.py
```

The script uses `spotify/spotify_config.json` and the existing OAuth cache. It
searches for each recording, records its Spotify ID, URL, ISRC, album, release
date, duration, and validation status.

Spotify removed track popularity from Development Mode API responses in
February 2026 and does not expose cumulative track streams through the official
Web API. By default the script therefore reads the exact monthly-listener count
from each artist's public Spotify page, timestamps the snapshot, and ranks that
artist-level reach proxy. Because the design contains exactly one song per
artist, no artist is counted twice. This operationalization measures **artist
popularity**, not the popularity of the individual recording.

Refresh all public counts for the final common-date snapshot with:

```bash
python3 spotify/metal_popularity.py --refresh-listeners
```

The optional track-level alternative remains available. Enter cumulative
stream counts into `spotify/spotify_stream_counts.csv`, record one common
capture date, then calculate tiers without repeating API calls:

```bash
python3 spotify/metal_popularity.py --metric track_stream_count --offline
```

Do not label monthly listeners as `track popularity`; report the construct as
`Spotify artist monthly-listener popularity`. YouTube Art Track views remain a
track-level construct, so comparisons between platforms should use within-
platform percentiles and explicitly acknowledge that construct difference.

## YouTube Music procedure

The existing `youtube_music/ytmusic_auth.json` is enough for candidate
resolution and a preliminary view-count run:

```bash
python3 youtube_music/metal_popularity.py
```

The script requires `MUSIC_VIDEO_TYPE_ATV`, YouTube Music's Art Track type, and
checks artist, title, album year, artist-credit count, and studio-version terms.
It measures the exact video ID that will be inserted into the study playlist.

For the official final snapshot, create a Google Cloud API key with **YouTube
Data API v3** enabled. Public video statistics need an API key but do not need
OAuth or access to participants' Google accounts. Keep the key outside the
repository and run:

```bash
export YOUTUBE_API_KEY='your-key'
python3 youtube_music/metal_popularity.py
```

The script then replaces preliminary player-response values with official API
`viewCount`, `likeCount`, `commentCount`, and `publishedAt` values. View count
is the popularity metric; likes and comments are retained only as secondary
engagement variables.

## Final selection

After both tier files are complete:

```bash
python3 experiment_setup/select_balanced_playlist.py
```

The output is `experiment_setup/final_balanced_playlist.csv`. The selector prefers no more than
two songs from one country. If the observed 3x3 cells make that cap impossible,
the affected output row is marked `country cap relaxed`.

Archive all three result CSVs with the collection date. Popularity values
change, so the final playlist and its tier assignments must refer to one frozen
measurement snapshot.
