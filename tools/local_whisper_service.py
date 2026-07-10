from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import tempfile
import threading
import time
import uuid
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
MAX_UPLOAD_MB = int(os.environ.get("WHISPER_MAX_UPLOAD_MB", "2048"))
AUTH_TOKEN = os.environ.get("WHISPER_AUTH_TOKEN", "").strip()
TRANSLATION_PROVIDER = os.environ.get("TRANSLATION_PROVIDER", "auto").strip().lower()
TRANSLATION_MODEL = os.environ.get("TRANSLATION_MODEL", "Helsinki-NLP/opus-mt-en-zh")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
LOCAL_EN_SMALL_MODEL_DIR = os.path.join(MODELS_DIR, "faster-whisper-small")
LOCAL_EN_MEDIUM_MODEL_DIR = os.path.join(MODELS_DIR, "faster-whisper-medium")
LOCAL_MULTI_MEDIUM_MODEL_DIR = os.path.join(MODELS_DIR, "faster-whisper-medium（Multilingual model）")

_translator_lock = threading.Lock()
_translator = None
_model_lock = threading.Lock()
_models = {}
_jobs_lock = threading.Lock()
_jobs = {}


class TranscribeHandler(BaseHTTPRequestHandler):
    server_version = "VideoEnglishWhisper/0.2"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/ping":
            if not self.authorized(parsed):
                self.send_json({"error": "unauthorized"}, status=401)
                return
            self.send_text("ok")
            return

        if parsed.path == "/models":
            if not self.authorized(parsed):
                self.send_json({"error": "unauthorized"}, status=401)
                return
            self.send_json(model_status())
            return

        if parsed.path.startswith("/jobs/"):
            if not self.authorized(parsed):
                self.send_json({"error": "unauthorized"}, status=401)
                return
            job_id = parsed.path.rsplit("/", 1)[-1]
            job = get_job(job_id)
            if job is None:
                self.send_json({"error": "job not found"}, status=404)
            else:
                self.send_json(job)
            return

        if parsed.path != "/transcribe":
            self.send_json({"error": "not found"}, status=404)
            return

        if not self.authorized(parsed):
            self.send_json({"error": "unauthorized"}, status=401)
            return

        query = parse_qs(parsed.query)
        video_key = query.get("video", ["backpacking"])[0]
        video_path = VIDEO_PATHS.get(video_key)
        if not video_path or not os.path.exists(video_path):
            self.send_json({"error": f"video not found: {video_key}"}, status=404)
            return

        self.transcribe_and_send(video_path)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path not in ("/transcribe", "/jobs"):
            self.send_json({"error": "not found"}, status=404)
            return

        if not self.authorized(parsed):
            self.send_json({"error": "unauthorized"}, status=401)
            return

        content_length = int(self.headers.get("Content-Length", "0") or "0")
        is_chunked = self.headers.get("Transfer-Encoding", "").lower() == "chunked"
        if content_length <= 0 and not is_chunked:
            self.send_json({"error": "empty upload"}, status=400)
            return
        if content_length > MAX_UPLOAD_MB * 1024 * 1024:
            self.send_json({"error": f"upload is larger than {MAX_UPLOAD_MB} MB"}, status=413)
            return

        try:
            video_path = self.save_upload(content_length, is_chunked)
        except Exception as exc:
            self.send_json({"error": f"could not read upload: {exc}"}, status=400)
            return

        if parsed.path == "/jobs":
            job_id = create_job(video_path)
            self.send_json({"job_id": job_id})
            return

        try:
            self.transcribe_and_send(video_path)
        finally:
            try:
                os.remove(video_path)
            except OSError:
                pass

    def authorized(self, parsed):
        if not AUTH_TOKEN:
            return True
        header = self.headers.get("Authorization", "")
        if header == f"Bearer {AUTH_TOKEN}":
            return True
        query_token = parse_qs(parsed.query).get("token", [""])[0]
        return query_token == AUTH_TOKEN

    def save_upload(self, content_length, is_chunked):
        content_type = self.headers.get("Content-Type", "")
        extension = guess_extension(content_type)
        if is_chunked:
            return write_chunked_temp_upload(self.rfile, extension)
        return write_temp_upload(self.rfile, extension, content_length)

    def transcribe_and_send(self, video_path):
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


def guess_extension(content_type):
    if "mp4" in content_type or "aac" in content_type:
        return ".m4a"
    if "webm" in content_type:
        return ".webm"
    if "quicktime" in content_type or "mov" in content_type:
        return ".mov"
    if "mpeg" in content_type:
        return ".mp3"
    if "wav" in content_type:
        return ".wav"
    return ".mp4"


def write_temp_upload(source, suffix, content_length):
    fd, path = tempfile.mkstemp(prefix="video_english_upload_", suffix=suffix)
    remaining = content_length
    with os.fdopen(fd, "wb") as output:
        while remaining > 0:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            output.write(chunk)
            remaining -= len(chunk)
    return path


