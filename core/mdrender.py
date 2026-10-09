# -*- coding: utf-8 -*-
"""把 Markdown 编译成 Kivy 的 markup 行。

设计要点：
1. 自己写解析器，输出的是「控件指令」而不是 HTML —— 每一行是一个 dict，
   阅读器按指令创建 Label / 卡片 / 分隔线。零第三方依赖，Android 打包不会翻车。
2. 因为 Kivy 的 markup 里 `[` 有特殊含义，所有正文里的 `[` / `&` 都会被
   转义成 `&bl;` / `&amp;`（Kivy 官方支持的实体），显示时再还原。
3. 中文断行由 core/textwrap.py 负责，这里只保证给它的 markup 标签是配平的。
"""

import re

from kivy.metrics import dp, sp
from kivy.utils import get_color_from_hex

# 行内代码 / 代码块的固定配色（两套主题都好看）
CODE_FG = "#D6409F"
# ==高亮== 的前景色（Kivy markup 不支持文字底色，用暖橙近似）
MARK_FG = "#C2410C"
CODE_BG = "#F1F3F9"
CODE_BG_DARK = "#1E2430"

BLOCK_COMMANDS = [
    "h1", "h2", "h3", "h4", "para", "bullet", "number", "quote", "hr", "code",
    "table", "image", "blank", "task",
]


def escape(s):
    """把用户文本变成可安全放进 Kivy markup 的字符串。"""
    return s.replace("&", "&amp;").replace("[", "&bl;").replace("]", "&br;")


def unescape(s):
    return s.replace("&bl;", "[").replace("&br;", "]").replace("&amp;", "&")


