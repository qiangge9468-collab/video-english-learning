# 看视频学英语

一个 Android 英语视频学习 App：导入本地视频后，可以自动生成英文字幕和中文字幕，按句复读，点击单词查中文释义和发音，并把字幕、播放进度和单词本保存在本机。

这个仓库是远程 Whisper 版本。手机负责播放视频、抽取音频和学习交互；电脑负责运行 Whisper 字幕服务。这样即使手机性能一般，也可以得到比较稳定的字幕识别效果。

## 功能概览

- 导入手机里的本地视频文件。
- 导入已有 SRT 字幕。
- 从视频中抽取 16 kHz mono WAV 音频并上传到电脑 Whisper 服务。
- 电脑端使用 `faster-whisper` 生成英文字幕，可同时生成中文翻译。
- 支持 USB 调试、本地局域网或 Cloudflare Tunnel 远程连接电脑服务。
- 字幕按视频 URI 缓存在 App 私有目录，再次打开同一视频会自动加载。
- 支持英文、中文、双语三种字幕显示模式。
- 支持整段播放、单句复读、上一句、下一句。
- 支持字幕整体提前/延后 0.5 秒微调。
- 点击当前英文句子中的单词可查中文释义、音标、英文释义和例句。
- 支持系统 TextToSpeech 发音。
- 支持单词本，保存查过的单词及对应视频句子。
- 保留手机端 `whisper.cpp` native 管线，默认关闭，可按需启用。

## 安装包

仓库的 `release/` 目录用于放可直接安装的 APK：

```text
release/app-debug.apk
release/SHA256SUMS.txt
```

安装方式：

1. 在 Android 手机上打开 `release/app-debug.apk`。
2. 按系统提示允许安装来自当前来源的应用。
3. 安装完成后打开“看视频学英语”。

如果使用 adb 安装：

```powershell
adb install -r release/app-debug.apk
```

当前 APK 包名是：

```text
com.codex.videolearnenglish.remote
```

它可以和原版包名不同的旧版本并存安装。

## 快速使用

### 1. 准备视频

把要学习的英文视频放到手机里，例如 `Download` 目录。App 只读取你选择的视频，不会扫描整台手机。

### 2. 打开视频

1. 打开 App。
2. 点“导入”。
3. 选择本地视频文件。
4. 视频加载成功后，可以先点“播放”确认画面和声音正常。

### 3. 使用已有字幕

如果你已经有 SRT 字幕：

1. 点“字幕”。
2. 选择 `.srt` 文件。
3. 字幕会出现在右侧或下方列表中。
4. 点任意一句，App 会跳转到该句并开始单句复读。

SRT 支持两种常见格式：

```text
1
00:00:01,000 --> 00:00:03,000
This is the English subtitle.
这是中文字幕。
```

如果只有英文行，也可以正常使用。后续可点“生成”补中文翻译。

### 4. 自动生成字幕

没有字幕时，点“生成”。App 会：

1. 从当前视频抽取音频。
2. 把 WAV 音频上传到电脑 Whisper 服务。
3. 显示上传和识别进度。
4. 下载识别结果。
5. 保存到本机字幕缓存。

第一次使用前需要先启动电脑端服务，见下方“电脑端 Whisper 服务”。

### 5. 学习操作

常用按钮说明：

| 按钮 | 作用 |
| --- | --- |
| 播放/暂停 | 正常播放或暂停视频 |
| 导入 | 选择本地视频 |
| 上句/下句 | 切换当前复读句子 |
| 翻译关/翻译开 | 当前句子是否显示中文翻译 |
| 英文/双语/中文 | 切换字幕列表显示模式 |
| Loop On/Loop Off | 开关单句循环 |
| 复读 | 从当前句开头重新播放 |
| 生成 | 自动生成字幕 |
| 字幕 | 导入 SRT 字幕 |
| 早0.5秒 | 字幕整体提前 0.5 秒 |
| 晚0.5秒 | 字幕整体延后 0.5 秒 |
| 导出 | 导出当前字幕，可选择英文字幕或英中双字幕 |
| 单词本 | 查看已保存的查词记录 |

