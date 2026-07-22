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
INFLUX_RP = "ot_RAW_Envision_Edge"     # raw = pre-scaling, ≈ true BACnet presentValue
INFLUX_USER = os.environ.get("RP_INFLUX_USER", "root")
INFLUX_PASS = os.environ.get("RP_INFLUX_PASS", "REDACTED_SEE_ENV_FILE")
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


def build_mapping(name_filter: re.Pattern) -> dict:
    """Parse ld_info.xml + each selected asset's point.csv into:
        { assetId: {device, equipment, points: {point_name: (otype, oinst)}} }
    Cached locally so repeat runs don't re-pull the config.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, "mapping.json")
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)

    ld_xml = _ssh(f"cat {LD_INFO}")
    mapping = {}
    for m in re.finditer(r"<ld_info\b([^>]*)>", ld_xml):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        laddr = attrs.get("logic_addr_str", "")
        asset_id = attrs.get("asset_id", "")
        point_path = attrs.get("point_path", "")
        if not (asset_id and point_path and name_filter.search(laddr)):
            continue
        # logic_addr_str: "RVP_118_L1_CH_01_bms_20260606:7777:0"
        parts = laddr.split(":")
        device = parts[1] if len(parts) > 1 else ""
        equipment = parts[0]

        points = {}
        for row in csv.DictReader(io.StringIO(_ssh(f"cat {point_path}"))):
            objid = (row.get("objectid") or "").strip()
            pname = (row.get("point-name") or "").strip()
            if not objid or ":" not in objid or not pname:
                continue  # skip virtual/control points with no BACnet address
            otype, _, oinst = objid.partition(":")
            points[pname] = [otype, oinst]
        mapping[asset_id] = {"device": device, "equipment": equipment, "points": points}

    with open(cache, "w") as f:
        json.dump(mapping, f, indent=2)
    print(f"[collector] mapping: {len(mapping)} assets "
          f"({sum(len(a['points']) for a in mapping.values())} points)", flush=True)
    return mapping


def pull_readings(mapping: dict, window: str):
    """Query influx for each asset's series in the window; yield decoded readings."""
    for asset_id, info in mapping.items():
        q = (f'SELECT value FROM {INFLUX_RP}./^HDB_EnOS/ '
             f"WHERE \\\"assetId\\\"='{asset_id}' AND time > now() - {window}")
        out = _influx(q)
        for row in csv.reader(io.StringIO(out)):
            # csv columns: name,time,value  (header repeats per measurement)
            if len(row) < 3 or row[0] == "name":
                continue
            measurement, ts, val = row[0], row[1], row[2]
            point_name = measurement.split("@", 1)[-1]
            obj = info["points"].get(point_name)
            if obj is None:
                continue  # point not in this asset's BACnet map (EnOS-derived)
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


def cycle(name_filter: re.Pattern, window: str):
    mapping = build_mapping(name_filter)
    readings = list(pull_readings(mapping, window))
    sent = publish(readings)
    print(f"[collector] published {sent} readings to MQTT", flush=True)
    return sent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--window", default="15m", help="influx lookback per cycle")
    ap.add_argument("--filter", default=None, help="asset name regex (default: 2 chillers)")
    args = ap.parse_args()
    name_filter = re.compile(args.filter) if args.filter else DEFAULT_FILTER

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
