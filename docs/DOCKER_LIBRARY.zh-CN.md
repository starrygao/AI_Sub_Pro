# Docker 媒体库字幕服务

目标：在服务器持续发现 Emby 新条目和直接放入媒体目录的视频，检查中文字幕、下载/整理/转码状态，自动翻译缺失字幕并保存至视频同目录。桌面端保持独立。

## 数据流与约束

- Emby 最近条目 + 分页历史盘点；媒体目录分批遍历覆盖直接上传。
- 默认跳过明确只有中文音轨的视频，任务标记为“中文原声，无需翻译”。依据音轨语言标识（含普通话/粤语）判断；混合语言或未知语言不会误跳过。可在 `library.json` 设置 `skip_chinese_audio: false` 关闭。
- 内嵌中文/繁体字幕、同名外挂中文字幕直接跳过。仅强制字幕不能代表整片已有中文字幕。
- 文件大小、纳秒修改时间、inode/device 连续稳定至少 300 秒；临时文件不进入翻译。
- qBittorrent / Transmission 下载和校验状态、MoviePilot 整理任务、VTrans 持久队列共同决定就绪。任一必需服务不可读时停止新的翻译及字幕发布。
- 使用 MoviePilot 原下载路径和 inode 对照识别硬链接，避免整理后的文件仍在下载。
- VTrans 排队、转码或等待发布期间延后；原位替换改变文件版本后重新检查。发布前核对版本，旧视频的译文不写回新视频。
- 优先已有外语文本字幕，无文本字幕时使用 faster-whisper。翻译使用现有 Codex CLI provider、质量检查与导出验证。
- 仅翻译，不烧录、不替换视频。通过现有导出门禁后原子创建 `视频名.chi.srt`；遇到已有不同内容不覆盖。
- TMDB 身份优先 Emby，再 MoviePilot/NFO。剧集使用系列 TMDB ID，不能把单集 TMDB ID 当作系列。
- 单媒体任务、独立容器 FFmpeg/FFprobe、nice 19、ionice idle、2 CPU/4GB 内存、较低 CPU/I/O 权重。Emby 有转码时不启动新媒体处理。

## 部署

`deploy/docker/Dockerfile` 与 `deploy/docker/compose.yaml`。配置、模型、任务、Codex 登录分别持久化。镜像中不含媒体库令牌、登录凭证或项目数据。服务器入口为 `app.server:app`，桌面入口不变。

默认监听 loopback，部署时显式设置局域网地址。HTTP API 使用账户验证和跨站写入校验；服务器页面使用认证 HTTP 轮询。可从 VTrans 复制 PBKDF2 账户文件到本服务私有配置目录复用同一账户，无需读取密码；这是一份独立副本，不修改 VTrans。

`/config/library.json` 包含 `emby`、`qbittorrent`、`transmission`、`moviepilot`、`vtrans` 的连接配置、监控根目录及路径映射。该文件及账户、运维令牌须为 600，配置目录挂载只读。

