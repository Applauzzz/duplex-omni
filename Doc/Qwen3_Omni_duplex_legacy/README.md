# Qwen3-Omni Streaming Duplex — 交接文档

本目录是 **Qwen3-Omni 全双工语音对话（duplex）** 这一轮开发/调试的完整交接资料。项目代码在
`/mnt/geminihzceph/user_whynotzhliu/Omni`，模型为 `Qwen3-Omni-30B-A3B-Instruct`，框架是
`vllm-omni`（8 卡 H20，三阶段 thinker / talker / code2wav）。

这一轮的工作已经结束，后续开发转向新的方案（见"后续方向"）。以下内容按"接手后需要知道什么"组织，
每篇文档都可以单独阅读。

## 仓库整合说明（2026-10-22）

本项目现在由 `duplex-omni` 与两个 fork 组成。项目根的 `vllm-omni/`、`vllm-src/` 是固定提交的 Git submodule；阶段一与阶段二源码改动保存在 fork 的 `duplex-stage2` 分支。开发环境须安装这些子仓库的源码，不能假定原工作区的 editable 安装会自动切换。

本目录其余内容是阶段一历史交接记录，原机器路径、未提交状态及验收结论保留其当时含义。阶段二入口为 `../stage2-mimo-qwen-omni/README.md`；部署时以该文档的当前仓库说明为准。

## 文档索引

| 文档 | 内容 | 什么时候看 |
|---|---|---|
| `01_architecture.md` | 系统分层、三阶段流水线、duplex 引擎的核心概念与关键代码位置 | 第一次接手，想了解整体结构 |
| `02_running.md` | 起停服务、端口、给同事的访问方式、日志位置、常见故障 | 要起服务或排查服务起不来 |
| `03_vad_config.md` | VAD 参数怎么从 deploy config 暴露出来、三层优先级 | 要调整 VAD 灵敏度/静音判定 |
| `04_known_issues.md` | 已修的问题、遗留问题（以及为什么没修） | 想知道现状的边界和坑 |
| `05_debug_barge_in_garbled_audio.md` | 连续打断后 talker 乱码的完整排查报告 | 复现或继续排查乱码/重答问题 |
| `06_change_log.md` | 这一轮所有代码改动的清单（相对 upstream） | review 代码、决定哪些改动要带回主线 |

在 `Doc/` 目录下还有这一轮之前就存在的背景资料：

- `qwen3_omni_duplex_architecture.md` — vllm-omni duplex 的架构说明（upstream 视角）
- `qwen3_omni_service_architecture.md` — 服务化相关
- `qwen3_omni_service_config.md` — 服务配置说明
- `debug_20261014_barge_in_garbled_audio.md` — 本次 debug 的原始报告（`05` 篇是它的整理版）

## 一句话现状

**可以正常跑**：起服务后，页面能进行 VAD 自动断句的全双工语音对话，支持打断，支持通过 deploy
config 调整 VAD 参数。

**两个已知行为问题**（都不是崩溃，详见 `04_known_issues.md`）：

1. 打断后重答上一轮 —— 被打断且没播完的回答，一个字都不会记入历史，模型以为那个问题没答过。
   **未修**，需要先定策略。
2. 连续打断后 talker 输出乱码 —— **已修**（去掉 prompt 里的空 assistant 回复）。修法带来上面第 1 点
   的副作用，属于同一个根因的两面。

## 后续方向

下一步开发转向 `Doc/mimo_qwen3_omni_talker_plan_a.md` 描述的 talker 方案（streaming talker，
文本与音频对齐）。本目录记录的是改方案之前的基线状态和结论，包括：

- 哪些问题是 Qwen3-Omni 现有 talker 的固有局限（文本与音频不对齐），新方案可以从根上解决；
- 哪些是引擎/duplex 层的实现问题，新方案仍需面对。

特别是 `04_known_issues.md` 里的"打断后重答"和 `05` 篇里关于"文字与音频不对齐导致无法判断用户听到了
多少"的分析，对评估新方案有直接参考价值。

## 交接 checklist

接手的人建议按这个顺序过一遍：

1. 读 `01_architecture.md`，确认能画出数据流。
2. 按 `02_running.md` 起一次服务，确认端到端可用（大约 6~7 分钟启动）。
3. 按 `04_known_issues.md` 验证两个已知行为问题是否仍然存在。
4. 决定是否要继续修"打断后重答"，需要先看 `05` 篇第 6 节的设计权衡。
5. `06_change_log.md` 里的改动都在工作区未提交，需要 review 后再决定要不要带回主线。
