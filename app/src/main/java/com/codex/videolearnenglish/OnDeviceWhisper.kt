package com.codex.videolearnenglish

import android.content.Context
import android.media.AudioFormat
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMuxer
import android.net.Uri
import android.util.Log
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import kotlin.math.roundToInt

data class WhisperSegment(
    val startMs: Int,
    val endMs: Int,
    val text: String
)

data class RemoteAudioFile(
    val file: File,
    val durationMs: Int,
    val mimeType: String
)

fun interface WhisperProgressListener {
    fun onProgress(
        percent: Int,
        processedMs: Int,
        totalMs: Int,
        chunkIndex: Int,
        chunkCount: Int
    )
}

class OnDeviceWhisperTranscriber(private val context: Context) {
    val modelDirectory: File
        get() = internalModelDirectory

    private val internalModelDirectory: File
        get() = File(context.filesDir, "models").apply { mkdirs() }

    private val externalModelDirectory: File
        get() = File(context.getExternalFilesDir(null), "models").apply { mkdirs() }

    fun status(): String {
        val model = preferredModelFile()
        return when {
            model == null -> {
                "没有找到本机 Whisper 模型。请把 ggml-small.en.bin 放到：${modelDirectory.path}；当前目录：${modelDirectoryStatus()}"
            }
            !WhisperNative.isAvailable -> "本机 Whisper JNI 库加载失败：${WhisperNative.loadError ?: "未知错误"}"
            else -> "本机 Whisper 已就绪：${model.name}"
        }
    }

    fun canTranscribe(): Boolean {
        return preferredModelFile() != null && WhisperNative.isAvailable
    }

    fun transcribe(
        videoUri: Uri,
        progressListener: WhisperProgressListener? = null
    ): List<WhisperSegment> {
        val model = preferredModelFile() ?: error("没有找到本机 Whisper 模型。")
        if (!WhisperNative.isAvailable) error("本机 Whisper JNI 库还没有接入。")
        val pcm = AudioPcmExtractor(context).decodeToMono16KhzFile(videoUri)
        Log.i("OnDeviceWhisper", "Decoded ${pcm.file.length()} bytes of PCM at ${pcm.sampleRate} Hz")
        progressListener?.onProgress(0, 0, pcm.durationMs, 0, 0)
        return try {
            WhisperNative.transcribe(model.absolutePath, pcm.file.absolutePath, pcm.sampleRate, progressListener)
        } finally {
            pcm.file.delete()
        }
    }

    fun extractAudioForRemoteUpload(
        videoUri: Uri,
        progress: ((Int) -> Unit)? = null
    ): RemoteAudioFile {
        val aac = cachedRemoteAudioFile(videoUri, "m4a")
        if (aac.exists() && aac.length() > 0L) {
            if (aac.length() <= MAX_CACHED_REMOTE_AAC_BYTES) {
                return RemoteAudioFile(aac, 0, "audio/mp4")
            }
            aac.delete()
        }
        copyCompressedAudioTrackForRemoteUpload(videoUri) { percent ->
            progress?.invoke(percent.coerceIn(0, 100))
        }?.let { copied ->
            if (copied.file.length() <= MAX_CACHED_REMOTE_AAC_BYTES) {
                Log.i("OnDeviceWhisper", "Using copied AAC audio ${copied.file.length()} bytes")
                return copied
            }
            Log.i(
                "OnDeviceWhisper",
                "Copied AAC audio is ${copied.file.length()} bytes; recompressing for remote upload"
            )
            copied.file.delete()
        }
        val pcm = AudioPcmExtractor(context).decodeToMono16KhzFile(videoUri) { percent ->
            progress?.invoke((percent * 75 / 100).coerceIn(0, 75))
        }
        try {
            runCatching {
                encodePcm16ToAacM4a(pcm.file, aac, pcm.sampleRate) { percent ->
                    progress?.invoke((75 + percent * 25 / 100).coerceIn(75, 100))
                }
            }.onSuccess {
                if (aac.exists() && aac.length() > 0L) {
                    return RemoteAudioFile(aac, pcm.durationMs, "audio/mp4")
                }
            }.onFailure {
                aac.delete()
            }
            val wav = cachedRemoteAudioFile(videoUri, "wav")
            if (wav.exists() && wav.length() > 44L) {
                return RemoteAudioFile(wav, pcm.durationMs, "audio/wav")
            }
            writePcm16Wav(pcm.file, wav, pcm.sampleRate)
            return RemoteAudioFile(wav, pcm.durationMs, "audio/wav")
        } finally {
            pcm.file.delete()
        }
    }

