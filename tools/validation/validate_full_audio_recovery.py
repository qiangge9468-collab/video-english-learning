#!/usr/bin/env python3
"""Validate quality gates and speech-gap recovery against complete cached audio."""

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERSION_DIR = ROOT / "tools" / "versions" / "v2.1.0"


def load_service(data_root):
    os.environ["VIDEO_ENGLISH_DATA_DIR"] = str(data_root)
    sys.path.insert(0, str(VERSION_DIR))
    spec = importlib.util.spec_from_file_location(
        "full_audio_recovery_service", VERSION_DIR / "service.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def issue_kind(service, segment):
    repeated = service.pathological_repeated_phrase(segment.get("text", ""))
    compression = float(segment.get("compression_ratio") or 0.0)
    temperature = float(segment.get("temperature") or 0.0)
    if repeated and (
        temperature >= 0.6
        or compression >= 2.2
        or float(repeated["density"]) >= 0.18
    ):
        return "repeated_phrase_loop"
    if service.implausible_count_sequence(segment.get("text", "")):
        return "implausible_count_sequence"
    return ""


def speech_ranges(audio_path):
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    audio = decode_audio(str(audio_path), sampling_rate=16000)
    options = VadOptions(
        onset=0.35,
        offset=0.30,
        min_silence_duration_ms=250,
        speech_pad_ms=200,
    )
    chunks = get_speech_timestamps(audio, options)
    return (
        [(item["start"] / 16000.0, item["end"] / 16000.0) for item in chunks],
        len(audio) / 16000.0,
    )


def validate(service, data_root, audio_hash, video_title, model_holder):
    cache = data_root / "cache" / audio_hash
    with (cache / "whisper_segments.json").open("r", encoding="utf-8-sig") as handle:
        segments = json.load(handle)
    with (cache / "whisper_words.json").open("r", encoding="utf-8-sig") as handle:
        words = json.load(handle)
    audio_path = next((data_root / "audio").glob(f"{audio_hash}.*"))

    rejected = {
        int(segment["id"]): issue_kind(service, segment)
        for segment in segments
        if issue_kind(service, segment)
    }
    kept_segments = [
        segment for segment in segments
        if int(segment.get("id", -1)) not in rejected
    ]
    kept_words = [
        word for word in words
        if int(word.get("segment_id", -1)) not in rejected
    ]
    kept_segments, kept_words = service.rebuild_raw_transcription_artifacts(
        kept_segments, kept_words
    )
    ranges, duration = speech_ranges(audio_path)
    gaps_before = service.find_uncovered_speech_gaps(kept_words, ranges, duration)

    recovery_debug = {"recovered": [], "rejected_hallucinations": []}
    if gaps_before:
        if model_holder[0] is None:
            model_holder[0] = service.get_whisper_model(service.choose_transcription_model("en"))
        kept_segments, kept_words, recovery_debug = service.recover_uncovered_speech(
            model_holder[0],
            str(audio_path),
            kept_segments,
            kept_words,
            "en",
            video_title,
        )
    gaps_after = service.find_uncovered_speech_gaps(kept_words, ranges, duration)
    remaining_issues = [
        issue_kind(service, segment)
        for segment in kept_segments
        if issue_kind(service, segment)
    ]
    return {
        "audio_hash": audio_hash,
        "video_title": video_title,
        "audio_duration_seconds": duration,
        "vad_speech_ranges": len(ranges),
        "cached_segments": len(segments),
        "rejected_cached_segments": len(rejected),
        "rejected_kinds": list(rejected.values()),
        "recovery_candidates": len(gaps_before),
        "recovered_segments": len(recovery_debug.get("recovered") or []),
        "rejected_recovery_hallucinations": len(
            recovery_debug.get("rejected_hallucinations") or []
        ),
        "remaining_vad_candidates": len(gaps_after),
        "remaining_quality_issues": len(remaining_issues),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    parser.add_argument(
        "--video",
        action="append",
        required=True,
        help="audio_hash=video title",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    service = load_service(args.data_root)
    model_holder = [None]
    reports = []
    for item in args.video:
        audio_hash, title = item.split("=", 1)
        reports.append(
            validate(service, args.data_root, audio_hash, title, model_holder)
        )
    if model_holder[0] is not None:
        service.release_idle_models(force=True)
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    else:
        for report in reports:
            print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
