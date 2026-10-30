# 当前 MiMo Semantic VAD 实现详解

> 2026-10-28 v0.3 工作树更新：VASD 已改为 8 秒默认滑窗的 A/B 有语义/
> 无语义分类；首个 speech chunk 即判断。VAED 保持 AVAD speech-stop 后判定。
> VASD 滑窗只限制分类输入，`DECODE` 必须向普通 MiMo Chat 交付本轮所有已
> 接受音频。用户无主动交互意图时由 Chat Prompt 要求模型精确输出
> `listening`；不再使用受限 LISTENING/GENERATE 分类、阈值或 KV sidecar。
> 2026-10-28 标签更新：VASD 的受限输出为 `需要`/`不需要`，分别映射
> `<b>`/`</b>`；VAED 的受限输出为 `已`/`未`，分别映射 `<c>`/`</c>`。
> 这四个字符串在当前 MiMo tokenizer 中均为单 token。

更新时间：2026-10-28
分支：`feature/SVAD`
规范来源：`duplex_input_fsm_function_spec.md`
主要实现：`workspace/experiments/20261025_mimo_tts_integration/semantic_vad.py`
调试服务：`workspace/experiments/20261025_mimo_tts_integration/svad_debug_server.py`

本文主体记录 v0.2 的实现和历史验收证据；文件开头的 2026-10-27 注记描述
当前 v0.3 工作树差异。涉及 REJECT、A/B/C VASD 的正文均属于 v0.2 历史，
不代表 v0.3 当前策略。
它不是新的功能规格；状态机的权威规则仍然是
`duplex_input_fsm_function_spec.md`。

## 1. 状态说明

当前需要区分两类事实：

1. **规范要求**：三状态 FSM、A/B VASD、VAED Complete、四类控制事件。
2. **当前运行服务 `svad20`**：加载 v0.3 VASD 滑窗、完整 `decode_audio`
   Chat 交付和外部 CosyVoice 流式 TTS；v0.2 记录仅作为历史证据。

当前运行服务快照（2026-10-29）：

| 服务 | PID | 监听 | 资源 | 状态 |
|---|---:|---|---|---|
| MiMo | 42095 | `127.0.0.1:8090` | GPU 0-3 | 运行中 |
| SVAD UI `svad20` | 403729 | `28.29.217.180:8080` | CPU | 运行中 |
| External CosyVoice3 | 外部服务 | `29.213.195.135:8100` | 服务外部管理 | 运行中 |

当前 `svad20` 服务包含：

- Silero AVAD。
- MiMo VASD / VAED。
- 受限单 Token logprob 分类。
- `Silence / Judge / Listen` FSM。
- Silence 区间日志。
- FSM 图与持久时间轴。
- MiMo 文本 Chat。
- MiMo 增量文本块、单任务连续 `text_idx` submit、并发 CosyVoice poll 和
  浏览器 PCM 播放。策略为 `EagerTTSStrategy`，不是等待完整回复后再合成。
- 三个可编辑中文 Prompt。
- VAED 只在 AVAD `speech_stopped` 下降沿运行。
- `</c>` 后跨静音保持 Listen，恢复说话后继续同一轮。
- VAED `<c>` 概率、margin、确认次数和 8 秒静音兜底配置。

## 2. 总体架构

```text
浏览器麦克风
    |
    | PCM16 音频批次
    v
SVAD WebSocket 服务
    |
    +--> Silero AVAD
    |      输出 speech / probability / started / stopped
    |
    +--> 三状态 Input FSM
    |      Silence / Judge / Listen
    |
    +--> MiMo VASD
    |      Judge 中判断 BREAK / NO_BREAK / REJECT
    |
    +--> MiMo VAED
    |      Listen 中判断 COMPLETE / INCOMPLETE
    |
    +--> FSM DECODE
           |
           +--> MiMo Chat SSE 文本回复
           +--> 浏览器右侧对话框
```

三个 MiMo 任务共享同一个模型服务、同一个 backbone 和同一套权重：

```text
MiMo-V2.6-Flash-RL @ 127.0.0.1:8090
    |
    +-- VASD 短生命周期请求
    +-- VAED 短生命周期请求
    +-- Chat 流式生成请求
```

当前没有三个持久模型 Session，也没有三套长期 KV Cache。
每次 VASD、VAED、Chat 都是独立 HTTP 请求。

## 3. 三种时间尺度

当前系统中存在三个不同的音频处理粒度。

