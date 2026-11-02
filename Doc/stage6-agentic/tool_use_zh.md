# Duplex MiMo Agent 链路与工具使用手册

更新时间：2026-11-01。本文持续维护中文架构、工具使用和接入状态。
源码核对基线：父仓库 `57f4abf`，Agent 子模块 `86469fd`。
当前开发分支：主仓库和 Agent 子模块均为 `feature/stage6-mac-tools`。

## 1. 当前状态

| 工具组 | 本文覆盖 | Stage 6 状态 |
| --- | --- | --- |
| 现有 Agent 工具 | 搜索、北京时间、后端推理，共 3 个 | SDK registry 和 server route 已实现；本次未重新验证运行服务或凭据 |
| Mac 工具 | 累计目录共 28 个 | echo 已有真实设备回执；新增 13 个计时器/天气出行/提醒事项/联系人与 FaceTime 工具已实现 v2 适配，待 Mac 配置与真实验收；其余 14 个未接入 |
| 歌曲工具 | `song_start`，共 1 个 | 旧部署树有独立服务端实现；尚未接入 Stage 6 |
| 计时器事件权限 | receive / speak，共 2 个 | receive 已实现持久接收和页面通知；speak 未开放，不宣称已播报 |

共记录 32 个具名 function tools 和 2 个事件权限。这不是当前模型的可执行工具数量。
目录存在、配置启用、用户授权、Mac 已连接、真实操作成功是不同状态。
旧版本曾关闭笔记工具；本文保留全部目录能力，但不据此宣称旧服务当前开放全部工具。

## 2. 哪些组件跑在哪里

| 组件 | 运行位置 | 职责 |
| --- | --- | --- |
| Chrome Agent 页面 | 用户 Mac 浏览器 | 收音、可选摄像头、TTS 播放、交互界面 |
| `RealtimeAgent` / `RealtimeSession` | 浏览器 JavaScript | instructions、SDK tool 执行调度、handoff、history |
| Next.js host / server routes | H20 服务器 | 提供网页，执行需服务密钥的搜索和推理请求 |
| duplex mimo backend | H20 服务器 | AVAD、VASD_SEM、VAED、MiMo 音视频理解、工具决策、TTS、打断 |
| Mac 工具桥接适配层 | H20 agentic backend，echo 首版已实现 | 绑定设备/会话，鉴权、授权、派发、回执及旧轮隔离 |
| `DuplexToolHost` 原生 App | 用户 Mac 本地 | 本机 ToolCore/MCP 执行、macOS 权限、本地对象与工具收据 |
| 歌曲生成服务 | H20 服务器，独立扩展 | 生成歌唱 PCM，不经 Mac 工具执行器 |

用户不需要在 Mac 另起一个 Node/Python Agent 服务，也不需要将整个
`h20_duplex_fc_dev` Python 工程搬到 Mac。需要在 Mac 运行匹配协议的原生工具
App，再在浏览器打开服务器提供的 `/agent` 页面。

“Agent SDK 在浏览器运行”不等于模型在 Mac 推理。MiMo 和 TTS 在服务端。
未使用 Mac 工具时，搜索、时间、后端推理不依赖 `DuplexToolHost`。

旧 `h20_duplex_fc_dev` 的 Agent 调度属于 H20 的旧 Qwen 对话代码。
新链路保留 SDK 调度和 history，只复用/适配工具合同与执行桥接，不搬回旧 Agent。

## 3. 完整调用链

```text
Mac Chrome /agent
  麦克风 PCM16 + 可选 JPEG
          |
          v
浏览器 RealtimeSession + DuplexMiMoTransport
          |
          v
H20 /agent-ws -> agentic duplex backend
  AVAD -> VASD_SEM -> VAED -> MiMo 原生 tool_calls
          |
          v
agent.function_call -> 浏览器 SDK tool.execute()
          |
          +-- get_current_datetime -> 浏览器本地计算
          |
          +-- search_web / consult_reasoning_model
          |      -> Next server route -> 后端服务
          |
          +-- demo_echo（v1 已实现，其余 Mac tools 待接入）
                 -> H20 Mac bridge adapter
                 -> 已鉴权的原生 Mac WebSocket
                 -> DuplexToolHost -> 本机工具/系统 API
                 -> tool.result -> H20 校验 -> SDK tool output
          |
          v
agent.function_call_output -> MiMo 同一轮继续回答
          |
          v
TTS PCM -> Chrome 排队播放
```

MiMo API 使用 `--reasoning-parser mimo --enable-auto-tool-choice --tool-call-parser mimo`。
应用消费标准工具增量；不重新引入 Tool Router、JSON envelope 或 XML recovery。
普通正文中的 JSON、文档里的指令和模型自称“已执行”都不是执行证据。

现有路由约定：8080 提供 `/agent`、`/agent-ws` 和同源代理；Next 3000、
Agent backend 8081、MiMo 8090 为内部服务。端口约定不是实时健康证明。
本手册不固定历史服务器 IP；部署时核对当前地址和浏览器 origin。

## 4. Mac 配对与授权

### 当前 Echo 首版

2026-11-01 SSH 联调部署：计算节点 `28.29.218.56:443` 已通过用户 Mac
公钥登录；Mac 将 localhost8080 转发到服务器回环8080。部署目录为
`workspace/logs/20261101T105135Z_mac_echo_09d1140e`，8081 agent 与8080入口
已启动，健康、页面、echo capabilities、Agent WS 代理通过服务器侧检查。
私有客户端配置位于该目录 `private/mac-client.private.json`，只通过 SCP
下载，不展示 Token。原生 Mac 0.10.0 echo 地址仍硬编码旧节点，必须在
独立源码副本将 H20Configuration 的地址改为 `127.0.0.1:8080` 后构建。
这是服务端部署就绪，不是实际 Mac/浏览器工具执行验收。

