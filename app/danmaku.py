"""游戏模式的弹幕：一条条从右往左滑过去，外加一个能累积的弹幕框。

做法跟气泡一样：**分层窗口**（逐像素透明）+ 只移动窗口不重贴图。
    ⚠ 不自己注册 WndProc（64 位下签名一错就整进程崩）。
    ⚠ 冻结包里所有 Win32 指针参数都用 c_void_p + cast(byref(...))。
"""

import ctypes
import os
import random
import time
from ctypes import wintypes as wt

from PIL import Image, ImageDraw, ImageFont

import bubble

user32 = ctypes.windll.user32
# ⭐ 1.0.0：120 帧要用 1ms 定时器精度（Tk 的 after 走的是系统定时器，默认 ~15.6ms）
winmm = ctypes.windll.winmm
try:
    winmm.timeBeginPeriod.argtypes = [ctypes.c_uint]
    winmm.timeBeginPeriod.restype = ctypes.c_uint
    winmm.timeEndPeriod.argtypes = [ctypes.c_uint]
    winmm.timeEndPeriod.restype = ctypes.c_uint
except Exception:
    pass
_定时精度 = False

SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = -1

HERE = os.path.dirname(os.path.abspath(__file__))
字路 = os.path.join(HERE, 'assets', '字体', 'ZCOOLKuaiLe-Regular.ttf')

user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.SetWindowPos.restype = ctypes.c_int
# ⭐ 0.9.8：一次把好几条一起挪（DeferWindowPos 打包发）——
#   一条一条 SetWindowPos 太慢，帧数上不去，看着就一跳一跳的。
try:
    user32.BeginDeferWindowPos.argtypes = [ctypes.c_int]
    user32.BeginDeferWindowPos.restype = ctypes.c_void_p
    user32.DeferWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_uint]
    user32.DeferWindowPos.restype = ctypes.c_void_p
    user32.EndDeferWindowPos.argtypes = [ctypes.c_void_p]
    user32.EndDeferWindowPos.restype = ctypes.c_int
except Exception:
    pass


