# Stage 2：MiMo × Qwen3-Omni Streaming Duplex — 项目初始化文档

> 本文是阶段 2 的入口文档（/init）。接手者 / Agent 先读本文，再按需读同目录的方案文档和
> `Doc/Qwen3_Omni_duplex_legacy/`（阶段 1 交接资料）。
> 文中代码位置均已对照当前工作区核对（2026-10-19，vllm-omni `main` @ `c0331048d` + 阶段 1 未提交改动）。

## 当前仓库组织（2026-10-22）

`duplex-omni` 保存项目配置、启动/验证脚本及交接资料；项目根的两个子目录是 Git submodule：

- `vllm-omni/` → `https://github.com/Applauzzz/vllm-omni.git`
- `vllm-src/` → `https://github.com/Applauzzz/vllm.git`

两个 fork 的开发分支为 `duplex-stage2`，父仓库固定具体提交。分别保留上游 Git 历史；vLLM 的 MiMo 回移与本机依赖调整独立提交。本次只完成仓库组织，紧耦合的状态机/级联实现仍在 vllm-omni fork，后续再按扩展接口分层。

本机子仓库已经配置 `origin` 为 fork、`upstream` 为原库。新克隆不会继承本机 Git remote 配置，首次跟进上游可在项目根执行：

```bash
git -C vllm-omni remote add upstream https://github.com/vllm-project/vllm-omni.git
git -C vllm-src remote add upstream https://github.com/vllm-project/vllm.git
```

`git submodule update --init --recursive` 按父库固定提交检出，通常处于 detached HEAD。需要修改子库时先切到 `duplex-stage2` 或新建开发分支；先提交并推送子库，再在父库提交更新后的 gitlink。

```bash
git clone --recurse-submodules https://github.com/Applauzzz/duplex-omni.git
```

安装模型环境时使用上述子仓库源码；当前机器原环境仍关联旧工作区，本次未重新安装或启停服务。子仓库各自保留 `.git`，版本推导不依赖父仓库的 `init commit`。此后更新上游应先在 fork 的兼容性分支合并并验证，再更新父仓库的 submodule 提交，不自动追随最新 main。

从项目根调用脚本时显式配置外部路径。以下是当前机器布局的示例（其他机器替换相应参数），首次部署须先安装匹配的两库、PyTorch/CUDA 及模型环境，不能仅用现有环境路径就认为已切换源码：

```bash
OMNI_CONDA_ACTIVATE=../../my_envs/miniconda3/bin/activate \
OMNI_CONDA_ENV=omni \
MODEL=../../modelbase/Omni/Qwen3-Omni-30B-A3B-Instruct \
bash workspace/scripts/start_duplex_service.sh

python workspace/experiments/20261021_mimo_qwen_bridge/start_services.py \
  --bin-dir ../../my_envs/miniconda3/envs/omni/bin \
  --model-dir ../../modelbase/Omni

python workspace/experiments/20261021_mimo_qwen_bridge/validate_realtime.py \
  --model "$(realpath ../../modelbase/Omni/Qwen3-Omni-30B-A3B-Instruct)" --mode samples
```

启动脚本占用固定 GPU/端口，运行前先确认资源，不要与旧实例同时启动。验证脚本的 `--model` 必须与后端服务公开的模型标识一致；后端使用绝对模型路径作为标识时，请传对应绝对路径。日志和验证输出不提交。

以下正文保留原阶段计划与历史观测；其中“未提交”“尚未验证”和机器路径是记录当时的状态，不表示本次重新完成了 GPU 或部署验收。

## 0. 文档索引

| 文档 | 内容 |
|---|---|
| `README.md`（本文） | 项目定位、已核实的代码事实、目标架构、阶段计划、工程约定 |
| `mimo_qwen3_omni_talker_plan_a.md` | 方案 A 原稿：跨模型只传字符串、先做 Qwen 文本回灌对照实验。**注意其中与本项目前提的差异，见 §2.3** |
| `../Qwen3_Omni_duplex_legacy/` | 阶段 1：三阶段流水线、duplex 引擎、起停服务、已知问题（打断后重答等） |

---

