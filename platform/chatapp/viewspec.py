"""The view-spec grammar — the contract between chat and the app runtime.

A view is NOT code. It is a declarative composition of two vocabularies:
  - functions (the verbs): named data queries in functions.py
  - components (the nouns): hand-built render primitives in static/components.js
The app-dev agent emits specs in this grammar; the runtime interprets them.
A bad generation fails validation here (with agent-readable errors) instead of
shipping a bug. Specs are stored in config_maps and claimed in the events log,
so every view is regenerable, diffable, and has provenance.
"""

from __future__ import annotations

import re

# ── The component vocabulary (the nouns) ────────────────────────────
# data_fns: which functions produce the data shape this component renders.
# props: allowed presentation knobs (all optional).
COMPONENTS = {
    "stat": {
        "desc": "One headline number (a stat tile): value + unit + your title as label.",
        "data_fns": ["agg_latest"],
        "props": {"precision": "int decimals (default 1)",
                  "unit": "override unit string"},
        "default_width": 3,
    },
    "trend": {
        "desc": "Time-series line chart, one line per series. Use for change-over-time.",
        "data_fns": ["series"],
        "props": {"unit": "y-axis unit override",
                  "precision": "int decimals in tooltip (default 1)"},
        "default_width": 6,
    },
    "bars": {
        "desc": "Horizontal bar list — ranked magnitude comparison across equipment or types.",
        "data_fns": ["agg_latest_by"],
        "props": {"precision": "int decimals (default 1)",
                  "unit": "override unit string"},
        "default_width": 6,
    },
    "table": {
        "desc": "Plain data table. Use for point-level detail or equipment inventory.",
        "data_fns": ["latest", "equipment_list", "equipment_summary", "agg_latest_by", "alarms"],
        "props": {"columns": "list of column keys to show, in order"},
        "default_width": 6,
    },
    "alarms": {
        "desc": "Active alarm/trip/fault list with status colors. Empty = all clear.",
        "data_fns": ["alarms"],
        "props": {},
        "default_width": 6,
    },
    "note": {
        "desc": "Short text block (no query) — context, reading guidance, caveats.",
        "data_fns": [],
        "props": {"text": "the text to show (required)"},
        "default_width": 12,
    },
}

# ── Argument schemas for the function vocabulary (the verbs) ────────
# The registry itself lives in functions.py; the validator only needs
# signatures. Kept together with the grammar so one file defines "valid spec".
_MATCH = ("match", str, "case-insensitive regex over point names, e.g. 'kw_active$'")
FUNCTION_ARGS = {
    "latest": {
        "required": [],
        "optional": [_MATCH, ("equipment", str, "equipment name, e.g. 'CH_1'"),
                     ("device_type", str, "device type name, e.g. 'Chiller'"),
                     ("limit", int, "max rows (default 200)")],
    },
    "agg_latest": {
        "required": [("op", ("sum", "avg", "min", "max", "count", "latest"), "aggregate op"),
                     _MATCH],
        "optional": [("equipment", str, ""), ("device_type", str, "")],
    },
    "agg_latest_by": {
        "required": [("op", ("sum", "avg", "min", "max", "count"), "aggregate op"),
                     _MATCH],
        "optional": [("by", ("equipment", "device_type"), "group key (default equipment)"),
                     ("device_type", str, ""), ("limit", int, "max bars (default 20)")],
    },
    "series": {
        "required": [_MATCH],
        "optional": [("equipment", str, ""), ("device_type", str, ""),
                     ("hours", int, "window (default 24, max 168)"),
                     ("group", ("point", "equipment", "total"), "one series per… (default point)"),
                     ("agg", ("avg", "sum", "min", "max"), "within-bucket agg (default avg)"),
                     ("max_series", int, "cap (default 6, hard max 8)")],
    },
    "equipment_list": {
        "required": [],
        "optional": [("device_type", str, ""), ("limit", int, "default 100")],
    },
    "equipment_summary": {"required": [], "optional": []},
    "alarms": {
        "required": [],
        "optional": [_MATCH, ("device_type", str, "")],
    },
}

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


