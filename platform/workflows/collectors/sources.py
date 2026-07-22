"""Collector sources — WHAT to fetch and how to decode it into readings.

A source is the smart, platform-side logic for one kind of data: it decides
what to request (via a transport), and interprets the result into normalized
readings keyed by raw BACnet identity. Poll list, cadence, retries, watermark,
and publishing all live in the framework above — a source is a pure
"pull(since) -> (readings, new_watermark)".

Sources:
  influx_enos  — incumbent-historian adapter: reads an EnOS edge's InfluxDB and
                 reverse-maps (measurement point-name + assetId) back to raw
                 BACnet identity via the edge's ld_info.xml + point.csv config.
  (bacnet_pull comes next — generic pull-mode agent.)
"""

import base64
import csv
import io
import json
import os
import re
import shlex
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import httpx
import psycopg2

from .transport import Transport

RESTATE_INGRESS = os.environ.get("RESTATE_INGRESS_URL", "http://restate:8080")

# BACnet object-type name → numeric enum (for ReadProperty requests)
OBJ_TYPE_NUM = {
    "analog-input": 0, "analog-output": 1, "analog-value": 2,
    "binary-input": 3, "binary-output": 4, "binary-value": 5,
    "multi-state-input": 13, "multi-state-output": 14, "multi-state-value": 19,
}
PRESENT_VALUE = 85


def norm_ts(ts: str) -> str:
    """RFC3339 → fixed 9-digit-fractional form: same length/format for every
    value, so lexicographic order == chronological and influx accepts it back."""
    core = ts.rstrip("Z")
    if "." in core:
        head, frac = core.split(".", 1)
        frac = (frac + "0" * 9)[:9]
    else:
        head, frac = core, "0" * 9
    return f"{head}.{frac}Z"


class Source(ABC):
    @abstractmethod
    def pull(self, watermark):
        """Return (readings, new_watermark). readings: list of dicts with
        device_id, object_type, object_instance, value, unit, observed_at,
        and a provenance dict. new_watermark: opaque string to persist, or the
        old watermark if nothing new."""
        ...


# ── EnOS incumbent-historian adapter ────────────────────────────────

class InfluxEnosSource(Source):
    LD_INFO = "/home/envuser/energy-os/edge-dpf/config/fe_config_data/ld_info.xml"

    def __init__(self, transport: Transport, config: dict):
        self.t = transport
        c = config.get("influx", {})
        self.influx_bin = c.get("bin", "/home/envuser/influxdb-1.6.5/bin/influx")
        self.db = c["db"]
        self.rps = c.get("rps", ["ot_RAW_Envision_Edge", "ot_DI_Envision_Edge"])
        self.meas_re = c.get("measurement_re", "^HDB_EnOS")
        self.user = os.environ.get("RP_INFLUX_USER", "root")
        self.passwd = os.environ.get("RP_INFLUX_PASS", "")
        self.bootstrap = config.get("bootstrap_window", "10m")
        self._mapping = None  # module-lifetime cache (process is long-lived)

    # -- reverse-map: assetId → device instance + point.csv → objectid --
    def _mapping_load(self):
        if self._mapping is not None:
            return self._mapping
        ld_xml = self.t.exec(f"cat {self.LD_INFO}")
        assets = []
        for m in re.finditer(r"<ld_info\b([^>]*)>", ld_xml):
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
            laddr = attrs.get("logic_addr_str", "")
            asset_id = attrs.get("asset_id", "")
            ppath = attrs.get("point_path", "")
            if not (asset_id and ppath):
                continue
            parts = laddr.split(":")
            assets.append((asset_id, parts[1] if len(parts) > 1 else "", parts[0], ppath))

        paths = sorted({a[3] for a in assets})
        script = "".join(f'echo "@@@{p}"; cat "{p}" 2>/dev/null; ' for p in paths)
        blob = self.t.exec(script)
        csv_by_path, cur, buf = {}, None, []
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
        for asset_id, device, equip, ppath in assets:
            points = {}
            for row in csv.DictReader(io.StringIO(csv_by_path.get(ppath, ""))):
                objid = (row.get("objectid") or "").strip()
                pname = (row.get("point-name") or "").strip()
                if objid and ":" in objid and pname:
                    otype, _, oinst = objid.partition(":")
                    points[pname] = (otype, oinst)
            mapping[asset_id] = {"device": device, "equipment": equip, "points": points}
        self._mapping = mapping
        return mapping

    def _influx(self, query: str) -> str:
        if not re.match(r"^\s*(select|show)\b", query, re.I):
            raise ValueError("read-only: only SELECT/SHOW permitted")
        # shlex.quote each value so the remote shell parses it as one token —
        # the query mixes single quotes (InfluxQL time literals) and double
        # quotes ("assetId"), which hand-escaping gets wrong.
        remote = (f"{self.influx_bin} -username {shlex.quote(self.user)} "
                  f"-password {shlex.quote(self.passwd)} "
                  f"-database {shlex.quote(self.db)} -precision rfc3339 "
                  f"-format csv -execute {shlex.quote(query)}")
        return self.t.exec(remote)

    def pull(self, watermark):
        mapping = self._mapping_load()
        time_pred = (f"time > '{watermark}'" if watermark
                     else f"time > now() - {self.bootstrap}")
        readings, newest, unmapped = [], watermark, 0
        for rp in self.rps:
            q = (f'SELECT value FROM {rp}./{self.meas_re}/ '
                 f'WHERE {time_pred} GROUP BY "assetId"')
            for row in csv.reader(io.StringIO(self._influx(q))):
                if len(row) < 4 or row[0] == "name":
                    continue
                measurement, tags, ts, val = row[0], row[1], row[2], row[3]
                asset_id = tags.split("assetId=", 1)[-1] if "assetId=" in tags else ""
                info = mapping.get(asset_id)
                if info is None:
                    continue
                obj = info["points"].get(measurement.split("@", 1)[-1])
                if obj is None:
                    unmapped += 1
                    continue
                try:
                    value = float(val)
                except ValueError:
                    continue
                nts = norm_ts(ts)
                if newest is None or nts > newest:
                    newest = nts
                readings.append({
                    "device_id": info["device"],
                    "object_type": obj[0], "object_instance": obj[1],
                    "value": value, "unit": "", "observed_at": ts,
                    "provenance": {"enos_asset_id": asset_id,
                                   "enos_equipment": info["equipment"]},
                })
        return readings, newest


