# PopularityAnalyzer

Tools and saved data for studying popularity bias in Spotify and YouTube Music recommendations. The study used ten controlled users on each platform. Each user listened to the same 30-song **Heavy Metal MCT** playlist over six weeks. The main recommendation analysis covers **weeks 3-6**, with Spotify and YouTube Music analysed separately.

> **AI-generated documentation:** This README was generated with AI assistance and checked against the repository's scripts and saved table structure on 14 November 2026. It describes the current implementation, including its limits; it is not a guarantee that live platform interfaces will remain unchanged.

All commands below run from the **PopularityAnalyzer project root**, with the Python environment activated. Paths are relative to that root.

## Workflow and Main Scripts

1. Resolve the candidate recordings and collect platform-specific popularity values.
2. Select or reconstruct the balanced baseline and install it in the listening profiles.
3. Collect weekly recommendations, preserving their original order and identifiers.
4. Check the snapshots and prepare the clean platform tables.
5. Generate separate platform summaries, figures and statistical checks.
6. Process exported listening histories as a separate check on what was played.

The workflow is **not one automatic pipeline**. In particular, collecting a new week does not import it into the clean analysis tables.

| Python entry point | Purpose | Access and important side effects |
| --- | --- | --- |
| [`spotify/metal_popularity.py`](spotify/metal_popularity.py) | Resolve candidate Spotify recordings and collect popularity metadata. | Usually network access; writes results and caches. |
| [`youtube_music/metal_popularity.py`](youtube_music/metal_popularity.py) | Resolve candidate YouTube Music recordings and collect video views. | Network access; writes results. |
| [`experiment_setup/select_balanced_playlist.py`](experiment_setup/select_balanced_playlist.py) | Reconstruct the realized baseline, or run the earlier allocation method. | Saved inputs; default output replaces the canonical baseline. |
| [`experiment_setup/build_dual_popularity_playlists.py`](experiment_setup/build_dual_popularity_playlists.py) | Build alternative rank-based and magnitude-based selections. | Saved inputs; writes alternative selections and evaluations. |
| [`spotify/add_research_playlist.py`](spotify/add_research_playlist.py) | Add baseline tracks to an existing Spotify playlist. | Network access and playlist-write permission. |
| [`youtube_music/manage_youtube_profiles.py`](youtube_music/manage_youtube_profiles.py) | Manage browser-auth profiles and inspect the selected identity. | Local credential writes; identity checks use the network. |
| [`youtube_music/add_research_playlist.py`](youtube_music/add_research_playlist.py) | Add baseline videos to a named YouTube Music playlist. | Network access; can create a playlist with `--create`. |
| [`spotify/fetch_weekly_playlist_metadata.py`](spotify/fetch_weekly_playlist_metadata.py) | Export the copied weekly playlists for a range of users. | Network access; one collection account for all users. |
| [`youtube_music/fetch_discover_mix_snapshot.py`](youtube_music/fetch_discover_mix_snapshot.py) | Export one user's first 30 returned Discover Mix items. | Network access; refreshes derived auth and saves response logs. |
| [`analysis/build_listening_history_metadata.py`](analysis/build_listening_history_metadata.py) | Parse listening exports, match baseline items and retrieve metadata. | Normally network access; can overwrite derived history outputs. |
| [`analysis/sync_realized_balanced_playlist.py`](analysis/sync_realized_balanced_playlist.py) | Reconcile existing analytical data with the realized baseline. | Offline; overwrites multiple baseline, history and analysis files. |
| [`analysis/plot_recommended_popularity.py`](analysis/plot_recommended_popularity.py) | Generate the main platform figures and weekly tests. | Offline; reads prepared clean tables. |
| [`analysis/review_recommendation_results.py`](analysis/review_recommendation_results.py) | Generate additional user-week, low-popularity and time comparisons. | Offline; also needs frozen reference and listening-history data. |

The profile-resolution helper, [`youtube_music/youtube_auth_profiles.py`](youtube_music/youtube_auth_profiles.py), is used by the YouTube tools; it is not a separate collection command. Earlier inspectors, `spotify/spotify_discover_weekly.py` and `youtube_music/youtube_music_discover_mix.py`, do not provide the same workflow or safeguards as the weekly collectors above.

