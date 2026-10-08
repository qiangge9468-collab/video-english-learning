"""Independent short-context retries for ALL whole-audio uncovered VAD ranges.

Candidates are review-only: no OCR prompts, no deletion/overwrite of baseline,
no automatic claim that VAD-positive noise/music is intelligible speech.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time


def windows(ranges, duration, padding=1., max_seconds=18., words=None):
    result = []
    for start, end in sorted(ranges):
        if words:
            # VAD can fragment a quiet utterance. Retry its whole WORD gap,
            # not only a subsecond loud syllable, without borrowing OCR text.
            before = [float(w["end"]) for w in words if float(w["end"]) <= start]
            after = [float(w["start"]) for w in words if float(w["start"]) >= end]
            left, right = max(before, default=0.), min(after, default=duration)
            if right-left <= max_seconds-2*padding:
                start, end = left, right
        start, end = max(0., start-padding), min(duration, end+padding)
        if result and start <= result[-1][1] and end-result[-1][0] <= max_seconds:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("coverage", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--whole-word-gap", action="store_true", help="Retry complete nearby word gaps, including quiet VAD-negative portions")
    args = parser.parse_args()
    os.environ["PATH"] = os.pathsep.join([str(Path(sys.prefix)/"Library/bin"), os.environ.get("PATH", "")])
    import torch
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio
    model = WhisperModel(args.model, device="cuda", compute_type="int8_float16", local_files_only=True)
    args.output.mkdir(parents=True, exist_ok=True)
    reports = []
    for item in json.loads(args.manifest.read_text(encoding="utf-8")):
        target = args.output/item["name"]
        target.mkdir(exist_ok=True)
        if (target/"recovery.json").exists():
            raise FileExistsError("Keep previous experiments; choose a new output")
        audit = json.loads((args.coverage/(item["name"]+".json")).read_text(encoding="utf-8"))
        source_words = json.loads((Path(item["cache"])/"whisper_words.json").read_text(encoding="utf-8-sig")) if args.whole_word_gap else None
        candidates = windows(audit["uncovered_ranges"], audit["duration"], padding=.35 if args.whole_word_gap else 1., words=source_words)
        audio = decode_audio(item["audio"], sampling_rate=16000)
        started = time.monotonic()
        rows = []
        with (target/"windows.jsonl").open("w", encoding="utf-8") as log:
            for i, (start, end) in enumerate(candidates):
                parts, _ = model.transcribe(audio[int(start*16000):int(end*16000)], language="en", beam_size=5,
                    vad_filter=False, word_timestamps=True, condition_on_previous_text=False,
                    initial_prompt=None, temperature=0., no_speech_threshold=.6)
                result = []
                for part in parts:
                    result.append({"start": part.start+start, "end": part.end+start, "text": part.text.strip(),
                        "avg_logprob": part.avg_logprob, "no_speech_prob": part.no_speech_prob,
                        "compression_ratio": part.compression_ratio,
                        "words": [{"text": w.word.strip(), "start": w.start+start, "end": w.end+start,
                                   "probability": w.probability} for w in part.words or []]})
                record = {"window_start": start, "window_end": end, "segments": result,
                          "review_required": True}
                rows.append(record)
                log.write(json.dumps(record)+"\n")
                log.flush()
                if i % 10 == 0:
                    print(f'{item["name"]}: gap {i+1}/{len(candidates)}', flush=True)
        (target/"recovery.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
        report = {"name": item["name"], "whole_audio_vad_ranges_scanned": len(audit["speech_ranges"]),
                  "uncovered_ranges": len(audit["uncovered_ranges"]), "retry_windows": len(candidates),
                  "whole_word_gap": args.whole_word_gap,
                  "elapsed_seconds": time.monotonic()-started, "scope": "all_gaps_from_whole_audio_audit",
                  "accuracy": None, "release_allowed": False}
        reports.append(report)
        (args.output/"summary.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
