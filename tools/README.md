# tools 目录说明

电脑端代码现在按“版本”和“用途”分类。`tools` 根目录只保留分类文件夹与本索引；服务状态、日志和调试抓取统一放在 `runtime/`。

## 当前推荐版本

日常使用 v2.0.6：

```powershell
powershell -ExecutionPolicy Bypass -File tools/versions/v2.0.6/start_service.ps1
```

v2.0.6 文件：

- `versions/v2.0.6/service.py`：Whisper、WhisperX CUDA 对齐、语义断句、翻译、持久队列和仪表盘 API。
- `versions/v2.0.6/install_whisperx_cuda.ps1`：创建独立 Python 3.11/CUDA 环境并缓存英文对齐模型。
- `versions/v2.0.6/whisperx_worker.py`：隔离运行 WhisperX 3.8.6 强制对齐。
- `versions/v2.0.6/start_service.ps1`：一键启动；服务就绪后自动打开本地仪表盘。
- `versions/v2.0.6/durable_job_store.py`：断点上传、任务和字幕缓存。
- `versions/v2.0.6/semantic_worker.py`：隔离运行的 SaT + spaCy 进程。
- `versions/v2.0.6/dashboard.html`：本地只读网页仪表盘。

## 目录结构

```text
tools/
  versions/
    legacy/        最初的旧版服务
    v2.0.2/        断点上传和持久任务版本
    v2.0.3/        语义断句版本
    v2.0.4/        字幕空洞和翻译修复版本
    v2.0.5/        保留的仪表盘版本
    v2.0.6/        当前 WhisperX CUDA 对齐和断句质量版本
  shared/          多个版本共用的代码
  network/         局域网、公网和 Cloudflare 工具
  tests/
    unit/          Python 单元与回归测试
    integration/   PowerShell、GPU 和网络运行测试
  utilities/       音频与维护辅助工具
  runtime/         自动生成的 URL、状态、日志、PID 和 UI 抓取
```

版本号由父文件夹表示，所以每个版本内部统一使用 `service.py`、`start_service.ps1` 等简洁名称，同时仍能独立保留和复现旧版本。

## 测试

在项目根目录运行完整 Python 回归测试：

```powershell
D:\Anaconda\python.exe -m unittest discover -s tools/tests/unit -p "test_*.py"
```

PowerShell 集成测试位于 `tools/tests/integration/`。

## 运行时文件

运行时文件只属于本机，并由 Git 忽略，详见 `runtime/README.md`。不要把源码放进 `runtime/`，也不要提交生成的 URL 文件中的 token。
