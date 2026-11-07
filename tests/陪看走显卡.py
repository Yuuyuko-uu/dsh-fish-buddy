"""陪看要不要走显卡 —— 1.6.10 的回归。

跑：cd app && python ../tests/陪看走显卡.py

不碰真显卡、也不碰真模型：sherpa_onnx 和 GPU 子进程都打桩，
验的是**选择逻辑**——
  ① 设置说 cpu        → 本地建引擎，跟以前一样
  ② 设置说 cuda 但引擎没装 → 退回本地，不许报错
  ③ 设置说 cuda 且引擎在   → 走 GPU 子进程，结果就是子进程回的话
  ④ GPU 跑到一半断了       → 退回本地，且不再回头试 GPU
  ⑤ 电话和陪看共用同一个子进程（不重复占显存）
"""
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(os.path.dirname(HERE), 'app')
sys.path.insert(0, APP)


# ---------------------------------------------------------------------------
# 打桩：sherpa_onnx（本地识别器）
# ---------------------------------------------------------------------------
class _流:
    def __init__(self, 话):
        self.result = types.SimpleNamespace(text=话)

    def accept_waveform(self, *a, **k):
        pass


class _识别器:
    def __init__(self, 话, 名字):
        self.话 = 话
        self.名字 = 名字
        self.建法 = []

    def create_stream(self):
        return _流(self.话)

    def decode_stream(self, s):
        pass


def _装假sherpa():
    模 = types.ModuleType('sherpa_onnx')

    class _离线:
        @staticmethod
        def from_paraformer(**k):
            _离线.最近 = ('paraformer', k)
            return _识别器('本地-paraformer', 'paraformer')

        @staticmethod
        def from_sense_voice(*a, **k):
            _离线.最近 = ('sense', k)
            return _识别器('本地-sense', 'sense')

    模.OfflineRecognizer = _离线
    模.VadModelConfig = lambda: types.SimpleNamespace(
        silero_vad=types.SimpleNamespace(), sample_rate=16000)
    模.VoiceActivityDetector = lambda *a, **k: None
    sys.modules['sherpa_onnx'] = 模
    return _离线


class _假GPU:
    """假的 GPU 子进程客户端：跟 gpu引擎.GPU服务 同样的三个方法。"""

    def __init__(self, 回话='显卡认的', 准备=True, 识别会炸=False):
        self.回话 = 回话
        self.准备结果 = 准备
        self.识别会炸 = 识别会炸
        self.准备次数 = 0
        self.识别次数 = 0
        self.要过的目录 = []

    def 准备(self, 模型目录=''):
        self.准备次数 += 1
        self.要过的目录.append(模型目录)
        return self.准备结果

    def 识别(self, 样本):
        self.识别次数 += 1
        if self.识别会炸:
            raise RuntimeError('GPU 子进程断了')
        return self.回话

    def 关掉(self):
        pass


class 陪看走显卡(unittest.TestCase):
    def setUp(self):
        self.离线 = _装假sherpa()
        import paths
        import gpu引擎
        self.paths = paths
        self.gpu = gpu引擎
        self._原设备 = paths.当前设备
        self._原共享 = gpu引擎.共享服务
        self._原就绪 = gpu引擎.就绪

    def tearDown(self):
        self.paths.当前设备 = self._原设备
        self.gpu.共享服务 = self._原共享
        self.gpu.就绪 = self._原就绪

    # ---- 小工具 ----
    def 设设备(self, 值):
        self.paths.当前设备 = lambda: 值

    def 装共享(self, 假):
        self.gpu.共享服务 = lambda: 假

    def 引擎(self):
        import watch_ui
        return watch_ui.SenseEngine(lang='zh', 档='int8')

    # ---- ① ----
    def test_1_设置是cpu就本地(self):
        self.设设备('cpu')
        e = self.引擎()
        self.assertEqual(e.名, 'SenseVoice')
        self.assertEqual(e.transcribe([0.0] * 1600), '本地-sense')
        self.assertIsNone(e._gpu)

    # ---- ② ----
    def test_2_要cuda但引擎没装_退回本地(self):
        self.设设备('cuda')
        self.装共享(_假GPU(准备=False))
        e = self.引擎()
        self.assertIsNone(e._gpu, '没准备好就不能挂在 GPU 上')
        self.assertEqual(e.transcribe([0.0] * 1600), '本地-sense')

    # ---- ③ ----
    def test_3_要cuda且引擎在_走显卡(self):
        self.设设备('cuda')
        假 = _假GPU(回话='显卡认的')
        self.装共享(假)
        e = self.引擎()
        self.assertEqual(e.名, 'GPU')
        self.assertEqual(e.transcribe([0.0] * 1600), '显卡认的')
        self.assertEqual(假.识别次数, 1, '应该只问显卡，不许本地也认一遍')
        self.assertEqual(假.要过的目录[0], self.paths.档目录('int8'),
                         '要把陪看选的那一档告诉子进程，不能让它自己挑')

    # ---- ④ ----
    def test_4_显卡断了退回本地且不再试(self):
        self.设设备('cuda')
        假 = _假GPU(识别会炸=True)
        self.装共享(假)
        e = self.引擎()
        self.assertEqual(e.名, 'GPU')
        self.assertEqual(e.transcribe([0.0] * 1600), '本地-sense', '断了要立刻用本地顶上')
        self.assertIsNone(e._gpu)
        self.assertIn('退回', e.名)
        第一次 = 假.识别次数
        self.assertEqual(e.transcribe([0.0] * 1600), '本地-sense')
        self.assertEqual(假.识别次数, 第一次, '断过一次就不许再问显卡')

    # ---- ⑤ ----
    def test_5_共享一个子进程(self):
        甲 = self.gpu.共享服务()
        乙 = self.gpu.共享服务()
        self.assertIs(甲, 乙, '电话和陪看必须是同一个 GPU 子进程，不然显存翻倍')

    # ---- ⑥ ----
    def test_6_另一档模型不硬用(self):
        服 = self.gpu.GPU服务()
        服.连 = object()          # 假装已经连上
        服.模型目录 = self.paths.档目录('fp32')
        self.assertTrue(服.准备(self.paths.档目录('fp32')))
        self.assertFalse(服.准备(self.paths.档目录('int8')),
                         '子进程跑着 A 档时，B 档不能假装能用')


if __name__ == '__main__':
    unittest.main(verbosity=2)
