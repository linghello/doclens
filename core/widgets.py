# -*- coding: utf-8 -*-
"""现代感控件库。

Kivy 自带控件长得像 2012 年的安卓，这里全部自己画：
圆角卡片、柔和阴影、水波纹按压反馈、底部弹层、Toast。
所有控件只认 Theme 给的 rgb 列表，换肤 = 重建界面。
"""

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.graphics import (
    Canvas,
    Color,
    Ellipse,
    Line,
    RoundedRectangle,
    StencilPop,
    StencilPush,
    StencilUnUse,
    StencilUse,
)
from kivy.metrics import dp, sp
from kivy.properties import (
    BooleanProperty,
    ListProperty,
    NumericProperty,
    OptionProperty,
    StringProperty,
)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

FONT = "AppFont"

__all__ = [
    "FONT", "Surface", "Card", "RippleBehavior", "ModernButton", "IconButton",
    "AppBar", "SearchField", "Chip", "Divider", "EmptyState", "Toast",
    "BottomSheet", "ProgressLine", "TypeBadge", "SectionTitle", "IconLabel",
]


# ── 圆角表面（背景 + 阴影 + 描边 + 裁剪） ──────────────────────
class Surface(ButtonBehavior, Widget):
    """给任意控件加上「圆角背景 + 柔和阴影 + 描边 + 圆角裁剪」，
    并支持水波纹按压反馈。

    硬性约束（踩过坑，别改）：
    1. **必须放在 MRO 第一位**（`class DocRow(Surface, BoxLayout)`）。
       它继承自 ButtonBehavior，只有排在首位，Kivy 编译期生成的事件注册
       才能正常走到它的 ``__init__``。
    2. 背景色属性叫 ``surface_bg`` 而不是 ``bg`` —— ``Widget.bg`` 在 Kivy
       里是尺寸别名（right/bottom），赋值会触发 TypeError 或读回元组。
    3. 混入类构造顺序必须是 ``super().__init__()`` → 再建 canvas。
    """

    surface_bg = ListProperty([1, 1, 1, 1])
    radius = ListProperty([dp(16)] * 4)
    outline = ListProperty([0, 0, 0, 0])
    outline_w = NumericProperty(dp(1))
    elevation = NumericProperty(1)
    shadow_color = ListProperty([0, 0, 0, 0.07])
    ripple_rgba = ListProperty([0.5, 0.5, 0.5, 0.16])
    ripple_dur = NumericProperty(0.42)

    def __init__(self, *a, **kw):
        # 兼容写法：调用方传 bg= 也能生效（Widget.bg 是尺寸别名，不能直接用）
        if "surface_bg" not in kw and "bg" in kw:
            kw["surface_bg"] = kw.pop("bg")
        # ButtonBehavior.__init__ 会立刻派发事件，先把内部对象准备好
        self._ripple_canvas = Canvas()
        self._ripple_color = Color(rgba=[1, 1, 1, 0])
        self._ripple_ellipse = Ellipse(size=(0, 0))
        self._ripple_anim = None
        super().__init__(*a, **kw)
        # canvas 要等 super().__init__ 之后才存在
        with self.canvas.before:
            self._sh_colors = [Color(rgba=[0, 0, 0, 0]), Color(rgba=[0, 0, 0, 0])]
            self._sh_rects = [RoundedRectangle(), RoundedRectangle()]
            self._bg_color = Color(rgba=self.surface_bg)
            self._bg_rect = RoundedRectangle(radius=self.radius)
            self._ol_color = Color(rgba=self.outline)
            self._ol_line = Line(width=self.outline_w)
            StencilPush()
            self._stencil_rect = RoundedRectangle(radius=self.radius)
            StencilUse()
        with self.canvas.after:
            StencilUnUse()
            StencilPop()
        self._ripple_canvas.add(self._ripple_color)
        self._ripple_canvas.add(self._ripple_ellipse)
        try:
            self.canvas.after.insert(len(self.canvas.after.children),
                                     self._ripple_canvas)
        except Exception:
            self.canvas.after.add(self._ripple_canvas)
        for p in ("pos", "size", "surface_bg", "radius", "outline", "outline_w",
                  "elevation", "shadow_color"):
            self.bind(**{p: self._sync_surface})
        self._sync_surface()

    # 水波纹
    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        if getattr(self, "_ripple_canvas", None) is not None:
            self._start_ripple(touch)
        return super().on_touch_down(touch)

    def _start_ripple(self, touch):
        if self._ripple_anim:
            self._ripple_anim.cancel(self)
            self._ripple_anim = None
        x, y = self.to_local(*touch.pos)
        d = max(self.width, self.height) * 2.1
        self._ripple_ellipse.pos = (x - d / 2, y - d / 2)
        self._ripple_ellipse.size = (d, d)
        col = self.ripple_rgba
        self._ripple_color.rgba = [col[0], col[1], col[2], col[3]]
        self._ripple_anim = Animation(rgba=[col[0], col[1], col[2], 0.0],
                                      d=self.ripple_dur, t="out_quad")
        self._ripple_anim.bind(on_complete=self._clear_ripple)
        self._ripple_anim.start(self._ripple_color)

    def _clear_ripple(self, *a):
        self._ripple_color.rgba = [0, 0, 0, 0]
        self._ripple_anim = None



    def _sync_surface(self, *a):
        x, y = self.pos
        w, h = self.size
        e = self.elevation
        rad = self.radius
        for i, (dy, spread, k) in enumerate(((dp(2), dp(1), 1.0), (dp(6), dp(2), 0.6))):
            r = max(0.0, (rad[0] if rad else 0) + spread)
            self._sh_rects[i].pos = (x - spread, y - dy)
            self._sh_rects[i].size = (w + 2 * spread, h + 2 * spread)
            self._sh_rects[i].radius = [r] * 4
            sc = self.shadow_color
            self._sh_colors[i].rgba = [sc[0], sc[1], sc[2], sc[3] * k * e]
        self._bg_color.rgba = self.surface_bg
        self._bg_rect.pos = (x, y)
        self._bg_rect.size = (w, h)
        self._bg_rect.radius = rad
        self._stencil_rect.pos = (x, y)
        self._stencil_rect.size = (w, h)
        self._stencil_rect.radius = rad
        ow = self.outline_w
        if self.outline[3] > 0.001 and ow > 0:
            self._ol_color.rgba = self.outline
            # 描边画在边缘内侧半个线宽处，避免被裁掉
            self._ol_line.width = ow
            self._ol_line.rounded_rectangle = (
                x + ow / 2, y + ow / 2, max(0, w - ow), max(0, h - ow),
                rad[0] if rad else 0,
            )
        else:
            self._ol_color.rgba = [0, 0, 0, 0]


