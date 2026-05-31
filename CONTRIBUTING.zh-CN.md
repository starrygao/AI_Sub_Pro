# 贡献指南

语言：[English](CONTRIBUTING.md) | [简体中文](CONTRIBUTING.zh-CN.md)

欢迎贡献代码。请保持改动聚焦，并为行为变化补充测试。

## 本地设置

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
npm install
npm run build:css
pytest
```

## 贡献规范

- 不要提交运行数据、API key、下载媒体、构建产物或 ASR 模型文件。
- 保持面向用户的工作流本地优先，并默认采用安全设置。
- 字幕解析、项目存储行为、provider 错误和 API 变化需要添加回归测试。
- 前端改动需要更新覆盖相关状态变化的 JavaScript 测试。
- 提交信息应清楚说明本次改动影响的用户可见行为或安全问题。
