# 看视频学英语

一个 Android 英语视频学习 App：导入本地视频后，可以自动生成英文字幕和中文字幕，按句复读，点击单词查中文释义和发音，并把字幕、播放进度和单词本保存在本机。

这个仓库是远程 Whisper 版本。手机负责播放视频、抽取音频和学习交互；电脑负责运行 Whisper 字幕服务。这样即使手机性能一般，也可以得到比较稳定的字幕识别效果。

## 功能概览

- 导入手机里的本地视频文件。
- 导入已有 SRT 字幕。
- 从视频中抽取 16 kHz mono WAV 音频并上传到电脑 Whisper 服务。
- 电脑端使用 `faster-whisper` 生成英文字幕，并可通过电脑端翻译接口补全中文翻译。
- v2.0.0 新增底部四个页面：`学习`、`生成字幕中`、`已完成`、`我的`，并加入图标化底部导航、空状态插画和任务视频第一帧预览。
- `生成字幕中` 页面支持一次选择多个视频，后台排队生成英文字幕并自动调用电脑端翻译成中文；任务支持暂停、继续、重试，网络或服务中断时会自动续跑数次。
- `已完成` 页面集中管理已经生成好中英双语字幕的视频，可开始学习、导出、重翻或删除记录。
- `我的` 页面包含作者信息、作者图、单词本入口、详细使用说明、电脑端服务说明、GitHub 链接和版本信息。
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
release/app-v1.0.0.apk
release/app-v2.0.0.apk
release/SHA256SUMS.txt
```

版本说明：

| 安装包 | 版本 | 适合场景 | 主要功能 |
| --- | --- | --- | --- |
| `release/app-v1.0.0.apk` | 1.0.0 | 想继续使用上一版稳定学习界面 | 单个学习界面内完成导入视频、生成字幕、翻译、复读、查词、导出字幕等操作。 |
| `release/app-v2.0.0.apk` | 2.0.0 | 推荐安装的新版本 | 新增底部四页：学习、生成字幕中、已完成、我的；加入图标化导航、作者图、任务视频第一帧预览和空状态插画；支持批量选择多个视频后台排队生成英文字幕和中文翻译；任务可暂停、继续、重试并自动续跑；已完成视频可集中管理、开始学习、导出、重翻或删除。 |

安装方式：

1. 推荐在 Android 手机上打开 `release/app-v2.0.0.apk`。
2. 按系统提示允许安装来自当前来源的应用。
3. 安装完成后打开“看视频学英语”。

如果使用 adb 安装：

```powershell
adb install -r release/app-v2.0.0.apk
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
5. 如果电脑端翻译可用，会继续补全中文字幕。
6. 保存到本机字幕缓存。

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
| 长按英文/双语/中文 | 查看当前中文翻译来源，并选择用电脑端或手机端重新翻译 |
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

同一个电脑端服务也负责更高质量的英译中翻译。App 里点“生成”后，如果已有英文字幕但没有中文翻译，或者切换到“双语/中文”时发现翻译为空，App 会优先请求电脑端 `/translate` 接口；电脑端不可用时会保留英文字幕并提示中文翻译失败，修好服务后可长按“英文/双语/中文”重新翻译。

最重要的一点：手机端“长按生成”可以打开服务地址设置页。每次换网络环境时，先长按“生成”，把服务地址改成对应环境的地址，点“测试”成功后，再返回点“生成”。

如果已经有英文字幕但中文翻译不准，可以长按“英文/双语/中文”按钮。弹窗会显示当前中文字幕来自电脑端、手机端、导入字幕还是旧缓存，并提供两个重新翻译入口：

- 电脑端重翻：优先推荐。手机把已有英文字幕按每批 16 句发送给电脑端 `/translate`，电脑用 `transformers` 模型翻译，手机端会显示类似“电脑端翻译中：16/153”的进度，完成后自动写回本地字幕缓存。
- 手机端重翻：备用方案。手机使用 ML Kit 英译中模型翻译，首次使用需要联网下载模型，准确性通常弱于电脑端。

重新翻译会覆盖当前中文字幕，但会保留英文字幕和时间轴。翻译任务和生成字幕一样在前台服务中运行，切到后台或锁屏后仍会继续，前提是系统没有强行限制 App 后台网络。

