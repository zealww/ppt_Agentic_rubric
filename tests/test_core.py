import json
import tempfile
import unittest
from pathlib import Path

from pujiang_ppt_eval.domain import Criterion, Rubric, RunConfig, Subcriterion
from pujiang_ppt_eval.evaluator import PresentationEvaluator
from pujiang_ppt_eval.parsing import clean_extracted_text, parse_first_json_object, validate_score_response
from pujiang_ppt_eval.prompts import single_slide_prompt
from pujiang_ppt_eval.web import _build_command
from pujiang_ppt_eval.rubric import load_rubric, score_criterion, weighted_total


ROOT = Path(__file__).resolve().parents[1]


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rubric = load_rubric(ROOT / "pujiang_ppt_eval" / "rubrics" / "default.json")

    def test_default_compatibility_weights(self):
        self.assertEqual({x.name: x.weight for x in self.rubric.criteria},
                         {"Content": .3, "Visual_Design": .3, "Layout": .2, "Complexity": .2})
        layout = next(x for x in self.rubric.criteria if x.name == "Layout")
        self.assertEqual({x.name: x.weight for x in layout.subcriteria},
                         {"Spatial_Balance": .3, "Element_Alignment": .3, "No_Overlapping": .4})

    def test_scores_match_legacy_formula(self):
        response = {"Content": {"sub_scores": {
            "Accuracy_and_Completeness": 8, "Logical_Flow": 9, "Cognitive_Rhythm": 7}}}
        content = next(x for x in self.rubric.criteria if x.name == "Content")
        score, _ = score_criterion(content, response)
        self.assertEqual(score, 8.0)
        totals = {"Content": 8, "Visual_Design": 7, "Layout": 6, "Complexity": 5}
        self.assertEqual(weighted_total(self.rubric, totals), 67.0)

    def test_parser_accepts_trailing_output(self):
        self.assertEqual(parse_first_json_object('```json\n{"a": 1}\n``` extra {"b":2}'), {"a": 1})

    def test_base64_cleanup(self):
        dirty = "hello ![image](data:image/png;base64,QUJDRA==) world"
        clean = clean_extracted_text(dirty)
        self.assertNotIn("base64", clean)
        self.assertIn("hello", clean)

    def test_new_rubric_requires_no_code_change(self):
        data = {
            "name": "custom", "version": 1,
            "criteria": [{"name": "Readability", "input_mode": "slide_images", "weight": 1,
                          "subcriteria": [{"name": "Legibility", "weight": 1,
                                           "description": "Readable text"}]}]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rubric.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            rubric = load_rubric(path)
        score, _ = score_criterion(rubric.criteria[0],
                                   {"Readability": {"sub_scores": {"Legibility": 9}}})
        self.assertEqual(score, 9)

    def test_single_slide_mode_and_explanations(self):
        rubric = load_rubric(ROOT / "pujiang_ppt_eval" / "rubrics" / "with_single_slide.json")
        criteria = rubric.by_mode("single_slide")
        self.assertEqual([item.name for item in criteria], ["Single_Slide_Quality"])
        prompt = single_slide_prompt("demo", 2, 5, criteria)
        self.assertIn("slide 2 of 5", prompt)
        self.assertIn("sub_reasons", prompt)
        valid = {"Single_Slide_Quality": {
            "sub_scores": {"Content_Clarity": 8, "Visual_Effectiveness": 7, "Layout_Execution": 9},
            "sub_reasons": {"Content_Clarity": "clear message", "Visual_Effectiveness": "good hierarchy",
                            "Layout_Execution": "aligned and unclipped"},
            "reason": "solid slide"}}
        self.assertEqual(validate_score_response(valid, criteria), [])

    def test_missing_score_explanation_is_rejected(self):
        rubric = load_rubric(ROOT / "pujiang_ppt_eval" / "rubrics" / "with_single_slide.json")
        criterion = rubric.by_mode("single_slide")
        invalid = {"Single_Slide_Quality": {"sub_scores": {
            "Content_Clarity": 8, "Visual_Effectiveness": 7, "Layout_Execution": 9}}}
        self.assertTrue(any("sub_reasons" in error for error in validate_score_response(invalid, criterion)))

    def test_single_slide_evaluator_aggregates_and_preserves_reasons(self):
        criterion = Criterion("Page", "single_slide", 1.0, "page quality", (
            Subcriterion("Clarity", 1.0, "clarity"),))
        rubric = Rubric("test", 1, 0, 10, True, (criterion,))

        class FakePreprocessor:
            def render(self, ppt, deck_dir, force):
                paths = [deck_dir / "slide_images" / "slide_0001.png",
                         deck_dir / "slide_images" / "slide_0002.png"]
                for path in paths:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()
                return paths

        class FakeModel:
            def scored_json(self, prompt, images, criteria, response_dir, label, retries):
                score = 8 if label.endswith("0001") else 6
                return {"Page": {"sub_scores": {"Clarity": score},
                                 "sub_reasons": {"Clarity": f"visible evidence for {score}"},
                                 "reason": "page reason"}}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = RunConfig(root, root / "out", "results.json", "fake", root / "r.json",
                               None, None, None, 1, 150, 8, 4096, 0, 0, False, False, False)
            evaluator = PresentationEvaluator(config, rubric, FakeModel())
            evaluator.preprocessor = FakePreprocessor()
            result = evaluator.evaluate(root / "demo.pptx", "demo")
        self.assertEqual(result["scores"]["Page"], 7.0)
        self.assertEqual(result["weighted_total"], 70.0)
        self.assertEqual(len(result["per_slide_scores"]), 2)
        self.assertEqual(result["per_slide_scores"][0]["score_explanations"]["Page"]["Clarity"],
                         "visible evidence for 8")

    def test_web_builds_same_cli_command(self):
        command = _build_command(
            source=Path("/tmp/ppts"), output=Path("/tmp/results"), model="vision-model",
            rubric=Path("/tmp/rubric.json"), result_file="scores.json", topic_map="",
            workers=2, dpi=150, max_grids=8, max_tokens=4096, api_retries=3,
            format_retries=2, resume=True, force_render=False, force_extract=True,
            base_url="https://gateway.example/v1")
        self.assertIn("pujiang_ppt_eval", command)
        self.assertIn("--resume", command)
        self.assertIn("--force-extract", command)
        self.assertIn("https://gateway.example/v1", command)


if __name__ == "__main__":
    unittest.main()
