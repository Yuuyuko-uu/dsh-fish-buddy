"""耳朵：麦克风 → 自动断句 → 本地离线识别 → 文字。

沿用 emu-hands 里已经验过的那套（sherpa-onnx 的 SenseVoice + silero VAD），
不联网、不上传。识别结果通过 on_text 回调交出去。
"""
import os
import re
import queue
import sys
import threading

import numpy as np


# ⭐ 1.0.6：识别模型**全进程只加载一次**。
#   以前每个「耳朵」实例都自己 from_sense_voice() 一遍（894MB 的模型），
#   所以按一次电话 / 按一次按住说话都要等它重新加载 —— 表现出来就是「按了没反应、过一会儿才活」。
_识别器们 = {}


def 拿识别器(模型目录, num_threads=4):
    键 = (os.path.abspath(str(模型目录)), int(num_threads))
    if 键 in _识别器们:
        return _识别器们[键]
    import sherpa_onnx
    r = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=os.path.join(键[0], 'model.onnx'),
        tokens=os.path.join(键[0], 'tokens.txt'),
        num_threads=键[1], use_itn=True, language='zh',
    )
    _识别器们[键] = r
    return r


def 预热(模型目录, num_threads=4):
    """程序一起来就把模型读进内存（第一次要几秒，之后就秒开了）。"""
    try:
        return 拿识别器(模型目录, num_threads) is not None
    except Exception:
        return False


