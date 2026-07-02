from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import threading
from urllib.parse import parse_qs, urlparse

VIDEO_PATHS = {
    "backpacking": r"C:\Users\ASUS\Downloads\Full Gear List for Solo Backpacking.mp4",
}

SENTENCE_END_RE = re.compile(r"[.!?][\"')\]]*$")
MAX_SENTENCE_SECONDS = 14.0
MAX_SENTENCE_CHARS = 180
START_PADDING_SECONDS = 0.03
END_PADDING_SECONDS = 0.22
MIN_GAP_SECONDS = 0.03
TRANSLATION_BATCH_SIZE = 8
TRANSLATION_PROVIDER = os.environ.get("TRANSLATION_PROVIDER", "auto").strip().lower()
TRANSLATION_MODEL = os.environ.get("TRANSLATION_MODEL", "Helsinki-NLP/opus-mt-en-zh")

_translator_lock = threading.Lock()
_translator = None


class TranscribeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/ping":
            self.send_text("ok")
            return

        if parsed.path != "/transcribe":
            self.send_json({"error": "not found"}, status=404)
            return

        query = parse_qs(parsed.query)
        video_key = query.get("video", ["backpacking"])[0]
        video_path = VIDEO_PATHS.get(video_key)
        if not video_path or not os.path.exists(video_path):
            self.send_json({"error": f"video not found: {video_key}"}, status=404)
            return

        try:
            segments = transcribe(video_path)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)
            return

        self.send_json(segments)

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text, status=200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))


def transcribe(video_path):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Run: python -m pip install faster-whisper"
        ) from exc

    model_name = os.environ.get("WHISPER_MODEL", "tiny.en")
    device = os.environ.get("WHISPER_DEVICE", "cpu")
    compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
    print(f"Loading Whisper model {model_name} on {device}/{compute_type}...")
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    print(f"Transcribing {video_path}...")
    segments, _info = model.transcribe(
        video_path,
        language="en",
        beam_size=5,
        vad_filter=True,
        word_timestamps=True,
    )
    raw_segments = []
    raw_words = []
    for segment in segments:
        text = " ".join(segment.text.strip().split())
        words = getattr(segment, "words", None) or []
        for word in words:
            word_text = " ".join(word.word.strip().split())
            if word_text:
                raw_words.append(
                    {
                        "start": float(word.start),
                        "end": float(word.end),
                        "text": word_text,
                    }
                )
        if text:
            raw_segments.append(
                {
                    "start": float(segment.start),
                    "end": float(segment.end),
                    "text": text,
                    "translation": "",
                }
            )
    result = words_to_sentence_segments(raw_words) if raw_words else merge_sentence_segments(raw_segments)
    result = add_sentence_timing_padding(result)
    result = translate_segments(result)
    print(f"Generated {len(result)} segments.")
    return result


def translate_segments(segments):
    if not segments or TRANSLATION_PROVIDER in ("", "none", "off"):
        return segments

    translator = get_translator()
    if translator is None:
        print("No local English-to-Chinese translator is available. Returning English captions only.")
        return segments

    translated = []
    texts = [segment["text"] for segment in segments]
    for start in range(0, len(texts), TRANSLATION_BATCH_SIZE):
        batch = texts[start : start + TRANSLATION_BATCH_SIZE]
        translations = translator(batch)
        for offset, translation in enumerate(translations):
            segment = dict(segments[start + offset])
            segment["translation"] = translation
            translated.append(segment)
    return translated


def get_translator():
    global _translator
    with _translator_lock:
        if _translator is not None:
            return _translator
        _translator = build_translator()
        return _translator


def build_translator():
    if TRANSLATION_PROVIDER in ("auto", "argos"):
        translator = build_argos_translator()
        if translator is not None or TRANSLATION_PROVIDER == "argos":
            return translator

    if TRANSLATION_PROVIDER in ("auto", "transformers", "hf"):
        translator = build_transformers_translator()
        if translator is not None or TRANSLATION_PROVIDER in ("transformers", "hf"):
            return translator

    return None


def build_argos_translator():
    try:
        import argostranslate.translate
    except ImportError:
        return None

    installed_languages = argostranslate.translate.get_installed_languages()
    from_language = next((language for language in installed_languages if language.code == "en"), None)
    to_language = next((language for language in installed_languages if language.code in ("zh", "zt", "zh_cn")), None)
    if from_language is None or to_language is None:
        print("Argos Translate is installed, but the en->zh package is not installed.")
        return None

    translation = from_language.get_translation(to_language)

    def translate_batch(texts):
        return [translation.translate(text).strip() for text in texts]

    print("Using Argos Translate for English-to-Chinese subtitles.")
    return translate_batch


def build_transformers_translator():
    try:
        from transformers import MarianMTModel, MarianTokenizer
    except ImportError:
        return None

    print(f"Loading translation model {TRANSLATION_MODEL}...")
    tokenizer = MarianTokenizer.from_pretrained(TRANSLATION_MODEL)
    model = MarianMTModel.from_pretrained(TRANSLATION_MODEL)

    def translate_batch(texts):
        encoded = tokenizer(texts, return_tensors="pt", padding=True, truncation=True, max_length=512)
        generated = model.generate(**encoded, max_length=512, num_beams=4)
        return [text.strip() for text in tokenizer.batch_decode(generated, skip_special_tokens=True)]

    print(f"Using Transformers model {TRANSLATION_MODEL} for English-to-Chinese subtitles.")
    return translate_batch


