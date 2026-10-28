# -*- coding: utf-8 -*-
"""字幕 OCR（读屏幕上的字幕）—— 只用 onnxruntime，不依赖 opencv。

工作方式：
  · 设置里点「框字幕」，盖一层遮罩，像 Windows 那样拖一个框；**松手框就消失**，只记住坐标；
  · 之后陪看优先读**框里那行字**（官方字幕），框里连续没字才退回听声音。

引擎是 PP-OCRv6 的 small 版两个模型（检测 9.5MB + 识别 20.3MB，放 `%LOCALAPPDATA%\\鱼搭子\\ocr`）：
  检测 → 概率图直接用 numpy 求行列投影拿到那一行的框（**不用 opencv 找轮廓**）→ 识别。
实测（本机、动画硬字幕）：平均 72ms 一帧，比系统自带 OCR 准（系统的会把「被称为魔境」读成「被称艹一」，
短句直接读不到）。

断句三条规矩（真跑出来的经验，别改回去）：
  1. 同一段文字**连续 3 帧**才算这句真出现 —— 字幕淡入那两帧是残缺的；
  2. 跟当前这句**很像**（最长公共子序列占比 ≥ 0.6）就当同一句，留更完整的那版；
  3. 只在**字幕消失**时定稿 —— 换行不算，这样一句只推一次。
"""
import ctypes
import os
import threading
import time

import numpy as np
from PIL import Image, ImageGrab

import paths

检测文件 = 'PP-OCRv6_det_small.onnx'
识别文件 = 'PP-OCRv6_rec_small.onnx'

稳帧数 = 3            # 连续几帧一样才算这句出现
空帧数 = 2            # 连续几帧没字才算字幕消失
相似门槛 = 0.6


def 目录():
    return os.path.join(paths.用户目录(), 'ocr')


def 就绪():
    """两个模型都在用户目录里就算就绪；少了的话先从程序自带的 assets\\ocr 拷一份过来。"""
    d = 目录()
    缺 = [f for f in (检测文件, 识别文件) if not os.path.exists(os.path.join(d, f))]
    if 缺:
        源 = os.path.join(paths.资源目录(), 'assets', 'ocr')
        try:
            os.makedirs(d, exist_ok=True)
            for f in 缺:
                从 = os.path.join(源, f)
                if os.path.exists(从):
                    import shutil
                    shutil.copyfile(从, os.path.join(d, f))
        except Exception:
            pass
    return all(os.path.exists(os.path.join(d, f)) for f in (检测文件, 识别文件))


