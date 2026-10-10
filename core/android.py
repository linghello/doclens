# -*- coding: utf-8 -*-
"""Android 平台胶水。

只做三件事：
  1. 安全地拿到 android 模块（桌面端返回 None）；
  2. 调系统文件选择器（ACTION_OPEN_DOCUMENT / ACTION_GET_CONTENT）；
  3. 处理返回的 content:// URI —— 通过 monkeypatch 让 os.path.isfile / stat /
     os.stat 认识这类 URI，这样 store.import_path() 用 shutil.copyfile
     （内部是 open()，能读 content URI）就能直接复制，不必走 Java 流。

桌面端所有函数都退化成「用 Kivy 自带的 FileChooserPopup」。
"""

import os
import sys

from kivy.clock import Clock
from kivy.logger import Logger
from kivy.utils import platform

IS_ANDROID = platform == "android"

_android = None
_activity = None
_pending_uri = None
_request_code = 0x4C45  # "LE"

MIME_FILTER = [
    "text/plain", "text/markdown", "text/x-markdown",
    "application/octet-stream", "*/*",
]


class AndroidProxy(object):
    """持有 Java 侧对象，避免被 GC 回收。"""

    pass


proxy = AndroidProxy()


def get_android():
    global _android
    if not IS_ANDROID:
        return None
    if _android is None:
        try:
            import android  # type: ignore
            _android = android
        except Exception as exc:
            Logger.warning("DocLens: 无法导入 android 模块: %s", exc)
            _android = False
    return _android or None


def activity():
    global _activity
    if _activity is None:
        a = get_android()
        if a:
            try:
                _activity = a.mActivity
            except Exception:
                _activity = False
    return _activity or None


def toast(message, long=False):
    a = get_android()
    if not a:
        return False
    try:
        from jnius import autoclass  # type: ignore
        Toast = autoclass("android.widget.Toast")
        act = activity()
        if act is None:
            return False
        dur = Toast.LENGTH_LONG if long else Toast.LENGTH_SHORT
        act.runOnUiThread(Toast.makeText(act.getApplicationContext(),
                                         str(message), dur).show)
        return True
    except Exception as exc:
        Logger.warning("DocLens: Toast 失败 %s", exc)
        return False


def vibrate(ms=18):
    a = get_android()
    if not a:
        return False
    try:
        from jnius import autoclass  # type: ignore
        act = activity()
        if act is None:
            return False
        Context = autoclass("android.content.Context")
        vibrator = act.getSystemService(Context.VIBRATOR_SERVICE)
        if vibrator is None:
            return False
        Build = autoclass("android.os.Build")
        if Build.VERSION.SDK_INT >= 26:
            VibrationEffect = autoclass("android.os.VibrationEffect")
            vibrator.vibrate(VibrationEffect.createOneShot(int(ms), 60))
        else:
            vibrator.vibrate(int(ms))
        return True
    except Exception:
        return False


# ── content:// URI 支持 ─────────────────────────────
_PATCHED = False


def patch_content_uri():
    """让 os.stat / os.path.isfile 接受 content:// URI。

    Python 的 open() 在 Android 上由 CPython 自带实现，能处理 content://；
    但判断文件是否存在要靠我们的桩函数。
    """
    global _PATCHED
    if _PATCHED or not IS_ANDROID:
        return
    real_stat = os.stat
    real_isfile = os.path.isfile
    real_exists = os.path.exists

    def _is_content_uri(p):
        return isinstance(p, str) and p.startswith("content://")

    def _stat_content(uri):
        try:
            with open(uri, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
            return os.stat_result((0, 0, 0, 0, 0, 0, size, 0, 0, 0))
        except Exception:
            raise FileNotFoundError(uri)

    def stat_(path, *a, **kw):
        if _is_content_uri(path):
            return _stat_content(path)
        return real_stat(path, *a, **kw)

    def isfile_(path):
        if _is_content_uri(path):
            return True
        return real_isfile(path)

    def exists_(path):
        if _is_content_uri(path):
            return True
        return real_exists(path)

    os.stat = stat_
    os.path.isfile = isfile_
    os.path.exists = exists_
    _PATCHED = True
    Logger.info("DocLens: 已启用 content:// URI 支持")


def set_pending_uri(uri):
    global _pending_uri
    _pending_uri = uri


def take_pending_uri():
    global _pending_uri
    uri, _pending_uri = _pending_uri, None
    return uri


def _start_for_result(act, intent, request_code):
    """优先用自定义 Activity 的 startActivityForResult（能拿到结果）；
    拿不到就退化成普通 startActivity，由其它入口兜底。"""
    custom = getattr(act, "startActivityForResultSafe", None)
    if custom is not None:
        custom(intent, request_code)
        return
    act.startActivityForResult(intent, request_code)


# ── 文件选择器 ──────────────────────────────────────
def pick_files(callback, allow_multiple=True, images_only=False):
    """打开系统文件选择器；回调签名 callback([(display_name, path_or_uri), ...])。

    ``images_only=True`` 时只让选图片（用于插入图片 / 设置背景）。
    """
    proxy.callback = callback
    if not IS_ANDROID:
        Clock.schedule_once(lambda dt: _desktop_pick(callback, images_only), 0.05)
        return True

    try:
        from jnius import autoclass  # type: ignore

        patch_content_uri()
        act = activity()
        if act is None:
            Clock.schedule_once(lambda dt: callback([]), 0)
            return False

        Intent = autoclass("android.content.Intent")
        intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.setType("image/*" if images_only else "*/*")
        if allow_multiple:
            intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, True)

        _start_for_result(act, intent, _request_code)
        return True
    except Exception as exc:
        Logger.warning("DocLens: 打开选择器失败: %s", exc)
        Clock.schedule_once(lambda dt: callback([]), 0)
        return False


