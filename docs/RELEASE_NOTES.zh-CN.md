# 发布说明

语言：[English](RELEASE_NOTES.md) | [简体中文](RELEASE_NOTES.zh-CN.md)

## v1.3.20 - 原生拖拽事件透传修复

主要内容：

- 拖拽区域不再阻断 Finder drop 事件冒泡，让 pywebview 原生桥接能收到事件并解析本地路径。
- “未获得视频本地路径”提示改为延迟兜底；如果原生桥接及时返回真实路径，会取消该提示，避免导入前误报失败。

质量验证：

- 本地目标测试已通过：`81 passed`。
- 本地安装包目标：`AI_Sub_Pro_v1.3.20.dmg`。

安装包：

- `AI_Sub_Pro_v1.3.20.dmg` 是本 release line 的 macOS 安装包名称。

## v1.3.19 - 原生文件拖拽桥接

主要内容：

- 新增 pywebview 原生拖拽桥接，让 macOS Finder 拖入文件时能把真实本地路径传给导入流程。
- 原生拖拽路径复用现有的单视频和批量视频前端处理逻辑，不再依赖浏览器层直接暴露文件路径。

质量验证：

- 本地目标测试已通过：`80 passed`。
- 本地安装包目标：`AI_Sub_Pro_v1.3.19.dmg`。

安装包：

- `AI_Sub_Pro_v1.3.19.dmg` 是本 release line 的 macOS 安装包名称。

## v1.3.18 - 桌面拖拽导入稳定性

主要内容：

- 桌面拖拽现在会先把 Finder 的 `file://` 数据解析为本地视频路径，再创建项目。
- 如果桌面壳拿不到拖入视频的本地路径，界面会拒绝大文件上传兜底，并提示使用文件选择器。
- 拖拽区域会拦截拖拽后的后续点击事件，避免误打开原生文件选择器。

质量验证：

- 本地目标测试已通过：`67 passed`。
- 本地安装包目标：`AI_Sub_Pro_v1.3.18.dmg`。

安装包：

- `AI_Sub_Pro_v1.3.18.dmg` 是本 release line 的 macOS 安装包名称。

## v1.3.17 - 自动专业质量闭环

主要内容：

- 专业模式现在是默认自动路径：自动知识库候选只作为翻译软提示，不再作为翻译前人工
  审校门槛。
- 新增策展古生物术语、安全的自动科学名多数派归一、稳定短地点/专名锚点识别。
- 质量报告界面改为建议继续自动返工或暂缓交付，不再提示人工确认。

质量验证：

- 本地目标测试已通过：`175 passed`。
- 本地安装包目标：`AI_Sub_Pro_v1.3.17.dmg`。

安装包：

- `AI_Sub_Pro_v1.3.17.dmg` 是本 release line 的 macOS 安装包名称。

## v1.3.16 - 历史字幕批量润色

主要内容：

- 扩展括号非对白提示识别，覆盖打字、偷笑/咯咯笑、亲吻声、玻璃破碎、翅膀扑动、
  海浪拍岸、含混广播等字幕说明。
- 使用当前 QA 自动返工链路刷新并润色本机已有翻译 SRT 输出。
- 本机已有最终翻译项目已全部通过阻塞质量门：`26 / 26` 通过，剩余阻塞问题为 `0`。

质量验证：

- 本地目标测试已通过：`118 passed`。
- 历史字幕润色共完成 `934` 条模型重点返工，并应用 `34` 条确定性非对白清理。
- 历史报告剩余项均为非阻塞提醒：`45` 条科学名一致性提醒、`73` 条专名提醒。
- 本地安装包目标：`AI_Sub_Pro_v1.3.16.dmg`。

安装包：

- `AI_Sub_Pro_v1.3.16.dmg` 是本 release line 的 macOS 安装包名称。

## v1.3.15 - 括号音效提示清理

主要内容：

- 翻译后处理现在会删除译文对白里夹带的括号音效 / SDH 提示，例如
  `[笑声]`、`[手机振动]`、`（紧张音乐）`，同时保留 `[亨利]` 这类说话人标签。
