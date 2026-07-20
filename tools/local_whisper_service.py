from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import sys
import tempfile
import threading
import time
import uuid
import urllib.request
from urllib.parse import parse_qs, unquote, urlparse

VIDEO_PATHS = {
    "backpacking": r"C:\Users\ASUS\Downloads\Full Gear List for Solo Backpacking.mp4",
}

def repair_local_proxy_env():
    detected = urllib.request.getproxies()
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        value = os.environ.get(name, "")
        if re.match(r"^https://(127\.0\.0\.1|localhost)(:\d+)?(/.*)?$", value):
            fixed = "http://" + value[len("https://") :]
            os.environ[name] = fixed
            print(f"Adjusted {name} for local proxy compatibility: {fixed}")
    for scheme, value in detected.items():
        if scheme.lower() in ("http", "https") and re.match(r"^https://(127\.0\.0\.1|localhost)(:\d+)?(/.*)?$", value):
            fixed = "http://" + value[len("https://") :]
            env_name = f"{scheme.upper()}_PROXY"
            os.environ[env_name] = fixed
            print(f"Adjusted Windows {scheme} proxy for Python compatibility via {env_name}: {fixed}")


repair_local_proxy_env()


def add_windows_gpu_dll_directories():
    if os.name != "nt":
        return
    candidates = []
    for base in sys.path:
        if not base or not os.path.isdir(base):
            continue
        candidates.extend(
            [
                os.path.join(base, "ctranslate2"),
                os.path.join(base, "nvidia", "cuda_runtime", "bin"),
                os.path.join(base, "nvidia", "cuda_nvrtc", "bin"),
                os.path.join(base, "nvidia", "cublas", "bin"),
                os.path.join(base, "nvidia", "cudnn", "bin"),
                os.path.join(base, "torch", "lib"),
                os.path.join(base, "av.libs"),
            ]
        )
    for path in candidates:
        if os.path.isdir(path):
            try:
                os.add_dll_directory(path)
            except (AttributeError, OSError):
                pass


add_windows_gpu_dll_directories()

SENTENCE_END_RE = re.compile(r"[.!?][\"')\]]*$")
SOFT_SENTENCE_END_RE = re.compile(r"[,;:][\"')\]]*$")
MIN_SUBTITLE_SECONDS = float(os.environ.get("SUBTITLE_MIN_SECONDS", "1.2"))
TARGET_SUBTITLE_SECONDS = float(os.environ.get("SUBTITLE_TARGET_SECONDS", "5.8"))
PREFERRED_MAX_SUBTITLE_SECONDS = float(os.environ.get("SUBTITLE_PREFERRED_MAX_SECONDS", "8.5"))
MAX_SUBTITLE_SECONDS = float(os.environ.get("SUBTITLE_MAX_SECONDS", "12.0"))
PREFERRED_MAX_SUBTITLE_WORDS = int(os.environ.get("SUBTITLE_PREFERRED_MAX_WORDS", "24"))
MAX_SUBTITLE_WORDS = int(os.environ.get("SUBTITLE_MAX_WORDS", "30"))
PREFERRED_MAX_SUBTITLE_CHARS = int(os.environ.get("SUBTITLE_PREFERRED_MAX_CHARS", "140"))
MAX_SUBTITLE_CHARS = int(os.environ.get("SUBTITLE_MAX_CHARS", "160"))
SILENCE_BREAK_SECONDS = float(os.environ.get("SUBTITLE_SILENCE_SECONDS", "0.75"))
SOFT_SILENCE_SECONDS = float(os.environ.get("SUBTITLE_SOFT_SILENCE_SECONDS", "0.32"))
ABSOLUTE_SILENCE_SECONDS = float(os.environ.get("SUBTITLE_ABSOLUTE_SILENCE_SECONDS", "1.2"))
START_PADDING_SECONDS = 0.03
END_PADDING_SECONDS = 0.22
MIN_GAP_SECONDS = 0.03
TRANSLATION_BATCH_SIZE = int(os.environ.get("TRANSLATION_BATCH_SIZE", "16"))
MAX_UPLOAD_MB = int(os.environ.get("WHISPER_MAX_UPLOAD_MB", "2048"))
AUTH_TOKEN = os.environ.get("WHISPER_AUTH_TOKEN", "").strip()
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
LOCAL_NLLB_MODEL_DIR = os.path.join(MODELS_DIR, "nllb-200-distilled-600M")
DEFAULT_TRANSLATION_MODEL = (
    LOCAL_NLLB_MODEL_DIR
    if os.path.isfile(os.path.join(LOCAL_NLLB_MODEL_DIR, "config.json"))
    else "facebook/nllb-200-distilled-600M"
)
TRANSLATION_PROVIDER = os.environ.get("TRANSLATION_PROVIDER", "auto").strip().lower()
TRANSLATION_MODEL = os.environ.get("TRANSLATION_MODEL", DEFAULT_TRANSLATION_MODEL)
TRANSLATION_DEVICE = os.environ.get("TRANSLATION_DEVICE", "auto").strip().lower()
TRANSLATION_SOURCE_LANGUAGE = os.environ.get("TRANSLATION_SOURCE_LANGUAGE", "eng_Latn").strip()
TRANSLATION_TARGET_LANGUAGE = os.environ.get("TRANSLATION_TARGET_LANGUAGE", "zho_Hans").strip()
TRANSLATION_STYLE = os.environ.get("TRANSLATION_STYLE", "subtitle").strip().lower()
TRANSLATION_LOCAL_FILES_ONLY = os.environ.get("TRANSLATION_LOCAL_FILES_ONLY", "auto").strip().lower()
DEVICE_FALLBACK = os.environ.get("MODEL_DEVICE_FALLBACK", "1").strip().lower() not in ("0", "false", "no", "off")
WHISPER_HOTWORDS = os.environ.get(
    "WHISPER_HOTWORDS",
    "clear English subtitles, proper names, place names, product names",
).strip()
WHISPER_INITIAL_PROMPT = os.environ.get(
    "WHISPER_INITIAL_PROMPT",
    "Clear English travel, hiking, backpacking, motorcycle and route-planning captions.",
).strip()
WHISPER_FORCE_LANGUAGE = os.environ.get("WHISPER_FORCE_LANGUAGE", "en").strip().lower()
OUTDOOR_HOTWORDS = (
    "Dyneema, Dyneema Composite Fabric, DCF, UltraGrid, Hyperlite Mountain Gear, "
    "trekking poles, trail runners, backpacking quilt, strength-to-weight ratio, "
    "base camp, thru-hike, ultralight backpacking"
)

