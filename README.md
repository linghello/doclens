# DocLens

一个用 **Python + Kivy** 写的 Android 本地文档阅读器。界面完全自绘，不依赖任何第三方 UI 库。

- 支持格式：**TXT** / **Markdown**
- 深色 / 浅色 / 跟随系统 三套主题
- 中文排版：自己写的 CJK 断行 + 避头尾，中英混排不会挤成竖条
- 纯离线：**不要任何权限**，文件躺在 App 自己的沙盒里，不联网、不读相册
- 阅读进度自动记住，下次打开停在原地

---

## 一、桌面预览（先在电脑上看看长什么样）

**方式 A：双击 `run_preview.bat`**（最快）

它会自动找到装了 Kivy 的 Python（优先本项目的 venv），直接跑 `main.py`。
不用装 WSL、不用 Android SDK、不用手机 —— APK 就是这份 Python 代码被 buildozer 冻起来的，
所以桌面看到的样子基本就是手机上的样子。那个黑窗口留着别关，它是日志：崩了会在里面打 traceback。

**方式 B：手动**

```bash
# 建一个隔离的 venv，别污染系统 Python
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / WSL / macOS
source .venv/bin/activate

pip install kivy==2.3.1 pillow
python main.py
```

启动后会自动把 `samples/` 里的两份示例文档导进沙盒，直接就能点开看。

**桌面端快捷键**

| 按键 | 作用 |
| --- | --- |
| `Esc` | 返回文档库 / 关闭弹层 |
| `空格` | 阅读器里向下翻一页 |
| 拖文件进窗口 | 导入 `.md` / `.txt` |

---

## 二、打 APK

`buildozer` 只能在 Linux 下跑。Windows 上有两条路，**按你有没有 WSL 选**：

| | 方式 A：本机 WSL | 方式 B：GitHub 云端 |
| --- | --- | --- |
| 前提 | 装 WSL2 + Ubuntu（约 3–5 GB，要重启） | 有个 GitHub 仓库 |
| 耗时 | 首次 30–90 分钟 | 首次 30–90 分钟（在云上跑，不吃你机器） |
| 门槛 | 要占本机磁盘和内存 | 零本地依赖 |
| 适合 | 要反复构建 / 断网 | 偶尔出一次包 |

> ⚠️ **本机当前没装任何 WSL 发行版**（`HKCU\...\Lxss` 注册表键不存在），
> 所以现在双击 `build_apk.bat` 会直接告诉你「WSL is installed but has NO Linux distro yet」，
> 这是预期行为，不是 bug。要走方式 A 就先按下面第 0 步装 Ubuntu。

### 方式 A：本机 WSL

**0. 装 WSL2（已装可跳过）**

管理员 PowerShell：

```powershell
wsl --install -d Ubuntu
```

重启后设好 Ubuntu 的用户名密码（**别用 root**，buildozer 会拒绝 root 运行）。

**1. 打包**

双击 `build_apk.bat`，或在 WSL 终端里手动跑：

```bash
cd /mnt/c/Users/<你的用户名>/.../doclens
bash build_apk.sh              # debug APK（最快，能直接装）
bash build_apk.sh release      # release APK（体积更小）
bash build_apk.sh clean        # 清掉 .buildozer / bin 重来
```

> 用 `bash build_apk.sh` 而不是 `./build_apk.sh`：在 `/mnt/c` 上 `chmod +x`
> 常常不生效（DrvFs 默认不存 metadata），直接 `./` 会 Permission denied。

脚本会自己装系统依赖、建独立 venv、默认走腾讯云 PyPI 镜像（想用官方源加 `USE_OFFICIAL_PYPI=1`）。

### 方式 B：GitHub 云端（不需要 WSL）

仓库里已经放好 `.github/workflows/build-apk.yml`：

1. 把 `doclens/` 整个 push 到 GitHub（**公开仓库即可，Actions 免费额度够用**）
2. 仓库页面 → **Actions** → 左侧 **Build APK** → **Run workflow**
3. 等 30–90 分钟（首次；有缓存后几分钟）
4. 在该次 run 页面底部的 **Artifacts** 里下载 `doclens-apk-debug`

工作流固定在 `ubuntu-22.04` —— 24.04 移除了 `libtinfo5`，buildozer 会找不到它而报错。

**云端构建踩过的两个坑（都已修好，改配置前务必看一眼）**

**1. 磁盘不够 —— 失败得毫无线索。** GitHub 托管的 Ubuntu 运行器**只有约 14 GB 可用磁盘**，
却预装了约 6 GB 的 Android SDK（`/usr/local/lib/android`，我们不用这份）。
而 p4a 完整编译要 15–20 GB。

