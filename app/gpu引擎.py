"""GPU 引擎（N 卡加速）：下载、自检、子进程干活。

为什么单独一个模块、而且**全部在子进程里跑**：
    主程序是单文件 exe，里面打的是 **CPU 版** sherpa_onnx。
    GPU 版是另一个包，里面有自己的 `sherpa_onnx` 和 `onnxruntime.dll` ——
    两份同名 DLL 在**同一个进程**里会撞（先加载的那份被复用，另一份等于没装）。
    所以 GPU 那套一律交给 `鱼搭子.exe --gpu-自检` / `--gpu-识别` 这两个**子进程**，
    主进程只通过本机端口跟它说话。

    ⭐ 实测过（2026-11-02）：冻结后的 exe 能从外部目录 import 第二份 sherpa_onnx，
       并真的建出 OfflineRecognizer（见 `_临时文件/实验-外部加载/`）。

要下的四样东西：
    1. sherpa-onnx CUDA 版轮子（192MB）—— 引擎本体
    2. cudart（3MB）、cublas（524MB）、cudnn（709MB）—— 它跑起来还缺的库
    「我已经装过 CUDA 了」的人只需要第 1 样。
"""
import importlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

import paths

def 子进程命令(*参数):
    """怎么把自己的另一个实例拉起来。

    冻结后是 `鱼搭子.exe --gpu-xxx`；**从源码跑时**是 `python ball.py --gpu-xxx`
    （`sys.executable` 那时候是 python.exe，直接塞参数它不会认）。
    """
    import sys as _s
    if getattr(_s, 'frozen', False):
        return [_s.executable] + list(参数)
    return [_s.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ball.py')] + list(参数)


# ---------------------------------------------------------------------------
# 放在哪
# ---------------------------------------------------------------------------
def 引擎目录():
    return os.path.join(paths.模型目录(), 'gpu')


def 包目录():
    """sherpa_onnx 这个包解出来放这儿。"""
    return os.path.join(引擎目录(), 'sherpa_onnx')


def 库目录():
    """它旁边的那些 DLL 全塞这里（Windows 只在「谁加载我」的目录里找依赖）。"""
    return os.path.join(包目录(), 'lib')


# ---------------------------------------------------------------------------
# 要下什么
# ---------------------------------------------------------------------------
# 版本对齐：引擎用 1.13.8，跟主程序里打的 CPU 版**同一个版本**。
_轮子 = 'sherpa_onnx-1.13.8+cuda12.cudnn9-cp312-cp312-win_amd64.whl'

下载项 = [
    {
        '键': '引擎',
        '名': 'GPU 引擎（sherpa-onnx CUDA 版）',
        '网址': 'https://huggingface.co/csukuangfj2/sherpa-onnx-wheels/resolve/main/cuda/1.13.8/' + _轮子,
        '大小': 192,
        '要': True,          # 必下
        '解开': '轮子',
    },
    {
        '键': 'cudart',
        '名': 'CUDA 运行时（cudart）',
        '网址': ('https://developer.download.nvidia.com/compute/cuda/redist/cuda_cudart/'
                'windows-x86_64/cuda_cudart-windows-x86_64-12.9.37-archive.zip'),
        '大小': 3,
        '要': False,
        '解开': 'zip',
    },
    {
        '键': 'cublas',
        '名': 'cuBLAS（显卡算矩阵要用）',
        '网址': ('https://developer.download.nvidia.com/compute/cuda/redist/libcublas/'
                'windows-x86_64/libcublas-windows-x86_64-12.9.0.13-archive.zip'),
        '大小': 524,
        '要': False,
        '解开': 'zip',
    },
    {
        '键': 'cudnn',
        '名': 'cuDNN 9（卷积要用）',
        # ⚠ 别手写 PyPI 的文件路径：那是哈希过的目录（packages/aa/38/…），
        #   写成 packages/source/... 会 404 —— 2026-11-02 真踩过一次。
        '网址': ('https://files.pythonhosted.org/packages/aa/38/f856579877f7c1c5066e61182e7de7bc27bf35a78c8d1b0fa592e6985bc4/'
                'nvidia_cudnn_cu12-9.27.0.42-py3-none-win_amd64.whl'),
        '大小': 709,
        '要': False,
        '解开': '轮子',
    },
    {
        '键': 'cufft',
        # ⚠ 1.6.7：这一样**以前漏了**，真机上 C++ 直接说
        #   `onnxruntime_providers_cuda.dll ... depends on "cufft64_11.dll" which is missing`
        #   —— 下完前面四样也照样退回 CPU。cuFFT 是 ORT 的 CUDA 后端硬依赖。
        '名': 'cuFFT 11（显卡算傅里叶要用）',
        '网址': ('https://developer.download.nvidia.com/compute/cuda/redist/libcufft/'
                'windows-x86_64/libcufft-windows-x86_64-11.4.0.6-archive.zip'),
        '大小': 189,
        '要': False,
        '解开': 'zip',
    },
]

# 判断「装好了」看这几个文件在不在（少了任何一个都跑不起来）
# ⚠ 全部都在 `sherpa_onnx/lib/` 里（解包时一律塞那儿，Windows 只认「谁加载我」旁边的 DLL）。
#   2026-11-02 真踩过：以前把后四个写在 `gpu/` 根上 → 就算全下完也一直判「缺文件」。
必需文件 = [
    os.path.join('sherpa_onnx', '__init__.py'),
    os.path.join('sherpa_onnx', 'lib', 'onnxruntime_providers_cuda.dll'),
    os.path.join('sherpa_onnx', 'lib', 'cudart64_12.dll'),
    os.path.join('sherpa_onnx', 'lib', 'cublas64_12.dll'),
    os.path.join('sherpa_onnx', 'lib', 'cublasLt64_12.dll'),
    os.path.join('sherpa_onnx', 'lib', 'cudnn64_9.dll'),
    os.path.join('sherpa_onnx', 'lib', 'cufft64_11.dll'),
]


def 缺什么():
    """返回缺的文件名（空列表 = 齐了）。"""
    缺 = []
    for 相 in 必需文件:
        全 = os.path.join(引擎目录(), 相)
        if not os.path.isfile(全) or os.path.getsize(全) < 1024:
            缺.append(os.path.basename(相) if 'dll' in 相 else 相.replace('\\', '/'))
    return 缺


def 就绪():
    return not 缺什么()


def 自检结果路():
    return os.path.join(引擎目录(), '自检.json')


def 读自检():
    """上次自检的结论：{'成': bool, '说': str, 'at': 时间}；没测过就是 None。"""
    try:
        with open(自检结果路(), encoding='utf-8') as f:
            j = json.load(f)
        return j if isinstance(j, dict) else None
    except Exception:
        return None


def 记下自检(j):
    try:
        os.makedirs(引擎目录(), exist_ok=True)
        with open(自检结果路(), 'w', encoding='utf-8') as f:
            json.dump(j, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 下载 + 解压
# ---------------------------------------------------------------------------
class 下载中:
    """进度：0~1，以及「在下第几样」。界面每 300ms 读一次。"""

    def __init__(self):
        self.锁 = threading.Lock()
        self.在跑 = False
        self.停 = False
        self.比 = 0.0
        self.说 = ''

    def 停一下(self):
        self.停 = True

    def 记(self, 比, 说):
        with self.锁:
            self.比 = 比
            self.说 = 说

    def 读(self):
        with self.锁:
            return self.比, self.说


def _记(话):
    """下载也留证据 —— 出问题时要能看出「哪条路、什么错」。

    ⚠ 1.6.6：这一块以前**一句日志都没有**，用户报「跳一下就没了」我什么都看不到。
      直接复用 models 那套（同一个 下载记录.log，跟模型下载的记录在一起）。
    """
    try:
        import models
        models.记下载('[GPU] ' + str(话))
    except Exception:
        pass


def _候选地址(网址):
    """官方 → hf-mirror 兜底。非 huggingface 的地址就那一个。"""
    出 = [网址]
    if '://huggingface.co/' in 网址:
        出.append(网址.replace('://huggingface.co/', '://hf-mirror.com/', 1))
    return 出


def _打开(地址, 头, 超时=60):
    """按「系统代理 → 直连」试 —— 跟 models.py 里那套完全一样。

    ⚠ 1.6.6：以前这里直接用 urllib.request.urlopen 裸连。
      后果：**挂了系统代理的人也用不上**（urllib 只认环境变量），而引擎那个 192MB 恰好在 huggingface 上，
      直连是不通的 —— 用户看到的就是「进度跳一下就没了」。三个模型没事，因为它们走的是 models 那套。
    """
    try:
        import models
        return models._打开(地址, 头, 超时, 说=lambda 文: _记('  ' + 文))
    except Exception:
        return urllib.request.urlopen(urllib.request.Request(地址, headers=头), timeout=超时)


def _下一条(地址, 到, 进度, 名, 起, 长):
    """从**一个**地址下（支持续传：有 .part 就接着下）。"""
    片 = 到 + '.part'
    已有 = os.path.getsize(片) if os.path.exists(片) else 0
    头 = {'user-agent': 'dsh-fish-buddy'}
    if 已有:
        头['range'] = 'bytes=%d-' % 已有
    响 = _打开(地址, 头)
    try:
        总 = int(响.headers.get('content-length') or 0)
        if 已有 and getattr(响, 'status', 0) == 206:
            总 = 已有 + 总
        elif 已有:
            已有 = 0                      # 服务器不理 range，就从头来
        模式 = 'ab' if 已有 else 'wb'
        下 = 已有
        with open(片, 模式) as f:
            while True:
                if 进度.停:
                    raise RuntimeError('停了')
                块 = 响.read(256 * 1024)
                if not 块:
                    break
                f.write(块)
                下 += len(块)
                if 总 > 0:
                    进度.记(min(0.99, 起 + (长 * (下 / 总))), '%s %d%%' % (名, int(下 * 100 / 总)))
    finally:
        try:
            响.close()
        except Exception:
            pass
    if 已有 == 0 and os.path.getsize(片) < 1024:
        raise RuntimeError('下到的是空文件')
    os.replace(片, 到)


def _用curl下(地址, 到, 进度, 名, 起, 长):
    """python 这条路全不通时，交给系统的 curl.exe（跟 models.py 里同一个兜底思路）。"""
    import subprocess
    curl = os.path.join(os.environ.get('SystemRoot') or 'C:/Windows', 'System32', 'curl.exe')
    if not os.path.isfile(curl):
        raise RuntimeError('没有 curl.exe')
    片 = 到 + '.part'
    进度.记(min(0.99, 起), '%s（改用 curl 下）' % 名)
    旗 = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    子 = subprocess.run([curl, '-L', '--retry', '2', '--connect-timeout', '30',
                         '-o', 片, 地址], capture_output=True, creationflags=旗)
    if 子.returncode != 0 or not os.path.isfile(片) or os.path.getsize(片) < 1024:
        raise RuntimeError('curl 也没成：%s' % (子.stderr or b'')[:120])
    os.replace(片, 到)


def _下文件(网址, 到, 进度, 名, 起, 长):
    """下一条：官方 → 镜像 → （都不行）curl。每一步都记日志。"""
    错 = None
    候选 = _候选地址(网址)
    for 第几, 址 in enumerate(候选, 1):
        try:
            # 界面这一行也要说 —— 卡在「连不上」时不能看着像死了
            进度.记(进度.读()[0], '正在试%s：%s' % (
                '' if len(候选) == 1 else '（%d/%d）' % (第几, len(候选)),
                址.split('/')[2]))
            _记('试：' + 址.rsplit('/', 1)[-1][:60])
            _下一条(址, 到, 进度, 名, 起, 长)
            _记('成了：' + 址.rsplit('/', 1)[-1][:60])
            return
        except Exception as e:
            错 = e
            _记('失败：%s → %s' % (址.rsplit('/', 1)[-1][:50], str(e)[:150]))
    try:
        _用curl下(_候选地址(网址)[-1], 到, 进度, 名, 起, 长)
        _记('curl 成了')
    except Exception as e:
        _记('curl 也失败：%s' % str(e)[:150])
        raise 错 or e


def _解轮子(轮子路, 想去哪):
    """从 wheel 里挑出要的东西（只解包，不装）。"""
    with zipfile.ZipFile(轮子路) as z:
        for 项 in z.namelist():
            名 = os.path.basename(项).lower()
            # sherpa 包主体
            if 项.startswith('sherpa_onnx/'):
                目标 = os.path.join(引擎目录(), 项)
                os.makedirs(os.path.dirname(目标), exist_ok=True)
                with z.open(项) as 源, open(目标, 'wb') as 出:
                    shutil.copyfileobj(源, 出)
                continue
            # cudnn 轮子里的 dll（在 nvidia/cudnn/bin/ 下）
            if 想去哪 == '库' and 名.endswith('.dll'):
                目标 = os.path.join(库目录(), os.path.basename(项))
                os.makedirs(库目录(), exist_ok=True)
                with z.open(项) as 源, open(目标, 'wb') as 出:
                    shutil.copyfileobj(源, 出)


def _解压缩包(压缩路):
    """cuBLAS / cudart 的 archive.zip：只挑 dll，全扔进库目录。"""
    with zipfile.ZipFile(压缩路) as z:
        for 项 in z.namelist():
            if not 项.lower().endswith('.dll'):
                continue
            目标 = os.path.join(库目录(), os.path.basename(项))
            os.makedirs(库目录(), exist_ok=True)
            with z.open(项) as 源, open(目标, 'wb') as 出:
                shutil.copyfileobj(源, 出)


_每项要的文件 = {
    '引擎': (os.path.join('sherpa_onnx', '__init__.py'),
             os.path.join('sherpa_onnx', 'lib', 'onnxruntime_providers_cuda.dll')),
    'cudart': ('cudart64_12.dll',),
    'cublas': ('cublas64_12.dll', 'cublasLt64_12.dll'),
    'cudnn': ('cudnn64_9.dll',),
    'cufft': ('cufft64_11.dll',),
}


def _这项已经好了(键):
    要 = _每项要的文件.get(键, ())
    return bool(要) and all(os.path.isfile(os.path.join(库目录(), 相)) for 相 in 要)


def 下载(只下引擎=False, 进度=None):
    """把引擎和那几个库下下来、解开。返回 (成, 说)。"""
    进度 = 进度 or 下载中()
    进度.在跑 = True
    try:
        os.makedirs(库目录(), exist_ok=True)
        项们 = [x for x in 下载项 if (not 只下引擎) or x['要']]
        总长 = sum(x['大小'] for x in 项们) or 1
        已走 = 0.0
        with tempfile.TemporaryDirectory(prefix='鱼搭子gpu-') as 临时:
            for 项 in 项们:
                进度.记(已走 / 总长, '正在下：' + 项['名'])
                if _这项已经好了(项['键']):
                    # 已经解好了就跳过：重复点下载、或者上次中途停了，都不该再下一遍
                    已走 += 项['大小']
                    continue
                临时路 = os.path.join(临时, 项['键'] + '.tmp')
                _下文件(项['网址'], 临时路, 进度, 项['名'], 已走 / 总长, 项['大小'] / 总长)
                进度.记(已走 / 总长, '正在解开：' + 项['名'])
                if 项['键'] == '引擎':
                    _解轮子(临时路, '包')
                elif 项['键'] == 'cudnn':
                    _解轮子(临时路, '库')
                else:
                    _解压缩包(临时路)
                try:
                    os.remove(临时路)
                except Exception:
                    pass
                已走 += 项['大小']
        进度.记(0.99, '下完了')
        缺 = 缺什么()
        if 缺:
            return False, '还缺：' + '、'.join(缺)
        return True, '装好了'
    except Exception as e:
        说 = str(e)
        if '停了' in 说:
            return False, '停了（下次接着下）'
        return False, '下载失败：%s' % 说
    finally:
        进度.在跑 = False


# ---------------------------------------------------------------------------
# 子进程：从外面那份引擎 import
# ---------------------------------------------------------------------------
def _加DLL路径():
    """让 Windows 能在引擎目录里找到 .pyd 依赖的那些 DLL。"""
    for 路 in (引擎目录(), 库目录(), 包目录()):
        try:
            if os.path.isdir(路):
                os.add_dll_directory(路)
        except Exception:
            pass
    # 老式找法也得开着（有的 DLL 只认 PATH）
    try:
        os.environ['PATH'] = 库目录() + os.pathsep + 引擎目录() + os.pathsep + os.environ.get('PATH', '')
    except Exception:
        pass


def _装外部找法(目录, 包名='sherpa_onnx'):
    """让 `import sherpa_onnx` / `sherpa_onnx.xxx` 统统落到外部目录。

    ⚠⚠ 1.6.7（真机报的）：**这是之前那个「加载成功」的假象来源**。
      `gpu/sherpa_onnx/__init__.py` 第一行是 `from sherpa_onnx.lib._sherpa_onnx import ...`
      —— **绝对导入**。以前我把外部包按 `sherpa_onnx_gpu` 加载，那句绝对导入照常走 sys.path，
      于是找到的是 **exe 里打包的 CPU 版** pyd，C++ 那边就报
      `Please compile with -DSHERPA_ONNX_ENABLE_GPU=ON`。
      用户看到的「下载完了但用不了显卡」就是这个：引擎下下来了，程序和它根本没接上。
    """
    import importlib.util

    class 找法:
        def find_spec(self, 名, 路=None, 目标=None):
            if 名 != 包名 and not 名.startswith(包名 + '.'):
                return None
            相 = 名.split('.')
            基 = os.path.join(目录, *相)
            if os.path.isdir(基):
                入 = os.path.join(基, '__init__.py')
                if os.path.isfile(入):
                    return importlib.util.spec_from_file_location(名, 入, submodule_search_locations=[基])
                return None
            for 尾 in ('.pyd', '.py', '.so'):
                全 = 基 + 尾
                if os.path.isfile(全):
                    return importlib.util.spec_from_file_location(名, 全)
            return None

    找 = 找法()
    sys.meta_path.insert(0, 找)
    return 找


def 加载外部引擎():
    """从引擎目录 import 第二份 sherpa_onnx（**名字就叫 sherpa_onnx**，整体顶掉 exe 里那份）。"""
    if not os.path.isfile(os.path.join(包目录(), '__init__.py')):
        return None, '引擎没装好（找不到 %s）' % os.path.join(包目录(), '__init__.py')
    _加DLL路径()
    try:
        # 先把 exe 里那份（以及它的子模块）赶出 sys.modules，否则 import 会直接命中旧的
        for 名 in [m for m in list(sys.modules) if m == 'sherpa_onnx' or m.startswith('sherpa_onnx.')]:
            sys.modules.pop(名, None)
        _装外部找法(引擎目录())
        模块 = importlib.import_module('sherpa_onnx')
        真在 = os.path.abspath(getattr(模块, '__file__', '') or '')
        if not 真在.startswith(os.path.abspath(包目录())):
            return None, '加载回来的还是 exe 里那份（%s），不是引擎目录里的' % 真在
        return 模块, ''
    except Exception as e:
        return None, '%s: %s' % (type(e).__name__, e)


def _建识别器(模块, 设备, 模型目录):
    模型 = os.path.join(模型目录, 'model.onnx')
    词表 = os.path.join(模型目录, 'tokens.txt')
    return 模块.OfflineRecognizer.from_sense_voice(
        模型, 词表, num_threads=2, provider=设备)


def _有N卡():
    """机器上到底有没有 NVIDIA 显卡。

    ⚠ 光看「识别器建起来了」不够：sherpa-onnx 拿不到 CUDA 时**不抛异常**，
      只在 stderr 打一句 `Fallback to cpu`，然后照常跑 CPU ——
      2026-11-02 在 AMD 机器上实测，「自检通过」了，其实一直在用 CPU。
    """
    try:
        import subprocess
        旗 = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        出 = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],
                            capture_output=True, timeout=6, creationflags=旗)
        return 出.returncode == 0 and bool((出.stdout or b'').strip())
    except Exception:
        return False


