#!/usr/bin/env bash
# ============================================================
#  DocLens · WSL 一键打包脚本
#
#  在 WSL(Ubuntu) 里跑这个脚本，就能把当前目录的 Kivy 项目
#  打成 Android APK。
#
#  用法：
#      chmod +x build_apk.sh
#      ./build_apk.sh              # 打 debug APK（最快，能直接装）
#      ./build_apk.sh release      # 打 release APK（体积小）
#      ./build_apk.sh clean        # 清掉构建缓存重来
#
#  产物：  bin/doclens-1.0.0-*-arm64-v8a_*.apk
# ============================================================

set -euo pipefail

MODE="${1:-debug}"
RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; CYA=$'\033[36m'; RST=$'\033[0m'

say()  { printf '%s==>%s %s\n' "$CYA" "$RST" "$*"; }
ok()   { printf '%s[ok]%s %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '%s[!]%s %s\n' "$YEL" "$RST" "$*"; }
die()  { printf '%s[x]%s %s\n' "$RED" "$RST" "$*" >&2; exit 1; }

# ── 0. 环境自检 ─────────────────────────────────────────
[ -f buildozer.spec ] || die "当前目录没有 buildozer.spec，请在 doclens 项目根目录运行"

if ! grep -qi microsoft /proc/version 2>/dev/null; then
    warn "看起来不是 WSL 环境。buildozer 只能在 Linux 下跑，继续可能失败。"
fi

if [ "$(id -u)" = "0" ]; then
    warn "不要用 root 直接跑（buildozer 会拒绝）。用普通用户运行，脚本内部会自行 sudo。"
fi

# ── 1. 装系统依赖 ───────────────────────────────────────
say "检查系统依赖…"
MISSING=""
for pkg in git zip unzip openjdk-17-jdk autoconf libtool pkg-config \
           zlib1g-dev libncurses-dev libncursesw5-dev libtinfo5 \
           cmake libffi-dev libssl-dev; do
    dpkg -s "$pkg" >/dev/null 2>&1 || MISSING="$MISSING $pkg"
done

if [ -n "$MISSING" ]; then
    say "需要安装缺失的包：$MISSING"
    sudo apt-get update -qq
    # shellcheck disable=SC2086
    sudo apt-get install -y -qq $MISSING
    ok "系统依赖装好了"
else
    ok "系统依赖齐了"
fi

# libtinfo5 在 Ubuntu 24.04 已移除，buildozer 有时候还会找它，软链兜一下
if ! ldconfig -p 2>/dev/null | grep -q libtinfo.so.5; then
    if [ -e /lib/x86_64-linux-gnu/libtinfo.so.6 ]; then
        warn "libtinfo.so.5 缺失，做一条软链兜底（buildozer 会找它）"
        sudo ln -sf /lib/x86_64-linux-gnu/libtinfo.so.6 \
                    /lib/x86_64-linux-gnu/libtinfo.so.5 2>/dev/null || true
    fi
fi

# ── 2. 装 python 工具 ───────────────────────────────────
export PIP_DISABLE_PIP_VERSION_CHECK=1

if ! command -v pip3 >/dev/null 2>&1; then
    say "安装 pip / venv…"
    sudo apt-get install -y -qq python3-pip python3-venv
fi

# 用独立 venv，不污染系统 python；已存在就复用
VENV="$HOME/.doclens-build-venv"
if [ ! -d "$VENV" ]; then
    say "创建构建用 venv（$VENV）…"
    python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

# 国内直连 pypi 很慢，默认走腾讯云镜像；想用官方源就设 USE_OFFICIAL_PYPI=1
if [ "${USE_OFFICIAL_PYPI:-0}" = "1" ]; then
    PIP_INDEX=""
    say "使用官方 PyPI 源"
else
    PIP_INDEX="-i https://mirrors.cloud.tencent.com/pypi/simple"
    say "使用腾讯云 PyPI 镜像（设 USE_OFFICIAL_PYPI=1 可切回官方源）"
fi

say "安装/更新 buildozer + cython…"
# shellcheck disable=SC2086
pip install -q --upgrade $PIP_INDEX pip setuptools wheel
# shellcheck disable=SC2086
pip install -q --upgrade $PIP_INDEX "buildozer>=1.5.0" "cython<3.0"

ok "buildozer $(buildozer --version 2>/dev/null | head -1)"

# ── 3. 清缓存（可选） ───────────────────────────────────
if [ "$MODE" = "clean" ]; then
    say "清理 .buildozer / bin…"
    rm -rf .buildozer bin
    ok "清完了，再跑一次 ./build_apk.sh 开始构建"
    exit 0
fi

# ── 4. 打包 ─────────────────────────────────────────────
# 首次构建要下 Android SDK/NDK（约 3–5 GB）并编译 python-for-android，
# 视网络情况 30–90 分钟。之后增量构建只要几分钟。
export GRADLE_OPTS="-Xmx2048m -Dfile.encoding=UTF-8"

if [ "$MODE" = "release" ]; then
    say "开始打 release APK（首次构建要 30–90 分钟，请耐心等）…"
    buildozer -v android release
    ARTIFACT=$(ls -t bin/*.apk 2>/dev/null | head -1 || true)
else
    say "开始打 debug APK（首次构建要 30–90 分钟，请耐心等）…"
    buildozer -v android debug
    ARTIFACT=$(ls -t bin/*.apk 2>/dev/null | head -1 || true)
fi

echo
if [ -n "${ARTIFACT:-}" ] && [ -f "$ARTIFACT" ]; then
    ok "打包完成：$ARTIFACT  ($(du -h "$ARTIFACT" | cut -f1))"
    echo
    say "安装到手机（USB 调试打开、adb 可用时）："
    echo "      adb install -r \"$ARTIFACT\""
    echo
    # 注意：WSL 里的 $USER 是 Linux 用户名，跟 Windows 用户名通常不是一回事，
    # 所以这里问 Windows 要 %USERPROFILE%，别再拿 $USER 拼路径。
    WINHOME=""
    if command -v cmd.exe >/dev/null 2>&1; then
        WINHOME=$(cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r' || true)
    fi
    if [ -n "$WINHOME" ]; then
        say "或者把 APK 拷到 Windows 桌面："
        echo "      cp \"$ARTIFACT\" \"$(wslpath "$WINHOME")/Desktop/\""
    else
        say "APK 就在项目 bin/ 目录里，Windows 下可以直接打开："
        echo "      <项目目录>\\bin\\$(basename "$ARTIFACT")"
    fi
else
    die "没找到产物，请往上翻日志找报错（常见：SDK license 没接受、NDK 下载超时）"
fi
