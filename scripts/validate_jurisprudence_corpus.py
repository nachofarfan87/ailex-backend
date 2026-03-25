"""
Validate curated jurisprudence datasets before admitting them into AILEX.

Usage:
    python scripts/validate_jurisprudence_corpus.py
    python scripts/validate_jurisprudence_corpus.py path/to/jurisprudence
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_engine.jurisprudence_curation import validate_curated_corpus_root  # noqa: E402


def main() -> int:
    target_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else (ROOT / "data" / "jurisprudence")
    reports = validate_curated_corpus_root(target_root)

    payload = [report.to_dict() for report in reports]
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    has_errors = any(not report.is_valid for report in reports)
    return 1 if has_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
