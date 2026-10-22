# VAD 配置的暴露与调整

## 1. 背景：为什么需要这个改动

原来 VAD 参数只能硬编码在前端 JS 里（`qwen3_turn.js` 的 `initialMessages()` 中写死的
`turn_detection` 对象），服务端无法覆盖。这一轮把它做成了可以从 deploy config 控制的默认值。

## 2. 三层优先级

**客户端 `session.update` 的显式值 > deploy config 的 `server_vad_defaults` > 代码硬编码兜底值**

"是否开启 VAD"（`turn_detection` 是否为 `null`）**始终由客户端决定**，deploy config 只影响"已开启
VAD 时各字段的默认值"。这样设计是为了不剥夺前端的控制权，同时让运维能在不碰前端代码的情况下调整
端点检测（endpointing）。

## 3. 配置文件

`workspace/configs/demo_vad.json`（JSON 格式的 deploy config）：

```json
{
  "_readme": ["...说明文字，不会被加载..."],
  "base_config": "../../vllm-omni/vllm_omni/deploy/qwen3_omni_moe.yaml",
  "session_mode": "duplex",
  "stages": [{ "stage_id": 0, "limit_mm_per_prompt": { "audio": 4, "image": 8 } }],
  "duplex_session": {
    "server_vad_model_path": null,
    "server_vad_defaults": {
      "threshold": 0.95,
      "prefix_padding_ms": 300,
      "silence_duration_ms": 500,
      "min_speech_duration_ms": 96,
      "create_response": true,
      "interrupt_response": true
    },
    "max_sessions": 1,
    "idle_ttl_s": 300.0,
    "disconnect_grace_s": 30.0,
    "max_pending_input_bytes_per_session": 16777216,
    "max_pending_turns_per_session": 4,
    "warmup_frames": 0
  }
}
```

**注意 `threshold` 当前是 `0.95`**，这是排查过程中被人改过的，灵敏度很低（接近 1 才判定为语音）。
如果要恢复默认灵敏度请改回 `0.5`。

### 几个容易踩的点

- `base_config` 是相对路径，相对于**配置文件所在目录**。`workspace/configs/` 到
  `vllm-omni/vllm_omni/deploy/qwen3_omni_moe.yaml` 是 `../../vllm-omni/...`。
- `duplex_session` 下**不能放说明性的键**。这一整段会被 `**kwargs` 原样传给
  `DuplexSessionRuntimeConfig(**...)` 构造函数，未知键会报 `TypeError: unexpected keyword argument`。
  说明文字只能放在顶层的 `_readme`（顶层键不会被传进任何 dataclass）。
- `.json` 能被 `--deploy-config` 直接接受，不需要改加载代码：`OmegaConf.load()` 按文件内容解析，
  JSON 是 YAML 的子集。

## 4. `duplex_session` 字段说明

| 字段 | 含义 |
|---|---|
| `server_vad_model_path` | `null` = 自动找 HF 缓存里的 `istupakov/silero-vad-onnx` 的 `silero_vad.onnx`，找不到回退到 pip 的 silero-vad（torch 后端）。显式配了路径但文件不存在或缺 ONNX Runtime 会直接报错，不静默回退 |
| `server_vad_defaults` | VAD 调参默认值，见下 |
| `max_sessions` | 并发 duplex 会话上限。**改大后必须重启三阶段后端才生效**。当前是 1，意味着你和同事不能同时用 |
| `idle_ttl_s` | 空闲会话回收时间（秒），`null` 表示永不因空闲回收 |
| `disconnect_grace_s` | WebSocket 断线后的宽限期（秒），期间可 `session.resume` |
| `max_pending_input_bytes_per_session` | 单会话未提交输入缓冲上限（字节） |
| `max_pending_turns_per_session` | 单会话排队轮次上限 |
| `warmup_frames` | 启动预热静音帧数，`0` 表示不预热（音频主导模型） |

### `server_vad_defaults` 合法键

对应 Realtime 协议 `turn_detection` 的 `server_vad` 字段，不含 `type`：

| 键 | 约束 |
|---|---|
| `threshold` | `> 0.15` 且 `<= 1` |
| `prefix_padding_ms` | 非负数 |
| `silence_duration_ms` | 非负数 |
| `min_speech_duration_ms` | 非负数 |
| `create_response` | 布尔 |
| `interrupt_response` | 布尔 |

校验在 `vllm_omni/config/stage_config.py` 的 `_validate_server_vad_defaults()`，配置写错会在启动时
直接报 `ValueError`，不会静默忽略。

## 5. 配置传递链路

```
deploy YAML/JSON  duplex_session: {...}
  → stage_config.py: DuplexSessionRuntimeConfig(**raw_dict["duplex_session"])
  → DeployConfig.duplex_session
  → duplex_orchestrator.py: duplex_session_config=...
  → DuplexSessionManager(runtime_config=...)
        │
        ├─ 会话创建：DuplexOmni.open_session()
        │     → _resolve_session_config(..., server_vad_defaults=self.duplex_session_config.server_vad_defaults)
        │     → DuplexSessionConfig.from_realtime(config, model=..., server_vad_defaults=...)
        │     → normalize_turn_detection_session_payload(payload, defaults=server_vad_defaults)
        │
        └─ session.update：DuplexSessionControl.on_session_update()
              → PendingTurnDetectionUpdate.prepare(payload, backend_provider=..., defaults=self._server_vad_defaults())
              → normalize_turn_detection_session_payload(payload, defaults=...)
```

VAD backend（`SileroVADBackendProvider`）在 `DuplexSessionManager.__init__()` 里构造一次，
所有会话共享，不是每会话新建（ONNX 后端无状态）。

## 6. 引擎侧共享的 VAD 实例

`SileroVADBackendProvider` 在 `DuplexSessionManager.__init__()` 中构造一次，所有会话共享
（ONNX 后端无状态），不是每会话新建。

## 7. 前端对应的三种模式

`server.py` 的 `--adapter` 决定前端行为：

| 模式 | 说明 |
|---|---|
| `--vad`（默认使用） | 引擎侧 server_vad 自动断句，`barge_in_on_speech` 自动打断 |
| `--gate`（本轮新增） | `turn_detection: null`，手动 Open gate / Close gate 提交，Interrupt 手动打断。适合脚本化复现 |
| `--stt` | 半双工，说话后按 Send turn |

## 8. 安全/容量提醒

- **服务没有任何鉴权**，任何能访问该端口的人都能用。
- `max_sessions=1`：同一时间只有一个人能用。要多人并发需要改配置并重启后端。
