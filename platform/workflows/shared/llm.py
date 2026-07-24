"""LLM integration via LiteLLM."""

import json
import litellm
from .config import LLM_MODEL, LLM_API_BASE, LLM_API_KEY


# ── Equipment Discovery ─────────────────────────────────────────────

DISCOVER_EQUIPMENT_SYSTEM_PROMPT = """You are an expert at parsing building automation system (BAS) naming conventions.

Given a list of raw BACnet/IoT tags and a list of known device types, group the tags by equipment and identify each equipment's type.

BACnet object names typically follow a pattern: {building}_{equipment}_{point}
For example: "NPCCR_PAU_01_103_1_SaT" means building=NPCCR, equipment=PAU_01_103_1, point=SaT

Rules:
- Extract the equipment name WITHOUT the building prefix
- Multiple raw tags belong to the same equipment if they share the same equipment portion of the name
- Match each equipment to one of the available device types

Domain heuristics (these are the mistakes to avoid — learned from real plants):
- PLANT / HEADER / SYSTEM points are NOT a piece of equipment. A prefix like
  "CHPL", "*_Plant", "*_header", "*_system", "system_efficiency", "HeatLoad",
  or plant-level totals describes the whole plant, not one device — do NOT
  emit it as equipment. Leave such tags ungrouped.
- Watch for INFIXES inside point names. A segment that appears in the MIDDLE of
  many point names (e.g. "hli" in "CH_1_hli_raw_temp_chws") is part of the
  point naming, NOT a separate device. Do not create equipment like "CH_1_hli"
  or "CH_HLI" — those points belong to "CH_1".
- DEDUPE name variants of the same physical unit. "CHWP_1" and "CHWPUMP_1" are
  the same chilled-water pump; "CWP_2" and "CWPUMP_2" the same condenser pump.
  Emit ONE equipment per physical unit, using the shortest canonical name.
- Do NOT group by device/gateway id (e.g. "7777", "Rivervale_Chiller_7777",
  "ModbusNetwork_*"). Those are network addresses, not equipment.
- Vendor/driver point-groups (e.g. "SC-equip-App", raw controller internals
  with no clear equipment name) are NOT physical equipment — leave ungrouped.
- Prefer NOT emitting equipment over inventing a dubious one. Ungrouped tags
  are fine; wrong equipment pollutes the model.

Respond in JSON format only."""

DISCOVER_EQUIPMENT_USER_TEMPLATE = """## Available Device Types:
{device_types}

## Raw Tags to group:
{rawtags}
{feedback_section}
Group all raw tags by equipment. Return a JSON array of equipment objects:
[
  {{
    "equipment_name": "PAU_01_103_1",
    "equipment_type": "PAU",
    "rawtag_ids": ["bldg:agent:161:analog-input:1", "bldg:agent:161:analog-input:3", ...]
  }},
  ...
]"""

# ── File Understanding (extraction) ─────────────────────────────────

SUMMARIZE_FILE_PROMPT = """You are cataloging files from a building-management project folder.
Given a filename and a content sample, describe the file in ONE sentence:
what it is, what it contains, and roughly how much (e.g. "Niagara BACnet
point export: 929 points across 4 devices for Rivervale Plaza").
Respond with the sentence only — no JSON, no markdown."""

TABLE_MAPPING_SYSTEM_PROMPT = """You are an expert at reading BMS/BACnet point-list exports (Niagara, Desigo, Metasys, generic CSV).

Given the header and sample rows of a spreadsheet, produce a column mapping spec identifying which columns carry which roles. Respond in JSON only:

{
  "sheet": "<sheet name to extract>",
  "columns": {
    "device":    "<column with the source device/controller name, or null>",
    "object_id": "<column with the BACnet object identifier like analogInput:0 or AI,1>",
    "name":      "<column with the point name>",
    "facets":    "<column with Niagara facets (contains units=u:...), or null>",
    "unit":      "<column with a plain engineering unit, or null>",
    "value":     "<column with a current/sample value, or null>",
    "write":     "<column indicating writability, or null>",
    "path":      "<column with a station path, or null>"
  },
  "device_instance_regex": "<regex whose group 1 captures the numeric BACnet device instance from the device name, or null if not derivable>"
}

Rules:
- Column values must be EXACT header strings from the sample, or null.
- object_id and name are required — pick the best candidates.
- Prefer a facets column over a plain unit column when both exist."""

