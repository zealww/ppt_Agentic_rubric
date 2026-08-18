from __future__ import annotations

import json
from pathlib import Path


def load_topic_map(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise ValueError("Topic map must be a JSON object mapping PPT stem to topic string")
    return data


def resolve_topic(ppt: Path, mapping: dict[str, str]) -> str:
    return mapping.get(ppt.stem, ppt.stem)

