"""Isolated WhisperX forced-alignment worker for computer service v2.1.0."""

import argparse
import json
import os
import sys
import tempfile


def read_json(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json_atomic(path, value):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix="whisperx_worker_", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--language", default="en")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--quality-guard", action="store_true",
                        help="Experimental lossless alignment with explicit unresolved diagnostics")
    args = parser.parse_args()

    os.makedirs(args.model_dir, exist_ok=True)
    # Directly invoking a Conda environment's python.exe does not activate its
    # PATH. WhisperX launches ffmpeg by name, so expose only this isolated
    # environment's binary directories to the worker process.
    environment_bins = [os.path.join(sys.prefix, "Library", "bin"), os.path.join(sys.prefix, "Scripts")]
    existing_path = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join(environment_bins + [existing_path])
    os.environ.setdefault("TORCH_HOME", args.model_dir)
    os.environ.setdefault("HF_HOME", args.model_dir)

    import whisperx

    payload = read_json(args.input)
    source_segments = payload.get("segments") or []
    transcript = [
        {
            "start": float(segment["start"]),
            "end": float(segment["end"]),
            "text": str(segment.get("text", "")).strip(),
        }
        for segment in source_segments
        if str(segment.get("text", "")).strip()
    ]
    audio = whisperx.load_audio(args.audio)
    model_a, metadata = whisperx.load_align_model(
        language_code=args.language,
        device=args.device,
        model_dir=args.model_dir,
    )
    if args.quality_guard:
        from guarded_alignment import align_guarded

        def align_one(segment):
            aligned = whisperx.align([segment], model_a, metadata, audio, args.device,
                                     interpolate_method="ignore", return_char_alignments=False)
            return [word for part in aligned.get("segments", []) for word in part.get("words", [])]

        segments, words, debug = align_guarded(source_segments, payload.get("words", []),
                                               align_one, len(audio)/16000)
        debug.update(language=args.language, device=args.device)
        if not words:
            raise RuntimeError("WhisperX returned no source words")
        write_json_atomic(args.output, {"segments": segments, "words": words, "debug": debug})
        return
    aligned = whisperx.align(
        transcript,
        model_a,
        metadata,
        audio,
        args.device,
        interpolate_method="nearest",
        return_char_alignments=False,
    )

    segments = []
    words = []
    source_index = 0
    for aligned_segment in aligned.get("segments") or []:
        while (
            source_index + 1 < len(source_segments)
            and float(source_segments[source_index]["end"]) <= float(aligned_segment.get("start", 0.0))
        ):
            source_index += 1
        source = source_segments[source_index] if source_segments else {}
        segment_words = []
        for word in aligned_segment.get("words") or []:
            if word.get("start") is None or word.get("end") is None:
                continue
            text = " ".join(str(word.get("word", "")).split())
            if not text:
                continue
            item = {
                "index": len(words),
                "segment_id": len(segments),
                "start": float(word["start"]),
                "end": float(word["end"]),
                "text": text,
                "probability": (
                    float(word["score"]) if word.get("score") is not None else None
                ),
                "aligned_by": "whisperx",
            }
            segment_words.append(item)
            words.append(item)
        if not segment_words:
            continue
        segments.append({
            "id": len(segments),
            "start": float(segment_words[0]["start"]),
            "end": float(segment_words[-1]["end"]),
            "text": " ".join(str(aligned_segment.get("text", "")).split()),
            "avg_logprob": source.get("avg_logprob"),
            "no_speech_prob": source.get("no_speech_prob"),
            "compression_ratio": source.get("compression_ratio"),
            "temperature": source.get("temperature"),
            "word_start": segment_words[0]["index"],
            "word_end": segment_words[-1]["index"] + 1,
            "translation": "",
            "aligned_by": "whisperx",
        })

    if not segments or not words:
        raise RuntimeError("WhisperX returned no aligned words")
    write_json_atomic(
        args.output,
        {
            "segments": segments,
            "words": words,
            "debug": {
                "alignment": "whisperx",
                "language": args.language,
                "device": args.device,
                "segment_count": len(segments),
                "word_count": len(words),
            },
        },
    )


if __name__ == "__main__":
    main()
