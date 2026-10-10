# -*- coding: utf-8 -*-
"""DocLens · 手机文档查看器 —— 启动入口（桌面与 Android 共用）。

桌面直接跑：  python main.py
打包成 APK 由 buildozer 调用本文件。
"""

import os
import sys

# 原生崩溃（SIGSEGV）Python 的 try/except 抓不到，faulthandler 能在信号发生时
# 把「当时执行到哪一行 Python」写进日志。⚠️ 坑：安卓上 p4a 会把 sys.stderr 换成
# 一个不支持 fileno() 的伪文件，直接 faulthandler.enable()（默认写 stderr）会抛
# io.UnsupportedOperation: fileno，在启动第一行就把 App 干崩——所以必须显式传一个
# 真实文件，并用 try 兜底，绝不能让它影响启动。
import faulthandler
try:
    _FAULT_LOG = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "faulthandler.log"), "w")
    faulthandler.enable(file=_FAULT_LOG)
except Exception:
    _FAULT_LOG = None

# 让 core / screens 能被 import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 密度（dp/sp 的换算基准）必须在 import kivy 之前定好，否则整个界面尺寸全错：
#   桌面：固定 1dp = 1px（本机 DPI 175%，不固定窗口会变成 700x1453）；
#   安卓：必须显式给出真实密度！Kivy 在 SDL2 引导下自动取密度时会去 autoclass
#         'org.renpy.android.Hardware'（那是老 pygame 引导才有的类），拿不到；
#         而若放任为 1，界面就只有应有的 1/密度 大 —— 440dpi 屏（2.75 倍）上
#         字小到看不清、按钮变成一个点。
_IS_ANDROID = bool(os.environ.get("ANDROID_ARGUMENT")
                   or os.environ.get("ANDROID_BOOTLOGO"))
if not os.environ.get("KIVY_METRICS_DENSITY"):
    if _IS_ANDROID:
        _dens = 2.0  # 兜底：常见中高密度屏
        try:
            from jnius import autoclass  # type: ignore
            _dm = autoclass("org.kivy.android.PythonActivity").mActivity \
                .getResources().getDisplayMetrics()
            _dens = float(_dm.density)
        except Exception:
            pass
        os.environ["KIVY_METRICS_DENSITY"] = "%.3f" % _dens
    else:
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

import sys
import traceback

# ── 启动崩溃捕获 ────────────────────────────────────
# 安卓上 p4a 把 Python stderr 重定向到 logcat（python 标签），但红米等机器的
# 环形缓冲只有几秒，真正的 traceback 会被冲掉；未捕获的异常还会一路冒泡到
# 原生层 Py_Exit -> Py_Finalize，触发 SIGSEGV（SDLThread），反而看不到根因。
# 这里把异常抓住：写文件 + 在屏幕上显示，既避免闪退，也让根因一目了然。
def _crash_path():
    try:
        a = App.get_running_app()
        if a and getattr(a, "user_data_dir", None):
            return os.path.join(a.user_data_dir, "doclens_crash.txt")
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "doclens_crash.txt")


def _write_crash(text):
    try:
        with open(_crash_path(), "w", encoding="utf-8") as fh:
            fh.write(text)
        Logger.warning("DocLens: 已把启动错误写入 %s", _crash_path())
    except Exception as exc:
        Logger.warning("DocLens: 写崩溃日志失败 %s", exc)


def _crash_excepthook(etype, exc, tb):
    _write_crash("".join(traceback.format_exception(etype, exc, tb)))


sys.excepthook = _crash_excepthook


def _build_error_widget(tb_text):
    """用红色错误屏把 traceback 直接画出来，方便截图回传。"""
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.label import Label
    from kivy.uix.scrollview import ScrollView

    root = BoxLayout(orientation="vertical")
    hdr = Label(
        text="DocLens 启动失败 —— 请把下方内容截图发给开发者",
        font_name="Roboto", color=(1, 0.42, 0.42, 1),
        size_hint_y=None, height=46, halign="left", valign="middle",
        text_size=(Window.width or 360, None),
    )
    sv = ScrollView()
    lab = Label(
        text=tb_text, font_name="Roboto",
        color=(0.95, 0.95, 0.97, 1),
        halign="left", valign="top", markup=False,
        text_size=(Window.width or 360, None),
    )
    sv.add_widget(lab)
    root.add_widget(hdr)
    root.add_widget(sv)
    return root


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
        try:
            return self._build_ui()
        except Exception:
            tb = traceback.format_exc()
            _write_crash(tb)
            Logger.error("DocLens: build() 抛出异常：\n%s", tb)
            return _build_error_widget(tb)

    def _build_ui(self):
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
            try:
                self._handle_android_intent()
            except Exception:
                tb = traceback.format_exc()
                _write_crash(tb)
                Logger.error("DocLens: on_start 处理 Intent 失败：\n%s", tb)

    # ── 启动收尾 ────────────────────────────────────
    def _startup(self):
        try:
            if platform not in ("android", "ios"):
                self._load_desktop_samples()
            self.ui.library.refresh()
            self.ui.library.animate_in()
            Clock.schedule_once(lambda dt: self.core.maybe_first_hint(), 1.2)
        except Exception:
            tb = traceback.format_exc()
            _write_crash(tb)
            Logger.error("DocLens: _startup 抛出异常：\n%s", tb)
            # 尽量把错误显示在界面上（build 已成功时 ui 存在）
            try:
                if getattr(self, "ui", None) is not None:
                    from kivy.uix.widget import Widget
                    err = _build_error_widget(tb)
                    self.ui.clear_widgets()
                    self.ui.add_widget(err)
            except Exception:
                pass

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
    try:
        DocLens().run()
    except Exception:
        # 覆盖 App.run() 初始化阶段（build 之前）抛出的 Python 异常
        tb = traceback.format_exc()
        _write_crash(tb)
        Logger.error("DocLens: App.run() 抛出异常：\n%s", tb)
        try:
            from kivy.app import App
            app = App.get_running_app()
            if app is not None and app.root is None:
                app.root = _build_error_widget(tb)
        except Exception:
            pass
    else:
        # 正常退出（用户关闭 / 系统销毁 Activity）。run() 返回后，p4a 还会走
        # sys.exit -> Py_Exit -> exit -> __cxa_finalize；在 MIUI/HyperOS 上这一步
        # 常因 pyjnius / android 等 JNI 桥的 atexit / 析构函数指针损坏而 SIGSEGV
        # （抓到的 tombstone 正是这个栈）。这里在 Python 层直接硬退出，跳过那段
        # C 层收尾，避免退出时闪崩。数据在每个操作后用 flush() 落盘，硬退出安全。
        if platform == "android":
            os._exit(0)
