"""The building agent — one agent, two entry points.

Chat (/chat) and app-dev (/api/appdev) are the same agent: a tool-calling
loop over the function registry, plus publish_view. Answering "what's the
chiller drawing?" and pinning "a dashboard of plant power" use the same
verbs — a published view is literally the queries the agent would have run
to answer you, crystallized into blocks (GUI = memoized chat).

The claude-shim flattens messages into one prompt (claude -p has no tool
channel), so tool use is a text protocol: the model emits exactly one JSON
object per step — {"tool": ..., "args": ...} or {"answer": ...} — and the
loop executes, appends the result, and re-prompts. A malformed step is fed
back as an error, not crashed on.
"""

from __future__ import annotations

import json
import re
import urllib.request

import functions
import viewspec

MAX_STEPS = 8            # tool calls + retries per user turn
RESULT_BUDGET = 6000     # chars of tool result fed back per step

SYSTEM = """You are the live operations agent for the {building} building — a chiller plant plus air-side units, monitored in real time. You answer operators' questions from live data and, when asked, pin live dashboards ("views") for them.

## How you act
Respond with EXACTLY ONE JSON object and nothing else — no markdown, no prose outside it:
- {{"tool": "<name>", "args": {{...}}}} — look at data, or publish a view
- {{"answer": "<your reply to the user>"}} — when you have what you need

HARD RULE — grounding: a numeric reading may appear in an answer ONLY if it came back from a tool result earlier in this conversation. You have NO live values in this prompt; for any question about current conditions your first response MUST be a tool call. Never estimate, recall, or extrapolate a value — a plausible invented number is worse than no answer. Answer concisely and concretely: numbers with units, named equipment. If data isn't there, say so plainly.

## Data tools
{fn_catalog}

## View tools
- **publish_view**(spec: <view spec object>) — validate + pin a live dashboard; returns its URL, or the validation errors to fix. Use when the user wants a dashboard/view/app pinned, or agrees to one.
- **list_views**() — the views already published.
- **get_view**(name: str) — the full spec of a published view.

## Custom components (this installation's private library overlay)
When the base components can't express what the user wants (interactive filters, sorting, drill-downs, a bespoke layout), CREATE a component instead of refusing:
- **publish_component**(name, description, prototype, code) — kebab-case name; prototype = the base component it derives from (used as fallback if this one breaks); code = JavaScript defining `function render(root, data, props)`.
- **get_component**(name) — its stored definition incl. code (to modify it: edit and re-publish same name).
- **delete_component**(name) — user says discard/delete/do-over.

Component code runs sandboxed in its own frame:
- `render(root, data, props)` is re-invoked with the block's live query result on every refresh; data is exactly what the block's query fn returns.
- The base library is preloaded: `window.Components` (stat, trend, bars, table, alarms, note) and `window.VizPalette`. PREFER WRAPPING a base component over redrawing — e.g. a filterable table = draw a <select> of distinct values, then `Components.table(mount, {{rows: filtered}}, props)` on change.
- `await queryData(fn, args)` fetches more data on user interaction (read functions only).
- Vanilla JS only, no external URLs (they won't load), keep it small. Errors inside render() show in the block and the view falls back to the prototype on next load.

After publishing, reference it in a view spec like any component: {{"component": "<its name>", "query": {{...}}}}. Custom blocks may also omit query entirely if they fetch via queryData.
Existing custom components: {custom_components}

Views are ITERATED, not one-shot: to change a view, send publish_view the FULL modified spec with the SAME name — it replaces the old version. Keep the parts the user didn't ask to change. If the user asks for a block, add it even when it is currently empty — components have designed empty states (alarms shows "all clear"); don't refuse or ask permission because there happens to be no data this minute.

## View spec grammar (for publish_view)
{grammar}

{component_catalog}

## The building ({building})
{context}

## Point-name matching
`match` args are case-insensitive regexes over the point names above. Anchor them so they don't over-match: 'kw_active$' not 'kw'. Setpoints (*_sp, write_*) are targets, not measurements — match '_raw_temp_chws$' style to exclude them. Prefer device_type filters for fleet summaries, equipment for a named unit.

After a successful publish_view, answer with the view's URL so the user can open it. If publish_view returns errors, fix the spec and call it again."""


def _extract_json(content: str):
    """First JSON object in the model's output, tolerant of fences/preamble."""
    s = content
    if "```" in s:
        m = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
        if m:
            s = m.group(1)
    i = s.find("{")
    if i < 0:
        raise ValueError("no JSON object in response")
    return json.JSONDecoder().raw_decode(s[i:])[0]


