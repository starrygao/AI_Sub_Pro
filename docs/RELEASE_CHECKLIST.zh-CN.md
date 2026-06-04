# 发布检查清单

语言：[English](RELEASE_CHECKLIST.md) | [简体中文](RELEASE_CHECKLIST.zh-CN.md)

发布 GitHub Release 前使用这份清单。

## 触发方式

- Release tag 使用 `v*` 格式，例如 `v1.2.0`；release workflow 会通过这个
  tag trigger 进入正式发布路径。
- 打 tag 前可以用 `workflow_dispatch` 手动执行 dry run，先验证发布流程。
- Pull request 应保持在 dry-run 路径，并使用 `--allow-empty`，这样不需要真实
  构建产物也能验证 release preparation。

## 打包策略

- 默认安装包是 base app package：包含应用、前端资源和 ffmpeg 二进制，但不会
  打包本地 Whisper 模型，也不会收集 optional ASR / 可选 ASR 后端包。
- 只有在明确要制作更大的离线包时，才设置 `AISUBPRO_BUNDLE_LOCAL_ASR=1`。该选项
  会打包 `models/asr`，并收集已安装的可选本地 ASR 后端，例如
  `faster-whisper`、`mlx-whisper` 或 `openai-whisper`。
- Release notes 中要说明每个资产是基础包，还是 optional local ASR package。

## 验证

- 发布前运行聚焦打包测试：
  `python3 -m pytest -q tests/test_packaging_scripts.py`。
- 运行 release dry run：
  `python3 tools/release/prepare_release.py --dist-dir dist --output dist/release-size-report.json --checksum-dir dist --allow-empty`。
- 构建 DMG 或其他资产后，用 `shasum -a 256 -c <artifact>.sha256` 或等价工具进行
  checksum / SHA-256 校验。
- 上传前检查 `dist/release-size-report.json`，确认资产名称和包体大小符合预期。

## 发布

- 只有在测试、dry run、checksum 校验和 size report 检查都通过后，才推送 `v*`
  tag。
- 上传来自同一个 `dist` 目录的 DMG、checksum 文件和 size report。
- 如果需要分片资产，请发布分片 checksum，并在 release notes 中写明合并命令。
