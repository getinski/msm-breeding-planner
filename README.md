# MSM Breeding Planner

Generates a per-island Excel breeding plan for filling **My Singing Monsters**
box monsters (Wubboxes, Amber Island, Wublins, etc.).

Runs fully offline against a static snapshot of the game database
(`game_data.json`) shipped with the repo.

## Setup

Requires Python 3.11+.

```bash
pip install -r requirements.txt
```

## Run

```bash
python server.py
```

The server starts and your browser opens to the app. Pick the islands you own,
choose box monsters to fill, and click **Generate Plan** to download the
`.xlsx`.

The React UI is pre-built into `frontend/dist/`, so Node isn't required to run
the app. Only needed if you change frontend source — then `cd frontend && npm
install && npm run build`.

## Building a release binary

PyInstaller bundles the Python interpreter, the game data, and the prebuilt
frontend into a single executable users can double-click — no Python install
required.

```bash
pip install -r requirements-build.txt
pyinstaller build.spec
```

The binary lands at `dist/msm-breeding-planner` (or `.exe` on Windows).
PyInstaller can't cross-compile, so each OS must be built on a matching
machine. Upload the resulting binary to a GitHub Release for users to
download.

## License

MIT — see [LICENSE](LICENSE).