### 3.1 浏览器发送批次

浏览器通过 AudioWorklet 持续采集 PCM16。
页面使用可配置的 `audio_chunk_ms` 作为最小目标提交间隔，默认 500 ms，
即目标 0.5 秒一个浏览器音频 chunk。

实际发送可能长于目标间隔：

- 同一时间只允许一个音频请求 in-flight。
- 如果模型慢，多个 worklet 数据会合并成一个较长批次。
- 页面使用最小间隔 gate，不主动提交短于 `audio_chunk_ms` 的批次。

因此日志中的 `chunk` 是网络/调度批次，不是固定时长语音帧。

### 3.2 Silero AVAD 帧

Silero 内部处理固定为：

```text
512 samples @ 16 kHz = 32 ms
```

一个浏览器批次进入 Silero 后会被拆成多个 32 ms 帧。

Silero 使用：

- 激活阈值 `threshold`。
- 负阈值滞回。
- `min_speech_duration_ms`。
- `silence_duration_ms`。
- `prefix_padding_ms`。

AVAD 持续运行，不由 MiMo 执行声学 VAD。

### 3.3 MiMo 语义判断窗口

MiMo VASD / VAED 接收的是**累计音频**，不是孤立的最新 chunk，但调用时机不同。

Judge 中：

```text
第一次 VASD：候选音频 [0, T1]
第二次 VASD：候选音频 [0, T2]
第三次 VASD：候选音频 [0, T3]
```

Listen 中的 active speech chunk 不调用 VAED。只有 AVAD 报告
`speech_stopped=true` 时，才把当前完整累计话轮交给 VAED：

```text
第一次声学端点：VAED 输入 [0, T1]
若返回 </c>，用户恢复说话并继续累计
第二次声学端点：VAED 输入 [0, T2]
```

当前不是 MiMo 原生增量音频 KV 推理。每次请求都重新把累计音频编码成 WAV，
再调用 `/v1/chat/completions`。

## 4. FSM 状态

FSM 只有三个公开状态。

### 4.1 Silence

职责：

- 持续运行 AVAD。
- 不调用 VASD。
- 不调用 VAED。
- 不触发 Prefill 或 Decode。

规则：

```text
speech=0 -> Silence / NO_OP
speech=1 -> Judge / NO_OP
```

### 4.2 Judge

职责：

- 累积候选音频。
- 调用 MiMo VASD。
- 判断是否应该打断当前助手回复。
- 执行 Reject。

规则：

```text
reject=0 AND break=1 -> Listen / PREFILL / interrupt=true
effective_break=0 AND speech=1 -> Judge / NO_OP
effective_break=0 AND speech=0 -> Silence / NO_OP
```

Reject 不增加 FSM 状态：

```text
reject=1 -> effective_break=0
```

### 4.3 Listen

职责：

- 已经确认有效 Break。
- 继续接收用户音频。
- 只在声学停止下降沿调用 MiMo VAED。
- 判断用户语义是否完成。

v0.2 规则：

```text
speech=1 -> Listen / CHUNK_PREFILL，不运行 VAED
speech_stopped=1 AND complete=0 -> Listen / CHUNK_PREFILL，进入语义等待
speech=0 AND 已判断 complete=0 -> Listen / NO_OP，不重复运行 VAED
等待期间 speech=1 -> Listen / CHUNK_PREFILL，继续同一轮
speech_stopped=1 AND complete=1 -> Silence / DECODE
语义未完成静音达到外部超时 -> Silence / DECODE
```

进入 Listen 必须来自：

```text
break=1 AND reject=0
```

Listen 中不再执行 Reject。

## 5. 音频缓存

### 5.1 Silence 前缀缓存

Silero 的 `speech_active` 可能在真实词首之后才激活。
为避免丢失开头音频，adapter 在 Silence 中保留有限前缀：

```text
prefix_padding_ms + min_speech_duration_ms + 32 ms
```

当 AVAD 激活时，前缀块和当前块一起进入 Judge 候选缓存。

### 5.2 Judge 候选缓存

从 `Silence -> Judge` 起累积候选音频。

- NO_BREAK / REJECT：继续缓存。
- `Judge -> Silence`：丢弃缓存。
- BREAK：所有候选音频一次性作为初始 PREFILL 载荷。

### 5.3 Listen 轮次缓存

Break 后候选缓存复制为完整轮次缓存。
之后每个有效 Listen chunk：