# ---------------- 引擎 ----------------
class 识别器:
    """检测 + 识别。第一次用的时候才加载模型（几十毫秒），别在启动时拖慢程序。"""

    def __init__(self):
        self._检测 = None
        self._识别 = None
        self._字表 = None
        self._锁 = threading.Lock()

    def _起(self):
        if self._检测 is not None:
            return
        import onnxruntime as ort
        d = 目录()
        选 = ['CPUExecutionProvider']
        self._检测 = ort.InferenceSession(os.path.join(d, 检测文件), providers=选)
        self._识别 = ort.InferenceSession(os.path.join(d, 识别文件), providers=选)
        表 = self._识别.get_modelmeta().custom_metadata_map.get('character') or ''
        self._字表 = [''] + 表.split('\n')      # 0 是 CTC 的 blank

    def 认(self, 图):
        """图 = PIL 图或 H×W×3 的 numpy（RGB）。返回 (文字, 框 or None)。

        ⭐ 0.4.9：
           以前把最上到最下的**整块**压成一行去认 —— 框里要是有中日两行字幕，
           两行就被挤成一句。现在按行切段、每段单独认，再**先挑中文那行**交出去。
        """
        with self._锁:
            self._起()
            a = np.asarray(图.convert('RGB') if isinstance(图, Image.Image) else 图, dtype=np.uint8)
            行们 = []
            for 框 in self._找多行(a):
                左, 上, 右, 下 = 框
                文 = 清洗(self._识(a[上:下, 左:右]))
                if 文:
                    行们.append((文, 框))
            if not 行们:
                return '', None
            return 挑一行(行们)

    # 检测：压到长边 640（宽高必须是 32 的倍数，不然 onnxruntime 里 Resize 会报错）
    def _找多行(self, a):
        """返回若干个「一行字」的框（从上到下）—— 两行字幕就是两个框。"""
        h, w = a.shape[:2]
        比例 = 640.0 / max(h, w)
        新宽 = max(32, int(np.ceil(w * 比例 / 32.0)) * 32)
        新高 = max(32, int(np.ceil(h * 比例 / 32.0)) * 32)
        小 = np.asarray(Image.fromarray(a).resize((新宽, 新高), Image.BILINEAR), dtype=np.float32) / 255.0
        小 = (小 - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
        概率 = self._检测.run(None, {'x': 小.transpose(2, 0, 1)[None, ...]})[0][0, 0]
        够 = max(2, int(新高 * 0.02))
        行们 = np.where((概率 > 0.3).sum(axis=1) >= 够)[0]
        if not len(行们):
            return []
        # 按行投影切成几段：段内算同一行，段与段之间的空白就是字幕行距
        空隙 = max(3, int(新高 * 0.012))
        段们 = []
        起 = 上 = int(行们[0])
        for i in 行们[1:]:
            i = int(i)
            if i - 上 <= 空隙:
                上 = i
            else:
                段们.append((起, 上))
                起 = 上 = i
        段们.append((起, 上))
        sy, sx = 新高 / float(h), 新宽 / float(w)
        出 = []
        for 段上, 段下 in 段们:
            带 = 概率[段上:段下 + 1, :]
            列们 = np.where((带 > 0.3).sum(axis=0) >= 2)[0]
            if not len(列们):
                continue
            上p = max(0, int(段上 / sy) - 8)
            下p = min(h, int(段下 / sy) + 9)
            左p = max(0, int(列们[0] / sx) - 10)
            右p = min(w, int(列们[-1] / sx) + 12)
            if 右p - 左p < 8 or 下p - 上p < 8:
                continue
            出.append((左p, 上p, 右p, 下p))
        return 出

    # 识别：单行 → 高 48、等比宽
    def _识(self, a):
        h, w = a.shape[:2]
        宽 = max(8, int(round(w * 48.0 / max(1, h))))
        图 = np.asarray(Image.fromarray(a).resize((宽, 48), Image.BILINEAR), dtype=np.float32)
        图 = (图 / 255.0 - 0.5) / 0.5
        出 = self._识别.run(None, {'x': 图.transpose(2, 0, 1)[None, ...]})[0][0]
        序 = 出.argmax(axis=1)
        字们, 上 = [], -1
        for i in 序:
            if i != 0 and i != 上:
                字们.append(self._字表[i] if i < len(self._字表) else '')
            上 = i
        return ''.join(字们).strip()


# ---------------- 断句 ----------------
def 算字(t):
    return sum(1 for ch in t if ch.isalnum())


def 假名数(t):
    """一句里有多少个假名（平假名 / 片假名）—— 用来分中文还是日文。"""
    return sum(1 for ch in (t or '') if '\u3040' <= ch <= '\u30ff')


def 是日文(t):
    """有假名、而且占比不低 → 当成日文那行。"""
    n = 算字(t)
    if n < 2:
        return False
    return 假名数(t) / float(n) >= 0.15


def 挑一行(行们):
    """从认出来的几行里挑该交出去的那行：**有中文就中文**，只剩日文才用日文。

    口径：语音识别是兜底，字幕优先；字幕里也中文优先
    （同一句的日文和中文各发一遍，看着就是重复）。
    """
    if not 行们:
        return '', None
    中文们 = [x for x in 行们 if not 是日文(x[0])]
    选 = 中文们 or list(行们)
    return max(选, key=lambda x: (算字(x[0]), len(x[0])))


def 清洗(t):
    """去掉首尾不是字的东西（`0那你就…` 这种淡入残影）。"""
    t = (t or '').strip()
    if len(t) >= 4 and t[0] == '0' and t[1].isalnum() and ord(t[1]) > 127:
        t = t[1:]
    左, 右 = 0, len(t)
    while 左 < 右 and not (t[左].isalnum() or t[左] in '「『（(【'):
        左 += 1
    while 右 > 左 and not (t[右 - 1].isalnum() or t[右 - 1] in '」』）)】'):
        右 -= 1
    t = t[左:右]
    return t if 算字(t) >= 2 else ''


def 公共子序列(a, b):
    前 = [0] * (len(b) + 1)
    for ca in a:
        当 = [0]
        for j, cb in enumerate(b, 1):
            当.append(前[j - 1] + 1 if ca == cb else max(前[j], 当[j - 1]))
        前 = 当
    return 前[-1]


def 像同一句(a, b):
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    return 公共子序列(a, b) / max(len(a), len(b)) >= 相似门槛


class 断句器:
    """喂「这一帧读到什么」，吐出「该定下来的句子」。纯逻辑，能单测。"""

    def __init__(self):
        self.上帧 = ''
        self.连着同 = 0
        self.候选 = []
        self.空帧 = 0

    def 最好(self):
        return max(self.候选, key=lambda x: (算字(x), len(x))) if self.候选 else ''

    def 喂(self, 文):
        """返回「这次该定稿的句子」（没有就返回空串）。"""
        文 = 清洗(文)
        if not 文:
            self.上帧, self.连着同 = '', 0
            self.空帧 += 1
            if self.空帧 >= 空帧数 and self.候选:
                好 = self.最好()
                self.候选 = []
                return 好
            return ''
        self.空帧 = 0
        if 文 == self.上帧:
            self.连着同 += 1
        else:
            self.上帧, self.连着同 = 文, 1
        if self.连着同 < 稳帧数:
            return ''
        if not self.候选:
            self.候选 = [文]
        elif 像同一句(self.最好(), 文):
            self.候选.append(文)
        else:
            好 = self.最好()
            self.候选 = [文]
            return 好
        return ''

    def 收尾(self):
        if not self.候选:
            return ''
        好 = self.最好()
        self.候选 = []
        return 好


# ---------------- 抓图 ----------------
def 抓(框):
    """框 = (x, y, 宽, 高)，虚拟桌面坐标。返回 PIL 图；失败返回 None。"""
    try:
        x, y, w, h = [int(v) for v in 框]
        if w < 8 or h < 8:
            return None
        return ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    except Exception:
        return None


# ---------------- 框选遮罩 ----------------
def 屏幕们():
    """[(左, 上, 右, 下)]，物理像素。"""
    import tkinter as tk
    结果 = []

    class RECT(ctypes.Structure):
        _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long),
                    ('right', ctypes.c_long), ('bottom', ctypes.c_long)]

    def 回调(hMonitor, hdc, lprc, 参数):
        r = ctypes.cast(lprc, ctypes.POINTER(RECT)).contents
        结果.append((r.left, r.top, r.right, r.bottom))
        return 1

    try:
        CALLBACK = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                                      ctypes.POINTER(RECT), ctypes.c_double)
        ctypes.windll.user32.EnumDisplayMonitors(0, 0, CALLBACK(回调), 0)
    except Exception:
        pass
    if not 结果:
        try:
            结果.append((0, 0, tk.Tk().winfo_screenwidth(), tk.Tk().winfo_screenheight()))
        except Exception:
            结果.append((0, 0, 1920, 1080))
    return 结果