- QA 现在能识别方括号和圆括号包裹的非对白提示，包括音乐符号、语言提示、撞击声、
  呼吸/叹气、电话、门、天气和动物叫声等。
- 已刷新本机历史项目输出：翻译 SRT 文件中待清理的括号音效提示命中数为 `0`。

质量验证：

- 本地目标测试已通过：`118 passed`。
- 历史输出 dry-run 已验证：`26` 个本机已翻译项目中待清理括号音效提示为 `0` 条。
- 本地安装包目标：`AI_Sub_Pro_v1.3.15.dmg`。

安装包：

- `AI_Sub_Pro_v1.3.15.dmg` 是本 release line 的 macOS 安装包名称。

## v1.3.14 - SRT 质检提醒刷新

主要内容：

- SRT 解析现在会保留字幕块内部换行，避免已经换行的字幕在复检时被误判为一行过长。
- `♪` 这类纯音乐符号行会被视为非对话音效，不再误报缺译。
- 确定性后处理会在 QA / 导出前清空整条都是音效说明的译文，包括多行音效说明。
- 已刷新本机 S02E07 项目的 QA 报告和导出字幕，报告中不再有剩余提醒。

质量验证：

- 本地目标测试已通过：`116 passed`。
- S02E07 QA 报告已验证为 `0` 个问题、`0` 个警告，导出字幕音乐符号命中数为 `0`。
- 本地安装包目标：`AI_Sub_Pro_v1.3.14.dmg`。

安装包：

- `AI_Sub_Pro_v1.3.14.dmg` 是本 release line 的 macOS 安装包名称。

## v1.3.13 - 专名一致性自动统一

主要内容：

- 新增保守的翻译后专名统一 pass：只有在能安全抽取出明确多数译法时，才会统一少数译法。
- 翻译质量保存流程会在确定性专名统一后重新运行 QA，让后续报告反映清理后的结果。
- 已审校并更新本机已有项目输出里的专名/术语一致性问题。

质量验证：

- 本地目标测试已通过：`56 passed`。
- 已验证现有导出字幕音乐符号命中数为 `0`，报告中剩余
  `proper_name_inconsistent` 条目为 `0`。
- 本地安装包目标：`AI_Sub_Pro_v1.3.13.dmg`。

安装包：

- `AI_Sub_Pro_v1.3.13.dmg` 是本 release line 的 macOS 安装包名称。

## v1.3.12 - 字幕音乐符号清理

主要内容：

- 最终 SRT 写入器现在会从导出字幕里删除 `♪`、`♫`、`♬`、`🎵`、`🎶`
  这类音乐装饰符号。
- 翻译提示词明确要求 provider 不要在译文里输出这些音乐装饰符号。

质量验证：

- 本地目标测试已通过：`111 passed`。
- 已清理现有项目导出字幕，并验证最终输出 SRT 文件中音乐符号命中数为 `0`。
- 本地安装包目标：`AI_Sub_Pro_v1.3.12.dmg`。

安装包：

- `AI_Sub_Pro_v1.3.12.dmg` 是本 release line 的 macOS 安装包名称。

## v1.3.11 - 质量门槛提醒分级

主要内容：

- 报告型推断一致性提醒不再阻塞项目交付，也不会让项目停在“待质量确认”。
- QA 报告摘要现在区分阻塞问题和报告型提醒，并据此计算未解决位置。

质量验证：

- 本地目标测试已通过：`87 passed`。
- 本地安装包目标：`AI_Sub_Pro_v1.3.11.dmg`。

安装包：

- `AI_Sub_Pro_v1.3.11.dmg` 是本 release line 的 macOS 安装包名称。

## v1.3.10 - 批量文件夹翻译

主要内容：

- 首页来源模式新增批量文件夹入口，可递归扫描本地视频文件。
- 批量任务复用现有项目创建和 `start-full` 工作流，并用一次任务设置应用到全部视频。
- 桌面版新增原生文件夹选择器，用于批量导入。

质量验证：

- 本地目标测试已通过：`108 passed`。
- 本地安装包目标：`AI_Sub_Pro_v1.3.10.dmg`。

安装包：

- `AI_Sub_Pro_v1.3.10.dmg` 是本 release line 的 macOS 安装包名称。