## Installation

Create an isolated Python 3 environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements_analysis.txt
```

For collection and listening-history processing, also install:

```sh
python -m pip install -r spotify/requirements_spotify.txt \
  -r youtube_music/requirements_youtube_music.txt \
  -r analysis/requirements_listening_history.txt
```

The project uses Spotipy for Spotify Web API access, `ytmusicapi` for the YouTube Music web-client interface, and public Spotify artist pages for monthly listeners. pandas and NumPy handle tables and calculations, Matplotlib produces plots, SciPy supplies statistical and selection methods, and pypdf reads PDF history exports.

The requirements specify minimum package versions, not a locked environment. Record the Python version, installed package versions and project revision when reproducing a result. An old Python build using LibreSSL may produce an `urllib3` warning; use a maintained Python build with supported OpenSSL rather than hiding the warning.

## Recreate the Analysis from Saved Data

This is the shortest route when the checked study inputs are already present. It does **not** contact either platform or require account credentials:

```sh
python analysis/plot_recommended_popularity.py --weeks 3 4 5 6
python analysis/review_recommendation_results.py --weeks 3 4 5 6
```

The first command reads the two clean platform tables. The second additionally reads the saved candidate results, canonical baseline and combined listening-history tables. Both replace generated files with the same names. To keep an earlier set of figures, select another destination for **both** commands:

```sh
python analysis/plot_recommended_popularity.py --weeks 3 4 5 6 \
  --output-dir /tmp/popularity-review
python analysis/review_recommendation_results.py --weeks 3 4 5 6 \
  --output-dir /tmp/popularity-review
```

For only the main Spotify plots, use `--platform Spotify`; for YouTube Music, use `--platform YouTube`. The review script processes both platforms. It is study-specific: it expects ten users and 30 recommendations per user-week, and its time comparison requires at least three distinct weeks.

### What the analysis calculates

- **Raw popularity:** artist monthly listeners on Spotify; views of the exact video on YouTube Music. The raw counts are never treated as interchangeable across platforms.
- **Log popularity:** `log10(value + 1)` reduces the effect of very large counts while keeping zero defined.
- **Baseline comparison:** the user-week median ratio is `(recommendation median + 1) / (baseline median + 1)`.
- **Frozen candidate-pool position:** stored percentiles locate each item relative to the original 83 candidates on its own platform, not relative to that week's recommendations.
- **Representation:** the summaries count all five popularity groups, including both Buffer groups, and report shares above baseline thresholds.
- **Uncertainty and tests:** the main script uses 5,000 user-level bootstrap resamples, weekly two-sided Wilcoxon signed-rank tests on median log-popularity differences, Holm adjustment within each platform, and rank-biserial effect sizes. The review script adds a Friedman comparison across weeks and Kendall's W. The Friedman p-value is an approximation and needs caution with ten users and four weeks.

A combined weekly median uses all recommendation positions. An average of the ten user medians gives each user one summary value. These are different calculations; use the output column names and figure descriptions to identify which is shown. For the Wilcoxon tests, recommendation values are log-transformed **before** taking each user's median; the baseline reference is the log of its raw median plus one. This is not necessarily the log of the raw-median ratio.

Missing popularity is not replaced with zero. User-week summaries below 80% popularity coverage are excluded from user-level inference; available values can still contribute to combined descriptive summaries. Check coverage before interpreting a comparison.

## Collect Weekly Recommendations

> These commands make live requests. Week and folder arguments label a new snapshot; they do not retrieve a historical playlist. A rerun can change the observations or replace an existing output. Preserve earlier outputs and response logs first.

### Spotify: copied Discover Weekly playlists

The researcher must first copy each user's Discover Weekly playlist into the **single collection account's library**, naming the copies `Week6_User1` through `Week6_User10`, for example. The script does not make these copies and does not sign in as each experimental user.

Configure the collection application in `spotify/auth/spotify_config.json` with `client_id`, `client_secret` and `redirect_uri`. The default weekly token cache is `spotify/auth/.spotify_cache`; `--config` and `--cache` override these locations. The read scopes cover private/collaborative playlists and the library. Application access remains subject to Spotify's current rules.

```sh
# Check playlist names and access first. This still makes network requests.
python spotify/fetch_weekly_playlist_metadata.py 6 Week6_24August --dry-run

