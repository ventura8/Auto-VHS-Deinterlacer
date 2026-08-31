#!/usr/bin/env bash
set -euo pipefail

# Build Debian (.deb) package for Auto-VHS-Deinterlacer
# Usage: ./build_deb.sh <version> [output_dir]

VERSION="${1:-1.1.0}"
OUTPUT_DIR="${2:-dist}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

ARCH="amd64"
PKG_NAME="auto-vhs-deinterlacer"
BUILD_DIR="${REPO_ROOT}/build/deb/${PKG_NAME}_${VERSION}_${ARCH}"

echo "==> Building Debian package for ${PKG_NAME} v${VERSION} (${ARCH})..."

rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}/DEBIAN"
mkdir -p "${BUILD_DIR}/opt/auto-vhs-deinterlacer"
mkdir -p "${BUILD_DIR}/usr/local/bin"
mkdir -p "${OUTPUT_DIR}"

# Copy application files
cp -r "${REPO_ROOT}/auto_deinterlancer.py" "${BUILD_DIR}/opt/auto-vhs-deinterlacer/"
cp -r "${REPO_ROOT}/config.yaml" "${BUILD_DIR}/opt/auto-vhs-deinterlacer/"
cp -r "${REPO_ROOT}/install.sh" "${BUILD_DIR}/opt/auto-vhs-deinterlacer/"
cp -r "${REPO_ROOT}/start.sh" "${BUILD_DIR}/opt/auto-vhs-deinterlacer/"
cp -r "${REPO_ROOT}/LICENSE" "${BUILD_DIR}/opt/auto-vhs-deinterlacer/"
cp -r "${REPO_ROOT}/README.md" "${BUILD_DIR}/opt/auto-vhs-deinterlacer/"
cp -r "${REPO_ROOT}/pyproject.toml" "${BUILD_DIR}/opt/auto-vhs-deinterlacer/"
cp -r "${REPO_ROOT}/poetry.lock" "${BUILD_DIR}/opt/auto-vhs-deinterlacer/"
cp -r "${REPO_ROOT}/modules" "${BUILD_DIR}/opt/auto-vhs-deinterlacer/"
cp -r "${REPO_ROOT}/assets" "${BUILD_DIR}/opt/auto-vhs-deinterlacer/"

chmod +x "${BUILD_DIR}/opt/auto-vhs-deinterlacer/install.sh"
chmod +x "${BUILD_DIR}/opt/auto-vhs-deinterlacer/start.sh"

# Create launcher symlink in /usr/local/bin
cat << 'EOF' > "${BUILD_DIR}/usr/local/bin/auto-vhs-deinterlacer"
#!/usr/bin/env bash
exec /opt/auto-vhs-deinterlacer/start.sh "$@"
EOF
chmod +x "${BUILD_DIR}/usr/local/bin/auto-vhs-deinterlacer"

# Generate DEBIAN/control
cat << EOF > "${BUILD_DIR}/DEBIAN/control"
Package: ${PKG_NAME}
Version: ${VERSION}
Section: video
Priority: optional
Architecture: ${ARCH}
Maintainer: Sergiu Alexandrescu <alexandrescu.sergiu@gmail.com>
Depends: python3 (>= 3.12), python3-venv, ffmpeg
Description: Automated VHS Deinterlacer and Restoration Pipeline
 Studio-grade automated deinterlacing and audio synchronization tool
 for modernizing VHS captures with VapourSynth (QTGMC) and FFmpeg.
EOF

# Generate DEBIAN/postinst
cat << 'EOF' > "${BUILD_DIR}/DEBIAN/postinst"
#!/usr/bin/env bash
set -e
echo "Auto-VHS-Deinterlacer installed to /opt/auto-vhs-deinterlacer."
echo "To initialize the virtual environment, run:"
echo "  cd /opt/auto-vhs-deinterlacer && ./install.sh"
exit 0
EOF
chmod 755 "${BUILD_DIR}/DEBIAN/postinst"

# Build package
dpkg-deb --build --root-owner-group "${BUILD_DIR}" "${OUTPUT_DIR}/${PKG_NAME}_${VERSION}_${ARCH}.deb"
echo "==> Successfully created ${OUTPUT_DIR}/${PKG_NAME}_${VERSION}_${ARCH}.deb"
