"""鱼搭子 · 桌面小挂件和总面板（独立程序）

鱼图悬浮窗负责方便地呼出总面板；电话、陪看等功能都从总面板进入。

启动：pythonw ball.py（没有黑窗）；自测：python ball.py --selftest；看面板：--demo
"""
import ctypes
import importlib.util
import json
import os
import queue
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# 路径与配置统一交给 paths.py：打包后配置和模型在 %LOCALAPPDATA%\鱼搭子\，
# 老位置的 config.json（里面是开发机上的绝对路径）第一次跑会自动搬过来。
import paths


def 读配置():
    return paths.读配置()


右键日志 = os.path.join(paths.用户目录(), '右键记录.log')


def 记右键(说什么):
    """右键/托盘菜单的取证日志：谁弹的、谁执行的、谁退出的。"""
    try:
        import time as _t
        if os.path.exists(右键日志) and os.path.getsize(右键日志) > 512 * 1024:
            try:
                os.replace(右键日志, 右键日志 + '.1')
            except Exception:
                open(右键日志, 'w', encoding='utf-8').close()
        with open(右键日志, 'a', encoding='utf-8') as f:
            f.write('%s %s\n' % (_t.strftime('%H:%M:%S'), 说什么))
    except Exception:
        pass


def 存配置():
    return paths.写配置(配置)


def 开DPI():
    # 每显示器 DPI 感知（Win10 1703+ 优先 v2）：这样远程把系统缩放从 125% 调到 150% 时，
    # 我们拿到的是「真的变大了」，能自己跟着重排，而不是被 Windows 拉成糊的位图。
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    for 试 in (lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2),
               lambda: ctypes.windll.shcore.SetProcessDpiAwareness(1),
               lambda: ctypes.windll.user32.SetProcessDPIAware()):
        try:
            试()
            return
        except Exception:
            continue


# 窗口收到 WM_DPICHANGED 时记下的新 DPI（0 = 没收到过）
收到的新DPI = 0


def 显示器DPI(窗号=None):
    """按「窗口在哪个显示器」问 DPI（Windows 10 起都有；拿不到返回 0）。

    这个接口跟着显示器走，**会实时变**；GetDpiForWindow 会粘在窗口创建时的值上，不能当唯一依据。
    """
    try:
        u = ctypes.windll.user32
        sh = ctypes.windll.shcore
        u.MonitorFromWindow.restype = ctypes.c_void_p
        u.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        sh.GetDpiForMonitor.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                        ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
        hmon = None
        if 窗号:
            hmon = u.MonitorFromWindow(ctypes.c_void_p(int(窗号)), 2)      # 最近的那个
        if not hmon:
            u.MonitorFromPoint.restype = ctypes.c_void_p
            u.MonitorFromPoint.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            hmon = u.MonitorFromPoint(ctypes.byref(_POINT(0, 0)), 0)
        if not hmon:
            return 0
        x, y = ctypes.c_uint(), ctypes.c_uint()
        if sh.GetDpiForMonitor(ctypes.c_void_p(hmon), 0, ctypes.byref(x), ctypes.byref(y)) != 0:
            return 0
        return int(x.value or 0)
    except Exception:
        return 0


def _颜色们(值, 默认):
    """'#rrggbb' → (r, g, b)；写错了就用默认。"""
    try:
        s = str(值 or '').strip().lstrip('#')
        if len(s) == 6:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except Exception:
        pass
    return 默认


def _字体路(名字):
    """字体名 → 文件路径：站酷快乐体（自带的）或本机任意字体；给了路径直接用。"""
    名 = str(名字 or '').strip()
    自带 = os.path.join(HERE, 'assets', '字体', 'ZCOOLKuaiLe-Regular.ttf')
    if not 名 or 名 in ('站酷快乐体', 'ZCOOL KuaiLe'):
        return 自带 if os.path.exists(自带) else None
    try:
        import 字体表
        落 = 字体表.找(名)
        if 落:
            return 落
    except Exception:
        pass
    return 自带 if os.path.exists(自带) else None


def 系统缩放(窗号=None):
    """当前屏幕缩放比：96 DPI = 1.0（125% 就是 1.25）。拿不到就当 1.0。

    顺序（越靠前越可信）：
      ① 窗口收到的 WM_DPICHANGED ② 显示器当前 DPI
      ③ 系统 DPI ④ 老的 GetDeviceCaps
    ⚠️ 不先用 GetDpiForWindow：它在缩放改了以后可能还返回老值。
    """
    try:
        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        dpi = int(globals().get('收到的新DPI') or 0)
        if dpi <= 0:
            dpi = 显示器DPI(窗号)
        if dpi <= 0:
            try:
                dpi = int(u.GetDpiForSystem())
            except Exception:
                dpi = 0
        if dpi <= 0:
            h = g.GetDC(0)
            dpi = int(g.GetDeviceCaps(h, 88))      # LOGPIXELSX
            g.ReleaseDC(0, h)
        if dpi <= 0:
            return 1.0
        return max(0.5, min(4.0, dpi / 96.0))
    except Exception:
        return 1.0


配置 = 读配置()
本机直连 = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 本机端口不走代理

# —— 淡蓝磨砂配色 ——
淡底 = '#dcebf3'
淡卡 = '#edf5fa'
淡卡亮 = '#f8fcfe'
淡线 = '#b6cbd8'
字深 = '#304858'
字次 = '#718797'
禁用 = '#a8b9c4'
绿 = '#2f8f63'
红 = '#c0566a'

# 系统自带线图标（Segoe MDL2 Assets）
图标字 = {
    '电话': '\uE717',
    '直播': '\uE7F4',
    '游戏': '\uE7FC',
}
图标字体 = 'Segoe MDL2 Assets'


def 命中悬浮按钮(x, y, 边长):
    """图上的热区：下面三颗圆钮各是一个功能，**上面那一大块是设置页**。

    返回 '电话' / '直播' / '游戏' / '设置' / None（None = 既不是按钮也不是上面那块，
    只能用来拖动窗口）。
    """
    nx, ny = x / 边长, y / 边长
    for 名称, cx, cy, rx, ry in (
            ('电话', 0.272, 0.850, 0.105, 0.110),
            ('直播', 0.494, 0.848, 0.105, 0.110),
            ('游戏', 0.722, 0.847, 0.105, 0.110)):
        if ((nx - cx) / rx) ** 2 + ((ny - cy) / ry) ** 2 <= 1:
            return 名称
    # 上面那一整块（大肥鱼的头 + 身子 + 旁边的鲸鱼）= 设置页
    if ny < 0.68:
        return '设置'
    return None


# ---------------- Windows 原生：圆窗 / 圆角窗 / 磨砂 ----------------
def _hwnd(窗):
    u = ctypes.windll.user32
    u.GetParent.argtypes = [ctypes.c_void_p]
    u.GetParent.restype = ctypes.c_void_p
    return u.GetParent(ctypes.c_void_p(窗.winfo_id()))


def 定圆窗(窗, 尺寸):
    try:
        窗.update_idletasks()
        rgn = ctypes.windll.gdi32.CreateEllipticRgn(0, 0, int(尺寸), int(尺寸))
        ctypes.windll.user32.SetWindowRgn(_hwnd(窗), rgn, True)
        return True
    except Exception:
        return False


def 定圆角窗(窗, 宽, 高, 圆=18):
    try:
        窗.update_idletasks()
        rgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, int(宽) + 1, int(高) + 1, 圆, 圆)
        ctypes.windll.user32.SetWindowRgn(_hwnd(窗), rgn, True)
        return True
    except Exception:
        return False


def 定形窗(窗, 透明图, 边长, 阈值=90):
    """窗口形状 = 图上不透明的轮廓（呆毛、尾巴、旁边的东西全留着，不是个球）。"""
    try:
        from PIL import Image
        窗.update_idletasks()
        蒙 = 透明图.split()[-1].resize((边长, 边长), Image.LANCZOS)
        蒙 = 蒙.point(lambda v: 255 if v >= 阈值 else 0)
        px = 蒙.load()
        gdi = ctypes.windll.gdi32
        user32 = ctypes.windll.user32
        gdi.CreateRectRgn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        gdi.CreateRectRgn.restype = ctypes.c_void_p
        gdi.CombineRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
        gdi.CombineRgn.restype = ctypes.c_int
        gdi.DeleteObject.argtypes = [ctypes.c_void_p]
        gdi.DeleteObject.restype = ctypes.c_int
        user32.SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
        user32.SetWindowRgn.restype = ctypes.c_int
        总 = gdi.CreateRectRgn(0, 0, 0, 0)
        for y in range(边长):
            x = 0
            while x < 边长:
                if px[x, y]:
                    x0 = x
                    while x < 边长 and px[x, y]:
                        x += 1
                    片 = gdi.CreateRectRgn(x0, y, x, y + 1)
                    gdi.CombineRgn(总, 总, 片, 2)
                    gdi.DeleteObject(片)
                else:
                    x += 1
        user32.SetWindowRgn(_hwnd(窗), 总, True)
        return True
    except Exception:
        return False


class _ACCENT(ctypes.Structure):
    _fields_ = [('AccentState', ctypes.c_int),
                ('AccentFlags', ctypes.c_int),
                ('GradientColor', ctypes.c_uint),
                ('AnimationId', ctypes.c_int)]


class _WINCOMP(ctypes.Structure):
    _fields_ = [('Attribute', ctypes.c_int),
                ('Data', ctypes.POINTER(_ACCENT)),
                ('SizeOfData', ctypes.c_size_t)]


def 磨砂(窗, 红加绿蓝=(220, 236, 250), 不透明=200, 模糊=4):
    """Windows 原生毛玻璃（accent 4 = 亚克力）。失败就算了，不影响用。"""
    try:
        窗.update_idletasks()
        r, g, b = 红加绿蓝
        色 = (int(不透明) << 24) | (b << 16) | (g << 8) | r     # 注意是 ABGR
        acc = _ACCENT(模糊, 2, 色, 0)
        data = _WINCOMP(19, ctypes.pointer(acc), ctypes.sizeof(acc))
        ctypes.windll.user32.SetWindowCompositionAttribute(_hwnd(窗), ctypes.byref(data))
        return True
    except Exception:
        return False


class _POINT(ctypes.Structure):
    _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]


class _SIZE(ctypes.Structure):
    _fields_ = [('cx', ctypes.c_long), ('cy', ctypes.c_long)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ('biSize', ctypes.c_uint32), ('biWidth', ctypes.c_long),
        ('biHeight', ctypes.c_long), ('biPlanes', ctypes.c_uint16),
        ('biBitCount', ctypes.c_uint16), ('biCompression', ctypes.c_uint32),
        ('biSizeImage', ctypes.c_uint32), ('biXPelsPerMeter', ctypes.c_long),
        ('biYPelsPerMeter', ctypes.c_long), ('biClrUsed', ctypes.c_uint32),
        ('biClrImportant', ctypes.c_uint32),
    ]


class _RGBQUAD(ctypes.Structure):
    _fields_ = [('rgbBlue', ctypes.c_ubyte), ('rgbGreen', ctypes.c_ubyte),
                ('rgbRed', ctypes.c_ubyte), ('rgbReserved', ctypes.c_ubyte)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [('bmiHeader', _BITMAPINFOHEADER), ('bmiColors', _RGBQUAD * 1)]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [('BlendOp', ctypes.c_ubyte), ('BlendFlags', ctypes.c_ubyte),
                ('SourceConstantAlpha', ctypes.c_ubyte), ('AlphaFormat', ctypes.c_ubyte)]


_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
                              ctypes.c_size_t, ctypes.c_ssize_t)


class _WNDCLASS(ctypes.Structure):
    _fields_ = [('style', ctypes.c_uint), ('lpfnWndProc', _WNDPROC),
                ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                ('hInstance', ctypes.c_void_p), ('hIcon', ctypes.c_void_p),
                ('hCursor', ctypes.c_void_p), ('hbrBackground', ctypes.c_void_p),
                ('lpszMenuName', ctypes.c_wchar_p), ('lpszClassName', ctypes.c_wchar_p)]