### 6. 查词和发音

字幕生成或导入后：

1. 点字幕列表中的一句。
2. 上方当前句会显示英文。
3. 点英文句子里的单词。
4. 弹窗显示中文释义、音标、英文释义和例句。
5. 点“发音”播放该单词读音。
6. 查过的单词会进入单词本。

### 7. 导出字幕

字幕生成或导入后，可以点“导出”保存 SRT 文件：

1. 点第三行按钮里的“导出”。
2. 选择“只导出英文字幕”或“导出英中双字幕”。
3. 在系统文件保存窗口里选择保存位置和文件名。
4. 导出的文件可以用于播放器、剪辑软件或继续分享给其他设备。

## 电脑端 Whisper 服务

手机自动生成字幕时，需要电脑运行一个 Whisper HTTP 服务。手机负责从视频里抽取音频并上传，电脑负责识别字幕并把结果返回给手机。

最重要的一点：手机端“长按生成”可以打开服务地址设置页。每次换网络环境时，先长按“生成”，把服务地址改成对应环境的地址，点“测试”成功后，再返回点“生成”。

### 环境要求

- Windows 10/11、macOS 或 Linux。
- Python 3.10+。
- FFmpeg，建议加入 `PATH`。
- 足够的磁盘空间存放 Whisper 模型。
- CPU 可用；NVIDIA GPU + CUDA 会更快。

安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
```

如果还没有 FFmpeg，Windows 可以用 winget 安装：

```powershell
winget install --id Gyan.FFmpeg
```

### 模型目录

推荐把 faster-whisper 模型放在仓库的 `models/` 目录。该目录默认被 Git 忽略，因为模型通常很大，不适合直接提交到仓库。

推荐目录名：

```text
models/faster-whisper-small/
models/faster-whisper-medium/
models/faster-whisper-medium（Multilingual model）/
```

每个模型目录里应包含 `model.bin` 等模型文件。服务会按以下逻辑选择模型：

| 场景 | 优先模型 |
| --- | --- |
| 语言检测 | `models/faster-whisper-small`，然后 multilingual medium |
| 英文字幕 | `models/faster-whisper-small`，然后 `models/faster-whisper-medium` |
| 其他语言 | multilingual medium |

如果本地模型目录不存在，`faster-whisper` 会尝试按模型名加载，例如 `small.en`。这可能触发联网下载。

## 自动生成字幕：完整步骤

### 第一步：电脑端启动服务

先进入项目目录：

```powershell
cd C:\tmp\video-english-learning-remote
```

然后根据手机和电脑的连接环境选择一个脚本。

| 使用环境 | 电脑端脚本 | App 服务地址 |
| --- | --- | --- |
| Android 模拟器 | `tools/start_remote_whisper_service.ps1` | `http://10.0.2.2:8765/transcribe` |
| 真机 USB 调试 | `tools/start_remote_whisper_service.ps1` | `http://127.0.0.1:8765/transcribe` |
| 手机和电脑同一 Wi-Fi | `tools/start_lan_whisper_service.ps1` | 服务窗口打印的 `http://电脑IP:8765/transcribe` |
| 手机用流量、异地、不同 Wi-Fi | `tools/start_public_whisper_service.ps1` | Cloudflare 打印的 `https://xxxxx.trycloudflare.com/transcribe?token=...` |

### 第二步：手机端设置服务地址

1. 打开 App，先点“导入”选择视频。
2. 长按“生成”，进入 Whisper 服务设置页。
3. 填入对应环境的服务地址。
4. 点“测试”。看到连接正常后返回。
5. 点“生成”，App 会抽取音频、上传到电脑、等待 Whisper 识别并保存字幕。

生成过程中可以短暂切到后台。App 会尽量用前台服务继续上传和轮询任务，但不要在系统后台清理里强行结束 App，也不要关闭电脑端 PowerShell 服务窗口。

## 不同环境的连接方法

### 方式 A：Android 模拟器