# Collect all ten copied playlists using the same authenticated account.
python spotify/fetch_weekly_playlist_metadata.py 6 Week6_24August

# Restrict a run to User2.
python spotify/fetch_weekly_playlist_metadata.py 6 Week6_24August \
  --start-user 2 --end-user 2
```

Name matching normally tolerates case, spacing and punctuation differences, including hyphens versus underscores. `--strict-playlist-names` requires exact names. Missing or ambiguous matches are rejected.

The collector follows every playlist page and exports the track items it finds. **It does not stop at or require 30 tracks.** Verify the count and order of each copied playlist. Track, album and artist metadata are added where available. Monthly listeners come from public artist pages and are cached within the run. Compact K/M/B counts are converted to numbers and marked approximate; failed lookups remain empty with diagnostics.

For a custom destination, Spotify's `--output-root` is the **final platform directory**; `UserN` folders are created directly below it:

```sh
python spotify/fetch_weekly_playlist_metadata.py 6 Week6_24August \
  --output-root /path/to/results/Week6_24August/Spotify
```

### YouTube Music: per-user Discover Mix

Each controlled user has a separate browser-auth profile, normally `user_01` through `user_10`. The registry also supports the researcher's `user_aysima_original` profile. Profile resolution is implemented in `youtube_auth_profiles.py`.

```sh
python youtube_music/manage_youtube_profiles.py list
python youtube_music/manage_youtube_profiles.py setup user_02
```

Save an authenticated browser request copied as cURL in that user's `youtube_music/auth/profiles/user_02/curl_out`. The file contains session credentials: keep it private and ensure it came from the intended signed-in user. To import a request explicitly or inspect the configured identity:

```sh
python youtube_music/manage_youtube_profiles.py set-headers user_02 \
  --source /path/to/saved-request.txt
python youtube_music/manage_youtube_profiles.py whoami user_02 --save
```

The import validates header structure, backs up an existing `auth.json` and installs the new configuration. It does not prove that the session remains valid. The identity utility uses the saved auth directly; a stale derived authorization header can fail even when the weekly collector can regenerate that header from a valid cookie.

Collect User2's Week6 snapshot with:

```sh
python youtube_music/fetch_discover_mix_snapshot.py \
  --profile user_02 6 Week6_24August
```

- `user_02` selects the user and default `User2` destination. **`6` is the week number**, not the user number.
- Every normal run imports that profile's `curl_out`, backs up the previous auth and generates temporary current authorization material from the cookie. This cannot renew an expired or revoked session.
- `--headers-source PATH` selects another saved request. `--use-existing-auth` skips the normal cURL import. The automatic reimport is a weekly-collector feature, not a promise made by every YouTube script.
- `--playlist-id URL_OR_ID` bypasses automatic Discover Mix discovery. Otherwise the collector uses a configured/saved identifier or searches library/home responses. A saved identifier does not freeze playlist contents.
- The collector attempts a live account-name lookup, but can fall back to a saved registry label. It does not automatically reject every identity mismatch. Check the selected browser user and reported identity yourself.
- The collector requests 30 items, retains the **first 30 returned items in order**, and requires a video ID for each. Other `--limit` values and incomplete lists are rejected. The server can still return a larger response internally.
- Repeating the command is **not guaranteed to return the same songs, different songs, or advance the mix by exactly 30 songs**.

Unlike Spotify, YouTube's `--output-root` is the **parent of the experiment folder**:

```sh
python youtube_music/fetch_discover_mix_snapshot.py \
  --profile user_02 6 Week6_24August --output-root /path/to/results