### 环境要求

- Windows 10/11、macOS 或 Linux。
- Python 3.10+。
- FFmpeg，建议加入 `PATH`。
- 足够的磁盘空间存放 Whisper 模型。
- CPU 可作为兼容回退；推荐 NVIDIA GPU。当前验证可用组合为：`faster-whisper 1.1.0`、`ctranslate2 4.5.0`、CUDA 12.4 runtime/cuBLAS、cuDNN 9、带 CUDA 的 PyTorch。

安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
```

如果想使用电脑端翻译，也需要安装 `requirements.txt` 里的翻译依赖：`argostranslate`、`transformers`、`sentencepiece`、`torch`。依赖已写在同一个文件里。注意 `requirements.txt` 不能替不同显卡驱动选择正确的 PyTorch CUDA wheel；如果 `torch.version.cuda` 显示 `None`，请按 [PyTorch 官方安装选择器](https://pytorch.org/get-started/locally/) 重新安装与本机驱动匹配的 CUDA 版本。

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
models/faster-distil-whisper-large-v3/
models/faster-whisper-medium（Multilingual model）/
models/nllb-200-distilled-600M/
```

Whisper 模型目录里应包含 `model.bin` 等文件；NLLB 目录里应包含 `config.json`、`tokenizer.json`、`sentencepiece.bpe.model` 和模型权重。服务会按以下逻辑选择模型：

| 场景 | 优先模型 |
| --- | --- |
| 语言检测 | `models/faster-whisper-small`，然后 multilingual medium |
| 英文字幕 | `models/faster-distil-whisper-large-v3`，然后 `models/faster-whisper-medium`，最后 `models/faster-whisper-small` |
| 其他语言 | multilingual medium |
| 英译中 | `models/nllb-200-distilled-600M`；目录不存在时使用 `facebook/nllb-200-distilled-600M` 并尝试下载 |

如果本地模型目录不存在，`faster-whisper` 会尝试按模型名加载，例如 `small.en`。这可能触发联网下载。

一键脚本默认会把英文识别模型设置为 `distil-large-v3`，也就是本地目录 `models/faster-distil-whisper-large-v3/`。同时脚本会启用一组字幕热词和提示词，帮助 Whisper 更准确识别旅行、路线、户外装备类视频里的固定表达，例如 `as the crow flies`、`long way around Africa`、`coast to coast`、`Google Maps`。如果你想临时改回更快但准确率较低的 medium 或 small，可以在启动前设置：

手机端如果看到 `Loading language detector only: faster-whisper-small`，这只表示电脑端正在用小模型快速判断视频语言，并不是正式生成字幕的模型。检测到英文后，进度会继续显示 `Loading subtitle model: faster-distil-whisper-large-v3`，后续英文字幕会由 `distil-large-v3` 生成。

```powershell
$env:WHISPER_ENGLISH_MODEL="medium"
powershell -ExecutionPolicy Bypass -File tools/start_video_english_service.ps1
```

如果某个视频有很多专有名词，也可以启动前自定义热词：

```powershell
$env:WHISPER_HOTWORDS="Prudhoe Bay, Lillooet, Garmin inReach Mini, as the crow flies"
powershell -ExecutionPolicy Bypass -File tools/start_video_english_service.ps1
```

## 自动生成字幕：完整步骤

### 第一步：电脑端启动服务

先进入项目目录：

```powershell
cd C:\tmp\video-english-learning-remote
```

