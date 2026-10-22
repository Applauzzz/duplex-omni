# 排查报告：连续打断后 talker 输出乱码音频

本文是 `Doc/debug_20261014_barge_in_garbled_audio.md` 的整理版，补充了后来才定位到的
"打断后重答"问题。原始报告保留了完整的日志片段，需要原始数据时看那份。

- 日期：2026-10-14
- 模型：Qwen3-Omni-30B-A3B-Instruct｜节点 `TENCENT64`（28.29.216.165）｜UI 端口 8080
- 结论：**根因已定位并修复并验证**；修复引出一个副作用（打断后重答），未修，待定策略

---

## 1. 现象

1. 一轮一轮正常对话没有问题；
2. 连续打断多次之后，网页端不再显示模型的文字输出，talker 仍在说话但是乱码；
3. 一旦出现就会持续，后面几轮也是这样；
4. 早期还伴随报错 `No assistant response item is registered for resp-duplex-...`。

## 2. 结论

被打断轮次留下的**空 assistant 回复**被原样拼进 prompt。打断次数一多，prompt 窗口里的 assistant
回复几乎全是空的，模型照着上下文的规律学会了"回复空"——thinker 直接输出 `<|im_end|>`（只有 1 个
token）。talker 在**没有任何文字条件**的情况下照样生成了几十个 codec token，也就是 1~3 秒乱码。
这一轮的空回复又会写回历史，形成雪球效应。

修复：`format_history()` 丢掉空 assistant 消息，前后用户输入合并成一个 user 轮。

## 3. 排查过程

### 3.1 先处理报错（症状，非根因）

报错来自 `playback_ledger.py`：`has_assistant_response_item()` 返回 False 时 `playback.ack` 被拒绝。
根因是 `end_response()` 只在 `assistant_text` 非空时注册 snapshot，而"文本空但有音频"的情况真实存在。
修好后报错消失，**乱码依然存在**——说明这只是症状。

### 3.2 被否定或降级的方向（避免重复劳动）

| 假设 | 依据 | 结论 |
|---|---|---|
| turn_id 复用 | 日志里 `e.1...turn4` / `e.2...turn4` 共用编号 | 现象真实，但不是根因：有的失败轮次没有复用编号。降级为遗留问题 |
| abort 竞态（旧 epoch 音频没停干净） | 取消任务有 0.25s 超时等待 | 不符合"持续失败"特征；失败轮次是完整跑完的请求 |
| 空 assistant 历史让模型回空（纯文字验证） | `/v1/chat/completions` A/B 对照 | **没复现，对照实验不等价**：chat 路径会丢掉空 assistant（prompt token 从 100 降到 64），和 duplex 拼 prompt 的逻辑不同 |
| 上下文/异步传输混串 | 用户提出 | 符合"连续打断才触发"，但具体机制要靠下面的证据确定 |

### 3.3 关键证据 1：失败轮次 thinker 都只输出 1 个 token

从 stage0 日志的 `StageRequestStats` 提取（3 个会话共 25 轮）：

| 会话 | response | thinker 输入 | **thinker 输出** | talker 输出 |
|---|---|---|---|---|
| 409f | 3-97a2547a | 444 | 43 | 175 |
| 409f | **4-d143ea49** | 352 | **1** | 23 |
| 409f | **5-197245c2** | 352 | **1** | 62 |
| 409f | **5-b0c1410c** | 349 | **1** | 16 |
| fe7c | **4-5923a146** | 454 | **1** | 26 |
| e0a5 | **4-01ac5436**（用户报告的那一轮） | 429 | **1** | 63 |

规律：每次乱码都对应"thinker 输出 1 个 token + talker 输出几十个"；三个会话**第一次失败都在
epoch=4**（第 4 次打断之后）；失败之后大多继续失败。

### 3.4 关键证据 2：prompt dump

插件自带开关 `VLLM_OMNI_QWEN_VISUAL_DEBUG_DIR`，开启后每轮把 prompt 写到
`<dir>/<hash>/input.json`。开启后重启后端复现，19 轮里有 8 轮 thinker 只输出 1 个 token。

用户报告的最后一轮（e13 turn14）的 prompt（省略 system，音频记为 `[AUDIO]`）：

```
<|im_start|>user
[AUDIO]<|im_end|>
<|im_start|>assistant
<|im_end|>                 ← 空
<|im_start|>user
[AUDIO]<|im_end|>
<|im_start|>assistant
<|im_end|>                 ← 空
<|im_start|>user
[AUDIO]<|im_end|>
<|im_start|>assistant
<|im_end|>                 ← 空
<|im_start|>user
[AUDIO]<|im_end|>
<|im_start|>assistant      ← 模型直接输出 <|im_end|>
```

上下文里的 assistant 回复**全部为空**。正常轮次（如 e2 turn2）里 assistant 都有内容。中间状态
（e4 turn2 失败 / e4 turn3 成功，前面都是 2 个空回复）说明这是随空回复数量升高而概率增大的上下文
模仿行为。

### 3.5 修复后的验证

用 `scripted_barge_in.py` 脚本（gate 模式，连续 5 轮"提交 → 收到第一个音频块 → cancel →
ack played_ms=0"，第 6 轮正常播完）：

