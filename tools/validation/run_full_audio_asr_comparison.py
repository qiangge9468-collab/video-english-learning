"""Independent full-audio ASR comparison with VAD disabled.

Never consumes OCR text, never merges unchecked words into production captions.
Retains raw results and decoding options for every audio, including repetitions.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    os.environ["PATH"] = os.pathsep.join([str(Path(sys.prefix)/"Library/bin"), os.environ.get("PATH", "")])
    for directory in [Path(sys.prefix)/"Library/bin", Path(sys.prefix)/"Lib/site-packages/torch/lib"]:
        if directory.is_dir():
            os.add_dll_directory(str(directory))
    import torch  # Keep CUDA DLL dependencies loaded before CTranslate2.
    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cuda", compute_type="int8_float16", local_files_only=True)
    args.output.mkdir(parents=True, exist_ok=True)
    reports = []
    for item in json.loads(args.manifest.read_text(encoding="utf-8")):
        target = args.output/item["name"]
        target.mkdir(exist_ok=True)
        output = target/"asr.json"
        if output.exists():
            raise FileExistsError("Refusing to replace previous experiment")
        started = time.monotonic()
        options = {"language": "en", "beam_size": 5, "word_timestamps": True,
                   "vad_filter": False, "condition_on_previous_text": False,
                   "temperature": [0., .2, .4, .6, .8, 1.]}
        stream, info = model.transcribe(item["audio"], **options)
        segments, words = [], []
        print(f'START {item["name"]}: {info.duration:.1f}s', flush=True)
        with (target/"segments.jsonl").open("w", encoding="utf-8") as log:
            for segment in stream:
                start_index = len(words)
                for word in segment.words or []:
                    words.append({"index": len(words), "segment_id": len(segments),
                                  "text": word.word.strip(), "start": word.start, "end": word.end,
                                  "probability": word.probability, "asr_probability": word.probability})
                record = {"id": len(segments), "start": segment.start, "end": segment.end,
                          "text": segment.text.strip(), "word_start": start_index, "word_end": len(words),
                          "avg_logprob": segment.avg_logprob, "no_speech_prob": segment.no_speech_prob,
                          "compression_ratio": segment.compression_ratio, "temperature": segment.temperature}
                segments.append(record)
                log.write(json.dumps(record)+"\n")
                if len(segments) % 25 == 0:
                    log.flush()
                    print(f'{item["name"]}: {segment.end:.0f}/{info.duration:.0f}s', flush=True)
        report = {"name": item["name"], "duration": info.duration, "word_count": len(words),
                  "segment_count": len(segments), "elapsed_seconds": time.monotonic()-started,
                  "options": options, "model": args.model, "scope": "complete_audio",
                  "independent_reference_used_for_decoding": False, "accuracy": None, "release_allowed": False}
        output.write_text(json.dumps({"segments": segments, "words": words, "report": report}), encoding="utf-8")
        reports.append(report)
        (args.output/"summary.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