- 加入完整轮次缓存。
- 作为 CHUNK_PREFILL 的新增载荷。
- 不重复提交已经交付的旧 chunk。

语义未完成后的重复静音块不进入轮次缓存，也不再次调用 VAED。

### 5.4 Decode 音频

当前工作树的 `FSMOutput.decode_audio` 在 DECODE 时携带完整 accepted-turn 音频。
Chat 使用这份完整轮次音频，而不是只使用最后一个 chunk。

## 6. VASD 分类

### 6.1 外部规范标签

```text
<b>     -> BREAK
</b>    -> NO_BREAK
REJECT  -> 拒识
```

### 6.2 为什么不直接比较这些 Token

MiMo tokenizer 实测：

| 标签 | Token 数 |
|---|---:|
| `<b>` | 2 |
| `</b>` | 3 |
| `<c>` | 2 |
| `</c>` | 3 |
| `REJECT` | 2 |

因此它们不是单 Token，不能直接在单个生成位置比较 logprob。

### 6.3 内部分类码

运行时使用现有单 Token：

| 内部码 | Token ID | 映射 |
|---|---:|---|
| `A` | 32 | `<b>` |
| `B` | 33 | `</b>` |
| `C` | 34 | `REJECT` |

请求参数：

```json
{
  "max_tokens": 1,
  "temperature": 0.0,
  "logprobs": true,
  "top_logprobs": 0,
  "logprob_token_ids": [32, 33, 34],
  "allowed_token_ids": [32, 33, 34]
}
```

`allowed_token_ids` 限制第一生成位置只能输出 A/B/C。
`logprob_token_ids` 强制响应返回全部候选的 logprob。

### 6.4 VASD 中文 Prompt

```text
你是双工语音助手的语义打断分类器。请根据候选用户音频，只输出一个分类码：
A：用户正在对助手表达有意义的请求或问题，应当打断助手，对应 <b>；
B：音频内容可以理解，但不应打断助手，对应 </b>；
C：没有可接受的有效语义，例如环境噪声或无法辨认的声音，对应 REJECT。
只能输出 A、B 或 C，不得解释。
```

## 7. VAED 分类

### 7.1 外部规范标签

```text
<c>   -> COMPLETE
</c>  -> INCOMPLETE
```

### 7.2 内部分类码

| 内部码 | Token ID | 映射 |
|---|---:|---|
| `A` | 32 | `<c>` |
| `B` | 33 | `</c>` |

请求参数：

```json
{
  "max_tokens": 1,
  "logprobs": true,
  "logprob_token_ids": [32, 33],
  "allowed_token_ids": [32, 33]
}
```

### 7.3 VAED 中文 Prompt

```text
你是双工语音助手的语义结束分类器。请根据当前累计的用户音频，只输出一个分类码：
A：用户语义已经完整，助手可以开始回答，对应 <c>；
B：用户仍在表达未完成的意思，需要继续聆听，对应 </c>。
只能输出 A 或 B，不得解释。
```

## 8. Logprob 与置信度

VASD 和 VAED 分别在自己的候选集合中归一化：

```text
P_i = exp(logprob_i - max_logprob)
      / sum_j exp(logprob_j - max_logprob)
```

VASD 概率空间：`{<b>, </b>, REJECT}`。
VAED 概率空间：`{<c>, </c>}`。

页面字段：

- `confidence`：选中类别的归一化概率。
- `margin`：第一名和第二名的原始 logprob 差。
- `semantic_logprobs`：所有规范标签的原始 logprob。

VASD 和 VAED 的 confidence 来自不同分类空间，不能直接横向比较。

## 9. 旧运行版问题

旧 `svad07` 在 active speech 前缀上反复运行 VAED，并采用 argmax：

```text
如果 <c> 的 logprob 大于 </c>，立即 complete=1
```

真实日志中以下低置信度 `<c>` 也曾立即 Decode：

| P(`<c>`) | margin |
|---:|---:|
| 77.7% | 1.25 |
| 70.6% | 0.875 |
| 62.2% | 0.50 |
| 56.2% | 0.25 |

这解释了“一段话还没说完就开始 Decode”。该行为已由 `svad08` 的
声学端点触发模式替换。

## 10. 当前 v0.2 VAED 完成策略

VAED 只在每个 AVAD `speech_stopped` 下降沿评估一次完整累计话轮。默认接受条件：

```text
P(<c>) >= 0.90
AND margin >= 2.0
AND 当前确认次数达到配置值
```