TABLE_MAPPING_USER_TEMPLATE = """## File: {filename}

## Content sample (CSV):
{sample}

Produce the column mapping spec JSON."""


def summarize_file(filename: str, sample: str) -> str:
    """One-line description of a file from its content sample."""
    content = _call_llm(SUMMARIZE_FILE_PROMPT,
                        f"## File: {filename}\n\n{sample}", max_tokens=200)
    return content.strip().strip('"')


def propose_table_mapping(filename: str, sample: str) -> dict:
    """Ask the LLM for a column mapping spec for a tabular point export."""
    content = _call_llm(
        TABLE_MAPPING_SYSTEM_PROMPT,
        TABLE_MAPPING_USER_TEMPLATE.format(filename=filename, sample=sample),
    )
    return json.loads(content)


# ── Point Classification ────────────────────────────────────────────

CLASSIFY_SYSTEM_PROMPT = """You are an expert at classifying building automation system (BAS) data points.

Given a list of raw BACnet/IoT tags belonging to a specific equipment and a set of target property types, match each property type to the most likely raw tag(s).

For each property type, return:
- The ID of the best matching raw tag (or null if no good match)
- A confidence score from 0.0 to 1.0
- A brief reason for the match

Consider:
- Object names often contain abbreviations (SAT=Supply Air Temp, RAT=Return Air Temp, OaT=Outdoor Air Temp, ChwST=Chilled Water Supply Temp, etc.)
- Object types (analog-input, analog-output, binary-input, etc.)
- Value ranges and units when available

Match the MEASURED value, not a related control point:
- Prefer the raw sensor over a SETPOINT ("*_sp", "*_setpoint", "write_*") — a
  setpoint is a target, not the measurement. Only pick a setpoint if the target
  type is explicitly a setpoint.
- Prefer this equipment's OWN point over a plant/header aggregate ("*_header",
  "CHPL_*") — the header is a plant total, not this unit's reading.
- Distinguish chilled water (chw/chws/chwr) from condenser water (cw/cws/cwr):
  chws/chwr are the evaporator side, cws/cwr the condenser side.
- If the only candidate is a setpoint or header when a real measurement is
  wanted, return null with a low confidence rather than forcing a bad match.

Respond in JSON format only."""

CLASSIFY_USER_TEMPLATE = """## Equipment: {equipment_name} ({equipment_type})

## Target Property Types:
{property_types}

## Raw Tags belonging to this equipment:
{rawtags}

{feedback_section}

For each target property type, identify the best matching raw tag from this equipment.
Respond with a JSON object where keys are property type names and values are objects with:
- "rawtag_id": string or null
- "confidence": number 0.0-1.0
- "reason": string

Example response:
{{
  "supply_air_temp": {{"rawtag_id": "bldg:agent:161:analog-input:3", "confidence": 0.95, "reason": "Object name SAT matches supply air temperature"}},
  "return_air_temp": {{"rawtag_id": null, "confidence": 0.0, "reason": "No matching tag found"}}
}}"""


def _call_llm(system_prompt: str, user_content: str, max_tokens: int = 16384) -> str:
    """Call LLM and return the raw content string, stripping markdown fences."""
    response = litellm.completion(
        model=LLM_MODEL,
        api_base=LLM_API_BASE if LLM_API_BASE else None,
        api_key=LLM_API_KEY if LLM_API_KEY else None,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
    )
    content = response.choices[0].message.content
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()
    return content


