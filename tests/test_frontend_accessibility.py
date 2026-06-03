import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_home_file_entry_controls_have_accessible_names():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")

    assert 'role="button"' in html
    assert 'aria-label="选择或拖入视频文件"' in html
    assert '@keydown.enter.prevent="openFilePicker()"' in html
    assert '@keydown.space.prevent="openFilePicker()"' in html
    assert 'aria-label="视频文件路径"' in html


def test_packaged_frontend_uses_local_runtime_assets():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")

    assert "https://cdn.tailwindcss.com" not in html
    assert "cdn.jsdelivr.net" not in html
    assert '/static/css/tailwind.css' in html
    assert '/static/vendor/alpinejs/alpine.min.js' in html
    assert (ROOT / "app/static/css/tailwind.css").is_file()
    assert (ROOT / "app/static/vendor/alpinejs/alpine.min.js").is_file()


def test_static_external_links_use_noopener():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")

    assert 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html


def test_settings_controls_have_accessible_names():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")

    expected_labels = [
        ":aria-label=\"translationProviderLabel(provider) + ' API 密钥'\"",
        ":aria-label=\"(showKeys[provider] ? '隐藏 ' : '显示 ') + translationProviderLabel(provider) + ' API 密钥'\"",
        ":aria-label=\"'从剪贴板粘贴 ' + translationProviderLabel(provider) + ' API 密钥'\"",
        ":aria-label=\"'测试 ' + translationProviderLabel(provider) + ' API 密钥'\"",
        "aria-label=\"Whisper 模型\"",
        "aria-label=\"ASR 默认语言\"",
        "aria-label=\"ASR 时间偏移毫秒\"",
        "aria-label=\"主翻译引擎\"",
        "aria-label=\"主翻译模型\"",
        "aria-label=\"TMDB API 密钥\"",
        "aria-label=\"预告片下载清晰度\"",
        "aria-label=\"返回项目列表\"",
        "aria-label=\"项目 ASR 语言\"",
        "aria-label=\"项目目标语言\"",
        "aria-label=\"更多操作\"",
        "aria-label=\"关闭错误提示\"",
        "aria-label=\"切换内嵌字幕处理方式\"",
        "aria-label=\"新增下一行字幕\"",
        "aria-label=\"分割这一行字幕\"",
        "aria-label=\"删除这一行字幕\"",
    ]
    for label in expected_labels:
        assert label in html


def test_checkbox_controls_have_explicit_accessible_names():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")

    checkboxes = re.findall(r"<input\b(?=[^>]*type=\"checkbox\")[^>]*>", html, flags=re.DOTALL)
    assert checkboxes
    assert [
        checkbox
        for checkbox in checkboxes
        if "aria-label=" not in checkbox and ":aria-label=" not in checkbox
    ] == []


def test_form_controls_have_accessible_names():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")

    controls = re.findall(r"<(?:input|select|textarea)\b[^>]*>", html, flags=re.DOTALL)
    assert controls
    assert [
        control
        for control in controls
        if (
            "aria-label=" not in control
            and ":aria-label=" not in control
            and "aria-labelledby=" not in control
        )
    ] == []


def test_toasts_have_live_region_semantics():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")

    assert ':role="t.type === \'error\' ? \'alert\' : \'status\'"' in html
    assert ':aria-live="t.type === \'error\' ? \'assertive\' : \'polite\'"' in html
    assert 'aria-atomic="true"' in html


def test_provider_key_test_buttons_have_disabled_and_loading_states():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/css/app.css").read_text(encoding="utf-8")

    assert "keyStatus[provider]==='testing' || !settings.api_keys[provider]?.trim()" in html
    assert "keyStatus[provider]==='testing' ? '测试中...' : '测试'" in html
    assert ':disabled="settingsSaving"' in html
    assert "settingsSaving ? '保存中...' : '保存设置'" in html
    assert "settingsApiKeyProviders()" in html
    assert "settingsApiKeyProviders()" in js
    assert "modelErrors.primary" in html
    assert "modelErrors.polish" in html
    assert "settings-login-button" in html
    assert "kb-new-button" in html
    assert ".settings-login-button" in css
    assert ".kb-new-button" in css


def test_project_detail_export_actions_have_disabled_and_pending_states():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")

    assert ':disabled="!canExportSrt(\'translated\')"' in html
    assert ':disabled="!canExportSrt(\'bilingual\')"' in html
    assert ':disabled="!canExportSrt(\'original\')"' in html
    assert "exportSrtLabel('translated')" in html
    assert "exportUnavailableMessage('translated')" in html
    assert "canExportSrt(format)" in js
    assert "isExportingSrt(format)" in js
    assert "hasExportableTranslatedSubtitles()" in js