## v1.3.9 - 翻译质量流程加固

主要内容：

- 自动知识库建议现在会进入翻译上下文，不再用强制预审队列阻塞用户翻译。
- 科学名词和拉丁词处理更严格，减少误报的术语建议，同时保留有价值的自动识别术语。
- 翻译 QA 会区分确认缺陷和推断型术语/专名警告；任务可以完成，但在需要专业复核时会
  明确展示质量确认状态。
- 前端现在会展示翻译质量状态，不再把带警告的结果伪装成完全干净的最终交付。

质量验证：

- 本地完整测试套件已通过：`1219 passed in 219.75s`。
- 打包脚本 regression 已通过：`33 passed`。
- 本地安装包目标：`AI_Sub_Pro_v1.3.9.dmg`。

安装包：

- `AI_Sub_Pro_v1.3.9.dmg` 是本 release line 的 macOS 安装包名称。

## v1.3.8 - 下载位置提醒与弹出菜单层级修复

主要内容：

- 在线视频任务在下载前会弹出确认框，说明源视频会保存到
  `~/AI_Sub_Pro_Data/projects/<project-id>/original.mp4`，不会保存到系统
  Downloads / 下载目录。
- 在线视频项目即使最终烧录视频还未完成，也可以在项目卡片中点击“显示”打开项目位置，
  便于查看已下载源视频和中间文件。
- 项目详情的更多操作菜单改用专用高层级 popover，展开选项不会再被邻近卡片或面板遮挡。

质量验证：

- 前端/accessibility/settings regression 已通过：`116 passed`。
- 红绿 focused regression 已通过：`5 passed`。
- 本地安装包目标：`AI_Sub_Pro_v1.3.8.dmg`。

安装包：

- `AI_Sub_Pro_v1.3.8.dmg` 是本 release line 的 macOS 安装包名称。

## v1.3.7 - 网络视频信息识别与原生字幕翻译

主要内容：

- 首页独立 TMDB 预告入口改为在线视频翻译入口，支持 YouTube 链接和直接视频文件
  URL。
- 新增直接 URL 预告 API，可在不依赖 TMDB 元数据的情况下创建下载、听写、翻译项目；
  影视项目的 TMDB 元数据补全能力仍然保留。
- URL 项目会在用户留空标题或源语言为 auto 时先探测网络视频信息，并保存来源标题、
  上传者、频道、时长、源语言和平台字幕可用性。
- 下载到的原生字幕会按检测到的源语言优先采用，不再只看英文；采用成功后会跳过 ASR，
  直接翻译平台字幕文件。
- 翻译提示词会接收更强的内容类型上下文，包括学术、访谈、技术教程、影视和合法成人
  内容指导，以及检测到的网络来源上下文。

质量验证：

- 本地完整测试套件已通过：`1111 passed in 202.29s`。
- 预告/前端/项目元数据 focused regression 已通过：`176 passed`。
- 翻译质量 regression 已通过：`28 passed`。
- 打包脚本 regression 已通过：`33 passed`。
- 本地安装包目标：`AI_Sub_Pro_v1.3.7.dmg`。

安装包：

- `AI_Sub_Pro_v1.3.7.dmg` 是本 release line 的 macOS 安装包名称。

## v1.3.5 - ASR 安装提醒与模型目录同步

主要内容：

- 系统检查现在会在用户显式选择了未安装的本地 ASR 后端，或本机没有任何本地
  ASR 后端时，返回可展示的安装提醒。
- 设置页会内联显示 ASR 依赖提醒，并在当前会话中对每个缺失后端只弹出一次 toast。
- Whisper 模型选项现在来自后端能力目录，不再在前端重复硬编码；用户已配置的自定义
  模型也会保留在可选列表中。
- 自动模式下只要至少有一个本地 ASR 后端可用，就不会因为未选择的可选后端缺失而打扰用户。

质量验证：

- 完整测试套件已通过：`1087 passed in 198.90s`。
- ASR/设置/前端 focused regression 已通过：`202 passed in 24.24s`。
- 源码运行态检查已通过：`/api/system-check` 返回 6 个 ASR 模型选项；MLX 可用且
  backend 为 auto 时不返回安装提醒；设置页能渲染动态模型选项和 ASR 安装提醒。