RUNTIME_CONFIG_PATH = os.environ.get(
    "WHISPER_RUNTIME_CONFIG",
    os.path.join(PROJECT_ROOT, "tools", "runtime_service_config.json"),
)
RUNTIME_STATUS_PATH = os.environ.get(
    "WHISPER_RUNTIME_STATUS",
    os.path.join(PROJECT_ROOT, "tools", "runtime_status.json"),
)
LOCAL_EN_SMALL_MODEL_DIR = os.path.join(MODELS_DIR, "faster-whisper-small")
LOCAL_EN_MEDIUM_MODEL_DIR = os.path.join(MODELS_DIR, "faster-whisper-medium")
LOCAL_EN_DISTIL_LARGE_V3_MODEL_DIR = os.path.join(MODELS_DIR, "faster-distil-whisper-large-v3")
LOCAL_EN_LARGE_V3_MODEL_DIR = os.path.join(MODELS_DIR, "faster-whisper-large-v3")
LOCAL_MULTI_MEDIUM_MODEL_DIR = os.path.join(MODELS_DIR, "faster-whisper-medium（Multilingual model）")

_translator_lock = threading.Lock()
_translator = None
_model_lock = threading.Lock()
_models = {}
_jobs_lock = threading.Lock()
_jobs = {}
_runtime_status_lock = threading.Lock()


def compact_model_name(model_name):
    if not model_name:
        return ""
    return os.path.basename(model_name) if os.path.exists(model_name) else model_name


def default_runtime_status():
    return {
        "service": "starting",
        "port": os.environ.get("WHISPER_PORT", "8765"),
        "configured_english_model": os.environ.get("WHISPER_ENGLISH_MODEL", "large-v3"),
        "configured_whisper_device": os.environ.get("WHISPER_DEVICE", "auto"),
        "configured_whisper_compute_type": os.environ.get("WHISPER_COMPUTE_TYPE", "auto"),
        "translation_provider": TRANSLATION_PROVIDER,
        "translation_model": compact_model_name(TRANSLATION_MODEL),
        "translation_languages": f"{TRANSLATION_SOURCE_LANGUAGE}->{TRANSLATION_TARGET_LANGUAGE}",
        "translation_style": TRANSLATION_STYLE,
        "translation_batch_size": TRANSLATION_BATCH_SIZE,
        "job_status": "idle",
        "stage": "idle",
        "progress": 0,
        "message": "Waiting for a phone request",
    }


