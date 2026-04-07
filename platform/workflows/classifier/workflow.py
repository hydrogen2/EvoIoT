"""Classification workflow using Restate."""

from restate import Workflow, WorkflowContext, WorkflowSharedContext
from pydantic import BaseModel
from typing import Any

from ..shared import graph, llm


class ClassifyRequest(BaseModel):
    """Request to classify raw tags for a set of TBox types."""
    building_id: str
    source_id: str | None = None  # Optional: filter to specific source
    tbox_types: list[str]  # Property type names to classify


class ProposalInfo(BaseModel):
    """Info about a classification proposal."""
    rawtag_id: str
    tbox_type: str
    confidence: float
    reason: str
    status: str = "proposed"


class ReviewDecision(BaseModel):
    """Human decision on a proposal."""
    rawtag_id: str
    tbox_type: str
    approved: bool
    feedback: str | None = None  # Comment for rework if rejected


class ClassifyState(BaseModel):
    """Workflow state."""
    request: ClassifyRequest
    proposals: list[ProposalInfo] = []
    pending_review: list[ProposalInfo] = []
    approved: list[ProposalInfo] = []
    rejected: list[ProposalInfo] = []
    rework_feedback: str | None = None


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
    6. Rework if needed
    """
    state = ClassifyState(request=request)

    # Step 1: Fetch data
    rawtags = await ctx.run("fetch_rawtags", lambda: _fetch_rawtags(request))
    property_defs = await ctx.run("fetch_property_defs", lambda: _fetch_property_defs(request.tbox_types))

    if not rawtags:
        return {"status": "error", "message": "No RawTags found for context"}

    if not property_defs:
        return {"status": "error", "message": "No PropertyDefs found for requested types"}

    # Step 2: Classify with LLM
    classifications = await ctx.run(
        "classify",
        lambda: _classify(rawtags, request.tbox_types, property_defs, state.rework_feedback)
    )

    # Step 3: Create proposals in graph
    proposals = await ctx.run(
        "create_proposals",
        lambda: _create_proposals(classifications)
    )
    state.proposals = proposals
    state.pending_review = proposals.copy()

    # Step 4: Wait for human review
    # This promise will be resolved by external call to /classifier/{workflow_id}/review
    review_decisions = await ctx.promise("review").value()

    # Step 5: Process decisions
    to_rework = []
    feedback_parts = []

    for decision in review_decisions:
        proposal = next(
            (p for p in state.pending_review
             if p.rawtag_id == decision.rawtag_id and p.tbox_type == decision.tbox_type),
            None
        )
        if not proposal:
            continue

        if decision.approved:
            # Approve in graph
            await ctx.run(
                f"approve_{decision.tbox_type}",
                lambda d=decision: _approve_proposal(d.rawtag_id, d.tbox_type, "workflow")
            )
            proposal.status = "approved"
            state.approved.append(proposal)
        else:
            # Mark for rework
            proposal.status = "rejected"
            state.rejected.append(proposal)
            to_rework.append(decision.tbox_type)
            if decision.feedback:
                feedback_parts.append(f"{decision.tbox_type}: {decision.feedback}")

        state.pending_review = [p for p in state.pending_review if p != proposal]

    # Step 6: Rework if needed
    if to_rework and feedback_parts:
        state.rework_feedback = "\n".join(feedback_parts)

        # Re-classify with feedback
        rework_classifications = await ctx.run(
            "rework_classify",
            lambda: _classify(rawtags, to_rework, property_defs, state.rework_feedback)
        )

        # Create new proposals
        rework_proposals = await ctx.run(
            "create_rework_proposals",
            lambda: _create_proposals(rework_classifications)
        )

        state.pending_review.extend(rework_proposals)

        # Wait for another review round
        rework_decisions = await ctx.promise("rework_review").value()

        for decision in rework_decisions:
            if decision.approved:
                await ctx.run(
                    f"approve_rework_{decision.tbox_type}",
                    lambda d=decision: _approve_proposal(d.rawtag_id, d.tbox_type, "workflow")
                )

    return {
        "status": "completed",
        "approved": [p.model_dump() for p in state.approved],
        "rejected": [p.model_dump() for p in state.rejected]
    }


@classification_workflow.handler()
async def get_state(ctx: WorkflowSharedContext) -> dict:
    """Get the current workflow state (pending proposals, etc.)."""
    # This is a read-only handler to check status
    # In a real implementation, we'd store state in ctx and return it
    return {"status": "use /classifier/{id}/review to submit decisions"}


# Helper functions (run inside ctx.run for journaling)

async def _fetch_rawtags(request: ClassifyRequest) -> list[dict]:
    """Fetch RawTags from graph."""
    return await graph.get_rawtags_for_context(request.building_id, request.source_id)


async def _fetch_property_defs(tbox_types: list[str]) -> list[dict]:
    """Fetch PropertyDefs from graph."""
    return await graph.get_property_defs(tbox_types)


async def _classify(
    rawtags: list[dict],
    tbox_types: list[str],
    property_defs: list[dict],
    feedback: str | None
) -> dict[str, llm.ClassificationResult]:
    """Call LLM to classify."""
    return await llm.classify_rawtags(rawtags, tbox_types, property_defs, feedback)


async def _create_proposals(classifications: dict[str, llm.ClassificationResult]) -> list[ProposalInfo]:
    """Create proposal edges in graph."""
    proposals = []
    for tbox_type, result in classifications.items():
        for candidate in result.candidates:
            if candidate.rawtag_id:
                await graph.create_is_type_of_edge(
                    rawtag_id=candidate.rawtag_id,
                    property_name=tbox_type,
                    status="proposed",
                    confidence=candidate.confidence,
                    reason=candidate.reason
                )
                proposals.append(ProposalInfo(
                    rawtag_id=candidate.rawtag_id,
                    tbox_type=tbox_type,
                    confidence=candidate.confidence,
                    reason=candidate.reason,
                    status="proposed"
                ))
    return proposals


async def _approve_proposal(rawtag_id: str, tbox_type: str, approved_by: str) -> None:
    """Approve a proposal in graph."""
    await graph.update_is_type_of_status(
        rawtag_id=rawtag_id,
        property_name=tbox_type,
        status="approved",
        approved_by=approved_by
    )
