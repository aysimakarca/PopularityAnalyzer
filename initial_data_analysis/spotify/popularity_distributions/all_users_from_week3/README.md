# Spotify weekly popularity distributions

Metric: `spotify_artist_monthly_listeners` (primary artist monthly listeners).

Included recommendation weeks: Week3, Week4.
Included users: User1, User2, User3, User4, User5, User6, User7, User8, User9, User10.
Week1 and Week2 recommendations included: no.
The original playlist is included in every figure regardless of the week setting.

Spotify popularity is an artist-level reach proxy, not track popularity.

Files:

- `popularity_tracks.csv`: normalized track-level data and comparisons with the original distribution.
- `playlist_popularity_summary.csv`: descriptive statistics, median shifts, and the two-sample KS distance for every weekly playlist.
- `plots/user_XX_popularity_distributions.png`: original-versus-weekly ECDF and box/strip plots for one user only.
- `run_metadata.json`: inputs and run settings used to create this directory.

The count axes are logarithmic because popularity spans orders of magnitude. Raw counts remain in both CSV files.
