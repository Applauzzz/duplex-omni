# Duplex Input FSM：AVAD + Semantic VAD 功能规格说明

> 版本：v0.3（VASD 改为有/无语义二分类滑窗；DECODE 保留完整已接收上下文）
> 用途：提供给 Omni模型 作为输入控制模块的实现与验收依据。
> 参考：`speech_fsm_en.pdf`（Speech interaction: VAD FSM and inference behavior）及后续语义窗口约定。

## 1. 目标

实现一个用于实时双工语音对话的 **Input Controller**。控制器通过独立的声学 VAD（AVAD）和基于 Omni 模型的语义 VAD（VASD、VAED），使用 **三个 FSM 状态**决定当前音频应如何被处理，以及何时向推理系统发出 **Prefill / Chunk Prefill / Decode** 指令。

本期目标是严格复现当前约定，不额外引入其他状态、判定规则或交互策略。

- **AVAD**：是否检测到语音活动，对应 `speech ∈ {0,1}`。
- **VASD**：当前滑动音频窗口是否包含可识别语义，对应 `break ∈ {0,1}`；有语义即进入 Listen/Prefill，无语义继续 Judge。
- **VAED**：当前输入是否已经语义完成，对应 `complete ∈ {0,1}`。
- **FSM**：只有 `Silence`、`Judge`、`Listen` 三个状态。
- **Inference**：按 FSM 事件执行 `Prefill`、`Chunk Prefill` 或触发 `Decode`。

这里的“打断”指发出中断当前模型回复的控制指令；实际停止 Thinker/Talker 生成及播放由下游推理系统执行。

## 2. 模块组成与职责

| 组件 | 输入 | 输出 | 职责 |
|---|---|---|---|
| Acoustic VAD（AVAD） | 实时音频块 | `speech` | 检测声学语音活动；各状态均持续运行 |
| Semantic VASD（Omni） | 最近 x 秒滑动音频窗口 | `break` | `<b>`：有可识别语义；`</b>`：无可识别语义 |
| Semantic VAED（Omni） | 正在收听的音频及必要上下文 | `complete` | 在 `Listen` 状态判断语义是否结束 |
| Input FSM | 当前状态及上述判定值 | 下一状态、控制事件 | 严格按第 5 节的规则转移 |
| Inference Scheduler（外部） | 控制事件及对应音频 | 执行状态 | 实际执行 Prefill、Chunk Prefill、Decode 或中断 |

> VASD 和 VAED 使用 Omni 模型实现；它们可以共享底层模型实例，但对 FSM 暴露的是两个独立的语义判断接口。此处不规定具体模型、Prompt 或训练细节。

## 3. 语义信号与六个 Special Token

采用以下 **三个二值语义信号、六个 Special Token**；本期不更名、不增加其他 Special Token。

| 信号 | `1` 的 Token | `0` 的 Token | 定义 | 提供方 |
|---|---|---|---|---|
| `speech` | `<s>` | `</s>` | 1：有语音活动；0：无语音活动 | AVAD |
| `break` | `<b>` | `</b>` | 1：窗口中有可识别语义；0：窗口中无可识别语义 | VASD |
| `complete` | `<c>` | `</c>` | 1：语义完成；0：尚未完成 | VAED |

**使用规则：**

1. `speech` 的判定结果由 **声学 AVAD** 提供；`<s>`、`</s>` 是该信号的约定语义标记，不要求 Omni 模型重新执行声学 VAD。
2. `break` 只在 `Judge` 状态作为语义判断参与状态转移。
3. `complete` 只在 `Listen` 状态作为语义判断参与状态转移。
4. 三个信号对 FSM 均为布尔值。上述 Token 映射用于训练标注、消息序列化或日志表达，具体承载方式由实现确定，但不改变其语义。

### 3.1 VASD 滑动窗口

- 配置 `vasd_window_ms` 定义 VASD 可见的最大最近音频时长。
- 窗口未满时使用当前已有前缀：`[t0]`、`[t0,t1]`、……。
- 以 500ms chunk、8s 窗口为例，满窗口后依次判断 `[t0..t15]`、`[t1..t16]`、……。
- 滑动只作用于 VASD 分类输入；完整 Judge/Listen 音频上下文不得被裁剪。
- VASD 模型只允许两个单 token 中文分类码：`需要 -> <b>`，`不需要 -> </b>`，其他 logits 屏蔽。

## 4. FSM 状态定义

### 4.1 `Silence`

- **职责**：监控是否出现语音活动。
- **运行模块**：AVAD。
- **状态行为**：`speech=0` 时维持 `Silence`；`speech=1` 时进入 `Judge`。
- **不做的事**：不运行 VASD/VAED 判定，不因输入触发 Prefill。