第一次构建的症状特别有迷惑性：日志在编译 hostpython3 到一半时**硬生生截断**，
之后 7 分钟完全空白，**而且日志里找不到任何 `No space left on device`** ——
因为磁盘满了，运行器连日志都写不进去。

工作流里的 `Free up disk space` 步骤是**必需的**，不是优化。
⚠️ 注意它只删 `/opt/hostedtoolcache/CodeQL`，**不能删整个 `/opt/hostedtoolcache`** ——
`setup-python` 装的 Python 就在里面（`/opt/hostedtoolcache/Python/...`）。

**2. `p4a.branch` 必须钉住。** `buildozer.spec` 里这一行不要删：

```ini
p4a.branch = v2024.01.21
```

buildozer 默认拉 p4a 的 **master**，而 master 已经把 `python3` recipe 推到了
**Python 3.14.2**；但 Kivy 2.3.1 的 recipe 又把 Cython 限死在 `<=3.0.12`，
那个 Cython 不支持 Python 3.14 —— 会在编译 Kivy 时炸掉。

| p4a 版本 | 默认 Python | 结论 |
| --- | --- | --- |
| master | 3.14.2 | ❌ 不能用 |
| **v2024.01.21** | **3.11.5** | ✅ 用这个 |
| v2023.09.16 | 3.10.10 | 偏旧 |


### 产物与安装

```
bin/doclens-1.0.0-arm64-v8a_*.apk
```

```bash
adb install -r bin/doclens-1.0.0-arm64-v8a_debug.apk
# 或者直接拷到手机点安装
```

> 只打了 `arm64-v8a`（2019 年后的手机基本都是这个架构），APK 能小一半。
> 需要兼容老 32 位机型就改 `buildozer.spec` 里的 `android.archs = arm64-v8a, armeabi-v7a`。


---

## 三、项目结构

```
doclens/
├── main.py                 入口：注册字体、建窗口、处理 Android 分享 intent
├── app.py                  Shell（换页/弹层/Toast）+ 各弹层逻辑
├── buildozer.spec          打包配置
├── build_apk.sh            WSL 一键构建脚本（LF 换行，绝不要改成 CRLF）
├── build_apk.bat           Windows 双击打包入口（纯 ASCII + CRLF，见第七节）
├── run_preview.bat         Windows 桌面预览入口（纯 ASCII + CRLF）
├── _smoke.py               桌面回归截图脚本
├── .github/workflows/
│   └── build-apk.yml       GitHub 云端打包（不需要 WSL）
├── core/
│   ├── theme.py            深/浅色两套配色 + 语义化取色
│   ├── widgets.py          自绘控件：Surface/Card/IconButton/AppBar/Chip…
│   ├── mdrender.py         Markdown → 控件指令（块级 + 行内）
│   ├── textwrap.py         CJK 断行 + 避头尾（用 Kivy markup 标签栈）
│   ├── store.py            沙盒文档存取、进度、收藏、摘要缓存
│   └── android.py          Android 分享 intent / 文件选择
├── screens/
│   ├── library.py          文档库：搜索 / 收藏 / 继续阅读 / 全部
│   └── reader.py           阅读器：块级渲染 + 精确高度测量
├── assets/fonts/
│   └── NotoSansSC-Regular.ttf   思源黑体子集（2.6 MB，含自绘图标字形）
├── samples/                两份示例文档
└── tools/
    ├── build_font.py       从系统思源黑体裁子集（GB2312 + 图标 + 空白）
    └── patch_icons.py      用几何图形自绘缺失的图标字形
```

---

## 四、字体是怎么来的

系统自带的思源黑体（`NotoSansSC-VF.ttf`）有 **16.9 MB**，直接打进 APK 太浪费。所以：

1. `tools/build_font.py` 裁出 **GB2312 全覆盖**（6763 汉字 + 682 符号）的子集；
2. 系统字体里 `⌕ ⚙ ⋮ ✎` 这类符号是**空字形**（声明了但没有轮廓），
   由 `tools/patch_icons.py` 用纯几何图形**程序化自绘**（规避微软专有符号字体版权）；
3. 补回被 subset 丢掉的空白字符（普通空格、全角空格等）。

结果 **2.6 MB**，中文 + 图标全都在。

> 需要改图标或扩充字符集时：
> ```bash
> python tools/build_font.py     # 先裁子集
> python tools/patch_icons.py    # 再补自绘图标
> ```

