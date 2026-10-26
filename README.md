# duplex-omni

基于 **Qwen3-Omni 与 MiMo 的流式语音对话开发项目**，覆盖多轮会话、服务端 VAD、播放反馈、打断取消以及模型级联。

项目采用 **应用仓库 + 两个上游 fork**：`duplex-omni` 管理项目配置、运行入口、集成验证与交接资料；`vllm-omni` 和 `vllm` 保留独立 Git 历史，用 submodule 固定经过验证的源码组合，方便继续开发和跟进上游。

> 本 README 对应 2026-10-22 整合后的源码状态。项目仍在开发中，不是开箱即用的生产部署包。源码整合已经完成；新的源码目录尚未重新完成模型环境安装及 GPU 端到端验收。文中的历史测试结果不等同于新机器部署通过。

## 目录

- [项目目标与当前状态](#项目目标与当前状态)
- [系统架构](#系统架构)
- [仓库组织与版本基线](#仓库组织与版本基线)
- [获取项目](#获取项目)
- [环境与安装](#环境与安装)
- [部署与运行](#部署与运行)
- [配置与会话协议](#配置与会话协议)
- [验证与测试](#验证与测试)
- [日常开发与上游更新](#日常开发与上游更新)
- [日志资源与故障排查](#日志资源与故障排查)
- [已知限制与后续工作](#已知限制与后续工作)
- [文档与代码导航](#文档与代码导航)
- [许可证与第三方内容](#许可证与第三方内容)

## 项目目标与当前状态

### 阶段一：Qwen3-Omni streaming duplex

使用 `Qwen3-Omni-30B-A3B-Instruct` 的 thinker → talker → code2wav 三阶段流水线，提供：

- 文本、音频及模型支持的多模态输入。
- 多轮会话及上下文管理。
- 服务端 VAD 断句与自动提交。
- 回复文字和语音的流式输出。
- 朗读中打断、取消，以及播放 ACK 驱动的历史提交。
- 沿用 `realtime_web` 浏览器前端和 WebSocket 代理。

这里的 duplex 是**可以并行接收输入、按轮提交并打断输出**，不是模型原生的连续音频输入 KV 流。不要将其等同于逐帧增量 thinker 推理。

### 阶段二：MiMo 文本替换 + Qwen 原生语音链路

MiMo 直接接收原始输入并流式生成回复正文；Qwen thinker 保留真实 prompt prefill，多模态 hidden 仍参与 talker 输入，但其生成的回复文字不再作为语音正文。

跨模型边界传递的是 **MiMo 正文字符串**：用 Qwen tokenizer 重分词，再查 Qwen 的 embedding 表，按原生输入协议送给 talker。**不传 MiMo token ID、embedding 或 hidden，不训练或修改模型权重。**

### 历史验证记录

整合前的同机实验记录包括：

| 项目 | 结果与边界 |
|---|---|
| 相关 CPU 回归 | 500 项通过；这是原开发环境的记录，不是本 README 编写时重新运行的结果 |
| 短样例语音 | 英文、中文数字、中英混合、音频回复及取消后新轮共 5 个样例，经 MiMo 回转写人工核对与正文一致 |
| 长回答流式 | 单次样例首音频约 0.23 秒，早于 MiMo SSE 结束的约 2.34 秒；不是吞吐或延迟承诺 |
| 多轮与取消 | 已做记忆、朗读中取消、取消后新轮、纯文字、新会话 reset 和 UI 代理测试 |
| 本次源码整合 | 两库 11,369 个文件与原工作树做过内容/权限核对，语法与 Git 检查通过 |

独立 Qwen 原文本回灌的音频对照、受控慢 SSE、完整故障注入以及浏览器麦克风/VAD 听测矩阵仍待补齐。生成日志、WAV 和测试工具环境没有提交到本仓库。

## 系统架构

### 阶段一

```text
浏览器 / Realtime 客户端
          │ WebSocket
          ▼
realtime_web UI 代理
          │
          ▼
duplex 会话层：VAD、历史、轮次、取消、播放 ACK
          │
          ▼
Qwen thinker ──► Qwen talker ──► code2wav
   文本/hidden        codec         音频块
          └──────── 流式文字与音频 ───────► 客户端
```

### 阶段二

```text
                     同一轮原始输入与会话上下文
                              │
               ┌──────────────┴──────────────┐
               ▼                             ▼
       Qwen thinker prefill             MiMo 独立服务
       prompt layer-0 embedding         流式回复正文 SSE
       多模态 layer-24 hidden                │
               │                       稳定增量 Qwen 分词
               │                       Qwen embedding 查表
               └──────────────┬──────────────┘
                              ▼
                   原生 Qwen talker 输入协议
                              │ codec 块
                              ▼
                           code2wav
                              │ 音频流
                              ▼
                            客户端
```

桥接首包需要真实 Qwen prefill 和 MiMo 首个稳定文本 token；后续逐 token 发送文本 embedding，文本真正结束后才送结束条件。桥接同时管理正文事件、私有 prefill 传输以及取消清理，避免原 thinker 输出抢占 MiMo 正文。

当前桥接要求 Qwen async-chunk 流水线及本机 `SharedMemoryConnector`。它不是已验证的跨节点 RDMA 桥接实现。打断必须覆盖 MiMo、thinker、talker 和 code2wav，且旧轮输出不能重新写入新轮历史。

### 开发边界

| 仓库 | 应放置的开发内容 |
|---|---|
| `duplex-omni` | 项目级入口、业务会话策略、模型级联选择、部署配置、集成测试和文档 |
| `vllm-omni` fork | 多阶段执行、stage 数据传输、模型输入协议、engine/worker 扩展接口 |
| `vllm` fork | 底层模型支持、权重加载、算子、执行与调度改动 |

**当前状态机和桥接仍有 engine 内部耦合，代码暂留在 vllm-omni fork。** 本次没有为了分仓立即搬动实现。后续根据稳定扩展接口逐步抽离应用层逻辑，不以“文件名像状态机”为依据机械迁移。

## 仓库组织与版本基线

```text
duplex-omni/
├── README.md
├── .gitmodules
├── .gitignore
├── vllm-omni/                         # submodule：Applauzzz/vllm-omni
├── vllm-src/                          # submodule：Applauzzz/vllm
├── Doc/
│   ├── Qwen3_Omni_duplex_legacy/       # 阶段一历史交接
│   └── stage2-mimo-qwen-omni/          # 阶段二设计与交接
└── workspace/
    ├── configs/
    │   ├── demo_vad.json
    │   └── mimo_qwen_duplex.json
    ├── scripts/start_duplex_service.sh
    └── experiments/20261021_mimo_qwen_bridge/
        ├── start_services.py
        ├── validate_realtime.py
        └── verify_speech.py
```

`vllm-src/` 的目录名为了兼容现有配置和交接路径而保留，对应的远端仓库是 `vllm`。

初始化时的版本组合如下；**实际使用的提交以当前父仓库 gitlink 为准**，不要把该表当成自动跟随的分支版本：

| 子库 | 原始源码基线 | 项目提交 | 分支 |
|---|---|---|---|
| vllm-omni | `c0331048d` | `6a841874e`：Qwen duplex + MiMo streaming bridge | `duplex-stage2` |
| vllm | `ced6857afa` | `dd39f0d8be`：MiMo 回移；`ba860768a9`：环境依赖适配 | `duplex-stage2` |

vLLM 的模型回移和本机依赖删减是两个独立提交。依赖适配移除了部分 PyTorch 系列版本声明，**并不意味着运行时不需要 PyTorch、音频依赖或 CUDA 扩展**。

## 获取项目

```bash
git clone --recurse-submodules https://github.com/Applauzzz/duplex-omni.git
cd duplex-omni

git submodule status
```

已经克隆父仓库但未初始化子库：

```bash
git submodule update --init --recursive
```

下文除克隆步骤外，命令默认从 **duplex-omni 项目根目录**执行。`git submodule update` 按父库固定提交检出；`--remote` 会追随分支，不是复现固定版本的步骤。

## 环境与安装

### 硬件和模型前提

- 当前主要验证环境是 Linux、Python 3.12 和 NVIDIA CUDA；两库 Python 声明的交集为 `>=3.10,<3.14`，不代表全部版本都已完成本项目验证。
- 阶段二历史部署使用 8 × H20 96 GB 中的 7 卡：MiMo TP4 用 4 卡，Qwen 三阶段各 1 卡。
- 阶段一随 `demo_vad.json` 继承的配置采用 2 张可见卡：thinker 在逻辑卡 0，talker/code2wav 在逻辑卡 1。显存是否足够要按所选硬件和配置实际核查。
- 模型为 `Qwen3-Omni-30B-A3B-Instruct` 和 `MiMo-V2.6-Flash-RL`；权重、tokenizer 与配置文件由使用者另外准备，不包含在 Git 仓库中。
- MiMo 部署依赖可信 checkpoint 的 remote code，脚本会传 `--trust-remote-code`；不要加载不可信来源的模型代码。

### 依赖基线与构建边界

原开发环境读取到的关键版本为 Python `3.12.14`、PyTorch `2.13.0+cu129`、torchaudio `2.11.0+cu129`、torchvision `0.28.0+cu129`、transformers `5.14.1`、FlashInfer `0.6.18.post1`。这是环境记录，不是跨平台通用安装锁文件。

需要额外满足：

1. GPU 驱动、CUDA toolkit 和当前 PyTorch 构建相容。
2. vLLM 核心、MoE、FlashAttention 等扩展已经构建或安装为匹配版本；纯 Python 源码拷贝不能替代这些二进制组件。
3. CMake、Ninja、setuptools/setuptools-scm、编译器及构建涉及的 Rust 等工具按选定构建路径准备。
4. 两库平台 requirements 与前端/测试依赖已经安装。VAD 可使用本地 ONNX 模型或 `silero-vad` 后端。

构建细节参考子库文档：[vLLM 源码文档](vllm-src/README.md)、[vLLM-Omni 源码文档](vllm-omni/README.md)。构建可能获取外部依赖，本仓库不是离线自足的二进制发行包。

在**专门的项目环境**中安装，不要直接重装仍在服务其他实例的原环境。以下是依赖已经核对、PyTorch/CUDA 已准备好的源码安装步骤，不是完整的一键环境创建脚本：

```bash
python -m pip install -r vllm-src/requirements/build/cuda.txt

# --no-deps 防止安装时自动替换已核对的 PyTorch/算子组合；
# 必须事先满足子库 requirements，不能借此忽略缺失依赖。
VLLM_TARGET_DEVICE=cuda VLLM_VERSION_OVERRIDE=0.30.1.dev0 \
  python -m pip install --no-build-isolation --no-deps -e ./vllm-src

VLLM_OMNI_TARGET_DEVICE=cuda VLLM_OMNI_VERSION_OVERRIDE=0.1.0 \
  python -m pip install --no-build-isolation --no-deps -e ./vllm-omni

python -m pip check
```

这里的版本 override 沿用项目环境的基础版本标识，用于避免新 clone 的 tag 集合造成意外版本推导；**它不修改源码，也不证明 ABI 兼容**。升级源码后应重新选择版本及依赖组合。`pip check` 只能检查已声明依赖，不能检验被本机适配移除的版本约束或 CUDA ABI。

本项目的 UI/验证脚本还使用 FastAPI、Uvicorn、aiohttp、NumPy、soundfile 和支持 `proxy=None` 参数的 `websockets`。这些依赖应随所选环境安装；如使用 torch VAD 后端还需要 `silero-vad`。无需为了跑少量测试安装所有与本项目无关的模型 extras。

### 确认导入的是新子库

```bash
python -c 'import vllm, vllm_omni; print(vllm.__file__); print(vllm_omni.__file__)'
command -v python
command -v vllm
```

导入路径应指向本次 clone 的 `vllm-src/vllm/` 与 `vllm-omni/vllm_omni/`。仅把 cwd 切到新项目根，不会自动改变旧环境的 editable 安装。

## 部署与运行

### 共同准备

先激活上述匹配环境，并确认卡和端口没有被其他实例占用：

```bash
nvidia-smi --query-gpu=index,memory.used --format=csv
export NO_PROXY=localhost,127.0.0.1
export no_proxy=localhost,127.0.0.1

# 本机原目录布局示例；其他机器替换为自己的模型目录。
export MODEL_ROOT="$(realpath ../../modelbase/Omni)"
export QWEN_MODEL="$MODEL_ROOT/Qwen3-Omni-30B-A3B-Instruct"
export EXPERIMENT=workspace/experiments/20261021_mimo_qwen_bridge
```

`MODEL_ROOT` 中需存在两个 checkpoint 子目录。`QWEN_MODEL` 取绝对路径，让后端、UI 和验证客户端使用一致的模型标识；最终以 `/v1/models` 返回值为准。

### 阶段一：Qwen baseline

以下是与现有 `demo_vad.json` 设备配置一致的入口：单控制器启动，thinker 占逻辑卡 0，talker/code2wav 共享逻辑卡 1。物理卡 `0,1` 仅作示例，先确认空闲与显存容量。

```bash
CUDA_VISIBLE_DEVICES=0,1 vllm serve "$QWEN_MODEL" \
  --omni \
  --port 8092 \
  --deploy-config workspace/configs/demo_vad.json
```

保持该终端运行；后端就绪后另开终端启动下文 UI。本命令按当前配置和 CLI 对照编写，未在 README 编写时另起一套 GPU 服务验证。

仓库还保留了阶段一历史脚本 [start_duplex_service.sh](workspace/scripts/start_duplex_service.sh)，支持 `MODEL`、`DEPLOY_CONFIG`、`QWEN_GPUS`、`VLLM_PORT`、`UI_PORT`、`OMNI_CONDA_ACTIVATE`、`OMNI_CONDA_ENV` 等覆盖。

**该脚本不是上述双卡入口的直接替代：**它逐 stage 进程各暴露一张卡，而随库默认配置是 `devices=0/1/1`；显式 `QWEN_GPUS` 又要求每个 stage 的 `devices=0`。使用历史脚本前应提供一致的三进程部署配置；不要把 `demo_vad.json` 不经调整就用于该入口，也不要仅为绕过检查删除 GPU 校验。本次文档维护没有修改其启动逻辑。

### 阶段二：MiMo + Qwen 三阶段

在所选模型环境中执行：

```bash
python "$EXPERIMENT/start_services.py" \
  --bin-dir "$(dirname "$(command -v vllm)")" \
  --model-dir "$MODEL_ROOT"
```

脚本的当前固定分配：

| 服务 | 物理 GPU | 端口/作用 |
|---|---|---|
| MiMo TP4 + EP | `0,1,2,3` | `8090`，OpenAI 兼容流式接口，模型名 `mimo-v2.6-flash` |
| Qwen thinker | `4` | `8092`，duplex Realtime 后端 |
| Qwen talker | `5` | headless stage 1 |
| Qwen code2wav | `6` | headless stage 2 |
| stage 协调 | — | 本机 master port `26100` |
| realtime_web | — | 单独启动，示例端口 `7865` |

每个 Qwen stage 只看到一张卡，所以桥接配置把三个 stage 的 `devices` 都设为逻辑卡 `0`。MiMo 服务及 master 地址固定为本机 loopback。脚本尚没有自定义 GPU/端口选项；想换布局需要同时审查脚本和部署配置。

若 MiMo 已按相同模型名、端口运行，只需重启 Qwen 三阶段：

```bash
python "$EXPERIMENT/start_services.py" \
  --qwen-only \
  --bin-dir "$(dirname "$(command -v vllm)")" \
  --model-dir "$MODEL_ROOT"
```

`--qwen-only` 仍会等待既有 MiMo 的健康检查。启动脚本成功后服务进程留在后台；它不是常驻进程监督器。异常启动时会向本次仍存活的进程组发送 TERM，不负责管理其他实例。

### 浏览器 UI

阶段二启动器**不启动前端**。后端就绪后，在另一个已激活相同项目环境的终端、项目根执行：

```bash
export NO_PROXY=localhost,127.0.0.1
export no_proxy=localhost,127.0.0.1

python vllm-omni/examples/online_serving/realtime_web/server.py \
  --host 127.0.0.1 \
  --port 7865 \
  --profile qwen3-turn \
  --vad \
  --model "$QWEN_MODEL" \
  --ws-backend ws://127.0.0.1:8092
```

本机打开 `http://127.0.0.1:7865/`。远程使用时优先端口转发或带 HTTPS/WSS 的代理；浏览器麦克风需要安全上下文。该命令只监听 loopback，没有提供公网认证网关。不要为了 demo 把未配置访问控制的推理后端直接暴露到公网。

`--profile qwen3-turn` 和 `--vad` 需要明确指定；UI 的默认 profile/端口不是本项目的这组设置。远程浏览器通过同源代理连接后端时，不应直接使用服务器的 `127.0.0.1:8092`。

### 健康检查

```bash
curl --noproxy '*' -fsS http://127.0.0.1:8090/health      # 仅阶段二
curl --noproxy '*' -fsS http://127.0.0.1:8092/v1/models
curl --noproxy '*' -fsS http://127.0.0.1:7865/healthz
```

健康接口成功不代表正文与语音一致，仍需下面的多轮、取消和音频内容验证。

## 配置与会话协议

### 配置继承

```text
阶段一：workspace/configs/demo_vad.json
          └── vllm-omni/vllm_omni/deploy/qwen3_omni_moe.yaml

阶段二：workspace/configs/mimo_qwen_duplex.json
          └── demo_vad.json
               └── qwen3_omni_moe.yaml
```

`base_config` 相对所在配置文件解析。阶段二覆盖 `duplex_session` 及各 stage 的相关字段，不要假设所有嵌套对象都会递归合并。

主要默认项：

| 配置 | 默认含义 |
|---|---|
| `mimo_endpoint` / `mimo_model` | 本机 MiMo `8090` / `mimo-v2.6-flash`，仅桥接模式 |
| `max_sessions` | 1，不能把当前验收当成并发容量证明 |
| `idle_ttl_s` / `disconnect_grace_s` | 300 秒空闲回收 / 30 秒断线宽限 |
| `server_vad_defaults.threshold` | 0.95 |
| `prefix_padding_ms` / `silence_duration_ms` | 300 / 500 毫秒 |
| `min_speech_duration_ms` | 96 毫秒 |
| `create_response` / `interrupt_response` | VAD 自动创建回复 / 允许打断 |
| `server_vad_model_path` | null，允许自动发现模型或使用包后端 |

VAD 参数优先级：客户端 `session.update` 显式设置 → 部署默认 → 代码兜底。客户端把 `turn_detection` 设为 null 时禁用自动断句，部署默认不会强行覆盖它。显式配置无效的本地 ONNX 路径会报错，不会静默回退。

### Realtime 交互

客户端使用 `/v1/realtime` WebSocket，Qwen 项目路径通过 `duplex=1` 和匹配的 `model` 标识选择会话。常见事件有：

- `session.update`、`session.close`：设置或结束会话。
- `conversation.item.create` + `response.create`：文本轮。
- `input_audio_buffer.append` + `input_audio_buffer.commit`：音频积累与提交。
- `response.output_audio.delta`、`response.output_audio_transcript.delta`、`response.done`：流式回复。
- `response.cancel`：取消当前回复。
- `playback.ack`：客户端报告实际播放/提交进度。

接收到了音频并不代表用户听完。取消及播放 ACK 的处理会影响历史提交，不能用“全部收到的 transcript”代替已播放的回复历史。详细协议见 [fork 的 Realtime duplex API 文档](vllm-omni/docs/serving/realtime_duplex_api.md)。

## 验证与测试

### 不启动服务的检查

```bash
python "$EXPERIMENT/start_services.py" --help
python "$EXPERIMENT/validate_realtime.py" --help
python "$EXPERIMENT/verify_speech.py" --help
bash -n workspace/scripts/start_duplex_service.sh
```

### 相关单元回归

在已安装匹配模型库及 pytest、pytest-asyncio、pytest-mock 等测试依赖的项目环境运行。部分测试还依赖子库 `dev` 声明中的额外包，缺依赖时先补环境，不复制旧实验的 pyvendor：

```bash
python -m pytest \
  vllm-omni/tests/model_executor/models/qwen3_omni/test_mimo_bridge.py \
  vllm-omni/tests/model_executor/models/qwen3_omni/test_qwen3_omni_forward_contract.py \
  vllm-omni/tests/model_executor/models/qwen3_omni/test_duplex_plugin.py \
  vllm-omni/tests/engine/test_duplex_orchestrator.py \
  vllm-omni/tests/engine/duplex/test_session_runner.py \
  vllm-omni/tests/model_executor/stage_input_processors/test_qwen3_omni_streaming_helpers.py \
  vllm-omni/tests/distributed/omni_connectors/test_chunk_transfer_adapter.py \
  vllm-omni/tests/worker/test_omni_connector_mixin.py \
  vllm-omni/tests/worker/test_gpu_ar_model_runner.py \
  -q -p no:cacheprovider
```

通过单元测试不等于通过真实模型、语音内容或浏览器验收。测试项数量会随子库版本变化，不应固定断言每次都是 500。

### 已启动阶段二后端的验证

```bash
# 英文、数字、混合正文及长回答
python "$EXPERIMENT/validate_realtime.py" --model "$QWEN_MODEL" --mode samples

# 多轮文字历史
python "$EXPERIMENT/validate_realtime.py" --model "$QWEN_MODEL" --mode text

# 原始音频、朗读中取消、取消后新轮
python "$EXPERIMENT/validate_realtime.py" --model "$QWEN_MODEL" --mode audio

# 纯文字、长流、主动断线
python "$EXPERIMENT/validate_realtime.py" --model "$QWEN_MODEL" --mode textonly
python "$EXPERIMENT/validate_realtime.py" --model "$QWEN_MODEL" --mode streaming
python "$EXPERIMENT/validate_realtime.py" --model "$QWEN_MODEL" --mode disconnect

# 新会话不应继承上面的姓名；也可走 UI 的 WebSocket 代理
python "$EXPERIMENT/validate_realtime.py" --model "$QWEN_MODEL" --port 7865 --mode reset
```

验证脚本关闭自动 VAD，使用显式提交；音频模式中的取消是在收到输出音频后发送 `response.cancel`，**不是浏览器麦克风触发 VAD 打断的完整测试**。`reset` 检查新连接没有既有姓名，不是完整的 resume/reset 协议矩阵。

每轮输出保存在实验目录的 `turn_*.json` 与 `turn_*.wav`；重复同一模式会覆盖同名结果。要保留多轮实验记录，应在下一次运行前归档结果。

### 音频内容核对

先执行 `samples` / `audio` 产生文件，再利用 MiMo 回转写：

```bash
python "$EXPERIMENT/verify_speech.py" english numbers mixed
python "$EXPERIMENT/verify_speech.py" audio1 after_cancel
```

结果写入 `speech_transcription.json`，其中包含 `reference` 和 `asr`。该脚本不自动计算 WER/CER 或断言相等，需人工核对漏读、错读和尾部完整性；同模型回转写不能替代独立 ASR 和实际听测。使用私有录音时注意输入文件、输出日志及服务访问权限。

验收至少检查：正文与音频一致、首音频先于正文结束、取消后无旧轮输出污染、下一轮正常、客户端播放 ACK 与历史策略一致。

## 日常开发与上游更新

### 修改子库

submodule 初始化通常是 detached HEAD。编辑前先检查有无本地改动，再切到项目分支：

```bash
git -C vllm-omni status
git -C vllm-omni switch duplex-stage2

git -C vllm-src status
git -C vllm-src switch duplex-stage2
```

新 clone 中没有本地项目分支时，用对应命令替代 `switch`：

```bash
git -C vllm-omni switch -c duplex-stage2 --track origin/duplex-stage2
git -C vllm-src switch -c duplex-stage2 --track origin/duplex-stage2
```

不要盲目切换到远端最新提交后立即更新父库：先确认它与当前固定版本的差异，再决定是否采用。可从固定提交新建功能分支开展实验，避免影响已验证组合。

子库修改的交付顺序：

1. 在对应 fork 分支提交改动并完成相关验证。
2. 推送该分支，保证新 SHA 能从远端获取。
3. 在父库提交新 gitlink 和必要配置/文档，再推送父库。

```bash
# 示例：子库提交已完成且位于预期分支
git -C vllm-omni push origin duplex-stage2

# 父库固定新提交；本次是否更新另一个子库按实际验证组合决定
git add vllm-omni
git commit -m "chore: update validated vllm-omni revision"
git push origin main
```

`git add vllm-omni` 在父仓库只记录子库提交指针，不会替子库提交未提交的源码。父库 README、项目脚本及配置改动直接在父库提交。

### 跟进上游

本机整合时已配置 `origin` 为个人 fork、`upstream` 为原库；这些本机 remote 设置不会随父仓库 clone 自动传播。先查看，缺失时再添加：

```bash
git -C vllm-omni remote -v
git -C vllm-src remote -v

# 仅在 upstream 不存在时执行
git -C vllm-omni remote add upstream https://github.com/vllm-project/vllm-omni.git
git -C vllm-src remote add upstream https://github.com/vllm-project/vllm.git

git -C vllm-omni fetch upstream
git -C vllm-src fetch upstream
```

升级不是仅执行 `fetch`：在独立兼容性分支选择目标上游提交，合并或选择性回移，解决冲突，验证 **vLLM + vLLM-Omni + PyTorch/CUDA** 组合，再更新父库。不要强推已共享的项目分支，也不要默认使用 `git submodule update --remote` 替代兼容性验证。

开发约定：模型/执行机制与应用策略分层；实验按主题放 `workspace/experiments/`，日志放 `workspace/logs/`；不提交 checkpoint、环境、token、录音输出或构建缓存。

## 日志资源与故障排查

### 运行输出

- 阶段二服务日志和 PID：`workspace/logs/20261021_mimo_qwen_bridge/`。
- 阶段一历史脚本日志：`workspace/logs/<日期时间>_duplex_service/`。
- 语音验证结果：`workspace/experiments/20261021_mimo_qwen_bridge/turn_*`。

上述运行输出均应留在 Git 外。服务日志可能包含输入、回复或会话标识，分享前先脱敏；不要将 Git 凭据环境脚本提交进仓库。

### 停止服务

成功启动后脚本退出不代表服务退出。停止前先核对 PID 的命令行、模型、端口与归属；只停止本次实例，不使用全局 `pkill python` / `pkill vllm` 清空机器上的其他服务。

阶段二 PID 文件只记录本次启动的服务，UI 单独启动则需单独管理。历史阶段一脚本对 UI 的清理不完整，不应假设 EXIT trap 负责全部前后端。PID 文件可能陈旧，不能把其中数字当成无条件可杀进程。

### 常见问题

| 症状 | 优先检查 |
|---|---|
| 导入仍来自旧 Omni 目录 | editable 安装、当前 Python/`vllm` 所在环境及 `PYTHONPATH` |
| `_C`、FlashAttention、MoE 等导入失败 | 扩展是否构建，PyTorch/CUDA/驱动与二进制 ABI 是否匹配 |
| 模型找不到或 Realtime 拒绝模型名 | checkpoint 路径和 `/v1/models` 返回的标识是否与 UI/客户端一致 |
| UI 健康但 WebSocket 连接失败 | `--ws-backend`、`NO_PROXY/no_proxy`、后端端口与会话配置 |
| 浏览器麦克风不可用 | 安全上下文、麦克风授权、HTTPS/WSS 或本地端口转发 |
| Qwen stage 设备编号错误 | 单进程可见卡列表与 `devices`；双卡配置不能照搬到每进程单卡启动 |
| 文本正常但音频漏读/乱读 | 实际音频回转写、完整 prefill、稳定分词、codec EOS、取消与尾包生命周期 |
| `--qwen-only` 一直未就绪 | MiMo 是否已经在 8090 正常运行 |
| 连续打断后重答上一轮 | 当前已播放文本与历史提交策略，不要直接认定取消没有生效 |

## 已知限制与后续工作

1. 当前 MiMo 桥接限本机 SHM + Qwen async-chunk，跨节点传输未经完整验证。
2. `StableQwenTokenizer` 校验 Qwen tokenizer 的 NFC 与 Split/ByteLevel 结构；替换 tokenizer/checkpoint 后必须重新审查，不能把实现直接推广到任意模型。
3. MiMo bridge 使用 `enable_thinking=false`，消费正文 `content` 而非 reasoning；工具调用不受支持，特殊控制 token 或异常断流会作为失败处理。
4. 缺失真实 prefill 不会用全零 hidden 代替；任何“能出声音”的结果都不能直接算正文接入成功。
5. 默认单会话配置；并发容量、多用户资源隔离与生产部署安全不在当前实验结论之内。
6. 打断后部分回复的文字/音频对齐及历史截断仍有策略限制，不能宣称所有重答问题已解决。
7. 需要补独立 Qwen 回灌对照、更多语言/数字/长文本样例、受控慢流、断流/取消竞争、浏览器 VAD 及完整故障注入矩阵。
8. 新环境部署需重建或安装匹配组件，源码提交本身不是环境锁文件或模型部署证明。
9. 应用级状态机和级联策略的独立包/入口尚未抽离；优先定义 engine 扩展接口，保持可验证基线，再逐步迁移。

## 文档与代码导航

### 文档入口

- [MiMo 单核心双工 + Qwen3-TTS](Doc/stage3-mimo-single-omni/README.md)：已接通原实时前端、Silero VAD、MiMo 正文流与独立 TTS，支持播放 ACK 和打断恢复；[2026-10-26 阶段快照](Doc/stage3-mimo-single-omni/checkpoint_20261026.md)记录提交范围、验证和剩余验收项。
- 当前任务计划：`.planning/2026-10-25-mimo-single-omni-duplex/`；新会话先按 `AGENTS.md` 恢复状态。
- [阶段一交接入口](Doc/Qwen3_Omni_duplex_legacy/README.md)
- [阶段一架构](Doc/Qwen3_Omni_duplex_legacy/01_architecture.md)
- [阶段一历史起停与排错](Doc/Qwen3_Omni_duplex_legacy/02_running.md)
- [VAD 配置说明](Doc/Qwen3_Omni_duplex_legacy/03_vad_config.md)
- [历史已知问题](Doc/Qwen3_Omni_duplex_legacy/04_known_issues.md)
- [连续打断乱码排查](Doc/Qwen3_Omni_duplex_legacy/05_debug_barge_in_garbled_audio.md)
- [阶段一改动清单](Doc/Qwen3_Omni_duplex_legacy/06_change_log.md)
- [阶段二初始化与设计](Doc/stage2-mimo-qwen-omni/README.md)
- [阶段二执行计划](Doc/stage2-mimo-qwen-omni/plan_a.md)
- [MiMo × Qwen Talker 方案 A](Doc/stage2-mimo-qwen-omni/mimo_qwen3_omni_talker_plan_a.md)

阶段交接正文保留其历史时间点的机器路径、未提交状态和待验证事项。发生冲突时，先看当前源码与本 README，不将历史部署命令或 IP 当成当前实例信息。

### 关键实现

| 位置 | 作用 |
|---|---|
| [duplex_orchestrator.py](vllm-omni/vllm_omni/engine/duplex_orchestrator.py) | 会话与多 stage 协调、MiMo 接入、取消和输出分派 |
| [duplex/session/](vllm-omni/vllm_omni/engine/duplex/session/) | 会话管理、runner、历史/播放账本、租约 |
| [Qwen duplex plugin](vllm-omni/vllm_omni/model_executor/models/qwen3_omni/duplex/plugin.py) | Qwen 输入与模型会话适配 |
| [mimo_bridge.py](vllm-omni/vllm_omni/model_executor/models/qwen3_omni/duplex/mimo_bridge.py) | SSE、稳定分词、embedding、私有 prefill 与文本桥接 |
| [Qwen stage processor](vllm-omni/vllm_omni/model_executor/stage_input_processors/qwen3_omni.py) | thinker/talker/code2wav chunk 协议 |
| [qwen3_omni.py](vllm-omni/vllm_omni/model_executor/models/qwen3_omni/qwen3_omni.py) | 原生 talker 条件构造与文本结束保护 |
| [gpu_model_runner.py](vllm-omni/vllm_omni/worker/gpu_model_runner.py) | worker payload 同步与模型预处理 |
| [MiMo 模型](vllm-src/vllm/model_executor/models/mimo_v2.py) / [MTP](vllm-src/vllm/model_executor/models/mimo_v2_mtp.py) | fused FP8 QKV 权重/scale 分片回移 |
| [realtime_web](vllm-omni/examples/online_serving/realtime_web/) | UI、客户端 profile 和 WebSocket 代理 |
| [桥接单元测试](vllm-omni/tests/model_executor/models/qwen3_omni/test_mimo_bridge.py) | 分词、序列化、prefill/控制向量、取消和结束协议回归 |

## 许可证与第三方内容

两个子库分别保留各自的 Apache-2.0 许可证及第三方声明：[vLLM LICENSE](vllm-src/LICENSE)、[vLLM-Omni LICENSE](vllm-omni/LICENSE)。父仓库目前未单独声明许可证，不应仅因引用这两个子库就推定全部父库内容采用同一授权。模型权重的获取与使用遵守各自模型许可证，不能用代码许可证替代模型授权。
