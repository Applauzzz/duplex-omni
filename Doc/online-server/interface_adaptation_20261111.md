# 双工服务接口适配分析

日期：2026-11-11。

本文为临时交付对接文档，不改变主干项目计划或服务实现。
所有映射均为适配设计建议，不代表已经实现或通过联调。

## 1. 范围与依据

本次对接仅包含纯语音 AVAD + VASD + VAED + MiMo + TTS，
不包含视频、OpenAI Agents SDK、Mac tools 或后台 reasoning 功能。

对照来源：

- [调用方标准接口文档](双工服务接口文档.md)。
- [当前 WebSocket 协议](websocket.md)。
- [当前调度逻辑](scheduling.md)。
- 应用实现：`workspace/experiments/20261025_mimo_tts_integration/svad_debug_server.py`。
- 判停实现：同目录 `semantic_vad.py`。
- 浏览器播放参考：同目录 `svad_debug.html`。

当前已记录的内部接口地址为 `ws://28.29.217.68:8080/ws`。
本文未重新检查在线状态；地址为节点部署信息，不是长期服务发现约定。

## 2. 总体结论

双方的交互模型基本一致：持续送音频和静音、服务端判停、
流式返回文字和音频、播放期间允许用户插话。

但当前服务不是标准接口的直接实现：

| 层次 | 调用方标准 | 当前服务 |
|---|---|---|
| 传输 | svrkit newrpc 双向流 | WebSocket `/ws` |
| 编码 | proto2 二进制 | JSON 文本帧 |
| 音频载荷 | 原始 bytes | base64 PCM |
| 上行粒度 | 20ms 实时持续推送 | 目标200ms批次，处理期间可合并 |
| 应用背压 | 调用方不等待每帧处理回执 | 参考客户端最多一个音频批次在途 |
| 自动打断状态 | 未定义客户端播放反馈事件 | 依赖 `playback.state` |
| 回复终止 | 每轮必须 `RESPONSE_AUDIO_DONE` | 正常、拒识、取消、错误分散在不同事件 |

建议新增独立适配服务，保留现有模型服务和内部协议。
适配层必须管理状态与时序，不能只替换事件名称。

```mermaid
flowchart LR
    C["调用方：svrkit / protobuf"] --> A["适配服务：会话状态、音频聚合、事件映射"]
    A --> W["内部 WebSocket /ws"]
    W --> M["AVAD / VASD / VAED / MiMo / TTS"]
    M --> W
    W --> A
    A --> C
```

## 3. 建会话与身份

### 建议流程

1. 建立一条 svrkit 流，固定该流的 uin。
2. 首包 `SESSION_CREATE`，验证并保存 `trace_id`、用户身份和音频配置。
3. 建立独立内部 WS，发送 `configure`，等待 `configured`。
4. 验证后端就绪并满足配置，之后才返回 `SESSION_CREATED`。
5. 会话结束时取消内部工作、关闭 WS，再尽力下发 `SESSION_CLOSED`。

`configured` 目前证明配置和 adapter 初始化成功，不等于 MiMo/TTS
后端握手已经成功；适配层需明确就绪检查标准、失败分类和超时。
调用方文档约定后端握手上限8秒、调用方等待10秒，实际可达性需验收。

### 标识映射

| 标识 | 适配要求 |
|---|---|
| `trace_id` | 原样保存、回带并串联日志，不替换成内部 session_id |
| `useruin` | 按标准解析；不能仅保存在适配日志却声称已贯通推理日志 |
| 内部 `session_id` | 当前服务每个WS生成，作为内部连接关联标识 |
| `question_id` / `response_id` | 由服务侧明确生成，与内部turn_id关联，保证跨会话不冲突 |
| `req_id` | 用于上行日志；不擅自改成需要下行回带的字段 |
| `chunk_index` | 保留上行编号用于丢帧统计；下行每个response从0递增 |
| `dialog_id` | 不能直接映射内部session_id来宣称支持续聊 |

