# -*- coding: utf-8 -*-
"""阅读器：把 Markdown 控件指令渲染成一长条可滚动的流式页面。

排版策略（这是本 App 最讲究的部分）：
  * 每一块（标题/段落/代码/表格）自己算高度 —— Label 先把文本量出来，
    再按「可用宽度」做中英混排断行（core/textwrap.py），最后把断好的文本塞回去。
  * 好处是中文能正确折行、不会溢出、表格能横向滚动、代码块有底色卡片，
    而且高度是精确的，滚动条和进度计算都准。
"""

import os
import re

from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from core import mdrender, textwrap as tw
from core.widgets import (
    AppBar, Card, FONT, IconButton, ProgressLine, Surface,
)

MONO = "AppMono"

# 正文基准字号（sp）。mdrender 对正文块给倍率 1.0，对标题给绝对字号。
BODY_SIZE = 15.0


class SelectableLabel(Label):
    """可以横向拖动的行（代码 / 表格），并支持长按选中文本。"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.register_event_type("on_selected")
        self._allow_select = kw.pop("selectable", True)

    def on_selected(self, *a):
        pass


def _text_height(text, font_name, font_size, width, line_spacing=1.0):
    """预量一段（可含 markup 的）文本在给定宽度下的真实渲染高度。

    做法：**真的建一个 Label 让它排版**，再读 ``texture_size``。

    坑（非常重要）：不要自己断行 + 用 CoreLabel 的 ``content_size`` 估高度。
    Kivy 排版时是按「含 markup 标签的原始字符串」来算折行的 ——
    ``[b][s]不上传、[/s][/b]`` 这一串在 Kivy 眼里比可见文字「不上传、」宽得多，
    于是它会把行折得更早、行数更多。而按可见文字估算的高度只算了 3 行，
    实际渲染出来是 5 行 —— 文字就溢出色块、上下互相重叠。
    """
    if width <= 8:
        return font_size * (text.count("\n") + 1) * line_spacing * 1.3
    lbl = Label(text=text, font_name=font_name, font_size=font_size,
                markup=True, halign="left", valign="top",
                size_hint=(None, None), size=(width, 0),
                line_height=line_spacing, text_size=(width, None))
    lbl.texture_update()
    h = lbl.texture_size[1]
    if h <= 1:
        # 文本提供器还没就绪：退回「行数 × 行高」估算
        h = (text.count("\n") + 1) * font_size * line_spacing * 1.32
    return h


class ReaderView(FloatLayout):
    """阅读器主体。

    本身是 FloatLayout（ScrollView 只能挂一个子控件，装不下浮层），
    内部的 ``scroll`` 才是真正滚动的部分。
    """

    doc_rel = StringProperty("")
    doc_title = StringProperty("")
    progress = NumericProperty(0.0)
    font_scale = NumericProperty(1.0)
    is_fav = BooleanProperty(False)

    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        self.blocks = []
        self._last_w = 0
        self._labels = []       # (label, block, style) 便于改字号时重排
        self.reparse_ev = None
        self.save_ev = None
        self._saved_progress = 0.0
        # 不透明底色：否则会把下面的文档库透出来
        with self.canvas.before:
            self._bg_c = Color(rgba=app.theme.c("bg"))
            self._bg_r = Rectangle()
        self.bind(pos=self._sync_bg, size=self._sync_bg)
        self._sync_bg()
        # 内层滚动容器：正文全在这里面
        self.scroll = ScrollView(bar_width=dp(3), do_scroll_x=False,
                                 size_hint=(1, 1))
        self.scroll.bind(scroll_y=self._on_scroll_y)
        self.add_widget(self.scroll)

    def _sync_bg(self, *a):
        self._bg_r.pos = self.pos
        self._bg_r.size = self.size

    def restyle(self):
        """换肤后被复用：刷新底色。"""
        self._bg_c.rgba = self.app.theme.c("bg")

    # ── 生命周期 ────────────────────────────────────
    def load(self, rel, title=""):
        self.doc_rel = rel
        self.doc_title = title
        self.is_fav = self.app.store.is_fav(rel)
        self._saved_progress = self.app.store.progress(rel)
        self.app.store.mark_opened(rel)
        text = self.app.store.read(rel) or ""
        self.raw = text
        self.blocks = mdrender.parse(text, 1.0, self.app.colors_for_md())
        self._pending_scroll = self._saved_progress
        self.rebuild(force=True)

    def rebuild(self, force=False):
        w = self.width
        if not force and abs(w - self._last_w) < 4:
            return
        self._last_w = w
        self._build()

    def on_size(self, *a):
        if self.doc_rel:
            Clock.schedule_once(lambda dt: self.rebuild(), 0.02)

    # ── 构建 ────────────────────────────────────────
    def _avail_width(self):
        # 右边多留 46dp：悬浮字号坞（宽 42 + 边距）压在这里，
        # 不留的话正文最后几个字会被坞盖住。
        return max(dp(160), self.width - dp(20) - dp(46))

    def _base(self, size):
        """``size`` 来自 mdrender：正文块给的是「倍率」（1.0），标题块给的是
        绝对字号（22.0 等）。两者统一成绝对字号再套字号缩放。

        坑：以前直接 ``size * font_scale``，正文的 1.0 就成了 1px 字号，
        整页文字被压成一条细线。
        """
        s = float(size or 1.0)
        if s <= 3.0:
            s = BODY_SIZE * s          # 倍率形式 → 乘正文字号
        return sp(s) * self.font_scale * self.app.font_scale

    def _build(self):
        avail = self._avail_width()
        self.scroll.clear_widgets()
        # 顶部 62dp：让正文从悬浮顶栏下方开始，别被顶栏压住第一行。
        # 右侧 50dp：给悬浮字号坞让位。
        box = BoxLayout(orientation="vertical", size_hint_y=None,
                        padding=[dp(20), dp(62), dp(50), dp(48)])
        box.bind(minimum_height=box.setter("height"))
        self.box = box
        self._labels = []

        c = self.app.theme
        meas_cache = {}

        def measurer(font_name, size):
            key = (font_name, round(size, 1))
            m = meas_cache.get(key)
            if m is None:
                m = tw.Measurer(font_name, size)
                meas_cache[key] = m
            return m

        if not self.blocks:
            box.add_widget(Widget(size_hint_y=None, height=dp(120)))
            box.add_widget(Label(text="这份文档是空的", font_name=FONT, font_size=sp(15),
                                 color=c.c("muted"), size_hint_y=None, height=dp(40)))
            self.scroll.add_widget(box)
            return

        for block in self.blocks:
            w = self._make_block(block, avail, measurer)
            if w is not None:
                box.add_widget(w)
        self.scroll.add_widget(box)
        Clock.schedule_once(self._apply_start_progress, 0.08)

    def _apply_start_progress(self, *a):
        """恢复到上次读到的位置。

        坑：``1.0 - progress`` 换来的是「还剩多少」，而 Kivy 的 scroll_y 是
        「已滚过多少」，所以这里必须用 progress 本身 —— 以前写成 1-progress，
        读完一半的文档会被翻到 50% 处（看着像从头开始），进度条也永远对不上。
        """
        if getattr(self, "_pending_scroll", 0) <= 0.01:
            return
        if self.box is None or self.box.height <= self.scroll.height + dp(4):
            return
        self.scroll.scroll_y = max(0.0, min(1.0, self._pending_scroll))

    # ── 单块渲染 ────────────────────────────────────
    def _mk_label(self, text, font_name, size, color, width, halign="left",
                  line_spacing=1.0, markup=True, pad=None, selectable=False,
                  on_height=None):
        """建一个「会自动重排版」的文本 Label。

        折行交给 Kivy 自己（``text_size`` + ``halign``），高度用真实排版量出来。

        坑：不要自己用 wrap_markup 插入 ``\\n`` 再按「可见文字宽度」估高度。
        Kivy 是按含标签的原始串来折行的，两种算法对不上时行数会差一倍，
        文字就溢出色块互相重叠。这里统统一句话：**让 Kivy 折，按它的结果取高**。
        """
        h = _text_height(text, font_name, size, width, line_spacing)
        lbl = Label(text=text, font_name=font_name, font_size=size,
                    color=color, markup=markup, halign=halign, valign="top",
                    size_hint_y=None, height=h + (pad or 0),
                    line_height=line_spacing)
        lbl.text_size = (width, None)

        def _follow(inst, w):
            if w <= dp(20):
                return
            if abs(w - (inst.text_size[0] or 0)) < 0.6:
                return
            nh = _text_height(text, font_name, size, w, line_spacing)
            inst.text_size = (w, None)
            inst.height = nh + (pad or 0)
            inst._width = w
            if on_height is not None:
                on_height(inst.height)
        lbl.bind(width=_follow)
        lbl._meas = tw.Measurer(font_name, size)
        lbl._style = (font_name, size, halign, line_spacing, markup)
        lbl._width = width
        return lbl

    def _make_block(self, block, avail, measurer):
        c = self.app.theme
        cmd = block["cmd"]

        def gap(h=dp(8)):
            return Widget(size_hint_y=None, height=h)

        # ── 标题 ──────────────────────────────────
        if cmd in ("h1", "h2", "h3", "h4", "h5", "h6"):
            lvl = int(cmd[1])
            size = self._base(block["size"])
            if lvl == 1:
                l2 = self._mk_label(block["text"], FONT, size, c.c("text"),
                                    avail, pad=dp(6))
                # h1 下面加一条装饰线（主色长条 + 粉色短条）
                deco = Widget(size_hint_y=None, height=dp(5))
                with deco.canvas:
                    Color(rgba=c.c("primary", 0.85))
                    r1 = RoundedRectangle(radius=[2] * 4)
                    Color(rgba=c.c("accent", 0.85))
                    r2 = RoundedRectangle(radius=[2] * 4)
                def _deco(w, *a):
                    r1.pos = (0, 1)
                    r1.size = (min(dp(46), w.width), dp(3))
                    r2.pos = (min(dp(46), w.width) + dp(5), 1)
                    r2.size = (dp(14), dp(3))
                deco.bind(pos=_deco, size=_deco)
                outer = BoxLayout(orientation="vertical", size_hint_y=None,
                                  padding=[0, dp(18), 0, dp(6)])
                outer.add_widget(l2)
                outer.add_widget(deco)
                outer.height = l2.height + dp(28)
                # 正文宽度变化导致换行数变化时，跟着更新外层高度，
                # 否则文字会溢出色块和下一块重叠。
                l2.bind(height=lambda i, v, o=outer: setattr(o, "height", v + dp(28)))
                self._labels.append((l2, block, {"kind": "head", "lvl": lvl}))
                return outer
            pad_top = {2: dp(20), 3: dp(16), 4: dp(12), 5: dp(10), 6: dp(8)}[lvl]
            color = "text" if lvl <= 3 else "text2"
            lbl = self._mk_label(block["text"], FONT, size, c.c(color), avail,
                                 pad=dp(4))
            outer = BoxLayout(orientation="vertical", size_hint_y=None,
                              padding=[0, pad_top, 0, dp(4)])
            outer.add_widget(lbl)
            outer.height = lbl.height + pad_top + dp(4)
            if lvl == 2:
                bar = Widget(size_hint_y=None, height=dp(10))
                with bar.canvas:
                    Color(rgba=c.c("primary", 0.75))
                    r = RoundedRectangle(radius=[2] * 4)
                bar.bind(pos=lambda w, *a: (setattr(r, "pos", (0, w.height / 2 - dp(1.5))),
                                            setattr(r, "size", (dp(30), dp(3)))))
                outer.add_widget(bar)
                outer.height += dp(10)
                lbl.bind(height=lambda i, v, o=outer, pt=pad_top:
                         setattr(o, "height", v + pt + dp(14)))
            else:
                lbl.bind(height=lambda i, v, o=outer, pt=pad_top:
                         setattr(o, "height", v + pt + dp(4)))
            self._labels.append((lbl, block, {"kind": "head", "lvl": lvl}))
            return outer

        # ── 段落 ──────────────────────────────────
        if cmd == "para":
            size = self._base(block["size"])
            outer = BoxLayout(orientation="vertical", size_hint_y=None,
                              padding=[0, dp(3), 0, dp(3)])
            lbl = self._mk_label(block["text"], FONT, size, c.c("text"), avail,
                                 line_spacing=1.02,
                                 on_height=lambda h, o=outer: setattr(
                                     o, "height", h + dp(6)))
            outer.add_widget(lbl)
            outer.height = lbl.height + dp(6)
            self._labels.append((lbl, block, {"kind": "para"}))
            return outer

        # ── 列表 ──────────────────────────────────
        if cmd in ("bullet", "number"):
            size = self._base(block["size"])
            indent = dp(22) + dp(14) * block.get("level", 0)
            bullet_w = dp(20)
            text_w = max(dp(80), avail - indent - bullet_w)
            marker = ("•" if cmd == "bullet" else "%d." % (block.get("num") or 1))
            msize = size * 0.95
            mlbl = Label(text=marker, font_name=FONT, font_size=msize,
                         color=c.c("primary"), markup=False, halign="left",
                         valign="top", size_hint=(None, None),
                         width=bullet_w, text_size=(bullet_w, None))
            row = BoxLayout(orientation="horizontal", size_hint_y=None,
                            padding=[indent, dp(2), 0, dp(2)], spacing=0)

            def _sync_row(h, r=row, m=mlbl):
                m.height = h
                r.height = h + dp(4)

            lbl = self._mk_label(block["text"], FONT, size, c.c("text"), text_w,
                                 on_height=_sync_row)
            mlbl.height = lbl.height
            row.add_widget(mlbl)
            row.add_widget(lbl)
            lbl.size_hint_x = 1
            row.height = lbl.height + dp(4)
            self._labels.append((lbl, block, {"kind": "list"}))
            return row

        # ── 任务清单 ──────────────────────────────
        if cmd == "task":
            size = self._base(block["size"])
            indent = dp(22) + dp(14) * block.get("level", 0)
            box_w = dp(20)
            checked = block.get("checked")
            glyph = Label(text="✓" if checked else "", font_name=FONT,
                          font_size=sp(11), color=c.c("on_primary") if checked else c.c("surface"),
                          markup=False, size_hint=(None, None), size=(box_w, box_w))
            with glyph.canvas.before:
                Color(rgba=c.c("primary", 1.0) if checked else c.c("muted", 0.6))
                box = RoundedRectangle(radius=[dp(5)] * 4)
                Color(rgba=c.c("primary") if checked else c.c("surface"))
                inner = RoundedRectangle(radius=[dp(5)] * 4)
            def _sync(g, *a):
                box.pos = (g.x, g.center_y - box_w / 2)
                box.size = (box_w, box_w)
                inner.pos = (g.x + dp(1), g.center_y - box_w / 2 + dp(1))
                inner.size = (box_w - dp(2), box_w - dp(2))
            glyph.bind(pos=_sync, size=_sync)
            text_w = max(dp(80), avail - indent - box_w - dp(10))
            txt = self._mk_label(block["text"], FONT, size,
                                 c.c("muted") if checked else c.c("text"), text_w)
            row = BoxLayout(orientation="horizontal", size_hint_y=None,
                            padding=[indent, dp(3), 0, dp(3)], spacing=dp(10))
            row.add_widget(glyph)
            row.add_widget(txt)
            txt.size_hint_x = 1
            row.height = max(txt.height, box_w) + dp(6)
            return row

        # ── 引用 ──────────────────────────────────
        if cmd == "quote":
            size = self._base(block["size"])
            style = {"kind": "quote"}
            bar_w = dp(5)
            pad_l, pad_r = dp(11), dp(12)
            text_w = max(dp(80), avail - bar_w - pad_l - pad_r)
            lbl = self._mk_label(block["text"], FONT, size, c.c("text2"), text_w,
                                 pad=dp(2))
            card = Card(orientation="horizontal", size_hint_y=None,
                        surface_bg=c.c("surface3"),
                        radius=[dp(0), dp(12), dp(12), dp(0)],
                        elevation=0, padding=[pad_l, dp(7), pad_r, dp(7)])
            card.add_widget(lbl)

            # 左侧强调竖条
            bar = Widget(size_hint=(None, 1), width=bar_w)
            with bar.canvas:
                Color(rgba=c.c("primary", 0.8))
                br = RoundedRectangle(radius=[2] * 4)
            bar.bind(pos=lambda w, *a: (setattr(br, "pos", w.pos),
                                        setattr(br, "size", w.size)))
            wrap = BoxLayout(orientation="horizontal", size_hint_y=None,
                             height=card.height)
            wrap.add_widget(bar)
            wrap.add_widget(card)

            outer = BoxLayout(orientation="vertical", size_hint_y=None,
                              padding=[0, dp(5), 0, dp(5)])
            outer.add_widget(wrap)

            def _sync_quote(h, c=card, w=wrap, o=outer):
                c.height = h
                w.height = h
                o.height = h + dp(10)

            card.height = lbl.height + dp(14)
            _sync_quote(card.height)

            # 绑定放在最后：这三个容器都建好之后再绑，
            # 否则绑定在 add_widget 期间就会触发，而那时 wrap/outer 还不存在
            # （异常被静默吞掉，版面也就永远不刷新 —— 表现就是引用块文字互相重叠）。
            lbl.bind(height=lambda i, v: _sync_quote(v + dp(14)))
            self._labels.append((lbl, block, style))
            return outer

        # ── 分隔线 ────────────────────────────────
        if cmd == "hr":
            outer = BoxLayout(size_hint_y=None, height=dp(22))
            line = Widget()
            with line.canvas:
                Color(rgba=c.c("divider"))
                lr = RoundedRectangle(radius=[1] * 4)
            line.bind(pos=lambda w, *a: (setattr(lr, "pos", (0, w.center_y)),
                                         setattr(lr, "size", (w.width, dp(1)))),
                      size=lambda w, *a: (setattr(lr, "pos", (0, w.center_y)),
                                          setattr(lr, "size", (w.width, dp(1)))))
            outer.add_widget(line)
            return outer

        # ── 空行 ──────────────────────────────────
        if cmd == "blank":
            return gap(dp(10))

        # ── 代码块 ────────────────────────────────
        if cmd == "code":
            size = self._base(13.0)
            code = block["code"]
            lang = (block.get("lang") or "code").lower()
            meas = tw.Measurer(MONO, size)
            lines = code.split("\n") or [""]
            longest = max((meas.width(ln) for ln in lines), default=0)
            text_w = max(dp(120), min(longest, avail - dp(30)))

            body = self._mk_label(code, MONO, size, c.c("text", 0.92), text_w,
                                  line_spacing=1.06, pad=dp(0))
            head = BoxLayout(size_hint_y=None, height=dp(24), spacing=dp(8))
            lang_lbl = Label(text=lang.upper(), font_name=FONT, font_size=sp(10.5),
                             color=c.c("muted"), markup=False, halign="left",
                             valign="middle")
            lang_lbl.text_size = (dp(90), None)
            lang_lbl.bind(size=lambda w, *a: setattr(w, "text_size", (w.width, None)))
            # ⧉ (U+29C9) 不在思源黑体的字形表里，会渲染成豆腐块。
            # 换成 ▣ (U+25A3，「方框套方框」)，语意接近复制且字体确实有。
            copy = IconButton(icon="▣", size=(dp(26), dp(26)), font_size=sp(13),
                              icon_color=c.c("text2"), base_color=c.c("primary_soft", 0.9),
                              radius_ratio=0.6)
            copy.bind(on_release=lambda *a: self._copy_code(code))
            head.add_widget(lang_lbl)
            head.add_widget(copy)

            hscroll = ScrollView(size_hint_y=None, do_scroll_x=True, do_scroll_y=False,
                                 bar_width=dp(2))
            hscroll.height = body.height + dp(6)
            inner = BoxLayout(size_hint=(None, 1), width=text_w + dp(4))
            inner.add_widget(body)
            hscroll.add_widget(inner)

            card = Card(orientation="vertical", size_hint_y=None,
                           surface_bg=c.c("code_bg"), radius=[dp(14)] * 4, elevation=0,
                           padding=[dp(12), dp(8), dp(12), dp(10)],
                           outline=c.c("divider", 0.9), outline_w=dp(1))
            card.add_widget(head)
            card.add_widget(hscroll)
            card.height = hscroll.height + head.height + dp(20)

            outer = BoxLayout(orientation="vertical", size_hint_y=None,
                              padding=[0, dp(6), 0, dp(6)])
            outer.add_widget(card)
            outer.height = card.height + dp(12)
            return outer

        # ── 表格 ──────────────────────────────────
        if cmd == "table":
            size = self._base(13.5)
            header, rows = block["header"], block["rows"]
            ncol = max(1, block.get("cols") or len(header))
            cell_pad = dp(10)
            meas = tw.Measurer(FONT, size)
            col_w = []
            for k in range(ncol):
                best = 0
                for r in [header] + rows:
                    if k < len(r) and r[k]:
                        for piece in re.split(r"\s+", r[k]):
                            pass
                        best = max(best, min(meas.width(r[k]), dp(190)))
                col_w.append(max(dp(64), best) + cell_pad * 2)
            total_w = sum(col_w)

            grid = BoxLayout(orientation="vertical", size_hint=(None, None),
                             width=total_w, spacing=0)

            def make_row(cells, is_head, striping):
                row = BoxLayout(orientation="horizontal", size_hint_y=None,
                                spacing=0)
                row_h = 0
                rendered = []
                for k in range(ncol):
                    raw = cells[k] if k < len(cells) else ""
                    txt = mdrender.render_inline(raw, size,
                                                 self.app.theme.hex("text"),
                                                 self.app.theme.hex("primary"))
                    inner_w = max(dp(30), col_w[k] - cell_pad * 2)
                    m = tw.Measurer(FONT, size)
                    wrapped = tw.wrap_markup(txt, m, inner_w)
                    h = _text_height(wrapped, FONT, size, inner_w)
                    # 文本高度 + 上下内边距（Card padding 的 7+7），
                    # 别再额外 +14 —— 那会把每行撑成两倍高。
                    cell_h = h + dp(14)
                    cell = Card(size_hint=(None, None), width=col_w[k],
                                surface_bg=(c.c("primary_soft") if is_head else
                                            (c.c("surface") if striping == 0
                                             else c.c("surface2"))),
                                radius=[0] * 4, elevation=0,
                                outline=c.c("divider", 0.85), outline_w=dp(0.7),
                                padding=[cell_pad, dp(7), cell_pad, dp(7)])
                    lbl = Label(text=wrapped, font_name=FONT, font_size=size,
                                markup=True, halign="left", valign="top",
                                color=c.c("text"), size_hint=(1, None),
                                height=h, bold=is_head)
                    lbl.text_size = (inner_w, None)
                    cell.height = cell_h
                    cell.add_widget(lbl)
                    rendered.append((cell, cell_h))
                    row_h = max(row_h, cell_h)
                for cell, _h in rendered:
                    cell.height = row_h
                    row.add_widget(cell)
                row.height = row_h
                return row

            rows_w = []
            rows_w.append(make_row(header, True, 0))
            for ri, r in enumerate(rows):
                rows_w.append(make_row(r, False, ri % 2))

            # 自己把行高加起来算总高。
            # 坑：``grid.height`` 依赖 minimum_height 的绑定，add_widget 之后
            # 那一瞬间它还是 0，直接拿来当 ScrollView 高度会让整张表塌成 0，
            # 表格下面出现一大片空白。
            total_h = sum(rw.height for rw in rows_w)
            for rw in rows_w:
                grid.add_widget(rw)
            grid.height = total_h

            hscroll = ScrollView(size_hint_y=None, do_scroll_x=True, do_scroll_y=False,
                                 bar_width=dp(2))
            hscroll.height = total_h
            hscroll.add_widget(grid)
            hold = BoxLayout(orientation="vertical", size_hint_y=None,
                             height=total_h + dp(12), padding=[0, dp(6), 0, dp(6)])
            hold.add_widget(hscroll)
            return hold

        # ── 图片 ──────────────────────────────────
        if cmd == "image":
            holder = BoxLayout(orientation="vertical", size_hint_y=None,
                               height=dp(76), padding=[0, dp(8), 0, dp(8)])
            return holder

        return None

    # ── 交互 ────────────────────────────────────────
    def _copy_code(self, code):
        try:
            from kivy.core.clipboard import Clipboard
            Clipboard.copy(code)
            self.app.toast("代码已复制")
        except Exception:
            self.app.toast("复制失败")

    def _on_scroll_y(self, _w, value):
        if not self.doc_rel:
            return
        # 内容还没撑满一屏时 scroll_y 恒为 1，换算出来 progress=0，安全；
        # 但刚 add_widget 那一瞬 scroll_y 可能是 0，会把进度误写成 100%
        # （表现：一打开文档就「已读完」，下次再进直接跳到末尾）。
        # 所以内容不超过一屏时一律不算进度。
        if self.box is None or self.box.height <= self.scroll.height + dp(4):
            self.progress = 0.0
            return
        self.progress = max(0.0, min(1.0, 1.0 - value))
        if self.save_ev is None:
            self.save_ev = Clock.schedule_once(self._save_progress, 0.8)

    def _save_progress(self, *a):
        self.save_ev = None
        if self.doc_rel:
            self.app.store.set_progress(self.doc_rel, self.progress)

    # ── 字号 ────────────────────────────────────────
    def bump_font(self, delta):
        scale = self.app.font_scale
        scale = max(0.8, min(1.8, round(scale + delta, 2)))
        self.app.set_font_scale(scale)
        self.rebuild(force=True)

    def scroll_by(self, pages):
        step = self.height * 0.86 * pages
        total = max(1.0, self.box.height - self.scroll.height)
        target = self.scroll.scroll_y + step / total
        self.scroll.scroll_y = max(0.0, min(1.0, target))
