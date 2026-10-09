# -*- coding: utf-8 -*-
"""DocLens · 手机文档查看器 —— 启动入口（桌面与 Android 共用）。

桌面直接跑：  python main.py
打包成 APK 由 buildozer 调用本文件。
"""

import os
import sys

# 让 core / screens 能被 import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 桌面端固定 1dp = 1px（本机 DPI 175%，不固定的话窗口会变成 700x1453）。
# 必须在 import kivy 之前设置。
if not os.environ.get("KIVY_METRICS_DENSITY"):
    os.environ["KIVY_METRICS_DENSITY"] = "1"

from kivy.config import Config  # noqa: E402

Config.set("kivy", "exit_on_escape", "0")
Config.set("graphics", "resizable", "1")
Config.set("input", "mouse", "mouse,multitouch_on_demand")

from kivy.app import App  # noqa: E402
from kivy.clock import Clock  # noqa: E402
from kivy.core.text import LabelBase  # noqa: E402
from kivy.core.window import Window  # noqa: E402
from kivy.logger import Logger  # noqa: E402
from kivy.utils import platform  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
FONT_DIR = os.path.join(ASSETS, "fonts")

# 注册图标 / 正文字体（子集化的思源黑体，中英 + 图标字符全覆盖）
for name in ("NotoSansSC-Regular.ttf", "NotoSansSC-Bold.ttf"):
    path = os.path.join(FONT_DIR, name)
    if os.path.isfile(path):
        LabelBase.register("AppFont", fn_regular=path)
        break
else:
    # 兜底：用系统字体，至少不会崩
    for cand in (r"C:\Windows\Fonts\Deng.ttf", "/system/fonts/NotoSansCJK-Regular.ttc",
                 "/system/fonts/DroidSansFallback.ttf"):
        if os.path.isfile(cand):
            LabelBase.register("AppFont", fn_regular=cand)
            break
    else:
        LabelBase.register("AppFont", fn_regular="Roboto")

mono = None
for cand in (os.path.join(FONT_DIR, "RobotoMono-Regular.ttf"),
             r"C:\Windows\Fonts\CascadiaMono.ttf",
             r"C:\Windows\Fonts\consola.ttf",
             "/system/fonts/DroidSansMono.ttf"):
    if os.path.isfile(cand):
        mono = cand
        break

# 行内代码 / 代码块用的字体。
# 坑：Cascadia / consola 这些等宽字体**没有中文字形**，而本 App 的代码块
# 里经常有中文（`# 中文注释也能正常显示`）。只注册等宽字体的话，这些中文
# 会全部变成豆腐块 □□□□，而且测量高度也会算错（字宽为 0）。
# 解决：AppMono / RobotoMono 都指向带完整 CJK 的字体，牺牲等宽换取不漏字。
_cjk_font = None
for cand in (os.path.join(FONT_DIR, "NotoSansSC-Regular.ttf"),
             r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
             r"C:\Windows\Fonts\msyh.ttc",
             r"C:\Windows\Fonts\Deng.ttf",
             "/system/fonts/NotoSansCJK-Regular.ttc"):
    if os.path.isfile(cand):
        _cjk_font = cand
        break

_code_font = _cjk_font or mono or "Roboto"
LabelBase.register("AppMono", fn_regular=_code_font)
LabelBase.register("RobotoMono", fn_regular=_code_font)


class DocLens(App):
    title = "DocLens"

    def build(self):
        from app import DocLensApp, Shell

        if platform not in ("android", "ios"):
            # 桌面预览：摆成手机比例。
            # Windows 开了显示缩放时（本机 175%），Kivy 请求的像素尺寸会被系统
            # 再乘一次缩放比，写 400 会得到 700。这里按缩放比反算回去。
            try:
                from kivy.metrics import Metrics
                win_scale = max(1.0, float(Metrics.dpi) / 96.0)
            except Exception:
                win_scale = 1.0
            Window.size = (int(round(400 / win_scale)), int(round(830 / win_scale)))
            Window.clearcolor = (0.95, 0.96, 0.98, 1)

        self.core = DocLensApp()
        shell = Shell(self.core)
        self.ui = shell

        Window.bind(on_keyboard=self._on_key)
        Window.bind(on_drop_file=self._on_drop)
        Clock.schedule_once(lambda dt: self._startup(), 0.35)
        return shell

    def on_start(self):
        # Android 从「分享到」或文件关联进来的路径
        if platform == "android":
            self._handle_android_intent()

    # ── 启动收尾 ────────────────────────────────────
    def _startup(self):
        if platform not in ("android", "ios"):
            self._load_desktop_samples()
        self.ui.library.refresh()
        self.ui.library.animate_in()
        Clock.schedule_once(lambda dt: self.core.maybe_first_hint(), 1.2)

    def _load_desktop_samples(self):
        """桌面首次运行时塞两篇示例文档，方便直接看到效果。"""
        store = self.core.store
        if store.list_docs():
            return
        samples = os.path.join(BASE, "samples")
        if not os.path.isdir(samples):
            return
        for fn in sorted(os.listdir(samples)):
            if os.path.splitext(fn)[1].lower() not in (".md", ".txt"):
                continue
            try:
                store.import_path(os.path.join(samples, fn))
            except Exception as exc:
                Logger.warning("DocLens: 导入示例失败 %s: %s", fn, exc)

    # ── 输入事件 ────────────────────────────────────
    def _on_key(self, _win, key, *_a):
        if key == 27:  # 返回键 / Esc
            if self.ui._sheet is not None:
                self.ui._sheet.dismiss()
                self.ui._sheet = None
                return True
            if self.ui.reader is not None:
                self.ui.close_reader()
                return True
            if platform != "android":
                self.stop()
                return True
        if key == 82 and self.ui.reader is None:  # 桌面端模拟安卓菜单键
            self.core.settings_sheet()
            return True
        return False

    def _on_drop(self, _win, path, *_a):
        """桌面端把文件拖进窗口即导入。"""
        try:
            name = self.core.store.import_path(path.decode("utf-8")
                                               if isinstance(path, bytes) else path)
            self.ui.library.refresh()
            self.core.toast("已导入 %s" % name)
        except Exception as exc:
            Logger.warning("DocLens: 拖入导入失败: %s", exc)
        return True

    # ── Android 分享 / 打开方式 ─────────────────────
    def _handle_android_intent(self):
        try:
            from jnius import autoclass  # type: ignore
            from core import android as droid

            act = droid.activity()
            if act is None:
                return
            intent = act.getIntent()
            if intent is None:
                return
            action = intent.getAction()
            if action not in ("android.intent.action.SEND",
                              "android.intent.action.VIEW"):
                return
            uri = intent.getData() if action.endswith("VIEW") else \
                intent.getParcelableExtra("android.intent.extra.STREAM")
            if uri is None:
                return
            name = droid._query_name(uri)
            self.core.store.import_path(str(uri))
            Clock.schedule_once(lambda dt: self.ui.library.refresh(), 0.5)
            Clock.schedule_once(lambda dt: self.core.toast("已导入 %s" % name), 0.6)
        except Exception as exc:
            Logger.warning("DocLens: 处理 Intent 失败: %s", exc)


if __name__ == "__main__":
    DocLens().run()
