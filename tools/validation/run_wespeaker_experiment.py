"""Account-free full-audio speaker evidence, isolated from production.

WeSpeaker ResNet34-LM + existing Silero VAD. Uses the official 80-bin Kaldi
frontend and 1.5 s / .75 s embedding windows. Spectral graph clustering follows
the approach documented in the official VoxConverse recipe, with fixed seed.
No overlap detector: acoustic proposals require additional semantic support.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"tools/versions/v2.1.0"))
from speaker_boundary_evidence import boundary_evidence


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def windows(speech, length=1.5, step=.75):
    result = []
    for group, (a, b) in enumerate(speech):
        if b-a < .255:
            continue
        start = a
        while True:
            end = min(start+length, b)
            result.append({"start": start, "end": end, "speech_group": group})
            if end >= b:
                break
            start += step
    return result


def cluster(embeddings):
    import numpy as np
    from scipy.linalg import eigh
    from sklearn.cluster import KMeans
    n = len(embeddings)
    if n <= 2:
        return np.zeros(n, dtype=int)
    norm = embeddings/np.maximum(np.linalg.norm(embeddings, axis=1, keepdims=True), 1e-8)
    similarity = norm @ norm.T
    # Match the reference recipe's retained-neighbor scale, with explicit
    # small-input guards. All observations participate, no fixed speaker count.
    keep = min(n-2, 10) if n < 1000 else max(2, n-int(.99*n))
    nearest = np.argsort(similarity, axis=1)[:, -keep:]
    adjacency = np.zeros((n,n), dtype=np.float64)
    adjacency[np.arange(n)[:,None], nearest] = 1
    adjacency = (adjacency+adjacency.T)/2
    np.fill_diagonal(adjacency, 0)
    laplacian = np.diag(adjacency.sum(axis=1))-adjacency
    limit = min(20, n-1)
    values, vectors = eigh(laplacian, subset_by_index=[0, limit])
    count = int(np.argmax(np.diff(values)))+1
    return KMeans(n_clusters=count, random_state=0, n_init=10).fit_predict(vectors[:,:count])


def turns_from_windows(win, labels):
    turns = []
    for i, (window, label) in enumerate(zip(win, labels)):
        a, b = window["start"], window["end"]
        if i and win[i-1]["speech_group"] == window["speech_group"]:
            a = (win[i-1]["end"]+window["start"])/2
        if i+1 < len(win) and win[i+1]["speech_group"] == window["speech_group"]:
            b = (window["end"]+win[i+1]["start"])/2
        speaker = "speaker_"+str(int(label))
        if turns and turns[-1]["speaker"] == speaker and abs(turns[-1]["end"]-a) < 1e-6:
            turns[-1]["end"] = b
        else:
            turns.append({"start": a, "end": b, "speaker": speaker})
    return turns


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest", type=Path)
    p.add_argument("alignment", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--ort-site", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("Preserve earlier runs")
    sys.path.insert(0, str(args.ort_site.resolve()))
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", OMP_NUM_THREADS="4")
    import numpy as np
    import torch
    import torchaudio.compliance.kaldi as kaldi
    import onnxruntime as ort
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    torch.set_num_threads(4)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA required, no silent CPU fallback")
    ort.preload_dlls()
    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    options.enable_profiling = True
    args.output.mkdir(parents=True)
    options.profile_file_prefix = str(args.output/"onnx-profile")
    session = ort.InferenceSession(str(args.model), sess_options=options, providers=[
        ("CUDAExecutionProvider", {"gpu_mem_limit": str(2*1024**3), "cudnn_conv_algo_search": "HEURISTIC"})])
    session.disable_fallback()
    if "CUDAExecutionProvider" not in session.get_providers():
        raise RuntimeError("GPU execution provider failed to initialize")
    reports = []
    for item in json.loads(args.manifest.read_text(encoding="utf-8-sig")):
        started = time.monotonic()
        name = item["name"]
        print("START full-audio " + name, flush=True)
        audio = decode_audio(item["audio"], sampling_rate=16000)
        duration = len(audio)/16000
        if item.get("duration") and abs(duration-item["duration"]) > 1:
            raise ValueError("Decoded audio duration mismatch")
        audio_hash = sha(item["audio"])
        if item.get("audio_sha256") and audio_hash != item["audio_sha256"]:
            raise ValueError("Audio identity mismatch")
        vad = get_speech_timestamps(audio, VadOptions(threshold=.5, min_speech_duration_ms=255,
            min_silence_duration_ms=250, speech_pad_ms=0))
        speech = [(s["start"]/16000, s["end"]/16000) for s in vad]
        win = windows(speech)
        embedding_batches, features = [], []
        for i, w in enumerate(win):
            waveform = torch.from_numpy(audio[round(w["start"]*16000):round(w["end"]*16000)].copy()).unsqueeze(0)*32768
            fbank = kaldi.fbank(waveform, num_mel_bins=80, frame_length=25, frame_shift=10,
                               dither=0., sample_frequency=16000, window_type="hamming", use_energy=False).numpy()
            # Repetition padding and per-window mean normalization match the
            # reference recipe; true audio intervals stay unpadded in results.
            fbank = np.resize(fbank, (150,80))
            features.append(fbank-fbank.mean(axis=0, keepdims=True))
            if len(features) == 16 or i == len(win)-1:
                embedding_batches.append(session.run(["embs"], {"feats": np.stack(features)})[0])
                features = []
            if (i+1) % 200 == 0:
                print(f"  {name}: {i+1}/{len(win)} windows", flush=True)
        embs = np.concatenate(embedding_batches) if embedding_batches else np.empty((0,256))
        labels = cluster(embs)
        turns = turns_from_windows(win, labels)
        alignment = args.alignment/name/"alignment.json"
        words = json.loads(alignment.read_text(encoding="utf-8-sig"))["words"]
        evidence = boundary_evidence(words, turns)
        # Overlap detection is UNKNOWN, not a claim that no overlapping speech
        # occurred. Keep these proposals opt-in and semantically corroborated.
        evidence.update(name=name, scope="complete_audio", decoded_duration=duration, speech_ranges=speech,
            exclusive_turns=turns, model_sha256=sha(args.model), audio_sha256=audio_hash,
            alignment_sha256=sha(alignment), requires_semantic_support=True, overlap_detection_available=False,
            window_seconds=1.5, step_seconds=.75, window_count=len(win),
            provider=session.get_providers(), onnxruntime_version=ort.__version__, release_allowed=False)
        (args.output/(name+".json")).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        np.savez_compressed(args.output/(name+"-embeddings.npz"), embeddings=embs, labels=labels)
        reports.append({"name": name, "duration": duration, "words": len(words), "windows": len(win),
                        "speakers": len(set(labels.tolist())), "turns": len(turns),
                        "boundary_candidates": len(evidence["boundaries"]), "elapsed_seconds": time.monotonic()-started,
                        "scope": "complete_audio", "accuracy": None, "release_allowed": False})
        print(json.dumps(reports[-1]), flush=True)
        (args.output/"summary.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    profile = Path(session.end_profiling())
    events = json.loads(profile.read_text(encoding="utf-8"))
    providers = Counter(e.get("args", {}).get("provider") for e in events if e.get("args", {}).get("provider"))
    verification = {"provider_node_events": dict(providers), "gpu_verified": providers["CUDAExecutionProvider"] > 0,
                    "model_sha256": sha(args.model), "code_sha256": sha(__file__)}
    (args.output/"execution.json").write_text(json.dumps(verification, indent=2), encoding="utf-8")
    print(json.dumps(verification), flush=True)
    if not verification["gpu_verified"]:
        raise RuntimeError("No recorded CUDA node execution")


if __name__ == "__main__":
    main()
