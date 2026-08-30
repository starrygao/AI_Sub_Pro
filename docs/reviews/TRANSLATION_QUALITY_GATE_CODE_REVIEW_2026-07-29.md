# AI Sub Pro 翻译质量门与交付事务代码审查

## Executive Summary

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High / P1 | 5 |
| Medium / P2 | 1 |
| Low | 0 |

**Overall risk:** High

**Recommendation:** REJECT / CONDITIONAL。当前翻译成品不能认定为专业交付级；当前工作树也不应在修复 3 个烧录事务 P1 前合并和安装。

关键结论：

- 已安装的 1.3.25 会把严重字幕问题作为可确认警告，并且后端导出接口不验证质量证书。这直接解释了“50 个严重问题仍询问是否继续导出”。
- 工作树 1.3.26 已改为前端阻断和后端证书校验双门禁；相关前端、导出和翻译质量测试通过。
- 最新真实项目的 150 条源/译文数量差异全部是可确定识别的音乐或音效描述，普通对白真实漏译为 0；“50 个严重问题”主要是旧版缺少权威 `sound_description` 元数据造成的误报。
- 最新真实 QA 报告仍保留 5–6 个语义问题，包括核心条件关系漏译和语义错位，因此成品本身仍不达到专业翻译交付标准。
- 取消 ABA、启动失败回滚和进度同版本复审通过；烧录崩溃恢复仍有 3 个 P1。

## Scope and Evidence

- 工作树：`codex/professional-translation-quality-gate`，基线 HEAD `5929fd1`
- 已安装版本：`/Applications/AI Sub Pro.app`，版本 `1.3.25`
- 工作树版本：`1.3.26`
- 最新真实项目：
  - `/Users/gaopengxiang/AI_Sub_Pro_Data/data/projects/0737e65f`
  - `/Users/gaopengxiang/AI_Sub_Pro_Data/data/projects/74122f7b`
- 审查策略：Focused differential review；翻译门禁、导出、取消/启动、烧录事务按高风险路径分析。

## Findings

### P1 — 已安装 1.3.25 明确允许严重问题继续导出

**Installed files:**

- `/Applications/AI Sub Pro.app/Contents/Resources/app/static/js/app.js:3991`
- `/Applications/AI Sub Pro.app/Contents/Resources/app/static/js/app.js:4233`
- `/Applications/AI Sub Pro.app/Contents/Resources/app/api/projects.py:1844`

前端为 severe 问题生成“是否继续导出”确认框，后端直接读取 `translated.srt` / `bilingual.srt`，没有调用质量证书验证。这是用户所见行为的直接根因。

工作树已经在 `app/static/js/app.js:550-564` 阻断 `blocked` / `needs-review`，并在 `app/api/projects.py:2086-2098` 通过 `validate_translation_delivery` fail-closed。

### P1 — 最新真实翻译仍有明确语义错误，不能评为专业级

`0737e65f/translation_qa_report.json` 仍记录 5 个问题，包括：

- block 209 漏掉“别因为我而停下”的原因关系；
- block 232–233 条件/结果关系被拆坏并错位；
- block 493 语义不确定。

`74122f7b/translation_qa_report.json` 仍记录 6 个问题，包括身份语义、陈述/祈使语气、核心内容漏译和词义选择错误。

两份旧报告都缺少当前权威证书所需的 policy、run id、content hash、source generation hash 和 delivery artifact hashes。当前 `app/utils/translation_certification.py:72-89` 会正确拒绝它们，不能把旧的 `passed` 原样迁移为新证书。

### P1 — Project/workflow 写入不具备掉电 durable 保证，恢复证据却会被删除

`app/utils/project_store.py:48-74` 的 `atomic_write_json` 在 `os.replace` 前后没有 fsync 临时文件和父目录。workflow 的完成状态最终复用该写入路径。烧录提交随后删除 backup、snapshot 和 manifest。

掉电窗口中，进程已收到“写入成功”，恢复证据也已删除，但 project/workflow rename 或文件内容仍可能未落盘。重启后可能只剩旧或损坏状态，无法判断已提交输出。

### P1 — Encoder 运行期间项目稳定代际可变化，live commit 未重新验证 generation