- 本地 DMG 校验已通过：`hdiutil verify dist/AI_Sub_Pro_v1.3.5.dmg`
  报告 checksum 有效，并且在 `dist/` 下运行
  `shasum -a 256 -c AI_Sub_Pro_v1.3.5.dmg.sha256` 通过。
- 本机安装版验证已通过：`/api/settings` 报告 app 版本 `1.3.5`，
  ASR 后端为 `auto`，且 `/api/system-check` 暴露 `asr_model_options`。

安装包：

- 已为 macOS 用户附加 `AI_Sub_Pro_v1.3.5.dmg`，并提供对应的
  `AI_Sub_Pro_v1.3.5.dmg.sha256` 校验文件和 `release-size-report.json`。
- 本地产物大小：328 MB DMG / 816 MB app。

## v1.3.4 - UI 自动收起与 ASR 后端选择

主要内容：

- macOS 侧栏在长页面向下滚动时会自动收起，回到顶部附近会展开；移动端布局不受影响。
- 设置页新增本地 ASR 后端选择：`auto`、`mlx_whisper`、`faster_whisper`、
  `openai_whisper`。
- ASR 主流程现在会真正使用该后端设置。`auto` 保持原有
  MLX -> faster-whisper -> openai-whisper fallback；显式选择某个后端时，
  失败会明确暴露，不再静默切换到其它引擎。
- 系统检查推荐现在会报告当前配置的 ASR 后端，以及本机是否已安装对应依赖。

质量验证：

- 完整测试套件已通过：`1084 passed in 192.63s`。
- UI/ASR/设置 focused regression 已通过：`199 passed in 20.91s`。
- 桌面运行态检查已通过：设置页滚动后侧栏从 220px 收起到 72px，回到顶部恢复，
  且 ASR 后端选择器可见。
- 本地 DMG 校验已通过：`hdiutil verify dist/AI_Sub_Pro_v1.3.4.dmg`
  报告 checksum 有效，并且在 `dist/` 下运行
  `shasum -a 256 -c AI_Sub_Pro_v1.3.4.dmg.sha256` 通过。
- 本机安装版验证已通过：`/api/settings` 报告 app 版本 `1.3.4`，
  ASR 后端为 `auto`。

安装包：

- 已为 macOS 用户附加 `AI_Sub_Pro_v1.3.4.dmg`，并提供对应的
  `AI_Sub_Pro_v1.3.4.dmg.sha256` 校验文件和 `release-size-report.json`。
- 本地产物大小：330 MB DMG / 816 MB app。

## v1.3.3 - 打包版 ASR 后端修复

主要内容：

- 修复 macOS 打包版可能在听写时失败并提示 `No working ASR backend found`
  的问题；根因是默认安装包排除了所有本地 Whisper 后端模块。
- macOS 和 Windows 打包现在会默认打包已安装的 ASR 后端包；大型 Whisper 模型文件
  仍通过 `AISUBPRO_BUNDLE_LOCAL_ASR=1` 显式打包。
- 启用 ASR 后端打包但构建环境没有任何本地后端时，打包脚本会直接失败，避免发布
  会在识别阶段崩溃的安装包。
- 新增 `requirements-asr.txt`，并让 release workflow 安装它，确保 release 构建
  至少有一个兜底 ASR 后端可打包。

质量验证：

- 完整测试套件已通过：`1053 passed in 60.24s`。
- 设置/打包 focused suite 已通过：`33 passed in 1.04s`。
- 打包单独 suite 已通过：`32 passed in 0.24s`。
- 本地 DMG 校验已通过：`hdiutil verify dist/AI_Sub_Pro_v1.3.3.dmg`
  报告 checksum 有效，并且在 `dist/` 下运行
  `shasum -a 256 -c AI_Sub_Pro_v1.3.3.dmg.sha256` 通过。
- 本机安装版验证已通过：`/api/settings` 报告 app 版本 `1.3.3`，
  `/api/system-check` 报告 `mlx_whisper: true`、
  `asr_recommendation.ready: true`，后端为 `mlx_whisper`，模型来源为
  `cache`。

