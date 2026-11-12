# WebSocket 接入协议

## 1. 连接与数据格式

接口 `/ws`，生产使用 `wss://<voice-domain>/ws`。
当前实现只处理JSON文本帧；不是直接binary PCM，也不是OpenAI Realtime事件集。
配置先于audio，连接关闭不保留历史。WebSocket有20秒heartbeat，
服务max_msg_size为2MiB；这不是应用话轮/并发配额。

交付约定音频为单声道、16kHz、PCM16 little-endian，base64编码。
200ms等于3200样本/6400字节原始PCM；base64后约8536字符。
不要在`audio`里塞WAV头或压缩音频。现有服务也支持pcm_f32le/重采样，
但本次接入先固定PCM16/16kHz，减少格式分支。同一话轮采样率不得变化。

## 2. 客户端消息

首次配置使用服务默认值：

```json
{"type":"configure"}
```

等待`configured`，核对服务实际参数后再发送音频：

```json
{
  "type": "audio",
  "audio": "<base64-of-mono-pcm16-little-endian>",
  "format": "pcm16",
  "sample_rate_hz": 16000
}
```

持续发送包括静音的采集数据，不能客户端VAD先把静音全部丢掉；
服务端靠静音样本关闭AVAD，靠后续批次推进兜底。不要传`video_frame`。
现有浏览器发的`sequence`是客户端计数，服务端响应sequence自行递增。

播放状态：

```json
{"type":"playback.state","active":true}
```

```json
{"type":"playback.state","active":false}
```

开始实际播放后报true；最后一块播放完成/主动停止并清空队列后报false。
`tts.done`到达时不一定播放完，不能立刻报false。

取消和重置：

```json
{"type":"response.cancel"}
```

```json
{"type":"reset"}
```

response.cancel取消回复，不等于重置输入FSM/历史；生产入口可映射为
明确的用户取消操作。reset清空本连接历史/FSM/pending并取消当前响应，
客户端同步清空播放和本地话轮状态，等待`reset`回执。

当前调试服务还接受`prompts.update`、Agent等扩展事件；
它们不属于本次生产消息集，应在入口拒绝。configure仅允许上线批准字段，
不得让客户端任意替换system prompt或扩大资源预算。

## 3. 服务端消息

| type | 关键字段 | 客户端处理 |
|---|---|---|
| `configured` | session_id、config、prompts | 确认配置再上行 |
| `transition` | sequence、avad、transition、commands | 本批处理完成，释放上行背压 |
| `semantic_error` | sequence、request_kind、raw_output等 | 本批分类无效，记录并释放背压；不当成有效完成 |
| `chat.pending` | turn_id、reason | 本轮暂候旧任务/播放结束 |
| `chat.started` | turn_id、audio_chunk_count | 建立回复对象 |
| `chat.delta` | turn_id、delta | 增量拼接显示；不按每token另起TTS |
| `chat.done` | turn_id、text | 文字完成，识别listening |
| `tts.text` | turn_id、text_idx、text、final、request_id | 外部TTS文本提交回执 |
| `tts.audio` | turn_id、pcm、samples、sample_rate_hz、request_id | 解码PCM按轮次顺序播放 |
| `tts.done` | turn_id、text_chunks、samples | PCM输出结束，等待本地排队播放完成 |
| `chat.cancelled` / `tts.cancelled` | turn_id、reason、retained | 停旧轮播放、清队列，忽略该旧轮后续数据 |
| `tts.error` | turn_id、message | 语音失败，保留已有文字 |
| `chat.error` | turn_id、message | 停该轮播放，反馈失败，不伪造完成 |
| `reset` | session_id | 清本地记录与计数 |
| `error` | message | 会话错误；准备关闭/重连，不盲目重发 |

`commands`是adapter/FSM内部命令名称的观测，不要求客户端再发送
`input_audio_buffer.commit`或OpenAI response.create，自动提交由服务端负责。
`transition.transition`含previous_state/next_state、fsm_event、
decode_reason、completion_accepted等，详见[调度与日志](scheduling.md)。

PCM输出例子：

```json
{
  "type": "tts.audio",
  "turn_id": 85,
  "pcm": "<base64-pcm16>",
  "samples": 2400,
  "sample_rate_hz": 24000,
  "request_id": "svad-<task-id>"
}
```

输出采样率以字段为准，不固定沿用输入16kHz。base64解码后
字节数须等于samples*2；按little-endian有符号16位转播放器格式。
客户端以turn_id隔离旧/新轮，以request_id关联外部TTS；不能把已取消
旧轮的音频插入新轮播放。客户端播放源队列必须有容量和断连清理策略。

## 4. 背压与时序

沿用当前浏览器策略：最多一个audio批次在途，收到transition或semantic_error
后再发下一批。处理期间继续采集并合并到下一批，不能不断堆积每200ms请求。
目标批次200ms不等于服务器独立定时器；当语义请求超过200ms，合并批次变长。
生产接入需限制采集积压、WS发送缓冲和整轮时长，超限明确丢弃/结束会话，
不能无限放大batch直到超过2MiB或内存预算。

上行背压不等待chat.done/tts.done；输入接收与旧回复输出可并发。
服务端每个连接串行读取上行事件，所以当分类await时，playback.state/
response.cancel等消息也可能等待；这是应用调度边界，不承诺即时控制延迟。

## 5. 资源与失败边界

- 普通Chat当前新话轮WAV最多3MiB，模型上下文32768 token。
  30轮不是任意长音频都能容纳，需工程定义时长预算。
- VASD/VAED只分类窗口，但已接纳整轮仍保留；1024块不代表固定秒数。
- TTS单块最多500字符、整次累计4096字符、轮询音频预算180秒，
  submit/poll各自有HTTP超时。当前正文通常受512输出token另行约束。
- 外部TTS失败可能已有部分语音；保留文本不等于整句已完整朗读。
- 断连取消本地工作，不持久化历史；重连后configure建立新状态。
- Chat Prompt依赖模型精确输出`listening`控制静默，不能保证任何不规范
  文本都被程序自动滤除；上线要验收拒识与不朗读内部控制内容。

## 6. 最小上线验收

1. 入口拒绝video_frame、Agent/工具路由和越权配置，确认认证失败不能建会话。
2. configured下发chunk/8000、audio200、AVAD256、fallback128、history30。
3. 有效语音自动完成一轮，收到正文与PCM；背景/噪声不造成错误播报。
4. 观察VAED“已”但AVAD仍开时不Decode；关闭且合格时semantic_complete。
5. 不合格且停声后可兜底、用户恢复说话可取消兜底，句内停顿质量达标。
6. 长回复首个tts.audio早于chat.done；全部PCM连续播放，音色/采样率正确。
7. 播放中讲话打断，旧音频清空，新回复不串轮；播放状态上下行正确。
8. reset与断连释放会话，TTS失败可保留文字，MiMo失败不伪造结果。
9. 压测分类/Chat竞争与外部TTS容量；记录并发数、延迟、显存及积压上限。

这些步骤是交接验收清单，不是本文编写时已执行的新验收结果。