def words_to_sentence_segments(words):
    result = []
    current_words = []
    current_start = None

    for word in words:
        text = word["text"].strip()
        if not text:
            continue

        if current_start is None:
            current_start = word["start"]
        current_words.append(word)

        sentence_text = words_to_text(current_words)
        duration = word["end"] - current_start
        if is_sentence_complete(text) or should_force_word_break(sentence_text, duration):
            result.append(
                {
                    "start": current_start,
                    "end": word["end"],
                    "text": sentence_text,
                    "translation": "",
                }
            )
            current_words = []
            current_start = None

    if current_words and current_start is not None:
        result.append(
            {
                "start": current_start,
                "end": current_words[-1]["end"],
                "text": words_to_text(current_words),
                "translation": "",
            }
        )

    return result


def words_to_text(words):
    text = " ".join(word["text"].strip() for word in words if word["text"].strip())
    text = re.sub(r"\s+([,.!?;:%])", r"\1", text)
    text = re.sub(r"\s+(['’]s\b)", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+n't\b", "n't", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def should_force_word_break(text, duration):
    if is_sentence_complete(text):
        return True
    return duration >= MAX_SENTENCE_SECONDS or len(text) >= MAX_SENTENCE_CHARS


def merge_sentence_segments(raw_segments):
    result = []
    current = None

    for segment in raw_segments:
        text = segment["text"].strip()
        if not text:
            continue

        if current is None:
            current = {
                "start": segment["start"],
                "end": segment["end"],
                "text": text,
                "translation": "",
            }
        else:
            current["end"] = segment["end"]
            current["text"] = join_text(current["text"], text)

        duration = current["end"] - current["start"]
        if is_sentence_complete(current["text"]) or duration >= MAX_SENTENCE_SECONDS or len(current["text"]) >= MAX_SENTENCE_CHARS:
            result.append(clean_caption(current))
            current = None

    if current is not None:
        result.append(clean_caption(current))

    return split_overlong_captions(result)


def is_sentence_complete(text):
    return bool(SENTENCE_END_RE.search(text.strip()))


def join_text(left, right):
    if not left:
        return right
    if not right:
        return left
    return f"{left.rstrip()} {right.lstrip()}"


def clean_caption(segment):
    return {
        "start": segment["start"],
        "end": segment["end"],
        "text": " ".join(segment["text"].split()),
        "translation": segment.get("translation", ""),
    }


def split_overlong_captions(segments):
    result = []
    for segment in segments:
        text = segment["text"]
        if len(text) <= MAX_SENTENCE_CHARS:
            result.append(segment)
            continue

        parts = split_text_at_soft_boundaries(text)
        if len(parts) <= 1:
            result.append(segment)
            continue

        total_chars = sum(len(part) for part in parts)
        start = segment["start"]
        duration = segment["end"] - segment["start"]
        elapsed_chars = 0
        for part in parts:
            part_start = start + duration * (elapsed_chars / total_chars)
            elapsed_chars += len(part)
            part_end = start + duration * (elapsed_chars / total_chars)
            result.append(
                {
                    "start": part_start,
                    "end": part_end,
                    "text": part,
                    "translation": "",
                }
            )
    return result


def split_text_at_soft_boundaries(text):
    chunks = []
    current = ""
    for piece in re.split(r"(?<=[,;:])\s+", text):
        candidate = piece if not current else f"{current} {piece}"
        if len(candidate) <= MAX_SENTENCE_CHARS:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return chunks


def add_sentence_timing_padding(segments):
    if not segments:
        return []

    adjusted = []
    for index, segment in enumerate(segments):
        next_segment = segments[index + 1] if index + 1 < len(segments) else None
        start = max(0.0, float(segment["start"]) - START_PADDING_SECONDS)
        end = float(segment["end"])
        padded_end = end + END_PADDING_SECONDS

        if next_segment is not None:
            next_start = float(next_segment["start"])
            if next_start > end + MIN_GAP_SECONDS:
                padded_end = min(padded_end, next_start - MIN_GAP_SECONDS)
            else:
                padded_end = end

        adjusted.append(
            {
                "start": start,
                "end": max(padded_end, start + 0.2),
                "text": segment["text"],
                "translation": segment.get("translation", ""),
            }
        )

    return adjusted


def main():
    server = ThreadingHTTPServer(("0.0.0.0", 8765), TranscribeHandler)
    print("Local Whisper service running at http://0.0.0.0:8765")
    print("Ping endpoint: http://<your-computer-lan-ip>:8765/ping")
    print("Phone endpoint: http://<your-computer-lan-ip>:8765/transcribe?video=backpacking")
    print("Emulator endpoint: http://10.0.2.2:8765/transcribe?video=backpacking")
    server.serve_forever()


if __name__ == "__main__":
    main()
