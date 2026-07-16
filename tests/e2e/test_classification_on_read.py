"""
E2E test: equipment discovery + classification-on-read flow with provenance verification.

Scenario:
  1. Seed RawTags and readings via MQTT (flows through Bento → Postgres)
  2. Trigger equipment discovery — LLM groups RawTags into Equipment nodes
  3. First call to get_readings_by_type(equipment, type) finds no classification
     → triggers classifier workflow (scoped to the equipment)
  4. Wait for workflow to produce proposals (LLM classifies based on metadata)
  5. Approve the proposals
  6. Second call to get_readings_by_type() returns the actual readings
  7. Verify the full provenance chain in evoiot.events

Note: the tenant is unique per run. Restate workflow keys
(equipment_discovery/<b64 tenant>, classifier/<b64 tenant:equipment:type>)
are single-use, so re-running against a live stack (E2E_MANAGE_STACK=0)
needs fresh keys.
"""

import base64
import time

import pytest
from conftest import publish_discovery, publish_telemetry, wait_for_db_rows

TENANT = "test-e2e-" + time.strftime("%Y%m%d%H%M%S", time.gmtime())
TBOX_TYPE = "zone_air_temp"
SOURCE_ID = "test-agent"
DEVICE_ID = "9001"


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


@pytest.fixture(scope="module")
def seeded_data(db, mqtt_client):
    """Seed RawTags via MQTT discovery and readings via MQTT telemetry."""
    # Publish discovery message — Bento creates RawTag via upsert_rawtag()
    publish_discovery(mqtt_client, TENANT, SOURCE_ID, devices=[
        {
            "device_id": DEVICE_ID,
            "objects": [
                {
                    "object_type": "analog-value",
                    "object_instance": "10",
                    "object_name": "floor1_zone_air_temperature",
                    "unit": "degrees-celsius",
                }
            ]
        }
    ])

    # Wait for RawTag to appear in graph (scoped to this run's tenant)
    rawtag_id = None
    for attempt in range(30):
        with db.cursor() as cur:
            cur.execute("LOAD 'age'")
            cur.execute("SET search_path = ag_catalog, evoiot, public")
            cur.execute(f"""
                SELECT id FROM cypher('platform', $$
                    MATCH (r:RawTag)
                    WHERE r.building_id = '{TENANT}'
                      AND r.object_type = 'analog-value' AND r.object_instance = '10'
                    RETURN r.id
                $$) AS (id agtype)
            """)
            row = cur.fetchone()
            if row:
                rawtag_id = str(row[0]).strip('"')
                break
        time.sleep(2)

    assert rawtag_id is not None, "RawTag not created from MQTT discovery after 60s"

    # Publish telemetry readings via MQTT — Bento writes to readings table
    publish_telemetry(mqtt_client, TENANT, SOURCE_ID, [
        {"value": 22.5, "device_id": DEVICE_ID, "object_type": "analog-value", "object_instance": "10"},
        {"value": 23.0, "device_id": DEVICE_ID, "object_type": "analog-value", "object_instance": "10"},
        {"value": 22.8, "device_id": DEVICE_ID, "object_type": "analog-value", "object_instance": "10"},
    ])

    # Wait for readings to appear in DB
    wait_for_db_rows(
        db,
        "SELECT id FROM evoiot.readings WHERE tenant_id = %s AND rawtag_id = %s",
        (TENANT, rawtag_id),
        min_count=3,
    )

    return {"rawtag_id": rawtag_id, "tenant_id": TENANT}


