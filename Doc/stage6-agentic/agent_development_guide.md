# Duplex MiMo Agent 开发与运维指南

更新时间：2026-10-31。

## 1. 当前能力与入口

Duplex MiMo Agent 由三部分组成：

- Duplex MiMo：AVAD、VASD_SEM、VAED、音视频理解和回答生成。
- 流式 TTS：把 MiMo 文本转换成 24 kHz PCM。
- OpenAI Agents SDK：管理 instructions、function tools、handoffs、history 和 Agent lifecycle。

正式浏览器入口：

    http://28.29.217.180:8080/agent

原状态机调试入口：

    http://28.29.217.180:8080/

Chrome 通过 HTTP IP 使用麦克风和摄像头时，需要把 8080 origin 视为安全来源：

    /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
      --user-data-dir=/tmp/chrome-mimo-agent-8080 \
      --unsafely-treat-insecure-origin-as-secure=http://28.29.217.180:8080 \
      --new-window http://28.29.217.180:8080/agent

## 2. 总体架构

    Browser /agent
      microphone PCM16 + optional JPEG + TTS playback
              |
              v
    RealtimeSession
      Agent instructions + tools + handoffs + SDK history
              |
              v
    DuplexMiMoTransport
              |
              v
    8080 same-origin proxy /agent-ws
              |
              v
    8081 agentic duplex backend
      AVAD -> VASD_SEM -> VAED
      MiMo multimodal Chat + Agent tool bridge + TTS
              |
              +--> MiMo 8090
              +--> external TTS

组件职责：

| 组件 | 职责 |
|------|------|
| useDuplexMedia | 麦克风采集、摄像头采样、PCM 播放 |
| DuplexMiMoTransport | SDK transport 事件与 duplex WebSocket 协议互转 |
| RealtimeSession | Tool 执行、handoff、SDK history 和 lifecycle |
| AgenticMiMoChatProvider | MiMo 推理、tool decision、等待 SDK tool output |
| SemanticRealtimeAdapter | VAD 状态机和音频/视频准入 |
| MiMo | 音频、视频和对话上下文理解 |
| TTS provider | 文本分段和流式 PCM 合成 |

## 3. 代码位置

父仓库：

    workspace/experiments/20261025_mimo_tts_integration/
      agent_runtime.py
      semantic_vad.py
      svad_debug_server.py
      svad_config.json
      test_agent_runtime.py
      test_svad_debug.py

Agent framework 子模块：

    third_party/openai-realtime-agents/
      src/app/agentConfigs/duplexMimo/
        index.ts
        manifest.json
      src/app/duplex-mimo/page.tsx
      src/app/agent/page.tsx
      src/app/hooks/useDuplexMedia.ts
      src/app/lib/DuplexMiMoTransport.ts
      src/app/lib/DuplexMiMoTransport.test.ts
      public/duplex_pcm_capture.js

## 4. 当前默认 Agent

当前默认 Agent 是单一通用多模态助手 duplex_assistant。

默认 tools 和 handoffs 都为空。普通音视频问答直接走 MiMo 原生流式多模态 Chat，
不会经过 structured tool envelope。这样可以保留 MiMo 的普通问答和视觉质量。

静态描述保存在：

    src/app/agentConfigs/duplexMimo/manifest.json

可执行 Agent 和工具函数定义在：

    src/app/agentConfigs/duplexMimo/index.ts

Agent instructions 应明确角色、业务边界、工具调用条件、不得猜测的信息，以及如何
使用本轮音频和视频。工具 execute 是函数，不能只写在 manifest JSON 中。

## 5. 添加 Function Tool

### 5.1 浏览器内无敏感信息的工具

在 duplexMimo/index.ts 中使用 SDK tool()：

    import { RealtimeAgent, tool } from '@openai/agents/realtime';

    const getCurrentTime = tool({
      name: 'get_current_time',
      description: '获取指定 IANA 时区的当前时间。',
      parameters: {
        type: 'object',
        properties: {
          timeZone: {
            type: 'string',
            description: '例如 Asia/Shanghai',
          },
        },
        required: ['timeZone'],
        additionalProperties: false,
      },
      execute: async ({ timeZone }) => ({
        timeZone,
        time: new Intl.DateTimeFormat('zh-CN', {
          timeZone,
          dateStyle: 'full',
          timeStyle: 'long',
        }).format(new Date()),
      }),
    });

    export const duplexAssistant = new RealtimeAgent({
      name: 'duplex_assistant',
      instructions: [
        '你是通用实时多模态助手。',
        '用户询问当前时间时必须调用 get_current_time。',
        '不得编造工具结果。',
      ].join(' '),
      tools: [getCurrentTime],
      handoffs: [],
    });

    export const duplexMimoScenario = [duplexAssistant];