## 1. 项目定位

**阶段 1（已完成）**：基于 vllm-omni 搭建 Qwen3-Omni-30B-A3B 的 streaming duplex 语音对话（VAD 断句、打断、
前端），三阶段 thinker → talker → code2wav。

**阶段 2（本项目）**：用 **MiMo 的文字输出替换 Qwen3-Omni thinker 给 talker 的文字生成部分**，
保留 Qwen3-Omni thinker 产生的多模态 hidden。talker 最终接收：

```
[控制/提示部分 emb] + [Qwen thinker 多模态 middle hidden] + [MiMo 输出文本的 emb]
```

硬性要求：

1. **保持 Qwen3-Omni 的 streaming 特性**：talker 边收文本边出 codec，code2wav 边出音频。
2. **MiMo 纳入 streaming 设计**：MiMo 增量出字 → 增量喂 talker，不能等 MiMo 整段生成完。
3. 保留 duplex 能力：VAD、打断（barge-in 需同时取消 MiMo / thinker / talker / code2wav）。
4. 不训练、不改权重。

---

## 2. 已核实的关键事实

### 2.1 Checkpoint 与环境

| 项 | 值 |
|---|---|
| Qwen ckpt | `/mnt/geminihzceph/user_whynotzhliu/modelbase/Omni/Qwen3-Omni-30B-A3B-Instruct`（~66 GB，bf16） |
| MiMo ckpt | `/mnt/geminihzceph/user_whynotzhliu/modelbase/Omni/MiMo-V2.6-Flash-RL`（~166 GB） |
| GPU | 8 × H20 96 GB |
| Python env | `/mnt/geminihzceph/user_whynotzhliu/my_envs/miniconda3/envs/omni` |
| vLLM | `0.30.1.dev0`，源码安装于 `/mnt/geminihzceph/user_whynotzhliu/vllm-src`（tag `v0.30.0`） |
| transformers | 5.14.1 |
| vllm-omni | `Omni/vllm-omni`（`main`，阶段 1 的 13 个文件改动**仍未提交**，见 legacy `06_change_log.md`） |

**MiMo-V2.6-Flash-RL**（`config.json` / `README.md`）：

- `architectures: MiMoV2ForCausalLM`，`model_type: mimo_v2`；48 层（39 SWA + 9 GA，window 128），hidden 4096，
  MoE 256 路由专家 / 激活 8；原生全模态（带 `vision_config`、`audio_config`、`audio_tokenizer/`）。
- 量化：`fp8`（e4m3）+ `store_dtype: mxfp4`；带 MTP（`num_nextn_predict_layers: 3`）和 `dflash/` 投机解码草稿模型。
- **是推理模型**：chat template 有 `<think>…</think>` 和 `enable_thinking` 开关；官方推荐
  `--reasoning-parser mimo --tool-call-parser mimo`，`--tensor-parallel-size 4`，采样 `temperature=1.0, top_p=0.95`。
- vLLM 源码已有 `vllm/model_executor/models/mimo_v2.py`（`MiMoV2ForCausalLM`）、`mimo_v2_omni.py`
  （`MiMoV2OmniForCausalLM`）、`mimo_v2_mtp.py`。**该 ckpt 的 mxfp4 存储格式、多模态塔能否被当前 vLLM 正常加载，尚未验证。**
- vllm-omni 里已有的 `mimo_audio` pipeline（`vllm_omni/deploy/mimo_audio.yaml`、
  `stage_input_processors/mimo_audio.py`）是另一个模型 MiMo-Audio，**与本项目无关**，不要混用。

**Qwen3-Omni**：thinker text hidden 2048，vocab 152064；`talker_config.accept_hidden_layer = 24`；
talker 控制 token：`codec_pad/bos/eos = 2148/2149/2150`，`codec_nothink/think_bos/think_eos = 2155/2156/2157`。

**GPU 预算**：MiMo TP4（4 卡）+ Qwen 三阶段（各 1 卡，共 3 卡）= 7 卡，8 卡内可放下，但无冗余。

### 2.2 Qwen3-Omni thinker → talker 的真实输入协议

这是本项目最关键的接口，全部基于源码：

