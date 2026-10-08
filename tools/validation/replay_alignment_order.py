"""Replay only chronology on saved guarded alignment, preserving first run."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"tools/versions/v2.1.0"))
from guarded_alignment import order_artifacts_chronologically


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for source in sorted(args.input.glob("*/alignment.json")):
        output = args.output/source.parent.name/"alignment.json"
        if output.exists():
            raise FileExistsError("Do not overwrite earlier experiments")
        result = json.loads(source.read_text(encoding="utf-8"))
        count = len(result["words"])
        moved = order_artifacts_chronologically(result["segments"], result["words"])
        assert count == len(result["words"])
        result["debug"].update(chronologically_reordered_words=moved, replayed_from=str(source),
                               replay_scope="chronology_only_no_new_alignment_inference")
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(source.parent.name, count, moved)


if __name__ == "__main__":
    main()
