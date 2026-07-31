# 运行时输出

这里保存电脑服务自动生成的本机状态。除本说明外，目录内文件全部由 Git 忽略。

```text
runtime/
  legacy/        无版本号的历史状态和 URL
  v2.0.2/        v2.0.2 配置、状态和 URL
  v2.0.3/        v2.0.3 配置、状态、URL 和日志
  v2.0.4/        v2.0.4 配置、状态、URL、日志和 UI 抓取
  v2.0.5/        保留版本配置、状态和 URL
  v2.0.6/        当前版本配置、状态和 URL
  cache/         可丢弃的 Python 缓存
```

这些文件可能包含临时鉴权 token 或公网隧道地址，只用于本机诊断。

v2.0.6 启动脚本会写入：

- `runtime/v2.0.6/config.json`
- `runtime/v2.0.6/status.json`
- `runtime/v2.0.6/latest_service_urls.txt`

删除运行状态文件不会删除音频、任务或字幕缓存；这些数据单独保存在项目根目录的 `service_data_v2.0.6/`。
