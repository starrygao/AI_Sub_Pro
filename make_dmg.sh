#!/bin/bash
# 构建 AI Sub Pro macOS DMG 安装包
# 产出: dist/AI_Sub_Pro_v1.3.1.dmg
set -e
cd "$(dirname "$0")"

APP_NAME="AI Sub Pro"
VERSION="1.3.1"
DMG_NAME="AI_Sub_Pro_v${VERSION}"
APP_PATH="dist/${APP_NAME}.app"
DMG_STAGING=""
USE_CREATE_DMG="${AISUBPRO_USE_CREATE_DMG:-0}"

cleanup_create_dmg_temp_images() {
    # create-dmg can leave a mounted read-write image behind when the
    # customization phase fails. Clean those before falling back to hdiutil.
    hdiutil info | awk -v dmg="${DMG_NAME}" '
        /^image-path[[:space:]]*:/ {
            active = (index($0, "/rw.") && index($0, "." dmg ".dmg"))
            next
        }
        active && /^\/dev\// {
            print $1
        }
    ' | while read dev; do
        hdiutil detach "$dev" -quiet 2>/dev/null || hdiutil detach "$dev" -force -quiet 2>/dev/null || true
    done

    find dist -maxdepth 1 -name "rw.*.${DMG_NAME}.dmg" -type f -print0 2>/dev/null | while IFS= read -r -d '' image; do
        rm -f "$image"
    done
}

cleanup() {
    cleanup_create_dmg_temp_images
    if [ -n "$DMG_STAGING" ] && [ -d "$DMG_STAGING" ]; then
        rm -rf "$DMG_STAGING"
    fi
}
trap cleanup EXIT

create_hdiutil_dmg() {
    cleanup
    DMG_STAGING="$(mktemp -d)"
    cp -R "$APP_PATH" "$DMG_STAGING/"
    ln -s /Applications "$DMG_STAGING/Applications"
    hdiutil create -volname "${APP_NAME}" -srcfolder "$DMG_STAGING" -ov -format UDZO "dist/${DMG_NAME}.dmg"
}

echo "=== 构建 AI Sub Pro v${VERSION} DMG 安装包 ==="
echo ""

# ── 第1步: 构建最新 .app ──
echo "[1/5] 构建最新 .app..."
bash build_mac.sh

echo "[2/5] 找到 ${APP_PATH}"
du -sh "$APP_PATH"

# ── 第3步: Ad-hoc 代码签名（让其他 Mac 可以运行）──
echo ""
echo "[3/5] 代码签名 (ad-hoc)..."
# 移除旧签名
codesign --remove-signature "$APP_PATH" 2>/dev/null || true
# 对所有 .so / .dylib 签名
find "$APP_PATH" -name "*.so" -o -name "*.dylib" | while read lib; do
    codesign --force --sign - "$lib" 2>/dev/null || true
done
# 对 ffmpeg/ffprobe 签名
find "$APP_PATH" -name "ffmpeg" -o -name "ffprobe" | while read bin; do
    codesign --force --sign - "$bin" 2>/dev/null || true
done
# 对主可执行文件签名
find "$APP_PATH/Contents/MacOS" -type f -perm +111 | while read exe; do
    codesign --force --sign - "$exe" 2>/dev/null || true
done
# 对整个 .app 签名
codesign --force --deep --sign - "$APP_PATH"
echo "  签名完成"

# 验证签名
codesign --verify --deep "$APP_PATH" 2>&1 && echo "  签名验证: 通过" || echo "  签名验证: 部分警告（ad-hoc 正常）"

# ── 第4步: 创建 DMG ──
echo ""
echo "[4/5] 创建 DMG 安装包..."
rm -f "dist/${DMG_NAME}.dmg"

if [ "$USE_CREATE_DMG" = "1" ] && command -v create-dmg &>/dev/null; then
    create-dmg \
        --volname "${APP_NAME}" \
        --volicon "$APP_PATH/Contents/Resources/AppIcon.icns" 2>/dev/null \
        --window-pos 200 120 \
        --window-size 660 400 \
        --icon-size 100 \
        --icon "${APP_NAME}.app" 180 190 \
        --hide-extension "${APP_NAME}.app" \
        --app-drop-link 480 190 \
        --no-internet-enable \
        "dist/${DMG_NAME}.dmg" \
        "$APP_PATH" \
    || {
        # create-dmg 可能因为缺少图标报错，用简单方式
        echo "  create-dmg 高级模式失败，使用 hdiutil..."
        cleanup_create_dmg_temp_images
        create_hdiutil_dmg
    }
else
    # 用系统自带的 hdiutil
    create_hdiutil_dmg
fi

prepare_release_metadata() {
    if command -v python3 >/dev/null 2>&1; then
        python3 tools/release/prepare_release.py \
            --dist-dir dist \
            --output dist/release-size-report.json \
            --checksum-dir dist
        echo "  release metadata: dist/release-size-report.json and .sha256 files"
    else
        echo "  python3 not found; skipped release checksum metadata"
    fi
}

prepare_release_metadata

# ── 第5步: 完成 ──
echo ""
echo "[5/5] 构建完成!"
echo ""
DMG_SIZE=$(du -sh "dist/${DMG_NAME}.dmg" | awk '{print $1}')
echo "  DMG: dist/${DMG_NAME}.dmg ($DMG_SIZE)"
echo ""
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  安装方式:"
echo "    1. 双击 DMG 打开"
echo "    2. 将 AI Sub Pro 拖入 Applications"
echo "    3. 首次打开: 右键 → 打开 (绕过 Gatekeeper)"
echo "    4. 若未随 app 打包 ASR 模型，首次识别会自动下载 Whisper 模型"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
