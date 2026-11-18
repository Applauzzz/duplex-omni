# 上线适配：后端新话轮取消策略

分支：`feature/duplex-online-service`，基于 `159dd11`。
本文件记录实现接口，不代表完成线上联调。中间层由其他工程负责。

## 配置

部署使用独立配置文件，在现有配置中设置：

```json
{
  "server_policy": {
    "vaed_mode": "chunk",
    "interrupt_policy": "new_user_turn"
  }
}
```

此片段不是完整配置；保留原配置的config与prompts。
直接运行svad_debug_server.py时，通过现有参数 `--config` 指向部署配置。
缺省 `interrupt_policy=playback` 保留原网页行为。
模式由服务端配置决定，客户端configure不能覆盖；
configured.config.interrupt_policy回带有效值。
代码变更需应用重载，本文实施没有重载或修改共享主配置。

## 行为

- 每个连接新会话，仍走AVAD、VASD、VAED，再进入Chat。
- VASD接纳新话轮、发出PREFILL事件时，取消上一条未作废回复。
  不是每批音频、每个分类prefill或Chat开始时都取消。
- 不读取客户端playback.state，不等待停止播放确认。
- 生成中的旧Chat/TTS本地任务被取消；已结束回复也可通知清理尾部音频。
- 首轮没有上一条回复，不发送取消。每条回复只作废一次。
- 取消不改变当前音频准入和Chat的listening拒识规则。
- 没有新增ASR、续聊、供应商TTS取消接口或svrkit接口。
  本地取消停止提交、轮询和转发，不承诺供应商立即停止已提交的合成。

## 中间层事件

仍使用内部JSON WS协议，取消示例：

```json
{
  "type": "tts.cancelled",
  "turn_id": 3,
  "reason": "new_user_turn",
  "audio_done": true,
  "retained": false,
  "interruption_marker": null
}
```

type也可能是chat.cancelled。两者都作废指定turn_id，
中间层应统一处理，不能只监听tts.cancelled。

新增audio_done表示该turn_id此前是否已发送正常tts.done，
不是客户端播放完成确认：

| 内部取消事件 | 中间层标准映射 |
|---|---|
| audio_done=false | 尚未正常音频结束，发RESPONSE_AUDIO_DONE(interrupted=true) |
| audio_done=true | 已发正常音频结束，发RESPONSE_CANCELED，避免重复DONE |

最终以中间层自己记录的标准事件终止状态为准：
例如TTS失败、文本-only或listening路径可能已由中间层补过DONE，
不能仅根据audio_done重复终止。

客户端按response_id停止、清队列、屏蔽已取消回复的迟到音频。
正常DONE之后仍可收到CANCELED的行为需双方确认。
其他编码、20ms聚合、ID、错误、静默路径收口由中间层实现，
参见 [适配分析](interface_adaptation_20261111.md)。

## 边界

此策略是“新有效用户话轮使上一回复作废”，不推断用户实际播放位置。
不要求decode、TTS和playback时间戳映射。
对Chat已生成但客户端未听到的历史内容，仍沿用既有历史策略；
不是逐词播放账本或精准断点恢复。

## 验证

env.sh初始化后激活omni，使用当前实验目录、已验证runtime overlay和
当前vllm-omni的进程级PYTHONPATH，核对解释器及服务模块导入路径。
四个相关本地WebSocket测试通过，耗时1.308秒：

- 新策略：无playback反馈时取消生成中的回复及已正常输出结束的回复；
  浏览器不能覆盖策略，迟到playback=true不阻塞下一轮。
- 原策略：播放状态为true时语义打断生成。
- 原策略：不播放时语义放通不取消生成。
- reset取消活跃TTS的原行为。

使用受控Chat/TTS/VAD，无真实模型请求；现有aiohttp警告保留。
git diff --check通过，尚未进行中间层集成和真实播放验收。