def _check_args(fn: str, args: dict, path: str, errors: list):
    sig = FUNCTION_ARGS[fn]
    known = {}
    for name, typ, _ in sig["required"] + sig["optional"]:
        known[name] = typ
    for name, typ, _ in sig["required"]:
        if name not in args:
            errors.append(f"{path}: query.args missing required '{name}' for fn '{fn}'")
    for k, v in args.items():
        if k not in known:
            errors.append(f"{path}: unknown arg '{k}' for fn '{fn}' "
                          f"(allowed: {', '.join(known)})")
            continue
        typ = known[k]
        if isinstance(typ, tuple):
            if v not in typ:
                errors.append(f"{path}: arg '{k}' must be one of {list(typ)}, got {v!r}")
        elif typ is int:
            if not isinstance(v, int) or isinstance(v, bool):
                errors.append(f"{path}: arg '{k}' must be an integer, got {v!r}")
        elif not isinstance(v, typ):
            errors.append(f"{path}: arg '{k}' must be {typ.__name__}, got {v!r}")
    if "match" in args:
        try:
            re.compile(args["match"])
        except re.error as e:
            errors.append(f"{path}: arg 'match' is not a valid regex: {e}")


def validate(spec, custom_components=None) -> list[str]:
    """Validate a view spec. Returns a list of error strings (empty = valid).
    Messages are written for the app-dev agent's retry loop — each one says
    where, what, and what would be accepted instead.

    custom_components: names of this installation's private components (the
    library overlay). Their blocks may query any read function and carry any
    props — the component's own code defines its contract."""
    custom = set(custom_components or ())
    errors: list[str] = []
    if not isinstance(spec, dict):
        return ["spec must be a JSON object"]

    name = spec.get("name", "")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        errors.append("'name' must be kebab-case: lowercase letters/digits/hyphens, "
                      "2-63 chars, e.g. 'rp-overview'")
    if not isinstance(spec.get("title"), str) or not spec.get("title", "").strip():
        errors.append("'title' (non-empty string) is required")
    if not isinstance(spec.get("building"), str) or not spec.get("building"):
        errors.append("'building' (string) is required")
    refresh = spec.get("refresh_s", 60)
    if not isinstance(refresh, int) or not 15 <= refresh <= 3600:
        errors.append("'refresh_s' must be an integer between 15 and 3600")
    if "description" in spec and not isinstance(spec["description"], str):
        errors.append("'description' must be a string")

    allowed_top = {"name", "title", "building", "description", "refresh_s", "blocks"}
    for k in spec:
        if k not in allowed_top:
            errors.append(f"unknown top-level key '{k}' (allowed: {', '.join(sorted(allowed_top))})")

    blocks = spec.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        errors.append("'blocks' must be a non-empty array")
        return errors
    if len(blocks) > 24:
        errors.append(f"too many blocks ({len(blocks)}), max 24")

    for i, b in enumerate(blocks):
        path = f"blocks[{i}]"
        if not isinstance(b, dict):
            errors.append(f"{path}: must be an object")
            continue
        comp = b.get("component")
        if comp not in COMPONENTS and comp not in custom:
            errors.append(f"{path}: unknown component {comp!r} "
                          f"(available: {', '.join(COMPONENTS)}"
                          + (f"; custom: {', '.join(sorted(custom))}" if custom else "")
                          + ")")
            continue
        if comp not in COMPONENTS:
            # custom component: structural checks only, its code owns the rest
            for k in b:
                if k not in {"component", "title", "width", "query", "props"}:
                    errors.append(f"{path}: unknown key '{k}'")
            w = b.get("width", 6)
            if not isinstance(w, int) or not 1 <= w <= 12:
                errors.append(f"{path}: 'width' must be an integer 1-12 (grid columns)")
            q = b.get("query")
            if q is not None:
                if not isinstance(q, dict) or q.get("fn") not in FUNCTION_ARGS:
                    errors.append(f"{path}: query.fn must be one of "
                                  f"{', '.join(FUNCTION_ARGS)}")
                elif not isinstance(q.get("args", {}), dict):
                    errors.append(f"{path}: query.args must be an object")
                else:
                    _check_args(q["fn"], q.get("args", {}), path, errors)
            continue
        cdef = COMPONENTS[comp]
        for k in b:
            if k not in {"component", "title", "width", "query", "props"}:
                errors.append(f"{path}: unknown key '{k}'")
        if "title" in b and not isinstance(b["title"], str):
            errors.append(f"{path}: 'title' must be a string")
        w = b.get("width", cdef["default_width"])
        if not isinstance(w, int) or not 1 <= w <= 12:
            errors.append(f"{path}: 'width' must be an integer 1-12 (grid columns)")

        query = b.get("query")
        if comp == "note":
            if query is not None:
                errors.append(f"{path}: 'note' takes no query")
            if not isinstance(b.get("props", {}).get("text"), str):
                errors.append(f"{path}: 'note' requires props.text (string)")
        else:
            if not isinstance(query, dict):
                errors.append(f"{path}: 'query' object required, "
                              f"shape {{\"fn\": ..., \"args\": {{...}}}}")
                continue
            fn = query.get("fn")
            if fn not in FUNCTION_ARGS:
                errors.append(f"{path}: unknown fn {fn!r} "
                              f"(available: {', '.join(FUNCTION_ARGS)})")
                continue
            if fn not in cdef["data_fns"]:
                errors.append(f"{path}: component '{comp}' renders data from "
                              f"{cdef['data_fns']}, not '{fn}'")
            args = query.get("args", {})
            if not isinstance(args, dict):
                errors.append(f"{path}: query.args must be an object")
            else:
                _check_args(fn, args, path, errors)

        props = b.get("props", {})
        if not isinstance(props, dict):
            errors.append(f"{path}: 'props' must be an object")
        else:
            for k in props:
                if k not in cdef["props"]:
                    errors.append(f"{path}: component '{comp}' has no prop '{k}' "
                                  f"(allowed: {', '.join(cdef['props']) or 'none'})")
    return errors


