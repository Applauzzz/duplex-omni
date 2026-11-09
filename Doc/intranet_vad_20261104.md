# 新节点内网 VAD 部署

日期：2026-11-04。普通 VAD + MiMo + 外部 CosyVoice，不启用 agent、
SDK 工具、Mac 配对或后台 reasoning。原启动交接保留历史节点信息，
新节点以本记录为准。

## 地址与配置

- 本节点业务 IP：`28.29.217.68`，不是旧节点 `28.29.218.56`。
- 浏览器入口：`http://28.29.217.68:8080/`，不是 `/agent`。
- MiMo：`http://127.0.0.1:8090`，TP4 + EP，GPU 0-3。
- TTS：`http://29.213.195.135:8100`，外部 CosyVoice submit/poll 协议。
- 主配置目录：`workspace/experiments/20261025_mimo_tts_integration/`。
- 主配置：该目录下的 `svad_config.json`，直接读取，不是运行副本。
- 当前历史：`config.history_turns=30`；保留用户最新中文 `chat_prompt`。
- 原配置内 agent 专用字段保留，但普通路径不会启用工具。

当前运行目录：

```text
workspace/logs/20261104T105813Z_intranet_vad_bfvtKZxP/
```

其中 `*_launch.json` 记录真实 PID、进程组、命令和解释器，`*.log`
保存原始日志，`audio_probe_*` 保存本次独立验证结果。运行状态以新健康检查
和文末验收记录为准，不以“进程已经启动”替代验收。

## Mac 直连

不需要 SSH 隧道，但客户端必须有到该 IP/8080 的内网路由和访问权限。
普通 HTTP IP 页面涉及麦克风安全上下文，沿用独立 Chrome profile 的方式：

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --user-data-dir=/tmp/chrome-duplex-vad-20261104 \
  --unsafely-treat-insecure-origin-as-secure=http://28.29.217.68:8080 \
  --new-window http://28.29.217.68:8080/
```

打开后手动启动麦克风并允许权限，不会自动开始对话。这里的参数仅适用于
可信内网测试地址，不是 HTTPS 部署。其他内网用户可以使用同一地址；
其网络可达性和本机麦克风权限仍需分别验证。服务没有新增访问认证，
不应将该端口转发到公网。

## 运行命令

项目根：

```text
/mnt/geminihzceph/user_whynotzhliu/Omni/duplex-omni
```

本次先检查了 GPU/端口归属，八张 H20 空闲且没有 MiMo/VAD 服务，
才执行冷启动。重启前必须重新检查，不能重复占用正在运行的端口。

初始化：

```bash
cd /mnt/geminihzceph/user_whynotzhliu/Omni/duplex-omni
source /mnt/geminihzceph/user_whynotzhliu/my_envs/env.sh
conda activate omni
export ROOT="$PWD"
export RUNTIME="$ROOT/workspace/logs/20261101T_native_mimo_agent_081500/runtime"
export RUN="$(mktemp -d "$ROOT/workspace/logs/$(date -u +%Y%m%dT%H%M%SZ)_intranet_vad_XXXXXXXX")"
ln -s "$RUNTIME" "$RUN/runtime"
export PYTHONPATH="$RUN/runtime:$ROOT/vllm-omni"
export PYTHONDONTWRITEBYTECODE=1
```

runtime 使用当前源码和既有编译扩展，链接指向共享目录；不修改 editable
install。解释器是 `omni/bin/python`。这个版本的原生扩展名是
`vllm._C_stable_libtorch`，不是 `vllm._C`。保留已有版本不匹配警告，
最终以真实推理结果判断兼容性，不通过重装环境掩盖问题。

仅在 GPU 0-3 空闲且 MiMo 没有运行时，在第一个终端执行：

```bash
export CUDA_VISIBLE_DEVICES=0,1,2,3
python -B workspace/experiments/20261025_mimo_single_phase2/run_service.py \
  --run "$RUN" --role mimo --attempt cold01 --port 8090
```

第二个终端重新初始化环境，并将 `RUN` 设置为第一个终端生成的同一绝对目录：

```bash
python -B workspace/experiments/20261025_mimo_single_phase2/run_service.py \
  --run "$RUN" --role svad-ui --attempt intranet01 \
  --ui-host 28.29.217.68 --port 8080
```

该 runner 为普通页面选择 `svad_debug_server.py`，不加 `--agentic`；
使用脚本默认的主配置、MiMo8090和外部TTS8100。每次新启动创建新目录，
禁止覆盖既有 attempt 日志。只在所属终端 Ctrl-C 停止对应 supervisor，
不要宽泛停止 Python，也不要停止外部 TTS。

## 验证

```bash
curl --noproxy '*' --fail --max-time 10 http://28.29.217.68:8080/health
curl --noproxy '*' --fail --max-time 10 http://28.29.217.68:8080/defaults
curl --noproxy '*' --fail --max-time 10 http://127.0.0.1:8090/v1/models
```

页面、健康和 defaults 通过只证明服务端就绪。真实浏览器收音、播放和内网
客户端可达性需要用户确认；长回答流式验收要求首个 `tts.audio` 早于
`chat.done`，短回答不保证这一顺序。

## 本次验收结果

- MiMo 于 11:18:46 UTC 启动 API，应用启动完成。VAD supervisor8212 /
  child8467，MiMo supervisor5967 / child6419，两个服务保留运行。
- 最终内网地址 `/health`：`mimo=true`、`tts=true`，检查耗时12.4ms。
- `/`、`/capture_worklet.js`、`/defaults` 均200；defaults核实三十轮历史和
  最新中文 prompt；真实 WebSocket configure/音频输入通过。
- 同一真实回放中 VASD_SEM输出“有”，VAED输出“已”，随后正文分六次delta
  返回“三加四等于七。”；TTS返回71760字节24kHz PCM，音频保存为 `reply.wav`。
- 结果目录：上述运行目录下 `audio_probe_20261104T110535Z/`，包含
  `defaults.json`、`events.json`、`summary.json` 和 `reply.wav`。
- 这是冷启动第一轮，首PCM29.389s、文字完成29.198s，时间从回放开始计，
  包含输入与首次预热；不是常态延迟指标。短回复音频晚于文字完成，
  不作为长回复流式重叠验收。没有执行完整单元测试套件。
- 用户 Mac/其他内网客户端路由、浏览器权限、真实收音/播放和打断仍待确认；
  服务端自检不证明客户端可达。

## WebSocket 修复

用户11:41UTC的浏览器页面/健康请求已到达服务器，但 `/ws` 返回403。
普通 VAD 误用了 Mac 授权的 HTTPS/localhost 限制。已修正普通模式为
同源 HTTP/HTTPS 校验，跨站请求仍拒绝，agent/Mac安全策略不变。

只重载 VAD 为 `intranet02`，child35622，日志
`svad-ui_intranet02.log`；MiMo/TTS保持运行。一个聚焦端到端测试通过，
线上带真实浏览器Origin的WebSocket配置通过，恶意Origin403，
健康MiMo/TTS=true。刷新原地址并手动启动麦克风即可，无需换IP或SSH。