---

## 五、开发时会踩到的 Kivy 坑

这些都是本项目实际踩过并写在代码注释里的，改代码前值得看一眼：

1. **`Widget.bg` 是尺寸别名**（`right`/`bottom`），不是背景色。
   本项目的背景色属性一律叫 **`surface_bg`**。
2. **`ButtonBehavior` 必须放 MRO 第一位**（`class DocRow(Surface, BoxLayout)`），
   否则 `register_event_type` 拿不到，点击无效。
3. **`ScrollView` 只接受一个子控件**，浮层要另挂 `FloatLayout`。
4. **`font.setGlyphOrder()` 会丢字形** —— 它会用旧顺序重建 `glyf.glyphOrder`，
   把刚 append 的自绘字形静默丢弃。
5. **`Label.texture_size` 才是真实排版尺寸**；
   `CoreLabel.content_size` 在按「可见文字宽度」估算时和 Kivy 实际折行对不上
   （Kivy 是按含 markup 标签的原始串折行的，行数能差一倍）。
   所以 `reader._text_height()` 的做法是**真的建一个 Label 排版再读高度**。
6. **HiDPI**：`KIVY_METRICS_DENSITY` 必须在 `import kivy` **之前**设好，
   否则本机 175% 缩放会把 `dp(94)` 变成 164.5px。

---

## 六、桌面端自动截图（回归用）

```bash
python _smoke.py        # 产出 shots/*.png
```

会依次走：导入示例 → 打开阅读器 → 滚动 → 关阅读器 → 换深色主题 →
设置面板 → 大字号阅读，全程截图，末尾打印 `SMOKE errors=[] ALL_OK`。
改完 UI 跑一遍，扫一眼截图就知道有没有崩版面。

---

## 七、两个 .bat 为什么是纯 ASCII（**别改**）

`build_apk.bat` 和 `run_preview.bat` 里**一个中文都没有**，这是故意的，不是偷懒。

**踩过的坑**：最初这两个文件写成了「UTF-8 编码 + 中文注释 + LF 换行」，
双击后 cmd 直接喷一屏：

```
'tu锌?REM ' 不是内部或外部命令，也不是可运行的程序或批处理文件。
'l' 不是内部或外部命令，也不是可运行的程序或批处理文件。
'cho.' 不是内部或外部命令，也不是可运行的程序或批处理文件。
```

**原因**：`cmd.exe` 读 `.bat` 用的是 **OEM 代码页（本机 = 936 / GBK）**，不是 UTF-8。
一个中文字在 UTF-8 里是 **3 字节**，在 GBK 眼里是 **1.5 个字符** ——
剩下那个「半个」前导字节会**把后面一个字节吃掉**，而它后面可能是 `\n`（换行）
或 `e`（`echo` 的第一个字母）。结果就是：

- 行被**拼接**到上一行去（所以报错里出现 `REM` 混在乱码后面）
- `@echo off` 变成 `cho off`、`echo.` 变成 `cho.`
- 整个脚本被解析得面目全非

叠加第二个问题：那两个文件当时还是 **LF 换行**（`\r\n` 数量为 0）。
cmd 的批处理解析器要 CRLF，纯 LF 会加剧上面的错位。

**现在的状态**（已用脚本校验）：

| 文件 | 编码 | 换行 | 非 ASCII 字节 |
| --- | --- | --- | --- |
| `build_apk.bat` | ASCII | CRLF | 0 |
| `run_preview.bat` | ASCII | CRLF | 0 |
| `build_apk.sh` | UTF-8 | **LF**（shell 脚本必须 LF） | 有中文注释，正常 |

**规则**：
- 改 `.bat` 时**不要往里写中文**，提示信息用英文。中文说明写在本 README 里。
- 用记事本 / VS Code 保存 `.bat` 时确认是 **ANSI/ASCII + CRLF**，别存成 UTF-8。
- `.sh` 反过来：必须是 **LF**，存成 CRLF 的话 bash 会报 `bad interpreter: /bin/bash^M`。

另外，`build_apk.bat` 里**刻意不用 `for /f` + `wslpath`**（老版本用了，正好是出错的那一行）。
现在直接 `wsl.exe --cd "<Windows 路径>"` —— WSL 自己会把 Windows 路径转成 `/mnt/...`，
少一层 shell 解析就少一堆引号地狱。

---

## 八、许可

- 代码：随意用。
- 字体：`NotoSansSC` 为 **SIL Open Font License 1.1**，可自由分发（含商用）。
