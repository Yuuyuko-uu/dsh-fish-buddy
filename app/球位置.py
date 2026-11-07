"""球该放哪儿 —— 纯函数，不碰 tkinter，方便测（issue #7）。

三块屏非矩形拼接时，「虚拟屏幕」那个外接矩形里有大块没有显示器的空洞。
以前默认位置和外接矩形对齐，球就落进洞里：人看不见，程序却认为它在显示状态。
"""
import ctypes
import os


def 枚举显示器(兜底=(0, 0, 1920, 1080)):
    """每块屏的 (x, y, 宽, 高)。拿不到就返回兜底那一条。"""
    try:
        if os.name == 'nt':
            from ctypes import wintypes
            u = ctypes.windll.user32
            屏们 = []

            def 回调(hMon, hdc, rect, data):
                r = rect.contents
                屏们.append((int(r.left), int(r.top),
                             int(r.right - r.left), int(r.bottom - r.top)))
                return 1

            函数型 = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.POINTER(wintypes.RECT), ctypes.c_double)
            u.EnumDisplayMonitors(0, 0, 函数型(回调), 0)
            if 屏们:
                return 屏们
    except Exception:
        pass
    return [兜底]


def 主屏(屏们):
    """原点 (0,0) 落在哪块屏上，那块就是主屏；查不到就挑面积最大的。"""
    屏们 = list(屏们 or [])
    if not 屏们:
        return (0, 0, 1920, 1080)
    for 屏 in 屏们:
        sx, sy, sw, sh = 屏
        if sx <= 0 < sx + sw and sy <= 0 < sy + sh:
            return 屏
    return max(屏们, key=lambda s: s[2] * s[3])


def 落哪块屏(屏们, x, y):
    """点 (x,y) 在哪块屏上；落在空洞里就挑离得最近的那块。"""
    屏们 = list(屏们 or [])
    if not 屏们:
        return (0, 0, 1920, 1080)
    for 屏 in 屏们:
        sx, sy, sw, sh = 屏
        if sx <= x <= sx + sw and sy <= y <= sy + sh:
            return 屏
    最近, 最小 = 屏们[0], None
    for 屏 in 屏们:
        sx, sy, sw, sh = 屏
        dx = max(sx - x, 0, x - (sx + sw))
        dy = max(sy - y, 0, y - (sy + sh))
        距 = dx * dx + dy * dy
        if 最小 is None or 距 < 最小:
            最近, 最小 = 屏, 距
    return 最近


def 限位置(屏们, 球径, x, y):
    """把球关进它所在那块屏里（不是整个虚拟屏幕）。"""
    x, y = int(x), int(y)
    sx, sy, sw, sh = 落哪块屏(屏们, x, y)
    return (max(sx, min(x, sx + sw - 球径)),
            max(sy, min(y, sy + sh - 球径)))


def 默认位置(屏们, 球径, 边距=48, 竖向比例=0.55):
    """没存过位置时的落点：主屏右侧偏下。"""
    sx, sy, 宽, 高 = 主屏(屏们)
    return 限位置(屏们, 球径, sx + 宽 - 球径 - 边距, sy + int(高 * 竖向比例))
