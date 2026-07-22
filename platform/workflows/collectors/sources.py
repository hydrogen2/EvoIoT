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

import csv
import io
import os
import re
import shlex
from abc import ABC, abstractmethod

from .transport import Transport


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


def build_source(config: dict, transport: Transport) -> Source:
    stype = config.get("source")
    if stype == "influx_enos":
        return InfluxEnosSource(transport, config)
    raise ValueError(f"unknown source type: {stype}")
