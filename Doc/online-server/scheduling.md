# 完整调度图

本图描述当前纯语音普通 provider、`vaed_mode=chunk` 的实际应用调度。
不包含video、tools或Agent。Mermaid源码可直接渲染；文字段落说明关键边界。

## 1. 服务拓扑与资源

```mermaid
flowchart LR
    C["语音客户端<br/>采集 / 播放 / 背压"]
    G["生产入口<br/>WSS / 鉴权 / 消息允许列表"]
    A["普通 aiohttp 应用<br/>/ws<br/>每连接 adapter + history"]
    V["Silero AVAD<br/>共享 backend / 独立声学状态"]
    M["MiMo vLLM :8090<br/>共享四张 H20 / TP4 + EP"]
    T["外部 CosyVoice :8100<br/>submit / poll"]
    C <-->|"JSON + base64 PCM"| G
    G <-->|"固定连接"| A
    A --> V
    A -->|"VASD / VAED<br/>独立请求，max_tokens=1"| M
    A <-->|"完整话轮 Chat<br/>正文 SSE delta"| M
    A -->|"同一task_id增量文本"| T
    T -->|"PCM分块"| A
```

VASD、VAED和Chat都竞争同一个MiMo引擎，应用没有专用分类GPU队列、
请求优先级隔离或已验收固定并发数。TTS GPU由外部owner管理。
TP/EP是模型内部并行，不能解释为四个独立用户服务副本。

## 2. 输入 FSM 与语义端点

```mermaid
flowchart TD
    I["收到非空audio批次"]
    V["AVAD先处理<br/>16kHz / 512样本帧 / 32ms"]
    W{"已有未完成等待？"}
    R{"本批speech_active？"}
    X["取消兜底计时"]
    TO{"仍关闭且墙钟已超128ms？"}
    F["force_decode<br/>不附加当前检查批次<br/>不再运行本批VAED"]
    S{"当前FSM状态"}
    SI["Silence<br/>保存有限前缀，等待声学激活"]
    J["Judge<br/>候选最近8秒 -> VASD"]
    Q{"有 + 概率/margin/确认达标？"}
    N{"AVAD仍激活？"}
    K["保留Judge候选，等下一批"]
    L["进入Listen<br/>候选转完整话轮缓存<br/>PREFILL事件"]
    B{"客户端报告正在播放？"}
    BI["语义打断<br/>取消旧Chat/TTS/播放"]
    E["Listen每批音频 -> VAED<br/>只分类最近8秒"]
    H{"已 + 置信度/确认达标<br/>且本批AVAD关闭？"}
    D["semantic_complete -> DECODE"]
    U{"AVAD已关闭？"}
    WT["首次启动兜底计时<br/>后续未完成不重置"]
    CT["保持Listen / 累积完整话轮"]
    OUT["FSM回Silence<br/>完整已缓存音频进入回复调度"]
    I --> V --> W
    W -->|否| S
    W -->|是| R
    R -->|是| X --> S
    R -->|否| TO
    TO -->|是| F --> OUT
    TO -->|否| S
    S -->|Silence| SI
    SI -->|激活| J
    SI -->|未激活| I
    S -->|Judge| J
    J --> Q
    Q -->|否| N
    N -->|是| K --> I
    N -->|否| SI
    Q -->|是| L --> B
    B -->|是| BI --> I
    B -->|否| I
    S -->|Listen| E --> H
    H -->|是| D --> OUT
    H -->|否| U
    U -->|是| WT --> CT
    U -->|否| CT
    CT --> I
```

- 每批先同步执行AVAD，再await语义判定；AVAD与VAED不是并行竞争。
- AVAD把收到样本按32ms处理，不足一帧留给下一批，声学静音按样本累计。
  `speech_active=false`是滞回/连续静音后的关闭，不是单帧低概率。
- VASD只有Judge执行，首个激活批次可同次进入Judge并分类；进入Listen后不再跑VASD。
- chunk轮询是每个收到的非空Listen批次，包括静音；不是独立200ms定时器。
  分类窗口按完整批次滑动，单批超窗口仍保留该整批，不保证精确裁剪8000ms。
- 完成门槛：`已`、probability>=0.8、margin>=2、连续次数>=1、AVAD关闭。
  说话时的“已”可累积确认，但不能Decode；关闭批次会重新判VAED，
  不是取旧“已”缓存直接Decode。未合格会清零确认。
- `128ms`从AVAD关闭且某次VAED未接受后的时刻开始按墙钟计。
  后续批次先检查超时，超时则直接Decode，不进行这一批VAED。
  用户恢复语音取消等待。`0`关闭该兜底。
- 256ms声学门控与128ms兜底不是固定总延迟，实际受批次相位、语义请求、
  GPU排队、是否首次合格等影响。兜底没有独立timer，缺少后续音频就不检查。
- 分类只用窗口，Chat用整轮已缓存音频。FSM `PREFILL/CHUNK_PREFILL`
  是应用事件/缓存契约；当前普通服务到DECODE才发完整WAV的Chat请求，
  不代表此前已把每块送入同一engine session增量KV prefill。

## 3. 回复、流式 TTS 与播放时序