```

This creates `/path/to/results/Week6_24August/Youtube/User2/`. Use `--output` for an explicit CSV filename. Folder-derived dates are naming labels, not measured capture times.

### Response recovery and collection checks

The YouTube collector saves request/response records by default in a timestamped `api_responses` directory beside the output. The instrumented request sender records JSON responses before higher-level parsing; non-JSON errors can also be saved. This allows inspection of songs returned before a parsing failure. It is not a universal network recorder or an automatic offline recovery command.

If a run fails, **inspect the saved responses before making another live request**, since a later run may change Discover Mix. A completed CSV is written through a temporary file and renamed, but may still contain missing enrichment fields. This protects final-file assembly, not metadata completeness or earlier versions with the same name.

After every collection, check user identity, playlist ID, item count, order, non-empty track/video IDs, capture time, popularity coverage and lookup errors. Preserve missing metadata as missing; do not drop the original recommendation or silently replace it with a later song. Record separate measurement and repair dates when recovering metadata.

## Candidate Resolution and the Balanced Playlist

These are setup/reconstruction tools, not necessary for rerunning plots from existing clean data. **Back up the frozen reference files before running them.** New observations can change rankings, tiers and later comparisons. Selecting a different result filename does not necessarily redirect every cache or evaluation output.

```sh
python spotify/metal_popularity.py \
  --metric artist_monthly_listeners --output /tmp/spotify_candidates.csv
python youtube_music/metal_popularity.py \
  --profile user_aysima_original --output /tmp/youtube_candidates.csv
```

The Spotify resolver scores artist, title, release and version information. Monthly listeners are the default metric; manually supplied track stream counts are an optional alternative, not the study's primary measure. The YouTube resolver prefers album Art Tracks and checks artist/title/year/credits. Its optional `--api-key` or `YOUTUBE_API_KEY` route uses the official YouTube Data API; the study baseline used `ytmusicapi` player responses, and weekly collection does not require that key. Inspect flagged matches rather than assuming the first search result is correct.

To reconstruct the realized baseline without replacing the canonical destination:

```sh
python experiment_setup/select_balanced_playlist.py \
  --output /tmp/reconstructed_baseline.csv
```

By default this recovers the 30 recordings and their order from the preserved original-playlist snapshot, checking unique candidates, usable saved metadata and ten Low, ten Middle and ten High items on each platform. It does not independently enforce every earlier design constraint, such as the country cap.

`--ignore-realized-playlist` instead runs the earlier cross-platform tier-allocation method. That method favours target percentile centres and applies a country cap that can be relaxed and reported. It is not a reconstruction of the installed playlist.

`build_dual_popularity_playlists.py` creates alternative rank-based and magnitude-based selections. Its magnitude method groups sorted `log10(value + 1)` observations into three contiguous clusters, preserves ties and applies a minimum cluster size. Constrained selection also considers cross-platform tiers, subgenre totals and country limits. Review its `--help` and output arguments before running it: the saved rank-based selection is also an input to baseline synchronization.

### Install the playlist

```sh
# Spotify requires an existing, unambiguously named playlist.
python spotify/add_research_playlist.py --playlist-name "Heavy Metal MCT"

# Import the intended YouTube user's browser headers before installation.
python youtube_music/manage_youtube_profiles.py set-headers user_02 \
  --source youtube_music/auth/profiles/user_02/curl_out
python youtube_music/add_research_playlist.py \
  --profile user_02 --playlist-name "Heavy Metal MCT" --create
```

Both installers read the canonical baseline by default and require 30 distinct platform IDs. Their default playlist name is `MCT Research`, so supply the study name explicitly. They add missing items and verify **membership**, not exact order or the absence of duplicates/unrelated items. Inspect the final playlist manually. YouTube creation defaults to private; Spotify installation does not create a missing playlist. The Spotify installer uses a separate write-capable token cache, not the weekly collector's read cache. Copying the prepared Spotify playlist to the controlled users was manual.

### Synchronize an already prepared study

```sh
python analysis/sync_realized_balanced_playlist.py
```

**Do not run this as an initial import or a harmless check. It has no command-line parser or safe `--help` mode.** It expects existing clean tables and listening-history outputs, uses fixed repository paths, and overwrites several files. It reads the preserved original order and saved rank-based values, checks the 10/10/10 tier balance and 15/15 subgenre split, and updates baseline rows, baseline-relative comparisons, history matches and older summaries/plots. It makes no platform calls.

The realized baseline includes *Digital Slavery* by Emerald and *Brand New Me* by Shaman instead of the earlier planned *World on Fire* and *Starbreaker*. Synchronization does not import new recommendation weeks or regenerate all current platform figures. After an intentional synchronization, rerun both analysis commands and review affected reports.

## Listening-History Processing

```sh
python analysis/build_listening_history_metadata.py --platform spotify
python analysis/build_listening_history_metadata.py --platform youtube \
  --youtube-profile user_aysima_original \
  --youtube-curl youtube_music/auth/profiles/user_aysima_original/curl_out