def handle_activity_result(request_code, result_code, intent):
    """由自定义 Activity 调用，把选中的 URI 交给业务层。"""
    if request_code != _request_code:
        return False
    cb = getattr(proxy, "callback", None)
    if cb is None:
        return False
    try:
        items = []
        if intent is None:
            Clock.schedule_once(lambda dt: cb([]), 0)
            return True
        clip = intent.getClipData()
        if clip is not None and clip.getItemCount() > 0:
            for k in range(clip.getItemCount()):
                uri = clip.getItemAt(k).getUri()
                items.append((_query_name(uri), str(uri)))
        else:
            data = intent.getData()
            if data is not None:
                items.append((_query_name(data), str(data)))
        Clock.schedule_once(lambda dt: cb(items), 0)
        return True
    except Exception as exc:
        Logger.warning("DocLens: 解析选择结果失败: %s", exc)
        Clock.schedule_once(lambda dt: cb([]), 0)
        return True


def _query_name(uri):
    try:
        from jnius import autoclass  # type: ignore
        act = activity()
        if act is None:
            return "文档.md"
        resolver = act.getContentResolver()
        cursor = resolver.query(uri, None, None, None, None)
        if cursor is not None and cursor.moveToFirst():
            idx = cursor.getColumnIndex("_display_name")
            if idx >= 0:
                name = cursor.getString(idx)
                cursor.close()
                return name or "文档.md"
            cursor.close()
    except Exception:
        pass
    name = str(uri).rstrip("/").split("/")[-1]
    return name or "文档.md"


# ── 桌面端退路 ──────────────────────────────────────
def _desktop_pick(callback, images_only=False):
    """桌面端用 Kivy 自带的选择器（支持多选）。"""
    try:
        from kivy.uix.filechooser import FileChooserListView
        from kivy.uix.popup import Popup
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.button import Button

        if images_only:
            filters = ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.bmp"]
        else:
            filters = ["*.md", "*.markdown", "*.txt", "*.log", "*.csv", "*.json", "*"]
        root = BoxLayout(orientation="vertical", spacing=4, padding=4)
        fc = FileChooserListView(path=os.path.expanduser("~"),
                                 filters=filters, multiselect=not images_only)
        root.add_widget(fc)
        bar = BoxLayout(size_hint_y=None, height=44, spacing=6)
        popup = Popup(title="选择要导入的文档（可多选）", content=root,
                      size_hint=(0.92, 0.9))

        def choose(*a):
            files = [f for f in fc.selection if os.path.isfile(f)]
            popup.dismiss()
            callback([(os.path.basename(f), f) for f in files])

        ok = Button(text="导入选中")
        ok.bind(on_release=choose)
        cancel = Button(text="取消")
        cancel.bind(on_release=lambda *a: (popup.dismiss(), callback([])))
        bar.add_widget(ok)
        bar.add_widget(cancel)
        root.add_widget(bar)
        popup.open()
        proxy.popup = popup
    except Exception as exc:
        Logger.warning("DocLens: 桌面选择器失败: %s", exc)
        callback([])


def share_content(text, title="分享文档"):
    """调用系统分享（桌面端复制到剪贴板）。"""
    if IS_ANDROID:
        try:
            from jnius import autoclass  # type: ignore
            act = activity()
            Intent = autoclass("android.content.Intent")
            intent = Intent(Intent.ACTION_SEND)
            intent.setType("text/plain")
            intent.putExtra(Intent.EXTRA_SUBJECT, title)
            intent.putExtra(Intent.EXTRA_TEXT, text)
            chooser = Intent.createChooser(intent, title)
            act.startActivity(chooser)
            return True
        except Exception as exc:
            Logger.warning("DocLens: 分享失败: %s", exc)
            return False
    try:
        from kivy.core.clipboard import Clipboard
        Clipboard.copy(text)
        return "clipboard"
    except Exception:
        return False