def write_chunked_temp_upload(source, suffix):
    fd, path = tempfile.mkstemp(prefix="video_english_upload_", suffix=suffix)
    total = 0
    limit = MAX_UPLOAD_MB * 1024 * 1024
    with os.fdopen(fd, "wb") as output:
        while True:
            size_line = source.readline().strip()
            if not size_line:
                continue
            chunk_size = int(size_line.split(b";", 1)[0], 16)
            if chunk_size == 0:
                source.readline()
                break
            total += chunk_size
            if total > limit:
                raise ValueError(f"upload is larger than {MAX_UPLOAD_MB} MB")
            output.write(source.read(chunk_size))
            source.read(2)
    return path


def create_job(video_path):
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {
            "id": job_id,
            "status": "queued",
            "stage": "queued",
            "progress": 0,
            "message": "Queued",
            "result": None,
            "error": None,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
    thread = threading.Thread(target=run_job, args=(job_id, video_path), daemon=True)
    thread.start()
    return job_id


def get_job(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job is not None else None


def update_job(job_id, **changes):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.update(changes)
        job["updated_at"] = time.time()


def run_job(job_id, video_path):
    try:
        update_job(job_id, status="running", stage="starting", progress=1, message="Preparing uploaded file")

        def progress(stage, percent, message):
            update_job(job_id, status="running", stage=stage, progress=percent, message=message)

        result = transcribe(video_path, progress)
        update_job(
            job_id,
            status="done",
            stage="done",
            progress=100,
            message=f"Generated {len(result)} subtitles",
            result=result,
        )
    except Exception as exc:
        update_job(job_id, status="error", stage="error", progress=100, message=str(exc), error=str(exc))
    finally:
        try:
            os.remove(video_path)
        except OSError:
            pass


def transcribe(video_path, progress=None):
    report(progress, "detecting", 3, "Detecting language")
    language = detect_language(video_path, progress)
    model_name = choose_transcription_model(language)
    report(progress, "loading", 10, f"Loading model for {language or 'unknown'}")
    model = get_whisper_model(model_name)
    print(f"Transcribing {video_path} with {model_name}; detected language={language or 'unknown'}...")
    report(progress, "transcribing", 12, "Generating subtitles")
    segments, info = model.transcribe(
        video_path,
        language=language if language else None,
        beam_size=5,
        vad_filter=True,
        word_timestamps=True,
        condition_on_previous_text=True,
        temperature=0.0,
    )
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    raw_segments = []
    raw_words = []
    for segment in segments:
        text = " ".join(segment.text.strip().split())
        if duration > 0:
            percent = 12 + int(min(1.0, max(0.0, float(segment.end) / duration)) * 74)
            report(progress, "transcribing", percent, f"Transcribing {format_seconds(segment.end)} / {format_seconds(duration)}")
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
    report(progress, "postprocessing", 88, "Post-processing subtitle timing")
    result = words_to_sentence_segments(raw_words) if raw_words else merge_sentence_segments(raw_segments)
    result = merge_short_incomplete_segments(result)
    result = add_sentence_timing_padding(result)
    report(progress, "translating", 92, "Translating English subtitles")
    result = translate_segments(result, language)
    print(f"Generated {len(result)} segments.")
    return result


def report(callback, stage, percent, message):
    if callback is not None:
        callback(stage, int(max(0, min(100, percent))), message)


def display_model_name(model_name):
    return os.path.basename(model_name) if os.path.exists(model_name) else model_name


def format_seconds(seconds):
    total = int(max(0, seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def detect_language(video_path, progress=None):
    detector_name = choose_language_detector_model()
    report(progress, "detecting", 4, f"Loading language detector: {display_model_name(detector_name)}")
    detector = get_whisper_model(detector_name)
    print(f"Detecting language with {detector_name}...")
    report(progress, "detecting", 6, "Running language detection")
    _segments, info = detector.transcribe(
        video_path,
        beam_size=1,
        vad_filter=True,
        word_timestamps=False,
        temperature=0.0,
    )
    language = getattr(info, "language", None)
    probability = getattr(info, "language_probability", None)
    if language:
        print(f"Detected language={language}, probability={probability}")
    return language


def choose_language_detector_model():
    if model_dir_exists(LOCAL_EN_SMALL_MODEL_DIR):
        return LOCAL_EN_SMALL_MODEL_DIR
    if model_dir_exists(LOCAL_MULTI_MEDIUM_MODEL_DIR):
        return LOCAL_MULTI_MEDIUM_MODEL_DIR
    multilingual = find_model_dir("faster-whisper-medium", "multi")
    if multilingual:
        return multilingual
    return choose_transcription_model("en")


def choose_transcription_model(language):
    if language == "en":
        preference = os.environ.get("WHISPER_ENGLISH_MODEL", "small").strip().lower()
        english_models = {
            "small": LOCAL_EN_SMALL_MODEL_DIR,
            "medium": LOCAL_EN_MEDIUM_MODEL_DIR,
        }
        preferred_model = english_models.get(preference)
        if preferred_model and model_dir_exists(preferred_model):
            return preferred_model
        fallback_order = (
            (LOCAL_EN_MEDIUM_MODEL_DIR, LOCAL_EN_SMALL_MODEL_DIR)
            if preference == "medium"
            else (LOCAL_EN_SMALL_MODEL_DIR, LOCAL_EN_MEDIUM_MODEL_DIR)
        )
        for model_dir in fallback_order:
            if model_dir_exists(model_dir):
                return model_dir
        return "small.en"

    if model_dir_exists(LOCAL_MULTI_MEDIUM_MODEL_DIR):
        return LOCAL_MULTI_MEDIUM_MODEL_DIR
    multilingual = find_model_dir("faster-whisper-medium", "multi")
    if multilingual:
        return multilingual
    return choose_transcription_model("en")


def find_model_dir(*needles):
    if not os.path.isdir(MODELS_DIR):
        return None
    normalized_needles = [needle.lower() for needle in needles]
    for name in os.listdir(MODELS_DIR):
        path = os.path.join(MODELS_DIR, name)
        if not os.path.isdir(path) or not model_dir_exists(path):
            continue
        lower_name = name.lower()
        if all(needle in lower_name for needle in normalized_needles):
            return path
    return None


def model_dir_exists(path):
    return os.path.exists(os.path.join(path, "model.bin"))


def model_status():
    return {
        "detector": choose_language_detector_model(),
        "english": choose_transcription_model("en"),
        "other": choose_transcription_model("zh"),
        "paths": {
            "english_medium": LOCAL_EN_MEDIUM_MODEL_DIR,
            "english_small": LOCAL_EN_SMALL_MODEL_DIR,
            "multilingual_medium": LOCAL_MULTI_MEDIUM_MODEL_DIR,
        },
    }


def get_whisper_model(model_name=None):
    with _model_lock:
        if model_name is None:
            model_name = os.environ.get("WHISPER_MODEL", default_whisper_model())
        if model_name in _models:
            return _models[model_name]

        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper is not installed. Run: python -m pip install faster-whisper"
            ) from exc

        device = os.environ.get("WHISPER_DEVICE", "cpu")
        compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
        print(f"Loading Whisper model {model_name} on {device}/{compute_type}...")
        try:
            model = WhisperModel(model_name, device=device, compute_type=compute_type)
        except Exception as exc:
            fallback_model = os.environ.get("WHISPER_FALLBACK_MODEL", "tiny.en")
            if fallback_model == model_name:
                raise
            print(f"Could not load Whisper model {model_name}: {exc}")
            print(f"Falling back to cached Whisper model {fallback_model}.")
            model_name = fallback_model
            model = WhisperModel(fallback_model, device=device, compute_type=compute_type)
        _models[model_name] = model
        return model


def default_whisper_model():
    if model_dir_exists(LOCAL_EN_SMALL_MODEL_DIR):
        return LOCAL_EN_SMALL_MODEL_DIR
    if model_dir_exists(LOCAL_EN_MEDIUM_MODEL_DIR):
        return LOCAL_EN_MEDIUM_MODEL_DIR
    return "small.en"


def translate_segments(segments, language="en"):
    if not segments or language != "en" or TRANSLATION_PROVIDER in ("", "none", "off"):
        return segments

    try:
        translator = get_translator()
    except Exception as exc:
        print(f"Could not load translation model: {exc}. Returning English captions only.")
        return segments

    if translator is None:
        print("No local English-to-Chinese translator is available. Returning English captions only.")
        return segments

    translated = []
    texts = [segment["text"] for segment in segments]
    for start in range(0, len(texts), TRANSLATION_BATCH_SIZE):
        batch = texts[start : start + TRANSLATION_BATCH_SIZE]
        try:
            translations = translator(batch)
        except Exception as exc:
            print(f"Translation failed: {exc}. Returning English captions only.")
            return segments
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


def merge_short_incomplete_segments(segments):
    if len(segments) < 2:
        return segments

    merged = []
    index = 0
    while index < len(segments):
        current = dict(segments[index])
        while index + 1 < len(segments) and should_merge_short_incomplete(current, segments[index + 1]):
            next_segment = segments[index + 1]
            current["end"] = next_segment["end"]
            current["text"] = join_text(current["text"], next_segment["text"])
            current["translation"] = ""
            index += 1
        merged.append(clean_caption(current))
        index += 1
    return merged


def should_merge_short_incomplete(current, next_segment):
    text = current["text"].strip()
    if not text or is_sentence_complete(text):
        return False
    gap = float(next_segment["start"]) - float(current["end"])
    word_count = len([part for part in text.split() if part])
    combined_length = len(text) + 1 + len(next_segment["text"].strip())
    return gap <= 1.5 and combined_length <= 140 and (word_count <= 3 or len(text) <= 24)


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
    host = os.environ.get("WHISPER_HOST", "0.0.0.0")
    port = int(os.environ.get("WHISPER_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), TranscribeHandler)
    print(f"Whisper service running at http://{host}:{port}")
    print("GET  /ping")
    print("GET  /transcribe?video=backpacking keeps the old local-file debug flow.")
    print("POST /transcribe accepts an uploaded video/audio file from the phone.")
    print("Set WHISPER_AUTH_TOKEN before exposing this service to the internet.")
    server.serve_forever()


if __name__ == "__main__":
    main()
