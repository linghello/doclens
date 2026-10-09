# -*- coding: utf-8 -*-
"""把图标字形合并进中文子集字体。

思源黑体（NotoSansSC）缺少一批我们用作 UI 图标的符号（☰ ⌕ ⚙ ⋮ ✕ …），
Windows 的 Segoe UI Symbol 里有，但它是微软专有字体，不能打进 APK。

这里采用 **纯几何自绘** 的方案：直接在字体里用直线/圆弧指令
（TTGlyph pen）描出这些图标。笔画是程序生成的，不涉及任何第三方字体版权。
这样 APK 里只有一个字体文件，Android 上不会缺字形、也不会出现方块。

用法：  python tools/patch_icons.py
"""

from __future__ import annotations

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = os.path.join(BASE, "assets", "fonts", "NotoSansSC-Regular.ttf")

UPM = 1000          # 源字体 unitsPerEm 实测值
INK = 640           # 图标绘制区大小
BOX = (UPM - INK) // 2
STROKE = 66         # 默认笔画粗细


# ── 绘制助手 ────────────────────────────────────────────
class _IconPen:
    """绘制器统一入口，把绘制指令转发给底层 TTGlyphPen。

    坑：以前这里 ``self._p = Pen(pen)``，而 ``Pen.__init__`` 又自己新建了一个
    ``TTGlyphPen``，导致所有笔画都画进了那个临时 pen，外部拿到的仍是空字形
    （症状：图标全是豆腐块，glyph.numberOfContours == 0）。
    现在直接把外部 pen 交给绘制助手。
    """

    def __init__(self, pen):
        self._p = Pen(pen)

    def __getattr__(self, item):
        return getattr(self._p, item)

    def glyph(self):
        return self._p._pen.glyph()


class Pen:
    def __init__(self, glyph):
        from fontTools.pens.ttGlyphPen import TTGlyphPen

        # 复用外部传入的 pen：外部要靠 pen.glyph() 取回结果
        self._pen = glyph if isinstance(glyph, TTGlyphPen) else TTGlyphPen(None)
        self.glyph = glyph

    def close(self):
        # 把 contour 收尾（TTGlyphPen 需要显式 closePath）
        return self._pen.glyph()

    # 基本图形
    def rect(self, x, y, w, h):
        self._poly([(x, y), (x + w, y), (x + w, y + h), (x, y + h)])

    def rrect(self, x, y, w, h, r):
        r = min(r, w / 2, h / 2)
        self._seg([
            ("m", x + r, y), ("l", x + w - r, y),
            ("q", x + w, y, x + w, y + r), ("l", x + w, y + h - r),
            ("q", x + w, y + h, x + w - r, y + h), ("l", x + r, y + h),
            ("q", x, y + h, x, y + h - r), ("l", x, y + r),
            ("q", x, y, x + r, y),
        ])

    def bar(self, x, y, w, h):
        self.rect(x, y, w, h)

    def hbar(self, x, y, w, t=STROKE):
        self.rect(x, y, w, t)

    def vbar(self, x, y, h, t=STROKE):
        self.rect(x, y, t, h)

    def _poly(self, pts):
        self._pen.moveTo(pts[0])
        for p in pts[1:]:
            self._pen.lineTo(p)
        self._pen.closePath()

    def _seg(self, cmds):
        """用直线逼近圆弧，避免依赖 qCurveTo 的 off-curve 处理。"""
        pts = []
        cur = None
        for c in cmds:
            op = c[0]
            if op == "m":
                if pts:
                    self._poly(pts)
                pts = [(c[1], c[2])]
                cur = (c[1], c[2])
            elif op == "l":
                pts.append((c[1], c[2]))
                cur = (c[1], c[2])
            elif op == "q":
                cx, cy, ex, ey = c[1], c[2], c[3], c[4]
                x0, y0 = cur
                for i in range(1, 7):
                    t = i / 6.0
                    x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * ex
                    y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * ey
                    pts.append((x, y))
                cur = (ex, ey)
        if pts:
            self._poly(pts)

    def arc(self, cx, cy, r, start, end, steps=40, closed=False):
        import math
        pts = []
        for i in range(steps + 1):
            a = math.radians(start + (end - start) * i / steps)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        if closed:
            self._poly(pts)
        else:
            # 开放弧线用一圈细环近似，换成小矩形带太丑，改用两端闭合的环带
            self._poly(pts)

    def ring(self, cx, cy, r_out, r_in, start=0, end=360, steps=64):
        """圆环（甜甜圈），可只画一段弧。"""
        import math
        outer, inner = [], []
        for i in range(steps + 1):
            a = math.radians(start + (end - start) * i / steps)
            outer.append((cx + r_out * math.cos(a), cy + r_out * math.sin(a)))
            inner.append((cx + r_in * math.cos(a), cy + r_in * math.sin(a)))
        self._poly(outer + list(reversed(inner)))

    def line(self, x1, y1, x2, y2, t=STROKE):
        """任意方向的粗线段。"""
        import math
        dx, dy = x2 - x1, y2 - y1
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln * t / 2, dx / ln * t / 2
        self._poly([(x1 + nx, y1 + ny), (x2 + nx, y2 + ny),
                    (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)])


