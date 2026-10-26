# 验证与实验记录

建立时间：2026-10-25。实际执行日志与阶段状态保存在选定计划的 `progress.md`。
此文件规定后续验证门槛，不把尚未运行的测试记为通过。

## 当前会话验证范围

- 已核对 Git/子库状态、源码入口、模型 JSON 和两套 Python 环境的模块路径/版本。
- 未启动 GPU 服务、未安装依赖、未运行完整 fork pytest、未更新模型或环境。
- 文档修改执行路径/链接和 Git whitespace 检查。
- 可选 stdlib splitter smoke 只验证文本分段模块，不代表 package 导入、
  GPU 合成、完整 CPU suite 或端到端模型链路通过。

## 必需测试族

路径相对 `vllm-omni/`；先确认测试环境导入当前子模块，不使用旧实验 pyvendor 偷换源码。

| 改动面 | 当前测试入口/新增要求 |
|--------|----------------------|
| 会话/取消/ACK | tests/engine/duplex/test_session_runner.py、test_engine_session.py、test_overlap_policy.py、test_session_manager.py |
| 声学 VAD | tests/engine/duplex/test_vad_backend.py、test_duplex_deploy_config.py；新 reducer/假时钟回放 |
| 分段 | tests/entrypoints/openai_api/test_speech_text_splitter.py；新正文 span/尾部 flush/无标点/预算测试 |
| TTS serving | tests/entrypoints/openai_api/test_serving_speech_stream.py；新 HTTP 取消/PCM 拆包/错误终态 |
| TTS chunk | tests/model_executor/stage_input_processors/test_qwen3_tts_async_chunk.py |
| CustomVoice | tests/e2e/online_serving/test_qwen3_tts_customvoice.py；独立固定文本听测 |
| 旧级联回归 | tests/model_executor/models/qwen3_omni/test_mimo_bridge.py、test_duplex_plugin.py、tests/engine/test_duplex_orchestrator.py |
| 新 MiMo 入口 | 父仓库新增 mock SSE/HTTP/协议回放测试；原始音频与内容端到端 |

测试包 conftest 会加载 vLLM/runtime fixtures。当前 `liu` 缺完整栈，
`omni` 缺 pytest 系列且指向旧树；不能通过跳过这些依赖就宣称全套回归通过。
任何 skip、fixture 缺失、收集失败、CUDA ABI 错误分别记录。

## 回放矩阵

| 类别 | 场景与断言 |
|------|------------|
| 正文 | 中文、英文、数字、小数、缩写、中英混合、分割 UTF-8、reasoning、空正文 |
| 输出 | 首包、长句、句间衔接、最终 flush、非空有效 PCM、无漏读/重复/提前结束 |
| 假双工排除 | 生成和播放期间持续接收输入，不等待整段回复才开启麦克风处理 |
| 状态机 | 短静音、长静音、句中停顿、短附和、噪声、真实抢话、回声 |
| 取消 | SSE 首字前、TTS 首包前、播放中、SSE 完成而 TTS 未完、尾包竞争、重复 cancel |
| 隔离 | 迟到旧文本/音频/ACK/语义决定，立即新轮、新会话、reset、resume、关闭 |
| 历史 | 用户实际听完的完整段被提交，未听段不提交，连续打断不制造空 assistant 模仿 |
| 故障 | HTTP 非 200、SSE 断流/缺 DONE、TTS 中断/无音频、超时、慢客户端、队列上限 |
| 后端 | 取消后 MiMo 与 TTS 实际请求停止，GPU 无残留请求，新轮可运行 |

正文/音频内容需听测或独立 ASR。MiMo 回转写仅辅助，不能作为唯一正确性证据。

## 不覆盖实验

建议布局：

```text
workspace/experiments/<日期>_mimo_single_omni/   # 可跟踪脚本/fixtures/配置
workspace/logs/<UTC时间>_mimo_single_<阶段>_<唯一ID>/
  manifest.json
  events.jsonl
  service_*.log
  input_*.wav
  output_*.wav
  metrics.json
```

创建 run 根目录必须拒绝已存在路径；失败重试另建 attempt 子目录，不用 `open("w")`
重写上次目录。raw audio/logs 不进 Git，记录可跟踪摘要与产物路径。
不运行现有固定 `turn_*.wav/json`、speech_transcription.json 或服务日志覆盖路径。

manifest 至少包括 run ID、UTC 时间、父/子库 SHA/dirty 状态、模型路径/config digest、
Python 与关键包版本、真实导入源、GPU UUID/可见卡、端口、启动参数、
音色/语言/seed/切分配置、输入 fixture 与期望、测试命令、退出码及产物校验值。

## 失败账本

每次失败在发生后记录，不将失败藏在“已修复”摘要里：

| 日期/阶段 | 尝试 | 命令/场景 | 现象 | 根因证据 | 解决/下一次变化 | 验证 |
|-----------|------|-----------|------|----------|-----------------|------|
| 2026-10-25/P1 | 1 | 查询猜测的 TTS docs 路径 | 两文件不存在 | rg exit 2 | rg --files 找到 speech_api.md/text_to_speech.md | 已定位 |

区分缺环境、代码错误、协议错误、模型输出质量和硬件资源不足。
同一失败不原样重复；三次尝试后记录假设变化及需要的外部条件。
当前已识别约束：外部 Doc 写权限、两套环境导入/依赖不匹配。

## 完成规则

阶段门槛通过后才标 complete，并记录实现范围、测试、失败/解决、决策及文件清单。
本轮只有规划阶段可以完成；后续阶段保持 pending，不以计划写完代替开发完成。
