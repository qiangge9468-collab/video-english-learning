"""Re-score saved model features without reloading models; preserve first runs."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/versions/v2.1.0"))
from semantic_caption_segmenter_v206 import BoundaryFeatures, SegmenterConfig, normalize_words, learning_sentences
from alignment_quality import audit_words


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    summaries = json.loads((args.experiment/"summary.json").read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    result = []
    for summary in summaries:
        cache = Path(summary["cache"])
        raw = json.loads((cache/"whisper_words.json").read_text(encoding="utf-8-sig"))
        words = normalize_words(raw)
        debug = json.loads((args.experiment/cache.name/"debug.json").read_text(encoding="utf-8"))
        features = [BoundaryFeatures(index=0)] + [BoundaryFeatures(**b) for b in debug["boundaries"]]
        features.append(BoundaryFeatures(index=len(words)))
        sentences, decisions = learning_sentences(words, features, SegmenterConfig(learning_sentence_mode=True))
        target = args.output/cache.name
        target.mkdir(exist_ok=True)
        quality = audit_words(raw)
        baseline = json.loads((cache/"english.json").read_text(encoding="utf-8-sig"))
        for name, content in (("learning.json", sentences), ("decisions.json", decisions), ("alignment_quality.json", quality)):
            (target/name).write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
        result.append({"title": summary["title"], "input_words": len(raw),
                       "word_range_coverage": sentences[-1]["word_end"] if sentences else 0,
                       "baseline_cues": len(baseline), "learning_sentences": len(sentences),
                       "display_cues": sum(len(s["display_cues"]) for s in sentences),
                       "warnings": len(decisions["warnings"]),
                       "alignment_issues": dict(Counter(i["kind"] for i in quality["issues"])),
                       "reference_accuracy": None, "release_allowed": False})
    (args.output/"summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
