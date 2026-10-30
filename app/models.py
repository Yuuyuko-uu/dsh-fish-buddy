"""语音模型：一键下载（三档可选）。

每档只下两个文件：
    model.onnx    识别模型本体（SenseVoice int8 / fp32，或者 Paraformer）
    tokens.txt    词表
不管哪一档，落到本地都叫 `model.onnx` + `tokens.txt`；分哪一档靠目录区分
（`paths.档目录()`：int8 / paraformer 各一个子目录，fp32 摆在 models\\ 根上）。

VAD 那个 silero_vad.onnx 很小，直接打在程序里（`asr_models/silero_vad.onnx`），
第一次用时拷到那档目录。

下载策略：**镜像优先、官方兜底**；能续传（下到 .part，断了再点接着下）；
代理连不上就直连再试一次（本机有 127.0.0.1:12000 的代理，代理挂了不该让下载卡死）。
"""
import os
import threading
import time
import urllib.error
import urllib.request

import paths


def 源们(档):
    """这一档那两份文件从哪下 —— **官方优先、hf-mirror 兜底**。

    ⭐ 1.5.9：顺序原来反着（镜像在前）。实测镜像现在会 302 到官方 CDN，
    走不通时还直接回 401；而「通QQ」那边一直是官方优先，装得好好的 —— 照它的来。
    """
    项 = paths.语音档们[档]
    仓库 = 项['仓库']
    表 = {}
    for 名 in (项['远端'], 'tokens.txt'):
        表[名] = [
            'https://huggingface.co/%s/resolve/main/%s' % (仓库, 名),
            'https://hf-mirror.com/%s/resolve/main/%s' % (仓库, 名),
        ]
    return 表


# ⭐ 1.5.9：取模型的那几条路。
#   以前只试「系统代理 → 直连」两种，可很多人（包括本机）环境里根本没有代理变量，
#   而 hf-mirror 现在会 302 到 huggingface 的 CDN，直连那一下会一直挂着 ——
#   表现出来就是进度条停在「0.0/? MB」一动不动。
#   现在按顺序试：系统代理 → 本机几个常见代理端口（挂着客户端但没设环境变量的情况）→ 直连。
_直连 = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_开们缓存 = None


def _候选开们():
    """取模型的两条路：系统/环境代理 → 直连。

    ⚠ 不去猜本机代理端口 —— 每个人机器上的端口都不一样，猜错了只是白等。
    """
    global _开们缓存
    if _开们缓存 is None:
        _开们缓存 = [('系统代理', urllib.request.build_opener()), ('直连', _直连)]
    return _开们缓存


def _打开(地址, 头, 超时, 说=None):
    """按候选顺序试，全都打不开就把最后一个错抛出去（每一跳都通过 说 报一句人话）。"""
    错 = None
    for i, (名, 开) in enumerate(_候选开们()):
        try:
            回 = 开.open(urllib.request.Request(地址, headers=头), timeout=超时)
            记下载('%s 通了（%s）' % (名, 地址.rsplit('/', 1)[-1]))
            return 回
        except Exception as e:
            错 = e
            记下载('%s 不行（%s）：%s' % (名, 地址.rsplit('/', 1)[-1], str(e)[:120]))
            if 说:
                try:
                    说('「%s」连不上，换下一条路（%d/%d）' % (名, i + 1, len(_候选开们())))
                except Exception:
                    pass
    raise 错 if 错 else RuntimeError('打不开')


def 记下载(话):
    """下载这件事也留个证据 —— 出问题时要能看出是「哪条路、什么错」。"""
    try:
        import paths
        路 = os.path.join(paths.用户目录(), '下载记录.log')
        with open(路, 'a', encoding='utf-8') as f:
            f.write('%s %s' % (time.strftime('%m-%d %H:%M:%S'), 话) + chr(10))
    except Exception:
        pass


def _curl参数组():
    """curl 的两种走法：环境里配了代理就用它，否则直连。"""
    组们 = []
    for 键 in ('HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy'):
        值 = os.environ.get(键)
        if 值 and 值.startswith('http'):
            组们.append(('环境代理', ['-x', 值]))
            break
    组们.append(('不带代理', []))
    return 组们


