# 独立 VAD + MiMo + TTS 启动交接

整理日期：2026-11-03。适用于本计算节点的现有工作树，不包含 agent、
OpenAI SDK、Mac 工具或后台 reasoning。本文整理启动方式，没有执行停服或新启动。

## 1. 链路与入口

```text
浏览器持续收音/可选视频
  -> Silero AVAD
  -> MiMo VASD_SEM / VAED
  -> 完整用户话轮提交 MiMo Chat
  -> 正文 SSE delta
  -> 增量文本分块 / CosyVoice submit
  -> 并行 poll PCM / 浏览器播放
```

启动脚本为 `svad_debug_server.py`，**不加 `--agentic`**。访问 `/`，
不是 `/agent`。根页面和 `/ws` 可独立工作，不需要 Next.js、ICHAT_API_KEY
或 Mac 授权。虽然脚本保留 agent 代理路由，本链路不使用这些路由。

当前 8080 entry 进程本身没有 `--agentic`，因此现有 SSH 转发下直接访问
`http://localhost:8080/` 就是普通 VAD 控制台；`/agent` 才进入 agent 页面。
这是已有服务的使用方式，不需要再起一个同端口进程。

此处 TTS 是外部 **CosyVoice Audio Engine**，不是历史本地 Qwen3-TTS。
两者 HTTP 协议不同，不能只替换端口就互换。

## 2. 目录与配置

项目根目录：

```text
/mnt/geminihzceph/user_whynotzhliu/Omni/duplex-omni
```

| 路径（相对项目根） | 用途 |
|---|---|
| `workspace/experiments/20261025_mimo_tts_integration/` | 本链路的代码和主配置目录 |
| `workspace/experiments/20261025_mimo_tts_integration/svad_config.json` | VAD、TTS、历史、prompt 的统一配置 |
| `workspace/experiments/20261025_mimo_tts_integration/svad_debug_server.py` | 独立服务入口 |
| `workspace/experiments/20261025_mimo_tts_integration/svad_debug.html` | 根页面控制台 |
| `workspace/experiments/20261025_mimo_tts_integration/semantic_vad.py` | VAD 状态机、分类和流式 MiMo Chat |
| `workspace/experiments/20261025_mimo_tts_integration/streaming_tts.py` | 文本分块、CosyVoice submit/poll 客户端 |
| `workspace/experiments/20261025_mimo_single_phase2/run_service.py` | 可选 MiMo 冷启动 supervisor |
| `workspace/experiments/20261025_mimo_single_phase2/qwen3_tts_h20.yaml` | 历史本地 Qwen3-TTS 配置，本链路不用 |
| `workspace/configs/` | 旧 demo/级联配置，不是本链路的主配置目录 |
| `workspace/logs/` | 每次新建的运行日志、运行清单和原始验证结果 |

`svad_config.json` 中：

- `config.audio_chunk_ms`：浏览器音频批次目标间隔。
- `threshold`、`prefix_padding_ms`、`silence_duration_ms`、
  `min_speech_duration_ms`：Silero 声学 VAD。
- `vasd_window_ms`、`sem_*`：语义有效性判定。
- `complete_*`、`incomplete_silence_timeout_ms`：语义完成/超时兜底。
- `max_buffered_chunks`：音频缓存上限。
- `tts_enabled`、`tts_reg_id`、`tts_speed`、`tts_target_rms`：TTS 设置。
- `tts_min_chars` / `tts_max_chars`：正文增量分块，当前为 8 / 48。
- `history_turns`：历史轮数，当前为 10；0 关闭历史。
- `retain_interrupted_context`：是否保留带中断标记的部分回复。
- `prompts.vasd_sem_prompt`、`vaed_prompt`、`chat_prompt`：普通链路 prompt。
- `_说明`：字段说明，不参与推理。

agent 专用的 `background_reasoning`、`agent_tool_prompt`、
`agent_forced_prompt`、`background_reasoning_prompt` 不会启用普通链路的
SDK 工具调用。不要为启动普通链路而删除或覆盖原有 agent 配置。

