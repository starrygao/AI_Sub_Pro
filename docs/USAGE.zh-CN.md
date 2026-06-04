# 使用指南

语言：[English](USAGE.md) | [简体中文](USAGE.zh-CN.md)

AI Sub Pro 在本地运行，项目文件、API key、字幕导出文件和知识库数据都会保存在
用户自己的电脑上。

## 预编译安装包

可用的预编译安装包会随 GitHub Releases 发布。

- macOS 用户可以从 `v1.2.0` release 资产下载 `AI_Sub_Pro_v1.2.0.dmg` 和
  `AI_Sub_Pro_v1.2.0.dmg.sha256`，运行
  `shasum -a 256 -c AI_Sub_Pro_v1.2.0.dmg.sha256` 校验后打开 DMG，将
  **AI Sub Pro** 拖入 **Applications**。如果首次启动被 Gatekeeper 拦截，请
  右键应用并选择 **打开**。
- Windows 用户可以使用已发布的 Windows 安装包。当前 release 暂未附带预编译
  Windows 安装包；需要在 Windows 机器上运行 `build_win.bat` 从源码构建。

默认安装包是 base app build，不包含本地 Whisper 模型文件，也不包含 optional
ASR backend packages / 可选 ASR 后端包。面向离线使用的大包需要显式设置
`AISUBPRO_BUNDLE_LOCAL_ASR=1` 构建，并在 release notes 中标注为 optional ASR
package。

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
- 用于预告片搜索的 TMDB API key。

## ASR 模式

ASR 模式表达处理意图，而不是固定指定某一个后端：

- **速度优先** 会选择当前最快的本地后端。在 Apple Silicon 上通常是使用
  `large-v3-turbo` 的 `mlx-whisper`。
- **准确率优先** 会优先选择更大的模型，并在可用时选择支持 VAD 或 beam search
  的后端。
- **离线优先** 会优先使用已打包或已缓存的模型，并在需要下载模型时明确提示。

`/api/system-check` 会报告检测到的 ASR 后端、模型缓存状态和当前后端/模型推荐。
测试会模拟这些检查，不会下载模型。

源码运行时，可以在本地 Python 环境中安装可选 ASR 后端。打包版只有在维护者设置
`AISUBPRO_BUNDLE_LOCAL_ASR=1` 时，才会把 optional local ASR packages 和
`models/asr` 一起打进安装包；否则模型会在首次使用时下载，或从常规本地缓存读取。

## 处理本地视频

1. 在首页拖入视频，或粘贴本地视频路径。
2. 确认 ASR 源语言和目标字幕语言。
3. 点击 **开始**，或打开项目后使用 **一键处理**。
4. 在编辑器中审校原文和译文字幕行。
5. 导出翻译、双语或原文 `.srt` 字幕文件。
6. 当 `ffmpeg` 可用时，将字幕烧录到视频中。

如果视频已经包含文本字幕轨，AI Sub Pro 可以跳过 ASR，直接使用内嵌字幕作为源
时间轴。

## 工作流恢复

长时间运行的工作流会把结构化进度写入项目运行数据中的 `workflow_state.json`。
状态文件记录每个阶段、受限长度的分阶段日志、工作流停止时的失败阶段，以及可
用于恢复的最后一个已验证产物。

项目页面可以显示失败阶段、下载捕获的日志、重试失败阶段，或从最后一个已验证
产物继续处理。重试和继续处理会使用与正常处理相同的任务锁，因此同一项目同一
时间只能运行一个工作流操作。

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
项目页还可以根据 TMDB 元数据和当前字幕扫描建议词条。用户可以逐条审校建议，
编辑推荐译名或备注，然后把选中的词条加入项目知识库；不需要的建议可以拒绝，
之后不会反复提示。

翻译完成后，如果存在可用的 trace 数据，项目知识库面板会显示最近一次使用记录。
该记录说明哪些 KB 词条命中了源字幕，并被加入翻译上下文。

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

测试覆盖 API 路由、任务调度、字幕解析、provider 契约、项目存储安全和前端
JavaScript 行为。

## 翻译质量评测

修改 translator、provider 或知识库逻辑后，可以运行确定性的 golden corpus 评测：

```bash
mkdir -p build/evaluation
python3 -m app.evaluation.cli --corpus tests/fixtures/golden_corpus/milestone1.json --json-out build/evaluation/milestone1.json --markdown-out build/evaluation/milestone1.md
```

默认 milestone 语料使用仓库内已提交的候选输出，不会调用网络服务或付费翻译
provider。报告包含术语覆盖、行数对齐、漏翻、格式保留，以及供人工审校填写的
评分占位。

## 常见问题

- **端口已被占用**：停止正在监听 `127.0.0.1:18090` 的 AI Sub Pro 进程。
- **媒体功能不可用**：确认 `ffmpeg` 和 `ffprobe` 在 `PATH` 中。
- **翻译失败**：确认所选 provider 已配置并登录。
- **首次 ASR 很慢**：本地 Whisper 模型可能需要下载。
- **字幕烧录失败**：使用支持字幕渲染的 `ffmpeg` 构建。