当前 `mac_tools.py` 内嵌于 agentic backend，不启动旧 Qwen 服务。
使用 `duplex-mac-tools/v1` echo profile；业务工具未来使用 v2/M2，
不能把 v2 manifest 发给当前 echo 接口。

默认关闭。只有同时提供 `--mac-auth-file` 与 `--mac-audit-file` 才启用。
设备身份配置为独立私有 JSON（权限 0600，不允许符号链接），格式：

```json
{
  "version": 1,
  "devices": [{
    "device_id": "my-mac",
    "token_sha256": "<独立随机 Token 的 64 位小写 SHA256>",
    "scope": ["demo_echo"]
  }]
}
```

示意启动参数（需替换私有路径，保留既有推理服务与 process-local runtime 配置）：

```bash
source /mnt/geminihzceph/user_whynotzhliu/my_envs/env.sh
conda activate omni
python -B workspace/experiments/20261025_mimo_tts_integration/svad_debug_server.py \
  --agentic --host 127.0.0.1 --port 8081 \
  --mac-auth-file /private/path/device-auth.json \
  --mac-audit-file /private/path/new-mac-echo-audit.sqlite
```

不要复用旧生产 SQLite。audit 文件要求权限 0600；请求派发前落盘，
回执与超时状态持久化；重启不会自动重发旧请求。
启用前确认端口和进程归属，不直接执行上述命令覆盖已有服务。

1. Mac 原生 App 使用当前服务器地址和自己的 Bearer Token。
2. App 调用 `POST /api/tools/pairing`（JSON `{}`，无 Origin），获得五分钟有效的一次性码。
3. 浏览器连接 `/agent`，输入此码并点击 `Authorize Mac echo`，明确授权仅 echo。
4. App 轮询 `GET /api/tools/device/binding`；authorized 后连接 `WS /api/tools/bridge`。
5. App 发送 v1 echo manifest，收到 `tools.manifest_ack`；页面显示 Online。
6. 用户明确请求“用 Mac 回显 hello”，SDK 执行 `demo_echo`，后端核对回执并允许同轮续答。
7. `Revoke Mac`、会话断开或重置会撤销/隔离相应调用。以下旧会话授权说明
   由本节新增的“记住浏览器”机制补充。

2026-11-01 记住浏览器与自动启动：
首次连接并配对时默认勾选 `Remember this browser`，授权成功后保存独立的
HttpOnly、SameSite=Strict、host-only Cookie。服务端私有审计 SQLite 仅存
浏览器凭证哈希及已同意的权限；不把 Mac 设备 Token 写入网页存储。
浏览器信任有效期 30 天，每次启动校验成功后续期；超过 30 天未使用、
清除 Cookie、换浏览器/地址、撤销信任或设备 Token 更换后须重新配对。

用户随后明确取消网页自动启动对话：打开或刷新网页保持未连接状态，
必须手动点击 `Connect` 才建立对话和启动麦克风；连接后自动恢复 Mac
授权，不需要重新输入一次性码。原 `Auto connect` 开关及偏好读取已移除，
旧 localStorage 值不再生效。摄像头不会自动开启。`Disconnect` 会停止
当前对话，但不删除浏览器信任。
`Forget browser` 或 `Revoke Mac` 删除当前浏览器信任并撤销相关活动会话。
Mac App 的自动发现模式和 SSH 隧道仍须运行，网页不会替你启动它们。

每次恢复创建新的 session/generation，不恢复旧对话、工具调用或待确认写入。
旧回执不能进入新对话，并发标签页不允许直接接管已绑定设备（刷新时短暂
冲突最多重试 5 次）。M2 仅恢复之前明确同意的同一 workspace/context
权限，并重新校验服务端 policy；新权限不自动增加。FaceTime 采集暂停
状态也持久化，刷新后必须显式 `Resume assistant`，写入/呼叫确认照常保留。
接口为 `POST /api/tools/browser/status|remember|forget`，校验同源 Origin；
仅 HTTPS 或 SSH 下 localhost HTTP，服务仍不应作为无鉴权公网接口开放。

可以保持 Mac App 的“自动连接已授权的 H20 语音会话”开启；若已暂停，
点击“恢复／重试自动连接”。自动连接负责在浏览器授权后发现会话并连接
工具桥，不会替用户授权，也不会启动浏览器 Agent 对话。首次仍需在已连接的
`/agent` 页面粘贴五分钟内的一次性码并点击 `Authorize Mac echo`，
之后等待 Online，无需再点手动连接。未选择记住浏览器、信任失效或撤销时，
新浏览器会话仍需重新授权；有效信任的刷新/重新打开会自动恢复。
刷新重连修正：普通网页断开对工具桥使用正常关闭码 1000，Mac 自动发现
继续轮询；只有显式撤销使用 4411（Mac 会停止自动发现）。之前普通断开也
用了 4411，导致浏览器已连接但 Mac 不再连接，`demo_echo` 无法注册。
旧 App 已停止时点一次“恢复／重试自动连接”；无需重编译或更换设备 Token。
网页整体 Connected 只代表 Agent 连接，Mac tools 必须显示 Online 才有 echo。
网页顶部和左侧 Mac tools 区域均有独立状态标识：绿色 `Online` 显示当前
可用工具数量及名称；橙色 `Waiting for Mac` 表示已配对但工具尚未可用；
`Not paired`、`Unavailable`、`Offline` 分别区分未配对、服务不可用和
对话未连接。浏览器信任本身不算工具在线。
App 源码会在成功连接或配对码过期时清除其复制的码（仅当剪贴板仍是该码）。
用户本机 `pbpaste | wc -c` 先后报告 15 和 32；32 符合预期码长度，
但长度不能证明码正确、未过期或授权成功，不记录码内容。

