# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('app/static', 'app/static'), ('app', 'app')]
binaries = [('/opt/homebrew/bin/ffmpeg', 'bin'), ('/opt/homebrew/bin/ffprobe', 'bin')]
hiddenimports = ['uvicorn', 'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto', 'uvicorn.protocols.websockets.websockets_sansio_impl', 'uvicorn.lifespan', 'uvicorn.lifespan.on', 'fastapi', 'pydantic', 'starlette', 'starlette.routing', 'starlette.middleware', 'starlette.middleware.cors', 'starlette.responses', 'starlette.staticfiles', 'starlette.websockets', 'openai', 'httpx', 'anyio', 'anyio._backends', 'anyio._backends._asyncio', 'h11', 'websockets', 'webview', 'webview.platforms.cocoa', 'mlx_whisper', 'whisper', 'yt_dlp', 'yt_dlp.utils', 'yt_dlp.extractor', 'yt_dlp_ejs', 'guessit', 'babelfish', 'rebulk', 'brotli', 'Cryptodome', 'mutagen', 'certifi']
tmp_ret = collect_all('guessit')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('babelfish')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('mlx')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('openai')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('starlette')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('httpx')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('mlx_whisper')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('yt_dlp')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('yt_dlp_ejs')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app/main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pytest',
        'guessit.test',
        'guessit.test.rules',
        'guessit.test.rules.processors_test',
        'guessit.test.test_api',
        'guessit.test.test_api_unicode_literals',
        'guessit.test.test_benchmark',
        'guessit.test.test_main',
        'guessit.test.test_options',
        'guessit.test.test_yml',
        'tensorboard',
        'torch.utils.tensorboard',
        'webview.platforms.android',
        'webview.platforms.win32',
        'webview.platforms.winforms',
        'webview.platforms.edgechromium',
        'webview.platforms.mshtml',
        'webview.platforms.gtk',
        'webview.platforms.qt',
        'webview.platforms.cef',
        'urllib3.contrib.emscripten',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AI Sub Pro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AI Sub Pro',
)
app = BUNDLE(
    coll,
    name='AI Sub Pro.app',
    icon=None,
    bundle_identifier=None,
)
