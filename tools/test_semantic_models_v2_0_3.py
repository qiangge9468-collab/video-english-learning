import os
import sys

from semantic_caption_segmenter import segment_words


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAT_MODEL_DIR = os.environ.get(
    "SAT_MODEL_DIR", os.path.join(PROJECT_ROOT, "models", "sat-12l-sm")
)
SAT_TOKENIZER_DIR = os.environ.get(
    "SAT_TOKENIZER_DIR", os.path.join(PROJECT_ROOT, "models", "xlm-roberta-base")
)
SPACY_MODEL = os.environ.get("SPACY_MODEL", "en_core_web_trf")


def timed_words(text):
    result = []
    cursor = 0.0
    for index, token in enumerate(text.split()):
        result.append(
            {
                "index": index,
                "segment_id": 0,
                "start": cursor,
                "end": cursor + 0.27,
                "text": token,
                "probability": 0.96,
            }
        )
        cursor += 0.31
    return result


def main():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    from wtpsplit import SaT
    import spacy

    print(f"python={sys.executable}")
    print(f"sat={SAT_MODEL_DIR}")
    print(f"tokenizer={SAT_TOKENIZER_DIR}")
    print(f"spacy={SPACY_MODEL}")

    sat = SaT(
        SAT_MODEL_DIR,
        tokenizer_name_or_path=SAT_TOKENIZER_DIR,
        from_pretrained_kwargs={"local_files_only": True},
    )
    nlp = spacy.load(SPACY_MODEL)
    text = (
        "So you get a lot of variety on the trek so for example right now "
        "we are walking alongside this beautiful river like it has jungly "
        "vibes around us and honestly it is amazing."
    )
    doc = nlp(text)
    noun_chunks = [chunk.text for chunk in doc.noun_chunks]
    segments, debug = segment_words(
        timed_words(text),
        sat_model=sat,
        spacy_nlp=nlp,
    )
    output_texts = [item["text"] for item in segments]
    print(f"noun_chunks={noun_chunks}")
    print(f"segments={output_texts}")
    print(f"fallback={debug.get('used_fallback', False)}")

    if not any("beautiful river" in item for item in output_texts):
        raise AssertionError("semantic segmenter did not preserve 'beautiful river'")
    if any(item.rstrip(".,!?").endswith("beautiful") for item in output_texts):
        raise AssertionError("semantic segmenter split between beautiful and river")
    if not any("beautiful river" in chunk for chunk in noun_chunks):
        raise AssertionError("spaCy did not identify the expected noun phrase")
    print("semantic model integration: OK")


if __name__ == "__main__":
    main()