def discover_equipment_from_rawtags(
    rawtags: list[dict],
    device_types: list[dict],
    feedback: str | None = None,
) -> list[dict]:
    """
    Group raw tags by equipment using LLM.

    Args:
        feedback: human guidance from a rejected previous round, so the LLM
                  re-groups rather than repeating the same mistake.

    Returns:
        List of {equipment_name, equipment_type, rawtag_ids}
    """
    if not rawtags:
        return []

    device_types_str = "\n".join(
        f"- {dt.get('name', '')}: {dt.get('label', '')}" for dt in device_types
    )

    # Send condensed rawtag info — only id, object_name, type to stay within
    # token limits. object_name is a flat property (it used to be buried in a
    # raw_data blob); without it the LLM sees nameless tags and falls back to
    # grouping by device id, which is useless.
    condensed = []
    for rt in rawtags:
        condensed.append({
            "id": rt.get("id", ""),
            "name": rt.get("object_name", ""),
            "type": rt.get("object_type", ""),
        })
    rawtags_str = json.dumps(condensed, default=str)

    feedback_section = ""
    if feedback:
        feedback_section = (f"\n## Human Feedback (from the previous attempt):\n{feedback}\n"
                            "\nRe-group accordingly — correct what the feedback says is wrong.\n")

    user_content = DISCOVER_EQUIPMENT_USER_TEMPLATE.format(
        device_types=device_types_str,
        rawtags=rawtags_str,
        feedback_section=feedback_section,
    )

    print(f"[llm] discover_equipment: sending {len(rawtags)} rawtags, {len(device_types)} device types", flush=True)
    content = _call_llm(DISCOVER_EQUIPMENT_SYSTEM_PROMPT, user_content)
    print(f"[llm] discover_equipment response length: {len(content)}", flush=True)
    print(f"[llm] discover_equipment response preview: {content[:500]}", flush=True)

    try:
        result = json.loads(content)
        if isinstance(result, list):
            print(f"[llm] discover_equipment: parsed {len(result)} equipment groups", flush=True)
            return result
        print(f"[llm] discover_equipment: unexpected result type: {type(result)}", flush=True)
        return []
    except json.JSONDecodeError as e:
        print(f"[llm] discover_equipment: JSON parse error: {e}", flush=True)
        print(f"[llm] discover_equipment: raw content: {content[:1000]}", flush=True)
        return []


def classify_rawtags(
    rawtags: list[dict],
    tbox_types: list[str],
    property_defs: list[dict],
    equipment_name: str = "",
    equipment_type: str = "",
    feedback: str | None = None
) -> dict:
    """
    Classify raw tags against TBox property types using LLM.
    Tags should be pre-filtered to a specific equipment.

    Args:
        rawtags: List of RawTag nodes belonging to the equipment
        tbox_types: List of property type names to classify
        property_defs: PropertyDef nodes with metadata
        equipment_name: Name of the equipment these tags belong to
        equipment_type: Device type of the equipment
        feedback: Optional human feedback for rework

    Returns:
        Dict mapping tbox_type -> {candidates: [{rawtag_id, confidence, reason}]}
    """
    if not rawtags or not tbox_types:
        return {t: {"candidates": []} for t in tbox_types}

    # Format property types with their definitions
    prop_info = []
    for pdef in property_defs:
        name = pdef.get('name', '')
        if name in tbox_types:
            prop_info.append(f"- {name}: {pdef.get('label', '')} - {pdef.get('description', '')}")
    if not prop_info:
        for t in tbox_types:
            prop_info.append(f"- {t}")

    property_types_str = "\n".join(prop_info)
    rawtags_str = json.dumps(rawtags, indent=2, default=str)

    feedback_section = ""
    if feedback:
        feedback_section = f"""## Human Feedback (from previous attempt):
{feedback}

Please reconsider your classifications based on this feedback."""

    user_content = CLASSIFY_USER_TEMPLATE.format(
        equipment_name=equipment_name,
        equipment_type=equipment_type,
        property_types=property_types_str,
        rawtags=rawtags_str,
        feedback_section=feedback_section
    )

    content = _call_llm(CLASSIFY_SYSTEM_PROMPT, user_content)

    try:
        result_json = json.loads(content)
    except json.JSONDecodeError:
        return {t: {"candidates": []} for t in tbox_types}

    results: dict = {}
    for tbox_type in tbox_types:
        match = result_json.get(tbox_type, {})
        candidates = []
        if match.get("rawtag_id"):
            candidates.append({
                "rawtag_id": match["rawtag_id"],
                "confidence": match.get("confidence", 0.0),
                "reason": match.get("reason", ""),
            })
        results[tbox_type] = {"candidates": candidates}

    return results