class Card(Surface, BoxLayout):
    """最基础的圆角卡片容器。"""

    def __init__(self, **kw):
        if "surface_bg" not in kw:
            kw["surface_bg"] = kw.pop("bg", [1, 1, 1, 1])
        super().__init__(**kw)
        if "padding" not in kw:
            self.padding = [dp(14)] * 4


# ── 按钮 ───────────────────────────────────────────────
class ModernButton(Surface, BoxLayout):
    """填充 / 描边 / 幽灵 三种样式的现代按钮。"""

    text = StringProperty("")
    style = OptionProperty("filled", options=["filled", "outlined", "ghost"])
    font_size = NumericProperty(sp(15))
    text_color = ListProperty([1, 1, 1, 1])
    icon = StringProperty("")
    radius = ListProperty([dp(14)] * 4)

    def __init__(self, **kw):
        kw.setdefault("elevation", 0)
        if "surface_bg" not in kw:
            kw["surface_bg"] = kw.pop("bg", [0, 0, 0, 0])
        super().__init__(**kw)
        self.orientation = "horizontal"
        self.padding = [dp(16), 0]
        self.spacing = dp(8)
        self._icon = Label(text=self.icon, font_name=FONT, font_size=self.font_size * 1.05,
                           size_hint=(None, 1), color=self.text_color, markup=False)
        self._lbl = Label(text=self.text, font_name=FONT, font_size=self.font_size,
                          color=self.text_color, halign="center", valign="middle",
                          shorten=False, markup=False)
        self._lbl.bind(size=lambda *a: setattr(self._lbl, "text_size",
                                               (self._lbl.width, None)))
        if self.icon:
            self.add_widget(self._icon)
        self.add_widget(self._lbl)
        self.bind(icon=self._sync_i, text=self._sync_t, text_color=self._sync_c,
                  font_size=self._sync_c)

    def _sync_i(self, *a):
        self._icon.text = self.icon
        self._icon.font_size = self.font_size * 1.05

    def _sync_t(self, *a):
        self._lbl.text = self.text

    def _sync_c(self, *a):
        self._icon.color = self.text_color
        self._lbl.color = self.text_color
        self._icon.font_size = self.font_size * 1.05
        self._lbl.font_size = self.font_size