```mermaid
sequenceDiagram
    participant C as 客户端
    participant A as WS应用
    participant M as MiMo
    participant Q as 有界文本队列
    participant T as 外部TTS
    C->>A: audio持续提交（等待transition后下一批）
    A->>M: VASD/VAED窗口，one-token
    M-->>A: 标签 + 两候选logprobs
    A-->>C: transition，DECODE
    Note over A: 若旧响应/播放未结束，暂存pending_decode
    A-->>C: chat.started(turn_id)
    A->>M: 历史 + 当前完整WAV，stream=true
    par 正文decode与文本提交
        loop SSE正文delta
            M-->>A: delta.content
            A-->>C: chat.delta
            A->>Q: 标点/长度分块（8至48字符）
            Q->>T: submit(task_id,text_idx,text)
            T-->>A: submit成功
            A-->>C: tts.text
        end
        M-->>A: finish_reason + DONE
        A->>Q: flush残余 + 结束标记
        Q->>T: is_text_complete=true
        A-->>C: chat.done，写会话历史
    and 并行PCM轮询
        loop TTS未结束
            A->>T: poll(task_id)
            T-->>A: JSON元数据 + NUL + PCM16
            A-->>C: tts.audio(turn_id,pcm,sample_rate)
            C->>C: 按顺序排队播放
            C-->>A: playback.state(active=true)
        end
        A-->>C: tts.done
        C->>C: 等本地播放队列真正结束
        C-->>A: playback.state(active=false)
    end
    Note over C,A: 上行收音持续，下一轮分类可与旧回复输出重叠
```

正文、TTS submit、TTS poll是独立异步任务；文本队列maxsize=8形成背压，
队列满时正文转发会等待。一个回复共用一个TTS task_id，text_idx递增，
最后发送文本结束标记。不是等待完整decode后才统一送TTS。
短回复可能早于首PCM结束decode；长回复应验收首PCM与decode的重叠。

`chat.done`表示文字完成并写入历史；`tts.done`表示服务端PCM流完成；
两者都不是用户已听完。客户端需要在最后PCM播放完后报告false。
`listening`由Chat Prompt控制，精确该值不朗读；不算额外FSM分类阶段。
客户端必须保留此控制值的处理，不把它当普通回答念出。

## 4. 打断与 pending 调度

```mermaid
flowchart TD
    SEM["Judge接受有效语义"]
    P{"playback.state仍为true？"}
    CANCEL["取消当前Chat/TTS本地任务<br/>发chat.cancelled或tts.cancelled"]
    CL["客户端停止旧turn播放<br/>清空已排队PCM / 报false"]
    HI["若生成尚未结束且配置允许<br/>历史保留partial + 中断标记"]
    DN["新话轮最终DECODE"]
    ACTIVE{"旧chat任务未结束<br/>或客户端还在播放？"}
    PD["暂存单个pending_decode<br/>发送chat.pending"]
    FREE["chat任务完成回调<br/>或playback=false"]
    GO["无旧任务且不播放 -> 启动新Chat"]
    SEM --> P
    P -->|是| CANCEL --> CL --> HI
    P -->|否| DN
    HI --> DN
    DN --> ACTIVE
    ACTIVE -->|是| PD --> FREE --> GO
    ACTIVE -->|否| GO
```

当前不是同时说话模式：播放中的有效语义会打断，未放通噪声不会打断。
客户端不报告播放状态会破坏此策略，不能只消费音频而省略上行状态。
取消停止本地SSE消费、TTS submit/poll和浏览器播放；外部TTS无取消API，
不承诺已提交远端工作立即释放GPU。

每连接最多一个活动Chat任务、一个待启动decode槽，不是无限多话轮队列。
客户端用turn_id隔离旧PCM、取消事件和新回复，已缓冲数据不会被撤回。
生成中保留的是已生成文字，不是已播放字级对齐；decode已完成的历史不会
因随后播放打断被改写为精确已听文本。

## 5. 会话生命周期与容量

每个WS创建独立FSM、声学状态、历史、队列和任务。新连接先configure，
连接断开取消所属响应并释放adapter，历史不持久化。reset清空历史/候选/
当前响应/pending。configure重建输入adapter和响应设置，不是跨实例热迁移。

引擎调度沿用部署runtime的vLLM scheduler；本应用没有增加可承诺的
跨用户公平调度、分类优先级或并发 admission control。生产入口须配置
连接与话轮限额，并以压测结果确定容量，不能用“能建立多个WS”当容量验收。
30轮原始音频历史、8秒分类窗口以及长轮WAV都会占内存/上下文预算。

## 6. 日志读法

| 字段/组合 | 含义 |
|---|---|
| `request_kind=VASD_SEM` | Judge语义有效性请求 |
| `request_kind=VAED`、command=`<c>` | 模型输出“已”，不保证门控接受 |
| `<c>` + `speech=true` + `completion_accepted=false` | 语义完整但AVAD未关闭，继续Listen |
| `semantic_complete` + `completion_accepted=true` + `speech=false` | 语义和声学共同通过，直接Decode |
| `incomplete_silence_timeout` + `NOT_RUN` | 本批超时兜底，不再请求VAED |
| UI `AVAD · NOT_RUN` | 无request_kind时显示AVAD；不是AVAD没有执行 |

实际例子（2026-11-09，北京时间）：15:39:41.394，VAED“已”、
probability99.88%/margin6.75，但speech=true不提交；15:39:41.587，
本批重新判“已”且speech=false，semantic_complete直接Decode。
证据：`workspace/logs/20261109T071156Z_mac_echo_7bf548e5/entry.log`。
该开发会话含可选视频，不作为本次纯语音范围隔离或生产音频验收证据。