# ── Generic BACnet pull-mode agent ──────────────────────────────────

class BacnetPullSource(Source):
    """Live BACnet ReadProperty polling, executed transiently on the edge.

    The edge holds a dormant read tool (bacnet-tools, raw sockets so it
    coexists with any incumbent BACstac); this source invokes it per pull —
    no resident daemon. The poll list is owned by the platform: it comes from
    the RawTags the platform already knows exist for each configured device.
    There is no history here — each pull is a snapshot at read time, so the
    watermark is unused.
    """

    def __init__(self, transport: Transport, config: dict):
        self.t = transport
        b = config.get("bacnet", {})
        self.tool = b.get("tool_dir", "/home/envuser/bacnet-tools")
        # devices to poll: just instance ids — addressing is DISCOVERED, not
        # configured. (An optional explicit ip/objects per entry still works.)
        self.devices = b.get("devices", [])
        self.chunk = int(b.get("chunk", 30))
        self.timeout = float(b.get("timeout", 5.0))
        self.tenant = config["tenant"]
        self.edge_ref = (config.get("transport") or {}).get("ref", "rp-edge")

    @staticmethod
    def _graph_conn():
        conn = psycopg2.connect(host=os.environ.get("POSTGRES_HOST", "postgres"),
                                port=os.environ.get("POSTGRES_PORT", "5432"),
                                database=os.environ.get("POSTGRES_DB", "postgres"),
                                user=os.environ.get("POSTGRES_USER", "postgres"),
                                password=os.environ.get("POSTGRES_PASSWORD", "postgres"))
        conn.autocommit = True
        return conn

    def _device_ip(self, device_id: str):
        """Device addressing is graph knowledge (written by device_discovery),
        not config. Returns the discovered IP or None."""
        conn = self._graph_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("LOAD 'age'")
                cur.execute("SET search_path = ag_catalog, evoiot, public")
                cur.execute(f"""
                    SELECT ip FROM (SELECT * FROM cypher('platform', $$
                        MATCH (r:RawTag {{building_id: '{self.tenant}',
                                          device_id: '{device_id}', tag_type: 'device'}})
                        RETURN r.device_ip
                    $$) AS (ip agtype)) s
                """)
                row = cur.fetchone()
        finally:
            conn.close()
        if row and row[0]:
            v = str(row[0]).strip('"')
            return v if v and v != "null" else None
        return None

    def _trigger_discovery(self):
        """Resolution-chain style: on missing addressing, fire the BACnet
        metadata scan async (keyed by tenant, re-runnable) and let the next
        cycle read the discovered IPs from the graph."""
        key = base64.urlsafe_b64encode(self.tenant.encode()).decode().rstrip("=")
        try:
            httpx.post(f"{RESTATE_INGRESS}/bacnet_scan/{key}/scan/send",
                       json={"tenant": self.tenant}, timeout=10)
        except httpx.HTTPError as e:
            print(f"[bacnet_pull] scan trigger failed: {e}", flush=True)

    def _poll_list(self, device_id: str):
        """Object RawTags the platform knows for this device = the poll list."""
        conn = self._graph_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("LOAD 'age'")
                cur.execute("SET search_path = ag_catalog, evoiot, public")
                cur.execute(f"""
                    SELECT object_type, object_instance FROM (
                        SELECT * FROM cypher('platform', $$
                            MATCH (r:RawTag)
                            WHERE r.building_id = '{self.tenant}'
                              AND r.device_id = '{device_id}'
                              AND r.tag_type = 'object'
                            RETURN r.object_type, r.object_instance
                        $$) AS (object_type agtype, object_instance agtype)
                    ) s
                """)
                out = []
                for otype, oinst in cur.fetchall():
                    ot = str(otype).strip('"')
                    oi = str(oinst).strip('"')
                    if ot in OBJ_TYPE_NUM and oi.isdigit():
                        out.append((ot, oi))
                return out
        finally:
            conn.close()

    def _read_target(self, target: dict, objects):
        ip = target["ip"]
        if target.get("port"):
            ip = f"{ip}:{target['port']}"
        extra = ""
        if target.get("dnet") is not None:
            extra += f" --dnet {int(target['dnet'])}"
        if target.get("dadr"):
            extra += f" --dadr {shlex.quote(str(target['dadr']))}"

        readings = []
        for i in range(0, len(objects), self.chunk):
            batch = objects[i:i + self.chunk]
            # label = index within batch; results come back in request order
            points = " ".join(
                f"{OBJ_TYPE_NUM[ot]}:{oi}:{PRESENT_VALUE}:p{j}"
                for j, (ot, oi) in enumerate(batch))
            cmd = (f"cd {shlex.quote(self.tool)} && python3 bacread_multi.py "
                   f"{shlex.quote(ip)} {points} --timeout {self.timeout} --json{extra}")
            out = self.t.exec(cmd, timeout=int(self.timeout * len(batch) + 30))
            try:
                parsed = json.loads(out)
            except json.JSONDecodeError:
                continue
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            for (ot, oi), res in zip(batch, parsed):
                val = res.get("value")
                if val is None or isinstance(val, list):
                    continue  # timeout/error/multi — skip
                try:
                    value = float(val)
                except (TypeError, ValueError):
                    continue
                readings.append({
                    "device_id": target["device_id"],
                    "object_type": ot, "object_instance": oi,
                    "value": value, "unit": "", "observed_at": now,
                    "provenance": {"read_by": "bacnet_pull", "device_ip": target["ip"]},
                })
        return readings

    def pull(self, watermark):
        readings, missing = [], []
        for dev in self.devices:
            device_id = dev if isinstance(dev, str) else dev["device_id"]
            # addressing: explicit ip (rare), else discovered from the graph
            ip = (dev.get("ip") if isinstance(dev, dict) else None) or self._device_ip(device_id)
            if not ip:
                missing.append(device_id)
                continue
            target = {"device_id": device_id, "ip": ip}
            if isinstance(dev, dict):
                target.update({k: dev[k] for k in ("port", "dnet", "dadr") if k in dev})
            objects = (dev.get("objects") if isinstance(dev, dict) else None)
            objects = ([(o[0], str(o[1])) for o in objects] if objects
                       else self._poll_list(device_id))
            readings.extend(self._read_target(target, objects))

        if missing:  # no addressing yet → kick discovery, resolve next cycle
            self._trigger_discovery()
            print(f"[bacnet_pull] no IP for devices {missing}; triggered "
                  f"device_discovery", flush=True)
        return readings, watermark  # snapshot source: watermark unchanged


def build_source(config: dict, transport: Transport) -> Source:
    stype = config.get("source")
    if stype == "influx_enos":
        return InfluxEnosSource(transport, config)
    if stype == "bacnet_pull":
        return BacnetPullSource(transport, config)
    raise ValueError(f"unknown source type: {stype}")