### 4.2 `Judge`

- **职责**：判断当前声音是否应该打断模型。
- **运行模块**：AVAD + VASD。
- **优先级**：**先判断有效 `break`，否则再依据 `speech` 决定维持或退出。**
- **状态行为**：`break=1` 时进入 `Listen` 并发出 `PREFILL`；`break=0` 且 `speech=1` 时留在 `Judge`；`break=0` 且 `speech=0` 时返回 `Silence`。
- **首块判断**：`Silence -> Judge` 后，当前首个 speech chunk `t0` 立即执行一次 VASD。

### 4.3 `Listen`

- **职责**：在已确认打断后持续接收完整用户轮次，并在声学停顿点判断语义是否完成。
- **运行模块**：AVAD 持续运行；VAED 只在 AVAD 从 active 变为 stopped 的下降沿运行。
- **语音进行中**：`speech=1` 时不运行 VAED，保持 `Listen`，新增音频触发 `CHUNK_PREFILL`。
- **声学停顿**：`speech_stopped=1` 时，将当前轮次的全部累计音频一次性送入 VAED。
- **语义未完成**：`complete=0 ∧ speech=0` 时保持 `Listen`，允许跨越静音等待用户继续，不触发 Decode。
- **恢复说话**：语义未完成的等待期间重新出现 `speech=1`，继续同一轮 `Listen` 和 `CHUNK_PREFILL`，不重新运行 VASD。
- **语义完成**：只有 VAED 的有效 `complete=1` 才转入 `Silence` 并发出 `DECODE`。
- **超时兜底**：VAED 返回未完成后持续静音超过外部配置的等待时间，可由运行策略触发 `DECODE`；超时不是第四个 FSM 状态。

## 5. 状态转移表（实现的唯一权威规则）

| 当前状态 | 判定条件 | 下一状态 | 对外动作 |
|---|---|---|---|
| `Silence` | `speech=0` | `Silence` | `NO_OP` |
| `Silence` | `speech=1` | `Judge` | 进入打断语义判断；暂不 Prefill |
| `Judge` | `break=1` | `Listen` | `PREFILL`；通知下游打断当前回复 |
| `Judge` | `break=0 ∧ speech=1` | `Judge` | `NO_OP`；继续滑窗判断 |
| `Judge` | `break=0 ∧ speech=0` | `Silence` | `NO_OP`；结束当前候选输入 |
| `Listen` | `speech=1`（普通语音块） | `Listen` | `CHUNK_PREFILL`；不运行 VAED |
| `Listen` | `speech_stopped=1 ∧ complete=0` | `Listen` | `CHUNK_PREFILL` 当前终点块；跨静音等待 |
| `Listen` | `speech=0 ∧ 已判断 complete=0` | `Listen` | `NO_OP`；不重复运行 VAED |
| `Listen` | 等待期间重新 `speech=1` | `Listen` | `CHUNK_PREFILL`；继续同一轮 |
| `Listen` | `speech_stopped=1 ∧ complete=1` | `Silence` | `DECODE` |
| `Listen` | 语义未完成静音达到外部超时 | `Silence` | `DECODE`（外部兜底策略） |

说明：`Judge` 按 **Break 优先** 判断。`Listen` 不再把普通 `speech=0` 直接等价为轮次结束；VAED 的完整轮次判断决定是否结束。

```mermaid
stateDiagram-v2
    [*] --> Silence
    Silence --> Silence: speech=0
    Silence --> Judge: speech=1
    Judge --> Listen: break=1 / PREFILL + interrupt
    Judge --> Judge: break=0 & speech=1
    Judge --> Silence: break=0 & speech=0
    Listen --> Listen: speech=1 / CHUNK_PREFILL
    Listen --> Listen: speech_stopped & complete=0 / wait continuation
    Listen --> Listen: speech resumes / CHUNK_PREFILL
    Listen --> Silence: speech_stopped & complete=1 / DECODE
    Listen --> Silence: incomplete-silence timeout / DECODE
```

## 6. 对推理系统的控制语义

FSM 只**发出事件**，不在状态机内部实现 GPU 调度、KV Cache 修改或音频播放。

| 事件 | 产生时机 | 下游要求 |
|---|---|---|
| `NO_OP` | 维持或退出没有有效打断的检测阶段 | 不因该事件改变当前模型推理流程 |
| `PREFILL` | `Judge → Listen`，且有效 `break=1` | 发出打断指令；将已接收的当前有效输入送入 Prefill |
| `CHUNK_PREFILL` | `Listen` 中收到新增语音，或收到第一次语义未完成的声学终点块 | 将新增音频 Chunk 送入增量 Prefill |
| `DECODE` | `Listen → Silence`，由声学终点上的有效 `complete=1` 或外部静音超时触发 | 将本轮所有已接受音频交给 Chat，并开始 Decode 阶段 |