class IconButton(Surface, Label):
    """纯图标按钮（圆形底座 + 字符图标）。"""

    icon = StringProperty("")
    icon_color = ListProperty([0, 0, 0, 1])
    base_color = ListProperty([0, 0, 0, 0])
    ripple_rgba = ListProperty([0.5, 0.5, 0.5, 0.18])
    radius_ratio = NumericProperty(1.0)  # 1=圆形，0.55=圆角方

    def __init__(self, **kw):
        kw.setdefault("markup", False)
        kw.setdefault("size_hint", (None, None))
        kw.setdefault("size", (dp(40), dp(40)))
        # 必须用图标字体！否则继承 Label 的默认 Roboto，⌕ ⋮ ⚙ ＋ 全是空白/豆腐块
        kw.setdefault("font_name", FONT)
        # 图标必须居中！Label 默认 halign=left / valign=bottom，
        # 而 valign 要生效又必须先有 text_size —— 否则大字（如 22sp 的 ＋）
        # 会从按钮底部往上冒，上半截被裁掉，看起来就是「按钮上什么都没有」。
        kw.setdefault("halign", "center")
        kw.setdefault("valign", "middle")
        # base_color 就是这个按钮的底色，直接当 surface_bg 用，别再画两层
        # （以前 base_color 画在下面、白色 surface_bg 盖在上面，
        #   主色按钮看起来就是一块白板、图标也被盖住）。
        if "surface_bg" not in kw:
            kw["surface_bg"] = kw.get("base_color") or kw.pop("bg", [0, 0, 0, 0])
        kw.setdefault("elevation", 0)
        super().__init__(**kw)
        # 调用方传了 size= 会让 setdefault 失焦，这里强制回正。
        self.size_hint = (None, None)
        self.size = kw.get("size", (dp(40), dp(40)))
        # text_size 跟着按钮走：valign="middle" 只有拿到 text_size 才生效
        self.text_size = self.size
        self.bind(size=lambda i, v: setattr(i, "text_size", v))
        # 圆角/圆形由 Surface 的 surface_bg + radius 负责，
        # base_color 只是对外保留的别名，改它就等于改底色。
        rr = min(self.size) * self.radius_ratio / 2
        self.radius = [rr] * 4
        self.bind(pos=self._s, size=self._s, base_color=self._s,
                  radius_ratio=self._s,
                  icon=lambda *a: setattr(self, "text", self.icon),
                  icon_color=lambda *a: setattr(self, "color", self.icon_color))
        self.text = self.icon
        self.color = self.icon_color

    def _s(self, *a):
        rr = min(self.size) * self.radius_ratio / 2
        self.radius = [rr] * 4
        if self.base_color:
            self.surface_bg = self.base_color