**(1) Thinker 只导出两层**：layer 0（= `embed_tokens` 查表结果）和 layer 24（`accept_hidden_layer`）。
`qwen3_omni.py:288` `_thinker_capture_layer_indices()` 返回 `[0, accept_hidden_layer]`。

**(2) Talker prefill 组装**：`qwen3_omni.py:1007` `_thinker_to_talker_prefill()` 按 `<|im_start|>` 切 ChatML 段：

| 段 | Talker 输入 | 代码 |
|---|---|---|
| system | **整段丢弃**（"Talker should ignore thinker system prompt"） | `qwen3_omni.py:1051-1053` |
| user（每轮） | 文本位置：`text_projection(layer0 embed)`；audio/image/video 位置：`hidden_projection(layer24 hidden)` | `qwen3_omni.py:1171` `_get_talker_user_parts` |
| 历史 assistant | **丢弃** | `qwen3_omni.py:1080-1082` |
| 当前 assistant | 9 个位置：`<\|im_start\|>assistant\n` 3 个 + 4×`tts_pad` + `tts_bos` + **第 1 个文本 token**；叠加 codec 控制 embed（`nothink, think_bos, think_eos, speaker_id, codec_pad, codec_bos`） | `qwen3_omni.py:1216` `_get_talker_assistant_parts` |

`stage_input_processors/qwen3_omni.py:79` `_compute_talker_prompt_ids_length()` 按同样规则算 talker 占位长度
（user 段总长 + 9）。

**(3) Talker decode：每个 codec 步消费 1 个文本 token**。`qwen3_omni.py:1090` `_thinker_decode_to_talker_decode()`：
取下一个 thinker 生成 token 的 **layer0 embedding** → `text_projection` → 与 codec embed 相加；
文本耗尽后先送 `tts_eos`，之后一直送 `tts_pad`。

**(4) Streaming 传输（`async_chunk: true`，`deploy/qwen3_omni_moe.yaml:15`）**：
`stage_input_processors/qwen3_omni.py:370` `thinker2talker_async_chunk()`：

- chunk 0：`embed.prefill`（prompt 全部 layer0）+ `hidden_states.output`（prompt 全部 layer24）+ `tts_bos/eos/pad`
  + `ids.all/prompt` + speaker/language；需等到至少 1 个生成 token 后才发出（`:457`）。
- chunk ≥1：`embed.decode`，形状 `[1, 2048]`，**每个生成 token 一个 chunk**，带 `meta.finished`。
- talker 侧在 chunk 未到达时停在 `WAITING_FOR_CHUNK`（`core/sched/omni_scheduling_coordinator.py`），
  即 **talker 节奏天然由上游文本速度门控**。超时 `VLLM_OMNI_INPUT_WAIT_TIMEOUT_S`（默认 600s）。
- talker → code2wav：`talker2code2wav_async_chunk()`（`:640`），首包 4 帧、之后 25 帧一包、左上下文 25 帧。

### 2.3 由此得到的设计结论

1. **"MiMo 输出文本的 emb" = Qwen thinker 的 `embed_tokens`（Qwen 重分词后的 MiMo 文本）**。
   assistant 文本在原链路里本来就只是 layer-0 查表，**不需要 thinker forward**。跨模型边界只传字符串，
   MiMo 的 token id / embedding / hidden 一律不进入 Qwen —— 这与 plan A 的原则一致。
2. **"多模态 middle hidden" = 只在 user 段的 audio/image/video 位置使用 layer-24 hidden**，这部分仍需 Qwen thinker
   对 prompt 做 prefill。也就是说 thinker 从"prefill + 自回归解码"退化为"只做 prefill"。
3. **与 plan A 的差异**：plan A 主张 text-only、尽量省略 thinker forward、"目标不等于 sys_emb + middle_hidden + mimo_text_emb"。
   本项目前提是**保留 thinker 多模态 hidden**，所以 plan A 的 Phase 1（文本回灌对照实验）、"只传字符串"、
   "禁止捷径"仍然适用；但"移除 thinker forward"不是目标，**保留 thinker prefill**。