在 `Silence` 和未确认 `break=1` 的 `Judge` 阶段，FSM 不发出停止生成指令。只有 `break=1` 才使下游接到打断指令。

### 6.1 音频缓存边界

为满足 `Judge → Listen` 时 Prefill 获取有效输入的要求：

- 自 `Silence → Judge` 起，暂存本次候选语音对应的音频块。
- 若有效 `break=1`：将已暂存且尚未送入 Prefill 的音频作为初始输入随 `PREFILL` 一次性提交。
- 若从 `Judge → Silence`（始终未打断）：清空本次候选输入缓存。
- 在 `Listen`：后续新增块通过 `CHUNK_PREFILL` 交付，不重复提交已经 Prefill 的块。
- `Listen → Silence` 后结束本次输入轮次，清理该轮临时缓存。

音频缓存只是实现状态转移所需的数据结构，**不是新增 FSM 状态**。

## 7. 推理侧完整上下文与 Chat 策略

这部分属于 **Inference System**，不是 Input FSM 的第四个状态，也不增加
额外的推理分类器或 KV sidecar gate。

下游在收到 `PREFILL` 与每一个 `CHUNK_PREFILL` 时，必须保留全部已通过
VASD 的用户音频。到 `DECODE` 时，Chat 看到的输入必须是同一用户轮次的完整
已接受上下文，而不是最后一个 chunk 或 VASD 滑窗：

```text
PREFILL:       audio0
CHUNK_PREFILL: audio1
CHUNK_PREFILL: audio2
DECODE Chat:   [audio0, audio1, audio2]
```

- VASD 的 `vasd_window_ms` 仅限制分类器输入，不能裁剪 `DECODE` 的 Chat 音频。
- 当前 HTTP 调试服务在 `DECODE` 时把完整 `decode_audio` 序列化为一个用户 WAV
  传给普通 Chat 请求；这保证完整上下文，但不声称实现原生增量 KV Prefill。
- 用户没有主动交互意图时，由 Chat Prompt 要求模型精确输出 `listening`；这属于
  文本生成策略，不是 LISTENING/GENERATE 分类、阈值或新的 FSM 状态。

## 8. 建议的接口契约

以下为实现层接口示例；字段名可以适应现有仓库，但语义不可更改。

### 8.1 组件输出

```python
# Acoustic VAD
speech: bool

# Semantic VASD，仅在 Judge 使用
break_decision: bool

# Semantic VAED，仅在 Listen 使用
complete: bool
```

### 8.2 FSM 输入 / 输出

```python
@dataclass
class FSMInput:
    audio_chunk: bytes | object  # 实际类型遵循音频接入层
    speech: bool
    break_decision: bool | None = None
    complete: bool | None = None

@dataclass
class FSMOutput:
    state: str                    # Silence / Judge / Listen
    event: str                    # NO_OP / PREFILL / CHUNK_PREFILL / DECODE
    interrupt: bool               # 仅有效 break=1 的转移置 True
    prefill_audio: object | None  # 当前事件需要交付的音频
```

`break_decision` 只在 `Judge` 使用，`complete` 只在 `Listen` 使用。`interrupt=True` 必须与 `Judge → Listen` 的有效 `break=1` 同时发生。

### 8.3 单次事件处理伪代码

```python
def fsm_step(state, speech, break_decision=None, complete=None):
    if state == "Silence":
        if speech:
            return "Judge", "NO_OP", False
        return "Silence", "NO_OP", False

    if state == "Judge":
        assert break_decision is not None
        if break_decision:                          # break 优先
            return "Listen", "PREFILL", True
        if speech:
            return "Judge", "NO_OP", False
        return "Silence", "NO_OP", False

    if state == "Listen":
        assert complete is not None
        if complete:
            return "Silence", "DECODE", False
        if speech or semantic_endpoint_evaluated:
            return "Listen", "CHUNK_PREFILL", False
        return "Listen", "NO_OP", False

    raise ValueError(f"Invalid state: {state}")
```

伪代码仅规定状态转移；音频缓存、Omni 调用、事件交付和异步执行由具体代码封装。

## 9. 必须覆盖的功能测试