# ── 顶栏 ───────────────────────────────────────────────
class AppBar(Surface, BoxLayout):
    """顶部栏：左侧按钮、居左标题、右侧动作区。"""

    title = StringProperty("")
    subtitle = StringProperty("")
    appbar_bg = ListProperty([1, 1, 1, 1])   # 避开 Widget.bg 的尺寸别名
    # ⚠️ Label 的默认颜色是白色！浅色主题下不显式设色 = 「白纸上的白字」，
    # 整个顶栏标题直接隐形（这就是「白色主题挡住字」的元凶之一）。
    title_color = ListProperty([0.08, 0.10, 0.15, 1])
    subtitle_color = ListProperty([0.36, 0.39, 0.47, 1])

    def __init__(self, **kw):
        if "surface_bg" not in kw:
            kw["surface_bg"] = kw.pop("bg", kw.pop("appbar_bg", [1, 1, 1, 1]))
        self.left_box = BoxLayout(size_hint=(None, 1), width=dp(48))
        self.center_box = BoxLayout(orientation="vertical", padding=[0, dp(4), 0, 0])
        self.right_box = BoxLayout(size_hint=(None, 1), width=dp(48))
        kw.setdefault("elevation", 0)
        super().__init__(**kw)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = kw.get("bar_height", dp(56))
        self.padding = [dp(6), 0, dp(10), 0]
        self.spacing = dp(2)
        self.add_widget(self.left_box)
        self.add_widget(self.center_box)
        self.add_widget(self.right_box)
        self._t = Label(text=self.title, font_name=FONT, font_size=sp(17),
                        bold=True, halign="left", valign="middle", markup=False,
                        shorten=True, shorten_from="right",
                        color=self.title_color)
        self._t.bind(size=lambda *a: setattr(self._t, "text_size", (self._t.width, None)))
        self.center_box.add_widget(self._t)
        if self.subtitle:
            self._s = Label(text=self.subtitle, font_name=FONT, font_size=sp(11),
                            halign="left", valign="middle", markup=False,
                            color=self.subtitle_color)
            self._s.bind(size=lambda *a: setattr(self._s, "text_size", (self._s.width, None)))
            self.center_box.add_widget(self._s)
        self.bind(title=lambda *a: setattr(self._t, "text", self.title),
                  title_color=lambda *a: setattr(self._t, "color", self.title_color))

    def add_right(self, widget):
        self.right_box.add_widget(widget)
        self.right_box.width = sum(w.width for w in self.right_box.children) + dp(4)

    def add_left(self, widget):
        self.left_box.add_widget(widget)
        self.left_box.width = sum(w.width for w in self.left_box.children) + dp(4)


