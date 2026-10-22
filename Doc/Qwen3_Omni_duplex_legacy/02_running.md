# 起停服务、访问方式与日志

所有命令都在项目根目录执行：

```bash
cd /mnt/geminihzceph/user_whynotzhliu/Omni
```

## 1. 一键启动

```bash
DEPLOY_CONFIG=workspace/configs/demo_vad.json UI_PORT=8080 bash workspace/scripts/start_duplex_service.sh
```

脚本做的事：`flock` 防并发 → 自动挑 3 张空闲 GPU → 拉起 stage 0/1/2 → 轮询
`http://127.0.0.1:$VLLM_PORT/v1/models` 等待就绪 → 起 UI → 打印访问地址。

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `DEPLOY_CONFIG` | `vllm-omni/vllm_omni/deploy/qwen3_omni_duplex.yaml` | **相对路径**，必须在项目根目录运行 |
| `UI_PORT` | `7865` | 本环境实际用 `8080`（放通端口） |
| `VLLM_PORT` | `8092` | 后端 API 端口 |

启动耗时约 **6~7 分钟**（30B MoE 的编译 + CUDA Graph 预热）。脚本内 `READY_TIMEOUT=3000` 秒，
最多重试 2 次。

## 2. 停止

```bash
pkill -9 -f "[v]llm serve.*Qwen3-Omni-30B-A3B-Instruct"; pkill -9 -f "[s]erver.py --port"
```

**两个注意点**（都踩过）：

1. pattern 写成 `[v]`、`[s]` 的形式。直接写 `vllm serve`，`pkill -f` 会匹配到执行这条命令的 shell
   自己，把自己 kill 掉，命令没有任何输出。
2. **停止和启动必须分开执行**。启动脚本靠 `/tmp/start_duplex_service.lock` 防并发，而锁是通过文件
   描述符继承实现的——旧进程没退出时锁还没释放，并行启动会直接报：
   ```
   检测到已有一份 start_duplex_service.sh 在运行（锁文件 /tmp/start_duplex_service.lock）
   ```

如果锁报错但 `ps aux | grep start_duplex_service` 看不到进程，用这个查真正持有锁的进程：

```bash
for pid in $(ls /proc | grep -E '^[0-9]+$'); do
  ls -l /proc/$pid/fd 2>/dev/null | grep -q start_duplex_service.lock && echo "held by $pid: $(tr '\0' ' ' </proc/$pid/cmdline | cut -c1-90)"
done
```

> 之前的坑：UI 端口实际是 8080，但用了 `pkill -f "server.py --port 7865"` 去杀，端口不匹配没杀掉，
> 遗留进程一直持有锁导致后续启动全部失败。**写 pkill pattern 时不要写死端口**（用
> `pkill -9 -f "[s]erver.py --port"`）。

## 3. 访问方式

**本机**：`http://127.0.0.1:8080/`

**同事（内网）**：`http://28.29.216.165:8080/`（末位斜杠不能省）。80/8080/8081/443 是默认放通端口。

**浏览器必须带参数启动**。因为 `AudioContext.audioWorklet` 只在安全上下文（HTTPS 或 localhost）
下存在，裸 IP + HTTP 访问会报 `Cannot read properties of undefined (reading 'addModule')`。

Mac：
```bash
open -na "Google Chrome" --args --user-data-dir=/tmp/h20-duplex-http-profile --unsafely-treat-insecure-origin-as-secure="http://28.29.216.165:8080" "http://28.29.216.165:8080/"
```

Windows：
```
chrome.exe --user-data-dir="C:\temp\h20-duplex-http-profile" --unsafely-treat-insecure-origin-as-secure="http://28.29.216.165:8080" "http://28.29.216.165:8080/"
```

> 命令**必须写在一行**，或者每行末尾加 `\` 续行。分成多行不带 `\` 的话，zsh 会把后面几行当成独立
> 命令执行，报 `no such file or directory`，而 Chrome 只会被打开一个空白窗口（不带参数和网址）。
>
> 另外 `--user-data-dir` 指向的 profile 如果已经有 Chrome 实例在跑，新参数不会生效，要把那个实例
> 完全退出（Mac 上 `Cmd+Q`）或换一个目录名。

## 4. 日志

每次启动创建一个目录：`workspace/logs/<YYYYmmdd_HHMMSS>_duplex_service/`

| 文件 | 内容 |
|---|---|
| `stage0_attempt1.log` | **主要看这个**：thinker + API server，VAD 判定、每轮提交、token 统计 |
| `stage1_attempt1.log` | talker |
| `stage2_attempt1.log` | code2wav |
| `ui.log` | UI 代理（WS trace 也写在这里） |
| `ui.pid` | UI 进程号 |

失败重试会生成 `*_attempt2.log`。

常用查看方式：

```bash
# 实时跟踪（就绪后会打印 "Starting vLLM API server 0 on http://0.0.0.0:8092"）
tail -f workspace/logs/<目录>/stage0_attempt1.log

# 看每轮的 VAD 判定和提交
grep -E "Duplex VAD|Duplex committed turn" workspace/logs/<目录>/stage0_attempt1.log

