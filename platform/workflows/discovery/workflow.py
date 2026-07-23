"""Equipment discovery workflow using Restate."""

from restate import Workflow, WorkflowContext, WorkflowSharedContext
from pydantic import BaseModel

from shared import graph
from shared.llm import discover_equipment_from_rawtags
from shared.traced import traced_run, _emit_event


class DiscoverRequest(BaseModel):
    """Request to discover equipment from raw tags."""
    tenant_id: str
    building: str | None = None       # optional scope within the tenant


equipment_discovery_workflow = Workflow("equipment_discovery")


@equipment_discovery_workflow.main()
async def run(ctx: WorkflowContext, request: DiscoverRequest) -> dict:
    """
    Discover equipment by grouping RawTags using LLM.

    1. Fetch all RawTags for the tenant
    2. Fetch DeviceType ontology
    3. Call LLM to group tags by equipment
    4. Create proposals (Equipment nodes with status=proposed)
    5. Wait for human review
    6. Apply approved equipment, delete rejected
    """
    # Step 1: Fetch RawTags
    rawtags = await traced_run(ctx,
        "fetch_rawtags",
        lambda: graph.get_rawtags_for_context(request.tenant_id, request.building)
    )

    if not rawtags:
        return {"status": "error", "message": "No RawTags found for tenant"}

    # Step 2: Fetch DeviceType ontology
    device_types = await traced_run(ctx,
        "fetch_device_types",
        lambda: graph.get_device_types()
    )

    # Step 3: Call LLM to group by equipment
    equipment_list = await traced_run(ctx,
        "discover_equipment",
        lambda: discover_equipment_from_rawtags(rawtags, device_types)
    )

    if not equipment_list:
        return {"status": "completed", "message": "No equipment discovered", "equipment": []}

    # Step 4: Create Equipment nodes + BELONGS_TO edges
    created = await traced_run(ctx,
        "create_equipment",
        lambda: _create_proposals(equipment_list, request.tenant_id)
    )

    return {
        "status": "completed",
        "equipment_count": len(created),
        "equipment": created,
    }


@equipment_discovery_workflow.handler()
async def get_proposals(ctx: WorkflowSharedContext) -> dict:
    """Get the current equipment proposals pending review."""
    proposals = graph.get_pending_equipment()
    return {"status": "pending_review", "proposals": proposals}


@equipment_discovery_workflow.handler()
async def review(ctx: WorkflowSharedContext, decisions: list[dict]) -> dict:
    """Submit review decisions.

    Args:
        decisions: List of {equipment_name, approved: bool, feedback?: str}
    """
    await ctx.promise("review").resolve(decisions)
    return {"status": "review submitted", "decisions": decisions}


def _create_proposals(equipment_list: list[dict], tenant_id: str) -> list[dict]:
    """Create proposed Equipment nodes and BELONGS_TO edges."""
    proposals = []
    for equip in equipment_list:
        name = equip.get("equipment_name")
        etype = equip.get("equipment_type")
        rawtag_ids = equip.get("rawtag_ids", [])

        if not name or not etype:
            continue

        for rawtag_id in rawtag_ids:
            graph.create_equipment_and_link(
                tenant_id=tenant_id,
                equipment_name=name,
                equipment_type=etype,
                rawtag_id=rawtag_id,
                status="approved",
            )

        proposals.append({
            "equipment_name": name,
            "equipment_type": etype,
            "rawtag_count": len(rawtag_ids),
            "status": "proposed",
        })

    return proposals
