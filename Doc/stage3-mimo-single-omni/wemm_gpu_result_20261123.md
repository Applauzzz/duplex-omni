# WeMM GPU 移植验收补充

这是此前发布的 `wemm_port_20261123.md` 的新增结果，不覆盖历史快照。
最终测试目录为 `workspace/logs/20261123T090228Z_wemm_port_f3fx8aht`。

TP2 BF16 权重加载、音频 profiling、文字/真实 WAV 流式回复和一 token
候选 logprobs 均通过。文字六个增量，音频七个增量；
分类返回“有”，同时提供“有/无”logprobs，margin 为 5.125。
测试正常退出 0，GPU 4/5 显存归零，现有公开 MiMo 服务不变。

额外适配了本地 cache 构造参数、音频 dummy，以及缺少 librosa 时使用
scipy 重采样的 WAV/FLAC 路径。未安装共享依赖、修改 checkpoint 或提交推送。
视频等格式仍需可用的媒体解码依赖，未完成视频验收。

后续单独接入应用 backbone、真实 tokenizer 分类 ID 和多 token 中断标记，
验证 VASD/VAED、历史、取消、TTS 重叠及语义质量。
