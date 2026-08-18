from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .domain import Rubric


class ResultStore:
    def __init__(self, path: Path):
        self.path = path

    def load_successes(self) -> list[dict]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return list(payload.get("results", []))

    def save(self, *, started_at: str, duration_seconds: float, model: str,
             source: Path, rubric: Rubric, results: list[dict], failures: list[dict]) -> None:
        count = len(results)
        summary = {
            "count": count,
            "failed": len(failures),
            "mean_weighted_total": round(sum(x["weighted_total"] for x in results) / count, 3) if count else None,
            "mean_by_criterion": {
                criterion.name: round(sum(x["scores"][criterion.name] for x in results) / count, 3)
                for criterion in rubric.criteria
            } if count else {},
        }
        payload = {
            "metadata": {
                "started_at": started_at, "completed_at": datetime.now().isoformat(),
                "duration_seconds": round(duration_seconds, 3), "model": model,
                "source": str(source.resolve()), "rubric": rubric.name,
                "rubric_version": rubric.version,
            },
            "results": results, "failures": failures, "summary": summary,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