安装包：

- 已为 macOS 用户附加 `AI_Sub_Pro_v1.3.3.dmg`，并提供对应的
  `AI_Sub_Pro_v1.3.3.dmg.sha256` 校验文件和 `release-size-report.json`。
- 附带的 macOS 安装包包含一个已安装的 ASR 后端包；不包含本地 Whisper 模型文件，
  模型会在首次使用时下载，或从常规本地缓存读取。本地资产大小：328 MB DMG /
  816 MB app。
- Windows 安装包需要在 Windows 机器上运行 `build_win.bat` 生成；当前 release
  暂未附带预编译 Windows 安装包，请先使用源码安装。

## v1.3.1 - 设置页版本号显示补丁

主要内容：

- 在设置页“存储 / 发布”区域新增当前 app 版本号，方便确认本机正在运行的安装版。
- `GET /api/settings` 新增只读 `app_info` 元数据，包含 app 名称和版本号。
- 保存设置时会剥离只读 app 元数据，避免把版本号写入用户 `config.json`。
- 后端 FastAPI 版本改为统一读取 `app/version.py`，后续发版时 UI 和 API 使用同一个
  版本来源。

质量验证：

- 完整测试套件已通过：`1052 passed in 72.45s`。
- 设置/打包 focused suite 已通过：`164 passed in 12.50s`。
- 本机安装版验证已通过：`/api/settings` 的 `app_info` 返回
  `{"name": "AI Sub Pro", "version": "1.3.1"}`。

安装包：

- 已为 macOS 用户附加 `AI_Sub_Pro_v1.3.1.dmg`，并提供对应的
  `AI_Sub_Pro_v1.3.1.dmg.sha256` 校验文件和 `release-size-report.json`。
- 附带的 macOS 安装包是 base app build，不包含本地 Whisper 模型文件，也不包含
  optional ASR backend packages / 可选 ASR 后端包。
- Windows 安装包需要在 Windows 机器上运行 `build_win.bat` 生成；当前 release
  暂未附带预编译 Windows 安装包，请先使用源码安装。

## v1.3.0 - 翻译准确度评测与检索升级

主要内容：

- 新增本地字幕 A/B 评测 CLI，可对原文、旧译文、新译文和可选参考字幕生成
  JSON 与 Markdown 准确度报告。
- 新增更安全的本地双语语料导入流程，支持 JSONL、TSV、CSV，要求 source、
  license、语言对元数据，并提供行数限制、重复处理和导入摘要。
- 升级口语库和翻译记忆检索：可用时使用 SQLite FTS5，不可用时回退到确定性
  n-gram 评分，并加入有界评分、backend trace 和检索例句数量限制。
- 新增确定性专名一致性检查，针对重复出现的源语言名称检测译名不一致，并写入
  翻译 QA 报告。
- 新增保守 QA 自动修复轮次，最多两轮；当修复 provider 只返回部分行时，会保留
  未返回行的原译文，避免数据丢失。
- 已补充英文和简体中文使用说明，覆盖本地评测和语料导入工作流。

质量验证：

- 完整测试套件已通过：`1050 passed in 64.46s`。
- 翻译准确度 focused suite 已通过：`158 passed in 4.19s`。
- 本地 `Brilliant Minds` 评测报告生成已通过，并在
  `/tmp/ai-sub-pro-brilliant-minds-quality` 写入
  `translation_accuracy_report.json` 和 `translation_accuracy_report.md`。

安装包：

- 已为 macOS 用户附加 `AI_Sub_Pro_v1.3.0.dmg`，并提供对应的
  `AI_Sub_Pro_v1.3.0.dmg.sha256` 校验文件和 `release-size-report.json`。
- 附带的 `.sha256` 文件和 `release-size-report.json` 与 DMG 来自同一次本地
  macOS 构建。
- 附带的 macOS 安装包是 base app build，不包含本地 Whisper 模型文件，也不包含
  optional ASR backend packages / 可选 ASR 后端包。
- Windows 安装包需要在 Windows 机器上运行 `build_win.bat` 生成；当前 release
  暂未附带预编译 Windows 安装包，请先使用源码安装。

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
