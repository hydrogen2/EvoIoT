#!/usr/bin/env python3
"""RP edge SSH collector — pulls EnOS-collected telemetry, reverse-maps it to
raw BACnet identity, and republishes into EvoIoT.

The RP building's EnOS edge already polls BACnet and stores readings in a local
InfluxDB, keyed by EnOS's own model (measurement `<model>@<point>`, tag
`assetId`). This collector treats EnOS's onboarding purely as a DECODING TABLE:

    influx (measurement point-name + assetId)
      → ld_info.xml : assetId → BACnet device instance + point.csv path
      → point.csv   : point-name → BACnet objectid
      → raw BACnet identity (device, object_type:instance)
      → EvoIoT rawtag_id  (joins the RawTags already extracted from the export)

EvoIoT never learns EnOS asset ids or its model — it receives pure
BACnet-keyed telemetry through the normal MQTT → Bento → readings path.

Read-only against production: only SHOW/SELECT on influx, only cat on config.

    python collect.py --once            # one pull cycle
    python collect.py --loop --interval 60
"""

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import time

import paho.mqtt.client as mqtt

EDGE_SSH = os.environ.get("RP_EDGE_SSH", "hdb-rp-gw")
INFLUX_BIN = "/home/envuser/influxdb-1.6.5/bin/influx"
INFLUX_DB = "ot_o17757913456311166"
# EnOS splits points across retention policies by type; the pre-normalization
# "raw" tiers are disjoint and together ≈ true BACnet presentValue for the
# whole building: RAW = analog, DI = digital/binary.
INFLUX_RPS = ["ot_RAW_Envision_Edge", "ot_DI_Envision_Edge"]
INFLUX_USER = os.environ.get("RP_INFLUX_USER", "root")
INFLUX_PASS = os.environ.get("RP_INFLUX_PASS", "")  # set via .env (gitignored)
LD_INFO = "/home/envuser/energy-os/edge-dpf/config/fe_config_data/ld_info.xml"

MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

TENANT = "HDB"
# rawtag_id namespace segment: must match how the RawTags were created
# (file extraction used source_id='bms-export'). This is the physical-point
# namespace, NOT the telemetry agent — see the note at the bottom of the file.
RAWTAG_SOURCE = "bms-export"
AGENT_ID = "rp-edge-ssh"

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
WATERMARK = os.path.join(CACHE_DIR, "watermark.txt")

# Which assets to collect: name substring (matches logic_addr_str). Default =
# the two chillers on the chiller-plant gateway (device instance 7777).
DEFAULT_FILTER = re.compile(r"_CH_0[12]_")


def _ssh(remote_cmd: str) -> str:
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", EDGE_SSH, remote_cmd],
        capture_output=True, text=True, timeout=90,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ssh failed: {r.stderr.strip()[:400]}")
    return r.stdout


def _influx(query: str) -> str:
    """Run a read-only influx query, return CSV. Refuses non-SELECT/SHOW."""
    if not re.match(r"^\s*(select|show)\b", query, re.I):
        raise ValueError("read-only: only SELECT/SHOW permitted")
    remote = (f"{INFLUX_BIN} -username {INFLUX_USER} -password '{INFLUX_PASS}' "
              f"-database {INFLUX_DB} -precision rfc3339 -format csv "
              f'-execute "{query}"')
    return _ssh(remote)


def _parse_point_csv(text: str) -> dict:
    points = {}
    for row in csv.DictReader(io.StringIO(text)):
        objid = (row.get("objectid") or "").strip()
        pname = (row.get("point-name") or "").strip()
        if not objid or ":" not in objid or not pname:
            continue  # skip virtual/control points with no BACnet address
        otype, _, oinst = objid.partition(":")
        points[pname] = [otype, oinst]
    return points


