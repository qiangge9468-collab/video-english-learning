"""Classify existing full-cohort translations without rerunning or rewriting them.

Nonempty output and heuristic warnings are NOT translation accuracy.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Preserve previous audits")
    with tempfile.TemporaryDirectory() as temporary:
        os.environ.update(VIDEO_ENGLISH_DATA_DIR=temporary,
                          WHISPER_RUNTIME_CONFIG=str(Path(temporary)/"config.json"),
                          WHISPER_RUNTIME_STATUS=str(Path(temporary)/"status.json"))
        sys.path.insert(0, str(ROOT/"tools/versions/v2.1.0"))
        import service
        reports = []
        for path in sorted(args.input.glob("*/bilingual.json")):
            items = json.loads(path.read_text(encoding="utf-8"))
            statuses = [service.caption_translation_status(s["text"], s.get("translation")) for s in items]
            reports.append({"name": path.parent.name, "sentences": len(items),
                            "statuses": dict(Counter(statuses)),
                            "warning_indexes": [i for i,s in enumerate(statuses)
                                                if s not in ("generated_unreviewed", "deterministic")],
                            "translation_accuracy": None, "release_allowed": False})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(reports, indent=2), encoding="utf-8")
        print(json.dumps(reports))


if __name__ == "__main__":
    main()
