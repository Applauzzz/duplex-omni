# 内网 Demo 重载记录

日期：2026-11-09。节点业务IP：`28.29.217.68`。
这不是此前localhost/SSH节点`28.29.218.56`。

## 访问

页面：`http://28.29.217.68:8080/`。
WebSocket：`ws://28.29.217.68:8080/ws`。
供可达该节点的内网用户调试，不需要每人建立SSH隧道。
不是互联网公开服务，不是带TLS/鉴权/容量承诺的生产入口。

远端HTTP页面可以打开，但浏览器麦克风需安全上下文。沿用已使用的
独立Chrome测试profile策略，Mac示例：

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --user-data-dir=/tmp/chrome-duplex-intranet-21768 \
  --unsafely-treat-insecure-origin-as-secure=http://28.29.217.68:8080 \
  --new-window http://28.29.217.68:8080/
```

只能对这个受控demo origin使用该测试方式，不建议作为生产访问方案。
其他操作系统使用对应Chrome可执行路径和相同参数。无需Agent页、SDK、
Mac pairing code。正式多人访问应配置受信任HTTPS/WSS入口。

## 配置与归属

- 分支：`feature/svad-vaed-polling`；交付时使用包含本文档与轮询实现的提交，
  不是开发基线8352472。运行进程归属为下述November9快照，发布不重启服务。
- 仅重载普通应用；无`--agentic`。原MiMo PID6419、TP4/EP、8090保留。
- 主配置：`workspace/experiments/20261025_mimo_tts_integration/svad_config.json`。
- VAED模式chunk、窗口8000ms、audio200ms、AVAD静音256ms、
  不完整静音兜底128ms、历史30轮；TTS外部CosyVoice服务复用。
- 新运行目录：`workspace/logs/20261109_intranet_chunk_rzxilUYm`。
- 新应用PID60050，启动记录`svad-ui_chunk01_launch.json`。
- 旧应用PID35622已正常收到SIGINT退出，不再处理连接。

服务读取开发共享主配置；修改会影响新连接，应用代码/schema更改需要重载。
用户刷新网页再启动麦克风，旧连接不能保留历史。
页面仍是原调试控制台，包含视频控件/参数编辑；本次纯语音使用不启用摄像头。
未实施生产消息隔离或用户鉴权，不应将本demo当最终上线服务。

## 验证边界

应用就绪检查结果保存于运行目录`readiness.json`，检查页面、worklet、
health、defaults及带正确同源Origin的真实WS configure/reset。
该检查不提交音频，不代表实际远端网络、麦克风、播放或多用户容量验收。
实际远端用户仍需确认可达性并进行一轮语音测试。
