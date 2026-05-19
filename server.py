"""
server.py — Flask backend for the MSM breeding planner UI.

Endpoints (all under /api):
    GET  /islands           list of visible islands (paired + ordered for the UI)
    GET  /box-monsters      box-monster catalog (id, name, req counts)
    GET  /settings          current breeding_config.conf content (UI-shape)
    POST /settings          persist UI settings → breeding_config.conf
    POST /generate          generate the .xlsx and stream it as a download

In production the built frontend (frontend/dist) is served from /.
In dev, run `npm run dev` inside frontend/ — Vite proxies /api to this server.
"""

from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

from plan_breeding import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_DATA_PATH,
    PlanError,
    build_plan_workbook,
    list_box_monsters,
    list_islands,
    load_config,
    load_game_data,
    resolve_island_configs,
    save_config,
)


# ── UI-only visibility / ordering rules ───────────────────────────────────────

HIDDEN_ISLAND_INTERNAL_NAMES: frozenset[str] = frozenset({
    "ISLAND_GOLD",
    "ISLAND_ETHEREAL",
    "ISLAND_SHUGA",
    "ISLAND_TRIBAL",
    "ISLAND_UNDERLING",   # Wublin Island
    "ISLAND_COMPOSER",
    "ISLAND_CELESTIAL",
    "ISLAND_BATTLE",
    "ISLAND_22",          # Amber Island
})

# UI grouping for the islands strip.  Order matches the user's mental model:
# Main contains every base island (no mirrors); Mirror contains the mirror variants.
ISLAND_GROUPS: tuple[dict, ...] = (
    {
        "label": "Main",
        "islands": (
            "ISLAND_1",       # Plant
            "ISLAND_2",       # Cold
            "ISLAND_3",       # Air
            "ISLAND_4",       # Water
            "ISLAND_5",       # Earth
            "ISLAND_FIRE",    # Fire Haven
            "ISLAND_14",      # Fire Oasis
            "ISLAND_18",      # Light
            "ISLAND_15",      # Psychic
            "ISLAND_16",      # Faerie
            "ISLAND_17",      # Bone
        ),
    },
    {
        "label": "Mirror",
        "islands": (
            "ISLAND_1_MIRROR",
            "ISLAND_2_MIRROR",
            "ISLAND_3_MIRROR",
            "ISLAND_4_MIRROR",
            "ISLAND_5_MIRROR",
            "ISLAND_18_MIRROR",
            "ISLAND_15_MIRROR",
            "ISLAND_16_MIRROR",
            "ISLAND_17_MIRROR",
        ),
    },
)

# Flat ordered list of all UI-visible islands (used by _visible_islands).
VISIBLE_ISLAND_ORDER: tuple[str, ...] = tuple(
    name for g in ISLAND_GROUPS for name in g["islands"]
)


def _categorize_box(m: dict) -> str | None:
    """Group box monsters for the UI dropdown. Returns None to hide the row.

    - Wubboxes are intentionally excluded.
    - 'Amber Monsters' = CLASS_FIRE plus Viveine (the lone CLASS_SEASON_ECO Amber box).
    - 'Wublins' covers both ' Wublin Island'-suffixed names and the CLASS_SUPERNATURAL
      monsters (Brump, Zynth, …) that live as Wublin Island statues.
    """
    name = m.get("common_name") or ""
    cls = m.get("class") or ""
    if "Wubbox" in name:
        return None
    if cls in ("CLASS_FIRE", "CLASS_SEASON_ECO"):
        return "Amber Monsters"
    if name.endswith(" Wublin Island") or cls == "CLASS_SUPERNATURAL":
        return "Wublins"
    if cls == "CLASS_CELESTIAL":
        return "Celestials"
    return None


# Display order of the dropdown categories.
BOX_CATEGORY_ORDER: tuple[str, ...] = ("Amber Monsters", "Wublins", "Celestials")


def _visible_islands(data: dict[str, Any]) -> list[dict]:
    """Return only the islands the UI exposes, in the configured UI order."""
    indexed: dict[str, dict] = {}
    for isl in list_islands(data):
        name = isl["internal_name"]
        if name in HIDDEN_ISLAND_INTERNAL_NAMES:
            continue
        if any(ch.isdigit() for ch in isl["display_name"]):
            continue
        if name in indexed:
            continue
        indexed[name] = isl

    return [indexed[name] for name in VISIBLE_ISLAND_ORDER if name in indexed]


