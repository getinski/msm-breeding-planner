"""
plan_breeding.py

Generates a per-island Excel breeding plan for filling box monsters
(Wubboxes, Amber Island, Wublins, etc.).  If anything in the requirements
can't be obtained on the selected islands, the planner raises PlanError so
the caller can tell the user which island to add.

Checkboxes use the native Excel 365 checkbox format via xlsxwriter.

Reads the offline game database from game_data.json (shipped with the repo).
The web UI (server.py) drives this module — config is loaded/saved via
load_config / save_config and plans are produced via build_plan_workbook.
"""

from __future__ import annotations

import json
import sys
import tomllib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import xlsxwriter


_REPO_ROOT = Path(__file__).resolve().parent

# When frozen by PyInstaller, bundled read-only data is extracted to
# sys._MEIPASS at runtime; user-writable files live next to the executable
# so they survive between launches.
_FROZEN = getattr(sys, "frozen", False)
_BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", _REPO_ROOT))
_USER_ROOT = Path(sys.executable).parent if _FROZEN else _REPO_ROOT

DEFAULT_DATA_PATH = _BUNDLE_ROOT / "game_data.json"
DEFAULT_CONFIG_PATH = _USER_ROOT / "breeding_config.conf"

ENHANCED_MULTIPLIER = 0.75  # Enhanced breeding structures run at 75% of normal time.

# ── Island helpers ────────────────────────────────────────────────────────────

def island_display_name(isl: dict[str, Any]) -> str:
    """Return the island's display_name (computed in the fetcher), with
    fallbacks if the data was produced by an older fetcher."""
    if not isinstance(isl, dict):
        return str(isl)
    name = isl.get("display_name")
    if name:
        return name
    internal = isl.get("name") or ""
    label = internal.removeprefix("ISLAND_").replace("_", " ").strip()
    return f"Island {label}" if label else (internal or "?")


# ── Dangerous breeding combos ─────────────────────────────────────────────────
# Each tuple is (quad_id, partner_id).  These are the documented quad-fail pairs:
# breeding them produces the partner most of the time, and the quad occasionally.
# That's exactly what you want when the quad IS the target — and exactly what you
# want to AVOID when the partner (a double) is the target.

DANGEROUS_COMBO_IDS: list[tuple[int, int]] = [
    (29,  14),   # Entbrat + Drumpler
    (27,   9),   # Deedge + Pango
    (28,   8),   # Riff + Quibble
    (28,  13),   # Riff + Fwog
    (25,  11),   # Shellbeat + Oaktopus
    (26,   6),   # Quarrister + Dandidoo
    (275, 263),  # Tring + Stogg
    (282, 285),  # Sneyser + Phangler
    (478, 468),  # Blow't + Furcorn (Fire Haven)
    (411, 299),  # Gloptic + Oaktopus (Fire Haven)
    (424, 415),  # Pladdie + Drumpler (Fire Haven)
    (444, 435),  # Plinkajou + Fwog (Fire Haven)
]

_DANGEROUS_PAIRS: frozenset[frozenset] = frozenset(
    frozenset(pair) for pair in DANGEROUS_COMBO_IDS
)
_QUAD_IDS: frozenset[int] = frozenset(pair[0] for pair in DANGEROUS_COMBO_IDS)

# Tab order in the generated spreadsheet — each main island is followed by its
# mirror counterpart (where one exists).  Islands not in this list fall to the
# bottom in island_id order.
SHEET_ISLAND_ORDER: tuple[str, ...] = (
    "ISLAND_1",        "ISLAND_1_MIRROR",
    "ISLAND_2",        "ISLAND_2_MIRROR",
    "ISLAND_3",        "ISLAND_3_MIRROR",
    "ISLAND_4",        "ISLAND_4_MIRROR",
    "ISLAND_5",        "ISLAND_5_MIRROR",
    "ISLAND_FIRE",
    "ISLAND_14",
    "ISLAND_18",       "ISLAND_18_MIRROR",
    "ISLAND_15",       "ISLAND_15_MIRROR",
    "ISLAND_16",       "ISLAND_16_MIRROR",
    "ISLAND_17",       "ISLAND_17_MIRROR",
)


# ── Data builders ─────────────────────────────────────────────────────────────