class 分层悬浮窗:
    """Windows 每像素透明的鱼图窗口；不做二值裁边，保留原图的柔和边缘。"""

    _WS_POPUP = 0x80000000
    _WS_EX_TOPMOST = 0x00000008
    _WS_EX_TOOLWINDOW = 0x00000080
    _WS_EX_LAYERED = 0x00080000
    _ULW_ALPHA = 0x00000002
    _AC_SRC_OVER = 0
    _AC_SRC_ALPHA = 1
    _WM_MOUSEMOVE = 0x0200
    _WM_LBUTTONDOWN = 0x0201
    _WM_LBUTTONUP = 0x0202
    _WM_RBUTTONUP = 0x0205
    _WM_MOUSEACTIVATE = 0x0021
    _MK_LBUTTON = 0x0001
    _MA_NOACTIVATE = 3
    _SW_HIDE = 0
    _SW_SHOWNOACTIVATE = 4
    _SWP_NOSIZE = 0x0001
    _SWP_NOACTIVATE = 0x0010
    _SWP_SHOWWINDOW = 0x0040
    _SM_XVIRTUALSCREEN = 76
    _SM_YVIRTUALSCREEN = 77
    _SM_CXVIRTUALSCREEN = 78
    _SM_CYVIRTUALSCREEN = 79

    def __init__(self, tk, 图片, 边长, 位置, on_action, on_right_click, on_moved):
        self.tk = tk
        self.图片 = 图片
        self.边长 = int(边长)
        self.x, self.y = map(int, 位置)
        self.on_action = on_action
        self.on_right_click = on_right_click
        self.on_moved = on_moved
        self._按下 = None
        self._拖过 = False
        self._类名 = 'FishBuddyLayeredWindow_%d' % os.getpid()
        self._回调 = _WNDPROC(self._消息)
        self._屏DC = None
        self._内存DC = None
        self._位图 = None
        self._旧位图 = None
        self._像素 = ctypes.c_void_p()
        self._窗口 = None
        self._注册窗口类()
        self._建位图()
        self._建窗口()
        self._画(self.x, self.y)
        ctypes.windll.user32.ShowWindow(self._窗口, self._SW_SHOWNOACTIVATE)

    @property
    def 可见(self):
        return bool(self._窗口 and ctypes.windll.user32.IsWindowVisible(self._窗口))

    def _注册窗口类(self):
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
        user32.IsWindowVisible.restype = ctypes.c_int
        user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.ShowWindow.restype = ctypes.c_int
        user32.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
        user32.GetCursorPos.restype = ctypes.c_int
        user32.SetCapture.argtypes = [ctypes.c_void_p]
        user32.SetCapture.restype = ctypes.c_void_p
        user32.ReleaseCapture.restype = ctypes.c_int
        user32.DestroyWindow.argtypes = [ctypes.c_void_p]
        user32.DestroyWindow.restype = ctypes.c_int
        user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.ReleaseDC.restype = ctypes.c_int
        user32.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                          ctypes.c_size_t, ctypes.c_ssize_t]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASS)]
        user32.RegisterClassW.restype = ctypes.c_ushort
        kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        wc = _WNDCLASS(0, self._回调, 0, 0, kernel32.GetModuleHandleW(None),
                       None, None, None, None, self._类名)
        if not user32.RegisterClassW(ctypes.byref(wc)):
            raise ctypes.WinError(ctypes.get_last_error())

    def _建位图(self):
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        user32.GetDC.argtypes = [ctypes.c_void_p]
        user32.GetDC.restype = ctypes.c_void_p
        gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
        gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
        gdi32.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.POINTER(_BITMAPINFO),
                                          ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p),
                                          ctypes.c_void_p, ctypes.c_uint32]
        gdi32.CreateDIBSection.restype = ctypes.c_void_p
        gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        gdi32.SelectObject.restype = ctypes.c_void_p
        self._屏DC = user32.GetDC(None)
        self._内存DC = gdi32.CreateCompatibleDC(self._屏DC)
        if not self._屏DC or not self._内存DC:
            raise ctypes.WinError(ctypes.get_last_error())
        头 = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), self.边长,
                              -self.边长, 1, 32, 0, 0, 0, 0, 0, 0)
        信息 = _BITMAPINFO(头, (_RGBQUAD * 1)())
        self._位图 = gdi32.CreateDIBSection(self._屏DC, ctypes.byref(信息), 0,
                                          ctypes.byref(self._像素), None, 0)
        if not self._位图 or not self._像素:
            raise ctypes.WinError(ctypes.get_last_error())
        self._旧位图 = gdi32.SelectObject(self._内存DC, self._位图)
        self._写像素()

    def _写像素(self):
        from PIL import Image
        缩 = self.图片.resize((self.边长, self.边长), Image.LANCZOS).convert('RGBA')
        rgba = 缩.tobytes()
        bgra = bytearray(len(rgba))
        for i in range(0, len(rgba), 4):
            r, g, b, a = rgba[i:i + 4]
            bgra[i] = b * a // 255
            bgra[i + 1] = g * a // 255
            bgra[i + 2] = r * a // 255
            bgra[i + 3] = a
        ctypes.memmove(self._像素, bytes(bgra), len(bgra))

    def _建窗口(self):
        user32 = ctypes.windll.user32
        user32.CreateWindowExW.argtypes = [ctypes.c_uint, ctypes.c_wchar_p,
                                           ctypes.c_wchar_p, ctypes.c_uint,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                                           ctypes.c_void_p, ctypes.c_void_p]
        user32.CreateWindowExW.restype = ctypes.c_void_p
        self._窗口 = user32.CreateWindowExW(
            self._WS_EX_LAYERED | self._WS_EX_TOPMOST | self._WS_EX_TOOLWINDOW,
            self._类名, '鱼搭子', self._WS_POPUP, self.x, self.y,
            self.边长, self.边长, None, None,
            ctypes.windll.kernel32.GetModuleHandleW(None), None)
        if not self._窗口:
            raise ctypes.WinError(ctypes.get_last_error())

    def _画(self, x, y):
        user32 = ctypes.windll.user32
        user32.UpdateLayeredWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                               ctypes.POINTER(_POINT), ctypes.POINTER(_SIZE),
                                               ctypes.c_void_p, ctypes.POINTER(_POINT),
                                               ctypes.c_uint32, ctypes.POINTER(_BLENDFUNCTION),
                                               ctypes.c_uint]
        user32.UpdateLayeredWindow.restype = ctypes.c_int
        目标 = _POINT(int(x), int(y))
        大小 = _SIZE(self.边长, self.边长)
        源 = _POINT(0, 0)
        混合 = _BLENDFUNCTION(self._AC_SRC_OVER, 0, 255, self._AC_SRC_ALPHA)
        if not user32.UpdateLayeredWindow(self._窗口, self._屏DC, ctypes.byref(目标),
                                          ctypes.byref(大小), self._内存DC,
                                          ctypes.byref(源), 0, ctypes.byref(混合),
                                          self._ULW_ALPHA):
            raise ctypes.WinError(ctypes.get_last_error())
        self.x, self.y = int(x), int(y)

    def _屏幕范围(self):
        u = ctypes.windll.user32
        u.GetSystemMetrics.argtypes = [ctypes.c_int]
        u.GetSystemMetrics.restype = ctypes.c_int
        return (u.GetSystemMetrics(self._SM_XVIRTUALSCREEN),
                u.GetSystemMetrics(self._SM_YVIRTUALSCREEN),
                u.GetSystemMetrics(self._SM_CXVIRTUALSCREEN),
                u.GetSystemMetrics(self._SM_CYVIRTUALSCREEN))

    def _限位置(self, x, y):
        sx, sy, sw, sh = self._屏幕范围()
        return (max(sx, min(int(x), sx + sw - self.边长)),
                max(sy, min(int(y), sy + sh - self.边长)))

    def _命中按钮(self, x, y):
        return 命中悬浮按钮(x, y, self.边长)

    def _移动到(self, x, y):
        x, y = self._限位置(x, y)
        self._画(x, y)

    def 显示(self):
        if self._窗口:
            ctypes.windll.user32.ShowWindow(self._窗口, self._SW_SHOWNOACTIVATE)

    def 隐藏(self):
        if self._窗口:
            ctypes.windll.user32.ShowWindow(self._窗口, self._SW_HIDE)

    def 销毁(self):
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        gdi32.DeleteObject.restype = ctypes.c_int
        gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
        gdi32.DeleteDC.restype = ctypes.c_int
        if self._窗口:
            user32.DestroyWindow(self._窗口)
            self._窗口 = None
        if self._内存DC:
            if self._旧位图:
                gdi32.SelectObject(self._内存DC, self._旧位图)
            if self._位图:
                gdi32.DeleteObject(self._位图)
            gdi32.DeleteDC(self._内存DC)
            self._内存DC = None
        if self._屏DC:
            user32.ReleaseDC(None, self._屏DC)
            self._屏DC = None

    def _消息(self, hwnd, msg, wparam, lparam):
        user32 = ctypes.windll.user32
        # ⭐ 0.0.9：Windows 改了缩放会给我们发 WM_DPICHANGED —— 这是最准的信儿，
        #   记下来让主线程重排（GetDpiForWindow 会「粘」在窗口创建时的 DPI 上，不可靠）。
        if msg == 0x02E0:
            try:
                新 = int(wparam) & 0xFFFF
                if 新 > 0:
                    global 收到的新DPI
                    收到的新DPI = 新
            except Exception:
                pass
            return 0
        if msg == self._WM_MOUSEACTIVATE:
            return self._MA_NOACTIVATE
        if msg == self._WM_LBUTTONDOWN:
            pt = _POINT()
            if user32.GetCursorPos(ctypes.byref(pt)):
                动作 = self._命中按钮(pt.x - self.x, pt.y - self.y)
                self._按下 = (pt.x, pt.y, self.x, self.y, 动作)
                self._拖过 = False
                user32.SetCapture(hwnd)
            return 0
        if msg == self._WM_MOUSEMOVE and self._按下 and (wparam & self._MK_LBUTTON):
            pt = _POINT()
            if user32.GetCursorPos(ctypes.byref(pt)):
                x0, y0, wx, wy, 动作 = self._按下
                dx, dy = pt.x - x0, pt.y - y0
                if 动作 is None and (abs(dx) > 4 or abs(dy) > 4):
                    self._拖过 = True
                if self._拖过:
                    try:
                        self._移动到(wx + dx, wy + dy)
                    except Exception:
                        pass
            return 0
        if msg == self._WM_LBUTTONUP:
            if self._按下 is None:
                return 0
            user32.ReleaseCapture()
            动过 = self._拖过
            按下 = self._按下
            self._按下 = None
            self._拖过 = False
            try:
                if 动过:
                    self.on_moved(self.x, self.y)
                elif 按下 and 按下[4]:
                    pt = _POINT()
                    if user32.GetCursorPos(ctypes.byref(pt)):
                        松开处 = self._命中按钮(pt.x - self.x, pt.y - self.y)
                        if 松开处 == 按下[4]:
                            self.tk.after_idle(lambda k=松开处: self.on_action(k))
            except Exception:
                pass
            return 0
        if msg == self._WM_RBUTTONUP:
            try:
                self.tk.after_idle(self.on_right_click)
            except Exception:
                pass
            return 0
        return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)


class _GUID(ctypes.Structure):
    _fields_ = [('Data1', ctypes.c_uint32), ('Data2', ctypes.c_uint16),
                ('Data3', ctypes.c_uint16), ('Data4', ctypes.c_ubyte * 8)]


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ('cbSize', ctypes.c_uint32), ('hWnd', ctypes.c_void_p),
        ('uID', ctypes.c_uint32), ('uFlags', ctypes.c_uint32),
        ('uCallbackMessage', ctypes.c_uint32), ('hIcon', ctypes.c_void_p),
        ('szTip', ctypes.c_wchar * 128), ('dwState', ctypes.c_uint32),
        ('dwStateMask', ctypes.c_uint32), ('szInfo', ctypes.c_wchar * 256),
        ('uTimeoutOrVersion', ctypes.c_uint32),
        ('szInfoTitle', ctypes.c_wchar * 64), ('dwInfoFlags', ctypes.c_uint32),
        ('guidItem', _GUID), ('hBalloonIcon', ctypes.c_void_p),
    ]


class Tk分层图:
    """把带透明通道的鱼图绘到 Tk 窗口上，不另建原生消息窗口。"""

    _GWL_EXSTYLE = -20
    _WS_EX_LAYERED = 0x00080000
    _ULW_ALPHA = 0x00000002
    _AC_SRC_OVER = 0
    _AC_SRC_ALPHA = 1

    def __init__(self, 窗, 图片, 边长):
        self.窗口 = _hwnd(窗)
        self.图片 = 图片
        self.边长 = int(边长)
        self._桌面DC = None
        self._内存DC = None
        self._位图 = None
        self._旧位图 = None
        self._像素 = ctypes.c_void_p()
        self._旧样式 = None
        self._设置接口()
        self._启用分层样式()
        try:
            self._建位图()
        except Exception:
            self.销毁()
            raise

    def _设置接口(self):
        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        u.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        u.SetWindowLongPtrW.restype = ctypes.c_void_p
        u.GetDC.argtypes = [ctypes.c_void_p]
        u.GetDC.restype = ctypes.c_void_p
        u.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        u.ReleaseDC.restype = ctypes.c_int
        g.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
        g.CreateCompatibleDC.restype = ctypes.c_void_p
        g.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.POINTER(_BITMAPINFO),
                                       ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p),
                                       ctypes.c_void_p, ctypes.c_uint32]
        g.CreateDIBSection.restype = ctypes.c_void_p
        g.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        g.SelectObject.restype = ctypes.c_void_p
        g.DeleteObject.argtypes = [ctypes.c_void_p]
        g.DeleteObject.restype = ctypes.c_int
        g.DeleteDC.argtypes = [ctypes.c_void_p]
        g.DeleteDC.restype = ctypes.c_int
        u.UpdateLayeredWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                          ctypes.POINTER(_POINT), ctypes.POINTER(_SIZE),
                                          ctypes.c_void_p, ctypes.POINTER(_POINT),
                                          ctypes.c_uint32, ctypes.POINTER(_BLENDFUNCTION),
                                          ctypes.c_uint]
        u.UpdateLayeredWindow.restype = ctypes.c_int

    def _启用分层样式(self):
        u = ctypes.windll.user32
        self._旧样式 = u.GetWindowLongPtrW(self.窗口, self._GWL_EXSTYLE)
        新样式 = int(self._旧样式) | self._WS_EX_LAYERED
        ctypes.set_last_error(0)
        u.SetWindowLongPtrW(self.窗口, self._GWL_EXSTYLE, ctypes.c_void_p(新样式))
        错误 = ctypes.get_last_error()
        if 错误:
            raise ctypes.WinError(错误)

    def _建位图(self):
        from PIL import Image
        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        self._桌面DC = u.GetDC(None)
        self._内存DC = g.CreateCompatibleDC(self._桌面DC)
        if not self._桌面DC or not self._内存DC:
            raise ctypes.WinError(ctypes.get_last_error())
        头 = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), self.边长,
                              -self.边长, 1, 32, 0, 0, 0, 0, 0, 0)
        信息 = _BITMAPINFO(头, (_RGBQUAD * 1)())
        self._位图 = g.CreateDIBSection(self._桌面DC, ctypes.byref(信息), 0,
                                        ctypes.byref(self._像素), None, 0)
        if not self._位图 or not self._像素:
            raise ctypes.WinError(ctypes.get_last_error())
        self._旧位图 = g.SelectObject(self._内存DC, self._位图)
        缩 = self.图片.resize((self.边长, self.边长), Image.LANCZOS).convert('RGBA')
        rgba = 缩.tobytes()
        bgra = bytearray(len(rgba))
        for i in range(0, len(rgba), 4):
            r, green, b, a = rgba[i:i + 4]
            bgra[i] = b * a // 255
            bgra[i + 1] = green * a // 255
            bgra[i + 2] = r * a // 255
            bgra[i + 3] = a
        ctypes.memmove(self._像素, bytes(bgra), len(bgra))

    def 更新(self, x, y):
        dest = _POINT(int(x), int(y))
        size = _SIZE(self.边长, self.边长)
        source = _POINT(0, 0)
        blend = _BLENDFUNCTION(self._AC_SRC_OVER, 0, 255, self._AC_SRC_ALPHA)
        if not ctypes.windll.user32.UpdateLayeredWindow(
                self.窗口, self._桌面DC, ctypes.byref(dest), ctypes.byref(size),
                self._内存DC, ctypes.byref(source), 0, ctypes.byref(blend), self._ULW_ALPHA):
            raise ctypes.WinError(ctypes.get_last_error())

    def 销毁(self):
        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        if self._内存DC:
            if self._旧位图:
                g.SelectObject(self._内存DC, self._旧位图)
            if self._位图:
                g.DeleteObject(self._位图)
            g.DeleteDC(self._内存DC)
            self._内存DC = None
        if self._桌面DC:
            u.ReleaseDC(None, self._桌面DC)
            self._桌面DC = None
        if self._旧样式 is not None and self.窗口:
            u.SetWindowLongPtrW(self.窗口, self._GWL_EXSTYLE,
                                ctypes.c_void_p(int(self._旧样式)))
            self._旧样式 = None


class _MSG(ctypes.Structure):
    _fields_ = [('hwnd', ctypes.c_void_p), ('message', ctypes.c_uint),
                ('wParam', ctypes.c_size_t), ('lParam', ctypes.c_ssize_t),
                ('time', ctypes.c_uint), ('pt', _POINT)]