模型服务地址不是这个 JSON 的字段，用 `--mimo-url`、`--tts-url` 指定。
`/defaults` 会重新读取配置；修改文件后刷新页面，再启动麦克风或点击
“应用全部设置”加载会话设置。配置应用可能重建会话/清空历史，不是运行中
模型请求的热更新。独立实验可用 `--config` 指定另一份完整 JSON。

## 3. 依赖与启动前检查

现有部署依赖：

| 服务 | 地址/位置 | 说明 |
|---|---|---|
| MiMo | `http://127.0.0.1:8090` | 当前 TP4 服务；普通链路复用，不重复加载 |
| TTS | `http://29.213.195.135:8100` | 外部服务；本文不管理其启动 |
| MiMo 权重 | `/mnt/geminihzceph/user_whynotzhliu/modelbase/Omni/MiMo-V2.6-Flash-RL` | 冷启动才使用 |
| 已验证 runtime | `workspace/logs/20261101T_native_mimo_agent_081500/runtime` | 当前 Python 源码/编译扩展 overlay |

runtime 不是便携安装包，包含指向同节点已编译依赖的链接；迁移节点时必须
重新核对链接和环境，不能把缺失依赖当作配置问题或直接指向未编译 vllm-src。

在计算节点执行：

```bash
cd /mnt/geminihzceph/user_whynotzhliu/Omni/duplex-omni
source /mnt/geminihzceph/user_whynotzhliu/my_envs/env.sh
conda activate omni
export ROOT="$PWD"
export RUNTIME="$ROOT/workspace/logs/20261101T_native_mimo_agent_081500/runtime"
export PYTHONPATH="$RUNTIME:$ROOT/vllm-omni"
export PYTHONDONTWRITEBYTECODE=1

python -B -c 'import sys, vllm, vllm_omni; print(sys.executable); print(vllm.__file__); print(vllm_omni.__file__)'
pgrep -af 'svad_debug_server|launch_mac_echo|vllm.entrypoints'
nvidia-smi
curl --noproxy '*' --fail --max-time 10 http://127.0.0.1:8090/v1/models
curl --noproxy '*' --fail --max-time 10 http://29.213.195.135:8100/health
```

预期解释器为 `omni/bin/python`，vllm 来自上述 runtime，vllm_omni 来自当前
仓库子模块。不要重装环境或改 editable install 来绕过导入根问题。
模型健康和 TTS 健康不等于浏览器音频/首包延迟验收。

## 4. 单独启动普通服务

在完成上一节环境设置后，选择一个空闲服务端口。当前 8080/8081 已由现有
应用占用，下面用回环 **8082** 示例；通过 SSH 转发使用它，不要求公网放通8082。
端口有其他 owner 时不要覆盖、kill 或自动换绑。

```bash
export PORT=8082
python -B -c 'import os, socket; s=socket.socket(); s.bind(("127.0.0.1", int(os.environ["PORT"]))); s.close(); print("port available")'
export RUN="$(mktemp -d "$ROOT/workspace/logs/$(date -u +%Y%m%dT%H%M%SZ)_standalone_svad_XXXXXXXX")"
cp -n "$ROOT/workspace/experiments/20261025_mimo_tts_integration/svad_config.json" "$RUN/svad_config.json"
git rev-parse HEAD > "$RUN/parent_head.txt"
git diff --stat > "$RUN/worktree_summary.txt"
printf '%s\n' "PYTHONPATH=$PYTHONPATH" "MIMO=http://127.0.0.1:8090" "TTS=http://29.213.195.135:8100" "PORT=$PORT" > "$RUN/runtime.txt"

set -o pipefail
python -B "$ROOT/workspace/experiments/20261025_mimo_tts_integration/svad_debug_server.py" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --mimo-url http://127.0.0.1:8090 \
  --tts-url http://29.213.195.135:8100 \
  --config "$RUN/svad_config.json" \
  2>&1 | tee "$RUN/service.log"
```

保持前台运行，在另一终端检查。日志目录每次独占创建，配置快照不覆盖历史；
这里运行的是快照，之后修改 `$RUN/svad_config.json` 才影响该进程的默认配置。
如果需要直接使用主配置，把 `--config` 换成第 2 节的主 JSON 绝对路径；
主配置同时被当前其他服务读取，修改前确认影响范围。