def 开框选(根, 完成, 取消=None):
    """盖一层遮罩用来拖框。松手就把遮罩全部销毁，再回调 (x, y, 宽, 高)。"""
    import tkinter as tk

    层们 = []
    状态 = {'起': None, '矩形': None, '屏': None}

    def 收工(框):
        for 层 in 层们:
            try:
                层['窗'].destroy()
            except Exception:
                pass
        层们.clear()
        try: 根.grab_release()
        except Exception:
            pass
        if 框:
            完成(框)
        elif 取消:
            取消()

    def 按(层, e):
        状态['起'] = (e.x_root, e.y_root)
        状态['屏'] = 层
        if 状态['矩形']:
            层['画'].delete(状态['矩形'])
        左, 上 = e.x_root - 层['左'], e.y_root - 层['上']
        状态['矩形'] = 层['画'].create_rectangle(左, 上, 左, 上, outline='#3fa9f5', width=3)

    def 拖(层, e):
        if not 状态['起'] or 状态['屏'] is not 层:
            return
        起左, 起上 = 状态['起'][0] - 层['左'], 状态['起'][1] - 层['上']
        现左, 现上 = e.x_root - 层['左'], e.y_root - 层['上']
        if 状态['矩形']:
            层['画'].coords(状态['矩形'], 起左, 起上, 现左, 现上)
        层['字'].configure(text='松手就选好了（Esc 取消）  %d × %d' % (abs(现左 - 起左), abs(现上 - 起上)))

    def 松(层, e):
        if not 状态['起'] or 状态['屏'] is not 层:
            return
        x1, y1 = 状态['起']
        x2, y2 = e.x_root, e.y_root
        左, 右 = sorted([x1, x2])
        上, 下 = sorted([y1, y2])
        if 右 - 左 < 16 or 下 - 上 < 10:
            收工(None)
        else:
            收工((int(左), int(上), int(右 - 左), int(下 - 上)))

    for (l, t, r, b) in 屏幕们():
        窗 = tk.Toplevel(根)
        窗.overrideredirect(True)
        窗.attributes('-topmost', True)
        try:
            窗.attributes('-alpha', 0.35)
        except Exception:
            pass
        窗.configure(bg='black')
        窗.geometry('%dx%d+%d+%d' % (r - l, b - t, l, t))
        画 = tk.Canvas(窗, bg='black', highlightthickness=0, cursor='crosshair')
        画.pack(fill='both', expand=True)
        字 = tk.Label(窗, text='在这里拖一个框，把**字幕那一行**框住（松手就生效；Esc 取消）',
                     bg='#101418', fg='#e8f1f8', font=('Microsoft YaHei UI', 11))
        字.place(relx=0.5, y=24, anchor='n')
        层 = {'窗': 窗, '画': 画, '字': 字, '左': l, '上': t}
        层们.append(层)
        for 事件, 处理 in (('<ButtonPress-1>', 按), ('<B1-Motion>', 拖), ('<ButtonRelease-1>', 松)):
            画.bind(事件, lambda e, 层=层, f=处理: f(层, e))
        窗.bind('<Escape>', lambda e: 收工(None))
        画.focus_set()

    try:
        根.grab_set()
    except Exception:
        pass
