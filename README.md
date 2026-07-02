# Video English Learning

一个 Android 英语视频学习 App 原型：导入本地英文视频后，可以按句复读、同步显示字幕、点击当前句单词查中文释义和播放发音，并缓存已经生成或导入过的字幕。

## 当前能力

- 播放本地视频，支持测试视频路径 `/sdcard/Download/Full Gear List for Solo Backpacking.mp4`。
- 导入 SRT 字幕，支持英文字幕和第二行中文翻译。
- 调用 Whisper 服务生成英文字幕和中文翻译。
- 已接入手机端 Whisper 管线：视频音频会解码为 16kHz mono PCM，并通过 JNI 调用 `whisper.cpp`。
- 已有英文字幕时，可以直接在手机端生成中文翻译。
- 字幕按视频 URI 缓存，下次打开同一个视频会自动加载，不必重复生成。
- 上方当前句支持点击单词/短语查中文释义。
- 查词弹窗支持用系统 TextToSpeech 播放英文发音。
- 单句复读会在句尾提前收紧，减少带到下一句开头的问题。

## 使用流程

1. 打开 App。
2. 点“测试”加载默认测试视频，或点“导入”选择手机上的视频文件。
3. 如果已经有 SRT，点“字幕”导入。
4. 如果已有英文字幕但没有中文，点“生成”，App 会优先在手机端补中文翻译。
5. 如果没有字幕，点“生成”会优先尝试手机端 `whisper.cpp`。如果模型或 native 库还没有准备好，会回退到电脑端 Whisper 服务。
6. 点字幕列表中的句子进入单句复读。
7. 点上方当前句中的单词查词，再点“发音”播放单词读音。

## 字幕缓存

导入 SRT 或生成字幕成功后，App 会把字幕保存到应用私有目录：

```text
filesDir/subtitles_cache/<video-uri-sha256>.json
```

再次打开同一个视频时会自动读取缓存字幕。需要更新字幕时，再点“生成”或重新导入 SRT 即可覆盖缓存。

## 手机端中文翻译

App 使用 Google ML Kit Translation 做英译中：

```kotlin
implementation("com.google.mlkit:translate:17.0.3")
```

首次翻译时手机需要联网下载英译中模型。模型下载完成后，后续翻译可在手机端运行，不需要电脑服务器。翻译结果会写入字幕缓存。

注意：翻译准确性依赖英文字幕准确性。建议先确认英文字幕时间轴和文本，再生成中文翻译。

## 手机端 Whisper 字幕生成

字幕生成最重要的是准确性。不要用 Android 系统语音识别来处理视频文件：

- 它主要面向实时麦克风输入，不适合长视频文件。
- 分句和时间戳不稳定。
- 离线能力和机型相关，结果不可控。

推荐借鉴 `whisper.cpp` 的 Android 示例，把 Whisper 模型放到手机端本地推理：

- 项目：https://github.com/ggml-org/whisper.cpp
- Android 示例：https://github.com/ggml-org/whisper.cpp/tree/master/examples/whisper.android

本项目已经拉取 `whisper.cpp` 源码到：

```text
third_party/whisper.cpp
```

并新增了本项目自己的桥接层：

```text
app/src/main/java/com/codex/videolearnenglish/OnDeviceWhisper.kt
app/src/main/cpp/CMakeLists.txt
app/src/main/cpp/whisper_jni.cpp
```

工作流：

1. `OnDeviceWhisperTranscriber` 查找模型文件。
2. `AudioPcmExtractor` 用 Android `MediaExtractor`/`MediaCodec` 从视频 URI 解码音频。
3. 音频会转成 `16kHz mono FloatArray`。
4. `whisper_jni.cpp` 加载 `whisper.cpp` 模型并运行 `whisper_full`。
5. native 层返回 `WhisperSegment(startMs, endMs, text)`。
6. App 转为现有 `SubtitleLine`，保存缓存。

模型放置目录：

```text
/sdcard/Android/data/com.codex.videolearnenglish/files/models/
```

推荐先放：

```text
ggml-small.en.bin
```

App 会按以下顺序选择模型：

```text
ggml-medium.en.bin
ggml-small.en.bin
ggml-base.en.bin
ggml-tiny.en.bin
```

推荐模型选择：

| 模型 | 速度 | 准确性 | 建议 |
| --- | --- | --- | --- |
| `tiny` | 最快 | 较低 | 只用于功能测试 |
| `base` | 快 | 一般 | 短视频粗略可用 |
| `small` | 中等 | 较好 | 推荐给英语学习字幕 |
| `medium` | 慢 | 更好 | 高端手机或短片段使用 |

