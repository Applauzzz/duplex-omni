# 改动清单

本轮所有改动都在 `vllm-omni/` 子仓库的工作区（**未提交**）。`git status` 显示 13 个文件被修改。
下面按改动目的分组，方便 review 和决定哪些要带回主线。

```
 M examples/online_serving/realtime_web/app/index.html                    |  2 +
 M examples/online_serving/realtime_web/app/static/app.js                 | 74 ++++++++++
 M examples/online_serving/realtime_web/app/static/profiles/qwen3_turn.js | 48 ++++++---
 M examples/online_serving/realtime_web/server.py                         | 91 +++++++++++++++-
 M tests/model_executor/models/qwen3_omni/test_duplex_plugin.py           | 47 ++++++---
 M vllm_omni/config/stage_config.py                                       | 59 +++++++++
 M vllm_omni/engine/duplex/config.py                                      |  7 +-
 M vllm_omni/engine/duplex/session/control.py                             | 14 ++-
 M vllm_omni/engine/duplex/session/engine_session.py                      | 17 +++
 M vllm_omni/engine/duplex/session/helpers.py                             |  2 +
 M vllm_omni/engine/duplex/turn_detection.py                              | 55 ++++++----
 M vllm_omni/entrypoints/duplex_omni.py                                   | 14 ++-
 M vllm_omni/model_executor/models/qwen3_omni/duplex/plugin.py            | 20 +++-
```

---

## A. VAD 配置暴露（功能开发，建议保留）

目的：让 deploy config 能控制 `turn_detection` 的默认值，取代原先只能硬编码在前端 JS 的做法。

| 文件 | 改动 |
|---|---|
| `vllm_omni/config/stage_config.py` | `DuplexSessionRuntimeConfig` 新增 `server_vad_defaults: dict \| None`；新增类属性 `_SERVER_VAD_DEFAULT_FIELDS`、`_SILERO_VAD_MIN_THRESHOLD`；`__post_init__` 调用新增的 `_validate_server_vad_defaults()`，校验未知键、`threshold` 区间 `(0.15, 1]`、非负数值、布尔类型 |
| `vllm_omni/engine/duplex/turn_detection.py` | `TurnDetectionConfig.from_realtime()`、`normalize_turn_detection_session_payload()`、`PendingTurnDetectionUpdate.prepare()` 三个签名都新增 `defaults` 参数，实现"客户端显式值 > deploy 默认值 > 代码兜底"三層取值 |
| `vllm_omni/engine/duplex/config.py` | `DuplexSessionConfig.from_realtime()` 新增 `server_vad_defaults` 参数并透传给 `normalize_turn_detection_session_payload()` |
| `vllm_omni/entrypoints/duplex_omni.py` | `_resolve_session_config()` 新增 `server_vad_defaults` 参数；`open_session()` 传入 `self.duplex_session_config.server_vad_defaults` |
| `vllm_omni/engine/duplex/session/control.py` | import 加 `Mapping`；新增 `_server_vad_defaults()` helper（从 `manager.runtime_config` 读）；`on_session_update()` 透传 |

配套新文件：`workspace/configs/demo_vad.json`（本轮交付的配置样例，含 `_readme` 说明）。

## B. 乱码 bug 修复（建议保留）

| 文件 | 改动 |
|---|---|
| `vllm_omni/model_executor/models/qwen3_omni/duplex/plugin.py` | 新增 `_is_empty_content()`；`format_history()` 跳过空 assistant 消息（根因修复） |
| `vllm_omni/engine/duplex/session/engine_session.py` | `end_response()`：有音频但文本为空时也注册空文本 snapshot（症状修复，避免 `playback.ack` 报 `playback_item_not_found`） |
| `tests/model_executor/models/qwen3_omni/test_duplex_plugin.py` | 4 处断言改为合并后的形式；2 个测试改名；新增 `test_format_history_never_renders_only_empty_assistant_turns` |

## C. 诊断工具（可选，建议保留但确认默认关闭）

