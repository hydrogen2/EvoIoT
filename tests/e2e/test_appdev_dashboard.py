"""E2E: the app-dev agent generates a working dashboard for the RP building.

Chat-to-dev for the app layer: a natural-language request goes to the chatapp's
/api/appdev, the agent composes a view spec from the function/component
vocabularies grounded in live building context, the spec validates, is stored
(config_maps projection + claim in the events log), and every block's query
returns live data through /api/data — i.e. the dashboard would render.

Requires the PERSISTENT stack with real RP data flowing (chatapp is not in
CORE_SERVICES and the RP readings come from the live collector):

    E2E_MANAGE_STACK=0 pytest test_appdev_dashboard.py -v

Skips itself when the chatapp or live readings are absent. The LLM output is
nondeterministic, so assertions are structural invariants, not exact specs.
"""

import json
import os
import sys

import httpx
import pytest

CHATAPP_URL = os.environ.get("CHATAPP_URL", "http://localhost:8899")
TENANT = "HDB"

# the grammar is importable straight from the chatapp source
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../platform/chatapp")))
import viewspec  # noqa: E402

REQUEST = ("A dashboard for the RP building: overall plant status at a glance — "
           "total chiller plant power, chilled water supply and return temps, "
           "active alarms, chiller temperature trends over the day, and power "
           "by equipment.")


@pytest.fixture(scope="module")
def chatapp():
    """Client for the chatapp; skip the module when it isn't serving live data."""
    client = httpx.Client(base_url=CHATAPP_URL, timeout=330)
    try:
        r = client.get("/building")
        r.raise_for_status()
        if r.json().get("live_points", 0) == 0:
            pytest.skip("chatapp up but no live RP readings — needs the persistent stack")
    except httpx.HTTPError:
        pytest.skip("chatapp not reachable — run the persistent stack (E2E_MANAGE_STACK=0)")
    yield client
    client.close()


@pytest.fixture(scope="module")
def generated(chatapp):
    r = chatapp.post("/api/appdev", json={"request": REQUEST})
    assert r.status_code == 200, f"appdev failed: {r.text[:800]}"
    return r.json()


def test_spec_is_valid(generated):
    assert generated["name"]
    assert generated["attempts"] <= 3
    errors = viewspec.validate(generated["spec"])
    assert not errors, f"stored spec fails the grammar: {errors}"


def test_spec_covers_the_request(generated):
    comps = [b["component"] for b in generated["spec"]["blocks"]]
    assert "stat" in comps, "no headline stat tiles"
    assert "trend" in comps, "no trend chart"
    assert "alarms" in comps, "no alarms block"
    assert generated["spec"]["building"] == "RP"


def test_every_block_query_returns_live_data(chatapp, generated):
    spec = generated["spec"]
    for i, b in enumerate(spec["blocks"]):
        if not b.get("query"):
            continue
        r = chatapp.post("/api/data", json={
            "fn": b["query"]["fn"], "args": b["query"].get("args", {}),
            "building": spec["building"]})
        assert r.status_code == 200, f"block {i} query failed: {r.text[:300]}"
        d = r.json()
        assert "error" not in d, f"block {i}: {d['error']}"
        if b["component"] == "alarms":
            # legitimately empty when nothing is tripped — but it must be
            # monitoring something, else the match regex is wrong
            assert d.get("monitored", 0) > 0, f"block {i}: alarms monitor nothing"
        elif b["component"] == "stat":
            assert d.get("value") is not None, f"block {i}: stat matched no live points"
        elif b["component"] == "trend":
            assert d.get("series"), f"block {i}: trend has no series"
            assert all(s["points"] for s in d["series"])
        else:
            assert d.get("rows"), f"block {i}: no rows"