2026-11-01 自动连接协议修正：原服务端发现响应的 `binding_revision`
只有 UUID，未满足 Mac 0.10.0 的 `32位小写十六进制.数字` 格式，
会显示“连接协议不匹配”。现等待授权和已授权响应均符合此格式，
受控 WS 查询使用同一 revision。无需重编译 Mac App；应用服务重载后
浏览器授权失效，须重新申请码并授权。启动器支持
`--reuse-private-dir` 保留原设备身份和审计文件，新日志仍写入独立运行目录。

2026-11-01 网页启动报 `Unknown event: 'agent.capture.ready'`：
这是新版 Next 网页已热更新、旧 Python 后端未重载的事件协议不一致，
不是 Mac 芯片或配对码错误。当前后端接受 `agent.capture.ready`、
`agent.capture.hold`、`agent.capture.resume`，即使 M2 policy 尚未启用。
修改这些事件后须同步重载本项目 8080/8081 应用服务，保留原私有目录；
无需重启 MiMo、TTS、SSH 或 Next。随后刷新 `/agent` 并重新连接，
Mac echo 需重新申请一次性码授权，不能复用旧浏览器会话授权。
握手成功只代表采集协议兼容，不代表 M2 工具已开放或真实 FaceTime 已验收。

2026-11-01 真实设备验收进度：服务日志证明 Mac 曾完成连接并动态注册
`demo_echo`，但连接随后断开，最近对话未调用工具。服务器主动测试在等待
Mac 重新连接的 25 秒门槛超时，未派发调用，不能计为工具执行成功。
测试时须保持 SSH 隧道、Mac App 自动连接及已授权浏览器会话运行；
页面曾显示 Online 不代表当前仍连接。

2026-11-01 13:36 UTC 后续实测通过：真实 Mac `demo_echo` 返回
`status=succeeded`、`data.text=duplex-mac-live-test`、`error=null`，
审计回执落盘，同轮 MiMo 续答并产生 12 个 TTS 音频块。产物位于
`workspace/logs/20261101T133646Z_real_mac_echo_664f755a`。
此测试使用临时协议客户端，并非浏览器 RealtimeSession；实际浏览器
SDK 语音调用、打断和迟到回执仍需统一验收。测试结束关闭临时会话，
用户浏览器继续使用时仍须为自己的会话授权。

HTTP 路由和 WebSocket 均经 8080 同源代理转发到 agentic backend。
设备 Token 不放在 URL、配对输入框或浏览器。正式部署需要可信 TLS 或受控加密隧道；
未加密 HTTP/WS 仅限隔离开发网络，不能保护传输中的 Token。
当前没有 `/api/tools/m2/*`、离线结果补交接口或主动 timer 事件。
Mac 客户端若只支持 M2、旧地址白名单或自动配对 UI，仍需原生侧适配/验收。

验收：桥接 5/5、实际固定版本 SDK/transport 4/4、服务端相关链路 3/3，
TypeScript 检查通过。SDK 测试使用模拟传输，服务端使用协议兼容 Mac 客户端
与模拟模型，两者分别验证；尚未在一个真实浏览器/MiMo/Mac 会话联合验收。

### 后续业务工具授权设计

1. H20 注册独立设备身份；Mac 私下导入客户端配置。旧版存 Keychain，
   检查到的 0.10.0 版使用权限受限的本机私有凭据文件，不应混淆版本。
2. 用户打开 Agent 会话，将浏览器与自己的 Mac 设备绑定。
3. 用户逐项选择工具权限；macOS 的系统权限和清单/目录选择在原生 App 完成。
4. Mac 主动查询 H20 绑定状态，再建立携带 Bearer header 的原生 WebSocket。
5. Mac 上报实际支持且获授权的 manifest，收到 ACK 后才能认定已协商。
6. 新适配层仅向 SDK/模型暴露有效能力；权限撤销或设备离线后禁止派发。

设备记忆和自动发现可以减少重复抄码，但不能自动增加授权。
每台 Mac 使用独立 `device_id`、凭据及自己的 `workspace_id/context_id`；
不能复制其他 Mac 的对象映射或正式数据库。

原生工具通道与浏览器音视频通道是两个连接。Mac 主动连 H20；
H20 不需要直接访问 Mac 的本机 MCP 端口。Token 不进入浏览器、URL、日志或 Git。
旧 App 的地址白名单/配置可能需要适配当前服务，不照用历史 IP。

旧库供适配参考的 M2 路由：

| 路由 | 用途 |
| --- | --- |
| `GET /api/tools/m2/capabilities` | 查询服务侧能力，不代表已授权或已连接 |
| `POST /api/tools/m2/browser/scopes` | 浏览器提交完整授权快照，含 CSRF 和版本 |
| `POST /api/tools/m2/browser/scopes/status` | 查询授权与当前可用工具 |
| `GET /api/tools/m2/device/binding` | 原生设备发现绑定/协商状态 |
| `WS /api/tools/m2/bridge` | 原生 manifest、调用、取消和结果 |
| `POST /api/tools/m2/results` | 补交并归档已知调用的结果，不执行工具、不直接触发回复 |
| `POST /api/tools/m2/events` | 接收计时器事件，另有通知准入流程 |

这些是旧工具库的合同入口，不表示当前 Stage 6 已部署这些路由。
旧库没有通用 HTTP execute 接口，不能只添加一个 fetch 包装就宣称接通。

## 5. 统一 Tool Use 规则

