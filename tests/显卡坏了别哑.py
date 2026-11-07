"""显卡那条路出问题时，别把整场弄哑 —— issue #8 / #10 的回归。

跑：cd app && python ../tests/显卡坏了别哑.py

不碰真显卡、不碰真模型：sherpa_onnx / sounddevice / GPU 子进程全打桩。
验的是：
  ① 选了 cuda，GPU 第一句就炸 → 这一句用本地认出结果，不抛异常
  ② 炸过一次之后永久走本地，不再回头问显卡（issue #10 的「永久哑掉」）
  ③ 失败时**不许关共享的 GPU 子进程**（电话和陪看共用一份，关掉会把别人弄哑）
  ④ 换新耳朵之前，旧耳朵要被停掉（issue #8 的进程堆积）
"""
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(os.path.dirname(HERE), 'app')
sys.path.insert(0, APP)


# ---------------------------------------------------------------------------
# 打桩
# ---------------------------------------------------------------------------
class _流:
    def __init__(self, 话):
        self.result = types.SimpleNamespace(text=话)

    def accept_waveform(self, *a, **k):
        pass


class _识别器:
    def __init__(self, 话):
        self.话 = 话

    def create_stream(self):
        return _流(self.话)

    def decode_stream(self, s):
        pass


def _装假sherpa():
    模 = types.ModuleType('sherpa_onnx')
    模.OfflineRecognizer = types.SimpleNamespace(
        from_paraformer=lambda **k: _识别器('本地-paraformer'),
        from_sense_voice=lambda *a, **k: _识别器('本地-sense'),
    )
    模.VadModelConfig = lambda: types.SimpleNamespace(
        silero_vad=types.SimpleNamespace(), sample_rate=16000)
    模.VoiceActivityDetector = lambda *a, **k: None
    sys.modules['sherpa_onnx'] = 模

    声 = types.ModuleType('sounddevice')
    声.query_devices = lambda *a, **k: {'default_samplerate': 16000}
    声.check_input_settings = lambda **k: None
    声.default = types.SimpleNamespace(device=(0, 0))
    sys.modules['sounddevice'] = 声


class _假GPU:
    def __init__(self, 会炸=True):
        self.会炸 = 会炸
        self.识别次数 = 0
        self.关掉次数 = 0

    def 准备(self, 模型目录=''):
        return True

    def 识别(self, 样本):
        self.识别次数 += 1
        if self.会炸:
            raise RuntimeError('子进程挂了')
        return '显卡认的'

    def 关掉(self):
        self.关掉次数 += 1


class 显卡坏了别哑(unittest.TestCase):
    def setUp(self):
        _装假sherpa()
        import ear
        import paths
        self.ear = ear
        self.paths = paths
        self._原设备 = paths.当前设备
        self._原拿 = ear.拿识别器
        ear.拿识别器 = lambda 目录, 线程=4: _识别器('本地-sense')
        ear._识别器们.clear()
        paths.当前设备 = lambda: 'cuda'

    def tearDown(self):
        self.ear.拿识别器 = self._原拿
        self.paths.当前设备 = self._原设备

    def 造耳朵(self, 假gpu):
        import gpu引擎
        gpu引擎.共享服务 = lambda: 假gpu
        e = self.ear.耳朵(依赖目录='', 模型目录='C:/假模型', on_text=lambda t: None, num_threads=1)
        e._懒加载()
        return e

    # ①
    def test_1_显卡炸了这一句用本地(self):
        假 = _假GPU(会炸=True)
        e = self.造耳朵(假)
        self.assertEqual(e._设备, 'cuda')
        文 = e._认([0.0] * 1600)
        self.assertEqual(文, '本地-sense', '显卡炸了也要能认出这一句，不能抛异常')
        self.assertEqual(假.识别次数, 1)

    # ②
    def test_2_炸过就永久本地(self):
        假 = _假GPU(会炸=True)
        e = self.造耳朵(假)
        e._认([0.0] * 1600)
        self.assertEqual(e._设备, 'cpu', '失败后要改成 cpu')
        self.assertIsNone(e._gpu, '不能还攥着 GPU 服务')
        第一次 = 假.识别次数
        self.assertEqual(e._认([0.0] * 1600), '本地-sense')
        self.assertEqual(假.识别次数, 第一次, '退回 CPU 之后不许再问显卡')

    # ③
    def test_3_失败不许关共享子进程(self):
        假 = _假GPU(会炸=True)
        e = self.造耳朵(假)
        e._认([0.0] * 1600)
        self.assertEqual(假.关掉次数, 0, '共享的子进程关掉会把电话/陪看一起弄哑')

    # ④
    def test_4_换耳朵前先停旧的(self):
        import inspect
        src = inspect.getsource(self.ear)
        self.assertTrue(os.path.exists(os.path.join(APP, 'ball.py')))
        with open(os.path.join(APP, 'ball.py'), encoding='utf-8') as f:
            文 = f.read()
        位 = 文.find('def _开耳朵_真的')
        段 = 文[位:位 + 3000]
        self.assertIn('旧.停()', 段, '建新耳朵之前要先把旧的停掉，否则收音线程和子进程都会堆')


if __name__ == '__main__':
    unittest.main(verbosity=2)
