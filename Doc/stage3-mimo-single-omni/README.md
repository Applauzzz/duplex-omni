# Stage 3: MiMo 单核心双工 Omni

建立时间：2026-10-25。2026-10-26 阶段更新：MiMo + Qwen3-TTS 基础集成已完成，
复用原实时前端、Silero VAD 和会话/播放账本；更广的质量、语义和性能验收仍开放。
用户已授权提交推送当前成果并停止本项目服务，运行状态见最新阶段快照。

## 目标与边界

MiMo-V2.6-Flash-RL 是唯一的多模态理解与回复生成模型；Qwen3-TTS CustomVoice
只负责把回复正文转成语音。移除目标链路对 Qwen3-Omni thinker、talker、code2wav
及其 prefill/embedding 的依赖，不修改模型权重。

这里的“单核心”不等于只有一个模型进程，也不是 MiMo 原生连续音频 KV 双工。
首版采用并行收音、按轮理解、流式正文、分段流式合成和可打断播放。
原生增量音频模型推理不在首版验收范围内。

## 文档入口

| 文件 | 内容 |
|------|------|
| [checkpoint_20261026.md](checkpoint_20261026.md) | 当前基础集成成果、聚焦测试、正常停服和恢复方式 |
| [checkpoint_20261026.json](checkpoint_20261026.json) | 版本、配置/代码摘要、测试与验收边界清单 |
| [architecture.md](architecture.md) | 已核实架构、依赖、复用边界与风险 |
| [implementation_plan.md](implementation_plan.md) | 六阶段方案、产物和独立验收门槛 |
| [decisions.md](decisions.md) | 技术决策、依据及待验证条件 |
| [validation.md](validation.md) | 验证矩阵、实验保护和失败记录规范 |
| [phase2_gpu_20261025.md](phase2_gpu_20261025.md) | GPU 基线、有效首音频、取消证据及剩余验收项 |
| [preview_20261025.md](preview_20261025.md) | 独立 TTS 试听入口、进程归属、启动失败与验证边界 |
| [restart_20261025_1440.md](restart_20261025_1440.md) | 释放 GPU 后的 MiMo/TTS 重启、当前进程与最小验证 |
| [direct_access_20261025_1512.md](direct_access_20261025_1512.md) | 恢复 Mac 直连策略、当前服务器 IP/7865 入口及验证 |
| [allowed_port_20261025_1536.md](allowed_port_20261025_1536.md) | 7865 网关 502 后按旧文档使用 8080，当前入口与 Mac 验证边界 |
| [mimo_tts_design_20261025.md](mimo_tts_design_20261025.md) | MiMo 到独立 TTS 的手动轮次方案与验收边界 |
| [mimo_tts_live_20261025.md](mimo_tts_live_20261025.md) | 已接通 MiMo+TTS、当前 8080 对话入口与 GPU 验证 |
| [realtime_vad_design_20261025.md](realtime_vad_design_20261025.md) | 复用原实时前端、VAD、runner 和播放 ACK 的接入方案 |
| [realtime_vad_live_20261025.md](realtime_vad_live_20261025.md) | MiMo 语音输入、独立 TTS、自动 VAD 与打断恢复验证及当前运行记录 |
| [voice_consistency_20261026.md](voice_consistency_20261026.md) | 每轮音色变化的源码诊断、候选原因与待补 GPU 试听门槛 |

任务状态以 Git 仓库中的以下文件为准：

```text
/mnt/geminihzceph/user_whynotzhliu/Omni/duplex-omni/
  .planning/2026-10-25-mimo-single-omni-duplex/
    task_plan.md
    findings.md
    progress.md
```

本目录是可读知识库，不是第二套独立任务状态。父仓库 `AGENTS.md` 提供新会话恢复入口。
主仓库和两个子模块均由 Git 维护；本轮未更新 gitlink、提交或推送。

## 当前结论

- 旧 MiMo-Qwen 级联不是 MiMo 单核心：Qwen thinker 仍提供真实多模态 prefill。
- 当前子库已有 Qwen3-TTS talker/code2wav、HTTP PCM、文本切分和相关测试，优先复用。
- TTS 默认缓冲全文到 `input.done`；句子/子句模式会开启独立合成请求。
  首版明确采用分段合成，不能声称是同一 TTS KV 的逐 token 输入。