def build_mapping(name_filter) -> dict:
    """Parse ld_info.xml + each selected asset's point.csv into:
        { assetId: {device, equipment, points: {point_name: (otype, oinst)}} }
    name_filter None selects every asset. All point.csv files are fetched in
    one SSH call. Cached locally so repeat runs don't re-pull the config.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    tag = "all" if name_filter is None else "filtered"
    cache = os.path.join(CACHE_DIR, f"mapping_{tag}.json")
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)

    ld_xml = _ssh(f"cat {LD_INFO}")
    assets = []  # (asset_id, device, equipment, point_path)
    for m in re.finditer(r"<ld_info\b([^>]*)>", ld_xml):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        laddr = attrs.get("logic_addr_str", "")
        asset_id = attrs.get("asset_id", "")
        point_path = attrs.get("point_path", "")
        if not (asset_id and point_path):
            continue
        if name_filter is not None and not name_filter.search(laddr):
            continue
        parts = laddr.split(":")  # "RVP_118_L1_CH_01_bms_...:7777:0"
        assets.append((asset_id, parts[1] if len(parts) > 1 else "", parts[0], point_path))

    # Fetch every referenced point.csv in a single SSH call, delimited.
    paths = sorted({a[3] for a in assets})
    script = "".join(f'echo "@@@{p}"; cat "{p}" 2>/dev/null; ' for p in paths)
    blob = _ssh(script)
    csv_by_path = {}
    cur = None
    buf = []
    for line in blob.splitlines():
        if line.startswith("@@@"):
            if cur is not None:
                csv_by_path[cur] = "\n".join(buf)
            cur, buf = line[3:], []
        else:
            buf.append(line)
    if cur is not None:
        csv_by_path[cur] = "\n".join(buf)

    mapping = {}
    for asset_id, device, equipment, point_path in assets:
        mapping[asset_id] = {
            "device": device, "equipment": equipment,
            "points": _parse_point_csv(csv_by_path.get(point_path, "")),
        }

    with open(cache, "w") as f:
        json.dump(mapping, f, indent=2)
    print(f"[collector] mapping: {len(mapping)} assets "
          f"({sum(len(a['points']) for a in mapping.values())} points)", flush=True)
    return mapping


def _norm_ts(ts: str) -> str:
    """RFC3339 → fixed 9-digit-fractional form. Same length/format for all
    values, so lexicographic order == chronological order and influx accepts
    it back verbatim as a time bound."""
    core = ts.rstrip("Z")
    if "." in core:
        head, frac = core.split(".", 1)
        frac = (frac + "0" * 9)[:9]
    else:
        head, frac = core, "0" * 9
    return f"{head}.{frac}Z"


def read_watermark():
    if os.path.exists(WATERMARK):
        with open(WATERMARK) as f:
            return f.read().strip() or None
    return None


def write_watermark(ts: str):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(WATERMARK, "w") as f:
        f.write(ts)


def pull_readings(mapping: dict, time_pred: str):
    """One bulk influx query per raw retention policy; yield decoded readings.
    time_pred is the WHERE time clause (e.g. "time > '<watermark>'").
    Reports how many point-series had no BACnet map (coverage diagnostic)."""
    unmapped = set()
    for rp in INFLUX_RPS:
        q = (f'SELECT value FROM {rp}./^HDB_EnOS/ '
             f'WHERE {time_pred} GROUP BY \\"assetId\\"')
        for row in csv.reader(io.StringIO(_influx(q))):
            # csv columns: name,tags,time,value  (header repeats per group)
            if len(row) < 4 or row[0] == "name":
                continue
            measurement, tags, ts, val = row[0], row[1], row[2], row[3]
            asset_id = tags.split("assetId=", 1)[-1] if "assetId=" in tags else ""
            info = mapping.get(asset_id)
            if info is None:
                continue  # asset not in selected scope
            point_name = measurement.split("@", 1)[-1]
            obj = info["points"].get(point_name)
            if obj is None:
                unmapped.add(f"{asset_id}:{point_name}")
                continue  # point not in this asset's BACnet map
            try:
                value = float(val)
            except ValueError:
                continue
            otype, oinst = obj
            yield {
                "device": info["device"], "otype": otype, "oinst": oinst,
                "value": value, "time": ts,
                "asset_id": asset_id, "point_name": point_name,
                "equipment": info["equipment"],
            }
    if unmapped:
        print(f"[collector] {len(unmapped)} point-series had no BACnet map (skipped)",
              flush=True)


def publish(readings) -> int:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="rp-edge-ssh-collector")
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    topic = f"buildings/{TENANT}/agents/{AGENT_ID}/telemetry"
    n = 0
    for r in readings:
        rawtag_id = f"{TENANT}:{RAWTAG_SOURCE}:{r['device']}:{r['otype']}:{r['oinst']}"
        payload = {
            "building_id": TENANT,
            "source_id": AGENT_ID,
            "rawtag_id": rawtag_id,
            "device_id": r["device"],
            "object_type": r["otype"],
            "object_instance": r["oinst"],
            "point_type": "unclassified",
            "value": r["value"],
            "unit": "",
            "agent_read_at": r["time"],
            # provenance of the decode (kept in raw_payload, not identity)
            "enos_asset_id": r["asset_id"],
            "enos_point": r["point_name"],
            "enos_equipment": r["equipment"],
        }
        client.publish(topic, json.dumps(payload), qos=1)
        n += 1
    client.loop_stop()
    client.disconnect()
    return n


def cycle(name_filter, bootstrap_window: str):
    """One incremental cycle: pull readings newer than the watermark (or the
    bootstrap window on first run), publish, and advance the watermark to the
    newest reading seen."""
    mapping = build_mapping(name_filter)
    wm = read_watermark()
    time_pred = f"time > '{wm}'" if wm else f"time > now() - {bootstrap_window}"

    readings = list(pull_readings(mapping, time_pred))
    if not readings:
        print("[collector] no new readings", flush=True)
        return 0

    sent = publish(readings)
    newest = max(_norm_ts(r["time"]) for r in readings)
    write_watermark(newest)
    print(f"[collector] published {sent} readings (watermark → {newest})", flush=True)
    return sent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--window", default="15m",
                    help="bootstrap lookback on first run (before a watermark exists)")
    ap.add_argument("--filter", default=None, help="asset name regex (default: 2 chillers)")
    ap.add_argument("--all", action="store_true", help="collect the whole building (all assets)")
    args = ap.parse_args()
    if args.all:
        name_filter = None
    elif args.filter:
        name_filter = re.compile(args.filter)
    else:
        name_filter = DEFAULT_FILTER

    if not INFLUX_PASS:
        sys.exit("RP_INFLUX_PASS not set (put it in collectors/rp_edge_ssh/.env)")

    if args.loop:
        while True:
            try:
                cycle(name_filter, args.window)
            except Exception as e:  # keep the loop alive on transient errors
                print(f"[collector] cycle error: {e}", flush=True)
            time.sleep(args.interval)
    else:
        cycle(name_filter, args.window)


if __name__ == "__main__":
    main()

# NOTE — rawtag_id namespace: the id segment 'bms-export' is the physical-point
# namespace (it's what the file extraction used), not the telemetry agent. Two
# evidence sources describing one BACnet point must produce the same rawtag_id,
# so identity can't encode "who reported it". The current rawtag template bakes
# source_id into identity; until that's generalized to a stable namespace, the
# collector aligns to 'bms-export' so its readings join the extracted RawTags.
