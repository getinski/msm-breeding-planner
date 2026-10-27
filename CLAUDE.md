# CLAUDE.md

msm-breeding-planner turns a My Singing Monsters game data snapshot into a per-island Excel breeding plan for filling box monsters. Start with README.md.

## Commands

```bash
python server.py                            # Flask app on :5050, opens the browser
cd frontend && npm install && npm run build # rebuild the UI into frontend/dist/
pyinstaller build.spec                      # single-file binary in dist/
```

There are no tests.

## Layout

- `plan_breeding.py`: loads `game_data.json`, finds recipes per island and builds the workbook.
- `server.py`: the Flask API (`/api/islands`, `/api/box-monsters`, `/api/settings`, `/api/generate`) and the static UI.
- `frontend/src/`: the React UI. `frontend/dist/` is the built copy and is committed.
- `game_data.json`: the offline game data snapshot.
- `breeding_config.conf`: the user's saved settings. Not committed.

## Rules

- `game_data.json` is the output of msm-api's `GameData.export_planner_json()`. Regenerate it from there instead of editing it by hand, and don't depend on fields that export doesn't produce.
- After changing `frontend/src/`, rebuild and commit `frontend/dist/` too, since `python server.py` serves the committed build.
- Pushing a `v*` tag publishes a GitHub Release (`.github/workflows/release.yml`). Don't push tags unless asked.