# ── 各图标的画法 ────────────────────────────────────────
def draw_x5655(p):
    """✕ 关闭 / 删除（交叉线）"""
    p.line(BOX, BOX, BOX + INK, BOX + INK)
    p.line(BOX + INK, BOX, BOX, BOX + INK)


def draw_check(p):
    """✓ 完成"""
    p.line(BOX + INK * 0.06, BOX + INK * 0.46,
           BOX + INK * 0.34, BOX + INK * 0.14)
    p.line(BOX + INK * 0.34, BOX + INK * 0.14,
           BOX + INK * 0.96, BOX + INK * 0.86)


def draw_menu(p):
    """☰ 菜单 / 设置入口"""
    for i in range(3):
        p.hbar(BOX + INK * 0.08, BOX + INK * (0.24 + 0.26 * i), INK * 0.84, 74)


def draw_search(p):
    """⌕ 搜索（放大镜）"""
    r = INK * 0.30
    cx, cy = BOX + INK * 0.44, BOX + INK * 0.62
    p.ring(cx, cy, r, r - 74)
    p.line(cx + r * 0.72, cy - r * 0.72,
           BOX + INK * 0.94, BOX + INK * 0.12, 84)


def draw_x2662(p):
    """☾ 深色模式（月牙，用两段圆弧围成）"""
    import math
    outer_r, inner_r = INK * 0.48, INK * 0.60
    cx, cy = BOX + INK * 0.5, BOX + INK * 0.5
    steps = 48
    pts = []
    for i in range(steps + 1):
        a = math.radians(118 + (296 - 118) * i / steps)
        pts.append((cx + outer_r * math.cos(a), cy + outer_r * math.sin(a)))
    ox, oy = cx + INK * 0.30, cy + INK * 0.10
    for i in range(steps + 1):
        a = math.radians(300 - (300 - 128) * i / steps)
        pts.append((ox + inner_r * math.cos(a), oy + inner_r * math.sin(a)))
    p._poly(pts)


def draw_home(p):
    """⌂ 首页（屋顶 + 屋身）"""
    top = BOX + INK * 0.94
    mid = BOX + INK * 0.46
    left, right = BOX + INK * 0.04, BOX + INK * 0.96
    p._poly([(left, mid), (BOX + INK * 0.5, top), (right, mid),
             (right - 80, mid), (BOX + INK * 0.5, top - 96), (left + 80, mid)])
    p._poly([(left + INK * 0.18, BOX + INK * 0.02),
             (right - INK * 0.18, BOX + INK * 0.02),
             (right - INK * 0.18, mid - 40),
             (left + INK * 0.18, mid - 40)])


def draw_gear(p):
    """⚙ 设置（齿轮：梯形外齿 + 中孔）

    坑：以前每个齿只用 4 个采样点，齿顶/齿根之间是直连的斜线，
    渲染出来像「爆炸星芒」而不是齿轮。这里按真实齿轮轮廓采样：
    每个齿是一段圆弧（齿顶）+ 一段圆弧（齿根）+ 两侧过渡。
    中孔用反向绕行的内圆，靠非零环绕规则形成镂空。
    """
    import math
    cx = cy = BOX + INK * 0.5
    r_tip = INK * 0.50       # 齿顶半径
    r_root = INK * 0.36      # 齿根半径
    teeth = 8
    gap_ratio = 0.52         # 齿顶占齿距的比例

    pts = []
    per = 360.0 / teeth
    for t in range(teeth):
        base = t * per
        a0 = base - per * gap_ratio / 2
        a1 = base + per * gap_ratio / 2
        for i in range(5):          # 齿顶圆弧
            a = math.radians(a0 + (a1 - a0) * i / 4)
            pts.append((cx + r_tip * math.cos(a), cy + r_tip * math.sin(a)))
        b0, b1 = a1, base + per - per * gap_ratio / 2
        for i in range(1, 5):       # 齿根圆弧
            a = math.radians(b0 + (b1 - b0) * i / 4)
            pts.append((cx + r_root * math.cos(a), cy + r_root * math.sin(a)))

    # 中孔：反向绕行（顺时针），与外轮廓相减
    r_hole = INK * 0.16
    hole = []
    for i in range(33):
        a = math.radians(-360.0 * i / 32)
        hole.append((cx + r_hole * math.cos(a), cy + r_hole * math.sin(a)))
    p._poly(pts + hole)