def 用curl下(地址, 临时, 说=None, 停=None):
    """⭐ 1.5.9：python 那条路取不动（镜像对它的请求回 401），就交给系统的 curl.exe。

    Windows 10 以后都自带 `C:/Windows/System32/curl.exe`；它取同一个地址是通的。
    返回下到的字节数；curl 不在、或者它也没成，返回 0。
    """
    import subprocess
    curl = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'curl.exe')
    if not os.path.exists(curl):
        curl = 'curl.exe'
    if not os.path.exists(curl) and curl == 'curl.exe':
        return 0
    for 名, 参数 in _curl参数组():
        if 说:
            try:
                说('用 curl 下（%s）' % 名)
            except Exception:
                pass
        try:
            过 = subprocess.Popen(
                [curl, '-L', '--fail', '--retry', '2', '--retry-delay', '3',
                 '-C', '-', '--max-time', '3600', '-o', 临时] + 参数 + [地址],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except Exception as e:
            记下载('curl 起不来（%s）：%s' % (名, str(e)[:80]))
            continue
        while 过.poll() is None:
            if 停 is not None and 停.is_set():
                过.kill()
                return 0
            try:
                已 = os.path.getsize(临时) if os.path.exists(临时) else 0
                if 说:
                    说('curl 正在下：%.1f MB' % (已 / 1048576.0))
            except Exception:
                pass
            time.sleep(0.7)
        try:
            错 = 过.stderr.read().decode('utf-8', 'replace').strip().splitlines()
        except Exception:
            错 = []
        尾 = (错[-1] if 错 else '')
        大小 = os.path.getsize(临时) if os.path.exists(临时) else 0
        if 过.returncode == 0 and 大小 > 1024:
            记下载('curl（%s）下成了 %d 字节' % (名, 大小))
            return 大小
        记下载('curl（%s）没成：退出码 %s %s' % (名, 过.returncode, 尾[:120]))
        # 这一组不行就把半截留下（下一组能接着下），继续试下一组
    return 0


class 下载器:
    """后台下某一档模型；界面每 300ms 读一次 `进度()` 就行。"""

    def __init__(self, 档=''):
        self.档 = 档 if 档 in paths.语音档们 else paths.当前语音档()
        self._目录 = paths.档目录(self.档)
        self._远端 = paths.语音档们[self.档]['远端']
        # 远端名 -> 本地名；三档在本机都落成这两个名字
        self._文件们 = ((self._远端, 'model.onnx'), ('tokens.txt', 'tokens.txt'))
        self.锁 = threading.Lock()
        self.状态 = {
            '进行中': False,
            '完成': False,
            '出错': '',
            '档': self.档,
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
            self.状态.update({'进行中': True, '完成': False, '出错': '', '已下字节': 0,
                            '总字节': 0, '说': '准备下载', '档': self.档})
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
            paths.补内置语音(self.档)
            总 = 0
            for i, (远端, 本地) in enumerate(self._文件们):
                if self._停.is_set():
                    self._改(进行中=False, 说='停了')
                    return
                if self._已完整(本地):
                    self._改(第几个=i + 1, 说='「%s」已经有了' % 本地)
                    continue
                self._改(当前文件=本地, 第几个=i + 1, 说='正在下「%s」' % 本地)
                总 += self._下一个(远端, 本地, i)
            if self._停.is_set():
                self._改(进行中=False, 说='停了')
                return
            paths.补内置语音(self.档)
            ok = paths.档就绪(self.档)
            self._改(进行中=False, 完成=ok, 总字节=总,
                     说='好了，可以说话了' if ok else '下完了但文件不齐，点「再试一次」')
        except Exception as e:
            self._改(进行中=False, 出错=str(e), 说='没下成：' + str(e))

    def _已完整(self, 本地):
        路 = os.path.join(self._目录, 本地)
        if not os.path.exists(路):
            return False
        return os.path.getsize(路) > 1024 * 1024 if 本地.endswith('.onnx') else os.path.getsize(路) > 1024

    def _下一个(self, 远端, 本地, 序):
        目标 = os.path.join(self._目录, 本地)
        临时 = 目标 + '.part'
        最后错 = None
        # ⭐ 1.5.9：**先用系统 curl**（Windows 自带）。
        #   实测同一秒、同一个代理：curl 206 正常下，python 那套被镜像回 401 ——
        #   所以别让 python 先转一圈，直接上 curl；它不成再退回 python 那几条路。
        第一步 = (源们(self.档).get(远端) or [''])[0]
        if 第一步:
            self._改(说='用 curl 下「%s」' % 本地)
            拿到 = 用curl下(第一步, 临时, 说=lambda 句: self._改(说=句), 停=self._停)
            if 拿到 > 1024 and os.path.getsize(临时) > 1024:
                记下载('curl 下成了 %s（%d 字节）' % (本地, 拿到))
                os.replace(临时, 目标)
                return 拿到
            记下载('curl 没下成 %s，改试 python 那几条路' % 本地)
        for 模板 in 源们(self.档).get(远端, []):
            地址 = 模板
            # 同一个源先试 3 次（断了就接着下，别一下子把已经下的白扔）
            for _ in range(5):
                if self._停.is_set():
                    return 0
                已有 = os.path.getsize(临时) if os.path.exists(临时) else 0
                try:
                    os.makedirs(self._目录, exist_ok=True)
                    头 = {'User-Agent': 'fishbuddy/1.0'}
                    if 已有:
                        头['Range'] = 'bytes=%d-' % 已有
                    回 = _打开(地址, 头, 15, lambda 句: self._改(说=句))
                    码 = getattr(回, 'status', 200)
                    if 码 == 200:
                        已有 = 0          # 服务器不认续传，从头来
                        模式 = 'wb'
                    elif 码 == 206:
                        模式 = 'ab'
                    elif 码 in (401, 403, 429, 503):
                        # ⭐ 1.5.9：镜像抽风/限流的时候会回这几个码，等一会儿重试比立刻放弃强
                        raise RuntimeError('镜像限流了（HTTP %d）' % 码)
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
                    if isinstance(e, urllib.error.HTTPError) and e.code in (401, 403, 429, 503):
                        # 被回「拒绝」说明这条源不认我们，重试没用 —— 直接换源/换 curl
                        self._改(说='这条源被拒了（HTTP %d），换一个' % e.code)
                        break
                    限流 = '限流' in str(e)
                    self._改(说=('镜像在限流，等一会儿再试（第 %d 次）' % (_ + 1)) if 限流 else
                              ('这一条路没通，再试一次（第 %d 次）' % (_ + 1)))
                    time.sleep(6 if 限流 else 2)
                    continue
        记下载('全都失败：%s' % str(最后错)[:120])
        raise RuntimeError('「%s」所有源都没下成（网络这块）：%s —— 挂个代理再点一次就行，已经下好的部分不会浪费'
                         % (本地, 最后错))


def 一下载器(档=''):
    return 下载器(档)
