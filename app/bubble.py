# -*- coding: utf-8 -*-
"""气泡：用**分层窗口**（UpdateLayeredWindow）画，字用 PIL 画进图里。

为什么要这么写：
- 以前窗口形状是 `SetWindowRgn` 区域的**二值**裁剪 → 边缘一圈锯齿；
- 以前文字是 Tk 画的，描边/加粗/居中都不好控。

现在：
- 整张图（气泡 + 字）在内存里合成成 RGBA，交给 `UpdateLayeredWindow` 做**逐像素 alpha** —— 边缘平滑，没有锯齿；
- 字用 PIL 的 `stroke_width`，描边、颜色、加粗、居中都能配；
- 窗口设成**鼠标穿透**，不挡鼠标；自己到点淡出。
"""
import ctypes
import ctypes.wintypes as wt
import os
import threading
import time
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32
# ⭐ 1.1.0：120 帧要先提系统定时器精度（Tk 的 after 默认 ~15.6ms 一跳）
winmm = ctypes.windll.winmm
try:
    winmm.timeBeginPeriod.argtypes = [ctypes.c_uint]
    winmm.timeBeginPeriod.restype = ctypes.c_uint
    winmm.timeEndPeriod.argtypes = [ctypes.c_uint]
    winmm.timeEndPeriod.restype = ctypes.c_uint
except Exception:
    pass

WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_POPUP = 0x80000000
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01


# ---- 64 位下句柄是 8 字节：所有用到的 Win32 调用都要先声明签名，否则会 Overflow ----
_句柄 = ctypes.c_void_p
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.DeleteDC.argtypes = [wt.HDC]
gdi32.SelectObject.argtypes = [_句柄, _句柄]
gdi32.SelectObject.restype = _句柄
gdi32.DeleteObject.argtypes = [_句柄]
gdi32.CreateDIBSection.restype = _句柄
user32.GetDC.argtypes = [wt.HWND]
user32.GetDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p]
user32.CreateWindowExW.restype = wt.HWND
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.UpdateLayeredWindow.argtypes = [wt.HWND, wt.HDC, ctypes.c_void_p, ctypes.c_void_p,
                                       wt.HDC, ctypes.c_void_p, wt.DWORD,
                                       ctypes.c_void_p, wt.DWORD]