```

The metadata account supplies access to track/video information; it is not necessarily the owner of the exported history. When changing the YouTube metadata profile, also supply its corresponding `--youtube-curl`, since the default cURL path is separately configured.

- **Spotify:** reads exported music-history JSON files, retains separate playback events, end-time strings and milliseconds played, resolves metadata, and marks baseline matches. Repeats and non-playlist events are retained. Experimental weeks use predefined study-specific date windows, not platform-provided session labels; local export times do not supply a UTC offset.
- **YouTube Music:** extracts video links and displayed order from browser-exported PDF history pages, then retrieves metadata once per distinct video. A visible history item is not a complete playback-event record. Missing week/timing information remains missing.
- **Image-based history:** the reader does not perform optical character recognition. Later User1/User10 image corrections require separate transcription and reconciliation. Rerunning only the PDF reader can overwrite those corrections; preserve them first.
- **Known repairs:** `--repair-existing-spotify-output` applies a defined set of saved-output repairs without new network calls. It is not a general offline importer.

## Updating the Analytical Inputs

The current project does **not** have a general raw-week-to-clean-table importer. Before analysing a new week or a recovered snapshot:

1. Preserve the source snapshot, response logs and retrieval dates.
2. Validate user/week/position and exact item identifiers against the source.
3. Add the recommendation appearances to the appropriate clean platform table using its existing schema. Keep the baseline rows once, not once per user or week.
4. Retain source-file/row provenance, missing-value information, and separate metadata measurement/repair dates where available.
5. Assign popularity percentiles and tiers using the same frozen platform reference and tie convention. Do not re-rank only the new playlist or replace the frozen calibration with current candidate counts.
6. Check counts, duplicates, metric coverage and tier/percentile agreement before running analysis.

The plotter consumes stored calibration fields and validates them; it does not build them from raw snapshots. `--input-dir` selects another directory containing the expected clean filenames. The review script also uses repository-relative reference/history inputs, so changing that argument alone does not relocate every dependency.

### Limits of the automated reproduction

The review script saves low/very-low counts, exact-ID deduplication checks, a check excluding user-weeks with later popularity measurements, and combined listening-history summaries. Its per-user history output contains event counts, **not the full per-user popularity comparisons** discussed separately during the study. The specific sensitivity check excluding User2's Week5 playlist is also not automated there. Reproducing those additional calculations requires a separately recorded analysis; the two figure commands should not be presented as reproducing them all.

Older tools and outputs under `initial_data_analysis/` and `recommended_popularity_plots/` use different baseline-relative calculations. They are not substitutes for the current frozen-candidate analysis.

## Local Tests

```sh
python -m unittest discover -s youtube_music/tests -v
```

The tests cover output naming, popularity boundaries, missing values, logarithmic fields and rejection of credential-like CSV columns. They do not test live authentication, changing response layouts or the entire pipeline. Most entry-point scripts provide `--help`; the synchronization script is the important exception described above.

## Data Layout and Meaning

The following section describes data and configuration files after the Python workflows, so that each output can be traced back to its producer.

### Popularity metrics and tiers

| Platform | Primary raw field | Meaning and limitation |
| --- | --- | --- |
| Spotify | `primary_artist_monthly_listeners` in weekly snapshots; `spotify_artist_monthly_listeners` in clean tables | The primary artist's rolling 28-day audience. It is an artist-level proxy, not a song's followers or cumulative streams. Several tracks by one artist can share a value. |
| YouTube Music | `view_count` | Cumulative views of the specific video upload. It is not a total across uploads, an artist's audience or a subscriber count. |

The original 83-candidate pool defines separate frozen popularity percentiles for each platform. The analysis uses:

| Group | Candidate-pool percentile `p` |
| --- | --- |
| Low | `p <= 25` |
| Lower Buffer | `25 < p < 37.5` |
| Middle | `37.5 <= p <= 62.5` |
| Upper Buffer | `62.5 < p < 75` |
| High | `p >= 75` |

The baseline contains ten Low, ten Middle and ten High recordings on each platform, with no Buffer items. Recommendations can belong to any of the five groups; Buffer items are included in calculations and denominators. Source tables can store a combined `Buffer` label, which the plotter splits using the percentile. The exploratory **very-low** threshold is the median popularity of the baseline's ten Low items: it identifies their lower half, not half of the entire candidate-pool Low group and not a sixth tier.

### Candidate and baseline files

| File | Role |
| --- | --- |
| [`experiment_setup/metal_candidates.csv`](experiment_setup/metal_candidates.csv) | The 83 screened candidate recordings and identifying characteristics, including artist/title, style, country and expected year. |
| [`spotify/spotify_popularity_results.csv`](spotify/spotify_popularity_results.csv) | Spotify candidate matches, saved popularity, source/capture information and classifications. |
| [`youtube_music/youtube_popularity_results.csv`](youtube_music/youtube_popularity_results.csv) | YouTube candidate matches, exact video views, validation and classifications. |
| [`experiment_setup/final_balanced_playlist.csv`](experiment_setup/final_balanced_playlist.csv) | Canonical realized 30-recording baseline with cross-platform identifiers and saved popularity. |
| [`experiment_setup/final_rank_based_playlist.csv`](experiment_setup/final_rank_based_playlist.csv) | Saved rank-based selection; also supplies frozen values to synchronization. |
| [`experiment_setup/final_magnitude_based_playlist.csv`](experiment_setup/final_magnitude_based_playlist.csv) | Alternative magnitude-based selection. |
| [`experiment_results/Week1_21July/Spotify/original_playlist_popularity.csv`](experiment_results/Week1_21July/Spotify/original_playlist_popularity.csv) | Preserved installed-playlist identity and order reference. Using it does not include Week1 recommendations in the main analysis. |

### Weekly and history outputs

Example layout using the collectors' default destinations:

```text
experiment_results/
  Week6_24August/
    Spotify/
      User2/
        Week6_User2_spotify_metadata.csv
        Week6_User2_spotify_metadata.json
      Week6_users1-10_spotify_metadata.csv
      Week6_users1-10_fetch_summary.csv
    Youtube/
      User2/
        Week6_User2_24.08.csv
        api_responses/
          <output-stem>-<run-timestamp>/
  Spotify_Listening_History/
    spotify_listening_history_metadata_all_users.csv
    spotify_listening_history_summary.csv
  Youtube_Listening_History/
    youtube_listening_history_metadata_all_users.csv
    youtube_listening_history_summary.csv
