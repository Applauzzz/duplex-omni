# Stage 5: MiMo VAD-Gated Video Input

建立时间：2026-10-30。

## 当前策略

视频不拥有独立状态机。浏览器只在发送音频 chunk 时，最多每秒附带一张
独立 JPEG：

```text
audio append
  audio: PCM
  video_frame: optional JPEG
```

Silence/Judge/Listen FSM、AVAD、VASD_SEM 和 VAED 都不读取视频内容。
`video_frame` 只是 audio chunk 的伴随字段：

- 候选音频未通过 VASD_SEM，伴随帧与该候选一起丢弃。
- 音频进入 PREFILL/CHUNK_PREFILL，伴随帧与同一个 accepted chunk 一起保留。
- DECODE 时，accepted chunks 中的 JPEG 按顺序组合为 vLLM 原生
  `video/jpeg` frame sequence。
- MiMo user content 顺序是 `video_url`、完整 `input_audio`、回答指令。
- reset、取消和会话历史沿用音频轮次边界，不维护视频专属时钟。
- 不启用摄像头时，协议与已有纯音频路径一致。

## 能力边界

这里的“随 PREFILL 放通”是应用层 chunk 所有权语义。当前 MiMo runner 仍把
PREFILL/CHUNK_PREFILL 缓冲在应用输入侧，模型实际执行发生在 DECODE/commit。
因此当前实现会在 DECODE 时一次性交付已放通的完整音频和视频，不声称已经实现
模型侧增量音视频 KV prefill。

## 传输与限制

- 浏览器摄像头为显式可选开关。
- 每次 audio flush 最多附一张 JPEG，采样间隔至少 1 秒。
- 单帧最大 512 KiB，最大 1920x1080 像素。
- 单轮最多选择 32 张 accepted 帧；超出时均匀下采样。
- 服务端以内联 `data:video/jpeg;base64,<frame1>,<frame2>,...` 发送给 MiMo，
  不经过短 MP4 容器转码。
- video metadata 不会转发给原有 realtime runner 的音频 append command。
- 普通会话不把摄像头帧写入 tracked 文件或实验目录。

## 已验证证据

### 原生模型视频能力

Artifact：

```text
workspace/logs/20261029T153733Z_mimo_single_phase2_64fdf1db/
  mimo_video_probe_20261030T083411Z_c03f134a/
```

三帧 MP4 顺序为红、绿、蓝。直接调用 MiMo 8090 返回 HTTP 200：

```text
红色、绿色、蓝色
```

该 MP4 仅证明模型原生视频能力。产品链路最初也使用短 MP4，但真实浏览器
单帧/短轮次触发 OpenCV 内存解码零帧，现已切换到 vLLM 有单测覆盖的
`video/jpeg` frame sequence。

### VAD 门控音视频链路

第一次 `video01` 探针发现 WebSocket 适配层遗漏 `video_frame`，保留失败证据：

```text
live_svad_probe_20261030T091105Z_bdfd5347/
```

修复后 `video02` 完整链路 artifact：

```text
live_svad_probe_20261030T125627Z_9a2a2c91/
```

结果：

- VASD_SEM 接受语音，进入 Listen。
- VAED 完成后 DECODE。
- `chat.started.video_frame_count = 8`。
- MiMo 最终回答：`视频中出现的三种主要颜色依次是红色、绿色和蓝色。`

### 短视频零帧修复

真实浏览器短轮次曾返回：

```text
Failed to apply MiMoOmniProcessor ...
tensor([], size=(0, 3, 360, 640))
```

当时产品链路把 accepted JPEG 帧转成短 MP4。vLLM 通过 OpenCV 的内存视频
接口读取该容器时，在部分单帧/短轮次上得到零帧；直接复现该底层接口还触发过
OpenCV segmentation fault。因此该问题不属于 FSM/VAD，也不是帧没有随音频放通。

当前产品链路改用 vLLM 原生且有单测覆盖的格式：

```text
data:video/jpeg;base64,<frame1>,<frame2>,...
```

修复后的 `video04` 证据：

```text
live_svad_probe_20261030T133852Z_70cfe560/  # 单帧，正常 chat.done
live_svad_probe_20261030T133926Z_77917ef8/  # 多帧，红/绿/蓝顺序正确
```

单帧和三帧 `video/jpeg` 也分别直连 MiMo 8090 返回 HTTP 200。

## 剩余验收

- 用户浏览器真实 camera permission 和预览。
- 真实人物/物体/运动画面质量。
- 长轮次帧下采样、延迟和内存统计。
- 视频历史对后续追问的实际质量。
- 如需模型侧实时音视频 KV prefill，扩展 runner/model port；不修改 FSM。