在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_remote_whisper_service.ps1
```

模拟器访问电脑主机要使用 Android Emulator 的特殊地址：

```text
http://10.0.2.2:8765/transcribe
```

在 App 里长按“生成”，填上这个地址，点“测试”，成功后再点“生成”。

### 方式 B：真机 USB 调试

适合开发调试。手机通过 USB 连接电脑并开启 USB 调试。

电脑端运行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_remote_whisper_service.ps1
```

这个脚本会启动 Whisper 服务，并尝试自动配置：

```powershell
adb reverse tcp:8765 tcp:8765
```

如果你想手动配置，也可以运行：

```powershell
adb devices
adb reverse --remove tcp:8765
adb reverse tcp:8765 tcp:8765
```

App 里长按“生成”，服务地址填：

```text
http://127.0.0.1:8765/transcribe
```

点“测试”，提示连接正常后，再点“生成”。

如果电脑服务实际端口不是 8765，例如 8767：

```powershell
adb reverse --remove tcp:8765
adb reverse tcp:8765 tcp:8767
```

手机端地址仍然填：

```text
http://127.0.0.1:8765/transcribe
```

### 方式 C：手机和电脑在同一个局域网

如果手机和电脑在同一个 Wi-Fi，可以不连接 USB，也不需要 `adb reverse`。

电脑端运行：

```powershell
cd C:\tmp\video-english-learning-remote
powershell -ExecutionPolicy Bypass -File tools/start_lan_whisper_service.ps1
```

服务窗口会打印可用地址，例如：

```text
http://192.168.0.133:8765/transcribe
```

App 里长按“生成”，填服务窗口打印的地址。注意不要填 `127.0.0.1`，在手机上 `127.0.0.1` 指的是手机自己，不是电脑。

可以用下面的脚本做电脑端自检：

```powershell
powershell -ExecutionPolicy Bypass -File tools/test_lan_whisper_service.ps1
```

如果手机无法连通，通常是以下原因：

- 手机和电脑没有连到同一个 Wi-Fi。
- 手机连了访客网络，路由器开启了“AP 隔离/客户端隔离”。
- Windows 防火墙没有允许 Python 在“专用网络”通信。
- App 地址填成了虚拟网卡 IP、`127.0.0.1`、`10.0.2.2` 或已经变化的旧电脑 IP。
- 电脑进入睡眠，或 PowerShell 服务窗口被关闭。

局域网默认不启用 token。如果你用 `-UseAuth` 启动，或环境里主动设置了 `WHISPER_AUTH_TOKEN`，服务窗口会打印带 token 的完整地址，例如：

```text
http://192.168.0.133:8765/transcribe?token=xxxx
```

这种情况下 App 必须填写完整地址，否则会出现 `HTTP 401` 或 `Broken pipe`。

### 方式 D：手机用流量、异地或不在同一个局域网

这种情况不要直接把 Python 服务端口暴露到公网。推荐用 Cloudflare Tunnel 建一个临时 HTTPS 地址。

先安装 `cloudflared`，二选一：

```powershell
winget install --id Cloudflare.cloudflared
```

或者下载 `cloudflared-windows-amd64.exe`，放到：

```text
tools/cloudflared.exe
```

电脑端只需要开一个 PowerShell 窗口运行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_public_whisper_service.ps1
```

这个脚本会同时做两件事：

- 启动本机 Whisper 服务。
- 启动 Cloudflare Tunnel，并生成一个 `https://xxxxx.trycloudflare.com` 公网地址。

窗口前面会打印类似：

```text
Auth token: 8f3a...
After cloudflared prints an https://xxxxx.trycloudflare.com URL, use this in the Android app:
  https://xxxxx.trycloudflare.com/transcribe?token=8f3a...
```

等 Cloudflare 输出这一行：

```text
Your quick Tunnel has been created! Visit it at:
https://twisted-priced-elevation-volt.trycloudflare.com
```

把上面的域名替换进 App 地址，最终应类似：

```text
https://twisted-priced-elevation-volt.trycloudflare.com/transcribe?token=8f3a...
```

App 里长按“生成”，填这个完整 HTTPS 地址，点“测试”，成功后再点“生成”。手机可以关 Wi-Fi 只用 4G/5G 测试。

公网自检脚本：

