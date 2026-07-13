# YouTube Music authentication files

All YouTube Music credential material is kept under this `auth` directory.
The non-secret profile registry is `youtube_auth_profiles.json`; live browser
cookies and their local backups are stored under `profiles/` and excluded from
Git.

Each `user_01` through `user_10` directory receives its own `auth.json` file.
These files contain live browser cookies and are ignored by Git. Never share,
print, or commit them.

`user_aysima_original` is a separately named preserved profile and is not one
of the ten experimental users.

Create credentials while signed into the corresponding account:

```bash
python3 youtube_music/manage_youtube_profiles.py setup user_01
python3 youtube_music/manage_youtube_profiles.py setup user_02
```

Repeat through `user_10`, then select a profile in supported commands:

```bash
python3 youtube_music/add_research_playlist.py --profile user_03
python3 youtube_music/youtube_music_discover_mix.py --profile user_03
python3 youtube_music/metal_popularity.py --profile user_03
```

You may instead set `YTMUSIC_PROFILE=user_03` for a shell session. An explicit
`--profile` always takes precedence.

Verify which account a profile belongs to and save its display name in the
non-secret registry:

```bash
python3 youtube_music/manage_youtube_profiles.py whoami user_03 --save
python3 youtube_music/manage_youtube_profiles.py list
```

The playlist-changing command deliberately refuses to run without an explicit
profile (or `YTMUSIC_PROFILE`) to reduce the chance of modifying the wrong
research account.

Copied request headers can also be installed from a text file. The previous
auth is retained as a timestamped local backup:

```bash
python3 youtube_music/manage_youtube_profiles.py set-headers user_01 \
  --source /path/to/copied-request-headers.txt
```
