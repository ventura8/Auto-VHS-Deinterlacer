#!/usr/bin/env bash
set -euo pipefail

# CI and headless installers must not depend on an interactive DBus keyring.
export POETRY_KEYRING_ENABLED=false

# ==============================================================================
#  Auto-VHS-Deinterlacer Installer (Linux & macOS)
# ==============================================================================
#  Author: Auto-VHS Team
#  Description:
#    Automated installer for Linux and macOS environments.
#    Sets up Python Virtual Environment (.venv), dependencies, QTGMC scripts,
#    verifies system media tooling (FFmpeg, VapourSynth), and creates start.sh.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================="
echo "  Auto-VHS-Deinterlacer Installer (POSIX)"
echo "=================================================="
echo ""

# ------------------------------------------------------------------------------
# 1. Detect OS & Platform
# ------------------------------------------------------------------------------
OS_TYPE="$(uname -s)"
echo "[INFO] Operating System: $OS_TYPE ($(uname -m))"

# ------------------------------------------------------------------------------
# 2. Check for Python 3.12
# ------------------------------------------------------------------------------
PYTHON_BIN=""
for candidate in python3.12 python3 /usr/bin/python3.12 /usr/local/bin/python3.12 /opt/homebrew/bin/python3.12 "$HOME/.local/bin/python3.12"; do
    if command -v "$candidate" >/dev/null 2>&1; then
        VER="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
        if [ "$VER" = "3.12" ]; then
            PYTHON_BIN="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "[ERROR] Python 3.12 is required but was not found."
    if [ "$OS_TYPE" = "Darwin" ]; then
        echo "  Install via Homebrew: brew install python@3.12"
    elif [ -f /etc/debian_version ]; then
        echo "  Install via APT: sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv python3.12-dev"
    elif [ -f /etc/arch-release ]; then
        echo "  Install via Pacman/AUR: sudo pacman -S python"
    elif [ -f /etc/fedora-release ]; then
        echo "  Install via DNF: sudo dnf install -y python3.12 python3.12-devel"
    fi
    exit 1
fi

echo "[INFO] Using Python: $("$PYTHON_BIN" --version) ($PYTHON_BIN)"

# ------------------------------------------------------------------------------
# 3. Create Virtual Environment
# ------------------------------------------------------------------------------
VENV_DIR="$SCRIPT_DIR/.venv"
if [ -d "$VENV_DIR" ]; then
    VENV_PY="$VENV_DIR/bin/python"
    if [ -x "$VENV_PY" ] && [ "$("$VENV_PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)" = "3.12" ]; then
        echo "[INFO] Existing Python 3.12 virtual environment found at .venv"
    else
        echo "[INFO] Recreating virtual environment at .venv..."
        rm -rf "$VENV_DIR"
        "$PYTHON_BIN" -m venv "$VENV_DIR"
    fi
else
    echo "[INFO] Creating Python Virtual Environment at .venv..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

# Print the lowercase SHA-256 of a file, preferring sha256sum (Linux) then
# shasum (macOS), and falling back to the venv Python so the installer never
# aborts under `set -e` on a host missing both utilities.
sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print tolower($1)}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print tolower($1)}'
    else
        "$VENV_PYTHON" -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$1"
    fi
}

# ------------------------------------------------------------------------------
# 4. Upgrade pip & Install Poetry
# ------------------------------------------------------------------------------
echo "[INFO] Upgrading pip..."
"$VENV_PIP" install --upgrade pip

echo "[INFO] Installing Poetry..."
"$VENV_PIP" install poetry==2.4.3

# ------------------------------------------------------------------------------
# 5. Install Dependencies via Poetry
# ------------------------------------------------------------------------------
echo "[INFO] Installing project runtime dependencies..."
"$VENV_PYTHON" -m poetry config virtualenvs.in-project true --local
"$VENV_PYTHON" -m poetry config virtualenvs.create false --local
if [ "${AVD_SKIP_ML_HEAVY:-0}" = "1" ]; then
    echo "   -> AVD_SKIP_ML_HEAVY=1 set; installing VapourSynth without optional ML dependencies."
    "$VENV_PYTHON" -m poetry install -v --only main --no-root
    "$VENV_PYTHON" -m pip install "vapoursynth==79"
else
    "$VENV_PYTHON" -m poetry install -v --only main,ml-heavy --no-root
fi

# ------------------------------------------------------------------------------
# 6. Setup havsfunc r33 with SHA-256 Integrity Verification
# ------------------------------------------------------------------------------
echo "[INFO] Setting up havsfunc r33 with SHA-256 integrity verification..."
HAVSFUNC_EXPECTED_SHA256="4da2839544b1ce9382db670b069dc358228251d147dad91f740a860840e04924"
SITE_PACKAGES="$("$VENV_PYTHON" -c 'import site; print(site.getsitepackages()[0])')"
HAVSFUNC_DEST="$SITE_PACKAGES/havsfunc.py"

mkdir -p "$SITE_PACKAGES"
HAVSFUNC_URL="https://raw.githubusercontent.com/HomeOfVapourSynthEvolution/havsfunc/r33/havsfunc.py"
HAVSFUNC_OK=0
for attempt in 1 2 3; do
    if command -v curl >/dev/null 2>&1; then
        if ! curl -fsSL "$HAVSFUNC_URL" -o "$HAVSFUNC_DEST"; then
            echo "[WARN] havsfunc.py download failed on attempt $attempt; retrying..."
            continue
        fi
    else
        if ! "$VENV_PYTHON" -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' \
            "$HAVSFUNC_URL" "$HAVSFUNC_DEST"; then
            echo "[WARN] havsfunc.py download failed on attempt $attempt; retrying..."
            continue
        fi
    fi

    DOWNLOADED_SHA256="$(sha256_of "$HAVSFUNC_DEST")"
    if [ "$DOWNLOADED_SHA256" = "$HAVSFUNC_EXPECTED_SHA256" ]; then
        HAVSFUNC_OK=1
        break
    else
        echo "[WARN] havsfunc.py SHA-256 integrity check failed on attempt $attempt! Expected: $HAVSFUNC_EXPECTED_SHA256, got: $DOWNLOADED_SHA256"
        rm -f "$HAVSFUNC_DEST"
        echo "       Deleted corrupt file; retrying download..."
    fi