def _抓stderr(函数):
    """跑一段 C++ 的活儿，顺手把它打到 stderr 的话抓下来（sherpa 的「退回 CPU」就在那儿）。"""
    import tempfile
    路 = tempfile.mktemp(prefix='鱼搭子gpu-', suffix='.log')
    fd = os.open(路, os.O_RDWR | os.O_CREAT | os.O_TRUNC)
    旧 = os.dup(2)
    结果, 错 = None, ''
    try:
        os.dup2(fd, 2)
        结果 = 函数()
    finally:
        try:
            os.dup2(旧, 2)
        except Exception:
            pass
        try:
            os.close(旧)
        except Exception:
            pass
        try:
            os.close(fd)
        except Exception:
            pass
    try:
        with open(路, encoding='utf-8', errors='replace') as f:
            错 = f.read()[-1500:]
    except Exception:
        pass
    try:
        os.remove(路)
    except Exception:
        pass
    return 结果, 错


def 子进程自检():
    """--gpu-自检：真的用 GPU 建一个识别器、真的跑一次，把结论写进 json。"""
    结论 = {'成': False, '说': '', 'at': int(time.time())}
    try:
        if not _有N卡():
            结论['说'] = '这台机器没有 NVIDIA 显卡（或没装显卡驱动）—— 用不了显卡，用上面三档就行'
            记下自检(结论)
            try:
                print(json.dumps(结论, ensure_ascii=False), flush=True)
            except Exception:
                pass
            return 2
        模块, 错 = 加载外部引擎()
        if 模块 is None:
            结论['说'] = 错
        else:
            模型目录 = paths.档目录(paths.可用档() or paths.默认语音档)
            结论['说'] = '引擎加载好了，但模型没装：' + 模型目录
            if os.path.isfile(os.path.join(模型目录, 'model.onnx')):
                def 试跑():
                    识别器 = _建识别器(模块, 'cuda', 模型目录)
                    结 = 识别器.create_stream()
                    结.accept_waveform(16000, [0.0] * 8000)
                    识别器.decode_stream(结)
                    return 识别器
                try:
                    _, 错文 = _抓stderr(试跑)
                    低 = 错文.lower()
                    if 'fallback to cpu' in 低 or 'fallback to cpu!' in 低:
                        原因 = '显卡这条路没接上，引擎退回 CPU 了'
                        for 行 in 错文.splitlines():
                            if 'fallback' in 行.lower() or 'cuda' in 行.lower():
                                原因 = 行.strip()[:240]
                                break
                        结论['说'] = 原因 + '（多半是缺 CUDA 运行时或 cuDNN 版本不对）'
                    else:
                        结论['成'] = True
                        结论['说'] = '显卡能用（建了识别器、跑了一小段静音，没有退回 CPU）'
                except Exception as e:
                    结论['说'] = 'GPU 建不起来：%s' % str(e)[:300]
    except Exception as e:
        结论['说'] = '自检自己崩了：%s' % str(e)[:300]
    记下自检(结论)
    try:
        print(json.dumps(结论, ensure_ascii=False), flush=True)
    except Exception:
        pass
    return 0 if 结论['成'] else 2