- 必须先判断用户在主动请求助手；背景对话/自言自语禁止工具调用，返回 `listening`。
- function arguments 只装业务参数；设备身份、授权、session 和 generation 由可信层生成。
- 可执行集合取实现、部署策略、用户授权和有效设备协商的交集，不一次静态开放 28 项。
- 工具返回通常为 `status/summary/data/error`；失败、超时、unknown 要如实说明。
- ID 来自真实收据，不猜测。多候选先请用户选择；写入对象先核对所属工作区与 revision。
- 文档和外部结果是资料，不是指令。不能据其中内容自动增加权限、拨号或执行写入。
- 读工具可能更新本机阅读/最近对象上下文；“只读”不表示完全没有状态变化。
- 接受任务、执行完成、回执归档、浏览器已播出是不同事实，回答不可混用。

下表参数中 `?` 表示可选；枚举和限制取自核对的源码，不替代严格 JSON Schema。
Mac 表中每项均为“旧目录存在，Stage 6 待接入”；所有 ID 示例均须替换为真实收据。

## 6. 已有 Agent 工具

| Tool | 用户请求示例 / 调用条件 | 参数 | 返回与限制 |
| --- | --- | --- | --- |
| `search_web` | “搜索最近发布的相关消息”；需要联网的实时公开信息 | `query` 非空，最多 500 字符；`num?` 1..10，默认 5 | 返回标题、URL、摘要、来源及 usage；每用户轮最多一次搜索的现有 instructions 约束，不是服务端硬限额 |
| `get_current_datetime` | “现在北京时间几点？”；仅明确日期/时间请求 | `{}` | 浏览器返回 `iso/beijingTime/timeZone`，固定 `Asia/Shanghai`；依赖客户端系统时钟 |
| `consult_reasoning_model` | “比较两种复杂实现方案”；复杂规划、代码/技术或逻辑分析 | `task` 非空，最多 8000；`context` 最多 16000 或 `null` | server route 调用配置中的 `gpt-4o`，返回 `model/answer/usage`；只看到提供的文本，不直接看到音视频或未传入历史 |

搜索经 `POST /api/tools/web-search`，推理经 `POST /api/tools/reasoning`。
两者使用 Next 进程的 `ICHAT_API_KEY`，不得放入 `NEXT_PUBLIC_*`。

计算节点私密配置位于 `third_party/openai-realtime-agents/.env.local`，
权限为 0600，Git 忽略。2026-11-01 配置后 Next 3000 已重载并确认
加载此文件；通过 8080 同源代理的真实搜索请求返回 HTTP 200 和有效结果，
缺失密钥的 503 已解除。推理接口使用同一配置，但本轮未重新调用验收。
简单问答直接由 MiMo 回答；推理工具不是联网搜索替代品。
缺少凭据应显式报错，不能伪造搜索或推理结果。

## 7. Mac 基础与上下文

| Tool | 用户请求示例 | 参数 | 结果及使用边界 |
| --- | --- | --- | --- |
| `demo_echo` | “调用回显，内容是苹果一二三” | `text`，最多 200 个 Unicode 码点，可为空 | 原样 `data.text`；无业务副作用，首个桥接验收工具 |
| `context_get` | “刚才打开的是哪个文档？” | `{}` | `context_id/revision/timezone/observed_at`，可选最近笔记、计时器、提醒、日程、呼叫、文档页码和媒体进度；缺省/空字段不是已知对象 |

`context_get` 的扩展字段依 profile 而异；不能借它猜测目录未声明的
`recent_place_id/recent_route_id`，也不保证本机媒体进度意味着已有媒体控制工具。

## 8. Mac 本地测试笔记

这四个工具操作 Mac 本地测试库，不写 Apple Notes，也不任意读写用户文件。
旧歌曲部署曾停用笔记目录；是否开放必须核对实际策略与协商。

| Tool | 用户请求示例 | 参数 | 结果及使用边界 |
| --- | --- | --- | --- |
| `note_create` | “建一条笔记，标题会议，内容讨论接口” | `title` 1..120；`body` 0..2000 | 返回 `note_id/title/body/revision/created_at/updated_at`；属于写入 |
| `note_get` | “读一下刚才那条笔记” | `note_id` | 返回完整笔记并设为最近笔记；使用已知工作区 ID |
| `note_append` | “给这条笔记加一行结论” | `note_id`、`text` 1..2000、整数 `expected_revision` >=1 | 追加后返回新 revision；冲突先重读，不能覆盖；整条正文最多 16000 UTF-8 字节 |
| `note_search` | “找标题或正文包含接口的笔记” | `query` 1..120；`limit?` 1..10，默认 5 | 返回 `notes` 的 ID、标题、excerpt、revision；字面子串检索，不是语义向量检索 |

## 9. Mac 本地计时器

| Tool | 用户请求示例 | 参数 | 结果及使用边界 |
| --- | --- | --- | --- |
| `timer_start` | “设一个三分钟泡茶倒计时” | `label` 1..120；`duration_seconds` 整数 1..86400 | 返回 `timer_id/due_at/timezone/state/remaining_seconds` 等；持久化本地测试计时器，不创建 Apple 提醒 |
| `timer_list` | “还有哪些倒计时？” | `state?` 为 all/running/finished/cancelled，默认 all；`limit?` 1..20，默认 10 | 返回 `timers` 与剩余秒数 |
| `timer_cancel` | “取消泡茶倒计时” | 已知 `timer_id` | 取消未完成对象；重复取消保持状态，已到期事件不能撤回 |

事件权限与上述三个工具分开：