    private fun encodePcm16ToAacM4a(
        pcmFile: File,
        outputFile: File,
        sampleRate: Int,
        progress: ((Int) -> Unit)? = null
    ) {
        val tempFile = File(outputFile.parentFile, "${outputFile.name}.tmp")
        tempFile.delete()
        var codec: MediaCodec? = null
        var muxer: MediaMuxer? = null
        var muxerStarted = false
        val totalSamples = (pcmFile.length() / BYTES_PER_PCM16_SAMPLE).coerceAtLeast(1L)
        try {
            val format = MediaFormat.createAudioFormat("audio/mp4a-latm", sampleRate, 1).apply {
                setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC)
                setInteger(MediaFormat.KEY_BIT_RATE, REMOTE_AAC_BITRATE)
                setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 16 * 1024)
            }
            codec = MediaCodec.createEncoderByType("audio/mp4a-latm")
            codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
            muxer = MediaMuxer(tempFile.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
            codec.start()

            val bufferInfo = MediaCodec.BufferInfo()
            val inputChunk = ByteArray(16 * 1024)
            var inputDone = false
            var outputDone = false
            var submittedSamples = 0L
            var outputTrack = -1
            FileInputStream(pcmFile).use { input ->
                while (!outputDone) {
                    if (!inputDone) {
                        val inputIndex = codec.dequeueInputBuffer(TIMEOUT_US)
                        if (inputIndex >= 0) {
                            val inputBuffer = codec.getInputBuffer(inputIndex)
                            inputBuffer?.clear()
                            val maxBytes = inputBuffer?.remaining()?.coerceAtMost(inputChunk.size) ?: 0
                            val read = if (maxBytes > 0) input.read(inputChunk, 0, maxBytes) else -1
                            val presentationTimeUs = submittedSamples * 1_000_000L / sampleRate
                            if (read <= 0) {
                                codec.queueInputBuffer(
                                    inputIndex,
                                    0,
                                    0,
                                    presentationTimeUs,
                                    MediaCodec.BUFFER_FLAG_END_OF_STREAM
                                )
                                inputDone = true
                            } else {
                                inputBuffer?.put(inputChunk, 0, read)
                                codec.queueInputBuffer(inputIndex, 0, read, presentationTimeUs, 0)
                                submittedSamples += read / BYTES_PER_PCM16_SAMPLE
                                progress?.invoke((submittedSamples * 100 / totalSamples).toInt().coerceIn(0, 99))
                            }
                        }
                    }

                    when (val outputIndex = codec.dequeueOutputBuffer(bufferInfo, TIMEOUT_US)) {
                        MediaCodec.INFO_TRY_AGAIN_LATER -> Unit
                        MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                            outputTrack = muxer.addTrack(codec.outputFormat)
                            muxer.start()
                            muxerStarted = true
                        }
                        else -> if (outputIndex >= 0) {
                            val outputBuffer = codec.getOutputBuffer(outputIndex)
                            if (outputBuffer != null && bufferInfo.size > 0 && muxerStarted) {
                                outputBuffer.position(bufferInfo.offset)
                                outputBuffer.limit(bufferInfo.offset + bufferInfo.size)
                                muxer.writeSampleData(outputTrack, outputBuffer, bufferInfo)
                            }
                            outputDone = bufferInfo.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0
                            codec.releaseOutputBuffer(outputIndex, false)
                        }
                    }
                }
            }
            codec.stop()
            codec.release()
            codec = null
            if (muxerStarted) muxer.stop()
            muxer.release()
            muxer = null
            if (outputFile.exists()) outputFile.delete()
            if (!tempFile.renameTo(outputFile)) {
                tempFile.copyTo(outputFile, overwrite = true)
                tempFile.delete()
            }
            progress?.invoke(100)
        } finally {
            runCatching { codec?.stop() }
            runCatching { codec?.release() }
            runCatching { if (muxerStarted) muxer?.stop() }
            runCatching { muxer?.release() }
            tempFile.delete()
        }
    }

    fun deleteCachedRemoteAudio(videoUri: Uri) {
        val prefix = remoteAudioCacheKey(videoUri)
        remoteAudioCacheDirectory.listFiles()
            ?.filter { it.name.startsWith(prefix) }
            ?.forEach { it.delete() }
    }

    private fun copyCompressedAudioTrackForRemoteUpload(
        videoUri: Uri,
        progress: ((Int) -> Unit)?
    ): RemoteAudioFile? {
        val extractor = MediaExtractor()
        var muxer: MediaMuxer? = null
        try {
            extractor.setDataSource(context, videoUri, null)
            val trackIndex = findAudioTrack(extractor)
            if (trackIndex < 0) error("视频里没有可识别的音频轨道。")
            val format = extractor.getTrackFormat(trackIndex)
            val mime = format.getString(MediaFormat.KEY_MIME).orEmpty()
            if (mime != "audio/mp4a-latm") return null
            val durationUs = if (format.containsKey(MediaFormat.KEY_DURATION)) {
                format.getLong(MediaFormat.KEY_DURATION)
            } else {
                0L
            }
            val outputFile = cachedRemoteAudioFile(videoUri, "m4a")
            if (outputFile.exists() && outputFile.length() > 0L) {
                return RemoteAudioFile(outputFile, (durationUs / 1000L).toInt(), "audio/mp4")
            }
            val tempFile = File(outputFile.parentFile, "${outputFile.name}.tmp")
            tempFile.delete()
            extractor.selectTrack(trackIndex)
            muxer = MediaMuxer(tempFile.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
            val outputTrack = muxer.addTrack(format)
            muxer.start()

            val maxInputSize = if (format.containsKey(MediaFormat.KEY_MAX_INPUT_SIZE)) {
                format.getInteger(MediaFormat.KEY_MAX_INPUT_SIZE).coerceAtLeast(256 * 1024)
            } else {
                256 * 1024
            }
            val buffer = ByteBuffer.allocate(maxInputSize)
            val info = MediaCodec.BufferInfo()
            while (true) {
                buffer.clear()
                val sampleSize = extractor.readSampleData(buffer, 0)
                if (sampleSize < 0) break
                info.set(
                    0,
                    sampleSize,
                    extractor.sampleTime.coerceAtLeast(0L),
                    extractor.sampleFlags
                )
                muxer.writeSampleData(outputTrack, buffer, info)
                if (durationUs > 0) {
                    progress?.invoke((extractor.sampleTime * 100 / durationUs).toInt().coerceIn(0, 99))
                }
                extractor.advance()
            }
            muxer.stop()
            muxer.release()
            muxer = null
            if (outputFile.exists()) outputFile.delete()
            if (!tempFile.renameTo(outputFile)) {
                tempFile.copyTo(outputFile, overwrite = true)
                tempFile.delete()
            }
            progress?.invoke(100)
            return RemoteAudioFile(outputFile, (durationUs / 1000L).toInt(), "audio/mp4")
        } catch (error: Exception) {
            Log.w("OnDeviceWhisper", "Could not copy compressed audio track", error)
            return null
        } finally {
            runCatching { muxer?.stop() }
            runCatching { muxer?.release() }
            extractor.release()
        }
    }

    private fun findAudioTrack(extractor: MediaExtractor): Int {
        for (i in 0 until extractor.trackCount) {
            val format = extractor.getTrackFormat(i)
            val mime = format.getString(MediaFormat.KEY_MIME).orEmpty()
            if (mime.startsWith("audio/")) return i
        }
        return -1
    }

    private val remoteAudioCacheDirectory: File
        get() = File(context.filesDir, "remote_audio_cache").apply { mkdirs() }

    private fun cachedRemoteAudioFile(videoUri: Uri, extension: String): File {
        return File(remoteAudioCacheDirectory, "${remoteAudioCacheKey(videoUri)}.$extension")
    }

    private fun remoteAudioCacheKey(videoUri: Uri): String {
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(videoUri.toString().toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }
    }

    private fun writePcm16Wav(pcmFile: File, wavFile: File, sampleRate: Int) {
        val dataSize = pcmFile.length()
        RandomAccessFile(wavFile, "rw").use { wav ->
            wav.setLength(0)
            writeAscii(wav, "RIFF")
            writeIntLe(wav, (36 + dataSize).toInt())
            writeAscii(wav, "WAVE")
            writeAscii(wav, "fmt ")
            writeIntLe(wav, 16)
            writeShortLe(wav, 1)
            writeShortLe(wav, 1)
            writeIntLe(wav, sampleRate)
            writeIntLe(wav, sampleRate * 2)
            writeShortLe(wav, 2)
            writeShortLe(wav, 16)
            writeAscii(wav, "data")
            writeIntLe(wav, dataSize.toInt())
            FileInputStream(pcmFile).use { input ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val read = input.read(buffer)
                    if (read <= 0) break
                    wav.write(buffer, 0, read)
                }
            }
        }
    }

    private fun writeAscii(file: RandomAccessFile, text: String) {
        file.write(text.toByteArray(Charsets.US_ASCII))
    }

    private fun writeIntLe(file: RandomAccessFile, value: Int) {
        file.write(value and 0xFF)
        file.write((value ushr 8) and 0xFF)
        file.write((value ushr 16) and 0xFF)
        file.write((value ushr 24) and 0xFF)
    }

    private fun writeShortLe(file: RandomAccessFile, value: Int) {
        file.write(value and 0xFF)
        file.write((value ushr 8) and 0xFF)
    }

    private fun preferredModelFile(): File? {
        val names = listOf(
            "ggml-medium.en.bin",
            "ggml-small.en.bin",
            "ggml-base.en.bin",
            "ggml-tiny.en.bin"
        )
        return names
            .flatMap { name -> candidateModelDirectories().map { File(it, name) } }
            .firstOrNull { it.exists() && it.length() > 0L }
    }

    private fun candidateModelDirectories(): List<File> {
        return listOf(internalModelDirectory, externalModelDirectory)
    }

    private fun modelDirectoryStatus(): String {
        return candidateModelDirectories().joinToString("；") { dir ->
            val files = dir.listFiles()
                ?.joinToString { "${it.name}(${it.length() / 1024 / 1024}MB)" }
                .orEmpty()
                .ifBlank { "空目录" }
            "${dir.path}=$files"
        }
    }

    private companion object {
        private const val REMOTE_AAC_BITRATE = 48_000
        private const val MAX_CACHED_REMOTE_AAC_BYTES = 80L * 1024L * 1024L
        private const val BYTES_PER_PCM16_SAMPLE = 2
        private const val TIMEOUT_US = 10_000L
    }
}

