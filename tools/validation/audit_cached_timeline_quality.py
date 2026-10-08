#!/usr/bin/env python3
"""Run v2.1.0 quality gates over complete cached subtitle timelines."""

import argparse
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERSION_DIR = ROOT / "tools" / "versions" / "v2.1.0"


def load_service():
    sys.path.insert(0, str(VERSION_DIR))
    spec = importlib.util.spec_from_file_location(
        "timeline_audit_service", VERSION_DIR / "service.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def describe_issue(service, segment):
    repeated = service.pathological_repeated_phrase(segment.get("text", ""))
    compression = float(segment.get("compression_ratio") or 0.0)
    temperature = float(segment.get("temperature") or 0.0)
    repetition_loop = bool(
        repeated
        and (
            temperature >= 0.6
            or compression >= 2.2
            or float(repeated["density"]) >= 0.18
        )
    )
    if repetition_loop:
        return {
            "kind": "repeated_phrase_loop",
            "detail": repeated,
        }
    if service.implausible_count_sequence(segment.get("text", "")):
        return {
            "kind": "implausible_count_sequence",
            "detail": None,
        }
    start = float(segment.get("start", 0.0))
    end = float(segment.get("end", start))
    if end <= start:
        return {
            "kind": "non_positive_duration",
            "detail": None,
        }
    return None


def audit(cache_root, audio_hash):
    path = cache_root / audio_hash / "whisper_segments.json"
    with path.open("r", encoding="utf-8-sig") as handle:
        segments = json.load(handle)
    service = load_service()
    issues = []
    for segment in segments:
        issue = describe_issue(service, segment)
        if issue:
            issues.append({
                "start": float(segment.get("start", 0.0)),
                "end": float(segment.get("end", 0.0)),
                "kind": issue["kind"],
                "detail": issue["detail"],
                "text": str(segment.get("text", ""))[:300],
            })
    final_path = cache_root / audio_hash / "english.json"
    final_issues = None
    if final_path.is_file():
        with final_path.open("r", encoding="utf-8-sig") as handle:
            final_segments = json.load(handle)
        final_issues = [
            {"index": index, **issue}
            for index, segment in enumerate(final_segments)
            if (issue := describe_issue(service, segment)) is not None
        ]
    return {
        "audio_hash": audio_hash,
        "segment_count": len(segments),
        "timeline_end_seconds": max(
            (float(segment.get("end", 0.0)) for segment in segments),
            default=0.0,
        ),
        "issues_before_quality_gates": issues,
        "issues_after_quality_gates": len(final_issues) if final_issues is not None else None,
        "final_caption_issues": final_issues,
        "reference_timing_evaluated": False,
        "translation_evaluated": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cache_root", type=Path)
    parser.add_argument("audio_hash", nargs="+")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    reports = [audit(args.cache_root, audio_hash) for audio_hash in args.audio_hash]
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
        return
    for report in reports:
        print(
            f"{report['audio_hash']}: {report['timeline_end_seconds']:.2f}s, "
            f"{report['segment_count']} segments, "
            f"{len(report['issues_before_quality_gates'])} rejected issue(s), "
            f"{report['issues_after_quality_gates']} remaining"
        )
        for issue in report["issues_before_quality_gates"]:
            print(
                f"  {issue['start']:.2f}-{issue['end']:.2f} "
                f"{issue['kind']}: {issue['text']}"
            )


if __name__ == "__main__":
    main()
