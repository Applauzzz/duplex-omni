  已确认范围

  - 用户明确要求本轮一并接入多轮 duplex；现有 Qwen 上下文管理、历史裁剪、VAD、播放 ACK、打断机制保持不变。仅当前轮 assistant 生成文本来源换成 MiMo，历史 assistant
  自然由现有机制记录 MiMo 实际回复。
  - MiMo 独立 OpenAI SSE 服务，TP4+EP，GPU 0–3；原始音频输入，enable_thinking=false。Qwen thinker/talker/code2wav 分配 GPU 4/5/6，GPU7留空。
  - Qwen thinker 保留真实多模态 prefill；不额外向 talker 注入 system embedding，不训练、不改权重。
  - 原 Qwen-only 链路保留作为对照；现有13个未提交的阶段1文件改动不得覆盖。不自动提交、重置或清理用户文件。
  - 当前节点 welm45-deepep-9，8×H20均空闲；启动联调前重新确认资源与默认路由 IP，不沿用旧地址。

  已核实接口与设计依据

  路径均相对 vllm-omni/：

  - vllm_omni/model_executor/stage_input_processors/qwen3_omni.py:370：chunk0缓存 prompt，待文本 embedding 到齐；后续 embed.decode
  为单token。原始生成首token不能直接当作已计算的 embedding。
  - vllm_omni/model_executor/models/qwen3_omni/qwen3_omni.py:866,1007,1171,1216：user多模态位置取layer24，文本取layer0；system和历史assistant不进入talker；当前assistant保
  持3个ChatML位置+4pad+BOS+首文本及原codec/speaker控制。
  - 同文件:1090：decode无文本时注入tts_eos，然后tts_pad；必须依赖上游未完成时的WAITING_FOR_CHUNK，不能以暂时缺字触发EOS。
  - vllm_omni/utils/mm_outputs.py:42、worker_v2/omni_ar_model_runner.py:356：hidden/embedding走inter-stage，不在普通客户端文字输出里；不能从OpenAI响应取prompt hidden。
  - engine/duplex_orchestrator.py:360,403,142,217：提交、预热下游、输出投影及取消/清理接入点。
  - models/qwen3_omni/duplex/plugin.py:221,299,379：现有qwen_messages快照已处理音频保留、整轮裁剪、空assistant与user合并，复用它构造两模型消息，不再维护另一套会话历史。
  - checkpoint index 已确认thinker.model.embed_tokens.weight位于model-00001-of-00015.safetensors，可只加载这张约594MiB的BF16表用于CPU
  lookup，不加载另一个Qwen模型、不对每个MiMo token执行thinker forward。

  推荐实现

  1. 每轮独立的异步桥接，驻留现有 Duplex orchestrator

  新增一个模型专属桥接模块（建议 vllm_omni/model_executor/models/qwen3_omni/duplex/mimo_bridge.py），集中管理：

  - MiMo异步SSE客户端、Qwen增量重分词与embedding lookup、prefill合并、chunk写入和请求取消。
  - 仅服务端配置的 MiMo endpoint/model；前端不能指定任意后端地址。配置启用后只替换相应 Qwen duplex 请求，普通Qwen-only部署不变。
  - 用现有session/epoch/turn/request_id绑定请求资源；SSE、等待prefill与写入均不阻塞scheduler/orchestrator事件循环。

  每轮执行：

  1. 从不可变的qwen_messages快照构造MiMo消息：同样的system、历史MiMo assistant文本和已保留user音频/文本/图片。音频转为input_audio WAV；仅MiMo音频轮加已验证的中性audio
  hint。不把hint塞入Qwen历史，不扩展视频能力。
  2. 提交Qwen thinker和启动MiMo SSE并行进行。MiMo max_tokens/temperature来自现有会话配置；Qwen
  thinker使用max_tokens=1作为prefill载体，丢弃其采样文字，不声称这是完全无sampling的新引擎路径。
  3. 将真实Qwen prompt层0/layer24、TTS特殊embedding及展开后的prompt IDs交给桥接；收到MiMo首个稳定Qwen token后发送talker首包。
  4. MiMo只输出正文delta.content；reasoning、工具调用与模型控制token不进入talker。SSE解析需处理网络拆包、多事件及Unicode，错误不得伪装正常EOS。

  2. thinker prefill转交与主chunk流单写入者

  修改 stage_input_processors/qwen3_omni.py：

  - 针对桥接标记的请求，按prompt长度积累真实prefill的层0/layer24，处理chunked-prefill。
  - 复用现有SharedMemoryConnector序列化，把prefill写入与request唯一绑定的私有桥接key；不发原生Qwen输出文字/正常{rid}_0_{chunk}流。CPU桥接是主thinker→talker
  chunk序列的唯一写入者。
  - 处理最终回调可能没有tensor的情况；在全部prompt行到齐时即可交付，不依赖首个Qwen生成token的后续forward。
  - 私有传输首次聚焦当前单机SHM部署；其他connector明确拒绝该模式，不假装已经支持跨节点RDMA。读取/清理由桥接持有，避免父进程退出回收共享内存。
  - 核查当前MRV2及原V1终止回调：桥接请求禁止原thinker结束生成主流finish sentinel；只在确有必要时对connector终止路径作窄范围修改。阶段0结束不等于MiMo文本结束。

  首包：embed.prefill = Qwen prompt embedding + MiMo首token的Qwen embedding；hidden_states.output保留真实prompt layer24（仅user多模态位置消费）；ids.prompt保留展开后ChatML
   IDs，ids.all与embedding行对应，保留TTS BOS/EOS/PAD及speaker/language。只需复用原生talker prefill，不引入MiMo hidden。

  后续：以Qwen token顺序发送embed.decode
  [1,2048]；统一单调chunk编号、无重复、无漏token。正常MiMo结束后flush剩余token，才发送meta.finished=true。空正文走无音频的正常结束并撤销预热下游，不用零向量凑首token。

  3. 增量分词与embedding

  - 进程内一次加载本地Qwen tokenizer及真实checkpoint embedding表，CPU lookup得到原生layer0向量，再沿原text_projection进入talker。
  - 按当前tokenizer真实normalizer/pretokenizer边界提交稳定token，保留可被续文改变的尾段与特殊token候选；不能依靠固定N字符或连续两次共同前缀宣称稳定。
  - 在流结束时flush，并验证已发+flush IDs与一次性Qwen编码一致（按既有normalization规则）。覆盖中文、英文、混合、数字、空白、组合Unicode与拆分的特殊token。
  - 严格稳定分词对长无分隔字符串可能缓冲至标点/EOS，单独记录等待时间；不通过改写文本或重新生成整句TTS隐藏该限制。

  4. 沿用 Duplex transcript、历史与取消

  修改 engine/duplex_orchestrator.py 和 models/qwen3_omni/duplex/plugin.py 的必要接缝：

  - Qwen原生stage0文字不投影；MiMo delta以相同request/fence进入现有runner输出mailbox，产生现有transcript事件，让现有历史/ACK机制记录MiMo文字。
  - stage0预填充完成、MiMo文本完成、stage2音频完成必须分开。音频轮仅stage2完成才能关闭语音轮；纯文本轮按MiMo完成收尾；空回复/错误不能留下WAITING请求。
  - 打断、reset、关闭会话、提交失败或stage错误时：先失效epoch/turn与bridge写入许可，取消MiMo HTTP流/任务、prefill等待和待发送数据，再沿现有路径abort
  thinker/talker/code2wav。确认MiMo服务已停止该断连请求，不只前端停止显示。
  - 每次await后校验请求仍存活，晚到旧字/旧音频不能进入下一轮。沿用现有播放ACK与截断规则，不借机开发新的文本音频对齐。
  - 复用现有realtime_web及instructions配置，不另建MiMo demo前端。

  5. 启动配置

  优先修改现有 workspace/scripts/start_duplex_service.sh 增加显式GPU绑定；必要的新联调配置放workspace/configs/，启用MiMo端点与bridge，继承已有duplex/VAD配置。

  - MiMo GPU0–3，8090；Qwen 4/5/6，沿用原后端8092、UI7865。
  - Qwen-only未启用bridge的路径保持原行为。MiMo失败不静默回退为Qwen文字。
  - Bash调用采用相对路径；长服务启动由受跟踪任务管理，TERM按已知进程组清理，不杀其他作业。日志/实验放workspace/logs/<日期>_mimo_qwen_bridge/与workspace/experiments/<日期>_
  mimo_qwen_bridge/。

  修改文件范围

  核心已有文件：
  - vllm-omni/vllm_omni/model_executor/stage_input_processors/qwen3_omni.py
  - vllm-omni/vllm_omni/engine/duplex_orchestrator.py
  - vllm-omni/vllm_omni/model_executor/models/qwen3_omni/duplex/plugin.py
  - vllm-omni/vllm_omni/config/stage_config.py（仅所需服务端配置）
  - workspace/scripts/start_duplex_service.sh

  必要新增：模型专属duplex/mimo_bridge.py、对应桥接测试与联调配置/实验脚本。优先扩展已有测试；不创建无关文档或通用框架。若runtime终止行为确需调整，限定在distributed/omni_c
  onnectors/model_runner/omni_connector_payload_transport.py/worker_v2/omni_data_plane.py已核实回调接缝，并增加回归测试。

  执行与验收顺序

  1. 保存工作区改动基线供diff核对，不提交；实现核心桥接和CPU测试。
  2. CPU测试：现有streaming helpers、duplex plugin/session
  runner/orchestrator测试，加prefill/ID行数、首token替换、decode顺序、最终EOS、空回复、SSE拆包、重分词、取消各时点及两个会话隔离。使用现有vendor
  pytest依赖；测试缺依赖或失败如实报告，不能跳过当成功。
  3. 协议对照：用Qwen同样的回复字符串回灌桥接，对比文本、token IDs、embedding与控制位置；原链路保留作语音对照。固定talker采样seed，不把随机波形差异判为协议错误。
  4. 新的集成验证：同时部署MiMo TP4+Qwen三阶段，固定中/英/数字/混合样例，保存MiMo正文、talker消费IDs、有效wav、结束原因及TTFT/TTFA分项。核对语音读的是MiMo回复，没有Qwen首
  字混入、漏读或早EOS；若无ASR工具用人工听测，不能只凭非空wav断言内容正确。
  5. 多轮duplex：同一会话历史确为MiMo回复；打断前/首包等待/朗读中取消，立即新轮及reset、断连、MiMo故障；无晚到输出、残留GPU请求或共享内存。
  6. 真streaming门槛：受控延迟MiMo流中，第一段有效音频必须早于MiMo DONE，且整轮talker/code2wav
  KV和codec流不重启。对实际中文样例记录稳定分词带来的缓冲，不以离线结果替代流式验收。

  本轮批准后按上述步骤实施，不再重复已完成的单MiMo独立冒烟；只运行与新桥接有关的回归和联调。