当前历史仅保存在连接内，断连不恢复。跨连接续聊需要单独的历史存储、
身份校验、保留策略及恢复接口；第一版可明确不支持，需调用方同意。

首包前音频丢弃、重复CREATE忽略、未知上行类型忽略等标准行为，
由适配层实现；当前WS会拒绝配置前音频及未知事件，不能直接透传。
会话配置在适配层冻结，不暴露调试端的中途prompt/config更新能力。

## 4. 上行音频与调度

共同支持的首版音频：

- 单声道、16kHz、PCM signed 16-bit little-endian。
- 调用方每20ms发送640字节，不携带WAV头，持续发送静音。
- 适配层将原始bytes编码为base64后发送内部 `audio`。

标准上行格式名 `pcm` 对应其默认s16le输入；当前内部格式名为 `pcm16`。
不要把下行 `pcm` 误认为int16：标准下行该名称表示float32。
Opus等格式未在本适配中承诺支持，不得接受协商后按PCM错误解析。

### 收发分离

适配层需要独立任务：

| 任务 | 责任 |
|---|---|
| svrkit上行接收 | 按实时节拍持续收20ms帧，验证编号和格式，不等待VAED |
| 内部音频提交 | 聚合目标200ms音频，等待上一批transition/semantic_error后提交 |
| 内部WS接收 | 持续接收文字、音频、取消及错误，不被上行推理阻塞 |
| svrkit下行发送 | 有界队列发送标准事件，不阻塞接收/判停控制 |

不能将每个20ms帧直接提交到当前Listen判别循环，否则可能改变VAED
调用频率、块数预算和负载。当前 `audio_chunk_ms` 是参考客户端批次目标，
不是服务端自动聚合器；适配层必须自行落实聚合。

处理期间可以在内部合并后续音频，但必须限制积压时长、批次大小、
发送缓冲与整轮时长。超过预算的结束/错误策略需约定，不能无限缓存，
也不能静默丢弃语音后声称实时无损。

20ms传输与32ms AVAD内部帧不冲突：内部检测器可以累计不足一帧的采样。
不过保持传输畅通不代表后端推理能实时跟上，需要测量积压和判停延迟。

### 上行事件映射

| 标准事件 | 内部动作 | 状态 |
|---|---|---|
| `SESSION_CREATE` | 建WS、configure、就绪检查 | 需适配 |
| `INPUT_AUDIO_APPEND` | 聚合后发送audio | 需适配 |
| `INPUT_AUDIO_COMMIT` | 强制判停并回复 | 当前普通WS无对应入口，需实现或协商 |
| `RESPONSE_CANCEL` | response.cancel | 可映射；标准允许忽略，但必须明确选择 |
| `SESSION_CLOSE` | 清理内部任务并关闭WS | 需适配 |

不得用一个假的静音包冒充COMMIT。标准COMMIT与服务端自动判停的回执
是否都需要 `INPUT_AUDIO_COMMITTED`，应由协议维护方确认。

## 5. Playback与自动打断

### 当前实现

网页收到 `tts.audio`，按采样率将PCM排入AudioContext，随后上报：

```json
{"type":"playback.state","active":true}
```

这是“已安排播放/仍持有待播放音频”的状态，不是硬件首采样点确认。
首块通常安排在浏览器当前时间之后约30ms。

收到 `tts.done` 时只标记音频流结束。排队音频全部播放完，或主动停止
并清空队列之后，才上报：

```json
{"type":"playback.state","active":false}
```

服务端默认false。VASD语义接受且该状态为true才自动取消旧回复。
新话轮完成时，如果旧Chat尚未结束或playback为true，先进入pending；
两个条件均解除后再生成待处理回复。

因此存在三个独立状态：

| 状态 | 含义 |
|---|---|
| chat.done | 文字生成结束 |
| tts.done | 音频发送结束 |
| playback=false | 播放队列结束或主动清空 |

当前状态是连接级布尔值，没有turn_id、播放位置和逐采样ACK。
模型生成中但尚未排入音频时，也不是playback=true。
当前网页没有明确300ms播放提前量上限。