```

The actual directory spelling is **`Youtube`**, while the analysis destination uses lowercase `youtube`. Spotify JSON can be disabled with `--no-json`. History directories also retain source exports and per-user derived outputs. Spotify history rows are playback events, while YouTube history rows are visible captured items; their counts do not measure the same thing.

### Clean analytical tables

The main inputs are in [`analysis_results/popularity_bias/clean_platform_tables/`](analysis_results/popularity_bias/clean_platform_tables/):

- `spotify_weeks3_6_song_popularity_clean.csv`
- `youtube_weeks3_6_song_popularity_clean.csv`

Each currently contains **1,230 rows: 1,200 recommendation appearances plus 30 baseline rows**. One recommendation row represents one position for one user in one week, not one globally unique song. Repeated identifiers across users/weeks remain separate appearances. `row_type` is `recommended` or `final_balanced_baseline`.

| Column group | Important fields and interpretation |
| --- | --- |
| Observation | `platform`, `week_number`, `user_number`, `playlist_position`, playlist identifiers and labels. |
| Recording | `track_id`, YouTube `video_id`, `track_name`, `artist_name`, credited artists, album and duration where available. IDs identify exact platform items; title matching alone does not prove the same recording. |
| Primary popularity | `popularity_value`, `popularity_metric`, `popularity_metric_scope`, `popularity_available`, plus the platform-specific raw field. Empty means missing, not zero. |
| Transformations | `popularity_log10_plus1` represents `log10(value + 1)`. Older `popularity_log10` fields have a different convention and should not be substituted. |
| Frozen calibration | `original_candidate_pool_percentile_83`, `original_candidate_pool_rank_tier_83`, `original_candidate_pool_reference_size`. These support the main tier comparisons. |
| Other comparisons | `final_playlist_percentile_30`, `final_playlist_tier_30`, baseline-threshold flags and exact-ID repeat flags. The 30-item baseline-relative fields are not the 83-candidate calibration. |
| Provenance | `source_file`, `source_file_row`, `captured_at_utc`, `capture_date`. Some source paths preserve the original machine's absolute location and are provenance labels, not portable runtime paths. |
| Later YouTube metadata | `popularity_measurement_at_utc`, `metadata_repaired_at_utc`, where populated. Some repaired raw files also use `retrievedAt`; preserve its meaning when reconciling them. |

**Dates have different meanings.** A folder/date label identifies the intended snapshot. Capture time records the collection. A popularity measurement can happen later, and a repair date can be later still without a new measurement. None should silently replace another. Recollecting today's counts cannot recover a historical popularity value.

### Generated figures and tables

Default destination: [`analysis_results/popularity_bias/platform_popularity_plots/`](analysis_results/popularity_bias/platform_popularity_plots/), with separate `spotify/` and `youtube/` directories.

| Figure | Producer and purpose |
| --- | --- |
| `01_song_popularity_by_user_and_week.png` | Main plotter: item popularity for each user and week. |
| `02_weekly_popularity_ecdf.png` | Main plotter: cumulative distributions against the baseline. |
| `03_user_popularity_trajectories.png` | Main plotter: changes in user summaries across weeks. |
| `04_weekly_bias_summary.png` | Main plotter: weekly user-level comparisons and bootstrap intervals. |
| `05_original_pool_tier_composition.png` | Main plotter: five-group composition relative to the frozen reference. |
| `06_user_week_percentile_heatmap.png` | Main plotter: user-week candidate-pool percentile summaries. |
| `07_account_popularity_and_low_counts.png` | Review script: user-week median ratios and Low counts. The filename retains the older word `account`. |
| `08_user_week_popularity_groups.png` | Review script: full five-group counts for every user-week. |

Together the scripts produce **eight numbered figures and seven CSV summaries per platform**. The main script writes `weekly_popularity_summary.csv`, `user_week_popularity_summary.csv` and `popularity_bias_tests.csv`. The review script adds `user_week_popularity_comparison.csv`, `low_popularity_user_week_summary.csv`, `low_popularity_weekly_summary.csv` and `temporal_popularity_test.csv`, plus a shared `recommendation_review_results.json` at the output root.

Figures are not copied to a thesis/Overleaf project automatically. Update any report's figure files, captions and numerical statements together after changing analytical inputs. For additional selection-method background, see [`POPULARITY_METHOD.md`](POPULARITY_METHOD.md), while keeping its method context separate from the current frozen-reference recommendation analysis.

## Credentials, Privacy and Sharing

Spotify configuration and token caches are under `spotify/auth/`. YouTube's profile registry is `youtube_music/auth/youtube_auth_profiles.json`; session files normally live under `youtube_music/auth/profiles/<profile>/` as `curl_out`, `auth.json` and timestamped backups.

**Do not assume these files are excluded from Git.** The reviewed working copy includes tracked authentication-related paths. Adding ignore rules does not untrack an existing file or remove it from history. Before publishing, inspect the index and history, remove private material through a separately reviewed cleanup, and revoke/rotate any credentials that have been exposed.

Browser cURL dumps, cookies, authorization headers and token backups can grant account access. Response logs filter credential-like structured keys, but raw errors and account metadata can still be sensitive. Review logs, listening histories, account names, owner identifiers and private playlist links before sharing. Pseudonymous user labels alone do not anonymize the underlying exports.
