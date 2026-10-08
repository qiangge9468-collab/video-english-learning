# 90% 整句可用率：分阶段实施记录

更新：2026-10-08。工作位于隔离实验分支；正式版本、APK、生产缓存未替换。

**后续进展**：用户无法注册 HF，现已改用免注册 WeSpeaker，本地 CUDA 已完成 11 部完整音频实验；不再需要接受 Community-1 条款。详见 [免注册方案与真实运行结果](caption-account-free-speaker-experiment.md)。随后完成本地 4B/7B 的全片断句对照，以及 11 部全部 1,647 条上下文翻译；英文回退 31→1，但 13 条待复核，断句变体均未超过基线，详见 [本地语义实验](caption-local-semantic-experiment.md)。当前 284 项单元测试通过。下文关于“待授权”和 250 项测试的内容是首阶段记录，不是当前阻塞条件。联合准确率仍未证明达到 90%。

## 验收定义

本轮按用户确认的新目标采用 **90% 整句联合可用率**。一条学习句须同时满足：英文内容正确、自然断句、语音首尾误差各不超过 0.5 秒且不切掉发音、中文完整忠实。不能把四项分别达到 90% 当作整句达到 90%。历史 95% 实验报告保留原样。

新工具 `tools/validation/evaluate_joint_caption_reference.py` 规定：

- 分母为参考学习句数加上没有匹配参考的额外生成句数；漏句失败，额外句也扣分。
- 英文回退、翻译失败或待复核译文不能算翻译成功。
- 多个碎片不能在评分时拼起来假装一个正确学习句；一个生成句不能重复满足多个参考句。
- 参考须核查整片漏识别语音；OCR 显示起止不是实际发音起止。
- 审校绑定精确输出摘要，候选文字、时间或翻译改变后旧审校失效。
- 最终至少四部冻结前未参与调参的完整视频，各自达标，并覆盖独白、对话、计数和噪声；不能用平均值掩盖某片失败。

旧 `evaluate_caption_reference.py` 的分项指标只用于历史诊断，不作为新目标的发布证明。新门槛也不能靠勾选布尔值证明质量：须实际听完、核对完整参考、补上漏句并保留审校证据。目前没有完整独立联合参考，因此 **联合准确率未知，尚未证明达到 90%**。

## 第一步：独立参考校准

代码与完整缓存复查已完成。`stabilize_ocr_reference.py` 不读取 ASR 或待评时间戳，只根据连续帧 OCR 校准：完整字幕至少出现两次，中间漏读的一行必须是同一完整字幕的连续子串，所有读数须同时符合共同完整字幕，不能通过共同短句把不同字幕串起来。容许至多一帧采样量化差；保留原始组、文本变体、观测次数和来源编号。结果仍未审校。

`run_reference_calibration.py` 复查 10 部完整 OCR 缓存，共 **6,989 秒（约 116.48 分钟）**。这是全片已有缓存重放，不是本轮重新识别全部音频。AIRFLARE 无完整硬字幕参考，单独记录，不能算通过。

| 视频 | 原始 OCR 组 | 校准后组 | 合并组数 |
| --- | ---: | ---: | ---: |
| Switzerland | 352 | 352 | 0 |
| Rinjani | 723 | 723 | 0 |
| Bangladesh | 1093 | 1090 | 2 |
| Interview | 87 | 87 | 0 |
| Perspectives | 84 | 84 | 0 |
| Illusion | 21 | 21 | 0 |
| Thirty Days | 106 | 104 | 2 |
| Movement | 78 | 78 | 0 |
| Champion | 161 | 160 | 1 |
| Budget Cuts | 79 | 74 | 2 |

所有观测次数保持不变。Budget Cuts 约 246 秒处，OCR 偶尔只读到第二行，原审计错误报告约 3.3 秒不重叠；连续帧校准后该条告警消失。**这是参考误报修正，不是移动音频字幕，也不是识别准确率提升的证明。** Rinjani、Bangladesh 各一条较大显示时间分歧仍保留。完整结果在忽略目录 `.validation/reference-calibration-r1`、`reference-calibration-r2`。

## 第二步：声音与语义联合断句

接口完成，真实推理待授权。新增 `speaker_boundary_evidence.py`、`run_speaker_boundary_experiment.py`，参考 [WhisperX](https://github.com/m-bain/whisperX) 的独立对齐/说话人分离，以及 [pyannote Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) 的 exclusive diarization 接口。

- 整片音频通过 FFmpeg 解码，在本地 CUDA 推理，不上传音频，关闭 pyannote 遥测。
- 只接受合法下载的本地模型，离线加载，不自动接受条款，不打印或传递令牌参数。
- 按逐词音频交集投影说话人；低覆盖、重叠说话、对齐回退和重叠词时间不强制断句。
- 明确的换人位置可作为独立声学边界，但仍标记待复核并记录语法冲突；不改写 ASR 字词和时间。
- 使用 `run_cohort_learning_experiment.py --speaker-root ...` 显式接入；正式默认关闭。

本机安装了 pyannote.audio 4.0.7，但没有 Community-1 模型或 HF 凭据。下载需用户自行接受共享联系信息的条款，本次没有代为同意。Windows TorchCodec 解码依赖有问题，实验使用内存 waveform 输入绕开；尚未完成实际模型推理验证。

授权并备妥模型后，先对已有对话开发集整片推理并比较所有学习句，不能只修 Budget Cuts 179–186 秒案例。已有 11 部视频均视为开发/回归素材，不再当作新盲测集。

## 后续尚未完成

1. 实际 CUDA 说话人实验及整片效果比较已完成（见后续进展）；语言模型断句实验未优于基线，仍不能发布。
2. 上下文翻译候选已完成；完整独立语义审校尚未完成，英文回退减少不代表翻译正确。
3. 冻结候选后另选至少四部未调参完整视频，制作独立发音、自然句界及译文参考，逐片联合验收。
4. 达标后才提升为默认实现并发布 GitHub 安装包。目前不能声称任意新视频达到 90%。

## 测试

- 250 项单元测试通过，包含“分项均 90% 而联合仅 60% 必须失败”、漏句/额外句、审校摘要失效、OCR 误合并保护和说话人覆盖保护。
- 11 部完整缓存转录、16,428 词、1,644 条学习句：关闭说话人开关时，文本、词范围、时间、复核标记和显示块与旧实验输出逐项一致。
- 这是逻辑回归和缓存审计，不是人工准确率或实际说话人模型实测。

复现命令（输出目录须不存在）：

```powershell
python -m unittest discover -s tools/tests/unit -p 'test_*.py'
python tools/validation/run_reference_calibration.py .validation .validation/reference-calibration-new
python tools/validation/replay_speaker_disabled_regression.py .validation .validation/speaker-disabled-new.json
python tools/validation/run_speaker_boundary_experiment.py MANIFEST ALIGNMENT_DIR OUTPUT_DIR --model AUTHORIZED_LOCAL_MODEL --ffmpeg FFMPEG_PATH
python tools/validation/evaluate_joint_caption_reference.py REVIEW_JSON ARTIFACT_JSON REPORT_JSON
```

联合验收未达标或参考不足返回退出码 2，不应绕过。
