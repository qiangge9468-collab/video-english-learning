#include <jni.h>
#include <android/log.h>
#include <algorithm>
#include <cstdint>
#include <fstream>
#include <string>
#include <thread>
#include <vector>

#include "whisper.h"

#define LOG_TAG "VELWhisperJNI"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

namespace {

int cpu_thread_count() {
    return std::max(2u, std::min(4u, std::thread::hardware_concurrency()));
}

jobject make_segment(JNIEnv *env, jclass segment_class, jmethodID constructor, int start_ms, int end_ms, const char *text) {
    jstring j_text = env->NewStringUTF(text == nullptr ? "" : text);
    jobject segment = env->NewObject(segment_class, constructor, start_ms, end_ms, j_text);
    env->DeleteLocalRef(j_text);
    return segment;
}

void throw_error(JNIEnv *env, const char *message) {
    jclass error_class = env->FindClass("java/lang/IllegalStateException");
    if (error_class != nullptr) {
        env->ThrowNew(error_class, message);
    }
}

struct SegmentResult {
    int start_ms;
    int end_ms;
    std::string text;
};

struct ProgressBridge {
    JavaVM *vm = nullptr;
    jobject listener = nullptr;
    jmethodID on_progress = nullptr;
    int chunk_index = 0;
    int chunk_count = 0;
    int chunk_seconds = 20;
    int active_chunk_samples = 0;
    int total_samples = 0;
    int last_percent = -1;
};

JNIEnv *bridge_env(ProgressBridge *bridge) {
    if (bridge == nullptr || bridge->vm == nullptr) return nullptr;
    JNIEnv *env = nullptr;
    if (bridge->vm->GetEnv(reinterpret_cast<void **>(&env), JNI_VERSION_1_6) != JNI_OK) {
        if (bridge->vm->AttachCurrentThread(&env, nullptr) != JNI_OK) return nullptr;
    }
    return env;
}

void report_progress(ProgressBridge *bridge, int chunk_progress) {
    if (bridge == nullptr || bridge->listener == nullptr || bridge->on_progress == nullptr) return;
    if (bridge->total_samples <= 0) return;

    const int clamped_chunk_progress = std::max(0, std::min(100, chunk_progress));
    const int64_t chunk_start = static_cast<int64_t>(bridge->chunk_index) * bridge->chunk_seconds * 16000;
    const int64_t chunk_done = static_cast<int64_t>(bridge->active_chunk_samples) * clamped_chunk_progress / 100;
    const int processed_samples = static_cast<int>(std::min<int64_t>(bridge->total_samples, chunk_start + chunk_done));
    const int percent = static_cast<int>(std::min<int64_t>(100, static_cast<int64_t>(processed_samples) * 100 / bridge->total_samples));
    if (percent == bridge->last_percent && clamped_chunk_progress != 100) return;
    bridge->last_percent = percent;

    JNIEnv *env = bridge_env(bridge);
    if (env == nullptr) return;
    env->CallVoidMethod(
            bridge->listener,
            bridge->on_progress,
            percent,
            processed_samples * 1000 / 16000,
            bridge->total_samples * 1000 / 16000,
            bridge->chunk_index,
            bridge->chunk_count);
    if (env->ExceptionCheck()) {
        env->ExceptionClear();
    }
}

void vel_whisper_progress_callback(struct whisper_context *, struct whisper_state *, int progress, void *user_data) {
    report_progress(static_cast<ProgressBridge *>(user_data), progress);
}

bool read_pcm_chunk(std::ifstream &input, std::vector<float> &pcm) {
    std::vector<int16_t> raw(pcm.size());
    input.read(reinterpret_cast<char *>(raw.data()), static_cast<std::streamsize>(raw.size() * sizeof(int16_t)));
    const std::streamsize bytes_read = input.gcount();
    if (bytes_read <= 0) return false;

    const size_t samples_read = static_cast<size_t>(bytes_read) / sizeof(int16_t);
    pcm.resize(samples_read);
    for (size_t i = 0; i < samples_read; ++i) {
        pcm[i] = static_cast<float>(raw[i]) / 32768.0f;
    }
    return !pcm.empty();
}

}

