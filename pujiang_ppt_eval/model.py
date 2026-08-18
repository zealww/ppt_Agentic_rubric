from __future__ import annotations

import base64
import os
import time
from pathlib import Path

from openai import OpenAI

from .domain import Criterion
from .parsing import parse_first_json_object, validate_score_response


class OpenAICompatibleModel:
    """The only provider-specific component; replace this class to add another backend."""

    def __init__(self, model: str, api_key: str | None, base_url: str | None,
                 max_tokens: int = 4096, api_retries: int = 3):
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("Missing OPENAI_API_KEY (environment or .env)")
        self.client = OpenAI(api_key=key, base_url=base_url or os.getenv("OPENAI_BASE_URL") or None,
                             timeout=300)
        self.model = model
        self.max_tokens = max_tokens
        self.api_retries = api_retries

    def complete(self, prompt: str, images: list[Path] | None = None) -> str:
        content: object = prompt
        if images:
            content = [{"type": "text", "text": prompt}]
            for path in images:
                mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                content.append({"type": "image_url", "image_url": {
                    "url": f"data:{mime};base64,{encoded}", "detail": "high"}})
        last_error = None
        for attempt in range(self.api_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model, messages=[{"role": "user", "content": content}],
                    max_tokens=self.max_tokens)
                return response.choices[0].message.content or ""
            except Exception as exc:
                last_error = exc
                if attempt < self.api_retries:
                    time.sleep(min(2 ** attempt, 20))
        raise RuntimeError(f"Model call failed after retries: {last_error}")

    def scored_json(self, prompt: str, images: list[Path] | None,
                    criteria: tuple[Criterion, ...], response_dir: Path,
                    label: str, format_retries: int) -> dict:
        response_dir.mkdir(parents=True, exist_ok=True)
        last_error = "unknown format error"
        for attempt in range(1, format_retries + 2):
            raw = self.complete(prompt, images)
            (response_dir / f"{label}_attempt_{attempt}.txt").write_text(raw, encoding="utf-8")
            try:
                parsed = parse_first_json_object(raw)
                errors = validate_score_response(parsed, criteria)
                if errors:
                    raise ValueError("; ".join(errors))
                return parsed
            except ValueError as exc:
                last_error = str(exc)
                if attempt <= format_retries:
                    print(f"  {label} response invalid ({last_error}); retrying {attempt}/{format_retries}")
                    time.sleep(min(2 ** (attempt - 1), 10))
        raise ValueError(f"{label} returned invalid JSON after {format_retries + 1} attempts: "
                         f"{last_error}. Raw responses: {response_dir}")

