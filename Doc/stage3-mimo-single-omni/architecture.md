# 架构分析

核对时间：2026-10-25。事实来源为历史 Doc、当前固定源码、本地模型配置和环境只读检查。
“源码支持”与“当前环境实测通过”分开记录。

## 1. Git 与源码基线

| 仓库 | 分支 | 当前提交 |
|------|------|----------|
| duplex-omni | main | 9628f6c |
| vllm-omni | duplex-stage2 | 6a841874ef56cf0590c5f5c24889a4ca65e6ac15 |
| vllm-src | duplex-stage2 | ba860768a965efadcf059089c04862c46e568242 |

开始分析时三棵工作树干净。父仓库用 submodule 固定组合，不自动跟随远端更新。
本轮不改推理代码；新的计划和知识库作为父仓库文件管理。

## 2. 三条现有路径

### Qwen3-Omni 双工

```text
浏览器收音/播放
  -> realtime_web 同源 WS 代理
  -> OmniDuplexSessionHandler
  -> DuplexSessionManager / Runner / EngineSession
  -> Qwen3OmniDuplexPlugin
  -> thinker -> talker -> code2wav
  -> Realtime 文本/音频事件与 playback.ack
```

每次音频提交重新构造带历史的 prompt，开启全新推理请求。
会话双工负责持续收音、轮次、打断和播放；async-chunk 负责单请求内的模型阶段流传输。
两者不是同一概念。2026-09-29 旧报告的 realtime/async-chunk 互斥限制
不能套用到当前 fork，当前级联明确要求 async-chunk。

### MiMo-Qwen 级联

```text
已裁剪的同一份会话上下文
  -> Qwen thinker: 真实 prompt prefill，max_tokens=1 作为载体
  -> MiMo 独立服务: 原始音频/文本等输入 -> 正文 SSE
两者汇合:
  Qwen prefill + MiMo 字符串的 Qwen 重分词/embedding
  -> Qwen talker -> Qwen code2wav
```

`DuplexOrchestrator` 在初始化时限制该桥接必须是 Qwen3OmniDuplexPlugin、
async-chunk 和本机 SharedMemoryConnector。原 thinker 正文被丢弃。
因此不能只替换某个 stage 配置就移除 Qwen 理解模型。

### 单独 MiMo

2026-10-19 记录已通过 TP4/TP8 + EP 加载和正文流测试；2026-10-22 README
也记录了级联原始音频样例。本轮不把这些历史结果升级为新树实测。

当前 `vllm-src` 的 `MimoV2ModelArchConfigConvertor` 检测到 `vision_config`
后将 checkpoint 声明的 MiMoV2ForCausalLM 转成 MiMoV2OmniForCausalLM，
后者加载视觉/音频塔并组合 MiMoV2FlashForCausalLM。
这解决了静态类选择问题，不能代替实际音频输入验证。
另一个 `mimo_audio` pipeline 是不同模型，不用于本目标。

## 3. 会话层可复用能力

| 源码位置，均在 vllm-omni 下 | 能力与限制 |
|----------------------------|------------|
| vllm_omni/entrypoints/duplex/serving.py | WS 协议转译、连接生命周期，不是业务状态机 |
| vllm_omni/engine/duplex/session/manager.py | 准入、租约、会话路由 |
| vllm_omni/engine/duplex/session/runner.py | 单会话有序 mailbox、异步模型任务、取消 |
| vllm_omni/engine/duplex/session/engine_session.py | response/历史/播放状态与 epoch/fence |
| vllm_omni/engine/duplex/session/playback_ledger.py | ACK 检查与已播放历史 |
| vllm_omni/engine/duplex/turn_detection.py | Silero 声学 VAD、speech_started/stopped 与自动 commit |
| vllm_omni/engine/duplex/session/overlap_policy.py | 打断/继续/丢弃、时长/RMS/短附和规则 |
| vllm_omni/engine/duplex/contracts.py | DuplexStagePort 与不可变 fenced 请求/输出类型 |

首选项目侧实现外部模型服务适配器，通过 DuplexStagePort 组合现有 session manager/runner。
逻辑通道可表示 MiMo 正文和 TTS 音频，但它们不是统一 vLLM 调度的物理 stage。
必须先验证注册、终态、采样参数、虚拟 stage 输出与取消账本的契约。
未验证前不承诺现有 runner 可以无修改复用，也不另写第二套历史账本。

MiMo SSE 与音频消息转换可以从现有桥接中提取为窄接口。
现有 `build_mimo_messages` 引用 Qwen history formatting，桥接顶层还导入 torch/SHM；
新入口不应整包依赖该模块。禁止把 MiMo token ID/hidden 跨模型传给 TTS。

## 4. Qwen3-TTS 可用组件

模型路径：
`/mnt/geminihzceph/user_whynotzhliu/modelbase/Omni/Qwen3-TTS-12Hz-1.7B-CustomVoice`。