4. **关于"sys prompt emb"**：当前代码中 talker **完全不看 system 段**，也不看历史 assistant 段。
   若需要"sys prompt emb"进入 talker，属于**改变原生输入协议**（模型训练时没见过），需要对照实验证明无害；
   默认建议沿用原生协议（system 只给 MiMo 和 Qwen thinker 用）。→ 待决策 D3。
5. **ID 空间不可混用的实例**：MiMo `audio_token_id=151669` 在 Qwen 里是 `<|audio_start|>`；
   MiMo 的 EOS 之一 `151672` 在 Qwen 里是 `<tts_text_bos>`；词表 152576 vs 152064。

---

## 3. 目标架构（streaming）

```
浏览器 ──WS──▶ server.py(UI 代理) ──▶ vllm serve --omni (duplex 引擎)
                                        │
          user audio/text/image ────────┼──────────────────────────────┐
                                        ▼                              ▼
                     Qwen thinker (stage 0, 只 prefill)          MiMo (TP4, 独立服务或新 stage)
                     导出 prompt 的 layer0 embed                 流式生成回复文本
                     + layer24 hidden (多模态位置)                    │
                                        │                       reasoning 过滤（丢 <think>）
                                        │                              │
                                        │                     增量 Qwen 重分词（稳定前缀）
                                        │                              │
                                        │                     Qwen embed_tokens 查表 [1,2048]
                                        ▼                              ▼
                              chunk 0: prefill payload        chunk ≥1: embed.decode（逐 token）
                                        └──────────┬───────────────────┘
                                                   ▼
                                     Qwen talker (stage 1, 原生协议不变)
                                                   ▼
                                     code2wav (stage 2) ──▶ 音频流
```

**桥接层（新代码）的职责**：

1. 同一轮内协调 Qwen thinker prefill 与 MiMo 生成，二者可并行；chunk 0 需要 prefill 结果 + MiMo 首个稳定 token。
2. MiMo 增量文本 → 过滤 reasoning / 工具调用 / 特殊 token → 用 Qwen tokenizer 增量编码。
   **跨 chunk 分词边界**：只发出"后续文本不会再改变其分词"的稳定 token（保留尾部若干字符），流结束时 flush。
3. 用 Qwen thinker `embed_tokens` 把 Qwen token id 转成 layer0 embedding，按原 async_chunk 协议发给 talker；
   同时构造 `ids.all`，使当前 assistant 段的 id 与发出的 embedding 对齐（talker 依赖 ids 切段、算长度）。
4. MiMo 结束 → 发 `meta.finished=True`，talker 自动接 `tts_eos`。
5. 文字 transcript 事件改由 MiMo 文本驱动（原来是 stage 0 文本输出，`duplex/plugin.py:72` `project()`）。

**会话 / duplex 层**：

- 每轮 prompt 同时为两个模型构造：MiMo 的消息（MiMo chat template）和 Qwen thinker 的 ChatML（历史 assistant
  内容应是 **MiMo 的回复**，以保证 thinker 的 user 段 hidden 在同样的上下文下计算）。
- 打断：除现有取消路径外，必须 abort MiMo 请求；被打断回复的历史截断策略见 legacy `04_known_issues.md` §二.1。
- **潜在收益（待验证）**：talker 每个 codec 步消费 1 个文本 token，桥接层知道"第 k 个 token 在第 k 步被送入"，
  可产出近似的文本-音频对齐（`audio_text_mark`），有望从根上解决阶段 1 的"打断后重答"。需实测 talker
  发音相对文本输入的延迟/偏移后再下结论。

---

## 4. 待决策问题（开工前需确认）