```powershell
powershell -ExecutionPolicy Bypass -File tools/test_remote_whisper_service.ps1 -AppUrl "https://xxxxx.trycloudflare.com/transcribe?token=8f3a..."
```

注意事项：

- PowerShell 窗口必须一直开着。关闭窗口后，Cloudflare 地址会失效。
- 每次重新启动 `start_public_whisper_service.ps1`，Cloudflare 免费临时域名通常会变化，需要重新填写 App 地址。
- 不要把没有 token 的本地服务暴露到公网。
- `start_public_whisper_service.ps1` 会自动生成安全 token；如果环境变量里误设了“你的token”这类占位文本，脚本也会忽略并重新生成。

### 方式 E：手动启动服务

如果你不想用脚本，也可以直接启动 Python 服务：

```powershell
$env:WHISPER_AUTH_TOKEN="change-this-token"
$env:WHISPER_PORT="8765"
python tools/local_whisper_service.py
```

本机检查：

```powershell
Invoke-WebRequest "http://127.0.0.1:8765/ping?token=change-this-token"
```

查看模型选择：

```text
http://127.0.0.1:8765/models?token=change-this-token
```

### GPU 加速

如果电脑有可用的 NVIDIA GPU 和 CUDA 环境：

```powershell
$env:WHISPER_DEVICE="cuda"
$env:WHISPER_COMPUTE_TYPE="float16"
powershell -ExecutionPolicy Bypass -File tools/start_remote_whisper_service.ps1
```

CPU 默认参数：

```text
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
```

## Android Studio 构建

### 环境要求

- Android Studio。
- JDK 17。
- Android SDK Platform 35。
- Gradle Wrapper，仓库已包含 `gradlew` 和 `gradlew.bat`。
- 如果启用手机端 `whisper.cpp` native 构建，还需要 Android NDK 和 CMake。

建议把项目放在纯英文路径下。Windows 上 NDK/CMake/ninja 对中文路径兼容性不稳定。

### 构建 debug APK

```powershell
.\gradlew.bat assembleDebug
```

输出位置：

```text
app/build/outputs/apk/debug/app-debug.apk
```

### 启用手机端 whisper.cpp native

远程版本默认关闭手机端 native Whisper：

```properties
enableWhisperNative=false
```

如需启用：

```powershell
.\gradlew.bat -PenableWhisperNative=true assembleDebug
```

启用后需要准备 Android NDK/CMake，并把 GGML 模型放到手机 App 私有模型目录：

```text
/sdcard/Android/data/com.codex.videolearnenglish.remote/files/models/
```

App 查找顺序：

```text
ggml-medium.en.bin
ggml-small.en.bin
ggml-base.en.bin
ggml-tiny.en.bin
```

英语学习建议至少使用 `small.en`。

## 字幕缓存和学习数据

字幕缓存保存在 App 私有目录：

```text
filesDir/subtitles_cache/<video-uri-sha256>.json
```

单词本保存在：

```text
filesDir/wordbook_history.json
```

卸载 App 会删除这些私有数据。重新安装或清除应用数据后，需要重新导入或生成字幕。

## 远程服务 API

App 当前主要使用异步任务接口：

```text
POST /jobs?token=<WHISPER_AUTH_TOKEN>
GET /jobs/<job_id>?token=<WHISPER_AUTH_TOKEN>
```

辅助接口：

```text
GET /ping
GET /models?token=<WHISPER_AUTH_TOKEN>
GET /transcribe?video=backpacking
POST /transcribe?token=<WHISPER_AUTH_TOKEN>
```

返回字幕格式：

```json
[
  {
    "start": 1.23,
    "end": 4.56,
    "text": "This is an English sentence.",
    "translation": "这是一个英文句子。"
  }
]
```

## 仓库结构

