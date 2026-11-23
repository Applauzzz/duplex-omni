# Qwen3-Omni Thinker 兼容

分支：模型兼容，基于 origin/main 2f9677b，不包含上线 new_user_turn 策略。
这是在原 MiMo-only 系统上的可选模型扩展，不替换历史基线。

## 接入范围

AVAD、VASD、VAED、FSM、历史轮数、文本分段及外部 TTS 保持现有逻辑。
使用普通 vllm-src 的 Qwen3OmniMoeForConditionalGeneration 注册项：
它映射到 Qwen3OmniMoeThinkerForConditionalGeneration。
注意：当前环境安装的 vllm-omni 通用插件会覆盖这个注册项。
原生 thinker 模型进程必须设置 VLLM_PLUGINS=""，不改环境安装；
仅使用普通 vllm CLI 并不足以保证实际加载的是原生 thinker。
模型的 hf_to_vllm_mapper 丢弃 talker.* 和 code2wav.* 权重，
不启用 vllm-omni thinker/talker/code2wav 多阶段流水线。
Qwen Agent/tool parsing 不在本阶段支持范围；Qwen+agentic 启动直接拒绝。

## 单 Token 判别

实际模型目录的 AutoTokenizer(local_files_only=True) 验证结果：

| 输出字 | Token ID | 对应意义 |
|---|---|---|
| 有 | 18830 | VASD 有语义 |
| 无 | 42192 | VASD 无语义 |
| 已 | 36667 | VAED complete |
| 未 | 38342 | VAED incomplete |
| ⏸ | 149660 | 历史回复中断标记 |

五者都是单 token，此 checkpoint 恰好与 MiMo 相同，不改 Prompt 分类用词。
启动时按 Qwen tokenizer 重新解析四个分类字并校验单 token 往返和唯一性，
不假定未来 tokenizer 也相同。max_tokens=1、allowed_token_ids、
logprob_token_ids、双候选归一化 probability/margin 保持原协议。
阈值不自动调整；不同模型的校准、拒识质量与端点质量仍需实际音频验收。

## 启动模板

模型目录：
/mnt/geminihzceph/user_whynotzhliu/modelbase/Omni/Qwen3-Omni-30B-A3B-Instruct。
以下是模板，尚未 GPU 启动验收。先检查 GPU、端口、当前解释器、
vllm 导入根和已编译 _C ABI；不要直接复用其他节点的 runtime。

```bash
source /mnt/geminihzceph/user_whynotzhliu/my_envs/env.sh
conda activate omni
# 用当前 vllm-src 及已核验的 _C runtime；不要改环境 editable install。
VLLM_PLUGINS="" python -m vllm.entrypoints.cli.main serve \
  /mnt/geminihzceph/user_whynotzhliu/modelbase/Omni/Qwen3-Omni-30B-A3B-Instruct \
  --served-model-name qwen3-omni-thinker \
  --host 127.0.0.1 --port 8092 \
  --tensor-parallel-size 4 --max-model-len 32768 \
  --limit-mm-per-prompt '{"audio":31,"image":0,"video":0}'
```

普通 UI 服务使用已核验 runtime + 当前 vllm-omni 的进程 PYTHONPATH：

```bash
python -B workspace/experiments/20261025_mimo_tts_integration/svad_debug_server.py \
  --backbone qwen3-omni --backbone-model qwen3-omni-thinker \
  --lm-url http://127.0.0.1:8092 --host 127.0.0.1 --port 8082 \
  --config workspace/experiments/20261025_mimo_tts_integration/svad_config.json
```

--backbone-tokenizer 可覆盖本地 tokenizer 目录；模型 API 名称必须与
--served-model-name 一致。旧 --mimo-url 及默认 MiMo 路径兼容。
历史音频数限制需覆盖 history_turns+当前轮，本例为30+1；
32768 上下文不是30轮长音频必然能容纳的保证。

## Streaming 与边界

复用音频 input_audio WAV 请求及 Chat SSE content 增量；
逐增量 yield 给现有文本 chunker/TTS，不先拼接完整回复。
VAD 分类仍非流式的一 token 请求。正常答复不消费 reasoning_content。
当前 Prompt 中 enable_thinking=false 不等价于所有模型都有可切换 thinking 模式。
使用指定 Instruct checkpoint，实际模板、音频输入、finish_reason、
取消断连和下游 TTS 重叠仍需真实推理确认。
已有类名与部分 UI/log 标签仍保留 MiMo，避免无关重构；不代表实际选用 MiMo。

## 验收门槛

- 本地 tokenizer 已实测，未修改模型目录。
- 受控 classifier 请求与 Chat 逐段输出测试；保留 MiMo 回归。
- 后续 GPU 门槛：语音 VASD/VAED、Chat 首字及多个 delta、TTS 首音频
  早于 Chat 完成、取消无后续数据、历史追问、真实静音/拒识质量。
- 未承诺语义阈值可直接复用的质量、未提交或推送。

## 2026-11-18 本节点部署

网页：http://28.29.218.211:8080/，原生协议：
ws://28.29.218.211:8080/ws。不是 Agent 页面或上线协议适配服务。
模型 API 仅监听127.0.0.1:8092，served name为qwen3-omni-thinker。
模型PID37788，UI PID23631；TP4，GPU0-3，max_num_seqs4，
max_model_len32768，eager模式，未启用talker。