| # | 问题 | 选项 / 现状 |
|---|---|---|
| D1 | **MiMo 的输入是什么？** | (a) 直接喂原始音频/图像给 MiMo（它是原生全模态）；(b) Qwen thinker 先转写成文字再给 MiMo（多一次 thinker 解码，延迟高）；(c) 先做纯文本输入 PoC |
| D2 | **MiMo 以什么形态接入？** | (a) 独立 `vllm serve`（OpenAI 流式 API），桥接层做客户端，改动小、易调试；(b) 作为 vllm-omni pipeline 新 stage，与 thinker/talker 统一调度、统一 abort，工作量大 |
| D3 | talker 是否需要 system prompt emb | 默认否（保持原生协议）；如需，作为对照实验单独评估 |
| D4 | MiMo thinking 模式 | 语音场景建议 `enable_thinking=false` 降低首字延迟；若开启，`<think>` 内容绝不送 talker |
| D5 | thinker 的角色 | 只做 prefill（`max_tokens` 最小化）/ 继续生成文本作为对照基线 |
| D6 | 阶段 1 未提交改动 | 开分支前先按 A/B/C/D 分组提交，避免与阶段 2 改动混在一起 |

---

## 5. 阶段计划

每一步都要保留原链路作为对照，失败要写清阻塞点（plan A §8 的要求同样适用）。

| Phase | 内容 | 门槛 |
|---|---|---|
| P0 基线 | 起阶段 1 服务确认可用；单独起 MiMo（TP4）验证能加载、能流式出字、测 TTFT/吞吐 | MiMo 在当前 vLLM 上可用 |
| P1 Dump | 在 `thinker2talker_async_chunk` / `talker_preprocess_prefill` 处 dump 一轮完整 payload（shape、dtype、ids、各段长度） | 能画出逐位置的 talker 输入表 |
| P2 Qwen 回灌 | Qwen 自己的回复文本 → decode → Qwen 重分词 → embed 查表 → 按原协议喂 talker，与原链路比对 | 音频与原链路一致/等价（ASR 回转录） |
| P3 MiMo 离线 | 单轮：Qwen thinker 只 prefill + MiMo 完整文本 → talker → wav | 中/英/数字/混合 10~20 条样例通过 |
| P4 MiMo 流式 | MiMo 增量文本 → 稳定分词 → 逐 token chunk；测 TTFA 分段（thinker prefill / MiMo TTFT / talker / code2wav） | 无漏读、无提前 EOS、无断续 |
| P5 Duplex | 接入 duplex 引擎：双模型 prompt 构造、transcript 事件、打断取消 MiMo、历史策略；前端沿用阶段 1 | 阶段 1 的脚本化打断复现可跑通 |
| P6 对齐（可选） | 基于 talker 文本消费步产出文本-音频对齐，修复"打断后重答" | — |

验收指标沿用 plan A §5，另加：`mimo_ttft_ms`、`thinker_prefill_ms`、`talker_wait_for_chunk_ms`
（talker 因 MiMo 慢而饿死的时间）。

---

## 6. 代码地图（阶段 2 会动到的地方）

| 位置 | 作用 |
|---|---|
| `vllm_omni/model_executor/models/qwen3_omni/pipeline.py` | 三阶段拓扑、各 stage 的 processor 挂载点 |
| `vllm_omni/model_executor/stage_input_processors/qwen3_omni.py` | thinker→talker（`:370` async_chunk，`:485` full_payload，`:577` token_only）、talker→code2wav（`:640`） |
| `vllm_omni/model_executor/models/qwen3_omni/qwen3_omni.py` | talker 输入组装：`:866` prefill，`:1007` 切段，`:1090` decode 取文本，`:1171`/`:1216` user/assistant 段 |
| `vllm_omni/model_executor/models/qwen3_omni/qwen3_omni_moe_talker.py` | `text_projection` / `hidden_projection` |
| `vllm_omni/model_executor/models/qwen3_omni/duplex/plugin.py` | duplex 插件：`:141` capabilities，`:221` prompt 构造，`:299` 历史格式化，`:379` 拼请求，`:72` 输出投影 |
| `vllm_omni/engine/duplex/session/` | 会话状态机、runner、打断、playback ledger（见 legacy `01_architecture.md` §2） |
| `vllm_omni/core/sched/omni_scheduling_coordinator.py` | `WAITING_FOR_CHUNK` 门控 |
| `vllm_omni/deploy/qwen3_omni_moe.yaml`、`qwen3_omni_duplex.yaml`、`workspace/configs/demo_vad.json` | 部署配置（`async_chunk`、connector、VAD） |
| `vllm-src/vllm/model_executor/models/mimo_v2*.py` | vLLM 的 MiMo 实现 |
| `examples/online_serving/realtime_web/` | 前端 + WS 代理 |

