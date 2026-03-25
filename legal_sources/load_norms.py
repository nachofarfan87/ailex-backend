"""Load bundled Argentine normative corpus files from backend/data/legal/ar."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


_BACKEND_DIR = Path(__file__).resolve().parents[1]
_NORMATIVE_BASE_DIR = _BACKEND_DIR / "data" / "legal" / "ar"
_CORPUS_LAYOUT: dict[str, tuple[str, ...]] = {
    "nacional": (
        "constitucion_nacional",
        "codigo_civil_comercial",
        "lct_20744",
    ),
    "jujuy": (
        "constitucion_jujuy",
        "cpcc_jujuy",
    ),
}


@lru_cache(maxsize=1)
def load_normative_corpus() -> dict[str, dict]:
    """
    Load bundled normative JSON files keyed by file stem.

    Returns:
        {
            "constitucion_nacional": {...},
            "codigo_civil_comercial": {...},
            "constitucion_jujuy": {...},
            "cpcc_jujuy": {...},
            "lct_20744": {...},
        }
    """
    corpus: dict[str, dict] = {}

    for jurisdiction, file_stems in _CORPUS_LAYOUT.items():
        jurisdiction_dir = _NORMATIVE_BASE_DIR / jurisdiction
        for file_stem in file_stems:
            file_path = jurisdiction_dir / f"{file_stem}.json"
            corpus[file_stem] = _load_json_file(file_path)

    return corpus


def _load_json_file(file_path: Path) -> dict:
    if not file_path.exists():
        raise FileNotFoundError(f"Normative corpus file not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"Normative corpus file must contain a JSON object: {file_path}")

    return data