def draw_dots_v(p):
    """⋮ 更多（竖排三点）"""
    r = INK * 0.085
    for i in range(3):
        cy = BOX + INK * (0.76 - 0.26 * i)
        p.ring(BOX + INK * 0.5, cy, r, 0, steps=16)


def draw_pen(p):
    """✎ 编辑 / 重命名（斜杆笔）"""
    p._poly([
        (BOX + INK * 0.02, BOX + INK * 0.02),
        (BOX + INK * 0.22, BOX + INK * 0.04),
        (BOX + INK * 0.90, BOX + INK * 0.74),
        (BOX + INK * 0.72, BOX + INK * 0.94),
        (BOX + INK * 0.04, BOX + INK * 0.24),
    ])
    p._poly([
        (BOX + INK * 0.24, BOX + INK * 0.30),
        (BOX + INK * 0.78, BOX + INK * 0.84),
        (BOX + INK * 0.70, BOX + INK * 0.92),
        (BOX + INK * 0.16, BOX + INK * 0.38),
    ])


def draw_backspace(p):
    """⌫ 返回 / 清除"""
    p._poly([
        (BOX + INK * 0.02, BOX + INK * 0.5),
        (BOX + INK * 0.30, BOX + INK * 0.92),
        (BOX + INK * 0.96, BOX + INK * 0.92),
        (BOX + INK * 0.96, BOX + INK * 0.08),
        (BOX + INK * 0.30, BOX + INK * 0.08),
    ])
    p._poly([
        (BOX + INK * 0.20, BOX + INK * 0.5),
        (BOX + INK * 0.38, BOX + INK * 0.78),
        (BOX + INK * 0.88, BOX + INK * 0.78),
        (BOX + INK * 0.88, BOX + INK * 0.22),
        (BOX + INK * 0.38, BOX + INK * 0.22),
    ])


def draw_refresh(p):
    """⟳ 刷新 / 重新阅读"""
    p.ring(BOX + INK * 0.5, BOX + INK * 0.5, INK * 0.46, INK * 0.46 - 76,
           start=-40, end=250)
    p.line(BOX + INK * 0.72, BOX + INK * 0.14,
           BOX + INK * 0.96, BOX + INK * 0.20, 84)
    p.line(BOX + INK * 0.72, BOX + INK * 0.14,
           BOX + INK * 0.66, BOX + INK * 0.40, 84)


GLYPHS = {
    "✕": draw_x5655,
    "✓": draw_check,
    "☰": draw_menu,
    "⌕": draw_search,
    "☾": draw_x2662,
    "⌂": draw_home,
    "⚙": draw_gear,
    "⋮": draw_dots_v,
    "✎": draw_pen,
    "⌫": draw_backspace,
    "⟳": draw_refresh,
}


def main() -> int:
    from fontTools.ttLib import TTFont, newTable

    if not os.path.isfile(FONT):
        print(f"[!] 找不到字体 {FONT}，先跑 tools/build_font.py")
        return 2

    font = TTFont(FONT)
    cmap = font.getBestCmap()
    glyf = font["glyf"]
    hmtx = font["hmtx"]
    order = font.getGlyphOrder()
    upm = font["head"].unitsPerEm
    print(f"[*] unitsPerEm = {upm}, 现有字形 {len(order)} 个")

    added = []
    for ch, drawer in GLYPHS.items():
        cp = ord(ch)
        if cp in cmap:
            added.append(ch)
            continue
        name = "uni%04X" % cp
        from fontTools.pens.ttGlyphPen import TTGlyphPen

        pen = TTGlyphPen(None)
        p = Pen(pen)
        drawer(p)
        glyph = pen.glyph()
        glyph.recalcBounds(glyf)
        glyf[name] = glyph
        hmtx[name] = (UPM, 60)
        cmap[cp] = name
        order.append(name)
        added.append(ch)

    font.setGlyphOrder(order)
    font.glyphOrder = order

    # 写回所有 Unicode cmap 子表
    for table in font["cmap"].tables:
        if table.isUnicode():
            table.cmap = cmap
    # 更新 maxp
    if "maxp" in font:
        font["maxp"].numGlyphs = len(order)

    font.save(FONT)
    size = os.path.getsize(FONT) / 1048576
    print(f"[✓] 已补入 {len(added)} 个图标字形: {''.join(added)}")
    print(f"[✓] {FONT}  ({size:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