def 批量移(项们):
    """[(hwnd, x, y), ...] 一次挪到新位置；打包失败就退回一条条挪。"""
    if not 项们:
        return
    try:
        h = user32.BeginDeferWindowPos(len(项们))
        if not h:
            raise RuntimeError('BeginDeferWindowPos 没给句柄')
        for hwnd, x, y in 项们:
            h = user32.DeferWindowPos(h, hwnd, HWND_TOPMOST, int(x), int(y), 0, 0,
                                      SWP_NOSIZE | SWP_NOACTIVATE)
            if not h:
                raise RuntimeError('DeferWindowPos 中途失败')
        user32.EndDeferWindowPos(h)
        return
    except Exception:
        pass
    for hwnd, x, y in 项们:
        try:
            user32.SetWindowPos(hwnd, HWND_TOPMOST, int(x), int(y), 0, 0,
                                SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:
            pass

try:
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
    user32.GetCursorPos.restype = ctypes.c_int
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
except Exception:
    pass
_鼠标点 = wt.POINT()


def 字体(字号, 路=None):
    # ⭐ 1.3.2：建好的字体要**登记路径**，bubble 那边靠它查「这个字体有没有这个字」
    #   （没登记就等于「未知」，一律当作有 → 颜文字永远是方块）。
    实路 = 路 or 字路
    try:
        体 = ImageFont.truetype(实路, int(字号))
    except Exception:
        try:
            体 = ImageFont.truetype(字路, int(字号))
            实路 = 字路
        except Exception:
            return ImageFont.load_default()
    try:
        bubble.字体路径登记(体, 实路)
    except Exception:
        pass
    return 体


def 画一句(文本, 字号=26, 字色=(255, 255, 255), 描边=(40, 40, 60), 描边宽=3, 路=None):
    """一句话 → 一张 RGBA 图（白字深描边，跟弹幕姬一样好认）。"""
    文 = str(文本 or '').strip()
    if not 文:
        return None
    字 = 字体(字号, 路)          # ⚠ 别把循环变量取名叫 字体，这里会撞成局部变量
    路实 = 路 or 字路
    # ⭐ 1.3.2：弹幕也走「一句话两种字体」—— 站酷没有的颜文字/符号换成系统字体，
    #   以前这里只有一种字体，游戏模式里飘过去就是一串方块。
    段们 = bubble.切混排(文, 字, 路实, 字号)
    try:
        主上, 主下 = 字.getmetrics()
    except Exception:
        主上, 主下 = int(字号), int(字号 * 0.3)
    宽段 = 0.0
    for 段, 用字 in 段们:
        try:
            宽段 += 用字.getlength(段)
        except Exception:
            宽段 += 字.getlength(段)
    宽 = max(1, int(round(宽段)) + 描边宽 * 2 + 6)
    高 = max(1, int(主上 + 主下) + 描边宽 * 2 + 6)
    图 = Image.new('RGBA', (宽, 高), (0, 0, 0, 0))
    笔 = ImageDraw.Draw(图)
    基 = 描边宽 + 3 + 主上              # 基线：主字体的 ascent 往下挪
    x = float(描边宽 + 3)
    for 段, 用字 in 段们:
        if not 段:
            continue
        try:
            笔.text((x, 基), 段, font=用字, fill=字色 + (255,),
                   stroke_width=描边宽, stroke_fill=描边 + (255,), anchor='ls')
        except TypeError:
            笔.text((x, 基 - 主上), 段, font=用字, fill=字色 + (255,))
        try:
            x += 用字.getlength(段)
        except Exception:
            x += 字.getlength(段)
    return 图


_句末 = '。！？；…!?;）)'
_句中 = '，、：,:'


def 切句(文本):
    """按句号 / 问号 / 叹号切句，标点跟着前一句走。"""
    句们, 当 = [], ''
    for 字 in str(文本 or ''):
        if 字 in ' \t\r\n':
            continue
        当 += 字
        if 字 in _句末:
            句们.append(当)
            当 = ''
    if 当:
        句们.append(当)
    return 句们


def 拆弹幕(文本, 限=28):
    """把一段话拆成几条弹幕 —— **跟弹幕框一样按「一句一句」分**，不按字数切。

    ⭐ 1.5.3：口径统一成「一条弹幕 = 一句话」：
      · 先按换行分段，再按句号/问号/叹号/分号切句（标点跟着前一句走）；
      · 一句**超过 2 倍上限**才退到逗号切（长句不断开就没法看）；
      · 再长（超过 4 倍）才硬切，切完剩下的整段保留，不丢字；
      · 绝不把标点丢到下一条开头。
    """
    限 = max(8, int(限))
    文 = str(文本 or '').strip()
    if not 文:
        return []
    块们 = []
    for 段 in 文.split('\n'):
        段 = 段.strip()
        if not 段:
            continue
        for 句 in 切句(段):
            # ⭐ 1.5.4：**一句就是一条**，绝不把两句并成一条 ——
            #   太长（> 4 倍上限）才往下切，切也是在这句内部切。
            if len(句) <= 限 * 4:
                块们.append(句)
                continue
            # 超长句：先按逗号切（逗号跟着前一段走）
            for 小 in _按标点分(句, _句中):
                if len(小) <= 限 * 2:
                    块们.append(小)
                    continue
                切点 = _最佳切点(小, 限)
                if 切点 <= 0:
                    切点 = 限
                块们.append(小[:切点])
                尾 = 小[切点:]
                while 尾 and len(尾) > 限 * 4:
                    块们.append(尾[:限])
                    尾 = 尾[限:]
                if 尾:
                    块们.append(尾)
    return 块们 or [文]


def _最佳切点(文本, 限):
    """在一段没有标点的长句里找一个**像样的**断点：限附近最近的标点/空格后面；找不到就 -1。"""
    标点们 = '。！？；…，、：,;.!? \t'
    最好 = -1
    最好远 = 10 ** 9
    for i, 字 in enumerate(文本[:限 + 6]):
        if 字 in 标点们:
            远 = abs((i + 1) - 限)
            if 远 < 最好远:
                最好远 = 远
                最好 = i + 1
    return 最好


def _按标点分(文本, 标点们):
    段们, 当 = [], ''
    for 字 in 文本:
        当 += 字
        if 字 in 标点们:
            段们.append(当)
            当 = ''
    if 当:
        段们.append(当)
    return 段们


class 一条:
    """一条弹幕：一个分层小窗，靠 SetWindowPos 移动（不重贴图，才够快）。"""

    def __init__(self, 图, x, y):
        self.窗 = bubble.分层窗()
        self.窗.贴图(图, int(x), int(y))
        # ⚠ 0.8.6：分层窗口建出来是**隐藏**的，
        #   UpdateLayeredWindow 只画不显示，必须再 ShowWindow 一次才看得见。
        self.窗.显()
        self.宽, self.高 = 图.size
        self.x, self.y = float(x), float(y)

    def 移到(self, x):
        self.x = float(x)
        try:
            user32.SetWindowPos(self.窗.hwnd, HWND_TOPMOST, int(self.x), int(self.y),
                                0, 0, SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:
            pass

    @property
    def 右(self):
        return self.x + self.宽

    def 关(self):
        try:
            self.窗.关()
        except Exception:
            pass


class 弹幕层:
    """屏幕上有几条弹幕在滑；分跑道，同一条跑道不叠字。"""

    def __init__(self, 根, 屏框, 字号=26, 秒每屏=6.0, 最多=10, 顶留=80, 底留=90,
                 字色=(255, 255, 255), 描边=(40, 40, 60), 路=None, 区域='全屏', 帧率=60):
        self.根 = 根
        self.sx, self.sy, self.sw, self.sh = 屏框
        self.字号 = max(12, int(字号))
        self.秒每屏 = max(1.0, float(秒每屏))
        self.最多 = max(1, int(最多))
        # ⭐ 1.0.0：每秒画几帧（60 / 120）。120 需要把系统定时器精度提到 1ms，见 _要120()
        self.帧率 = 120 if int(帧率 or 60) >= 100 else 60
        self._间隔 = max(4, int(round(1000.0 / self.帧率)))
        self.条们 = []
        self.道空 = {}          # 跑道号 -> 右边界（这条跑道最后一条的右边到哪了）
        self.字色 = 字色
        self.描边 = 描边
        self.路 = 路
        # ⭐ 0.8.0：全屏 / 上半屏 / 下半屏
        self.区域 = 区域 or '全屏'
        if self.区域 == '上半屏':
            self.顶留, self.底留 = 60, int(self.sh * 0.52)
        elif self.区域 == '下半屏':
            self.顶留, self.底留 = int(self.sh * 0.52), 90
        else:
            self.顶留, self.底留 = int(顶留), int(底留)
        self._定时 = None

    # ---------- 跑道 ----------
    def 改(self, 字号=None, 秒每屏=None, 最多=None, 帧率=None):
        """就地改样式：不用重建，下一条弹幕就按新的来。"""
        if 字号 is not None:
            self.字号 = max(12, min(96, int(字号)))
        if 秒每屏 is not None:
            self.秒每屏 = max(1.0, float(秒每屏))
        if 最多 is not None:
            self.最多 = max(1, int(最多))
        if 帧率 is not None:
            self.帧率 = 120 if int(帧率) >= 100 else 60
            self._间隔 = max(4, int(round(1000.0 / self.帧率)))
            self._要120()
        return True

    def _要120(self):
        """120 帧得先把系统定时器精度提到 1ms —— 不然 Tk 的 after 最快也就 ~15.6ms（约 64 帧）。"""
        global _定时精度
        if self.帧率 < 100:
            self._放精度()
            return
        if _定时精度:
            return
        try:
            winmm.timeBeginPeriod(1)
            _定时精度 = True
        except Exception:
            _定时精度 = False

    def _放精度(self):
        global _定时精度
        if not _定时精度:
            return
        try:
            winmm.timeEndPeriod(1)
        except Exception:
            pass
        _定时精度 = False

    def _道高(self):
        return int(self.字号 * 1.9)

    def _道数(self):
        可用 = max(1, self.sh - self.顶留 - self.底留)
        return max(1, min(12, 可用 // self._道高()))

    def _选道(self, 图宽):
        """找一条已经让开的跑道；都占着就等（返回 None）。

        ⭐ 0.8.0：在**让开的**跑道里随机挑，
        不然总从最上面那条开始，看着像排队。
        """
        道数 = self._道数()
        闲着 = []
        for i in range(道数):
            右 = self.道空.get(i, -1e9)
            if 右 < self.sw - 30:        # 上一条的尾巴已经离开右边界
                闲着.append(i)
        if not 闲着:
            return None
        # 前 3 条里随机（太随机会显得乱，也容易两条挨太近）
        闲着.sort(key=lambda i: self.道空.get(i, -1e9))
        return random.choice(闲着[:3])

    def _道y(self, i):
        return self.sy + self.顶留 + i * self._道高()

    # ---------- 发 ----------
    def 发(self, 文本):
        图 = 画一句(文本, self.字号, 字色=self.字色, 描边=self.描边, 路=self.路)
        if 图 is None:
            return False
        if len(self.条们) >= self.最多:
            return False
        i = self._选道(图.width)
        if i is None:
            return False
        x = self.sw
        self.条们.append(一条(图, x, self._道y(i)))
        self.道空[i] = x + 图.width
        return True

    def 走一步(self):
        """推进一帧：按**真实过去的时间**算位移，帧率掉了速度也不变。"""
        现在 = time.perf_counter()
        上回 = getattr(self, '_上次走', None)
        self._上次走 = 现在
        dt = 0.016 if 上回 is None else max(0.001, min(0.10, 现在 - 上回))
        像素每秒 = (self.sw + 400) / max(0.5, float(self.秒每屏))
        步 = 像素每秒 * dt
        移 = []
        留 = []
        for 条 in self.条们:
            条.x -= 步
            移.append((条.窗.hwnd, int(条.x), int(条.y)))
            if 条.x + 条.宽 > -30:
                留.append(条)
            else:
                条.关()
        self.条们 = 留
        批量移(移)
        # 跑道空出来：按每条的右边界重算
        for i in range(self._道数()):
            最右 = -1e9
            for 条 in self.条们:
                if abs(条.y - self._道y(i)) < self._道高() / 2:
                    最右 = max(最右, 条.右)
            self.道空[i] = 最右
        return True

    def 开(self):
        if self._定时:
            return
        self._上次走 = None
        self._要120()

        def 跑():
            try:
                self.走一步()
            except Exception:
                pass
            try:
                self._定时 = self.根.after(self._间隔, 跑)
            except Exception:
                self._定时 = None
        跑()

    def 停(self):
        if self._定时:
            try:
                self.根.after_cancel(self._定时)
            except Exception:
                pass
        self._定时 = None
        self._放精度()
        for 条 in self.条们:
            条.关()
        self.条们 = []


class 弹幕框:
    """角上一块会累积的弹幕板（**分层窗口**：逐像素透明，边缘平滑没有黑边锯齿）。

    ⚠ 为什么不用 Tk 窗口：Tk 的 `-transparentcolor` 是**二值**透明 ——
      你那块图边缘是半透明的，抠完就是一圈黑边加锯齿。
      分层窗口走 UpdateLayeredWindow，跟气泡/鱼一样平滑。
    ⚠ 分层窗口鼠标穿透，所以「退出 / 清空」放在右上角那颗小 ✕ 上（那是普通 Tk 窗口，能点）。
    """

    def __init__(self, 根, 屏框, 位置='右下', 宽=380, 高=0, 字号=20, 最多行=12, 菜单=None, 双击=None,
                 设置=None, 锁定=False, 锁切换=None):
        import tkinter as tk

        self.tk = tk
        self.根 = 根
        self.设置 = 设置
        # ⭐ 1.3.4：锁定位置 —— 全屏打游戏时鼠标到处划，框会跟着被拖走。
        #   锁住之后是**真穿透**（WS_EX_TRANSPARENT），鼠标直接穿到游戏里，框一点都接不住。
        self.锁定 = bool(锁定)
        self.锁切换 = 锁切换
        self.sx, self.sy, self.sw, self.sh = 屏框
        self.宽 = max(240, int(宽))
        比例 = 0.0
        路 = os.path.join(HERE, 'assets', '弹幕框.png')
        if os.path.exists(路):
            try:
                with Image.open(路) as 试:
                    比例 = 试.width / float(试.height)
            except Exception:
                比例 = 0.0
        self.高 = max(160, int(高)) if 高 else (int(self.宽 / 比例) if 比例 else 380)
        self.内区 = (0.19, 0.335, 0.83, 0.955) if 比例 else (0.06, 0.12, 0.94, 0.94)
        self.字号 = max(12, int(字号))
        self.最多 = max(3, int(最多行))
        self.行们 = []
        self.位置 = 位置 or '右下'
        self.菜单 = 菜单
        self.双击 = 双击
        self.字体路 = None

        self.窗 = bubble.分层窗(穿透=False)
        # ⭐ 1.3.6：锁着就**真穿透** —— 鼠标直接穿到游戏里，这个窗口一点都接不住
        try:
            self.窗.穿透 = bool(self.锁定)
        except Exception:
            pass
        self._底 = self._底图()
        self.钮区 = {}
        self._上回按 = False
        self._按下处 = None      # 拖动用：按下去时鼠标在屏幕哪儿
        self._按在局 = None      # 按下去时鼠标在框里的哪儿
        self._拖过 = False
        self._上次窗位 = None
        self._重画()
        self._轮询鼠标()

    # ---------- 鼠标（分层窗口没有消息循环，用轮询） ----------
    def 设锁定(self, 开):
        """锁住 = 真穿透（鼠标穿过去）+ 停掉鼠标轮询；解锁相反。"""
        self.锁定 = bool(开)
        try:
            if self.窗:
                self.窗.设穿透(self.锁定)
        except Exception:
            pass
        try:
            if self.锁定:
                if getattr(self, '_定时', None):
                    self.根.after_cancel(self._定时)
                    self._定时 = None
            elif not getattr(self, '_定时', None):
                self._定时 = self.根.after(12, self._轮询鼠标)
        except Exception:
            pass

    def _点(self, 名):
        try:
            if 名 == '回球':
                if callable(self.双击):
                    self.双击()
            elif 名 == '锁':
                if callable(getattr(self, '锁切换', None)):
                    self.锁切换()
            elif 名 == '设置':
                if callable(getattr(self, '设置', None)):
                    self.设置()
                elif callable(self.菜单):
                    self.菜单(None, None)
        except Exception:
            pass

    def _轮询鼠标(self):
        """分层窗口没有窗口过程，鼠标只能靠这里轮询。

        ⭐ 0.9.1：拖动卡顿的原因就是这里 50ms 才看一次（20fps）→ 改成 12ms，
        并且**按下那一刻**就把窗口位置记下来（之后每帧只用「按下点 + 位移」算，不再重新推位置）。
        """
        try:
            if self.窗.hwnd:
                p = _鼠标点
                if user32.GetCursorPos(ctypes.byref(p)):
                    按 = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
                    x, y = self._位置算()
                    在内 = (x <= p.x < x + self.宽) and (y <= p.y < y + self.高)
                    if 按 and not self._上回按:
                        if 在内:
                            局 = (p.x - x, p.y - y)
                            命中 = None
                            for 名, (a, b, c, d) in (self.钮区 or {}).items():
                                if a <= 局[0] <= c and b <= 局[1] <= d:
                                    命中 = 名
                                    break
                            if 命中:
                                self._点(命中)
                            elif not self.锁定:
                                self._按下处 = (p.x, p.y)
                                self._按在局 = (x, y)
                                self._拖过 = False
                            # 锁着就什么都不做：位置不动，也不会误触发双击
                    elif 按 and self._按下处:
                        dx = p.x - self._按下处[0]
                        dy = p.y - self._按下处[1]
                        if abs(dx) > 2 or abs(dy) > 2:
                            self._拖过 = True
                            新x = max(self.sx, min(int(self._按在局[0] + dx), self.sx + self.sw - self.宽))
                            新y = max(self.sy, min(int(self._按在局[1] + dy), self.sy + self.sh - self.高))
                            if (新x, 新y) != (self._上次窗位):
                                self._上次窗位 = (新x, 新y)
                                self.位置 = '自由'
                                self.自由位置 = (新x, 新y)
                                try:
                                    user32.SetWindowPos(self.窗.hwnd, -1, int(新x), int(新y),
                                                        0, 0, 0x0001 | 0x0010)
                                except Exception:
                                    pass
                    elif not 按:
                        self._按下处 = None
                    self._上回按 = 按
        except Exception:
            pass
        try:
            self._定时 = self.根.after(12, self._轮询鼠标)
        except Exception:
            self._定时 = None

    # ---------- 底 ----------
    def _底图(self):
        路 = os.path.join(HERE, 'assets', '弹幕框.png')
        if os.path.exists(路):
            try:
                图 = Image.open(路).convert('RGBA')
                return 图.resize((self.宽, self.高), Image.LANCZOS)
            except Exception:
                pass
        图 = Image.new('RGBA', (self.宽, self.高), (0, 0, 0, 0))
        笔 = ImageDraw.Draw(图)
        笔.rounded_rectangle([0, 0, self.宽 - 1, self.高 - 1], radius=14,
                             fill=(16, 24, 34, 236), outline=(120, 170, 210, 235), width=2)
        return 图

    def _位置算(self):
        if self.位置 == '自由' and getattr(self, '自由位置', None):
            return self._收到框内(*self.自由位置)
        空 = 16
        if self.位置 == '右上':
            x, y = self.sx + self.sw - self.宽 - 空, self.sy + 空
        elif self.位置 == '左上':
            x, y = self.sx + 空, self.sy + 空
        elif self.位置 == '左下':
            x, y = self.sx + 空, self.sy + self.sh - self.高 - 空
        else:
            x, y = self.sx + self.sw - self.宽 - 空, self.sy + self.sh - self.高 - 空
        return self._收到框内(x, y)

    def _收到框内(self, x, y):
        """⭐ 0.7.2：**不许出屏**。"""
        return (max(self.sx, min(int(x), self.sx + self.sw - self.宽)),
                max(self.sy, min(int(y), self.sy + self.sh - self.高)))

    # ---------- 内容 ----------
    def 加(self, 文本):
        文 = str(文本 or '').strip()
        if not 文:
            return
        self.行们.append(文)
        self.行们 = self.行们[-self.最多:]
        self._重画()

    def 设状态(self, 文本):
        """框底那行小状态（比如「已截图待发 · 2 张」）。传空就清掉。"""
        文 = str(文本 or '').strip()
        if 文 == getattr(self, '状态', ''):
            return
        self.状态 = 文
        self._重画()

    def 清(self):
        self.行们 = []
        self._重画()

    def _折行(self, 文, 体, 宽):
        """按像素宽折行（中文没有空格，只能一个字一个字量）。"""
        行们, 当 = [], ''
        for 字 in 文:
            if 体.getlength(当 + 字) > 宽 and 当:
                行们.append(当)
                当 = 字
            else:
                当 += 字
        行们.append(当)
        return [x for x in 行们 if x]

    def _重画(self):
        from PIL import ImageTk

        图 = self._底.copy()
        笔 = ImageDraw.Draw(图)
        左 = int(self.宽 * self.内区[0])
        上 = int(self.高 * self.内区[1])
        右 = int(self.宽 * self.内区[2])
        下 = int(self.高 * self.内区[3])
        体 = 字体(self.字号, getattr(self, '字体路', None))
        体小 = 字体(max(10, self.字号 - 4), getattr(self, '字体路', None))
        行高 = int(self.字号 * 1.55)
        缩进 = int(体.getlength('· '))
        文宽 = max(40, 右 - 左 - 缩进)

        # ⭐ 0.8.0：**不要时间，前面加个「·」**；一排放不下就折到下一排（跟图一样）。
        块们 = []
        for 文 in self.行们:
            块们.append(self._折行(文, 体, 文宽))
        容量 = max(1, (下 - 上) // 行高)
        摆 = []
        用 = 0
        for 行们 in reversed(块们):
            if 用 + len(行们) > 容量:
                break
            摆.append(行们)
            用 += len(行们)
        摆.reverse()
        # ⭐ 0.9.7：一句话就比整个框还长 —— 以前这种只画一个「…」，现在从开头显示满一框
        if not 摆 and 块们:
            摆 = [块们[-1][:容量]]
            用 = len(摆[0])

        y = 上 if 用 * 行高 < (下 - 上) else 下 - 用 * 行高
        for 行们 in 摆:
            for i, 行 in enumerate(行们):
                if i == 0:
                    笔.text((左, y), '· ', font=体, fill=(120, 150, 185, 250))
                # ⭐ 1.3.2：框里的字也走混排（颜文字不再出方块）
                try:
                    基 = y + i * 行高 + 体.getmetrics()[0]
                except Exception:
                    基 = y + i * 行高 + self.字号
                _x = float(左 + 缩进)
                for _段, _字 in bubble.切混排(行, 体, self.字体路 or 字路, self.字号):
                    if not _段:
                        continue
                    try:
                        笔.text((_x, 基), _段, font=_字, fill=(46, 74, 104, 245), anchor='ls')
                    except Exception:
                        笔.text((_x, y + i * 行高), _段, font=_字, fill=(46, 74, 104, 245))
                    try:
                        _x += _字.getlength(_段)
                    except Exception:
                        _x += 体.getlength(_段)
            y += len(行们) * 行高
        if not 摆:
            笔.text((左, 上 + max(0, (下 - 上) // 2 - self.字号)), '…',
                    font=体, fill=(150, 175, 200, 235))
        # ⭐ 1.4.10：那行小状态画在**框内区的最下面**（以前按整窗高度算，落在框边外/框外，看不见）
        try:
            if getattr(self, '状态', ''):
                小号 = max(11, int(self.字号 * 0.66))
                try:
                    小体 = ImageFont.truetype(self.字体路 or 字路, 小号)
                except Exception:
                    小体 = 体小
                底线 = int(下) - max(6, int(self.字号 * 0.28))
                # 底下垫一条淡淡的底色，不然字压在花纹上看不清
                # 左下角有个手柄装饰，往右让一点，别压上去
                起x = int(左) + int(self.字号 * 1.8)
                # 就一行小字，不加白底（框本身就是框，垫白块更难看）
                笔.text((起x, 底线), self.状态, font=小体, fill=(58, 96, 138, 240), anchor='ls')
        except Exception:
            pass
        # ⭐ 0.8.8：图上一个字都不写，热区就是她俩的脑袋（点大肥鱼=设置，点小鲸鱼=回球）
        #   大肥鱼的脑袋 = 设置，小鲸鱼的脑袋 = 回球。图上不加任何字。
        try:
            self.钮区 = {
                '设置': (int(self.宽 * 0.02), int(self.高 * 0.02), int(self.宽 * 0.46), int(self.高 * 0.32)),
                '回球': (int(self.宽 * 0.62), int(self.高 * 0.08), int(self.宽 * 0.99), int(self.高 * 0.34)),
            }
        except Exception:
            pass
        try:
            x, y = self._位置算()
            self.窗.贴图(图, int(x), int(y))
            # ⚠ 0.8.6：分层窗口建出来是隐藏的，贴完必须显一次
            self.窗.显()
        except Exception as e:
            try:
                import ball
                ball.记右键('弹幕框贴图失败：%s' % e)
            except Exception:
                pass

    # ---------- 收尾 ----------
    def 关(self):
        try:
            if getattr(self, '_定时', None):
                self.根.after_cancel(self._定时)
        except Exception:
            pass
        self._定时 = None
        try:
            self.窗.关()
        except Exception:
            pass