为了保证准确性，本项目按这个流程设计：

1. 从视频中抽取 16kHz mono PCM 音频。
2. 使用 `whisper.cpp` Android native 层加载 `ggml-small.en.bin` 或更高质量模型。
3. 开启 word/segment timestamp，保留每句开始和结束时间。
4. 对长视频分段识别，每段之间保留少量重叠，避免句子被切断。
5. 对过短、过长或空文本的片段做后处理。
6. 英文字幕稳定后，再调用手机端英译中。
7. 保存缓存，避免重复推理。

## 电脑端 Whisper 服务

当前仍保留电脑端服务作为兜底调试方式：

```powershell
python tools/local_whisper_service.py
```

模拟器默认地址：

```text
http://10.0.2.2:8765/transcribe?video=backpacking
```

真机需要把服务地址改成电脑局域网 IP。长按“生成”可以修改服务地址。

## Android Studio 构建

本机 JDK 路径示例：

```powershell
$env:JAVA_HOME='C:\Program Files\Microsoft\jdk-17.0.19.10-hotspot'
```

构建 debug APK：

```powershell
.\gradlew.bat assembleDebug
```

如果命令不是在项目根目录执行，可以指定项目目录：

```powershell
.\gradlew.bat -p G:\document\手机app\video-english-learning assembleDebug
```

APK 输出位置：

```text
app/build/outputs/apk/debug/app-debug.apk
```

### 启用手机端 whisper.cpp native 编译

当前项目已经在 `gradle.properties` 中打开：

```properties
enableWhisperNative=true
```

所以 Android Studio 直接 Build/Run 时会编译并打包 `whisper.cpp` native 库。命令行也可以这样构建：

```powershell
.\gradlew.bat -PenableWhisperNative=true assembleDebug
```

需要安装的 SDK 组件：

```text
NDK 26.3.11579264
CMake 3.22.1
```

如果命令行报错：

```text
The SDK directory is not writable
```

请在 Android Studio 里安装：

```text
Tools > SDK Manager > SDK Tools > NDK (Side by side)
Tools > SDK Manager > SDK Tools > CMake
```

然后再运行 native 构建命令。

如果只是想临时构建一个不带手机端 Whisper 的 APK，可以把 `gradle.properties` 里的 `enableWhisperNative=true` 改成 `false`。

### Windows 路径注意事项

NDK/CMake/ninja 在 Windows 上对中文路径支持不稳定。如果项目放在：

```text
G:\document\手机app\video-english-learning
```

native 构建可能会把 `手机app` 解析成乱码路径，出现类似错误：

```text
ninja: fatal: chdir to 'G:\document\謇区惻app\...' - No such file or directory
```

解决办法：把整个项目复制到全英文路径再用 Android Studio 打开，例如：

```text
G:\android_projects\video-english-learning
```

或：

```text
C:\AndroidProjects\video-english-learning
```

模型文件也可以继续放在手机 App 目录，不需要重新下载；如果要保留电脑侧备份，把 `models/ggml-small.en.bin` 一起复制过去即可。

## 模拟器调试

查看设备：

```powershell
adb devices
```

安装到 Android Studio 模拟器：

```powershell
adb -s emulator-5554 install -r app/build/outputs/apk/debug/app-debug.apk
```

启动：

```powershell
adb -s emulator-5554 shell am start -n com.codex.videolearnenglish/.LearningActivity
```

查看崩溃日志：

```powershell
adb -s emulator-5554 logcat -d -t 300 | Select-String -Pattern "FATAL EXCEPTION|AndroidRuntime|videolearnenglish"
```

## 后续本机 Whisper 接入清单

- 安装 NDK/CMake。
- 用 `-PenableWhisperNative=true` 编译并修正可能的 CMake 兼容问题。
- 把 `ggml-small.en.bin` 放到 App models 目录。
- 在真机上跑短视频，校验识别速度和时间戳。
- 增加字幕置信度/低质量提示。
- 在识别完成后自动调用手机端英译中。

## 准确性建议

- 英语学习建议至少使用 `small.en` 模型。
- 嘈杂视频可以先用外部工具降噪，再生成字幕。
- 自动分句不是百分百可靠，学习前最好快速检查开头几句和长句。
- 如果一句尾部带到下一句，可以使用“早0.5秒/晚0.5秒”微调整体偏移，或重新生成更好的字幕。