_INLINE = [
    # 图片：![alt](src)
    ("img", re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")),
    # 链接：[text](url)
    ("link", re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")),
    # 行内代码
    ("code", re.compile(r"`([^`]+)`")),
    # 粗斜体 / 粗体 / 斜体
    ("bi", re.compile(r"\*\*\*([^*]+)\*\*\*")),
    ("bi", re.compile(r"___([^_]+)___")),
    ("b", re.compile(r"\*\*([^*]+)\*\*")),
    ("b", re.compile(r"__([^_]+)__")),
    ("i", re.compile(r"\*([^*\n]+)\*")),
    ("i", re.compile(r"(?<![A-Za-z0-9_])_([^_\n]+)_(?![A-Za-z0-9_])")),
    # 删除线
    ("s", re.compile(r"~~([^~]+)~~")),
    # 高亮（非标准，但很多人用）
    ("mark", re.compile(r"==([^=]+)==")),
]


def _scan_tokens(text):
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in "\\`*_{}[]()#+-.!>~=":
            tokens.append(("text", text[i + 1]))
            i += 2
            continue
        if ch == "`":
            end = text.find("`", i + 1)
            if end != -1:
                tokens.append(("code", text[i + 1:end]))
                i = end + 1
                continue
        if ch in "*_" and text.startswith(ch * 2, i):
            n_run = 2
            if text.startswith(ch * 3, i):
                n_run = 3
            close = text.find(ch * n_run, i + n_run)
            if close > i + n_run:
                kind = {2: "b", 3: "bi"}[n_run]
                tokens.append(("open_" + kind, None))
                tokens.append(("open_inner", text[i + n_run:close]))
                tokens.append(("close_inner", None))
                tokens.append(("close_" + kind, None))
                i = close + n_run
                continue
        # 单星/单下划线 → 斜体。
        # 坑：以前只认 2/3 连写，``*斜体*`` 会原样漏出去（屏幕上带着星号）。
        # 下划线要额外排除「词内下划线」（如 some_var_name），否则会吃掉半个标识符。
        if ch == "*" or (ch == "_" and (i == 0 or not text[i - 1].isalnum())):
            close = text.find(ch, i + 1)
            if close > i + 1 and "\n" not in text[i + 1:close]:
                if ch != "_" or close + 1 >= n or not text[close + 1].isalnum():
                    tokens.append(("open_i", None))
                    tokens.append(("open_inner", text[i + 1:close]))
                    tokens.append(("close_inner", None))
                    tokens.append(("close_i", None))
                    i = close + 1
                    continue
        if ch == "~" and text.startswith("~~", i):
            close = text.find("~~", i + 2)
            if close > i + 2:
                tokens.append(("open_s", None))
                tokens.append(("open_inner", text[i + 2:close]))
                tokens.append(("close_inner", None))
                tokens.append(("close_s", None))
                i = close + 2
                continue
        if ch == "=" and text.startswith("==", i):
            close = text.find("==", i + 2)
            if close > i + 2:
                tokens.append(("open_mark", None))
                tokens.append(("open_inner", text[i + 2:close]))
                tokens.append(("close_inner", None))
                tokens.append(("close_mark", None))
                i = close + 2
                continue
        tokens.append(("text", ch))
        i += 1
    return tokens


def render_inline(text, base_size, text_color, link_color, code_fg=None):
    """把一行 markdown 行内语法编译成 Kivy markup 字符串。"""
    code_fg = code_fg or CODE_FG
    text = text.replace("\t", "    ")
    # 先处理图片/链接（它们内部禁止嵌套其它语法）
    out = []
    pos = 0

    link_re = _INLINE[1][1]
    img_re = _INLINE[0][1]

    combined = re.compile(
        r"!\[[^\]]*\]\([^)\s]+(?:\s+\"[^\"]*\")?\)"
        r"|\[[^\]]+\]\([^)\s]+(?:\s+\"[^\"]*\")?\)"
    )

    for m in combined.finditer(text):
        out.append(_render_plain(text[pos:m.start()], base_size, text_color,
                                 link_color, code_fg))
        chunk = m.group(0)
        im = img_re.fullmatch(chunk)
        if im:
            alt = escape(im.group(1) or "图片")
            out.append("[color=%s][size=%d]▤ %s[/size][/color]" %
                       (link_color, int(base_size * 0.96), alt))
        else:
            lm = link_re.fullmatch(chunk)
            label = _render_plain(lm.group(1), base_size, text_color, link_color, code_fg)
            out.append("[u][color=%s]%s[/color][/u]" % (link_color, label))
        pos = m.end()
    out.append(_render_plain(text[pos:], base_size, text_color, link_color, code_fg))
    return "".join(out)


def _render_plain(text, base_size, text_color, link_color, code_fg):
    parts = []
    bold = False
    ital = False
    strike = False
    mark = False
    for kind, payload in _scan_tokens(text):
        if kind == "text":
            parts.append(escape(payload))
        elif kind == "code":
            parts.append("[font=RobotoMono][color=%s]%s[/color][/font]"
                         % (code_fg, escape(payload)))
        elif kind in ("open_b", "open_bi"):
            parts.append("[b]")
            bold = True
            if kind == "open_bi":
                parts.append("[i]")
                ital = True
        elif kind == "close_b":
            parts.append("[/b]")
            bold = False
        elif kind == "close_bi":
            parts.append("[/b][/i]")
            bold = ital = False
        elif kind == "open_i":
            parts.append("[i]")
            ital = True
        elif kind == "close_i":
            parts.append("[/i]")
            ital = False
        elif kind == "open_s":
            parts.append("[color=#8A93A6]")
            strike = True
        elif kind == "close_s":
            parts.append("[/color]")
            strike = False
        elif kind == "open_mark":
            # 高亮：黄色底 + 深色字（Kivy 没有 background 标签，
            # 用前景色近似；深/浅主题下都还能看清）。
            parts.append("[color=%s]" % MARK_FG)
            mark = True
        elif kind == "close_mark":
            parts.append("[/color]")
            mark = False
        elif kind == "open_inner":
            # ``payload`` 就是被 ** / __ / ~~ 包裹的文字本体，
            # 必须原样写出来！
            # 坑：这里以前只写了一个 ``[s]``，把 payload 整个丢了 ——
            # 于是 ``**很多字**`` 渲染成 ``[b][s][/s][/b]``，
            # 屏幕上只剩两个孤零零的星号，加粗文字全部消失。
            parts.append("[s]%s" % escape(payload))
        elif kind == "close_inner":
            parts.append("[/s]")
    return "".join(parts)


# ── 块级解析 ────────────────────────────────────────────
LIST_RE = re.compile(r"^(\s*)([-*+]|\d{1,3}[.)])\s+(.*)$")
TASK_RE = re.compile(r"^\[([ xX])\]\s+(.*)$")
HR_RE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
HEAD_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
FENCE_RE = re.compile(r"^\s{0,3}(```+|~~~+)\s*([\w#+.-]*)\s*$")
QUOTE_RE = re.compile(r"^\s{0,3}>\s?(.*)$")


def _split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    cells = []
    buf = ""
    i = 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line) and line[i + 1] == "|":
            buf += "|"
            i += 2
            continue
        if line[i] == "|":
            cells.append(buf.strip())
            buf = ""
        else:
            buf += line[i]
        i += 1
    cells.append(buf.strip())
    return cells


def _inline(text, size, color, link, code_fg):
    return render_inline(text, size, color, link, code_fg)


def parse(markdown_text, size_scale=1.0, colors=None):
    """解析 Markdown，返回控件指令列表。

    colors 需要提供: text, text2, muted, primary, divider, code_bg, code_fg,
                     quote_bar, highlight
    """
    col = colors or {}
    text_c = col.get("text", "#151A26")
    text2 = col.get("text2", "#5B6478")
    primary = col.get("primary", "#4F46E5")
    muted = col.get("muted", "#9AA2B5")
    cbar = col.get("quote_bar", "#C9CFFB")
    code_fg = col.get("code_fg", CODE_FG)

    blocks = []
    hsize = {
        1: 27.0, 2: 22.0, 3: 18.5, 4: 16.5, 5: 15.0, 6: 14.0,
    }

    def emit(**kw):
        blocks.append(kw)

    lines = markdown_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    n = len(lines)
    counter = {}          # 列表编号状态
    prev_blank = False

    while i < n:
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.strip()

        # 空行
        if not stripped:
            if not prev_blank and blocks and blocks[-1]["cmd"] not in ("blank",):
                emit(cmd="blank")
            prev_blank = True
            counter = {}
            i += 1
            continue
        prev_blank = False

        # 代码块
        m = FENCE_RE.match(line)
        if m:
            lang = m.group(2) or ""
            body = []
            i += 1
            while i < n and not FENCE_RE.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1
            emit(cmd="code", lang=lang, code="\n".join(body), size=size_scale)
            counter = {}
            continue

        # 分隔线
        if HR_RE.match(line):
            emit(cmd="hr")
            counter = {}
            i += 1
            continue

        # 标题
        m = HEAD_RE.match(line)
        if m:
            lvl = len(m.group(1))
            emit(cmd="h%d" % lvl,
                 text=_inline(m.group(2), hsize[lvl], text_c, primary, code_fg),
                 size=hsize[lvl] * size_scale,
                 plain=unescape(m.group(2)))
            counter = {}
            i += 1
            continue

        # 表格
        if "|" in line and i + 1 < n and TABLE_SEP_RE.match(lines[i + 1]):
            header = _split_row(line)
            i += 2
            rows = []
            while i < n and lines[i].strip() and "|" in lines[i]:
                rows.append(_split_row(lines[i]))
                i += 1
            cols = len(header)
            emit(cmd="table", header=header, rows=rows, cols=cols, size=size_scale)
            counter = {}
            continue

        # 引用（支持连续多行）
        if QUOTE_RE.match(line):
            buf = []
            while i < n:
                qm = QUOTE_RE.match(lines[i])
                if qm:
                    buf.append(qm.group(1))
                    i += 1
                elif lines[i].strip() and not lines[i].lstrip().startswith(("#", "```")):
                    buf.append(lines[i].strip())
                    i += 1
                else:
                    break
            emit(cmd="quote",
                 # 必须过 _inline！否则引用里的 **粗体** / `代码` 会连着星号
                 # 和反引号一起原样显示（段落和列表都过了，就这里漏了）。
                 text=_inline(" ".join(x for x in buf if x), 15.5,
                              text_c, primary, code_fg),
                 plain=unescape(" ".join(x for x in buf if x)),
                 size=size_scale)
            counter = {}
            continue

        # 列表
        lm = LIST_RE.match(line)
        if lm:
            indent = len(lm.group(1).replace("\t", "    "))
            level = min(3, indent // 2)
            marker = lm.group(2)
            content = lm.group(3)
            ordered = marker[0].isdigit()
            # 任务清单
            tm = TASK_RE.match(content)
            if tm:
                emit(cmd="task", checked=tm.group(1).lower() == "x",
                     text=_inline(tm.group(2), 15.5, text_c, primary, code_fg),
                     level=level, size=size_scale)
            else:
                key = (level, indent)
                if ordered:
                    counter[key] = counter.get(key, 0) + 1
                    num = counter[key]
                else:
                    num = None
                emit(cmd="number" if ordered else "bullet",
                     text=_inline(content, 15.5, text_c, primary, code_fg),
                     num=num, level=level, size=size_scale)
            i += 1
            continue

        # 单独成行的图片
        im0 = _INLINE[0][1].fullmatch(stripped)
        if im0:
            emit(cmd="image", alt=im0.group(1) or "图片", src=im0.group(2))
            counter = {}
            i += 1
            continue

        # 普通段落（合并软换行）
        buf = [stripped]
        i += 1
        while i < n:
            nxt = lines[i]
            ns = nxt.strip()
            if (not ns or HEAD_RE.match(nxt) or FENCE_RE.match(nxt)
                    or LIST_RE.match(nxt) or HR_RE.match(nxt)
                    or QUOTE_RE.match(nxt) or TABLE_SEP_RE.match(nxt)
                    or (im0 and _INLINE[0][1].fullmatch(ns))
                    or ("|" in nxt and i + 1 < n and TABLE_SEP_RE.match(lines[i + 1]))):
                break
            buf.append(ns)
            i += 1
        emit(cmd="para",
             text=_inline(" ".join(buf), 15.5, text_c, primary, code_fg),
             plain=unescape(" ".join(buf)),
             size=size_scale)

    # 去掉首尾空行
    while blocks and blocks[0]["cmd"] == "blank":
        blocks.pop(0)
    while blocks and blocks[-1]["cmd"] == "blank":
        blocks.pop()
    return blocks


def plain_text(blocks):
    """抽出纯文本（用于搜索与统计）。"""
    buf = []
    for b in blocks:
        c = b["cmd"]
        if c in ("h1", "h2", "h3", "h4", "h5", "h6", "para", "bullet", "number",
                 "task", "quote"):
            buf.append(b.get("plain") or unescape(_strip_tags(b.get("text", ""))))
        elif c == "code":
            buf.append(b.get("code", ""))
        elif c == "table":
            buf.append(" ".join(b["header"]))
            for r in b["rows"]:
                buf.append(" ".join(r))
        elif c == "image":
            buf.append(b.get("alt", ""))
    return "\n".join(buf)


_TAG = re.compile(r"\[/?[^\]]*\]")


def _strip_tags(s):
    return _TAG.sub("", s)


def stats(markdown_text):
    """字数 / 行数 / 阅读时长（按 350 字/分钟）。"""
    text = _TAG.sub("", markdown_text)
    chars = len(re.sub(r"\s", "", text))
    lines = len(markdown_text.split("\n"))
    han = len(re.findall(r"[\u4e00-\u9fff]", text))
    words = len(re.findall(r"[A-Za-z0-9_']+", text))
    minutes = max(1, int(round((han + words) / 350.0)))
    return {"chars": chars, "lines": lines, "minutes": minutes}