默认参数：

```text
complete_probability_threshold = 0.90
complete_margin_threshold = 2.0
complete_confirmations = 1
incomplete_silence_timeout_ms = 8000
```

行为：

- 模型输出 `<c>` 但不满足阈值：FSM 输入仍为 `complete=0`。
- 默认第一次高置信度 `<c>` 即触发 DECODE。
- 如果把确认次数设为 N，大于等于 N 个声学端点连续给出合格 `<c>` 才触发 DECODE。
- 任意 `</c>` 或低置信度 `<c>`：确认计数归零。
- `</c>` 后保持 Listen；重复静音不重跑 VAED，也不追加到轮次缓存。
- 用户恢复说话时继续同一 Listen 轮次，不重新运行 VASD。
- 未完成静音达到 8 秒默认超时后，由外部策略兜底 DECODE。

日志区分：

- `semantic_command=<c>`：模型原始判断。
- `completion_accepted=false`：策略未接受。
- `completion_confirmation_count`：当前连续确认数。

## 11. 语义未完成静音等待

典型链路：

```text
“帮我规划一个去北京的行程，别急着规划，让我想想去哪好呢？”
    -> AVAD speech_stopped
    -> VAED </c>
    -> 保持 Listen，跨静音等待
“反正必须要去天安门”
    -> 继续同一 Listen 话轮
    -> 下一次 speech_stopped
    -> VAED <c>
    -> DECODE
```

adapter 使用 `_semantic_waiting` 和 `_incomplete_silence_started`：

- `</c>` 后开始静音计时并保持公开状态 Listen。
- 重复静音返回 NO_OP，不追加音频、不重跑 VAED。
- speech 恢复时清除等待计时，继续累计当前话轮。
- 8 秒默认超时发出外部兜底 DECODE。

它不是第四个 FSM 状态，只是 Listen 内部的外部计时策略。

## 12. Chat 推理

### 12.1 触发条件

只有 FSM 发出 `DECODE` 才启动 Chat：

```text
Listen -> Silence / DECODE
    -> 完整 decode_audio
    -> MiMo Chat SSE
```

### 12.2 Chat 中文 Prompt

```text
你是一个实时语音对话助手。请直接理解用户音频并回答用户的问题。
回复应自然、简洁、口语化，优先使用一到三句话；不要输出 Markdown，不要展示思考过程。
始终使用用户所使用的语言回答。
```

每个音频 user message 后还附加：

```text
这是用户对你的提问。请直接回答问题，不要转写、复述或描述这段音频。
```

### 12.3 对话历史

最多保留 4 个完成轮次：

```text
user audio + 中文回答提示
assistant text
```

历史属于当前 WebSocket 会话，断开后丢弃。

### 12.4 Chat 打断

新的有效 BREAK：

- 取消当前 Chat task。
- 关闭当前 MiMo HTTP 流。
- 页面收到 `chat.cancelled`。
- FSM 进入 Listen 接收新用户轮次。

## 13. All-in-one 配置

页面顶部“全部设置”面板集中暴露：

- audio chunk ms，范围 50 到 5000 ms。
- AVAD threshold。
- prefix padding、silence duration、min speech duration。
- max buffered chunks。
- VASD break probability、margin、confirmations。
- VAED complete probability、margin、confirmations。
- semantic-incomplete silence timeout。
- VASD、VAED、Chat 三个中文 Prompt。

服务端默认值来自仓库内文件：

```text
workspace/experiments/20261025_mimo_tts_integration/svad_config.json
```

`/defaults` 每次请求都会重新读取并完整校验该文件，不缓存。因此直接在服务器
本地修改 JSON 后刷新网页，表单和下一次建立的 WebSocket 会话都会使用新值，
不需要重启 MiMo 或 SVAD UI。JSON 格式或字段非法时页面显示明确错误，不会静默
混用旧值与新值。

标准 JSON 不支持 `//` 或 `#` 注释。文件使用顶层 `_说明` 对象保存每个参数和
Prompt 的中文说明；服务端忽略该对象，只读取 `config` 和 `prompts`。

三个中文 Prompt 是：

- VASD Prompt。
- VAED Prompt。
- Chat Prompt。

点击“应用全部设置”发送完整 `configure`：

