[app]

# ── 基本信息 ─────────────────────────────────────────────
title = DocLens
package.name = doclens
package.domain = io.doclens

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,ttf,otf,md,txt,json
source.include_patterns = assets/*,samples/*
# 不打包源码整理工具 / 桌面测试 / 截图 / CI 配置
# 注意：不要写 *.md —— samples/ 里的示例文档就是 .md，那是 App 要用到的。
source.exclude_dirs = tools,shots,bin,.buildozer,__pycache__,.github,.git,.idea,.vscode
source.exclude_patterns = _smoke.py,*.pyc,*.out,*.bat,*.sh,README*,buildozer.spec

version = 1.0.0

# ── 依赖 ────────────────────────────────────────────────
# ⚠️ Kivy 2.3.x 的 kivy/core/image/__init__.py 在模块加载时就 import filetype，
# 而 p4a v2024.01.21 的 kivy recipe 没有把它带进来 → 缺了会直接
# ModuleNotFoundError 闪退。必须显式加上。
requirements = python3,kivy==2.3.1,pyjnius,android,filetype

orientation = portrait
fullscreen = 0

# ── 图标 / 启动图（可选，有就填） ───────────────────────
# icon.filename = %(source.dir)s/assets/icon.png
# presplash.filename = %(source.dir)s/assets/presplash.png

# ── 权限：一个都不要 ────────────────────────────────────
# DocLens 是纯离线阅读器：文件全部躺在 App 自己的沙盒里，
# 不联网、不读相册、不要存储权限。
android.permissions =

# 目标 API（Play 商店现在要求 34+；34 对 Android 13/14 都友好）
android.api = 34
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24
android.accept_sdk_license = True

# 只出 arm64，安装包能小一半（2019 年后的手机基本都是 arm64）
android.archs = arm64-v8a

android.allow_backup = False

# 让 logcat 能直接看到 print 输出（调试用）
android.logcat_filters = *:S python:D

# 应用中文名（AndroidManifest 里的 label）
android.presplash_color = #4F46E5

# ── 打包选项 ────────────────────────────────────────────
# release 版才有 R8 混淆/压缩，APK 更小
android.release_artifact = apk
android.debug_artifact = apk

# ── python-for-android ──────────────────────────────────
# ⚠️ 必须钉住分支，不要删这行！
#
# buildozer 默认拉 p4a 的 **master**，而 master 目前把 python3 recipe 推到了
# Python 3.14.2 —— 但 Kivy 2.3.1 的 recipe 又把 Cython 限死在 <=3.0.12，
# 而那个 Cython 不支持 Python 3.14。结果会在编译 Kivy 时炸掉。
#
# 各版本对照：
#   master         -> Python 3.14.2  ← 不能用
#   v2024.01.21    -> Python 3.11.5  ← 用这个
#   v2023.09.16    -> Python 3.10.10
p4a.branch = v2024.01.21

p4a.bootstrap = sdl2
p4a.local_recipes =

[buildozer]
log_level = 2
warn_on_root = 1
