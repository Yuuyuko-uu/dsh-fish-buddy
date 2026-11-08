"""显卡版 onnxruntime 的下载与安装（不塞安装包，点一下才下）。

⚠ 2026-11-08 用户实测：最新的 onnxruntime-gpu 是给 **CUDA 13** 编的，
  他机器上是 CUDA 12 → 缺 cublasLt64_13.dll，起不来。
  所以：① 先探机器上是 CUDA 12 还是 13，直接挑对应版本（少下一个 250MB）
        ② 装完真的起一次会话试跑，不行再换别的版本兜底
"""

import json
import os
import subprocess
import sys
import threading
import urllib.request
import zipfile

import ocr
import paths

PyPI = 'https://pypi.org/pypi/onnxruntime-gpu/json'
代理直连 = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 版本 → 它要的 CUDA 大版本
CUDA12版 = '1.22.0'
CUDA12老版 = '1.19.2'


def _取(址, 超时=30):
    req = urllib.request.Request(址, headers={'user-agent': 'fish-buddy'})
    with 代理直连.open(req, timeout=超时) as r:
        return r.read()


def _找dll(名):
    """在 PATH 和 System32 里找某个 dll，找到就返回它所在目录。"""
    处 = [os.environ.get('SystemRoot', r'C:\Windows') + r'\System32']
    处 += [p for p in (os.environ.get('PATH') or '').split(os.pathsep) if p]
    处 += [
        r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA',
    ]
    for d in 处:
        if not d or not os.path.isdir(d):
            continue
        try:
            if os.path.isfile(os.path.join(d, 名)):
                return d
        except Exception:
            pass
    # CUDA 装在默认目录时，运行时 DLL 在 bin 里：扫一层子目录
    根 = r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA'
    if os.path.isdir(根):
        try:
            for v in os.listdir(根):
                p = os.path.join(根, v, 'bin')
                if os.path.isfile(os.path.join(p, 名)):
                    return p
        except Exception:
            pass
    return ''


def 探测CUDA():
    """返回 '13' / '12' / ''（探不出来）。看 cublasLt 的版本号最准。"""
    if _找dll('cublasLt64_13.dll'):
        return '13'
    if _找dll('cublasLt64_12.dll'):
        return '12'
    # 兜底：问 nvidia-smi 它报的 CUDA 版本
    try:
        出 = subprocess.run(['nvidia-smi'], capture_output=True, text=True, timeout=8).stdout
        i = 出.find('CUDA Version')
        if i >= 0:
            v = 出[i + 13:i + 20].strip().split('.')[0]
            if v in ('12', '13'):
                return v
    except Exception:
        pass
    return ''


def 候选顺序():
    """按探测结果排：CUDA 12 的机器先下 1.22.0，别白下 250MB。"""
    v = 探测CUDA()
    if v == '12':
        return [CUDA12版, '', CUDA12老版], v
    if v == '13':
        return ['', CUDA12版, CUDA12老版], v
    return ['', CUDA12版, CUDA12老版], v


def 找安装包(指定=''):
    """挑一个跟本机 Python 对得上的 Windows 轮子；指定版本就按指定的来。"""
    j = json.loads(_取(PyPI).decode('utf-8'))
    版 = 指定 or j['info']['version']
    标 = 'cp%d%d' % (sys.version_info.major, sys.version_info.minor)
    for f in j['releases'].get(版, []):
        名 = f.get('filename') or ''
        if 名.endswith('.whl') and 'win_amd64' in 名 and 标 in 名:
            return 版, f
    raise RuntimeError('PyPI 上没有 %s 版、适配本机 Python（%s）的 Windows 包' % (版, 标))


def _试跑():
    """装完真起一次会话：能起来才算数。返回 (能不能用, 说明)。"""
    d = ocr.GPU运行时目录()
    for m in list(sys.modules):
        if m == 'onnxruntime' or m.startswith('onnxruntime.'):
            del sys.modules[m]
    if d in sys.path:
        sys.path.remove(d)
    sys.path.insert(0, d)
    try:
        import onnxruntime as ort
        可用 = ort.get_available_providers()
        if 'CUDAExecutionProvider' not in 可用:
            return False, '这个包不带 CUDA（可用：%s）' % ','.join(可用)
        d2 = ocr.目录()
        检测 = os.path.join(d2, 'PP-OCRv6_det_small.onnx')
        if os.path.isfile(检测):
            ort.InferenceSession(检测, providers=['CUDAExecutionProvider'])
        return True, 'ok'
    except Exception as e:
        return False, str(e)[:160]


class 下载器:
    """后台下 + 解压 + 试跑；界面每 300ms 读一次 进度() 就行。"""

    def __init__(self):
        self.锁 = threading.Lock()
        self.状态 = {'进行中': False, '完成': False, '已下字节': 0, '总字节': 0, '说': ''}
        self._停 = threading.Event()

    def 进度(self):
        with self.锁:
            return dict(self.状态)

    def 停(self):
        self._停.set()

    def _改(self, **kw):
        with self.锁:
            self.状态.update(kw)

    def 开始(self):
        if self.状态['进行中']:
            return False
        threading.Thread(target=self._跑, daemon=True).start()
        return True

    def _装一版(self, 指定):
        版, 包 = 找安装包(指定)
        名 = 包['filename']
        总 = int(包.get('size') or 0)
        self._改(说='下 %s（%dMB）' % (名, round(总 / 1048576)), 已下字节=0, 总字节=总)
        os.makedirs(ocr.目录(), exist_ok=True)
        临时 = os.path.join(ocr.目录(), '_gpu.whl.part')
        目标 = os.path.join(ocr.目录(), '_gpu.whl')
        已 = 0
        req = urllib.request.Request(包['url'], headers={'user-agent': 'fish-buddy'})
        with 代理直连.open(req, timeout=60) as r, open(临时, 'wb') as f:
            while True:
                if self._停.is_set():
                    raise RuntimeError('停了')
                块 = r.read(256 * 1024)
                if not 块:
                    break
                f.write(块)
                已 += len(块)
                self._改(已下字节=已)
        os.replace(临时, 目标)

        self._改(说='解压 %s…' % 版)
        目录 = ocr.GPU运行时目录()
        if os.path.isdir(目录):
            import shutil
            shutil.rmtree(目录, ignore_errors=True)
        os.makedirs(目录, exist_ok=True)
        with zipfile.ZipFile(目标) as z:
            z.extractall(目录)
        try:
            os.remove(目标)
        except Exception:
            pass
        return 版

    def _跑(self):
        self._改(进行中=True, 完成=False, 说='看看要下哪个包…')
        最后错 = ''
        try:
            顺序, 探到 = 候选顺序()
            self._改(说=('机器上是 CUDA %s，按这个挑版本' % 探到) if 探到 else '没探出 CUDA 版本，先试最新的')
            for 指定 in 顺序:
                if self._停.is_set():
                    self._改(说='停了')
                    return
                try:
                    版 = self._装一版(指定)
                except Exception as e:
                    最后错 = str(e)[:120]
                    continue
                self._改(说='%s 装好了，试跑一次…' % 版)
                行, 说 = _试跑()
                if 行:
                    self._改(完成=True, 说='✓ %s 能用显卡' % 版)
                    return
                最后错 = '%s 起不来：%s' % (版, 说)
                self._改(说=最后错 + '，换别的版本再试…')
            self._改(说='都没成。最后的错：' + 最后错)
        except Exception as e:
            self._改(说='没下成：%s' % str(e)[:120])
        finally:
            self._改(进行中=False)