### 标准接口缺口

标准上行未定义playback反馈。如果适配层一直不上报true，
当前自动打断和pending语义不能直接满足标准要求。

需要选择并验收以下方案之一：

1. 调用方允许增加可选播放状态反馈，由适配层转为内部playback消息。
2. 不改变标准，适配层按已发送PCM时长、发送节奏与已知播放缓冲，
   维护预计播放状态并上报；必须声明这是估计，不是实际播放ACK。
3. 对接版本另行定义服务端response-active打断策略，明确涵盖生成期、
   音频输出期和尾部播放期。这会改变现有策略，需要独立实现与验收。

不能在tts.done到达时立即假定客户端已播完。
如果采用估计，缓冲暂停、网络延迟及客户端暂停都会造成偏差，
需明确容忍范围和超时；不能把无反馈情况下的估计宣称为精确同步。

## 6. 下行事件映射

| 当前事件 | 标准事件 | 补充行为 |
|---|---|---|
| configured | SESSION_CREATED | 先完成就绪检查，回带trace_id |
| transition | 可选内部观测 | 不逐批透传为标准回复，供适配状态机使用 |
| chat.started | 建立回复关联状态 | 不是用户开口，不冒充ASR_STARTED |
| chat.delta | RESPONSE_TEXT_DELTA | 增量透传，所有回复字段带ID |
| chat.done | RESPONSE_TEXT_DONE | 完整text校对；处理listening例外 |
| 首个tts.audio前 | RESPONSE_AUDIO_STARTED | 补事件；tts_type取值需约定 |
| tts.audio | RESPONSE_AUDIO_DELTA | 解base64成bytes、校验格式、补chunk_index |
| tts.done | RESPONSE_AUDIO_DONE | 正常收口，不代表实际播放结束 |
| chat.cancelled / tts.cancelled | RESPONSE_AUDIO_DONE + 可选CANCELED | interrupted=true，终止一次 |
| chat.error / tts.error / error | ERROR及必要终止事件 | 区分轮次失败与会话致命错误 |
| WS关闭 | SESSION_CLOSED及关流 | 正常/异常原因分类，尽力发送 |

下行音频格式以实际 `sample_rate_hz` 为准。当前TTS没有输出采样率协商入口；
只有实际返回与协商一致时才能无转码交付，不能强行把字段写成24kHz。
音色、speed、loudness与当前reg_id、倍率、target_rms不是同一套参数，
需要模板映射和范围校验，不能直接复制数值。

### 每轮收口

适配层维护每个response的生命周期：

```text
建立 → 文本/音频增量 → 正常结束 / 被打断 / 失败
```

每个已经建立的回复最多一个 `RESPONSE_AUDIO_DONE`，终止后丢弃旧轮增量。
正常、打断、错误、无音频及文本-only输出的收口规则都需覆盖。
可选 `RESPONSE_DONE` 仅做记录，不能代替AUDIO_DONE。

特殊情况：

- `listening` 是内部静默控制，不应作为用户回复或送入TTS。
  当前内部仍发送chat.delta/chat.done；是否建立外部response、
  是否发送空AUDIO_DONE及使用何种状态码，需要调用方确认。
- TTS关闭或失败可能没有tts.done，必须补足外部终止路径。
- 标准要求TEXT_DONE与增量拼接一致；如果需要隐藏控制输出，
  需采用明确的文本缓冲/过滤策略，不能发出后再撤回。
- 正常AUDIO_DONE已经发送但客户端仍有尾部音频时发生插话，
  不能再重复发AUDIO_DONE；需约定补发CANCELED等尾部清理方式。
- 标准允许两轮事件交错，不能只维护一个“最近response”的归属。

## 7. 不能仅靠事件转换补出的能力

