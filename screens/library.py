# -*- coding: utf-8 -*-
"""文档库：搜索 / 收藏 / 最近阅读 / 全部文档。"""

import os
import time

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Ellipse, Line, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from core import mdrender, textwrap as tw
from core.store import TEXT_EXT
from core.widgets import (
    AppBar, Chip, EmptyState, FONT, IconButton,
    SearchField, Surface, TypeBadge,
)


def human_size(n):
    if n < 1024:
        return "%d B" % n
    if n < 1024 * 1024:
        return "%.1f KB" % (n / 1024.0)
    return "%.1f MB" % (n / 1048576.0)


def _ellipsize(text, font_name, font_size, max_w=None, bold=False):
    """按像素宽度把文本截断并补「…」。

    不用 Label 自带的 ``shorten``：它在本项目常见的
    ``text_size=(w, None) + valign="middle"`` 组合下会误判宽度，
    把明明放得下的标题也截成「DocLen…」。这里自己量、自己裁，结果可预期。

    ``max_w`` 为 None 或 <=0 时返回原文。
    """
    if not max_w or max_w <= 8:
        return text
    try:
        lbl = CoreLabel(text=("[b]%s[/b]" % text) if bold else text,
                        font_name=font_name, font_size=font_size,
                        markup=bool(bold))
        lbl.refresh()
    except Exception:
        # 字体还没注册（App 启动极早期）时别炸，原样返回
        return text
    if lbl.content_size[0] <= max_w:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        cand = text[:mid] + ell
        try:
            c = CoreLabel(text=("[b]%s[/b]" % cand) if bold else cand,
                          font_name=font_name, font_size=font_size,
                          markup=bool(bold))
            c.refresh()
        except Exception:
            return text
        if c.content_size[0] <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + ell if lo < len(text) else text


