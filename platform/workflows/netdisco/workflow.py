"""BACnet metadata source — a first-class metadata source, peer to the file
(project-folder) source. Both produce the point inventory; they differ only in
what they carry. The file source (BMS export) gives names, units, equipment
context — curated, no addressing, no liveness. This source gives the exhaustive
on-the-wire inventory + addressing + live confirmation — no friendly names.
Fused on BACnet identity in the graph, each fills the other's gaps.

Runs a full scan on the edge over SSH (bacsearch → per-device object
enumeration, via bacnet-tools raw sockets so it coexists with the incumbent
BACstac), then fuses each device+object into the graph via upsert_rawtag:
corroboration upgrades a file-derived RawTag's origin to 'wire' and adds
addressing/live-name without clobbering its metadata; scan-only points (e.g.
a device the export missed) are created fresh.

Kept separate from the collector's hot loop by construction. `_scan` is the
seam where LLM escalation belongs for complex topology (routed BACnet,
multi-interface) — an agent orchestrating the same tools over SSH.
"""

import json

from restate import VirtualObject, ObjectContext

from collectors.framework import _load_config_map, _connect, resolve_namespace
from collectors.transport import SshTransport
from shared.traced import traced_run

# BACnet object-type enum → dashed name (matches the file extraction's forms so
# wire and file RawTags share an identity). Device (8) becomes the device tag;
# unrecognized types are kept as type-<N> so nothing is lost.
OBJ_TYPE_NAME = {
    0: "analog-input", 1: "analog-output", 2: "analog-value",
    3: "binary-input", 4: "binary-output", 5: "binary-value",
    13: "multi-state-input", 14: "multi-state-output", 19: "multi-state-value",
}
DEVICE_TYPE = 8

bacnet_scan = VirtualObject("bacnet_scan")


def _load_bacnet_source(tenant: str):
    """The tenant's registered BACnet metadata data source (source_type='bacnet')."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT config FROM evoiot.data_sources
                           WHERE source_type = 'bacnet' AND config->>'tenant' = %s
                             AND enabled LIMIT 1""", (tenant,))
            row = cur.fetchone()
    finally:
        conn.close()
    return (row[0] if row else None)


def _transport(tenant: str, edge_ref: str) -> SshTransport:
    ssh = _load_config_map(tenant, edge_ref).get("ssh", {})
    host, user = ssh["host"], ssh.get("user")
    return SshTransport(target=f"{user}@{host}" if user else host)


def _scan(transport: SshTransport, tools_dir: str, window: int, timeout: float):
    """Deterministic full scan: bacsearch + per-device object enumeration.
    Seam for LLM escalation on complex networks (not yet built)."""
    out = transport.exec(
        f"cd {tools_dir} && python3 bacscan_raw.py --name --window {window} "
        f"--timeout {timeout} --out /tmp/evoiot_scan.jsonl 2>/dev/null "
        f"&& cat /tmp/evoiot_scan.jsonl",
        timeout=600)
    devices = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("_meta") or "device" not in rec:
            continue
        devices.append(rec)
    return devices


def _fuse(tenant: str, namespace: str, devices: list) -> dict:
    """Fuse the scan into the graph. Returns counts."""
    conn = _connect()
    stats = {"devices": 0, "objects": 0, "skipped": 0}
    try:
        with conn.cursor() as cur:
            # upsert_rawtag(tenant, building, device, otype, oinst, tag_type,
            #   origin, evidence, object_name, unit, value_sample, path, ip, port)
            for d in devices:
                dev = str(d["device"])
                cur.execute("SELECT evoiot.upsert_rawtag(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (tenant, namespace, dev, None, None, "device",
                             "wire", "bacnet:whois", None, None, None, None,
                             d.get("ip"), str(d.get("port") or "")))
                stats["devices"] += 1
                for o in d.get("objects", []):
                    otype_num = o.get("type")
                    if otype_num == DEVICE_TYPE or "instance" not in o:
                        stats["skipped"] += 1
                        continue
                    otype = OBJ_TYPE_NAME.get(otype_num, f"type-{otype_num}")
                    cur.execute("SELECT evoiot.upsert_rawtag(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                (tenant, namespace, dev, otype, str(o["instance"]),
                                 "object", "wire", "bacnet:objectlist",
                                 o.get("name"), None, None, None, None, None))
                    stats["objects"] += 1
    finally:
        conn.close()
    return stats


@bacnet_scan.handler()
async def scan(ctx: ObjectContext, request: dict) -> dict:
    """Full inventory scan keyed by tenant. Config from the tenant's registered
    bacnet data source; edge access from the config-map seed it references."""
    tenant = (request or {}).get("tenant") or ctx.key()
    config = _load_bacnet_source(tenant)
    if config is None:
        return {"status": "no_source", "message": f"no bacnet data source for {tenant}"}

    edge_ref = (config.get("transport") or {}).get("ref", "rp-edge")
    namespace = resolve_namespace(config)   # building name (from the seed)
    b = config.get("bacnet", {})
    tools_dir = b.get("tool_dir", "/home/envuser/bacnet-tools")
    window = int(b.get("window", 8))
    timeout = float(b.get("read_timeout", 4.0))

    transport = _transport(tenant, edge_ref)

    devices = await traced_run(ctx, "scan_network",
        lambda: _scan(transport, tools_dir, window, timeout), data_id=tenant)
    if not devices:
        return {"status": "completed", "message": "no devices", "devices": []}

    stats = await traced_run(ctx, "fuse_inventory",
        lambda: _fuse(tenant, namespace, devices), data_id=tenant)

    return {"status": "completed",
            "discovered_devices": [{"device": d["device"], "ip": d.get("ip"),
                                    "objects": d.get("object_count")} for d in devices],
            **stats}
