from __future__ import annotations

import time
from pathlib import Path

from .domain import Rubric, RunConfig
from .extraction import ContentExtractor
from .model import OpenAICompatibleModel
from .preprocess import SlidePreprocessor
from .prompts import content_prompt, single_slide_prompt, visual_prompt
from .rubric import score_criterion, weighted_total


class PresentationEvaluator:
    """Orchestrates components; contains no provider-, rubric-, or rendering-specific logic."""

    def __init__(self, config: RunConfig, rubric: Rubric, model: OpenAICompatibleModel):
        self.config = config
        self.rubric = rubric
        self.model = model
        self.preprocessor = SlidePreprocessor(config.dpi)
        self.extractor = ContentExtractor(model, config.workers)

    def evaluate(self, ppt: Path, topic: str) -> dict:
        started = time.perf_counter()
        deck_dir = self.config.output / ppt.stem
        deck_dir.mkdir(parents=True, exist_ok=True)
        images = self.preprocessor.render(ppt, deck_dir, self.config.force_render)
        print(f"[{ppt.name}] rendered/cached {len(images)} slides")
        response_dir = deck_dir / "model_responses"
        combined = {}
        per_slide_scores = []
        single_aggregates = {}

        text_criteria = self.rubric.by_mode("extracted_text")
        if text_criteria:
            contents = self.extractor.extract(images, deck_dir, self.config.force_extract)
            combined.update(self.model.scored_json(
                content_prompt(topic, len(images), contents, text_criteria), None, text_criteria,
                response_dir, "content", self.config.format_retries))

        image_criteria = self.rubric.by_mode("slide_images")
        if image_criteria:
            grids = self.preprocessor.grids(images, deck_dir, self.config.force_render)
            combined.update(self.model.scored_json(
                visual_prompt(topic, len(images), image_criteria), grids[:self.config.max_grids],
                image_criteria, response_dir, "visual", self.config.format_retries))

        # A single_slide criterion is evaluated independently for every original slide image.
        # Its deck-level score is the arithmetic mean of the per-slide sub-scores.
        single_criteria = self.rubric.by_mode("single_slide")
        if single_criteria:
            slide_responses = []
            for slide_number, image in enumerate(images, 1):
                print(f"  single-slide evaluation {slide_number}/{len(images)}")
                response = self.model.scored_json(
                    single_slide_prompt(topic, slide_number, len(images), single_criteria),
                    [image], single_criteria, response_dir,
                    f"single_slide_{slide_number:04d}", self.config.format_retries)
                slide_responses.append(response)
                item_scores, item_sub_scores, item_explanations, item_reasons = {}, {}, {}, {}
                for criterion in single_criteria:
                    item_scores[criterion.name], item_sub_scores[criterion.name] = score_criterion(
                        criterion, response, self.rubric.minimum, self.rubric.maximum,
                        self.rubric.integer_scores)
                    item_explanations[criterion.name] = response[criterion.name]["sub_reasons"]
                    item_reasons[criterion.name] = response[criterion.name].get("reason", "")
                per_slide_scores.append({
                    "slide_number": slide_number, "image_path": str(image.resolve()),
                    "scores": item_scores, "sub_scores": item_sub_scores,
                    "score_explanations": item_explanations, "reasons": item_reasons,
                })

            for criterion in single_criteria:
                averaged_subs = {
                    sub.name: round(sum(float(response[criterion.name]["sub_scores"][sub.name])
                                        for response in slide_responses) / len(slide_responses), 3)
                    for sub in criterion.subcriteria
                }
                combined[criterion.name] = {
                    "sub_scores": averaged_subs,
                    "sub_reasons": {
                        sub.name: f"Deck aggregate: mean of {len(slide_responses)} per-slide scores; "
                                  "see per_slide_scores for slide-specific explanations."
                        for sub in criterion.subcriteria
                    },
                    "reason": f"Arithmetic aggregation of independent evaluations for {len(slide_responses)} slides."
                }
                single_aggregates[criterion.name] = {
                    "score": round(sum(item["scores"][criterion.name] for item in per_slide_scores)
                                   / len(per_slide_scores), 3),
                    "sub_scores": averaged_subs,
                }

        scores, sub_scores = {}, {}
        for criterion in self.rubric.criteria:
            if criterion.name in single_aggregates:
                scores[criterion.name] = single_aggregates[criterion.name]["score"]
                sub_scores[criterion.name] = single_aggregates[criterion.name]["sub_scores"]
            else:
                scores[criterion.name], sub_scores[criterion.name] = score_criterion(
                    criterion, combined, self.rubric.minimum, self.rubric.maximum,
                    self.rubric.integer_scores)
        score_explanations = {
            criterion.name: combined.get(criterion.name, {}).get("sub_reasons", {})
            for criterion in self.rubric.criteria
        }
        total_weight = sum(criterion.weight for criterion in self.rubric.criteria)
        score_calculation = {
            "criteria": {
                criterion.name: {
                    "formula": " + ".join(
                        f"{sub.name}×{sub.weight / sum(x.weight for x in criterion.subcriteria):.6f}"
                        for sub in criterion.subcriteria),
                    "aggregation": ("arithmetic mean across per-slide criterion scores"
                                    if criterion.input_mode == "single_slide"
                                    else "weighted sum of integer model sub-scores"),
                }
                for criterion in self.rubric.criteria
            },
            "weighted_total_formula": " + ".join(
                f"{criterion.name}×{criterion.weight / total_weight:.6f}"
                for criterion in self.rubric.criteria) + ", normalized to 0-100",
        }
        return {
            "ppt_id": ppt.stem, "ppt_path": str(ppt.resolve()), "topic": topic,
            "num_slides": len(images), "scores": scores, "sub_scores": sub_scores,
            "weighted_total": weighted_total(self.rubric, scores),
            "score_explanations": score_explanations,
            "score_calculation": score_calculation,
            "reasons": {c.name: combined.get(c.name, {}).get("reason", "") for c in self.rubric.criteria},
            "overall_feedback": combined.get("Overall_Feedback", ""),
            "strengths": combined.get("Top_Strengths", []),
            "improvements": combined.get("Areas_for_Improvement", []),
            "content_limitation": "No source document supplied; factual accuracy is not source-grounded.",
            "per_slide_scores": per_slide_scores,
            "evaluation_duration_seconds": round(time.perf_counter() - started, 3),
        }
