"""LLM integration via LiteLLM."""

import json
import litellm
from .config import LLM_MODEL, LLM_API_BASE, LLM_API_KEY


CLASSIFY_SYSTEM_PROMPT = """You are an expert at classifying building automation system (BAS) data points.

Given a list of raw BACnet/IoT tags and a set of target property types, match each property type to the most likely raw tag(s).

For each property type, return:
- The ID of the best matching raw tag (or null if no good match)
- A confidence score from 0.0 to 1.0
- A brief reason for the match

Consider:
- Object names often contain abbreviations (SAT=Supply Air Temp, RAT=Return Air Temp, etc.)
- Object types (analog-input, analog-output, binary-input, etc.)
- Value ranges and units when available
- The raw_data field may contain additional metadata

Respond in JSON format only."""

CLASSIFY_USER_TEMPLATE = """## Target Property Types:
{property_types}

## Available Raw Tags:
{rawtags}

{feedback_section}

For each target property type, identify the best matching raw tag.
Respond with a JSON object where keys are property type names and values are objects with:
- "rawtag_id": string or null
- "confidence": number 0.0-1.0
- "reason": string

Example response:
{{
  "supply_air_temp": {{"rawtag_id": "bacnet-sim:device-1:analog-input:1", "confidence": 0.95, "reason": "Object name 'SAT' matches supply air temperature"}},
  "return_air_temp": {{"rawtag_id": null, "confidence": 0.0, "reason": "No matching tag found"}}
}}"""


def classify_rawtags(
    rawtags: list[dict],
    tbox_types: list[str],
    property_defs: list[dict],
    feedback: str | None = None
) -> dict:
    """
    Classify raw tags against TBox property types using LLM.

    Args:
        rawtags: List of RawTag nodes from graph
        tbox_types: List of property type names to classify
        property_defs: PropertyDef nodes with metadata (label, description, etc.)
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

    # If we have no property definitions for requested types, still try
    if not prop_info:
        for t in tbox_types:
            prop_info.append(f"- {t}")

    property_types_str = "\n".join(prop_info)

    # Format raw tags
    rawtags_str = json.dumps(rawtags, indent=2, default=str)

    # Add feedback section if reworking
    feedback_section = ""
    if feedback:
        feedback_section = f"""## Human Feedback (from previous attempt):
{feedback}

Please reconsider your classifications based on this feedback."""

    user_content = CLASSIFY_USER_TEMPLATE.format(
        property_types=property_types_str,
        rawtags=rawtags_str,
        feedback_section=feedback_section
    )

    # Call LLM (some models don't support response_format)
    response = litellm.completion(
        model=LLM_MODEL,
        api_base=LLM_API_BASE if LLM_API_BASE else None,
        api_key=LLM_API_KEY if LLM_API_KEY else None,
        messages=[
            {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ]
    )

    # Parse response - handle markdown code blocks
    content = response.choices[0].message.content
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()

    try:
        result_json = json.loads(content)
    except json.JSONDecodeError:
        return {t: {"candidates": []} for t in tbox_types}

    # Convert to simple dict format
    results: dict = {}
    for tbox_type in tbox_types:
        match = result_json.get(tbox_type, {})
        candidates = []
        if match.get("rawtag_id"):
            candidates.append({
                "rawtag_id": match["rawtag_id"],
                "confidence": match.get("confidence", 0.0),
                "reason": match.get("reason", "")
            })
        results[tbox_type] = {"candidates": candidates}

    return results
