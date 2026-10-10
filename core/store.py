# -*- coding: utf-8 -*-
"""文档仓库：扫描 / 导入 / 收藏 / 阅读进度 / 设置持久化。

所有用户数据都写在 user_data_dir，Android 上卸载即清空，不需要任何权限。
"""

import json
import os
import re
import shutil
import time

from kivy.app import App

TEXT_EXT = {".md", ".markdown", ".mdown", ".mkd", ".txt", ".text", ".log", ".csv", ".json"}
MAX_BYTES = 8 * 1024 * 1024  # 单文件 8MB 上限，避免手机被撑爆

ENC_TRY = ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "utf-16", "latin-1")


def _root():
    try:
        base = App.get_running_app().user_data_dir
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".doclens")
    return base


class Store:
    def __init__(self):
        self.base = _root()
        self.docs_dir = os.path.join(self.base, "documents")
        self.thumb_dir = os.path.join(self.base, "thumbnails")
        self.images_dir = os.path.join(self.base, "images")
        self.state_path = os.path.join(self.base, "state.json")
        self.cache_path = os.path.join(self.base, "cache.json")
        os.makedirs(self.docs_dir, exist_ok=True)
        os.makedirs(self.thumb_dir, exist_ok=True)
        os.makedirs(self.images_dir, exist_ok=True)
        self.state = self._load(self.state_path, {
            "favorites": [], "progress": {}, "theme": "system",
            "font_scale": 1.0, "history": [], "first_run": True,
            "styles": {},
        })
        self._cache = self._load(self.cache_path, {})
        self._dirty = False
        self._cache_dirty = False

    # ── 低层 ────────────────────────────────────────
    @staticmethod
    def _load(path, default):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                merged = dict(default)
                merged.update(data)
                return merged
        except Exception:
            pass
        return dict(default)

    def flush(self, *a):
        if not self._dirty:
            return
        try:
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.state, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self.state_path)
            self._dirty = False
        except Exception:
            pass

    def flush_cache(self, *a):
        if not self._cache_dirty:
            return
        try:
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._cache, fh, ensure_ascii=False)
            os.replace(tmp, self.cache_path)
            self._cache_dirty = False
        except Exception:
            pass

    # ── 文档 ────────────────────────────────────────
    def list_docs(self):
        docs = []
        for name in os.listdir(self.docs_dir):
            if name.startswith("."):
                continue
            path = os.path.join(self.docs_dir, name)
            if not os.path.isfile(path):
                continue
            try:
                st = os.stat(path)
            except OSError:
                continue
            rel = name
            cached = self._cache.get(rel, {})
            docs.append({
                "name": name,
                "path": path,
                "rel": rel,
                "size": st.st_size,
                "mtime": st.st_mtime,
                "preview": cached.get("preview", ""),
                "chars": cached.get("chars", 0),
                "minutes": cached.get("minutes", 0),
                "title": cached.get("title") or self._title_from_name(name),
            })
        docs.sort(key=lambda d: d["mtime"], reverse=True)
        return docs

    @staticmethod
    def _title_from_name(name):
        base = os.path.splitext(name)[0]
        base = re.sub(r"[_\-]+", " ", base).strip()
        return base or name

    def read(self, rel):
        path = os.path.join(self.docs_dir, rel)
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as fh:
            raw = fh.read()
        for enc in ENC_TRY:
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw.decode("utf-8", errors="replace")

    def unique_name(self, filename):
        filename = os.path.basename(filename).replace("\x00", "")
        filename = filename.strip() or "未命名.md"
        stem, ext = os.path.splitext(filename)
        if not ext:
            ext = ".md"
        cand = stem + ext
        k = 1
        while os.path.exists(os.path.join(self.docs_dir, cand)):
            k += 1
            cand = "%s (%d)%s" % (stem, k, ext)
        return cand

    def import_bytes(self, filename, data):
        name = self.unique_name(filename)
        path = os.path.join(self.docs_dir, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return name

    def import_text(self, filename, text):
        return self.import_bytes(filename, text.encode("utf-8"))

    def import_path(self, src_path):
        """从本机路径复制一份进来。"""
        name = self.unique_name(os.path.basename(src_path))
        dst = os.path.join(self.docs_dir, name)
        shutil.copyfile(src_path, dst)
        return name

    # ── 图片 / 文档样式 ─────────────────────────────
    IMG_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")

    def import_image(self, src_path):
        """把图片复制进 App 的 images 目录，返回可直接写进 markdown 的相对路径。"""
        ext = os.path.splitext(src_path)[1].lower()
        if ext not in self.IMG_EXT:
            ext = ".jpg"
        stem = re.sub(r'[\\/:*?"<>|\s]+', "_",
                      os.path.splitext(os.path.basename(src_path))[0])[:40] or "image"
        cand = stem + ext
        k = 1
        while os.path.exists(os.path.join(self.images_dir, cand)):
            k += 1
            cand = "%s_%d%s" % (stem, k, ext)
        shutil.copyfile(src_path, os.path.join(self.images_dir, cand))
        return "images/" + cand

    def image_path(self, src):
        """把 markdown 里的图片路径解析成本机绝对路径；找不到返回 None。"""
        if not src:
            return None
        s = str(src).strip().strip("<>")
        if s.startswith("file://"):
            s = s[7:]
        cands = []
        if os.path.isabs(s):
            cands.append(s)
        else:
            # 依次试：App 数据根 / documents / images
            cands.append(os.path.join(self.base, s))
            cands.append(os.path.join(self.docs_dir, s))
            cands.append(os.path.join(self.images_dir, os.path.basename(s)))
        for p in cands:
            try:
                if os.path.isfile(p):
                    return p
            except OSError:
                continue
        return None

    def doc_style(self, rel):
        """每篇文档的个性化样式：{'bg': 'images/xx.jpg', 'bg_opacity': 0.22}"""
        try:
            return dict(self.state.get("styles", {}).get(rel, {}))
        except Exception:
            return {}

    def set_doc_style(self, rel, **kw):
        styles = self.state.setdefault("styles", {})
        cur = dict(styles.get(rel, {}) or {})
        cur.update(kw)
        if not cur.get("bg"):
            cur.pop("bg", None)
        if cur:
            styles[rel] = cur
        else:
            styles.pop(rel, None)
        self._dirty = True
        self.flush()
        return cur

    def write_text(self, rel, text):
        """覆盖写入正文（编辑器保存用），并让预览缓存失效。"""
        path = os.path.join(self.docs_dir, rel)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
        self._cache.pop(rel, None)
        self._cache_dirty = True
        self._dirty = True
        self.flush_cache()
        return True

    def delete(self, rel):
        path = os.path.join(self.docs_dir, rel)
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            return False
        self.state["favorites"] = [r for r in self.state["favorites"] if r != rel]
        self.state["progress"].pop(rel, None)
        self._cache.pop(rel, None)
        self._dirty = self._cache_dirty = True
        self.flush()
        self.flush_cache()
        thumb = os.path.join(self.thumb_dir, os.path.splitext(rel)[0] + ".png")
        if os.path.isfile(thumb):
            try:
                os.remove(thumb)
            except OSError:
                pass
        return True

    def rename(self, rel, new_stem):
        new_stem = re.sub(r'[\\/:*?"<>|]', "_", new_stem).strip() or "未命名"
        ext = os.path.splitext(rel)[1]
        new_rel = new_stem + ext
        if new_rel == rel:
            return rel
        new_rel = self.unique_name(new_rel)
        src = os.path.join(self.docs_dir, rel)
        dst = os.path.join(self.docs_dir, new_rel)
        os.rename(src, dst)
        if rel in self.state["favorites"]:
            self.state["favorites"] = [new_rel if r == rel else r
                                       for r in self.state["favorites"]]
        if rel in self.state["progress"]:
            self.state["progress"][new_rel] = self.state["progress"].pop(rel)
        if rel in self._cache:
            self._cache[new_rel] = self._cache.pop(rel)
        self._dirty = self._cache_dirty = True
        self.flush()
        self.flush_cache()
        return new_rel

    # ── 缓存元信息 ──────────────────────────────────
    def update_meta(self, rel, preview, chars, minutes, title=None):
        entry = self._cache.get(rel, {})
        entry.update({"preview": preview, "chars": chars, "minutes": minutes})
        if title:
            entry["title"] = title
        self._cache[rel] = entry
        self._cache_dirty = True

    def cached_preview(self, rel):
        return self._cache.get(rel, {}).get("preview", "")

    def invalidate_meta(self, rel):
        """丢弃某篇的摘要/字数缓存（编辑保存后要重算）。"""
        if rel in self._cache:
            self._cache.pop(rel, None)
            self._cache_dirty = True
            self.flush_cache()

    # ── 收藏 ────────────────────────────────────────
    def is_fav(self, rel):
        return rel in self.state["favorites"]

    def toggle_fav(self, rel):
        favs = self.state["favorites"]
        if rel in favs:
            favs.remove(rel)
            value = False
        else:
            favs.insert(0, rel)
            value = True
        self._dirty = True
        self.flush()
        return value

    # ── 阅读进度 ────────────────────────────────────
    def progress(self, rel):
        return float(self.state["progress"].get(rel, 0.0))

    def set_progress(self, rel, value):
        self.state["progress"][rel] = round(max(0.0, min(1.0, value)), 4)
        self._dirty = True

    def mark_opened(self, rel):
        hist = self.state["history"]
        if rel in hist:
            hist.remove(rel)
        hist.insert(0, rel)
        del hist[20:]
        doc = None
        for d in self.list_docs():
            if d["rel"] == rel:
                doc = d
                break
        if doc:
            base = self.state.setdefault("open_counts", {})
            base[rel] = base.get(rel, 0) + 1
            self.state.setdefault("last_open", {})[rel] = time.time()
        self._dirty = True
        self.flush()

    def recent(self, limit=8):
        docs = {d["rel"]: d for d in self.list_docs()}
        out = []
        for rel in self.state["history"]:
            if rel in docs:
                out.append(docs[rel])
            if len(out) >= limit:
                break
        return out

    # ── 设置 ────────────────────────────────────────
    def get(self, key, default=None):
        return self.state.get(key, default)

    def set(self, key, value):
        self.state[key] = value
        self._dirty = True

    def storage_usage(self):
        total = 0
        for root, _dirs, files in os.walk(self.base):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total