# ── 搜索框 ─────────────────────────────────────────────
class SearchField(Surface, BoxLayout):
    """圆角搜索框，含放大镜图标与清除按钮。"""

    hint = StringProperty("搜索文档…")
    text = StringProperty("")
    # ⚠️ 颜色按主题传入。Label 默认白字（放大镜会隐形）；
    # TextInput 的 foreground/hint 若写死深色，深色主题下同样看不见。
    icon_color = ListProperty([0.45, 0.48, 0.56, 1])
    entry_text_color = ListProperty([0.10, 0.10, 0.15, 1])
    hint_text_color = ListProperty([0.60, 0.62, 0.68, 1])
    cursor_color = ListProperty([0.31, 0.27, 0.90, 1])

    def __init__(self, **kw):
        if "surface_bg" not in kw:
            kw["surface_bg"] = kw.pop("bg", [1, 1, 1, 1])
        kw.setdefault("elevation", 0)
        super().__init__(**kw)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(46)
        hint = self.hint
        self.entry = TextInput(
            text="", hint_text=hint, multiline=False,
            font_name=FONT, font_size=sp(15), background_normal="",
            background_active="", background_color=[0, 0, 0, 0],
            foreground_color=self.entry_text_color,
            cursor_color=self.cursor_color,
            padding=[dp(6), dp(12), dp(6), dp(12)], size_hint=(1, 1),
            hint_text_color=self.hint_text_color, write_tab=False,
        )
        self.padding = [dp(12), 0, dp(6), 0]
        self.spacing = dp(6)
        self._ico = Label(text="⌕", font_name=FONT, font_size=sp(19),
                          size_hint=(None, 1), width=dp(24), markup=False,
                          color=self.icon_color)
        self._clr = IconButton(icon="✕", size=(dp(30), dp(30)), font_size=sp(15),
                               base_color=[0, 0, 0, 0])
        self._clr.bind(on_release=lambda *a: self._clear())
        self.add_widget(self._ico)
        self.add_widget(self.entry)
        self.entry.bind(text=lambda i, v: setattr(self, "text", v))
        self.bind(hint=lambda *a: setattr(self.entry, "hint_text", self.hint))
        self.bind(text=lambda *a: self._sync_clr())

    def _sync_clr(self, *a):
        if self.text and self._clr.parent is None:
            self.add_widget(self._clr)
        elif not self.text and self._clr.parent is not None:
            self.remove_widget(self._clr)

    def _clear(self):
        self.entry.text = ""
        self.entry.focus = True

    def focus(self):
        self.entry.focus = True

    def restyle(self, text_color=None, hint_color=None, cursor=None):
        """换肤后由外部调用，刷新 TextInput 内部颜色。"""
        if text_color is not None:
            self.entry.foreground_color = text_color
        if hint_color is not None:
            self.entry.hint_text_color = hint_color
        if cursor is not None:
            self.entry.cursor_color = cursor


# ── 零散小件 ────────────────────────────────────────────
class Chip(Surface, BoxLayout):
    """小标签：文件类型、字数、状态等。"""

    text = StringProperty("")
    label_color = ListProperty([0.3, 0.3, 0.4, 1])
    font_size = NumericProperty(sp(11))

    def __init__(self, **kw):
        if "surface_bg" not in kw:
            kw["surface_bg"] = kw.pop("bg", [1, 1, 1, 1])
        kw.setdefault("elevation", 0)
        kw.setdefault("radius", [dp(8)] * 4)
        kw.setdefault("size_hint", (None, None))
        kw.setdefault("size", (dp(24), dp(22)))
        super().__init__(**kw)
        self.orientation = "horizontal"
        # 不能只 setdefault —— 调用方传了 size= 就会跳过默认值，
        # 而 size_hint 一旦留在 (1,1)，chip 会在定高父容器里被纵向拉满。
        self.size_hint = (None, None)
        self.padding = [dp(8), dp(3), dp(8), dp(3)]
        tl = Label(text=self.text, font_name=FONT, font_size=self.font_size,
                   color=self.label_color, size_hint=(None, 1), markup=False)
        tl.bind(texture_size=lambda i, v: setattr(tl, "width", v[0] + dp(2)))
        self.bind(text=lambda *a: setattr(tl, "text", self.text),
                  label_color=lambda *a: setattr(tl, "color", self.label_color))
        self.add_widget(tl)
        self.height = dp(22)

        def _fit(*_a):
            self.width = tl.width + self.padding[0] + self.padding[2]
        tl.bind(width=_fit)
        Clock.schedule_once(_fit, 0)


class Divider(Widget):
    """1px 分割线。"""

    color = ListProperty([0, 0, 0, 0.08])

    def __init__(self, **kw):
        super().__init__(**kw)
        self.size_hint_y = None
        self.height = dp(1)
        with self.canvas:
            self._c = Color(rgba=self.color)
            self._r = RoundedRectangle(radius=[0.5] * 4)
        self.bind(pos=self._s, size=self._s, color=self._s)

    def _s(self, *a):
        self._c.rgba = self.color
        self._r.pos = self.pos
        self._r.size = self.size


