"""Complete-cohort learning sentence / translation experiment, isolated outputs.

Requires full alignment artifacts. Never writes into the live service or caches.
Run segment with SaT/spaCy Python, translate with the GPU translation Python.
"""
import argparse
from collections import Counter
import json
import hashlib
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"tools/versions/v2.1.0"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--phase", choices=("segment", "translate"), default="segment")
    parser.add_argument("--learning-threshold", type=float, default=.75)
    parser.add_argument("--soft-dependencies", action="store_true")
    parser.add_argument("--punctuation-root", type=Path)
    parser.add_argument("--punctuation-threshold", type=float, default=.8)
    parser.add_argument("--speaker-root", type=Path)
    args = parser.parse_args()
    if not 0 <= args.learning_threshold <= 1:
        parser.error("learning threshold must be between zero and one")
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    torch.set_num_threads(4)
    if args.phase == "segment":
        from wtpsplit import SaT
        import spacy
        from semantic_caption_segmenter_v206 import SegmenterConfig, segment_words, normalize_words, analyze_boundaries, learning_sentences
        sat = SaT(str(args.project/"models/sat-12l-sm"), tokenizer_name_or_path=str(args.project/"models/xlm-roberta-base"),
                  from_pretrained_kwargs={"local_files_only": True})
        nlp = spacy.load("en_core_web_trf")
    else:
        os.environ.update(VIDEO_ENGLISH_DATA_DIR=str(args.output/"isolated-service"),
                          WHISPER_RUNTIME_CONFIG=str(args.output/"config.json"),
                          WHISPER_RUNTIME_STATUS=str(args.output/"status.json"),
                          TRANSLATION_MODEL=str(args.project/"models/nllb-200-distilled-600M"),
                          TRANSLATION_DEVICE="cuda", TRANSLATION_PROVIDER="transformers",
                          TRANSLATION_STYLE="generic",
                          TRANSLATION_LOCAL_FILES_ONLY="1", TRANSLATION_BATCH_SIZE="8")
        import service
    reports = []
    for item in json.loads(args.manifest.read_text(encoding="utf-8")):
        started = time.monotonic()
        target = args.output/item["name"]
        target.mkdir(exist_ok=True)
        destination = target/("learning.json" if args.phase == "segment" else "bilingual.json")
        if destination.exists():
            raise FileExistsError("Refusing to replace an earlier run")
        print(f'START {args.phase} {item["name"]}', flush=True)
        if args.phase == "segment":
            source = json.loads((args.input/item["name"]/"alignment.json").read_text(encoding="utf-8"))
            config = SegmenterConfig(
                learning_sentence_mode=True, learning_boundary_probability=args.learning_threshold,
                learning_soft_dependency_boundaries=args.soft_dependencies)
            if args.punctuation_root or args.speaker_root:
                from dataclasses import replace
                path = args.input/item['name']/'alignment.json'
                original = normalize_words(source['words'])
                analysis = original
                if args.punctuation_root:
                    from run_punctuation_experiment import analysis_words
                    evidence = json.loads((args.punctuation_root/item['name']/'punctuation.json').read_text(encoding='utf-8'))
                    if evidence['input_sha256'] != hashlib.sha256(path.read_bytes()).hexdigest():
                        raise ValueError('Wrong punctuation input provenance')
                    analysis = analysis_words(original,evidence['predictions'],args.punctuation_threshold)
                    config = replace(config,learning_punctuation_threshold=args.punctuation_threshold)
                features = analyze_boundaries(analysis,sat,nlp,config)
                original_features = analyze_boundaries(original,config=config)
                for index in range(1,len(original)):
                    # Preserve ASR punctuation separately from inferred endings.
                    features[index].punctuation = original_features[index].punctuation
                    if args.punctuation_root:
                        features[index].restored_terminal_probability = evidence['predictions'][index-1]['terminal_probability']
                if args.speaker_root:
                    speaker = json.loads((args.speaker_root/(item['name']+'.json')).read_text(encoding='utf-8'))
                    if speaker['alignment_sha256'] != hashlib.sha256(path.read_bytes()).hexdigest():
                        raise ValueError('Wrong speaker input provenance')
                    if len(original) != len(source['words']):
                        raise ValueError('Speaker index projection requires unchanged word count')
                    config = replace(config,learning_speaker_boundaries=True)
                    from semantic_caption_segmenter_v206 import apply_speaker_evidence
                    rejected_speaker_boundaries = apply_speaker_evidence(original, features, speaker, config)
                result,debug = learning_sentences(original,features,config)
                debug['analysis_text_punctuation_restored'] = bool(args.punctuation_root)
                if args.punctuation_root:
                    debug['punctuation_input_sha256'] = evidence['input_sha256']
                if args.speaker_root:
                    debug['speaker_alignment_sha256'] = speaker['alignment_sha256']
                    debug['speaker_rejected_without_semantic_support'] = rejected_speaker_boundaries
            else:
                result, debug = segment_words(source["words"], sat, nlp, config)
            (target/"debug.json").write_text(json.dumps(debug), encoding="utf-8")
            report = {"input_words": len(source["words"]), "learning_sentences": len(result),
                      "display_cues": sum(len(s["display_cues"]) for s in result), "warnings": debug.get("warnings", []),
                      "learning_threshold": args.learning_threshold, "soft_dependencies": args.soft_dependencies}
            if result and (result[0]["word_start"] != 0 or result[-1]["word_end"] != len(source["words"]) or
                           any(a["word_end"] != b["word_start"] for a,b in zip(result, result[1:]))):
                raise RuntimeError("Nonconserving segmentation")
        else:
            source = json.loads((args.input/item["name"]/"learning.json").read_text(encoding="utf-8"))
            result = service.translate_segments(source)
            report = {"learning_sentences": len(source), "nonempty_translation": sum(bool(s.get("translation")) for s in result),
                      "translation_status_counts": dict(Counter(s.get("translation_status", "missing") for s in result)),
                      "translation_accuracy": None}
        destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        reports.append({"name": item["name"], **report, "elapsed_seconds": time.monotonic()-started,
                        "scope": "complete_cached_transcript", "accuracy": None, "release_allowed": False})
        (args.output/"summary.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
        print(json.dumps(reports[-1]), flush=True)


if __name__ == "__main__":
    main()
