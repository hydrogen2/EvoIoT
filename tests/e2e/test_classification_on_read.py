"""
E2E test: classification-on-read flow.

Scenario:
  1. Seed RawTags (with descriptive metadata) and readings into a fresh DB
  2. First call to get_readings_by_type() finds no classification → triggers workflow
  3. Wait for workflow to produce proposals (LLM classifies based on metadata)
  4. Approve the proposals
  5. Second call to get_readings_by_type() returns the actual readings
"""

import time

import pytest
from conftest import seed_rawtag, seed_readings

TENANT = "test-e2e"
TBOX_TYPE = "ZoneAirTemperatureSensor"


@pytest.fixture(scope="module")
def seeded_data(db):
    """Seed RawTags with obvious temperature metadata and matching readings."""
    rawtag_id = seed_rawtag(
        db,
        tenant_id=TENANT,
        source_id="test-agent",
        device_id="9001",
        object_type="analog-value",
        object_instance="10",
        raw_data='{"object_name": "floor1_zone_air_temperature", "unit": "degrees-celsius", "object_type": "analog-value"}',
    )

    seed_readings(db, TENANT, rawtag_id, [
        {"value": 22.5, "age_seconds": 60},
        {"value": 23.0, "age_seconds": 120},
        {"value": 22.8, "age_seconds": 180},
    ])

    return {"rawtag_id": rawtag_id, "tenant_id": TENANT}


def test_classification_on_read(seeded_data, api, restate):
    rawtag_id = seeded_data["rawtag_id"]

    # ---------------------------------------------------------------
    # Step 1: First call — no classification exists, triggers workflow
    # ---------------------------------------------------------------
    r = api.get("/rpc/get_readings_by_type", params={
        "p_tbox_type": TBOX_TYPE,
        "p_tenant_id": TENANT,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("classification_pending", "ok"), f"Unexpected status: {body}"

    if body["status"] == "ok":
        # Already classified (possible on retry) — skip to verification
        assert len(body["data"]) > 0
        return

    # ---------------------------------------------------------------
    # Step 2: Wait for workflow to produce proposals
    # ---------------------------------------------------------------
    # The workflow ID is derived from tenant_id + tbox_type, base64 encoded
    # We need to find it. Poll Restate for active workflows.
    proposals = []
    workflow_id = None

    for attempt in range(60):
        # Try to find the workflow by checking invocations
        # The get_readings_by_type function encodes the ID as base64(tenant:type)
        import base64
        workflow_id = base64.b64encode(f"{TENANT}:{TBOX_TYPE}".encode()).decode()

        r = restate.get(f"/classifier/{workflow_id}/get_proposals")
        if r.status_code == 200:
            data = r.json()
            if data.get("proposals"):
                proposals = data["proposals"]
                break
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
    # Step 3: Approve the proposals
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
    for attempt in range(30):
        r = restate.get(f"/restate/workflow/classifier/{workflow_id}/output")
        if r.status_code == 200:
            output = r.json()
            if output.get("status") == "completed":
                break
        time.sleep(2)

    assert output.get("status") == "completed", f"Workflow not completed: {output}"

    # ---------------------------------------------------------------
    # Step 4: Second call — classification exists, returns readings
    # ---------------------------------------------------------------
    r = api.get("/rpc/get_readings_by_type", params={
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
