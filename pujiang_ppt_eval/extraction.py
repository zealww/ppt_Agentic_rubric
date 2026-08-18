from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .model import OpenAICompatibleModel
from .parsing import clean_extracted_text
from .prompts import EXTRACTION_PROMPT


class ContentExtractor:
    def __init__(self, model: OpenAICompatibleModel, workers: int = 2):
        self.model = model
        self.workers = workers

    def extract(self, images: list[Path], deck_dir: Path, force: bool = False) -> str:
        content_dir = deck_dir / "slide_contents"
        content_dir.mkdir(parents=True, exist_ok=True)

        def one(index: int, image: Path) -> tuple[int, str]:
            cache = content_dir / f"slide_{index:04d}.md"
            if cache.exists() and not force:
                text = clean_extracted_text(cache.read_text(encoding="utf-8"))
            else:
                text = clean_extracted_text(self.model.complete(EXTRACTION_PROMPT, [image]))
            # Rewriting also cleans historical Base64-contaminated caches.
            cache.write_text(text, encoding="utf-8")
            return index, text

        results = {}
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = [pool.submit(one, i, image) for i, image in enumerate(images, 1)]
            for future in as_completed(futures):
                index, text = future.result()
                results[index] = text
        return "\n\n".join(f"# Slide {i}\n{results[i]}" for i in sorted(results))