def grammar_markdown(building: str) -> str:
    """The spec shape itself, as prompt text — kept beside the validator so
    the two can't drift apart silently."""
    return f"""A view spec is a JSON object:
{{
  "name": "<kebab-case, e.g. rp-overview>",
  "title": "<human title>",
  "building": "{building}",
  "description": "<one line: what this view shows>",
  "refresh_s": 60,
  "blocks": [
    {{"component": "<component>", "title": "<block heading>", "width": <1-12 grid columns>,
      "query": {{"fn": "<function>", "args": {{...}}}}, "props": {{...}}}},
    ...
  ]
}}
The page is a 12-column grid; widths in a row should sum to 12 (e.g. four stats of width 3, then two width-6 blocks). Blocks appear in order. Lead with what an operator glances at: stat tiles, then alarms, then trends, then detail tables."""


def components_markdown() -> str:
    """The component vocabulary as markdown — the agent's render menu."""
    lines = ["### Components (what a block can render)"]
    for name, c in COMPONENTS.items():
        fns = f" — data from: {', '.join(c['data_fns'])}" if c["data_fns"] else " — no query"
        lines.append(f"- **{name}** (default width {c['default_width']}): {c['desc']}{fns}")
        for p, d in c["props"].items():
            lines.append(f"    - props.{p}: {d}")
    return "\n".join(lines)


def functions_markdown() -> str:
    """The function vocabulary as markdown — the agent's query menu."""
    lines = []
    for name, sig in FUNCTION_ARGS.items():
        parts = []
        for arg, typ, desc in sig["required"]:
            t = "|".join(typ) if isinstance(typ, tuple) else typ.__name__
            parts.append(f"{arg}: {t} (REQUIRED{', ' + desc if desc else ''})")
        for arg, typ, desc in sig["optional"]:
            t = "|".join(typ) if isinstance(typ, tuple) else typ.__name__
            parts.append(f"{arg}: {t}{' — ' + desc if desc else ''}")
        lines.append(f"- **{name}**({'; '.join(parts) or 'no args'})")
    return "\n".join(lines)


def catalog_markdown() -> str:
    """Both vocabularies — kept for callers that want the full menu."""
    return (components_markdown() + "\n\n### Functions (what a query can call)\n"
            + functions_markdown())
