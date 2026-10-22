# 架构与关键代码位置

## 1. 系统分层

```
浏览器 (Chrome, 麦克风 + AudioWorklet 播放)
   │  WebSocket: /v1/realtime?duplex=1&model=...
   ▼
server.py (UI 静态托管 + 同源 WS 代理)          端口 8080
   │  ws://127.0.0.1:8092
   ▼
vllm serve --omni --stage-id 0 (APIServer)     端口 8092
   │  内部 omni-master 127.0.0.1:26100
   ├── stage 0  thinker   (GPU x1)
   ├── stage 1  talker    (GPU x1, --headless)
   └── stage 2  code2wav  (GPU x1, --headless)
```

- UI 只是一层**透明转发**代理，不解析协议内容（`server.py` 的 `_pump_client_to_backend` /
  `_pump_backend_to_client`），方便排查时加日志。
- 三阶段由 stage 0 的 APIServer 通过 omni-master 协调，另外两个是 headless worker。
- 对外协议是 OpenAI Realtime 风格（`vllm_omni/protocol/realtime/events.py` 负责把内部事件渲染成
  线上 JSON）。**注意：线上字段名和引擎内部 payload 字段名不同**，排查时容易踩坑，见第 5 节。

## 2. duplex 引擎的核心模块

| 模块 | 路径 | 职责 |
|---|---|---|
| 会话管理 | `vllm_omni/engine/duplex/session/manager.py` | 会话生命周期、准入、`runtime_config` 持有 |
| 会话状态 | `vllm_omni/engine/duplex/session/engine_session.py` | response/item/history/playback 的核心状态机 |
| 事件循环 | `vllm_omni/engine/duplex/session/runner.py` | 处理客户端事件、编排一轮对话 |
| 模型输出 | `vllm_omni/engine/duplex/session/model_channel.py` | 把 stage 输出转成 Realtime 事件 |
| 客户端指令 | `vllm_omni/engine/duplex/session/control.py` | `session.update`、`response.create` 等 |
| VAD | `vllm_omni/engine/duplex/turn_detection.py` | server_vad 参数解析与默认值 |
| 协议渲染 | `vllm_omni/protocol/realtime/events.py` | `to_realtime()` 序列化 |

## 3. Qwen3-Omni duplex 插件

`vllm_omni/model_executor/models/qwen3_omni/duplex/plugin.py`

Qwen3-Omni 是 **turn 模型**：每一轮提交都是一次全新的请求，没有原生 streaming KV、也没有模型驱动的
轮次决策。插件的关键能力声明见 `capabilities()`，其中与行为直接相关的几个：

- `supports_barge_in = True`
- `supports_core_resumable_request = False` → 每轮把完整历史重新编码进 prompt
- `supports_independent_io_streams = True` → 输入上传和音频播放可以同时进行
- `supports_realtime_endpoint = True`
- `adapter_patterns = ["turn_commit"]`

**最重要的方法是 `prepare_prompt_config()` 和 `format_history()`**（`plugin.py` 约 211~311 行）：

- `prepare_prompt_config()`：从会话历史构建 `qwen_messages`。它决定保留哪些轮次（16 条消息窗口、
  最多 4 段音频）、把音频 payload 和消息条目关联起来、丢弃音频已被淘汰的轮次。
- `format_history()`：把消息列表整理成给模型看的形态，合并连续的用户输入、渲染 assistant 回复。
  这两个方法是调试上下文类 bug 时最先要看的地方。

`plan_append()`（约 361 行）负责最终拼 prompt：加上 instructions、处理图像、调用
`processor.apply_chat_template()`。

## 4. 一轮对话的数据流

```
麦克风 → input_audio_buffer.append（持续上传）
       ↓ VAD 判定语音结束（或用户手动 commit）
input_audio_buffer.committed → 会话历史追加一条 user 消息（带音频）
       ↓
response.created → reserve_history_item（预留位置）
       ↓
stage 0 thinker 生成文字 → response.output_audio_transcript.delta
       ↓ 异步
stage 1 talker 生成 codec → stage 2 code2wav 生成波形
       ↓
response.output_audio.delta（音频帧，约 12.5 帧/秒）
       ↓ 播放结束
response.done → end_response() 决定这段文字是否记入历史
       ↓
客户端 playback.ack（played_ms / committed_ms）→ 最终提交/截断
```

**关键点**：Qwen3-Omni 的文字流和音频流是**独立的**，没有对齐信息
（`plugin.py` 里 `audio_text_mark: False`、`text_requires_complete_audio=True`）。这带来两个后果，
也是大部分行为问题的根源：

1. 无法知道"用户听到的 12.3 秒音频对应到文字的第几个字"；
2. 历史提交只能采取"要么全记、要么不记"的策略（详见 `04_known_issues.md` 第 2 节）。

## 5. 排查时最容易踩的坑：两套字段名

引擎内部构造事件时用的是一套字段名（`model_channel.py`），经过 `to_realtime()` 渲染到线上后是
另一套（`protocol/realtime/events.py`）：

| 内部 / 直觉上的名字 | 线上实际字段名 |
|---|---|
| `audio` | `delta`（`AudioDelta`） |
| `text`（音频转写） | `delta`（`TranscriptDelta`） |
| `epoch` | 大多数事件**不透传** `epoch`，只有 `overlap.decision` 等少数事件带 |
| `response_id` | `response_id`（这个一致） |

曾经按内部字段名去解析线上帧，结果音频长度全是 0、`epoch` 全是 `None`，日志完全不可信。
排查协议相关问题时，请以 `protocol/realtime/events.py` 为准。

## 6. 前端

`vllm-omni/examples/online_serving/realtime_web/`

- `server.py`：静态托管 + WS 代理，支持 `--profile`（`qwen3-turn` / `minicpm-native` / `aura-ptt`）
  和 `--adapter`（`stt` / `vad` / `gate`）。
- `app/static/profiles/qwen3_turn.js`：Qwen 的 profile，决定 `session.update` 的内容、
  消息格式、ack 行为。
- 本轮新增的 **gate 模式**（`--gate`）：`turn_detection: null`，"Open gate / Close gate" 手动提交，
  "Interrupt" 手动打断。绕开 VAD，方便脚本化复现打断场景。

## 7. 关键常量与限制

| 项 | 值 | 位置 / 说明 |
|---|---|---|
| 音频历史窗口 | 4 段 | `plugin.py` 的 `history_limit` |
| 消息窗口 | 16 条（按整轮向外取整） | `plugin.py` |
| `max_sessions` | 1（demo 配置） | `demo_vad.json`，同一时间只能一个人用 |
| 输入采样率 | VAD 模式 24k，gate/stt 模式 16k | `qwen3_turn.js` |
| 输出采样率 | 24 kHz pcm16 | stage 2 |
| 默认 instructions | 中文全双工语音助手预设 | `qwen3_turn.js` 的 `presets.assistant` |