第一次加载 Torch/Silero 可能需要一段时间，等待启动日志，不反复重启。
停止在该终端按 Ctrl-C，只停止这个普通应用，不停止 MiMo 或外部 TTS。
不要使用宽泛的 `pkill python`。改用8080前先协调并正常停止既有应用 owner。

## 5. Mac 访问

保留当前已有8080隧道时，可以直接打开现有普通页面：

```text
http://localhost:8080/
```

独立8082示例在 Mac 新开终端：

```bash
ssh -N -p 443 \
  -i ~/.ssh/id_ed25519 \
  -o IdentitiesOnly=yes \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -L 127.0.0.1:18080:127.0.0.1:8082 \
  root@28.29.218.56
```

浏览器打开 `http://localhost:18080/`，点击 Start microphone 并允许麦克风，
按需启用摄像头。SSH 是计算节点的443入口，服务端8082仅需回环可达。
IP 是本节点当前交接地址，节点变化后必须重新核对，不沿用历史IP。
如果18080已被占用，选另一个本地端口并同步修改浏览器地址。

localhost 方式不需要此前远端 HTTP origin 的 Chrome 不安全实验参数。
出现 `channel ... Connection refused`，表示 SSH 已连通但转发目标服务未监听，
先检查服务端端口和启动日志，不重新生成 SSH key 或 Mac pairing code。

## 6. 验收与故障排查

在计算节点另一个终端：

```bash
curl --noproxy '*' --fail --max-time 10 http://127.0.0.1:8082/health
curl --noproxy '*' --fail --max-time 10 http://127.0.0.1:8082/defaults
curl --noproxy '*' --fail --max-time 10 http://127.0.0.1:8082/
```

- `/health` 的 `mimo` 和 `tts` 应均为 true，`/defaults` 是本次配置。
- 根页面应显示 VAD 状态/对话面板，不是 Agent 工具页面。
- 发问后应看到 `chat.delta` 增量；文本分块事件为 `tts.text`，音频为 `tts.audio`。
- 真正流式的验收是长回答 **首个 `tts.audio` 早于 `chat.done`**，不只看
  `/health` 或 SSE `stream=True`。短回答可能先完成 decode，再等首 PCM。
- 正文分块需达到最小长度/标点或最大长度，不是每个 token 都单独提交 TTS。
- 背景话语可能得到 `listening` 并静默；有效语义讲话在播放中会打断。
- TTS失败时保留文字，检查外部服务和 `tts_reg_id=bench_spk` 是否可用。
- 外部协议使用 `/submit`、`/poll` 和 `EagerTTSStrategy`；无远端取消接口，
  本地取消停止轮询/播放，不承诺已提交的远端计算物理停止。

不要用 `probe_svad_live.py` 默认结果验收 TTS：该探针显式关闭了 TTS。
历史流式证据见 Stage4 README 的 incremental_tts_probe 段落，
不是本次新启动验收。本次未运行 GPU/浏览器回放。

## 7. MiMo 未运行时的可选冷启动

只有8090没有现有服务且 GPU0-3确实可用时才执行。TP4 模型昂贵，不要因为
普通页面未启动而重启模型；不停止其他用户进程。先执行第3节环境初始化。

```bash
export MODEL_RUN="$(mktemp -d "$ROOT/workspace/logs/$(date -u +%Y%m%dT%H%M%SZ)_standalone_mimo_XXXXXXXX")"
ln -s "$RUNTIME" "$MODEL_RUN/runtime"
export CUDA_VISIBLE_DEVICES=0,1,2,3
python -B "$ROOT/workspace/experiments/20261025_mimo_single_phase2/run_service.py" \
  --run "$MODEL_RUN" --role mimo --attempt cold01 --port 8090
```

supervisor 记录模型命令、环境、GPU、PID、日志和退出码；Ctrl-C由它转发给
所属子进程。模型参数来自现有 runner：TP4/EP、max-model-len32768、
gpu-memory-utilization0.90、served-model-name `mimo-v2.6-flash`。
保留 native mimo parser 标志不意味着普通服务使用 SDK 工具。

TTS 由外部 owner 提供，本文只交接客户端地址/协议，**不提供或猜测其启动命令**。
若外部 TTS 不可用，先联系其 owner；历史本地 Qwen3-TTS 不是此路径的替代启动。
