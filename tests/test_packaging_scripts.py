from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_build_mac_preserves_tracked_pyinstaller_spec():
    script = (ROOT / "build_mac.sh").read_text(encoding="utf-8")

    assert "*.spec" not in script
    assert "--specpath" in script
    assert "build/spec" in script
    assert 'ROOT_DIR="$(pwd)"' in script
    assert '--add-data "${ROOT_DIR}/app/static:app/static"' in script
    assert '--add-data "${ROOT_DIR}/app:app"' in script


def test_build_mac_can_bundle_local_asr_models_and_optional_faster_whisper():
    script = (ROOT / "build_mac.sh").read_text(encoding="utf-8")

    assert "ASR_MODEL_DATA_ARGS" in script
    assert '[ -d "$ROOT_DIR/models/asr" ]' in script
    assert '--add-data "${ROOT_DIR}/models/asr:models/asr"' in script
    assert '"${ASR_MODEL_DATA_ARGS[@]}"' in script
    assert "ASR_BACKEND_ARGS" in script
    assert 'python3 -c "import faster_whisper"' in script
    assert "--collect-all faster_whisper" in script
    assert '"${ASR_BACKEND_ARGS[@]}"' in script


def test_build_mac_requires_subtitle_capable_ffmpeg():
    script = (ROOT / "build_mac.sh").read_text(encoding="utf-8")

    assert "FFMPEG_CANDIDATES" in script
    assert "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg" in script
    assert "/usr/local/opt/ffmpeg-full/bin/ffmpeg" in script
    assert "-hide_banner -filters" in script
    assert " subtitles " in script
    assert "ERROR: ffmpeg with subtitles filter not found" in script


def test_packaging_builds_local_frontend_assets_before_bundling():
    build_mac = (ROOT / "build_mac.sh").read_text(encoding="utf-8")
    build_win = (ROOT / "build_win.bat").read_text(encoding="utf-8")
    root_package = (ROOT / "package.json").read_text(encoding="utf-8")
    electron_package = (ROOT / "electron/package.json").read_text(encoding="utf-8")

    assert '"build:css"' in root_package
    assert build_mac.index("npm run build:css") < build_mac.index("python3 -m PyInstaller")
    assert build_win.index("npm run build:css") < build_win.index("python -m PyInstaller")
    assert '"prebuild-mac": "cd .. && npm run build:css"' in electron_package
    assert '"prebuild-win": "cd .. && npm run build:css"' in electron_package


def test_pyinstaller_builds_exclude_test_only_modules():
    build_mac = (ROOT / "build_mac.sh").read_text(encoding="utf-8")
    build_win = (ROOT / "build_win.bat").read_text(encoding="utf-8")

    assert "--exclude-module pytest" in build_mac
    assert "--exclude-module guessit.test" in build_mac
    assert "--exclude-module guessit.test.test_api" in build_mac
    assert "--exclude-module torch.utils.tensorboard" in build_mac
    assert "--hidden-import pycryptodomex" not in build_mac

    assert "--exclude-module pytest" in build_win
    assert "--exclude-module torch.utils.tensorboard" in build_win


def test_mac_pyinstaller_excludes_non_macos_optional_platform_modules():
    build_mac = (ROOT / "build_mac.sh").read_text(encoding="utf-8")
    spec = (ROOT / "AI Sub Pro.spec").read_text(encoding="utf-8")
    excluded = (
        "webview.platforms.android",
        "webview.platforms.win32",
        "webview.platforms.winforms",
        "webview.platforms.edgechromium",
        "webview.platforms.mshtml",
        "webview.platforms.gtk",
        "webview.platforms.qt",
        "webview.platforms.cef",
        "urllib3.contrib.emscripten",
    )

    for module in excluded:
        assert f"--exclude-module {module}" in build_mac
        assert f"'{module}'" in spec


