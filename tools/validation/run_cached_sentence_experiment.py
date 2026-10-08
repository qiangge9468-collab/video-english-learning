"""Offline full-cache segmentation experiment; never changes the live cache."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/versions/v2.1.0"))
from semantic_caption_segmenter_v206 import SegmenterConfig, segment_words


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    torch.set_num_threads(4)
    from wtpsplit import SaT
    import spacy
    sat = SaT(str(args.project / "models/sat-12l-sm"),
              tokenizer_name_or_path=str(args.project / "models/xlm-roberta-base"),
              from_pretrained_kwargs={"local_files_only": True})
    nlp = spacy.load("en_core_web_trf")
    args.output.mkdir(parents=True, exist_ok=True)
    titles = ["Hiking 200km", "How to AIRFLARE", "I Found Pakistans", "Switzerland", "Crossing Africa"]
    selected = {}
    for version in ("v2.0.6", "v2.1.0"):
        data = args.project / f"service_data_{version}"
        for upload in sorted((data / "uploads").glob("*.json")):
            metadata = json.loads(upload.read_text(encoding="utf-8-sig"))
            title = metadata.get("video_title", "")
            cache = data / "cache" / metadata["audio_hash"]
            if any(title.startswith(t) for t in titles) and (cache / "whisper_words.json").is_file():
                selected[title] = cache
    reports = []
    for title, cache in selected.items():
        started = time.monotonic()
        words = json.loads((cache / "whisper_words.json").read_text(encoding="utf-8-sig"))
        print(f"START {title} {len(words)} words", flush=True)
        result, debug = segment_words(words, sat, nlp, SegmenterConfig(learning_sentence_mode=True))
        target = args.output / cache.name
        target.mkdir(exist_ok=True)
        for name, content in (("learning.json", result), ("debug.json", debug)):
            (target/name).write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
        report = {"title": title, "cache": str(cache), "output": str(target),
                  "input_words": len(words), "output_sentences": len(result),
                  "warning_count": len(debug["warnings"]),
                  "covered_word_ranges": result[-1]["word_end"] if result else 0,
                  "elapsed_seconds": time.monotonic()-started,
                  "reference_accuracy": None, "release_gate": "not_evaluated"}
        reports.append(report)
        (args.output/"summary.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