---

## 7. 工程约定

- **目录**：实验脚本/测试放 `workspace/experiments/<YYYYMMDD>_<主题>/`，日志放 `workspace/logs/`，不要散落在根目录；
  阶段 2 的文档放本目录。
- **Bash 用相对路径**（工作目录 `Omni/`）；Read/Write/Edit 工具用绝对路径。
- **删除**：只在 Omni workspace 内删除，且先 `mv` 到 `/data/trash`，不直接 `rm`。
- **起停服务**：沿用 legacy `02_running.md`（`pkill` 用 `[v]llm`/`[s]erver.py` 写法、起停分开、启动约 6~7 分钟）。
  MiMo 加入后 GPU 分配要显式指定，启动脚本自动挑 3 张空闲卡的逻辑需要改造。
- **测试**：`omni` 环境无 pytest，用 legacy `02_running.md` §8 的 `PYTHONPATH=.../pyvendor` 方式。
- **安全底线**（来自 plan A）：不要把 MiMo token id 当 Qwen token id；不要把 MiMo embedding/hidden 写进 talker；
  不要用全零 hidden 冒充多模态 hidden；不要绕过原生 speaker / BOS / EOS / codec 对齐逻辑；
  不要对每个文本 chunk 重跑整句 TTS 假装流式。

---

## 8. MiMo 单独部署冒烟记录（2026-10-19）

**结论**：MiMo-V2.6-Flash-RL 已在 8 卡 H20 上跑通，TP8 可用。

**关键前提（本地改动）**：v0.30.0 的 `mimo_v2.py` 不认识这份 ckpt 的 fused QKV 布局
（ckpt 按 4 份预切，SWA 层 13568 行 / scale 108 行），TP4 报
`size of tensor a (1856) must match tensor b (1792)`，TP8 报 KV head 断言。
需把 v0.31.0 的 `mimo_v2.py` + `mimo_v2_mtp.py` 回移（`mimo_v2_omni.py` 依赖 0.31 的
`MultiModalDummyOptions`，**不要**回移）。
- patch：`workspace/experiments/20261019_mimo_smoke/backport_mimo_v0.31.0.patch`
- 离线切分验证：`workspace/experiments/20261019_mimo_smoke/check_qkv_shard_v031.py`

**启动命令**（8 卡全用）：

```bash
vllm serve ../modelbase/Omni/MiMo-V2.6-Flash-RL \
  --served-model-name mimo-v2.6-flash --tensor-parallel-size 8 --enable-expert-parallel \
  --trust-remote-code --gpu-memory-utilization 0.90 --max-model-len 32768 \
  --reasoning-parser mimo --port 8090 --host 127.0.0.1
```

TP4+EP 亦可（`--tensor-parallel-size 4` 且 `CUDA_VISIBLE_DEVICES=0,1,2,3`）。

**实测数据**：

| 项 | TP4+EP | TP8+EP |
|---|---|---|
| 权重加载 | 65 shards / 164s | 65 shards / 165s |
| 单卡显存（权重后） | ~47 GB | ~30 GB |
| KV cache | 39.6 GiB，122 万 token | 59.3 GiB，314 万 token |
| 中文短句 TTFT | 0.25 s | 0.24 s |
| 长回答吞吐 | ~64 tok/s | ~190 tok/s |
| 8 并发聚合 | — | ~639 tok/s |
| 启动到就绪 | ~11 min | ~14 min |

**接口注意事项**：
- **thinking 字段名是 `reasoning`**（不是 `reasoning_content`），流式 delta 里键名也是 `reasoning`。
- `enable_thinking=false` 时模板注入 `<think></think>`，模型直接出正文；`true` 时先出 reasoning。
  语音场景建议用 `false`，避免 reasoning 拖高首字延迟。
- ckpt 是 `quant_method=fp8` + `store_dtype=mxfp4`（专家权重 U8 + U8 scale），0.30 的
  `Mxfp4MoEMethod` 能正常吃，不需要为 MXFP4 升级 vLLM。
