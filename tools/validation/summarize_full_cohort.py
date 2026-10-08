"""Summarize complete local experiments without promoting OCR to ground truth."""
import argparse
from collections import Counter
import json
from pathlib import Path
from compare_ocr_proposals import compare, proposals


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("validation_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.validation_root
    reports = []
    args.output.mkdir(parents=True, exist_ok=True)
    for item in read(args.manifest):
        name = item["name"]
        baseline = read(Path(item["cache"])/"whisper_words.json")
        aligned = read(root/"full-audio-r1-ordered"/name/"alignment.json")
        alternative = read(root/"full-novad-r1"/name/"asr.json")
        record = {"name": name, "duration_seconds": alternative["report"]["duration"],
                  "baseline_words": len(baseline), "guarded_words": len(aligned["words"]),
                  "novad_words": len(alternative["words"]),
                  "guarded_word_statuses": dict(Counter(w["alignment_status"] for w in aligned["words"])),
                  "release_allowed": False, "accuracy": None,
                  "reference_status": "unreviewed_ocr" if name != "airflare" else "no_continuous_burned_subtitle_reference"}
        ocr = root/("updated-ocr-"+name)
        if name != "airflare":
            extraction = read(ocr/"extraction.json")
            if not extraction["complete_video_reference"]:
                raise ValueError("Cannot summarize partial OCR as whole-video reference")
            # Explicit frame-selected ROI; two-line captions require the upper
            # line too. Never choose this threshold by ASR matching scores.
            cues = proposals(ocr, item.get("ocr_min_y", 0))
            record["ocr_min_y"] = item.get("ocr_min_y", 0)
            record["ocr_samples"] = extraction["sample_count"]
            record["ocr_cues"] = len(cues)
            for label, words in (("baseline", baseline), ("guarded", aligned["words"]), ("novad", alternative["words"])):
                triage = compare(cues, words)
                (args.output/(name+"-"+label+"-triage.json")).write_text(json.dumps(triage, ensure_ascii=False, indent=2), encoding="utf-8")
                record[label+"_ocr_word_recall_not_accuracy"] = triage["ocr_word_recall"]
        reports.append(record)
    report = {"scope": "four_complete_audio_runs_three_complete_burned_subtitle_scans",
              "videos": reports, "release_allowed": False, "status": "independent_review_incomplete"}
    (args.output/"summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