def test_mac_pyinstaller_keeps_pywebview_collection_macos_only():
    build_mac = (ROOT / "build_mac.sh").read_text(encoding="utf-8")
    spec = (ROOT / "AI Sub Pro.spec").read_text(encoding="utf-8")

    assert "--hidden-import webview" in build_mac
    assert "--hidden-import webview.platforms.cocoa" in build_mac
    assert "--collect-all webview" not in build_mac
    assert "'webview.platforms.cocoa'" in spec
    assert "collect_all('webview')" not in spec


def test_pyinstaller_includes_selected_uvicorn_websocket_backend():
    build_mac = (ROOT / "build_mac.sh").read_text(encoding="utf-8")
    build_win = (ROOT / "build_win.bat").read_text(encoding="utf-8")
    spec = (ROOT / "AI Sub Pro.spec").read_text(encoding="utf-8")

    assert "--hidden-import uvicorn.protocols.websockets.websockets_sansio_impl" in build_mac
    assert "--hidden-import uvicorn.protocols.websockets.websockets_sansio_impl" in build_win
    assert "uvicorn.protocols.websockets.websockets_sansio_impl" in spec


def test_make_dmg_rebuilds_app_before_packaging():
    script = (ROOT / "make_dmg.sh").read_text(encoding="utf-8")

    assert "bash build_mac.sh" in script
    assert "if [ ! -d \"$APP_PATH\" ]" not in script
    assert script.index("bash build_mac.sh") < script.index("codesign --remove-signature")


def test_make_dmg_hdiutil_fallback_includes_applications_shortcut():
    script = (ROOT / "make_dmg.sh").read_text(encoding="utf-8")

    assert "DMG_STAGING" in script
    assert 'ln -s /Applications "$DMG_STAGING/Applications"' in script
    assert 'cp -R "$APP_PATH" "$DMG_STAGING/"' in script
    assert 'hdiutil create -volname "${APP_NAME}" -srcfolder "$DMG_STAGING"' in script
    assert '-srcfolder "$APP_PATH"' not in script


def test_make_dmg_uses_stable_hdiutil_by_default_and_create_dmg_is_opt_in():
    script = (ROOT / "make_dmg.sh").read_text(encoding="utf-8")

    assert 'USE_CREATE_DMG="${AISUBPRO_USE_CREATE_DMG:-0}"' in script
    assert 'if [ "$USE_CREATE_DMG" = "1" ] && command -v create-dmg &>/dev/null; then' in script
    assert script.index('USE_CREATE_DMG="${AISUBPRO_USE_CREATE_DMG:-0}"') < script.index('if [ "$USE_CREATE_DMG" = "1" ]')
    assert 'else\n    # 用系统自带的 hdiutil' in script
    assert script.index('else\n    # 用系统自带的 hdiutil') < script.index('create_hdiutil_dmg\nfi')


def test_make_dmg_cleans_failed_create_dmg_temp_mounts_before_fallback():
    script = (ROOT / "make_dmg.sh").read_text(encoding="utf-8")

    assert "cleanup_create_dmg_temp_images()" in script
    assert "hdiutil info | awk" in script
    assert 'index($0, "/rw.")' in script
    assert 'index($0, "." dmg ".dmg")' in script
    assert 'hdiutil detach "$dev" -quiet' in script
    assert 'hdiutil detach "$dev" -force -quiet' in script
    assert 'find dist -maxdepth 1 -name "rw.*.${DMG_NAME}.dmg"' in script

    cleanup = script[script.index("cleanup() {") : script.index("create_hdiutil_dmg()")]
    assert "cleanup_create_dmg_temp_images" in cleanup

    fallback = script[script.index("create-dmg \\") : script.index("else\n    # 用系统自带的 hdiutil")]
    assert fallback.index("cleanup_create_dmg_temp_images") < fallback.index("create_hdiutil_dmg")


def test_start_script_uses_headless_backend_for_browser_entrypoint():
    script = (ROOT / "start.sh").read_text(encoding="utf-8")

    assert "app/main.py --headless" in script
    assert "http://127.0.0.1:18090" in script
    assert "sleep 2" not in script
    assert "curl -fsS" in script
    assert 'kill -0 "$PID"' in script
    assert "trap cleanup EXIT INT TERM" in script
    assert script.index('if curl -fsS "$URL"') < script.index("python3 app/main.py --headless")