encoder 在 delivery 锁外运行。项目 PATCH 路径可同时修改 `target_language`、`manual_terms` 等稳定字段，但 live commit 只验证 transaction id、state、stage path 和 SHA，没有比较当前 `burn_project_generation_hash` 与 manifest 中记录的 generation。

只读复审已在临时目录复现：encoder 基于旧认证交付生成视频，同时 PATCH 把目标语言从简体中文改为繁体中文；最终项目被标记 `completed`，旧代际视频被提交，manifest 被删除。

### P1 — 首次输出 rollback 删除 final 后缺少独立目录 fsync 屏障

无旧输出时，rollback 先 unlink 未提交 final，随后清理 manifest；manifest unlink 才 fsync 目录。掉电允许 manifest 删除持久化而 final 删除未持久化，重启出现“无 manifest、正常 final 文件仍可见”的孤儿状态，当前 orphan 规则不会删除正式输出名。

### P2 — “专业级”认证缺少独立评估与 release 质量基准

严格语义 QA 在 `app/api/translate.py:2669` 和 `app/api/translate.py:3472` 继续使用 `translator.primary`，即生成与评审共享同一 provider/model，存在相关性盲区。

Release CI 只运行单元/集成测试，没有执行真实翻译质量 benchmark。仓库 golden corpus 只有 12 个小型手工 case，并不运行模型生成，也不能证明长片字幕达到专业译审标准。

## Correct Behavior Confirmed

- 当前权威音效分类对最新项目统计：
  - source blocks: 739
  - translated blocks: 589
  - unmatched sound-description blocks: 150
  - unmatched ordinary-dialogue blocks: 0
- 当前工作树会拒绝两份旧报告：`Translation quality certification identity is incomplete`。
- 前端/导出测试：120 passed。
- 专业、语义、缺译、证书聚焦测试：147 passed。
- 取消/启动复审：
  - 60 个聚焦测试通过；
  - 26 个 ABA/锁序/启动窗口测试通过；
  - 两个额外故障注入通过；
  - 未发现 P0–P2。
- 烧录聚焦测试：62 passed，但未覆盖上述掉电和 generation 竞态。
- `python3 -m compileall -q app` 通过。
- `git diff --check` 通过。

## Modification Plan

### Immediate / Blocking

1. 将当前真实字幕标记为旧证书/待重新认证，禁止继续导出或烧录，不把旧 `passed` 迁移为新 `passed`。
2. 修复 durable JSON commit：临时文件 flush+fsync、原子 replace、父目录 fsync；project 与 workflow 均成功 durable 后才能删除 burn recovery evidence。
3. live burn commit 在 delivery 锁内重新计算并比较 project generation；不一致时 rollback，不得提交 stage。
4. 首次输出 rollback 在 unlink final 后立即 fsync 项目目录，再允许删除 manifest。
5. 为以上 3 个烧录 P1 增加 after-effect、掉电顺序模型、并发 PATCH 和重启恢复测试。

### Translation Quality Closure

6. 用 1.3.26 严格专业模式重跑最新真实项目，生成完整的 run/content/source/artifact 哈希证书。
7. 用真实项目回归断言 150 条音效描述不计为缺译、普通对白缺译为 0，且任何 semantic mismatch 都阻止无人值守交付。
8. 对 block 209、232–233、493 等已知问题建立固定回归样本；修复后重新跑全片语义覆盖。
9. 引入独立 QA provider/model 或人工抽检门禁，避免生成模型自审；release pipeline 执行带专业参考译文的真实 corpus benchmark。

### Release

10. 子代理逐项复审上述修复；全量 pytest、compileall、diff-check 和打包检查全部通过。
11. 收敛到 main、提交、构建并安装 1.3.26+；确认新应用版本和资源哈希后再删除 1.3.25。
12. 在新版本上重新运行最新项目；只有 0 severe、0 unresolved semantic、100% semantic coverage 且人工抽检通过时，才标记为专业交付级。

## Limitations

- 本轮按用户要求只读审查，没有修改业务代码、提交、安装、删除旧版本或重跑真实翻译任务。
- 掉电问题通过持久化语义与故障窗口分析确认；现有测试不能模拟真实断电缓存丢失。
- “专业翻译级”是译文质量结论，单元测试和自评模型不能单独证明，最终仍需独立基准或人工译审证据。
