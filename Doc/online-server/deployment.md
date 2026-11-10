# 部署与环境

## 1. 项目与目录

项目根：`/mnt/geminihzceph/user_whynotzhliu/Omni/duplex-omni`。
以下代码路径均相对项目根：

| 路径 | 职责 |
|---|---|
| `workspace/experiments/20261025_mimo_tts_integration/svad_debug_server.py` | aiohttp HTTP/WS 入口、会话与回复调度 |
| 同目录 `semantic_vad.py` | FSM、窗口、MiMo 分类与正文 SSE |
| 同目录 `streaming_tts.py` | 增量文本分块、外部 TTS submit/poll |
| 同目录 `svad_config.json` | 统一配置与三个普通语音 Prompt |
| 同目录 `svad_debug.html` | 内部调试页面，仍含非交付的视频控件 |
| `vllm-omni/vllm_omni/engine/duplex/vad.py` | Silero backend、会话声学状态 |
| `vllm-omni/examples/online_serving/realtime_web/app/static/pcm_worklet.js` | 浏览器 PCM 采集 worklet |
| `workspace/experiments/20261025_mimo_single_phase2/run_service.py` | 可选单独 MiMo 冷启动 supervisor |
| `workspace/logs/` | 不可覆盖的新运行目录、日志/配置/验证产物 |

`workspace/configs/` 不是本链路主配置目录。不要使用旧 Qwen/MiMo-Qwen
demo 的启动命令替代本次服务。

## 2. 交付环境

现有节点基线，不是任意新机器的最低安装要求：

| 项目 | 核实值/交付位置 |
|---|---|
| OS | Linux，内核 `5.4.241-1-tlinux4-0017.7` |
| Python | `3.12.14`，Conda `omni` |
| 解释器 | `/mnt/geminihzceph/user_whynotzhliu/my_envs/miniconda3/envs/omni/bin/python` |
| Torch | `2.13.0+cu129` |
| Transformers | `5.14.1` |
| vLLM 包元数据 | `0.30.1.dev0+gced6857af.d20260929.cu129` |
| vLLM-Omni 包元数据 | `0.1.0` |
| aiohttp / NumPy | `3.14.3` / `2.3.5` |
| GPU | 节点八张 NVIDIA H20，每张报告 `97871 MiB`；MiMo 使用四张 |
| 驱动 | `575.57.08`；Torch 编译 CUDA 为12.9，不等于驱动版本 |
| 模型权重 | `/mnt/geminihzceph/user_whynotzhliu/modelbase/Omni/MiMo-V2.6-Flash-RL` |
| runtime overlay | `workspace/logs/20261101T_native_mimo_agent_081500/runtime` |
| AVAD | 当前应用实际加载 `TorchSileroBackend`，声学状态按连接隔离 |
| 外部 TTS | `http://29.213.195.135:8100`，需部署节点出站可达 |

版本元数据不能替代源码和编译制品摘要。当前存在 vLLM/Omni 版本警告；
上线不通过临时重装消除警告，要固定已验证组合并在目标环境验收。

**runtime 不是便携安装包**：例如其
`vllm/_C_stable_libtorch.abi3.so` 链接到
`/mnt/geminihzceph/user_whynotzhliu/Omni/vllm-src/vllm/_C_stable_libtorch.abi3.so`。
迁移时必须交付/重建对应源码、扩展、模型和 Silero 缓存，
检查所有链接及 ABI；单独复制 Git 仓库或日志目录不能保证可运行。

## 3. 配置基线

权威完整配置：
`workspace/experiments/20261025_mimo_tts_integration/svad_config.json`。
部署使用独立配置快照，不与开发 Agent 服务共用可变文件。

