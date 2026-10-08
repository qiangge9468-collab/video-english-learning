"""Full-audio LOCAL Community-1 inference, using a user-provided authorized snapshot.

No token arguments, remote API, download, or automatic acceptance of model terms.
Run separately from ASR/translation to avoid competing for the 6GB GPU.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"tools/versions/v2.1.0"))
from speaker_boundary_evidence import boundary_evidence


def file_hash(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def annotation_turns(annotation):
    return [{"start": s.start, "end": s.end, "speaker": str(label)}
            for s, _, label in annotation.itertracks(yield_label=True)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("alignment", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    if not args.model.is_dir() or not (args.model/"config.yaml").exists():
        parser.error("Authorized local Community-1 snapshot required; no automatic gated download")
    if args.output.exists():
        raise FileExistsError("Preserve earlier experiments")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYANNOTE_METRICS_ENABLED="0")
    import numpy as np
    import torch
    from pyannote.audio import Pipeline
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this experiment")
    pipeline = Pipeline.from_pretrained(str(args.model))
    pipeline.to(torch.device("cuda"))
    args.output.mkdir(parents=True)
    model_hashes = {str(p.relative_to(args.model)): file_hash(p) for p in args.model.rglob("*") if p.is_file() and ".git" not in p.parts}
    reports = []
    for item in json.loads(args.manifest.read_text(encoding="utf-8-sig")):
        name = item["name"]
        print("START full-audio speaker inference " + name, flush=True)
        audio = Path(item["audio"])
        alignment = args.alignment/name/"alignment.json"
        decoded = subprocess.run([args.ffmpeg, "-v", "error", "-i", str(audio), "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"],
                                 capture_output=True, check=True)
        waveform = torch.from_numpy(np.frombuffer(decoded.stdout, dtype=np.float32).copy()).unsqueeze(0)
        duration = waveform.shape[1]/16000
        with torch.inference_mode():
            output = pipeline({"waveform": waveform, "sample_rate": 16000})
        turns = annotation_turns(output.exclusive_speaker_diarization)
        simultaneous = [{"start": s.start, "end": s.end} for s in output.speaker_diarization.get_overlap()]
        words = json.loads(alignment.read_text(encoding="utf-8-sig"))["words"]
        result = boundary_evidence(words, turns, simultaneous)
        result.update(name=name, scope="complete_audio", decoded_duration=duration, device="cuda",
                      model_hashes=model_hashes, audio_sha256=file_hash(audio), alignment_sha256=file_hash(alignment),
                      exclusive_turns=turns, overlapping_speech=simultaneous, release_allowed=False)
        (args.output/(name+".json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        reports.append({"name": name, "duration": duration, "boundary_candidates": len(result["boundaries"]), "accuracy": None})
        print(json.dumps(reports[-1]), flush=True)
    (args.output/"summary.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