| Scope | 用途 | 前置条件 |
| --- | --- | --- |
| `timer.events.receive` | 接收并持久归档 `timer.finished` | 设备、来源事件和接收权限有效，去重 |
| `timer.events.speak` | 在原语音会话空闲时播报到期 | receive 链路和独立 speak 授权有效；还须当前会话通知准入 |

创建成功不等于已接通到期播报。事件归档 ACK 不等于用户听到。
新 Stage 6 的主动事件调度尚未实现，不能把事件硬塞成普通 function result。

## 10. Mac 天气与出行

旧合同的免 Key 公共 provider 由 Mac 执行，H20 不读取 Mac 的业务密钥或正式库。
这是合同能力，不保证公共服务当前可达。

| Tool | 用户请求示例 | 参数 | 结果及使用边界 |
| --- | --- | --- | --- |
| `weather_get` | “深圳天气怎么样？” | `location` 1..80，明确城市或“经度,纬度”；`kind?` current/forecast，默认 current | 当前模型天气或最多三天预报，带来源、有效时间、`is_mock/is_stale`；不自动定位，不冒称实时观测 |
| `place_search` | “找深圳的某个公园” | `query` 和 `city` 均 1..80；`limit?` 1..5 | 返回候选 `place_id`、名称地址、WGS84 坐标；多候选先确认，城市仅查询条件，不保证行政边界过滤 |
| `route_plan` | “从选定地点步行到另一个地点” | `origin_place_id/destination_place_id`；`mode` driving/walking/cycling | ID 必须来自同 owner 的成功地点搜索收据；返回估计距离、耗时、最多 24 步；无实时交通、无公交、不启动导航 |

`search_web` 与 `weather_get` 是不同实现路径。后者未接入时不得伪装已在 Mac
查询天气。接入后需更新工具选择 instructions，避免同轮重复查询。

## 11. Apple 提醒事项

须在 Mac 授予系统权限并选定提醒清单，网页 scope 不代替系统权限。
这些工具不复用本地测试 timer，也没有本次确认的到期语音事件。

| Tool | 用户请求示例 | 参数 | 结果及使用边界 |
| --- | --- | --- | --- |
| `apple_reminder_create` | “加一个明天交报告的待办” | `title` 1..120；`notes?` 最多 2000；`due_at?` | 返回不透明 `reminder_id/revision/state/due_at` 等；可创建无到期时间待办，有时间须明确含时区 ISO8601 |
| `apple_reminder_list` | “看看未完成的待办” | `state?` pending/completed/all；`limit?` 1..20 | 返回已选清单内对象和 revision；不接受 Apple 内部 ID |
| `apple_reminder_update` | “把刚才那个待办标为完成” | `reminder_id/expected_revision`；可选 title、notes、due_at、state(pending/completed)、clear_due | 返回新 revision；`clear_due=true` 移除到期时间；冲突重查，不猜版本 |
| `apple_reminder_delete` | “删除刚才查到的待办” | `reminder_id/expected_revision` | 返回 `deleted=true` 和对象 ID；有副作用，按适配层确认策略执行 |

相对日期需明确用户时区并转成具体时间；不知道或存在歧义先问，不随意填默认日期。

## 12. Apple 日历

须在 Mac 授予日历权限并选定目标日历；首版只支持单次可编辑日程。

| Tool | 用户请求示例 | 参数 | 结果及使用边界 |
| --- | --- | --- | --- |
| `apple_event_create` | “安排指定时间的一小时会议” | `title/start_at/end_at/timezone`；`location?/notes?` | 起止 ISO8601 含时区，timezone 为 IANA；返回 `event_id/revision` 等；单次最长 7 天，不创建邀请或重复规则 |
| `apple_event_list` | “查看下周的日程” | `start_at/end_at`；`limit?` 1..20 | 查询范围最多 31 天，返回 ID、revision 和可编辑信息 |
| `apple_event_update` | “把这次会议改到明确的新时间” | `event_id/expected_revision`；可选 title、location、notes、start_at/end_at/timezone | 时间变更必须同时给三个时间字段；不修改重复、全天或邀请对象 |
| `apple_event_delete` | “删除刚才查到的这次会议” | `event_id/expected_revision` | 删除已观察的可编辑单次对象，返回 `deleted=true`；不删除重复、全天或邀请对象 |

ID/revision 属于不透明业务收据，不是模型生成的字符串。创建/修改未知结果
不得换新 invocation 自动重做，以免重复写入系统日历。

## 13. Mac 授权文档阅读

用户先在原生 App 授权目录。只读取 PDF/TXT/MD/Markdown，不上传路径或书签。

| Tool | 用户请求示例 | 参数 | 结果及使用边界 |
| --- | --- | --- | --- |
| `document_folders` | “有哪些允许读取的文档目录？” | `{}` | 返回 `folder_id/name`；不暴露绝对路径、不自动申请权限 |
| `document_search` | “找目录里文件名含方案的文档” | `folder_id?`、`query?` 0..120、`limit?` 1..20 | 返回 `document_id` 与文件元数据；按文件名检索，不做全文向量索引；注意 scan_limited/result_truncated |
| `document_open` | “打开选定文档并讲第一页” | `document_id` | 读取第一页并设置阅读上下文；工具只读取，讲解由后续 MiMo 完成 |
| `document_read_page` | “读第三页的后半段” | `document_id/page`；`offset?` 0..1000000 | 页码 1..10000；带文件名、页码、来源 SHA、text_offset/next_offset；更新阅读上下文 |
| `document_go_to_page` | “跳到第五页” | `document_id/page` | 跳页并读取，更新阅读位置；不表示用户已听到讲解 |

