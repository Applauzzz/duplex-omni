# VAED Chunk 轮询

分支：`feature/svad-vaed-polling`，基于 Mac tools checkpoint `8352472`。

## 当前策略

- `vaed_mode=chunk`：进入 Listen 后每个收到的音频批次调用一次 VAED，
  不再要求 `speech_stopped` 边沿。请求串行，不在后台创建独立定时器。
- `audio_chunk_ms=200` 控制浏览器目标提交间隔；请求处理中音频会合并，
  因此轮询不是严格每二百毫秒一次，也不并行发起积压请求。
- `vaed_window_ms=8000`：分类只取最近八秒完整 chunk；不足时取已有音频。
  与 VASD 相同，单块超过窗口仍保留该整块。最终 Chat 保留完整话轮。
- 完成判别仍要求概率、margin 和连续确认通过，并且当前
  `AVAD.speech_active=false` 才 Decode。说话期间的“已”不能触发回复。
- 连续确认按轮询次数累计；“未”或置信度不足清零。

## 声学与兜底

“AVAD 关闭”指带滞回和静音累计的 `speech_active=false`，
不是某一帧概率低于阈值。`silence_duration_ms` 仍影响关闭时机，
当前设置为 `256 ms`，未删除声学判停门控。轮询提前完成语义判别，
但不保证消除声学等待；实际触发还取决于音频批次边界与请求耗时。

只有 AVAD 已关闭且本次 VAED 未接受时才启动兜底等待。当前
`incomplete_silence_timeout_ms=128` 保留。后续未完成轮询不重置计时；
恢复语音清零。后续批次到达时若已经超时，直接兜底 Decode，
该批不再调用 VAED，沿用原逻辑不把该超时检查批次附加到话轮。

## 配置与兼容

统一 JSON 的 `server_policy` 管理 `vaed_mode`，`config` 管理 `vaed_window_ms`；
普通 VAD 网页仅显示，不提交这两个参数。服务端忽略浏览器伪造的覆盖值。
`endpoint` 模式保留之前的 AVAD 端点触发、完整话轮 VAED 行为。
旧配置缺省使用 endpoint。当前主配置已设置以下顶层区域：

```json
{
  "server_policy": {
    "vaed_mode": "chunk"
  },
  "config": {
    "audio_chunk_ms": 200,
    "silence_duration_ms": 256,
    "vasd_window_ms": 8000,
    "vaed_window_ms": 8000,
    "incomplete_silence_timeout_ms": 128
  }
}
```

窗口与 VASD 窗口并列，避免两个区域重复定义窗口。加载器仍兼容旧的
server_policy 窗口字段，该区域若有同名值会优先，所以主配置已删除重复值。
修改后重连会话读取新值，前端的应用设置不能覆盖模式或窗口。
旧应用不认识 config.vaed_window_ms，会在刷新时返回错误，因此本次
迁移必须配合应用重载，不能只修改 JSON 留着旧进程。

AVAD 与 VAED 串行：当前批次先执行 AVAD，再执行 VAED。静音累计按
收到的音频采样点跨批次保存，而不是等待 VAED 的墙上时钟时间；
VAED 执行快慢不会取消二百五十六毫秒的声学门控。

修改代码后需要重载应用服务才生效，模型服务不需要重启。
用户已授权仅重载 8080 普通 VAD 与 8081 Agent 应用，复用原 Mac 身份、
审计与 M2 策略。MiMo 和外部 TTS 保持运行。真实语音误判、
请求负载和延迟仍需后续验收，服务就绪不代表这些质量门槛通过。

## 本轮验证

七个聚焦用例通过：语义模块五个、服务模块两个，包含真实本地
WebSocket 的配置、说话期间完成不 Decode、关闭后无端点边沿也能
Decode，以及完整音频交给 Chat。覆盖窗口滑动、连续确认、兜底不被
轮询重置、恢复说话取消等待、旧端点基线。网页脚本语法检查通过。
模型判别和声学状态在这些测试中受控，不代表真实音频质量验收。

配置迁移新增验证仅复用服务模块两个用例，均通过，未扩大测试套件。
验证窗口从 config 读取、刷新生效、浏览器不能覆盖模式/窗口，
以及256/128参数保持不变。

## 应用重载结果

运行目录：`workspace/logs/20261109T071156Z_mac_echo_7bf548e5`。
Agent应用PID `2967420`，普通VAD应用PID `2967422`。
两者健康检查显示MiMo/TTS可用，默认值与真实WebSocket配置均为
chunk/8000，前端覆盖被忽略，`/agent`返回200。
仅应用重载，原MiMo PID `2301222`和外部TTS保持运行。
浏览器需要刷新并重新开启采集；Mac连接若断开需恢复连接，
原身份与审计文件未更换。当前localhost/SSH访问方式不变。