class TypeBadge(Surface, BoxLayout):
    """文档类型徽章：MD / TXT。"""

    text = StringProperty("MD")
    label_color = ListProperty([1, 1, 1, 1])

    def __init__(self, **kw):
        if "surface_bg" not in kw:
            kw["surface_bg"] = kw.pop("bg", [1, 1, 1, 1])
        kw.setdefault("elevation", 0)
        kw.setdefault("radius", [dp(12)] * 4)
        super().__init__(**kw)
        # 同上：调用方传了 size= 时 setdefault 不生效，这里再兜一次。
        self.size_hint = (None, None)
        self.size = kw.get("size", (dp(46), dp(46)))
        self.padding = [0, 0, 0, 0]
        tl = Label(text=self.text, font_name=FONT, font_size=sp(13), bold=True,
                   color=self.label_color, markup=False)
        self.bind(text=lambda *a: setattr(tl, "text", self.text),
                  label_color=lambda *a: setattr(tl, "color", self.label_color))
        self.add_widget(tl)


class SectionTitle(BoxLayout):
    """分区标题（左标题 + 右侧可选说明）。"""

    def __init__(self, text="", right="", color=None, **kw):
        super().__init__(**kw)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(30)
        self.add_widget(Label(text=text, font_name=FONT, font_size=sp(13), bold=True,
                              halign="left", color=color or [0.1, 0.1, 0.15, 1],
                              markup=False))
        if right:
            self.add_widget(Label(text=right, font_name=FONT, font_size=sp(11),
                                  halign="right", size_hint=(None, 1), width=dp(90),
                                  color=color or [0.1, 0.1, 0.15, 1], markup=False))


class IconLabel(Label):
    """带图标字体的标签（图标与文字同色）。"""

    def __init__(self, **kw):
        kw.setdefault("font_name", FONT)
        kw.setdefault("markup", False)
        super().__init__(**kw)


class ProgressLine(Widget):
    """细进度条（阅读进度）。"""

    value = NumericProperty(0.0)  # 0..1
    color = ListProperty([0.3, 0.27, 0.9, 1])
    track_color = ListProperty([0, 0, 0, 0.08])

    def __init__(self, **kw):
        super().__init__(**kw)
        self.size_hint_y = None
        self.height = dp(3)
        with self.canvas:
            self._tc = Color(rgba=self.track_color)
            self._tr = RoundedRectangle(radius=[1.5] * 4)
            self._fc = Color(rgba=self.color)
            self._fr = RoundedRectangle(radius=[1.5] * 4)
        self.bind(pos=self._s, size=self._s, value=self._s,
                  color=self._s, track_color=self._s)

    def _s(self, *a):
        self._tc.rgba = self.track_color
        self._fc.rgba = self.color
        self._tr.pos = self.pos
        self._tr.size = self.size
        self._fr.pos = self.pos
        self._fr.size = (max(0.0, self.width * min(1.0, max(0.0, self.value))), self.height)


class EmptyState(BoxLayout):
    """空状态插画（用矢量画一个空心文档 + 文案）。"""

    def __init__(self, title="还没有文档", desc="点下方按钮导入 .md / .txt 文件",
                 color=None, accent=None, **kw):
        super().__init__(**kw)
        self.orientation = "vertical"
        # ⚠️ 必须定高：空状态被塞进 size_hint_y=None + minimum_height 的纵向
        # BoxLayout，那里 size_hint_y 仍是默认 1 的子控件分到的高度是 0
        # → 整个空状态（插画 + 文案）完全不显示，页面上只剩一片空白。
        self.size_hint_y = None
        self.height = dp(360)
        self.spacing = dp(10)
        self.add_widget(Widget(size_hint=(1, 0.2)))
        glyph = _DocGlyph(color=accent or [0.31, 0.27, 0.9, 1])
        glyph.size_hint = (None, None)
        glyph.size = (dp(96), dp(118))
        glyph.pos_hint = {"center_x": 0.5}
        self.add_widget(glyph)
        t = Label(text=title, font_name=FONT, font_size=sp(16), bold=True,
                  halign="center", color=color or [0.1, 0.1, 0.15, 1], markup=False,
                  size_hint_y=None, height=dp(28))
        self.add_widget(t)
        d = Label(text=desc, font_name=FONT, font_size=sp(12.5), halign="center",
                  color=(color or [0.1, 0.1, 0.15, 1])[:3] + [0.6], markup=False,
                  size_hint_y=None, height=dp(40))
        d.bind(size=lambda *a: setattr(d, "text_size", (d.width, None)))
        self.add_widget(d)
        self.add_widget(Widget(size_hint=(1, 0.3)))


