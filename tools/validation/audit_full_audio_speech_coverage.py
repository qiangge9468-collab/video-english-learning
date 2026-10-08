"""Whole-audio VAD coverage audit of FINAL word times, not pre-alignment times.

VAD can itself miss speech; this audit is a diagnostic, never a recall score.
Supports the explicitly installed faster-whisper 1.1 and 1.2 parameter names.
"""
import argparse
import inspect
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"tools/versions/v2.1.0"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ["VIDEO_ENGLISH_DATA_DIR"] = str(args.output/"isolated-service")
    os.environ["WHISPER_RUNTIME_STATUS"] = str(args.output/"status.json")
    import service
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    signature = inspect.signature(VadOptions)
    thresholds = {"onset": .35, "offset": .30} if "onset" in signature.parameters else {"threshold": .35, "neg_threshold": .30}
    options = {**thresholds, "min_silence_duration_ms": 250, "speech_pad_ms": 200}
    summary = []
    for item in json.loads(args.manifest.read_text(encoding="utf-8")):
        audio = decode_audio(item["audio"], sampling_rate=16000)
        ranges = [(r["start"]/16000, r["end"]/16000) for r in get_speech_timestamps(audio, VadOptions(**options))]
        words = json.loads((Path(item["cache"])/"whisper_words.json").read_text(encoding="utf-8-sig"))
        gaps = service.find_uncovered_speech_gaps(words, ranges, len(audio)/16000)
        report = {"name": item["name"], "duration": len(audio)/16000, "vad_options": options,
                  "scope": "complete_audio", "speech_ranges": ranges, "uncovered_ranges": gaps,
                  "uncovered_seconds": sum(b-a for a,b in gaps), "uncovered_count": len(gaps),
                  "vad_is_not_ground_truth": True, "accuracy": None}
        (args.output/(item["name"]+".json")).write_text(json.dumps(report, indent=2), encoding="utf-8")
        summary.append({k:v for k,v in report.items() if k not in ("speech_ranges", "uncovered_ranges")})
        print(json.dumps(summary[-1]), flush=True)
    (args.output/"summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