done

if [ "$HAVSFUNC_OK" != 1 ]; then
    echo "[ERROR] havsfunc.py could not be downloaded with valid SHA-256 integrity after multiple attempts."
    exit 1
fi
echo "   -> havsfunc.py verified successfully."

echo "[INFO] Installing pinned mvsfunc dependency..."
if ! command -v git >/dev/null 2>&1; then
    echo "[WARN] git is unavailable; skipping pinned mvsfunc installation."
    echo "       Install git and rerun install.sh to enable mvsfunc-dependent filters."
else
    MVSFUNC_COMMIT="865c7486ca860d323754ec4774bc4cca540a7076"
    "$VENV_PYTHON" -m pip install --upgrade \
        "git+https://github.com/HomeOfVapourSynthEvolution/mvsfunc.git@$MVSFUNC_COMMIT"
fi

PATCH_SCRIPT="$SCRIPT_DIR/modules/core/patch_havsfunc.py"
if [ -f "$PATCH_SCRIPT" ]; then
    echo "   -> Patching havsfunc compatibility..."
    PYTHONPATH="$SCRIPT_DIR" "$VENV_PYTHON" -m modules.core.patch_havsfunc
fi

# ------------------------------------------------------------------------------
# 6b. Configure VapourSynth and build the native plugin stack (Linux / macOS)
# ------------------------------------------------------------------------------
# On Windows install.ps1 pulls prebuilt plugin DLLs via vsrepo. vsrepo has no
# Linux/macOS binaries, so here we assemble the same QTGMC stack. Plugins that
# ship as installable system libraries (ffms2 via libffms2) are copied straight
# from the OS package; the rest are compiled from source as a fallback so the
# pipeline behaves identically on every platform:
#   ffms2            - indexed source filter for MPEG files with irregular timestamps
#   bs (BestSource)  - general source filter (the wheel bundles none)
#   fmtc (fmtconv)    - resampling used by QTGMC SourceMatch / Lossless
#   mv (mvtools)      - motion estimation, the core of QTGMC
#   rgvs (RemoveGrain)- spatial smoothing / Repair
#   znedi3           - the default QTGMC edge-directed interpolator
#   eedi3m           - referenced unconditionally by havsfunc QTGMC_Interpolate
#   misc             - MiscFilters (Hysteresis) used by QTGMC noise paths
#   nnedi3cl         - OPTIONAL OpenCL interpolator; enables GPU QTGMC
#   fft3dfilter      - OPTIONAL denoiser; required by every QTGMC noise
#                      path (EZDenoise > 0 or NoiseProcess >= 1)
# Set AVD_SKIP_VS_PLUGINS=1 to skip this section.
echo "[INFO] Configuring VapourSynth for this virtual environment..."

vs_has() {
    "$VENV_PYTHON" - "$@" 2>/dev/null <<'PY'
import sys, vapoursynth as vs
c = vs.core
sys.exit(0 if all(hasattr(c, n) for n in sys.argv[1:]) else 1)
PY
}

REQUIRED_PLUGINS="ffms2 bs fmtc mv rgvs znedi3 eedi3m misc"
# Optional: absent on hosts without OpenCL. Included in the "already present"
# gate so a stack missing only the GPU plugin still enters the build section.
OPTIONAL_PLUGINS="nnedi3cl fft3dfilter"

if [ "${AVD_SKIP_VS_PLUGINS:-0}" = "1" ]; then
    echo "   -> AVD_SKIP_VS_PLUGINS=1 set; skipping VapourSynth plugin build."
elif vs_has $REQUIRED_PLUGINS $OPTIONAL_PLUGINS; then
    echo "   -> VapourSynth plugin stack already present."