class _DocGlyph(Widget):
    """一个折角文档的矢量插画。"""

    color = ListProperty([0.31, 0.27, 0.9, 1])

    def __init__(self, **kw):
        super().__init__(**kw)
        with self.canvas:
            self._c = Color(rgba=self.color)
            self._body = RoundedRectangle()
            self._fold = RoundedRectangle()
            self._c2 = Color(rgba=[1, 1, 1, 1])
            self._lines = [RoundedRectangle() for _ in range(4)]
        self.bind(pos=self._s, size=self._s, color=self._s)

    def _s(self, *a):
        x, y, w, h = self.pos[0], self.pos[1], self.width, self.height
        self._c.rgba = self.color
        self._body.pos = (x, y)
        self._body.size = (w, h)
        self._body.radius = [dp(12)] * 4
        fold = w * 0.34
        self._fold.pos = (x + w - fold, y + h - fold)
        self._fold.size = (fold, fold)
        self._fold.radius = [dp(4)] * 4
        self._c2.rgba = [1, 1, 1, 0.92]
        for i, r in enumerate(self._lines):
            lw = w * (0.62 - 0.07 * (i % 3))
            r.pos = (x + w * 0.16, y + h * (0.62 - i * 0.15))
            r.size = (lw, dp(4))
            r.radius = [dp(2)] * 4


# ── Toast ──────────────────────────────────────────────
class Toast(Surface, BoxLayout):
    """底部浮动提示，2 秒自动消失。"""

    text = StringProperty("")

    def __init__(self, **kw):
        if "surface_bg" not in kw:
            kw["surface_bg"] = kw.pop("bg", [1, 1, 1, 1])
        kw.setdefault("radius", [dp(16)] * 4)
        kw.setdefault("elevation", 2)
        super().__init__(**kw)
        self.size_hint = (None, None)
        self.padding = [dp(18), dp(11), dp(18), dp(11)]
        self.opacity = 0
        self._lbl = Label(text=self.text, font_name=FONT, font_size=sp(13.5),
                          color=[1, 1, 1, 1], halign="center", markup=False,
                          size_hint=(None, 1))
        self._lbl.bind(texture_size=lambda i, v: setattr(self._lbl, "width", v[0] + dp(4)))
        self.add_widget(self._lbl)
        self.bind(text=self._sync)

    def _sync(self, *a):
        self._lbl.text = self.text

    def show(self, parent, message, duration=2.0):
        self.text = message
        if self.parent is not None:
            parent.remove_widget(self)
        parent.add_widget(self)
        w = min(parent.width - dp(48), self._lbl.width + self.padding[0] + self.padding[2])
        self.size = (w, dp(42))
        self.x = (parent.width - w) / 2
        self.y = dp(24)
        self.opacity = 0
        anim = Animation(opacity=1, y=dp(38), d=0.22, t="out_cubic")
        anim.bind(on_complete=lambda *x: Clock.schedule_once(
            lambda dt: self._dismiss(parent), duration))
        anim.start(self)

    def _dismiss(self, parent):
        anim = Animation(opacity=0, y=dp(24), d=0.18, t="in_cubic")
        anim.bind(on_complete=lambda *x: parent.remove_widget(self)
                  if self.parent is parent else None)
        anim.start(self)