| 能力 | 当前情况 | 首版建议 |
|---|---|---|
| ASR转写 | MiMo直接理解音频，无ASR文本流 | 协商省略转写，不伪造识别文本 |
| ASR_STARTED | 可观察AVAD/VASD，但不是现成ASR事件 | 明确采用声学开口还是语义放通时机及ID |
| 跨连接续聊 | 连接内历史，断连清理 | 明确不支持，或另建持久化能力 |
| 外部chat_req | 当前不调用文档中的Agent服务 | 纯语音模式声明忽略，不拼成任意system prompt |
| exit_intent | 无标准挂断意图状态码 | 不用关键词猜测，协商暂不支持 |
| 开场白 | 当前无标准模板开场白链路 | 可选能力，不擅自自动启动对话 |
| Opus/float32输出 | 未在本适配中验证 | 首版只支持共同PCM16格式 |
| 强制COMMIT | 普通WS未暴露 | 明确能力缺口 |

若改为调用对方Agent，必须实现chat_req会话模板保存和每轮拷贝，
只覆盖标准轮次级字段、保留会话级字段、生成唯一session_id；
这是独立后端集成，不是浏览器OpenAI Agents SDK配置转换。

## 8. 错误、超时与资源

- 参数/协商非法对应2001；后端建连/就绪失败对应2002。
- 会话中后端连接异常按标准3000/3001/3002分类，不能全部只报字符串。
- 轮次Chat/TTS失败和整个WS断开不是同一个故障。
  若用vendor错误0表达局部失败，必须约定是否继续会话及该轮如何收口。
- svrkit KeepAlive、约60秒上行无数据结束、5秒下行发送策略由适配层实现。
  WS heartbeat=20不是这些规则的等价实现。
- 当前内部send使用锁并await发送，分类在上行事件循环中await；
  不是严格的无阻塞主协程。适配层收发分离不能消除内部控制消息等待。
- 下行队列必须有界；音频帧或终止事件发送失败的处理需明确，
  不能丢失关键收口事件后继续宣称该轮正常结束。
- 日志应包括trace_id、内部session_id、response映射、结束原因、
  上下行字节/帧数、丢帧和积压；身份与敏感载荷按上线规范处理。

## 9. 联调前必须确认

1. 谁实现svrkit适配服务，以及可用的svrkit编译/运行环境。
2. 提供真实 `duplex_dialogue.proto` 和必要依赖，确认字段号、枚举、
   默认值和proto2 optional存在性；本文只有文档级语义核对。
3. 第一版是否接受无ASR文本、无跨连接续聊、无外部Agent、PCM16限定。
4. playback采用真实反馈、服务端估计还是新的response-active策略。
5. listening、文本-only、TTS失败和尾部插话的收口语义。
6. COMMIT、AUDIO_COMMITTED和exit_intent的能力要求。
7. 音频协商、模板音色、速度/响度参数的映射与不支持项处理。
8. 上下行缓冲预算、超限错误及并发/延迟目标。

## 10. 最小验收矩阵

| 场景 | 验收要点 |
|---|---|
| 建会话 | trace_id原样回带；未就绪不接音频；失败分类和超时正确 |
| 20ms真实推流 | 持续收发、静音保留、内部聚合、积压有界 |
| 正常问答 | TEXT增量与DONE一致；PCM格式一致；AUDIO_DONE一次 |
| 有语义但不对助手说话 | listening不朗读；外部生命周期不悬挂 |
| 播放中插话 | 旧轮及时清队列；interrupted标识正确；新旧ID不串 |
| 生成期插话 | 按选定策略取消或等待，不依赖不存在的播放反馈 |
| 音频发完后的尾部插话 | 不重复收口；仍能清理客户端残余音频 |
| TTS/Chat失败 | 错误与终止顺序明确，局部失败不冒充连接故障 |
| 停止/断流 | 清理内部任务和缓冲；SESSION_CLOSED尽力下发 |
| 未知事件/重复CREATE | 按标准忽略，不导致内部WS协议报错 |
| 并发/慢收端 | 不无限堆积，不阻塞接收，关键终止事件有失败处理 |

当前仅完成文档与源码静态对照，没有实现适配服务、编译protobuf、
进行svrkit联调、模型回放或新增性能验收。
