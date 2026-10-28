"""语音模型：一键下载。

只要两种文件（约 230MB + 1MB）：
    model.int8.onnx   SenseVoice 的中文模型（最好用的那一个，别的引擎都不带了）
    tokens.txt        它的词表
VAD 那个 silero_vad.onnx 很小，直接打在程序里（`asr_models/silero_vad.onnx`），
第一次用时拷到用户目录。

下载策略：**镜像优先、官方兜底**；能续传（下到 .part，断了再点接着下）；
代理连不上就直连再试一次（本机有 127.0.0.1:12000 的代理，代理挂了不该让下载卡死）。
"""
import os
import threading
import time
import urllib.request

import paths

模型名 = paths.语音模型名

源们 = {
    'model.int8.onnx': [
        'https://hf-mirror.com/csukuangfj/{m}/resolve/main/{f}',
        'https://huggingface.co/csukuangfj/{m}/resolve/main/{f}',
    ],
    # ⭐ 0.2.4：fp32 那份（「高精度」）跟 int8 在同一个仓库，只是文件名不同
    'model.onnx': [
        'https://hf-mirror.com/csukuangfj/{m}/resolve/main/{f}',
        'https://huggingface.co/csukuangfj/{m}/resolve/main/{f}',
    ],
    'tokens.txt': [
        'https://hf-mirror.com/csukuangfj/{m}/resolve/main/{f}',
        'https://huggingface.co/csukuangfj/{m}/resolve/main/{f}',
    ],
}

# 两种取法：先按系统代理（本机 12000 端口能用），不行再直连
_带代理 = urllib.request.build_opener()
_直连 = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _打开(地址, 头, 超时):
    错 = None
    for 开 in (_带代理, _直连):
        try:
            return 开.open(urllib.request.Request(地址, headers=头), timeout=超时)
        except Exception as e:
            错 = e
    raise 错 if 错 else RuntimeError('打不开')


class 下载器:
    """后台下模型；界面每 300ms 读一次 `进度()` 就行。"""

    def __init__(self, 文件们=None, 路径=None, 就绪=None):
        # 默认下「基础语音模型」；传 文件们/路径/就绪 就能下「高精度」那份（用法见文件结尾的 高精度下载器()）
        self._文件们 = tuple(文件们) if 文件们 else tuple(paths.语音文件)
        self._路径 = 路径 or paths.语音路径
        self._就绪 = 就绪 or paths.语音就绪
        self._基础 = 文件们 is None and 路径 is None
        self.锁 = threading.Lock()
        self.状态 = {
            '进行中': False,
            '完成': False,
            '出错': '',
            '当前文件': '',
            '已下字节': 0,
            '总字节': 0,
            '速度': 0.0,        # 字节/秒
            '第几个': 0,
            '共几个': len(self._文件们),
            '说': '',
        }
        self._线程 = None
        self._停 = threading.Event()

    # ---------- 对外 ----------
    def 进度(self):
        with self.锁:
            return dict(self.状态)

    def 开始(self):
        with self.锁:
            if self.状态['进行中']:
                return False
            self.状态.update({'进行中': True, '完成': False, '出错': '', '已下字节': 0, '总字节': 0, '说': '准备下载'})
            self._停.clear()
        self._线程 = threading.Thread(target=self._跑, daemon=True)
        self._线程.start()
        return True

    def 停(self):
        self._停.set()

    # ---------- 内部 ----------
    def _改(self, **kw):
        with self.锁:
            self.状态.update(kw)

    def _跑(self):
        try:
            if self._基础:
                paths.补内置语音()
            总 = 0
            for i, 名 in enumerate(self._文件们):
                if self._停.is_set():
                    self._改(进行中=False, 说='停了')
                    return
                if self._已完整(名):
                    self._改(第几个=i + 1, 说='「%s」已经有了' % 名)
                    continue
                self._改(当前文件=名, 第几个=i + 1, 说='正在下「%s」' % 名)
                总 += self._下一个(名, i)
            if self._停.is_set():
                self._改(进行中=False, 说='停了')
                return
            if self._基础:
                paths.补内置语音()
            ok = self._就绪()
            self._改(进行中=False, 完成=ok, 总字节=总,
                     说='好了，可以说话了' if ok else '下完了但文件不齐，点「再试一次」')
        except Exception as e:
            self._改(进行中=False, 出错=str(e), 说='没下成：' + str(e))

    def _已完整(self, 名):
        路 = self._路径(名)
        if not os.path.exists(路):
            return False
        return os.path.getsize(路) > 1024 * 1024 if 名.endswith('.onnx') else os.path.getsize(路) > 1024

    def _下一个(self, 名, 序):
        目标 = self._路径(名)
        临时 = 目标 + '.part'
        最后错 = None
        for 模板 in 源们.get(名, []):
            地址 = 模板.format(m=模型名, f=名)
            # 同一个源先试 3 次（断了就接着下，别一下子把已经下的白扔）
            for _ in range(3):
                if self._停.is_set():
                    return 0
                已有 = os.path.getsize(临时) if os.path.exists(临时) else 0
                try:
                    头 = {'User-Agent': 'fishbuddy/1.0'}
                    if 已有:
                        头['Range'] = 'bytes=%d-' % 已有
                    回 = _打开(地址, 头, 30)
                    码 = getattr(回, 'status', 200)
                    if 码 == 200:
                        已有 = 0          # 服务器不认续传，从头来
                        模式 = 'wb'
                    elif 码 == 206:
                        模式 = 'ab'
                    else:
                        raise RuntimeError('HTTP %d' % 码)
                    长 = int(回.headers.get('Content-Length') or 0)
                    总长 = 已有 + 长
                    已 = 已有
                    起时 = time.time()
                    起量 = 已
                    with open(临时, 模式) as f:
                        while True:
                            if self._停.is_set():
                                回.close()
                                return 0
                            块 = 回.read(256 * 1024)
                            if not 块:
                                break
                            f.write(块)
                            已 += len(块)
                            用 = time.time() - 起时
                            速 = (已 - 起量) / 用 if 用 > 0.2 else 0
                            self._改(已下字节=已, 总字节=总长, 速度=速)
                    回.close()
                    if 总长 and 已 < 总长:
                        raise RuntimeError('没下完（%d/%d）' % (已, 总长))
                    os.replace(临时, 目标)
                    return 已
                except Exception as e:
                    最后错 = e
                    time.sleep(1.5)
                    continue
        raise RuntimeError('「%s」所有源都没下成：%s' % (名, 最后错))


def 一下载器():
    return 下载器()


