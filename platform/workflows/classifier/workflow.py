"""Classification workflow using Restate."""

from restate import Workflow, WorkflowContext, WorkflowSharedContext
from pydantic import BaseModel

from shared import graph
from shared.llm import classify_rawtags


class ClassifyRequest(BaseModel):
    """Request to classify raw tags for a set of TBox types."""
    tenant_id: str
    source_id: str | None = None
    tbox_types: list[str]


# Create the workflow
classification_workflow = Workflow("classifier")


@classification_workflow.main()
async def run(ctx: WorkflowContext, request: ClassifyRequest) -> dict:
    """
    Main classification workflow.

    1. Fetch RawTags and PropertyDefs
    2. Call LLM to classify
    3. Create proposals in graph
    4. Wait for human review
    5. Handle approvals/rejections
    """
    # Step 1: Fetch data from graph
    rawtags = await ctx.run(
        "fetch_rawtags",
        lambda: graph.get_rawtags_for_context(request.tenant_id, request.source_id)
    )

    if not rawtags:
        return {"status": "error", "message": "No RawTags found for context"}

    property_defs = await ctx.run(
        "fetch_property_defs",
        lambda: graph.get_property_defs(request.tbox_types)
    )

    # Step 2: Classify with LLM
    classifications = await ctx.run(
        "classify",
        lambda: classify_rawtags(rawtags, request.tbox_types, property_defs)
    )

    # Step 3: Create proposals in graph
    proposals = await ctx.run(
        "create_proposals",
        lambda: _create_proposals(classifications)
    )

    if not proposals:
        return {
            "status": "completed",
            "message": "No classifications proposed by LLM",
            "proposals": []
        }

    # Step 4: Wait for human review
    # Workflow suspends here until /classifier/{id}/review is called
    review_decisions = await ctx.promise("review").value()

    # Step 5: Process decisions
    approved = []
    rejected = []

    for decision in review_decisions:
        matching = [p for p in proposals
                   if p["rawtag_id"] == decision.get("rawtag_id")
                   and p["tbox_type"] == decision.get("tbox_type")]
        if matching:
            proposal = matching[0]
            if decision.get("approved"):
                await ctx.run(
                    f"approve_{proposal['tbox_type']}",
                    lambda p=proposal: graph.update_is_type_of_status(
                        p["rawtag_id"], p["tbox_type"], "approved", "workflow"
                    )
                )
                approved.append(proposal)
            else:
                await ctx.run(
                    f"reject_{proposal['tbox_type']}",
                    lambda p=proposal, d=decision: graph.update_is_type_of_status(
                        p["rawtag_id"], p["tbox_type"], "rejected",
                        feedback=d.get("feedback")
                    )
                )
                rejected.append(proposal)

    return {
        "status": "completed",
        "approved": approved,
        "rejected": rejected
    }


@classification_workflow.handler()
async def get_proposals(ctx: WorkflowSharedContext) -> dict:
    """Get the current proposals pending review."""
    # Query graph for proposals with status='proposed'
    proposals = graph.get_pending_proposals()
    return {"status": "pending_review", "proposals": proposals}


@classification_workflow.handler()
async def review(ctx: WorkflowSharedContext, decisions: list[dict]) -> dict:
    """Submit review decisions to complete the workflow.

    Args:
        decisions: List of {rawtag_id, tbox_type, approved, feedback?}
    """
    await ctx.promise("review").resolve(decisions)
    return {"status": "review submitted", "decisions": decisions}


# Helper functions (sync for ctx.run journaling)

def _create_proposals(classifications: dict) -> list[dict]:
    """Create proposal edges in graph for each classification."""
    proposals = []
    for tbox_type, result in classifications.items():
        for candidate in result.get("candidates", []):
            rawtag_id = candidate.get("rawtag_id")
            if rawtag_id:
                # Create IS_TYPE_OF edge in graph with status=proposed
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
