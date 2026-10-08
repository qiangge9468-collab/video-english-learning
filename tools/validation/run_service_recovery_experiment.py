"""Execute the actual service repair policy over every audio in a cohort.

Writes a new cache-shaped experimental directory and follow-up manifest;
never overwrites baseline caches. Run forced alignment/segmentation after this.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"tools/versions/v2.1.0"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("alignment", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--name", help="Diagnostic selection only; not full-cohort verification")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ.update(VIDEO_ENGLISH_DATA_DIR=str(args.output/"isolated-service"),
                      WHISPER_RUNTIME_STATUS=str(args.output/"status.json"),
                      WHISPER_RUNTIME_CONFIG=str(args.output/"config.json"))
    os.environ["PATH"] = os.pathsep.join([str(Path(sys.prefix)/"Library/bin"), os.environ.get("PATH", "")])
    import torch
    import service
    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cuda", compute_type="int8_float16", local_files_only=True)
    summary, manifest = [], []
    for item in json.loads(args.manifest.read_text(encoding="utf-8")):
        if args.name and args.name != item["name"]:
            continue
        source = json.loads((args.alignment/item["name"]/"alignment.json").read_text(encoding="utf-8"))
        output = args.output/item["name"]
        output.mkdir(exist_ok=True)
        if (output/"whisper_words.json").exists():
            raise FileExistsError("Keep earlier experimental outputs")
        started = time.monotonic()
        segments, words, debug = service.recover_uncovered_speech(model, item["audio"],
            source["segments"], source["words"], "en", item["name"], whole_word_gap=True)
        for filename, data in (("whisper_segments.json", segments), ("whisper_words.json", words), ("recovery.json", debug)):
            (output/filename).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        if debug.get("error"):
            raise RuntimeError(debug["error"])
        report = {"name": item["name"], "before_words": len(source["words"]), "after_words": len(words),
                  "added_candidates": len(debug["recovered"]), "remaining_candidates": len(debug.get("remaining_candidates", [])),
                  "elapsed_seconds": time.monotonic()-started, "accuracy": None, "release_allowed": False}
        summary.append(report)
        manifest.append({**item, "baseline_cache": item["cache"], "cache": str(output.resolve())})
        (args.output/"summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        (args.output/"manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