user32.UpdateLayeredWindow.restype = wt.BOOL
user32.DestroyWindow.argtypes = [wt.HWND]
user32.RegisterClassW.argtypes = [ctypes.c_void_p]
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HMODULE


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [('BlendOp', ctypes.c_ubyte),
                ('BlendFlags', ctypes.c_ubyte),
                ('SourceConstantAlpha', ctypes.c_ubyte),
                ('AlphaFormat', ctypes.c_ubyte)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', wt.DWORD), ('biWidth', wt.LONG), ('biHeight', wt.LONG),
                ('biPlanes', wt.WORD), ('biBitCount', wt.WORD), ('biCompression', wt.DWORD),
                ('biSizeImage', wt.DWORD), ('biXPelsPerMeter', wt.LONG), ('biYPelsPerMeter', wt.LONG),
                ('biClrUsed', wt.DWORD), ('biClrImportant', wt.DWORD)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [('bmiHeader', _BITMAPINFOHEADER), ('bmiColors', wt.DWORD * 3)]


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [('style', wt.UINT),
                ('lpfnWndProc', ctypes.c_void_p),
                ('cbClsExtra', ctypes.c_int),
                ('cbWndExtra', ctypes.c_int),
                ('hInstance', wt.HINSTANCE),
                ('hIcon', wt.HICON),
                ('hCursor', wt.HANDLE),
                ('hbrBackground', wt.HBRUSH),
                ('lpszMenuName', wt.LPCWSTR),
                ('lpszClassName', wt.LPCWSTR)]


class 分层窗:
    """无边框、置顶、鼠标穿透的分层窗口。

    ⚠ 用系统自带的 `Static` 类建窗，**不注册自己的 WndProc** ——
      自建窗口过程要挂 ctypes 回调，64 位下签名一错就是整进程崩（2026-10-27 点几下就整进程崩）。
      这里不需要收消息，只要「能贴图、能移动、能隐藏」就够。
    """

    def __init__(self, 穿透=True):
        self.hwnd = None
        self.宽 = 0
        self.高 = 0
        self.穿透 = bool(穿透)

    def 建(self, 宽, 高):
        if self.hwnd:
            return self.hwnd
        扩 = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        if self.穿透:
            # ⭐ 0.8.7：弹幕框要能接住点击（里面画了「回球 / 设置」），所以它可以不穿透
            扩 |= WS_EX_TRANSPARENT
        self.hwnd = user32.CreateWindowExW(
            扩, 'Static', '气泡', WS_POPUP, -10000, -10000, int(宽), int(高),
            None, None, kernel32.GetModuleHandleW(None), None)
        self.宽, self.高 = int(宽), int(高)
        return self.hwnd

    def 设穿透(self, 开):
        """中途切换「鼠标能不能点到我」。开=鼠标直接穿过去（游戏里最需要）。

        ⭐ 1.3.6：弹幕框锁住时要**真穿透** —— 只「不给拖」是假锁定，
        鼠标划过去还是被这个窗口接住（游戏里会看到光标、甚至卡一下）。
        """
        self.穿透 = bool(开)
        if not self.hwnd:
            return
        try:
            GWL_EXSTYLE = -20
            现 = user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE) or 0
            新 = (现 | WS_EX_TRANSPARENT) if self.穿透 else (现 & ~WS_EX_TRANSPARENT)
            user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, 新)
        except Exception:
            pass

    def 挪(self, x, y):
        """只挪位置，**不重画**。

        ⭐ 1.6.4（issue #3 报的「拖鲸鱼时气泡留在原地」）：
          以前「跟随」走的是 `贴图()` —— 它每次都要把整张图逐像素重新拼一遍
          （444×251 就是十几万次 Python 循环），拖动时每秒几十次鼠标事件根本跟不上，
          表现就是「气泡不跟」。挪位置只需要 SetWindowPos，便宜几百倍。
        """
        if not self.hwnd:
            return
        try:
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            user32.SetWindowPos(self.hwnd, 0, int(x), int(y), 0, 0,
                                SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        except Exception:
            pass

    def 关(self):
        try:
            if self.hwnd:
                user32.DestroyWindow(self.hwnd)
        except Exception:
            pass
        self.hwnd = None

    def 贴图(self, 图, x, y, 不透明=255):
        """把 RGBA 图整张贴上去（预乘 alpha）。"""
        宽, 高 = 图.size
        self.建(宽, 高)
        数据 = bytearray()
        px = 图.load()
        for yy in range(高 - 1, -1, -1):          # DIB 是自下而上
            for xx in range(宽):
                r, g, b, a = px[xx, yy]
                if a == 255:
                    数据 += bytes((b, g, r, 255))
                elif a == 0:
                    数据 += b'\x00\x00\x00\x00'
                else:
                    k = a / 255.0
                    数据 += bytes((int(b * k), int(g * k), int(r * k), a))

        hdc = user32.GetDC(None)
        屏dc = gdi32.CreateCompatibleDC(hdc)
        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = 宽
        bmi.bmiHeader.biHeight = 高
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0
        位 = ctypes.c_void_p()
        gdi32.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.UINT,
                                           ctypes.c_void_p, ctypes.c_void_p, wt.DWORD]
        gdi32.CreateDIBSection.restype = ctypes.c_void_p
        hbmp = gdi32.CreateDIBSection(
            屏dc, ctypes.cast(ctypes.byref(bmi), ctypes.c_void_p), 0,
            ctypes.cast(ctypes.byref(位), ctypes.c_void_p), None, 0)
        旧 = gdi32.SelectObject(屏dc, hbmp)
        ctypes.memmove(位, bytes(数据), len(数据))
        blend = _BLENDFUNCTION(AC_SRC_OVER, 0, int(不透明), AC_SRC_ALPHA)
        目标 = wt.POINT(int(x), int(y))
        大小 = wt.SIZE(宽, 高)
        原点 = wt.POINT(0, 0)
        # ⚠ 0.7.7：
        #   `ctypes.windll.user32` 是**全进程共用一个对象**，ball.py 自己的窗口每次重画都会把
        #   UpdateLayeredWindow 的 argtypes 改成 POINTER(_POINT) 版本 —— 之后我们这边传 c_void_p
        #   就会 `expected LP__POINT instance instead of c_void_p`。所以**每次调用前重新声明一次**。
        user32.UpdateLayeredWindow.argtypes = [wt.HWND, wt.HDC, ctypes.c_void_p, ctypes.c_void_p,
                                               wt.HDC, ctypes.c_void_p, wt.DWORD,
                                               ctypes.c_void_p, wt.DWORD]
        user32.UpdateLayeredWindow.restype = wt.BOOL
        user32.UpdateLayeredWindow(
            self.hwnd, hdc,
            ctypes.cast(ctypes.byref(目标), ctypes.c_void_p),
            ctypes.cast(ctypes.byref(大小), ctypes.c_void_p),
            屏dc,
            ctypes.cast(ctypes.byref(原点), ctypes.c_void_p),
            0,
            ctypes.cast(ctypes.byref(blend), ctypes.c_void_p),
            ULW_ALPHA)
        gdi32.SelectObject(屏dc, 旧)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(屏dc)
        user32.ReleaseDC(None, hdc)

    def 藏(self):
        if self.hwnd:
            user32.ShowWindow(self.hwnd, 0)

    def 显(self):
        if self.hwnd:
            user32.ShowWindow(self.hwnd, 5)


_英文数字 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.%+-/:：'


# ---------- ⭐ 1.2.2：备用字体 ----------
# 站酷快乐体好看，但缺字（颜文字里的 ｡･ω･｡、♡、①、日文假名、emoji…）。
# 缺字时画出来是「豆腐块」，看着就是乱码。这里做**一句话两种字体**：
# 主字体有的字照旧用主字体，主字体没有的，单独换成系统字体画。
#
# 判断「这个字体有没有这个字」不能靠「画出来看看」—— 缺字的豆腐块跟真字形很难比，
# 各个字体的 notdef 宽度还不一样。所以直接读字体文件的 cmap 表（自己解析，不依赖第三方库）。
_备用体缓存 = {}
_字形缓存 = {}
_覆盖缓存 = {}
_字体路径 = {}


