# 免注册说话人辅助断句实验

2026-10-08。用户无法注册 Hugging Face，因此改用 **WeSpeaker 英文 ResNet34-LM + Silero VAD + 原有 WhisperX 对齐 + SaT/标点语义判断**。无需 HF/ModelScope 账号、令牌或用户联系方式。Community-1 不再是推进实验的前提。

## 来源、运行与隐私

- 模型使用 [WeSpeaker 官方 VoxConverse 配方](https://github.com/wenet-e2e/wespeaker/blob/master/examples/voxconverse/v2/run.sh) 提供的公开 HTTPS 下载地址，不使用 gated 模型的第三方绕过镜像。
- [官方预训练模型说明](https://github.com/wenet-e2e/wespeaker/blob/master/docs/pretrained.md) 指出 VoxCeleb 模型许可为 CC-BY-4.0；WeSpeaker 代码为 Apache-2.0。实验记录保留来源与署名，不将第三方权重混入本项目 MIT 许可。
- 下载大小 26,530,309 字节；SHA-256：`7bb2f06e9df17cdf1ef14ee8a15ab08ed28e8d0ef5054ee135741560df2ec068`。这是下载后记录的摘要，不冒充作者发布的签名。
- 默认代理遇到证书错误，改为验证证书的官方 HTTPS 直连成功；没有使用 `verify=False` 或关闭 TLS 校验。
- ONNX Runtime GPU 1.23.2 单独安装在 `.validation-deps/wespeaker-gpu`，未替换正式 Python 环境原有依赖；参照 [官方 CUDA 兼容说明](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)。
- 音频在电脑本地处理，没有发送到外部服务。模型与运行日志保留在忽略目录，不打包进手机 APK。

## 实施

新增下载脚本 `tools/utilities/download_wespeaker_experiment_model.py` 与整片运行脚本 `tools/validation/run_wespeaker_experiment.py`。采用官方前端参数、1.5 秒声纹窗口和 0.75 秒步进，对整片 VAD 语音区间提取声纹、聚类；说话人数不按某个视频硬编码。

该方案没有完整重叠说话检测。报告明确标为 `overlap_detection_available=false`，不能将缺少检测结果当作不存在重叠说话。因此声学换人只是候选，另需语义支持；保护主谓连接、实体、缩写、低置信度对齐和不确定时间。

修正了一类词表保护冲突：词表中的助动词拼写也可能是句末实义动词。仅在“声学换人 + SaT ≥0.9 + 独立标点概率 ≥0.8 + ROOT/VERB”同时满足且其他短语保护允许时，放行此类边界。不根据视频名或预期台词改写文字。

实验默认关闭。`replay_speaker_learning.py` 要求旧的整片语义缓存能精确重现，再加入独立声学结果；若对齐输入摘要不一致则拒绝。没有重跑 ASR，不改变原始词序与词时间。

## 完整音频测试

本轮实际重新处理 **11 部完整音频，共 8,304.08 秒（138.40 分钟），6,718 个声纹窗口**，不只是重放说话人缓存或检查几个片段。三个批次执行记录均确认 CUDA 节点实际运行，合计 44,200 次 CUDA 节点事件；少量 shape 运算在 CPU 上，不声称全部算子都在 GPU。

| 完整音频 | 声纹窗口 | 学习句旧→新 |
| --- | ---: | ---: |
| Switzerland | 615 | 192→192 |
| Rinjani | 1596 | 405→405 |
| Bangladesh | 1830 | 415→415 |
| AIRFLARE | 1165 | 229→229 |
| Interview | 209 | 73→75 |
| Perspectives | 267 | 79→79 |
| Illusion | 54 | 8→8 |
| Thirty Days | 156 | 36→36 |
| Movement | 172 | 36→36 |
| Champion | 425 | 98→98 |
| Budget Cuts | 229 | 73→74 |

新增三处边界把问答/回应从上一句分开，例如 `What should I do` 与 `update your resume`。它们是自动实验结果，仍需对照声音人工审校，不能据此称整片准确率达到 90%。模型检测到的其他换人候选大多已处于句界，或因语义保护被拒绝。

三部 TED 的全文出版句界 F1 保持 87.32%、78.26%、83.67%，合计约 83.33%；**这一轮没有提升这些独白视频的指标**。该指标也不是联合可用率。说话人分离仅解决部分对话合句，不能替代进一步语义分句和翻译优化。

新结果共 1,647 条学习句。翻译只对新增拆分产生的 6 条输入重新调用本地 NLLB；其余 1,641 条要求文字、词范围、起止时间精确一致后复用旧译文并记录摘要，不冒充全部重新翻译。完整输出保留所有英文回退和待审校状态。

11 部完整输出的结构审计均通过：16,428 个输入词无丢失、无重复、无改写、无顺序倒置，学习句完整划分词序列，翻译没有改变对应英文和时间。Budget Cuts 新拆分两句的输出为“我该怎么办？”和“更新你的简历”；后面另一处多人对话合句仍未解决。31 条已有英文回退仍存在，不能计作中文翻译通过。

## 结果位置与复现

本地忽略目录：`.validation/wespeaker-{budget,online,original}-r1` 保存整片声学结果与 GPU 执行证明；`wespeaker-learning-*-r2`、`wespeaker-translation-*-r2`、`wespeaker-integrity-*-r2` 保存对应整片结果。旧实验不覆盖。

```powershell
python tools/utilities/download_wespeaker_experiment_model.py MODEL_DIR --direct
python tools/validation/run_wespeaker_experiment.py MANIFEST ALIGNMENT OUTPUT --model MODEL_DIR/voxceleb_resnet34_LM.onnx --ort-site ORT_GPU_DIR
python tools/validation/replay_speaker_learning.py MANIFEST ALIGNMENT PRIOR_LEARNING SPEAKER_RESULTS OUTPUT
python tools/validation/translate_changed_learning_units.py MANIFEST NEW_LEARNING PRIOR_TRANSLATION OUTPUT --model NLLB_LOCAL_DIR
python -m unittest discover -s tools/tests/unit -p 'test_*.py'
```

本轮 256 项测试通过。最终目标仍按 [整句联合验收](caption-joint-accuracy-plan.md) 判定；完整音频处理成功、程序测试通过均不等于准确率达标。已有视频都是开发/回归集，最终还需要未参与调试的视频与独立完整参考。尚未升级默认方案、发布 APK 或宣称达到 90%。
