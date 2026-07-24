"""Equipment discovery workflow using Restate."""

from restate import Workflow, WorkflowContext, WorkflowSharedContext
from pydantic import BaseModel

from shared import graph
from shared.llm import discover_equipment_from_rawtags, review_equipment_grouping
from shared.traced import traced_run, _emit_event


CHUNK_MAX_TAGS = 300   # keep each LLM call under the timeout / output ceiling


def _chunk_device_tags(tags: list[dict]) -> list[list[dict]]:
    """Split one device's tags into batches under CHUNK_MAX_TAGS. Sort by
    object_name first so a single equipment's points stay adjacent and a size
    cut rarely lands mid-equipment (e.g. an FCU device with ~71 units)."""
    if len(tags) <= CHUNK_MAX_TAGS:
        return [tags]
    ordered = sorted(tags, key=lambda t: (t.get("object_name") or "", t.get("id") or ""))
    return [ordered[i:i + CHUNK_MAX_TAGS]
            for i in range(0, len(ordered), CHUNK_MAX_TAGS)]


def _group_chunked(rawtags: list[dict], device_types: list[dict],
                   feedback: str = None) -> list[dict]:
    """Group tags in focused batches, not all at once. A monolithic 1059-tag
    call on a careful model exceeds the LLM timeout AND drifts (the smaller,
    focused scope is what makes the LLM get the chiller plant right). Split
    per BACnet device — equipment don't span devices, so that's lossless — then
    cap oversized devices into name-sorted batches. Results are merged."""
    by_device = {}
    for t in rawtags:
        by_device.setdefault(t.get("device_id", ""), []).append(t)

    merged = []
    for device_id, tags in by_device.items():
        for batch in _chunk_device_tags(tags):
            groups = discover_equipment_from_rawtags(batch, device_types, feedback=feedback)
            merged.extend(groups or [])
    return merged


class DiscoverRequest(BaseModel):
    """Request to discover equipment from raw tags."""
    tenant_id: str
    building: str | None = None       # optional scope within the tenant


equipment_discovery_workflow = Workflow("equipment_discovery")