def _读覆盖(路):
    """这个字体文件覆盖了哪些码位（读 cmap 表；.ttc 取第一个字体）。"""
    if 路 in _覆盖缓存:
        return _覆盖缓存[路]
    码 = set()
    try:
        import struct
        with open(路, 'rb') as f:
            头 = f.read(12)
        if 头[:4] == b'ttcf':
            with open(路, 'rb') as f:
                f.seek(12)
                偏移 = struct.unpack('>I', f.read(4))[0]
        else:
            偏移 = 0
        with open(路, 'rb') as f:
            f.seek(偏移)
            版, 表数 = struct.unpack('>IH', f.read(6))
            f.seek(偏移 + 12)
            目录 = [struct.unpack('>4sIII', f.read(16)) for _ in range(表数)]
            cmap偏移 = None
            for 标, _, 偏, 长 in 目录:
                if 标 == b'cmap':
                    cmap偏移 = 偏
                    break
            if cmap偏移 is not None:
                f.seek(cmap偏移)
                _, 子表数 = struct.unpack('>HH', f.read(4))
                子表 = [struct.unpack('>HHI', f.read(8)) for _ in range(子表数)]
                for 平台, 编码, 子偏 in 子表:
                    if 编码 not in (3, 4, 10) and 平台 not in (0, 3):
                        continue
                    f.seek(cmap偏移 + 子偏)
                    格式 = struct.unpack('>H', f.read(2))[0]
                    if 格式 == 4:
                        f.seek(cmap偏移 + 子偏)
                        _, 长4, _, 段数 = struct.unpack('>HHHH', f.read(8))
                        f.read(6)              # 省掉 searchRange/entrySelector/rangeShift
                        结束们 = struct.unpack('>%dH' % (段数 // 2), f.read(段数))
                        f.read(2)              # reservedPad
                        开始们 = struct.unpack('>%dH' % (段数 // 2), f.read(段数))
                        f.read(段数)           # idDelta
                        范围偏移位置 = f.tell()
                        for i in range(段数 // 2):
                            起, 止 = 开始们[i], 结束们[i]
                            if 起 == 0xFFFF:
                                continue
                            码.update(range(起, 止 + 1))
                    elif 格式 == 12:
                        f.seek(cmap偏移 + 子偏)
                        f.read(2)
                        f.read(2)
                        _, 组数 = struct.unpack('>II', f.read(8))
                        for _ in range(min(组数, 65536)):
                            起, 止, 索引 = struct.unpack('>III', f.read(12))
                            if 止 - 起 <= 0xFFFF:
                                码.update(range(起, 止 + 1))
    except Exception:
        pass
    _覆盖缓存[路] = 码
    return 码


def _字形有(体, 字, 键前=''):
    """这个字体里有没有这个字（读字体文件的 cmap）。读不出来就当作「有」，保持原样。"""
    if not 字 or 字 in ('\n', '\r', '\t') or 字.isspace():
        return True
    路 = _字体路径.get(id(体))
    if not 路:
        return True
    键 = (路, 字)
    if 键 in _字形缓存:
        return _字形缓存[键]
    覆盖 = _读覆盖(路)
    有 = (not 覆盖) or (ord(字[0]) in 覆盖)
    _字形缓存[键] = 有
    return 有


def _备用字体们(号, 主路=''):
    """一串兜底字体（微软雅黑 → Segoe UI Symbol → 黑体）。跟主字体同一个文件的不算。"""
    键 = (号, 主路)
    if 键 in _备用体缓存:
        return _备用体缓存[键]
    们 = []
    try:
        import os as _os
        # 雅黑先来（中文/假名/全角符号最全），再 Segoe UI Symbol（♡♪★ ✧ 这类符号），最后黑体
        for 路 in (r'C:\Windows\Fonts\msyh.ttc',          # 中文 + 假名 + 全角符号
                   r'C:\Windows\Fonts\seguisym.ttf',       # ♡ ♪ ★ ✧ 这类符号
                   r'C:\Windows\Fonts\segoeui.ttf',        # 阿拉伯文（颜文字里的 و）+ 组合符
                   r'C:\Windows\Fonts\malgun.ttf',         # 韩文（颜文字里的 ㅂ）
                   r'C:\Windows\Fonts\leelawui.ttf',       # 泰文（颜文字里的 ๑）
                   r'C:\Windows\Fonts\simhei.ttf',
                   r'C:\Windows\Fonts\YuGothM.ttc'):
            if not _os.path.exists(路):
                continue
            if 主路 and _os.path.normcase(路) == _os.path.normcase(主路):
                continue
            try:
                体 = ImageFont.truetype(路, 号)
                字体路径登记(体, 路)
                们.append(体)
            except Exception:
                continue
    except Exception:
        们 = []
    _备用体缓存[键] = 们
    return 们


def 字体路径登记(体, 路):
    try:
        _字体路径[id(体)] = 路
    except Exception:
        pass


def 切混排(行, 主体, 主路, 号):
    """把一行切成若干段：[(文字, 用哪个字体), …] —— 主字体缺的字单独换系统字体。

    ⭐ 1.3.2：从 气泡 里提出来，**弹幕和弹幕框也用它**（以前只有气泡做了兜底，
    游戏模式里飘的弹幕、框里攒的字碰到颜文字还是方块）。
    """
    备们 = _备用字体们(号, 主路)
    if not 备们:
        return [(行, 主体)]
    段们 = []
    for 字 in 行:
        字体 = 主体
        if not _字形有(主体, 字, ('主', 主路, 号)):
            for i, 备 in enumerate(备们):
                if _字形有(备, 字, ('备%d' % i, 号)):
                    字体 = 备
                    break
        if 段们 and 段们[-1][1] is 字体:
            段们[-1] = (段们[-1][0] + 字, 字体)
        else:
            段们.append((字, 字体))
    return 段们 or [(行, 主体)]


def 混排宽(行, 主体, 主路, 号):
    """这一行按混排之后有多宽。"""
    宽 = 0.0
    for 段, 字体 in 切混排(行, 主体, 主路, 号):
        try:
            宽 += 字体.getlength(段)
        except Exception:
            宽 += 主体.getlength(段)
    return 宽


def _切词(文本):
    """把一句话切成「不许拆开的段」：英文单词 / 数字 / 百分比算一段，中文一个字一段。

    ⭐ 0.9.4：以前一个字符一个字符断，`87.5%` 会被拆成两行、`DeepSeek` 也会断在中间。
    现在只在这类段之间换行，段本身太长才会退回去拆字。
    """
    段们, 当 = [], ''
    for 字 in 文本:
        if 字 == chr(10):
            if 当:
                段们.append(当)
                当 = ''
            段们.append(chr(10))
            continue
        if 字 in _英文数字:
            当 += 字
            continue
        if 当:
            段们.append(当)
            当 = ''
        段们.append(字)
    if 当:
        段们.append(当)
    # 句末标点跟前一个字走，开括号跟后一个字走。它们一起量宽，不能挂出框。
    合段 = []
    for 段 in 段们:
        if 合段 and 段 != '\n' and 合段[-1] != '\n' and (
                段[0] in '。，、；：！？）」』】》〉〕〗…·.,;:!?)]}'
                or 合段[-1][-1] in '（「『【《〈〔〖([{'):
            合段[-1] += 段
        else:
            合段.append(段)
    return 合段


def 量内区(图):
    """气泡内区：按行找最长的一段亮区（只有气泡那几行又亮又宽）。"""
    宽, 高 = 图.size
    px = 图.load()
    行们 = []
    for y in range(int(高 * 0.42), int(高 * 0.96)):
        最长 = (0, 0)
        当 = None
        x = int(宽 * 0.28)
        x末 = int(宽 * 0.98)
        while x < x末:
            r, g, b, a = px[x, y]
            if a > 250 and (r + g + b) / 3.0 > 186:
                if 当 is None:
                    当 = x
            else:
                if 当 is not None and x - 当 > 最长[1] - 最长[0]:
                    最长 = (当, x)
                当 = None
            x += 1
        if 当 is not None and x末 - 当 > 最长[1] - 最长[0]:
            最长 = (当, x末)
        if 最长[1] - 最长[0] > int(宽 * 0.35):
            行们.append((y, 最长[0], 最长[1]))
    if not 行们:
        return (int(宽 * 0.33), int(高 * 0.55), int(宽 * 0.93), int(高 * 0.84))
    ys = [a for a, _, _ in 行们]
    return (min(b for _, b, _ in 行们), min(ys), max(c for _, _, c in 行们), max(ys))


_定时精度 = False


def _要精度(要):
    """120 帧得把系统定时器精度提到 1ms（Tk 的 after 默认只有 ~15.6ms）。"""
    global _定时精度
    if 要 and not _定时精度:
        try:
            winmm.timeBeginPeriod(1)
            _定时精度 = True
        except Exception:
            _定时精度 = False
    elif not 要 and _定时精度:
        try:
            winmm.timeEndPeriod(1)
        except Exception:
            pass
        _定时精度 = False


class 气泡:
    def __init__(self, 根, 图路, 字体路, 宽=520,
                 字色='#1c3a52', 描边色='#ffffff', 描边=2, 加粗=False,
                 最大字号=22, 最多行=4):
        self.根 = 根
        self.字色 = 字色
        self.描边色 = 描边色
        self.描边 = int(描边)
        self.加粗 = bool(加粗)
        self.最大字号 = int(最大字号)
        self.最多行 = int(最多行)
        self.原 = Image.open(图路).convert('RGBA')
        蒙 = self.原.split()[-1].point(lambda v: 255 if v >= 40 else 0)
        self.原 = self.原.crop(蒙.getbbox())
        self.最宽 = int(宽)
        self._按宽(self.最宽)
        self.字体路 = 字体路
        self.窗 = 分层窗()
        self._藏定时 = None
        self._淡 = None
        self.次图 = None
        self.次位置 = (0, 0)
        # ⭐ 0.9.2：字多就分页（一页一页换），最后一页停够了才淡掉
        self.页们 = [[]]
        self._第几页 = 0
        self._停秒 = 6.0
        self._换页秒 = 4.0
        self._翻转 = False
        self._位置 = (0, 0)
        self._入定时 = None
        self._底图 = None
        # ⭐ 1.1.0：淡入淡出按「每秒画几帧」算（60 / 120）
        self.帧率 = 60
        self._帧间 = 17
        self._入帧 = 11
        self._出帧 = 19
        # ⭐ 1.3.0：淡入/淡出的**真实时长**，跟「停留几秒」一点关系没有
        self._淡入毫秒 = 180
        self._淡出毫秒 = 320
        self.设帧率(60)

    def 设帧率(self, 帧率=60, 淡入毫秒=None, 淡出毫秒=None):
        """换帧率：帧越高淡得越顺，代价是更费一点电。"""
        if 淡入毫秒 is not None:
            self._淡入毫秒 = float(淡入毫秒)
        if 淡出毫秒 is not None:
            self._淡出毫秒 = float(淡出毫秒)
        self.帧率 = 120 if int(帧率 or 60) >= 100 else 60
        self._帧间 = max(4, int(round(1000.0 / self.帧率)))
        self._入帧 = max(4, int(self.帧率 * self._淡入毫秒 / 1000.0))
        self._出帧 = max(6, int(self.帧率 * self._淡出毫秒 / 1000.0))
        try:
            _要精度(self.帧率 >= 100)
        except Exception:
            pass

    def _按宽(self, 宽):
        """等比缩放到这个宽度，并把「气泡里能写字的地方」重新量一遍。"""
        宽 = max(300, min(int(宽), self.最宽))
        if 宽 == getattr(self, '宽', None):
            return self.内
        self.宽 = 宽
        倍 = 宽 / float(self.原.width)
        self.图 = self.原.resize((宽, int(self.原.height * 倍)), Image.LANCZOS)
        宽, 高 = self.图.size
        # ⭐ 0.9.5：内区只是「大概范围」，每一行真正能写多宽由 _量宽() 按图逐行量。
        #   以前这里写死 0.165/0.50 —— 字压到画上那只手上、还顶出气泡上半圈。
        self.内 = (int(宽 * 0.135), int(高 * 0.560), int(宽 * 0.905), int(高 * 0.852))
        self._宽表 = None
        return self.内

    # ---------- 每行能写多宽（按图量） ----------
    def _量宽(self):
        """逐行扫气泡里那块白：记下每一行「白到哪儿」，字就跟着气泡形状走。

        气泡上下是圆弧 —— 只有中间那几行能写满，越靠上下越窄。
        取一整个矩形的话，要么上下冒出去，要么左右空一大圈。
        """
        if getattr(self, '_宽表', None) is not None:
            return self._宽表
        宽, 高 = self.图.size
        px = self.图.load()
        x0, y0, x1, y1 = self.内
        表 = {}
        for y in range(max(0, y0 - 6), min(高, y1 + 6)):
            最好 = None           # (左, 右) 最长的那段白
            当 = None
            for x in range(max(0, x0), min(宽, x1)):
                r, g, b, a = px[x, y]
                白 = a > 200 and (r + g + b) / 3.0 > 196 and (b - r) < 46
                if 白:
                    if 当 is None:
                        当 = x
                    末 = x
                else:
                    if 当 is not None:
                        if 最好 is None or (末 - 当) > (最好[1] - 最好[0]):
                            最好 = (当, 末)
                        当 = None
            if 当 is not None and (最好 is None or (末 - 当) > (最好[1] - 最好[0])):
                最好 = (当, 末)
            if 最好 and 最好[1] - 最好[0] > 60:
                表[y] = 最好
        self._宽表 = 表
        return 表

    def _行范围(self, 顶, 底):
        """文字和描边所占的每一条像素行，都得落在这一段底色里。"""
        表 = self._量宽()
        白段 = [表.get(y) for y in range(顶, max(顶 + 1, 底))]
        if None in 白段:
            return None
        return max(左 for 左, _ in 白段), min(右 for _, 右 in 白段) + 1

    def _行中(self, i, 行数, 行高):
        顶 = (self.内[1] + self.内[3] - 行数 * 行高) // 2
        return 顶 + i * 行高 + 行高 // 2

    def _量一行(self, 体, 行):
        """共用混排基线，量出每段字的位置和整行带描边的外框。"""
        段们, 框们 = [], []
        起 = 0.0
        for 段, 字体 in 切混排(行, 体, self.字体路, 体.size):
            左, 顶, 右, 底 = 字体.getbbox(段, anchor='ls', stroke_width=self.描边)
            # Pillow 画字时先取整，再用小数部分做亚像素偏移。
            像素起 = int(起)
            框们.append((像素起 + 左, 顶, 像素起 + 右 + (起 != 像素起), 底))
            段们.append((起, 段, 字体))
            起 += 字体.getlength(段)
        return 段们, (min(左 for 左, _, _, _ in 框们), min(顶 for _, 顶, _, _ in 框们),
                      max(右 for _, _, 右, _ in 框们), max(底 for _, _, _, 底 in 框们))

    def _行位置(self, 字框, 行中, 翻转=False):
        左字, 顶字, 右字, 底字 = 字框
        y = 行中 - (顶字 + 底字) // 2
        范围 = self._行范围(y + 顶字, y + 底字)
        if 范围 is None:
            return None
        左, 右 = 范围
        留边 = max(3, self.宽 // 130)
        if 右字 - 左字 + 留边 * 2 > 右 - 左:
            return None
        if 翻转:
            左, 右 = self.宽 - 右, self.宽 - 左
        return (左 + 右 - 左字 - 右字) // 2, y

    def 排字(self, 文本):
        """第一页的 (字体, 行, 行高, 字号) —— 量一下排得下吗用它。"""
        页们, 体, 行高, 号 = self.排页(文本)
        return 体, 页们[0], 行高, 号

    def _取字体(self, 号):
        体 = ImageFont.truetype(self.字体路, 号)
        字体路径登记(体, self.字体路)
        行高 = max(int(round(号 * 1.28)), 号 + self.描边 * 2 + 1)
        return 体, 行高, 号

    def _定字号(self):
        """短句用随气泡大小变化的正常字号。"""
        内宽 = self.内[2] - self.内[0]
        return self._取字体(max(16, min(40, round(内宽 / 18))))

    def _每页行(self, 行高):
        # 上下还有一小段扫描范围，实际字框仍要逐像素行检查。
        高内 = self.内[3] - self.内[1] + 10
        return max(1, min(self.最多行, 高内 // 行高))

    def _排一页(self, 段们, 起, 行高, 量字框):
        """分别试居中的一行、两行、三行等，选能放下最多原文的排法。"""
        最好, 最远 = [], 起
        for 行数 in range(1, self._每页行(行高) + 1):
            行们, 到 = [], 起
            上行底 = 0
            for i in range(行数):
                行中 = self._行中(i, 行数, 行高)
                行, 行底 = '', 上行底
                while 到 < len(段们) and 段们[到] != '\n':
                    试 = 行 + 段们[到]
                    字框 = 量字框(试)
                    位置 = self._行位置(字框, 行中)
                    if 位置 is None or 位置[1] + 字框[1] < 上行底:
                        break
                    行 = 试
                    行底 = 位置[1] + 字框[3]
                    到 += 1
                if not 行:
                    break
                行们.append(行)
                上行底 = 行底
                while 到 < len(段们) and 段们[到] == '\n':
                    到 += 1
            # 合成时按实际行数居中，因此只接受以相同行数排出来的一页。
            if len(行们) == 行数 and 到 > 最远:
                最好, 最远 = 行们, 到
                if 到 == len(段们):
                    break
        return 最好, 最远

    def _备排页(self, 原段们, 体, 行高):
        @lru_cache(maxsize=512)
        def 量字框(行):
            return self._量一行(体, 行)[1]

        中线 = self._行中(0, 1, 行高)
        段们 = []
        for 段 in 原段们:
            # 只有单独占一行也放不下的长单词或长数字才拆开。
            if len(段) > 1 and self._行位置(量字框(段), 中线) is None:
                段们.extend(段)
            else:
                段们.append(段)
        return 段们, 量字框

    def 排页(self, 文本):
        """优先整页读完，长文本按顺序分页，每行用自己所在位置的宽度。"""
        原段们 = _切词(str(文本 or '').replace('\r\n', '\n').replace('\r', '\n').strip() or '…')
        体, 行高, 号 = self._定字号()
        段们, 量字框 = self._备排页(原段们, 体, 行高)
        首, 到 = self._排一页(段们, 0, 行高, 量字框)
        整页 = 到 == len(段们)
        尾行太短 = False
        if 整页 and len(首) > 1:
            左, _, 右, _ = 量字框(首[-1])
            前左, _, 前右, _ = 量字框(首[-2])
            尾行太短 = (右 - 左) * 3 < 前右 - 前左
        if 整页 and not 尾行太短:
            return [首], 体, 行高, 号

        # 稍微缩字能省下一页就缩；只是尾行短，最多降两号，并且要能省掉一整行。
        最小 = max(15, 号 - (2 if 整页 else max(2, 号 // 8)))
        for 小号 in range(号 - 1, 最小 - 1, -1):
            小体, 小行高, _ = self._取字体(小号)
            小段们, 小量字框 = self._备排页(原段们, 小体, 小行高)
            一页, 末 = self._排一页(小段们, 0, 小行高, 小量字框)
            if 末 == len(小段们) and (not 整页 or len(一页) < len(首)):
                return [一页], 小体, 小行高, 小号

        页们 = []
        页, 起 = 首, 0
        while True:
            if 到 == 起:
                raise ValueError('气泡里找不到放字的位置')
            页们.append(页)
            if 到 == len(段们):
                return 页们, 体, 行高, 号
            起 = 到
            页, 到 = self._排一页(段们, 起, 行高, 量字框)

    def 合成(self, 文本, 翻转=False):
        """（里面只合成第一页）—— 框的大小是固定的，跟字多少无关。"""
        文本 = str(文本 or '').strip()
        self._按宽(self.最宽)
        页们, 体, 行高, 号 = self.排页(文本)
        return self.合成页(页们[0], 体, 行高, 翻转)

    def 合成页(self, 行们, 体, 行高, 翻转=False):
        底 = self.图.transpose(Image.FLIP_LEFT_RIGHT) if 翻转 else self.图
        图 = 底.copy()
        画 = ImageDraw.Draw(图)
        for i, 行 in enumerate(行们):
            段们, 字框 = self._量一行(体, 行)
            x, y = self._行位置(字框, self._行中(i, len(行们), 行高), 翻转)
            for 起, 段, 字体 in 段们:
                画.text((x + 起, y), 段, font=字体, anchor='ls', fill=self.字色,
                        stroke_width=self.描边, stroke_fill=self.描边色)
        return 图

    def _所在屏(self, x, y):
        """这个坐标在哪块显示器上 → 那块显示器的 (左, 上, 右, 下)。

        ⭐ 1.3.1：以前一律按**主屏**宽高算，所以球挪到副屏、气泡还是被拉回主屏。
        现在按球的位置查显示器；查不到就退回主屏（老行为）。
        """
        try:
            import ctypes
            from ctypes import wintypes
            class 点(ctypes.Structure):
                _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]
            class 矩形(ctypes.Structure):
                _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long),
                            ('right', ctypes.c_long), ('bottom', ctypes.c_long)]
            class 显示器信息(ctypes.Structure):
                _fields_ = [('cbSize', ctypes.c_ulong), ('rcMonitor', 矩形),
                            ('rcWork', 矩形), ('dwFlags', ctypes.c_ulong)]
            u = ctypes.windll.user32
            u.MonitorFromPoint.argtypes = [点, ctypes.c_ulong]
            u.MonitorFromPoint.restype = ctypes.c_void_p
            u.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(显示器信息)]
            u.GetMonitorInfoW.restype = wintypes.BOOL
            柄 = u.MonitorFromPoint(点(int(x), int(y)), 2)   # 2 = DEFAULTTONEAREST
            信息 = 显示器信息()
            信息.cbSize = ctypes.sizeof(显示器信息)
            if 柄 and u.GetMonitorInfoW(柄, ctypes.byref(信息)):
                r = 信息.rcMonitor
                return (int(r.left), int(r.top), int(r.right), int(r.bottom))
        except Exception:
            pass
        try:
            宽, 高 = int(self.根.winfo_screenwidth()), int(self.根.winfo_screenheight())
            return (0, 0, 宽, 高)
        except Exception:
            return (0, 0, 1920, 1080)

    def 跟随(self, 球框=None):
        """球在拖动 → 气泡跟着挪，不留在原地。

        ⚠⚠ 1.6.4 修（用户报的「拖鲸鱼气泡不动」）：这个方法**以前被写在 `分层窗` 里**
          （窗口包装那一层），而调用的是 `self.气泡.跟随(...)` —— 那个类里根本没有它，
          每次调用都抛 AttributeError，外面 `except Exception: pass` 一吞，就「看起来没这功能」。
          实测日志：`气泡跟随出错：'气泡' object has no attribute '跟随'`，拖一次刷几十行。
        """
        if 球框:
            self.球框 = 球框
        if self.次图 is None or not self.窗.hwnd:
            return
        try:
            x, y = self._球旁边(self.次图, 翻转=bool(getattr(self, '_翻转', False)))
            self.次位置 = (x, y)
            # 只挪位置，不重画（重画要逐像素拼十几万次，拖动时根本跟不上）
            if not self.窗.挪(x, y):
                self.窗.贴图(self.次图, x, y)
        except Exception as e:
            self.记一笔('跟随出错：%s' % e)

    def 记一笔(self, 话):
        """写进挂件的右键记录（跟 ball.记右键 同一个文件）。"""
        try:
            import paths as _p
            import time as _t
            with open(os.path.join(_p.用户目录(), '右键记录.log'), 'a', encoding='utf-8') as f:
                f.write(_t.strftime('%H:%M:%S') + ' ' + 话 + chr(10))
        except Exception:
            pass

    def 显示(self, 文本, 秒=6.0, 位置=None, 球径=None, 球框=None, 大小=1.0, 换页秒=4.0):
        文本 = str(文本 or '').strip()
        if not 文本:
            return False
        self._取消定时()
        # 框的尺寸只看「球多大 + 气泡大小%」：跟字多少无关，短句也是这么大
        try:
            self.最宽 = max(240, min(int((球径 or 132) * 3.24 * 大小), 900))
        except Exception:
            self.最宽 = 460
        self._按宽(self.最宽)
        self.球框 = 球框 or getattr(self, '球框', None)
        self.页们, self.体, self.行高, self.字号 = self.排页(文本)
        self._第几页 = 0
        self._停秒 = max(1.0, float(秒))
        self._换页秒 = max(0.8, float(换页秒))
        图 = self.图
        self._翻转 = False
        try:
            球框们 = [int(v) for v in (self.球框 or (0, 0, 132, 132))]
            球x, 球y, 球宽, 球高 = 球框们[0], 球框们[1], 球框们[2], 球框们[3]
        except Exception:
            球x, 球y, 球宽, 球高 = 0, 0, 132, 132
        # ⭐ 1.3.1：按**球所在的那块显示器**来定边 —— 球在副屏，气泡就出在副屏；
        #   球在主屏最右边时，右边放不下就翻到球的**左边**（在主屏内），不会跨屏跑过去。
        屏左, 屏上, 屏右, 屏下 = self._所在屏(球x + 球宽 // 2, 球y + 球高 // 2)
        if 位置:
            x, y = 位置
        else:
            x, y = self._球旁边(图)
            # 按「尾巴在左边、气泡往右展开」算一下原始位置；放不下就镜像到左边
            原x = 球x + int(球宽 * 0.90) - int(图.width * 0.24)
            if 原x + 图.width > 屏右 - 8 or 原x < 屏左 + 8:
                self._翻转 = True
                x, y = self._球旁边(图, 翻转=True)
        try:
            x = max(屏左 + 8, min(int(x), 屏右 - 图.width - 8))
        except Exception:
            x = int(x)
        try:
            y = max(屏上 + 8, min(int(y), 屏下 - 图.height - 8))
        except Exception:
            y = max(0, int(y))
        self._位置 = (x, y)
        # ⭐ 1.8.4：**每来一条就是一个新的一代**。
        #   上一句如果正在淡出，这一下就让它作废（见 _淡出 里的代检查）——
        #   不然它走完会 `窗.藏()`，把刚换上新字的这个气泡一起藏掉，
        #   表现就是「连着说话时，每句闪一下就没」。
        self._代 = getattr(self, '_代', 0) + 1
        # 气泡还在（上一句没消失）→ 原地换字，不淡入；已经不见了 → 才淡入
        try:
            刚还挂着 = float(getattr(self, '_可见到', 0) or 0) + 1.0 > time.perf_counter()
        except Exception:
            刚还挂着 = False
        self._显示这页(淡入=not 刚还挂着)
        return True

    # ---------- 翻页 ----------
    def _取消定时(self):
        # ⚠ 1.8.4：`_出定时`（淡出的定时器）以前**没在这里取消** ——
        #   一句说完正在淡出，下一句正好来了：显示() 取消的只是藏/入定时，
        #   淡出还在一帧帧走，走完 `窗.藏()` 把**刚显示出来的新气泡**藏掉。
        #   表现就是「第一句正常，后面每句闪一下就没」。
        for 名 in ('_藏定时', '_入定时', '_出定时'):
            号 = getattr(self, 名, None)
            if 号:
                try:
                    self.根.after_cancel(号)
                except Exception:
                    pass
                setattr(self, 名, None)

    def 正在读多页(self):
        """最后一页也要停够设定的时间，下一条回复才能接上。"""
        return len(self.页们) > 1 and self._藏定时 is not None

    def _显示这页(self, 淡入=False):
        self._取消定时()
        行们 = self.页们[max(0, min(self._第几页, len(self.页们) - 1))]
        图 = self.合成页(行们, self.体, self.行高, self._翻转)
        self.次图 = 图
        self.次位置 = self._位置
        if 淡入:
            # ⭐ 0.9.4：别硬邦邦一下冒出来 —— 先只有框（没字），再淡进来、字随后出来
            底 = self.图.transpose(Image.FLIP_LEFT_RIGHT) if self._翻转 else self.图
            self._底图 = 底.copy()
            self._淡入(0)
        else:
            self.窗.贴图(图, self.次位置[0], self.次位置[1])
            self.窗.显()
        还有下一页 = self._第几页 < len(self.页们) - 1
        # ⭐ 0.9.2：还有下一页就按「每页停几秒」翻；最后一页停够了才淡掉
        等 = self._换页秒 if 还有下一页 else self._停秒
        self._可见到 = time.perf_counter() + 等
        下个 = self._下一页 if 还有下一页 else self.藏
        try:
            self._藏定时 = self.根.after(int(max(0.5, 等) * 1000), 下个)
        except Exception:
            self._藏定时 = None

    def _淡入(self, 步=0, 总=None, 起=None):
        """冒出来：从 94% 大小淡进来，头一下只有框、没有字，字在第二下才出来。

        ⭐ 1.3.0：同样按真实时间推进（`_淡入毫秒`，默认 180ms），主线程忙的时候也不会拖长。
        """
        import time as _t
        if 起 is None:
            起 = _t.perf_counter()
        总 = int(总 if 总 is not None else self._入帧)
        比时 = (_t.perf_counter() - 起) / max(0.04, self._淡入毫秒 / 1000.0)
        if 步 >= 总 or 比时 >= 1.0:
            try:
                self.窗.贴图(self.次图, self.次位置[0], self.次位置[1])
            except Exception:
                pass
            self._入定时 = None
            return
        比时 = min(1.0, max(0.0, 比时))
        比 = 0.94 + 0.06 * 比时
        不透明 = int(255 * (0.30 + 0.70 * 比时))
        源 = self._底图 if 步 == 0 else self.次图
        try:
            图 = 源
            if 比 < 0.999 and 源 is not None:
                宽, 高 = 源.size
                图 = 源.resize((max(1, int(宽 * 比)), max(1, int(高 * 比))), Image.LANCZOS)
            x = self.次位置[0] + (self.次图.size[0] - 图.size[0]) // 2
            y = self.次位置[1] + (self.次图.size[1] - 图.size[1]) // 2
            self.窗.贴图(图, x, y, 不透明=不透明)
            self.窗.显()
        except Exception:
            pass
        try:
            self._入定时 = self.根.after(self._帧间, lambda: self._淡入(步 + 1, 总, 起))
        except Exception:
            self._入定时 = None

    def _下一页(self):
        self._藏定时 = None
        self._第几页 += 1
        self._显示这页()

    def 藏(self):
        self._取消定时()
        self._可见到 = time.perf_counter()
        # 让还在跑的淡出作废（不然它会走完再把窗藏一次）
        self._代 = getattr(self, '_代', 0) + 1
        self._淡出(0)

    def _淡出(self, 步=0, 起=None, 代=None):
        """一点点变淡再消失（分层窗可以给整体不透明度）。

        ⭐ 1.1.0：以前固定 6 帧 × 45ms，一帧跳一格，看着是一顿一顿淡下去的。
        ⭐ 1.3.0：改成**按真实时间**推进 —— 淡出永远是 `_淡出毫秒`（默认 320ms），
          跟「停留几秒」完全无关。以前是按帧数走的，主线程一忙（弹幕、截图）
          每帧的实际间隔就变长，320ms 能拖成 1 秒多，看着就是「消散很慢、不流畅」。
        ⭐ 1.8.4：带**代**跑。淡出走到一半时新消息来了（`显示()` 会把代 +1），
          这一次淡出就作废，**不许再把窗藏掉** —— 连着说话时气泡要一直在，只换字。
        """
        import time as _t
        if 代 is None:
            代 = getattr(self, '_代', 0)
        if getattr(self, '_代', 0) != 代:
            return
        if 起 is None:
            起 = _t.perf_counter()
        比 = (_t.perf_counter() - 起) / max(0.05, self._淡出毫秒 / 1000.0)
        if 比 >= 1.0:
            if getattr(self, '_代', 0) == 代:
                self.窗.藏()
            return
        不透明 = max(0, int(255 * (1.0 - 比)))
        try:
            if self.次图 is not None:
                self.窗.贴图(self.次图, self.次位置[0], self.次位置[1], 不透明=不透明)
        except Exception:
            pass
        try:
            self._出定时 = self.根.after(self._帧间, lambda: self._淡出(步 + 1, 起, 代))
        except Exception:
            self.窗.藏()

    def __del__(self):
        try:
            self.窗.关()
        except Exception:
            pass

    def _球旁边(self, 图, 翻转=False):
        """贴在球的正上方：气泡的尖角指着球，既不盖住球，也不出屏幕。"""
        球框 = getattr(self, '球框', None)
        try:
            if 球框:
                球x, 球y, 球宽, 球高 = [int(v) for v in 球框]
            else:
                位 = self.根.geometry()
                尺寸, 位置 = 位.split('+', 1)[0], 位.split('+', 1)[1]
                球宽, 球高 = [int(v) for v in 尺寸.split('x')]
                球x, 球y = [int(v) for v in 位置.split('+')]
            屏宽 = self.根.winfo_screenwidth()
            屏高 = self.根.winfo_screenheight()
        except Exception:
            球x = 球y = 球宽 = 球高 = 0
            屏宽, 屏高 = 1920, 1080
        # 气泡的尖角在图宽的 24%、底边处；让这个尖角落到球的左上角内侧 →
        # 整体看起来就是「从右上角斜着冒出来」，而不是直愣愣压头顶。
        if 翻转:
            尖x = 球x + int(球宽 * 0.10)
            尖y = 球y + int(球高 * 0.12)
            x = 尖x - int(图.width * 0.80)
        else:
            尖x = 球x + int(球宽 * 0.90)   # 球的上方偏右 → 气泡斜着从右上方出来
            尖y = 球y + int(球高 * 0.12)
            x = 尖x - int(图.width * 0.20)
        y = 尖y - 图.height
        # ⭐ 1.3.1：**按球所在的那块显示器**夹边界（以前用主屏宽高，所以球在副屏时
        #   气泡会被硬拽回主屏）。宠物可以贴边，气泡不能出屏 —— 但只在它自己那块屏里夹。
        屏左, 屏上, 屏右, 屏下 = self._所在屏(球x + 球宽 // 2, 球y + 球高 // 2)
        if y < 屏上 + 8:
            y = 屏上 + 8
        if y + 图.height > 屏下 - 8:
            y = max(屏上 + 8, 屏下 - 图.height - 8)
        x = max(屏左 + 8, min(x, 屏右 - 图.width - 8))
        return (x, y)
