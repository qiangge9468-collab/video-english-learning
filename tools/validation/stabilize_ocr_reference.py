"""Independent multi-frame OCR triage. Never converts display timing to speech timing.

Only join contiguous groups whose every reading is a contiguous portion of the
same repeatedly observed full caption. Keep raw groups, variants and provenance.
No ASR text, word times, translations or desired accuracy enter this operation.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from compare_ocr_proposals import proposals, tokens


def is_part(part, whole):
    return bool(part) and any(whole[i:i+len(part)] == part for i in range(len(whole)-len(part)+1))


def canonical(group, minimum_observations=2):
    variants = Counter()
    for cue in group:
        variants.update(cue.get("variants", {cue["text"]: cue["observations"]}))
    if not variants:
        return None
    # Do not chain A -> a shared short line -> unrelated B.
    candidate = max(variants, key=lambda text: (len(tokens(text)), variants[text]))
    full = tokens(candidate)
    if sum(n for text, n in variants.items() if tokens(text) == full) < minimum_observations:
        return None
    if any(not is_part(tokens(text), full) or len(tokens(text)) < 4 for text in variants):
        return None
    if not any(len(tokens(text)) < len(full) for text in variants):
        return None
    return candidate


def stabilize(cues, max_duration=12.0, frame_tolerance=.001):
    groups, start = [], 0
    while start < len(cues):
        best = start+1
        for end in range(start+1, len(cues)):
            # The sampler selects real frames, so .5 s sampling can become
            # .52 s on a 25 fps source. Permit at most one frame, not a blank.
            gap = cues[end]["start"] - cues[end-1]["end"]
            if not -.001 <= gap <= frame_tolerance+.001 or cues[end]["end"]-cues[start]["start"] > max_duration:
                break
            if canonical(cues[start:end+1]):
                best = end+1
        groups.append(cues[start:best])
        start = best
    result = []
    for group in groups:
        variants = Counter()
        for cue in group:
            variants.update(cue.get("variants", {cue["text"]: cue["observations"]}))
        result.append({"id": len(result), "start": group[0]["start"], "end": group[-1]["end"],
                       "text": canonical(group) if len(group) > 1 else group[0]["text"],
                       "observations": sum(c["observations"] for c in group),
                       "variants": dict(variants), "raw_ids": [c["id"] for c in group],
                       "reviewed": False, "speech_timing": None,
                       "status": "partial_line_consensus_unreviewed" if len(group)>1 else "raw_unreviewed"})
    return result


def audit(folder, min_y=0):
    raw = proposals(folder, min_y)
    source = json.loads((folder/"source.json").read_text(encoding="utf-8"))
    frame_tolerance = min(.1, 1/max(1, source.get("fps", 25)))
    stable = stabilize(raw, frame_tolerance=frame_tolerance)
    paths = [folder/"source.json", folder/"samples.jsonl"]
    return {"policy": "ocr-partial-line-consensus-v1", "release_allowed": False,
            "accuracy": None, "min_y": min_y,
            "frame_tolerance": frame_tolerance,
            "input_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
            "raw_count": len(raw), "stable_count": len(stable),
            "merged_groups": sum(len(g["raw_ids"])>1 for g in stable),
            "observations_before": sum(g["observations"] for g in raw),
            "observations_after": sum(g["observations"] for g in stable),
            "raw": raw, "stable": stable}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ocr", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--min-y", type=float, default=0)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Preserve earlier reference evidence")
    result = audit(args.ocr, args.min_y)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in ("raw", "stable")}))


if __name__ == "__main__":
    main()
