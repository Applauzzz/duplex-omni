# 已知问题

分三类：**已修**、**遗留（有明确修法但需要先定策略）**、**固有局限（换 talker 方案才能解决）**。

---

## 一、已修

### 1. `No assistant response item is registered for resp-...`

- **现象**：报错，且伴随"thinker 没有输出、talker 说乱码"。
- **原因**：`engine_session.py` 的 `end_response()` 只在 `assistant_text` 非空时才把 response 注册进
  `assistant_response_snapshots`。文本为空但 talker 已经发出音频时，这次 response 在三个登记处
  （`active_response_id` / `item_ids`+`pending_item_ids` / `assistant_response_snapshots`）都查不到，
  前端随后发来的 `playback.ack` 就被 `playback_ledger.py` 拒绝。
- **修法**：额外检查这次 response 的 playback cursor（`sent_ms` / `generated_ms`），有音频就注册一个
  空文本的 snapshot。和处理 overlap 的 `snapshot_active_response_for_drain()` 保持一致。
- **状态**：已修并验证。**这个只是症状**，根因见下面的第 3 条。根因修好后这条路径很少会走到，但作为
  防御保留。

### 2. 连续打断后 talker 输出乱码音频

- **现象**：一轮一轮正常对话没问题；连续打断多次后，网页不显示模型文字输出，talker 说乱码；一旦
  出现就会持续。
- **根因**：被打断轮次留下的**空 assistant 回复**被原样渲染进 prompt
  （`<|im_start|>assistant\n<|im_end|>`）。打断次数一多，上下文里的 assistant 回复全是空的，模型
  照着学，第一个 token 就输出 `<|im_end|>`（thinker 总共只输出 1 个 token）。talker 在没有任何文字
  条件的情况下照样生成了几十个 codec token，这就是乱码的来源。这一轮的空回复又写回历史，形成雪球
  效应，所以会一直持续。
- **修法**：`plugin.py` 的 `format_history()` 跳过内容为空的 assistant 消息，前后的用户输入合并成
  一个 user 轮。只改发给模型的 prompt 视图，会话历史本身不变。
- **验证**：`tests/model_executor/models/qwen3_omni/` + `tests/engine/duplex/` 共 599 个通过；
  脚本模拟连续打断 5 次后，6 份 prompt dump 里都不再有空回复，最后一轮 thinker 从 1 个 token 恢复到
  178 个，输出完整的正常回复。
- **副作用**：引出下面的遗留问题 1。
- **详细过程**：见 `05_debug_barge_in_garbled_audio.md`。

---

## 二、遗留问题（有修法，需要先定策略）

### 1. 打断后重答上一轮 ⚠️ 当前存在，未修

- **现象**（用户报告）：
  对话里已经完整回答过"推荐什么鞋"、"第三天去哪"，用户打断之后，模型的下一段回答又把这几个问题
  重新答了一遍。
- **原因**：**两个因素叠加**。

  因素 A：Qwen 的文字和音频没有对齐信息，引擎对被打断的回答采用"要么全记、要么不记"的策略
  （`engine_session.py:1655` 的 `_text_chars_for_audio_ms`，由 `plugin.py:118` 的
  `text_requires_complete_audio=True` 触发）。实测数据：

  | 回答 | 总时长 | 已听 | 比例 | 记入历史 |
  |---|---|---|---|---|
  | 3-de26bbab | 18.6s | 14.4s | 77% | **空** |
  | 7-66fbf5d7 | 15.7s | 12.0s | 76% | **空** |
  | 9-a3bf93d8 | 24.9s | 14.5s | 58% | **空** |
  | 5-2cec6bab | 30.4s | 8.0s | 26% | **空** |
  | 6-a3eac2bc | 18.9s | 18.9s | 100% | 完整 |

  听了 77% 也记为"一个字没听到"。

  因素 B：修复第 2 条时去掉了 prompt 里的空回复，于是这些"没记入历史的回答"对应的**用户提问**
  被合并进下一轮，模型看到的是"用户连问了 4 个问题还没得到回答"，就把它们一起重答了。

  修复前的表现是相反的：空回复渲染成 `assistant: <|im_end|>`，模型知道"答过了"不会重答，但容易
  照着学回复空 → 乱码。**两头都不理想，真正的病根在因素 A。**

