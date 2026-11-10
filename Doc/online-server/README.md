# 纯语音服务上线交接

交接日期：2026-11-09。交付对象：负责部署、接入、容量与上线验收的工程团队。

## 1. 本次上线范围

本次只交付 **WebSocket 纯语音 VAD + MiMo + TTS 服务**：

```text
客户端持续上传麦克风 PCM
  -> Silero AVAD 声学判定
  -> MiMo VASD 语义有效性 / VAED 语义完成判定
  -> MiMo 理解完整用户话轮并流式生成正文
  -> 外部 CosyVoice 流式文本合成
  -> WebSocket 返回 PCM / 客户端播放
```

| 包含 | 不包含 |
|---|---|
| PCM 音频输入、声学/语义端点、自动提交 | video input、摄像头、图像/视频问答 |
| 语音理解、正文 delta、TTS PCM 输出 | Agent SDK、Realtime SDK 协议适配 |
| 连续收音、语义打断、会话内历史 | 工具调用、联网搜索、Mac tools、MCP |
| 重置、取消、错误与状态事件 | 后台 reasoning、非阻塞任务栏 |

入口为普通服务 `/ws`，启动 **不加 `--agentic`**。不是 `/agent-ws`，
也不是 OpenAI Realtime 协议。客户端无需 OpenAI SDK、Next.js、Node 服务、
ICHAT_API_KEY 或 Mac 配对。

MiMo 是唯一语音理解与回复模型，无独立 ASR 转写环节。
当前 TTS 是 **外部 CosyVoice Audio Engine 的 submit/poll 协议**，
不是历史本地 Qwen3-TTS，也不是 MiMo 原生音频输出。
双工指持续收音、并发输出和可打断；不代表同一模型音频 KV 持续增量推理。

## 2. 文档导航

| 文档 | 内容 |
|---|---|
| [部署与环境](deployment.md) | 交付版本、目录、依赖、启动、网络、更新与回滚 |
| [完整调度图](scheduling.md) | 拓扑、FSM、端点、流式输出、打断、并发边界 |
| [WebSocket 协议](websocket.md) | 消息格式、音频格式、背压、播放状态、错误与验收 |
| [内网 Demo 重载](intranet_demo_20261109.md) | 28.29.217.68:8080开发入口、Chrome访问与验证边界 |

本目录是此次上线交接入口。其他阶段文档仅作为历史参考，遇到参数、
TTS 类型或调度差异，以本目录与本次交付配置/源码为准。

## 3. 版本与交付状态

当前开发分支：`feature/svad-vaed-polling`。
父仓库开发基线：`8352472c1a301665ffcc983f68d1d36ee2883c42`。
VAED chunk 轮询代码、配置及本文档随本次分支提交发布；交付版本应选择
包含本文档的提交，不能仅 checkout 上述开发基线。
部署前记录实际 checkout 的 SHA、子模块 SHA 与配置摘要；
提交及推送结果见所选计划的 progress.md。

| 子模块 | 当前 gitlink |
|---|---|
| `vllm-omni` | `6a841874ef56cf0590c5f5c24889a4ca65e6ac15` |
| `vllm-src` | `ba860768a965efadcf059089c04862c46e568242` |
| `third_party/openai-realtime-agents` | `57592f951fe229b0dea95acf8f3951796fbdaa73` |

最后一个子模块不参与本次语音请求链路。现有 Python 入口仍复用了同仓库
Agent/Mac 辅助模块，不承诺这是已经拆分好的纯语音最小安装包。

## 4. 上线隔离要求

现有服务代码仍保留视频字段、Agent 代理路由及调试配置事件。
“此次不交付”不等于“源码已经删除/禁止”。工程上线必须落实：

1. 只部署普通应用，不启动 8081 Agent、3000 Next 或 `launch_mac_echo.py`。
2. 生产入口只放行 `/ws`；`/health` 限内部探活；需要调试时受控开放
   `/`、`/defaults`、`/capture_worklet.js`，不要把调试控制台当生产 UI。
3. 拒绝 `/agent`、`/agent-ws`、`/_next/*`、`/api/tools/*` 等非语音路由。
4. WebSocket 消息层使用允许列表，拒绝 `video_frame` 和 `agent.*` 等事件。
   普通 HTTP 路径网关不能自动检查升级后的 JSON，需由接入层/专用适配器实施。
5. 限制客户端修改 Prompt/阈值。当前普通服务允许覆盖多数会话配置，
   仅 VAED 模式/窗口强制来自服务端，不能宣称全部配置已经只读。
6. 配置鉴权、TLS/WSS、连接/音频时长/请求速率与资源配额；当前应用没有
   可直接依赖的生产用户鉴权和租户配额。网络内网可达不等于访问授权。

这些是上线门槛，不是本次文档编写已完成的代码改造。

## 5. 验收与剩余风险

2026-11-09 已记录普通服务健康、默认值与真实 WS configure 正常。
真实日志出现 `VAED=<c>` 且 `speech=false` 的 `semantic_complete` Decode，
也出现 `incomplete_silence_timeout` 兜底。相关受控测试已验证窗口、
AVAD 门控、兜底计时和配置归属。

这些证据不替代生产验收。以下事项上线前需明确 owner 并闭环：

- 发布不可变代码与 runtime 制品，验证目标节点编译依赖。
- 实施上述语音范围隔离、鉴权、配置权限和日志脱敏。
- 验收真实语音、句内停顿、背景说话、噪声、打断与断网恢复。
- 验收长回答首个 `tts.audio` 早于 `chat.done`，客户端播放连续且不串轮。
- 压测多用户的 P50/P95 延迟、显存、吞吐、队列与会话历史开销。
- 明确外部 TTS 的服务 owner、可用区、音色、容量、超时与 SLA。
- 当前不承诺固定并发人数、持久历史、音频播放 ACK 精确对齐，
  或取消后远端 TTS 计算立即停止。

本次整理没有新增生产部署、修改运行代码或执行新的音频/负载验收。
