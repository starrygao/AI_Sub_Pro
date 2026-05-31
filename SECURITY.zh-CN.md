# 安全策略

语言：[English](SECURITY.md) | [简体中文](SECURITY.zh-CN.md)

AI Sub Pro 会在本地保存运行数据，包括通过界面配置的 API key。请不要提交
`data/`、日志、项目媒体、生成字幕或模型缓存。

## 报告安全问题

如果仓库启用了 GitHub Security Advisories，请优先通过该渠道私下报告安全问题。
如果未启用，请创建 issue，并只提供最小复现信息；不要包含密钥、私有媒体或个人
数据。

## 本地 API 暴露面

应用设计为在 localhost 上使用。默认情况下，CORS 只接受 loopback 浏览器来源。
修改 host 绑定、CORS、项目文件路径、文件上传处理和媒体下载行为时，请仔细审查
安全影响。
