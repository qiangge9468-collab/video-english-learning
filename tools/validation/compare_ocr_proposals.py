"""Triage OCR proposals against cached words, NOT an accuracy/release claim.

Retains unmatched/low-confidence cues in the denominator. Search is time-local
to avoid matching a repeated phrase hours away. Display cue endpoints are
reported separately from actual speech timings, which require audio review.
"""
import argparse
from collections import Counter
from difflib import SequenceMatcher
import json
from pathlib import Path
import re


def tokens(text):
    return re.findall(r"[a-z]+(?:'[a-z]+)?|\d+", text.lower().replace("’", "'"))


def sorted_lines(lines):
    # Group baselines before x ordering: OCR detector may output two pieces
    # of one subtitle line in the wrong order if their y values differ slightly.
    rows = []
    for item in sorted(lines, key=lambda x: min(p[1] for p in x["box"])):
        y = sum(p[1] for p in item["box"]) / 4
        height = max(p[1] for p in item["box"]) - min(p[1] for p in item["box"])
        if rows and abs(rows[-1][0]-y) < max(8, height*.6):
            rows[-1][1].append(item)
        else:
            rows.append((y, [item]))
    return [item for _, row in rows for item in sorted(row, key=lambda x: min(p[0] for p in x["box"]))]


def proposals(folder, min_y=0):
    source = json.loads((folder / "source.json").read_text(encoding="utf-8"))
    interval = source["interval"]
    groups = []
    current = None
    for line in (folder / "samples.jsonl").read_text(encoding="utf-8").splitlines():
        frame = json.loads(line)
        # Region selected from VIDEO FRAMES, never from the generated transcript.
        # Keep raw samples so excluded overlays and missing subtitles are auditable.
        scale = min(1, 1280/source["width"])
        english = [item for item in frame["lines"] if tokens(item["text"])
                   and source["crop_top"] + sum(p[1] for p in item["box"])/4/scale/source["height"] >= min_y]
        text = " ".join(x["text"].strip() for x in sorted_lines(english)).strip()
        same = current and text and SequenceMatcher(None, tokens(current["last_text"]), tokens(text), autojunk=False).ratio() >= .8
        if same and frame["time"] - current["last_sample"] <= interval*1.2:
            current["end"] = frame["time"]+interval
            current["variants"][text] += 1
            current["last_text"] = text
            current["last_sample"] = frame["time"]
            current["observations"] += 1
        else:
            if current:
                groups.append(current)
            current = None if not text else {
                "start": frame["time"], "end": frame["time"]+interval,
                "variants": Counter({text: 1}), "last_text": text,
                "last_sample": frame["time"], "observations": 1}
    if current:
        groups.append(current)
    return [{"id": i, "start": g["start"], "end": g["end"],
             "text": g["variants"].most_common(1)[0][0], "observations": g["observations"],
             "variants": dict(g["variants"]), "reviewed": False} for i, g in enumerate(groups)]


def compare(cues, words):
    rows = []
    for cue in cues:
        reference = tokens(cue["text"])
        window = [(i, t) for i, w in enumerate(words)
                  if float(w["end"]) >= cue["start"]-20 and float(w["start"]) <= cue["end"]+20
                  for t in tokens(w["text"])]
        matcher = SequenceMatcher(None, reference, [t for _, t in window], autojunk=False)
        blocks = [b for b in matcher.get_matching_blocks() if b.size]
        matched = sum(b.size for b in blocks)
        mapped = [window[b.b+k][0] for b in blocks for k in range(b.size)]
        row = {**cue, "reference_token_count": len(reference), "matched_tokens": matched,
               "ocr_word_recall": matched/max(1, len(reference)),
               "candidate_word_start": min(mapped) if mapped else None,
               "candidate_word_end": max(mapped)+1 if mapped else None,
               "onset_delta_from_display": None, "offset_delta_from_display": None}
        if mapped:
            first, last = min(mapped), max(mapped)
            row["onset_delta_from_display"] = float(words[first]["start"])-cue["start"]
            row["offset_delta_from_display"] = float(words[last]["end"])-cue["end"]
            row["candidate_text"] = " ".join(w["text"] for w in words[first:last+1])
        rows.append(row)
    total = sum(r["reference_token_count"] for r in rows)
    return {"status": "unreviewed_ocr_triage_only", "release_allowed": False,
            "speech_timing_accuracy": None, "sentence_boundary_accuracy": None,
            "cue_count": len(rows), "reference_token_count": total,
            "ocr_word_recall": sum(r["matched_tokens"] for r in rows)/total if total else None,
            "unmatched_cues": sum(r["matched_tokens"] == 0 for r in rows), "items": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ocr", type=Path)
    parser.add_argument("words", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--min-y", type=float, default=0)
    args = parser.parse_args()
    cues = proposals(args.ocr, args.min_y)
    words = json.loads(args.words.read_text(encoding="utf-8-sig"))
    result = compare(cues, words)
    result["min_y"] = args.min_y
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k != "items"}))


if __name__ == "__main__":
    main()