object WhisperNative {
    val loadError: String?

    val isAvailable: Boolean

    init {
        val result = runCatching {
            System.loadLibrary("whisper_jni")
        }
        isAvailable = result.isSuccess
        loadError = result.exceptionOrNull()?.message
        if (isAvailable) {
            Log.i(TAG, "Loaded whisper_jni")
        } else {
            Log.e(TAG, "Failed to load whisper_jni", result.exceptionOrNull())
        }
    }

    fun transcribe(
        modelPath: String,
        pcmPath: String,
        sampleRate: Int,
        progressListener: WhisperProgressListener?
    ): List<WhisperSegment> {
        return nativeTranscribePcmFile(modelPath, pcmPath, sampleRate, progressListener).toList()
    }

    private external fun nativeTranscribePcmFile(
        modelPath: String,
        pcmPath: String,
        sampleRate: Int,
        progressListener: WhisperProgressListener?
    ): Array<WhisperSegment>

    private const val TAG = "WhisperNative"
}

private data class PcmAudio(
    val file: File,
    val sampleRate: Int,
    val durationMs: Int
)

private class AudioPcmExtractor(private val context: Context) {
    fun decodeToMono16KhzFile(uri: Uri, progress: ((Int) -> Unit)? = null): PcmAudio {
        val extractor = MediaExtractor()
        val outputFile = File.createTempFile("whisper_audio_", ".pcm", context.cacheDir)
        val writer = Pcm16Writer(outputFile)
        var decoder: MediaCodec? = null
        try {
            extractor.setDataSource(context, uri, null)
            val trackIndex = findAudioTrack(extractor)
            if (trackIndex < 0) error("视频里没有可识别的音频轨道。")
            extractor.selectTrack(trackIndex)

            val inputFormat = extractor.getTrackFormat(trackIndex)
            val mime = inputFormat.getString(MediaFormat.KEY_MIME) ?: error("音频轨道缺少 MIME。")
            val durationUs = if (inputFormat.containsKey(MediaFormat.KEY_DURATION)) {
                inputFormat.getLong(MediaFormat.KEY_DURATION)
            } else {
                0L
            }
            decoder = MediaCodec.createDecoderByType(mime)
            decoder.configure(inputFormat, null, null, 0)
            decoder.start()

            decodeLoop(extractor, decoder, writer, durationUs, progress)
        } finally {
            writer.close()
            runCatching { decoder?.stop() }
            runCatching { decoder?.release() }
            extractor.release()
        }
        val samples = outputFile.length() / BYTES_PER_PCM16_SAMPLE
        val durationMs = (samples * 1000 / TARGET_SAMPLE_RATE).toInt()
        return PcmAudio(outputFile, TARGET_SAMPLE_RATE, durationMs)
    }