def read_runtime_status_file():
    try:
        if os.path.exists(RUNTIME_STATUS_PATH):
            with open(RUNTIME_STATUS_PATH, "r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
                return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def runtime_status():
    status = default_runtime_status()
    status.update(read_runtime_status_file())
    return status


def write_runtime_status(**changes):
    try:
        with _runtime_status_lock:
            status = default_runtime_status()
            status.update(read_runtime_status_file())
            status.update({key: value for key, value in changes.items() if value is not None})
            status["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            os.makedirs(os.path.dirname(RUNTIME_STATUS_PATH), exist_ok=True)
            temp_path = f"{RUNTIME_STATUS_PATH}.tmp"
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(status, handle, ensure_ascii=False, indent=2)
            os.replace(temp_path, RUNTIME_STATUS_PATH)
    except Exception as exc:
        print(f"Could not write runtime status: {exc}", flush=True)


class TranscribeHandler(BaseHTTPRequestHandler):
    server_version = "VideoEnglishWhisper/0.2"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/config":
            self.send_json(service_config())
            return

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

        if parsed.path == "/status":
            if not self.authorized(parsed):
                self.send_json({"error": "unauthorized"}, status=401)
                return
            self.send_json(runtime_status())
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
        if parsed.path == "/translate":
            if not self.authorized(parsed):
                self.send_json({"error": "unauthorized"}, status=401)
                return
            self.translate_and_send()
            return

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
        video_title = decode_video_title(self.headers.get("X-Video-Title", ""))

        if parsed.path == "/jobs":
            job_id = create_job(video_path, video_title)
            self.send_json({"job_id": job_id})
            return

        try:
            self.transcribe_and_send(video_path, video_title)
        finally:
            try:
                os.remove(video_path)
            except OSError:
                pass

    def translate_and_send(self):
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0:
            self.send_json({"error": "empty request"}, status=400)
            return
        if content_length > 10 * 1024 * 1024:
            self.send_json({"error": "request is too large"}, status=413)
            return
        try:
            body = self.rfile.read(content_length).decode("utf-8-sig")
            payload = json.loads(body)
            texts = payload.get("texts", [])
            if not isinstance(texts, list):
                raise ValueError("texts must be a list")
            clean_texts = [str(text).strip() for text in texts]
            print(f"POST /translate count={len(clean_texts)}", flush=True)
            translations = translate_texts(clean_texts)
            self.send_json({"translations": translations})
        except Exception as exc:
            print(f"POST /translate failed: {exc}", flush=True)
            self.send_json({"error": f"translation failed: {exc}"}, status=500)

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

    def transcribe_and_send(self, video_path, video_title=""):
        try:
            print(f"POST /transcribe sync file={video_path}", flush=True)
            segments = transcribe(video_path, video_title=video_title)
        except Exception as exc:
            print(f"POST /transcribe failed: {exc}", flush=True)
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


def decode_video_title(value):
    try:
        return unquote(str(value or "")).strip()[:300]
    except Exception:
        return str(value or "").strip()[:300]


def build_transcription_context(video_title=""):
    title = re.sub(r"[_\s]+", " ", str(video_title or "")).strip()
    title = re.sub(r"\.(mp4|m4a|mov|mkv|webm)$", "", title, flags=re.IGNORECASE)
    prompt_parts = [WHISPER_INITIAL_PROMPT] if WHISPER_INITIAL_PROMPT else []
    hotword_parts = [WHISPER_HOTWORDS] if WHISPER_HOTWORDS else []
    if title:
        prompt_parts.append(f"The video title is: {title}.")
        hotword_parts.append(title)
    if re.search(
        r"\b(hik|backpack|camp|trail|mountain|outdoor|gear|trek|switzerland|pakistan)\w*\b",
        title,
        flags=re.IGNORECASE,
    ):
        prompt_parts.append("Use accurate outdoor, hiking, camping and ultralight gear terminology.")
        hotword_parts.append(OUTDOOR_HOTWORDS)
    prompt = " ".join(part for part in prompt_parts if part).strip()
    hotwords = ", ".join(part for part in hotword_parts if part).strip()
    return prompt or None, hotwords or None


def service_config():
    current_port = int(os.environ.get("WHISPER_PORT", "8765"))
    token_suffix = f"?token={AUTH_TOKEN}" if AUTH_TOKEN else ""
    config = {
        "token_required": bool(AUTH_TOKEN),
        "transcribe_urls": [f"http://127.0.0.1:{current_port}/transcribe{token_suffix}"],
    }
    try:
        with open(RUNTIME_CONFIG_PATH, "r", encoding="utf-8-sig") as handle:
            saved = json.load(handle)
        if isinstance(saved, dict):
            saved_port = int(saved.get("port", current_port))
            if saved_port == current_port:
                urls = saved.get("transcribe_urls", [])
                if isinstance(urls, list):
                    merged = config["transcribe_urls"] + [str(url).strip() for url in urls if str(url).strip()]
                    config["transcribe_urls"] = list(dict.fromkeys(merged))
                if saved.get("public_url"):
                    config["public_url"] = str(saved["public_url"])
                if saved.get("lan_urls"):
                    config["lan_urls"] = saved["lan_urls"]
            else:
                config["warning"] = f"ignored runtime config for port {saved_port}; current port is {current_port}"
    except FileNotFoundError:
        pass
    except Exception as exc:
        config["warning"] = f"could not read runtime config: {exc}"
    return config


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


def create_job(video_path, video_title=""):
    job_id = uuid.uuid4().hex
    write_runtime_status(
        current_job_id=job_id,
        job_status="queued",
        stage="queued",
        progress=0,
        message="Queued uploaded file",
        source_file=os.path.basename(video_path),
    )
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
    thread = threading.Thread(target=run_job, args=(job_id, video_path, video_title), daemon=True)
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


def run_job(job_id, video_path, video_title=""):
    try:
        print(f"[job {job_id}] queued file={video_path}")
        update_job(job_id, status="running", stage="starting", progress=1, message="Preparing uploaded file")
        write_runtime_status(
            current_job_id=job_id,
            job_status="running",
            stage="starting",
            progress=1,
            message="Preparing uploaded file",
            source_file=os.path.basename(video_path),
            subtitle_count=0,
            error="",
        )

        def progress(stage, percent, message):
            print(f"[job {job_id}] {percent:03d}% {stage}: {message}", flush=True)
            update_job(job_id, status="running", stage=stage, progress=percent, message=message)
            write_runtime_status(current_job_id=job_id, job_status="running", stage=stage, progress=percent, message=message)

        result = transcribe(video_path, progress, video_title)
        print(f"[job {job_id}] done segments={len(result)}", flush=True)
        write_runtime_status(
            current_job_id=job_id,
            job_status="done",
            stage="done",
            progress=100,
            message=f"Generated {len(result)} subtitles",
            subtitle_count=len(result),
            error="",
        )
        update_job(
            job_id,
            status="done",
            stage="done",
            progress=100,
            message=f"Generated {len(result)} subtitles",
            result=result,
        )
    except Exception as exc:
        print(f"[job {job_id}] error: {exc}", flush=True)
        write_runtime_status(
            current_job_id=job_id,
            job_status="error",
            stage="error",
            progress=100,
            message=str(exc),
            error=str(exc),
        )
        update_job(job_id, status="error", stage="error", progress=100, message=str(exc), error=str(exc))
    finally:
        try:
            os.remove(video_path)
        except OSError:
            pass


def transcribe(video_path, progress=None, video_title=""):
    if WHISPER_FORCE_LANGUAGE and WHISPER_FORCE_LANGUAGE not in ("auto", "detect"):
        language = WHISPER_FORCE_LANGUAGE
        report(progress, "detecting", 6, f"Using configured language: {language}")
    else:
        report(progress, "detecting", 3, "Detecting language")
        language = detect_language(video_path, progress)
    model_name = choose_transcription_model(language)
    model_label = display_model_name(model_name)
    write_runtime_status(subtitle_model=model_label, detected_language=language or "unknown")
    print(f"Selected subtitle model: {model_label}; detected language={language or 'unknown'}", flush=True)
    report(progress, "loading", 10, f"Loading subtitle model: {model_label} for {language or 'unknown'}")
    model = get_whisper_model(model_name)
    print(f"Transcribing {video_path} with {model_name}; detected language={language or 'unknown'}...")
    report(progress, "transcribing", 12, f"Generating subtitles with {model_label}")
    initial_prompt, hotwords = build_transcription_context(video_title)
    segments, info = model.transcribe(
        video_path,
        language=language if language else None,
        beam_size=5,
        patience=1.2,
        vad_filter=True,
        vad_parameters={
            "min_silence_duration_ms": 400,
            "speech_pad_ms": 150,
        },
        word_timestamps=True,
        condition_on_previous_text=True,
        prompt_reset_on_temperature=0.5,
        initial_prompt=initial_prompt,
        hotwords=hotwords,
        temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
        compression_ratio_threshold=1.35,
        log_prob_threshold=-1.0,
        no_speech_threshold=0.6,
        hallucination_silence_threshold=1.0,
    )
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    raw_segments = []
    raw_words = []
    for segment in segments:
        text = " ".join(segment.text.strip().split())
        if duration > 0:
            percent = 12 + int(min(1.0, max(0.0, float(segment.end) / duration)) * 74)
            report(progress, "transcribing", percent, f"{model_label}: {format_seconds(segment.end)} / {format_seconds(duration)}")
        words = getattr(segment, "words", None) or []
        segment_word_start = len(raw_words)
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
        preserve_segment_terminal_punctuation(raw_words, segment_word_start, text)
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
    result = correct_recognized_captions(result)
    result = add_sentence_timing_padding(result)
    report(progress, "translating", 92, "Translating English subtitles")
    result = translate_segments(result, language, progress)
    print(f"Generated {len(result)} segments.")
    return result


def report(callback, stage, percent, message):
    print(f"[progress] {int(max(0, min(100, percent))):03d}% {stage}: {message}", flush=True)
    if callback is not None:
        callback(stage, int(max(0, min(100, percent))), message)


def display_model_name(model_name):
    return os.path.basename(model_name) if os.path.exists(model_name) else model_name


def format_seconds(seconds):
    total = int(max(0, seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def correct_recognized_captions(segments):
    if not segments:
        return segments

    corrected = []
    for segment in segments:
        item = dict(segment)
        text = correct_recognized_caption_text(item.get("text", ""))
        if text != item.get("text", ""):
            item["text"] = text
            item["translation"] = ""
        corrected.append(item)
    return corrected


def correct_recognized_caption_text(text):
    text = " ".join((text or "").split())
    if not text:
        return text

    replacements = [
        (r"\bthis\s+is\s+the\s+lost\s+way\s+around\s+africa\b", "This is the long way around Africa"),
        (r"\bthe\s+lost\s+way\s+around\s+africa\b", "the long way around Africa"),
        (r"\blost\s+way\s+around\s+africa\b", "long way around Africa"),
        (r"\bgoogle\s+maps\s+it\b", "Google Maps it"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = re.sub(r"\bwith\s+the\s*,\s*with\s+the\b", "with the", text, flags=re.IGNORECASE)
    text = re.sub(r"\bi\b", "I", text)
    first_alpha = re.search(r"[A-Za-z]", text)
    if first_alpha and text[first_alpha.start()].islower():
        text = text[: first_alpha.start()] + text[first_alpha.start()].upper() + text[first_alpha.start() + 1 :]
    return text


def detect_language(video_path, progress=None):
    detector_name = choose_language_detector_model()
    report(progress, "detecting", 4, f"Loading language detector only: {display_model_name(detector_name)}")
    detector = get_whisper_model(detector_name)
    print(f"Detecting language with {detector_name}...")
    report(progress, "detecting", 6, "Running language detection only")
    _segments, info = detector.transcribe(
        video_path,
        beam_size=1,
        vad_filter=True,
        word_timestamps=False,
        temperature=0.0,
    )
    language = getattr(info, "language", None)
    probability = getattr(info, "language_probability", None)
    write_runtime_status(
        detector_model=display_model_name(detector_name),
        detected_language=language or "unknown",
        language_probability=probability,
    )
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
        preference = os.environ.get("WHISPER_ENGLISH_MODEL", "large-v3").strip().lower()
        english_models = {
            "distil": LOCAL_EN_DISTIL_LARGE_V3_MODEL_DIR,
            "distil-large": LOCAL_EN_DISTIL_LARGE_V3_MODEL_DIR,
            "distil-large-v3": LOCAL_EN_DISTIL_LARGE_V3_MODEL_DIR,
            "large": LOCAL_EN_LARGE_V3_MODEL_DIR,
            "large-v3": LOCAL_EN_LARGE_V3_MODEL_DIR,
            "small": LOCAL_EN_SMALL_MODEL_DIR,
            "medium": LOCAL_EN_MEDIUM_MODEL_DIR,
        }
        preferred_model = english_models.get(preference)
        if preferred_model and model_dir_exists(preferred_model):
            return preferred_model
        fallback_orders = {
            "small": (LOCAL_EN_SMALL_MODEL_DIR, LOCAL_EN_LARGE_V3_MODEL_DIR, LOCAL_EN_DISTIL_LARGE_V3_MODEL_DIR, LOCAL_EN_MEDIUM_MODEL_DIR),
            "medium": (LOCAL_EN_MEDIUM_MODEL_DIR, LOCAL_EN_LARGE_V3_MODEL_DIR, LOCAL_EN_DISTIL_LARGE_V3_MODEL_DIR, LOCAL_EN_SMALL_MODEL_DIR),
            "distil": (LOCAL_EN_DISTIL_LARGE_V3_MODEL_DIR, LOCAL_EN_LARGE_V3_MODEL_DIR, LOCAL_EN_MEDIUM_MODEL_DIR, LOCAL_EN_SMALL_MODEL_DIR),
            "distil-large": (LOCAL_EN_DISTIL_LARGE_V3_MODEL_DIR, LOCAL_EN_LARGE_V3_MODEL_DIR, LOCAL_EN_MEDIUM_MODEL_DIR, LOCAL_EN_SMALL_MODEL_DIR),
            "distil-large-v3": (LOCAL_EN_DISTIL_LARGE_V3_MODEL_DIR, LOCAL_EN_LARGE_V3_MODEL_DIR, LOCAL_EN_MEDIUM_MODEL_DIR, LOCAL_EN_SMALL_MODEL_DIR),
        }
        fallback_order = fallback_orders.get(
            preference,
            (LOCAL_EN_LARGE_V3_MODEL_DIR, LOCAL_EN_DISTIL_LARGE_V3_MODEL_DIR, LOCAL_EN_MEDIUM_MODEL_DIR, LOCAL_EN_SMALL_MODEL_DIR),
        )
        for model_dir in fallback_order:
            if model_dir_exists(model_dir):
                return model_dir
        return "large-v3"

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
            "english_large_v3": LOCAL_EN_LARGE_V3_MODEL_DIR,
            "english_distil_large_v3": LOCAL_EN_DISTIL_LARGE_V3_MODEL_DIR,
            "english_medium": LOCAL_EN_MEDIUM_MODEL_DIR,
            "english_small": LOCAL_EN_SMALL_MODEL_DIR,
            "multilingual_medium": LOCAL_MULTI_MEDIUM_MODEL_DIR,
        },
    }


def resolve_whisper_compute_type(requested_compute_type, device, model_name):
    requested = str(requested_compute_type or "auto").strip().lower()
    if requested != "auto":
        return requested
    if device != "cuda":
        return "int8"
    if display_model_name(model_name) == "faster-whisper-large-v3":
        return "int8_float16"
    return "float16"


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

        requested_device = os.environ.get("WHISPER_DEVICE", "auto")
        device = resolve_whisper_device(requested_device)
        requested_compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", "auto")
        compute_type = resolve_whisper_compute_type(requested_compute_type, device, model_name)
        write_runtime_status(
            whisper_model=display_model_name(model_name),
            whisper_device=device,
            whisper_compute_type=compute_type,
            message=f"Loading Whisper model {display_model_name(model_name)} on {device}/{compute_type}",
        )
        print(f"Loading Whisper model {model_name} on {device}/{compute_type}...")
        try:
            model = WhisperModel(model_name, device=device, compute_type=compute_type)
        except Exception as exc:
            if device == "cuda" and DEVICE_FALLBACK and is_cuda_runtime_error(exc):
                print(f"Could not load Whisper model on CUDA: {exc}")
                print("CUDA runtime is incomplete; retrying Whisper on CPU/int8.")
                device = "cpu"
                compute_type = "int8" if requested_compute_type == "auto" else requested_compute_type
                model = WhisperModel(model_name, device=device, compute_type=compute_type)
                write_runtime_status(
                    whisper_model=display_model_name(model_name),
                    whisper_device=device,
                    whisper_compute_type=compute_type,
                    message=f"Loaded Whisper model {display_model_name(model_name)} on {device}/{compute_type}",
                )
                _models[model_name] = model
                return model
            fallback_model = os.environ.get("WHISPER_FALLBACK_MODEL", "tiny.en")
            if fallback_model == model_name:
                raise
            print(f"Could not load Whisper model {model_name}: {exc}")
            print(f"Falling back to cached Whisper model {fallback_model}.")
            model_name = fallback_model
            try:
                model = WhisperModel(fallback_model, device=device, compute_type=compute_type)
            except Exception as fallback_exc:
                if device == "cuda" and DEVICE_FALLBACK and is_cuda_runtime_error(fallback_exc):
                    print(f"Could not load fallback Whisper model on CUDA: {fallback_exc}")
                    print("CUDA runtime is incomplete; retrying fallback Whisper on CPU/int8.")
                    device = "cpu"
                    compute_type = "int8" if requested_compute_type == "auto" else requested_compute_type
                    model = WhisperModel(fallback_model, device=device, compute_type=compute_type)
                else:
                    raise
        write_runtime_status(
            whisper_model=display_model_name(model_name),
            whisper_device=device,
            whisper_compute_type=compute_type,
            message=f"Loaded Whisper model {display_model_name(model_name)} on {device}/{compute_type}",
        )
        _models[model_name] = model
        return model


def resolve_whisper_device(requested_device):
    requested = (requested_device or "auto").strip().lower()
    if requested not in ("auto", "cuda"):
        return requested

    try:
        import ctranslate2

        cuda_available = ctranslate2.get_cuda_device_count() > 0
    except Exception as exc:
        print(f"Could not probe CUDA for faster-whisper: {exc}")
        cuda_available = False

    if cuda_available:
        return "cuda"
    if requested == "cuda" and not DEVICE_FALLBACK:
        raise RuntimeError("WHISPER_DEVICE=cuda was requested, but CTranslate2 cannot access a CUDA device")
    if requested == "cuda":
        print("CTranslate2 cannot access CUDA; falling back to CPU for Whisper.")
    else:
        print("CUDA is unavailable to CTranslate2; using CPU for Whisper.")
    return "cpu"


def is_cuda_runtime_error(exc):
    message = str(exc).lower()
    cuda_markers = (
        "cublas",
        "cudnn",
        "cuda",
        "cufft",
        "curand",
        "cusolver",
        "cusparse",
        "nvrtc",
        "not found or cannot be loaded",
        "could not load library",
    )
    return any(marker in message for marker in cuda_markers)


def default_whisper_model():
    if model_dir_exists(LOCAL_EN_LARGE_V3_MODEL_DIR):
        return LOCAL_EN_LARGE_V3_MODEL_DIR
    if model_dir_exists(LOCAL_EN_DISTIL_LARGE_V3_MODEL_DIR):
        return LOCAL_EN_DISTIL_LARGE_V3_MODEL_DIR
    if model_dir_exists(LOCAL_EN_MEDIUM_MODEL_DIR):
        return LOCAL_EN_MEDIUM_MODEL_DIR
    if model_dir_exists(LOCAL_EN_SMALL_MODEL_DIR):
        return LOCAL_EN_SMALL_MODEL_DIR
    return "large-v3"


def translate_segments(segments, language="en", progress=None):
    if not segments or language != "en" or TRANSLATION_PROVIDER in ("", "none", "off"):
        return segments

    try:
        translations = translate_texts([segment["text"] for segment in segments], progress)
    except Exception as exc:
        print(f"Translation failed: {exc}. Returning English captions only.")
        return segments
    if len(translations) != len(segments):
        return segments

    translated = []
    for segment, translation in zip(segments, translations):
        item = dict(segment)
        item["translation"] = translation
        translated.append(item)
    return translated


def translate_texts(texts, progress=None):
    if not texts or TRANSLATION_PROVIDER in ("", "none", "off"):
        return ["" for _ in texts]

    try:
        translator = get_translator()
    except Exception as exc:
        raise RuntimeError(f"could not load translation model: {exc}") from exc

    if translator is None:
        raise RuntimeError("no local English-to-Chinese translator is available")

    prepared_texts = [prepare_caption_for_translation(text) for text in texts]
    write_runtime_status(
        stage="translating",
        message=f"Translating {len(texts)} subtitles",
        translation_total=len(texts),
        translation_done=0,
        translation_model=display_model_name(TRANSLATION_MODEL),
        translation_provider=TRANSLATION_PROVIDER,
    )
    print(f"Translating {len(texts)} subtitles with {TRANSLATION_PROVIDER}/{display_model_name(TRANSLATION_MODEL)}; batch size={TRANSLATION_BATCH_SIZE}", flush=True)
    translated = [""] * len(texts)
    if progress is not None and texts:
        progress("translating", 92, f"Translating subtitles 0/{len(texts)}")
    for start in range(0, len(texts), TRANSLATION_BATCH_SIZE):
        batch = prepared_texts[start : start + TRANSLATION_BATCH_SIZE]
        end = min(start + len(batch), len(texts))
        print(f"Translation batch {start + 1}-{end}/{len(texts)}", flush=True)
        write_runtime_status(
            stage="translating",
            message=f"Translation batch {start + 1}-{end}/{len(texts)}",
            translation_total=len(texts),
            translation_done=start,
            translation_batch=f"{start + 1}-{end}/{len(texts)}",
        )
        try:
            translations = translator(batch)
        except Exception as exc:
            raise RuntimeError(f"translation failed: {exc}") from exc
        for offset, translation in enumerate(translations):
            index = start + offset
            translated[index] = polish_caption_translation(texts[index], prepared_texts[index], translation)
        mapped_progress = 92 + int((end / max(1, len(texts))) * 7)
        if progress is not None:
            progress("translating", min(99, mapped_progress), f"Translating subtitles {end}/{len(texts)}")
        write_runtime_status(
            stage="translating",
            progress=min(99, mapped_progress),
            message=f"Translated {end}/{len(texts)} subtitles",
            translation_total=len(texts),
            translation_done=end,
            translation_batch=f"{start + 1}-{end}/{len(texts)}",
        )
    return translated


def prepare_caption_for_translation(text):
    text = " ".join((text or "").split())
    if TRANSLATION_STYLE in ("", "raw", "none", "off"):
        return text

    replacements = [
        (r"\bthe\s+lost\s+way\s+around\s+africa\b", "the long way around Africa"),
        (r"\blost\s+way\s+around\s+africa\b", "long way around Africa"),
        (r"\bas\s+the\s+crow\s+flies\b", "in a straight line"),
        (r"\bgoogle\s+maps\s+it\b", "use Google Maps to figure it out"),
        (r"\bgoogle-map\s+it\b", "use Google Maps to figure it out"),
        (r"\bcoast\s+to\s+coast\b", "from one coast to the other coast"),
        (r"\bDCF\b", "Dyneema Composite Fabric (DCF)"),
        (r"\bstrength\s+to\s+weight\s+ratio\b", "strength-to-weight ratio"),
        (r"\brunner['\u2019]s\s+high\b", "the euphoric feeling known as runner's high"),
        (r"\bhiker['\u2019]s\s+high\b", "the euphoric feeling known as hiker's high"),
        (r"\btrekking\s+poles?\b", "hiking trekking poles"),
        (r"\bbackpacking\s+quilts?\b", "insulated backpacking quilts"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def polish_caption_translation(original, prepared, translation):
    text = " ".join((translation or "").split())
    if TRANSLATION_STYLE in ("", "raw", "none", "off"):
        return text

    source = " ".join((original or "").split()).lower()
    prepared_source = " ".join((prepared or "").split()).lower()

    fixed_sentences = [
        (r"\bjoin me and my family today as we go on a camping and hiking\.?$", "\u4eca\u5929\u548c\u6211\u53ca\u5bb6\u4eba\u4e00\u8d77\u53bb\u9732\u8425\u5f92\u6b65\u5427\u3002"),
        (r"\btrip to a beautiful glacier lake in canada\.?$", "\u524d\u5f80\u52a0\u62ff\u5927\u4e00\u5ea7\u7f8e\u4e3d\u7684\u51b0\u5ddd\u6e56\u3002"),
        (r"\bso grab your backpack,?\.?$", "\u6240\u4ee5\u5e26\u4e0a\u4f60\u7684\u80cc\u5305\uff0c"),
        (r"\ba tent,? your hiking boots,?\.?$", "\u4e00\u9876\u5e10\u7bf7\u548c\u4f60\u7684\u5f92\u6b65\u9774\uff0c"),
        (r"\band (let['\u2019]s do it|let us go)\.?$", "\u6211\u4eec\u51fa\u53d1\u5427\u3002"),
        (r"\byou['\u2019]re also going to need a good, warm winter jacket and sleeping bag\.?$", "\u4f60\u8fd8\u9700\u8981\u4e00\u4ef6\u4fdd\u6696\u7684\u51ac\u5b63\u5939\u514b\u548c\u4e00\u4e2a\u7761\u888b\u3002"),
        (r"\boh my\.?$", "\u5929\u554a\u3002"),
        (
            r"\bbut we don't get to go straight (as the crow flies|in a straight line)\.?$",
            "但我们不能按直线距离直接过去。",
        ),
        (
            r"\bthis is the (lost|long) way around africa\.?$",
            "这就是绕行非洲的漫长路线。",
        ),
        (
            r"\bif you're going to cross africa (coast to coast|from one coast to the other coast), you're going to need to do some planning\.?$",
            "如果你要横穿非洲，从一个海岸到另一个海岸，就得认真规划。",
        ),
        (r"\bsome serious planning\.?$", "而且是非常认真的规划。"),
        (
            r"\byou see, you can't just (google maps it|use google maps to figure it out)\.?$",
            "你看，这事不能只是打开谷歌地图随便搜一下就出发。",
        ),
    ]
    for pattern, replacement in fixed_sentences:
        if re.fullmatch(pattern, source, flags=re.IGNORECASE) or re.fullmatch(pattern, prepared_source, flags=re.IGNORECASE):
            return replacement

    fixed_fragments = [
        (
            r"\bbut we don't get to go straight (as the crow flies|in a straight line)\b",
            [
                ("但是我们不能直走一条直线", "但我们不能按直线距离直接过去"),
                ("但我们不能直走一条直线", "但我们不能按直线距离直接过去"),
                ("但我们不能直接走直线", "但我们不能按直线距离直接过去"),
            ],
        ),
        (
            r"\bthis is the (lost|long) way around africa\b",
            [
                ("这是非洲最远的路", "这就是绕行非洲的漫长路线"),
                ("这是在非洲各地的迷路", "这就是绕行非洲的漫长路线"),
                ("这是非洲各地的迷路", "这就是绕行非洲的漫长路线"),
            ],
        ),
        (
            r"\bif you're going to cross africa (coast to coast|from one coast to the other coast)\b",
            [
                ("如果你要从一个海岸穿越非洲到另一个海岸, 你需要做一些计划", "如果你要横穿非洲，从一个海岸到另一个海岸，就得认真规划"),
                ("如果你要穿越非洲海岸到海岸，你需要做一些规划", "如果你要横穿非洲，从一个海岸到另一个海岸，就得认真规划"),
            ],
        ),
        (
            r"\byou see, you can't just (google maps it|use google maps to figure it out)\b",
            [
                ("你不能只用谷歌地图来弄清楚", "你看，这事不能只是打开谷歌地图随便搜一下就出发"),
                ("你看，你不能只是谷歌地图它", "你看，这事不能只是打开谷歌地图随便搜一下就出发"),
            ],
        ),
    ]
    for pattern, replacements_for_fragment in fixed_fragments:
        if re.search(pattern, source, flags=re.IGNORECASE) or re.search(pattern, prepared_source, flags=re.IGNORECASE):
            for old, new in replacements_for_fragment:
                text = text.replace(old, new)

    replacements = [
        ("但是我们不能直走一条直线", "但我们不能按直线距离直接过去"),
        ("但我们不能直走一条直线", "但我们不能按直线距离直接过去"),
        ("这是非洲最远的路", "这就是绕行非洲的漫长路线"),
        ("像乌鸦飞来飞去一样直走", "按直线距离直接过去"),
        ("像乌鸦飞一样直走", "按直线距离直接过去"),
        ("乌鸦飞", "直线距离"),
        ("非洲各地的迷路", "绕行非洲的漫长路线"),
        ("非洲各地的失落之路", "绕行非洲的漫长路线"),
        ("海岸到海岸", "从一个海岸到另一个海岸"),
        ("一些严肃的计划", "非常认真的规划"),
        ("谷歌地图它", "用谷歌地图随便搜一下"),
        ("谷歌地图一下", "用谷歌地图随便搜一下"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return normalize_subtitle_chinese(text)


def normalize_subtitle_chinese(text):
    text = " ".join((text or "").split())
    replacements = [
        ("\u6293\u4f4f\u4f60\u7684\u80cc\u5305", "\u5e26\u4e0a\u4f60\u7684\u80cc\u5305"),
        ("\u5305\u88c5\u4e86\u6211\u4eec\u7684\u718a\u55b7\u96fe", "\u5e26\u4e0a\u4e86\u9632\u718a\u55b7\u96fe"),
        ("\u5305\u88c5\u718a\u55b7\u96fe", "\u5e26\u4e0a\u9632\u718a\u55b7\u96fe"),
        ("\u51ac\u5b63\u514b", "\u51ac\u5b63\u5939\u514b"),
        ("\u9732\u8425\u65c5\u884c", "\u9732\u8425\u4e4b\u65c5"),
        ("\u9732\u8425\u662f\u6709\u8da3\u7684", "\u9732\u8425\u5f88\u6709\u8da3"),
        ("\u8ba9\u6211\u4eec\u8fd9\u6837\u505a", "\u6211\u4eec\u51fa\u53d1\u5427"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    text = re.sub(r"(?<!\u9632)\u718a\u55b7\u96fe", "\u9632\u718a\u55b7\u96fe", text)
    if re.search(r"[\u3400-\u9fff]", text):
        text = re.sub(r",\s*", "\uff0c", text)
        text = re.sub(r"\.(?=$|\s)", "\u3002", text)
        text = text.replace("?", "\uff1f").replace("!", "\uff01")
        text = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", text)
        text = re.sub(r"^[\uff0c\u3002\uff1b\uff1a\uff01\uff1f\s]+", "", text)
        text = re.sub(r"([\uff0c\u3002\uff01\uff1f\uff1b\uff1a])\1+", r"\1", text)
        text = re.sub(r"\uff0c(?=[\u3002\uff01\uff1f\uff1b\uff1a])", "", text)
    return text


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
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    except ImportError:
        return None

    write_runtime_status(
        translation_provider="transformers",
        translation_model=display_model_name(TRANSLATION_MODEL),
        translation_device="loading",
        message=f"Loading translation model {display_model_name(TRANSLATION_MODEL)}",
    )
    print(f"Loading translation model {TRANSLATION_MODEL}...")
    tokenizer = load_pretrained(AutoTokenizer, TRANSLATION_MODEL)
    model = load_pretrained(AutoModelForSeq2SeqLM, TRANSLATION_MODEL)
    device = resolve_translation_device(torch, TRANSLATION_DEVICE)
    try:
        if device == "cuda":
            model.to(device=device, dtype=torch.float16)
        else:
            model.to(device)
    except Exception as exc:
        if device == "cuda" and DEVICE_FALLBACK and is_cuda_runtime_error(exc):
            print(f"Could not move translation model to CUDA: {exc}")
            print("CUDA runtime is incomplete; retrying translation on CPU.")
            device = "cpu"
            model.to(device)
        else:
            raise
    model.eval()

    is_nllb = getattr(model.config, "model_type", "") in ("m2m_100", "nllb")
    forced_bos_token_id = None
    if is_nllb:
        tokenizer.src_lang = TRANSLATION_SOURCE_LANGUAGE
        forced_bos_token_id = tokenizer.convert_tokens_to_ids(TRANSLATION_TARGET_LANGUAGE)
        if forced_bos_token_id is None or forced_bos_token_id == tokenizer.unk_token_id:
            raise RuntimeError(f"NLLB target language token is unavailable: {TRANSLATION_TARGET_LANGUAGE}")

    def translate_batch(texts):
        encoded = tokenizer(texts, return_tensors="pt", padding=True, truncation=True, max_length=512)
        encoded = {name: tensor.to(device) for name, tensor in encoded.items()}
        generation_options = {"max_new_tokens": 256, "num_beams": 4, "length_penalty": 1.35, "early_stopping": False}
        if forced_bos_token_id is not None:
            generation_options["forced_bos_token_id"] = forced_bos_token_id
        with torch.inference_mode():
            generated = model.generate(**encoded, **generation_options)
        return [text.strip() for text in tokenizer.batch_decode(generated, skip_special_tokens=True)]

    language_pair = f"{TRANSLATION_SOURCE_LANGUAGE}->{TRANSLATION_TARGET_LANGUAGE}" if is_nllb else "model default"
    write_runtime_status(
        translation_provider="transformers",
        translation_model=display_model_name(TRANSLATION_MODEL),
        translation_device=device,
        translation_languages=language_pair,
        message=f"Loaded translation model {display_model_name(TRANSLATION_MODEL)} on {device}",
    )
    print(f"Using Transformers model {TRANSLATION_MODEL} on {device} ({language_pair}) for English-to-Chinese subtitles.")
    return translate_batch


def load_pretrained(component, model_name):
    local_mode = TRANSLATION_LOCAL_FILES_ONLY
    if local_mode in ("1", "true", "yes", "on"):
        return component.from_pretrained(model_name, local_files_only=True)
    if local_mode in ("0", "false", "no", "off"):
        return component.from_pretrained(model_name)

    try:
        return component.from_pretrained(model_name, local_files_only=True)
    except Exception as exc:
        print(f"Could not load cached translation model locally: {exc}")
        print("Trying to download or refresh the translation model from Hugging Face...")
        return component.from_pretrained(model_name)


def resolve_translation_device(torch_module, requested_device):
    requested = (requested_device or "auto").strip().lower()
    if requested not in ("auto", "cuda"):
        return requested
    if torch_module.cuda.is_available():
        return "cuda"
    if requested == "cuda" and not DEVICE_FALLBACK:
        raise RuntimeError("TRANSLATION_DEVICE=cuda was requested, but this PyTorch build cannot access CUDA")
    if requested == "cuda":
        print("PyTorch cannot access CUDA; falling back to CPU for translation.")
    else:
        print("CUDA is unavailable to PyTorch; using CPU for translation.")
    return "cpu"


def preserve_segment_terminal_punctuation(raw_words, segment_word_start, segment_text):
    if len(raw_words) <= segment_word_start:
        return
    last_word = raw_words[-1]
    last_word["segment_end"] = True
    terminal_match = re.search(r"([,.!?;:])[\"')\]]*$", str(segment_text or "").strip())
    if not terminal_match:
        return
    terminal = terminal_match.group(1)
    last_word["segment_complete"] = terminal in ".!?"
    if not re.search(r"[,.!?;:]$", last_word["text"].strip()):
        last_word["text"] = last_word["text"].rstrip() + terminal


def words_to_sentence_segments(words):
    normalized_words = []
    for raw_word in words:
        text = str(raw_word.get("text", "")).strip()
        if not text:
            continue
        normalized_words.append(
            {
                "start": float(raw_word["start"]),
                "end": float(raw_word["end"]),
                "text": text,
                "segment_end": bool(raw_word.get("segment_end", False)),
                "segment_complete": bool(raw_word.get("segment_complete", False)),
            }
        )

    result = []
    current_words = []
    for index, word in enumerate(normalized_words):
        current_words.append(word)

        while len(current_words) > 1 and subtitle_limits_exceeded(current_words):
            split_at = find_preferred_word_boundary(current_words)
            if split_at <= 0 or split_at >= len(current_words):
                split_at = len(current_words) - 1
            result.append(make_word_segment(current_words[:split_at]))
            current_words = current_words[split_at:]

        if current_words and is_sentence_complete(word["text"]):
            result.append(make_word_segment(current_words))
            current_words = []
            continue

        next_word = normalized_words[index + 1] if index + 1 < len(normalized_words) else None
        if current_words and next_word and should_break_after_word(current_words, next_word):
            result.append(make_word_segment(current_words))
            current_words = []

    if current_words:
        result.append(make_word_segment(current_words))
    return merge_short_incomplete_segments(result)


def make_word_segment(words):
    return {
        "start": float(words[0]["start"]),
        "end": float(words[-1]["end"]),
        "text": words_to_text(words),
        "translation": "",
    }


def word_buffer_duration(words):
    if not words:
        return 0.0
    return float(words[-1]["end"]) - float(words[0]["start"])


def weak_subtitle_ending(text):
    matches = re.findall(r"[A-Za-z']+", text.lower())
    if not matches:
        return False
    last_word = matches[-1]
    return last_word.endswith("ing") or last_word in {
        "a", "an", "the", "to", "of", "with", "for", "from", "into", "on", "in", "at", "by",
        "and", "but", "or", "because", "that", "which", "who", "whom", "whose", "when", "if", "as",
        "i", "you", "he", "she", "it", "we", "they", "this", "these", "those", "there",
        "my", "your", "his", "her", "our", "their", "very", "really", "just", "kind", "sort",
        "much", "many", "more", "most", "less", "good", "not", "no", "so", "too", "quite",
        "am", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did",
        "can", "could", "will", "would", "shall", "should", "may", "might", "must",
    }


def starts_with_dependent_clause(text):
    normalized = " ".join(re.findall(r"[A-Za-z']+", text.lower()))
    return normalized.startswith("even though ") or normalized.startswith(
        ("although ", "because ", "if ", "unless ", "while ", "when ", "whenever ", "since ")
    )


def incomplete_clause_ending(text):
    stripped = text.strip()
    return weak_subtitle_ending(stripped) or (
        bool(SOFT_SENTENCE_END_RE.search(stripped)) and starts_with_dependent_clause(stripped)
    )


def starts_with_continuation(text):
    first = re.sub(r"^[^A-Za-z]+", "", str(text or "")).lower()
    return first in {
        "of", "to", "from", "for", "with", "without", "than", "that", "which", "who", "whom",
        "whose", "what", "where", "when", "why", "how",
    }


def should_break_after_word(current_words, next_word):
    duration = word_buffer_duration(current_words)
    if duration < MIN_SUBTITLE_SECONDS or len(current_words) < 3:
        return False

    current_text = words_to_text(current_words)
    previous_text = current_words[-1]["text"].strip()
    next_text = re.sub(r"^[^A-Za-z]+", "", next_word["text"]).lower()
    gap = float(next_word["start"]) - float(current_words[-1]["end"])

    if incomplete_clause_ending(current_text) or starts_with_continuation(next_text):
        return False

    if current_words[-1].get("segment_complete"):
        return True
    if (
        current_words[-1].get("segment_end")
        and duration >= TARGET_SUBTITLE_SECONDS
        and gap >= SOFT_SILENCE_SECONDS
    ):
        return True

    if gap >= ABSOLUTE_SILENCE_SECONDS:
        return True

    if SOFT_SENTENCE_END_RE.search(previous_text):
        return duration >= PREFERRED_MAX_SUBTITLE_SECONDS or (
            duration >= TARGET_SUBTITLE_SECONDS and gap >= SOFT_SILENCE_SECONDS
        )

    if gap >= SILENCE_BREAK_SECONDS and duration >= TARGET_SUBTITLE_SECONDS:
        return True

    clause_starters = {
        "and", "but", "so", "because", "although", "though", "while",
        "which", "who", "when", "where", "then", "however",
    }
    return (
        next_text in clause_starters
        and len(current_words) >= 6
        and duration >= TARGET_SUBTITLE_SECONDS
        and gap >= SOFT_SILENCE_SECONDS
    )


def subtitle_limits_exceeded(words):
    if not words:
        return False
    return (
        word_buffer_duration(words) > MAX_SUBTITLE_SECONDS
        or len(words) > MAX_SUBTITLE_WORDS
        or len(words_to_text(words)) > MAX_SUBTITLE_CHARS
    )


def find_preferred_word_boundary(words):
    if len(words) < 4:
        return len(words) - 1
    best_index = 0
    best_score = float("-inf")
    upper = len(words) - 1
    for split_at in range(3, upper + 1):
        left = words[:split_at]
        if word_buffer_duration(left) < MIN_SUBTITLE_SECONDS:
            continue
        left_text = words_to_text(left)
        previous_text = left[-1]["text"].strip()
        next_text = re.sub(r"^[^A-Za-z]+", "", words[split_at]["text"]).lower()
        gap = float(words[split_at]["start"]) - float(left[-1]["end"])
        duration = word_buffer_duration(left)
        score = -abs(duration - TARGET_SUBTITLE_SECONDS)

        if incomplete_clause_ending(left_text):
            score -= 30.0
        if starts_with_continuation(next_text):
            score -= 18.0
        if len(words) - split_at <= 2:
            score -= 6.0

        if is_sentence_complete(previous_text):
            score += 24.0
        elif SOFT_SENTENCE_END_RE.search(previous_text):
            score += 10.0
        if gap >= ABSOLUTE_SILENCE_SECONDS:
            score += 14.0
        elif gap >= SILENCE_BREAK_SECONDS:
            score += 8.0
        elif gap >= SOFT_SILENCE_SECONDS:
            score += 3.0
        if next_text in {"and", "but", "so", "because", "although", "which", "who", "when", "then"}:
            score += 3.0
        if duration > PREFERRED_MAX_SUBTITLE_SECONDS:
            score += 2.0
        if len(left) > PREFERRED_MAX_SUBTITLE_WORDS or len(left_text) > PREFERRED_MAX_SUBTITLE_CHARS:
            score -= 2.0
        if score > best_score:
            best_score = score
            best_index = split_at
    return best_index



def words_to_text(words):
    text = " ".join(word["text"].strip() for word in words if word["text"].strip())
    text = re.sub(r"\s+([,.!?;:%])", r"\1", text)
    text = re.sub(r"\s+-\s*", "-", text)
    text = re.sub(r"\s+(['’]s\b)", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+n't\b", "n't", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def should_force_word_break(text, duration):
    if is_sentence_complete(text):
        return True
    return duration >= MAX_SUBTITLE_SECONDS or len(text) >= MAX_SUBTITLE_CHARS


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
    next_text = next_segment["text"].strip()
    if not text or not next_text or is_sentence_complete(text):
        return False

    gap = float(next_segment["start"]) - float(current["end"])
    combined_text = join_text(text, next_text)
    combined_duration = float(next_segment["end"]) - float(current["start"])
    combined_words = len([part for part in combined_text.split() if part])
    if (
        gap > ABSOLUTE_SILENCE_SECONDS
        or combined_duration > MAX_SUBTITLE_SECONDS
        or combined_words > MAX_SUBTITLE_WORDS
        or len(combined_text) > MAX_SUBTITLE_CHARS
    ):
        return False

    next_word_count = len([part for part in next_text.split() if part])
    return (
        incomplete_clause_ending(text)
        or starts_with_continuation(next_text)
        or next_word_count <= 2
    )


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
        if is_sentence_complete(current["text"]) or duration >= MAX_SUBTITLE_SECONDS or len(current["text"]) >= MAX_SUBTITLE_CHARS:
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
        if len(text) <= MAX_SUBTITLE_CHARS:
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
        if len(candidate) <= MAX_SUBTITLE_CHARS:
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
    configured_english_model = os.environ.get("WHISPER_ENGLISH_MODEL", "large-v3")
    selected_english_model = display_model_name(choose_transcription_model("en"))
    write_runtime_status(
        service="running",
        port=str(port),
        configured_english_model=configured_english_model,
        whisper_model=selected_english_model,
        subtitle_model=selected_english_model,
        job_status="idle",
        stage="idle",
        progress=0,
        message="Waiting for a phone request",
    )
    server = ThreadingHTTPServer((host, port), TranscribeHandler)
    print(f"Whisper service running at http://{host}:{port}")
    print("GET  /ping")
    print("GET  /transcribe?video=backpacking keeps the old local-file debug flow.")
    print("POST /transcribe accepts an uploaded video/audio file from the phone.")
    print("Set WHISPER_AUTH_TOKEN before exposing this service to the internet.")
    server.serve_forever()


if __name__ == "__main__":
    main()