def test_click_navigation_uses_set_view_guard():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")

    assert '@click="view=' not in html
    assert "@click=\"setView('home')" in html
    assert "@click=\"setView('projects')" in html
    assert "@click=\"setView('settings')" in html
    assert "@click=\"openTrailerWizard()" in html


def test_project_rename_uses_app_modal_instead_of_prompt():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")

    assert "projectRenamePrompt" in html
    assert 'aria-labelledby="project-rename-title"' in html
    assert "aria-label=\"项目名称\"" in html
    assert "confirmRenameProject()" in html
    assert "isProjectMutationPending('rename', projectRenameTarget?.id)" in html
    assert "isProjectMutationPending('archive', p.id)" in html
    assert "归档中..." in html
    assert "保存中..." in html
    assert "projectMutationPending" in js
    assert "prompt(" not in js


def test_app_modals_have_dialog_semantics_and_escape_handlers():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")

    expected = [
        'role="dialog" aria-modal="true" aria-labelledby="app-confirm-title"',
        'role="dialog" aria-modal="true" aria-labelledby="project-rename-title"',
        'role="dialog" aria-modal="true" aria-labelledby="new-kb-title"',
        '@keydown.escape.window="resolveConfirm(false)"',
        '@keydown.escape.window="cancelRenameProject()"',
        '@keydown.escape.window="cancelNewKb()"',
        'x-ref="kbNewKeyInput"',
        'previousTrailerStep()',
        'trailerStep > 1 && trailerStep < 5',
        'advanceTrailerVideoStep()',
        ':disabled="!canFetchTrailerVideos()"',
        "trailerLoading ? '加载中...' : '下一步 →'",
    ]
    for snippet in expected:
        assert snippet in html


def test_dangerous_actions_use_app_confirm_modal_instead_of_native_confirm():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")

    assert "confirmPrompt" in html
    assert "resolveConfirm(false)" in html
    assert "resolveConfirm(true)" in html
    assert "askConfirm(" in js
    assert "confirm(" not in js


def test_claude_cli_status_errors_are_visible():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")

    assert 'x-show="settingsUsesLocalCli()"' in html
    assert "Claude / Codex CLI（本机）" in html
    assert "settingsUsesClaudeCli()" in js
    assert "settingsUsesLocalCli()" in js
    assert "settings.translation?.primary_provider === 'claude_cli'" not in js
    assert "claudeCliStatus && claudeCliStatus.error" in html
    assert "Claude 检查失败" in html
    assert "claudeCliStatus && !claudeCliStatus.installed && !claudeCliStatus.error" in html


def test_codex_cli_status_errors_are_visible():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")

    assert 'x-show="settingsUsesLocalCli()"' in html
    assert "Claude / Codex CLI（本机）" in html
    assert "settingsUsesCodexCli()" in js
    assert "settingsUsesLocalCli()" in js
    assert "Codex CLI 模型" in html
    assert "codexCliStatus && codexCliStatus.error" in html
    assert "Codex 检查失败" in html
    assert "checkCodexCliStatus()" in html
    assert "codexCliStatus && !codexCliStatus.installed && !codexCliStatus.error" in html


def test_full_document_mode_setting_is_not_hidden_behind_claude_only_copy():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")

    assert 'x-model="settings.translation.full_doc_mode"' in html
    assert "一次性全量翻译（尽量整份字幕一次请求，提升术语一致性）" in html
    assert "超出模型上下文时会自动回退到批量翻译" in html
    assert "利用 Claude 1M" not in html
    assert 'x-show="settings.translation.primary_provider === \'claude_cli\'" x-cloak class="mt-4 pt-4 border-t' not in html


def test_system_and_progress_refresh_errors_are_visible():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")

    assert "sysCheckError || (sysCheck && !sysCheck.ready)" in html
    assert "系统检查失败" in html
    assert "@click=\"refreshSystemCheck()\"" in html
    assert ":disabled=\"sysCheckLoading\"" in html
    assert "sysCheckLoading ? '检查中...' : '重试'" in html
    assert 'x-show="sysCheck" class="space-y-2 text-[12px]"' in html
    assert 'x-show="sysCheck && !systemTranslationReady()"' in html
    assert "progressRefreshError" in html
    assert "等待进度更新" in html