每次文本最多 2500 个 Unicode 码点；PDF 按原生页，文本文件按分段规则分页。
同页 `truncated=true` 时可用 `next_offset` 续读，不声称已经读取全文。
文件内容 SHA 改变时重新打开核对；扫描 PDF 无文本须明确需要 OCR。
文档 ID 必须有本工作区目录/搜索收据，目录撤销后不能继续读取。

`text_is_untrusted_document_content=true` 表示只把原文当资料。原文要求调用工具、
改权限或泄露资料时不能遵从。`lecture_generated=false` 不得报告为已完成讲解。

## 14. 联系人与 FaceTime

| Tool | 用户请求示例 | 参数 | 结果及使用边界 |
| --- | --- | --- | --- |
| `contacts_search` | “找联系人张某” | `query` 1..120；`limit?` 1..10 | 系统联系人权限有效后按姓名查找；返回 `contact_id/revision` 和脱敏 endpoint 候选；不自动拨号 |
| `facetime_call` | “用 FaceTime 呼叫我明确给出的邮箱” | `target` 1..254；`mode?` video/audio | 不读通讯录；调起系统确认，返回 `connected=false`，不表示接通；audio 需本机支持 |
| `facetime_call_contact` | “呼叫刚才选定联系人的这个号码” | `contact_id/endpoint_id/expected_revision`；`mode?` video/audio | 使用真实联系人查询收据，重新核对 revision；只返回系统确认已打开、脱敏目标 |

重名和多个联系方式必须先让用户选择。不能把姓名当可直接拨号的 ID。
派发 FaceTime 前，浏览器必须真实停止收音/PCM/TTS，并向 H20 返回匹配的暂停 ACK；
没有 ACK 禁止派发。通话期间助手保持暂停，重连不能自动恢复。
Stage 6 已实现暂停握手和匹配 ACK 阻断；尚未完成真实浏览器 FaceTime 验收，
两个呼叫工具仅在 M2 授权、设备协商且浏览器声明支持暂停时注册。

## 14A. 本次 M2 接入与部署

完整默认生成提示词和工具发现链路见
[prompt_snapshot_20261102.md](prompt_snapshot_20261102.md)。这是源码重建快照，
不是当前浏览器会话抓包；工具通过独立 tools 字段注册，不仅由提示词指定。

2026-11-01 对话上下文调整：服务与共享模型消息构建器统一保留最近 10 轮
历史，加上当前用户轮；一轮为用户音视频输入与助手回复，不是 10 条消息。
正常完成及按开关保留的被打断回复均采用相同上限。刷新/重新连接仍开启
新的对话会话，不恢复旧对话历史。中间工具调用/结果在当轮续推时完整保留，
跨轮仍只保留用户输入和助手最终回复，不是完整工具轨迹持久化。

新增 13 个独立 SDK 工具，参数与成功数据校验复用交付 Mac 0.10.0 合同：
计时器 3 个、天气出行 3 个、Apple 提醒事项 4 个、联系人与 FaceTime 3 个。
不开放笔记、日历、文档或 `context_get`。原 v1 echo 保持兼容。
新适配器为 `workspace/experiments/20261025_mimo_tts_integration/mac_m2.py`；
不导入旧 Qwen Agent。服务端默认关闭 M2，必须提供独立私密 policy。

### Mac 端

保持 SSH 8080 转发。在自己的 Mac 源码副本内更新 M2 的硬编码 WS 地址，
不是修改服务器上的原始参考库：

```bash
scp -P 443 root@28.29.218.56:/mnt/geminihzceph/user_whynotzhliu/Omni/duplex-omni/workspace/experiments/20261025_mimo_tts_integration/patch_mac_m2_endpoints.py ~/Downloads/
cd ~/Downloads/DuplexToolHost-duplex-mimo
python3 ~/Downloads/patch_mac_m2_endpoints.py .
./Scripts/build-app.sh
```

先退出旧 App 再打开 `dist/DuplexToolHost.app`，保留本机数据和设备配置。
若“恢复 M2”提示 `bridge_http_502`，先检查是否仍运行旧地址的构建。
2026-11-01 本次日志中，Mac 的 `/api/tools/m2/device/binding` 查询返回 200，
但没有观察到 `/api/tools/m2/bridge` 请求；这不等于工具已经在线。
原版 `M2Protocol.swift` 的连接地址和导入配置校验均单独写死为
`ws://29.213.201.220:8080/api/tools/m2/bridge`，只修补 H20 echo 不会改变它。
上面的补丁会同时修改两处；执行后可以在 Mac 核对：

```bash
grep -n 'api/tools/m2/bridge' Sources/HostRuntime/M2Protocol.swift
```

两处均应使用 `ws://127.0.0.1:8080/api/tools/m2/bridge`。重新构建后，
用 Cmd+Q 完全退出旧 App，再执行 `open dist/DuplexToolHost.app`，
保持 SSH 转发和网页手动连接，点击“恢复 M2”。
旧地址是当前优先排查项，尚未读取用户 Mac 的源码/运行构建确认根因。
如果仍为 502，提供上述地址检查输出和新错误；不要发送 Token 或私密 JSON。
在设置中选择 M2 模式、开启桌面及联系人远端 profile，确认正式工作区：
`workspace_id` 为自己的工作区别名，`context_id` 必须是本机现有正式上下文 ID。
不要任意生成 context ID。Apple 提醒事项需原生 App 授予权限并选定清单；
联系人需系统权限；FaceTime 需本机系统支持。先配对设备后再切换 M2。

### 服务器端

取得 Mac 确认的两个 ID 后，在计算节点运行（占位符须替换）：