推荐只运行这一行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_video_english_service.ps1
```

这个一键脚本会自动做这些事：

- 启动电脑端 Whisper 字幕服务。
- 默认启用电脑端英译中翻译：`transformers` + `NLLB-200 distilled 600M`，语言方向为 `eng_Latn -> zho_Hans`。
- Whisper 和 NLLB 默认都使用 `auto` 设备选择：各自的 CUDA 运行时可用时使用 GPU，否则打印原因并回退 CPU。
- 默认使用 `faster-distil-whisper-large-v3` 做英文字幕识别，并启用字幕热词提升常见短语识别准确率。
- 默认启用字幕优化翻译，会先修正少量高置信 Whisper 误识别短语，再把机器翻译结果润色成更自然的中文字幕。
- 自动给已连接的 Android 真机配置 `adb reverse`，USB 连接时优先走 USB。
- 打印局域网地址，手机和电脑在同一 Wi-Fi 时可自动切到局域网。
- 如果电脑已安装 `cloudflared`，会自动创建 Cloudflare Tunnel，手机用流量或不在同一局域网时也可以继续连接。
- 生成一个一次性 token，并把 USB、局域网、公网候选地址写入本机运行时配置。App 能从电脑端读取这些候选地址，按 USB -> 局域网 -> 公网的顺序自动选择可用连接。

PowerShell 窗口必须保持打开。关闭窗口后，电脑端字幕和翻译服务都会停止；Cloudflare 临时公网地址也会失效。

电脑端服务运行时，PowerShell 窗口会持续打印运行日志：

- 当前加载的 Whisper 字幕识别模型和设备，例如 `faster-distil-whisper-large-v3 on cuda/float16`。
- 语言检测、正式识别、后处理、翻译等阶段进度。
- 每个后台 job 的 `job id`、百分比、错误信息和完成字幕条数。
- `/translate` 的批次数量和当前翻译批次，例如 `Translation batch 17-32/153`。

### 第二步：手机端生成字幕

1. 打开 App，先点“导入”选择视频。
2. 电脑端一键脚本保持运行。
3. 点“生成”。App 会自动尝试 USB、局域网和公网候选地址，连上后抽取音频、上传到电脑、等待 Whisper 识别并保存字幕。

通常不需要再长按“生成”手动填写地址。只有换了电脑、清除了 App 数据，或公网 Cloudflare 地址变了但手机还没通过 USB/局域网同步到新配置时，才需要长按“生成”手动填写电脑端窗口打印的完整地址。

生成和翻译过程中可以切到后台或锁屏。App 会用前台服务、CPU 唤醒锁和 Wi-Fi 锁继续上传、轮询任务结果、翻译并保存字幕；通知栏会显示当前进度。不要在系统后台清理里强行结束 App，也不要关闭电脑端 PowerShell 服务窗口。如果手机系统限制后台网络，建议在系统电池设置里允许“看视频学英语”后台运行，并允许通知权限。

如果一开始手机走的是 Cloudflare 公网，后来进入同一局域网或插上 USB，App 会在后续轮询和分批翻译时重新检测候选地址，并自动优先切到 USB 或局域网；公网只作为最后兜底。正在上传的单次连接不能无损搬迁，但上传连接一旦中断，重试会重新选择当前最稳定的 USB/局域网/公网地址。

在 `生成字幕中` 页面可以管理后台任务：

- `暂停`：暂停排队、上传、轮询或分批翻译中的任务；已提取的音频缓存和已生成的本地字幕会保留。
- `继续`：把暂停或失败的任务重新放回队列，从缓存音频或缓存字幕继续处理。
- `重试`：清空该任务的失败次数并重新开始这一轮处理。
- 自动续跑：网络断开、电脑端服务临时中断、Cloudflare 地址不稳定等错误会自动续跑数次；连续失败太多次后才会停在失败状态，等待用户手动检查服务后再继续或重试。

每个任务卡左侧会显示视频第一帧缩略图，方便区分多个视频。

### 第三步：电脑端翻译

电脑端翻译不需要在手机里填写第二个地址。App 会根据选中的 `/transcribe` 地址自动推导 `/translate` 地址，例如：

```text
http://127.0.0.1:8765/transcribe              -> http://127.0.0.1:8765/translate
http://192.168.0.133:8765/transcribe          -> http://192.168.0.133:8765/translate
https://xxxxx.trycloudflare.com/transcribe?token=abc
                                               -> https://xxxxx.trycloudflare.com/translate?token=abc
