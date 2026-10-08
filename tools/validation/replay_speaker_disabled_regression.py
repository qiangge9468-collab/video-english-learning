"""Whole-transcript regression: opt-in speaker evidence must not change defaults."""
from dataclasses import fields
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"tools/versions/v2.1.0"))
from semantic_caption_segmenter_v206 import BoundaryFeatures, SegmenterConfig, learning_sentences, normalize_words


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("Preserve prior regression")
    root = args.root
    cohorts = [(root/"updated-cohort.json", root/"windowed-pipeline-r5/alignment", root/"punctuation-learning-r4-original"),
               (root/"online-holdout-r1/manifest.json", root/"online-holdout-r1/pipeline/alignment", root/"punctuation-learning-r4-online"),
               (root/"punctuation-reserved-r4/manifest.json", root/"punctuation-reserved-r4/pipeline/alignment", root/"punctuation-reserved-r4/pipeline/learning")]
    reports = []
    for manifest, aligned, prior in cohorts:
        for item in read(manifest):
            name = item["name"]
            old = read(prior/name/"learning.json")
            debug = read(prior/name/"debug.json")
            words = normalize_words(read(aligned/name/"alignment.json")["words"])
            features = [BoundaryFeatures(index=0)] + [BoundaryFeatures(**b) for b in debug["boundaries"]] + [BoundaryFeatures(index=len(words))]
            config = SegmenterConfig(**debug["config"])
            if config.learning_speaker_boundaries:
                raise ValueError("Not a disabled-speaker baseline")
            new, _ = learning_sentences(words, features, config)
            # Compare actual unit text, ranges, timings, flags and display cues,
            # not merely sentence counts. Ignore no output fields.
            same = new == old
            reports.append({"name": name, "scope": "complete_cached_transcript", "words": len(words),
                            "units": len(new), "exact_output_match": same, "accuracy": None})
            print(json.dumps(reports[-1]), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(reports, indent=2), encoding="utf-8")
    raise SystemExit(0 if all(r["exact_output_match"] for r in reports) else 1)


if __name__ == "__main__":
    main()
