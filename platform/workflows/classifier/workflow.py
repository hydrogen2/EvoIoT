"""Classification workflow using Restate."""

from restate import Workflow, WorkflowContext, WorkflowSharedContext
from pydantic import BaseModel

from shared import graph
from shared.llm import classify_rawtags
from shared.traced import traced_run, _emit_event


class ClassifyRequest(BaseModel):
    """Request to classify raw tags for a specific equipment and point types."""
    tenant_id: str
    equipment: str          # equipment name (e.g. "PAU_01_103_1")
    tbox_types: list[str]


# Create the workflow
classification_workflow = Workflow("classifier")

# Bounded feedback-driven rework (see equipment_discovery for the same pattern)
MAX_ROUNDS = 3


@classification_workflow.main()
async def run(ctx: WorkflowContext, request: ClassifyRequest) -> dict:
    """
    Main classification workflow.

    1. Fetch RawTags belonging to the equipment
    2. Fetch PropertyDefs and equipment type
    3. Call LLM to classify (scoped to this equipment)
    4. Create proposals in graph
    5. Wait for human review
    6. Handle approvals/rejections
    """
    # Step 1: Fetch RawTags for this equipment
    rawtags = await traced_run(ctx,
        "fetch_rawtags",
        lambda: graph.get_equipment_rawtags(request.tenant_id, request.equipment)
    )

    if not rawtags:
        return {"status": "error", "message": f"No RawTags found for equipment {request.equipment}"}

    # Step 2: Fetch PropertyDefs and equipment info
    property_defs = await traced_run(ctx,
        "fetch_property_defs",
        lambda: graph.get_property_defs(request.tbox_types)
    )

    # Get equipment type from graph
    equip_info = await traced_run(ctx,
        "fetch_equipment_info",
        lambda: _get_equipment_type(request.tenant_id, request.equipment)
    )

    # Steps 3-6: propose -> review -> (rework with feedback) -> ratify.
    # Rework re-classifies ONLY the rejected types (points are independent),
    # bounded so a stubborn disagreement terminates.
    pending_types = list(request.tbox_types)
    feedback = None
    approved, rejected, history = [], [], []

    for round_no in range(1, MAX_ROUNDS + 1):
        classifications = await traced_run(ctx,
            f"classify_r{round_no}",
            lambda t=pending_types, fb=feedback: classify_rawtags(
                rawtags, t, property_defs,
                equipment_name=request.equipment,
                equipment_type=equip_info.get("device_type", ""),
                feedback=fb,
            )
        )

        proposals = await traced_run(ctx,
            f"create_proposals_r{round_no}",
            lambda c=classifications: _create_proposals(c)
        )
        if not proposals:
            break

        ctx.set("round", round_no)
        review_decisions = await ctx.promise(f"review_{round_no}").value()

        _emit_event(
            component="restate.classifier",
            operation="human_review",
            data_id=ctx.key(),
            trace_id=ctx.key(),
            actor="human",
            payload={"round": round_no, "decisions": review_decisions},
        )

        notes, redo = [], []
        for decision in review_decisions or []:
            matching = [p for p in proposals
                        if p["rawtag_id"] == decision.get("rawtag_id")
                        and p["tbox_type"] == decision.get("tbox_type")]
            if not matching:
                continue
            proposal = matching[0]
            if decision.get("approved"):
                await traced_run(ctx, f"approve_{proposal['tbox_type']}_r{round_no}",
                    lambda p=proposal: graph.update_is_type_of_status(
                        p["rawtag_id"], p["tbox_type"], "approved", "workflow"),
                    data_id=proposal["rawtag_id"])
                approved.append(proposal)
            else:
                fb = decision.get("feedback")
                await traced_run(ctx, f"reject_{proposal['tbox_type']}_r{round_no}",
                    lambda p=proposal, f=fb: graph.update_is_type_of_status(
                        p["rawtag_id"], p["tbox_type"], "rejected", feedback=f),
                    data_id=proposal["rawtag_id"])
                rejected.append(proposal)
                if fb:
                    notes.append(f"- '{proposal['tbox_type']}' matched to "
                                 f"{proposal['rawtag_id']} was rejected: {fb}")
                    redo.append(proposal["tbox_type"])

        history.append({"round": round_no, "proposed": len(proposals),
                        "approved": len(approved), "rejected": len(rejected)})

        if not notes or round_no == MAX_ROUNDS:
            break
        pending_types = sorted(set(redo))
        feedback = "\n".join(notes)

    return {
        "status": "completed",
        "approved": approved,
        "rejected": rejected,
        "rounds": history,
    }


@classification_workflow.handler()
async def get_proposals(ctx: WorkflowSharedContext) -> dict:
    """Get the current proposals pending review."""
    proposals = graph.get_pending_proposals()
    return {"status": "pending_review", "proposals": proposals}


@classification_workflow.handler()
async def review(ctx: WorkflowSharedContext, decisions: list[dict]) -> dict:
    """Submit review decisions to complete the workflow.

    Args:
        decisions: List of {rawtag_id, tbox_type, approved, feedback?}
    """
    round_no = await ctx.get("round") or 1
    await ctx.promise(f"review_{round_no}").resolve(decisions)
    return {"status": "review submitted", "round": round_no, "decisions": decisions}


# Helper functions

def _get_equipment_type(tenant_id: str, equipment_name: str) -> dict:
    """Get the device type of an equipment from graph."""
    equip_id = f"{tenant_id}:{equipment_name}"
    query = f"""
        MATCH (e:Equipment {{id: '{equip_id}'}})-[:IS_TYPE_OF]->(d:DeviceType)
        RETURN d.name
    """
    results = graph.execute_cypher(query)
    if results:
        dtype = results[0]
        if isinstance(dtype, dict) and 'properties' in dtype:
            return {"device_type": dtype['properties'].get('name', '')}
        return {"device_type": str(dtype).strip('"')}
    return {"device_type": ""}


def _create_proposals(classifications: dict) -> list[dict]:
    """Create proposal edges in graph for each classification."""
    proposals = []
    for tbox_type, result in classifications.items():
        for candidate in result.get("candidates", []):
            rawtag_id = candidate.get("rawtag_id")
            if rawtag_id:
                graph.create_is_type_of_edge(
                    rawtag_id=rawtag_id,
                    property_name=tbox_type,
                    status="proposed",
                    confidence=candidate.get("confidence", 0.0),
                    reason=candidate.get("reason", "")
                )
                proposals.append({
                    "rawtag_id": rawtag_id,
                    "tbox_type": tbox_type,
                    "confidence": candidate.get("confidence", 0.0),
                    "reason": candidate.get("reason", ""),
                    "status": "proposed"
                })
    return proposals