### 5.2 需要密钥或数据库权限的工具

不要把服务密钥放进浏览器。execute 应调用 Next.js server route：

    const lookupOrder = tool({
      name: 'lookup_order',
      description: '查询订单状态。',
      parameters: {
        type: 'object',
        properties: { orderId: { type: 'string' } },
        required: ['orderId'],
        additionalProperties: false,
      },
      execute: async ({ orderId }) => {
        const response = await fetch('/api/tools/lookup-order', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ orderId }),
        });
        if (!response.ok) {
          throw new Error('Order lookup failed: ' + response.status);
        }
        return response.json();
      },
    });

对应后端文件：

    src/app/api/tools/lookup-order/route.ts

用户入口经过 8080，因此还要在 8080 同源代理中转发 /api/tools/* 到内部 3000。

### 5.3 Tool 设计要求

- name 使用稳定的 snake_case。
- description 明确何时调用，不要只描述实现。
- parameters 尽量严格，设置 required 和 additionalProperties: false。
- execute 返回可 JSON 序列化的小对象。
- 工具错误应抛出明确异常，不返回伪成功。
- 有副作用的工具需要确认、幂等键或 approval。
- 不要一次暴露大量相似工具，模型选择会变差。

### 5.4 当前 Web Search Tool

当前 search_web 使用 iChat Serper：

    POST http://ichat.woa.com/api/serper/search
    x-api-key: ICHAT_API_KEY

浏览器不会接触 token。调用链为：

    search_web execute()
      -> POST /api/tools/web-search
      -> 8080 same-origin proxy
      -> Next.js server route
      -> iChat Serper

Next.js 进程通过环境变量 ICHAT_API_KEY 获得 token。该值不得写入 Git、manifest、
NEXT_PUBLIC 变量或浏览器日志。

已验证每次 Serper 搜索返回 credits=1、cost_usd=0.0003。默认 instructions 要求
每个用户话轮最多调用一次 search_web，以控制限额。

iChat 普通 Chat Completions 支持 gpt-5/gpt-4.1，但当前 /responses 路由对
gpt-5 和 gpt-4.1 加 web_search 都返回 invalid model；chat.completions 的
web_search_options 也没有实际联网结果。因此当前使用 Serper Function Tool，
不是 OpenAI Hosted Web Search。

### 5.5 当前日期时间工具

get_current_datetime 在浏览器 Agent 中本地执行，不消耗搜索额度。返回：

- ISO UTC 时间。
- 北京时间格式化文本。
- 固定时区 Asia/Shanghai。

用户询问今天几号、现在几点、星期几或当前时间时，instructions 要求必须调用
get_current_datetime，禁止调用 search_web。真实语音验证只调用了一次
get_current_datetime，并按北京时间回答。

## 6. Tool 调用链

    User audio/video
      -> MiMo decides tool_call
      -> backend emits agent.function_call
      -> DuplexMiMoTransport emits SDK function_call
      -> RealtimeSession validates and runs tool.execute()
      -> sendFunctionCallOutput()
      -> backend receives agent.function_call_output
      -> MiMo continues the same turn
      -> final answer -> TTS

当前共享 MiMo 8090 没有启用 vLLM native tool-call parser。有 tools 时使用 JSON
schema tool envelope，arguments 是 JSON object 编码后的字符串，Python 服务会
再次解析和校验。没有 tools 时直接走普通 MiMo streaming Chat。

## 7. 添加 Handoff

Handoff 用于切换整个 Agent，而不是执行一次动作：

    const billingAgent = new RealtimeAgent({
      name: 'billing',
      instructions: '只处理账单和付款问题。',
      tools: [lookupInvoice],
      handoffs: [],
    });

    const routerAgent = new RealtimeAgent({
      name: 'router',
      instructions: '账单问题调用 transfer_to_billing；其他问题直接回答。',
      tools: [],
      handoffs: [billingAgent],
    });

SDK 会自动创建 transfer_to_billing。handoff 成功后：

- RealtimeSession.currentAgent 更新。
- 新 Agent 的 instructions/tools 通过 agent.session.update 发给服务端。
- handoff tool 和 output 写入 SDK history。
- MiMo 在同一个用户话轮继续生成最终回答。

不要创建无业务意义的双向 handoff 环。早期 greeter/haiku 示例已从默认配置移除，
因为它会向通用问答暴露无关 transfer tools。

## 8. 音频、视频和 TTS

### 8.1 音频

- AudioWorklet 输出 mono PCM16。
- 浏览器约每 500 ms 聚合一个音频 chunk。
- transport 把 AudioContext 的实际采样率发给服务端。
- AVAD、VASD_SEM、VAED 决定该轮是否进入 MiMo。

### 8.2 视频

- 摄像头必须由用户显式启用。
- 视频没有独立状态机。
- JPEG 只伴随 outgoing audio chunk，最多每秒一帧。
- 只有 VAD 接受的音频所携带帧会进入 MiMo。
- DECODE 时 accepted JPEG 组成 video/jpeg frame sequence。

页面 Agent Activity 会显示 Vision input: N frames：

- N = 0：该轮没有视频帧到达 MiMo。
- N > 0：视频已进入 MiMo；回答错误属于模型视觉质量，不是 transport 丢帧。

六张带 RED/GREEN/BLUE 标签的帧已在原 /ws 和 Agent /agent-ws 两条路径通过，
两者都正确回答红色、绿色、蓝色。

### 8.3 TTS 和打断

- 服务端发送 24 kHz PCM。
- 浏览器在一个 AudioContext 时间轴上排队播放。
- 首个播放块发送 playback.state active。
- 播放结束发送 playback.state inactive。
- 用户语义打断、SDK interrupt 或 disconnect 会清空播放队列。
- retained interruption 在 SDK history 中标为 incomplete，并保留 ⏸。

## 9. WebSocket 协议

SDK/浏览器到服务端：

| 事件 | 作用 |
|------|------|
| configure | 配置 VAD、TTS 和 retained context |
| audio | PCM16 音频及可选 video_frame |
| playback.state | 通知浏览器是否仍在播放 TTS |
| agent.session.update | 更新 Agent instructions 和 tools |
| agent.function_call_output | 回传 SDK tool/handoff 结果 |
| response.cancel | 取消当前模型/TTS 回复 |
| reset | 清空状态机和历史 |

服务端到 SDK/浏览器：

| 事件 | 作用 |
|------|------|
| configured | 配置完成 |
| transition | VAD/FSM 状态变化 |
| chat.started | 回答开始，包含 video_frame_count |
| agent.function_call | 请求 SDK 执行 tool/handoff |
| chat.delta / chat.done | 文本增量和完成 |
| chat.cancelled | 模型生成取消 |
| tts.audio / tts.done | PCM 音频和完成 |
| tts.cancelled | TTS 取消 |
| chat.error / error | 显式错误 |

## 10. 部署和端口

| 端口 | 服务 | 暴露范围 |
|------|------|----------|
| 8080 | 状态机页面及 Agent 同源代理 | 服务器 IP |
| 3000 | Next.js Agent host | 内部 |
| 8081 | Agentic duplex backend | loopback |
| 8090 | MiMo API | loopback |

8080 路由：

| 路径 | 目标 |
|------|------|
| / | 原状态机页面 |
| /ws | 原状态机 WebSocket |
| /agent | Agent 页面 |
| /agent-ws | Agent backend WebSocket |
| /_next/* | Next.js assets |
| /duplex_pcm_capture.js | AudioWorklet |
| /api/tools/* | Next.js server-side business tools |

环境初始化：

    source /mnt/geminihzceph/user_whynotzhliu/my_envs/env.sh
    conda activate omni

Agent backend 必须复用健康 8080 的 runtime snapshot。不要直接把当前 vllm-src
放进 PYTHONPATH，否则可能与已安装 CUDA 扩展版本不匹配。

## 11. 聚焦测试

Python Agent runtime：

    PYTHONPATH=workspace/experiments/20261025_mimo_tts_integration       python -m unittest -v test_agent_runtime

WebSocket tool/cancel：

    PYTHONPATH=workspace/experiments/20261025_mimo_tts_integration       python -m unittest -v       test_svad_debug.DebugServiceTests.test_agent_function_call_round_trip_continues_chat       test_svad_debug.DebugServiceTests.test_agent_response_cancel_stops_current_chat

TypeScript：

    cd third_party/openai-realtime-agents
    npx tsc --noEmit --pretty false

Transport history：

    node --experimental-strip-types --test       src/app/lib/DuplexMiMoTransport.test.ts

Production build：

    NEXT_TELEMETRY_DISABLED=1 npm run build

不要在运行 next dev 的同一目录同时执行 next build；两者共用 .next，build 会使
dev server 缺少 routes-manifest。完成 build 后需要重启 dev。

## 12. 日志与排障

服务端关键日志：

    agent_session_updated ... tools=[...]
    agent_chat_started ... video_frames=N tools=[...]
    agent_function_call ... name=... arguments=...

浏览器 Agent Activity 显示 Agent handoff、Tool start/end、Vision input 帧数、
后端错误和 Playback interrupted。

Conversation 主对话区也直接渲染 SDK history 中的 function_call item：

- status=in_progress 时显示工具名、格式化参数和旋转 loading。
- status=completed 时使用同一个 itemId 原位替换为完整 tool output。
- 参数和结果按 JSON 格式化；非 JSON 输出保留原始文本。

该显示不维护第二套 tool 状态，完全依赖 RealtimeSession history 的
item_update，因此不会与实际工具执行状态漂移。

Conversation 滚动容器默认处于贴底跟随模式。新消息、流式 delta、tool loading
或 tool completed 更新到来时，会在下一帧平滑滚动到底部。用户主动向上滚动且
距离底部超过 72px 时暂停自动滚动；用户重新滚回底部后自动恢复，避免阅读历史
时被强制拉回。

### MiMo agent returned no reply text

tool envelope 返回 final 但 content 为空。当前 schema 设置 minLength，并在同一
用户轮最多修正重试一次。第二次仍为空才抛错。

### invalid tool envelope

MiMo 在 structured tool 模式下偶尔会同时输出损坏的 JSON envelope 和重复
XML tool_call。服务端在严格 JSON 解析失败后，可以从第一个 XML tool_call
恢复工具名与 parameter，并丢弃后续重复块。

另一种已观察到的退化是：开头存在允许的 tool name 和一个完整的转义 JSON
arguments 对象，但 envelope 随后被单引号、think 标签或重复拒答文本截断。
服务端会按 JSON 对象深度恢复第一个完整 arguments，并忽略其后的文本。

恢复有严格边界：

- 工具名必须存在于当前 Agent tools。
- 只恢复第一个完整 tool_call。
- JSON 前缀只恢复第一个完整 arguments object。
- 未知工具不会执行。
- 不完整 arguments 不会执行。
- arguments 仍转换为 JSON 并交给 SDK 参数校验。

### 大量 Tool 错误

检查当前 Agent 是否暴露无关 tools/handoffs、tool name 是否一致、parameters
是否严格、execute 是否抛错，以及日志中的 tools 和 function call name。
默认 duplex_assistant 没有 tools，不应产生 tool call。

当前启用 search_web 后，涉及最新信息的轮次应出现一次 search_web。若同一轮重复
调用，检查 instructions 中的单次调用约束和服务端 agent_function_call 日志。

### 模型说看不到视频

先看 Vision input：

- no frames：检查 Enable camera、预览和浏览器权限。
- N frames：视频已进入模型，检查图像质量、光线和问题表达。

### 502 Bad Gateway

企业网关不允许直接访问 3000。使用 8080/agent，不要把 3000 作为 Mac 入口。

### 麦克风不可用

Chrome 安全 origin 必须是实际页面的 http://28.29.217.180:8080。

### Agent 页面 500

检查内部 Next 3000 是否运行，以及 8080 是否能访问 127.0.0.1:3000。

### /agent-ws 立即关闭

检查内部 8081：

    curl http://127.0.0.1:8081/health

## 13. 当前限制

- MiMo 8090 未配置 vLLM native tool-call parser。
- 有 tools 时使用 structured envelope；无 tools 时走普通 multimodal Chat。
- SDK user audio history 当前没有语音转写文本。
- 摄像头是低频 JPEG 上下文，不是模型侧连续视频 KV prefill。
- 真实业务工具的鉴权、approval、超时、重试和审计需要按业务实现。
- 父仓库和子模块修改尚未提交、推送。

## 14. 添加工具检查清单

1. 在 duplexMimo/index.ts 中定义 tool()。
2. 设置稳定 name、明确 description 和严格 parameters。
3. 实现 execute；敏感逻辑放 server route。
4. 把 tool 加入目标 RealtimeAgent.tools。
5. 更新 instructions，明确何时调用和不得猜测。
6. 如使用 /api/tools/*，更新 8080 同源代理。
7. 运行 TypeScript、transport 和 Agent runtime 聚焦测试。
8. 用真实语音验证 Tool start/end。
9. 检查 agent_function_call name 和 arguments。
10. 验证失败、超时、取消和重复调用行为。
