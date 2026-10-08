"""Re-align COMPLETE cached transcripts against complete audio; no live writes.

No ASR ground-truth claim: the cached transcript may already contain errors.
Inputs are an explicit manifest; model, audio, video and output paths are local.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4*1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model-dir", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    reports = []
    for item in read(args.manifest):
        target = args.output/item["name"]
        target.mkdir(exist_ok=True)
        if (target/"alignment.json").exists():
            raise FileExistsError("Choose a fresh output directory, preserving earlier experiments")
        cache = Path(item["cache"])
        payload = {"segments": read(cache/"whisper_segments.json"), "words": read(cache/"whisper_words.json")}
        (target/"input.json").write_text(json.dumps(payload), encoding="utf-8")
        record = {**item, "video_sha256": digest(item["video"]), "audio_sha256": digest(item["audio"]),
                  "source_words": len(payload["words"]), "reference_accuracy": None,
                  "scope": "complete_cached_transcript_against_complete_audio", "release_allowed": False}
        started = time.monotonic()
        print(f'START {item["name"]}: {len(payload["segments"])} segments', flush=True)
        with (target/"worker.log").open("w", encoding="utf-8") as log:
            completed = subprocess.run([sys.executable, str(ROOT/"tools/versions/v2.1.0/whisperx_worker.py"),
                "--input", str(target/"input.json"), "--output", str(target/"alignment.json"),
                "--audio", item["audio"], "--language", "en", "--device", "cuda", "--model-dir", args.model_dir,
                "--quality-guard"], stdout=log, stderr=subprocess.STDOUT)
        record["worker_exit_code"] = completed.returncode
        record["elapsed_seconds"] = time.monotonic()-started
        if completed.returncode == 0:
            debug = read(target/"alignment.json")["debug"]
            record.update({k: v for k, v in debug.items() if k != "segments"})
        reports.append(record)
        (args.output/"summary.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
        print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
