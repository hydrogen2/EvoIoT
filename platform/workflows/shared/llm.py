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
- Include ALL raw tags, even if you're unsure about the equipment type
- If an object name doesn't clearly indicate equipment (e.g. a standalone sensor), group it as a standalone equipment

Respond in JSON format only."""

DISCOVER_EQUIPMENT_USER_TEMPLATE = """## Available Device Types:
{device_types}

## Raw Tags to group:
{rawtags}

Group all raw tags by equipment. Return a JSON array of equipment objects:
[
  {{
    "equipment_name": "PAU_01_103_1",
    "equipment_type": "PAU",
    "rawtag_ids": ["bldg:agent:161:analog-input:1", "bldg:agent:161:analog-input:3", ...]
  }},
  ...
]"""

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
- The raw_data field may contain additional metadata

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


def _call_llm(system_prompt: str, user_content: str) -> str:
    """Call LLM and return the raw content string, stripping markdown fences."""
    response = litellm.completion(
        model=LLM_MODEL,
        api_base=LLM_API_BASE if LLM_API_BASE else None,
        api_key=LLM_API_KEY if LLM_API_KEY else None,
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
) -> list[dict]:
    """
    Group raw tags by equipment using LLM.

    Returns:
        List of {equipment_name, equipment_type, rawtag_ids}
    """
    if not rawtags:
        return []

    device_types_str = "\n".join(
        f"- {dt.get('name', '')}: {dt.get('label', '')}" for dt in device_types
    )
    rawtags_str = json.dumps(rawtags, indent=2, default=str)

    user_content = DISCOVER_EQUIPMENT_USER_TEMPLATE.format(
        device_types=device_types_str,
        rawtags=rawtags_str,
    )

    content = _call_llm(DISCOVER_EQUIPMENT_SYSTEM_PROMPT, user_content)

    try:
        result = json.loads(content)
        if isinstance(result, list):
            return result
        return []
    except json.JSONDecodeError:
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
