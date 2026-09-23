# 双语排版、服务器质量抽查与本地导出恢复（2026-09-23）

## 已修复的行为

App 与 Docker 共用的双语 SRT 导出器现在把每条字幕写成两条文本行：上方译文、下方原文。中文视觉换行合并，英文词间与句间保留空格，双人对白保留说话人标记，斜体标签保留。单语字幕原有换行策略不变。播放器仍可能按屏幕宽度自动折行；SRT 的两条文本行不能强制所有播放器只显示两行。

Line.of.Fire S01E01（项目 b6d76c74）的失败发生在导出阶段。源字幕的 208、343、829 条只有音乐符号和误混入的 WEBVTT/X-TIMESTAMP-MAP 头，被分类器误判为对白；译文去除音乐符号后为空，完整性检查因此报 978/981。511、934 条则是实际对白加相同格式头，必须保留对白。

分类和导出现在仅清理完整匹配的格式头行，未删除字幕原始文件，也未放宽缺失译文检查。原文、981 条恢复草稿、配置和质检报告的身份均核对一致后，通过现有原子发布流程重新导出 978 条有效字幕。既有质检结论和问题记录保留，没有整集重新翻译、修改译文或伪造新质检结果。

同名双语文件已另存到原视频目录：
`/Users/gaopengxiang/Downloads/电视剧/Line.of.Fire.S01E01.Pilot.1080p.Peacock.WEB-DL.DDP.5.1.H.264-CHDWEB.srt`。

## 服务器译文质量：仍存在实质问题

检查了两部已交付任务的实际字幕、源文/译文草稿、全部现存 QA 问题和相关上下文，并间隔抽查普通对白。不是逐帧音画审校，也不能据此给整库打分。

| 项目 | 有效字幕 | 修改前超过两行 | 修改后两行 | 原有 QA 提示 |
| --- | ---: | ---: | ---: | ---: |
| 骸骨骑士 S02E12（cc22b80e） | 330 | 102 | 330 | 7 |
| 千锤百炼 S02E02（6866ef2b） | 508 | 182 | 508 | 19 |

普通对白抽样大多可读，但下面的问题不能归为单纯排版：

1. **自动人名归一化会破坏正确译文。** 骸骨骑士源条目 260 的 `visit to Lalatoya` 被写成“来千代女大人”。`trace.deterministic_postprocess.proper_name_normalized_blocks` 明确记录两次 `Lady Chiyome: 拉拉托亚 → 千代女大人`，包含模型修复之后再次归一化。地点应为“拉拉托亚”，应修正实体匹配边界/歧义判断，不能继续用猜测的多数译名直接替换其他实体。
2. **千锤百炼存在人名不一致。** Hezekiah 出现“希西家／希泽家／希泽凯亚”；Miss Crane 出现“克雷恩／克兰”；Bull 的说话人标签同时出现“布尔／公牛”。这些是实际字幕中的不同译法，不能将全部一致性警告都视为误报。
3. **千锤百炼源条目 308 有时态/事实过度推断。** 前文“我必须赢”，后文“你若助我获胜，种植园就归你”，中间却译为“这次落败让我颜面扫地”，断言了尚未发生的落败。原句自身措辞含混，确切译法应结合音画，但目前译文明显不宜直接作为已核实事实。
4. 部分 QA 也是误报：例如把“艾莉安”和“艾莉安大人”的称谓差异、从“舒格”截取出来的“格”当作实体不一致。质量提示数量不能直接当作错译数量。
5. 当前 `unattended_with_warnings` 策略允许内容完整但保留语义问题的字幕交付，所以“完成”表示文件已交付，不代表逐句正确。此次没有改变用户现有交付策略，也没有把这两部字幕宣称为已完成语义修订。

此次生产变更只修复排版与格式头造成的导出故障。上述实体规则及具体错译作为质量检查发现记录，未额外改变译文或自动术语策略。

## 生产验证

- Docker 镜像：`sha256:ea492842ac49256d7168dfe1c7585abe00b768a8020bdae3a367de894811af7f`。
- 两部服务器项目重新发布后，证书验证通过，实际媒体目录 SRT 与项目双语文件字节一致；全部 838 条均为两行，两个 Emby 项目均已刷新。
- 只替换哈希与系统所有权记录吻合的旧字幕，原文件备份在各视频目录 `.aisub-backups`。保持旧文件名（含历史 `.chi.srt`），未修改视频。
- 更新时确认无正在翻译/发布任务，暂缓新任务启动，完成后恢复原先开启的自动监控。模型、账户、配置、媒体路径不变。
- 本地新 App 已安装；构建包通过固定证书签名及合成凭证写入、跨重启读取、清理测试。隔离项目经实际打包进程的 HTTP 导出返回 978 条两行字幕。
- 恢复脚本曾产生额外 Python 字节码，导致一次已安装包签名校验失败；随后从完整签名的构建包重新安装并验证通过。实际 App 目前等待 macOS 对现有钥匙串访问的用户授权，尚未完成真实账户启动验收。未读取或记录用户凭证内容。

## 测试与复现证据

先运行新回归：5 failed、32 passed，失败覆盖双语原文换行、多说话人换行、长字幕/斜体换行和 WEBVTT 导出故障。修复后相关测试共 **297 passed**：

```sh
python3 -m pytest tests/test_bilingual_srt.py tests/test_subtitle_source_contract.py \
  tests/test_translation_checkpoint.py tests/test_translation_delivery_transaction.py \
  tests/test_translation_qa.py tests/test_translation_qa_wrapped_dialogue.py \
  tests/test_translation_qa_entity_spans.py tests/test_library_publish.py \
  tests/test_bilingual_burn_integration.py -q
```

真实本地任务副本及生产恢复均核对：978 条有效字幕、两行、证书有效、原文与草稿哈希不变、0 次模型调用。最终 diff 已检查。

证据目录：`.runtime/verification/subtitle-quality-recovery-20260923/`。本地旧 App 与项目备份：`.runtime/handoff-backups/subtitle-quality-20260923/`。NAS 源码/镜像回滚分别位于 `/vol1/1000/docker/ai-sub-pro/backups/subtitle-quality-20260923/` 和 `ai-sub-pro:before-subtitle-quality-20260923`；NAS 项目备份保存在 vol2 数据目录 `recovery-backups/subtitle-quality-20260923/`。