class 耳朵:
    def __init__(self, 依赖目录, 模型目录, on_text, on_state=None,
                 sample_rate=16000, device=None, num_threads=4):
        self.依赖目录 = 依赖目录
        self.模型目录 = 模型目录
        self.sample_rate = sample_rate
        self.device = device
        self.num_threads = num_threads
        self.on_text = on_text
        self.on_state = on_state or (lambda *a: None)
        self._q = queue.Queue()
        self._stop = threading.Event()
        self._马上 = threading.Event()   # ⭐ 1.0.7：松手了，立刻定稿
        # ⭐ 1.2.1：麦克风可以一直开着（启动快），但**只有按着说话的那段时间才真的听**。
        #   以前开着就一直识别，松手之后旁边说话也会被录进去、发出去。
        self._收听中 = True
        self._识别器 = None
        self._vad = None

    # ---------- 模型 ----------
    def 记一笔(self, 话):
        """电话那条腿的取证日志：起点/模型/设备/音量/出错都写一行。

        界面上看不出卡在「麦克风 / 模型 / 音量」哪一步，
        所以要能把「设备开没开、有没有声音、模型加载到哪」全留下证据。
        """
        try:
            from paths import 用户目录
            import time as _t
            os.makedirs(用户目录(), exist_ok=True)
            with open(os.path.join(用户目录(), '电话-诊断.log'), 'a', encoding='utf-8') as f:
                f.write(_t.strftime('%H:%M:%S') + '  ' + str(话) + '\n')
        except Exception:
            pass

    def _懒加载(self):
        if self._识别器 is not None:
            return
        if self.依赖目录 and self.依赖目录 not in sys.path:
            sys.path.insert(0, self.依赖目录)
        import sherpa_onnx  # 放在这里，导入时不拖慢启动
        self.记一笔('模型目录=' + str(self.模型目录))

        self.模型目录 = os.path.abspath(self.模型目录)
        self._识别器 = 拿识别器(self.模型目录, self.num_threads)
        c = sherpa_onnx.VadModelConfig()
        c.silero_vad.model = os.path.join(self.模型目录, 'silero_vad.onnx')
        c.silero_vad.threshold = 0.35
        # ⭐ 0.5.0：
        #   「安静多久算一句」以前写死 1.2 秒 —— 现在跟设置里那个数走（默认 2.0）。
        静音秒 = 2.0
        try:
            from paths import 读配置
            静音秒 = float(读配置().get('断句静音秒') or 2.0)
        except Exception:
            pass
        静音秒 = max(0.4, min(8.0, 静音秒))
        c.silero_vad.min_silence_duration = 静音秒
        c.silero_vad.min_speech_duration = 0.1
        c.silero_vad.max_speech_duration = 15.0
        c.sample_rate = self.sample_rate
        self._vad = sherpa_onnx.VoiceActivityDetector(c, buffer_size_in_seconds=30)
        self.记一笔('模型和 VAD 都好了（安静 %.1f 秒算一句）' % 静音秒)

    def _认(self, samples):
        s = self._识别器.create_stream()
        s.accept_waveform(self.sample_rate, np.asarray(samples, dtype=np.float32))
        self._识别器.decode_stream(s)
        text = (s.result.text or '').strip()
        return text

    # ---------- 循环 ----------
    def 跑(self):
        try:
            self.on_state('loading')
            self._懒加载()
            import sounddevice as sd
            self.on_state('listening')
            self._stop.clear()
            self.记一笔('开麦克风：设备=%s 采样率=%s' % (self.device, self.sample_rate))
            self._峰值 = 0.0
            self._块数 = 0
            self._上次报 = 0.0
            with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype='float32',
                                device=self.device, callback=self._cb, blocksize=1024):
                self.记一笔('麦克风开着（进来 0 块之前不会有别的）')
                while not self._stop.is_set():
                    try:
                        chunk = self._q.get(timeout=0.2)
                    except queue.Empty:
                        # 松手时正好没新块过来，也得立刻定稿
                        if self._马上.is_set():
                            self._马上.clear()
                            try:
                                self._vad.flush()
                                self.记一笔('松手了：立刻定稿（没等到新的一块）')
                            except Exception:
                                pass
                            self._排空()
                        continue
                    try:
                        self._块数 += 1
                        self._峰值 = max(self._峰值, float(abs(chunk).max()))
                    except Exception:
                        pass
                    if not getattr(self, '_收听中', True):
                        # 没按着说话：声音不进识别（麦克风只是开着，起得快）。
                        # ⚠ 1.2.5：但**松手定稿的请求**必须照样处理 ——
                        #   以前这一句 `continue` 把松手后那一刻的 flush 也一起跳过了，
                        #   于是「按了、也截了图，但话一直发不出去」。
                        if getattr(self, '_马上', None) is not None and self._马上.is_set():
                            self._马上.clear()
                            try:
                                self._vad.flush()
                                self.记一笔('松手了：立刻定稿（没按着也照样定）')
                            except Exception:
                                pass
                            self._排空()
                        continue
                    self._vad.accept_waveform(chunk)
                    if self._马上.is_set():
                        self._马上.clear()
                        try:
                            self._vad.flush()
                            self.记一笔('松手了：立刻定稿')
                        except Exception:
                            pass
                    self._排空()
                    self._报一次()
        except Exception as e:
            self.记一笔('挂了：%s' % e)
            self.on_state('error', '麦克风打不开：%s' % e)
        finally:
            self.记一笔('这条腿结束了（进来 %d 块）' % getattr(self, '_块数', 0))
            self.on_state('idle')

    def _排空(self):
        """把 VAD 里已经定下来的段全认出来。"""
        while not self._vad.empty():
            seg = self._vad.front
            samples = seg.samples if hasattr(seg, 'samples') else seg
            self._vad.pop()
            try:
                text = self._认(samples)
            except Exception as e:
                self.记一笔('识别出错：%s' % e)
                self.on_state('error', '识别出错：%s' % e)
                continue
            if text:
                self.记一笔('听到：' + text)
                self.on_text(text)

    def 只听(self, 开):
        """⭐ 1.2.1：按着说话才听；松手就闭嘴（麦克风不关，起得快）。"""
        self._收听中 = bool(开)

    def 现在就说(self):
        """⭐ 1.0.7：按住说话松手 = 我说完了，别再等「安静几秒」——立刻把这段定下来。"""
        try:
            self._马上.set()
        except Exception:
            pass

    def _报一次(self):
        """每 10 秒记一行「收到几块 + 最大音量」，能一眼看出「设备开着但没声音」。"""
        try:
            import time as _t
            现在 = _t.time()
            if 现在 - getattr(self, '_上次报', 0) < 10:
                return
            self._上次报 = 现在
            self.记一笔('10 秒：收到 %d 块，最大音量 %.4f' % (self._块数, self._峰值))
            self._峰值 = 0.0
        except Exception:
            pass

    def _cb(self, indata, frames, t, status):
        self._q.put(indata[:, 0].copy())

    def 开(self):
        threading.Thread(target=self.跑, daemon=True).start()

    def 停(self):
        self._stop.set()

    def 暂停(self):
        self._stop.set()


def _端点键(名字):
    """把「麦克风 (Realtek HD Audio Mic input)」这类名字压成同一个键。

    同一只物理设备在 MME / DirectSound / WASAPI / WDM-KS 下面会各出现一次，
    名字不一样但**括号里的端点名是同一个** —— 按端点名合并，比按整串名字比更准。
    """
    t = str(名字 or '').strip()
    if not t:
        return ''
    m = re.findall(r'[（(]([^）)]+)[）)]', t)
    k = (m[-1] if m else t).strip().lower()
    # 去掉 API 层带来的尾巴和「输入/输出」这种词
    k = re.sub(r'\s*[-—]?\s*(input|output|wave\s*\d*|wave|input device|output device)\s*$', '', k)
    k = re.sub(r'\s+', ' ', k).strip(' -_')
    return k