    private fun findAudioTrack(extractor: MediaExtractor): Int {
        for (i in 0 until extractor.trackCount) {
            val format = extractor.getTrackFormat(i)
            val mime = format.getString(MediaFormat.KEY_MIME).orEmpty()
            if (mime.startsWith("audio/")) return i
        }
        return -1
    }

    private fun decodeLoop(
        extractor: MediaExtractor,
        decoder: MediaCodec,
        outSamples: Pcm16Writer,
        durationUs: Long,
        progress: ((Int) -> Unit)?
    ) {
        val bufferInfo = MediaCodec.BufferInfo()
        var inputDone = false
        var outputDone = false
        var sampleRate = 44_100
        var channelCount = 1
        var pcmEncoding = AudioFormat.ENCODING_PCM_16BIT

        while (!outputDone) {
            if (!inputDone) {
                val inputIndex = decoder.dequeueInputBuffer(TIMEOUT_US)
                if (inputIndex >= 0) {
                    val inputBuffer = decoder.getInputBuffer(inputIndex)
                    val sampleSize = if (inputBuffer == null) -1 else {
                        inputBuffer.clear()
                        extractor.readSampleData(inputBuffer, 0)
                    }
                    if (sampleSize < 0) {
                        decoder.queueInputBuffer(
                            inputIndex,
                            0,
                            0,
                            0L,
                            MediaCodec.BUFFER_FLAG_END_OF_STREAM
                        )
                        inputDone = true
                    } else {
                        decoder.queueInputBuffer(
                            inputIndex,
                            0,
                            sampleSize,
                            extractor.sampleTime.coerceAtLeast(0L),
                            0
                        )
                        if (durationUs > 0) {
                            progress?.invoke((extractor.sampleTime * 100 / durationUs).toInt().coerceIn(0, 99))
                        }
                        extractor.advance()
                    }
                }
            }

            when (val outputIndex = decoder.dequeueOutputBuffer(bufferInfo, TIMEOUT_US)) {
                MediaCodec.INFO_TRY_AGAIN_LATER -> Unit
                MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                    val outputFormat = decoder.outputFormat
                    sampleRate = outputFormat.getInteger(MediaFormat.KEY_SAMPLE_RATE)
                    channelCount = outputFormat.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
                    pcmEncoding = if (outputFormat.containsKey(MediaFormat.KEY_PCM_ENCODING)) {
                        outputFormat.getInteger(MediaFormat.KEY_PCM_ENCODING)
                    } else {
                        AudioFormat.ENCODING_PCM_16BIT
                    }
                }
                else -> if (outputIndex >= 0) {
                    val outputBuffer = decoder.getOutputBuffer(outputIndex)
                    if (outputBuffer != null && bufferInfo.size > 0) {
                        outputBuffer.position(bufferInfo.offset)
                        outputBuffer.limit(bufferInfo.offset + bufferInfo.size)
                        appendResampledMono(
                            outputBuffer.slice().order(ByteOrder.LITTLE_ENDIAN),
                            sampleRate,
                            channelCount,
                            pcmEncoding,
                            outSamples
                        )
                    }
                    outputDone = bufferInfo.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0
                    decoder.releaseOutputBuffer(outputIndex, false)
                }
            }
        }
    }

    private fun appendResampledMono(
        buffer: ByteBuffer,
        sourceRate: Int,
        channelCount: Int,
        pcmEncoding: Int,
        outSamples: Pcm16Writer
    ) {
        val mono = when (pcmEncoding) {
            AudioFormat.ENCODING_PCM_FLOAT -> readFloatMono(buffer, channelCount)
            else -> readInt16Mono(buffer, channelCount)
        }
        if (sourceRate == TARGET_SAMPLE_RATE) {
            mono.forEach { outSamples.writeFloat(it) }
            return
        }
        val outputSize = (mono.size.toDouble() * TARGET_SAMPLE_RATE / sourceRate).roundToInt()
        if (outputSize <= 0) return
        for (i in 0 until outputSize) {
            val sourcePosition = i.toDouble() * sourceRate / TARGET_SAMPLE_RATE
            val left = sourcePosition.toInt().coerceIn(0, mono.lastIndex)
            val right = (left + 1).coerceAtMost(mono.lastIndex)
            val fraction = (sourcePosition - left).toFloat()
            outSamples.writeFloat(mono[left] * (1f - fraction) + mono[right] * fraction)
        }
    }

    private fun readInt16Mono(buffer: ByteBuffer, channelCount: Int): FloatArray {
        val frameCount = buffer.remaining() / 2 / channelCount.coerceAtLeast(1)
        val result = FloatArray(frameCount)
        for (frame in 0 until frameCount) {
            var sum = 0f
            repeat(channelCount.coerceAtLeast(1)) {
                sum += buffer.short / 32768f
            }
            result[frame] = sum / channelCount.coerceAtLeast(1)
        }
        return result
    }

    private fun readFloatMono(buffer: ByteBuffer, channelCount: Int): FloatArray {
        val frameCount = buffer.remaining() / 4 / channelCount.coerceAtLeast(1)
        val result = FloatArray(frameCount)
        for (frame in 0 until frameCount) {
            var sum = 0f
            repeat(channelCount.coerceAtLeast(1)) {
                sum += buffer.float
            }
            result[frame] = sum / channelCount.coerceAtLeast(1)
        }
        return result
    }

    private companion object {
        private const val TARGET_SAMPLE_RATE = 16_000
        private const val BYTES_PER_PCM16_SAMPLE = 2
        private const val TIMEOUT_US = 10_000L
    }
}

private class Pcm16Writer(file: File) {
    private val stream = FileOutputStream(file)
    private val buffer = ByteArray(8192)
    private var position = 0

    fun writeFloat(value: Float) {
        val sample = (value.coerceIn(-1f, 1f) * 32767f).roundToInt().coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt())
        if (position + 2 > buffer.size) flush()
        buffer[position] = (sample and 0xFF).toByte()
        buffer[position + 1] = ((sample ushr 8) and 0xFF).toByte()
        position += 2
    }

    fun close() {
        flush()
        stream.close()
    }

    private fun flush() {
        if (position > 0) {
            stream.write(buffer, 0, position)
            position = 0
        }
    }
}
