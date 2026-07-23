"""Isolated SaT + spaCy worker used by the v2.0.3 computer service."""

import argparse
import json
import os
import sys
import tempfile

from semantic_caption_segmenter import SegmenterConfig, segment_words


def read_json(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json_atomic(path, value):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix="semantic_worker_", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def config_from_dict(value):
    allowed = set(SegmenterConfig.__dataclass_fields__)
    cleaned = {key: item for key, item in dict(value or {}).items() if key in allowed}
    return SegmenterConfig(**cleaned)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sat-model", required=True)
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--spacy-model", default="en_core_web_trf")
    args = parser.parse_args()

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    from wtpsplit import SaT
    import spacy

    payload = read_json(args.input)
    sat = SaT(
        args.sat_model,
        tokenizer_name_or_path=args.tokenizer,
        from_pretrained_kwargs={"local_files_only": True},
    )
    nlp = spacy.load(args.spacy_model)
    nlp.max_length = max(int(getattr(nlp, "max_length", 1_000_000)), 2_000_000)
    segments, debug = segment_words(
        payload.get("words") or [],
        sat_model=sat,
        spacy_nlp=nlp,
        config=config_from_dict(payload.get("config")),
    )
    debug["worker_python"] = sys.executable
    debug["sat_model"] = os.path.basename(args.sat_model.rstrip("\\/"))
    debug["spacy_model"] = args.spacy_model
    debug["semantic_device"] = "cpu"
    write_json_atomic(args.output, {"segments": segments, "debug": debug})


if __name__ == "__main__":
    main()