| 字段 | 当前值 | 含义 |
|---|---:|---|
| `server_policy.vaed_mode` | `chunk` | Listen 每收到一批音频判定 |
| `config.audio_chunk_ms` | 200 | 客户端目标提交间隔，不是严格模型周期 |
| `threshold` | 0.8 | AVAD 声学激活阈值 |
| `prefix_padding_ms` / `min_speech_duration_ms` | 300 / 96 | 前缀与激活长度 |
| `silence_duration_ms` | 256 | AVAD 连续声学静音门控 |
| `vasd_window_ms` / `vaed_window_ms` | 8000 / 8000 | 分类最近窗口，按整批滑动 |
| `sem_probability_threshold` / `sem_margin_threshold` | 0.8 / 1.5 | VASD 放通门槛 |
| `sem_confirmations` | 1 | VASD 连续合格次数 |
| `complete_probability_threshold` / `complete_margin_threshold` | 0.8 / 2 | VAED 完成门槛 |
| `complete_confirmations` | 1 | VAED 连续合格次数，另须 AVAD 关闭 |
| `incomplete_silence_timeout_ms` | 128 | 停声后未接受完成的墙钟兜底 |
| `max_buffered_chunks` | 1024 | 缓存块数上限，不是音频时长上限 |
| `history_turns` | 30 | 当前连接最近用户音频/助手回复对 |
| `retain_interrupted_context` | true | 生成中被打断保留 partial + `⏸` |
| `tts_enabled` / `tts_reg_id` | true / `bench_spk` | 外部服务音色需 owner 保证 |
| `tts_min_chars` / `tts_max_chars` | 8 / 48 | 标点分块下限与硬长度上限 |
| `tts_speed` / `tts_target_rms` | 1 / -25 | 语速与目标响度 |

除第一行外表中字段都在 `config`。模式/窗口禁止客户端覆盖；
不要在 `server_policy` 重复设置窗口，该区域同名值会覆盖 `config`。
三个生效 Prompt 是 `prompts.vasd_sem_prompt`、`vaed_prompt`、`chat_prompt`。
现有完整文件中 Agent 配置可保留，但普通 provider 不使用其工具能力。

`/defaults` 和新 WS 连接读取配置。已有连接持有本地快照；仅改文件不更新
已建立会话，需重连。`configure` 会重建 adapter、取消响应；
使用 `reset` 明确清空历史，不能依赖重新配置完成清空。
代码/schema 改动需重载应用；配置和代码版本必须一起发布。
普通 Chat 当前硬编码 `max_tokens=512`、`temperature=0`、禁用 thinking，
不在统一 JSON 里，不应暗示所有推理参数都已可配置。

## 4. 环境初始化与检查

同节点示例；目标环境迁移后需替换全部绝对路径：

```bash
cd /mnt/geminihzceph/user_whynotzhliu/Omni/duplex-omni
source /mnt/geminihzceph/user_whynotzhliu/my_envs/env.sh
conda activate omni
export ROOT="$PWD"
export RUNTIME="$ROOT/workspace/logs/20261101T_native_mimo_agent_081500/runtime"
export PYTHONPATH="$RUNTIME:$ROOT/vllm-omni"
export PYTHONDONTWRITEBYTECODE=1
python -B -c 'import sys,vllm,vllm_omni; print(sys.executable); print(vllm.__file__); print(vllm_omni.__file__)'
pgrep -af 'svad_debug_server|vllm.entrypoints.cli.main'
nvidia-smi
curl --noproxy '*' --fail --max-time 10 http://127.0.0.1:8090/v1/models
curl --noproxy '*' --fail --max-time 10 http://29.213.195.135:8100/health
```

env.sh 默认 `liu`，随后必须激活 `omni`。历史 editable 安装可能指向兄弟源码，
所以用进程级 PYTHONPATH 固定导入，不修改共享环境安装关系。
AVAD 应用不是纯标准库进程，仍需要上述环境、Omni 模块和现有辅助模块。

## 5. 单独启动纯语音应用

先复用健康 MiMo 和外部 TTS。**不启动 Agent/Next/Mac launcher。**
当前开发服务已占8080/8081，示例选空闲8082，不抢占或停止已有 owner：

```bash
export PORT=8082
python -B -c 'import os,socket; s=socket.socket(); s.bind(("127.0.0.1",int(os.environ["PORT"]))); s.close()'
export RUN="$(mktemp -d "$ROOT/workspace/logs/$(date -u +%Y%m%dT%H%M%SZ)_voice_online_XXXXXXXX")"
cp -n "$ROOT/workspace/experiments/20261025_mimo_tts_integration/svad_config.json" "$RUN/svad_config.json"
git rev-parse HEAD > "$RUN/parent_head.txt"
git submodule status > "$RUN/submodules.txt"
git diff --binary > "$RUN/worktree.patch"
sha256sum "$RUN/svad_config.json" > "$RUN/config.sha256"
python -m pip freeze > "$RUN/environment.txt"
set -o pipefail
python -B "$ROOT/workspace/experiments/20261025_mimo_tts_integration/svad_debug_server.py" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --mimo-url http://127.0.0.1:8090 \
  --tts-url http://29.213.195.135:8100 \
  --config "$RUN/svad_config.json" \
  2>&1 | tee "$RUN/service.log"
```