# ── 底部弹层 ────────────────────────────────────────────
class BottomSheet(FloatLayout):
    """从底部滑出的模态面板：半透明遮罩 + 圆角面板。"""

    # ⚠️ 面板底色 / 标题色必须由调用方按主题传入：Card 默认是纯白、
    # Label 默认是白字 —— 不传的话深色主题下一片白、浅色主题下标题隐形。
    bg_color = ListProperty([1, 1, 1, 1])
    title_color = ListProperty([0.08, 0.10, 0.15, 1])

    def __init__(self, title="", **kw):
        super().__init__(**kw)
        self._scrim_color = Color(rgba=[0, 0, 0, 0])
        self._scrim = RoundedRectangle(radius=[0] * 4)
        self.canvas.add(self._scrim_color)
        self.canvas.add(self._scrim)
        self.bind(size=self._sync_scrim, pos=self._sync_scrim)

        self.panel = Card(orientation="vertical", size_hint=(1, None),
                          surface_bg=self.bg_color,
                          padding=[dp(18), dp(14), dp(18), dp(18)])
        self.panel.pos_hint = {"x": 0}
        self.panel.radius = [dp(26), dp(26), 0, 0]
        self.add_widget(self.panel)

        head = BoxLayout(size_hint_y=None, height=dp(34))
        grab = Widget(size_hint=(None, 1), width=dp(36))
        with grab.canvas:
            Color(rgba=[0.5, 0.5, 0.55, 0.35])
            RoundedRectangle(pos=(grab.x + dp(6), grab.center_y - dp(1.5)),
                             size=(dp(24), dp(3)), radius=[1.5] * 4)
        head.add_widget(grab)
        self.title_lbl = Label(text=title, font_name=FONT, font_size=sp(15),
                               bold=True, halign="left", markup=False,
                               color=self.title_color)
        self.title_lbl.bind(size=lambda *a: setattr(self.title_lbl, "text_size",
                                                    (self.title_lbl.width, None)))
        head.add_widget(self.title_lbl)
        self.panel.add_widget(head)
        self.body = BoxLayout(orientation="vertical", size_hint_y=None)
        self.panel.add_widget(self.body)

        # 点击遮罩关闭
        self._touch_guard = Widget(size_hint=(1, 1))
        self._touch_guard.bind(on_touch_down=self._on_scrim_touch)
        self.add_widget(self._touch_guard, index=len(self.children))

    def _sync_scrim(self, *a):
        self._scrim.pos = self.pos
        self._scrim.size = self.size

    def _on_scrim_touch(self, w, touch):
        if self.panel.collide_point(*touch.pos):
            return False
        self.dismiss()
        return True

    def set_body(self, widget, height):
        self.body.clear_widgets()
        self.body.add_widget(widget)
        self.body.height = height
        self.panel.height = dp(48) + height

    def open(self, parent):
        parent.add_widget(self)
        self._scrim_color.rgba = [0, 0, 0, 0]
        self.panel.y = -self.panel.height
        Animation(_scrim_alpha=0.42, d=0.2).start(self) if False else None
        Animation(rgba=[0, 0, 0, 0.42], d=0.2).start(self._scrim_color)
        Animation(y=0, d=0.26, t="out_cubic").start(self.panel)

    def dismiss(self, *a):
        if self.parent is None:
            return
        p = self.parent
        Animation(rgba=[0, 0, 0, 0], d=0.18).start(self._scrim_color)
        anim = Animation(y=-self.panel.height, d=0.22, t="in_cubic")
        anim.bind(on_complete=lambda *x: p.remove_widget(self))
        anim.start(self.panel)


class ContentScroll(ScrollView):
    """带（可选）弹性边界的滚动容器。"""

    def __init__(self, **kw):
        kw.setdefault("bar_width", dp(3))
        kw.setdefault("scroll_type", ["content", "bars"])
        kw.setdefault("do_scroll_x", False)
        super().__init__(**kw)
