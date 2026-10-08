"""Run alignment -> learning sentences -> translation on ONE frozen cohort.

Input is a recovery experiment manifest. No production files are overwritten.
Stages use their own Python runtimes serially to avoid competing for GPU memory.
Completion means executed, not accurate; independent reference is still required.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4*1024*1024), b""):
            result.update(block)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--alignment-python", required=True)
    parser.add_argument("--semantic-python", required=True)
    parser.add_argument("--learning-threshold", type=float, default=.75)
    parser.add_argument("--soft-dependencies", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.learning_threshold <= 1:
        parser.error("learning threshold must be between zero and one")
    args.manifest = args.manifest.resolve()
    args.output = args.output.resolve()
    if args.output.exists():
        raise FileExistsError("Preserve previous full pipeline experiments")
    cohort = read(args.manifest)
    if not cohort or len({i["audio"] for i in cohort}) != len(cohort):
        raise ValueError("Explicit distinct cohort required")
    args.output.mkdir(parents=True)
    sources = list((ROOT/"tools/versions/v2.1.0").glob("*.py")) + list((ROOT/"tools/validation").glob("*.py"))
    snapshot = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    record = {"scope": "one_cohort_recovery_outputs_through_alignment_segmentation_translation",
              "source_sha256": snapshot, "input_manifest_sha256": digest(args.manifest),
              "inputs": [{"name": i["name"], "audio_sha256": digest(i["audio"]),
                          "words_sha256": digest(Path(i["cache"])/"whisper_words.json"),
                          "segments_sha256": digest(Path(i["cache"])/"whisper_segments.json")} for i in cohort],
              "stages": [], "complete": False, "accuracy": None, "release_allowed": False,
              "learning_threshold": args.learning_threshold, "soft_dependencies": args.soft_dependencies}
    def save():
        (args.output/"pipeline.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    save()
    scripts = ROOT/"tools/validation"
    commands = [
        ("alignment", [args.alignment_python, scripts/"run_full_audio_alignment_experiment.py", args.manifest,
            args.output/"alignment", "--model-dir", args.project/"models/whisperx"]),
        ("learning", [args.semantic_python, scripts/"run_cohort_learning_experiment.py", args.manifest,
            args.output/"alignment", args.output/"learning", "--project", args.project, "--phase", "segment",
            "--learning-threshold", str(args.learning_threshold)] + (["--soft-dependencies"] if args.soft_dependencies else [])),
        ("translation", [args.alignment_python, scripts/"run_cohort_learning_experiment.py", args.manifest,
            args.output/"learning", args.output/"translation", "--project", args.project, "--phase", "translate"]),
    ]
    environment = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONIOENCODING="utf-8")
    for stage, command in commands:
        if any(digest(ROOT/p) != h for p,h in snapshot.items()):
            raise RuntimeError("Source changed after experiment freeze; use a new run")
        started = time.monotonic()
        print(f"START {stage} for {len(cohort)} complete transcripts", flush=True)
        with (args.output/(stage+".log")).open("w", encoding="utf-8") as stream:
            process = subprocess.run([str(x) for x in command], cwd=ROOT, env=environment,
                                     stdout=stream, stderr=subprocess.STDOUT)
        record["stages"].append({"name": stage, "exit_code": process.returncode,
                                 "elapsed_seconds": time.monotonic()-started})
        save()
        if process.returncode:
            raise RuntimeError(f"{stage} failed: see its retained log")
        report = read(args.output/stage/"summary.json")
        if len(report) != len(cohort) or (stage == "alignment" and any(r.get("worker_exit_code") != 0 for r in report)):
            raise RuntimeError(f"{stage} incomplete")
        print(f"FINISH {stage}", flush=True)
    record["complete"] = True
    record["reference_status"] = "independent_accuracy_review_not_completed"
    save()
    print("Complete pipeline executed; accuracy remains unverified.", flush=True)


if __name__ == "__main__":
    main()