def human_time(ts):
    now = time.time()
    d = now - ts
    if d < 60:
        return "刚刚"
    if d < 3600:
        return "%d 分钟前" % int(d // 60)
    if d < 86400:
        return "%d 小时前" % int(d // 3600)
    if d < 86400 * 7:
        return "%d 天前" % int(d // 86400)
    return time.strftime("%m-%d", time.localtime(ts))


class DocRow(Surface, BoxLayout):
    """列表里的一张文档卡片。"""

    # 卡片固定高度（``height`` 在布局过程中会被父容器改，别直接读）
    fixed_height = NumericProperty(0)

    def __init__(self, app, doc, on_open, on_menu, **kw):
        kw.setdefault("radius", [dp(18)] * 4)
        kw.setdefault("elevation", 1)
        kw.setdefault("orientation", "horizontal")
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(94))
        kw.setdefault("padding", [dp(12), dp(12), dp(8), dp(12)])
        kw.setdefault("spacing", dp(12))
        # 卡片底色必须来自主题！Surface 默认是纯白 [1,1,1,1]，
        # 深色主题下会变成「白卡片 + 浅色字」——标题几乎不可见。
        kw.setdefault("surface_bg", app.theme.c("surface"))
        kw.setdefault("shadow_color", app.theme.c("shadow", 0.10))
        super().__init__(**kw)
        self.fixed_height = kw["height"]
        self.app = app
        self.doc = doc
        self._on_open = on_open
        c = app.theme

        ext = os.path.splitext(doc["name"])[1].lower().lstrip(".") or "txt"
        is_md = ext in ("md", "markdown", "mdown", "mkd")
        accent = c.c("primary") if is_md else c.c("accent")
        soft = c.c("primary_soft") if is_md else c.c("accent_soft")
        badge = TypeBadge(text=("MD" if is_md else "TXT").lower(),
                          surface_bg=soft, label_color=accent,
                          size=(dp(46), dp(46)))
        # 徽章固定尺寸、在 52 宽的槽里居中。
        # 坑：TypeBadge 是 Surface+BoxLayout，size_hint 一旦留在 (1,1)，
        # 它会跟着父容器撑开并把正文挤到右边。
        holder = BoxLayout(size_hint=(None, 1), width=dp(52))
        badge.size_hint = (None, None)
        badge.pos_hint = {"center_x": 0.5, "center_y": 0.5}
        holder.add_widget(badge)
        self.add_widget(holder)

        # 正文列：标题 + 摘要 + 元信息。三段都定高，由它们自己撑满卡片高度，
        # 不在末尾放 Spacer —— 放了会把整列压成 auto 高度、全部堆到顶上，
        # 卡片下半截出现一大片空白。
        body = BoxLayout(orientation="vertical", spacing=dp(2))
        # 标题：不用 Label 自带的 shorten（它在本项目的 text_size/valign 组合下
        # 会把明明放得下的标题也截成「DocLen…」）。宽度一确定就自己截断。
        title = Label(text=doc["title"], font_name=FONT, font_size=sp(15), bold=True,
                      color=c.c("text"), halign="left", valign="middle", markup=False,
                      size_hint_y=None, height=dp(24))

        def _fix_title(i, w):
            i.text_size = (w, None)
            # 宽度太小说明布局还没算完，别急着把标题截成一个「…」
            if w > dp(30):
                i.text = _ellipsize(doc["title"], FONT, sp(15), bold=True, max_w=w)
        title.bind(width=_fix_title)

        prev = doc.get("preview") or "还没有生成摘要，打开一次即可"
        p = Label(text=prev, font_name=FONT, font_size=sp(12),
                  color=c.c("muted"), halign="left", valign="top", markup=False,
                  size_hint_y=None, height=dp(20))

        def _fix_p(i, w):
            i.text_size = (w, None)
            if w > dp(30):
                i.text = _ellipsize(prev, FONT, sp(12), max_w=w)
        p.bind(width=_fix_p)

        meta = BoxLayout(size_hint_y=None, height=dp(22), spacing=dp(5))
        # 定高 + 不参与纵向拉伸，否则 chip 会被拉成和卡片一样高
        meta.size_hint_y = None

        def _fit_chips(*_a):
            """按可用宽度裁剪 chip。

            卡片右侧是进度环 / 更多按钮，正文区宽度是动态的；
            窄屏上三个 chip 会顶出卡片右边缘，所以从右往左量，
            放不下的直接隐藏（而不是压扁）——保持每个 chip 都可读。
            """
            avail = body.width if body.width > dp(40) else dp(180)
            used = 0.0
            for chip in reversed(meta.children):   # children 是倒序
                cw = chip.width if chip.width > 1 else dp(48)
                if used > 0 and used + cw + dp(5) > avail:
                    chip.opacity = 0
                    chip.size_hint = (None, None)
                    chip.size = (0, dp(22))
                else:
                    chip.opacity = 1
                    used += cw + dp(5)

        bits = [human_time(doc["mtime"])]
        if doc.get("minutes"):
            bits.append("约 %d 分钟" % doc["minutes"])
        bits.append(human_size(doc["size"]))
        for b in bits:
            meta.add_widget(Chip(text=b, surface_bg=c.c("surface3"),
                                 label_color=c.c("text2"),
                                 radius=[dp(7)] * 4, font_size=sp(10.5)))
        body.bind(width=lambda *a: Clock.schedule_once(_fit_chips, 0))
        Clock.schedule_once(_fit_chips, 0.05)
        body.add_widget(title)
        body.add_widget(p)
        body.add_widget(meta)
        self.add_widget(body)

        # 右侧动作区：定宽 34，进度环（如有）+ 更多按钮纵向居中。
        # 注意不能再加一个 Widget() 撑开，否则 progress/more 会被推到卡片底部。
        acts = BoxLayout(size_hint=(None, 1), width=dp(34),
                         orientation="vertical", spacing=0)
        prog = app.store.progress(doc["rel"])
        if 0.01 < prog < 0.995:
            ring = ProgressRing(value=prog, color=c.c("primary"),
                                size=(dp(28), dp(28)))
            rh = BoxLayout()
            ring.size_hint = (None, None)
            ring.pos_hint = {"center_x": 0.5, "center_y": 0.5}
            rh.add_widget(ring)
            acts.add_widget(rh)
        more = IconButton(icon="⋮", size=(dp(34), dp(34)), font_size=sp(17),
                          icon_color=c.c("text2"), radius_ratio=0.5)
        more.bind(on_release=lambda *a: on_menu(doc, more))
        mh = BoxLayout()
        more.pos_hint = {"center_x": 0.5, "center_y": 0.5}
        mh.add_widget(more)
        acts.add_widget(mh)
        self.add_widget(acts)

    def on_release(self):
        self._on_open(self.doc)


class ProgressRing(Widget):
    """阅读进度圆环。"""

    value = NumericProperty(0.0)

    def __init__(self, color=None, **kw):
        super().__init__(**kw)
        self.color = color or [0.3, 0.27, 0.9, 1]
        with self.canvas:
            Color(rgba=[self.color[0], self.color[1], self.color[2], 0.18])
            self._track = Line(width=dp(3), cap="round")
            Color(rgba=self.color)
            self._arc = Line(width=dp(3), cap="round")
        self.bind(pos=self._s, size=self._s, value=self._s)

    def _s(self, *a):
        cx, cy = self.center
        r = min(self.width, self.height) / 2 - dp(2)
        self._track.circle = (cx, cy, r, 0, 360, 48)
        ang = max(2.0, 360.0 * min(1.0, max(0.0, self.value)))
        self._arc.circle = (cx, cy, r, 90, 90 - ang, 48)


class LibraryView(BoxLayout):
    """文档库主界面。"""

    query = StringProperty("")
    filter_mode = StringProperty("all")   # all / fav

    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        self.orientation = "vertical"
        self._rows = []
        self._build_scaffold()

    # ── 骨架（顶栏 + 搜索） ──────────────────────────
    def _build_scaffold(self):
        c = self.app.theme
        head = BoxLayout(orientation="vertical", size_hint_y=None,
                         padding=[dp(18), dp(14), dp(14), dp(10)], spacing=dp(10))
        trow = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        big = Label(text="我的文档", font_name=FONT, font_size=sp(24), bold=True,
                    color=c.c("text"), halign="left", valign="middle", markup=False)
        big.bind(size=lambda i, v: setattr(i, "text_size", (i.width, None)))
        trow.add_widget(big)
        # 设置入口：右上角一个看得见、点得到的胶囊按钮。
        # （以前只有左下角一个 42dp 的齿轮图标 —— 在 1080p 屏上小成一个点，
        #   而且 ⚙ 字形也未必在子集化字体里，导致用户根本找不到设置。）
        gear = IconButton(icon="设置", size=(dp(76), dp(36)), font_size=sp(14),
                          icon_color=c.c("text2"), base_color=c.c("surface3"),
                          radius_ratio=0.45)
        gear.size_hint = (None, None)
        gear.bind(on_release=lambda *a: self.app.settings_sheet())
        trow.add_widget(gear)
        head.add_widget(trow)

        srow = BoxLayout(size_hint_y=None, height=dp(46),
                         padding=[0, 0, 0, 0], spacing=dp(10))
        self.search = SearchField(surface_bg=c.c("surface"), outline=c.c("divider"),
                                  outline_w=dp(1),
                                  icon_color=c.c("text2"),
                                  entry_text_color=c.c("text"),
                                  hint_text_color=c.c("muted"),
                                  cursor_color=c.c("primary"))
        self.search.bind(text=self._on_query)
        srow.add_widget(self.search)
        add = IconButton(icon="＋", size=(dp(46), dp(46)), font_size=sp(22),
                         icon_color=c.c("on_primary"), base_color=c.c("primary"),
                         radius_ratio=0.34)
        add.bind(on_release=lambda *a: self.app.add_menu())
        srow.add_widget(add)
        head.add_widget(srow)
        # 高度按子项累加，别再写死 —— 写死会和实际内容错位，标题被顶栏压住
        head.height = dp(40) + dp(46) + dp(10) + head.padding[1] + head.padding[3]
        self.add_widget(head)

        fl = BoxLayout(size_hint_y=None, height=dp(38), padding=[dp(18), 0, dp(14), 6],
                       spacing=dp(8))
        self.chip_all = self._filter_chip("全部文档", "all")
        self.chip_fav = self._filter_chip("★ 收藏", "fav")
        fl.add_widget(self.chip_all)
        fl.add_widget(self.chip_fav)
        fl.add_widget(Widget())
        self.add_widget(fl)

        self.scroll = ScrollView(bar_width=dp(3), do_scroll_x=False)
        self.list_box = BoxLayout(orientation="vertical", size_hint_y=None,
                                  padding=[dp(18), dp(4), dp(14), dp(96)],
                                  spacing=dp(10))
        # ScrollView 不会自动把子控件的宽度设为自身宽度，必须显式给
        # size_hint_x=1（并关掉 do_scroll_x）。不给的话 list_box 宽度会
        # 缩到 100px，里面每张卡片的标题都被截成「DocLen…」。
        self.list_box.size_hint_x = 1
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        self.scroll.add_widget(self.list_box)
        self.add_widget(self.scroll)

        self._last_signature = None

    def _filter_chip(self, text, mode):
        c = self.app.theme
        chip = Chip(text=text, surface_bg=c.c("surface3"), label_color=c.c("text2"),
                    radius=[dp(9)] * 4, font_size=sp(12))
        # 宽度交给 Chip 自己按文字量，别再写死 —— 写死会把「★ 收藏」裁掉。
        chip.height = dp(32)
        chip.padding = [dp(13), dp(6), dp(13), dp(6)]
        chip.bind(on_release=lambda *a: self._set_filter(mode))
        return chip

    def _set_filter(self, mode):
        self.filter_mode = mode
        c = self.app.theme
        for chip, m in ((self.chip_all, "all"), (self.chip_fav, "fav")):
            on = (m == mode)
            chip.bg = c.c("primary") if on else c.c("surface3")
            for child in chip.children:
                if isinstance(child, Label):
                    child.color = c.c("on_primary") if on else c.c("text2")
        self.refresh(smooth=False)

    def _on_query(self, _i, value):
        self.query = value
        self.refresh(smooth=False)

    # ── 内容刷新 ────────────────────────────────────
    def refresh(self, smooth=True):
        self._last_signature = None
        self._rebuild()

    def maybe_refresh(self):
        sig = self._signature()
        if sig != self._last_signature:
            self._rebuild()

    def _signature(self):
        docs = self.app.store.list_docs()
        q = self.query.strip().lower()
        n = 0
        for d in docs:
            if q and q not in d["name"].lower() and q not in d["title"].lower() \
                    and q not in (d.get("preview") or "").lower():
                continue
            if self.filter_mode == "fav" and not self.app.store.is_fav(d["rel"]):
                continue
            n += 1
        return (n, len(docs), q, self.filter_mode)

    def _rebuild(self):
        c = self.app.theme
        self._last_signature = self._signature()
        for w in list(self.list_box.children):
            self.list_box.remove_widget(w)
        store = self.app.store
        docs = store.list_docs()
        q = self.query.strip().lower()

        def match(d):
            if self.filter_mode == "fav" and not store.is_fav(d["rel"]):
                return False
            if q and q not in d["name"].lower() and q not in d["title"].lower() \
                    and q not in (d.get("preview") or "").lower():
                return False
            return True

        shown = [d for d in docs if match(d)]

        # 搜索有结果时的提示条
        if q:
            info = Label(text="找到 %d 份匹配「%s」的文档" % (len(shown), self.query),
                         font_name=FONT, font_size=sp(12), color=c.c("text2"),
                         size_hint_y=None, height=dp(26), halign="left", markup=False)
            info.bind(size=lambda i, v: setattr(i, "text_size", (i.width, None)))
            self.list_box.add_widget(info)

        if not docs:
            self.list_box.add_widget(EmptyState(
                title="书架上空空的",
                desc="点右上角的 ＋ 导入 .md / .txt 文档，或直接新建一篇\n（也可以把文件用「分享到」发进来）",
                color=c.c("text"), accent=c.c("primary")))
            return
        if not shown:
            self.list_box.add_widget(EmptyState(
                title="没有找到",
                desc=("换个关键词试试" if q else "收藏夹还是空的，点文档卡片的 ⋮ 可以收藏"),
                color=c.c("text"), accent=c.c("accent")))
            return

        # 最近阅读（仅在无搜索、全部视图时展示）
        if not q and self.filter_mode == "all":
            recent = [d for d in shown if store.progress(d["rel"]) > 0.01][:3]
            if recent:
                self.list_box.add_widget(self._section("继续阅读", "%d 篇在读" % len(recent)))
                for d in recent:
                    self.list_box.add_widget(self._wrap(DocRow(
                        self.app, d, self.app.open_doc, self.app.doc_menu)))

        title = "收藏" if self.filter_mode == "fav" else ("全部文档" if not q else "搜索结果")
        self.list_box.add_widget(self._section(title, "%d 份" % len(shown)))
        for d in shown:
            self.list_box.add_widget(self._wrap(DocRow(
                self.app, d, self.app.open_doc, self.app.doc_menu)))

    def _wrap(self, widget):
        """给卡片套一层定高容器。

        ``list_box`` 是 minimum_height 撑开的纵向 BoxLayout，里面每一项必须
        自己声明高度，否则会被压扁。
        坑：holder 高度必须用卡片的「固定高度」而不是读 widget.height ——
        读的时候布局还没跑，拿到的是默认 100，套出来的 holder 高度是错的，
        卡片再 size_hint_y=1 撑满，就变成了 182 高（应该 94）。
        """
        h = widget.fixed_height
        holder = BoxLayout(size_hint=(1, None), height=h + dp(10))
        holder.add_widget(widget)
        widget.size_hint = (1, None)
        widget.height = h
        return holder

    def _section(self, text, right):
        c = self.app.theme
        box = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(6))
        lbl = Label(text=text, font_name=FONT, font_size=sp(13), bold=True,
                    color=c.c("text2"), halign="left", valign="middle", markup=False)
        lbl.bind(size=lambda i, v: setattr(i, "text_size", (i.width, None)))
        r = Label(text=right, font_name=FONT, font_size=sp(11.5), color=c.c("muted"),
                  halign="right", valign="middle", markup=False,
                  size_hint=(None, 1), width=dp(70))
        box.add_widget(lbl)
        box.add_widget(r)
        return box

    def animate_in(self):
        """进入时的错落淡入，别小看这个，App 的「顺滑感」一半靠它。"""
        rows = list(reversed(self.list_box.children))
        for i, w in enumerate(rows):
            w.opacity = 0
            anim = Animation(opacity=1, d=0.26, t="out_cubic")
            Clock.schedule_once(lambda dt, a=anim, ww=w: a.start(ww), 0.022 * i)