```text
app/                         Android App 源码
app/src/main/java/...         Kotlin 主逻辑
app/src/main/cpp/             whisper.cpp JNI 桥接层
app/src/main/assets/          词典和示例字幕
tools/local_whisper_service.py 电脑端 Whisper HTTP 服务
tools/start_remote_whisper_service.ps1 USB/通用启动脚本，会自动配置 adb reverse
tools/start_lan_whisper_service.ps1    局域网启动脚本，会打印手机应填写的电脑 IP 地址
tools/test_lan_whisper_service.ps1     局域网服务自检脚本
tools/start_public_whisper_service.ps1 公网/手机流量一键脚本，会启动服务并创建 Cloudflare Tunnel
tools/test_remote_whisper_service.ps1  公网服务自检脚本
tools/start_cloudflare_tunnel.ps1      旧版 Cloudflare Tunnel 辅助脚本，通常不需要手动使用
third_party/whisper.cpp       whisper.cpp Git submodule
release/                      可安装 APK 和校验文件
requirements.txt              Python 服务依赖
REMOTE_WHISPER.md             远程字幕服务简明说明
```

## 克隆仓库

因为 `third_party/whisper.cpp` 是 submodule，建议这样克隆：

```powershell
git clone --recursive <你的仓库地址>
```

如果已经普通克隆：

```powershell
git submodule update --init --recursive
```

## 开源注意事项

- `local.properties`、`.idea/`、`.gradle/`、`app/build/` 等本机文件不会入库。
- `models/` 和 `*.bin` 默认忽略，避免把大型模型文件提交到 Git。
- `release/` 中的 APK 会被允许入库，便于用户直接下载安装。
- 远程服务 token 不要写进仓库；本地 USB/局域网默认不启用 token。如果要通过公网或不可信网络访问，请使用 `tools/start_public_whisper_service.ps1` 打印的一次性 token。
- 该项目源码使用 MIT License。`third_party/whisper.cpp` 遵循其上游许可证。

## 常见问题

### 点“生成”后连接失败

先长按“生成”，点“测试”确认服务地址可用。

- 模拟器：地址应为 `http://10.0.2.2:8765/transcribe`。
- USB 真机：检查 `adb reverse tcp:8765 tcp:8765` 是否成功，地址应为 `http://127.0.0.1:8765/transcribe`。
- 同一 Wi-Fi：地址应为电脑 Wi-Fi IPv4，例如 `http://192.168.0.133:8765/transcribe`，并确认 Windows 防火墙放行 Python。
- 手机流量/异地：使用 `tools/start_public_whisper_service.ps1`，地址必须是 `https://xxxxx.trycloudflare.com/transcribe?token=...`，并保持 PowerShell 窗口打开。

### 生成字幕失败，提示 `HTTP 401`

这是 token 不匹配。重新看电脑端 PowerShell 窗口打印的 App 地址，把完整地址复制到 App。公网模式下一定要带 `?token=...`。

### 生成字幕失败，提示 `Broken pipe`

通常是上传过程中连接被中断。先不要关闭手机 App 和电脑 PowerShell 窗口，再点“生成”重试；App 会保留已抽取的音频缓存，下次通常可以直接重试上传。公网模式下还要确认 Cloudflare Tunnel 窗口仍在运行，且 App 里填的是当前这次新生成的域名。

### 切到后台后生成字幕失败

电脑端确实负责 Whisper 识别，但手机仍要负责上传音频和轮询任务结果。长视频的音频可能几十 MB，如果系统把 App 后台网络或前台服务杀掉，上传会中断。建议首次生成时保持 App 在前台，或在系统电池设置里允许“看视频学英语”后台运行，并允许通知权限。

### 生成很慢

CPU 运行 Whisper 会比较慢。可以使用更小的模型，或使用 CUDA GPU 并设置 `WHISPER_DEVICE=cuda`、`WHISPER_COMPUTE_TYPE=float16`。

### 中文字幕为空

服务端会优先尝试本地翻译依赖。如果没有安装 Argos Translate 或 Transformers 翻译模型，可能只返回英文字幕。App 端也集成了 ML Kit 英译中，首次使用需要联网下载翻译模型。

### 字幕有轻微提前或延后

使用“早0.5秒”或“晚0.5秒”调整整体偏移。识别质量和时间轴还取决于视频音频质量、背景噪声和模型大小。

### Windows 构建 native 报中文路径错误

把项目复制到纯英文路径，例如：

```text
C:\AndroidProjects\video-english-learning-remote
```

再用 Android Studio 打开。