- Silero 提供声学 VAD；现有短附和白名单不是学习型语义 VAD。
- 旧链路部分播放历史可能被记为空，必须验证 ACK、文本分段与取消后的上下文。
- 默认 `liu` 环境缺少推理栈；历史 `omni` 环境的源码导入指向仓库外旧目录。
  新树的 GPU 运行、模型加载和全量 CPU 回归仍待验证。

## 下一步

2026-10-26 更新：按用户要求归档并推送现阶段成果。本项目 MiMo、TTS、UI
已正常停止，八张 H20 显存归零，8080/8090/8093 无监听。17 项聚焦测试及
Node 前端状态检查通过；本次被中断的 GPU 回放没有完成结果，不计入通过。
后续继续音色一致性对照、实际浏览器麦克风/播放、严格 stage idle、
声学误报、语义策略及性能验收。恢复前重新检查 GPU、端口和源码导入根；
不要把下面历史入口或 PID 当成当前运行状态。

2026-10-25 17:37Z 更新：恢复原 realtime_web 和真实 Silero/server_vad，
使用实际会话 runner/播放 ACK，不再以手动录音页作为目标入口。
六项会话/连接回归及真实 GPU 自动语音、历史、打断后回答新问题通过。
8080 UI 已切换并再次通过真实GPU回放，模型保持运行，测试端口已退出；
最终运行记录见 realtime_vad_live 文档。
语义VAD、浏览器麦克风/真实播放、严格stage idle等独立门槛仍开放。
以下段落为保留的历史状态，不作为新会话执行顺序。

2026-10-25 16:16Z 最新能力：用户确认8080试听可达后，已接通MiMo正文流到
Qwen3-TTS，首页现为文字/手动录音提交的对话页，旧试听保留在 `/tts`。
文字、原始WAV问答、历史追问、取消恢复的GPU测试通过；详见live文档。
这不是VAD自动判停或持续收音双工，浏览器麦克风及真实播放仍待用户体验。
Phase2严格idle/混合发音、Phase3旧runner组合证明等门槛保持开放。
此前“未联调”结论是历史状态，以此新增记录为准。

2026-10-25 15:36Z 最新入口：用户实际访问7865遇到IT网关502，按
`Doc/Qwen3_Omni_duplex_legacy/02_running.md` 的部署约定改用8080。
当前试听页为 `http://28.29.210.210:8080/`，旧7865入口已退出。
服务器侧页面/健康/GPU合成通过，但Mac可达性尚未验收；不能用本机自检
代替远端验证。请用新Chrome profile和匹配8080的origin参数。
此前7865记录保留为失败诊断历史，以新增8080入口文档为当前运行记录。

2026-10-25 15:12Z 入口修正：按用户历史 Mac 直连策略，试听页现监听
`http://28.29.210.210:7865/`，不再使用未配置转发的 Mac localhost。
旧 IP `28.29.210.139` 不是本次服务器接口；模型 API 仍限回环8090/8093。
页面和 GPU 合成已通过服务器 IP 检查，Mac 可达性仍待用户确认。
这是 TTS 试听页，不是 MiMo 对话/VAD/双工整合；详见新增入口文档。

2026-10-25 GPU 实测更新：MiMo TP4 原始音频/正文 SSE 与独立 CustomVoice
流式 PCM 已跑通，详见 Phase 2 报告。混合专有名词内容和真实 stage idle
门槛仍未关闭，Phase 2 保持 in_progress；尚未接 VAD 或 MiMo 到 TTS 适配器。
下面的“尚未验证”结论与初始 CPU 顺序属于 Phase 1 历史记录，以此更新为准。

2026-10-25 Phase 2 启动更新：按用户要求直接启动隔离 GPU 服务，
CPU 基线不作为前置门槛。初始化使用用户 env.sh，随后激活 omni。
以下保留最初规划顺序，不再作为当前执行顺序。

进入 Phase 2：先确认隔离环境及当前源码导入路径，运行相关 CPU 基线，
再独立验证本地 CustomVoice 的中文/英文 PCM 输出、首包、结束与取消。
只有这些门槛通过，才接 MiMo 的正文流。

## 知识库维护

Git 内本目录为规范来源；按阶段向用户指定的
`/mnt/geminihzceph/user_whynotzhliu/Omni/Doc/stage3-mimo-single-omni/`
发布新增文档。外部目录不在本仓库 Git 范围，也不在默认可写范围，
必须申请写权限；后续快照使用新版本目录或新增文件，不能静默覆盖本次快照。
原 Qwen 阶段和 stage2 文档保留其历史时间点，不把旧部署路径、测试数字和命令当成当前事实。