def 列输入设备():
    """能录的麦克风列表：[{'编号','名字','声道','默认','主机'}]。

    同一个麦克风在各家 API（MME / DirectSound / WASAPI / WDM-KS）下会出现四遍，
    这里**按名字去重**，优先留 WASAPI 那个（延迟低、音质好），默认那个也留。
    一个都拿不到就返回 []（不抛异常，设置页要能照常打开）。
    """
    try:
        import sounddevice as sd
        设备表 = list(sd.query_devices())
        主机表 = list(sd.query_hostapis())
        默认 = sd.default.device
    except Exception:
        return []
    try:
        # sounddevice 给的是个 `_InputOutputPair`（[输入号, 输出号]），不认 isinstance(list)
        默认号 = int(默认[0])
    except Exception:
        try:
            默认号 = int(默认)
        except Exception:
            默认号 = None

    def 主机名(号):
        try:
            return str(主机表[int(号)].get('name') or '')
        except Exception:
            return ''

    次序 = []          # 有序：[{'编号','名字','声道','默认','主机'}]
    for i, x in enumerate(设备表):
        try:
            声道 = int(x.get('max_input_channels') or 0)
        except Exception:
            声道 = 0
        if 声道 <= 0:
            continue
        名字 = str(x.get('name') or '').strip() or '（没名字的麦克风）'
        项 = {'编号': i, '名字': 名字, '声道': 声道,
              '默认': (默认号 is not None and i == 默认号), '主机': 主机名(x.get('hostapi'))}

        旧位 = None
        键 = _端点键(名字)
        for k, 旧 in enumerate(次序):
            同 = (旧['名字'] == 名字)
            # ⭐ 1.2.9：按**端点名**合并（同一只麦在 MME/DirectSound/WASAPI/WDM-KS 下各出现一次，
            #   名字不一样但括号里是同一个端点）。以前只按整串名字比，于是同一只麦列了三四遍。
            同端点 = bool(键) and 键 == _端点键(旧['名字'])
            # MME 的名字会被截到 30 来个字（括号都不闭合），所以前缀相同也算同一个设备；
            # 但太短的前缀别并（「麦克风 1」「麦克风 2」是两只）。
            像 = (not 同) and min(len(旧['名字']), len(名字)) >= 12 and (
                名字.startswith(旧['名字']) or 旧['名字'].startswith(名字))
            if 同 or 同端点 or 像:
                旧位 = k
                break
        if 旧位 is None:
            次序.append(项)
            continue

        旧 = 次序[旧位]
        留新 = False
        if 项['默认'] and not 旧['默认']:
            留新 = True                                    # 默认那只优先
        elif not 旧['默认'] and ('WASAPI' in 项['主机']) and ('WASAPI' not in 旧['主机']):
            留新 = True                                    # WASAPI 优先
        elif 'WASAPI' in 项['主机'] and 'WASAPI' in 旧['主机'] and len(名字) > len(旧['名字']):
            留新 = True                                    # 名字更完整的那只
        合 = dict(项 if 留新 else 旧)
        合['默认'] = bool(旧['默认'] or 项['默认'])
        次序[旧位] = 合
    return 次序


def 找设备(编号=None, 名字=''):
    """把配置里的选择变成 sounddevice 能用的 device，并给一句人话。

    返回 (device, 说法)。device 是设备号（或 None = 系统默认）。
    设备被拔了 / 换了电脑 → 按名字找；名字也对不上 → 退回系统默认，不报错。
    """
    设备 = 列输入设备()
    if not 设备:
        return None, '这台机器没找到能用的麦克风，先用系统默认'
    if 编号 in (None, '', 'None'):
        for d in 设备:
            if d['默认']:
                return d['编号'], '系统默认：' + d['名字']
        return None, '系统默认'
    try:
        号 = int(编号)
    except Exception:
        号 = None
    for d in 设备:
        if 号 is not None and d['编号'] == 号:
            return d['编号'], d['名字']
    if 名字:
        for d in 设备:
            if d['名字'] == 名字:
                return d['编号'], d['名字'] + '（换了编号，已按名字找回来）'
    return None, '原来选的那个麦克风不在了，先用系统默认'


def 列设备():
    for d in 列输入设备():
        print('  [%d] %s%s' % (d['编号'], d['名字'], '　← 系统默认' if d['默认'] else ''))