```

一键脚本默认已经使用下面的翻译设置：

```powershell
$env:TRANSLATION_PROVIDER="transformers"
$env:TRANSLATION_MODEL="models/nllb-200-distilled-600M"
$env:TRANSLATION_DEVICE="auto"
$env:TRANSLATION_SOURCE_LANGUAGE="eng_Latn"
$env:TRANSLATION_TARGET_LANGUAGE="zho_Hans"
$env:TRANSLATION_STYLE="subtitle"
```

`TRANSLATION_STYLE=subtitle` 是默认值，用于字幕场景优化。它不会改变接口格式，只是在电脑端翻译前后做轻量修正：例如把 `as the crow flies` 处理成“按直线距离”，把 Whisper 误识别的 `lost way around Africa` 修正为更合理的 `long way around Africa`，再翻译成“绕行非洲的漫长路线”。如果你想看模型未经优化的原始翻译，可以启动前设置：

```powershell
$env:TRANSLATION_STYLE="raw"
powershell -ExecutionPolicy Bypass -File tools/start_video_english_service.ps1
```

脚本优先使用仓库内的 `models/nllb-200-distilled-600M`，所以仓库移动到其他目录后不需要修改绝对路径；本地模型不存在时才使用 Hugging Face 模型 ID。也可以在运行脚本前用 `TRANSLATION_MODEL` 指向其他本地目录或模型 ID。注意使用英文半角引号 `"..."`，不要使用中文弯引号 `“...”`。

## 不同环境的连接方法

日常使用优先用一键脚本：

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_video_english_service.ps1
```

下面的 A/B/C/D/E 是高级排障和手动模式。一般不需要按环境分别运行这些旧脚本。

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

如果手机没有 USB 连接电脑，也不在同一个局域网，只用手机流量直接点“生成”，App 没办法自动知道电脑刚生成的 Cloudflare 临时域名。这种情况下必须先长按“生成”，手动填写电脑窗口打印的完整公网地址，例如 `https://真实域名.trycloudflare.com/transcribe?token=真实token`。如果你先用 USB 或局域网连通过一次，一键脚本会把新的公网候选地址同步给 App，之后拔掉 USB 或切到流量时才可能自动回退到公网地址。

如果脚本提示类似下面这样：

```text
Port 8766 is already in use.
Do not expose an old or unauthenticated Whisper service to the public internet.
```

说明这一轮服务没有真正启动，也没有生成新的可用公网地址。此时不要把窗口上方刚打印的 token 填进手机。你需要二选一：

1. 关闭旧的 Whisper/Cloudflare PowerShell 窗口，再重新运行脚本。
2. 换一个端口启动，例如：

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_public_whisper_service.ps1 -Port 8767
```

只有当你看到 Cloudflare 打印了真实域名，例如 `https://thriller-sacred-divided-appraisal.trycloudflare.com`，才把它和同一窗口里的 `Auth token` 组合成手机端地址：

```text
https://thriller-sacred-divided-appraisal.trycloudflare.com/transcribe?token=窗口里打印的AuthToken
```

不要填写 `https://xxxxx.trycloudflare.com/...`，也不要填写 `http://127.0.0.1:8766/...`。前者只是占位符，后者在手机流量环境下指向手机自己，不是电脑。

公网自检脚本：

```powershell
powershell -ExecutionPolicy Bypass -File tools/test_remote_whisper_service.ps1 -AppUrl "https://xxxxx.trycloudflare.com/transcribe?token=8f3a..."
```

注意事项：

- PowerShell 窗口必须一直开着。关闭窗口后，Cloudflare 地址会失效。
- 每次重新启动 `start_public_whisper_service.ps1`，Cloudflare 免费临时域名通常会变化，需要重新填写 App 地址。
- 使用一键脚本 `tools/start_video_english_service.ps1` 时也是同理：USB 和局域网地址可以自动探测；纯手机流量场景必须通过已同步的运行时配置或手动填写最新 Cloudflare 公网地址。
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

推荐的一键脚本默认设置 `WHISPER_DEVICE=auto`、`WHISPER_COMPUTE_TYPE=auto` 和 `TRANSLATION_DEVICE=auto`。CTranslate2 和 PyTorch 各自检测成功后，Whisper 使用 `cuda/float16`，NLLB 使用 CUDA；任一运行时不可用时只有对应模型回退 CPU。

如果使用 Clash Verge，建议把代理写成 HTTP 代理，例如 `http://127.0.0.1:7897`。优先使用清华 PyPI 源安装 CUDA 运行库：

```powershell
$env:HTTP_PROXY="http://127.0.0.1:7897"
$env:HTTPS_PROXY="http://127.0.0.1:7897"
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --force-reinstall `
  nvidia-cublas-cu12==12.4.5.8 `
  nvidia-cuda-runtime-cu12==12.4.127 `
  nvidia-cuda-nvrtc-cu12==12.4.127 `
  nvidia-cudnn-cu12==9.1.0.70
```