def test_electron_starts_python_backend_headless_on_loopback():
    main_js = (ROOT / "electron/main.js").read_text(encoding="utf-8")

    assert "const BACKEND_URL = 'http://127.0.0.1:18090';" in main_js
    assert "spawn(cmd, [appPath, '--headless']" in main_js


def test_electron_reuses_existing_loopback_backend_before_spawning_python():
    main_js = (ROOT / "electron/main.js").read_text(encoding="utf-8")

    assert "async function backendReady()" in main_js
    assert "let backendOwned = false;" in main_js
    assert "backendOwned = true;" in main_js
    assert "if (!backendOwned || !pythonProcess) return;" in main_js
    assert main_js.index("if (await backendReady())") < main_js.index("  startBackend();")


def test_electron_activate_rechecks_backend_before_creating_window():
    main_js = (ROOT / "electron/main.js").read_text(encoding="utf-8")
    ensure_window = main_js[main_js.index("async function ensureWindow()"):]

    assert "if (!(await backendReady()))" in ensure_window
    assert "if (!pythonProcess) startBackend();" in ensure_window
    assert "await waitForBackend();" in ensure_window
    assert "app.on('activate', () => { ensureWindow().catch(showStartupFailure); });" in main_js
    assert "if (!mainWindow) createWindow();" not in main_js


def test_electron_keeps_backend_alive_when_all_macos_windows_close():
    main_js = (ROOT / "electron/main.js").read_text(encoding="utf-8")

    window_all_closed = main_js[main_js.index("app.on('window-all-closed'"):]

    assert "if (process.platform !== 'darwin')" in window_all_closed
    assert window_all_closed.index("if (process.platform !== 'darwin')") < window_all_closed.index("killBackend();")
    assert "app.on('before-quit', killBackend);" in main_js


def test_electron_does_not_report_intentional_backend_shutdown_as_crash():
    main_js = (ROOT / "electron/main.js").read_text(encoding="utf-8")

    assert "let backendStopping = false;" in main_js
    assert "backendStopping = false;" in main_js[main_js.index("function startBackend()"):]
    assert "backendStopping = true;" in main_js[main_js.index("function killBackend()"):]
    assert "if (backendStopping || !backendOwned)" in main_js
    assert main_js.index("if (backendStopping || !backendOwned)") < main_js.index("dialog.showErrorBox('后端退出'")


def test_electron_opens_external_links_in_system_browser():
    main_js = (ROOT / "electron/main.js").read_text(encoding="utf-8")

    assert "shell" in main_js
    assert "setWindowOpenHandler" in main_js
    assert "will-navigate" in main_js
    assert "shell.openExternal(url)" in main_js
    assert "return { action: 'deny' };" in main_js


def test_electron_uses_user_data_dir_and_does_not_bundle_local_runtime_data():
    main_js = (ROOT / "electron/main.js").read_text(encoding="utf-8")
    package_json = (ROOT / "electron/package.json").read_text(encoding="utf-8")

    assert "AI_SUB_PRO_DATA_DIR" in main_js
    assert "app.getPath('userData')" in main_js
    assert '"from": "../data"' not in package_json


def test_windows_build_checks_ffprobe_and_launcher_uses_headless_loopback():
    script = (ROOT / "build_win.bat").read_text(encoding="utf-8")

    assert "where ffprobe >nul 2>&1" in script
    assert 'echo start "" "AI Sub Pro\\AI Sub Pro.exe" --headless' in script
    assert "http://127.0.0.1:18090" in script
    assert "timeout /t 3" not in script
    assert "Invoke-WebRequest" in script
    assert "for /l %%%%i in" in script


def test_gitignore_excludes_runtime_data_and_recovery_files():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    for pattern in (
        "data/config.json",
        "data/config.invalid-*.json",
        "data/knowledge.json",
        "data/knowledge.v1.backup.json",
    ):
        assert pattern in gitignore
