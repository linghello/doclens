# -*- coding: utf-8 -*-
"""阅读器：把 Markdown 控件指令渲染成一长条可滚动的流式页面。

排版策略（这是本 App 最讲究的部分）：
  * 每一块（标题/段落/代码/表格）自己算高度 —— Label 先把文本量出来，
    再按「可用宽度」做中英混排断行（core/textwrap.py），最后把断好的文本塞回去。
  * 好处是中文能正确折行、不会溢出、表格能横向滚动、代码块有底色卡片，
    而且高度是精确的，滚动条和进度计算都准。
"""

import json
import os
import re

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
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

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "assets")


def _measure_label(lbl):
    """让 Label 立刻完成一次排版，并让它把纹理缓存下来。

    这是打开速度的关键：以前为了量高度会另建一个临时 Label 做
    ``texture_update()``，然后真正的 Label 渲染时**又光栅化一遍** ——
    同一段文字排版两次。现在直接量真身，渲染时复用同一张纹理，省掉一半。
    """
    try:
        lbl.texture_update()
    except Exception:
        pass


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


class InkLayer(Widget):
    """批注手绘层：叠在正文之上、随正文一起滚动。

    坐标按「归一化」保存（x / 层宽、y / 层高），所以换字号、换屏宽之后
    批注依旧贴在同一段文字上。绘制时分两条线：已完成的笔画各自成一条
    Line（只在增删时改），正在画的只有一条 live Line（每帧只更新它），
    这样笔画再多也不会卡。
    """

    def __init__(self, app, doc_rel, **kw):
        super().__init__(**kw)
        self.app = app
        self.doc_rel = doc_rel
        self.strokes = []                 # 归一化的已完成笔画
        self.color = [0.93, 0.27, 0.36, 1]
        self.stroke_w = dp(3.2)
        self._cur = None                  # 正在画的（像素坐标）
        self.disabled = True              # 默认不拦截触摸
        with self.canvas.before:
            self._c_done = Color(rgba=self.color)
        self._done_lines = []
        with self.canvas:
            self._c_live = Color(rgba=self.color)
            self._live = Line(points=[], width=self.stroke_w,
                              joint="round", cap="round")
        self.bind(pos=self._relayout, size=self._relayout)

    # ── 持久化 ──────────────────────────────────
    def _path(self):
        d = os.path.join(self.app.store.base, "ink")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, self.doc_rel + ".json")

    def load(self):
        try:
            with open(self._path(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.strokes = [[(float(p[0]), float(p[1])) for p in s]
                            for s in data.get("strokes", []) if len(s) >= 2]
        except Exception:
            self.strokes = []
        self._rebuild_lines()

    def save(self):
        try:
            with open(self._path(), "w", encoding="utf-8") as fh:
                json.dump({"strokes": [[[round(x, 5), round(y, 5)] for x, y in s]
                                       for s in self.strokes]}, fh)
        except Exception:
            pass

    # ── 坐标 ────────────────────────────────────
    def _norm2px(self, nx, ny):
        w = max(1.0, self.width)
        h = max(1.0, self.height)
        return (self.x + nx * w, self.y + (1.0 - ny) * h)

    def _pts(self, stroke):
        out = []
        for nx, ny in stroke:
            out.extend(self._norm2px(nx, ny))
        return out

    def _new_line(self, points):
        line = Line(points=points, width=self.stroke_w,
                    joint="round", cap="round")
        self.canvas.before.add(line)
        self._done_lines.append(line)
        return line

    def _rebuild_lines(self):
        for l in self._done_lines:
            self.canvas.before.remove(l)
        self._done_lines = []
        self._live.points = []
        for s in self.strokes:
            self._new_line(self._pts(s))

    def _relayout(self, *a):
        self._rebuild_lines()

    def clear(self):
        self.strokes = []
        self._cur = None
        self.save()
        self._rebuild_lines()

    def undo(self):
        if self.strokes:
            self.strokes.pop()
            self.save()
            self._rebuild_lines()

    @property
    def count(self):
        return len(self.strokes)

    # ── 触摸 ────────────────────────────────────
    def collide_point(self, x, y):
        # 非批注模式下彻底不参与命中判定，保证正文照常滚动
        if self.disabled:
            return False
        return super().collide_point(x, y)

    def on_touch_down(self, touch):
        if self.disabled or not self.collide_point(*touch.pos):
            return False
        self._cur = [(touch.x, touch.y)]
        self._live.points = list(self._cur)
        return True

    def on_touch_move(self, touch):
        if self.disabled or self._cur is None:
            return False
        self._cur.append((touch.x, touch.y))
        # 只更新 live 这一条，不重画全部笔画
        pts = self._live.points
        pts.extend((touch.x, touch.y))
        return True

    def on_touch_up(self, touch):
        if self._cur is None:
            return False
        pts = self._cur
        self._cur = None
        self._live.points = []
        w = max(1.0, self.width)
        h = max(1.0, self.height)
        norm = [((x - self.x) / w, 1.0 - (y - self.y) / h) for x, y in pts]
        if len(norm) >= 2:
            self.strokes.append(norm)
            self._new_line(self._pts(norm))
            self.save()
        return True


class _LoadingOverlay(FloatLayout):
    """打开文档时的等待层：一张「正在思考……」贴纸 + 上下轻浮动。"""

    bob = NumericProperty(0.0)

    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        with self.canvas.before:
            self._c = Color(rgba=app.theme.c("bg"))
            self._r = Rectangle()
        self.bind(pos=self._sync_bg, size=self._sync_bg)
        self._sync_bg()
        self._img = Image(source=os.path.join(ASSETS, "loading", "thinking.png"),
                          size_hint=(None, None), allow_stretch=True,
                          keep_ratio=True, mipmap=True)
        self.add_widget(self._img)
        self._lbl = Label(text="正在打开文档…", font_name=FONT, font_size=sp(13.5),
                          color=app.theme.c("text2"), markup=False,
                          size_hint=(None, None), size=(dp(240), dp(24)),
                          halign="center", valign="middle")
        self.add_widget(self._lbl)
        self.bind(bob=lambda *a: self._sync_items(),
                  size=lambda *a: self._sync_items())
        self._sync_items()
        self._anim = None

    def _sync_bg(self, *a):
        self._r.pos = self.pos
        self._r.size = self.size

    def _sync_items(self, *a):
        iw = min(dp(230), max(dp(140), self.width * 0.52))
        ih = iw * (428.0 / 420.0)
        self._img.size = (iw, ih)
        cx = self.width / 2.0
        self._img.pos = (cx - iw / 2.0,
                         self.height * 0.56 + self.bob * dp(12) - ih / 2.0)
        self._lbl.pos = (cx - dp(120), self.height * 0.56 - ih / 2.0 - dp(40))

    def start(self):
        self.opacity = 1.0
        try:
            self._anim = (Animation(bob=1.0, d=0.85, t="in_out_sine")
                          + Animation(bob=0.0, d=0.85, t="in_out_sine"))
            self._anim.repeat = True
            self._anim.start(self)
        except Exception:
            pass

    def stop(self, on_done=None):
        if self._anim is not None:
            try:
                self._anim.cancel(self)
            except Exception:
                pass
            self._anim = None
        anim = Animation(opacity=0.0, d=0.16, t="out_quad")
        if on_done is not None:
            anim.bind(on_complete=lambda *a: on_done())
        anim.start(self)


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
        self.style = {}
        self._built_once = False
        self._tries = 0
        self.ink = None
        self.ink_mode = False
        self._loading = None
        self._bg_tex = None
        # 不透明底色：否则会把下面的文档库透出来
        with self.canvas.before:
            self._bg_c = Color(rgba=app.theme.c("bg"))
            self._bg_r = Rectangle()
            self._bg_img_c = Color(rgba=[1, 1, 1, 0])
            self._bg_img = Rectangle(texture=None)
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
        self._sync_bg_image()

    def _sync_bg_image(self, *a):
        """半透明背景图：按 cover 方式铺满整页。"""
        tex = self._bg_tex
        if tex is None:
            self._bg_img_c.rgba = [1, 1, 1, 0]
            self._bg_img.texture = None
            return
        self._bg_img_c.rgba = [1, 1, 1, float(self.style.get("bg_opacity", 0.22))]
        tw_, th_ = tex.size
        w, h = self.size
        if tw_ <= 0 or th_ <= 0 or w <= 0 or h <= 0:
            return
        scale = max(w / float(tw_), h / float(th_))     # cover：铺满，不留边
        dw, dh = tw_ * scale, th_ * scale
        self._bg_img.texture = tex
        self._bg_img.size = (dw, dh)
        self._bg_img.pos = (self.x + (w - dw) / 2.0, self.y + (h - dh) / 2.0)

    def apply_style(self, style=None):
        """应用该文档的个性化样式（半透明背景图等）。"""
        self.style = (style if style is not None
                      else self.app.store.doc_style(self.doc_rel))
        path = self.app.store.image_path(self.style.get("bg") or "")
        self._bg_tex = None
        if path:
            try:
                self._bg_tex = CoreImage(path).texture
            except Exception:
                self._bg_tex = None
        self._sync_bg_image()

    def restyle(self):
        """换肤后被复用：刷新底色。"""
        self._bg_c.rgba = self.app.theme.c("bg")

    # ── 生命周期 ────────────────────────────────────
    def load(self, rel, title=""):
        self.doc_rel = rel
        self.doc_title = title
        self.is_fav = self.app.store.is_fav(rel)
        self._saved_progress = self.app.store.progress(rel)
        try:
            self.app.store.mark_opened(rel)
        except Exception:
            pass
        text = self.app.store.read(rel) or ""
        self.raw = text
        self.blocks = mdrender.parse(text, 1.0, self.app.colors_for_md())
        self._pending_scroll = self._saved_progress
        self.apply_style()
        self._show_loading()
        # ⚠️ 关键：这里绝不能直接开始排版！
        #    此刻 self.width 还是默认的 100，建完 on_size 一到又得整篇重建一次
        #    —— 一篇文档白白排版两遍，这就是"打开很慢"的一大半原因。
        #    改成等布局给出真实宽度后再建一次（期间用加载层顶着）。
        self._built_once = False
        self._tries = 0
        Clock.schedule_once(self._deferred_build, 0)

    # ── 加载层 ──────────────────────────────────────
    def _show_loading(self):
        if self._loading is None:
            self._loading = _LoadingOverlay(self.app, size_hint=(1, 1))
            self.add_widget(self._loading)
        else:
            self._loading.opacity = 1.0
            if self._loading.parent is None:
                self.add_widget(self._loading)
        self._loading.start()

    def _hide_loading(self):
        ov, self._loading = self._loading, None
        if ov is None:
            return

        def _done():
            try:
                if ov.parent is not None:
                    self.remove_widget(ov)
            except Exception:
                pass
        ov.stop(on_done=_done)

    def _deferred_build(self, dt=0):
        if self.width < dp(80) and self._tries < 30:
            self._tries += 1
            Clock.schedule_once(self._deferred_build, 0)
            return
        self._last_w = self.width
        self._build()
        self._built_once = True
        self._hide_loading()

    def rebuild(self, force=False):
        w = self.width
        if not force and abs(w - self._last_w) < 4:
            return
        self._last_w = w
        self._build()

    def on_size(self, *a):
        # 只有"已经建过一次"之后才跟着尺寸重建；否则会和 _deferred_build 撞车
        if self.doc_rel and self._built_once:
            Clock.schedule_once(lambda dt: self.rebuild(), 0.05)

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
        # 外层 FloatLayout：正文（box）和手绘批注层（ink）叠在一起，这样批注
        # 会跟着正文一起滚动，而不是钉死在屏幕上。
        # （Kivy 的 ScrollView 只能挂一个子控件，所以 ink 不能直接放 ScrollView 下。）
        wrap = FloatLayout(size_hint_x=1, size_hint_y=None)
        wrap.pos_hint = {"x": 0, "y": 0}
        # 顶部 62dp：让正文从悬浮顶栏下方开始，别被顶栏压住第一行。
        # 右侧 50dp：给悬浮字号坞让位。
        box = BoxLayout(orientation="vertical", size_hint=(1, None),
                        pos_hint={"x": 0, "y": 0},
                        padding=[dp(20), dp(62), dp(50), dp(48)])
        box.bind(minimum_height=box.setter("height"))
        box.bind(height=lambda i, v, w=wrap: setattr(w, "height", v))
        self.box = box
        self.wrap = wrap
        self._labels = []
        wrap.add_widget(box)

        ink = InkLayer(self.app, self.doc_rel, size_hint=(1, 1),
                       pos_hint={"x": 0, "y": 0})
        ink.disabled = not self.ink_mode        # 平时不拦截触摸，能正常滚动
        wrap.add_widget(ink)
        self.ink = ink
        ink.load()

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
            self.scroll.add_widget(wrap)
            return

        for block in self.blocks:
            w = self._make_block(block, avail, measurer)
            if w is not None:
                box.add_widget(w)
        self.scroll.add_widget(wrap)
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
        lbl = Label(text=text, font_name=font_name, font_size=size,
                    color=color, markup=markup, halign=halign, valign="top",
                    size_hint_y=None, height=dp(10), line_height=line_spacing)
        lbl.text_size = (width, None)
        # 立刻量真身：这一次排版会被渲染直接复用（旧写法另建临时 Label
        # 量高度，等于把同一段文字光栅化两遍）。
        _measure_label(lbl)
        h = lbl.texture_size[1]
        if h <= 1:
            h = (text.count("\n") + 1) * size * line_spacing * 1.32
        lbl.height = h + (pad or 0)

        def _follow(inst, w):
            if w <= dp(20):
                return
            if abs(w - (inst.text_size[0] or 0)) < 0.6:
                return
            inst.text_size = (w, None)
            _measure_label(inst)
            nh = inst.texture_size[1]
            if nh <= 1:
                nh = (text.count("\n") + 1) * size * line_spacing * 1.32
            inst.height = nh + (pad or 0)
            inst._width = w
            if on_height is not None:
                on_height(inst.height)
        lbl.bind(width=_follow)
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
            alt = block.get("alt") or "图片"
            path = self.app.store.image_path(block.get("src") or "")
            if not path:
                holder = BoxLayout(orientation="vertical", size_hint_y=None,
                                   height=dp(54), padding=[0, dp(6), 0, dp(6)])
                holder.add_widget(Label(
                    text="［图片未找到：%s］" % alt, font_name=FONT,
                    font_size=sp(12.5), color=c.c("muted"), markup=False))
                return holder
            try:
                tex = CoreImage(path).texture
            except Exception:
                tex = None
            if tex is None:
                return None
            iw, ih = tex.size
            if iw <= 0 or ih <= 0:
                return None
            scale = min(1.0, avail / float(iw))      # 不放大小图，避免糊
            dw, dh = iw * scale, ih * scale
            holder = FloatLayout(size_hint_x=1, size_hint_y=None,
                                 height=dh + dp(20))
            img = Image(texture=tex, size_hint=(None, None), size=(dw, dh),
                        allow_stretch=True, keep_ratio=True, mipmap=True)
            img.pos_hint = {"center_x": 0.5, "center_y": 0.5}
            holder.add_widget(img)
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

    # ── 手绘批注（圈点） ────────────────────────────
    def set_ink_mode(self, on):
        """进入/退出批注模式。批注模式下禁止滚动，免得画着画着页面跑了。"""
        self.ink_mode = bool(on)
        if self.ink is not None:
            self.ink.disabled = not self.ink_mode
        try:
            self.scroll.do_scroll_y = not self.ink_mode
        except Exception:
            pass
        return self.ink_mode

    def toggle_ink_mode(self):
        return self.set_ink_mode(not self.ink_mode)

    def clear_ink(self):
        if self.ink is not None:
            self.ink.clear()
            self.app.toast("批注已清空")

    def undo_ink(self):
        if self.ink is not None:
            self.ink.undo()
            self.app.toast("已撤销一笔")

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