```bash
source /mnt/geminihzceph/user_whynotzhliu/my_envs/env.sh
conda activate omni
python -B workspace/experiments/20261025_mimo_tts_integration/prepare_mac_m2.py \
  --device-id duplex-mimo-mac-m5 \
  --workspace-id ACTUAL_WORKSPACE_ID --context-id ACTUAL_CONTEXT_ID \
  --output /tmp/duplex-mac-m2-policy.json
```

脚本只新建权限 0600 的 policy，不改设备 Token。已有启动器增加
`--m2-policy-file /tmp/duplex-mac-m2-policy.json`，保留
`--reuse-private-dir` 原凭据/审计，并使用新的独立运行日志目录。
只能在核实服务归属后重载应用；不要重启 MiMo/TTS/SSH。
用户当前工作区别名为 `mac-main-demo`（也是 Mac App 默认值）。在 M2
设置中点击“确认使用此正式工作区”后，它才是已确认映射的 workspace_id；
还须读取同一页面“上下文：”后的完整 context_id，服务器不能凭别名推导。
用户已提供正式 `context_id=A010280A-41D2-4AD7-8C80-93458433280C`。
实际 policy 位于 `/tmp/duplex-mac-m2-policy-20261101-actual.json`（0600），
仅用于 `duplex-mimo-mac-m5` 和此工作区/上下文。应用按此配置启用 M2；
浏览器必须另行勾选授权，Mac 必须完成地址修补、正式映射和 profile opt-in。
`/tmp` 配置不是持久化部署，节点重建后需按记录重新生成并检查，不复制 Token。

### 浏览器授权与行为

刷新 `/agent`，连接对话并完成设备配对；点击 `Mac permissions`，
勾选工具组及独立的 `Timer notifications`，点击 `Authorize selected tools`。
模型可用范围是 policy、网页 grant、Mac manifest 的交集。
写入/取消/删除/拨号会显示精确参数的 Confirm/Cancel 窗口，拒绝不派发。
FaceTime 确认后停止麦克风、摄像头和播放，返回关联暂停 ACK 后才派发。
系统确认已打开不等于通话接通；结束后用户点击 `Resume assistant` 恢复，
不会自动恢复摄像头。未知写结果不得自动重试。

`timer.finished` 事件校验原始 timer_start 成功回执及工作区，持久化后 ACK，
重复事件不重复通知。页面活动区显示到期事件；当前 ACK 为 suppressed，
意思是本次不主动语音播报，不是计时器执行失败。
离线 `/api/tools/m2/results` 仅归档旧回执，不重新执行、不续接旧模型轮次。

验证：v2 桥接 5 个、服务端 5 个、实际 SDK 使用模拟传输 5 个相关用例通过。
真实 Apple 写入、天气公共服务、联系人/FaceTime 和实际 Mac M2 尚待验收。

### 2026-11-01 真实 30 秒倒计时验收

本次用户网页语音触发 `timer_start`，参数为 30 秒、名称“30秒倒计时”。
Mac 返回 `status=succeeded`、`state=running`，计时器 ID 为
`A5C7A74A-89BF-48BD-873B-DA44912C34D6`。回执记录创建时间为
23:56:06.815 +08:00、截止时间为 23:56:36.815 +08:00；
Mac 在 23:56:37.014 +08:00 生成对应 `timer.finished` 事件，服务器已持久化。
这证明本次真实 Mac 创建及到期事件链路通过，不代表全部 13 个工具已验收。

网页 Confirm/Cancel 弹窗是写操作确认，不是执行成功凭证。
此工具创建的是 DuplexToolHost 自己持久化的本地倒计时，不是 macOS“时钟”
App 的计时器。按交付源码，Mac 设置的“本地笔记与倒计时”页显示名称、
剩余秒数、到期/取消状态；系统通知默认关闭，需用户点击“允许系统通知”。
已授权并成功排定后才可能出现带声音的系统通知，仍受系统通知/专注模式影响。
本次未直接检查用户 Mac 的画面或通知授权，不能宣称已弹出系统通知。
App 退出后不会继续运行本地检查循环；已排定的系统通知仍可提醒，
下次启动按持久化截止时间恢复到期状态。当前远端 ACK 为 `suppressed`，
表示不主动语音播报，不表示倒计时未执行。

### 通讯录 permission_required

2026-11-01 用户查询联系人时收到 `permission_required`。日志对应
`contacts_search`，这不是断线，也不是联系人不存在：Mac 尚未允许通讯录读取。
打开 DuplexToolHost 设置的 **FaceTime** 标签，点击 **授权通讯录**，
在系统弹窗允许后点击 **刷新权限状态**，确认显示“通讯录已授权”再查询。
如果以前拒绝过，需在 macOS 系统设置的隐私与安全性中允许 DuplexToolHost
访问通讯录。按当前原生实现，只有 `.authorized` 被接受；有限访问状态
不被当作完整授权。工具调用本身只检查权限，不主动申请。
网页 `Mac permissions`、M2 profile opt-in 与系统通讯录权限是不同层级，
均需满足；不要为此开放无关日历或文档目录。权限修复后的真实查询仍待验收。

### M2 绑定冲突与断线协议错误

`m2_binding_conflict` 表示同一设备已有其他未关闭的 M2 会话。活跃会话不能
被新网页自动接管。2026-11-02 用户完全退出 Chrome 后仍冲突，并出现
`bridge_protocol_error`；服务端确认 M2 状态通知向关闭中的网页写入时抛异常。
修复使断线通知不再造成原生桥接异常，并在重新授权时清理已失去对应 echo
设备绑定的孤立 M2 会话；有效旧会话仍拒绝接管。协议拒绝现在记录不含
参数/凭据的具体错误码，其他协议问题仍须依据新日志定位。
重载后网页手动 Connect，确认工具授权，再在 Mac 恢复 M2；
不删除私密 JSON、工作区或系统权限，不自动开始对话。
浏览器自动化环境未找到 Chromium，本轮没有截图验收。