else
    echo "[INFO] Building VapourSynth plugin stack (QTGMC) from source..."

    # Resolve the wheel's plugin autoload dir only once we know we are building,
    # so skipping the stack never imports vapoursynth (which would abort set -e).
    if ! VS_PKG_DIR="$("$VENV_PYTHON" -c 'import os, vapoursynth; print(os.path.dirname(vapoursynth.__file__))' 2>/dev/null)"; then
        echo "[ERROR] VapourSynth is unavailable in $VENV_DIR."
        echo "        Install the vapoursynth package in this virtual environment, then rerun install.sh."
        exit 1
    fi
    "$VENV_PYTHON" -m vapoursynth config || true
    VS_PLUGIN_DIR="$VS_PKG_DIR/plugins"
    mkdir -p "$VS_PLUGIN_DIR"
    export PKG_CONFIG_PATH="$VS_PKG_DIR/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"

    # --- Ensure the build toolchain is present --------------------------------
    # Run privileged package installs via sudo only when needed and available
    # (Docker images run as root with no sudo).
    SUDO=""
    if [ "$(id -u)" -ne 0 ]; then
        if command -v sudo >/dev/null 2>&1; then
            SUDO="sudo"
        else
            echo "[WARN] Not root and sudo is unavailable; cannot auto-install build packages."
        fi
    fi

    NEED_TOOLS=""
    for t in git meson ninja nasm autoconf automake pkg-config cmake make cc; do
        command -v "$t" >/dev/null 2>&1 || NEED_TOOLS="$NEED_TOOLS $t"
    done
    command -v libtoolize >/dev/null 2>&1 || command -v glibtoolize >/dev/null 2>&1 || NEED_TOOLS="$NEED_TOOLS libtool"
    NEED_FFMS_DEPS=0
    if ! pkg-config --exists libavformat libavcodec libavutil libswscale libswresample 2>/dev/null; then
        NEED_FFMS_DEPS=1
    fi
    if [ -n "$NEED_TOOLS" ] || [ "$NEED_FFMS_DEPS" -eq 1 ]; then
        echo "   -> Installing build dependencies${NEED_TOOLS:+:$NEED_TOOLS}"
        if [ "$OS_TYPE" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
            brew install nasm meson ninja autoconf automake libtool pkg-config cmake fftw xxhash ffmpeg >/dev/null || true
        elif [ -f /etc/debian_version ]; then
            $SUDO apt-get update -qq && $SUDO apt-get install -y --no-install-recommends \
                build-essential nasm meson ninja-build autoconf automake libtool \
                pkg-config cmake git libfftw3-dev libxxhash-dev libavformat-dev \
                libavcodec-dev libavutil-dev libswscale-dev libswresample-dev \
                libboost-filesystem-dev libboost-system-dev opencl-headers ocl-icd-opencl-dev || \
                echo "[WARN] Toolchain package install failed; plugin build may not complete."
        elif [ -f /etc/arch-release ]; then
            $SUDO pacman -S --needed --noconfirm base-devel nasm meson ninja autoconf automake libtool pkgconf cmake git fftw xxhash ffmpeg boost opencl-headers ocl-icd || true
        elif [ -f /etc/fedora-release ]; then
            $SUDO dnf install -y gcc gcc-c++ make nasm meson ninja-build autoconf automake libtool pkgconf-pkg-config cmake git zlib-devel fftw-devel xxhash-devel ffmpeg-free-devel boost-devel opencl-headers ocl-icd-devel || true
        else
            echo "[WARN] Unknown platform; install a C/C++ toolchain plus nasm, meson, ninja, autotools manually."
        fi
    fi

    VS_BUILD_DIR="$(mktemp -d)"
    NATIVE_FILE="$VS_BUILD_DIR/native.ini"
    cat > "$NATIVE_FILE" <<EOF
[binaries]
python = '$VENV_PYTHON'
python3 = '$VENV_PYTHON'
EOF

    # Build a meson-based VapourSynth plugin and copy its shared module out.
    vs_build_meson() {
        name="$1"; url="$2"; shift 2
        echo "   -> [$name] building (meson)..."
        d="$VS_BUILD_DIR/$name"
        git clone --depth 1 --recurse-submodules "$url" "$d" >/dev/null 2>&1 || { echo "[WARN] [$name] clone failed"; return 1; }
        if meson setup "$d/build" "$d" --native-file "$NATIVE_FILE" "$@" >"$d/setup.log" 2>&1 \
            && ninja -C "$d/build" >"$d/build.log" 2>&1; then
            find "$d/build" -maxdepth 1 \( -name '*.so' -o -name '*.dylib' \) -exec cp {} "$VS_PLUGIN_DIR/" \;
        else
            echo "[WARN] [$name] build failed (see $d/setup.log, $d/build.log)"; return 1
        fi
    }

    # Prefer an already-installed libffms2 over compiling one: the distro/Homebrew
    # shared library exports VapourSynthPluginInit2, so it loads directly as the
    # `ffms2` plugin (see AGENTS.md: prefer installed dependencies over source builds).
    vs_system_ffms2() {
        if [ "$OS_TYPE" = "Darwin" ]; then
            _brew_prefix="/usr/local"
            if command -v brew >/dev/null 2>&1; then
                _brew_prefix="$(brew --prefix)"
                brew list --versions ffms2 >/dev/null 2>&1 || brew install ffms2 >/dev/null 2>&1 || true
            fi
            for _p in "$_brew_prefix"/lib/libffms2*.dylib /usr/local/lib/libffms2*.dylib /opt/homebrew/lib/libffms2*.dylib; do
                [ -f "$_p" ] && { cp -f "$_p" "$VS_PLUGIN_DIR/libffms2.dylib"; return 0; }
            done
            return 1
        fi
        if ! ls /usr/lib/*/libffms2.so* /usr/lib/libffms2.so* /usr/lib64/libffms2.so* /usr/local/lib/libffms2.so* >/dev/null 2>&1; then
            if [ -f /etc/debian_version ]; then
                $SUDO apt-get update -qq >/dev/null 2>&1 || true
                for _pkg in libffms2-5 libffms2-4 libffms2-dev; do
                    $SUDO apt-get install -y --no-install-recommends "$_pkg" >/dev/null 2>&1 && break
                done
            elif [ -f /etc/arch-release ]; then
                $SUDO pacman -S --needed --noconfirm ffms2 >/dev/null 2>&1 || true
            elif [ -f /etc/fedora-release ]; then
                # Fedora's own libavcodec-free carries no H.264 decoder, so ffms2
                # linked against it cannot open the most common capture format.
                # RPM Fusion free ships the full FFmpeg as ffmpeg-libs; asking for
                # it explicitly is required, because "dnf install ffms2" alone is
                # satisfied by the -free libraries. --allowerasing swaps them out.
                if ! rpm -q rpmfusion-free-release >/dev/null 2>&1; then
                    $SUDO dnf install -y "https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm" >/dev/null 2>&1 || true
                fi
                $SUDO dnf install -y --allowerasing ffmpeg-libs ffms2 >/dev/null 2>&1 || true
            fi
        fi
        for _p in /usr/lib/*/libffms2.so* /usr/lib/libffms2.so* /usr/lib64/libffms2.so* /usr/local/lib/*/libffms2.so* /usr/local/lib/libffms2.so*; do
            [ -f "$_p" ] || continue
            case "$_p" in *.la) continue ;; esac
            cp -f "$_p" "$VS_PLUGIN_DIR/libffms2.so"
            return 0
        done
        return 1
    }

    # FFMS2 (provides ffms2). Its index-based decoding handles MPEG captures
    # whose frames have unknown timestamps, which BestSource cannot seek.
    if ! vs_has ffms2; then
        if vs_system_ffms2 && vs_has ffms2; then
            echo "   -> [ffms2] provided by installed libffms2 (no source build)."
        else
            echo "   -> [ffms2] building (autotools)..."
            d="$VS_BUILD_DIR/ffms2"
            if git clone --depth 1 https://github.com/FFMS/ffms2.git "$d" >/dev/null 2>&1 \
                && ( cd "$d" && ./autogen.sh && ./configure && make -j"$(getconf _NPROCESSORS_ONLN)" ) >"$VS_BUILD_DIR/ffms2.log" 2>&1; then
                if [ "$OS_TYPE" = "Darwin" ]; then
                    find "$d/src/core/.libs" -maxdepth 1 -type f -name 'libffms2*.dylib' -exec cp {} "$VS_PLUGIN_DIR/libffms2.dylib" \;
                else
                    cp "$d/src/core/.libs/libffms2.so" "$VS_PLUGIN_DIR/libffms2.so"
                fi
            else
                echo "[WARN] [ffms2] build failed (see $VS_BUILD_DIR/ffms2.log)"
            fi
        fi
    fi

    # bs (BestSource)
    vs_has bs || vs_build_meson bestsource https://github.com/vapoursynth/bestsource.git || true

    # fmtconv (autotools; provides fmtc)
    if ! vs_has fmtc; then
        echo "   -> [fmtconv] building (autotools)..."
        d="$VS_BUILD_DIR/fmtconv"
        if git clone --depth 1 https://github.com/EleonoreMizo/fmtconv.git "$d" >/dev/null 2>&1 \
            && ( cd "$d/build/unix" && ./autogen.sh && ./configure && make -j"$(getconf _NPROCESSORS_ONLN)" ) >"$VS_BUILD_DIR/fmtconv.log" 2>&1; then
            find "$d/build/unix/.libs" -maxdepth 1 -name 'libfmtconv.*' ! -name '*.la' -exec cp {} "$VS_PLUGIN_DIR/" \;
        else
            echo "[WARN] [fmtconv] build failed (see $VS_BUILD_DIR/fmtconv.log)"
        fi
    fi

    # mvtools (provides mv)
    vs_has mv || vs_build_meson vapoursynth-mvtools https://github.com/dubhater/vapoursynth-mvtools.git || true

    # RemoveGrain / Repair (provides rgvs)
    vs_has rgvs || vs_build_meson vs-removegrain https://github.com/vapoursynth/vs-removegrain.git || true

    # MiscFilters (provides misc)
    vs_has misc || vs_build_meson vs-miscfilters-obsolete https://github.com/vapoursynth/vs-miscfilters-obsolete.git || true

    # EEDI3 (provides eedi3m)
    vs_has eedi3m || vs_build_meson VapourSynth-EEDI3 https://github.com/HomeOfVapourSynthEvolution/VapourSynth-EEDI3.git || true

    # znedi3 (Makefile build; needs its weights file beside the .so)
    if ! vs_has znedi3; then
        echo "   -> [znedi3] building (make)..."
        d="$VS_BUILD_DIR/znedi3"
        ZN_ARGS=""
        case "$(uname -m)" in x86_64|amd64|i?86) ZN_ARGS="X86=1" ;; esac
        if git clone --depth 1 --recurse-submodules https://github.com/sekrit-twc/znedi3.git "$d" >/dev/null 2>&1 \
            && make -C "$d" -j"$(getconf _NPROCESSORS_ONLN)" $ZN_ARGS vsznedi3.so >"$VS_BUILD_DIR/znedi3.log" 2>&1; then
            cp "$d/vsznedi3.so" "$d/nnedi3_weights.bin" "$VS_PLUGIN_DIR/" \
                || echo "[WARN] [znedi3] built, but copying the plugin or its weights failed."
        else
            echo "[WARN] [znedi3] build failed (see $VS_BUILD_DIR/znedi3.log)"
        fi
    fi

    # fft3dfilter (OPTIONAL): QTGMC calls fft3dfilter for every noise-processing
    # path, so without it EZDenoise > 0 or NoiseProcess >= 1 raises AttributeError
    # and the generated script silently degrades to the Bob fallback. Native API4,
    # so it builds against the wheel headers with no extra flags. Needs fftw3f,
    # which the toolchain step already installs.
    if ! vs_has fft3dfilter; then
        vs_build_meson fft3dfilter https://github.com/myrsloik/VapourSynth-FFT3DFilter.git \
            && vs_has fft3dfilter && echo "   -> [fft3dfilter] QTGMC denoising available." \
            || echo "[WARN] [fft3dfilter] unavailable; QTGMC denoise options will fall back to Bob."
    fi

    # nnedi3cl (OPTIONAL, GPU): the OpenCL interpolator QTGMC uses when
    # manual_settings.use_gpu_opencl is on and EdiMode is the default nnedi3.
    # Without it QTGMC silently runs entirely on the CPU. Two quirks make this
    # build non-obvious, hence the explicit flags:
    #   * The plugin is still API3, but the VapourSynth wheel ships API4-only
    #     headers, so the API3 compatibility headers are fetched from the
    #     matching upstream tag. VapourSynth loads API3 plugins at runtime.
    #   * Boost.Compute reads cl_image_desc.mem_object, which the OpenCL headers
    #     only expose when __STRICT_ANSI__ is undefined -- so gnu++14, not c++14.
    # Failure here is never fatal: QTGMC falls back to the CPU znedi3 path.
    if ! vs_has nnedi3cl; then
        echo "   -> [nnedi3cl] building (meson, GPU/OpenCL)..."
        d="$VS_BUILD_DIR/nnedi3cl"
        api3="$VS_BUILD_DIR/api3"
        vs_ver="$("$VENV_PYTHON" -c 'import vapoursynth; print(vapoursynth.core.version_number())' 2>/dev/null || echo "")"
        mkdir -p "$api3"
        api3_ok=1
        for hdr in VapourSynth.h VSHelper.h; do
            curl -fsSL "https://raw.githubusercontent.com/vapoursynth/vapoursynth/R${vs_ver}/include/$hdr" \
                -o "$api3/$hdr" || api3_ok=0
        done
        if [ "$api3_ok" != 1 ] || [ -z "$vs_ver" ]; then
            echo "[WARN] [nnedi3cl] could not fetch API3 headers for R${vs_ver:-?}; skipping GPU plugin."
        elif git clone --depth 1 --recurse-submodules \
                https://github.com/HomeOfVapourSynthEvolution/VapourSynth-NNEDI3CL.git "$d" >/dev/null 2>&1 \
            && CXXFLAGS="-I$api3 ${CXXFLAGS:-}" meson setup "$d/build" "$d" --native-file "$NATIVE_FILE" \
                -Dcpp_std=gnu++14 >"$d/setup.log" 2>&1 \
            && ninja -C "$d/build" >"$d/build.log" 2>&1; then
            find "$d/build" -maxdepth 1 \( -name '*.so' -o -name '*.dylib' \) -exec cp {} "$VS_PLUGIN_DIR/" \;
            [ -f "$VS_PLUGIN_DIR/nnedi3_weights.bin" ] || cp "$d/NNEDI3CL/nnedi3_weights.bin" "$VS_PLUGIN_DIR/" 2>/dev/null || true
            vs_has nnedi3cl && echo "   -> [nnedi3cl] GPU QTGMC interpolation available." \
                || echo "[WARN] [nnedi3cl] built but did not load; QTGMC stays on CPU."
        else
            echo "[WARN] [nnedi3cl] build failed; QTGMC will run on CPU (see $d/setup.log, $d/build.log)."
        fi
    fi

    rm -rf "$VS_BUILD_DIR"

    if vs_has $REQUIRED_PLUGINS; then
        echo "   -> VapourSynth plugin stack ready: $REQUIRED_PLUGINS"
    else
        echo "[WARN] Some VapourSynth plugins are still missing. QTGMC may fall back to a"
        echo "       lower-quality deinterlacer. Missing:"
        for p in $REQUIRED_PLUGINS; do vs_has "$p" || echo "         - $p"; done
    fi
fi

# ------------------------------------------------------------------------------
# 6c. Install a self-contained FFmpeg (parity with Windows install.ps1)
# ------------------------------------------------------------------------------
# install.ps1 drops a static FFmpeg 9.0.2 into the venv so the pipeline does not
# depend on whatever the distro ships (Ubuntu 26.04 = 8.0.1). Do the same here:
# fetch a static build into .venv/bin, which the app puts first on PATH via
# modules/core/utils.py:setup_environment. Set AVD_SKIP_FFMPEG=1 to skip.
#
# Exact patch release pinned below (evermeet FF_VER, BtbN FF_VER and the SHA-256
# values). A .venv binary is only kept when it reports this exact version, so a
# bump here replaces an older 9.0.x that a previous install left behind.
FFMPEG_VERSION="9.0.2"

# True when the binary reports exactly $FFMPEG_VERSION. Matches
# "version 9.0.2 ..." (evermeet), "version n9.0.2-20260919 ..." (BtbN) and
# "version 9.0.2-essentials_build ..." (gyan) but not 9.0.1 or 9.0.21.
ffmpeg_is_pinned() {
    [ -x "$1" ] || return 1
    _ffv="$("$1" -version 2>/dev/null | head -n1 || true)"
    case "$_ffv" in
        *"version n${FFMPEG_VERSION} "*|*"version n${FFMPEG_VERSION}-"*|\
        *"version ${FFMPEG_VERSION} "*|*"version ${FFMPEG_VERSION}-"*) return 0 ;;
        *) return 1 ;;
    esac
}

# Download, verify and stage the evermeet.cx macOS FFmpeg/FFprobe builds.
# evermeet.cx publishes exact-versioned macOS (x86_64) builds but ships no
# checksum file, so the SHA-256 of each archive is pinned here (same pattern as
# HAVSFUNC_EXPECTED_SHA256 above and the FFmpeg pin in install.ps1). Any archive
# that does not match is deleted and nothing is installed.
# Usage: install_darwin_ffmpeg <tmp_dir>   -> sets FF_OK=1 on success.
# Kept as a self-contained function so tests/unit/test_runtime_helpers.py can
# execute it against fixture archives with a stubbed curl.
install_darwin_ffmpeg() {
    _ff_tmp="$1"
    # Kept literal (not $FFMPEG_VERSION) so the function stays self-contained
    # for the unit tests; keep it equal to FFMPEG_VERSION above.
    FF_VER="9.0.2"
    FFMPEG_ZIP_EXPECTED_SHA256="4acc0be580f9b2788029eb7bd4d645ff87968911b0a62aeeb3940d42d54558d5"
    FFPROBE_ZIP_EXPECTED_SHA256="24a9c968cd4da72d99c7245e914b921815835eb6dff01d99868031aebaf1d439"
    FF_GOT_ALL=1
    for tool in ffmpeg ffprobe; do
        case "$tool" in
            ffmpeg)  FF_ZIP_EXPECT="$FFMPEG_ZIP_EXPECTED_SHA256" ;;
            ffprobe) FF_ZIP_EXPECT="$FFPROBE_ZIP_EXPECTED_SHA256" ;;
        esac
        if ! curl -fsSL "https://evermeet.cx/ffmpeg/${tool}-${FF_VER}.zip" -o "$_ff_tmp/${tool}.zip"; then
            FF_GOT_ALL=0
            continue
        fi
        FF_ZIP_GOT="$(sha256_of "$_ff_tmp/${tool}.zip")"
        if [ "$FF_ZIP_GOT" != "$FF_ZIP_EXPECT" ]; then
            echo "[WARN] ${tool}-${FF_VER}.zip SHA-256 mismatch (expected $FF_ZIP_EXPECT, got $FF_ZIP_GOT)."
            echo "       Refusing to install the unverified archive."
            rm -f "$_ff_tmp/${tool}.zip"
            FF_GOT_ALL=0
            continue
        fi
        # Extract only the single expected binary, rejecting any path that
        # would escape the temp dir (zip-slip guard).
        "$VENV_PYTHON" - "$_ff_tmp/${tool}.zip" "$_ff_tmp" "$tool" <<'PYEOF' || FF_GOT_ALL=0
import os, sys, zipfile
zip_path, dest, tool = sys.argv[1:4]
dest = os.path.realpath(dest)
with zipfile.ZipFile(zip_path) as zf:
    names = zf.namelist()
    if names != [tool]:
        sys.exit(f"unexpected archive contents for {tool}: {names}")
    target = os.path.realpath(os.path.join(dest, tool))
    if os.path.dirname(target) != dest:
        sys.exit(f"refusing to extract {tool!r} outside {dest}")
    zf.extract(tool, dest)
PYEOF
    done
    if [ "$FF_GOT_ALL" = 1 ] && [ -f "$_ff_tmp/ffmpeg" ] && [ -f "$_ff_tmp/ffprobe" ]; then
        # Stage as one conditional so a cp/chmod failure does not abort the
        # installer under set -e; FF_OK stays 0 and the caller removes any
        # partial copy.
        if cp "$_ff_tmp/ffmpeg" "$_ff_tmp/ffprobe" "$VENV_DIR/bin/" \
           && chmod +x "$VENV_DIR/bin/ffmpeg" "$VENV_DIR/bin/ffprobe"; then
            FF_OK=1
        else
            echo "[WARN] Could not stage the FFmpeg binaries into $VENV_DIR/bin."
        fi
    fi
}

# Download, verify and stage the BtbN Linux FFmpeg build.
# A fixed autobuild tag and the SHA-256 of each archive are pinned here (same
# pattern as install_darwin_ffmpeg above and install.ps1). The "latest" tag is a
# moving target, and its checksums.sha256 lives in the same release as the
# archives, so it cannot protect against a swapped release. Bump FF_TAG, FF_VER
# (keep equal to FFMPEG_VERSION) and both hashes together. Any archive that
# does not match is deleted and nothing is installed.
# Usage: install_linux_ffmpeg <tmp_dir> <uname -m>   -> sets FF_OK=1 on success.
# Kept as a self-contained function so tests/unit/test_runtime_helpers.py can
# execute it against fixture archives with a stubbed curl.
install_linux_ffmpeg() {
    _ff_tmp="$1"
    FF_TAG="autobuild-2026-09-19-13-11"
    FF_VER="9.0.2"
    case "$2" in
        x86_64|amd64)
            FF_PLAT="linux64"
            FF_EXPECT="c67af56466837059601a1abd22109b7b771eeea137c9ff4b1db0bde66192dbc6" ;;
        aarch64|arm64)
            FF_PLAT="linuxarm64"
            FF_EXPECT="100182dfa879b37caa327b00f7020f04e2dd95c282e171efb92bff262259d463" ;;
        *)
            echo "[WARN] No prebuilt FFmpeg $FF_VER for architecture '$2'."
            return 0 ;;
    esac
    FF_BASE="https://github.com/BtbN/FFmpeg-Builds/releases/download/${FF_TAG}"
    FF_ASSET="ffmpeg-n${FF_VER}-${FF_PLAT}-gpl-${FF_VER%.*}.tar.xz"
    for attempt in 1 2 3; do
        rm -f "$_ff_tmp/ff.tar.xz"
        curl -fsSL "$FF_BASE/$FF_ASSET" -o "$_ff_tmp/ff.tar.xz" || continue
        FF_GOT="$(sha256_of "$_ff_tmp/ff.tar.xz")"
        if [ "$FF_EXPECT" != "$FF_GOT" ]; then
            echo "[WARN] FFmpeg archive SHA-256 mismatch on attempt $attempt (expected $FF_EXPECT, got $FF_GOT)."
            rm -f "$_ff_tmp/ff.tar.xz"
            echo "       Deleted corrupt archive; retrying download..."
            continue
        fi
        if ! tar -xf "$_ff_tmp/ff.tar.xz" -C "$_ff_tmp"; then
            echo "[WARN] Could not extract the FFmpeg archive on attempt $attempt."
            rm -f "$_ff_tmp/ff.tar.xz"
            continue
        fi
        FF_BIN="$(find "$_ff_tmp" -type d -name bin | head -n1)"
        if [ -z "$FF_BIN" ] || [ ! -f "$FF_BIN/ffmpeg" ] || [ ! -f "$FF_BIN/ffprobe" ]; then
            echo "[WARN] FFmpeg archive did not contain bin/ffmpeg and bin/ffprobe on attempt $attempt."
            continue
        fi
        # Stage as one conditional so a cp/chmod failure (disk full, permissions)
        # does not abort the installer under set -e; FF_OK stays 0 and the caller
        # removes any partial copy.
        if cp "$FF_BIN/ffmpeg" "$FF_BIN/ffprobe" "$VENV_DIR/bin/" \
           && chmod +x "$VENV_DIR/bin/ffmpeg" "$VENV_DIR/bin/ffprobe"; then
            FF_OK=1
            return 0
        fi
        echo "[WARN] Could not stage the FFmpeg binaries into $VENV_DIR/bin."
        return 0
    done
}

if [ "${AVD_SKIP_FFMPEG:-0}" = "1" ]; then
    echo "[INFO] AVD_SKIP_FFMPEG=1 set; skipping bundled FFmpeg."
elif ffmpeg_is_pinned "$VENV_DIR/bin/ffmpeg" && ffmpeg_is_pinned "$VENV_DIR/bin/ffprobe"; then
    echo "[INFO] Local FFmpeg $FFMPEG_VERSION already present in .venv."
else
    echo "[INFO] Installing self-contained FFmpeg $FFMPEG_VERSION into .venv/bin..."
    FF_TMP="$(mktemp -d)"
    FF_OK=0
    if [ "$OS_TYPE" = "Darwin" ]; then
        install_darwin_ffmpeg "$FF_TMP"
    else
        install_linux_ffmpeg "$FF_TMP" "$(uname -m)"
    fi
    rm -rf "$FF_TMP"
    if [ "$FF_OK" = 1 ] && ffmpeg_is_pinned "$VENV_DIR/bin/ffmpeg" && ffmpeg_is_pinned "$VENV_DIR/bin/ffprobe"; then
        echo "   -> $("$VENV_DIR/bin/ffmpeg" -version | head -n1)"
    else
        rm -f "$VENV_DIR/bin/ffmpeg" "$VENV_DIR/bin/ffprobe"
        echo "[WARN] Could not install bundled FFmpeg $FFMPEG_VERSION; the pipeline will"
        echo "       fall back to system FFmpeg. Install FFmpeg $FFMPEG_VERSION manually for parity."
    fi
fi

# ------------------------------------------------------------------------------
# 6b. NVENC (NVIDIA hardware encoding)
# ------------------------------------------------------------------------------
# FFmpeg's av1_nvenc needs three things: a GPU whose NVENC block can encode AV1
# (RTX 40 or 50 series; RTX 30 and older have NVENC but no AV1 encoder), the
# NVIDIA kernel driver, and the driver's userspace encode library
# libnvidia-encode.so.1. The bundled FFmpeg already carries NVENC support.
# The kernel driver is left to the user - it means a kernel module and usually
# a reboot - but the userspace library is a separate package on several
# distros (Ubuntu's headless and server driver flavours omit it), so it is
# installed here when the driver is present without it. Set AVD_SKIP_NVENC=1
# to skip this step.

# Usage: linux_distro_family  -> prints debian | fedora | arch, or nothing.
linux_distro_family() {
    if [ -f /etc/debian_version ]; then
        echo "debian"
    elif [ -f /etc/fedora-release ]; then
        echo "fedora"
    elif [ -f /etc/arch-release ]; then
        echo "arch"
    fi
}

# Usage: nvenc_library_package <family> <driver_version>
#   -> prints the package providing libnvidia-encode.so.1, or nothing if unknown.
# Debian and Ubuntu version the package by driver branch, so it must match the
# running driver exactly or apt would pull in a second driver stack.
nvenc_library_package() {
    case "$1" in
        debian) echo "libnvidia-encode-${2%%.*}" ;;
        fedora) echo "xorg-x11-drv-nvidia-cuda-libs" ;;
        arch) echo "nvidia-utils" ;;
    esac
}

# Usage: nvenc_library_present  -> succeeds when libnvidia-encode.so.1 is loadable.
# ldconfig's output is captured first: piping it into `grep -q` under pipefail
# can fail on SIGPIPE even when the library is listed.
nvenc_library_present() {
    local ldconfig_bin libs
    ldconfig_bin="$(command -v ldconfig || echo /sbin/ldconfig)"
    libs="$("$ldconfig_bin" -p 2>/dev/null || true)"
    case "$libs" in
        *"libnvidia-encode.so.1"*) return 0 ;;
    esac
    return 1
}

# Usage: install_nvenc_package <family> <package> <sudo-or-empty>
install_nvenc_package() {
    case "$1" in
        debian) $3 apt-get update -qq && $3 apt-get install -y --no-install-recommends "$2" ;;
        fedora) $3 dnf install -y "$2" ;;
        arch) $3 pacman -S --needed --noconfirm "$2" ;;
        *) return 1 ;;
    esac
}

# Usage: report_av1_nvenc <ffmpeg> [driver_version]
#   -> says whether AV1 output will use the GPU, and why not when it will not.
# Mirrors modules/core/utils.py:has_av1_nvenc_capability, which encodes one real
# frame: the encoder being listed proves nothing, since FFmpeg lists av1_nvenc
# on GPUs that cannot run it and on drivers too old for its NVENC API.
report_av1_nvenc() {
    local probe needed
    if probe="$("$1" -hide_banner -loglevel error -f lavfi -i color=c=black:s=256x256:r=1 \
        -frames:v 1 -c:v av1_nvenc -f null - 2>&1)"; then
        echo "[OK] AV1 NVENC available: AV1 output will be encoded on the GPU."
        return 0
    fi
    case "$probe" in
        *"required nvenc API version"*)
            # The FFmpeg build was compiled against a newer NVENC SDK than the
            # driver implements, which blocks every NVENC encoder, not just AV1.
            # FFmpeg names the minimum driver itself; report it verbatim.
            needed="${probe##*minimum required Nvidia driver for nvenc is }"
            [ "$needed" = "$probe" ] && needed="a newer release" || needed="${needed%% *} or newer"
            echo "[WARN] NVIDIA driver ${2:-(unknown)} is too old for this FFmpeg's NVENC; it needs $needed."
            echo "       Update the NVIDIA driver and reboot to enable GPU encoding." ;;
        *"No capable devices"*)
            echo "[INFO] This GPU has NVENC but no AV1 encoder (AV1 NVENC needs an RTX 40 or 50 series GPU)." ;;
        *)
            echo "[WARN] AV1 NVENC probe failed: ${probe%%$'\n'*}" ;;
    esac
    echo "       AV1 output will use the CPU encoder instead; ProRes output is unaffected."
}

# Usage: ensure_nvenc_runtime <ffmpeg>
# Never fails the install: every outcome here only decides GPU versus CPU AV1.
ensure_nvenc_runtime() {
    local driver family pkg sudo_cmd=""
    if ! command -v nvidia-smi >/dev/null 2>&1; then
        echo "[INFO] No NVIDIA driver found; NVENC unavailable. AV1 output will use the CPU encoder."
        return 0
    fi
    driver="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n1 || true)"
    if [ -z "$driver" ]; then
        echo "[WARN] nvidia-smi is present but reported no GPU; the NVIDIA driver may not be loaded."
        return 0
    fi
    if ! nvenc_library_present; then
        family="$(linux_distro_family)"
        pkg="$(nvenc_library_package "$family" "$driver")"
        if [ -z "$pkg" ]; then
            echo "[WARN] NVIDIA driver $driver has no libnvidia-encode.so.1 and this distro is not"
            echo "       recognised; install its NVENC library manually to enable GPU encoding."
        else
            echo "[INFO] NVIDIA driver $driver is missing its NVENC library; installing $pkg..."
            if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
                sudo_cmd="sudo"
            fi
            install_nvenc_package "$family" "$pkg" "$sudo_cmd" \
                || echo "[WARN] Could not install $pkg; NVENC stays unavailable."
        fi
    fi
    report_av1_nvenc "$1" "$driver"
}

if [ "${AVD_SKIP_NVENC:-0}" = "1" ]; then
    echo "[INFO] AVD_SKIP_NVENC=1 set; skipping the NVENC check."
elif [ "$OS_TYPE" = "Darwin" ]; then
    echo "[INFO] macOS has no NVIDIA driver support; AV1 output will use the CPU encoder."
else
    echo ""
    echo "[INFO] Checking NVIDIA NVENC hardware encoding..."
    if [ -x "$VENV_DIR/bin/ffmpeg" ]; then
        ensure_nvenc_runtime "$VENV_DIR/bin/ffmpeg"
    elif command -v ffmpeg >/dev/null 2>&1; then
        ensure_nvenc_runtime "$(command -v ffmpeg)"
    else
        echo "[WARN] No FFmpeg found to probe NVENC with; skipping the NVENC check."
    fi
fi

# ------------------------------------------------------------------------------
# 7. Check System Media Binaries (FFmpeg & VapourSynth)
# ------------------------------------------------------------------------------
echo ""
echo "=================================================="
echo "[INFO] Checking Media Tools Availability..."

# The app prepends .venv/bin to PATH at runtime (modules/core/utils.py:
# setup_environment), so report the venv copy first when present.
MISSING_TOOLS=()
for tool in ffmpeg ffprobe vspipe; do
    if [ -x "$VENV_DIR/bin/$tool" ]; then
        echo "   -> $tool: FOUND ($VENV_DIR/bin/$tool)"
    elif command -v "$tool" >/dev/null 2>&1; then
        echo "   -> $tool: FOUND ($(command -v "$tool"))"
    else
        echo "   -> $tool: NOT FOUND in PATH"
        MISSING_TOOLS+=("$tool")
    fi
done

if [ "${#MISSING_TOOLS[@]}" -gt 0 ]; then
    echo ""
    echo "[NOTICE] The following tools were not found in PATH: ${MISSING_TOOLS[*]}"
    echo "Please install them using your system package manager:"
    if [ "$OS_TYPE" = "Darwin" ]; then
        echo "  brew install ffmpeg vapoursynth"
    elif [ -f /etc/debian_version ]; then
        echo "  sudo apt-get update && sudo apt-get install -y ffmpeg vapoursynth vapoursynth-plugins"
    elif [ -f /etc/arch-release ]; then
        echo "  sudo pacman -S ffmpeg vapoursynth"
    elif [ -f /etc/fedora-release ]; then
        echo "  sudo dnf install -y ffmpeg vapoursynth vapoursynth-tools"
    fi
    exit 1
fi

# ------------------------------------------------------------------------------
# 8. Ensure Launcher (start.sh) is executable
# ------------------------------------------------------------------------------
echo ""
echo "[INFO] Ensuring launcher is executable: start.sh..."
if [ -f "$SCRIPT_DIR/start.sh" ]; then
    chmod +x "$SCRIPT_DIR/start.sh"
fi

echo ""
echo "=================================================="
echo "Installation Complete!"
echo "You can now run the application with:"
echo "  ./start.sh [path/to/video.mp4]"
echo "=================================================="