Codex 登录可用 `docker exec -it ai-sub-pro codex login --device-auth`，或按官方方法将已有登录凭证复制到专用 `/codex` 卷；不会复制个人会话、工具配置或整个 Codex 主目录。部署验收必须实际调用一次模型，并验证容器重建后登录可用，不能只检查 CLI 已安装。[OpenAI 官方登录说明](https://developers.openai.com/codex/auth)。

同目录字幕使用 ISO 语言标识 `chi`，保留原视频文件名；保存后向对应 Emby 条目发出刷新请求。[Emby 字幕命名说明](https://emby.media/support/articles/Subtitles.html)。

## 部署操作

1. 复制 `deploy/docker/.env.example` 为 `.env`，设置监听地址、UID/GID、数据目录、代理和真实媒体磁盘设备。
2. 在数据根目录分别建立 `config`、`data`、`codex`、`models`、`readiness` 目录；将 `library.example.json` 复制到 `config/library.json` 并填写真实连接信息。路径映射必须匹配各应用挂载，示例映射不能直接当作 NAS 实际配置。未使用的下载器可从配置移除。
3. 私有 `config/account.json` 使用 VTrans 的 PBKDF2 账户格式；`config/operator-token` 使用随机运维令牌。所有私有配置设置为 600，目录归运行 UID 所有。
4. 在 `deploy/docker` 执行 `docker compose -f compose.yaml -f compose.nas.yaml up -d --build`。没有适配磁盘设备时不使用 NAS 覆盖文件。
5. 登录 Codex CLI，确认状态页上全部连接正常，再点击“开启自动翻译”。

主服务使用 host 网络以访问 NAS 本机服务与代理，默认仍只监听 loopback。上传检测服务独立运行、无网络、只读根文件系统，读取主机 `/proc` 的打开写句柄并输出路径快照，不读取视频内容。该服务需要两项进程检查 capability 和放宽该容器的 AppArmor；快照过期或不可读时，主服务停止启动/发布。

模型缓存在 `/models`，首次无文本字幕的视频需要下载 faster-whisper small；后续重建复用缓存。媒体读写在本次 NAS 部署限制为 10MiB/s 与 2MiB/s，整机负载阈值为 24。正在执行的单任务不会因播放器开始转码而中断，但新任务会延后。

## 验收清单

- [x] 容器构建、启动、健康检查、重建持久化
- [x] Emby / MoviePilot / 两类下载器 / VTrans 实际状态验证
- [x] 上传未完成、下载暂停、整理中、转码替换的阻断与恢复
- [x] 实际 Codex 翻译、质量门禁、同目录字幕与 Emby 识别
- [x] 资源上限和正在播放的 Emby 服务无异常
- [x] 任务列表路径/状态/筛选/重试与常见屏宽检查

已发现服务器 MoviePilot 保存的一个旧 qBittorrent 地址（2060）不可达；实际运行的 qBittorrent 容器 WebUI 端口为 8085，部署以实际运行实例为准，另监控 Transmission。未修改 MoviePilot 的旧配置。


## 2026-09-22 验证记录

- NAS：`http://192.168.31.4:18091/library`，使用部署时复制的 VTrans 账户登录；原 VTrans 账户未修改。
- 实际外语 SRT → Codex → 质量检查 → 同目录 `TranslationProof.chi.srt` 完成；独立测试 Emby 将其识别为 `Language=zh, IsExternal=true, Codec=srt`。
- 无字幕视频 `AutoASRProof.mkv` 由目录遍历自动发现，经过稳定窗口、faster-whisper small 识别、Codex 翻译、质量检查并发布，生成 3 条中文字幕。模型已缓存约 464MB。
- `ChineseAudioProof.mkv` 无中文字幕但音轨标记为 `chi`，实际自动处理结果为 `native_language`，未创建翻译项目。
- 实际打开写入句柄时上传检测列出视频，关闭后恢复；暂停下载、MoviePilot 整理、VTrans 排队/待发布/替换、硬链接、陈旧快照阻断由自动测试覆盖。未操作真实下载或转码任务来制造故障。
- 播放观测：12 路 Emby 播放、0 转码，Sessions 请求约 19ms；字幕服务约 1.49GiB/4GiB、CPU 7.24%，Emby CPU 9.18%。这是验收时点观测，不代表所有负载下的延迟保证。
- UI 在 320/768/1024/1440 宽度检查无横向溢出，状态、路径、筛选、暂停/开启交互通过；使用无敏感数据的本地 fixture 验证视觉，真实 NAS API 另外验收。
- 回归：157 项相关测试通过（含服务器认证、跨站写入、分页、桌面端导出回归）。测试产物位于 `.runtime/verification/docker-library-20260922/`（不入 Git）。
- 测试媒体位于 `/vol2/1000/video/AI_Sub_Pro_Verification_20260922/`，与真实媒体分离，自动监控根目录不包含它。独立 Emby 测试实例的样本保留在 `AISubProof20260922` 文件夹。

容器重建验证：Codex 凭证文件一致、发现队列未丢失、已发布字幕哈希一致，模型缓存保留。单条目刷新使用当前 Emby 支持的 `Default` 模式，并明确禁用替换全部元数据/图片；测试确认移除和恢复外挂中文字幕均被该接口识别。[Emby 刷新接口](https://betadev.emby.media/reference/RestAPI/ItemRefreshService/postItemsByIdRefresh.html)。
