# -*- coding: utf-8 -*-
"""桌面端自动冒烟测试：导入示例 → 打开阅读器 → 换主题 → 设置面板，全程截图。

用法：  python _smoke.py
产出：  shots/*.png
"""

import os
import sys
import ctypes
import traceback

# 必须在 import kivy 之前设置！kivy.metrics 在导入时就固定 density，
# 之后再设环境变量已经晚了（本机 DPI 175%，会让所有 dp() 乘 1.75，
# 卡片高度从 94 变成 164.5，截图和实际布局全对不上）。
os.environ.setdefault("KIVY_METRICS_DENSITY", "1")
os.environ["KIVY_LOG_ENABLE"] = "0"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")
os.makedirs(SHOTS, exist_ok=True)

from kivy.config import Config  # noqa: E402

# 桌面预览尺寸（像素），和 main.py 的 Window.size 一致
Config.set("graphics", "width", "400")
Config.set("graphics", "height", "830")
# 关掉 HiDPI 缩放，保证「配置多少像素就是多少像素」，否则 glReadPixels 与
# 布局尺寸对不上，截图会被裁掉右边一半。
Config.set("graphics", "dpi", "96")

from kivy.clock import Clock  # noqa: E402
from kivy.core.window import Window  # noqa: E402

import main as M  # noqa: E402

errors = []


class Smoke(M.DocLens):
    def build(self):
        root = super().build()
        # 冒烟测试要可复现：清掉上次持久化的主题/进度，回到浅色 + 无进度。
        self.core.store.set("theme", "light")
        self.core.store.state["progress"] = {}
        self.core.store.flush()
        self.core.theme.set("light")
        Clock.schedule_once(self._reset_bg, 0.3)
        Clock.schedule_once(self._probe, 1.5)
        return root

    def _reset_bg(self, dt):
        """Shell 是按旧主题建的，这里把它整个换成浅色版本。"""
        try:
            self.core.rebuild_ui()
        except Exception:
            traceback.print_exc()

    def shot(self, name):
        """Kivy 的 screenshot 在 Windows 上会把路径拼坏，自己用 OpenGL 读像素写 PNG。

        注意：
        1. Windows 开 HiDPI 时真实帧缓冲比 Config 写的大，必须查 GL 视口，
           用 Window.size 会把图裁掉。
        2. glReadPixels 读的是「上一帧」，改完布局同一 tick 里截会拿到旧画面
           （表现为一张空白图）。所以截之前强制刷几遍。
        """
        from PIL import Image
        from kivy.graphics.opengl import (
            glReadPixels, glGetIntegerv, GL_RGB, GL_UNSIGNED_BYTE, GL_VIEWPORT,
        )
        # 连刷几帧：只刷一次仍可能读到布局未完成的旧帧
        try:
            from kivy.base import EventLoop
            for _ in range(3):
                Window.canvas.ask_update()
                EventLoop.idle()
        except Exception:
            pass
        vp = glGetIntegerv(GL_VIEWPORT)
        w, h = int(vp[2]), int(vp[3])
        data = glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE)
        img = Image.frombytes("RGB", (w, h), data)
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
        img.save(os.path.join(SHOTS, name + ".png"))
        print("SHOT %s %dx%d" % (name, w, h), flush=True)
        # 顺便把关键控件状态打出来，便于确认「截到的」和「布局算出的」一致
        self._dump(name)

    def _dump(self, name):
        try:
            rv = self.ui.reader
            if rv is None or getattr(rv, "box", None) is None:
                return
            from kivy.metrics import Metrics, sp
            print("DUMP %s density=%.2f sp(13.5)=%.1f" % (
                name, Metrics.density, sp(13.5)), flush=True)
            # 打印前 14 个块的高度，找出行高异常的
            kids = list(reversed(rv.box.children))
            for i, w in enumerate(kids[:14]):
                txt = ""
                for g in getattr(w, "children", []) or []:
                    if hasattr(g, "text"):
                        txt = g.text[:20]
                        break
                print("   blk%-2d %-12s h=%6.1f  %r" % (
                    i, w.__class__.__name__, w.height, txt), flush=True)
        except Exception:
            import traceback
            traceback.print_exc()

    def _probe(self, dt):
        try:
            docs = self.core.store.list_docs()
            print("SMOKE docs=%d" % len(docs), flush=True)
            self.core.open_doc(docs[0])
            Clock.schedule_once(self._after_open, 0.8)
        except Exception:
            traceback.print_exc()
            errors.append("probe")
            self.stop()

    def _after_open(self, dt):
        try:
            rv = self.ui.reader
            # 先让布局稳定：强制按当前宽度重建一次，再回到顶部
            rv.rebuild(force=True)
            rv.scroll.scroll_y = 1.0
            Clock.schedule_once(self._shot_top, 0.6)
        except Exception:
            traceback.print_exc()
            errors.append("open")
            self.stop()

    def _shot_top(self, dt):
        try:
            rv = self.ui.reader
            print("SMOKE blocks=%d content=%.0f viewport=%.0f"
                  % (len(rv.blocks), rv.box.height, rv.scroll.height), flush=True)
            self.shot("reader_light_top")
            rv.scroll.scroll_y = 0.45
            Clock.schedule_once(self._shot2, 0.5)
        except Exception:
            traceback.print_exc()
            errors.append("shot_top")
            self.stop()

    def _shot2(self, dt):
        try:
            self.shot("reader_light_mid")
            print("SMOKE progress=%.2f" % self.ui.reader.progress, flush=True)
            self.ui.close_reader()
            Clock.schedule_once(self._lib, 0.7)
        except Exception:
            traceback.print_exc()
            errors.append("shot2")
            self.stop()

    def _lib(self, dt):
        try:
            # 标题/摘要的省略是按「最终宽度」算的，布局稳定前先别截。
            # 多等一会儿，并强制重建一次列表，保证截到的是最终状态。
            self.ui.library.refresh(smooth=False)
            Clock.schedule_once(self._lib2, 0.6)
        except Exception:
            traceback.print_exc()
            errors.append("lib")
            self.stop()

    def _lib2(self, dt):
        try:
            self.shot("library_light")
            self.core.set_theme("dark")
            Clock.schedule_once(self._dark, 0.9)
        except Exception:
            traceback.print_exc()
            errors.append("lib2")
            self.stop()

    def _dark(self, dt):
        try:
            self.shot("library_dark")
            self.core.settings_sheet()
            Clock.schedule_once(self._settings, 0.7)
        except Exception:
            traceback.print_exc()
            errors.append("dark")
            self.stop()

    def _settings(self, dt):
        try:
            self.shot("settings_dark")
            self.ui._sheet.dismiss()
            self.ui._sheet = None
            docs = self.core.store.list_docs()
            self.core.open_doc(docs[-1])
            Clock.schedule_once(self._shot3, 0.9)
        except Exception:
            traceback.print_exc()
            errors.append("settings")
            self.stop()

    def _shot3(self, dt):
        try:
            self.shot("reader_dark")
            self.core.font_scale = 1.35
            self.ui.reader.rebuild(force=True)
            Clock.schedule_once(self._shot4, 0.5)
        except Exception:
            traceback.print_exc()
            errors.append("shot3")
            self.stop()

    def _shot4(self, dt):
        try:
            self.shot("reader_dark_bigfont")
            print("SMOKE errors=%s ALL_OK" % errors, flush=True)
        except Exception:
            traceback.print_exc()
        self.stop()


Smoke().run()