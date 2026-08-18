from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

InputMode = Literal["extracted_text", "slide_images", "single_slide"]


@dataclass(frozen=True)
class Subcriterion:
    name: str
    weight: float
    description: str


@dataclass(frozen=True)
class Criterion:
    name: str
    input_mode: InputMode
    weight: float
    description: str
    subcriteria: tuple[Subcriterion, ...]


@dataclass(frozen=True)
class Rubric:
    name: str
    version: int
    minimum: float
    maximum: float
    integer_scores: bool
    criteria: tuple[Criterion, ...]

    def by_mode(self, mode: InputMode) -> tuple[Criterion, ...]:
        return tuple(item for item in self.criteria if item.input_mode == mode)


@dataclass(frozen=True)
class RunConfig:
    source: Path
    output: Path
    result_file: str
    model: str
    rubric_path: Path
    topic_map: Path | None
    api_key: str | None
    base_url: str | None
    workers: int
    dpi: int
    max_grids: int
    max_tokens: int
    api_retries: int
    format_retries: int
    force_render: bool
    force_extract: bool
    resume: bool
