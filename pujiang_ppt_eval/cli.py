from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from .domain import RunConfig
from .evaluator import PresentationEvaluator
from .model import OpenAICompatibleModel
from .preprocess import discover_presentations
from .reporting import ResultStore
from .rubric import default_rubric_path, load_rubric
from .topics import load_topic_map, resolve_topic


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maintainable deck-level and single-slide VLM PPT evaluator")
    parser.add_argument("--source", required=True, type=Path, help="Flat directory of .ppt/.pptx files")
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--result-file", default="results.json")
    parser.add_argument("--model", required=True)
    parser.add_argument("--rubric", type=Path, default=default_rubric_path(),
                        help="Rubric JSON; defaults to the existing my_ppt_eval four-criterion rubric")
    parser.add_argument("--topic-map", type=Path, default=None,
                        help="Optional JSON mapping PPT filename stem to actual topic")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--max-grids", type=int, default=8, help="Four slides per grid")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--api-retries", type=int, default=3)
    parser.add_argument("--format-retries", type=int, default=2)
    parser.add_argument("--force-render", action="store_true")
    parser.add_argument("--force-extract", action="store_true")
    parser.add_argument("--resume", action="store_true")
    return parser


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    parser = build_parser()
    args = parser.parse_args()
    if not args.source.is_dir():
        parser.error(f"Source is not a directory: {args.source}")
    if args.workers < 1 or args.max_grids < 1 or args.api_retries < 0 or args.format_retries < 0:
        parser.error("workers/max-grids must be positive; retry counts must be non-negative")
    ppts = discover_presentations(args.source)
    if not ppts:
        parser.error(f"No .ppt/.pptx files directly under {args.source}")

    config = RunConfig(
        source=args.source, output=args.output, result_file=args.result_file, model=args.model,
        rubric_path=args.rubric, topic_map=args.topic_map, api_key=args.api_key,
        base_url=args.base_url, workers=args.workers, dpi=args.dpi, max_grids=args.max_grids,
        max_tokens=args.max_tokens, api_retries=args.api_retries,
        format_retries=args.format_retries, force_render=args.force_render,
        force_extract=args.force_extract, resume=args.resume)
    rubric = load_rubric(config.rubric_path)
    topic_map = load_topic_map(config.topic_map)
    store = ResultStore(config.output / config.result_file)
    results = store.load_successes() if config.resume else []
    done = {x.get("ppt_id") for x in results}
    pending = [ppt for ppt in ppts if ppt.stem not in done]
    if config.resume:
        print(f"Resume: keeping {len(results)} completed, evaluating {len(pending)} pending")

    model = OpenAICompatibleModel(config.model, config.api_key, config.base_url,
                                  config.max_tokens, config.api_retries)
    evaluator = PresentationEvaluator(config, rubric, model)
    started_at, clock = datetime.now().isoformat(), time.perf_counter()
    failures = []
    for index, ppt in enumerate(pending, 1):
        print(f"\n({index}/{len(pending)}) Evaluating {ppt.name}")
        try:
            results.append(evaluator.evaluate(ppt, resolve_topic(ppt, topic_map)))
        except Exception as exc:
            print(f"FAILED: {exc}")
            failures.append({"ppt_path": str(ppt.resolve()), "error": str(exc)})
        # Checkpoint after every presentation so interruption does not lose completed work.
        store.save(started_at=started_at, duration_seconds=time.perf_counter() - clock,
                   model=config.model, source=config.source, rubric=rubric,
                   results=results, failures=failures)
    print(f"\nDone: {len(results)} total succeeded, {len(failures)} failed this run")
    print(f"Results: {store.path.resolve()}")


if __name__ == "__main__":
    main()
