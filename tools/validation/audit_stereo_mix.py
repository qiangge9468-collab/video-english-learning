"""Whole-audio channel cancellation diagnostic; not a speech reference."""
import argparse
import json
from pathlib import Path
import subprocess
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ffmpeg", required=True)
    args = parser.parse_args()
    reports = []
    for item in json.loads(args.manifest.read_text(encoding="utf-8")):
        result = subprocess.run([args.ffmpeg, "-v", "error", "-i", item["audio"], "-vn",
                                 "-ac", "2", "-ar", "8000", "-f", "f32le", "pipe:1"], capture_output=True, check=True)
        audio = np.frombuffer(result.stdout, dtype="<f4").reshape(-1, 2)
        rows = []
        for start in range(0, len(audio), 40000):
            chunk = audio[start:start+40000].astype(np.float64)
            chunk -= chunk.mean(axis=0)
            energy = np.square(chunk).mean(axis=0)
            mixed = np.square(chunk.mean(axis=1)).mean()
            corr = np.mean(chunk[:, 0]*chunk[:, 1])/max(1e-12, np.sqrt(energy.prod()))
            db = 10*np.log10(max(1e-12, mixed)/max(1e-12, energy.max()))
            rows.append({"start": start/8000, "end": min(start+40000, len(audio))/8000,
                         "channel_correlation": float(corr), "mono_attenuation_db": float(db)})
        reports.append({"name": item["name"], "scope": "complete_audio", "blocks": rows,
                        "blocks_below_minus_12db": sum(r["mono_attenuation_db"] < -12 for r in rows)})
        args.output.write_text(json.dumps(reports, indent=2), encoding="utf-8")
        print(item["name"], reports[-1]["blocks_below_minus_12db"], flush=True)


if __name__ == "__main__":
    main()