## 15. 服务端歌曲扩展

`song_start` 不属于 28 个 Mac 工具，运行在旧部署树的 H20 歌曲桥接服务。
Mac 不需要为它增加工具执行器，但 Stage 6 需独立适配任务、音频、播放和取消。

| Tool | 用户请求示例 | 参数 | 结果及使用边界 |
| --- | --- | --- | --- |
| `song_start` | “创作并唱一小段原创歌” | `lyrics` 1..6000；`description` 最多 500，必填但可空 | 提交约 30 秒原创歌曲，返回 `task_id/state/duration_seconds`；任务接受不是已播放或已完成 |

旧实现要求本会话明确允许唱歌且部署启用。同轮最多一首。
歌词按 `[verse]` / `[chorus]` 独占首行组织，段间空行；校验还接受 `[bridge]`。
标签和歌词只进参数，不由普通 TTS 念出；工具接受后简短确认，再交歌曲播放器。
“会不会唱歌”、只写歌词或讨论歌曲不触发。该工具不承诺现成歌曲原曲/准确翻唱。

旧桥接通过内部 `/v1/songs` 提交任务，消费事件与 WAV chunks，使用歌曲专属
播放事件/stream，而非把任务 ID 当普通 TTS 音频。旧 PCM 为 48 kHz 双声道，
与当前对话 TTS 的 24 kHz 输出不同，不能直接混用采样率。
未知提交不自动重发；打断和关闭应取消原任务并丢弃旧轮音频。
源码中的 `/api/song/config`、`/api/song/stream` 不是当前 Stage 6 已部署路由。

## 16. 典型多工具流程

以下是接入后应验收的流程示意，不是当前已可运行的承诺：

```text
读取文档：document_folders -> document_search -> 用户选择
          -> document_open -> document_read_page/next_offset -> MiMo 讲解

修改提醒：apple_reminder_list -> 用户确认对象
          -> apple_reminder_update(真实 ID + revision) -> 回执后确认

规划路线：place_search(起点) + place_search(终点) -> 用户选择
          -> route_plan(同 owner 的两个真实 place_id) -> 说明估计值

呼叫联系人：contacts_search -> 用户选择 contact/endpoint
            -> 浏览器停止收音并 ACK -> facetime_call_contact
            -> 仅说明已打开系统确认，助手继续暂停
```

## 17. 打断、幂等与验收

桥接调用记录包含可信 device/workspace/context/session、generation、
authorization_revision、call_id 和 invocation_id。先持久化再派发。
用户插话、reset、disconnect 或权限撤销要使旧调用失效，并尽力发送取消。
迟到结果保留原身份，仅按规则归档，不改标为新轮、不污染新 history 或播放。
取消不是回滚；超时不是“确认没有发生写入”。

首个验收为真实 SDK `demo_echo` 闭环，再扩展只读工具，写入/通知/FaceTime/歌曲
各自验收。单模块修改最多选择 5 个相关用例，优先端到端：

1. SDK -> bridge -> 执行收据 -> 同轮最终回答。
2. 无设备/无授权/撤销权限时禁止派发。
3. 打断后旧结果不会进入新轮。
4. 超时/unknown 如实失败、不自动重复执行。
5. 重复收据幂等，错误 owner/身份被拒绝。

协议 test peer 通过后，还需真实 Mac 日志、服务端接受结果和浏览器回答/播放证据。
不能用历史测试总数、健康检查、mock 或模型口头确认代替实际验收。

## 18. 维护约定与源码入口

此文为长期中文入口；阶段快照保留历史。每次新增或修改工具，同步维护：

- 名称、参数/结果、使用条件、典型请求、执行位置和风险。
- 授权 scope、系统权限、前置收据及对象版本要求。
- 目录存在/适配完成/部署/真实验收状态及证据日期。
- 失败、超时、取消、幂等、隐私和播报限制。
- SDK registry/manifest、桥接合同及实际验证记录的一致性。

改变能力不能只改文档；状态只随相应验收门槛更新。
本次文档核对不更新工具可用状态，不自动提交/推送或重启服务。

| 来源 | 位置 |
| --- | --- |
| 当前 Agent 工具实现 | `third_party/openai-realtime-agents/src/app/agentConfigs/duplexMimo/index.ts` |
| 当前工具启用配置 | 同目录 `manifest.json` |
| 搜索/推理服务逻辑 | `third_party/openai-realtime-agents/src/app/api/tools/` |
| SDK 浏览器会话 | `third_party/openai-realtime-agents/src/app/duplex-mimo/page.tsx` |
| MiMo 原生工具循环 | `workspace/experiments/20261025_mimo_tts_integration/agent_runtime.py` |
| Mac 累计目录 | 外部库 `webapp/fc_contacts_catalog.json`，含此前 9/12/26 工具 |
| 旧工具桥接 | 外部库 `webapp/fc_m2_runtime.py`、`fc_m2_routes.py` |
| Mac 客户端说明 | 外部库 `function_calling/H20_ECHO_INTEGRATION_ZH.md`、`private_mac_clients/README_ZH.md` |
| 歌曲实现 | 外部库 `deploy/song_bridge_19755/voice-root/.../webapp/fc_song.py` |

上表“外部库”根目录为 `/mnt/geminihzceph/user_whynotzhliu/Omni/h20_duplex_fc_dev`；
常规 `webapp` 位于 `we_duplex_demo/L20_mac_demo_20260915/SSL-PVAD/webapp`。
精确 schema 以核对的源码及协商 profile 为准，本文是使用指南，不是 wire schema。