def resolve_island_configs(
    raw_islands: list[dict],
    island_settings: dict[str, dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Map internal island names (or numeric ids) → {structures, enhanced}."""
    internal_to_id = {isl["name"]: isl["island_id"] for isl in raw_islands}
    out: dict[int, dict[str, Any]] = {}
    for name, cfg in island_settings.items():
        n = str(name).strip()
        try:
            iid: int | None = int(n)
        except ValueError:
            iid = internal_to_id.get(n.upper())
        if iid is None:
            print(f"  ⚠ Unknown island '{n}' — not found in game data.")
            continue
        out[iid] = {
            "structures": max(1, int(cfg.get("structures", 1) or 1)),
            "enhanced":   bool(cfg.get("enhanced", False)),
        }
    return out


def _build_breeding_index(raw_breeding: list[dict]) -> dict[int, list[tuple[int, int]]]:
    idx: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for rec in raw_breeding:
        a, b, c = rec.get("a"), rec.get("b"), rec.get("c")
        if a and b and c:
            idx[c].append((a, b))
    return idx


def _build_m2i(raw_islands: list[dict]) -> dict[int, set[int]]:
    m2i: dict[int, set[int]] = defaultdict(set)
    for isl in raw_islands:
        iid = isl["island_id"]
        for m in isl.get("monsters") or []:
            m2i[m["monster"]].add(iid)
    return m2i


def _build_variant_index(raw_monsters: list[dict]) -> dict[int, tuple[int, ...]]:
    """Map each monster id → the tuple of all ids that are the *same* monster.

    The game gives island-specific re-skins their own ids — e.g. "Noggin"
    (id 3, Plant Island), "Noggin Composer Island" (id 202) and "Noggin Fire
    Island" (id 264) are three distinct ids for one monster.  Box requirements
    reference only the base id, so without this map the planner can never use a
    Fire/Faerie/Bone island to breed a required natural, and those islands sit
    idle.  Variants share display_name + class (and, in this data, genes), so
    that pair is the grouping key.  Singletons map to a one-element tuple.
    """
    groups: dict[tuple, list[int]] = defaultdict(list)
    for m in raw_monsters:
        key = (m.get("display_name") or m.get("common_name"), m.get("class"))
        groups[key].append(m["monster_id"])
    out: dict[int, tuple[int, ...]] = {}
    for ids in groups.values():
        shared = tuple(ids)
        for i in ids:
            out[i] = shared
    return out


# ── Breeding resolution ───────────────────────────────────────────────────────

def _find_recipes_per_island(
    mid: int,
    breeding_index: dict[int, list[tuple[int, int]]],
    m2i: dict[int, set[int]],
    owned: set[int],
    monster_genes: dict[int, str],
    raw_m: dict,
) -> dict[int, tuple[int, int]]:
    """Return the best (parent_a, parent_b) recipe for mid on each owned island.

    Scoring policy (lower wins):
      - Quad target → the documented dangerous pair, on any island it's valid.
      - Triple / non-listed double / single → self + island-quad (quad-fail).
      - Double listed as a dangerous-pair partner → avoid quad-fail; the gene-
        length tie-breaker naturally prefers single+single.
    """
    per_island: dict[int, tuple[float, int, int]] = {}

    for pa, pb in breeding_index.get(mid, []):
        is_quad_fail = (pa == mid and pb in _QUAD_IDS) or (pb == mid and pa in _QUAD_IDS)
        is_dangerous = frozenset({pa, pb}) in _DANGEROUS_PAIRS

        # A self-pair only earns its slot if it's the quad-fail recipe, or —
        # when the target itself is a quad — the documented dangerous pair.
        if (pa == mid or pb == mid) and not is_quad_fail:
            if not (mid in _QUAD_IDS and is_dangerous):
                continue

        valid = (
            m2i.get(pa, set())
            & m2i.get(pb, set())
            & m2i.get(mid, set())
            & owned
        )
        if not valid:
            continue

        for iid in valid:
            if is_dangerous and mid in _QUAD_IDS:
                score: float = -1000.0
            elif is_dangerous:
                # Listed dangerous pair for a non-quad target — produces the
                # quad too often.  Fall back to the gene-length scored options.
                score = 999999.0
            elif is_quad_fail:
                score = -1000.0
            else:
                score = float(len(monster_genes.get(pa, "")) + len(monster_genes.get(pb, "")))

            if iid not in per_island or score < per_island[iid][0]:
                per_island[iid] = (score, pa, pb)

    if per_island:
        return {iid: (pa, pb) for iid, (_, pa, pb) in per_island.items()}

    # Fallback: mid has no usable recipe of its own (rare — usually a target
    # with empty genes).  Pick the longest recipe that runs on a home island
    # so the slot at least incubates something productive.
    if len(monster_genes.get(mid, "")) > 1:
        return {}
    mid_islands = m2i.get(mid, set()) & owned
    if not mid_islands:
        return {}

    best_bt_per_island: dict[int, tuple[int, int, int]] = {}
    for result_mid, pairs in breeding_index.items():
        if result_mid == mid:
            continue
        for pa, pb in pairs:
            if pa == mid or pb == mid:
                continue
            if frozenset({pa, pb}) in _DANGEROUS_PAIRS:
                continue
            valid = m2i.get(pa, set()) & m2i.get(pb, set()) & mid_islands
            if not valid:
                continue
            bt = raw_m.get(result_mid, {}).get("build_time") or 0
            for iid in valid:
                if iid not in best_bt_per_island or bt > best_bt_per_island[iid][0]:
                    best_bt_per_island[iid] = (bt, pa, pb)

    return {iid: (pa, pb) for iid, (_, pa, pb) in best_bt_per_island.items()}


def _find_recipes_grouped(
    mid: int,
    variant_ids: dict[int, tuple[int, ...]],
    breeding_index: dict[int, list[tuple[int, int]]],
    m2i: dict[int, set[int]],
    owned: set[int],
    monster_genes: dict[int, str],
    raw_m: dict,
) -> dict[int, tuple[int, int]]:
    """Per-island recipes for mid, counting any island-variant of it as a fill.

    Resolves recipes for every variant id (same monster, different island skin)
    and unions them by island.  A required Noggin can then be bred on Fire Haven
    via its "Noggin Fire Island" recipe, so owned Fire/Faerie/Bone islands carry
    their share of the work instead of sitting idle.  Variants live on disjoint
    islands almost always; on the rare overlap, the first variant scheduled on an
    island keeps the slot (both yield the same monster, so it doesn't matter)."""
    per_island: dict[int, tuple[int, int]] = {}
    for vid in variant_ids.get(mid, (mid,)):
        sub = _find_recipes_per_island(vid, breeding_index, m2i, owned, monster_genes, raw_m)
        for iid, pair in sub.items():
            per_island.setdefault(iid, pair)
    return per_island


def _distribute(
    required_counts: Counter,
    breeding_index: dict,
    m2i: dict,
    island_configs: dict[int, dict[str, Any]],
    monster_genes: dict[int, str],
    cant_breed: set[int],
    raw_m: dict,
    variant_ids: dict[int, tuple[int, ...]],
    list_only: set[int] | None = None,
) -> tuple[dict[int, list[tuple]], set[int], set[int]]:
    """Schedule every required breed across the owned islands.

    Each island has N parallel slots (one per breeding structure).  Tasks are
    sorted longest-first and assigned to the (island, slot) with the earliest
    available finish time — classic LPT.  Enhanced structures run breeds at
    ENHANCED_MULTIPLIER × the base build_time.

    Monsters in list_only are still placed on an owned home island (so they
    appear in the plan and still occupy a structure for the time estimate), but
    with no parent recipe — the parent cells come out blank because the user
    sources these directly.  This is how the "recipe guide" toggle, when off,
    keeps every required monster in the plan without spelling out its parents.

    Returns (island_rows, directly_obtainable, unobtainable).  A monster in
    cant_breed (Wubboxes, Wublins, …) whose home island is owned counts as
    directly_obtainable and skips scheduling.  Anything else with no valid
    recipe lands in unobtainable, which callers report to the user.
    """
    owned: set[int] = set(island_configs.keys())
    list_only = list_only or set()
    island_rows: dict[int, list[tuple]] = defaultdict(list)
    directly_obtainable: set[int] = set()
    unobtainable: set[int] = set()

    tasks: list[tuple[int, int, dict[int, tuple], int, int]] = []
    for mid, count in required_counts.items():
        if mid in cant_breed and (m2i.get(mid, set()) & owned):
            directly_obtainable.add(mid)
            continue

        if mid in list_only:
            # No recipe — just needs to live on one of its owned home islands
            # (counting island-variants, so Fire/Faerie/Bone islands qualify).
            home: set[int] = set()
            for vid in variant_ids.get(mid, (mid,)):
                home |= m2i.get(vid, set()) & owned
            if not home:
                unobtainable.add(mid)
                continue
            per_island = {iid: (None, None) for iid in home}
        else:
            per_island = _find_recipes_grouped(
                mid, variant_ids, breeding_index, m2i, owned, monster_genes, raw_m
            )
            if not per_island:
                unobtainable.add(mid)
                continue

        bt = raw_m.get(mid, {}).get("build_time") or 0
        for i in range(count):
            tasks.append((bt, mid, per_island, i + 1, count))

    tasks.sort(key=lambda t: t[0], reverse=True)

    slot_loads: dict[int, list[float]] = {
        iid: [0.0] * cfg["structures"] for iid, cfg in island_configs.items()
    }

    for bt, mid, per_island, copy_n, total in tasks:
        best_iid: int | None = None
        best_slot: int = 0
        best_finish: float = float("inf")
        best_effective: float = 0.0
        for iid in per_island:
            if iid not in slot_loads or not slot_loads[iid]:
                continue
            slots = slot_loads[iid]
            slot_idx = min(range(len(slots)), key=lambda s: slots[s])
            mult = ENHANCED_MULTIPLIER if island_configs[iid]["enhanced"] else 1.0
            effective = bt * mult
            finish = slots[slot_idx] + effective
            if finish < best_finish:
                best_finish = finish
                best_iid = iid
                best_slot = slot_idx
                best_effective = effective

        if best_iid is None:
            unobtainable.add(mid)
            continue

        pa, pb = per_island[best_iid]
        island_rows[best_iid].append((mid, pa, pb, copy_n, total, best_effective))
        slot_loads[best_iid][best_slot] += best_effective

    for rows in island_rows.values():
        rows.sort(key=lambda r: r[5], reverse=True)

    return island_rows, directly_obtainable, unobtainable


# ── Errors ────────────────────────────────────────────────────────────────────

class PlanError(Exception):
    """User-input error the UI should render — code identifies the case,
    details carries any structured info the frontend needs to show."""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


# ── Workbook builder ──────────────────────────────────────────────────────────

def build_plan_workbook(
    data: dict[str, Any],
    targets: Counter | dict[int, int] | list[int],
    island_configs: dict[int, dict[str, Any]],
    out_path: Path,
    *,
    include_recipe_guide: bool = True,
) -> dict[str, Any]:
    """Write the breeding plan to out_path and return a small summary dict
    (row counts, monsters skipped as directly obtainable, and — when
    include_recipe_guide=False — the monsters listed without a parent recipe)."""
    raw_monsters = data["monsters"]
    raw_islands = data["islands"]
    raw_breeding = data["breeding"]
    cant_breed: set[int] = set(data.get("cant_breed_ids") or [])

    raw_m: dict[int, dict] = {m["monster_id"]: m for m in raw_monsters}
    monster_genes: dict[int, str] = {m["monster_id"]: m.get("genes") or "" for m in raw_monsters}
    m2i = _build_m2i(raw_islands)
    variant_ids = _build_variant_index(raw_monsters)
    id_to_display: dict[int, str] = {isl["island_id"]: island_display_name(isl) for isl in raw_islands}
    breeding_index = _build_breeding_index(raw_breeding)

    if not island_configs:
        raise ValueError("No valid owned islands resolved — check settings.")

    if isinstance(targets, list):
        target_counts: Counter = Counter(targets)
    else:
        target_counts = Counter()
        target_counts.update(dict(targets))

    def mname(mid: int) -> str:
        m = raw_m.get(mid, {})
        return m.get("display_name") or m.get("common_name") or str(mid)

    required_by_target: dict[int, Counter] = {}
    target_multipliers: dict[int, int] = {}
    all_required: Counter = Counter()

    for tid, mult in target_counts.items():
        if mult <= 0:
            continue
        traw = raw_m.get(tid)
        if not traw:
            print(f"  ⚠ Monster {tid} not in game data — skipping.")
            continue
        reqs_str = traw.get("box_monster_requirements")
        if not reqs_str:
            print(f"  ⚠ {mname(tid)} (id={tid}) has no box requirements — skipping.")
            continue
        scaled = Counter({mid: cnt * mult for mid, cnt in Counter(json.loads(reqs_str)).items()})
        required_by_target[tid] = scaled
        target_multipliers[tid] = mult
        all_required += scaled
        label = f"{mname(tid)} ×{mult}" if mult > 1 else mname(tid)
        print(f"  {label}: {sum(scaled.values())} requirements ({len(scaled)} unique)")

    if not required_by_target:
        raise ValueError("No valid targets with box requirements found.")

    # With the recipe guide off, every required monster stays in the plan as a
    # line-item but without a spelled-out recipe — the user breeds/buys them
    # however they like, so the parent cells come out blank.
    list_only: set[int] = set()
    if not include_recipe_guide:
        list_only = set(all_required)
        if list_only:
            print(f"  Recipe guide off — {len(list_only)} monster type(s) listed "
                  f"without parents")

    island_rows, directly_obtainable, unobtainable = _distribute(
        all_required, breeding_index, m2i, island_configs,
        monster_genes, cant_breed, raw_m, variant_ids, list_only,
    )

    # If anything's genuinely unreachable on the owned islands, bail out with a
    # structured error so the UI can suggest which island to add.
    if unobtainable:
        id_to_display_full: dict[int, str] = {
            isl["island_id"]: island_display_name(isl) for isl in raw_islands
        }
        missing_by_target: list[dict] = []
        for tid, reqs in required_by_target.items():
            missing = []
            for req_mid in sorted(reqs, key=lambda m: mname(m)):
                if req_mid not in unobtainable:
                    continue
                available_iids: set[int] = set()
                for vid in variant_ids.get(req_mid, (req_mid,)):
                    available_iids |= m2i.get(vid, set())
                missing.append({
                    "monster_id":   req_mid,
                    "display_name": mname(req_mid),
                    "available_on": sorted(
                        id_to_display_full.get(iid, f"Island {iid}")
                        for iid in available_iids
                    ),
                })
            if missing:
                missing_by_target.append({
                    "target_id":   tid,
                    "target_name": mname(tid),
                    "missing":     missing,
                })

        n_types = len(unobtainable)
        raise PlanError(
            code="missing_islands",
            message=(
                f"Cannot generate plan: {n_types} required monster "
                f"type{'s' if n_types != 1 else ''} cannot be obtained on your owned islands."
            ),
            details={"missing_by_target": missing_by_target},
        )

    # Directly-obtainable monsters are intentionally skipped — the user buys
    # them.  Surface that in the console for the CLI run, but it's not an error.
    if directly_obtainable:
        print(f"\n  {len(directly_obtainable)} required type(s) skipped (directly obtainable on owned islands):")
        for mid in sorted(directly_obtainable, key=lambda m: mname(m)):
            print(f"    {mname(mid)} ×{all_required[mid]}")

    def needed_for(mid: int) -> str:
        parts: list[str] = []
        for t, c in required_by_target.items():
            if c.get(mid, 0) > 0:
                mult = target_multipliers.get(t, 1)
                parts.append(f"{mname(t)} ×{mult}" if mult > 1 else mname(t))
        return ", ".join(parts)

    wb = xlsxwriter.Workbook(str(out_path))

    hdr_fmt = wb.add_format({
        "bold": True, "font_color": "white", "bg_color": "#1F4E79",
        "align": "center", "valign": "vcenter", "border": 1,
    })
    batch_fmts = [
        wb.add_format({"bg_color": "#DCE6F1", "valign": "vcenter"}),
        wb.add_format({"bg_color": "#FFFFFF",  "valign": "vcenter"}),
    ]
    center_fmts = [
        wb.add_format({"bg_color": "#DCE6F1", "valign": "vcenter", "align": "center"}),
        wb.add_format({"bg_color": "#FFFFFF",  "valign": "vcenter", "align": "center"}),
    ]
    num_decimal_fmts = [
        wb.add_format({"bg_color": "#DCE6F1", "valign": "vcenter", "align": "center", "num_format": "0.00"}),
        wb.add_format({"bg_color": "#FFFFFF",  "valign": "vcenter", "align": "center", "num_format": "0.00"}),
    ]
    total_label_fmt = wb.add_format({
        "bold": True, "align": "right", "valign": "vcenter", "bg_color": "#FFE699",
    })
    total_num_fmt = wb.add_format({
        "bold": True, "align": "center", "valign": "vcenter",
        "bg_color": "#FFE699", "num_format": "0.00",
    })
    bold_fmt = wb.add_format({"bold": True, "valign": "vcenter"})
    num_fmt  = wb.add_format({"align": "center", "valign": "vcenter"})

    def _write_island_sheet(island_id: int, rows: list[tuple]) -> None:
        cfg = island_configs[island_id]
        slots = cfg["structures"]
        enhanced = cfg["enhanced"]
        tab_base = id_to_display.get(island_id, f"Island {island_id}")
        ws = wb.add_worksheet(tab_base[:31])

        info = f"{slots} structure{'s' if slots != 1 else ''}" + (" (Enhanced ×0.75)" if enhanced else "")
        ws.merge_range(0, 0, 0, 6, f"{tab_base} — {info}", hdr_fmt)
        ws.set_row(0, 22)

        headers = ["Done", "Monster", "Parent A", "Parent B", "Copy", "Needed For", "Breed Time (h)"]
        for ci, h in enumerate(headers):
            ws.write(1, ci, h, hdr_fmt)
        ws.freeze_panes(2, 0)
        ws.set_row(1, 18)

        col_widths = [len(h) for h in headers]

        for ri, (mid, pa, pb, copy_n, total, effective_secs) in enumerate(rows, start=2):
            batch = (ri - 2) // max(slots, 1) + 1
            bfmt   = batch_fmts[(batch - 1) % 2]
            cfmt   = center_fmts[(batch - 1) % 2]
            numfmt = num_decimal_fmts[(batch - 1) % 2]

            copy_label  = f"{copy_n}/{total}" if total > 1 else ""
            breed_hours = effective_secs / 3600.0
            nf_label    = needed_for(mid)

            pa_name  = mname(pa) if pa is not None else ""
            pb_name  = mname(pb) if pb is not None else ""
            res_name = mname(mid)

            ws.insert_checkbox(ri, 0, False)
            ws.write(ri, 1, res_name,   bfmt)
            ws.write(ri, 2, pa_name,    bfmt)
            ws.write(ri, 3, pb_name,    bfmt)
            ws.write(ri, 4, copy_label, cfmt)
            ws.write(ri, 5, nf_label,   bfmt)
            ws.write_number(ri, 6, breed_hours, numfmt)

            for ci, val in enumerate(
                [res_name, pa_name, pb_name, copy_label, nf_label, f"{breed_hours:.2f}"],
                start=1,
            ):
                col_widths[ci] = max(col_widths[ci], len(str(val)))

        if rows:
            n = len(rows)
            data_first_excel = 3                  # 1-indexed Excel row of first data row
            data_last_excel  = n + 2              # 1-indexed Excel row of last data row
            g_range = f"G{data_first_excel}:G{data_last_excel}"
            a_range = f"A{data_first_excel}:A{data_last_excel}"

            total_row     = n + 2                 # 0-indexed for xlsxwriter
            bred_row      = n + 3
            remaining_row = n + 4
            total_excel   = total_row + 1
            bred_excel    = bred_row + 1

            ws.write(total_row, 5, "Total Breed Time (h)", total_label_fmt)
            ws.write_formula(total_row, 6, f"=SUM({g_range})", total_num_fmt)

            ws.write(bred_row, 5, "Bred Time (h)", total_label_fmt)
            ws.write_formula(bred_row, 6, f"=SUMIF({a_range},TRUE,{g_range})", total_num_fmt)

            ws.write(remaining_row, 5, "Remaining Time (h)", total_label_fmt)
            ws.write_formula(
                remaining_row, 6,
                f"=G{total_excel}-G{bred_excel}",
                total_num_fmt,
            )

        ws.set_column(0, 0, 7)
        ws.set_column(4, 4, 7)
        ws.set_column(6, 6, 16)
        for ci in (1, 2, 3, 5):
            ws.set_column(ci, ci, min(col_widths[ci] + 2, 40))

    ws_sum = wb.add_worksheet("Summary")
    sum_headers = ["Target Monster", "ID", "Required Monsters"]
    for ci, h in enumerate(sum_headers):
        ws_sum.write(0, ci, h, hdr_fmt)
    ws_sum.freeze_panes(1, 0)

    n_targets = 0
    for ri, (tid, rc) in enumerate(required_by_target.items(), start=1):
        mult  = target_multipliers.get(tid, 1)
        label = f"{mname(tid)} ×{mult}" if mult > 1 else mname(tid)
        total = sum(rc.values())
        ws_sum.write(ri, 0, label, bold_fmt)
        ws_sum.write(ri, 1, tid,   num_fmt)
        ws_sum.write(ri, 2, total, num_fmt)
        n_targets += 1

    ws_sum.set_column(0, 0, 35)
    ws_sum.set_column(1, 2, 18)

    id_to_internal: dict[int, str] = {isl["island_id"]: isl.get("name") or "" for isl in raw_islands}
    sheet_order_index = {name: i for i, name in enumerate(SHEET_ISLAND_ORDER)}
    fallback_index = len(SHEET_ISLAND_ORDER)

    def _sheet_sort_key(item: tuple[int, list]) -> tuple[int, int]:
        island_id = item[0]
        internal = id_to_internal.get(island_id, "")
        idx = sheet_order_index.get(internal, fallback_index)
        return (idx, island_id)

    sheet_info: list[tuple[str, int]] = []  # (sheet name, data-row count)
    for island_id, rows in sorted(island_rows.items(), key=_sheet_sort_key):
        _write_island_sheet(island_id, rows)
        name = id_to_display.get(island_id, f"Island {island_id}")[:31]
        sheet_info.append((name, len(rows)))

    # ── Summary totals block (calculated fields) ─────────────────────────────
    # Written after island sheets so we know their names and row counts for the
    # cross-sheet formula refs.
    pct_fmt = wb.add_format({
        "bold": True, "align": "center", "valign": "vcenter",
        "bg_color": "#FFE699", "num_format": "0.00%",
    })
    int_total_fmt = wb.add_format({
        "bold": True, "align": "center", "valign": "vcenter",
        "bg_color": "#FFE699",
    })
    decimal_total_fmt = wb.add_format({
        "bold": True, "align": "center", "valign": "vcenter",
        "bg_color": "#FFE699", "num_format": "0.00",
    })

    def _esc(name: str) -> str:
        return name.replace("'", "''")

    def _bred_monsters_formula() -> str:
        # Excel's SUM ignores boolean values — COUNTIF(range, TRUE) is what
        # works against the boolean checkbox cells in column A of each sheet.
        if not sheet_info:
            return "=0"
        parts = [f"COUNTIF('{_esc(n)}'!A:A,TRUE)" for n, _ in sheet_info]
        return "=" + "+".join(parts)

    def _total_time_formula() -> str:
        # Sum each island's data rows (G3:G{n+2}) — *not* the whole G column,
        # which would double-count the per-island Total/Bred/Remaining cells.
        parts = [
            f"SUM('{_esc(n)}'!G3:G{cnt + 2})"
            for n, cnt in sheet_info if cnt > 0
        ]
        return "=" + "+".join(parts) if parts else "=0"

    def _bred_time_formula() -> str:
        parts = [
            f"SUMIF('{_esc(n)}'!A3:A{cnt + 2},TRUE,'{_esc(n)}'!G3:G{cnt + 2})"
            for n, cnt in sheet_info if cnt > 0
        ]
        return "=" + "+".join(parts) if parts else "=0"

    # Row layout (0-indexed):
    #   blank
    #   Total Requirements / Bred Monsters / To Breed / Monsters Percentage
    #   blank
    #   Total Breed Time / Bred Time / Remaining Time / Time Percentage
    base = n_targets + 1
    reqs_row  = base + 1
    bredm_row = base + 2
    tobreed_row = base + 3
    monpct_row = base + 4

    ttime_row = monpct_row + 2
    btime_row = ttime_row + 1
    rtime_row = ttime_row + 2
    tpct_row  = ttime_row + 3

    reqs_excel  = reqs_row + 1
    bredm_excel = bredm_row + 1
    ttime_excel = ttime_row + 1
    btime_excel = btime_row + 1

    # Monsters block
    ws_sum.write(reqs_row, 1, "Total Requirements", total_label_fmt)
    ws_sum.write_formula(reqs_row, 2, f"=SUM(C2:C{n_targets + 1})", int_total_fmt)

    ws_sum.write(bredm_row, 1, "Bred Monsters", total_label_fmt)
    ws_sum.write_formula(bredm_row, 2, _bred_monsters_formula(), int_total_fmt)

    ws_sum.write(tobreed_row, 1, "To Breed", total_label_fmt)
    ws_sum.write_formula(
        tobreed_row, 2,
        f"=C{reqs_excel}-C{bredm_excel}",
        int_total_fmt,
    )

    ws_sum.write(monpct_row, 1, "Monsters Percentage", total_label_fmt)
    ws_sum.write_formula(
        monpct_row, 2,
        f"=IF(C{reqs_excel}=0,0,C{bredm_excel}/C{reqs_excel})",
        pct_fmt,
    )

    # Time block
    ws_sum.write(ttime_row, 1, "Total Breed Time (h)", total_label_fmt)
    ws_sum.write_formula(ttime_row, 2, _total_time_formula(), decimal_total_fmt)

    ws_sum.write(btime_row, 1, "Bred Time (h)", total_label_fmt)
    ws_sum.write_formula(btime_row, 2, _bred_time_formula(), decimal_total_fmt)

    ws_sum.write(rtime_row, 1, "Remaining Time (h)", total_label_fmt)
    ws_sum.write_formula(
        rtime_row, 2,
        f"=C{ttime_excel}-C{btime_excel}",
        decimal_total_fmt,
    )

    ws_sum.write(tpct_row, 1, "Time Percentage", total_label_fmt)
    ws_sum.write_formula(
        tpct_row, 2,
        f"=IF(C{ttime_excel}=0,0,C{btime_excel}/C{ttime_excel})",
        pct_fmt,
    )

    wb.close()

    total_rows = sum(len(r) for r in island_rows.values())
    print(f"\n  {total_rows} breed instructions across {len(island_rows)} island(s)")

    return {
        "total_rows":           total_rows,
        "islands_used":         len(island_rows),
        "directly_obtainable":  sorted(directly_obtainable),
        "listed_without_recipe": sorted(list_only),
    }


# ── Public listings (used by UI too) ──────────────────────────────────────────

def list_islands(data: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for isl in sorted(data["islands"], key=lambda x: x["island_id"]):
        out.append({
            "id":            isl["island_id"],
            "internal_name": isl["name"],
            "display_name":  island_display_name(isl),
        })
    return out


def list_box_monsters(data: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in sorted(data["monsters"], key=lambda x: x.get("display_name") or x["common_name"]):
        reqs_str = m.get("box_monster_requirements")
        if not reqs_str:
            continue
        reqs = json.loads(reqs_str)
        c = Counter(reqs)
        out.append({
            "id":            m["monster_id"],
            "common_name":   m["common_name"],
            "display_name":  m.get("display_name") or m["common_name"],
            "class":         m.get("class") or "",
            "total_reqs":    sum(c.values()),
            "unique_reqs":   len(c),
        })
    return out


# ── Config loading ────────────────────────────────────────────────────────────

def load_game_data(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(
            f"Game database not found at {path}.\n"
            f"Run fetch_game_data.py first to download it."
        )
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Normalize a loaded TOML config into the planner's expected shape.

    Expected schema:
        include_recipe_guide = true
        [islands.ISLAND_1]
        structures = 2
        enhanced = false
    """
    islands_cfg: dict[str, dict[str, Any]] = {}
    for name, val in (cfg.get("islands") or {}).items():
        if isinstance(val, dict):
            islands_cfg[name] = {
                "structures": int(val.get("structures", 1)),
                "enhanced":   bool(val.get("enhanced", False)),
            }
        else:
            islands_cfg[name] = {"structures": 1, "enhanced": False}

    # Fall back to the old key name for configs written before the rename.
    recipe_guide = cfg.get("include_recipe_guide", cfg.get("include_non_rare_recipes", True))
    return {
        "islands":              islands_cfg,
        "include_recipe_guide": bool(recipe_guide),
    }


def save_config(path: Path, settings: dict[str, Any]) -> None:
    """Persist island ownership and the recipe-guide toggle to TOML.

    Target monsters are deliberately left out — they're a per-session choice,
    not something to carry across runs.
    """
    lines: list[str] = ["# MSM Breeding Plan Config (managed by the web UI)\n"]
    lines.append(f"include_recipe_guide = {str(bool(settings.get('include_recipe_guide', True))).lower()}\n")

    islands = settings.get("islands") or {}
    for name, cfg in islands.items():
        lines.append(f"\n[islands.{name}]\n")
        lines.append(f"structures = {int(cfg.get('structures', 1))}\n")
        lines.append(f"enhanced = {str(bool(cfg.get('enhanced', False))).lower()}\n")

    path.write_text("".join(lines), encoding="utf-8")


def load_config(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return parse_config(tomllib.load(f))