def test_project_cards_and_subtitle_edit_cells_are_keyboard_reachable():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/css/app.css").read_text(encoding="utf-8")

    assert ':aria-label="\'打开项目 \' + (p.name || p.id)"' in html
    assert '@keydown.enter.self.prevent="openProject(p.id)"' in html
    assert '@keydown.space.self.prevent="openProject(p.id)"' in html
    assert ':aria-label="\'打开项目位置 \' + (p.name || p.id)"' in html
    assert ':aria-label="\'编辑第 \' + s.index + \' 条字幕译文\'"' in html
    assert ':title="currentProject?.name || \'\'' in html
    assert '@keydown.enter.prevent="startEdit(idx, s.translation)"' in html
    assert '<button type="button" x-show="trailerStep > 1 && trailerStep < 5"' in html
    assert ':disabled="isProjectMutationPending(\'reveal\', p.id)"' in html
    assert ':disabled="p.status===\'processing\' || !!p.pipeline_stage || isProjectMutationPending(\'delete\', p.id)"' in html
    assert ':disabled="projectActionsDisabled(currentProject)"' in html
    assert 'x-show="isProjectBusy(currentProject)"' in html
    assert "isProjectMutationPending('reveal', p.id) ? '打开中...' : '显示'" in html
    assert "isProjectMutationPending('delete', p.id) ? '删除中...' : '删除'" in html
    assert "projectActionPending === 'start-full' ? '启动中...'" in html
    assert "projectActionPending === 'cancel' ? '取消中...'" in html
    assert "isProjectMutationPending('embedded-subtitle', currentProject?.id)" in html
    assert "isProjectMutationPending('tmdb', currentProject?.id)" in html
    assert "subtitleActionsDisabled()" in html
    assert "subtitleActionPending: ''" in js
    assert "处理中..." in html
    assert "c.original_language ? `· ${c.original_language.toUpperCase()}` : ''" in html
    assert '[role="button"]:focus-visible' in css
    assert 'textarea:focus-visible' in css
    assert '-webkit-line-clamp: 2' in css
    assert 'text-overflow: ellipsis' in css


def test_project_detail_subtitles_have_mobile_card_layout_and_touch_actions():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/css/app.css").read_text(encoding="utf-8")

    assert "subtitle-table-panel" in html
    for snippet in (
        ".subtitle-table-panel th:last-child",
        ".subtitle-table-panel td button",
        ".subtitle-table-panel [role=\"button\"]",
        ".subtitle-table-panel table",
        ".subtitle-table-panel thead",
        ".subtitle-table-panel tr",
        ".subtitle-table-panel td:nth-child(3)::before",
        ".subtitle-table-panel td:nth-child(4)::before",
        ".subtitle-table-panel td:nth-child(5)",
    ):
        assert snippet in css


def test_main_shell_has_mobile_responsive_layout_rules():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/css/app.css").read_text(encoding="utf-8")

    for class_name in (
        "app-shell",
        "app-sidebar",
        "app-main",
        "home-view",
        "home-manual-path",
        "projects-list-header",
        "projects-list-actions",
        "projects-new-button",
        "project-detail-actions",
    ):
        assert class_name in html
    assert "@media (max-width: 767px)" in css
    assert ".app-shell" in css
    assert ".app-sidebar nav" in css
    assert ".home-manual-path" in css
    assert ".projects-list-header" in css
    assert ".projects-new-button" in css
    assert "white-space: nowrap;" in css
    assert ".project-detail-actions" in css


def test_primary_interactions_have_reliable_touch_targets():
    css = (ROOT / "app/static/css/app.css").read_text(encoding="utf-8")

    expected_rules = [
        ".app-sidebar nav button",
        'input:not([type="checkbox"]):not([type="radio"])',
        ".settings-api-key-row button",
        ".settings-tmdb-key-row button",
        ".projects-new-button",
        ".system-action-button",
        ".project-detail-actions button",
        ".knowledge-entry-grid button",
    ]
    for rule in expected_rules:
        assert rule in css

    assert "min-height: 2.75rem;" in css
    assert "min-height: 2.5rem;" in css
    assert "min-width: 2.5rem;" in css


def test_frontend_does_not_use_nonzero_letter_spacing():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/css/app.css").read_text(encoding="utf-8")

    assert "tracking-tight" not in html
    assert "tracking-wider" not in html

    nonzero_letter_spacing = [
        match.group(0)
        for match in re.finditer(r"letter-spacing:\s*([^;]+);", css)
        if match.group(1).strip() != "0"
    ]
    assert nonzero_letter_spacing == []


