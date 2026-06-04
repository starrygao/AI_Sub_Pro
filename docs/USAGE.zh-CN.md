# 使用指南

语言：[English](USAGE.md) | [简体中文](USAGE.zh-CN.md)

AI Sub Pro 在本地运行，项目文件、API key、字幕导出文件和知识库数据都会保存在
用户自己的电脑上。

## 预编译安装包

可用的预编译安装包会随 GitHub Releases 发布。

- macOS 用户可以从 `v1.1.1` release 资产下载全部
  `AI_Sub_Pro_v1.1.1.dmg.part-*` 分片（`part-aa` 到 `part-ar`），运行
  `cat AI_Sub_Pro_v1.1.1.dmg.part-* > AI_Sub_Pro_v1.1.1.dmg` 合并后打开 DMG，
  将 **AI Sub Pro** 拖入 **Applications**。如果首次启动被 Gatekeeper 拦截，
  请右键应用并选择 **打开**。
- Windows 用户可以使用已发布的 Windows 安装包。当前 release 暂未附带预编译
  Windows 安装包；需要在 Windows 机器上运行 `build_win.bat` 从源码构建。

## 源码安装

环境要求：

- Python 3.10 或更高版本。
- Node.js 18 或更高版本。
- `ffmpeg` 和 `ffprobe` 需要在 `PATH` 中。
- 可选 ASR 后端：`mlx-whisper`、`faster-whisper` 或 `openai-whisper`。

```bash
git clone https://github.com/<your-user>/AI_Sub_Pro.git
cd AI_Sub_Pro

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt

npm install
npm run build:css
```

## 运行

```bash
./start.sh
```

如果浏览器没有自动打开，请访问 `http://127.0.0.1:18090`。

仅启动后端：

```bash
python3 app/main.py --headless
```

启动 Electron 外壳：

```bash
cd electron
npm install
npm run start
```

## 配置翻译 Provider

在应用的 **设置** 页面中配置至少一个翻译 provider：

- OpenAI 兼容 API key 和模型。
- Claude CLI：本机已安装并完成登录时可用。
- Codex CLI：本机已安装并完成登录时可用。

还可以配置：

- 显示语言：跟随系统、简体中文或 English。
- Whisper 模型和源语言。
- 目标字幕语言。
- 翻译批量大小和上下文窗口。
- 重复文本与语气词过滤。
- 用户修订记忆和本地口语库检索。
- 可选的翻译后 QA 自动修复。
- 用于预告片搜索的 TMDB API key。

## 处理本地视频

1. 在首页拖入视频，或粘贴本地视频路径。
2. 确认 ASR 源语言和目标字幕语言。
3. 点击 **开始**，或打开项目后使用 **一键处理**。
4. 在编辑器中审校原文和译文字幕行。
5. 导出翻译、双语或原文 `.srt` 字幕文件。
6. 当 `ffmpeg` 可用时，将字幕烧录到视频中。

如果视频已经包含文本字幕轨，AI Sub Pro 可以跳过 ASR，直接使用内嵌字幕作为源
时间轴。

## 预告片工作流

首页的 **预告翻译** 可以基于 TMDB 与 YouTube 元数据创建项目。

1. 按标题或 TMDB ID 搜索。
2. 选择匹配的电影、剧集、季或预告片。
3. 通过 `yt-dlp` 下载元数据和预告片媒体。
4. 像普通项目一样审校、翻译、导出和烧录字幕。

## 知识库

知识库页面用于保存本地翻译规则，帮助同一项目内保持译名一致：

- 角色姓名。
- 地点和组织。
- 品牌名称。
- 俚语和固定表达。
- 项目级风格规则。

翻译器会在处理字幕批次时把这些条目作为上下文。

## 翻译质量闭环

AI Sub Pro 可以围绕字幕编辑流程自动提升译名一致性和口语自然度：

- **自动知识库建议** 会检查项目元数据和字幕文本，提出角色、地点、组织、标题、
  固定表达和风格规则候选。建议会保存在项目目录的 `kb_suggestions.json` 中，
  等待你接受或拒绝。
- **翻译记忆** 会学习你在编辑器中保存的字幕修改。本地 SQLite 数据库会记录原文、
  机器初译和最终确认译文，后续翻译前优先检索相似案例。
- **本地口语库检索** 可以使用你自行导入的例句。OpenSubtitles、Tatoeba 等公开
  语料需要保留来源和 license 元数据后再导入，不会默认联网下载。
- **QA 报告** 会在翻译后写入项目目录：
  `translation_qa_report.json` 和 `translation_qa_report.md`。确定性检查包括
  漏译、英文残留、重复 ID、知识库术语缺失、字幕过长和环境音处理。
- **自动修复** 是可选项。启用后，应用只会把有问题的字幕行发回当前 provider 做
  定向修复，不会重翻全文。

本地运行确定性评测语料：

```bash
python3 -m app.evaluation.cli \
  --corpus tests/fixtures/golden_corpus/translation_quality_loop.json \
  --format markdown
```

默认评测命令只使用仓库内 fixture，不调用付费或联网翻译 provider。

## 数据位置

开发模式下，运行数据保存在 `./data`。

打包后的应用会把运行数据保存到用户的应用数据目录。也可以通过环境变量覆盖：

```bash
export AI_SUB_PRO_DATA_DIR=/absolute/path/to/runtime-data
```

不要提交运行数据、API key、生成媒体或模型缓存。

## 测试

```bash
pytest
```

测试覆盖 API 路由、任务调度、字幕解析、provider 契约、项目存储安全、翻译 QA、
评测指标和前端 JavaScript 行为。

## 常见问题

- **端口已被占用**：停止正在监听 `127.0.0.1:18090` 的 AI Sub Pro 进程。
- **媒体功能不可用**：确认 `ffmpeg` 和 `ffprobe` 在 `PATH` 中。
- **翻译失败**：确认所选 provider 已配置并登录。
- **首次 ASR 很慢**：本地 Whisper 模型可能需要下载。
- **字幕烧录失败**：使用支持字幕渲染的 `ffmpeg` 构建。
