from __future__ import annotations

import json

from .domain import Criterion

EXTRACTION_PROMPT = """Extract this slide for a content-quality audit. Return concise Markdown only.
Include: (1) exact title/subtitle and every textual claim/callout; (2) all visible numbers and
chart/table data; (3) interpretations only for information-bearing images/icons. Ignore decoration.
Do not generate, embed, or return an image, data URI, Base64, JSON, or a Markdown image link."""


def _criteria_text(criteria: tuple[Criterion, ...]) -> str:
    lines = []
    for criterion in criteria:
        lines.append(f"### {criterion.name}\n{criterion.description}")
        for sub in criterion.subcriteria:
            lines.append(f"- {sub.name}: {sub.description}")
    return "\n".join(lines)


def _response_schema(criteria: tuple[Criterion, ...]) -> str:
    schema = {}
    for criterion in criteria:
        schema[criterion.name] = {
            "sub_scores": {sub.name: 0 for sub in criterion.subcriteria},
            "sub_reasons": {sub.name: "why this exact score was assigned" for sub in criterion.subcriteria},
            "reason": "detailed reasoning",
        }
    schema.update({"Overall_Feedback": "brief summary", "Top_Strengths": ["strength"],
                   "Areas_for_Improvement": ["improvement"]})
    return json.dumps(schema, ensure_ascii=False, indent=2)


def content_prompt(topic: str, num_slides: int, contents: str,
                   criteria: tuple[Criterion, ...]) -> str:
    return f"""You are evaluating the content of a complete presentation.
Topic: {topic}. Slide count: {num_slides}.

Important limitation: no source/reference document is available. For factual accuracy, judge
internal plausibility, contradictions, obvious errors, topic coverage and missing essential context
using the slides and your knowledge. Do not claim source-grounded verification.

Evaluate these criteria. Score every subcriterion with an EXACT INTEGER 0-10 and provide a
specific explanation for every individual subcriterion score:
{_criteria_text(criteria)}

Extracted contents:
{contents}

Return JSON only, with exactly this score structure:
{_response_schema(criteria)}"""


def visual_prompt(topic: str, num_slides: int,
                  criteria: tuple[Criterion, ...]) -> str:
    return f"""You are an expert presentation designer. Evaluate the attached slide grids for
the presentation titled \"{topic}\" ({num_slides} slides). Judge only what is visible. Score every
subcriterion with an EXACT INTEGER 0-10 and explain every individual score. Do not reward clutter
merely for being complex.

Evaluate these criteria:
{_criteria_text(criteria)}

Return JSON only, with exactly this score structure:
{_response_schema(criteria)}"""


def single_slide_prompt(topic: str, slide_number: int, num_slides: int,
                        criteria: tuple[Criterion, ...]) -> str:
    return f"""You are evaluating ONE slide from a presentation.
Presentation topic: \"{topic}\". This is slide {slide_number} of {num_slides}.
Judge only this attached slide. Do not infer the quality of unseen slides. Score every subcriterion
with an EXACT INTEGER 0-10 and provide a concrete explanation for every individual score. Cite
visible evidence such as text density, hierarchy, alignment, imagery, clipping, or information shown.

Evaluate these criteria:
{_criteria_text(criteria)}

Return JSON only, with exactly this score structure:
{_response_schema(criteria)}"""
