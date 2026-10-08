"""Whole-duration video/cache audio identity check (not caption accuracy).

Decode both entire streams; compare 10ms energy envelopes in every 60s block.
This detects wrong edits/offsets without copying media into the repository.
"""
import argparse
import json
from pathlib import Path
import subprocess
import numpy as np


def envelope(path, ffmpeg):
    command = [ffmpeg, "-v", "error", "-i", str(path), "-map", "0:a:0", "-vn",
               "-ac", "1", "-ar", "8000", "-f", "f32le", "pipe:1"]
    result = subprocess.run(command, capture_output=True, check=True)
    if result.stderr.strip():
        raise RuntimeError(result.stderr.decode(errors="replace"))
    samples = np.frombuffer(result.stdout, dtype="<f4")
    seconds = len(samples)/8000
    power = np.square(samples[:len(samples)//80*80].reshape(-1, 80)).mean(axis=1)
    return np.log10(power+1e-9), seconds


def compare(video, cached):
    rows = []
    for start in range(0, min(len(video), len(cached)), 6000):
        end = min(start+6000, len(video), len(cached))
        if end-start < 100:
            continue
        # Keep a common interior for all lags, not a different sample per lag.
        lo, hi = max(start, 100), min(end, len(video)-100)
        if hi-lo < 100:
            continue
        x = cached[lo:hi]-cached[lo:hi].mean()
        norm = np.linalg.norm(x)
        if norm < 1e-4:
            rows.append({"start": start/100, "end": end/100, "status": "uninformative_silence"})
            continue
        values = []
        for lag in range(-100, 101):
            y = video[lo+lag:hi+lag]
            y = y-y.mean()
            values.append(float(x.dot(y)/max(1e-9, norm*np.linalg.norm(y))))
        best = int(np.argmax(values))
        rows.append({"start": start/100, "end": end/100,
                     "zero_lag_correlation": values[100], "best_correlation": values[best],
                     "best_lag_seconds": (best-100)/100})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ffmpeg", required=True)
    args = parser.parse_args()
    reports = []
    for item in json.loads(args.manifest.read_text(encoding="utf-8")):
        video, video_seconds = envelope(item["video"], args.ffmpeg)
        audio, audio_seconds = envelope(item["audio"], args.ffmpeg)
        rows = compare(video, audio)
        report = {"name": item["name"], "video_audio_seconds": video_seconds,
                  "cached_audio_seconds": audio_seconds, "blocks": rows,
                  "caption_accuracy": None, "full_streams_decoded": True}
        reports.append(report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(reports, indent=2), encoding="utf-8")
        print(json.dumps({k:v for k,v in report.items() if k != "blocks"}), flush=True)


if __name__ == "__main__":
    main()
