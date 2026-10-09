# -*- coding: utf-8 -*-
"""DocLens 应用外壳：页面路由 + 阅读器浮层 + 弹层 / 设置 / 长按菜单。"""

import os

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.metrics import dp, sp
from kivy.graphics import Color, Rectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from core import android as droid
from core import mdrender
from core.store import Store, TEXT_EXT
from core.theme import READER_FONT_MAX, READER_FONT_MIN, Theme
from core.widgets import (
    AppBar, BottomSheet, Card, Divider, FONT, IconButton,
    ModernButton, ProgressLine, Surface, Toast,
)
from screens.library import LibraryView
from screens.reader import ReaderView

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# 图标用文字符号画：字体支持，跨平台一致，不用带 png
ICON_BACK = "←"
ICON_SEARCH = "⌕"
ICON_SUN = "☀"
ICON_MOON = "☾"
ICON_MINUS = "−"
ICON_PLUS = "＋"
ICON_STAR = "★"
ICON_STAR_O = "☆"
ICON_MORE = "⋮"
ICON_SHARE = "↗"
ICON_TRASH = "✕"
ICON_EDIT = "✎"
ICON_READ = "▤"
ICON_GEAR = "⚙"
ICON_TYPE = "A"


class Shell(FloatLayout):
    """根容器：负责换页、弹层、Toast。"""

    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        # 整页底色：不铺的话深色主题下会露出浅色窗口底
        with self.canvas.before:
            self._page_c = Color(rgba=app.theme.c("bg"))
            self._page_r = Rectangle()
        self.bind(pos=self._sync_page_bg, size=self._sync_page_bg)
        self._sync_page_bg()
        self.reader = None
        self.library = LibraryView(app)
        self.add_widget(self.library)
        self._sheet = None
        self._toast = None
        self._build_settings_button()

    def _sync_page_bg(self, *a):
        self._page_r.pos = self.pos
        self._page_r.size = self.size

    def restyle(self):
        """换肤后刷新整页底色。"""
        self._page_c.rgba = self.app.theme.c("bg")

    def _build_settings_button(self):
        """左下角的设置入口（齿轮）。"""
        c = self.app.theme
        holder = BoxLayout(size_hint=(None, None), size=(dp(52), dp(52)),
                          pos_hint={"x": 0, "y": 0}, padding=[dp(10), 0, 0, dp(10)])
        btn = IconButton(icon=ICON_GEAR, size=(dp(42), dp(42)), font_size=sp(17),
                         icon_color=c.c("text2"), base_color=c.c("surface"),
                         radius_ratio=1.0)
        btn.bind(on_release=lambda *a: self.app.settings_sheet())
        holder.add_widget(btn)
        self.add_widget(holder)
        self._settings_btn = holder
        Clock.schedule_interval(self._sync_settings_btn, 0.2)

    def _sync_settings_btn(self, *_a):
        if self._settings_btn is None:
            return False
        self._settings_btn.opacity = 0 if self.reader is not None else 1
        return self._settings_btn.parent is not None

    # ── 换页 ────────────────────────────────────────
    def open_reader(self, rel, title):
        if self.reader is not None:
            return
        rv = ReaderView(self.app, size_hint=(1, 1))
        self.reader = rv
        self.add_widget(rv)
        rv.load(rel, title)
        # 从右侧滑入
        rv.x = self.width
        Animation(x=0, d=0.24, t="out_cubic").start(rv)
        self._build_reader_overlay(rv)

    def close_reader(self, *_a):
        if self.reader is None:
            return
        rv = self.reader
        self.reader = None
        if rv.doc_rel:
            # 只保存「真的滚动过」的进度，别把 0 覆盖掉已有记录
            # （内容不足一屏时 progress 恒为 0，会把读了一半的记录清空）。
            if rv.progress > 0.01:
                self.app.store.set_progress(rv.doc_rel, rv.progress)
                self.app.store.flush()
        anim = Animation(x=self.width, d=0.2, t="in_cubic")
        anim.bind(on_complete=lambda *x: self.remove_widget(rv))
        anim.start(rv)
        Clock.schedule_once(lambda dt: self.library.refresh(smooth=False), 0.05)
        Clock.schedule_once(lambda dt: self.app.maybe_first_hint(), 0.4)

    # ── 阅读器浮层（顶栏 / 进度条 / 字号坞） ────────
    def _build_reader_overlay(self, rv):
        """阅读器本体是 ScrollView，只能有一个子控件，
        所以顶栏等一切浮层挂在它外面的 FloatLayout 上。"""
        overlay = FloatLayout(size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
        rv.add_widget(overlay)
        rv.overlay = overlay

        bar = rv._reader_bar = AppBar(appbar_bg=self.app.theme.c("surface"),
                                      elevation=0)
        bar.size_hint = (1, None)
        bar.pos_hint = {"top": 1}
        bar.title = rv.doc_title
        back = IconButton(icon=ICON_BACK, size=(dp(40), dp(40)), font_size=sp(20),
                          icon_color=self.app.theme.c("text"))
        back.bind(on_release=self.close_reader)
        bar.add_left(back)

        fav = IconButton(icon=ICON_STAR if rv.is_fav else ICON_STAR_O,
                         size=(dp(38), dp(38)), font_size=sp(17),
                         icon_color=self.app.theme.c("warn") if rv.is_fav
                         else self.app.theme.c("text2"))

        def toggle_fav(*a):
            now = self.app.store.toggle_fav(rv.doc_rel)
            rv.is_fav = now
            fav.icon = ICON_STAR if now else ICON_STAR_O
            fav.icon_color = self.app.theme.c("warn") if now else self.app.theme.c("text2")
            self.app.toast("已加入收藏" if now else "已取消收藏")
        fav.bind(on_release=toggle_fav)

        more = IconButton(icon=ICON_MORE, size=(dp(38), dp(38)), font_size=sp(18),
                          icon_color=self.app.theme.c("text2"))
        more.bind(on_release=lambda *a: self.app.reader_menu(rv))
        bar.add_right(fav)
        bar.add_right(more)
        overlay.add_widget(bar)

        prog = ProgressLine(value=rv.progress, color=self.app.theme.c("primary"),
                            track_color=self.app.theme.c("divider"))
        prog.size_hint = (1, None)
        prog.pos_hint = {"top": 1, "x": 0}
        prog.height = dp(2.5)
        overlay.add_widget(prog)
        rv._prog_line = prog
        rv._bar = bar
        rv.bind(progress=lambda i, v: setattr(prog, "value", v))

        overlay.add_widget(self._reader_dock(rv))

    def _reader_dock(self, rv):
        c = self.app.theme
        holder = FloatLayout(size_hint=(1, 1))
        card = Card(orientation="vertical", surface_bg=c.c("surface"),
                    radius=[dp(21)] * 4, elevation=2, padding=[dp(4)] * 4,
                    spacing=dp(4), size_hint=(None, None),
                    size=(dp(42), dp(42) * 3 + dp(8)),
                    pos_hint={"right": 0.97, "center_y": 0.42})

        def mk(icon, cb, size=13):
            b = IconButton(icon=icon, size=(dp(34), dp(34)), font_size=sp(size),
                           icon_color=c.c("text2"),
                           base_color=c.c("surface3", 0.001))
            b.bind(on_release=cb)
            return b

        up = mk(ICON_PLUS, lambda *a: self._font(rv, +0.08), 16)
        tp = Label(text=ICON_TYPE, font_name=FONT, font_size=sp(13),
                   color=c.c("muted"), size_hint=(None, None), size=(dp(34), dp(16)))
        down = mk(ICON_MINUS, lambda *a: self._font(rv, -0.08), 16)
        card.add_widget(up)
        card.add_widget(tp)
        card.add_widget(down)
        holder.add_widget(card)
        return holder

    def _font(self, rv, delta):
        scale = max(0.8, min(1.8, round(self.app.font_scale + delta, 3)))
        self.app.set_font_scale(scale)
        rv.font_scale = 1.0
        rv.rebuild(force=True)
        self.app.toast("字号 %.0f%%" % (scale * 100), short=True)

    # ── 弹层 / Toast ────────────────────────────────
    def show_sheet(self, title, widget, height):
        if self._sheet is not None:
            self._sheet.dismiss()
        sheet = BottomSheet(title=title)
        sheet.size_hint = (1, 1)
        sheet.set_body(widget, height)
        sheet.open(self)
        self._sheet = sheet
        return sheet

    def toast(self, message, short=False):
        if self._toast is None:
            self._toast = Toast()
        self._toast.ripple_rgba = [0, 0, 0, 0]
        self._toast.bg = self.app.theme.c("text", 0.92)
        self._toast.show(self, message, duration=1.4 if short else 2.0)


class DocLensApp(object):
    """不用 Kivy 的 App 子类包一层，方便同时被 desktop / android 入口复用。"""

    def __init__(self):
        from kivy.app import App

        self._app = App.get_running_app()
        self.store = Store()
        mode = self.store.get("theme", "system")
        if mode == "system":
            mode = "light"
        self.theme = Theme(mode)
        self.font_scale = float(self.store.get("font_scale", 1.0) or 1.0)
        self.pending_open = None
        self._first_hint_done = bool(self.store.get("first_run_seen"))

    # ── 换肤 ────────────────────────────────────────
    def colors_for_md(self):
        p = self.theme.p
        return {
            "text": p["text"], "text2": p["text2"], "muted": p["muted"],
            "primary": p["primary"], "divider": p["divider"],
            "code_bg": p["code_bg"], "code_fg": p["code_fg"],
            "quote_bar": p["quote_bar"], "highlight": p["highlight"],
        }

    def set_theme(self, mode):
        if mode == "system":
            mode = "light"
        self.theme.set(mode)
        self.store.set("theme", mode)
        self.store.flush()
        self.rebuild_ui()

    def set_font_scale(self, value):
        self.font_scale = value
        self.store.set("font_scale", value)
        self.store.flush()

    def rebuild_ui(self):
        ui = getattr(self._app, "ui", None)
        if ui is None:
            return
        parent = ui.parent
        rel = ui.reader.doc_rel if ui.reader else None
        title = ui.reader.doc_title if ui.reader else ""
        progress = ui.reader.progress if ui.reader else 0.0
        if ui.reader:
            ui.remove_widget(ui.reader)
            ui.reader = None
        if ui.library.parent is not None:
            ui.remove_widget(ui.library)
        new_shell = Shell(self)
        new_shell.size = ui.size
        new_shell.pos = ui.pos
        parent.remove_widget(ui)
        parent.add_widget(new_shell)
        self._app.ui = new_shell
        if rel:
            new_shell.open_reader(rel, title)
            Clock.schedule_once(
                lambda dt: setattr(new_shell.reader, "scroll_y",
                                   max(0.0, min(1.0, 1.0 - progress))), 0.12)
        else:
            new_shell.library.refresh(smooth=False)

    # ── 文档操作 ────────────────────────────────────
    def open_doc(self, doc):
        if isinstance(doc, dict):
            rel, title = doc["rel"], doc["title"]
        else:
            rel, title = doc, doc
        ui = getattr(self._app, "ui", None)
        if ui is None:
            self.pending_open = (rel, title)
            return
        ui.open_reader(rel, title)
        self._maybe_index(rel)

    def _maybe_index(self, rel):
        """第一次打开时生成摘要 / 字数缓存（廉价，直接同步做）。"""
        if self.store.cached_preview(rel):
            return
        text = self.store.read(rel) or ""
        st = mdrender.stats(text)
        first = ""
        for line in text.split("\n"):
            s = mdrender.unescape(
                mdrender._TAG.sub("", line)).strip().lstrip("#").strip()
            if len(s) > 8:
                first = s
                break
        self.store.update_meta(rel, first[:70], st["chars"], st["minutes"],
                               title=self._title_of(text, rel))
        self.store.flush_cache()

    def _title_of(self, text, rel):
        for line in text.split("\n")[:6]:
            s = line.strip()
            if s.startswith("#"):
                return s.lstrip("#").strip()[:42]
            if len(s) > 4 and not s.startswith("|"):
                return s[:42]
        return os.path.splitext(os.path.basename(rel))[0]

    def import_dialog(self):
        ui = getattr(self._app, "ui", None)
        if ui is None:
            return
        droid.pick_files(self._on_picked)

    def _on_picked(self, items):
        ui = getattr(self._app, "ui", None)
        if not items:
            return
        ok, bad = 0, 0
        for name, path in items:
            try:
                if os.path.splitext(name)[1].lower() not in TEXT_EXT:
                    # 允许无扩展名的纯文本
                    if os.path.splitext(name)[1]:
                        bad += 1
                        continue
                self.store.import_path(path)
                ok += 1
            except Exception as exc:
                from kivy.logger import Logger
                Logger.warning("DocLens: 导入失败 %s (%s)", name, exc)
                bad += 1
        if ui:
            ui.library.refresh()
        if ok and not bad:
            self.toast("已导入 %d 份文档" % ok)
        elif ok and bad:
            self.toast("导入 %d 份成功，%d 份不支持" % (ok, bad))
        elif bad:
            self.toast("这些文件不支持，试试 .md / .txt")
        self.maybe_first_hint()

    def new_document(self):
        ui = getattr(self._app, "ui", None)
        if ui is None:
            return
        name = self.store.import_text("未命名.md",
                                      "# 未命名\n\n在这里写下第一行文字。\n")
        ui.library.refresh()
        self.open_doc({"rel": name, "title": "未命名"})
        self.toast("已新建文档")

    def doc_menu(self, doc, anchor):
        c = self.theme
        body = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(2))
        fav = self.store.is_fav(doc["rel"])
        rows = [
            (ICON_STAR if not fav else ICON_STAR_O,
             "取消收藏" if fav else "加入收藏", lambda: self._fav(doc)),
            (ICON_EDIT, "重命名", lambda: self._rename(doc)),
            (ICON_SHARE, "分享正文", lambda: self._share(doc)),
            (ICON_TRASH, "删除文档", lambda: self._delete(doc), True),
        ]
        for row in rows:
            danger = len(row) > 3 and row[3]
            body.add_widget(self._menu_row(row[0], row[1], row[2], danger))
        body.height = dp(52) * len(rows) + dp(4)
        ui = getattr(self._app, "ui", None)
        ui.show_sheet(doc["title"][:24], body, body.height)

    def _menu_row(self, icon, text, cb, danger=False):
        c = self.theme

        from kivy.uix.boxlayout import BoxLayout

        class Row(Surface, BoxLayout):
            pass

        row = Row(surface_bg=c.c("surface3", 0.0), radius=[dp(13)] * 4, elevation=0,
                  size_hint_y=None, height=dp(52),
                  padding=[dp(14), 0, dp(8), 0], spacing=dp(12),
                  orientation="horizontal",
                  ripple_rgba=c.c("primary", 0.12))
        ic = Label(text=icon, font_name=FONT, font_size=sp(17),
                   color=c.c("accent") if danger else c.c("text2"),
                   size_hint=(None, 1), width=dp(24), markup=False)
        lbl = Label(text=text, font_name=FONT, font_size=sp(15),
                    color=c.c("accent") if danger else c.c("text"),
                    halign="left", valign="middle", markup=False)
        lbl.bind(size=lambda i, v: setattr(i, "text_size", (i.width, None)))
        row.add_widget(ic)
        row.add_widget(lbl)
        row.bind(on_release=lambda *a: (self._close_sheet(), cb()))
        return row

    def _close_sheet(self):
        ui = getattr(self._app, "ui", None)
        if ui and ui._sheet:
            ui._sheet.dismiss()
            ui._sheet = None

    def _fav(self, doc):
        now = self.store.toggle_fav(doc["rel"])
        self.toast("已加入收藏" if now else "已取消收藏")
        self._refresh_lib()

    def _rename(self, doc):
        from kivy.uix.textinput import TextInput
        c = self.theme
        stem = os.path.splitext(doc["name"])[0]
        holder = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(12))
        field = TextInput(text=stem, multiline=False, font_name=FONT, font_size=sp(15),
                          background_normal="", background_active="",
                          background_color=c.c("surface3"), foreground_color=c.c("text"),
                          cursor_color=c.c("primary"), padding=[dp(12), dp(12)],
                          size_hint_y=None, height=dp(48))
        holder.add_widget(field)
        btn = ModernButton(text="保存", surface_bg=c.c("primary"), text_color=c.c("on_primary"),
                           size_hint_y=None, height=dp(46))
        holder.add_widget(btn)
        holder.height = dp(106)
        ui = getattr(self._app, "ui", None)
        sheet = ui.show_sheet("重命名", holder, holder.height)

        def do(*a):
            new_rel = self.store.rename(doc["rel"], field.text.strip() or stem)
            sheet.dismiss()
            ui._sheet = None
            self._refresh_lib()
            self.toast("已重命名")
        btn.bind(on_release=do)
        Clock.schedule_once(lambda dt: setattr(field, "focus", True), 0.3)

    def _share(self, doc):
        text = self.store.read(doc["rel"]) or ""
        res = droid.share_content(text[:20000], doc["title"])
        if res == "clipboard":
            self.toast("桌面端已复制正文到剪贴板")
        elif not res:
            self.toast("分享失败")

    def _delete(self, doc):
        c = self.theme
        holder = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(12))
        msg = Label(text="删除后无法恢复，文件会从 App 内部存储中移除。",
                    font_name=FONT, font_size=sp(13.5), color=c.c("text2"),
                    size_hint_y=None, height=dp(44), halign="left", markup=False)
        msg.bind(size=lambda i, v: setattr(i, "text_size", (i.width, None)))
        holder.add_widget(msg)
        btn = ModernButton(text="确认删除", surface_bg=c.c("accent"),
                           text_color=[1, 1, 1, 1], size_hint_y=None, height=dp(46))
        holder.add_widget(btn)
        holder.height = dp(102)
        ui = getattr(self._app, "ui", None)
        sheet = ui.show_sheet("删除「%s」" % doc["title"][:16], holder, holder.height)

        def do(*a):
            self.store.delete(doc["rel"])
            sheet.dismiss()
            ui._sheet = None
            self._refresh_lib()
            self.toast("已删除")
        btn.bind(on_release=do)

    def _refresh_lib(self):
        ui = getattr(self._app, "ui", None)
        if ui:
            ui.library.refresh()

    # ── 阅读器菜单 ──────────────────────────────────
    def reader_menu(self, rv):
        c = self.theme
        body = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(2))
        rows = [
            (ICON_SHARE, "分享正文", lambda: self._share({"rel": rv.doc_rel,
                                                        "title": rv.doc_title})),
            (ICON_STAR if not rv.is_fav else ICON_STAR_O,
             "取消收藏" if rv.is_fav else "加入收藏",
             lambda: self._reader_fav(rv)),
            (ICON_READ, "重新从头阅读", lambda: self._reader_top(rv)),
        ]
        for icon, text, cb in rows:
            body.add_widget(self._menu_row(icon, text, cb))
        body.height = dp(52) * len(rows) + dp(4)
        ui = getattr(self._app, "ui", None)
        ui.show_sheet(rv.doc_title[:24], body, body.height)

    def _reader_fav(self, rv):
        now = self.store.toggle_fav(rv.doc_rel)
        rv.is_fav = now
        bar = getattr(rv, "_bar", None)
        if bar and bar.right.children:
            fav = bar.right.children[-1]
            fav.icon = ICON_STAR if now else ICON_STAR_O
            fav.icon_color = self.theme.c("warn") if now else self.theme.c("text2")
        self.toast("已加入收藏" if now else "已取消收藏")

    def _reader_top(self, rv):
        rv.scroll_y = 1.0

    # ── 设置 ────────────────────────────────────────
    def settings_sheet(self):
        c = self.theme
        body = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(14))
        # 主题
        body.add_widget(self._kv_label("外观", bold=True))
        seg = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        cur = self.store.get("theme", "system")
        for mode, text in (("light", "浅色"), ("dark", "深色"), ("system", "跟随系统")):
            on = (cur == mode)
            b = ModernButton(text=text,
                             surface_bg=c.c("primary") if on else c.c("surface3"),
                             text_color=c.c("on_primary") if on else c.c("text2"),
                             radius=[dp(13)] * 4)
            b.bind(on_release=lambda *a, m=mode: (self.set_theme(m),
                                                  self.toast("主题：%s" % m)))
            seg.add_widget(b)
        body.add_widget(seg)

        body.add_widget(Divider(color=c.c("divider")))
        body.add_widget(self._kv_label("阅读字号", bold=True))
        frow = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(10))
        minus = ModernButton(text="A−", style="outlined", outline=c.c("divider"),
                             outline_w=dp(1), text_color=c.c("text"))
        plus = ModernButton(text="A＋", style="outlined", outline=c.c("divider"),
                            outline_w=dp(1), text_color=c.c("text"))
        val = Label(text="%d%%" % int(self.font_scale * 100), font_name=FONT,
                    font_size=sp(15), color=c.c("text"), size_hint=(None, 1),
                    width=dp(70))
        minus.bind(on_release=lambda *a: self._scale(-0.1, val))
        plus.bind(on_release=lambda *a: self._scale(+0.1, val))
        frow.add_widget(minus)
        frow.add_widget(val)
        frow.add_widget(plus)
        body.add_widget(frow)

        body.add_widget(Divider(color=c.c("divider")))
        docs = self.store.list_docs()
        usage = self.store.storage_usage()
        info = "共 %d 份文档 · 占用 %.1f KB" % (len(docs), usage / 1024.0)
        body.add_widget(self._kv_label(info, color=c.c("text2")))
        body.add_widget(self._kv_label("DocLens v1.0 · 本地纯离线阅读器，不要任何权限",
                                       color=c.c("muted"), size=11.5))
        body.height = dp(300)
        ui = getattr(self._app, "ui", None)
        ui.show_sheet("设置", body, body.height)

    def _scale(self, delta, label):
        v = max(0.8, min(1.8, round(self.font_scale + delta, 2)))
        self.set_font_scale(v)
        label.text = "%d%%" % int(v * 100)
        ui = getattr(self._app, "ui", None)
        if ui and ui.reader:
            ui.reader.rebuild(force=True)

    def _kv_label(self, text, color=None, bold=False, size=14):
        lbl = Label(text=text, font_name=FONT, font_size=sp(size), bold=bold,
                    color=color or self.theme.c("text"), halign="left", valign="middle",
                    markup=False, size_hint_y=None, height=dp(26))
        lbl.bind(size=lambda i, v: setattr(i, "text_size", (i.width, None)))
        return lbl

    # ── 首次使用提示 ────────────────────────────────
    def maybe_first_hint(self):
        if self._first_hint_done:
            return
        ui = getattr(self._app, "ui", None)
        if ui is None or ui.reader is not None:
            return
        if self.store.list_docs():
            self._first_hint_done = True
            self.store.set("first_run", False)
            self.store.set("first_run_seen", True)
            self.store.flush()
            return
        self._first_hint_done = True
        self.store.set("first_run", False)
        self.store.set("first_run_seen", True)
        self.store.flush()
        self.toast("点右上角 ＋ 导入你的第一份文档", short=False)

    def toast(self, message, short=False):
        ui = getattr(self._app, "ui", None)
        if ui:
            ui.toast(message, short=short)
