"""显卡版 onnxruntime 的下载与安装（不塞安装包，点一下才下）。

为什么单独一个文件：ocr.py 只管用，下载和校验放这儿，坏了好查。
"""

import json
import os
import sys
import threading
import urllib.request
import zipfile

import paths
import ocr

PyPI = 'https://pypi.org/pypi/onnxruntime-gpu/json'
代理直连 = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _取(址, 超时=30):
    req = urllib.request.Request(址, headers={'user-agent': 'fish-buddy'})
    with 代理直连.open(req, timeout=超时) as r:
        return r.read()


def 找安装包():
    """从 PyPI 挑一个跟本机 Python 对得上的 Windows 轮子。"""
    j = json.loads(_取(PyPI).decode('utf-8'))
    版 = j['info']['version']
    标 = 'cp%d%d' % (sys.version_info.major, sys.version_info.minor)
    候选 = []
    for f in j['releases'].get(版, []):
        名 = f.get('filename') or ''
        if not 名.endswith('.whl'):
            continue
        if 'win_amd64' not in 名:
            continue
        if 标 not in 名:
            continue
        候选.append(f)
    if not 候选:
        raise RuntimeError('PyPI 上没有适配本机 Python（%s）的 Windows 包' % 标)
    return 版, 候选[0]


class 下载器:
    """后台下 + 解压；界面每 300ms 读一次 进度() 就行。"""

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
        t = threading.Thread(target=self._跑, daemon=True)
        t.start()
        return True

    def _跑(self):
        self._改(进行中=True, 完成=False, 说='看看要下哪个包…')
        try:
            版, 包 = 找安装包()
            名 = 包['filename']
            址 = 包['url']
            总 = int(包.get('size') or 0)
            self._改(说='下 %s（%dMB）' % (名, round(总 / 1048576)))
            临时 = os.path.join(ocr.目录(), '_gpu.whl.part')
            目标 = os.path.join(ocr.目录(), '_gpu.whl')
            os.makedirs(ocr.目录(), exist_ok=True)
            已 = 0
            req = urllib.request.Request(址, headers={'user-agent': 'fish-buddy'})
            with 代理直连.open(req, timeout=60) as r, open(临时, 'wb') as f:
                while True:
                    if self._停.is_set():
                        self._改(说='停了')
                        return
                    块 = r.read(256 * 1024)
                    if not 块:
                        break
                    f.write(块)
                    已 += len(块)
                    self._改(已下字节=已, 总字节=总)
            os.replace(临时, 目标)

            self._改(说='解压…')
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

            if not ocr.有GPU运行时():
                raise RuntimeError('解压完了但没看到 onnxruntime')
            self._改(完成=True, 说='装好了：%s' % 版)
        except Exception as e:
            self._改(说='没下成：%s' % str(e)[:120])
        finally:
            self._改(进行中=False)