def _clip(result) -> str:
    s = json.dumps(result, default=str)
    if len(s) <= RESULT_BUDGET:
        return s
    if isinstance(result, dict) and isinstance(result.get("rows"), list):
        rows = result["rows"]
        keep = dict(result)
        while len(json.dumps(keep, default=str)) > RESULT_BUDGET and len(keep["rows"]) > 5:
            keep["rows"] = keep["rows"][:max(5, len(keep["rows"]) // 2)]
        keep["truncated"] = f"{len(rows) - len(keep['rows'])} of {len(rows)} rows omitted — narrow the match if you need them"
        return json.dumps(keep, default=str)
    return s[:RESULT_BUDGET] + '…"}'


class Agent:
    def __init__(self, llm_base, llm_key, model, store, tenant, building,
                 context_fn):
        self.llm_base, self.llm_key, self.model = llm_base, llm_key, model
        self.store = store            # appdev.AppDev: view storage
        self.tenant, self.building = tenant, building
        self.context_fn = context_fn  # () -> live building context string

    # ── LLM ─────────────────────────────────────────────────────────

    def _llm(self, prompt: str) -> str:
        body = json.dumps({"model": self.model, "max_tokens": 8192,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(
            f"{self.llm_base}/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.llm_key}"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)["choices"][0]["message"]["content"]

    # ── Tools ───────────────────────────────────────────────────────

    def _run_tool(self, name: str, args: dict, trace: list) -> dict:
        if name == "publish_view":
            spec = args.get("spec", args if "blocks" in args else {})
            customs = {c["name"] for c in self.store.list_components()}
            errors = viewspec.validate(spec, custom_components=customs)
            if not errors:
                errors = self._liveness_check(spec, customs)
            entry = {"tool": name, "ok": not errors}
            if errors:
                entry["errors"] = errors
                trace.append(entry)
                return {"ok": False, "errors": errors}
            self.store.store(spec, request=trace and trace[0].get("user", "") or "")
            entry["name"] = spec["name"]
            entry["spec"] = spec
            trace.append(entry)
            return {"ok": True, "name": spec["name"], "url": f"/view/{spec['name']}"}
        if name == "list_views":
            trace.append({"tool": name, "ok": True})
            return {"views": self.store.list_views()}
        if name == "get_view":
            spec = self.store.get_view(args.get("name", ""))
            trace.append({"tool": name, "ok": spec is not None})
            return spec if spec is not None else {"error": f"no view named {args.get('name')!r}"}
        if name == "publish_component":
            errors = self._check_component(args)
            entry = {"tool": name, "ok": not errors, "name": args.get("name")}
            if errors:
                entry["errors"] = errors
                trace.append(entry)
                return {"ok": False, "errors": errors}
            comp = {"name": args["name"], "description": args.get("description", ""),
                    "prototype": args.get("prototype", ""), "code": args["code"],
                    "owner": ""}
            self.store.store_component(comp, request=trace[0].get("user", ""))
            trace.append(entry)
            return {"ok": True, "name": args["name"],
                    "note": "published — reference it in a view spec to see it live"}
        if name == "get_component":
            comp = self.store.get_component(args.get("name", ""))
            trace.append({"tool": name, "ok": comp is not None})
            return comp if comp else {"error": f"no component named {args.get('name')!r}"}
        if name == "delete_component":
            ok = self.store.delete_component(args.get("name", ""))
            trace.append({"tool": name, "ok": ok})
            return {"ok": ok}
        result = functions.call(name, args, self.tenant, self.building)
        trace.append({"tool": name, "args": args, "ok": True})
        return result

    @staticmethod
    def _check_component(args: dict) -> list[str]:
        errors = []
        name = args.get("name", "")
        if not isinstance(name, str) or not re.match(r"^[a-z0-9][a-z0-9-]{1,40}$", name):
            errors.append("component 'name' must be kebab-case, 2-41 chars")
        if name in viewspec.COMPONENTS:
            errors.append(f"'{name}' is a base component — pick a distinct name")
        code = args.get("code", "")
        if not isinstance(code, str) or "function render" not in code and "render =" not in code:
            errors.append("'code' must be a JS string defining function render(root, data, props)")
        elif len(code) > 20000:
            errors.append(f"'code' too large ({len(code)} chars, max 20000) — wrap a base component instead")
        proto = args.get("prototype", "")
        if proto and proto not in viewspec.COMPONENTS:
            errors.append(f"'prototype' must be a base component ({', '.join(viewspec.COMPONENTS)}) or empty")
        return errors

    def _liveness_check(self, spec: dict, customs=()) -> list[str]:
        """Self-check before publish: every queried block must return data NOW
        (except alarms — its empty state means all-clear, and note has no
        query). A block that matches nothing live is a miswritten match/filter,
        and the agent should fix it at generation time, not ship a dead tile."""
        errors = []
        for i, b in enumerate(spec.get("blocks", [])):
            q = b.get("query")
            if not q or b["component"] in ("alarms", "note"):
                continue
            try:
                d = functions.call(q["fn"], q.get("args", {}),
                                   self.tenant, spec.get("building", self.building))
            except (ValueError, TypeError) as e:
                errors.append(f"blocks[{i}]: query failed: {e}")
                continue
            live = (d.get("value") is not None or bool(d.get("rows"))
                    or bool(d.get("series")))
            if not live:
                errors.append(
                    f"blocks[{i}] ({b['component']} {b.get('title', '')!r}): query "
                    f"returned NO live data — the match/filters hit nothing that is "
                    f"currently reporting. Check the match against real point names "
                    f"(call latest to probe), adjust, or drop the block.")
        return errors

    # ── The loop ────────────────────────────────────────────────────

    def _system(self) -> str:
        customs = self.store.list_components()
        custom_desc = ("; ".join(
            f"{c['name']} ({c['description']}, wraps {c['prototype'] or 'nothing'})"
            for c in customs) or "(none yet)")
        return SYSTEM.format(
            building=self.building,
            fn_catalog=viewspec.functions_markdown(),
            grammar=viewspec.grammar_markdown(self.building),
            component_catalog=viewspec.components_markdown(),
            custom_components=custom_desc,
            context=self.context_fn())

    def run(self, message: str, history=None, current_view: str | None = None) -> dict:
        """One user turn -> final answer + tool trace (+ published view names).
        current_view: name of the view open on the user's screen, if any — its
        spec is injected so "add X to this" edits in place."""
        lines = [self._system()]
        if current_view:
            spec = self.store.get_view(current_view)
            if spec:
                lines.append(
                    f"\n## Currently open on the user's screen: view '{current_view}'\n"
                    f"{json.dumps(spec)}\n"
                    f"When the user says 'this view/dashboard/app' or asks for changes "
                    f"without naming a view, they mean this one — publish_view the full "
                    f"modified spec with name '{current_view}'.")
        lines.append("\n## Conversation")
        for t in (history or [])[-6:]:
            who = "User" if t.get("role") == "user" else "Assistant"
            lines.append(f"{who}: {t.get('content', '')}")
        lines.append(f"User: {message}")
        trace: list = [{"user": message}]

        answer = None
        for _ in range(MAX_STEPS):
            lines.append("\nRespond with the next JSON object (tool call or answer).")
            content = self._llm("\n".join(lines))
            lines.pop()
            try:
                obj = _extract_json(content)
            except ValueError as e:
                lines.append(f"Assistant: {content[:800]}")
                lines.append(f"Protocol error: {e}. Respond with ONE JSON object only.")
                continue
            if "answer" in obj:
                answer = str(obj["answer"])
                break
            name, args = obj.get("tool", ""), obj.get("args") or {}
            lines.append("Assistant: " + json.dumps({"tool": name, "args": args}))
            try:
                result = self._run_tool(name, args, trace)
            except (ValueError, TypeError) as e:
                result = {"error": str(e)}
                trace.append({"tool": name, "args": args, "ok": False, "error": str(e)})
            lines.append(f"Tool result ({name}): {_clip(result)}")
        if answer is None:
            answer = "I couldn't finish that within my step budget — try narrowing the request."

        published = [t["name"] for t in trace if t.get("tool") == "publish_view" and t.get("ok")]
        tools = [t["tool"] for t in trace if "tool" in t]
        return {"answer": answer, "tools": tools,
                "published": published[-1] if published else None, "trace": trace}

    # ── The app-dev entry point: same agent, seeded directive ───────

    def build_view(self, request: str) -> dict:
        """/api/appdev contract: NL request -> {name, spec, attempts}."""
        directive = (f"Build and publish a dashboard view for this request, then "
                     f"answer with its URL: {request}")
        out = self.run(directive)
        publishes = [t for t in out["trace"] if t.get("tool") == "publish_view"]
        ok = [t for t in publishes if t["ok"]]
        if not ok:
            err = ValueError("agent did not publish a valid view")
            err.validation_errors = (publishes[-1].get("errors", [])
                                     if publishes else [out["answer"][:300]])
            raise err
        last = ok[-1]
        return {"name": last["name"], "spec": last["spec"],
                "attempts": len(publishes), "answer": out["answer"]}
