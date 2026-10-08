# 本地上下文翻译试用

2026-10-08。用户批准先接入试用，在真实学习中反馈；不是“90% 联合正确率已达标”的发布。手机保持 v2.2.0 / versionCode 29，电脑服务保持 v2.1.0，没有修改或重新打包 APK。

## 接入范围

- 新视频生成字幕和电脑端重翻中文优先使用本地 `qwen3.5:4b-q4_K_M`。每批最多 12 个目标，带前后两句上下文，通过必填编号返回译文。
- 不让模型改写英文、词序、句子范围或时间戳；没有默认启用效果退步的语言模型断句、声纹或其他实验开关。
- 纯计数继续确定性翻译；缺编号、空输出、截断回答会逐条重试。数字不一致、无中文及疑似源句残缺保留待复核状态。
- Ollama/模型缺失时回退原翻译，不自动安装或下载。中途断连不会为每句话无限重试；保留完成条目，剩余条目回退，回退仍失败则保留英文并标记。
- 翻译前释放识别及旧翻译模型显存，结束后卸载上下文模型，并关闭本服务自行创建的 Ollama 进程，不关闭用户原本运行的进程。同步识别、同步翻译和队列任务共用推理锁，避免并发卸载。
- 缓存配置区分上下文模式/模型，避免直接把旧译文当作新结果。旧视频不会无提示整库替换。

## 启动与回退

这台电脑已经安装 Ollama 和对应 4B 模型。更新后正常启动：

```powershell
powershell -ExecutionPolicy Bypass -File tools/versions/v2.1.0/start_service.ps1
```

启动脚本默认 `TRANSLATION_CONTEXT_MODE=auto`、`TRANSLATION_STYLE=generic`。直接运行 `service.py` 的自定义脚本需要自行设置这两个变量。手机已有字幕使用 **生成+ → 仅重翻中文 → 电脑端重翻**，无需重新识别音频；新视频照常生成。

其他电脑先按 [Ollama 官方说明](https://docs.ollama.com/quickstart)安装，再明确下载一次模型：

```powershell
ollama pull qwen3.5:4b-q4_K_M
```

无需 Hugging Face 注册或云 API key。未装模型仍可使用原翻译。冷启动和上下文翻译可能明显慢于 NLLB，低显存时可能使用部分 CPU 计算。

回退旧方式（当前 PowerShell 窗口生效）：

```powershell
$env:TRANSLATION_CONTEXT_MODE = "off"
$env:TRANSLATION_STYLE = "subtitle"
powershell -ExecutionPolicy Bypass -File tools/versions/v2.1.0/start_service.ps1
```

## 隐私与诊断

本地模型默认端口 `127.0.0.1:11435` 不是手机上传端口，无需开放公网或填写进手机。创建的模型服务设置 `OLLAMA_NO_CLOUD=1`；请求禁用代理、拒绝重定向和非回环地址。服务没有上传字幕到云模型。

仪表盘出现 `local_context` / `Local contextual Chinese translation` 表示新后端工作；日志出现 `Local context unavailable ... using existing translation backend` 表示已回退。模型日志在未提交的 `service_data_v2.1.0/context-model.log`，不要公开日志或个人 token。

## 模拟器实测

使用已有 v2.2.0 APK、Android 模拟器 `emulator-5556`、720×1600，以及独立回环服务和数据目录。没有直接把预生成字幕写进手机。

1. 从手机文件选择器导入完整 60 秒 VOA Illusion 视频，点击生成。手机真实提取音频、上传并提交任务；电脑完成 large-v3、WhisperX、既有断句、本地上下文翻译；手机轮询收到并保存 **8 条双语字幕**。
2. 学习页开启翻译、选择第二句，截图检查英文、中文、当前句和视频显示，未见文字越界或控件遮挡。
3. 手机点击“仅重翻中文 → 电脑端重翻”，完成独立 `retranslate` 任务 **8/8**，均由 `local_context` 产生。7 条未审校、1 条源句残缺待复核；不是 7/8 正确率。结束后确认自行启动的模型进程退出。

本地原始证据位于 `.validation/context-runtime-e2e`，包括任务 `434ab27ec9ee493481110c7fff17c18b`（生成）和 `d8f88e547ccd40f1bdb6c583b41f06d8`（重翻），以及学习页/进度截图。视频、音频、完整转录不上传仓库。

**296 项电脑端单元测试通过**，包含本地地址保护、编号/数字检查、失败重试、断连回退、模型卸载、源句告警、缓存区分和字幕原字段保留；PowerShell 启动脚本语法检查通过。这些是功能测试，不是人工准确率证明。

## 已知问题

实测英文仍有一句停在 `behind each`，新翻译把中文说完整了，但不能以此声称修复了英文漏识别。新增 `source_fragment` 服务端标记只用于复核；当前手机 UI 尚不显示质量标记。

此前 11 部完整缓存的英文回退 31→1 属于旧实验指标，不能直接算成本次端到端正确率；本次未重新完成四部新视频独立全片联合验收。失败方案与限制见 [本地语义实验](caption-local-semantic-experiment.md)。请在真实学习中记录视频名、时间、英文/中文及实际听到的内容，以继续区分识别、断句、同步与翻译错误。
