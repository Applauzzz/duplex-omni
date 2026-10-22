# MiMo → Qwen3-Omni Talker：纯文本驱动语音生成方案 A

前置知识：MiMo—Qwen3 duplex项目是使用MiMo的文字输出替换qwen3 omni thinker给talker的文字生成部分，保留Qwen3 Omni thinker给出的多模态hidden，最终变成talker接收sys prompt emb+middle hidden+mimo output text emb，我们应该保证streaming的Qwen3 omni特性，将MiMo也纳入streaming的设计范围里。/mnt/geminihzceph/user_whynotzhliu/modelbase/Omni下面是两个模型的ckpt。

## 1. 目标与范围

**目标**：使用 MiMo 作为唯一的对话文本生成模型，将其输出的自然语言文本送入 Qwen3-Omni 的 Talker 链路生成语音。第一阶段仅验证**单轮、纯文本输入、完整文本生成后合成语音**，不接入 Agent、图像、音频输入、Duplex 或打断。

**原则**：不直接传 MiMo 的 embedding / hidden states；不训练 Adapter；优先复用 Qwen3-Omni 原有的 Text-to-Speech 条件化、Talker、MTP 和 Codec Decoder 实现。尽可能不执行 Qwen Thinker 的 Transformer forward。

> 注意：本文描述的是目标架构和实验方案，而不是声称所有当前版本的 vLLM-Omni 都已经提供外部文本直连 Talker 的公开 API。具体的模块路径、权重依赖和中间状态需以实际使用的 Qwen3-Omni 版本核对。

## 2. 核心结论：Talker 接收什么？

外部边界传递的是**文本**，不是 MiMo 的浮点表示：

```text
User text
    │
    ▼
MiMo generate()  ──→  UTF-8 response text
                          │
                          ▼
                 Qwen3-Omni tokenizer
                          │
                          ▼
                 Qwen text embedding
                          │
                          ▼
                 Qwen native projection /
                 Talker conditioning builder
                          │
                          ▼
                 Qwen3-Omni Talker
                          │
                          ▼
                 Audio codec + MTP
                          │
                          ▼
                 Codec decoder → waveform
```

### 三类信息不要混淆

| 信息 | 方案 A 中的处理 |
|---|---|
| MiMo 输出文本 | 先 detokenize 为字符串，再用 Qwen tokenizer 重编码 |
| MiMo Text Embedding / Middle Hidden | **不传入**，模型间表示空间不保证兼容 |
| Qwen Text Embedding | 使用 **Qwen 原生 embedding 权重**生成；经过原生投影 / conditioning 进入 Talker |
| Qwen Thinker Middle Hidden | 对于目标中的 text-only TTS 路径，优先验证可否省略；如果实现强依赖，不可用随意的全零向量冒充 |
| System Prompt | 用于 MiMo 的对话生成；Qwen Talker 是否需要专门的任务控制 token / prompt 由原始 TTS 链路确定，不是简单传入通用 system prompt embedding |
| Speaker / Codec history / BOS / EOS / positions | 必须保留 Qwen Talker 原生构造和状态管理 |

**因此，目标不等于** `sys_prompt_emb + qwen_middle_hidden + mimo_text_emb`。更准确地说，是“MiMo 文本 → Qwen 自己的文本条件化输入 + Talker 原生控制与 Codec 状态”。

## 3. 最小可行实现：先找到可工作的 Qwen TTS 基线

### Phase 0：固定环境和原始基线

1. 固定 checkpoint、Transformers / vLLM-Omni 版本、commit hash、精度和生成配置。
2. 在未修改的官方示例或已验证的项目实现中，跑通 Qwen3-Omni **文本到语音**或可等价复用的语音输出链路。
3. 保存中间信息：
   - Qwen Thinker 产生的文本及 token IDs；
   - 传给 Talker 的输入张量名称、形状、dtype、device；
   - 其中哪些字段来自 embedding lookup、哪些来自 Thinker forward、哪些是控制 token / speaker / codec 状态；
   - MTP 和 codec decoder 的输入输出；
   - 波形、首包时间、语音长度、是否正常 EOS。
4. **门槛**：原版 TTS 不通就不要开始跨模型替换。

### Phase 1：先做 Qwen 自身文本回灌（关键控制实验）

保持 Qwen 原本生成的**文本字符串**不变，将其重新送入候选的独立 TTS conditioning builder：

```text
Qwen output IDs → decode to text → Qwen tokenizer → original TTS builder → Talker
```

这一步用于排除 MiMo 模型差异。如果回灌不能正常生成语音，问题就在文本条件化接口或隐藏状态依赖，而非 MiMo 输出。

然后依次验证：

1. **标准原版链路**：Thinker + Talker 正常。
2. **文本重编码**：同一段文字重新 tokenizer，语音正常。
3. **移除 Thinker Transformer forward**：只保留必要的 Qwen embedding / projection 和 Talker；在合法输入协议下生成语音。

**停止条件**：如果第 3 步无法成立，应查清 Talker 哪些位置依赖 Thinker hidden，不能直接传全零 hidden 或误认为 text embedding 足以替代全部条件。此时选择：继续构建原生 text-only 输入协议、保留轻量必要路径，或者暂时改为 MiMo 文本 → 成熟独立 TTS 模型。

### Phase 2：接入 MiMo（非流式）