- **可选的修法**（都改 A，A 修好后 B 的副作用自然消失）：

  | 方案 | 做法 | 代价 |
  |---|---|---|
  | 按比例估算（推荐） | 按 `已听时长 / 总音频时长` 截取对应比例的文字，再往前截到最近的标点 | 是估算，可能多算/少算几个字 |
  | 超过阈值记全文 | 例如听到 50% 以上记全文，否则不记 | 粗糙，听了 51% 也当作全听到 |
  | 只要播过就记全文 | 有音频播放过就记整段 | 模型会以为用户听到了全部，可能说"刚才我说过……" |

  三个方案都要改 `_text_chars_for_audio_ms` 的 unaligned 分支。注意**现有测试明确断言了这条严格
  策略**（"部分播放的未对齐文本不得记入历史"），改动会破坏这些断言，属于策略变更而非纯 bugfix，
  所以本轮没有动。

### 2. turn_id 复用

- **现象**：被打断的 turn 编号会被下一个 epoch 用一次。日志里能看到
  `e.1...turn4` 和 `e.2...turn4` 指向两个不同的 response。
- **原因**：`session.turn_id` 只在 `complete_model_turn()` 里推进，而打断路径走的是
  `runner.py` 的 `_cancel_active_response()` → `end_response()`，不调用 `complete_model_turn()`。
- **影响**：目前没有发现它直接导致可见问题（排查乱码时一度怀疑它，后来被证据排除）。引擎的去重靠
  `(epoch, turn_id)` 组合，不是单靠 turn_id。
- **状态**：未修。仓库里已有先例在"安全边界提前关闭 response"时补一次推进
  （`model_channel.py` 的 `_end_active_response_before_future_model_turn()`）。

### 3. 服务无鉴权 + `max_sessions=1`

- VAD 服务没有任何鉴权，任何能访问端口的人都能用。
- `max_sessions=1`（demo 配置），同一时间只能一个人用，你和同事不能同时连。改大需要重启三阶段后端。

---

## 三、固有局限（现有 talker 的架构限制，换方案才能解决）

### 1. 无法知道用户听到了多少

Qwen3-Omni 的 thinker 文字流和 talker 音频流是**独立的**，没有"第 N 个字对应第 M 毫秒音频"的对齐
信息（`plugin.py` 里 `audio_text_mark: False`）。这直接导致遗留问题 1，也让"按实际听到的内容截断
历史"无法精确实现。

**这是评估新 talker 方案时最值得关注的一点**：如果新方案（streaming talker）能提供文本与音频的对齐
标记（类似 `audio_text_marks`），遗留问题 1 就能从根上解决，不需要按比例估算。

### 2. 被打断的回答无法部分提交

同上。对齐信息缺失使得历史提交只能全有或全无。

### 3. 每轮都要重新编码完整历史

`supports_core_resumable_request = False`，每一轮都是一次全新的请求，把整个会话历史（含音频）重新
编码进 prompt。这也意味着**历史长度和音频段数会直接影响延迟**，且音频窗口只有 4 段。

### 4. thinker 空回复时 talker 仍会发声

引擎层没有"thinker 无文字就丢弃音频"的保护。如果以后因为别的原因再次出现空回复，talker 仍然会输出
乱码。本轮评估过兜底方案（检测到空文字时丢弃该轮音频），但因为需要先确认文字事件和音频事件的先后
顺序，暂未实现。

---

## 验证问题是否复发

```bash
# thinker 输出 1 个 token = 空回复 = 乱码会复现
awk '/\[StageRequestStats \[request_id=/{match($0,/resp-duplex-[a-f0-9]+-[0-9]+-[a-f0-9]+/); rid=substr($0,RSTART+46)} /num_tokens_out/{y=$0; sub(/.*num_tokens_out */,"",y); split(y,b,"|"); print rid " thinker_out=" b[2]}' workspace/logs/<目录>/stage0_attempt1.log
```

开 `VLLM_OMNI_QWEN_VISUAL_DEBUG_DIR` 后，检查 prompt 里是否还有空 assistant 回复：

```bash
grep -c "<|im_start|>assistant$" <dump_dir>/*/input.json 2>/dev/null   # 或用 python 数
```

正常应该没有 `assistant` 后面紧跟 `<|im_end|>` 的空轮。
