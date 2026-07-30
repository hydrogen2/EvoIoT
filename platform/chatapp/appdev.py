"""View storage + live building context.

The app-dev *behavior* lives in agent.py (publish_view is a tool of the one
building agent). This module owns what's underneath it:

- storage: published specs land in config_maps (`view:<name>`, the queryable
  projection) and every publish appends a claim to the events log (the
  provenance) — the same claim/projection shape as the graph writes.
- context: the live grounding (equipment inventory + real point-name samples)
  the agent's prompt is built from.
"""

from __future__ import annotations

import hashlib
import json
import re

import psycopg2

import functions


def building_context(tenant: str, building: str) -> str:
    """Live grounding: equipment inventory + real point-name samples per type."""
    summary = functions.equipment_summary({"tenant": tenant, "building": building})
    meta = functions._meta_cache.get(tenant)
    latest = functions._latest_cache.get(tenant)
    lines = ["Equipment inventory (device type: units, points, live points):"]
    for r in summary["rows"]:
        lines.append(f"- {r['device_type']}: {r['count']} units, "
                     f"{r['points']} points ({r['live_points']} live)")
    by_type = {}
    for rid, m in meta.items():
        if building and m["building"] and m["building"] != building:
            continue
        if not m["device_type"]:
            continue
        by_type.setdefault(m["device_type"], []).append(
            (0 if rid in latest else 1, m["point"]))
    lines.append("\nSample point names (live points, per device type):")
    for dt, pts in sorted(by_type.items()):
        pts.sort()
        names = []
        seen = set()
        for _, p in pts:
            # strip the unit number so samples show the naming shape, not 90 repeats
            k = re.sub(r"\d+", "N", p)
            if k not in seen:
                seen.add(k)
                names.append(p)
            if len(names) >= 14:
                break
        lines.append(f"- {dt}: {', '.join(names)}")
    lines.append(f"\n{len(latest)} points reported a value in the last 2 hours.")
    return "\n".join(lines)


class ViewStore:
    def __init__(self, dsn: str, tenant: str):
        self.dsn, self.tenant = dsn, tenant

    def store(self, spec: dict, request: str = ""):
        """Publish: claim (provenance) + config_maps upsert (projection).
        Views today are read-only (the grammar has no action blocks until the
        write path exists), so publishes auto-approve; action-bearing views
        must go through ratification when they become possible."""
        spec_json = json.dumps(spec, ensure_ascii=False, sort_keys=True)
        sha = hashlib.sha256(spec_json.encode()).hexdigest()[:16]
        subject = f"view:{self.tenant}:{spec['building']}:{spec['name']}"
        conn = psycopg2.connect(self.dsn)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO evoiot.events
                         (component, operation, data_id, actor, payload,
                          claim_predicate, claim_object, claim_status)
                       VALUES ('chatapp', 'claim_view_spec', %s, 'building-agent',
                               %s, 'view_spec', %s, 'approved')""",
                    (subject, json.dumps({"request": request, "spec": spec}), sha))
                cur.execute(
                    """INSERT INTO evoiot.config_maps (tenant_id, name, config, description)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (tenant_id, name) DO UPDATE
                         SET config = EXCLUDED.config,
                             description = EXCLUDED.description,
                             updated_at = now()""",
                    (self.tenant, f"view:{spec['name']}", spec_json,
                     spec.get("description", "")))
        finally:
            conn.close()

    def list_views(self) -> list[dict]:
        conn = psycopg2.connect(self.dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT config FROM evoiot.config_maps
                       WHERE tenant_id = %s AND name LIKE 'view:%%'
                       ORDER BY updated_at DESC""", (self.tenant,))
                out = []
                for (cfg,) in cur.fetchall():
                    spec = cfg if isinstance(cfg, dict) else json.loads(cfg)
                    out.append({"name": spec.get("name"), "title": spec.get("title"),
                                "building": spec.get("building"),
                                "description": spec.get("description", "")})
                return out
        finally:
            conn.close()

    def get_view(self, name: str) -> dict | None:
        conn = psycopg2.connect(self.dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT config FROM evoiot.config_maps
                       WHERE tenant_id = %s AND name = %s""",
                    (self.tenant, f"view:{name}"))
                row = cur.fetchone()
                if not row:
                    return None
                return row[0] if isinstance(row[0], dict) else json.loads(row[0])
        finally:
            conn.close()

    # ── Custom components (the private overlay of the library) ──────
    # Private to this installation, so no ratification: exists / deleted, and
    # the claims log keeps version history for reverts. `prototype` names the
    # base-library component a renderer falls back to if the custom one is
    # missing or broken. `owner` is recorded now (single-operator today) so
    # multi-operator later is a filter, not a migration.

    def store_component(self, comp: dict, request: str = ""):
        cjson = json.dumps(comp, ensure_ascii=False, sort_keys=True)
        sha = hashlib.sha256(cjson.encode()).hexdigest()[:16]
        conn = psycopg2.connect(self.dsn)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO evoiot.events
                         (component, operation, data_id, actor, payload,
                          claim_predicate, claim_object, claim_status)
                       VALUES ('chatapp', 'claim_component_def', %s, 'building-agent',
                               %s, 'component_def', %s, 'approved')""",
                    (f"component:{self.tenant}:{comp['name']}",
                     json.dumps({"request": request, "component": comp}), sha))
                cur.execute(
                    """INSERT INTO evoiot.config_maps (tenant_id, name, config, description)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (tenant_id, name) DO UPDATE
                         SET config = EXCLUDED.config,
                             description = EXCLUDED.description,
                             updated_at = now()""",
                    (self.tenant, f"component:{comp['name']}", cjson,
                     comp.get("description", "")))
        finally:
            conn.close()

    def delete_component(self, name: str) -> bool:
        conn = psycopg2.connect(self.dsn)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO evoiot.events
                         (component, operation, data_id, actor,
                          claim_predicate, claim_object, claim_status)
                       VALUES ('chatapp', 'claim_component_def', %s, 'building-agent',
                               'component_def', null, 'retracted')""",
                    (f"component:{self.tenant}:{name}",))
                cur.execute(
                    """DELETE FROM evoiot.config_maps
                       WHERE tenant_id = %s AND name = %s""",
                    (self.tenant, f"component:{name}"))
                return cur.rowcount > 0
        finally:
            conn.close()

    def list_components(self) -> list[dict]:
        conn = psycopg2.connect(self.dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT config FROM evoiot.config_maps
                       WHERE tenant_id = %s AND name LIKE 'component:%%'
                       ORDER BY updated_at DESC""", (self.tenant,))
                out = []
                for (cfg,) in cur.fetchall():
                    c = cfg if isinstance(cfg, dict) else json.loads(cfg)
                    out.append({"name": c.get("name"), "prototype": c.get("prototype"),
                                "description": c.get("description", ""),
                                "owner": c.get("owner", "")})
                return out
        finally:
            conn.close()

    def get_component(self, name: str) -> dict | None:
        conn = psycopg2.connect(self.dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT config FROM evoiot.config_maps
                       WHERE tenant_id = %s AND name = %s""",
                    (self.tenant, f"component:{name}"))
                row = cur.fetchone()
                if not row:
                    return None
                return row[0] if isinstance(row[0], dict) else json.loads(row[0])
        finally:
            conn.close()
