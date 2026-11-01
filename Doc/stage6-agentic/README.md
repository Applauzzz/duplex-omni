# Stage 6: Agentic Duplex MiMo

建立时间：2026-10-31。

## 文档入口

| 文件 | 内容 |
|------|------|
| [agent_development_guide.md](agent_development_guide.md) | 当前架构、Tool/Handoff 开发、音视频、协议、部署、测试和排障手册 |

本 README 保留阶段设计和验证记录。实际开发与运维优先阅读
agent_development_guide.md。

## 目标

将现有 duplex MiMo 推理服务接入 OpenAI Agents SDK：

- duplex MiMo 继续唯一负责 VAD、音频/视频准入、MiMo 多模态推理、流式 TTS
  和语义打断。
- openai-realtime-agents 及其 @openai/agents/realtime runtime 负责 agent
  instructions、tools、handoffs、tool history 和 agent lifecycle。
- 现有 SVAD 浏览器前端冻结，不作为 Stage 6 agent 入口继续开发。

第三方框架以 Git submodule 固定在 third_party/openai-realtime-agents，
记录 URL 为用户 fork https://github.com/Applauzzz/openai-realtime-agents.git。

## 架构

    RealtimeAgent / RealtimeSession
      tools + handoffs + local history
                 |
                 v
    DuplexMiMoTransport (RealtimeTransportLayer)
                 |
                 v
    duplex MiMo /ws control + media protocol
      AVAD -> VASD_SEM -> VAED
      accepted audio + JPEG frame sequence
      MiMo streaming Chat + tool calls
      streaming TTS + interruption

custom transport 针对 fork 锁定的 @openai/agents 0.0.5 实现。默认
useRealtimeSession 仍使用 OpenAIRealtimeWebRTC；只有调用方显式传入
DuplexMiMoTransport 时才走本地 duplex MiMo。因此当前 demo UI 行为未切换。

## Agent 控制面

SDK 到服务端：

| 事件 | 含义 |
|------|------|
| agent.session.update | 当前 agent 的 instructions 和 function tools；handoff 后再次更新 |
| agent.function_call_output | SDK 执行 tool 或 handoff 后回传结果 |
| response.cancel | SDK/guardrail 主动取消当前回复 |
| audio | 16 kHz PCM16，可继续附带现有 video_frame |

服务端到 SDK：

| 事件 | SDK transport 映射 |
|------|--------------------|
| agent.function_call | function_call，由 RealtimeSession 执行 tool/handoff |
| chat.started | turn_started |
| chat.delta | assistant item_update + audio_transcript_delta |
| chat.done | completed assistant item + turn_done |
| tts.audio | audio ArrayBuffer |
| tts.done | audio_done |
| chat.cancelled / tts.cancelled | audio_interrupted |

MiMo tool-call loop 在 tool call 处暂停。RealtimeSession 根据当前
RealtimeAgent 执行普通 function tool，或执行 SDK handoff 并调用
updateSessionConfig 切换 instructions/tools；结果回传后 MiMo 在同一用户轮继续生成。

当前 MiMo 8090 使用 vLLM 原生工具解析：

    --reasoning-parser mimo
    --enable-auto-tool-choice
    --tool-call-parser mimo

有 tools/handoffs 时，AgenticMiMoChatProvider 将完整 OpenAI tools 数组交给 MiMo，
消费 vLLM 返回的流式 `tool_calls`，再交给 RealtimeSession 执行。tool output 以标准
tool message 回填并在同一轮继续生成。无 tools 时仍直接使用普通 streaming
multimodal Chat。Tool Router、JSON envelope 和损坏输出 recovery 已移除。

当前通用 Agent 暴露三个标准 Function Tools：

- `search_web`：Serper 实时公开信息搜索。
- `get_current_datetime`：北京时间日期和时间。
- `consult_reasoning_model`：通过 server-only Next route 调用 iChat `gpt-4o`
  处理复杂文本推理，再由 MiMo 组织最终口语回答。

工具集合由 manifest 显式声明并由实现 registry 校验；未知工具在 Agent 配置加载时
直接失败，不会静默暴露给 MiMo。

## 代码归属

父仓库：

    workspace/experiments/20261025_mimo_tts_integration/
      agent_runtime.py
      semantic_vad.py
      svad_debug_server.py
      test_agent_runtime.py
      test_svad_debug.py

第三方 fork：

    src/app/lib/DuplexMiMoTransport.ts
    src/app/hooks/useRealtimeSession.ts
    src/app/agentConfigs/duplexMimo/

duplexMimo/manifest.json 当前提供单一通用多模态 duplex_assistant，默认没有
tools/handoffs，并由 index.ts 构造成真实 RealtimeAgent。业务 tools 仍应使用
SDK 的 tool() 定义和执行函数；Python 服务不接管业务 tool implementation。

## 启动边界

duplex 服务增加显式 agent 模式：

    source /mnt/geminihzceph/user_whynotzhliu/my_envs/env.sh
    conda activate omni
    python workspace/experiments/20261025_mimo_tts_integration/svad_debug_server.py \
      --agentic --host 127.0.0.1 --port <isolated-port>