前台命令用于复现，生产由工程团队的进程管理平台监督，记录PID/退出码、
启动参数、runtime制品摘要，配置日志轮转和优雅停止。首次 Torch/Silero
初始化可能较慢，等待就绪，不重复启动。运行快照配置，不修改开发共享JSON。
`worktree.patch` 不包含未跟踪文件，也不是完整发布包；正式交付应为干净、
已发布SHA加配置/runtime制品。日志/环境文件受控保存，不能携带密钥上线。

### MiMo 未运行时

仅当8090空闲、四张GPU归属明确且可用时冷启动；不要因页面失败重启模型。
下面复用现有 supervisor，模型路径固定在脚本内，迁移需同步核对：

```bash
export MODEL_RUN="$(mktemp -d "$ROOT/workspace/logs/$(date -u +%Y%m%dT%H%M%SZ)_voice_mimo_XXXXXXXX")"
ln -s "$RUNTIME" "$MODEL_RUN/runtime"
export CUDA_VISIBLE_DEVICES=0,1,2,3
python -B "$ROOT/workspace/experiments/20261025_mimo_single_phase2/run_service.py" \
  --run "$MODEL_RUN" --role mimo --attempt cold01 --port 8090
```

参数：TP4、启用EP、max-model-len32768、gpu-memory-utilization0.90、
served-model-name `mimo-v2.6-flash`。保留 native parser 启动标志不意味着
纯语音 Chat 请求携带 tools；普通 provider 不发送工具定义。
TTS 是外部依赖，本仓库不提供其服务端启动命令，不能用 Qwen3-TTS
启动命令或 URL 替换冒充兼容实现。

## 6. 网络与访问

推荐生产拓扑：客户端 WSS -> 鉴权/消息校验入口 -> 回环普通应用；
MiMo8090仅应用可达，TTS8100仅受控出站。WS 升级保留连接、关闭
代理响应缓冲、匹配 Host/Origin、配置长连接超时；具体网关配置由上线团队提供。
同一个 WS 生命周期固定到一个应用实例，当前没有跨实例历史恢复。

普通 `/ws` 有同源检查：携带 Origin 时，scheme须为http/https，
Origin的netloc须与应用收到的Host一致。Origin不是用户鉴权。
客户端无Origin时代码不自动进行该检查；仍需入口鉴权。
部署域名和IP由上线团队确认，不使用本文开发节点IP当生产服务发现。

开发节点最近记录的业务IP为 `28.29.218.56`，仅作SSH例子：

```bash
ssh -N -p 443 \
  -i ~/.ssh/id_ed25519 \
  -o IdentitiesOnly=yes \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -L 127.0.0.1:18080:127.0.0.1:8082 \
  root@28.29.218.56
```

Mac打开 `http://localhost:18080/`，只允许麦克风，不启用摄像头。
此调试方式不是生产接入方案。部署时重新确认IP；旧节点
`28.29.217.68` 等不应混用。本机hosts曾把localhost映射业务IP，
服务端探活明确使用127.0.0.1；WS测试保持Host/Origin一致。

## 7. 探活、更新与回滚

```bash
curl --noproxy '*' --fail --max-time 10 http://127.0.0.1:8082/health
curl --noproxy '*' --fail --max-time 10 http://127.0.0.1:8082/defaults
```

`/health` HTTP200不够，要检查 `mimo=true`、`tts=true`。
`/defaults`核对chunk/8000/256/128/200/history30及配置来源。
健康检查不能代替一轮真实音频与长文本流式合成验收。

更新先停止接收新连接/排空，正常终止应用，启动新代码与配套配置，
重新检查WS与音频；无需同时重启健康的MiMo/TTS。应用停止会丢失连接内历史。
回滚同时恢复代码、配置、runtime版本，不把新增配置字段交给旧schema。
禁止在运行共享worktree切branch、`pkill python`或停止不明GPU owner。

开发对照：2026-11-09运行目录
`workspace/logs/20261109T071156Z_mac_echo_7bf548e5`，普通应用PID2967422；
此目录还包含不交付的Agent开发进程。上线只参考普通entry链路，
PID仅是历史归属，不可作为后续直接kill目标。