如果 CTranslate2 在 Windows 上仍提示 `cublas64_12.dll is not found or cannot be loaded`，可以把上述包里的 CUDA DLL 复制到 `D:\Anaconda\Lib\site-packages\ctranslate2\`；当前项目调试环境已这样配置过。

先检查两个 Python 运行时是否真的识别到 GPU：

```powershell
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
python -c "import ctranslate2; print(ctranslate2.get_cuda_device_count())"
```

期望最后分别看到 `True` 和大于 `0` 的设备数。如果是 `torch ...+cpu`、`torch.version.cuda` 为 `None`，说明安装的是 CPU 版 PyTorch；请安装与本机驱动匹配的 CUDA 版 PyTorch。如果 CTranslate2 返回 `0`，请检查 NVIDIA 驱动、CUDA 12 runtime/cuBLAS 和 cuDNN 9。

也可以直接跑项目自检脚本，它会真实调用 `models/faster-distil-whisper-large-v3` 做 GPU 识别，并调用 `models/nllb-200-distilled-600M` 做 GPU 翻译：

```powershell
powershell -ExecutionPolicy Bypass -File tools/test_gpu_models.ps1
```

期望看到类似：

```text
Loading Whisper model ...faster-distil-whisper-large-v3 on cuda/float16...
Using Transformers model ...nllb-200-distilled-600M on cuda (eng_Latn->zho_Hans)...
```

自动检测通过后直接启动：

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_video_english_service.ps1
```

如需严格要求 GPU、不可用时立即报错而不是回退，可在启动前设置 `$env:MODEL_DEVICE_FALLBACK="0"`，并把 `WHISPER_DEVICE`、`TRANSLATION_DEVICE` 都设为 `cuda`。

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
POST /translate?token=<WHISPER_AUTH_TOKEN>
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

`POST /translate` 用于只给已有英文字幕补中文翻译。请求体示例：

```json
{
  "texts": [
    "But we don't get to go straight as the crow flies.",
    "This is the lost way around Africa."
  ]
}
```

返回格式：

```json
{
  "translations": [
    "但我们不能走直线过去。",
    "这是绕行非洲的迷路路线。"
  ]
}
```

## 仓库结构

```text
app/                         Android App 源码
app/src/main/java/...         Kotlin 主逻辑
app/src/main/cpp/             whisper.cpp JNI 桥接层
app/src/main/assets/          词典和示例字幕
tools/local_whisper_service.py 电脑端 Whisper HTTP 服务
tools/start_video_english_service.ps1 推荐的一键启动脚本：字幕、翻译、USB、局域网、公网候选地址自动配置
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
- 远程服务 token 不要写进仓库；推荐使用 `tools/start_video_english_service.ps1` 自动生成一次性 token。脚本生成的 `tools/runtime_service_config.json` 是本机运行时配置，已被 Git 忽略。
- 该项目源码使用 MIT License。`third_party/whisper.cpp` 遵循其上游许可证。

## 常见问题

### 点“生成”后连接失败

先确认电脑端只运行这一行，并保持窗口打开：

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_video_english_service.ps1
```

新版 App 会自动尝试 USB、局域网和公网候选地址。排查顺序：

- USB 真机：确认手机已开启 USB 调试并允许本电脑调试；一键脚本会每隔几秒自动配置 `adb reverse`。
- 同一 Wi-Fi：确认手机和电脑在同一个局域网，Windows 防火墙允许 Python 通信。
- 手机流量/异地：确认电脑已安装 `cloudflared`，并且一键脚本窗口里已经打印 Cloudflare 公网地址。
- 如果仍失败，长按“生成”，把一键脚本窗口打印的完整地址手动填进去，再点“测试”。

### 生成字幕失败，提示 `HTTP 401`

这是 token 不匹配。新版一键脚本会自动生成 token，App 正常会从 `/config` 读取带 token 的候选地址。如果你手动填写地址，必须复制 PowerShell 窗口打印的完整地址，不能漏掉 `?token=...`。

### 生成字幕失败，提示 `Broken pipe`

