# 发布说明

语言：[English](RELEASE_NOTES.md) | [简体中文](RELEASE_NOTES.zh-CN.md)

## Unreleased - 翻译质量评测与知识库审校

这个尚未发布的 milestone 记录确定性评测流程和新的知识库审校工具。本
unreleased milestone 未附带新的应用安装包或 DMG。

主要内容：

- 新增 `python3 -m app.evaluation.cli`，用于基于 golden corpus 生成确定性的
  翻译质量报告，不调用网络服务或付费 provider。
- 新增项目知识库建议审校流程，可根据 TMDB 元数据和当前字幕生成建议词条，并
  支持编辑、接受和拒绝。
- 新增翻译过程中的 KB 使用 trace 记录，并通过项目 API 和前端面板展示可用的
  最近一次 KB 命中情况。

质量验证：

- 确定性评测 CLI 已通过，并为 7 个用例写出
  `build/evaluation/milestone1.json` 和 `build/evaluation/milestone1.md`。
- milestone 聚焦测试已通过：`109 passed in 1.66s`。
- 完整测试套件已通过：`838 passed in 45.70s`。

## v1.1.1 - 知识库注入修复

这个补丁版本修复真实翻译流程中的项目知识库 v2 注入路径。

主要内容：

- 翻译流水线现在会把已加载的项目元数据传入 `SubtitleTranslator`，因此知识库
  可以在真实工作流中使用 TMDB ID、项目名、标题、角色和剧情背景进行匹配。
- 项目专属术语和风格要求现在会应用到手动翻译、完整工作流翻译和预告片翻译，
  不再只在独立 prompt 构造测试中生效。
- 新增集成测试，验证项目元数据确实传到翻译器，防止这条接线路径再次回归。

质量验证：

- 完整测试套件已通过：`757 passed`。
- 前端 CSS 构建、Python 编译检查和 release 合并检查均已通过。

安装包：

- macOS DMG 以分片 release 资产提供：
  `AI_Sub_Pro_v1.1.1.dmg.part-aa` 到 `AI_Sub_Pro_v1.1.1.dmg.part-ar`。
- 使用 `cat AI_Sub_Pro_v1.1.1.dmg.part-* > AI_Sub_Pro_v1.1.1.dmg` 合并
  DMG，然后用 `AI_Sub_Pro_v1.1.1.dmg.sha256` 校验完整文件。分片校验值见
  `AI_Sub_Pro_v1.1.1.dmg.parts.sha256`。
- Windows 安装包需要在 Windows 机器上运行 `build_win.bat` 生成；当前 release
  暂未附带预编译 Windows 安装包，请先使用源码安装。

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