def test_spec_is_stored_and_page_serves(chatapp, generated, db):
    name = generated["name"]
    r = chatapp.get(f"/api/view/{name}")
    assert r.status_code == 200
    assert r.json() == generated["spec"]

    listed = chatapp.get("/api/views").json()["views"]
    assert any(v["name"] == name for v in listed)

    # the renderer page and the component library both serve
    page = chatapp.get(f"/view/{name}")
    assert page.status_code == 200 and "components.js" in page.text
    assert chatapp.get("/static/components.js").status_code == 200

    # provenance: the publish is a claim in the events log
    with db.cursor() as cur:
        cur.execute(
            """SELECT count(*) FROM evoiot.events
               WHERE component = 'chatapp' AND claim_predicate = 'view_spec'
                 AND data_id = %s AND claim_status = 'approved'""",
            (f"view:{TENANT}:{generated['spec']['building']}:{name}",))
        assert cur.fetchone()[0] >= 1, "no view_spec claim recorded"


# ── The unified agent: chat and app-dev are the same agent ──────────

def test_chat_answers_from_tools(chatapp):
    """A live value can only come from a tool call — the inventory sits in the
    agent's context, but current readings never do."""
    r = chatapp.post("/chat", json={
        "message": "What is the total plant electrical power draw right now, in kW?"})
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    assert d["answer"].strip()
    assert d["tools"], "agent answered a live-value question without calling any tool"
    assert any(ch.isdigit() for ch in d["answer"]), "answer carries no number"


def test_chat_can_pin_a_view(chatapp):
    """Crystallization: a chat request publishes a working view via publish_view."""
    r = chatapp.post("/chat", json={
        "message": "Pin a dashboard named e2e-pin-test with one stat: total plant "
                   "power (sum of kw_active). Just that one block."})
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    assert d["published"], f"nothing published; answer: {d['answer'][:200]}"
    spec = chatapp.get(f"/api/view/{d['published']}").json()
    assert not viewspec.validate(spec)
    assert d["published"] in d["answer"] or "/view/" in d["answer"]


def test_chat_edits_open_view_in_place(chatapp):
    """Iterative dev: with a view open on screen, "add X to this" republishes
    the SAME view with the addition, keeping the existing blocks.
    (Depends on test_chat_can_pin_a_view having published e2e-pin-test.)"""
    before = chatapp.get("/api/view/e2e-pin-test").json()
    r = chatapp.post("/chat", json={
        "message": "Add a block to this dashboard showing active alarms.",
        "view": "e2e-pin-test"})
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    assert d["published"] == "e2e-pin-test", \
        f"expected in-place update, got {d['published']!r}: {d['answer'][:200]}"
    after = chatapp.get("/api/view/e2e-pin-test").json()
    assert not viewspec.validate(after)
    comps = [b["component"] for b in after["blocks"]]
    assert "alarms" in comps, f"no alarms block added: {comps}"
    assert len(after["blocks"]) >= len(before["blocks"]), "existing blocks were dropped"


def test_chat_builds_custom_component(chatapp):
    """The private component overlay: when base components can't express the
    ask, the agent authors one (wrapping a base prototype), publishes it, and
    uses it in the view. (Depends on e2e-pin-test existing.)"""
    r = chatapp.post("/chat", json={
        "message": "Add a block to this dashboard titled 'Power points': a table "
                   "of latest points matching kw_active, with a text input above "
                   "it that filters rows by equipment name substring. The base "
                   "table can't do that, so build a custom component for it "
                   "(wrap the base table).",
        "view": "e2e-pin-test"})
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    assert d["published"] == "e2e-pin-test", \
        f"expected e2e-pin-test updated, got {d['published']!r}: {d['answer'][:200]}"

    spec = chatapp.get("/api/view/e2e-pin-test").json()
    custom_blocks = [b for b in spec["blocks"]
                     if b["component"] not in viewspec.COMPONENTS]
    assert custom_blocks, f"no custom-component block in spec: " \
        f"{[b['component'] for b in spec['blocks']]}"
    name = custom_blocks[0]["component"]

    comp = chatapp.get(f"/api/component/{name}")
    assert comp.status_code == 200, f"component {name!r} not stored"
    cd = comp.json()
    assert "render" in cd["code"], "component code defines no render()"
    assert not viewspec.validate(spec, custom_components={name})