def 子进程识别服务(端口=0):
    """--gpu-识别 <端口>：常驻，接收音频、返回文字。

    协议（每一条）：4 字节小端长度 + float32 PCM（16kHz 单声道）→
                  4 字节小端长度 + UTF-8 文本。
    """
    端口 = int(端口 or 0)
    模块, 错 = 加载外部引擎()
    if 模块 is None:
        try:
            print(json.dumps({'成': False, '说': 错}, ensure_ascii=False), flush=True)
        except Exception:
            pass
        return 3
    模型目录 = os.environ.get('鱼搭子_模型目录') or paths.档目录(paths.可用档() or paths.默认语音档)
    try:
        识别器 = _建识别器(模块, os.environ.get('鱼搭子_设备') or 'cuda', 模型目录)
    except Exception as e:
        try:
            print(json.dumps({'成': False, '说': '建不起识别器：%s' % str(e)[:300]}, ensure_ascii=False), flush=True)
        except Exception:
            pass
        return 4
    服 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    服.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    服.bind(('127.0.0.1', 端口))
    服.listen(4)
    try:
        真端口 = 服.getsockname()[1]
        print(json.dumps({'成': True, '端口': 真端口}, ensure_ascii=False), flush=True)
    except Exception:
        pass
    while True:
        try:
            连, _ = 服.accept()
        except Exception:
            continue
        threading.Thread(target=_招呼, args=(连, 识别器), daemon=True).start()


