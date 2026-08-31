#!/usr/bin/env bash
set -euo pipefail

# Build RPM (.rpm) package for Auto-VHS-Deinterlacer
# Usage: ./build_rpm.sh <version> [output_dir]

VERSION="${1:-1.1.0}"
OUTPUT_DIR="${2:-dist}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

ARCH="x86_64"
PKG_NAME="auto-vhs-deinterlacer"
RPMBUILD_DIR="${REPO_ROOT}/build/rpmbuild"

echo "==> Building RPM package for ${PKG_NAME} v${VERSION} (${ARCH})..."

rm -rf "${RPMBUILD_DIR}"
mkdir -p "${RPMBUILD_DIR}"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
mkdir -p "${OUTPUT_DIR}"

SPEC_FILE="${RPMBUILD_DIR}/SPECS/${PKG_NAME}.spec"

cat << EOF > "${SPEC_FILE}"
Name:           ${PKG_NAME}
Version:        ${VERSION}
Release:        1%{?dist}
Summary:        Automated VHS Deinterlacer and Restoration Pipeline
License:        MIT
URL:            https://github.com/ventura8/Auto-VHS-Deinterlacer
Requires:       python3 >= 3.12, ffmpeg

%description
Studio-grade automated deinterlacing and audio synchronization tool
for modernizing VHS captures with VapourSynth (QTGMC) and FFmpeg.

%install
rm -rf %{buildroot}
mkdir -p %{buildroot}/opt/auto-vhs-deinterlacer
mkdir -p %{buildroot}/usr/local/bin

cp -r ${REPO_ROOT}/auto_deinterlancer.py %{buildroot}/opt/auto-vhs-deinterlacer/
cp -r ${REPO_ROOT}/config.yaml %{buildroot}/opt/auto-vhs-deinterlacer/
cp -r ${REPO_ROOT}/install.sh %{buildroot}/opt/auto-vhs-deinterlacer/
cp -r ${REPO_ROOT}/start.sh %{buildroot}/opt/auto-vhs-deinterlacer/
cp -r ${REPO_ROOT}/LICENSE %{buildroot}/opt/auto-vhs-deinterlacer/
cp -r ${REPO_ROOT}/README.md %{buildroot}/opt/auto-vhs-deinterlacer/
cp -r ${REPO_ROOT}/pyproject.toml %{buildroot}/opt/auto-vhs-deinterlacer/
cp -r ${REPO_ROOT}/poetry.lock %{buildroot}/opt/auto-vhs-deinterlacer/
cp -r ${REPO_ROOT}/modules %{buildroot}/opt/auto-vhs-deinterlacer/
cp -r ${REPO_ROOT}/assets %{buildroot}/opt/auto-vhs-deinterlacer/

chmod +x %{buildroot}/opt/auto-vhs-deinterlacer/install.sh
chmod +x %{buildroot}/opt/auto-vhs-deinterlacer/start.sh

cat << 'LAUNCHER' > %{buildroot}/usr/local/bin/auto-vhs-deinterlacer
#!/usr/bin/env bash
exec /opt/auto-vhs-deinterlacer/start.sh "\$@"
LAUNCHER
chmod +x %{buildroot}/usr/local/bin/auto-vhs-deinterlacer

%files
/opt/auto-vhs-deinterlacer
/usr/local/bin/auto-vhs-deinterlacer

%post
echo "Auto-VHS-Deinterlacer installed to /opt/auto-vhs-deinterlacer."
echo "To initialize the virtual environment, run:"
echo "  cd /opt/auto-vhs-deinterlacer && ./install.sh"
EOF

rpmbuild --define "_topdir ${RPMBUILD_DIR}" -bb "${SPEC_FILE}"
cp "${RPMBUILD_DIR}/RPMS/${ARCH}"/*.rpm "${OUTPUT_DIR}/"
echo "==> Successfully created RPM package in ${OUTPUT_DIR}/"