```json
{
  "type": "configure",
  "audio_chunk_ms": 500,
  "threshold": 0.5,
  "prefix_padding_ms": 300,
  "silence_duration_ms": 500,
  "min_speech_duration_ms": 96,
  "max_buffered_chunks": 512,
  "break_probability_threshold": 0.8,
  "break_margin_threshold": 1.5,
  "break_confirmations": 1,
  "complete_probability_threshold": 0.9,
  "complete_margin_threshold": 2.0,
  "complete_confirmations": 1,
  "incomplete_silence_timeout_ms": 8000,
  "vasd_prompt": "...",
  "vaed_prompt": "...",
  "chat_prompt": "..."
}
```

未启动麦克风时，表单值在下一次启动时统一应用。会话运行中重新应用会取消
当前 Chat、关闭旧 adapter、按新数值重建 AVAD/FSM/语义策略，并同时更新三个
Prompt。更新只影响当前 WebSocket 会话，不写模型目录，不修改全局服务。

## 14. 日志

### 14.1 Silence 区间

连续 `Silence -> Silence` 不逐块写 INFO。

离开 Silence、reset 或连接关闭时写一条：

```json
{
  "state": "Silence",
  "started": 0,
  "ended": 0,
  "duration_ms": 1200.0,
  "audio_chunk_count": 4,
  "reason": "state_change",
  "session_id": "svad-..."
}
```

### 14.2 语义 logprob

`mimo_semantic_logprobs` 记录：

- request_id。
- VASD / VAED。
- 内部 A/B/C code。
- 规范 command。
- probability。
- margin。
- 全候选 logprobs。

### 14.3 状态转移

`semantic_vad_transition` 记录：

- previous_state / next_state。
- speech。
- break / reject / complete。
- FSM event。
- 模型内部 code。
- 规范语义 command。
- 所有候选 logprob。
- confidence / margin。
- completion accepted / confirmation count。
- Prefill / Decode 音频 chunk 数。
- 判定延迟。

## 15. 前端可视化

页面包括：

- 三节点 FSM 图。
- 六个规范 Token 的边标签。
- 当前节点和最近边高亮。
- 状态持久时间轴。
- AVAD probability。
- VASD / VAED 结果。
- 全候选 logprob、confidence、margin。
- VAED 完成策略接受状态与确认次数。
- semantic-incomplete silence wait 和已等待时长。
- 右侧 Chat 对话框。
- 三个中文 Prompt 编辑器。

## 16. 已验证证据

### 16.1 VASD / VAED

真实保存语音：

```text
VASD -> <b>
P = 97.53%
margin = 4.25

VAED -> <c>
P = 99.96%
margin = 7.875
```

### 16.2 Reject

一秒低幅白噪声：

```text
REJECT
67.3 ms
```

### 16.3 Chat

输入：

```text
三加四等于几？
```

初版问题：

- Chat 只转写问题。
- 语义完成后的声学尾音开启第二轮并取消第一条回复。

修正后探测 `chat_probe_20261026T154033Z`：

```text
chat_started = 1
chat_cancelled = 0
reply = 三加四等于七。
```

## 17. 当前已知限制

1. MiMo VASD / VAED 每次重新编码累计 WAV，不复用模型侧音频 KV。
2. `audio_chunk_ms` 是最小目标批次间隔；后端忙时实际批次会更长。
3. v0.2 已通过 35 项核心/WebSocket 回归，但真实北京长句仍需浏览器验收。
4. 当前没有训练后的真实 `<b>/<c>` 单 Token；A/B/C 只是内部分类码。
5. 当前没有 Speak Head；DECODE 后默认启动 Chat。
6. 当前已接入外部 CosyVoice3 TTS；Audio Engine 无 cancel 端点，因此本地
   BREAK 只能停止 poll 与浏览器播放，已提交的上游任务可能继续执行。
7. 页面历史只存在于当前浏览器 WebSocket 会话。
8. 尚未完成多语言、回声、多人背景音和长会话统计验收。

## 18. 推荐后续验证

1. 使用北京示例、长句、枚举句和句内停顿测试端点 VAED。
2. 分别统计 `<c>` 与 `</c>` 的概率分布和 margin。
3. 调整 `complete_probability_threshold`、`complete_margin_threshold` 和
   `complete_confirmations`。
4. 验证 8 秒未完成静音兜底是否符合实际交互节奏。
5. 验证真实浏览器中新 BREAK 对长 Chat 回复的取消。
6. 浏览器实测真实麦克风下的 TTS 可听首包、回声和 BREAK 后即时静音；当前
   服务端与协议回放已通过，但浏览器端没有播放 ACK 账本。