def _收够(连, 长):
    块 = b''
    while len(块) < 长:
        一 = 连.recv(长 - len(块))
        if not 一:
            return None
        块 += 一
    return 块


def _招呼(连, 识别器):
    import numpy as np
    try:
        while True:
            头 = _收够(连, 4)
            if not 头:
                break
            长 = struct.unpack('<I', 头)[0]
            if 长 == 0 or 长 > 4 * 16000 * 60:
                break
            身 = _收够(连, 长)
            if 身 is None:
                break
            样本 = np.frombuffer(身, dtype=np.float32)
            try:
                结 = 识别器.create_stream()
                结.accept_waveform(16000, 样本)
                识别器.decode_stream(结)
                文 = (结.result.text or '').strip()
            except Exception as e:
                文 = ''
                try:
                    sys.stderr.write('识别出错：%s\n' % e)
                except Exception:
                    pass
            出 = 文.encode('utf-8')
            连.sendall(struct.pack('<I', len(出)) + 出)
    except Exception:
        pass
    finally:
        try:
            连.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 主进程这边：把子进程拉起来、跟它说话
# ---------------------------------------------------------------------------
class GPU服务:
    """主进程侧的客户端。第一次用才拉子进程（不用显卡的人不会多一个进程）。"""

    def __init__(self):
        self.进程 = None
        self.连 = None
        self.锁 = threading.Lock()
        self.错 = ''
        self.模型目录 = ''

    def _拉起来(self, 模型目录=''):
        self.关掉()
        参数 = 子进程命令('--gpu-识别')
        环境 = dict(os.environ)
        # ⚠ 测试钩子：这台机器没有 N 卡，验证「子进程 + 通信」这条路时用 cpu 跑一遍。
        #   正常使用永远是 cuda。
        环境['鱼搭子_设备'] = os.environ.get('鱼搭子_测设备') or 'cuda'
        目录 = 模型目录 or paths.档目录(paths.可用档() or paths.当前语音档())
        环境['鱼搭子_模型目录'] = 目录
        self.模型目录 = 目录
        # ⚠ Windows 上子进程的 stdout 默认是**控制台代码页（GBK）**，
        #   父进程按 UTF-8 读会变成乱码、JSON 解析失败。强制两边都是 UTF-8。
        环境['PYTHONIOENCODING'] = 'utf-8'
        环境['PYTHONUTF8'] = '1'
        旗 = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        self.进程 = subprocess.Popen(参数, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     env=环境, creationflags=旗)
        行 = self.进程.stdout.readline().decode('utf-8', 'replace').strip()
        if not 行:
            # 孩子一句话没说就没影了 —— 把它吐在 stderr 上的东西带出来，不然只看到「没说话」
            错文 = ''
            try:
                self.进程.wait(timeout=5)
                错文 = (self.进程.stderr.read() or b'').decode('utf-8', 'replace')[-600:]
            except Exception:
                pass
            raise RuntimeError('GPU 子进程没起来（退出码 %s）%s'
                               % (self.进程.returncode, ('：' + 错文) if 错文 else ''))
        try:
            j = json.loads(行)
        except Exception:
            raise RuntimeError('GPU 子进程回的不是 JSON：%r' % 行[:200])
        if not j.get('成'):
            raise RuntimeError(j.get('说') or 'GPU 子进程起不来')
        端口 = int(j['端口'])
        连 = socket.create_connection(('127.0.0.1', 端口), timeout=30)
        self.连 = 连

    def 准备(self, 模型目录=''):
        with self.锁:
            if self.连 is not None:
                # ⭐ 1.6.10：已经连上就是这一份模型。别人要**另一档**时不能糊弄过去 ——
                #   否则陪看选了小模型、实际跑的是电话那份大的，两边对不上。
                if 模型目录 and self.模型目录 and os.path.abspath(模型目录) != os.path.abspath(self.模型目录):
                    self.错 = 'GPU 子进程已经在跑另一档模型'
                    return False
                return True
            if not 就绪() and not os.environ.get('鱼搭子_跳过就绪检查'):
                self.错 = '引擎没装齐：' + '、'.join(缺什么())
                return False
            try:
                self._拉起来(模型目录)
                self.错 = ''
                return True
            except Exception as e:
                self.错 = str(e)[:300]
                self.关掉()
                return False

    def 识别(self, 样本):
        """样本是 numpy float32（16k 单声道）。"""
        with self.锁:
            if self.连 is None:
                return ''
            数据 = 样本.astype('float32').tobytes()
            self.连.sendall(struct.pack('<I', len(数据)) + 数据)
            头 = _收够(self.连, 4)
            if not 头:
                raise RuntimeError('GPU 子进程断了')
            长 = struct.unpack('<I', 头)[0]
            身 = _收够(self.连, 长) or b''
            return 身.decode('utf-8', 'replace')

    def 关掉(self):
        try:
            if self.连 is not None:
                self.连.close()
        except Exception:
            pass
        self.连 = None
        try:
            if self.进程 is not None and self.进程.poll() is None:
                self.进程.terminate()
        except Exception:
            pass
        self.进程 = None


# ---------------------------------------------------------------------------
# 全进程共用一份
# ---------------------------------------------------------------------------
_共享 = None
_共享锁 = threading.Lock()

def 共享服务():
    """电话和陪看共用**同一个** GPU 子进程。

    ⭐ 1.6.10：以前两边各 `GPU服务()` 各拉一个 —— 两个 CUDA 引擎 + 两份模型，
       显存直接翻倍，8G 的卡会直接爆。这里只建一次。
    """
    global _共享
    with _共享锁:
        if _共享 is None:
            _共享 = GPU服务()
        return _共享