# ── App factory ───────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent
# When frozen by PyInstaller, the built frontend is extracted alongside the
# script into sys._MEIPASS — fall back to the repo path in dev.
_BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", _REPO_ROOT))
_FRONTEND_DIST = _BUNDLE_ROOT / "frontend" / "dist"


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)

    # Game data is read-only and large-ish — load once at startup.
    data = load_game_data(DEFAULT_DATA_PATH)

    @app.get("/api/islands")
    def api_islands():
        islands = _visible_islands(data)
        groups = [
            {"label": g["label"], "islands": list(g["islands"])}
            for g in ISLAND_GROUPS
        ]
        return jsonify({"islands": islands, "groups": groups})

    @app.get("/api/box-monsters")
    def api_box_monsters():
        out: list[dict] = []
        for m in list_box_monsters(data):
            cat = _categorize_box(m)
            if cat is None:
                continue
            out.append({**m, "category": cat})
        return jsonify({
            "monsters":   out,
            "categories": list(BOX_CATEGORY_ORDER),
        })

    @app.get("/api/settings")
    def api_get_settings():
        # Targets are deliberately NOT returned — they're session-only.
        if not DEFAULT_CONFIG_PATH.exists():
            return jsonify(_empty_settings())
        try:
            cfg = load_config(DEFAULT_CONFIG_PATH)
        except Exception as e:
            return jsonify({"error": f"Failed to load config: {e}", **_empty_settings()}), 200

        # Re-key islands by internal name so the frontend has a stable key.
        islands_internal: dict[str, dict] = {}
        for name, c in (cfg.get("islands") or {}).items():
            internal = _resolve_internal_name(name)
            if internal:
                islands_internal[internal] = {
                    "structures": int(c.get("structures", 1)),
                    "enhanced":   bool(c.get("enhanced", False)),
                }

        return jsonify({
            "islands":          islands_internal,
            "targets":          {},
            "include_non_rare": bool(cfg.get("include_non_rare", True)),
        })

    @app.post("/api/settings")
    def api_save_settings():
        payload = request.get_json(silent=True) or {}
        settings = _normalize_payload(payload)
        save_config(DEFAULT_CONFIG_PATH, settings)
        return jsonify({"ok": True})

    @app.post("/api/generate")
    def api_generate():
        payload = request.get_json(silent=True) or {}
        settings = _normalize_payload(payload)

        if not settings["islands"]:
            return jsonify({"error": "No owned islands selected."}), 400
        if not settings["targets"]:
            return jsonify({"error": "Pick at least one box monster."}), 400

        # Persist before generating so a crash doesn't lose the selection.
        save_config(DEFAULT_CONFIG_PATH, settings)

        island_configs = resolve_island_configs(data["islands"], settings["islands"])
        if not island_configs:
            return jsonify({"error": "Selected islands did not resolve in game data."}), 400

        # Write to a temp file (xlsxwriter wants a path), then stream it.
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            result = build_plan_workbook(
                data,
                settings["targets"],
                island_configs,
                tmp_path,
                include_non_rare=settings["include_non_rare"],
            )
            buf = io.BytesIO(tmp_path.read_bytes())
        except PlanError as e:
            details = dict(e.details or {})
            # Hide islands that aren't selectable in the UI from the suggestions.
            if e.code == "missing_islands":
                visible_names = {isl["display_name"] for isl in _visible_islands(data)}
                for t in details.get("missing_by_target", []):
                    for m in t.get("missing", []):
                        m["available_on"] = [n for n in m["available_on"] if n in visible_names]
            return jsonify({
                "error":   e.code,
                "message": e.message,
                "details": details,
            }), 400
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass

        buf.seek(0)
        resp = send_file(
            buf,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name="breeding_plan.xlsx",
        )
        # Summary fields piggy-backed on response headers so the client can show
        # a status toast without needing a second request.
        resp.headers["X-Plan-Rows"]         = str(result["total_rows"])
        resp.headers["X-Plan-Islands-Used"] = str(result["islands_used"])
        resp.headers["X-Plan-Skipped"]      = str(len(result.get("skipped_non_rare") or []))
        return resp

    # ── Static frontend (production) ──────────────────────────────────────
    if _FRONTEND_DIST.exists():
        @app.get("/")
        def index():
            return send_from_directory(_FRONTEND_DIST, "index.html")

        @app.get("/<path:filename>")
        def static_asset(filename: str):
            full = _FRONTEND_DIST / filename
            if full.exists() and full.is_file():
                return send_from_directory(_FRONTEND_DIST, filename)
            # SPA fallback for client-side routes
            return send_from_directory(_FRONTEND_DIST, "index.html")
    else:
        @app.get("/")
        def index_missing():
            return (
                "<h1>Frontend not built</h1>"
                "<p>Run <code>cd frontend && npm install && npm run dev</code> "
                "for development, or <code>npm run build</code> for production.</p>",
                200,
            )

    return app


# ── Helpers ───────────────────────────────────────────────────────────────────

def _empty_settings() -> dict[str, Any]:
    return {"islands": {}, "targets": {}, "include_non_rare": True}


def _resolve_internal_name(user_name: str) -> str | None:
    n = str(user_name).strip()
    return n if n.startswith("ISLAND_") else None


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept the UI's JSON shape and produce the planner's expected dict."""
    raw_islands = payload.get("islands") or {}
    islands: dict[str, dict] = {}
    for name, cfg in raw_islands.items():
        internal = _resolve_internal_name(str(name)) or str(name)
        islands[internal] = {
            "structures": max(1, int((cfg or {}).get("structures", 1) or 1)),
            "enhanced":   bool((cfg or {}).get("enhanced", False)),
        }

    raw_targets = payload.get("targets") or {}
    if isinstance(raw_targets, list):
        from collections import Counter
        targets = dict(Counter(int(x) for x in raw_targets))
    else:
        targets = {int(k): int(v) for k, v in raw_targets.items() if int(v) > 0}

    return {
        "targets":          targets,
        "islands":          islands,
        "include_non_rare": bool(payload.get("include_non_rare", True)),
    }


def main() -> None:
    import argparse
    import os
    import threading
    import webbrowser

    parser = argparse.ArgumentParser(description="Run the MSM breeding-planner web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't auto-open the browser on startup.")
    args = parser.parse_args()

    app = create_app()

    if not _FRONTEND_DIST.exists():
        print(
            "⚠ frontend/dist not found. Build the UI once with:\n"
            "    cd frontend && npm install && npm run build\n"
        )

    pretty_host = "localhost" if args.host in ("127.0.0.1", "0.0.0.0") else args.host
    url = f"http://{pretty_host}:{args.port}"

    # In Flask debug mode the reloader spawns a child process — only open the
    # browser from the child to avoid two tabs.
    is_reloader_child = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    should_open = not args.no_browser and (not args.debug or is_reloader_child)
    if should_open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    print(f"\nMSM Breeding Planner → {url}")
    print("Press Ctrl-C to stop.\n")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
