from __future__ import annotations

import json
from pathlib import Path

from .domain import Criterion, Rubric, Subcriterion


def default_rubric_path() -> Path:
    return Path(__file__).resolve().parent / "rubrics" / "default.json"


def load_rubric(path: Path) -> Rubric:
    data = json.loads(path.read_text(encoding="utf-8"))
    scale = data.get("score_scale", {})
    criteria = []
    seen = set()
    for raw in data.get("criteria", []):
        name = raw["name"]
        if name in seen:
            raise ValueError(f"Duplicate criterion: {name}")
        seen.add(name)
        mode = raw["input_mode"]
        if mode not in {"extracted_text", "slide_images", "single_slide"}:
            raise ValueError(f"Unsupported input_mode for {name}: {mode}")
        subs = tuple(Subcriterion(str(x["name"]), float(x["weight"]), str(x.get("description", "")))
                     for x in raw.get("subcriteria", []))
        if not subs or sum(x.weight for x in subs) <= 0:
            raise ValueError(f"Criterion {name} needs positively weighted subcriteria")
        criteria.append(Criterion(name, mode, float(raw["weight"]), str(raw.get("description", "")), subs))
    if not criteria or sum(x.weight for x in criteria) <= 0:
        raise ValueError("Rubric needs positively weighted criteria")
    return Rubric(str(data.get("name", path.stem)), int(data.get("version", 1)),
                  float(scale.get("min", 0)), float(scale.get("max", 10)),
                  bool(scale.get("integer", True)), tuple(criteria))


def score_criterion(criterion: Criterion, response: dict, minimum: float = 0,
                    maximum: float = 10, integer: bool = True) -> tuple[float, dict[str, float]]:
    raw = response.get(criterion.name, {}).get("sub_scores", {})
    scores = {}
    for sub in criterion.subcriteria:
        if sub.name not in raw:
            raise ValueError(f"Missing model score: {criterion.name}.{sub.name}")
        value = max(minimum, min(maximum, float(raw[sub.name])))
        scores[sub.name] = int(round(value)) if integer else value
    denominator = sum(x.weight for x in criterion.subcriteria)
    score = sum(scores[x.name] * x.weight for x in criterion.subcriteria) / denominator
    return round(score, 3), scores


def weighted_total(rubric: Rubric, scores: dict[str, float]) -> float:
    denominator = sum(x.weight for x in rubric.criteria)
    normalized = sum(scores[x.name] * x.weight for x in rubric.criteria) / denominator
    return round(normalized / rubric.maximum * 100, 2)
