"""Device discovery — first-class network discovery, separate from collection.

Collection is a dumb, fast, deterministic loop; discovery is occasional and
sometimes needs to reason. This workflow keeps them apart. It bootstraps from
the one seed a human must provide (edge SSH access, from a config map),
explores the edge over SSH, and writes what it learns (device → IP) into the
graph as revisable, provenanced facts. Collectors then READ addressing from the
graph and trigger this workflow when something is missing — never discover
inline.

Today the discovery step is deterministic (bacsearch + parse), which covers
simple sites. The `_discover_devices` seam is where LLM escalation belongs for
messy topology (routed BACnet, multiple interfaces): an agent orchestrating
bacsearch / bacrouter_raw / ip-addr over the same SSH transport, reasoning
about what it finds. Kept out of the collector's hot path by construction.
"""

import re
import time

from restate import VirtualObject, ObjectContext

from collectors.framework import _load_config_map
from collectors.transport import SshTransport
from shared.graph import execute_cypher
from shared.traced import traced_run

# A VirtualObject (keyed by edge), not a Workflow: discovery must be
# RE-RUNNABLE (retries, topology changes) — a Workflow key is single-use, so a
# failed attempt would poison it forever. Restate also serializes handler calls
# per key, so concurrent triggers for the same edge don't stampede.
device_discovery_workflow = VirtualObject("device_discovery")


def _transport(tenant: str, edge_ref: str) -> SshTransport:
    ssh = _load_config_map(tenant, edge_ref).get("ssh", {})
    host, user = ssh["host"], ssh.get("user")
    return SshTransport(target=f"{user}@{host}" if user else host)


def _bacsearch(transport: SshTransport, tools_dir: str, window: int):
    """Deterministic pass: one Who-Is, parse the device directory."""
    out = transport.exec(
        f"cd {tools_dir} && python3 bacsearch_raw.py --window {window} 2>/dev/null",
        timeout=window + 40)
    devices = []
    for m in re.finditer(r"device_instance=(\d+)\s+ip=([\d.]+)\s+port=(\d+)", out):
        devices.append({"device_instance": m.group(1), "ip": m.group(2),
                        "port": int(m.group(3))})
    return devices


def _discover_devices(transport: SshTransport, tools_dir: str, window: int):
    """Return the device directory. Deterministic bacsearch first; this is the
    seam where an LLM agent takes over for complex networks (not yet built —
    escalation would orchestrate bacrouter_raw/ip-addr/bacsearch and reason)."""
    devices = _bacsearch(transport, tools_dir, window)
    # if not devices: devices = _discover_devices_llm(transport, ...)  # future
    return devices


def _write_device_ips(tenant: str, devices: list) -> list:
    """Persist device → IP as graph facts on existing device RawTags."""
    now_ms = int(time.time() * 1000)
    written = []
    for d in devices:
        inst, ip = d["device_instance"], d["ip"]
        res = execute_cypher(f"""
            MATCH (r:RawTag {{building_id: '{tenant}', device_id: '{inst}', tag_type: 'device'}})
            SET r.device_ip = '{ip}', r.ip_discovered_at = {now_ms}
            RETURN r.id
        """)
        if res:
            written.append({"device_instance": inst, "ip": ip})
    return written


@device_discovery_workflow.handler()
async def run(ctx: ObjectContext, request: dict) -> dict:
    request = request or {}
    tenant = request["tenant"]
    edge_ref = request.get("edge_ref", "rp-edge")
    tools_dir = request.get("tools_dir", "/home/envuser/bacnet-tools")
    window = int(request.get("window", 6))

    # Transport is a cheap, deterministic local object — build it directly, not
    # as a journaled step (it isn't serializable, and needn't be replayed).
    transport = _transport(tenant, edge_ref)

    devices = await traced_run(ctx, "discover_devices",
        lambda: _discover_devices(transport, tools_dir, window), data_id=tenant)

    if not devices:
        return {"status": "completed", "message": "no devices discovered",
                "devices": []}

    written = await traced_run(ctx, "write_device_ips",
        lambda: _write_device_ips(tenant, devices), data_id=tenant)

    return {"status": "completed", "discovered": devices, "written": written}
