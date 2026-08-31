#!/usr/bin/env bash
set -euo pipefail

# Build macOS installer package (.pkg) with native .app bundle for Auto-VHS-Deinterlacer
# Usage: ./build_pkg.sh <version> <arch> [output_dir]
# arch: "arm64" or "x86_64"

VERSION="${1:-1.1.0}"
ARCH="${2:-arm64}"
OUTPUT_DIR="${3:-dist}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

PKG_IDENTIFIER="com.ventura8.auto-vhs-deinterlacer"
APP_NAME="Auto-VHS-Deinterlacer.app"
INSTALL_LOCATION="/Applications"
BUILD_ROOT="${REPO_ROOT}/build/pkg_${ARCH}"
PKG_ROOT="${BUILD_ROOT}/payload"
APP_BUNDLE="${PKG_ROOT}/${APP_NAME}"
CONTENTS_DIR="${APP_BUNDLE}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"
SCRIPTS_DIR="${BUILD_ROOT}/scripts"

ARCH_LABEL="AppleSilicon"
if [ "$ARCH" = "x86_64" ]; then
    ARCH_LABEL="Intel"
fi

PKG_OUTPUT="${OUTPUT_DIR}/Auto-VHS-Deinterlacer-v${VERSION}-${ARCH_LABEL}.pkg"

echo "==> Assembling macOS .app bundle and PKG for Auto-VHS-Deinterlacer v${VERSION} (${ARCH_LABEL})..."

rm -rf "${BUILD_ROOT}"
mkdir -p "${MACOS_DIR}"
mkdir -p "${RESOURCES_DIR}"
mkdir -p "${SCRIPTS_DIR}"
mkdir -p "${OUTPUT_DIR}"

# 1. Copy Application Payload into Resources
cp -r "${REPO_ROOT}/auto_deinterlancer.py" "${RESOURCES_DIR}/"
cp -r "${REPO_ROOT}/config.yaml" "${RESOURCES_DIR}/"
cp -r "${REPO_ROOT}/install.sh" "${RESOURCES_DIR}/"
cp -r "${REPO_ROOT}/start.sh" "${RESOURCES_DIR}/"
cp -r "${REPO_ROOT}/LICENSE" "${RESOURCES_DIR}/"
cp -r "${REPO_ROOT}/README.md" "${RESOURCES_DIR}/"
cp -r "${REPO_ROOT}/pyproject.toml" "${RESOURCES_DIR}/"
cp -r "${REPO_ROOT}/poetry.lock" "${RESOURCES_DIR}/"
cp -r "${REPO_ROOT}/modules" "${RESOURCES_DIR}/"
cp -r "${REPO_ROOT}/assets" "${RESOURCES_DIR}/"

chmod +x "${RESOURCES_DIR}/install.sh"
chmod +x "${RESOURCES_DIR}/start.sh"

# 2. Create Contents/Info.plist
cat << EOF > "${CONTENTS_DIR}/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Auto-VHS-Deinterlacer</string>
    <key>CFBundleDisplayName</key>
    <string>Auto-VHS-Deinterlacer</string>
    <key>CFBundleIdentifier</key>
    <string>${PKG_IDENTIFIER}</string>
    <key>CFBundleVersion</key>
    <string>${VERSION}</string>
    <key>CFBundleShortVersionString</key>
    <string>${VERSION}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleSignature</key>
    <string>????</string>
    <key>CFBundleExecutable</key>
    <string>Auto-VHS-Deinterlacer</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>CFBundleDocumentTypes</key>
    <array>
        <dict>
            <key>CFBundleTypeName</key>
            <string>Video File</string>
            <key>CFBundleTypeRole</key>
            <string>Viewer</string>
            <key>LSHandlerRank</key>
            <string>Alternate</string>
            <key>CFBundleTypeExtensions</key>
            <array>
                <string>mp4</string>
                <string>mov</string>
                <string>mkv</string>
                <string>avi</string>
                <string>ts</string>
            </array>
        </dict>
    </array>
</dict>
</plist>
EOF

# 3. Create PkgInfo
echo "APPL????" > "${CONTENTS_DIR}/PkgInfo"

# 4. Create Contents/MacOS/Auto-VHS-Deinterlacer Executable Launcher
cat << 'EOF' > "${MACOS_DIR}/Auto-VHS-Deinterlacer"
#!/usr/bin/env bash
set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESOURCES_DIR="${APP_DIR}/Resources"
cd "${RESOURCES_DIR}"

if [ ! -f ".venv/bin/python" ] && [ ! -f ".VENV/bin/python" ]; then
    echo "[INFO] Virtual environment not found. Bootstrapping Auto-VHS-Deinterlacer..."
    "${RESOURCES_DIR}/install.sh"
fi

exec "${RESOURCES_DIR}/start.sh" "$@"
EOF
chmod +x "${MACOS_DIR}/Auto-VHS-Deinterlacer"

# 5. Create postinstall script to symlink into /usr/local/bin
cat << 'EOF' > "${SCRIPTS_DIR}/postinstall"
#!/usr/bin/env bash
set -e
APP_PATH="/Applications/Auto-VHS-Deinterlacer.app"
BIN_LINK="/usr/local/bin/auto-vhs-deinterlacer"

mkdir -p /usr/local/bin
cat << 'LAUNCHER' > "$BIN_LINK"
#!/usr/bin/env bash
exec /Applications/Auto-VHS-Deinterlacer.app/Contents/MacOS/Auto-VHS-Deinterlacer "$@"
LAUNCHER
chmod +x "$BIN_LINK"

echo "Auto-VHS-Deinterlacer installed to $APP_PATH"
exit 0
EOF
chmod 755 "${SCRIPTS_DIR}/postinstall"

# 6. Build component package using pkgbuild
pkgbuild \
    --root "${PKG_ROOT}" \
    --identifier "${PKG_IDENTIFIER}" \
    --version "${VERSION}" \
    --install-location "${INSTALL_LOCATION}" \
    --scripts "${SCRIPTS_DIR}" \
    "${PKG_OUTPUT}"

echo "==> Successfully created ${PKG_OUTPUT}"
