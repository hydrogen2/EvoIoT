"""Tabular file rendering + mapping-spec application.

The extraction split: the LLM interprets a file's SCHEMA (which columns mean
what, how to parse embedded values) and returns a mapping spec; this module
applies that spec mechanically to every row. 929 rows cost zero LLM tokens.
"""

import csv
import io
import re

import openpyxl

# BACnet camelCase → canonical dashed form (matches wire discovery / BAC0)
_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")


def normalize_object_id(raw: str):
    """'analogInput:0' / 'AI,1' / 'multi-state-output:5' → ('analog-input', '0')."""
    if not raw:
        return None, None
    s = str(raw).strip().replace(",", ":").replace(";", ":")
    if ":" not in s:
        return None, None
    otype, _, instance = s.partition(":")
    otype = otype.strip()
    abbrev = {
        "AI": "analog-input", "AO": "analog-output", "AV": "analog-value",
        "BI": "binary-input", "BO": "binary-output", "BV": "binary-value",
        "MSI": "multi-state-input", "MSO": "multi-state-output",
        "MSV": "multi-state-value",
    }
    if otype.upper() in abbrev:
        otype = abbrev[otype.upper()]
    else:
        otype = _CAMEL_RE.sub("-", otype).lower().replace("_", "-")
        otype = otype.replace("multistate", "multi-state")
    return otype, instance.strip()


def parse_facets_unit(facets: str):
    """Niagara facets 'units=u:celsius;°C;(K);+273.15;|...' → '°C' (symbol)."""
    if not facets:
        return None
    m = re.search(r"units=u:([^|]+)", str(facets))
    if not m:
        return None
    fields = m.group(1).split(";")
    if fields and fields[0] in ("null", ""):
        return None
    # symbol field preferred, fall back to unit name
    if len(fields) > 1 and fields[1]:
        return fields[1]
    return fields[0] or None


def render_xlsx(path: str):
    """Visible sheets → [{sheet, header, rows}] with stringified cells.

    Loads via BytesIO: snapshots are content-addressed (no extension) and
    openpyxl refuses paths whose extension it doesn't recognize.
    """
    with open(path, "rb") as f:
        wb = openpyxl.load_workbook(io.BytesIO(f.read()), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        rows = [["" if c is None else str(c) for c in r]
                for r in ws.iter_rows(values_only=True)]
        rows = [r for r in rows if any(v.strip() for v in r)]
        if not rows:
            continue
        out.append({"sheet": ws.title, "header": rows[0], "rows": rows[1:]})
    return out


def sample_text(sheets, max_rows: int = 8) -> str:
    """Compact CSV sample of each sheet for LLM schema interpretation."""
    buf = io.StringIO()
    for s in sheets:
        buf.write(f"## sheet {s['sheet']!r} ({len(s['rows'])} data rows)\n")
        w = csv.writer(buf)
        w.writerow(s["header"])
        for r in s["rows"][:max_rows]:
            w.writerow([c[:60] for c in r])
        buf.write("\n")
    return buf.getvalue()


def apply_mapping(sheets, spec: dict):
    """Apply a validated mapping spec; returns point-claim dicts.

    Spec shape (produced by the LLM, validated before use):
      {
        "sheet": "Points",
        "columns": {                    # header names, required: object_id, name
          "device": "Source", "object_id": "Object ID", "name": "Name",
          "facets": "Facets",           # optional: Niagara facets → unit
          "unit": null,                 # optional: plain unit column
          "value": "Out", "write": "Write", "path": "Path"
        },
        "device_instance_regex": "(\\d+)$"   # optional: instance from device name
      }
    """
    sheet = next((s for s in sheets if s["sheet"] == spec.get("sheet")), None)
    if sheet is None:
        raise ValueError(f"mapping references unknown sheet {spec.get('sheet')!r}")

    header = sheet["header"]
    cols = spec.get("columns") or {}
    idx = {}
    for role, colname in cols.items():
        if not colname:
            continue
        if colname not in header:
            raise ValueError(f"mapping column {colname!r} (role {role}) not in header {header}")
        idx[role] = header.index(colname)
    for required in ("object_id", "name"):
        if required not in idx:
            raise ValueError(f"mapping lacks required role {required!r}")

    inst_re = None
    if spec.get("device_instance_regex"):
        inst_re = re.compile(spec["device_instance_regex"])

    def cell(row, role):
        i = idx.get(role)
        return row[i].strip() if i is not None and i < len(row) else ""

    claims, skipped = [], 0
    for rownum, row in enumerate(sheet["rows"], start=2):  # 1-based + header
        otype, oinstance = normalize_object_id(cell(row, "object_id"))
        name = cell(row, "name")
        if not otype or not name:
            skipped += 1
            continue

        device_name = cell(row, "device") or "unknown-device"
        device_id = device_name
        if inst_re:
            m = inst_re.search(device_name)
            # Guard against name-suffix false positives (SC-equip-App1 → "1"):
            # a trailing number is only a BACnet instance if a separator
            # precedes it (Rivervale_Chiller_7777 → 7777).
            if m and m.start(1) > 0 and device_name[m.start(1) - 1] in "_- ":
                device_id = m.group(1)

        unit = cell(row, "unit") or None
        if not unit and "facets" in idx:
            unit = parse_facets_unit(cell(row, "facets"))

        claims.append({
            "row": rownum,
            "device_id": device_id,
            "device_name": device_name,
            "object_type": otype,
            "object_instance": oinstance,
            "object_name": name,
            "unit": unit,
            "value_sample": cell(row, "value") or None,
            "writable": cell(row, "write") == "writable" or None,
            "path": cell(row, "path") or None,
        })
    return {"claims": claims, "skipped": skipped, "sheet": sheet["sheet"]}