```python
# 伪代码：具体 API 名称需根据已验证的模型版本实现
reply_text = mimo_generate(user_text).strip()

# 关键跨模型接口：字符串，不传 MiMo 隐藏层张量
qwen_text_ids = qwen_tokenizer(
    reply_text,
    add_special_tokens=False,
).input_ids

# 下面需要复用原版 Qwen TTS 的真实函数，不能只做一次 embed lookup 就调用裸 talker.forward()
conditioning = build_qwen_tts_conditioning(
    text_token_ids=qwen_text_ids,
    speaker_id=selected_speaker,
    # task-specific control tokens, positions, attention masks ...
)

codec_stream = qwen_talker_generate(conditioning)
waveform = qwen_codec_decode(codec_stream)
```

**严禁的捷径**：
- 不要将 MiMo 的 token IDs 当作 Qwen 的 token IDs。
- 不要将 MiMo 的 embedding 直接写入 Qwen Talker text embedding 位置。
- 不要根据张量 shape 相等假设语义空间相等。
- 不要忽略原版 speaker / BOS / EOS / codec-shift / MTP 对齐逻辑。
- 不要把供文本模型推理使用的 MiMo system prompt 当作 Talker 的通用 embedding 前缀。

## 4. 推荐工程模块划分

```text
mimo_talker_bridge/
├── mimo_client.py           # MiMo 文本生成；仅对外输出字符串
├── qwen_tts_adapter.py      # Qwen tokenizer、embedding、projection、控制 token
├── talker_runner.py         # Talker + MTP 推理及状态初始化
├── codec_decoder.py         # 调用既有 codec decoder / Code2Wav
├── run_offline.py           # 单轮离线验证入口
├── inspect_baseline.py      # dump 原始 Qwen Thinker→Talker payload
└── tests/
    ├── test_roundtrip.py    # Qwen 自身文本回灌
    ├── test_mimo_bridge.py  # MiMo 文本驱动
    └── test_eos.py          # EOS / 重复 / 说不全检查
```

优先将 `qwen_tts_adapter.py` 定义为单一可信边界：其输入为 `str` / Qwen token IDs，输出为**原版 Talker 可接受的完整 conditioning payload**，从而将 MiMo 与 Qwen 解耦。

## 5. 验收与测量

首轮选 10~20 条固定短文本，包括中文、英文、数字、标点和中英文混合。建议保留如下结果：

| 指标 | 验证方法 | 最低验收要求 |
|---|---|---|
| 正常发声 | 听测 / 波形非空 | 所有样例输出非空有效音频 |
| 内容一致性 | ASR 回转录，人工复核 | 无大段漏读、插话或幻觉 |
| EOS 正确性 | 观察 codec 结束与时长 | 无无限生成或异常截断 |
| 稳定性 | 同样例重复运行 | 不频繁出现崩溃或随机乱码 |
| TTFA / 总耗时 | 分别记录 MiMo、Talker、Decoder | 建立基线，暂不硬设阈值 |
| GPU 开销 | `nvidia-smi` / profile | 对比保留完整 Qwen Thinker 的版本 |

**实验日志建议**：`mimo_text`、`qwen_token_ids`、`conditioning_shapes`、`num_codec_steps`、`stop_reason`、`waveform_duration`、`mimo_latency_ms`、`talker_latency_ms`、`decoder_latency_ms`。

## 6. 流式升级（仅在离线版本稳定后）

将 MiMo 的稳定文本片段逐块送入 Talker，复用原始 chunk streaming 机制：

```text
MiMo incremental text
    → stable text chunks
    → Qwen retokenization / conditioning
    → stateful Talker generation
    → incremental codec decoder
    → playback
```

流式阶段必须额外验证 tokenizer 跨 chunk 边界、文本与音频对齐、Talker KV cache 续接、codec frame 的相位与边界、异常停止以及播放器缓冲。**不能简单对每个文本 chunk 重新执行完整单句 TTS 并假定语音无缝衔接。**

## 7. 技术风险与回退

1. **原版 Talker 的 text-only 接口并不独立**：先通过 Phase 1 定位隐藏状态依赖。若无法省略，就需要桥接模块/适配训练，或使用专门的 TTS 模型。
2. **Codec 生成异常**：优先排查控制 token、speaker、位置编码、codec 历史右移以及 EOS，而非首先修改模型权重。
3. **文本分词不一致**：模型间只传 Unicode 字符串；Qwen 独立重编码。
4. **延迟不理想**：先将全链路拆成 MiMo、conditioning、Talker、MTP、decoder 五段 profile；离线正确后再优化流水线。

## 8. 给工程 Agent 的执行指令

> 目标：在现有 Qwen3-Omni 推理工程里实现 MiMo 文本驱动 Qwen Talker 的多轮、流式 TTS PoC，禁止训练模型或修改原权重。第一步先检查当前源码和 checkpoint，定位原始 Thinker→Talker payload 的真实构建函数、Talker 是否支持 text-only conditioning、控制 token、middle hidden 依赖及 codec 输出协议。先完成 Qwen 文本回灌实验，再引入 MiMo 输出。跨模型仅传字符串，严禁直接混用 embedding / token IDs。保留原始链路作为对照，输出可运行的测试脚本和所有失败分析。如果发现无法无损省略 Thinker forward，要明确报告阻塞点，不要使用全零 hidden 冒充兼容或跳过验证。

## 9. 成功定义

最终验证的是：**MiMo 生成的任意纯文本回复可以在不执行 Qwen Thinker Transformer 推理、且不使用 MiMo Hidden States 的情况下，经 Qwen 原生文本条件化模块、Talker 和 codec decoder 正确生成语音。**

只有在原版代码确实支持该输入协议，并通过 Phase 1~2 验证后，才能称为真正的“无训练、纯文本夺舍”方案。