| 项目 | 当前证据 |
|------|----------|
| 模型 | custom_voice、1b7；主权重 3,833,402,552 字节 |
| 音色 | vivian、serena、uncle_fu、ryan、aiden、ono_anna、sohee、eric、dylan |
| tokenizer | 独立文本 tokenizer；16 路 codec；24 kHz speech tokenizer |
| 帧率 | 1,920 samples/frame，实际 12.5 fps |
| pipeline | qwen3_tts/pipeline.py，talker -> code2wav，无 duplex_plugin |
| 部署默认 | qwen3_tts.yaml，MRV2、async_chunk、两 stage 均 devices=0 |
| chunk 默认 | 首包 1 帧，常规 25 帧，左上下文 72 帧 |
| 对外接口 | /v1/audio/speech，/v1/audio/speech/stream |
| 文本切分 | SpeechTextSplitter 已处理数字、缩写、多语标点与尾部分隔符 |

首版优先独立 HTTP PCM 合成请求：项目管理分段、任务及 response/fence，
TTS 服务管理 codec/audio streaming。WS 默认全文缓冲；句子/子句模式才提前合成，
且 receive loop 会等待当前合成，未提供 Realtime 的 response.cancel 协议。
HTTP 路径有 shielded generator close，但断连后两个 TTS stage 是否真实停止仍须验收。

分段文本必须带原正文字符区间、segment_id、累计音频 sample offset。
已完成段的“合成文本覆盖范围”不等于段内逐字发声时间。
首版仅提交 ACK 覆盖的完整段，部分段保留未知；词级对齐属于后续独立验证，
不能用字符比例或可选 word_timestamps 参数伪称精确。

## 5. 目标数据流

```text
浏览器 / 现有 WS 代理
  -> 项目侧 MiMo duplex 入口
      输入通道: PCM 缓冲 -> Silero -> 轮次/语义决策 -> commit
      会话通道: 统一历史、epoch/fence、ACK、资源预算
      MiMo: 音频/文本 -> 正文 SSE
      输出通道: 稳定文本分段 -> Qwen3-TTS HTTP PCM -> 有序播放
      取消通道: fence 失效 -> 清播放 -> 关闭/取消 MiMo 和 TTS 请求
```

输入持续接收，不因 MiMo/TTS 等待而停读；输出顺序和队列预算有界。
MiMo 正文结束、TTS 完成、播放完成分别记账，不用同一个 done 标志混合。
所有 await 后及发包前验证 response/fence；旧轮文本、音频、语义决策均不得落入新轮。

## 6. VAD 与语义状态机

当前 Silero 判断声学语音；`server_vad` 会把 speech_stopped 当成结束，
并强制 barge_in_on_speech；校验拒绝 interrupt_response=false。
现有短附和白名单不是可靠的语义完成/抢话模型。

新状态至少分两条正交轴，避免“正在输出就不能听”的单状态限制：

- 输入：IDLE / SPEECH / END_PENDING。
- 输出：IDLE / GENERATING / PLAYING / CANCELLING；合成与播放可同时活跃。

声学证据先触发候选结束/候选抢话；纯状态 reducer 决定 commit、wait、
continue、interrupt 等动作。语义适配器提供带 input_revision/fence 的异步结果，
不把 VAD 概率直接当成语义结论。噪声、附和、句中停顿、回声和真实抢话分别测试。

首版声学策略与语义增强策略必须显式分开。语义原型可试同一 MiMo 的受控音频判断请求，
但它需要新增推理、会与正文服务争资源，且不是已有训练好的语义 VAD。
准确率、额外延迟、超时降级规则通过独立样例后才能启用；回声处理也不能只靠提高 VAD 阈值。

## 7. 环境与风险

| 环境 | 只读检查 |
|------|----------|
| 默认 liu | Python 3.12.14，torch 2.7.1+cu126，transformers 4.56.2；有 pytest，缺 vllm/omni/VAD/pytest-mock |
| 历史 omni | Python 3.12.14，torch 2.13.0+cu129，transformers 5.14.1；有 VAD，缺 pytest 系列 |
| omni 导入源 | /Omni/vllm-src 与 /Omni/vllm-omni，而非 /Omni/duplex-omni 子模块 |

不默改 serving 环境的 editable 安装。选择隔离测试环境/显式源码运行方式后，
先核验导入及二进制兼容。历史 8xH20/7 卡级联资源是部署记录，不是本轮空闲证明。
目标可先规划 MiMo TP4 + 独立 TTS 1 卡，但实际显存和可用卡必须现场测量。

优先风险：错源码验收、MiMo 多模态加载、TTS 真取消、分段韵律/空音频、
部分播放重答、队列积压、旧 epoch 污染、语义误判及语义请求额外成本。