# Rework rounds: a rejection with feedback re-runs the grouping with that
# guidance. Bounded so a stubborn disagreement terminates rather than spins.
MAX_ROUNDS = 3


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

    # Steps 3-6: propose -> review -> (rework with feedback) -> ratify.
    # Bounded so a stubborn disagreement ends rather than looping forever.
    feedback = None
    approved, rejected, history = [], [], []

    scope = rawtags          # round 1 groups everything; rework narrows to disputes

    for round_no in range(1, MAX_ROUNDS + 1):
        # Publish the round FIRST: creating proposals takes minutes, and a
        # review submitted during that window would otherwise read a stale
        # round and resolve an already-resolved promise, hanging the workflow.
        ctx.set("round", round_no)

        equipment_list = await traced_run(ctx,
            f"discover_equipment_r{round_no}",
            lambda sc=scope, fb=feedback: _group_chunked(sc, device_types, feedback=fb)
        )
        if not equipment_list:
            break

        # Self-check pass — a tool-grounded audit: each candidate is scored
        # against its real point signature (point_profile) and its type's peer
        # profile (tbox_profile), not by name. Drops non-equipment (all-sensor
        # headers/fragments, duplicates) and reclassifies signature mismatches
        # (e.g. a "Chiller" with a Valve signature). Applied to the in-memory
        # list BEFORE proposals, so it's plain list surgery — no graph churn.
        rawtag_by_id = {t["id"]: t for t in rawtags if t.get("id")}
        audit = await traced_run(ctx, f"self_check_r{round_no}",
            lambda el=equipment_list: review_equipment_grouping(
                el, rawtag_by_id, device_types))
        drop = set(audit.get("drop") or [])
        retype = {r["name"]: r["to_type"] for r in (audit.get("reclassify") or [])
                  if r.get("name") and r.get("to_type")}
        valid_types = {d.get("name") for d in device_types}
        if drop or retype:
            cleaned = []
            for e in equipment_list:
                nm = e.get("equipment_name")
                if nm in drop:
                    continue
                if nm in retype and retype[nm] in valid_types:
                    e = {**e, "equipment_type": retype[nm]}
                cleaned.append(e)
            equipment_list = cleaned

        # Already-ratified equipment must not be downgraded back to 'proposed'
        settled = {e["equipment_name"] for e in approved}
        proposed = await traced_run(ctx,
            f"create_proposals_r{round_no}",
            lambda el=equipment_list, sk=settled: _create_proposals(el, request.tenant_id, skip=sk)
        )
        if not proposed:
            break

        decisions = await ctx.promise(f"review_{round_no}").value()

        _emit_event(component="restate.discovery", operation="human_review",
                    data_id=ctx.key(), trace_id=ctx.key(), actor="human",
                    payload={"round": round_no, "decisions": decisions})

        by_name = {p["equipment_name"]: p for p in proposed}
        notes, disputed_tags = [], set()
        for d in decisions or []:
            name = d.get("equipment_name")
            if name not in by_name:
                continue
            if d.get("approved"):
                await traced_run(ctx, f"approve_{name}_r{round_no}",
                    lambda n=name: graph.update_equipment_status(request.tenant_id, n, "approved"),
                    data_id=f"{request.tenant_id}:{name}")
                approved.append(by_name[name])
            else:
                # capture the tags BEFORE deleting — they're the rework scope
                disputed_tags.update(by_name[name].get("rawtag_ids") or [])
                await traced_run(ctx, f"reject_{name}_r{round_no}",
                    lambda n=name: graph.delete_equipment(request.tenant_id, n),
                    data_id=f"{request.tenant_id}:{name}")
                rejected.append(by_name[name])
                if d.get("feedback"):
                    notes.append(f"- '{name}' (proposed as {by_name[name]['equipment_type']}) "
                                 f"was rejected: {d['feedback']}")

        history.append({"round": round_no, "proposed": len(proposed),
                        "approved": len(approved), "rejected": len(rejected),
                        "feedback_items": len(notes)})

        # No actionable guidance -> nothing to rework, we're done
        if not notes or round_no == MAX_ROUNDS:
            break

        # Rework ONLY the disputed tags. Re-running the whole grouping makes the
        # LLM re-derive everything from scratch and it drifts badly (observed:
        # a full re-run abandoned the good grouping for device-level buckets).
        scope = [rt for rt in rawtags if rt.get("id") in disputed_tags]
        if not scope:
            break
        feedback = "\n".join(notes)

    # Anything never ratified stays 'proposed' — never authoritative
    still_proposed = await traced_run(ctx, "pending_after_review",
        lambda: graph.get_pending_equipment(), data_id=ctx.key())

    return {
        "status": "completed",
        "approved": approved,
        "rejected": rejected,
        "still_proposed": [p for p in still_proposed
                           if p.get("tenant_id") == request.tenant_id],
        "rounds": history,
    }


@equipment_discovery_workflow.handler()
async def get_proposals(ctx: WorkflowSharedContext) -> dict:
    """Get the current equipment proposals pending review."""
    proposals = graph.get_pending_equipment()
    return {"status": "pending_review", "proposals": proposals}


@equipment_discovery_workflow.handler()
async def review(ctx: WorkflowSharedContext, decisions: list[dict]) -> dict:
    """Submit review decisions for the current round.

    Args:
        decisions: List of {equipment_name, approved: bool, feedback?: str}

    A rejection carrying `feedback` triggers a rework round: the grouping is
    re-run with that guidance instead of the correction being discarded.
    """
    round_no = await ctx.get("round") or 1
    await ctx.promise(f"review_{round_no}").resolve(decisions)
    return {"status": "review submitted", "round": round_no, "decisions": decisions}


def _create_proposals(equipment_list: list[dict], tenant_id: str,
                      skip: set = None) -> list[dict]:
    """Create proposed Equipment nodes and BELONGS_TO edges.

    `skip` holds names already ratified in this run — re-proposing them would
    downgrade an approved node back to 'proposed'."""
    proposals = []
    skip = skip or set()
    for equip in equipment_list:
        name = equip.get("equipment_name")
        etype = equip.get("equipment_type")
        rawtag_ids = equip.get("rawtag_ids", [])

        if not name or not etype or name in skip:
            continue

        for rawtag_id in rawtag_ids:
            graph.create_equipment_and_link(
                tenant_id=tenant_id,
                equipment_name=name,
                equipment_type=etype,
                rawtag_id=rawtag_id,
                status="proposed",   # ratified only via the review handler
            )

        proposals.append({
            "equipment_name": name,
            "equipment_type": etype,
            "rawtag_count": len(rawtag_ids),
            "rawtag_ids": rawtag_ids,   # rework scope if this gets rejected
            "status": "proposed",
        })

    return proposals
