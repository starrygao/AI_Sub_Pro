# 发布说明

语言：[English](RELEASE_NOTES.md) | [简体中文](RELEASE_NOTES.zh-CN.md)

## v1.1.0 - 显示语言选项

这个版本加入首个公开的多语言界面控制，并刷新了 macOS 打包版本。

主要内容：

- 在设置页新增 **显示语言**，支持 **跟随系统**、**简体中文** 和 **English**。
- 界面会将所选语言应用到导航、设置、状态标签、常见工作流文本和系统提示。
- 如果旧配置中存在不支持的显示语言，会自动恢复为 `auto`；设置 API 也会拒绝
  不支持的取值。
- README 和使用文档已同步补充英文与简体中文的显示语言说明。

质量验证：

- 完整测试套件已通过：`764 passed`。
- 发布文件已扫描，避免包含本地运行数据、构建缓存或个人账号标识。

安装包：

- 已为 macOS 用户附加 `AI_Sub_Pro_v1.1.0.dmg`，并提供对应的 `.sha256`
  校验文件。
- Windows 安装包需要在 Windows 机器上运行 `build_win.bat` 生成；当前 release
  暂未附带预编译 Windows 安装包，请先使用源码安装。

## v1.0.0 - 首个开源版本

AI Sub Pro 已作为 MIT 许可的本地优先字幕工作流工具公开发布。

主要内容：

- 本地 FastAPI 后端，支持浏览器和 Electron/pywebview 前端。
- 本地项目存储，用于保存上传视频、字幕、导出文件和设置。
- 通过 `mlx-whisper`、`faster-whisper` 或 `openai-whisper` 支持 ASR。
- 通过 OpenAI 兼容接口、Claude CLI 或 Codex CLI 进行翻译。
- 字幕编辑器支持翻译、双语和原文 SRT 导出。
- 知识库上下文支持人名、地点、品牌、俚语和风格规则。
- 支持 TMDB 与 YouTube 预告片项目工作流。
- 支持 `ffmpeg` 字幕烧录输出。
- 测试覆盖后端 API、项目存储安全、任务调度、provider 行为、字幕解析和前端
  JavaScript。

开源准备：

- 运行数据、构建产物、模型缓存和本地项目媒体均已从公开仓库排除。
- `.env.example` 和 `config.example.json` 记录了安全配置方式。
- 包含安全、贡献和第三方声明文件。

安装包：

- 已为 macOS 用户附加 `AI_Sub_Pro_v1.0.0.dmg`，并提供对应的 `.sha256`
  校验文件。
- Windows 安装包需要在 Windows 机器上运行 `build_win.bat` 生成；当前 release
  暂未附带预编译 Windows 安装包，请先使用源码安装。
