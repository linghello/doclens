# -*- coding: utf-8 -*-
"""
从系统自带的 Noto Sans SC（思源黑体，SIL OFL 开源授权）裁剪出一个
「够用且苗条」的中文 TrueType，供 Android / 桌面端 Kivy 使用。

系统字体 17.7 MB，直接打进 APK 太胖；GB2312 覆盖日常 99.9% 的中文场景，
裁剪后约 3 MB 左右，中英混排 + 常用符号全部有字形。

用法：
    python tools/build_font.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SRC = r"C:\Windows\Fonts\NotoSansSC-VF.ttf"
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
OUT = os.path.join(OUT_DIR, "NotoSansSC-Regular.ttf")

# 需要保证有字形的图标 / 标点 —— App 里的图标就是这些字符
ICON_CHARS = "←→↑↓✕✓✖☰⌕☀☾⌂▤▦⚙＋−×÷★☆●○◆▪·…—–「」『』《》〈〉【】⋮↗✎⌫⟳▣▥■□●"

# 额外需要覆盖的码位区间（拉丁、标点、箭头、几何、装饰符号等）
RANGES = [
    (0x0020, 0x007E),  # ASCII
    (0x00A0, 0x00FF),  # Latin-1 补充
    (0x0100, 0x017F),  # Latin Extended-A
    (0x0180, 0x024F),  # Latin Extended-B
    (0x0370, 0x03FF),  # 希腊字母
    (0x2000, 0x206F),  # 通用标点
    (0x2070, 0x209F),  # 上/下标
    (0x20A0, 0x20CF),  # 货币符号
    (0x2100, 0x214F),  # 字母式符号
    (0x2150, 0x218F),  # 数字形式
    (0x2190, 0x21FF),  # 箭头
    (0x2200, 0x22FF),  # 数学运算符
    (0x2300, 0x23FF),  # 杂项技术符号
    (0x2460, 0x24FF),  # 圈码数字
    (0x2500, 0x257F),  # 制表符
    (0x2580, 0x259F),  # 块元素
    (0x25A0, 0x25FF),  # 几何图形
    (0x2600, 0x26FF),  # 杂项符号
    (0x2700, 0x27BF),  # 装饰符号
    (0x27C0, 0x27EF),  # 杂项数学符号
    (0x2E80, 0x2EFF),  # CJK 部首补充
    (0x3000, 0x303F),  # CJK 标点
    (0x3040, 0x309F),  # 平假名
    (0x30A0, 0x30FF),  # 片假名
    (0x31C0, 0x31EF),  # CJK 笔画
    (0x3200, 0x32FF),  # 带圈 CJK 字符
    (0x3300, 0x33FF),  # CJK 兼容
    (0x4DC0, 0x4DFF),  # 易经六十四卦
    (0xA000, 0xA48F),  # 彝文（跳过也行，保留占位）
    (0xFE10, 0xFE1F),  # 竖排标点
    (0xFE30, 0xFE4F),  # CJK 兼容形式
    (0xFE50, 0xFE6F),  # 小变体形式
    (0xFF00, 0xFFEF),  # 全角/半角形式
    (0xFFF0, 0xFFFD),
]


UPM_UNITS = 1000


def gb2312_chars() -> set[str]:
    """GB2312 全字符集：6763 个汉字 + 682 个符号，覆盖日常中文。"""
    chars: set[str] = set()
    for hi in range(0xA1, 0xFF):
        for lo in range(0xA1, 0xFF):
            try:
                chars.add(bytes([hi, lo]).decode("gb2312"))
            except UnicodeDecodeError:
                continue
    return chars


def build_charset() -> set[int]:
    cps: set[int] = set()
    for ch in gb2312_chars():
        cps.add(ord(ch))
    for lo, hi in RANGES:
        cps.update(range(lo, hi + 1))
    for ch in ICON_CHARS:
        cps.add(ord(ch))
    # 去掉代理区与控制字符，避免 fontTools 报错
    cps = {c for c in cps if 0x20 <= c <= 0x10FFFF and not (0xD800 <= c <= 0xDFFF)}
    return cps


def _is_blank(glyf, name) -> bool:
    """字形存在但没有可见轮廓（思源黑体把很多符号声明成了空白字形）。"""
    try:
        g = glyf[name]
    except KeyError:
        return True
    if g.numberOfContours not in (0, None):
        return False
    if g.numberOfContours == 0:
        return True
    # 复合字形：看是否所有组件都指向空白
    return False


def _merge_icons(path):
    """把自绘图标字形合并进已落盘的字体，并补回被 subset 丢掉的空白字符。

    关键坑：
    1. 思源黑体**声明**了 ⌕ ☰ ⚙ ⋮ ✕ 等码位，但对应字形是空的
       （numberOfContours == 0）。不能简单地 ``if cp in cmap: continue``，
       否则这些码位永远画出豆腐块 —— 必须判断字形是否空白，空白则原地重绘。
    2. **空格 (U+0020) 会被 subset 直接删掉**（空轮廓视为无用），结果每个空格
       都渲染成豆腐块，同时断行算法找不到西文词边界、把单词拆成单字符。
       所以这里必须手工补回空白字符（宽度正确、无轮廓）。
    """
    from fontTools.ttLib import TTFont

    font = TTFont(path)
    cmap = font.getBestCmap()
    glyf = font["glyf"]
    hmtx = font["hmtx"]
    order = list(font.getGlyphOrder())
    patched, redrawn = [], []
    _DRAWN_CPS: set[int] = set()
    _SPACE_CPS: set[int] = set()

    # ── 1. 补回空白字符（无轮廓，只有 advance width） ──
    # 值 = 相对 em 的宽度，和中文字体常见的空白设置一致
    SPACES = {
        0x0020: 260,   # 普通空格
        0x00A0: 260,   # 不换行空格
        0x2002: 500,   # en space
        0x2003: 1000,  # em space
        0x2009: 180,   # thin space
        0x3000: 1000,  # 全角空格
    }
    fixed_spaces = []
    for cp, adv in SPACES.items():
        _SPACE_CPS.add(cp)
        existing = cmap.get(cp)
        if existing:
            # 已存在：修一下 advance，别让它变成 0 宽
            try:
                hmtx.metrics[existing] = (adv, 0)
            except KeyError:
                pass
            continue
        name = "space%04X" % cp
        try:
            from fontTools.ttLib.tables._g_l_y_f import Glyph
            g = Glyph()
            g.numberOfContours = 0
            glyf.glyphs[name] = g
            if name not in glyf.glyphOrder:
                glyf.glyphOrder.append(name)
        except Exception as exc:
            print(f"[!] 补空白字符 {hex(cp)} 失败: {exc}")
            continue
        hmtx.metrics[name] = (adv, 0)
        for table in font["cmap"].tables:
            if table.isUnicode():
                table.cmap[cp] = name
        fixed_spaces.append(chr(cp))

    try:
        from patch_icons import GLYPHS, _IconPen
        from fontTools.pens.ttGlyphPen import TTGlyphPen
    except Exception as exc:
        print(f"[!] 无法加载图标绘制器: {exc}")
        font.close()
        return

    for ch, drawer in GLYPHS.items():
        cp = ord(ch)
        old = cmap.get(cp)
        _DRAWN_CPS.add(cp)

        if old is not None and not _is_blank(glyf, old):
            continue  # 字体自带真实字形，别覆盖

        # 绘制到临时 pen，再决定是新建还是替换
        pen = TTGlyphPen(None)
        drawer(_IconPen(pen))
        glyph = pen.glyph()

        if old is not None:
            # 原地替换空白字形，保留原有 cmap 映射（图标专属字形）
            glyph.recalcBounds(glyf)
            glyf.glyphs[old] = glyph
            redrawn.append(ch)
        else:
            name = "icon%04X" % cp
            glyph.recalcBounds(glyf)
            glyf.glyphs[name] = glyph
            glyf.glyphOrder.append(name)
            hmtx.metrics[name] = (UPM_UNITS, 60)
            for table in font["cmap"].tables:
                if table.isUnicode():
                    table.cmap[cp] = name
            patched.append(ch)

    # 清掉「有 cmap 映射但字形空白」的顽固条目，避免渲染器挑到空白字形
    for table in font["cmap"].tables:
        if not table.isUnicode():
            continue
        for cp in list(table.cmap.keys()):
            if cp in _DRAWN_CPS or cp in _SPACE_CPS:
                continue
            try:
                if _is_blank(glyf, table.cmap[cp]):
                    del table.cmap[cp]
            except KeyError:
                del table.cmap[cp]

    if not patched and not redrawn and not fixed_spaces:
        font.close()
        print("[*] 图标 / 空白字形已齐备，无需补入")
        return

    # 坑：不能调 font.setGlyphOrder() —— 它会用旧顺序重建 glyf.glyphOrder，
    # 把刚 append 进去的自绘字形直接丢回原点（字形静默消失）。
    # 正确做法：只把 glyf.glyphOrder 与 maxp 对齐。
    order = list(glyf.glyphOrder)
    font.glyphOrder = order
    font["maxp"].numGlyphs = len(order)
    if "post" in font and hasattr(font["post"], "glyphOrder"):
        font["post"].glyphOrder = order
    font.save(path)
    font.close()
    if fixed_spaces:
        print(f"[*] 补回空白字符: {' '.join(repr(c) for c in fixed_spaces)}")
    if patched:
        print(f"[*] 新增自绘图标字形: {''.join(patched)}")
    if redrawn:
        print(f"[*] 重绘空白图标字形: {''.join(redrawn)}")


def main() -> int:
    try:
        from fontTools.ttLib import TTFont
        from fontTools import subset
    except ImportError:
        print("[!] 缺少 fontTools，请先: pip install fonttools brotli")
        return 2

    if not os.path.exists(SRC):
        print(f"[!] 找不到源字体: {SRC}")
        return 2

    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"[*] 源字体: {SRC}  ({os.path.getsize(SRC)/1048576:.1f} MB)")

    font = TTFont(SRC, lazy=False)
    cmap = set(font.getBestCmap().keys())
    want = build_charset()
    missing = sorted(c for c in want if c not in cmap)
    if missing:
        preview = "".join(chr(c) for c in missing[:40] if c >= 0x20)
        print(f"[!] 源字体缺 {len(missing)} 个码位（将忽略）: {preview!r}")

    # 可变字体：先实例化到 Regular(400)，让渲染结果稳定
    try:
        from fontTools.varLib import instancer

        if "fvar" in font:
            print("[*] 检测到可变字体，实例化 wght=400 ...")
            font = instancer.instantiateVariableFont(font, {"wght": 400}, inplace=False, updateFontNames=False)
    except Exception as exc:  # pragma: no cover - 失败也不致命
        print(f"[!] 实例化失败（改用默认实例）: {exc}")

    options = subset.Options()
    options.drop_tables += ["DSIG"]
    options.name_IDs = ["*"]
    options.name_legacy = True
    options.name_languages = ["*"]
    options.notdef_outline = True
    options.recalc_bounds = True
    options.layout_features = ["*"]  # 保留 GSUB/GPOS，中文竖排/标点挤压才正常
    options.desubroutinize = True

    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=[c for c in want if c in cmap])
    subsetter.subset(font)

    # 思源黑体没有 ☰ ⌕ ⚙ ⋮ ✕ 这些图标，用程序自绘的几何字形补进去。
    # 注意：必须先把字体落盘，再重新打开来改字形表 ——
    # 直接在 subset 后的内存对象上插字形，glyf 内部顺序会不一致。
    font.flavor = None
    font.save(OUT)
    font.close()

    try:
        _merge_icons(OUT)
    except Exception as exc:
        print(f"[!] 图标补入失败（App 会退回到文字按钮）: {exc}")

    size_mb = os.path.getsize(OUT) / 1048576
    print(f"[✓] 输出: {OUT}  ({size_mb:.2f} MB, {len(want - set(missing))} 个码位)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
