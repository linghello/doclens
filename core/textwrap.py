# -*- coding: utf-8 -*-
"""中英混排断行。

Kivy 自带的排版对没有空格的中文不够友好，这里自己算：
按「CJK 单字 / 西文单词 / 空格」切成 token，累加宽度贪心断行，
顺带做了中文避头尾（行首不放句号、逗号、右引号…）。

难点在于文本里混着 Kivy 的 markup 标签（[b]、[color=#xxx]），
直接插 \\n 可能把标签劈成两半 —— 所以断行时会先把标签栈关掉再开。
"""

import re

from kivy.core.text import Label as CoreLabel

TAG_RE = re.compile(r"\[/?[a-zA-Z][^\]]*\]")

# 不能出现在行首的字符（避头尾）
NO_LINE_START = set("，。、；：？！）」』】〉》”’%·…~!?,.:;)]}¢\"'")
# 不能出现在行尾的字符
NO_LINE_END = set("（「『【〈《“‘([{")


def is_cjk(ch):
    o = ord(ch)
    return (
        0x3040 <= o <= 0x30FF      # 假名
        or 0x3400 <= o <= 0x4DBF   # 扩展 A
        or 0x4E00 <= o <= 0x9FFF   # 基本区
        or 0xF900 <= o <= 0xFAFF   # 兼容
        or 0x3000 <= o <= 0x303F   # CJK 标点
        or 0xFF00 <= o <= 0xFFEF   # 全角
    )


def split_markup(markup):
    """把 markup 文本切成 [(可见文本, 标签栈)]，标签栈是该片段所处的样式。"""
    out = []
    stack = []
    buf = []
    i = 0
    n = len(markup)
    while i < n:
        m = TAG_RE.match(markup, i)
        if m:
            tag = m.group(0)
            if buf:
                out.append(("".join(buf), tuple(stack)))
                buf = []
            inner = tag[1:-1]
            if inner.startswith("/"):
                name = inner[1:].split("=")[0]
                for k in range(len(stack) - 1, -1, -1):
                    if stack[k].split("=")[0] == name:
                        del stack[k]
                        break
            else:
                stack.append(inner)
            i = m.end()
        else:
            buf.append(markup[i])
            i += 1
    if buf:
        out.append(("".join(buf), tuple(stack)))
    return out


def _tokenize(text):
    """把纯文本切成可断行的单元。"""
    tokens = []
    buf = ""
    buf_is_word = False
    for ch in text:
        if ch.isspace():
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
            buf_is_word = False
            continue
        if is_cjk(ch):
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
            buf_is_word = False
            continue
        # 西文：连成单词
        if buf_is_word:
            buf += ch
        else:
            if buf:
                tokens.append(buf)
            buf = ch
            buf_is_word = True
    if buf:
        tokens.append(buf)
    return tokens


def _open_tags(stack):
    return "".join("[%s]" % s for s in stack)


def _close_tags(stack):
    return "".join("[/%s]" % s.split("=")[0] for s in reversed(stack))


class Measurer:
    """字体宽度测量器（带缓存，按字号重建）。

    坑：``CoreLabel.get_extents()`` 在文本提供器还没就绪时会返回 0 或负数
    （例如 App 启动早期 / 字体刚注册完还没 refresh）。这会让断行算法以为
    每个字都「零宽度」，于是整段挤成一行 —— 阅读器里表现为文字被压成一条
    细线。所以这里做了兜底：测不出来就按字号估算。
    """

    def __init__(self, font_name, font_size):
        self._lbl = CoreLabel(font_name=font_name, font_size=font_size)
        try:
            self._lbl.refresh()
        except Exception:
            pass
        self._cache = {}
        self.font_name = font_name
        self.font_size = font_size

    def _est(self, s):
        """估算宽度：CJK 按 1.0em，西文按 0.55em。"""
        w = 0.0
        for ch in s:
            if ch == "\n":
                continue
            w += self.font_size * (1.0 if is_cjk(ch) else 0.55)
        return w

    def width(self, s):
        v = self._cache.get(s)
        if v is None:
            v = 0.0
            try:
                v = float(self._lbl.get_extents(s)[0])
            except Exception:
                v = 0.0
            # 明显不可信（0 或异常小）时用估算值兜底
            if v <= 1.0:
                v = self._est(s)
            self._cache[s] = v
        return v


def wrap_markup(markup, measurer, max_width):
    """给一段 markup 文本插入换行符，使其在 max_width 内正确折行。"""
    if max_width <= 8:
        return markup
    tokens = []
    for text, stack in split_markup(markup):
        for piece in _tokenize(text):
            full = _open_tags(stack) + piece + _close_tags(stack) if stack else piece
            # 只量「可见文字」的宽度！
            # 坑：以前这里量的是 ``full``（带 [b][s]…[/s][/b] 标签的整串），
            # 而 CoreLabel.get_extents 遇到标记串会返回一个恒定值（实测无论
            # 内容是「不上」还是「传、」都返回 200），于是每个 token 都「超宽」，
            # 贪心断行被迫每个 token 起一行 —— 屏幕上就是加粗段一个字一行。
            # 标签本身不占宽度（=0），所以只要直接量 piece 即可。
            tokens.append((piece, stack, full, measurer.width(piece)))
    if not tokens:
        return markup

    rows = []
    row = []
    row_w = 0.0
    i = 0
    n = len(tokens)
    while i < n:
        piece, stack, full, w = tokens[i]
        if w > max_width and len(piece) > 1 and not piece.isspace():
            # 超长西文单词：按字符硬切
            for ch in piece:
                f = _open_tags(stack) + ch + _close_tags(stack) if stack else ch
                cw = measurer.width(ch)
                if row_w + cw > max_width and row:
                    rows.append(row)
                    row, row_w = [], 0.0
                row.append((ch, stack, f, cw))
                row_w += cw
            i += 1
            continue
        if row and row_w + w > max_width:
            # 避头尾：句号/逗号等不能落到下一行行首，把它塞回本行
            if piece in NO_LINE_START:
                row.append((piece, stack, full, w))
                rows.append(row)
                row, row_w = [], 0.0
                i += 1
                continue
            rows.append(row)
            row, row_w = [], 0.0
            if piece.isspace():
                i += 1
                continue
        row.append((piece, stack, full, w))
        row_w += w
        i += 1
    if row:
        rows.append(row)

    parts = []
    cur = ()
    for ri, r in enumerate(rows):
        if parts:
            # 上一行收尾：关掉标签再换行
            if cur:
                parts.append(_close_tags(cur))
                cur = ()
            parts.append("\n")
        for piece, stack, full, w in r:
            if stack != cur:
                if cur:
                    parts.append(_close_tags(cur))
                if stack:
                    parts.append(_open_tags(stack))
                cur = stack
            parts.append(piece)
        # 行尾若是禁止字符（如左引号），与下一行首字符交换太麻烦，直接放行
    if cur:
        parts.append(_close_tags(cur))
    return "".join(parts)


def plain_width(text, measurer):
    return measurer.width(text)