extern "C" JNIEXPORT jobjectArray JNICALL
Java_com_codex_videolearnenglish_WhisperNative_nativeTranscribePcmFile(
        JNIEnv *env,
        jobject,
        jstring model_path,
        jstring pcm_path,
        jint sample_rate,
        jobject progress_listener) {
    if (sample_rate != 16000) {
        throw_error(env, "Whisper requires 16 kHz mono PCM.");
        return nullptr;
    }

    const char *model_path_chars = env->GetStringUTFChars(model_path, nullptr);
    if (model_path_chars == nullptr) {
        throw_error(env, "Could not read model path.");
        return nullptr;
    }

    whisper_context_params context_params = whisper_context_default_params();
    whisper_context *context = whisper_init_from_file_with_params(model_path_chars, context_params);
    env->ReleaseStringUTFChars(model_path, model_path_chars);

    if (context == nullptr) {
        throw_error(env, "Could not load Whisper model.");
        return nullptr;
    }

    const char *pcm_path_chars = env->GetStringUTFChars(pcm_path, nullptr);
    if (pcm_path_chars == nullptr) {
        whisper_free(context);
        throw_error(env, "Could not read PCM path.");
        return nullptr;
    }

    std::ifstream pcm_file(pcm_path_chars, std::ios::binary);
    env->ReleaseStringUTFChars(pcm_path, pcm_path_chars);
    if (!pcm_file) {
        whisper_free(context);
        throw_error(env, "Could not open decoded PCM file.");
        return nullptr;
    }

    pcm_file.seekg(0, std::ios::end);
    const int64_t total_bytes = static_cast<int64_t>(pcm_file.tellg());
    pcm_file.seekg(0, std::ios::beg);

    whisper_full_params params = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    params.print_progress = false;
    params.print_special = false;
    params.print_realtime = false;
    params.print_timestamps = false;
    params.translate = false;
    params.no_context = false;
    params.language = "en";
    params.n_threads = cpu_thread_count();

    // Keep chunks short on real phones. A 60s chunk can push whisper.cpp over
    // the native heap limit with the small.en model on some devices.
    constexpr int chunk_seconds = 20;
    constexpr int samples_per_chunk = 16000 * chunk_seconds;
    const int total_samples = static_cast<int>(std::max<int64_t>(0, total_bytes / static_cast<int64_t>(sizeof(int16_t))));
    const int chunk_count = total_samples <= 0 ? 0 : (total_samples + samples_per_chunk - 1) / samples_per_chunk;
    ProgressBridge progress_bridge;
    if (progress_listener != nullptr) {
        env->GetJavaVM(&progress_bridge.vm);
        progress_bridge.listener = env->NewGlobalRef(progress_listener);
        jclass listener_class = env->GetObjectClass(progress_listener);
        progress_bridge.on_progress = env->GetMethodID(listener_class, "onProgress", "(IIIII)V");
        env->DeleteLocalRef(listener_class);
        progress_bridge.chunk_count = chunk_count;
        progress_bridge.chunk_seconds = chunk_seconds;
        progress_bridge.total_samples = total_samples;
        params.progress_callback = vel_whisper_progress_callback;
        params.progress_callback_user_data = &progress_bridge;
    }
    std::vector<float> pcm(samples_per_chunk);
    std::vector<SegmentResult> segments;
    int chunk_index = 0;

    while (read_pcm_chunk(pcm_file, pcm)) {
        const int offset_ms = chunk_index * chunk_seconds * 1000;
        progress_bridge.chunk_index = chunk_index;
        progress_bridge.active_chunk_samples = static_cast<int>(pcm.size());
        report_progress(&progress_bridge, 0);
        LOGI("Running whisper_full low-memory chunk %d (%ds) with %zu samples and %d threads", chunk_index, chunk_seconds, pcm.size(), params.n_threads);
        int result = whisper_full(context, params, pcm.data(), static_cast<int>(pcm.size()));
        if (result != 0) {
            if (progress_bridge.listener != nullptr) env->DeleteGlobalRef(progress_bridge.listener);
            whisper_free(context);
            throw_error(env, "Whisper transcription failed.");
            return nullptr;
        }
        report_progress(&progress_bridge, 100);

        const int segment_count = whisper_full_n_segments(context);
        for (int i = 0; i < segment_count; ++i) {
            const char *text = whisper_full_get_segment_text(context, i);
            if (text == nullptr || text[0] == '\0') continue;
            segments.push_back({
                offset_ms + static_cast<int>(whisper_full_get_segment_t0(context, i) * 10),
                offset_ms + static_cast<int>(whisper_full_get_segment_t1(context, i) * 10),
                text
            });
        }
        chunk_index += 1;
        pcm.assign(samples_per_chunk, 0.0f);
    }

    jclass segment_class = env->FindClass("com/codex/videolearnenglish/WhisperSegment");
    if (segment_class == nullptr) {
        whisper_free(context);
        throw_error(env, "Could not find WhisperSegment class.");
        return nullptr;
    }
    jmethodID constructor = env->GetMethodID(segment_class, "<init>", "(IILjava/lang/String;)V");
    if (constructor == nullptr) {
        whisper_free(context);
        throw_error(env, "Could not find WhisperSegment constructor.");
        return nullptr;
    }

    jobjectArray output = env->NewObjectArray(static_cast<jsize>(segments.size()), segment_class, nullptr);
    for (jsize i = 0; i < static_cast<jsize>(segments.size()); ++i) {
        const SegmentResult &item = segments[static_cast<size_t>(i)];
        jobject segment = make_segment(env, segment_class, constructor, item.start_ms, item.end_ms, item.text.c_str());
        env->SetObjectArrayElement(output, i, segment);
        env->DeleteLocalRef(segment);
    }

    if (progress_bridge.listener != nullptr) {
        env->DeleteGlobalRef(progress_bridge.listener);
    }
    whisper_free(context);
    return output;
}