| 指标 | 修复前（e13） | 修复后（第 6 轮） |
|---|---|---|
| 会话历史结构 | user / 空 assistant 交替 | 同左（历史不变） |
| prompt 中空 assistant 轮数 | 4 | **0**（6 份 dump 全部为 0） |
| 最后一轮 prompt | 4 段交替 | `user: [AUDIO]x4` 合并成一轮 |
| thinker 输出 token | 1 | **178** |
| 结果 | 无文字 + 乱码 | 完整文字回复 + 约 63 秒正常音频 |

单元测试：`tests/model_executor/models/qwen3_omni/` + `tests/engine/duplex/` 共 599 passed,
1 skipped, 1 error（error 来自缺 `pytest-mock`，与本改动无关）。

## 4. 修复内容

### 4.1 根因修复

`vllm_omni/model_executor/models/qwen3_omni/duplex/plugin.py`

- 新增 `_is_empty_content()`：`None`、空白字符串、空列表都算空。
- `format_history()`：跳过内容为空的 assistant 消息；前后 user 内容自然合并成一个 user 轮。
  docstring 记录了原因（含"模型会模仿空回复"的解释）。
- 影响范围：只影响发给模型的 prompt 视图。`session.history` 仍保留空 assistant 条目，playback ack、
  截断、`conversation.item` 事件都不受影响。

`tests/model_executor/models/qwen3_omni/test_duplex_plugin.py`

- 4 处"prompt 里保留空 assistant 边界"的断言改成合并后的形式。
- `test_format_history_merges_user_parts_but_preserves_empty_assistant_boundary` →
  改名为 `..._and_drops_empty_assistant`，覆盖"有内容保留 / 空丢弃"两种情况。
- `test_empty_assistant_keeps_turn_boundary_in_audio_prompt` →
  改名为 `test_empty_assistant_merges_interrupted_input_into_audio_prompt`。
- 新增 `test_format_history_never_renders_only_empty_assistant_turns`，覆盖本次复现的场景。

### 4.2 症状修复

`vllm_omni/engine/duplex/session/engine_session.py` 的 `end_response()`：有音频但文本为空的 response
也注册空文本 snapshot。

### 4.3 诊断改动（可保留可回退）

- `examples/online_serving/realtime_web/server.py`：WS 逐帧 trace，默认关闭，`OMNI_WS_TRACE=1` 开启。
  **第一版按内部字段名取值导致音频长度全是 0、epoch 全是 None，日志不可信，后来改成不假设字段名**。
- `vllm_omni/engine/duplex/session/helpers.py`：`overlap.decision` 增加 `response_id` / `turn_id`。

## 5. 后续发现：打断后重答

修复上线后用户报告新问题：打断之后模型会把上一轮已经答过的问题再答一遍。

原因（详见 `04_known_issues.md` 遗留问题 1）：被打断且没播完的回答**一个字都不记入历史**
（听了 77% 也算没听到），修复后空回复被丢弃，对应的用户提问就合并进了下一轮。

实测数据：

| 回答 | 总时长 | 已听 | 比例 | 记入历史 |
|---|---|---|---|---|
| 3-de26bbab | 18.6s | 14.4s | 77% | 空 |
| 7-66fbf5d7 | 15.7s | 12.0s | 76% | 空 |
| 9-a3bf93d8 | 24.9s | 14.5s | 58% | 空 |
| 6-a3eac2bc | 18.9s | 18.9s | 100% | 完整 |

当时用户会话最后一轮的 prompt 是 `user: [AUDIO]x4`，中间零个 assistant 回复，所以模型把 4 个问题
一起答了。

## 6. 设计权衡（决定不修的原因）

"打断后记多少文字"没有唯一正确答案。三个候选：

1. **按比例估算**：按 `已听/总时长` 截取文字，回退到最近标点。最接近真实，但是估算。
2. **超阈值记全文**：简单，但粗糙。
3. **播过就记全文**：一定不重答，但模型会以为用户听到了全部。

关键约束：**现有测试明确断言了"部分播放的未对齐文本不得记入历史"这条严格策略**，改动会破坏这些
断言。所以这属于**策略变更**，不是纯 bugfix，本轮没有擅自改，留给下一阶段定。

## 7. 相关文件

| 类型 | 路径 |
|---|---|
| 根因修复 | `vllm-omni/vllm_omni/model_executor/models/qwen3_omni/duplex/plugin.py` |
| 症状修复 | `vllm-omni/vllm_omni/engine/duplex/session/engine_session.py` |
| 测试 | `vllm-omni/tests/model_executor/models/qwen3_omni/test_duplex_plugin.py` |
| 诊断 trace | `vllm-omni/examples/online_serving/realtime_web/server.py`、`vllm-omni/vllm_omni/engine/duplex/session/helpers.py` |
| 复现脚本 | `workspace/experiments/20261014_barge_in_garble/scripted_barge_in.py` |
| 对照实验 | `workspace/experiments/20261014_barge_in_garble/empty_assistant_probe.py` |
| 修复前日志 | `workspace/logs/20261014_081125_duplex_service/`、`workspace/logs/20261014_091625_duplex_service/` |
| 修复前 dump | `workspace/logs/20261014_qwen_prompt_dump/` |
| 修复后日志 | `workspace/logs/20261014_095238_duplex_service/` |
| 修复后 dump | `workspace/logs/20261014_qwen_prompt_dump_fix/` |