class Windows托盘:
    """把鱼图程序放进 Windows 托盘；托盘右键出菜单，双击把悬浮窗叫回来。

    ⚠⚠ 为什么托盘要**单独一个线程**（2026-10-26 血的教训）：
      托盘图标的点击是 Explorer **同步投递**到窗口过程里的。那一刻 Tk 的消息循环正跑着、
      GIL 是放开状态，Python 的 ctypes 回调一进去就是
          Fatal Python error: PyEval_RestoreThread: ... GIL is released (thread state is NULL)
      进程直接没（退出码 0xC0000409，栈破坏），连日志都写不出来 —— 表现就是「右键一下鱼就没了」。
      ⇒ 托盘窗口 + 它自己的 `GetMessage/DispatchMessage` 放在独立线程里；
        回调**只置一个标记**，主线程用 `根.after` 轮询标记再去弹菜单。
        两边都不跨线程碰 Tk，也不在「GIL 放开」的时刻跑 Python。
    """

    _NIM_ADD = 0
    _NIM_DELETE = 2
    _NIF_MESSAGE = 0x00000001
    _NIF_ICON = 0x00000002
    _NIF_TIP = 0x00000004
    _IMAGE_ICON = 1
    _LR_LOADFROMFILE = 0x00000010
    _LR_DEFAULTSIZE = 0x00000040
    _WS_POPUP = 0x80000000
    _WS_EX_TOOLWINDOW = 0x00000080
    _WM_APP = 0x8000
    _WM_RBUTTONUP = 0x0205
    _WM_CONTEXTMENU = 0x007B
    _WM_LBUTTONDBLCLK = 0x0203
    _WM_CLOSE = 0x0010

    def __init__(self, 根, on_menu, on_show, 图标路径):
        self.根 = 根
        self.on_menu = on_menu
        self.on_show = on_show
        self.图标路径 = 图标路径
        self.消息号 = self._WM_APP + 0x51
        self._类名 = 'FishBuddyTray_%d_%d' % (os.getpid(), id(self))
        self._实例 = None
        self.窗口 = None
        self._图标 = None
        self._数据 = _NOTIFYICONDATAW()
        self._回调 = None
        self._要弹菜单 = False
        self._要显示 = False
        self._停 = False
        self._就绪 = threading.Event()
        self._线程 = threading.Thread(target=self._线程跑, name='fishbuddy-tray', daemon=True)
        self._线程.start()
        if not self._就绪.wait(5):
            raise RuntimeError('托盘线程没起来')
        self.根.after(150, self._看看托盘)

    # ---------- 托盘线程 ----------
    def _线程跑(self):
        u = ctypes.windll.user32
        try:
            self._回调 = _WNDPROC(self._消息)      # 在托盘线程里创建，回调也在这个线程被调用
            self._注册窗口()
            self._添加图标(self.图标路径)
        except Exception:
            self._就绪.set()
            return
        self._就绪.set()
        msg = _MSG()
        while not self._停:
            r = u.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r in (0, -1):
                break
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))
        try:
            self._删图标()
        except Exception:
            pass

    def _注册窗口(self):
        u = ctypes.windll.user32
        k = ctypes.windll.kernel32
        u.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASS)]
        u.RegisterClassW.restype = ctypes.c_ushort
        u.CreateWindowExW.argtypes = [ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_wchar_p,
                                      ctypes.c_uint, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                      ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        u.CreateWindowExW.restype = ctypes.c_void_p
        u.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        u.DefWindowProcW.restype = ctypes.c_ssize_t
        k.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        k.GetModuleHandleW.restype = ctypes.c_void_p
        self._实例 = k.GetModuleHandleW(None)
        wc = _WNDCLASS(0, self._回调, 0, 0, self._实例, None, None, None, None, self._类名)
        if not u.RegisterClassW(ctypes.byref(wc)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.窗口 = u.CreateWindowExW(
            self._WS_EX_TOOLWINDOW, self._类名, '鱼搭子托盘', self._WS_POPUP,
            0, 0, 0, 0, None, None, self._实例, None)
        if not self.窗口:
            raise ctypes.WinError(ctypes.get_last_error())

    def _添加图标(self, 图标路径):
        u = ctypes.windll.user32
        u.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        u.LoadImageW.restype = ctypes.c_void_p
        self._图标 = u.LoadImageW(None, 图标路径, self._IMAGE_ICON, 0, 0,
                                 self._LR_LOADFROMFILE | self._LR_DEFAULTSIZE)
        if not self._图标:
            raise ctypes.WinError(ctypes.get_last_error())
        shell = ctypes.windll.shell32
        shell.Shell_NotifyIconW.argtypes = [ctypes.c_uint, ctypes.POINTER(_NOTIFYICONDATAW)]
        shell.Shell_NotifyIconW.restype = ctypes.c_int
        self._数据.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
        self._数据.hWnd = self.窗口
        self._数据.uID = 1
        self._数据.uFlags = self._NIF_MESSAGE | self._NIF_ICON | self._NIF_TIP
        self._数据.uCallbackMessage = self.消息号
        self._数据.hIcon = self._图标
        self._数据.szTip = '鱼搭子'
        if not shell.Shell_NotifyIconW(self._NIM_ADD, ctypes.byref(self._数据)):
            raise ctypes.WinError(ctypes.get_last_error())

    def _删图标(self):
        if not self.窗口:
            return
        try:
            ctypes.windll.shell32.Shell_NotifyIconW(
                self._NIM_DELETE, ctypes.byref(self._数据))
        except Exception:
            pass

    def _消息(self, hwnd, msg, wparam, lparam):
        """⚠ 这个函数跑在**托盘线程**里：只许置标记，不许碰 Tk、不许做重活。"""
        try:
            if msg == self.消息号:
                ev = int(lparam) & 0xFFFF
                if ev in (self._WM_RBUTTONUP, self._WM_CONTEXTMENU):
                    self._要弹菜单 = True
                    return 0
                if ev == self._WM_LBUTTONDBLCLK:
                    self._要显示 = True
                    return 0
                return 0
        except Exception:
            pass
        return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # ---------- 主线程 ----------
    def _看看托盘(self):
        if self._要弹菜单:
            self._要弹菜单 = False
            try:
                self.on_menu()
            except Exception as e:
                记右键('弹托盘菜单失败：%s' % e)
        if self._要显示:
            self._要显示 = False
            try:
                self.on_show()
            except Exception:
                pass
        try:
            self.根.after(150, self._看看托盘)
        except Exception:
            pass

    def 销毁(self):
        self._停 = True
        try:
            if self.窗口:
                ctypes.windll.user32.PostMessageW(
                    ctypes.c_void_p(int(self.窗口)), self._WM_CLOSE, 0, 0)
        except Exception:
            pass
        try:
            self._线程.join(1.5)
        except Exception:
            pass
        if self._图标:
            try:
                ctypes.windll.user32.DestroyIcon(ctypes.c_void_p(int(self._图标)))
            except Exception:
                pass
            self._图标 = None



class 鱼搭子:
    def __init__(self, tk):
        from PIL import Image, ImageTk
        self.tk, self.ImageTk = tk, ImageTk
        self.原图 = Image.open(os.path.join(HERE, 'assets', '浮窗.png')).convert('RGBA')

        self.根 = tk.Tk()
        self.根.withdraw()
        # ⭐ 0.8.2：在根上设一次默认图标，
        #   之后开的每个 Toplevel（设置页、面板、弹幕框）都会继承这个。
        try:
            图路 = os.path.join(HERE, 'assets', '鱼搭子.png')
            if os.path.exists(图路):
                self._应用图标 = ImageTk.PhotoImage(Image.open(图路).resize((64, 64), Image.LANCZOS))
                self.根.iconphoto(True, self._应用图标)
        except Exception:
            pass
        # ⭐ 屏幕缩放（远程把缩放调大 / 换了显示器）：别处都变大了，这里也得跟着变
        self.显示缩放 = 系统缩放()
        # ⭐ 0.6.0：基准固定成 100%（1.0），不再记「第一次跑时的缩放」——
        #   否则远程把缩放改过一回，回到本地就会按当时的基准算出一个巨球。
        if float(配置.get('ui_scale_base') or 0) != 1.0:
            配置['ui_scale_base'] = 1.0
            try:
                paths.写配置(配置)
            except Exception:
                pass
        # ⭐ 0.6.4：把基准换算一次 ——
        #   老配置是 ball_size=420、调到过 40%（168px）；现在 100% 就该是这 168px。
        #   换算完显示 100%、球还是原来那么大。
        if not 配置.get('尺寸换基准'):
            try:
                底 = int(配置.get('ball_size') or 420)
                倍 = float(配置.get('ui_scale') or 1.0)
                if 底 == 420:
                    配置['ball_size'] = 168
                    配置['ui_scale'] = max(0.2, min(2.0, round(倍 / 0.4, 2)))
                配置['尺寸换基准'] = True
                paths.写配置(配置)
            except Exception:
                pass
        self.球径 = self._算球径()
        self._设字缩放()
        self.配置 = 配置            # 设置页和程序用的是同一份（改了就生效）
        x, y = self._球位置()
        self._浮窗位置 = (x, y)
        self.面板 = None
        self.外框 = None
        self.页区 = None
        self.页框 = {}
        self.当前页 = None
        self.页标题 = None
        self.窗口图标 = None
        self._图标已设置 = False
        self.通话 = False
        self.耳朵 = None
        self.陪看模块 = None
        self.陪看程序 = None
        self.陪看承载 = None
        self.浮窗 = None
        self.分层图 = None
        self.托盘 = None
        self.球画 = None
        self.球图 = None
        self.待显示 = queue.Queue()
        self.未读回话 = []
        self.回话口 = None
        try:
            import reply_server
            口 = reply_server.回话口(
                lambda t: self.待显示.put(('回复', t)),
                端口=配置.get('回话端口', 8778),
                on_devices=self._列麦克风,
                on_device=self.换麦克风,
                # ⭐ 1.1.1：她要自己开口时，插件来这里要一张当下的画面
                on_shot=self._拍一张给插件,
            )
            if 口.开始():
                self.回话口 = 口
            else:
                self.待显示.put(('提示', '回话口占不上（端口 %s）：%s' % (口.端口, 口.状态.get('错', ''))))
        except Exception as e:
            self.待显示.put(('提示', '回话口没起来：%s' % e))
        self._拖动起点 = None
        self._拖过 = False
        self._建Tk浮窗(x, y)
        try:
            self.托盘 = Windows托盘(self.根, self._托盘菜单, self._显示悬浮窗,
                                  os.path.join(HERE, 'assets', '鱼搭子.ico'))
        except Exception:
            self.托盘 = None
        self.根.after(120, self._刷屏)
        self.根.after(500, self._看缩放)     # 远程调了屏幕缩放 → 自己跟着变
        self.根.after(900, self._热键轮询)   # ⭐ 1.0.2：全局截图热键
        # ⭐ 1.0.6：一起来就把语音模型读进内存（后台线程）——
        #   不然第一次按电话/按住说话要等它加载好几秒，看着像「按了没反应」。
        try:
            if paths.语音就绪():
                threading.Thread(target=self._预热语音, daemon=True).start()
        except Exception:
            pass

    def _预热语音(self):
        try:
            from ear import 预热
            import time as _t
            起 = _t.time()
            预热(paths.模型目录(), 2)
            记右键('语音引擎预热好了（%.1f 秒）' % (_t.time() - 起))
        except Exception as e:
            记右键('语音引擎预热没成：%s' % e)

    # ---------- 球 ----------
    def _虚拟屏幕(self):
        try:
            if os.name == 'nt':
                u = ctypes.windll.user32
                return (u.GetSystemMetrics(76), u.GetSystemMetrics(77),
                        u.GetSystemMetrics(78), u.GetSystemMetrics(79))
        except Exception:
            pass
        return (0, 0, self.根.winfo_screenwidth(), self.根.winfo_screenheight())

    def _限位置(self, x, y):
        sx, sy, sw, sh = self._虚拟屏幕()
        return (max(sx, min(int(x), sx + sw - self.球径)),
                max(sy, min(int(y), sy + sh - self.球径)))

    def _球位置(self):
        存 = 配置.get('ball_pos')
        sx, sy, 宽, 高 = self._虚拟屏幕()
        if isinstance(存, list) and len(存) == 2:
            x, y = int(存[0]), int(存[1])
        else:
            x, y = sx + 宽 - self.球径 - 48, sy + int(高 * 0.55)
        return self._限位置(x, y)

    # ---------- 球有多大 ----------
    def _球倍率(self):
        """球多大：**手动倍率** ×（勾了「跟着系统缩放」时才再乘屏幕缩放）。

        ⭐ 0.6.1：
           0.6.0 让球径无脑乘系统缩放 —— 可这只球是用 UpdateLayeredWindow 按**物理像素**
           画出来的，系统缩放本来不会让它自己变大 ⇒ 再乘一次就等于翻倍（200% 那里正好 ×2）。
           现在默认**纯像素**：100% = ball_size，50% = 一半，在哪台机器上都一样大；
           想让它跟着系统变大变小，就在设置里勾「跟着系统缩放」。
        """
        try:
            手动 = float(配置.get('ui_scale') or 1.0)
        except Exception:
            手动 = 1.0
        倍 = 手动
        if 配置.get('跟随系统缩放'):
            try:
                倍 = 手动 * float(self.显示缩放 or 1.0)
            except Exception:
                倍 = 手动
        return max(0.2, min(4.0, 倍))

    def _算球径(self, 倍率=None):
        """这只要多大（像素）：ball_size × 手动倍率 × 屏幕缩放，再夹一下屏幕上限。"""
        总 = self._球倍率() if 倍率 is None else max(0.3, min(4.0, float(倍率)))
        try:
            底 = int(配置.get('ball_size', 420))
        except Exception:
            底 = 420
        径 = int(round(底 * 总))
        # 换显示器 / 缩放乱跳时别冒出个巨球：最多屏幕短边的 45%
        try:
            _sx, _sy, 宽, 高 = self._虚拟屏幕()
            上限 = int(min(宽, 高) * 0.45)
            if 上限 > 72:
                径 = min(径, 上限)
        except Exception:
            pass
        return max(72, 径)

    def _面板倍率(self):
        """窗口面板只跟系统缩放走 —— 手动倍率只放大那只球，不撑大面板/设置页。"""
        try:
            现在 = float(self.显示缩放)
        except Exception:
            现在 = 1.0
        return max(0.4, min(4.0, 现在))

    def _设字缩放(self):
        """Tk 的字按点算，缩放变了要告诉它一声（已建好的控件也会跟着重算）。"""
        try:
            手动 = float(配置.get('ui_scale') or 1.0)
        except Exception:
            手动 = 1.0
        try:
            # ⚠ 手动倍率（ui_scale）只放大那只球，**不动界面字号** ——
            #   不然把球调到 140%，设置页的字也一起变 1.4 倍，整个窗口就撑爆了。
            self.根.tk.call('tk', 'scaling', max(0.5, float(self.显示缩放)) * 96.0 / 72.0)
        except Exception:
            pass

    def 重排(self):
        """按当前缩放重新排一遍：球的大小、字的缩放、面板尺寸。"""
        新 = self._算球径()
        self._设字缩放()
        if 新 != getattr(self, '球径', None):
            旧 = getattr(self, '球径', None)
            self.球径 = 新
            x, y = self._限位置(*self._浮窗位置)
            self._浮窗位置 = (x, y)
            try:
                self._建Tk浮窗(x, y)
                self._记尺寸('球径 %s → %s（屏幕 %d%%）' % (旧, 新, int(round(float(self.显示缩放 or 1) * 100))))
            except Exception as e:
                # ⚠ 以前这里只有一句看不到的 _写，于是「点小一点没反应」查不出原因
                self._记尺寸('球径 %s → %s 重建失败：%s' % (旧, 新, e))
        if self.当前页:
            try:
                self._调面板尺寸(self.当前页)
            except Exception:
                pass
        return 新

    def _记尺寸(self, 话):
        """尺寸变化的取证日志（%LOCALAPPDATA%\\鱼搭子\\尺寸-诊断.log）。"""
        try:
            p = os.path.join(paths.用户目录(), '尺寸-诊断.log')
            if os.path.exists(p) and os.path.getsize(p) > 512 * 1024:
                os.replace(p, p + '.1')
            with open(p, 'a', encoding='utf-8') as f:
                f.write(time.strftime('%H:%M:%S') + '  ' + str(话) + '\n')
        except Exception:
            pass

    def 调大小(self, 增减):
        """设置页里的「大一点 / 小一点」。返回一句人话。

        ⭐ 0.6.1：纯像素倍率（不再乘系统缩放），所以点一下就是 10%，看得见。
        """
        现 = float(配置.get('ui_scale') or 1.0)
        新 = max(0.2, min(2.0, round(现 + 增减, 2)))
        if abs(新 - 现) < 0.001:
            return '已经%s了' % ('最大' if 增减 > 0 else '最小')
        配置['ui_scale'] = 新
        try:
            paths.写配置(配置)
        except Exception:
            pass
        新径 = self.重排()
        return '悬浮窗大小：%d%%（%d px）' % (int(round(新 * 100)), 新径 or self.球径)

    def 跟系统缩放(self):
        配置['跟随系统缩放'] = True
        配置['ui_scale'] = 1
        try:
            paths.写配置(配置)
        except Exception:
            pass
        新径 = self.重排()
        return '跟着系统缩放了（屏幕 %d%%，球 %d px）' % (
            int(round(float(self.显示缩放 or 1) * 100)), 新径 or self.球径)

    def _看缩放(self):
        """半秒看一眼：远程把缩放调了 / 换了显示器，就自己重排（不用重启）。"""
        try:
            新 = 系统缩放(self.根.winfo_id())
            if abs(新 - float(self.显示缩放 or 1.0)) > 0.01:
                self.显示缩放 = 新
                self.重排()
                try:
                    self.待显示.put(('提示', '· 屏幕缩放变成 %d%%，跟着调好大小了' % int(round(新 * 100))))
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self.根.after(500, self._看缩放)
        except Exception:
            pass

    def _建Tk浮窗(self, x, y):
        from PIL import Image
        if self.分层图:
            try:
                self.分层图.销毁()
            except Exception:
                pass
            self.分层图 = None
        self.根.overrideredirect(True)
        self.根.attributes('-topmost', True)
        self.根.geometry('%dx%d+%d+%d' % (self.球径, self.球径, x, y))
        self.根.update_idletasks()
        try:
            self.分层图 = Tk分层图(self.根, self.原图, self.球径)
            self.球画 = self.根
            self.根.deiconify()
            self.根.update_idletasks()
            self.分层图.更新(x, y)
            self.根.bind('<ButtonPress-1>', self._鼠标按下)
            self.根.bind('<B1-Motion>', self._鼠标拖动)
            self.根.bind('<ButtonRelease-1>', self._鼠标松开)
            self.根.bind('<ButtonRelease-3>', self._菜单)
            return
        except Exception:
            if self.分层图:
                self.分层图.销毁()
                self.分层图 = None

        # 如果系统不支持每像素透明，退回带轮廓的 Tk 图层。
        self.球画 = self.tk.Canvas(self.根, width=self.球径, height=self.球径,
                                  highlightthickness=0, bd=0, bg=淡底)
        self.球画.pack()
        缩 = self.原图.resize((self.球径, self.球径), Image.LANCZOS)
        底 = Image.new('RGB', 缩.size, (220, 235, 244))
        底.paste(缩, (0, 0), 缩)
        self.球图 = self.ImageTk.PhotoImage(底)
        self.球画.create_image(0, 0, anchor='nw', image=self.球图)
        self.球画.bind('<ButtonPress-1>', self._鼠标按下)
        self.球画.bind('<B1-Motion>', self._鼠标拖动)
        self.球画.bind('<ButtonRelease-1>', self._鼠标松开)
        self.球画.bind('<ButtonRelease-3>', self._菜单)
        self.根.deiconify()
        定形窗(self.根, self.原图, self.球径, 阈值=1)

    def _鼠标按下(self, e):
        动作 = 命中悬浮按钮(e.x, e.y, self.球径)
        x, y = self._浮窗位置
        self._拖动起点 = (e.x_root, e.y_root, x, y, 动作)
        self._拖过 = False

    def _鼠标拖动(self, e):
        if not self._拖动起点:
            return
        x0, y0, wx, wy, 动作 = self._拖动起点
        dx, dy = e.x_root - x0, e.y_root - y0
        # 三颗圆钮是纯按钮（从它们身上不能拖）；上面那块「设置」既能拖、也能点（拖超过 4 像素算拖）
        if (动作 is None or 动作 == '设置') and (abs(dx) > 4 or abs(dy) > 4):
            self._拖过 = True
        if self._拖过:
            x, y = self._限位置(wx + dx, wy + dy)
            if self.分层图:
                self.分层图.更新(x, y)
            else:
                self.根.geometry('+%d+%d' % (x, y))
            self._浮窗位置 = (x, y)
            try:
                if getattr(self, '气泡', None) is not None:
                    径 = int(getattr(self, '球径', 0) or 0) or 132
                    self.气泡.跟随((int(x), int(y), 径, 径))
            except Exception:
                pass

    def _鼠标松开(self, e):
        动过 = self._拖过
        起点 = self._拖动起点
        self._拖动起点 = None
        if 动过:
            self._存位置(*self._浮窗位置)
            return
        if 起点 and 起点[4]:
            松开动作 = 命中悬浮按钮(e.x, e.y, self.球径)
            if 松开动作 == 起点[4]:
                self._选择功能(松开动作)

    def _浮窗已移动(self, x, y):
        self._浮窗位置 = (int(x), int(y))
        self._存位置(x, y)

    def _存位置(self, x=None, y=None):
        try:
            if x is None or y is None:
                if self.浮窗:
                    x, y = self.浮窗.x, self.浮窗.y
                else:
                    x, y = self._浮窗位置
            配置['ball_pos'] = [int(x), int(y)]
            self._写配置()
        except Exception:
            pass

    def _写配置(self):
        paths.写配置(配置)

    def _菜单(self, e=None):
        if e is None:
            self.根.after(100, self._弹出菜单)
        else:
            x, y = e.x_root, e.y_root
            self.根.after(100, lambda: self._弹出菜单(x, y))

    def _托盘菜单(self):
        """托盘右键：用**系统原生菜单**（跟系统托盘一致）。"""
        记右键('托盘右键 → 弹原生菜单')
        self._弹出菜单()

    def _建右键菜单(self):
        tk = self.tk

        def 守(工):
            """右键刚弹出来的头 250ms 里不执行 —— 防止右键那一下被当成点了第一项。"""
            def 跑():
                try:
                    if self._菜单还没稳住():
                        return
                except Exception:
                    pass
                工()
            return 跑

        m = tk.Menu(self.根, tearoff=0)
        m.add_command(label='鱼搭子', state='disabled')
        m.add_separator()
        可见 = self.根.state() != 'withdrawn'
        m.add_command(label=('隐藏悬浮窗' if 可见 else '显示悬浮窗'),
                      command=守(self._切换悬浮窗))
        if self.当前页:
            m.add_command(label='关闭当前功能', command=守(self._关闭功能))
        m.add_separator()
        m.add_command(label='退出', command=守(self._退出))
        return m

    def _弹出菜单(self, x=None, y=None):
        记右键('悬浮窗右键 → 准备弹菜单（%s,%s）' % (x, y))
        # ⭐ 0.1.5/0.1.6：
        #   ① 右键两条路径都会触发（分层窗 WndProc + Tk ButtonRelease-3）→ 0.4 秒内只弹一次；
        #   ② 菜单对象挂到 self 上，别被 GC 掉；
        #   ③ **千万别 grab_release**：Tk 的弹出菜单靠这个 grab 活着，放掉它就立刻消失
        #     （0.1.5 就是"排 30ms 后释放" → 菜单刚出来就被关掉，一次都没看见）；
        #   ④ 开菜单后 250ms 内不执行菜单命令 —— 防止右键那一下被误判成点了第一项（表现就是"悬浮窗自己灭了"）。
        现在 = time.monotonic()
        if 现在 - getattr(self, '_菜单时刻', -1e9) < 0.4:
            return
        self._菜单时刻 = 现在
        self._菜单刚开 = 现在
        旧 = getattr(self, '_菜单对象', None)
        if 旧 is not None:
            try:
                旧.unpost()
            except Exception:
                pass
            try:
                旧.destroy()
            except Exception:
                pass
        m = self._建右键菜单()
        self._菜单对象 = m
        try:
            if x is None or y is None:
                x, y = self.根.winfo_pointerxy()
            m.tk_popup(x, y)
        except Exception:
            pass

    def _菜单还没稳住(self):
        return (time.monotonic() - getattr(self, '_菜单刚开', -1e9)) < 0.25

    def _显示悬浮窗(self):
        self.根.deiconify()
        self.根.lift()
        self.根.attributes('-topmost', True)
        if self.分层图:
            self.根.after_idle(lambda: self.分层图.更新(*self._浮窗位置))

    def _切换悬浮窗(self):
        记右键('执行 _切换悬浮窗')
        if self.根.state() == 'withdrawn':
            self._显示悬浮窗()
        else:
            self.根.withdraw()

    def _设窗口图标(self, 窗):
        self._图标已设置 = False
        try:
            窗.iconbitmap(os.path.join(HERE, 'assets', '鱼搭子.ico'))
            self._图标已设置 = True
        except Exception:
            try:
                from PIL import Image
                ico = self.原图.resize((32, 32), Image.LANCZOS)
                self.窗口图标 = self.ImageTk.PhotoImage(ico)
                窗.iconphoto(True, self.窗口图标)
                self._图标已设置 = True
            except Exception:
                pass

    def _建功能窗(self):
        tk = self.tk
        p = tk.Toplevel(self.根)
        p.title('鱼搭子')
        p.configure(bg='#c9dbe6')
        p.resizable(True, True)
        p.protocol('WM_DELETE_WINDOW', self._关闭功能)
        self._设窗口图标(p)
        self.面板 = p

        边框 = tk.Frame(p, bg=淡线, padx=1, pady=1)
        边框.pack(fill='both', expand=True, padx=6, pady=6)
        self.外框 = tk.Frame(边框, bg=淡底, padx=10, pady=10)
        self.外框.pack(fill='both', expand=True)
        # ⭐ 0.0.5：顶上这一行是**功能开关** —— 摘页不再等于关功能，
        #   电话 / 陪看各有一个灯，点一下开、再点一下停。
        self.功能行 = tk.Frame(self.外框, bg=淡底)
        self.功能行.pack(fill='x', pady=(0, 6))
        self.灯电话 = tk.Button(self.功能行, text='○ 电话：关', command=self._切电话开关,
                              bg=淡卡, fg=字深, relief='flat', padx=10, pady=3,
                              font=('Microsoft YaHei UI', 9))
        self.灯电话.pack(side='left')
        self.灯陪看 = tk.Button(self.功能行, text='○ 陪看：关', command=self._切陪看开关,
                              bg=淡卡, fg=字深, relief='flat', padx=10, pady=3,
                              font=('Microsoft YaHei UI', 9))
        self.灯陪看.pack(side='left', padx=(6, 0))
        # ⭐ 1.1.4：第三盏灯 —— 游戏模式也能像电话/陪看一样在这儿开关
        self.灯游戏 = tk.Button(self.功能行, text='○ 游戏：关', command=self._切游戏开关,
                              bg=淡卡, fg=字深, relief='flat', padx=10, pady=3,
                              font=('Microsoft YaHei UI', 9))
        self.灯游戏.pack(side='left', padx=(6, 0))

        self.页区 = tk.Frame(self.外框, bg=淡底)
        self.页区.pack(fill='both', expand=True)
        self.页框 = {}
        self.面板.update_idletasks()

    def _选择功能(self, 键):
        if 键 == '电话':
            self._点电话()
        elif 键 == '直播':
            self._打开陪看()
        elif 键 == '游戏':
            self._打开游戏()
        elif 键 == '设置':
            self._切页('设置')

    def _清陪看(self):
        if self.陪看程序:
            try:
                self.陪看程序.stop()
            except Exception:
                pass

    def _调面板尺寸(self, 页面):
        if not self.面板:
            return
        sx, sy, sw, sh = self._虚拟屏幕()
        倍 = self._面板倍率()            # ⭐ 面板只跟系统缩放走（手动倍率只放大那只球）

        def 乘(v, 小=1):
            return max(小, int(round(v * 倍)))

        if 页面 == '陪看':
            # 沿用陪看原有窗口尺寸规则，只给淡蓝边框留出少量空间。
            屏宽, 屏高 = self.根.winfo_screenwidth(), self.根.winfo_screenheight()
            宽 = min(1700, max(1150, 屏宽 - 700)) + 20
            高 = min(1010, max(720, 屏高 - 400)) + 20
            宽 = min(宽, max(1040, sw - 16))
            高 = min(高, max(700, sh - 32))
            self.面板.minsize(1040, 700)
        elif 页面 == '电话':
            宽, 高 = 乘(360, 260), 乘(420, 300)
            self.面板.minsize(min(乘(320, 240), 宽), min(乘(360, 280), 高))
        elif 页面 == '设置':
            # 分页之后一页不长，560×660 足够；再挤也能滚，不会看不全
            宽, 高 = 乘(560, 420), 乘(660, 420)
            宽 = min(宽, max(380, sw - 24))
            高 = min(高, max(440, sh - 40))
            self.面板.minsize(min(乘(380, 340), 宽), min(乘(440, 380), 高))
        else:
            宽, 高 = 乘(int(配置.get('panel_width', 300)), 240), 乘(240, 180)
            self.面板.minsize(260, 200)
        bx, by = self._浮窗位置
        x = bx - 宽 - 12
        if x < sx + 8:
            x = bx + self.球径 + 12
        x = max(sx + 8, min(x, sx + sw - 宽 - 8))
        y = max(sy + 8, min(by + self.球径 // 2 - 高 // 2, sy + sh - 高 - 8))
        self.面板.geometry('%dx%d+%d+%d' % (宽, 高, x, y))

    def _切页(self, 页面):
        # ⭐ 0.0.5：切页**不再**停掉别的功能 —— 电话、陪看、游戏可以同时开着，
        #   栏位只决定「你现在看哪一格」。要停哪个，用上面那一行开关。
        if self.当前页 == 页面:
            if self.面板:
                self.面板.deiconify()
                self.面板.lift()
            return
        if not self.面板 or not self.面板.winfo_exists():
            self._建功能窗()
        if 页面 not in self.页框:
            self._建功能页(页面)
        for 框 in self.页框.values():
            框.pack_forget()
        self.当前页 = 页面
        self.页框[页面].pack(fill='both', expand=True)
        标题 = {'电话': '打电话', '陪看': '陪看', '游戏': '打游戏', '设置': '设置'}
        self.面板.title(标题.get(页面, '鱼搭子'))
        self._调面板尺寸(页面)
        self.面板.deiconify()
        self.面板.lift()

    def _停止当前功能(self):
        if self.当前页 == '电话':
            self._挂断()
        if self.当前页 == '陪看':
            self._清陪看()
        if self.当前页 == '设置' and getattr(self, '设置件', None):
            try:
                self.设置件.销毁()
            except Exception:
                pass
            self.设置件 = None

    def _建功能页(self, 页面):
        tk = self.tk
        页 = tk.Frame(self.页区, bg=淡底)
        self.页框[页面] = 页
        if 页面 == '电话':
            self._建电话页(页)
        elif 页面 == '陪看':
            self._建陪看页(页)
        elif 页面 == '设置':
            import settings
            self.设置件 = settings.设置页(页, self)
        elif 页面 == '游戏':
            tk.Label(页, text='打游戏还没接好。', bg=淡底, fg=字深,
                     font=('Microsoft YaHei UI', 11, 'bold')).pack(anchor='w', pady=(12, 4))
            tk.Label(页, text='做好后可以从这里打开。', bg=淡底, fg=字次,
                     font=('Microsoft YaHei UI', 9)).pack(anchor='w')

    def _建电话页(self, 内):
        tk = self.tk
        在 = paths.语音就绪()
        tk.Label(内, text=('说完一句会自动识别，并尝试发给大肥鱼。' if 在 else '还没装语音 —— 装一次，电话和陪看都能用。'),
                 bg=淡底, fg=字次, font=('Microsoft YaHei UI', 9)).pack(anchor='w', pady=(0, 8))
        self.状态 = tk.Label(内, text=('准备麦克风…' if 在 else '还没装语音'), bg=淡底,
                             fg=(字次 if 在 else 红), anchor='w',
                             font=('Microsoft YaHei UI', 9))
        self.状态.pack(fill='x', pady=(0, 6))
        self.流水 = tk.Text(内, bg=淡卡, fg=字深, bd=0, height=10,
                            font=('Microsoft YaHei UI', 9), wrap='word',
                            padx=10, pady=8, insertbackground=字深)
        self.流水.pack(fill='both', expand=True, pady=(0, 10))
        self.流水.configure(state='disabled')
        for 一 in getattr(self, '未读回话', [])[-20:]:
            self._写('大肥鱼：' + 一)
        self.未读回话 = []
        self.装语音钮 = tk.Button(内, text='去设置里装语音（约 240MB）', command=lambda: self._切页('设置'),
                               bg='#2f7fb8', fg='#ffffff', relief='flat',
                               font=('Microsoft YaHei UI', 10, 'bold'), pady=7)
        if not 在:
            self.装语音钮.pack(fill='x', pady=(0, 6))
        self.挂断钮 = tk.Button(内, text='挂断', command=self._挂断,
                              bg=红, fg='#ffffff', relief='flat',
                              font=('Microsoft YaHei UI', 10, 'bold'), pady=7)
        self.挂断钮.pack(fill='x')

    def _建陪看页(self, 内):
        tk = self.tk
        class 嵌入陪看框(tk.Frame):
            # 复用已验证的陪看 UI，但不让它把鱼搭子的总面板窗口改成独立窗口。
            def title(self, *args):
                pass

            def geometry(self, *args):
                pass

            def minsize(self, *args):
                pass

        self.陪看承载 = 嵌入陪看框(内, bg='#0e1014')
        self.陪看承载.pack(fill='both', expand=True)
        try:
            # 陪看现在**是程序自己的一部分**（app/watch_ui.py），不再按配置里的绝对路径去外面找，
            # 这样打包成 exe 之后也照样能开。
            import watch_ui
            self.陪看模块 = watch_ui
            self.陪看程序 = watch_ui.App(self.陪看承载)
        except Exception as e:
            for w in self.陪看承载.winfo_children():
                w.destroy()
            tk.Label(self.陪看承载, text='陪看打不开：' + str(e),
                     bg='#0e1014', fg='#e8ebf0',
                     font=('Microsoft YaHei UI', 10), padx=18, pady=18,
                     wraplength=520, justify='left').pack(anchor='nw')

    def _刷功能行(self):
        try:
            开电话 = bool(self.通话)
            self.灯电话.configure(
                text=('● 电话：在听' if 开电话 else '○ 电话：关'),
                fg=(绿 if 开电话 else 字深))
            开陪看 = bool(getattr(self.陪看程序, 'cap', None))
            self.灯陪看.configure(
                text=('● 陪看：在听' if 开陪看 else '○ 陪看：关'),
                fg=(绿 if 开陪看 else 字深))
            开游戏 = bool(getattr(self, '游戏模式', False))
            self.灯游戏.configure(
                text=('● 游戏：开着' if 开游戏 else '○ 游戏：关'),
                fg=(绿 if 开游戏 else 字深))
        except Exception:
            pass

    def _切游戏开关(self):
        """顶上那盏「游戏」灯：开着就退出，关着就进去（跟电话/陪看一个用法）。"""
        if getattr(self, '游戏模式', False):
            self._退出游戏()
        else:
            # ⚠ 1.1.5：这里以前会 `面板.withdraw()` —— 在设置页点它，整个设置页就没了。
            #   现在只进游戏模式、不碰面板；开着设置页的话把它留在最上面。
            self._进游戏模式()
            try:
                if self.面板 and self.当前页 == '设置':
                    self.面板.attributes('-topmost', True)
                    self.面板.deiconify()
                    self.面板.lift()
            except Exception:
                pass
        self._刷功能行()

    def _切电话开关(self):
        if self.通话:
            self._挂断()
        else:
            self._开通话()
        self._刷功能行()

    def _切陪看开关(self):
        if not self.陪看程序:
            # ⚠ 1.1.5：在设置页点这盏灯不能把页面切走（切走就等于把设置页关了）。
            if self.当前页 == '设置':
                if '陪看' not in self.页框:
                    self._建功能页('陪看')
            else:
                # 还没建过陪看页：先建（建的时候会挂上陪看那个界面）
                self._切页('陪看')
        if getattr(self.陪看程序, 'cap', None):
            self.陪看程序.stop()
            # ⭐ 1.1.1：陪看是全关 —— 它顺手开的那个电话也一起挂掉。
            #   不然人已经把陪看关了，麦克风还开着，话还在往会话里送。
            if getattr(self, '_电话陪看开的', False) and self.通话:
                self._挂断()
                self._写('陪看关了，顺手开的电话也一起关了')
            self._电话陪看开的 = False
        else:
            try:
                self.陪看程序.start()
            except Exception as e:
                self._写('陪看开不起来：%s' % e)
            # ⭐ 开了陪看，电话默认一起开（可在设置里关掉）
            try:
                if getattr(self.陪看程序, 'cap', None) and 配置.get('陪看带麦克风', True) and not self.通话:
                    self._开通话()
                    self._电话陪看开的 = True
            except Exception:
                pass
        self._刷功能行()

    def _关闭功能(self):
        # ⭐ 0.0.5：关掉面板 = 收起来，功能（麦克风 / 陪看）继续跑；
        #   要真停，用面板顶上那一行开关，或者右键托盘退出。
        self.当前页 = None
        if self.面板:
            self.面板.withdraw()

    def _打开游戏(self):
        """⭐ 0.7.0：点手柄 = 进游戏模式 —— 球藏起来，只剩弹幕和弹幕框。"""
        self.当前页 = '游戏'
        if self.面板:
            self.面板.withdraw()
        self._进游戏模式()

    # ---------- 游戏模式（0.7.0） ----------
    def _进游戏模式(self):
        # ⚠ 0.8.5：状态卡死时也要能重新开（以前这里直接 return，结果球藏了、框没出来，
        #   再点手柄就永远「已经在了」）
        # ⚠ 0.9.8：两样都真建出来了才算「已经在了」—— 以前只看框，
        #   飘的弹幕没建起来（或者是后来才把开关打开）就再也补不上。
        要框 = 配置.get('弹幕框开', True)
        要幕 = 配置.get('弹幕开', True)
        齐了 = ((getattr(self, '弹幕框', None) is not None or not 要框)
                and (getattr(self, '弹幕', None) is not None or not 要幕))
        if getattr(self, '游戏模式', False) and 齐了:
            return '已经在了'
        self.游戏模式 = True
        self.弹幕 = None
        self.弹幕框 = None
        try:
            import danmaku
            # ⚠ 游戏模式的东西**只用主屏**（0,0,主屏宽高）——
            #   用虚拟屏幕会把弹幕框丢到副屏去，放「左上」还会跑出屏幕外。
            屏 = (0, 0, int(self.根.winfo_screenwidth()), int(self.根.winfo_screenheight()))
        except Exception as e:
            屏 = None
            try:
                记右键('游戏模式没起来（导入失败）：%s' % e)
            except Exception:
                pass
        if 屏:
            if 配置.get('弹幕开', True):
                self._建弹幕层(屏)
            if 配置.get('弹幕框开', True):
                self._建弹幕框(屏)
        self._开游戏截图()
        # ⭐ 1.1.3：游戏模式也能说话 —— 按设置把麦克风开起来（退出时再关）
        try:
            if 配置.get('游戏开麦克风', False) and not getattr(self, '通话', False):
                self._开通话()
                self._电话游戏开的 = True
                记右键('游戏模式：麦克风也开着了')
        except Exception as e:
            记右键('游戏模式开麦克风没成：%s' % e)
        try:
            self.气泡.藏()
        except Exception:
            pass
        try:
            self.根.withdraw()          # 球（和面板）藏起来
        except Exception:
            pass
        try:
            self._刷功能行()
        except Exception:
            pass
        return '进了游戏模式'

    # ---------- 截图：游戏模式自己截 / 一个键随时截（1.0.2） ----------
    def _截图区(self, 键):
        """这个用途该截哪块：框过就用框，没框/框太小就整屏。"""
        try:
            框 = [int(v) for v in (配置.get(键) or [])]
        except Exception:
            框 = []
        try:
            屏宽 = int(self.根.winfo_screenwidth())
            屏高 = int(self.根.winfo_screenheight())
        except Exception:
            屏宽, 屏高 = 1920, 1080
        if len(框) < 4 or 框[2] < 200 or 框[3] < 120:
            return (0, 0, 屏宽, 屏高)
        return (框[0], 框[1], 框[2], 框[3])

    def _截一张(self, 来源='游戏'):
        """抓一张、压好、递给插件 —— 插件会把**图片本身**发给她看（不是只给路径）。"""
        try:
            import frames
        except Exception as e:
            self._记截图('截图没起来：%s' % e)
            return False
        框 = self._截图区('游戏截图框' if 来源 == '游戏' else '热键截图框')
        图 = frames.抓(框)
        if 图 is None:
            self._记截图('抓不到画面（%s）' % (框,))
            return False
        字节, 尺寸 = frames.压(图, 1280, 75)
        frames.存(字节, '截图')
        端口 = int(配置.get('dsh_port') or 8777)
        好, 说 = frames.发(端口, 字节, {
            '立即': 1, '来源': 来源, '尺寸': '%dx%d' % 尺寸, '时间点': int(time.time() * 1000)})
        self._记截图('截图（%s）：%dKB %s → %s｜%s'
                   % (来源, len(字节) // 1024, '%dx%d' % 尺寸, 'ok' if 好 else '失败', str(说)[:60]))
        return bool(好)

    def _记截图(self, 文):
        try:
            记右键(文)
        except Exception:
            pass
        try:
            self.待显示.put(('提示', '· ' + 文))
        except Exception:
            pass

    def _拍一张给插件(self):
        """⭐ 1.1.1：插件（她要自己开口的时候）来要一张当下的画面。

        截哪块跟「按住说话带图」一个口径：框过就用框，没框就整屏。
        """
        try:
            import frames
            框 = self._截图区('热键截图框')
            图 = frames.抓(框)
            if 图 is None:
                return None
            字节, 尺寸 = frames.压(图, 1280, 75)
            记右键('插件来要图：给了 %dKB %dx%d' % (len(字节) // 1024, 尺寸[0], 尺寸[1]))
            return 字节, 尺寸
        except Exception as e:
            记右键('插件来要图，没拍成：%s' % e)
            return None

    def _开游戏截图(self, 从头=True):
        """游戏模式里隔一会儿自己截一张递给她 —— 不然她没画面，只能瞎猜。

        ⭐ 1.1.6：`从头=False` 表示「只按新参数接着跑」——
        改设置重启计时器时，不能再把「第一张先等 3 秒」重来一遍（不然每存一次就立刻截一张）。
        """
        旧参数 = getattr(self, '_截图参数', None)
        self._停游戏截图()
        if not bool(配置.get('游戏截图开', True)):
            return False
        try:
            最短 = float(配置.get('游戏截图最短秒') or 45)
            最长 = float(配置.get('游戏截图最长秒') or 120)
        except Exception:
            最短, 最长 = 45.0, 120.0
        # ⚠ 1.1.2：以前下限写死 10 秒 —— 设置里填 5 会被悄悄抬成 10，看着像「说了 5 秒却半天不来」。
        最短 = max(3.0, min(最短, 3600.0))
        最长 = max(最短 + 1.0, min(最长, 7200.0))
        停 = threading.Event()
        self._截图停 = 停
        记右键('游戏截图：%d~%d 秒一张（第一张先等 3 秒）' % (最短, 最长))

        self._截图参数 = (最短, 最长)

        def 跑():
            import random
            第一张 = bool(从头)
            while not 停.is_set():
                间隔 = 3.0 if 第一张 else 最短 + (最长 - 最短) * random.random()
                第一张 = False
                睡到 = time.time() + 间隔
                while time.time() < 睡到 and not 停.is_set():
                    time.sleep(0.5)
                if 停.is_set() or not getattr(self, '游戏模式', False):
                    break
                self._截一张('游戏')
            记右键('游戏截图那条腿停了')

        try:
            threading.Thread(target=跑, name='fisbuddy-game-shot', daemon=True).start()
            return True
        except Exception as e:
            记右键('游戏截图没起来：%s' % e)
            return False

    def _停游戏截图(self):
        停 = getattr(self, '_截图停', None)
        if 停 is not None:
            停.set()
        self._截图停 = None

    # ---------- 按住说话：按住听，松开把这句（可能还有一张图）发过去 ----------
    def _热键轮询(self):
        """每 80ms 看一次两个说话键是按下去还是松开了（不挂键盘钩子，免得出事）。"""
        for 键项, 带图 in (('按住说键', False), ('按住说图键', True)):
            try:
                键 = int(配置.get(键项) or 0)
            except Exception:
                键 = 0
            if 键 <= 0:
                continue
            try:
                import ctypes as _ct
                按下 = bool(_ct.windll.user32.GetAsyncKeyState(键) & 0x8000)
            except Exception:
                按下 = False
            记 = getattr(self, '_按着们', None)
            if 记 is None:
                记 = self._按着们 = {}
            上次 = 记.get(键项, False)
            记[键项] = 按下
            if 按下 and not 上次:
                self._按住开始(带图)
            elif (not 按下) and 上次:
                self._按住松手(带图)
        try:
            self.根.after(80, self._热键轮询)
        except Exception:
            pass

    def _按住开始(self, 带图):
        if getattr(self, '_按住中', None):
            return
        按住 = {'带图': 带图, '起': time.time(), '图': None}
        self._按住中 = 按住
        # ⭐ 1.1.8：上一句说完之后耳朵会留一小会儿（默认 25 秒）——
        #   复用它能省掉「重新打开音频流」那半秒，不然按下就说话，前面几个字是丢的。
        自 = getattr(self, '_关耳定时', None)
        if 自:
            try:
                self.根.after_cancel(自)
            except Exception:
                pass
            self._关耳定时 = None
        if not getattr(self, '耳朵', None):
            try:
                self._开耳朵()
                # ⚠ 1.0.5：这个耳朵是「按住说话」临时开的，**收尾时必须关掉**。
                #   以前把「关不关」写在收尾里、还跟「待发」绑在一起 → 认出来的那句话把待发清掉，
                #   收尾直接 return，耳朵就一直跑（电话没开也在一直识音、一直发）。
                self._按住自开耳朵 = True
            except Exception as e:
                记右键('按住说话没开麦：%s' % e)
        # 复用上一句留下的耳朵时，也要认回「这是我开的」—— 不然收尾后它再也没人关
        if getattr(self, '耳朵', None) and not getattr(self, '通话', False):
            self._按住自开耳朵 = True
        self.待显示.put(('提示', '· 按住中…松手就发（%s）' % ('带一张图' if 带图 else '只说话')))
        # ⭐ 1.0.8：截的是**按下那一下**的画面 —— 她按下时看到的、想让她看的，就是这一帧。
        #   （松手时才截，说话这会儿画面可能已经变了。）
        if 带图:
            def 抓():
                try:
                    import frames
                    图 = frames.抓(self._截图区('热键截图框'))
                    if 图 is not None:
                        字节, _ = frames.压(图, 1280, 75)
                        按住['图'] = 字节
                        记右键('按住说话：按下那一下截了一张（%dKB）' % (len(字节) // 1024))
                except Exception as e:
                    记右键('按住说话的图没抓住：%s' % e)
            try:
                threading.Thread(target=抓, daemon=True).start()
            except Exception:
                pass
        # 兜底：万一下次收不到「松开」（改键、切窗口卡住），45 秒后自己收
        try:
            self.根.after(45000, lambda: self._按住收尾(按住))
        except Exception:
            pass

    def _按住松手(self, 带图):
        按住 = getattr(self, '_按住中', None)
        if not 按住:
            return
        self._按住中 = None
        self._按住待发 = 按住
        # ⭐ 1.0.7：松手 = 我说完了 —— 立刻让它把这段定下来，别再等「安静几秒」
        try:
            if getattr(self, '耳朵', None):
                self.耳朵.现在就说()
        except Exception:
            pass
        # 定稿是立刻的，收尾（关临时麦克风）给 1.2 秒就够
        try:
            self.根.after(1200, lambda: self._按住收尾(按住))
        except Exception:
            self._按住收尾(按住)

    def _按住收尾(self, 按住):
        """松开后等一会儿：**不管认没认出来，临时开的耳朵都要关掉**。"""
        还有 = getattr(self, '_按住待发', None) is 按住
        if 还有:
            self._按住待发 = None
        if getattr(self, '_按住自开耳朵', False) and not getattr(self, '通话', False):
            # ⭐ 1.1.8：先不关 —— 留 25 秒（热着），下一句按下就能立刻听到。
            #   一直没人用才真关，别让麦克风一直开着。
            self._按住自开耳朵 = False
            try:
                旧定时 = getattr(self, '_关耳定时', None)
                if 旧定时:
                    self.根.after_cancel(旧定时)
                self._关耳定时 = self.根.after(25000, self._关闲耳朵)
            except Exception:
                pass
        if 还有:
            self.待显示.put(('提示', '· 没听清这句（按住说话）'))

    def _关闲耳朵(self):
        """按住说话留下的那个耳朵，闲着太久就关掉（有电话在跑就不动它）。"""
        self._关耳定时 = None
        if getattr(self, '通话', False):
            return
        try:
            if getattr(self, '耳朵', None):
                self.耳朵.停()
                self.耳朵 = None
            记右键('按住说话：闲下来了，麦克风关了')
        except Exception:
            pass

    def _送图文(self, 文本, 图=None):
        """一句话（可能带图）发进会话：没图就走原来的送话，有图走 /hands/talk。"""
        if not 图:
            self._送(文本)
            return
        import base64
        import json
        import urllib.request
        端口 = int(配置.get('dsh_port') or 8777)
        try:
            体 = json.dumps({'text': 文本, '图片': base64.b64encode(图).decode('ascii')},
                            ensure_ascii=False).encode('utf-8')
            请求 = urllib.request.Request('http://127.0.0.1:%d/hands/talk' % 端口, data=体,
                                          headers={'Content-Type': 'application/json'})
            无代理 = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with 无代理.open(请求, timeout=8) as r:
                r.read()
            记右键('按住说话（带图）发出去了：%s' % 文本[:30])
        except Exception as e:
            记右键('按住说话带图没发出去：%s' % e)
            self._送(文本)

    # ---------- 游戏模式：建/重建那两块 ----------
    def _建弹幕层(self, 屏):
        import danmaku
        try:
            self.弹幕 = danmaku.弹幕层(
                self.根, 屏,
                字号=int(配置.get('弹幕字号') or 26),
                秒每屏=float(配置.get('弹幕速度秒') or 6),
                最多=int(配置.get('弹幕最多') or 10),
                区域=str(配置.get('弹幕位置') or '全屏'),
                帧率=int(配置.get('弹幕帧率') or 60),
                字色=_颜色们(配置.get('弹幕颜色'), (255, 255, 255)),
                描边=_颜色们(配置.get('弹幕描边'), (40, 40, 60)),
                路=_字体路(配置.get('弹幕字体')))
            self.弹幕.开()
        except Exception as e:
            self.弹幕 = None
            try:
                记右键('飘的弹幕没开起来：%s' % e)
            except Exception:
                pass
        return self.弹幕

    def _建弹幕框(self, 屏):
        import danmaku
        try:
            self.弹幕框 = danmaku.弹幕框(
                self.根, 屏, 位置=str(配置.get('弹幕框位置') or '右下'),
                宽=int(配置.get('弹幕框宽') or 380),
                字号=int(配置.get('框字号') or 20),
                菜单=self._弹幕框菜单, 双击=self._退出游戏, 设置=self._开设置)
            self.弹幕框.字体路 = _字体路(配置.get('框字体') or 配置.get('弹幕字体'))
            # ⭐ 1.1.5：记下这次是用哪套参数建的，之后「存设置」就不会白重建一遍
            self._框签名 = (配置.get('框字号'), 配置.get('框字体'), 配置.get('弹幕框宽'),
                          配置.get('弹幕框位置'), bool(配置.get('弹幕框开', True)))
            try:
                记右键('游戏模式：弹幕框建好了（%dx%d）' % (self.弹幕框.宽, self.弹幕框.高))
            except Exception:
                pass
        except Exception as e:
            self.弹幕框 = None
            try:
                记右键('弹幕框没建起来：%s' % e)
            except Exception:
                pass
        return self.弹幕框

    def _游戏设置变了(self):
        """设置里改了弹幕 / 弹幕框的样子：正在游戏模式里就当场按新的来。"""
        休 = getattr(self, '游戏模式', False)
        try:
            记右键('游戏设置改了：字号 %s / 速度 %s / 最多 %s / 框字号 %s / 框宽 %s'
                   % (配置.get('弹幕字号'), 配置.get('弹幕速度秒'), 配置.get('弹幕最多'),
                      配置.get('框字号'), 配置.get('弹幕框宽')))
        except Exception:
            pass
        if not 休:
            return '没在游戏模式里'
        # ⭐ 0.9.8：刚把「飘的弹幕」打开时它还没建过 —— 这里补建一个
        if 配置.get('弹幕开', True) and getattr(self, '弹幕', None) is None:
            try:
                屏0 = (0, 0, int(self.根.winfo_screenwidth()), int(self.根.winfo_screenheight()))
                self._建弹幕层(屏0)
            except Exception as e:
                try:
                    记右键('补建飘的弹幕没成：%s' % e)
                except Exception:
                    pass
        elif 配置.get('弹幕开', True) is False and getattr(self, '弹幕', None) is not None:
            try:
                self.弹幕.停()
            except Exception:
                pass
            self.弹幕 = None
        # 飘的那层：字号/速度/最多都能就地改，不用重建（在飞的弹幕照旧飞完）
        if getattr(self, '弹幕', None) is not None:
            try:
                self.弹幕.改(字号=int(配置.get('弹幕字号') or 26),
                             秒每屏=float(配置.get('弹幕速度秒') or 6),
                             最多=int(配置.get('弹幕最多') or 10),
                             帧率=int(配置.get('弹幕帧率') or 60))
            except Exception as e:
                try:
                    记右键('改飘的弹幕没成：%s' % e)
                except Exception:
                    pass
        # 框：**只有真改了框相关的几项**才整块重画（字号/字体/宽/位置/开关）。
        # ⚠ 1.1.5：以前每存一次都「关掉旧框、建个新框」—— 建窗是置顶的，
        #   设置页那边每敲一个字就被抢一次焦点、闪一下，弹幕也跟着卡。
        try:
            新签名 = (配置.get('框字号'), 配置.get('框字体'), 配置.get('弹幕框宽'),
                      配置.get('弹幕框位置'), bool(配置.get('弹幕框开', True)))
            旧签名 = getattr(self, '_框签名', None)
            if 新签名 == 旧签名:
                return '按新设置来了'
            旧 = self.弹幕框
            已有 = list(getattr(旧, '行们', [])) if 旧 is not None else []
            if 旧 is not None:
                try:
                    旧.关()
                except Exception:
                    pass
                self.弹幕框 = None
            屏 = (0, 0, int(self.根.winfo_screenwidth()), int(self.根.winfo_screenheight()))
            if 配置.get('弹幕框开', True):
                self._建弹幕框(屏)
                try:
                    for 句 in 已有[-12:]:
                        self.弹幕框.加(句)
                except Exception:
                    pass
            self._框签名 = 新签名
        except Exception as e:
            try:
                记右键('重画弹幕框没成：%s' % e)
            except Exception:
                pass
        return '按新设置来了'

    def _退出游戏(self):
        if not getattr(self, '游戏模式', False):
            return '本来就没开'
        self.游戏模式 = False
        self._停游戏截图()
        # ⭐ 0.9.7：退出时把还没放完的弹幕和重试定时都清掉
        self._弹幕队 = []
        if getattr(self, '_弹幕定时', None):
            try:
                self.根.after_cancel(self._弹幕定时)
            except Exception:
                pass
            self._弹幕定时 = None
        try:
            if self.弹幕:
                self.弹幕.停()
        except Exception:
            pass
        try:
            if self.弹幕框:
                self.弹幕框.关()
        except Exception:
            pass
        self.弹幕 = None
        self.弹幕框 = None
        # ⭐ 1.1.3：进游戏模式时顺手开的麦克风，退出来一起关
        try:
            if getattr(self, '_电话游戏开的', False) and getattr(self, '通话', False):
                self._挂断()
                记右键('退出游戏模式：顺手开的麦克风也关了')
            self._电话游戏开的 = False
        except Exception:
            pass
        # ⭐ 1.1.2：退出游戏模式时把气泡对象扔掉重建 —— 游戏模式里它被藏过、位置也是旧的球框，
        #   留着容易出现「退出来之后再也不冒气泡」。设成 None，下一句话会按新球位置重新建一个。
        try:
            if getattr(self, '气泡', None) is not None:
                self.气泡.藏()
        except Exception:
            pass
        self.气泡 = None
        try:
            self.根.deiconify()
        except Exception:
            pass
        try:
            self._建Tk浮窗(*self._浮窗位置)
        except Exception:
            pass
        try:
            self._刷功能行()
        except Exception:
            pass
        return '退出游戏模式了'

    def _弹幕框菜单(self, x, y):
        try:
            m = self.tk.Menu(self.根, tearoff=0)
            m.add_command(label='清空弹幕', command=lambda: (self.弹幕框 and self.弹幕框.清()))
            m.add_command(label='退出游戏模式', command=self._退出游戏)
            m.tk_popup(int(x), int(y))
        except Exception as e:
            try:
                self.待显示.put(('提示', '弹幕框菜单没弹出来：%s' % e))
            except Exception:
                pass

    def _开设置(self):
        """游戏模式里点大肥鱼 = 打开设置页，**不退出游戏模式**。"""
        try:
            self._切页('设置')
            if self.面板:
                self.面板.attributes('-topmost', True)
                self.面板.deiconify()
                self.面板.lift()
        except Exception as e:
            try:
                记右键('游戏模式里打开设置失败：%s' % e)
            except Exception:
                pass

    def _取一句(self, 文本):
        """把她的话收成弹幕用的文本：去掉 markdown 记号，段落之间留换行。**不截断**。

        ⭐ 0.9.9：以前只取第一行 —— 她分两段说的话，第二段整个丢掉（框里只剩第一条）。
        现在整段都收，飘的时候拆成几条依次滑，框里一段一条。
        """
        文 = str(文本 or '').strip()
        if not 文:
            return ''
        for 记号 in ('**', '__', '`', '#', '> '):
            文 = 文.replace(记号, '')
        行们 = [x.strip() for x in 文.split('\n') if x.strip()]
        return '\n'.join(行们)

    def _弹一句(self, 文本):
        """游戏模式里的一句话：飘弹幕（太长就拆几条）+ 整段进弹幕框（一段一条）。"""
        句 = self._取一句(文本)
        if not 句:
            return
        try:
            if getattr(self, '弹幕框', None):
                for 段 in 句.split('\n'):      # ⭐ 0.9.9：几段就记几条，不再只记第一条
                    self.弹幕框.加(段)
        except Exception as e:
            try:
                记右键('弹幕框没收下那句：%s' % e)
            except Exception:
                pass
        平 = 句.replace('\n', ' ')
        限 = max(8, int(配置.get('弹幕最多字') or 28))
        try:
            import danmaku as _弹
            块们 = _弹.拆弹幕(平, 限)
        except Exception:
            块们 = [平[i:i + 限] for i in range(0, len(平), 限)] or [平]
        队 = getattr(self, '_弹幕队', None)
        if 队 is None:
            队 = self._弹幕队 = []
        队.extend(块们)
        self._弹幕泵()

    def _弹幕能放下一条(self):
        """上一条快到左边了（走了八成）就放下一条 —— 不用等它整个消失。"""
        层 = getattr(self, '弹幕', None)
        们 = getattr(层, '条们', None) if 层 is not None else None
        if not 们:
            return True
        try:
            末 = max(们, key=lambda t: t.右 if hasattr(t, '右') else t.x + t.宽)
            屏宽 = int(getattr(层, 'sw', 1920) or 1920)
            return 末.右 <= 屏宽 * 0.20
        except Exception:
            return False

    def _弹幕泵(self):
        """排队放弹幕：上一条快滑到头了，才放下一条。"""
        队 = getattr(self, '_弹幕队', None) or []
        层 = getattr(self, '弹幕', None)
        if 层 is None:
            self._弹幕队 = []
            return
        if 队 and self._弹幕能放下一条():
            try:
                if 层.发(队[0]):
                    队.pop(0)
            except Exception as e:
                try:
                    记右键('弹幕没发出去：%s' % e)
                except Exception:
                    pass
        if not getattr(self, '游戏模式', False):
            self._弹幕队 = []
            return
        if 队 and getattr(self, '_弹幕定时', None) is None:
            try:
                self._弹幕定时 = self.根.after(120, self._弹幕再)
            except Exception:
                self._弹幕定时 = None

    def _弹幕再(self):
        self._弹幕定时 = None
        self._弹幕泵()

    def _试弹幕(self):
        """设置页那个「试一条」：不靠 QQ/DSH，直接塞一条进去看效果。"""
        if not getattr(self, '游戏模式', False):
            return '还没进游戏模式 —— 点手柄，或者上面那个「现在就进游戏模式」'
        self._弹一句('这是一条弹幕')
        return '塞了一条「这是一条弹幕」'

    def _打开陪看(self):
        # ⭐ 0.0.5：点那颗电视图标 = 真的开始听（不再只是把页面调出来）
        # ⭐ 0.0.6：「点了没用」= 左边没勾程序时 start 直接返回。
        #   现在没勾就自动挑「正在出声」的那些，挑不到才回一句人话。
        self._切页('陪看')
        if self.陪看程序 and not getattr(self.陪看程序, 'cap', None):
            开没开 = False
            说法 = ''
            try:
                自动 = getattr(self.陪看程序, '自动开', None)
                if callable(自动):
                    开没开, 说法 = 自动()
                else:
                    self.陪看程序.start()
                    开没开 = bool(getattr(self.陪看程序, 'cap', None))
            except Exception as e:
                说法 = '陪看开不起来：%s' % e
            if not 开没开:
                # 面板上那行小字太小，也在电话页的流水里留一句
                try:
                    self.待显示.put(('提示', '· ' + (说法 or '陪看没开起来')))
                except Exception:
                    pass
            if 开没开 and 配置.get('陪看带麦克风', True) and not self.通话:
                self._开通话()
        self._刷功能行()

    # ---------- 电话 ----------
    def _点电话(self):
        self._切页('电话')
        self._开通话()

    def _开通话(self):
        if self.通话:
            return
        self.通话 = True
        if hasattr(self, '状态'):
            self.状态.configure(text='准备麦克风…', fg=字次)
        self._刷功能行()
        self._开耳朵()

    def _开耳朵(self):
        """只准开一个耳朵。

        ⚠ 1.0.6：以前这里只看 `self.耳朵`，而它是**建完才赋值**的 —— 电话和按住说话挤在同一瞬间时，
          两边都以为「还没有耳朵」，于是各开一个：同一句话被听两遍、发两遍
          （诊断日志里会看到成对的「开麦克风」「10 秒：收到 N 块」）。
        """
        if getattr(self, '耳朵', None) or getattr(self, '_开耳朵中', False):
            return
        self._开耳朵中 = True
        try:
            self._开耳朵_真的()
        finally:
            self._开耳朵中 = False

    def _开耳朵_真的(self):
        if not paths.语音就绪():
            # 没装模型就别装样子：告诉客人怎么装，别让麦克风空转
            paths.补内置语音()
            self.待显示.put(('提示', '· 还没装语音模型 —— 点上面的上半块（设置页）装一下，一次就好'))
            if hasattr(self, '状态'):
                try:
                    self.状态.configure(text='还没装语音', fg=红)
                except Exception:
                    pass
            return
        try:
            from ear import 耳朵, 找设备
        except Exception:
            self._写('麦克风识别没能启动，请检查语音组件。')
            return
        设备, 说法 = 找设备(配置.get('mic_device'), 配置.get('mic_device_name') or '')
        if str(说法 or '').startswith('原来选的') or '没找到' in str(说法 or ''):
            self.待显示.put(('提示', '· ' + 说法 + '（想换的话点上面那块 → 麦克风）'))
        # ⚠ 2026-10-27（重复的根源）：挂断再开通话时，旧线程可能还没退干净 ——
        #   两个耳朵同时识别同一只麦克风，同一句话就被发两遍。给每个实例编号，旧号的结果一律丢。
        self._耳朵代 = getattr(self, '_耳朵代', 0) + 1
        代 = self._耳朵代
        self.耳朵 = 耳朵(
            依赖目录='',                      # 打包后 sherpa 就在程序里，不用再挂目录
            模型目录=paths.模型目录(),
            # ⚠ 2026-10-27：识别到一句就**在识别线程里直接发** ——
            #   以前只往 待显示 里塞、靠主线程的 _刷屏 去发；陪看和电话一起开时
            #   主线程被 ASR 挤住，句子就压在队列里发不出去。
            on_text=lambda t, 代=代: self._收到识别(t, 代),
            on_state=lambda *a: self.待显示.put(('状态', a)),
            device=设备,
            # 陪看也同时跑一个大模型 —— 电话这边别把核占满（4 → 2），
            # 不然两边一起开时，谁都被拖慢（2026-10-27 的「开了电话陪看就不发」）
            num_threads=2,
        )
        self.耳朵.开()

    def _列麦克风(self):
        """给回话口 / DSH 设置页看的：能录的麦克风 + 现在用的是哪个。"""
        try:
            from ear import 列输入设备
            设备 = 列输入设备()
        except Exception:
            设备 = []
        return {'列表': 设备,
                '当前': {'编号': 配置.get('mic_device'),
                         '名字': 配置.get('mic_device_name') or ''},
                '通话': bool(self.通话)}

    def 换麦克风(self, 编号, 名字=''):
        """改麦克风：存配置；电话开着就让主线程重开一次耳朵（HTTP 线程不碰 Tk）。"""
        c = dict(配置)
        c['mic_device'] = 编号
        c['mic_device_name'] = 名字 or ''
        落 = False
        try:
            落 = paths.写配置(c)
        except Exception:
            落 = False
        if 落:
            配置.update(c)
        try:
            from ear import 找设备
            _, 说法 = 找设备(编号, 名字 or '')
        except Exception:
            说法 = ''
        try:
            if self.通话:
                self.待显示.put(('换麦', None))
        except Exception:
            pass
        return 说法 or ('已换成 %s' % (名字 or '系统默认'))

    def _挂断(self):
        if self.耳朵:
            self.耳朵.停()
            self.耳朵 = None
        self.通话 = False
        try:
            self._刷功能行()
        except Exception:
            pass
        if hasattr(self, '状态'):
            try:
                self.状态.configure(text='已停下', fg=字次)
            except Exception:
                pass

    # ---------- 送出去 ----------
    def _收到识别(self, 文本, 代=None):
        """电话听到一句：界面上记一笔（走队列），同时**立刻**发出去（不走主线程）。"""
        # 旧耳朵（挂断前那个）晚到的结果，丢掉
        if 代 is not None and 代 != getattr(self, '_耳朵代', 0):
            return
        # ⚠ 1.0.5：电话没开、也没在按住说话 —— 这时候收到识别结果说明有残留的耳朵在跑，
        #   绝不能往会话里发（以前就是这么一直发的）。
        if not getattr(self, '通话', False) and getattr(self, '_按住待发', None) is None \
                and getattr(self, '_按住中', None) is None:
            记右键('没人该在听，却听到一句，跳过：%s' % str(文本)[:20])
            return
        # 同一句话两秒内只算一次（两路麦克风/线程偶尔会各报一遍）
        现 = time.time()
        上次 = getattr(self, '_上次识别', None)
        if 上次 and 上次[0] == 文本 and 现 - 上次[1] < 2.0:
            return
        self._上次识别 = (文本, 现)
        self.待显示.put(('你', 文本))
        # ⭐ 1.0.3：这句是「按住说话」说的 → 连同那张图一起发
        按住 = getattr(self, '_按住待发', None)
        if 按住 is not None and 现 - float(按住.get('起') or 现) < 25:
            self._按住待发 = None
            if 按住.get('带图'):
                for _ in range(24):          # 最多等 0.6 秒：按下那一下的图可能还在压
                    if 按住.get('图'):
                        break
                    time.sleep(0.025)
            self._送图文(文本, 按住.get('图'))
            return
        try:
            if getattr(self, '陪看程序', None):
                self.陪看程序.q.put(('phone', 文本))
        except Exception:
            pass
        self._送(文本)

    def _记电话(self, 话):
        try:
            import time as _t
            路 = os.path.join(paths.用户目录(), '电话-诊断.log')
            with open(路, 'a', encoding='utf-8') as f:
                f.write(_t.strftime('%H:%M:%S') + '  ' + str(话) + '\n')
        except Exception:
            pass

    def _送(self, 文本):
        端口 = 配置.get('dsh_port', 8777)
        路径 = 配置.get('dsh_path', '/hands/say')
        数据 = json.dumps({'text': 文本, 'session': 配置.get('session') or '',
                          '随机搭话秒': int(配置.get('随机搭话秒') or 0)},
                          ensure_ascii=False).encode('utf-8')

        def 跑():
            req = urllib.request.Request('http://127.0.0.1:%d%s' % (端口, 路径), data=数据,
                                         headers={'Content-Type': 'application/json'})
            try:
                with 本机直连.open(req, timeout=8) as r:
                    r.read()
                self.待显示.put(('提示', '· 发过去了'))
                self._记电话('送出：' + str(文本)[:40])
            except Exception as e:
                # 把**服务端自己说的原因**摆出来（比如「那间会话没开着」），
                # 别一律写成「没连上」—— 那会让人一直去查网络。
                原因 = ''
                try:
                    原因 = json.loads(e.read().decode('utf-8')).get('说', '')
                except Exception:
                    原因 = ''
                原因 = 原因 or str(e)[:70]
                self.待显示.put(('提示', '· 没发出去：' + 原因))
                self._记电话('没发出去：' + 原因)

        threading.Thread(target=跑, daemon=True).start()

    # ---------- 气泡：她那句话显示在鱼旁边（不装朗读桥也能看） ----------
    def _冒气泡(self, 文本, 重建=False):
        if not bool(self.配置.get('气泡开', True)):
            return
        try:
            import bubble
            if 重建:
                self.气泡 = None
            if getattr(self, '气泡', None) is None:
                基 = paths.资源目录()
                字体路 = _字体路(self.配置.get('气泡字体'))
                self.气泡 = bubble.气泡(
                    self.根,
                    os.path.join(基, 'assets', '气泡框.png'),
                    字体路,
                    字色=str(self.配置.get('气泡字色') or '#1c3a52'),
                    描边=int(self.配置.get('气泡描边', 2) or 0))
                # ⭐ 1.1.0：淡入淡出按设定帧率走（60 / 120）
                try:
                    self.气泡.设帧率(int(self.配置.get('气泡帧率') or 60))
                except Exception:
                    pass
            try:
                秒 = float(self.配置.get('气泡秒') or 6)
            except Exception:
                秒 = 6.0
            球径 = int(getattr(self, '球径', 0) or 0) or 132
            try:
                球x, 球y = self._浮窗位置
            except Exception:
                球x = 球y = 0
            self.球框 = (int(球x), int(球y), int(球径), int(球径))
            try:
                大小 = float(self.配置.get('气泡大小') or 85) / 100.0
            except Exception:
                大小 = 0.85
            try:
                换页秒 = float(self.配置.get('气泡换页秒') or 4)
            except Exception:
                换页秒 = 4.0
            self.气泡.显示(文本, 秒=秒, 球径=球径, 球框=self.球框,
                       大小=max(0.5, min(1.6, 大小)), 换页秒=换页秒)
        except Exception as e:
            try:
                记右键('气泡没冒出来：%s' % e)
            except Exception:
                pass

    # ---------- 刷屏 ----------
    def _写(self, 文本):
        if not self.通话:
            return
        self.流水.configure(state='normal')
        self.流水.insert('end', 文本 + '\n')
        self.流水.see('end')
        self.流水.configure(state='disabled')

    def _刷屏(self):
        while True:
            try:
                谁, 内容 = self.待显示.get_nowait()
            except queue.Empty:
                break
            if 谁 == '状态' and self.通话:
                态, *附 = 内容
                if 态 == 'loading':
                    self.状态.configure(text='正在准备麦克风…', fg=字次)
                elif 态 == 'listening':
                    self.状态.configure(text='● 正在听', fg=绿)
                elif 态 == 'idle':
                    self.状态.configure(text='○ 停了', fg=字次)
                elif 态 == 'error':
                    self.状态.configure(text='✕ ' + (附[0] if 附 else '出错'), fg=红)
                    self._写('✕ ' + (附[0] if 附 else '出错'))
            elif 谁 == '你':
                # ⚠ 2026-10-27：句子在 _收到识别 里已经直接发过了，
                #   这里再 _送 一次就会发两遍（日志里「送出」同一条出现两次就是这个）。
                self._写('你：' + 内容)
            elif 谁 == '换麦':
                # 设置页 / DSH 那边改了麦克风：在主线程里重开耳朵（HTTP 线程不碰 Tk）
                try:
                    if self.通话:
                        记右键('设置里换了麦克风：重开耳朵')
                        self._挂断()
                        self._开通话()
                        if not getattr(self, '通话', False):
                            记右键('⚠ 换麦之后电话没开起来（现在显示「关」）')
                except Exception as e:
                    记右键('换麦出错：%s' % e)
            elif 谁 == '回复':
                if getattr(self, '游戏模式', False):
                    # ⭐ 0.7.0：游戏模式里不冒气泡，改成弹幕滑过去 + 进弹幕框
                    try:
                        记右键('来了一句回复（游戏模式里）→ 走弹幕')
                    except Exception:
                        pass
                    self._弹一句(内容)
                    self.未读回话.append(内容)
                    self.未读回话 = self.未读回话[-50:]
                    continue
                try:
                    记右键('来了一句回复 → 冒气泡（%d 字，气泡开=%s）'
                           % (len(str(内容)), bool(self.配置.get('气泡开', True))))
                except Exception:
                    pass
                self._冒气泡(内容)
                if self.通话 and hasattr(self, '流水'):
                    self._写('大肥鱼：' + 内容)
                else:
                    self.未读回话.append(内容)
                    self.未读回话 = self.未读回话[-50:]
            else:
                self._写(内容)
        self.根.after(120, self._刷屏)

    def _退出(self, 保存位置=True):
        记右键('执行 _退出（保存位置=%s）' % 保存位置)
        try:
            if getattr(self, '回话口', None):
                self.回话口.停()
        except Exception:
            pass
        self._挂断()
        self._清陪看()
        if 保存位置:
            self._存位置()
        if self.托盘:
            self.托盘.销毁()
            self.托盘 = None
        if self.分层图:
            self.分层图.销毁()
            self.分层图 = None
        if self.浮窗:
            self.浮窗.销毁()
        if self.面板:
            try:
                self.面板.destroy()
            except Exception:
                pass
        self.根.destroy()


def 自测():
    import tkinter as tk
    开DPI()
    搭 = 鱼搭子(tk)
    搭.根.update_idletasks()
    断言 = [('鱼图悬浮窗可用', 搭.分层图 is not None and 搭.球画 is not None),
            ('保留配置里的鱼图大小（%d，按缩放算出来是 %d）' % (搭.球径, 搭._算球径()),
             搭.球径 == 搭._算球径()),
            ('程序进入 Windows 托盘', 搭.托盘 is not None),
            ('鱼图启动后就是主页面', 搭.面板 is None),
            ('电话图标热区正确', 命中悬浮按钮(.315 * 搭.球径, .785 * 搭.球径,
                                               搭.球径) == '电话'),
            ('直播图标热区正确', 命中悬浮按钮(.505 * 搭.球径, .785 * 搭.球径,
                                               搭.球径) == '直播'),
            ('游戏图标热区正确', 命中悬浮按钮(.705 * 搭.球径, .785 * 搭.球径,
                                               搭.球径) == '游戏'),
            ('上面那一大块是设置', 命中悬浮按钮(.5 * 搭.球径, .5 * 搭.球径,
                                            搭.球径) == '设置'),
            ('鱼图最上面那块也是设置', 命中悬浮按钮(.5 * 搭.球径, .12 * 搭.球径,
                                              搭.球径) == '设置'),
            ('最下面那点空白不触发任何功能', 命中悬浮按钮(.5 * 搭.球径, .98 * 搭.球径,
                                              搭.球径) is None)]
    菜单 = 搭._建右键菜单()
    菜单项 = [菜单.entrycget(i, 'label') for i in range(菜单.index('end') + 1)
              if 菜单.type(i) == 'command']
    断言.append(('右键菜单有单独的退出按钮', '退出' in 菜单项))
    菜单.destroy()
    菜单2 = 搭._建右键菜单()
    项们2 = [菜单2.entrycget(i, 'label') for i in range(菜单2.index('end') + 1)
             if 菜单2.type(i) == 'command']
    断言.append(('托盘也用系统原生菜单，里面有隐藏和退出（%s）' % '、'.join(项们2),
                  any('悬浮窗' in x for x in 项们2) and any('退出' in x for x in 项们2)))
    菜单2.destroy()
    搭._切页('电话')
    搭.根.update_idletasks()
    断言.append(('点击电话才打开电话功能窗', 搭.面板 is not None and 搭.当前页 == '电话'))
    断言.append(('左上角使用鱼图标', 搭._图标已设置))
    断言.append(('电话功能显示在同一功能窗', 搭.当前页 == '电话' and hasattr(搭, '流水')))
    断言.append(('切换页面不会自动打开麦克风', 搭.耳朵 is None))
    搭.通话 = True
    搭._选择功能('直播')
    搭.根.update_idletasks()
    # ⭐ 0.0.5：摘页**不再**停功能 —— 电话和陪看可以同时开
    断言.append(('切到陪看不会停掉电话（功能并行）', 搭.当前页 == '陪看' and 搭.通话 is True))
    断言.append(('看直播显示在功能窗内', 搭.陪看程序 is not None))
    搭._刷功能行()
    搭.根.update_idletasks()
    断言.append(('顶上有三盏功能灯（电话 / 陪看 / 游戏）',
                 hasattr(搭, '灯电话') and hasattr(搭, '灯陪看') and hasattr(搭, '灯游戏')))
    断言.append(('电话开着时灯是「在听」', '在听' in str(搭.灯电话.cget('text'))))
    断言.append(('游戏灯跟着游戏模式走', '游戏' in str(搭.灯游戏.cget('text'))))
    搭._选择功能('游戏')
    断言.append(('打游戏保留代码占位且不另开窗口',
                 搭.当前页 == '游戏' and 搭.面板.state() == 'withdrawn'))
    # 拖动判定：上面那块按住不动 = 开设置；按住挪开 = 拖窗口（不误触）
    class 假事件:
        def __init__(self, x, y, xr, yr):
            self.x, self.y, self.x_root, self.y_root = x, y, xr, yr

    起点 = (400, 160)
    搭._鼠标按下(假事件(起点[0], 起点[1], 1000, 500))
    搭._鼠标拖动(假事件(起点[0] + 2, 起点[1] + 1, 1002, 501))
    断言.append(('只挪 2 像素不算拖（避免点一下变拖动）', 搭._拖过 is False))
    搭._鼠标拖动(假事件(起点[0] + 40, 起点[1] + 30, 1040, 530))
    断言.append(('挪开 40 像素就算拖', 搭._拖过 is True))
    位置 = 搭._浮窗位置
    断言.append(('拖完窗口真的跟着走了', isinstance(位置, tuple) and len(位置) == 2))
    搭._拖动起点 = None

    搭._选择功能('设置')
    搭.根.update_idletasks()
    设 = getattr(搭, '设置件', None)
    断言.append(('点上面那块能开出设置页', 搭.当前页 == '设置' and 设 is not None))
    断言.append(('设置页里有语音状态和装语音按钮',
                 设 is not None and hasattr(设, '语音状态') and hasattr(设, '装钮')))
    断言.append(('设置页里有端口/会话/回调三栏',
                 设 is not None and all(hasattr(设, k) for k in ('端口', '会话', '回调'))))
    断言.append(('设置页里能读到现在配的端口',
                 设 is not None and str(设.端口.get()).isdigit()))
    断言.append(('语音没装时状态显示「还没装」或「已装好」之一',
                 设 is not None and ('还没装' in 设.语音状态.cget('text')
                                     or '已经装好' in 设.语音状态.cget('text'))))
    # ⭐ 设置页：一项一项点开改，不是一长条堆着
    断言.append(('设置页分成了几页（不再堆一长条）',
                 设 is not None and hasattr(设, '页们') and len(设.页们) >= 4))
    断言.append(('最前面三项是 语音 / 陪看 / 游戏（%s）' % (getattr(设, '页名', ()),),
                 设 is not None and tuple(设.页名[:3]) == ('语音', '陪看', '游戏')))
    断言.append(('「游戏」那页先放出来了（内容以后再填）',
                 设 is not None and '游戏' in getattr(设, '页们', {})))
    断言.append(('陪看页里「多久说一句」是按秒填的',
                 设 is not None and hasattr(设, '搭话秒') and str(设.搭话秒.get()).isdigit()))
    # ⭐ 0.3.0：秒数框按回车也得存，存完旁边得有个提示
    断言.append(('两个秒数框旁边都有「已存」提示位',
                 设 is not None and hasattr(设, '搭话提示') and hasattr(设, '抽帧提示')))
    断言.append(('秒数框接上了「回车也存」',
                 设 is not None and callable(getattr(设, '_秒框接上', None))
                 and callable(getattr(设, '_闪存好', None))))
    断言.append(('每一页都能上下滚',
                 设 is not None and len(getattr(设, '画们', [])) >= 4))
    切好了 = False
    try:
        设._切('关于')
        切好了 = (设.当前 == '关于')
        设._切('语音')
    except Exception:
        pass
    断言.append(('点左列能换页', 切好了))

    # ⭐ 麦克风：别人的机器上系统默认常常不是他想用的那只，得能自己挑
    断言.append(('设置页里有麦克风下拉', 设 is not None and hasattr(设, '麦框') and hasattr(设, '麦选')))
    断言.append(('麦克风下拉默认停在「系统默认」',
                 设 is not None and '系统默认' in str(设.麦选.get())))
    try:
        import ear as 耳
        设备表 = 耳.列输入设备()
        断言.append(('能列出这台机器上能录的麦克风',
                      isinstance(设备表, list) and len(设备表) >= 1))
        断, 说明 = 耳.找设备(9999, '根本不存在的麦克风')
        断言.append(('选了不存在的麦克风会退回系统默认', 断 is None and '不在了' in str(说明)))
        if 设备表:
            断2, _ = 耳.找设备(设备表[0]['编号'], '')
            断言.append(('按设备号能找回麦克风', 断2 == 设备表[0]['编号']))
    except Exception as e:
        断言.append(('能列出这台机器上能录的麦克风（%s）' % e, False))

    # ⭐ 陪看：点一下就该开（没勾程序就自动挑在出声的），挑不到得说人话
    断言.append(('陪看有「点一下就开」的入口', hasattr(搭.陪看程序, '自动开') if 搭.陪看程序 else False))
    # ⭐ 0.3.0：框字幕 / 框抽帧就摆在陪看面板上，不用每次都开设置
    断言.append(('陪看面板上能直接框字幕和框抽帧',
                 bool(搭.陪看程序) and hasattr(搭.陪看程序, 'btn_box_sub')
                 and hasattr(搭.陪看程序, 'btn_box_frame')
                 and callable(getattr(搭.陪看程序, '框字幕', None))
                 and callable(getattr(搭.陪看程序, '框抽帧', None))))
    断言.append(('陪看面板上也有「不要」「整屏」两个反向操作',
                 bool(搭.陪看程序) and hasattr(搭.陪看程序, 'btn_sub_off')
                 and hasattr(搭.陪看程序, 'btn_frame_full')
                 and callable(getattr(搭.陪看程序, '不要字幕', None))
                 and callable(getattr(搭.陪看程序, '整屏', None))))
    断言.append(('陪看面板上写着现在框到哪儿了', hasattr(搭.陪看程序, '框说明') if 搭.陪看程序 else False))
    # ⭐ 气泡：不装朗读桥也能看见她的话
    try:
        图路 = os.path.join(paths.资源目录(), 'assets', '气泡框.png')
        字体路 = os.path.join(paths.资源目录(), 'assets', '字体', 'ZCOOLKuaiLe-Regular.ttf')
        断言.append(('气泡图和字体都在（打包会带上）', os.path.exists(图路) and os.path.exists(字体路)))
        import bubble as _泡
        泡 = _泡.气泡(搭.根, 图路, 字体路)
        断言.append(('气泡内区量得出来（不是整张图）',
                    泡.内[2] - 泡.内[0] > 200 and 泡.内[3] - 泡.内[1] > 60 and 泡.内[0] > 60))
        体, 行们, 行高, 字号 = 泡.排字('这一集她一直没说话，光是听着你念叨那道菜的做法。等字幕滚到「小火慢炖」的时候。')
        宽内 = 泡.内[2] - 泡.内[0] - 16
        断言.append(('字每行都不超出气泡（%d 行 / %d 号）' % (len(行们), 字号),
                     # +12 是给「禁则」留的：句读会跟着上一行走，允许挂出去一点
                     len(行们) <= 泡.最多行 and all(体.getlength(x) <= 宽内 + 12 for x in 行们)))
        图 = 泡.合成('这一集她一直没说话，光是听着你念叨那道菜的做法。')
        断言.append(('气泡能合成出图（大小和框一致）', 图.size == 泡.图.size))
        # ⭐ 0.9.2：框的大小只看球和百分比，不跟着字多少变
        泡.最宽 = 500
        图短 = 泡.合成('嗯')
        图长 = 泡.合成('这一集她一直没说话，光是听着你念叨那道菜的做法，等字幕滚到小火慢炖的时候。')
        断言.append(('气泡框不会因为字少就变小（%s / %s）' % (图短.size, 图长.size), 图短.size == 图长.size))
        # ⭐ 0.9.2：话太长就分页，不是砍掉一半
        页们, _, _, _ = 泡.排页('这一集她一直没说话，光是听着你念叨那道菜的做法。等字幕滚到「小火慢炖」的时候，'
                              '她才慢慢把话接上，说这道菜的关键其实不在火候，而在最开始那一下翻炒的手感。')
        断言.append(('话太长会分页（%d 页）' % len(页们), len(页们) >= 2))
        断言.append(('分页不丢字', ''.join(''.join(p) for p in 页们).replace(chr(10), '')
                     == '这一集她一直没说话，光是听着你念叨那道菜的做法。等字幕滚到「小火慢炖」的时候，'
                        '她才慢慢把话接上，说这道菜的关键其实不在火候，而在最开始那一下翻炒的手感。'))
        # ⭐ 0.9.4：字号跟着框走；数字和英文不拆到两行
        泡.最宽 = 400
        泡._按宽(400)
        _, _, 号小 = 泡._定字号()
        泡.最宽 = 800
        泡._按宽(800)
        _, _, 号大 = 泡._定字号()
        断言.append(('气泡字号跟着框缩放（%d 号 → %d 号）' % (号小, 号大), 号大 > 号小))
        泡.最宽 = 500
        泡._按宽(500)
        页们2, _, _, _ = 泡.排页('这台机器 87.5% 的电量还算可以')
        行们2 = [行 for p in 页们2 for 行 in p]
        断言.append(('数字/英文不会被拆到两行（%s）' % 行们2,
                     all(not 行.rstrip().endswith('87.') and not 行.lstrip().startswith('5%')
                         and 'Deep' not in 行[-5:] for 行 in 行们2)))
        # ⭐ 0.9.5：每一行都要落在气泡那一段白里（不许压到画上的手、顶出圆弧）
        页们3, 体3, 行高3, _ = 泡.排页('间；太长，又像海报贴在屏幕上，压得人喘不过气。'
                                  '我觉得最合适的，是让气泡跟着你说话时的呼吸节奏一鼓一鼓。')
        越界 = []
        块高3 = 行高3 * len(页们3[0])
        顶3 = 泡.内[1] + max(0, ((泡.内[3] - 泡.内[1]) - 块高3) // 2)
        for i, 行 in enumerate(页们3[0]):
            左3, 右3 = 泡._行范围(顶3 + i * 行高3 + 行高3 // 2, 行高3)
            if 体3.getlength(行) > (右3 - 左3) + 2:
                越界.append(行)
        断言.append(('气泡：每行都写在气泡的白里（%d 行）' % len(页们3[0]), not 越界))
    except Exception as e:
        断言.append(('气泡那条（%s）' % e, False))
    # ⭐ 0.2.4：语言和模型都不给选了 —— 少了两个下拉，就不会有人选错
    try:
        陪 = 搭.陪看程序
        断言.append(('陪看不再有「语言」下拉', not hasattr(陪, 'lang')))
        断言.append(('陪看不再有「模型」下拉', not hasattr(陪, 'eng')))
        import watch_ui as _陪
        断言.append(('识别引擎默认走「高精度」（没装就自动退回小的那份）',
                     callable(getattr(_陪, '建引擎', None))))
    except Exception as e:
        断言.append(('陪看不给选语言/模型（%s）' % e, False))
    try:
        import watch_ui
        进程表, 读错 = watch_ui.list_audio_processes()
        断言.append(('打包版也读得到「谁在出声」' + (('（%s）' % 读错) if 读错 else ''), not 读错))
        断言.append(('读出来的是一张进程表', isinstance(进程表, list)))
    except Exception as e:
        断言.append(('打包版也读得到「谁在出声」（%s）' % e, False))
    try:
        陪 = 搭.陪看程序
        原刷 = 陪.refresh
        原勾 = list(陪.pchecks)
        陪.refresh = lambda: None      # 别真去刷新（会把上次的目标勾回来）
        陪.pchecks = []                # 假装一个都没勾
        开没, 说法 = 陪.自动开()
        断言.append(('一个都没勾时不会自己乱勾、也不硬开（%s / %s）' % (开没, 说法),
                     开没 is False and '勾' in str(说法)))
        陪.refresh = 原刷
        陪.pchecks = 原勾
    except Exception as e:
        断言.append(('一个都没勾时不会自己乱勾、也不硬开（%s）' % e, False))

    # ⭐ 0.2.0：断句改成「看字」，不再指望 VAD 等静音（片子里永远有环境音）
    try:
        import watch_ui as _陪
        断言.append(('断句：一句带句号就算一句', _陪.拆句('你好啊。') == ['你好啊。']))
        断言.append(('断句：两句话拆成两行', len(_陪.拆句('你好啊。我回来了。')) == 2))
        断言.append(('断句：太短的尾巴并回上一句', _陪.拆句('我回来了。嗯') == ['我回来了。嗯']))
        断言.append(('结尾有句号**不**算说完了（模型每次都加标点）',
                     _陪.该定稿('We are watching.', 1, 1.2) is False))
        断言.append(('没稳定、也没攒满 → 先别落定', _陪.该定稿('你好啊。', 1, 3.0) is False))
        断言.append(('连着几次认出来一样 → 落定', _陪.该定稿('你好啊', 3, 3.0) is True))
        断言.append(('攒满 7 秒还没完 → 硬切', _陪.该定稿('你好啊', 1, 7.0) is True))
        断言.append(('只有音乐没人说话满 12 秒 → 丢掉重来', _陪.该定稿('', 0, 12.0) is True))
        断言.append(('数字里的点不算句末（3.5 米）', _陪.拆句('他有三点五米，3.5 米吧。')[-1].endswith('。')))
        断言.append(('一句 7 秒的话会被拆成几行（%d 行）' % len(_陪.拆句(
                     '其他线索了，没了，就看咱俩谁能先找到。但我先打个电话。感觉绿油油的。')),
                     len(_陪.拆句('其他线索了，没了，就看咱俩谁能先找到。但我先打个电话。感觉绿油油的。')) >= 3))
        # ⭐ 0.2.1：静音段落会吐「그.」这种一个字的垃圾句，长度 2 刚好躲过老检查
        断言.append(('静音时吐的「그.」不算话（%d 个字）' % _陪.有内容('그.'), _陪.有内容('그.') < 2))
        断言.append(('「嗯。」也不够两个字（%d 个字）' % _陪.有内容('嗯。'), _陪.有内容('嗯。') < 2))
        断言.append(('正常一句算得过（「你好」= %d 个字）' % _陪.有内容('你好'), _陪.有内容('你好') >= 2))
        断言.append(('只有标点不算内容', _陪.有内容('……，。') == 0))
    except Exception as e:
        断言.append(('断句看字那几条（%s）' % e, False))

    # ⭐ 0.2.2：读屏幕上的字幕（框选 + OCR）—— 纯逻辑那半先打一打，不加载模型
    try:
        import ocr as _ocr
        断言.append(('字幕：把行首淡入残影削掉', _ocr.清洗('0那你就赶快回去') == '那你就赶快回去'))
        断言.append(('字幕：只有标点的那帧当没字', _ocr.清洗('……，。') == ''))
        断言.append(('字幕：同一句的残缺版算一句',
                     _ocr.像同一句('你是人精灵2', '你是人珏精灵？一') is True))
        断言.append(('字幕：两句不相干的别当成一句',
                     _ocr.像同一句('有道理', '这就是魔境的原因吗') is False))
        断言.append(('字幕：中文日文两行时只挑中文那行',
                     _ocr.挑一行([('マジックビジョンで世に訴えよう', (0, 0, 1, 1)),
                               ('通过魔法影像向大众公布结果', (0, 0, 1, 1))])[0] == '通过魔法影像向大众公布结果'))
        断言.append(('字幕：只剩日文的时候也交得出来',
                     _ocr.挑一行([('いやしっかりニヤニや', (0, 0, 1, 1))])[0] == 'いやしっかりニヤニや'))
        断言.append(('字幕：中文里夹个日文名字不算日文行',
                     _ocr.是日文('通过魔法影像向大众公布结果') is False
                     and _ocr.是日文('アルトアル王国の皆さん') is True))
        断 = _ocr.断句器()
        前三次 = [断.喂('这就是魔境的原因吗') for _ in range(3)]
        断言.append(('字幕：连着三帧一样才算这句出现（前三次都不定稿）',
                     all(x == '' for x in 前三次)))
        断.喂('有道理')
        断.喂('有道理')
        吐 = 断.喂('有道理')            # 第三帧新句 → 前一句走
        断言.append(('字幕：换句时把上一句交出来（%s）' % (吐 or '空'), 吐 == '这就是魔境的原因吗'))
        断.喂('')
        吐2 = 断.喂('')
        断言.append(('字幕：空白两帧就定稿（%s）' % (吐2 or '空'), 吐2 == '有道理'))
        # 模型真加载一次（空图，不该炸也不该出字）——这条保证打包版里 onnxruntime + 模型都在
        try:
            from PIL import Image as _图
            认器 = _ocr.识别器()
            文, 框 = 认器.认(_图.new('RGB', (420, 90), (8, 8, 8)))
            断言.append(('OCR 模型在（打包版里也能加载）', 文 == '' and 框 is None))
        except Exception as e:
            断言.append(('OCR 模型加载（%s）' % e, False))
    except Exception as e:
        断言.append(('读屏幕字幕那几条（%s）' % e, False))

    # ⭐ 0.3.0：抽帧（配台词 + 本地压缩）
    try:
        import frames as _帧
        from PIL import Image as _图2
        此刻 = time.time()
        字幕们 = [{'时': 此刻 + d, '文': t} for d, t in
                [(-18, '一'), (-12, '二'), (-6, '三'), (-1, '四'), (4, '五'), (9, '六')]]
        挑 = _帧.配台词(字幕们, 此刻, 左右=2)
        断言.append(('抽帧：配台词会取这一帧前后几句（%d 句）' % len(挑), 2 <= len(挑) <= 5))
        断言.append(('抽帧：配的台词里有「此刻正在说的那句」', any(x[1] == '四' for x in 挑)))
        图 = _图2.new('RGB', (2560, 1440), (30, 40, 50))
        字, 尺寸 = _帧.压(图, 1280, 75)
        断言.append(('抽帧：2K 能压到 1280 宽（%dx%d，%dKB）' % (尺寸[0], 尺寸[1], len(字) // 1024),
                     尺寸[0] == 1280 and len(字) < 200 * 1024))
    except Exception as e:
        断言.append(('抽帧那几条（%s）' % e, False))

    # 真的走一遍管线（假引擎，不加载模型）：连喂 11 秒音频 → 必须自己落一句话出来
    try:
        import threading
        import numpy as _np
        import watch_ui as _陪

        class 假引擎:
            def transcribe(self, a):
                return '这一句是自测用的，说得挺长的一句话。'

        原间隔 = _陪.认的间隔秒
        条们 = []
        cap = None
        try:
            _陪.认的间隔秒 = 0.0          # 自测不等 1.2 秒
            cap = _陪.Captioner(engine='sense', partial=False,
                                on_line=lambda t, m: 条们.append((m, t)))
            cap.engine = 假引擎()
            threading.Thread(target=cap._process, daemon=True).start()
            for _ in range(11 * 20):      # 11 秒（每秒 20 块 800 样本）
                cap.q.put(_np.zeros(800, dtype=_np.float32))
                time.sleep(0.002)
            time.sleep(0.6)
        finally:
            _陪.认的间隔秒 = 原间隔
            if cap is not None:
                cap.stop_flag.set()
        断言.append(('11 秒一直说话 → 自己会落定（不用等静音）%s' % (条们[:1],),
                     any(m == 'final' for m, _ in 条们)))
        断言.append(('落定的一句是完整话，不是碎片',
                     条们 and '。' in 条们[0][1] and len(条们[0][1]) >= 4))
    except Exception as e:
        断言.append(('连喂 11 秒音频会自动落定（%s）' % e, False))

    # ⭐ 0.7.6：气泡排字绝对不会排到框外
    try:
        泡 = getattr(搭, '气泡', None)
        if 泡 is not None:
            泡.最宽 = 604
            泡._按宽(604)
            体, 行们, 行高, 字号 = 泡.排字('很长的句子' * 30)
            高内 = 泡.内[3] - 泡.内[1]
            断言.append(('气泡：字再多也不会排到框外（%d 行，字号 %d，占高 %d/%d）'
                         % (len(行们), 字号, 行高 * len(行们), 高内),
                         len(行们) <= 泡.最多行 and 行高 * len(行们) <= 高内))
            断言.append(('气泡：字号有下限（%d ≥ 15）' % 字号, 字号 >= 15))
    except Exception as e:
        断言.append(('气泡排版那两条（%s）' % e, False))

    # ⭐ 0.7.0：游戏模式的弹幕（纯逻辑那半，不开窗）
    try:
        import danmaku as _弹
        断言.append(('弹幕：去掉 ** 记号，几段都留着（不再只取第一行）',
                     搭._取一句('**第一行**' + chr(10) + chr(10) + '第二行') == '第一行' + chr(10) + '第二行'))
        断言.append(('弹幕：长句一个字都不丢（%d 字）' % len(搭._取一句('字' * 80)),
                     len(搭._取一句('字' * 80)) == 80))
        图 = _弹.画一句('测试弹幕', 26)
        断言.append(('弹幕：能量出一张图（%dx%d）' % 图.size, 图.size[0] > 30 and 图.size[1] > 20))
        层 = _弹.弹幕层(None, (0, 0, 1920, 1080), 字号=26, 秒每屏=6, 最多=10)
        断言.append(('弹幕：屏幕能分出几条跑道（%d 条）' % 层._道数(), 层._道数() >= 5))
        # ⭐ 1.0.0：帧率能选 60 / 120（间隔跟着变）
        _层60 = _弹.弹幕层(None, (0, 0, 1920, 1080), 字号=26, 帧率=60)
        _层120 = _弹.弹幕层(None, (0, 0, 1920, 1080), 字号=26, 帧率=120)
        断言.append(('弹幕：60/120 帧的间隔对得上（%dms / %dms）' % (_层60._间隔, _层120._间隔),
                     _层60._间隔 == 17 and _层120._间隔 == 8))
        # ⭐ 1.0.1：长句在句号/逗号处断开，不把一个字劈到两条里
        _文2 = '说回片子。我一直记着她那段自我介绍：爱好是按时吃药静养，喜欢的调味料是盐。'
        _块2 = _弹.拆弹幕(_文2, 28)
        断言.append(('弹幕：长句按标点断开（%s）' % '｜'.join(_块2),
                     all(len(x) <= 28 for x in _块2) and ''.join(_块2) == _文2
                     and all(x[-1] in '。！？；…，、：,:' for x in _块2[:-1])))
        框 = _弹.弹幕框.__new__(_弹.弹幕框)          # 不建窗，只量「夹回屏幕里」这段
        框.sx, 框.sy, 框.sw, 框.sh, 框.宽, 框.高 = 0, 0, 2560, 1440, 520, 380
        断言.append(('弹幕框：放左上不会跑出屏幕（%s）' % (框._收到框内(-999, -999),),
                     框._收到框内(-999, -999) == (0, 0)))
        断言.append(('弹幕框：放右下也不会出去（%s）' % (框._收到框内(99999, 99999),),
                     框._收到框内(99999, 99999) == (2560 - 520, 1440 - 380)))
        # ⭐ 0.8.6：分层窗口建出来是隐藏的，贴完必须 ShowWindow —— 她那边「只看见一个 ✕」就是这条
        try:
            import ctypes as _ct
            _u = _ct.windll.user32
            _层 = _弹.弹幕层(搭.根, (0, 0, 1280, 720), 字号=24)
            _层.发('这是一条弹幕')
            _看得见 = bool(_层.条们) and bool(_u.IsWindowVisible(_层.条们[0].窗.hwnd))
            _层.停()
            断言.append(('飘的弹幕窗口真的显示出来了（不是隐藏的）', _看得见))
        except Exception as e:
            断言.append(('飘的弹幕能不能显示（%s）' % e, False))
        # ⭐ 0.9.3：整个游戏模式真的起得来（两块都建出来），不是「单独能跑」
        # ⚠ 0.9.8：自测不能被用户自己的开关影响 —— 先替它把「飘的弹幕 / 弹幕框」打开，跑完还原
        旧弹幕开 = 配置.get('弹幕开')
        旧框开 = 配置.get('弹幕框开')
        配置['弹幕开'] = True
        配置['弹幕框开'] = True
        try:
            搭._进游戏模式()
            层了 = getattr(搭, '弹幕', None)
            断言.append(('游戏模式：飘的弹幕建起来了（%s）' % ('有' if 层了 else
                         '没建；游戏模式=%s 弹幕开=%s' % (getattr(搭, '游戏模式', None), 配置.get('弹幕开'))),
                         层了 is not None))
            框了 = getattr(搭, '弹幕框', None)
            断言.append(('游戏模式：弹幕框建起来了（%s）' % (('(宽%d 高%d)' % (框了.宽, 框了.高)) if 框了 else '没建'),
                         框了 is not None))
        except Exception as e:
            断言.append(('游戏模式能不能整个起来（%s）' % e, False))
        finally:
            try:
                搭._退出游戏()
            except Exception:
                pass
            配置['弹幕开'] = 旧弹幕开
            配置['弹幕框开'] = 旧框开
    except Exception as e:
        断言.append(('弹幕那几条（%s）' % e, False))

    # ⭐ 屏幕缩放：远程把系统缩放从 125% 调到 150%，鱼也得跟着变大
    原倍 = 配置.get('ui_scale')
    原基 = 配置.get('ui_scale_base')
    原底 = 配置.get('ball_size')
    原跟 = 配置.get('跟随系统缩放')
    原显示 = 搭.显示缩放
    try:
        配置['ball_size'] = 120            # 小底数：免得撞到「不超过屏幕 45%」那道上限
        配置['ui_scale_base'] = 1.0
        配置['跟随系统缩放'] = False
        配置['ui_scale'] = 1.0
        搭.显示缩放 = 1.0
        一 = 搭._算球径()
        配置['ui_scale'] = 2.0
        二 = 搭._算球径()
        断言.append(('手动放大一倍，球也大一倍（%s → %s）' % (一, 二), abs(二 - 一 * 2) <= 2))
        配置['ui_scale'] = 1.0
        搭.显示缩放 = 1.5
        三 = 搭._算球径()
        断言.append(('没勾「跟着系统缩放」时，屏幕缩放不动球（%s = %s）' % (一, 三), 三 == 一))
        配置['跟随系统缩放'] = True
        四 = 搭._算球径()
        断言.append(('勾了之后 100%% → 150%%，球跟着变 1.5 倍（%s → %s）' % (一, 四),
                     abs(四 - int(round(一 * 1.5))) <= 2))
        断言.append(('设置页里有「悬浮窗大小」的调节',
                     设 is not None and hasattr(设, '大小标签')))
    except Exception as e:
        断言.append(('球的倍率那几条（%s）' % e, False))
    finally:
        搭.显示缩放 = 原显示
        配置['ui_scale'] = 原倍
        配置['ui_scale_base'] = 原基
        配置['ball_size'] = 原底
        配置['跟随系统缩放'] = 原跟

    # ⚠ 先把结果落文件，再打印：控制台是 GBK 的时候，断言名字里带个非中文（比如一个韩文字）
    #   就会 UnicodeEncodeError 把整个自测打断（2026-10-26 踩到）。文件是 UTF-8，不受影响。
    结语 = '共 %d 项，失败 %d 项' % (len(断言), sum(1 for _, ok in 断言 if not ok))
    try:   # 打包成 exe 之后没有控制台，落一份在用户目录里好查
        with open(os.path.join(paths.用户目录(), '自测结果.txt'), 'w', encoding='utf-8') as f:
            for 名, 过 in 断言:
                f.write(('PASS ' if 过 else 'FAIL ') + 名 + chr(10))
            f.write(结语 + chr(10))
    except Exception:
        pass
    for 名, 过 in 断言:
        try:
            print(('PASS ' if 过 else 'FAIL ') + 名)
        except Exception:
            try:  # 控制台编码装不下就换成 ?，别让一条打印把整轮自测打断
                print((('PASS ' if 过 else 'FAIL ') + 名).encode('gbk', 'replace').decode('gbk'))
            except Exception:
                pass
    try:
        print(结语)
    except Exception:
        pass
    搭._退出(保存位置=False)


if __name__ == '__main__':
    import tkinter as tk
    import traceback
    开DPI()
    if '--selftest' in sys.argv:
        自测()
    else:
        try:
            搭 = 鱼搭子(tk)
            搭.根.mainloop()
        except Exception:
            with open(os.path.join(paths.用户目录(), '出错了.log'), 'a', encoding='utf-8') as f:
                f.write(traceback.format_exc() + chr(10) * 2)
            raise