| 文件 | 改动 |
|---|---|
| `examples/online_serving/realtime_web/server.py` | WS 逐帧 trace，`OMNI_WS_TRACE=1` 才开启（默认静默）。`_trace_prefix()` / `_trace_frame()`，不假设字段名、只打印实际收到的字段和长字段长度。`OMNI_WS_TRACE_AUDIO=0` 可关掉音频帧 |
| `vllm_omni/engine/duplex/session/helpers.py` | `overlap_decision_event()` 增加 `response_id` / `turn_id` 两个诊断字段 |

## D. 前端 gate 模式（功能开发，建议保留）

目的：绕开 VAD，用脚本/手动方式稳定复现打断场景。

| 文件 | 改动 |
|---|---|
| `examples/online_serving/realtime_web/app/index.html` | 新增 "Open gate"、"Interrupt" 两个按钮 |
| `examples/online_serving/realtime_web/app/static/app.js` | +74 行，gate 模式的支持逻辑 |
| `examples/online_serving/realtime_web/app/static/profiles/qwen3_turn.js` | 新增第三种模式 `gate`（原 `stt` / `vad`）；`turn_detection: null`；手动 commit/interrupt；中文全双工语音助手的 instructions 预设 |

## E. 本目录之外的新增文件

```
workspace/configs/demo_vad.json                                 # VAD 配置样例
workspace/scripts/start_duplex_service.sh                       # 一键启动脚本（本轮多处修改）
workspace/experiments/20261014_barge_in_garble/                 # 复现脚本、对照实验、pytest vendor 目录
workspace/logs/                                                 # 各次启动日志 + prompt dump
Doc/debug_20261014_barge_in_garbled_audio.md                    # 原始 debug 报告
Doc/Qwen3_Omni_duplex_legacy/                                   # 本交接文档目录
```

`start_duplex_service.sh` 本轮的修改点：
- `DEPLOY_CONFIG` / `VLLM_PORT` / `UI_PORT` 可被环境变量覆盖；
- `flock` 文件锁防止并发启动；
- `READY_TIMEOUT` 从 300s 提到 3000s（30B MoE 编译+预热实测远超 5 分钟）；
- `set -m` + 进程组 kill，避免 `vllm serve` fork 出的子进程变孤儿占着 GPU；
- `CURL_BIN` 在 `conda activate` **之前**固定 curl 绝对路径（activate 后 PATH 里没有 curl，就绪检测
  会静默失败，把已启动成功的服务误杀）。

---

## 验证状态

| 改动组 | 验证方式 | 结果 |
|---|---|---|
| A（VAD 配置） | 手写脚本直接调用函数，6 个场景；`load_deploy_config()` 实际加载 `demo_vad.json` | 全部通过。**端到端未验证**（当时生产环境有同事在用，没重启） |
| B（乱码修复） | pytest 599 passed；脚本端到端复现 | 通过 |
| C（诊断工具） | `py_compile` + 样例 payload 冒烟；实际跑过一次会话 | 通过 |
| D（gate 模式） | 脚本用它跑通了 6 轮打断复现 | 通过 |

A 组缺端到端验证，接手后如果要确认"配置真的生效"，可以起服务后不传 VAD 参数开一个会话，检查服务端
日志/行为是否符合 `demo_vad.json` 里的值。

---

## review 时需要特别关注的点

1. **`plugin.py` 的 `format_history()` 改动**改变了模型看到的上下文结构，并且破坏了 4 个已有断言。
   这是有意为之的行为变更（原来保留空 assistant 作为轮次分隔），不是笔误。
2. **`engine_session.py` 的 `end_response()` 改动**让空文本但有音频的 response 也会注册 snapshot。
   手工复用 `tests/engine/duplex/test_engine_session.py` 里最相关的 5 个用例验证过没有回归，
   但当时环境跑不了完整 pytest（见 `02_running.md` 第 8 节），建议在能跑 pytest 的环境补一次完整回归。
3. **`demo_vad.json` 里的 `threshold` 当前是 `0.95`**，排查过程中被改过，灵敏度很低。上线前确认是否
   要恢复 `0.5`。
4. **C 组的 `server.py` trace** 默认关闭，但代码量不小（+91 行）。如果不想带回主线，可以直接回退
   这个文件。
5. **所有改动都没提交**，`git diff` 可以直接看。建议按 A/B/C/D 分组分别提交，方便取舍。
