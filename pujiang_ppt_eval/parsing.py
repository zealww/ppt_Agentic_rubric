from __future__ import annotations

import json
import re
from typing import Any

from .domain import Criterion


def parse_first_json_object(text: str) -> dict[str, Any]:
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    raise ValueError("Model response contains no valid JSON object")


def validate_score_response(value: dict[str, Any], criteria: tuple[Criterion, ...]) -> list[str]:
    errors = []
    for criterion in criteria:
        section = value.get(criterion.name)
        if not isinstance(section, dict):
            errors.append(f"missing section {criterion.name}")
            continue
        scores = section.get("sub_scores")
        reasons = section.get("sub_reasons")
        if not isinstance(scores, dict):
            errors.append(f"missing sub_scores {criterion.name}")
            continue
        if not isinstance(reasons, dict):
            errors.append(f"missing sub_reasons {criterion.name}")
            reasons = {}
        for sub in criterion.subcriteria:
            try:
                float(scores[sub.name])
            except (KeyError, TypeError, ValueError):
                errors.append(f"missing/invalid {criterion.name}.{sub.name}")
            explanation = reasons.get(sub.name)
            if not isinstance(explanation, str) or not explanation.strip():
                errors.append(f"missing explanation {criterion.name}.{sub.name}")
    return errors


def clean_extracted_text(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\(data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+\)",
                  "[embedded generated image removed]", text, flags=re.I)
    text = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+",
                  "[embedded generated image removed]", text, flags=re.I)
    text = re.sub(r"^```(?:markdown)?\s*|\s*```$", "", text.strip(), flags=re.I)
    return text.strip()
