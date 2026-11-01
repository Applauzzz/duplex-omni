当前 MiMo checkpoint 的 chat template 原生工具格式是：

  <tool_call><function=工具名>
  <parameter=参数名>参数值</parameter>
  </function></tool_call>

  当前 vLLM runtime 也注册了模型专用 parser：

  mimo

  因此 MiMo 8090 应增加：

  --enable-auto-tool-choice \
  --tool-call-parser mimo

  并保留现有：

  --reasoning-parser mimo

  完整关键参数类似：

  vllm serve /path/to/MiMo-V2.6-Flash-RL \
    --served-model-name mimo-v2.6-flash \
    --trust-remote-code \
    --reasoning-parser mimo \
    --enable-auto-tool-choice \
    --tool-call-parser mimo

  ## 启用后的标准链路

  SP + tools + history + current user audio/video
    -> MiMo 原生输出 tool call
    -> vLLM mimo parser
    -> OpenAI tool_calls delta
    -> RealtimeSession 执行工具
    -> tool output
    -> MiMo 最终回答

  当前已删除兼容层：

  - Tool Router
  - JSON tool envelope
  - XML recovery
  - malformed JSON-prefix recovery

  应用侧固定为：

  AgenticMiMoChatProvider(..., native_tool_calls=True)