def test_classification_on_read(seeded_data, api, restate, db):
    rawtag_id = seeded_data["rawtag_id"]

    # ---------------------------------------------------------------
    # Step 1: Trigger equipment discovery (LLM groups RawTags)
    # ---------------------------------------------------------------
    r = api.post("/rpc/discover_equipment", json={"p_tenant_id": TENANT})
    assert r.status_code == 200, f"discover_equipment failed: {r.text}"
    assert r.json()["status"] == "discovery_started"

    # ---------------------------------------------------------------
    # Step 2: Wait for Equipment to appear (LLM call in flight).
    # The LLM may create several equipment groups (e.g. one from the
    # device-level tag) — pick the one our RawTag BELONGS_TO, since
    # that is the scope the classifier will search in.
    # ---------------------------------------------------------------
    equipment = None
    for attempt in range(60):
        with db.cursor() as cur:
            cur.execute("LOAD 'age'")
            cur.execute("SET search_path = ag_catalog, evoiot, public")
            cur.execute(f"""
                SELECT name FROM cypher('platform', $$
                    MATCH (r:RawTag {{id: '{rawtag_id}'}})-[:BELONGS_TO]->(e:Equipment)
                    RETURN e.name
                $$) AS (name agtype)
            """)
            row = cur.fetchone()
            if row:
                equipment = str(row[0]).strip('"')
                break
        time.sleep(3)

    assert equipment is not None, (
        "No equipment discovered after 180s. The equipment_discovery workflow "
        "may have failed (check the LLM: docker logs evoiot-workflows, and "
        f"Restate invocation equipment_discovery/{_b64(TENANT)})"
    )

    # ---------------------------------------------------------------
    # Step 3: First read — no classification exists, triggers classifier
    # ---------------------------------------------------------------
    r = api.post("/rpc/get_readings_by_type", json={
        "p_equipment": equipment,
        "p_tbox_type": TBOX_TYPE,
        "p_tenant_id": TENANT,
    })
    assert r.status_code == 200, f"get_readings_by_type failed: {r.text}"
    body = r.json()
    assert body["status"] in ("classification_pending", "ok"), f"Unexpected status: {body}"

    if body["status"] == "ok":
        # Already classified (possible on retry) — skip to verification
        assert len(body["data"]) > 0
        return

    # ---------------------------------------------------------------
    # Step 4: Wait for classifier workflow to produce proposals
    # ---------------------------------------------------------------
    workflow_id = _b64(f"{TENANT}:{equipment}:{TBOX_TYPE}")
    proposals = []

    for attempt in range(60):
        r = restate.get(f"/classifier/{workflow_id}/get_proposals")
        if r.status_code == 200:
            data = r.json()
            # get_proposals returns ALL pending proposals — keep this run's only
            mine = [p for p in data.get("proposals", [])
                    if p.get("rawtag_id", "").startswith(TENANT + ":")]
            if mine:
                proposals = mine
                break
        # Fail fast if the workflow already completed without proposals
        # (LLM matched nothing) instead of polling out the full timeout.
        out = restate.get(f"/restate/workflow/classifier/{workflow_id}/output")
        if out.status_code == 200 and out.json().get("status") == "completed":
            pytest.fail(f"Classifier completed without proposals: {out.json()}")
        time.sleep(2)

    assert len(proposals) > 0, (
        f"No proposals after 120s. Workflow may have failed. "
        f"Last response: {r.status_code} {r.text}"
    )

    # Verify the proposal matches our seeded RawTag
    proposed_ids = [p["rawtag_id"] for p in proposals]
    assert rawtag_id in proposed_ids, (
        f"Expected {rawtag_id} in proposals, got {proposed_ids}"
    )

    # ---------------------------------------------------------------
    # Step 5: Approve the proposals
    # ---------------------------------------------------------------
    decisions = [
        {"rawtag_id": p["rawtag_id"], "tbox_type": p["tbox_type"], "approved": True}
        for p in proposals
    ]
    r = restate.post(
        f"/classifier/{workflow_id}/review",
        json=decisions,
    )
    assert r.status_code == 200, f"Review failed: {r.text}"

    # Wait for workflow to complete
    output = {}
    for attempt in range(30):
        r = restate.get(f"/restate/workflow/classifier/{workflow_id}/output")
        if r.status_code == 200:
            output = r.json()
            if output.get("status") == "completed":
                break
        time.sleep(2)

    assert output.get("status") == "completed", f"Workflow not completed: {output}"

    # ---------------------------------------------------------------
    # Step 6: Second read — classification exists, returns readings
    # ---------------------------------------------------------------
    r = api.post("/rpc/get_readings_by_type", json={
        "p_equipment": equipment,
        "p_tbox_type": TBOX_TYPE,
        "p_tenant_id": TENANT,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok", f"Expected 'ok', got: {body}"
    assert len(body["data"]) >= 3, f"Expected >=3 readings, got {len(body['data'])}"
    assert rawtag_id in body["rawtag_ids"], f"Expected {rawtag_id} in rawtag_ids"

    # Verify reading values
    values = sorted([d["value"] for d in body["data"]])
    assert 22.5 in values
    assert 23.0 in values

    # ---------------------------------------------------------------
    # Step 7: Verify provenance chain in events table
    # ---------------------------------------------------------------
    # Events are linked by data_id (rawtag_id) OR trace_id (workflow keys).
    # Both workflows use their Restate key as trace_id; approval/graph events
    # use rawtag_id as data_id.
    discovery_workflow_id = _b64(TENANT)
    with db.cursor() as cur:
        cur.execute(
            """SELECT component, operation, data_id, trace_id, actor, payload
               FROM evoiot.events
               WHERE data_id = %s OR trace_id IN (%s, %s)
               ORDER BY event_time""",
            (rawtag_id, workflow_id, discovery_workflow_id)
        )
        events = cur.fetchall()

    components = {e[0] for e in events}
    operations = {e[1] for e in events}

    # Verify events from all layers
    assert "postgres" in components, (
        f"No postgres events (readings INSERT). Components: {components}"
    )
    assert "graph" in components, (
        f"No graph events (upsert_rawtag, IS_TYPE_OF). Components: {components}"
    )
    assert "restate.classifier" in components, (
        f"No restate events (workflow steps). Components: {components}"
    )

    # Verify key workflow steps were recorded
    # (equipment discovery workflow)
    assert "discover_equipment" in operations, f"Missing discover_equipment. Operations: {operations}"
    assert "create_equipment" in operations, f"Missing create_equipment. Operations: {operations}"
    # (classifier workflow)
    assert "fetch_rawtags" in operations, f"Missing fetch_rawtags. Operations: {operations}"
    assert "classify" in operations, f"Missing classify. Operations: {operations}"
    assert "create_proposals" in operations, f"Missing create_proposals. Operations: {operations}"

    # Verify graph + relational events
    assert "upsert_rawtag" in operations, f"Missing upsert_rawtag. Operations: {operations}"
    assert "INSERT" in operations, f"Missing INSERT (readings). Operations: {operations}"

    # Should have events from all layers of both workflows
    assert len(events) >= 10, (
        f"Expected >= 10 provenance events, got {len(events)}: "
        + ", ".join(f"{e[0]}/{e[1]}" for e in events)
    )

    # Verify Bento tracer events exist (input_mqtt spans from pg_events tracer)
    with db.cursor() as cur:
        cur.execute(
            """SELECT component, operation FROM evoiot.events
               WHERE component = 'bento' AND operation = 'input_mqtt'"""
        )
        bento_events = cur.fetchall()

    assert len(bento_events) >= 2, (
        f"Expected >= 2 bento input_mqtt events (discovery + telemetry), got {len(bento_events)}"
    )

    print(f"\nProvenance chain for {rawtag_id} (classifier {workflow_id}, discovery {discovery_workflow_id}):")
    for e in events:
        print(f"  [{e[0]}] {e[1]} data_id={e[2]} (actor={e[4]})")
    print(f"  + {len(bento_events)} bento input_mqtt events (platform entry points)")