通常是上传过程中连接被中断。先不要关闭手机 App 和电脑 PowerShell 窗口，再点“生成”重试；App 会保留已抽取的音频缓存，下次通常可以直接重试上传。公网模式下还要确认一键脚本窗口仍在运行，且 Cloudflare Tunnel 没有断开。

### 生成字幕失败，提示 `unexpected end of stream`

多数情况下是公网 Cloudflare 地址已经失效、填了旧 tunnel、填了占位域名 `xxxxx.trycloudflare.com`，或电脑端服务窗口已经关闭。重新运行一键脚本：

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_video_english_service.ps1
```

等待 Cloudflare 打印真实 `https://...trycloudflare.com` 域名。App 如果曾通过 USB 或局域网连到电脑，会自动读取新公网候选地址；否则可以长按“生成”手动填完整地址：

```text
https://真实域名.trycloudflare.com/transcribe?token=同一窗口里的AuthToken
```

如果脚本提示端口已被占用，这一轮没有启动成功，需要先关闭旧窗口或换端口，例如 `-Port 8767`。

### 切到后台后生成字幕失败

电脑端确实负责 Whisper 识别和翻译，但手机仍要负责上传音频和轮询任务结果。新版 App 会用前台服务、CPU 唤醒锁和 Wi-Fi 锁支持后台、锁屏继续生成；通知栏进度应该继续变化。如果仍失败，通常是系统电池策略限制了后台网络。请在系统电池设置里允许“看视频学英语”后台运行，并允许通知权限，不要在生成过程中手动清理后台或关闭电脑端服务窗口。

### 生成很慢

先按“GPU 加速”一节运行两条检测命令。一键脚本会自动选择 GPU；如果日志显示回退 CPU，需修复对应的 CTranslate2 或 PyTorch CUDA 环境。GPU 环境暂时无法升级时，可以把 `WHISPER_ENGLISH_MODEL` 设为 `medium` 或 `small`。

### 中文字幕为空

App 会优先请求电脑端 `/translate` 接口补翻译。如果没有安装翻译依赖、模型第一次下载失败，或你填写的 Whisper 地址不可达，就可能只显示英文字幕。先确认电脑端服务能正常生成字幕，再确认启动前设置的翻译环境变量是否正确：

```powershell
$env:TRANSLATION_PROVIDER="transformers"
$env:TRANSLATION_MODEL="models/nllb-200-distilled-600M"
$env:TRANSLATION_DEVICE="auto"
```

然后重新启动对应脚本。手机端不需要额外填写翻译地址，只需要保证长按“生成”里填写的是正确的 `/transcribe` 地址。电脑端翻译不可用时，英文字幕仍会保留；修好电脑端服务后，长按“英文/双语/中文”选择“电脑端重翻”即可重新获取中文字幕。也可以在同一个弹窗里选择“手机端重翻”，使用 ML Kit 英译中作为备用方案。

如果看到下面这种错误：

```text
translation failed: could not load translation model: check_hostname requires server_hostname
```

通常是 Windows/Python 继承了不兼容的本地代理环境变量，例如把 `HTTPS_PROXY` 写成了 `https://127.0.0.1:7890`。新版 `tools/start_video_english_service.ps1` 会自动把这类本地代理修正为 `http://127.0.0.1:7890`。处理方法：

1. 关闭旧的 PowerShell 服务窗口。
2. 重新运行一键脚本：

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_video_english_service.ps1
```

如果仍失败，在同一个 PowerShell 里检查代理变量：

```powershell
Get-ChildItem Env:*proxy*
```

把本地 HTTP 代理写成 `http://127.0.0.1:端口`，不要写成 `https://127.0.0.1:端口`。仓库内没有 `models/nllb-200-distilled-600M` 时，翻译模型第一次加载需要联网下载 `facebook/nllb-200-distilled-600M`，下载成功后会缓存到电脑本地。

### 字幕有轻微提前或延后

使用“早0.5秒”或“晚0.5秒”调整整体偏移。识别质量和时间轴还取决于视频音频质量、背景噪声和模型大小。

### Windows 构建 native 报中文路径错误

把项目复制到纯英文路径，例如：

```text
C:\AndroidProjects\video-english-learning-remote
```

再用 Android Studio 打开。
