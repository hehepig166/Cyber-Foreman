# Lightweight Server Monitor

一个面向单机 NVIDIA 服务器的轻量监控网页，定时采集并持久化以下数据：

- 主机：CPU、内存、loadavg
- 进程：PID、CPU%、RSS、用户、命令行（按 CPU Top N）
- GPU：总体利用率/显存占用 + 每张卡利用率/显存 + GPU 进程显存占用

## 技术栈

- FastAPI + APScheduler
- SQLite
- psutil + nvidia-ml-py
- 原生 HTML + ECharts

## 快速启动

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.main
```

打开 `http://127.0.0.1:8000`（或 `server.port` 配置端口）查看页面。

## 配置文件（config.yaml）

项目根目录提供 `config.yaml`，默认内容如下：

```yaml
server:
  host: 0.0.0.0
  port: 8000

database:
  path: data/monitor.db

collection:
  sample_interval_seconds: 5
  process_top_n: 50

retention:
  days: 30

logging:
  file_path: logs/monitor.log
  level: INFO
  max_bytes: 10485760
  backup_count: 5

feishu:
  enabled: false
  report_interval_seconds: 3600
  webhook_env_var: FEISHU_BOT_WEBHOOK
  timeout_seconds: 5
```

字段说明：

- `server.host`：服务监听地址
- `server.port`：服务监听端口
- `database.path`：数据库文件路径（支持相对路径，相对项目根目录）
- `collection.sample_interval_seconds`：采样间隔秒数
- `collection.process_top_n`：每次采样保存的进程上限
- `retention.days`：保留天数，设为 `null` 可关闭自动清理
- `logging.file_path`：日志文件路径（支持相对路径，相对项目根目录）
- `logging.level`：日志级别（如 `INFO`、`WARNING`、`ERROR`）
- `logging.max_bytes`：单个日志文件最大字节数，超过后滚动
- `logging.backup_count`：滚动日志保留份数
- `feishu.enabled`：是否开启飞书 GPU 定时通知
- `feishu.report_interval_seconds`：飞书通知周期（秒）
- `feishu.webhook_env_var`：飞书 webhook 的环境变量名
- `feishu.timeout_seconds`：飞书请求超时（秒）

飞书 webhook 不写入配置文件，通过环境变量注入，例如：

```bash
export FEISHU_BOT_WEBHOOK='https://open.feishu.cn/open-apis/bot/v2/hook/xxxx'
```

## API 概览

- `GET /api/metrics/snapshot?limit=30`：当前快照（主机 + 进程 + GPU进程）
- `GET /api/metrics/history?range_window=1h`：历史曲线点位
- `GET /api/metrics/processes/current?limit=50`：当前进程列表
- `GET /api/metrics/gpu-processes/current?limit=50`：当前 GPU 进程列表
- `GET /api/metrics/gpu-devices/current`：当前每张 GPU 卡指标
- `GET /api/metrics/status`：采集状态和最近错误
- `GET /api/metrics/feishu-preview`：预览即将发送到飞书的 GPU 文本
- `GET /api/metrics/config`：当前生效配置（包含日志配置）
- `GET /healthz`：健康检查

## 说明

- 当 NVML Python 绑定不可用或无 NVIDIA GPU 时，CPU/进程采集仍正常运行。
- 所有数据时间戳按 UTC 存储，前端按浏览器本地时区显示。
- 服务日志默认写入 `logs/monitor.log`，并按大小自动滚动。

