# -*- coding: utf-8 -*-
"""设计系统：配色、圆角、间距、字号。

整个 App 只有两套色板（浅色 / 深色），所有控件从这里取色，
换肤时重建界面即可，不需要给每个控件写一堆 bind。
"""

from kivy.metrics import dp
from kivy.utils import get_color_from_hex

LIGHT = {
    "bg": "#F2F4F9",
    "surface": "#FFFFFF",
    "surface2": "#F7F8FC",
    "surface3": "#EEF1F8",
    "text": "#151A26",
    "text2": "#5B6478",
    "muted": "#9AA2B5",
    "primary": "#4F46E5",
    "primary2": "#6D64F0",
    "primary_soft": "#EDEDFE",
    "on_primary": "#FFFFFF",
    "accent": "#EC4899",
    "accent_soft": "#FDECF5",
    "ok": "#10B981",
    "warn": "#F59E0B",
    "divider": "#E7EAF2",
    "code_bg": "#F3F5FA",
    "code_fg": "#C0398B",
    "quote_bar": "#C9CFFB",
    "highlight": "#FFE58A",
    "shadow": "#2A3358",
    "scrim": "#0B1020",
    "card_border": "#ECEFF7",
}

DARK = {
    "bg": "#0C0F16",
    "surface": "#151A24",
    "surface2": "#1A2029",
    "surface3": "#222935",
    "text": "#E8EBF3",
    "text2": "#A6AEc2",
    "muted": "#6C758A",
    "primary": "#8B9BFF",
    "primary2": "#A5B1FF",
    "primary_soft": "#212845",
    "on_primary": "#0C0F16",
    "accent": "#FF7AB8",
    "accent_soft": "#2C1F2A",
    "ok": "#34D399",
    "warn": "#FBBF24",
    "divider": "#232A37",
    "code_bg": "#1B212C",
    "code_fg": "#FF9BCB",
    "quote_bar": "#3A4260",
    "highlight": "#5A4E1F",
    "shadow": "#000000",
    "scrim": "#000000",
    "card_border": "#202632",
}

PALETTES = {"light": LIGHT, "dark": DARK}

# ── 尺寸令牌 ────────────────────────────────────────────
R_SM = dp(10)
R_MD = dp(16)
R_LG = dp(22)
R_XL = dp(28)
PAD = dp(18)          # 页面左右留白
GAP = dp(12)          # 卡片间距
BAR_H = dp(56)        # 顶栏高度

READER_FONT_MIN = 13
READER_FONT_MAX = 27


class Theme:
    """一套色板 + 便捷取色（带缓存）。"""

    def __init__(self, name="light"):
        self.set(name)

    def set(self, name):
        self.name = name if name in PALETTES else "light"
        self.p = PALETTES[self.name]
        self.is_dark = self.name == "dark"
        self._cache = {}

    @property
    def other(self):
        return "dark" if self.name == "light" else "light"

    def hex(self, key):
        return self.p[key]

    def c(self, key, alpha=1.0):
        """返回 rgba 列表，可直接喂给 Kivy 的 Color 指令。"""
        ck = (key, alpha)
        v = self._cache.get(ck)
        if v is None:
            r, g, b, a = get_color_from_hex(self.p[key])
            v = [r, g, b, a * alpha]
            self._cache[ck] = v
        return v

    def shadow_rgba(self, level=1):
        base = 0.05 * level
        r, g, b, _ = get_color_from_hex(self.p["shadow"])
        return [r, g, b, base]