不带 --agentic 时继续使用原 MiMoChatProvider，保持当前服务行为。
Stage 6 首轮没有重启或替换已有 8080/8090 服务。

## 已验证

- AgenticMiMoChatProvider 的 tool-call 分片、等待 SDK 输出、handoff 后配置更新：
  2 项测试通过。
- 原 MiMo 当前/历史音视频 Chat payload：2 项回归通过。
- /ws 从 agent.session.update 到 function call、回传输出、最终 chat.done：
  1 项 WebSocket 端到端测试通过。
- fork 锁定依赖 npm ci 后，npx tsc --noEmit --pretty false 通过。
- 冻结页面/AudioWorklet 聚焦回归通过。
- 父仓库和子模块 git diff --check 通过。
- 隔离 8081 真实验证通过：真实 VASD_SEM/VAED 放通音频，MiMo 产生
  acknowledge_request function call，模拟 SDK 回传后同一轮进入 chat.done。
  Artifact：

    workspace/logs/20261031T_stage6_agentic/
      live_agent_probe_20261031T071408Z_9556c730/

- 真实 RealtimeSession handoff 通过：router 调用 SDK 自动生成的
  transfer_to_specialist，SDK 更新当前 agent/config/history，specialist 完成回复：

    workspace/logs/20261031T_stage6_agentic/
      sdk_handoff_probe_final_only/

- transport retained-interruption history 测试通过：accepted user audio 进入
  SDK history，取消的 partial assistant 标为 incomplete，retained 时追加 ⏸。
- response.cancel WebSocket 测试通过：当前生成被取消并返回
  chat.cancelled(reason=agent_interrupt)。

- 首次 native tool probe 保留为失败证据，确认当前 8090 缺少 parser：

    workspace/logs/20261031T_stage6_agentic/
      live_agent_probe_20261031T070515Z_b7c23f5f/

## 剩余门槛

- 为正式 agent 调用方接入麦克风 PCM、视频帧和 TTS PCM 播放；不修改冻结的
  SVAD 页面。当前已通过程序化 PCM transport 验证。
- 验证用户 fork 远端包含当前 submodule 基准提交，并分别提交/推送子模块与父仓库。
- 在真实浏览器中验收麦克风、摄像头、TTS 和业务工具凭据。

## Phase 6 浏览器 Agent Host

新增独立路由，不修改原状态机页面工作流。正式用户入口：

    http://28.29.218.56:8080/agent

内部 Next.js 和 agent backend 分别运行在 3000、8081，但企业网关不允许
Mac 直接访问 3000。8080 提供同源代理：

    /agent                    -> Next.js agent page
    /_next/*                  -> Next.js static/dev assets
    /duplex_pcm_capture.js    -> AudioWorklet
    /agent-ws                 -> agent backend WebSocket

原状态机页面和协议保持：

    /                         -> SVAD state-machine page
    /ws                       -> original SVAD WebSocket

页面直接创建 RealtimeSession 和 DuplexMiMoTransport：

- AudioWorklet 捕获单声道 PCM16，约每 500 ms 发送一次。
- transport 使用浏览器 AudioContext 的实际采样率。
- 摄像头为可选；JPEG 只伴随 audio flush，最多每秒一帧。
- TTS PCM 在浏览器 AudioContext 中按同一时间轴排队。
- 首个播放块发送 playback.state active，队列结束或打断发送 inactive。
- SDK handoff、tool start/end、当前 agent 和 conversation history 在页面展示。
- 关闭连接会释放麦克风、摄像头、AudioContext 和播放队列。

页面和 backend 均已服务器侧返回 HTTP 200；/agent-ws 已通过 configure
代理探针，production build 通过。真实
Mac 浏览器的 microphone/camera permission、预览和扬声器播放仍需用户验收。
直接 IP 的 HTTP 页面如果没有现有 Chrome insecure-origin 策略，浏览器可能
不提供 getUserMedia；页面会显示 secure-origin 错误而不是静默失败。

真实浏览器首次测试出现过 `MiMo agent returned no reply text`。日志确认
MiMo structured envelope 返回了 kind=final 但 content 为空。当前 schema
要求 content 最少一个字符；provider 仍提供一次同轮修正重试，避免 guided
decoding 忽略长度约束时直接丢弃用户话轮。通过 8080/agent-ws 的真实音频回归
已正常结束为 chat.done。

默认 Agent 已从 greeter/haiku 示例图调整为单一通用多模态
duplex_assistant，默认 tools/handoffs 为空。普通音视频问答直接走 MiMo 原生
streaming multimodal Chat；只有业务配置确实提供 SDK tools/handoffs 时才进入
structured tool envelope。

服务端每轮记录 video_frames 和 tools，页面 Agent Activity 同步显示
`Vision input: N frames`。六张带 RED/GREEN/BLUE 标签的 JPEG 通过原 /ws 和
Agent /agent-ws 均已正确回答红、绿、蓝。显示 N=0 才表示该轮浏览器没有送达
摄像头帧；N>0 但回答错误属于模型视觉质量问题，不是 transport 丢帧。
