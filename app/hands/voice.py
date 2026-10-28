"""嘴（听）：麦克风 → VAD 自动断句 → SenseVoice 离线识别 → 文字。

锁中文 + 热词纠错。识别结果逐句 print + 追加写 asr_log.txt（桥读这个文件送进会话）。
"""
import os
import queue
import threading
import sys

import paths  # 模型放在用户目录（打包后程序目录只读）

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import sherpa_onnx
import sounddevice as sd

ASR_DIR = paths.模型目录()

# 高频听错的词 → 正确的词（热词纠错；其余可在 config.json -> voice.hotwords 扩）
DEFAULT_HOTWORDS = {
    '大鳄鱼': '大肥鱼',
    '大饿鱼': '大肥鱼',
    '鳄鱼': '肥鱼',
}


def make_recognizer(num_threads=4, lang='zh'):
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=os.path.join(ASR_DIR, 'model.onnx'),
        tokens=os.path.join(ASR_DIR, 'tokens.txt'),
        num_threads=num_threads, use_itn=True, language=lang,
    )


def make_vad():
    c = sherpa_onnx.VadModelConfig()
    c.silero_vad.model = os.path.join(ASR_DIR, 'silero_vad.onnx')
    c.silero_vad.threshold = 0.35
    c.silero_vad.min_silence_duration = 0.7
    c.silero_vad.min_speech_duration = 0.25
    c.silero_vad.max_speech_duration = 12.0
    c.sample_rate = 16000
    return sherpa_onnx.VoiceActivityDetector(c, buffer_size_in_seconds=30)


def list_devices():
    print('默认输入设备:', sd.default.device)
    for i, x in enumerate(sd.query_devices()):
        if x['max_input_channels'] > 0:
            print('  [%d] %s' % (i, x['name']))


class Ear:
    def __init__(self, sample_rate=16000, device=None, num_threads=4, log_file=None, hotwords=None):
        self.sample_rate = sample_rate
        self.device = device
        self.recognizer = make_recognizer(num_threads)
        self.vad = make_vad()
        self.log_file = log_file or os.path.join(HERE, 'asr_log.txt')
        self.hotwords = dict(DEFAULT_HOTWORDS)
        if hotwords:
            self.hotwords.update(hotwords)
        self._q = queue.Queue()
        self._stop = threading.Event()

    def _cb(self, indata, frames, t, status):
        self._q.put(indata[:, 0].copy())

    def _transcribe(self, samples):
        s = self.recognizer.create_stream()
        s.accept_waveform(self.sample_rate, np.asarray(samples, dtype=np.float32))
        self.recognizer.decode_stream(s)
        text = (s.result.text or '').strip()
        for k, v in self.hotwords.items():
            text = text.replace(k, v)
        return text

    def emit(self, text):
        print('[听说] ' + text, flush=True)
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(text + '\n')
        except Exception:
            pass

    def run(self):
        """阻塞运行，直到 Ctrl-C / stop()。"""
        self._stop.clear()
        try:
            with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype='float32',
                                device=self.device, callback=self._cb, blocksize=1024):
                print('[听说] 开始听（Ctrl-C 结束）…', flush=True)
                while not self._stop.is_set():
                    try:
                        chunk = self._q.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    self.vad.accept_waveform(chunk)
                    while not self.vad.empty():
                        seg = self.vad.front
                        samples = seg.samples if hasattr(seg, 'samples') else seg
                        text = self._transcribe(samples)
                        self.vad.pop()
                        if text:
                            self.emit(text)
        except KeyboardInterrupt:
            pass
        except Exception as e:
            print('[听说] 出错:', e)

    def stop(self):
        self._stop.set()