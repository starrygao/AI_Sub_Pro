# 发布说明

语言：[English](RELEASE_NOTES.md) | [简体中文](RELEASE_NOTES.zh-CN.md)

## v1.2.2 - 扩展内置口语库

主要内容：

- 内置合成 phrase pack 从 3 个包 / 60 条扩展到 12 个包 / 600+ 条。
- 新增西语、法语、德语到简体中文 starter pack。
- 新增英语医疗、犯罪/刑侦、职场题材包。
- 短语检索现在支持 preferred tags，会根据项目 metadata 推断题材并对匹配例句做
  轻量加权，再注入翻译 prompt。
- 口语库 prompt 片段会显示 pack tags，trace 数据也会保留 pack id 和 tags。
- 新增本地 phrase-pack 导入 CLI，默认要求 source、license 和语言对元数据，避免
  导入公开语料时丢失来源/许可信息。

质量验证：

- 完整测试套件已通过：`931 passed in 68.49s`。
- 新增回归测试，覆盖生成器漂移、导入工具元数据校验、内置包规模、多语种检索、
  题材标签加权，以及题材 prompt 注入。

安装包：

- 已为 macOS 用户附加 `AI_Sub_Pro_v1.2.2.dmg`，并提供对应的
  `AI_Sub_Pro_v1.2.2.dmg.sha256` 校验文件和 `release-size-report.json`。
- 附带的 `.sha256` 文件和 `release-size-report.json` 与 DMG 来自同一次
  GitHub Actions 构建。
- 附带的 macOS 安装包是 base app build，不包含本地 Whisper 模型文件，也不包含
  optional ASR backend packages / 可选 ASR 后端包。
- Windows 安装包需要在 Windows 机器上运行 `build_win.bat` 生成；当前 release
  暂未附带预编译 Windows 安装包，请先使用源码安装。

## v1.2.1 - 内置口语包与翻译完成状态修复

主要内容：

- 新增英语、日语、韩语到简体中文的内置合成字幕口语 starter pack。
- 应用启动时会按 pack 版本自动导入本地 SQLite 口语库，打包后的安装版不再需要
  手动准备这些基础例句。
- 口语包导入会保留 pack id、版本、标签、来源和 license 元数据，并避免重复启动
  产生重复行。
- 项目详情和项目列表读取时会叠加当前 scheduler 进度，避免前端轮询时被旧的
  `project.json` 进度覆盖。
- 翻译完成统计会忽略 `[Music]` 这类可留空的环境音描述行，并在翻译结束时持久化
  最终进度和状态字段。

质量验证：

- 完整测试套件已通过：`926 passed in 54.80s`。
- 新增回归测试，覆盖 pack 幂等导入、新版本补充导入、内置 pack 发现、日语/韩语
  检索分词，以及翻译 prompt 注入。
- 新增集成测试，覆盖环境音描述行完成统计和运行时进度合并。

安装包：

- 已为 macOS 用户附加 `AI_Sub_Pro_v1.2.1.dmg`，并提供对应的
  `AI_Sub_Pro_v1.2.1.dmg.sha256` 校验文件和 `release-size-report.json`。
- 附带的 `.sha256` 文件和 `release-size-report.json` 与 DMG 来自同一次
  GitHub Actions 构建。
- 附带的 macOS 安装包是 base app build，不包含本地 Whisper 模型文件，也不包含
  optional ASR backend packages / 可选 ASR 后端包。
- Windows 安装包需要在 Windows 机器上运行 `build_win.bat` 生成；当前 release
  暂未附带预编译 Windows 安装包，请先使用源码安装。

## v1.2.0 - 质量评测、工作流恢复、字幕编辑器与发布流水线

这个版本把 v2 升级工作作为新的 macOS 安装包发布。它新增确定性质量评测、知识库
审校工具、ASR 意图模式、可恢复的长任务工作流、专业字幕编辑能力，以及可重复的
release pipeline。

主要内容：

- 新增字幕编辑器质量检查、合并、批量查找/替换、导出警告、键盘友好控制，以及
  便于快速审校的 timeline strip。
- 新增项目列表筛选、分组设置锚点，以及更明确的 provider、ASR、导出和网络错误
  下一步处理提示。
- 新增 release pipeline 文档，覆盖 `v*` tag trigger、dry-run release
  preparation、checksum 校验和 size report 检查。
- 将基础应用安装包与 optional local ASR package / 可选本地 ASR 包拆分。macOS
  和 Windows 默认打包不再包含本地 ASR 模型或后端；只有设置
  `AISUBPRO_BUNDLE_LOCAL_ASR=1` 时才会打包。
- macOS DMG 构建在生成 DMG 后，如果 Python 可用，会运行 release preparation
  helper，生成 checksum 文件和 `release-size-report.json`。
- 新增 `python3 -m app.evaluation.cli`，用于基于 golden corpus 生成确定性的
  翻译质量报告，不调用网络服务或付费 provider。
- 新增项目知识库建议审校流程，可根据 TMDB 元数据和当前字幕生成建议词条，并
  支持编辑、接受和拒绝。
- 新增翻译过程中的 KB 使用 trace 记录，并通过项目 API 和前端面板展示可用的
  最近一次 KB 命中情况。
- 新增面向意图的 ASR 模式，支持速度优先、准确率优先和离线优先，并根据检测到
  的本地后端和模型缓存状态给出后端/模型推荐。
- 新增结构化工作流状态、受限长度的分阶段日志、失败阶段展示、日志下载、重试，
  以及从最后一个已验证产物继续处理。

质量验证：

- 确定性评测 CLI 已通过，并为 7 个用例写出
  `build/evaluation/milestone1.json` 和 `build/evaluation/milestone1.md`。
- v2 聚合合并验证已通过：`902 passed in 104.00s`。
- release 分支验证已通过：`903 passed in 118.10s`。
- 打包脚本检查已通过：`31 passed in 0.16s`。
- 本地 v1.2.0 DMG 已使用 `AISUBPRO_BUNDLE_LOCAL_ASR=0` 构建通过，且
  `hdiutil verify dist/AI_Sub_Pro_v1.2.0.dmg` 报告 checksum 有效。
- v2 合并前 GitHub Actions release dry-run validation 已通过。

安装包：

- 已为 macOS 用户附加 `AI_Sub_Pro_v1.2.0.dmg`，并提供对应的
  `AI_Sub_Pro_v1.2.0.dmg.sha256` 校验文件和 `release-size-report.json`。
- tag 前本地 release artifact 校验记录 SHA256
  `e076b9776cccdcaf04051d863457b9d401addf6ea14417a265b55b31b97ac253`，大小
  `88,518,339` bytes。
- 附带的 macOS 安装包是 base app build，不包含本地 Whisper 模型文件，也不包含
  optional ASR backend packages / 可选 ASR 后端包。
- Windows 安装包需要在 Windows 机器上运行 `build_win.bat` 生成；当前 release
  暂未附带预编译 Windows 安装包，请先使用源码安装。

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