# 看每个请求的 thinker 输入/输出 token 数（快速判断是否出现空回复）
awk '/\[StageRequestStats \[request_id=/{match($0,/resp-duplex-[a-f0-9]+-[0-9]+-[a-f0-9]+/); rid=substr($0,RSTART+46)} /num_tokens_out/{y=$0; sub(/.*num_tokens_out */,"",y); split(y,b,"|"); print rid " thinker_out=" b[2]}' workspace/logs/<目录>/stage0_attempt1.log
```

**进度信息只在终端**："尝试 1 / 后端就绪 / 服务已全部就绪"这类输出只打印到你运行脚本的那个终端，
不写文件。

## 5. 调试开关

| 环境变量 | 作用 | 写到哪 |
|---|---|---|
| `OMNI_WS_TRACE=1` | UI 代理逐帧打印 WebSocket 消息（`C2B` / `B2C`） | `ui.log` |
| `OMNI_WS_TRACE_AUDIO=0` | 关掉高频音频帧，只留事件 | 同上 |
| `VLLM_OMNI_QWEN_VISUAL_DEBUG_DIR=<dir>` | 每轮把发给 thinker 的完整 prompt 写到 `<dir>/<hash>/input.json` | 指定目录 |

带调试启动：

```bash
VLLM_OMNI_QWEN_VISUAL_DEBUG_DIR=/mnt/geminihzceph/user_whynotzhliu/Omni/workspace/logs/prompt_dump \
OMNI_WS_TRACE=1 DEPLOY_CONFIG=workspace/configs/demo_vad.json UI_PORT=8080 \
bash workspace/scripts/start_duplex_service.sh
```

两个开关默认关闭，不影响正常服务。**注意 `VLLM_OMNI_QWEN_VISUAL_DEBUG_DIR` 每轮都写一个文件，
排查结束后要记得去掉。**

## 6. 常见故障

| 现象 | 原因 | 处理 |
|---|---|---|
| 启动报锁被占用 | 旧进程还在，或之前漏杀 | 见第 2 节 |
| 启动后端口连不上 | 还在加载模型 | 等 stage0 日志出现 `Starting vLLM API server`，约 6~7 分钟 |
| 页面报 `addModule` 错误 | 浏览器安全上下文限制 | 见第 3 节的 Chrome 参数 |
| UI 连不上后端（403 / 1011） | 手动重启 UI 时忘了 `NO_PROXY`，请求走了公司 HTTP 代理 | 重启 UI 前 `export NO_PROXY=localhost,127.0.0.1` |
| 同事连不上 | `max_sessions=1`，你正在占用 | 见 `03_vad_config.md` |

**手动重启 UI 时的正确姿势**（只重启 UI，不动后端，代价小）：

```bash
cd vllm-omni/examples/online_serving/realtime_web
. /mnt/geminihzceph/user_whynotzhliu/my_envs/miniconda3/bin/activate && conda activate omni
export NO_PROXY=localhost,127.0.0.1 && export no_proxy=localhost,127.0.0.1
OMNI_WS_TRACE=1 python server.py --port 8080 --profile qwen3-turn --vad \
  --model /mnt/geminihzceph/user_whynotzhliu/modelbase/Omni/Qwen3-Omni-30B-A3B-Instruct \
  --ws-backend ws://127.0.0.1:8092 > /path/to/ui.log 2>&1
```

注意：用 Bash 工具跑长驻进程时要用后台方式，直接在前台命令里加 `&` 会随命令结束被清理掉。

## 7. 脚本化复现（不依赖浏览器）

`workspace/experiments/20261014_barge_in_garble/scripted_barge_in.py`：gate 模式，连续 N 轮
"提交 → 收到第一个音频块 → cancel → ack played_ms=0"，最后一轮正常播完。用来在不说话的情况下
复现打断相关的问题。

```bash
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy NO_PROXY='*' \
  /mnt/geminihzceph/user_whynotzhliu/my_envs/miniconda3/envs/omni/bin/python \
  workspace/experiments/20261014_barge_in_garble/scripted_barge_in.py 5
```

（脚本里 `proxy=None`，但仍建议清掉代理环境变量，客户端库可能自己读环境变量。）

## 8. 跑测试

生产环境 `omni` 没装 pytest。为了不动它，pytest 装到了实验目录，用 `PYTHONPATH` 临时引入：

```bash
cd vllm-omni
PYTHONPATH=../workspace/experiments/20261014_barge_in_garble/pyvendor \
  /mnt/geminihzceph/user_whynotzhliu/my_envs/miniconda3/envs/omni/bin/python -m pytest \
  tests/model_executor/models/qwen3_omni/test_duplex_plugin.py -q -p no:cacheprovider
```

`pyvendor` 里有 pytest / pytest-asyncio / pytest-xdist。缺少 `pytest-mock`，所以
`test_qwen3_omni_embed.py` 和 `test_qwen3_omni_forward_contract.py` 会报 `fixture 'mocker' not found`，
与本轮改动无关。
