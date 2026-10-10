# -*- coding: utf-8 -*-
"""文档编辑器：新建 / 编辑 Markdown，支持插入图片与半透明背景设置。

设计：全屏浮层（和 ReaderView 一样挂在 Shell 上），
  顶栏：返回 / 标题 / 保存
  中间：TextInput（Kivy 自带软键盘会跟着弹）
  底部：插入图片 / 背景 / 预览
"""

import os
import re

from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.textinput import TextInput

from core import android as droid
from core.widgets import AppBar, FONT, IconButton, ModernButton

TEMPLATE = "# 未命名\n\n在这里写下第一行文字。\n"


class EditorView(FloatLayout):
    """Markdown 编辑器。``rel`` 为 None 表示新建。"""

    def __init__(self, app, rel=None, title="", **kw):
        super().__init__(**kw)
        self.app = app
        self.rel = rel
        self.is_new = rel is None
        self.doc_title = title or ("新建文档" if self.is_new else "编辑")
        c = app.theme

        with self.canvas.before:
            self._bg_c = Color(rgba=c.c("bg"))
            self._bg_r = Rectangle()
        self.bind(pos=self._sync_bg, size=self._sync_bg)
        self._sync_bg()

        root = BoxLayout(orientation="vertical")
        self.add_widget(root)

        # ── 顶栏 ────────────────────────────────────
        bar = AppBar(title=self.doc_title, appbar_bg=c.c("bg"), elevation=0,
                     title_color=c.c("text"))
        back = IconButton(icon="←", size=(dp(40), dp(40)), font_size=sp(20),
                          icon_color=c.c("text"))
        back.bind(on_release=lambda *a: self.close())
        bar.add_left(back)
        save = IconButton(icon="保存", size=(dp(74), dp(36)), font_size=sp(14),
                          icon_color=c.c("on_primary"),
                          base_color=c.c("primary"), radius_ratio=0.45)
        save.bind(on_release=lambda *a: self.save())
        bar.add_right(save)
        root.add_widget(bar)

        # ── 正文 ────────────────────────────────────
        holder = BoxLayout(padding=[dp(14), 0, dp(14), dp(8)])
        self.input = TextInput(
            text="", multiline=True, font_name=FONT, font_size=sp(15),
            background_normal="", background_active="",
            background_color=c.c("surface"),
            foreground_color=c.c("text"),
            cursor_color=c.c("primary"),
            hint_text="写点什么吧……支持 Markdown：# 标题、**粗体**、- 列表",
            hint_text_color=c.c("muted"),
            padding=[dp(14), dp(12), dp(14), dp(12)],
        )
        holder.add_widget(self.input)
        root.add_widget(holder)

        # ── 工具条 ──────────────────────────────────
        tools = BoxLayout(size_hint_y=None, height=dp(58), spacing=dp(8),
                          padding=[dp(14), 0, dp(14), dp(10)])
        for text, cb in (("插入图片", self.insert_image),
                         ("背景", self.bg_menu),
                         ("预览", self.preview)):
            b = ModernButton(text=text, surface_bg=c.c("surface3"),
                             text_color=c.c("text"), radius=[dp(13)] * 4)
            b.bind(on_release=lambda *a, f=cb: f())
            tools.add_widget(b)
        root.add_widget(tools)

        # ── 内容 ────────────────────────────────────
        if self.rel:
            try:
                self.input.text = app.store.read(self.rel) or ""
            except Exception:
                self.input.text = ""
        else:
            self.input.text = TEMPLATE
        self._initial = self.input.text
        self._dirty = False
        self.input.bind(text=self._on_change)

    # ── 基础 ────────────────────────────────────────
    def _sync_bg(self, *a):
        self._bg_r.pos = self.pos
        self._bg_r.size = self.size

    def _on_change(self, *a):
        self._dirty = True

    # ── 保存 / 关闭 ─────────────────────────────────
    def _derive_name(self, text):
        """从正文第一行猜一个文件名。"""
        for line in (text or "").split("\n"):
            s = line.strip().lstrip("#").strip()
            s = re.sub(r"[*_`>\[\]]", "", s).strip()
            if len(s) >= 2:
                return s[:24] + ".md"
        return "未命名.md"

    def save(self, quiet=False):
        text = self.input.text
        try:
            if self.rel is None:
                self.rel = self.app.store.import_text(self._derive_name(text), text)
                self.is_new = False
            else:
                self.app.store.write_text(self.rel, text)
        except Exception as exc:
            self.app.toast("保存失败：%s" % exc)
            return False
        self._dirty = False
        self._initial = text
        try:
            self.app.after_edit_saved(self.rel)
        except Exception:
            pass
        if not quiet:
            self.app.toast("已保存")
        return True

    def close(self):
        """返回：有改动就保存（新建且没动过则直接丢弃）。"""
        if self._dirty and self.input.text.strip() != TEMPLATE.strip():
            self.save(quiet=True)
        elif self._dirty and self.rel is not None:
            self.save(quiet=True)
        self.app.close_editor()

    # ── 插入图片 ────────────────────────────────────
    def insert_image(self):
        try:
            droid.pick_files(self._on_image_picked, images_only=True)
        except Exception as exc:
            self.app.toast("打开选择器失败：%s" % exc)

    def _on_image_picked(self, items):
        if not items:
            return
        ok = 0
        for _name, path in items:
            try:
                rel = self.app.store.import_image(path)
            except Exception as exc:
                self.app.toast("插入失败：%s" % exc)
                continue
            md = "\n![](%s)\n" % rel
            try:
                self.input.insert_text(md)
            except Exception:
                self.input.text += md
            ok += 1
        if ok:
            self.app.toast("已插入 %d 张图片" % ok)

    # ── 背景 / 预览 ─────────────────────────────────
    def bg_menu(self):
        if self.rel is None and not self.save(quiet=True):
            return
        self.app.doc_bg_sheet(self.rel, on_change=self._bg_changed)

    def _bg_changed(self):
        pass

    def preview(self):
        if self._dirty and not self.save(quiet=True):
            return
        rel = self.rel
        self.app.close_editor()
        Clock.schedule_once(lambda dt: self.app.open_doc(rel), 0.15)
