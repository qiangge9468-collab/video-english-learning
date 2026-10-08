"""Replay all complete OCR caches against unchanged full aligned transcripts."""
import argparse
import hashlib
import json
from pathlib import Path

from audit_ocr_timeline import audit as timeline
from stabilize_ocr_reference import audit as stabilize


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("validation_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.validation_root
    if args.output.exists():
        raise FileExistsError("Preserve prior evidence")
    args.output.mkdir(parents=True)
    cohorts = [(root/"updated-cohort.json", root, root/"windowed-pipeline-r5/alignment"),
               (root/"online-holdout-r1/manifest.json", root/"online-holdout-r1", root/"online-holdout-r1/pipeline/alignment"),
               (root/"punctuation-reserved-r4/manifest.json", root/"punctuation-reserved-r4", root/"punctuation-reserved-r4/pipeline/alignment")]
    summary = []
    for manifest, ocr_root, aligned_root in cohorts:
        for item in read(manifest):
            name = item["name"]
            folder = ocr_root/("updated-ocr-"+name)
            if not folder.exists():
                summary.append({"name": name, "status": "no_complete_ocr_reference", "accuracy": None})
                continue
            extraction = read(folder/"extraction.json")
            if not extraction["complete_video_reference"] or extraction.get("decode_errors"):
                raise ValueError("Incomplete OCR coverage")
            alignment = aligned_root/name/"alignment.json"
            words = read(alignment)["words"]
            result = stabilize(folder, item.get("ocr_min_y", 0))
            before = timeline(result["raw"], words)
            after = timeline(result["stable"], words)
            result.update(name=name, alignment_sha256=hashlib.sha256(alignment.read_bytes()).hexdigest(),
                          extraction=extraction, raw_timing=before, stable_timing=after)
            if result["observations_before"] != result["observations_after"]:
                raise AssertionError("Lost OCR observations")
            (args.output/(name+".json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            summary.append({"name": name, "status": "complete_ocr_cache_replay_unreviewed",
                            "duration": extraction["duration"], "decoded_frames": extraction["decoded_frames"],
                            "sample_count": extraction["sample_count"],
                            "raw_cues": result["raw_count"], "stable_cues": result["stable_count"],
                            "merged_groups": result["merged_groups"], "observations_preserved": True,
                            "raw_timing_counts": before["counts"], "stable_timing_counts": after["counts"],
                            "accuracy": None, "release_allowed": False})
            print(json.dumps(summary[-1]), flush=True)
    (args.output/"summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
