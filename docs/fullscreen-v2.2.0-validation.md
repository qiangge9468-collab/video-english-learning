# v2.2.0 全屏播放验证记录

## 环境和范围

- 手机端：versionName `2.2.0`，versionCode `28`；电脑服务维持 v2.1.0。
- 独立 Android 模拟器：Android 16 / API 36.1，x86_64，720 × 1600，density 280，手势导航。分别检查常规屏幕和系统双刘海模拟配置；全屏横屏时为 1600 × 720。
- 横屏素材：完整本地文件 `Full Gear List for Solo Backpacking.mp4`（12:46），真实 MediaPlayer / TextureView 播放和跳转；竖屏素材：12 秒 360 × 640 H.264/AAC 几何测试视频。
- 字幕使用测试代码中明确给出的中英双语样例及长句，用来验证当前句一致性、显示、交互和边界。**不是重新识别字幕，也不是对整部视频的 ASR 准确率评测；没有声称逐秒看完该视频。**
- 原有模拟器调试通道失去响应后，改用独立只读测试实例，没有清空原模拟器数据。

## 回归结果

以下 12 项在常规屏幕、双刘海配置分别通过（每轮 `Tests: 12, failures: 0`）：

| 检查 | 验证点 |
| --- | --- |
| 反复进入 / 退出全屏 | 连续三次切换，同一个播放器和 TextureView；暂停位置误差小于 500 ms，无主动跳回片头 |
| 当前句与翻译 | 与学习页文本相同；翻译关闭后无中文；字幕空隙不残留上一句 |
| 字幕设置 | 拖动、字号增减、锁定后不能移动或缩放、解锁和复位 |
| 播放中查词 | 控制栏约 3 秒隐藏，字幕仍显示；真实点词打开词典并暂停，关闭后恢复原播放状态 |
| 长句安全区域 | 超长中英字幕、拖到边缘，字幕不越出安全区域或被裁掉 |
| 单双击和锁定查词 | 真实单击隐藏 / 显示控制栏，双击播放 / 暂停；锁定后仍可点词，原先暂停时关闭词典不会自动播放 |
| 系统返回 | 退出全屏，不关闭学习页面 |
| 播放进度 | 真实触摸全屏进度条跳到视频中部，保持暂停；无字幕处清空字幕 |
| 学习状态 | 单句循环、选中句和字幕偏移在全屏切换后保留 |
| 设置持久化 | 重建学习页面后锁定状态仍存在 |
| 切后台 | 真实 Home 键离开，播放暂停；返回同一页面保留全屏、暂停和进度 |
| 竖屏视频 | 保持竖屏方向、原比例、同一个播放器；退出正常 |

另外，36 项 JVM 单元测试通过：字幕位置 5、播放位置恢复 3、任务列表策略 2、复习练习 7、复习调度 7、服务配对 4、字幕导航 8。

已人工检查模拟器截图：控制栏显示 / 隐藏、双语当前句、字幕锁定、词典弹窗、长句、退出后的学习页、竖屏画面。修复了双击事件透传、旋转时视频临时尺寸变化、以及展开字幕设置面板遮挡字幕等问题。控制栏隐藏后只保留视频与当前句；安全区不被字幕或返回按钮覆盖。视频采用等比适配，因此与屏幕比例不同时保留黑边，而不是裁切内容。

## 构建和已知限制

- `:app:assembleDebug`、`:app:assembleDebugAndroidTest`、`:app:testDebugUnitTest` 均完成。
- APK 为沿用现有签名的 debug 分发包；已用 `apksigner verify --print-certs` 确认签名有效且与保留的 v2.1.0 一致。测试 runner 仅在单独的测试 APK 中，不包含在发布安装包里。
- **全项目 Lint 未通过**：剩余 1 error / 72 warnings。error 为原有 `OnDeviceWhisper.kt:283` 把 `MediaExtractor.sampleFlags` 传给 `MediaCodec.BufferInfo.set` 的 `WrongConstant`，该代码在本次修改前已经存在且未改动。没有关闭全项目 Lint 或伪报零告警。新增字幕控件使用平台 Activity / Material 主题，针对不适用的 AppCompatCustomView 规则作了带解释的局部抑制。
- 这不是全部手机品牌、Android 版本或全部旧功能的完整兼容性认证；没有进行实体手机测试。全屏交互借鉴常见视频播放器，但不宣称与哔哩哔哩逐像素一致。字幕生成、联网翻译、后台队列和服务端模型没有在这次 UI 测试中重新执行。
- 旧版 APK、现有视频和缓存保持不变。

## 重复执行

使用独立 Android 13+ 模拟器（测试会改变测试 App 的视频、字幕设置和单词本），配置 JDK 17、Android SDK，并准备横屏真实视频和竖屏视频：

```powershell
powershell -ExecutionPolicy Bypass -File tools/tests/integration/test_fullscreen_v2_2_0.ps1 `
  -Serial emulator-5556 `
  -VideoPath 'C:\media\landscape.mp4' `
  -PortraitVideoPath 'C:\media\portrait.mp4'
```

横屏素材需长于 60 秒，竖屏素材需高大于宽。脚本固定模拟器测试文件名，不改源视频。使用已构建 APK 时可加 `-SkipBuild`。测试源：`app/src/androidTest/java/com/codex/videolearnenglish/FullscreenInstrumentation.kt`；字幕定位单元测试：`FullscreenSubtitlePositionTest.kt`。

脚本遇到断言失败或测试进程崩溃会报告失败，截图拉取到 Git 忽略的 `tools/runtime/v2.2.0/fullscreen-validation/`。图像用于本地复查，不把用户的视频素材提交到公共仓库。