def test_frontend_respects_reduced_motion_preference():
    css = (ROOT / "app/static/css/app.css").read_text(encoding="utf-8")

    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "animation: none !important;" in css
    assert "transition: none !important;" in css
    assert "scroll-behavior: auto !important;" in css


def test_secondary_text_colors_keep_readable_contrast():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/css/app.css").read_text(encoding="utf-8")

    def luminance(hex_color):
        rgb = [
            int(hex_color[i:i + 2], 16) / 255
            for i in (1, 3, 5)
        ]
        linear = [
            c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
            for c in rgb
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    def contrast(foreground, background):
        fg = luminance(foreground)
        bg = luminance(background)
        return (max(fg, bg) + 0.05) / (min(fg, bg) + 0.05)

    assert "/static/css/tailwind.css" in html
    assert "/static/css/app.css" in html
    assert html.index("/static/css/tailwind.css") < html.index("/static/css/app.css")

    assert ".text-surface-300,\n.text-surface-400" in css
    assert "color: #64748b;" in css
    assert "color: #8ba0b6;" not in css
    assert contrast("#64748b", "#ffffff") >= 4.5
    assert contrast("#64748b", "#f8fafc") >= 4.5


def test_file_upload_flow_reuses_error_aware_helper():
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")

    assert "async uploadVideoFile(file)" in js
    assert "async useSelectedVideoFile(file)" in js
    assert "await this.useSelectedVideoFile(file)" in js
    assert "throw new Error('上传失败')" not in js
    assert "服务器未返回文件路径" in js
    assert "event.target.value = ''" in js


def test_project_creation_entry_has_busy_and_duplicate_submit_states():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")

    assert "fileImporting: false" in js
    assert "projectCreating: false" in js
    assert "canStartProject()" in js
    assert "allowDuringImport" in js
    assert "if (this.projectCreating || (this.fileImporting && !allowDuringImport)) return;" in js
    assert "if (this.fileImporting || this.projectCreating) return;" in js
    assert ':aria-disabled="fileImporting || projectCreating"' in html
    assert ':disabled="!canStartProject()"' in html
    assert "读取中..." in html
    assert "创建中..." in html
    assert "请稍候，不要重复提交" in html


def test_home_dashboard_surfaces_project_summary_and_recent_work():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/css/app.css").read_text(encoding="utf-8")
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")

    assert "home-workbench" in html
    assert "home-primary" in html
    assert "home-aside" in html
    assert "homeProjectSummary()" in html
    assert "recentHomeProjects()" in html
    assert "home-link-button" in html
    assert "homeProjectSummary()" in js
    assert "recentHomeProjects" in js
    assert ".home-workbench" in css
    assert ".home-aside" in css
    assert ".home-link-button" in css
    assert "min-height: 2.5rem" in css


def test_settings_loader_preserves_default_section_shapes():
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")

    assert "normalizeSettings(data)" in js
    assert "this.settings = this.normalizeSettings(data)" in js
    assert "const apiKeys = this.isPlainObject(this.settings.api_keys)" in js


def test_duration_formatter_rejects_non_finite_values():
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")

    assert "const seconds = Number(s);" in js
    assert "!Number.isFinite(seconds)" in js
    assert "normalizeProgress(value)" in js
    assert "Math.max(0, Math.min(100, Math.round(progress)))" in js


def test_frontend_guards_malformed_project_and_subtitle_arrays():
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")

    assert "this.projects = Array.isArray(data) ? data.filter(p => this.isPlainObject(p)) : []" in js
    assert "this.subtitles = Array.isArray(data.blocks) ? data.blocks.filter(b => this.isPlainObject(b)) : []" in js


def test_subtitle_export_revokes_object_url():
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")

    assert "URL.createObjectURL(blob)" in js
    assert "URL.revokeObjectURL(url)" in js


def test_kb_frontend_guards_malformed_array_fields():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")

    assert "data.projects.filter(p => p && typeof p === 'object' && !Array.isArray(p))" in js
    assert "normalizeKb(data)" in js
    assert "Array.isArray(style.rules) ? style.rules.filter(rule => typeof rule === 'string') : []" in js
    assert "kbActionPending" in js
    assert "kbActionPending === 'save' ? '保存中...' : '保存'" in html
    assert "kbActionPending === 'delete' ? '删除中...' : '删除'" in html
    assert "kbActionPending === 'create' ? '创建中...' : '创建'" in html