| 编号 | 场景 | 预期结果 |
|---|---|---|
| T01 | 初始为 `Silence`，AVAD 输出 0 | 保持 `Silence`，无 Prefill |
| T02 | `Silence` 收到首个 `speech=1` chunk | 转入 `Judge` 并立即对 t0 执行 VASD |
| T03 | `Judge` 中 `speech=1, break=0` | 保持 `Judge`，不打断、不 Prefill |
| T04 | 500ms chunk、8s 窗口到 t15 | VASD 输入 `[t0..t15]` |
| T05 | T04 后收到 t16 | VASD 输入滑为 `[t1..t16]`，完整候选缓存仍保留 `[t0..t16]` |
| T06 | `Judge` 中 `break=1` | 转入 `Listen`，只触发一次初始 `PREFILL` 与打断 |
| T07 | `Listen` 中 `speech=1, complete=0` | 保持 `Listen`，新增音频 Chunk 触发 `CHUNK_PREFILL` |
| T08 | `Listen` 中普通 `speech=1` | 不运行 VAED，保持 `Listen` 并触发 `CHUNK_PREFILL` |
| T09 | AVAD `speech_stopped=1`，完整累计音频 VAED 输出 `complete=0` | 保持 `Listen`，跨静音等待，不触发 Decode |
| T10 | VASD 输出无语义 `</b>` | 保持 Judge，不向推理模型 Prefill |
| T11 | 同一音频 Chunk 已经用于初始 `PREFILL` | 不得再次放入 `CHUNK_PREFILL` |
| T12 | `DECODE` 后交给 Chat | Chat 接收本轮所有已通过 VASD 的完整音频，而不是 VASD 滑窗或最后一块 |
| T13 | 用户没有主动交互意图 | Chat Prompt 允许模型精确输出 `listening`，不增加分类网关 |
| T14 | T09 后用户恢复 `speech=1` | 继续同一轮 `Listen` 和 `CHUNK_PREFILL`，不经过 Judge |
| T15 | 后续 `speech_stopped=1, complete=1` | 返回 `Silence`，触发 `DECODE` |
| T16 | `complete=0` 后持续静音达到配置超时 | 外部策略触发 `DECODE`，无新增 FSM 状态 |

## 10. 日志与可观测性

至少记录以下字段，便于对状态转移和误打断做回放：

```text
timestamp
previous_state
speech
break_decision
complete
next_state
fsm_event
interrupt
prefill_audio_chunk_count
```

日志应同时记录 VASD 滑窗时长/块数、完整 `decode_audio` 块数，以及 Chat 实际接收的块数。

## 11. 本期实现边界（不得擅自扩展）

**必须实现：**

1. 三个状态：`Silence` / `Judge` / `Listen`。
2. AVAD、二分类 VASD、VAED 三类判定输入；VASD 使用 `需要/不需要`，VAED 使用 `已/未` 的受限单 token 输出。
3. 六个 Special Token：`<s>`、`</s>`、`<b>`、`</b>`、`<c>`、`</c>`。
4. 第 5 节规定的全部状态转移，以及相应 Prefill / Chunk Prefill / Decode 事件。
5. 未确认有语义 `<b>` 之前不打断、不提交 Prefill。
6. 需要时向外部推理系统发送打断和音频 Prefill 数据。
7. 单元测试、日志，以及完整已接受音频交给下游 Chat 的接口边界。

**本期不实现/不改变：**

- 不增加 Reject 状态；无语义直接映射到 `</b>`。
- 不为语义未完成的静音等待增加第四个 FSM 状态；等待和超时由 Listen 内部输入策略管理。
- 不新增独立的打断确认、说话人验证、重试或音频分流状态。
- 不改变 `Judge` 的 Break 优先规则；`Listen` 只在有效 `complete=1` 或外部静音超时时结束。
- 不规定具体 Omni 模型结构、训练方案、推理引擎或 GPU 调度细节。
- 不在 FSM 内实现 KV Cache、Talker 播放或模型 Decode 内核；这些属于推理后端。

## 12. 交付及验收要求

交付内容应至少包括：

- 可独立调用的三状态 FSM 控制器。
- Acoustic VAD、Omni VASD、Omni VAED 的接口适配层。
- VASD 滑窗二分类；无语义输入不能触发打断或 Prefill。
- DECODE 时完整已接受音频上下文交给 Chat；Chat Prompt 中的 `listening` 策略。
- 对外输出 `PREFILL`、`CHUNK_PREFILL`、`DECODE` 事件和相应音频载荷。
- 状态转移日志与第 9 节测试用例。
- 简洁的接入说明：如何把事件连接到当前的模型推理调度器。

**验收标准：** 依据第 5 节状态转移表逐项测试，状态、控制事件、滑窗边界和完整上下文交付全部符合预期。原生增量 request/KV 复用是独立的后续后端能力，不是本期 Chat 行为的前置条件。