实际启动清单与日志：

- 模型：workspace/logs/20261118T161533Z_qwen_native_kjocsx5z/launch.json、
  thinker.log。
- 网页：workspace/logs/20261118T154532Z_qwen_wpe3imxu/launch.json、
  ui.log。
- 当前读取的配置：上述网页目录的svad_config.json，是主配置的启动快照。
  修改主配置不会改变这个已启动实例；需要修改该快照或重启时换回主配置路径。
- 外部TTS：http://29.213.195.135:8100，bench_spk，24kHz PCM16。

本机HTTP首页200、模型/TTS健康、同Origin WebSocket configure通过。
真实200ms音频批次：VASD在800ms前缀上通过，概率0.859664、
margin1.8125；VAED判真且AVAD关闭后以semantic_complete触发Decode。
单轮探针single_turn_cz3cgjnm：25个chat.delta、10个tts.audio，
466800字节PCM；首音频3.154秒，Chat完成4.6199秒，TTS完成4.951秒。
这些是探针开始后的墙钟时间，音频按ACK发送，不是实时端点延迟指标。
首音频早于Chat完成1.466秒，确认decode与TTS流式重叠。
原音频含停顿，单轮探针只发送到第一次Decode，不代表完整5.16秒都进入该轮。

已知未验收项：真实远端浏览器麦克风/播放、打断取消、长历史、
并发负载及语义阈值质量。实测回复有Assistant:前缀并进入TTS，
不符合纯口语格式要求；本次未加字符串过滤或改共享Prompt，后续需适配。
首次插件覆盖导致的meta/CUDA失败、readiness等待超时和测试float WAV
读取失败均已保留记录；原生进程禁用插件、延长等待、测试内转换PCM后通过。

Mac Chrome直连麦克风使用独立测试profile：

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --user-data-dir=/tmp/chrome-duplex-qwen-218211 \
  --unsafely-treat-insecure-origin-as-secure=http://28.29.218.211:8080 \
  --new-window http://28.29.218.211:8080/
```

该命令只适用于内网演示，未提供TLS/auth生产部署保证。

## 原始 SSE 调试日志

2026-11-18 UI已更新为PID56326，入口地址和配置快照不变，模型37788不变。
当前UI日志：workspace/logs/20261118T170745Z_qwen_sse_nfef3o5f/ui.log。
启动开关--raw-sse-log-dir指向该目录下raw_sse。
每次普通Chat请求创建唯一chat-*.sse文件，保存应用解析前的响应体字节，
保留SSE换行、role/content、finish_reason和DONE；被取消的流可能只有部分数据。
ui.log中chat_raw_sse关联request_id/model/path。默认关闭；不捕获输入音频、
请求Prompt或HTTP传输分块头。目录0700/文件0600，含对话正文，需限制访问，
排障结束后移除启动开关并重启UI关闭；当前未设置自动轮转。

实测chat-ac55495f5b95473583be9750178e90c6.sse：
首帧delta.role=assistant且content为空，后续content分别为Assistant和冒号。
说明该样本不是应用parser把role拼进正文；上游生成/模板原因尚未确定，
User标签需要继续复现。未修改Prompt、未隐藏角色标签，流式TTS回归通过。

## 移除 Chat thinking 覆盖参数的对照测试

2026-11-18 按用户要求，Qwen Chat 不再发送
`chat_template_kwargs={"enable_thinking": false}`，而是完全省略该参数。
MiMo Chat 与 VASD/VAED 单 token 判别仍保留原参数，避免同时改变分类行为。
未修改 Prompt、未过滤角色名，也未切换到 vllm-omni 多阶段引擎。

同一段音频前三秒、同一 Prompt、空历史、temperature=0 的对照：

- 保留 false：正文以 `Assistant:` 开头，共二十五个文本增量。
- 省略参数：直接生成中文口语回复，无角色名前缀，共二十九个文本增量。

对照产物：workspace/logs/20261118_qwen_thinking_ab_an72yp3h/summary.json
及两个原始 SSE 文件。两个聚焦回归测试通过，MiMo 默认行为保持不变。

仅重启网页服务，当前 UI PID63515，模型 PID37788 不变；
网址仍为 http://28.29.218.211:8080/。
当前日志：workspace/logs/20261118T172800Z_qwen_sse_y04h0fwm/ui.log，
原始 SSE 位于同目录 raw_sse，配置仍读取原启动快照。

重启后真实 WebSocket 单轮通过：二十九个文本增量、十一个音频块、
462000 字节 PCM、chat.done 和 tts.done 均收到。
首音频在探针开始后1.9189秒，Chat完成2.9857秒，TTS完成3.2562秒，
确认仍为流式重叠，不是全文生成后才进入 TTS。
正文无角色前缀或暴露的思考过程。探针按ACK推流且在首次Decode停止输入，
这些时间不是实时端点延迟指标。
产物：workspace/logs/20261118T154532Z_qwen_wpe3imxu/
single_turn_trnj5__6/live_summary.json、live_events.json、live_output.pcm。

这支持当前窄范围修改，但不保证历史出现的 `user` 单独输出已全部解决。
网页服务重启已清空旧连接历史，需用新会话复测原始场景。
