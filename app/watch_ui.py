"""陪看 · 桌面版（纯 tkinter，无额外 GUI 依赖）。

选一个正在发声的进程 → 抓系统声音 → VAD 断句 → 识别 → 字幕。

工程技巧（灵感来自 Ai_EchoSub / LiveSpeech2Text / VAD 生产配置文档，见 README「致谢」）：
  1. 句子平滑合并：短碎片在停顿很小时自动拼成一句，不切得七零八落
  2. 防幻觉：静音抑制 + 常见幻觉黑名单 + 重复去重
  3. 音量归一：抓到/截出的音频常常偏小，先拉齐再判
"""
import os
import sys
import json
import threading
import time
import queue

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
sys.path.insert(0, HERE)

import paths  # 配置/模型/日志都在用户目录里（打包后程序目录是只读的）
import json as _json
import urllib.request as _urllib

# 本机端口一律不走代理（系统代理会把 127.0.0.1 也拦下来）
_本机直连 = _urllib.build_opener(_urllib.ProxyHandler({}))

# 诊断日志：出问题就看这个（>2MB 自动重开一份）
DIAG = os.path.join(paths.用户目录(), '陪看-诊断.log')

# ⭐ 0.0.9：每推一条字幕记一行，带结果。
#    出问题时直接翻这个文件，就能分清是「没推」还是「推了但被窗口滚掉」。
字幕日志 = os.path.join(paths.用户目录(), '字幕记录.log')


def _记一句字幕日志(文, 结果):
    try:
        if os.path.exists(字幕日志) and os.path.getsize(字幕日志) > 1_000_000:
            try:
                os.replace(字幕日志, 字幕日志 + '.1')
            except Exception:
                open(字幕日志, 'w', encoding='utf-8').close()
        with open(字幕日志, 'a', encoding='utf-8') as f:
            f.write('%s\t%s\t%s\n' % (time.strftime('%H:%M:%S'), str(结果)[:120],
                                      str(文 or '').replace('\n', ' ')[:120]))
    except Exception:
        pass


def diag(msg):
    try:
        if os.path.exists(DIAG) and os.path.getsize(DIAG) > 2_000_000:
            open(DIAG, 'w', encoding='utf-8').close()
        with open(DIAG, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%H:%M:%S') + '  ' + str(msg) + '\n')
    except Exception:
        pass

import numpy as np
import tkinter as tk
from tkinter import ttk, simpledialog
from tkinter.scrolledtext import ScrolledText



# ⭐ 1.0.9：勾过的进程要记在用户目录 —— 打包成单文件后 HERE 是临时解压目录，
#   每次启动都会被清掉，「记住勾过的进程」其实一次都没记住过。
TARGETFILE = os.path.join(paths.用户目录(), 'targets.json')


def load_targets():
    """记住勾过的进程：没发声时也留在列表里，重启也在。"""
    try:
        with open(TARGETFILE, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except Exception:
        return []


def save_targets(rows):
    try:
        with open(TARGETFILE, 'w', encoding='utf-8') as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
    except Exception:
        pass



class DarkOption(tk.Menubutton):
    """深色下拉框：ttk.Combobox 的弹出列表是白底的，跟深色界面打架。"""

    def __init__(self, master, values, width=10, command=None, **kw):
        super().__init__(master, bg=PANEL2, fg=FG, activebackground=HOVER,
                         activeforeground=FG, relief='flat',
                         font=('Microsoft YaHei UI', 10), padx=10, pady=4,
                         width=width, anchor='w', **kw)
        self._values = list(values)
        self._cur = ''
        self._command = command
        self._menu = tk.Menu(self, tearoff=0, bg=PANEL2, fg=FG,
                             activebackground=ACCENT, activeforeground='white',
                             relief='flat', borderwidth=0,
                             font=('Microsoft YaHei UI', 10))
        self.configure(menu=self._menu)
        self._rebuild()
        if self._values:
            self.set(self._values[0])

    def _rebuild(self):
        self._menu.delete(0, 'end')
        for v in self._values:
            self._menu.add_command(label=v, command=lambda v=v: self._pick(v))

    def _pick(self, v):
        self.set(v)
        if self._command:
            self._command(v)

    def set(self, v):
        self._cur = v
        self.configure(text=v)

    def get(self):
        return self._cur

    def set_values(self, values):
        self._values = list(values)
        self._rebuild()
        if self._cur not in self._values and self._values:
            self.set(self._values[0])


def mute_others(target_pid):
    """把除 target_pid 外的音频会话全静音，返回可恢复的 [(volume, 原mute)]。

    这样"设备环回"抓到的就只剩目标进程的声音 —— 不用虚拟声卡也能做到近似按进程抓。
    """
    saved = []
    try:
        from pycaw.pycaw import AudioUtilities
        for s in AudioUtilities.GetAllSessions():
            p = getattr(s, 'Process', None)
            if not p:
                continue
            try:
                if p.pid == target_pid:
                    continue
                vol = s.SimpleAudioVolume
                if not vol:
                    continue
                m = vol.GetMute()
                if m != 1:
                    vol.SetMute(1, None)
                    saved.append((vol, m))
            except Exception:
                pass
    except Exception:
        pass
    return saved


def restore_muted(saved):
    for vol, m in saved:
        try:
            vol.SetMute(m, None)
        except Exception:
            pass

# ---------- 防幻觉 ----------
# 常见 ASR 幻觉（无声/噪声时模型爱硬编出来的套话）
HALLUCINATIONS = {
    '谢谢观看', '感谢观看', '谢谢大家', '请不吝点赞', '点赞订阅', '订阅频道',
    '字幕由', '字幕提供', '字幕制作', '本期节目', '下次再见', 'amara', 'mbc',
    '中文字幕', '由amara', '请订阅', '欢迎订阅',
}
PUNCT = '。！？，、,.!?;；:：…'


def ends_sentence(s):
    return bool(s) and s[-1] in PUNCT


def looks_like_hallucination(t):
    low = t.lower()
    if len(t) <= 1:
        return True
    for h in HALLUCINATIONS:
        if h in low:
            return True
    # 全同一个字重复（"三三三三"）
    if len(set(t.replace(' ', ''))) == 1 and len(t) >= 3:
        return True
    return False


# ---------- 断句：看字，不看声音（0.2.0 重写） ----------
# 🔴 关键一条：片子里永远有环境音、音乐、底噪，VAD 想等「干净静音」才切段 —— 永远等不到。
#    实测：连续有声时 VAD 一段能长到 14~17 秒，而预览只留最近 5 秒 → 前面说过的话
#    既没落定、也没留在屏幕上，直接丢。所以断句改成**看文字**：
#      ① 连着几次认出来一模一样 → 说完了（模型每次都会给整段加标点，所以「结尾有句号」
#         不能当断句信号 —— 试过，会把一句话从中间剁开）
#      ② 攒满 7 秒还没完 → 硬切，切出来的整段再按标点拆成几行
句末 = '。！？!?….．'      # 都算句末（ASCII 的 '.' 夹在数字中间不算，见 是句末）
最长一句秒 = 7.0         # 到这儿硬切
认的间隔秒 = 1.2         # 多久整条重认一次（实测 10 秒音频只要 190ms）
稳定几次 = 3             # 连着 3 次认出来一样（约 2.4~3.6 秒没新字）就算说完


def 是句末(t, i):
    """t[i] 是不是真的句末。ASCII 句点夹在数字中间（3.5）不算。"""
    ch = t[i]
    if ch in '.．':
        prev = t[i - 1] if i > 0 else ''
        nxt = t[i + 1] if i + 1 < len(t) else ''
        if prev.isdigit() and nxt.isdigit():
            return False
    return ch in 句末


def 有内容(t):
    """去掉标点/空格/符号以后还剩几个「字」。用来挡静音时吐出来的垃圾句
    （实测：没声音时模型会吐「그.」「嗯。」这种一两个字的，长度 2 刚好躲过老的过滤）。"""
    return sum(1 for ch in str(t or '') if ch.isalnum())


def 拆句(t):
    """按句末标点拆成几行；尾巴不超过 6 个字就并回上一句，别切出「然后我」这种碎片。"""
    t = str(t or '').strip()
    out, cur = [], ''
    for i, ch in enumerate(t):
        cur += ch
        if 是句末(t, i):
            s = cur.strip()
            if s:
                out.append(s)
            cur = ''
    cur = cur.strip()
    if cur:
        if out and len(cur) <= 6:
            out[-1] = out[-1] + cur
        else:
            out.append(cur)
    return out


def 该定稿(文本, 相同次数, 秒):
    """这一句该不该落定。纯函数，自测直接打。

    ⚠ 别把「结尾有句号」当断句信号：模型每次都会把整段重新加一遍标点，
      拿它当闸会把一句话从中间剁成「We are watching.」这种碎片（实测过）。
    """
    if not 文本:
        return 秒 >= 12.0          # 一直只有音乐/没人说话：别无限攒，丢掉重来
    if 相同次数 >= 稳定几次:
        return True                # 连着几次一模一样 → 话说完了
    return 秒 >= 最长一句秒         # 一直不断 → 硬切（切出来的整段按标点拆行）


def list_audio_processes():
    rows = []
    try:
        from pycaw.pycaw import AudioUtilities
        for s in AudioUtilities.GetAllSessions():
            p = getattr(s, 'Process', None)
            if not p:
                continue
            try:
                rows.append((p.pid, p.name(), int(getattr(s, 'State', 0)) == 1))
            except Exception:
                pass
    except Exception as e:
        return [], str(e)
    dedup = {}
    for pid, name, act in rows:
        k = (pid, name)
        dedup[k] = (pid, name, act or dedup.get(k, (0, 0, False))[2])
    return sorted(dedup.values(), key=lambda x: (not x[2], x[1].lower())), None


class SenseEngine:
    """SenseVoice —— 全程序只有这一份模型（fp32，894MB，最准的那份）。

    ⭐ 0.2.5：int8 那 228MB 的小模型和 Paraformer 都退役了，
    这里不再有「哪一份」的概念，只认 `models\\model.onnx`。
    """

    def __init__(self, lang='auto'):
        import sherpa_onnx
        import paths
        目录 = paths.模型目录()
        模型 = os.path.join(目录, 'model.onnx')
        词表 = os.path.join(目录, 'tokens.txt')
        if not (os.path.exists(模型) and os.path.exists(词表)):
            raise RuntimeError('语音模型还没装（设置 → 语音里点「装语音」）')
        self.rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            模型, 词表, num_threads=4, use_itn=True,
            language=('auto' if not lang or lang == 'auto' else lang))
        self.名 = 'SenseVoice'

    def transcribe(self, samples):
        s = self.rec.create_stream()
        s.accept_waveform(16000, np.asarray(samples, dtype=np.float32))
        self.rec.decode_stream(s)
        return (s.result.text or '').strip()


def 建引擎(名='', lang='auto'):
    """陪看用的识别引擎。

    ⭐ 0.2.5：**只有一个模型**（fp32），语言也不给选。参数留着只是为了兼容老调用和自测。
    """
    return SenseEngine(lang)


class WhisperEngine:
    """faster-whisper：日语强得多（whisper 日语训练数据多）。"""

    def __init__(self, lang='ja', size='small'):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(size, device='cpu', compute_type='int8',
                                  download_root=os.path.join(ROOT, 'asr_models', 'whisper'),
                                  cpu_threads=8)
        # 'auto' = 让它自己判语言（whisper 的 language=None）
        self.lang = None if (not lang or lang == 'auto') else lang
        self.size = size

    def transcribe(self, samples):
        t0 = time.time()
        段们, _ = self.model.transcribe(
            np.asarray(samples, dtype=np.float32),
            language=self.lang, beam_size=1, vad_filter=False,
            condition_on_previous_text=False,          # 别顺着上一句瞎编
            temperature=0.0,                            # 贪心，不采样（少编）
            no_speech_threshold=0.55,                  # 像静音就跳过
            log_prob_threshold=-0.9,                   # 置信度低就跳过
            compression_ratio_threshold=2.2,           # 重复啰嗦就丢
        )
        out = []
        丢 = {'非语音': 0, '低置信': 0}
        for s in 段们:
            ns = getattr(s, 'no_speech_prob', None)
            lp = getattr(s, 'avg_logprob', None)
            if ns is not None and ns > 0.6:            # 判断成非语音
                丢['非语音'] += 1
                continue
            if lp is not None and lp < -1.0:           # 置信度太低 → 宁可不出
                丢['低置信'] += 1
                continue
            out.append(s.text)
        self.last_ms = int((time.time() - t0) * 1000)
        self.last_drop = 丢
        return ''.join(out).strip()


def wav_info(path):
    """解析流式 WAV 头：返回 (data 起始偏移, 采样率, 声道)；头没写完返回 (None, 0, 0)。"""
    try:
        with open(path, 'rb') as f:
            head = f.read(8192)
    except Exception:
        return None, 0, 0
    if len(head) < 12 or head[:4] != b'RIFF':
        return None, 0, 0
    i = 12
    rate, ch = 0, 0
    while i + 8 <= len(head):
        cid = head[i:i + 4]
        sz = int.from_bytes(head[i + 4:i + 8], 'little')
        if cid == b'fmt ' and i + 8 + 16 <= len(head):
            ch = int.from_bytes(head[i + 10:i + 12], 'little')
            rate = int.from_bytes(head[i + 12:i + 16], 'little')
        if cid == b'data':
            return i + 8, rate or 48000, ch or 1
        i += 8 + sz + (sz & 1)
    return None, 0, 0


class Captioner(threading.Thread):
    def __init__(self, lang='auto', mode='vad', chunk_sec=6.0, on_line=None, on_err=None,
                 on_status=None, target_pids=None, only_target=True, partial=True,
                 engine='auto'):
        super().__init__(daemon=True)
        from hands import voice
        self.voice = voice
        self.lang = lang
        self.engine = None
        # 引擎档位：auto（跟着语言走）/ sense / whisper / turbo
        self.engine_pick = engine or 'auto'
        self.vad = voice.make_vad()
        self.mode = mode
        self.chunk = int(max(2.0, chunk_sec) * 16000)
        self.target_pids = list(target_pids or [])
        self.only_target = only_target
        self._pcm_ch = 2
        self._pcm_factor = 3
        self.partial = partial
        self._src = {}
        self._src_t = {}
        self._src_lock = threading.Lock()
        self.on_line = on_line or (lambda t, m: None)
        self.on_err = on_err or (lambda e: None)
        self.on_status = on_status or (lambda s: None)
        self.stop_flag = threading.Event()
        self.q = queue.Queue(maxsize=6000)
        # 合并/去重状态
        self.last_text = ''
        self.last_t = 0.0
        self.last_raw = ''
        self.last_partial = ''
        self.pending_text = ''
        self.pending_t = 0.0

    # ---- 音频工具 ----
    def _gain(self, a):
        a = np.asarray(a, dtype=np.float32).reshape(-1)
        rms = float(np.sqrt((a * a).mean()) or 0.0)
        if rms < 1e-6:
            return a
        g = min(12.0, 0.10 / rms)
        return np.clip(a * g, -1.0, 1.0) if g > 1.0 else a

    @staticmethod
    def _rms(a):
        a = np.asarray(a, dtype=np.float32).reshape(-1)
        return float(np.sqrt((a * a).mean()) or 0.0)

    # ---- 识别 + 合并 ----
    def _text_of(self, raw):
        if self.engine is None:
            return ''
        return self.engine.transcribe(self._gain(raw))

    def _accept_final(self, raw):
        if self._rms(raw) < 0.004:     # 静音抑制
            return
        text = self._text_of(raw)
        if not text or looks_like_hallucination(text):
            return
        if text == self.last_raw:      # 连续重复 → 丢
            return
        self.last_raw = text
        now = time.time()

        # ⭐ 文本感知断句：VAD 只会切"停顿"，会切在喘气处。
        #   所以没句号且很短的，先挂起；下一段很快接上就拼成一句再出。
        if self.pending_text and now - self.pending_t >= 1.5:
            self._merge_or_emit(self.pending_text)
            self.pending_text = ''
        if self.pending_text and now - self.pending_t < 2.5:
            text = self.pending_text + text
            self.pending_text = ''
        if (not ends_sentence(text)) and len(text) < 40:
            self.pending_text = text
            self.pending_t = now
            return
        self.pending_text = ''
        self._merge_or_emit(text)

    def _merge_or_emit(self, text):
        now = time.time()
        gap = now - self.last_t
        prev = self.last_text
        # 短碎片 + 紧跟上一句 + 上一句没说完 → 合并
        short = len(text) <= 24 and not ends_sentence(text)
        if prev and gap < 1.6 and not ends_sentence(prev) and short:
            merged = prev + ('，' if not prev.endswith(PUNCT) else '') + text
            self.last_text = merged
            self.last_t = now
            self.on_line(merged, 'merge')
        else:
            self.last_text = text
            self.last_t = now
            self.on_line(text, 'final')

    # ---- 采集 ----
    def _pump(self, path):
        """跟读 ProcessAudioCapture 写出的 WAV：新数据 → float32 单声道 16k → 队列。"""
        off, rate, ch = None, 48000, 2
        pos = 0
        while not self.stop_flag.is_set():
            if off is None:
                off, rate, ch = wav_info(path)
                if off is None:
                    time.sleep(0.05)
                    continue
                pos = off
            try:
                size = os.path.getsize(path)
            except Exception:
                time.sleep(0.05)
                continue
            if size <= pos:
                time.sleep(0.04)
                continue
            try:
                with open(path, 'rb') as f:
                    f.seek(pos)
                    buf = f.read(size - pos)
            except Exception:
                break
            pos += len(buf)
            n = len(buf) // 4
            if n <= 0:
                continue
            a = np.frombuffer(buf[:n * 4], dtype=np.float32)
            if ch > 1:
                a = a[:(a.size // ch) * ch].reshape(-1, ch).mean(axis=1)
            factor = max(1, int(round(rate / 16000.0)))
            if factor > 1:
                m = (a.size // factor) * factor
                if m <= 0:
                    continue
                a = a[:m].reshape(-1, factor).mean(axis=1)
            try:
                self.q.put_nowait(a.astype(np.float32))
            except queue.Full:
                pass

    def _mixer_cb(self, pid):
        def cb(pcm, frames):
            try:
                a = np.frombuffer(pcm, dtype=np.float32)
                if self._pcm_ch > 1:
                    a = a[:(a.size // self._pcm_ch) * self._pcm_ch].reshape(-1, self._pcm_ch).mean(axis=1)
                f = self._pcm_factor
                if f > 1:
                    m = (a.size // f) * f
                    if m <= 0:
                        return
                    a = a[:m].reshape(-1, f).mean(axis=1)
                if a.size:
                    with self._src_lock:
                        self._src[pid] = np.concatenate([self._src.get(pid, np.zeros(0, np.float32)),
                                                         a.astype(np.float32)])
                        self._src_t[pid] = time.time()
            except Exception:
                pass
        return cb

    def _mixer(self):
        """把多个进程的音频合到一起（单进程时就是原样）。

        ⚠⚠ 2026-10-23 修（用户反馈「听漏 / 隔一分钟才识别一句」的真凶）：
          原来这里是 `n = min(len(v) for v in self._src.values())` —— 只要**任意一个**
          勾选的进程这 50ms 没吐数据，整条线就 continue，别的进程的声音也一起被卡住。
          勾两个进程时基本等于半瘫：安静的弹一个、出声的也出不来 ✗
          → 现在只有「最近还在出声」的进程参与凑数；安静超过 0.4 秒的直接按静音处理，
            并且把它攒的旧数据倒掉（不然它恢复出声时会把几分钟前的音频补进来）。
        """
        静音秒 = 0.4
        while not self.stop_flag.is_set():
            time.sleep(0.05)
            now = time.time()
            with self._src_lock:
                if not self._src:
                    continue
                活着 = [k for k in self._src if (now - self._src_t.get(k, 0.0)) < 静音秒]
                if not 活着:
                    # 全都安静了：清空积压，别等它恢复时补一堆旧声音
                    for k in list(self._src):
                        self._src[k] = np.zeros(0, np.float32)
                    continue
                n = min(len(self._src[k]) for k in 活着)
                if n < 800:
                    continue
                parts = [self._src[k][:n] for k in 活着]
                for k in 活着:
                    self._src[k] = self._src[k][n:]
                # 安静的那些：攒的东西不要了
                for k in list(self._src):
                    if k not in 活着:
                        self._src[k] = np.zeros(0, np.float32)
                mixed = parts[0] if len(parts) == 1 else np.sum(np.vstack(parts), axis=0)
            try:
                self.q.put_nowait(np.clip(mixed, -1.0, 1.0).astype(np.float32))
            except queue.Full:
                pass

    def run(self):
        try:
            # 2026-10-26：模型下拉现在有三种（都是本机识别，随便切）：
            #   SenseVoice（默认，228MB）/ SenseVoice 高精度（894MB）/ Paraformer（78MB，最省）
            self.on_status('正在加载模型…')
            self.engine = 建引擎(self.engine_pick, self.lang)
            self.on_status('模型：%s' % getattr(self.engine, '名', ''))
        except Exception as e:
            self.on_err('加载模型失败：%s: %s' % (type(e).__name__, e))
            return
        threading.Thread(target=self._process, daemon=True).start()
        if not self.target_pids:
            self.on_err('没勾选进程')
            return
        caps = []
        try:
            from proctap import ProcessAudioCapture as ProcCap
            self.on_status('正在抓 %d 个进程 …' % len(self.target_pids))
            for pid in self.target_pids:
                c = ProcCap(pid, on_data=self._mixer_cb(pid))
                c.start()
                caps.append(c)
                try:
                    fmt = c.get_format()
                    self._pcm_ch = int(fmt.get('channels', 2))
                    self._pcm_factor = max(1, int(round(int(fmt.get('sample_rate', 48000)) / 16000.0)))
                except Exception:
                    pass
            threading.Thread(target=self._mixer, daemon=True).start()
            self.on_status('')
            while not self.stop_flag.is_set():
                time.sleep(0.1)
        except Exception as e:
            self.on_err('抓取失败：%s: %s' % (type(e).__name__, e))
        finally:
            for c in caps:
                try:
                    c.stop()
                    c.close()
                except Exception:
                    pass

    def _认(self, 块们):
        """把整条「这一句」的音频认成文字。"""
        try:
            a = np.concatenate(块们) if len(块们) > 1 else 块们[0]
            t = self._text_of(a)
        except Exception as e:
            self.on_err(str(e))
            return ''
        t = (t or '').strip()
        # 去掉标点后不到两个字就别当话（静音段落会吐出「그.」这种）
        if not t or looks_like_hallucination(t) or 有内容(t) < 2:
            return ''
        return t

    def _定稿(self, 文本):
        """一条定稿 → 按标点拆成几句，一句一行发出去（不出十几秒一大坨）。"""
        文本 = (文本 or '').strip()
        if not 文本:
            return
        if 文本 == self.last_raw:          # 跟上一句一模一样（音乐循环 / 幻觉）→ 丢
            return
        self.last_raw = 文本
        for 句 in 拆句(文本):
            # 去掉标点后至少两个字：静音时吐出来的「그.」「嗯。」就挡在这里
            # （实测 2026-10-26：没声音的段落连续吐「그.」，长度 2 躲过了老检查）
            if 有内容(句) >= 2 and not looks_like_hallucination(句):
                self.on_line(句, 'final')

    def _process(self):
        """主循环：整条「这一句」的音频一直攒着，每 1.2 秒重认一遍，**看字**决定什么时候落定。

        🔴 0.2.0 重写：以前拿 VAD 切段当断句 —— 可片子里永远有环境音，
           VAD 那句「静音才切」等于没有闸：一段能长到 14~17 秒，而预览只留最近 5 秒，
           前面说过的话既没落定、也没留在屏幕上，**直接丢**。
           ⇒ 现在断句看文字：① 有句末标点 ② 连续几次认出来一模一样 ③ 攒满 10 秒硬切。
           缓冲区**从上一句定稿起一直累积**，不再滑动，所以前面说过的字不会被甩掉。
        """
        块们, 样本数 = [], 0
        上次文本, 相同次数, 上次认 = '', 0, 0.0
        buf_硬 = np.zeros(0, dtype=np.float32)      # 「连续硬切」模式用
        while True:
            # ⚠ 模型跟不上实时时，宁可漏一句，也不要越听越落后：
            #   积压超过约 7 秒就丢掉最老的，只留最近一小段。
            if self.q.qsize() > 150:
                丢 = 0
                while self.q.qsize() > 60:
                    try:
                        self.q.get_nowait()
                        丢 += 1
                    except queue.Empty:
                        break
                if 丢:
                    diag('积压丢弃 %d 块音频（模型跟不上实时，已跳到最近）' % 丢)
            停 = self.stop_flag.is_set()
            try:
                chunk = self.q.get(timeout=0.1)
            except queue.Empty:
                chunk = None
            if 停 and chunk is None:
                # 收尾：还剩半句就先落定，别白白丢掉
                if self.mode != 'chunk' and 样本数:
                    文 = self._认(块们)
                    if 文:
                        self._定稿(文)
                return

            静音 = False
            if chunk is not None:
                chunk = np.asarray(chunk, dtype=np.float32)
                if self.mode == 'chunk':
                    buf_硬 = np.concatenate([buf_硬, chunk])
                    while len(buf_硬) >= self.chunk:
                        piece, buf_硬 = buf_硬[:self.chunk], buf_硬[self.chunk:]
                        try:
                            self._accept_final(piece)
                        except Exception as e:
                            self.on_err(str(e))
                    continue
                块们.append(chunk)
                样本数 += chunk.size
                # VAD 只当「真的安静下来了」的提示（片子里有环境音，基本不会触发）
                self.vad.accept_waveform(self._gain(chunk))
                while not self.vad.empty():
                    self.vad.pop()
                    静音 = True

            if self.mode == 'chunk' or not 样本数:
                continue
            现在 = time.time()
            if 现在 - 上次认 < 认的间隔秒:
                continue
            上次认 = 现在
            文本 = self._认(块们)
            if 文本 and 文本 == 上次文本:
                相同次数 += 1
            elif 文本:
                相同次数 = 1
                上次文本 = 文本
            else:
                相同次数 = 0
            秒 = 样本数 / 16000.0

            该落 = 该定稿(文本, 相同次数, 秒) or (bool(文本) and 静音 and 秒 >= 0.8)
            if 该落:
                if 文本:
                    self._定稿(文本)
                块们, 样本数 = [], 0
                上次文本, 相同次数, self.last_partial = '', 0, ''
            elif 文本 and self.partial and 文本 != self.last_partial and 有内容(文本) >= 2:
                self.last_partial = 文本
                self.on_line(文本, 'partial')

    def stop(self):
        self.stop_flag.set()


BG = '#dcebf3'
PANEL = '#edf5fa'
PANEL2 = '#f8fcfe'
FG = '#304858'
MUTED = '#718797'
ACCENT = '#7faac4'
ACCENT_HOVER = '#6a96b2'
HOVER = '#e2eff6'
BORDER = '#b6cbd8'
TIME_COLOR = '#8295a3'
ERROR_COLOR = '#c0566a'
GREEN = '#2f8f63'


class App:
    def __init__(self, root):
        self.root = root
        self.cap = None
        self.procs = []
        self.n = 0
        root.title('陪看')
        # 窗口大小跟着屏幕走（1920 屏也不会超出；大屏就给得宽一点）
        try:
            屏宽, 屏高 = root.winfo_screenwidth(), root.winfo_screenheight()
        except Exception:
            屏宽, 屏高 = 1920, 1080
        宽 = min(1700, max(1150, 屏宽 - 700))
        高 = min(1010, max(720, 屏高 - 400))
        root.geometry('%dx%d' % (宽, 高))
        root.minsize(1040, 660)
        root.configure(bg=BG)

        style = ttk.Style(root)
        try:
            style.theme_use('clam')
        except Exception:
            pass
        style.configure('TCombobox', fieldbackground=PANEL2, background=PANEL2, foreground=FG,
                        arrowcolor=FG, bordercolor=PANEL2, lightcolor=PANEL2, darkcolor=PANEL2,
                        selectbackground=PANEL2, selectforeground=FG)
        style.map('TCombobox', fieldbackground=[('readonly', PANEL2)])

        # 顶栏
        head = tk.Frame(root, bg=BG)
        head.pack(fill='x', padx=16, pady=(14, 8))
        tk.Label(head, text='陪看', bg=BG, fg=FG, font=('Microsoft YaHei UI', 18, 'bold')).pack(side='left')
        tk.Label(head, text='  陪你看，她替你听', bg=BG, fg=MUTED,
                 font=('Microsoft YaHei UI', 9)).pack(side='left', pady=(6, 0))

        # 控制条
        bar = tk.Frame(root, bg=PANEL)
        bar.pack(fill='x', padx=16, pady=(0, 10), ipady=6)
        # ⭐ 0.2.4：语言和模型都不给选了 —— 语言自动，模型固定用「高精度」那份。
        #   少两个下拉，就不会有人选错。
        tk.Label(bar, text='识别：自动', bg=PANEL, fg=MUTED,
                 font=('Microsoft YaHei UI', 9)).pack(side='left', padx=(12, 6))

        tk.Label(bar, text='模式', bg=PANEL, fg=MUTED).pack(side='left', padx=(8, 4))
        self.mode = DarkOption(bar, ['智能断句', '连续硬切'], width=10)
        self.mode.pack(side='left', pady=8)

        self.pv = tk.BooleanVar(value=True)
        tk.Checkbutton(bar, text='实时预览（会修正）', variable=self.pv, bg=PANEL, fg=MUTED,
                       selectcolor=PANEL2, activebackground=PANEL, activeforeground=FG,
                       font=('Microsoft YaHei UI', 9), bd=0, highlightthickness=0
                       ).pack(side='left', padx=(10, 0), pady=8)

        self.btn_start = tk.Button(bar, text='开始听', command=self.start, bg=ACCENT, fg='white',
                                   relief='flat', font=('Microsoft YaHei UI', 10, 'bold'),
                                   activebackground=ACCENT_HOVER, activeforeground='white', padx=16, pady=4)
        self.btn_start.pack(side='right', padx=(6, 12), pady=6)
        self.btn_stop = tk.Button(bar, text='停止', command=self.stop, bg=PANEL2, fg=FG,
                                  relief='flat', font=('Microsoft YaHei UI', 10),
                                  activebackground=HOVER, activeforeground=FG, padx=14, pady=4,
                                  state='disabled')
        self.btn_stop.pack(side='right', pady=6)
        self.btn_clear = tk.Button(bar, text='清空', command=self.clear, bg=PANEL2, fg=MUTED,
                                   relief='flat', font=('Microsoft YaHei UI', 10),
                                   activebackground=HOVER, activeforeground=FG, padx=12, pady=4)
        self.btn_clear.pack(side='right', padx=(6, 0), pady=6)
        self.btn_ref = tk.Button(bar, text='刷新进程', command=self.refresh, bg=PANEL2, fg=MUTED,
                                 relief='flat', font=('Microsoft YaHei UI', 10),
                                 activebackground=HOVER, activeforeground=FG, padx=12, pady=4)
        self.btn_ref.pack(side='right', padx=(6, 0), pady=6)

        # ⭐ 0.3.0：**框选就在这块面板上做**，不用每次都开设置。
        #   跟设置页那两组一一对应：字幕区（框一下 / 不要）＋ 截图区（框一下 / 整屏）。
        #   ⚠ 这一排必须**单独一行**（直接挂在 root 上）—— 塞进上面那条 bar 里的话，
        #     Tk 会把它填进左右两组按钮中间的剩余空隙，就变成「挤在同一行、还没对齐」✗
        #     （2026-10-27）
        bar2 = tk.Frame(root, bg=PANEL)
        bar2.pack(fill='x', padx=16, pady=(0, 10), ipady=5)
        小 = dict(bg=PANEL2, fg=FG, relief='flat', bd=0, highlightthickness=0,
                  font=('Microsoft YaHei UI', 9), activebackground=HOVER, activeforeground=FG,
                  padx=10, pady=2)
        行头 = dict(bg=PANEL, fg=MUTED, font=('Microsoft YaHei UI', 9))

        tk.Label(bar2, text='字幕区', **行头).pack(side='left', padx=(12, 6))
        self.btn_box_sub = tk.Button(bar2, text='框一下', command=self.框字幕, **小)
        self.btn_box_sub.pack(side='left')
        self.btn_sub_off = tk.Button(bar2, text='不要', command=self.不要字幕, **小)
        self.btn_sub_off.pack(side='left', padx=(6, 0))

        tk.Label(bar2, text='｜', bg=PANEL, fg=BORDER,
                 font=('Microsoft YaHei UI', 9)).pack(side='left', padx=12)

        tk.Label(bar2, text='截图区', **行头).pack(side='left', padx=(0, 6))
        self.btn_box_frame = tk.Button(bar2, text='框一下', command=self.框抽帧, **小)
        self.btn_box_frame.pack(side='left')
        self.btn_frame_full = tk.Button(bar2, text='整屏', command=self.整屏, **小)
        self.btn_frame_full.pack(side='left', padx=(6, 0))

        self.框说明 = tk.Label(bar2, text='', bg=PANEL, fg=MUTED, anchor='w',
                            font=('Microsoft YaHei UI', 8))
        self.框说明.pack(side='left', padx=(14, 0))
        self._上次刷框 = 0.0
        self._刷框说明()

        # 主体
        mid = tk.Frame(root, bg=BG)
        mid.pack(fill='both', expand=True, padx=16, pady=(0, 6))

        left = tk.Frame(mid, bg=PANEL)
        left.pack(side='left', fill='y', padx=(0, 12))
        tk.Label(left, text='正在发声', bg=PANEL, fg=MUTED,
                 font=('Microsoft YaHei UI', 9)).pack(anchor='w', padx=12, pady=(10, 6))
        self.plist = tk.Frame(left, bg=PANEL)
        self.plist.pack(fill='both', expand=True, padx=8, pady=(0, 10))
        self.pchecks = []

        right = tk.Frame(mid, bg=PANEL)
        right.pack(side='left', fill='both', expand=True)
        hd = tk.Frame(right, bg=PANEL)
        hd.pack(fill='x', padx=12, pady=(10, 6))
        tk.Label(hd, text='字幕', bg=PANEL, fg=MUTED, font=('Microsoft YaHei UI', 9)).pack(side='left')
        self.cnt = tk.Label(hd, text='', bg=PANEL, fg=MUTED, font=('Microsoft YaHei UI', 9))
        self.cnt.pack(side='right')
        wrapf = tk.Frame(right, bg=PANEL)
        wrapf.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self.sb = tk.Scrollbar(wrapf, orient='vertical', bg=PANEL2, troughcolor=PANEL,
                               activebackground=BORDER, relief='flat', width=10,
                               borderwidth=0, highlightthickness=0)
        self.sb.pack(side='right', fill='y')
        self.txt = tk.Text(wrapf, bg=PANEL2, fg=FG, relief='flat', wrap='word',
                           font=('Microsoft YaHei UI', 12), insertbackground=FG,
                           borderwidth=0, padx=14, pady=10, yscrollcommand=self.sb.set)
        self.txt.pack(side='left', fill='both', expand=True)
        self.sb.configure(command=self.txt.yview)
        self.txt.configure(state='disabled')
        self.txt.tag_configure('t', foreground=TIME_COLOR, font=('Consolas', 8))
        self.txt.tag_configure('s', foreground=FG, font=('Microsoft YaHei UI', 12))
        # ⭐ 0.3.3：你自己的话（电话那条腿）/ 系统提示，用颜色区分开
        self.txt.tag_configure('phone', foreground='#2f8f63', font=('Microsoft YaHei UI', 12))
        self.txt.tag_configure('sys', foreground=MUTED, font=('Microsoft YaHei UI', 9))

        # 状态栏
        self.status = tk.Label(root, text='未开始', bg=BG, fg=MUTED, anchor='w',
                               font=('Microsoft YaHei UI', 9))
        self.status.pack(fill='x', padx=16, pady=(0, 12))

        self.q = queue.Queue()
        self.live = False
        self.live_from = ''          # 预览那块的起点（折行也能整块替换）
        self.ocr停 = None            # 读屏幕字幕那条腿的停止信号
        self.最后OCR = 0.0           # 上一次读到字幕的时间（听来的句子据此去重）
        self.最近有字幕 = 0.0         # ⭐ 0.4.9：上一次扫描**看到过字**的时间（语音兜底据此让路）
        self.待发 = None             # ⭐ 0.4.9：挂起中的日文字幕（等 2 秒看有没有中文顶上）
        self.帧停 = None             # 抽帧那条腿的停止信号（0.3.0）
        self.最近字幕 = []           # 抽帧配台词用：最近几十句 [{时, 文}]
        self.status_text = ''
        self.refresh()
        self.root.after(250, self.tick)
        self.root.after(8000, self._auto_refresh)

    def _auto_refresh(self):
        self.refresh()
        self.root.after(8000, self._auto_refresh)

    def refresh(self):
        procs, err = list_audio_processes()
        self.procs = procs
        sound = {pid: act for pid, name, act in procs}
        checked = {pid for v, pid, name in self.pchecks if v.get()}
        rows, seen = [], set()
        for t in load_targets():                       # 勾过的：永远留着（勾着）
            pid, name = t.get('pid'), t.get('name', '')
            if pid is None or (pid, name) in seen:
                continue
            seen.add((pid, name))
            rows.append((pid, name, bool(sound.get(pid)), True))
        for pid, name, act in procs:                   # 正在发声的：没勾过也列出来
            if (pid, name) in seen:
                continue
            seen.add((pid, name))
            rows.append((pid, name, act, pid in checked))
        for w in self.plist.winfo_children():
            w.destroy()
        self.pchecks = []
        if err:
            tk.Label(self.plist, text='读不到：' + err, bg=PANEL, fg=ERROR_COLOR, anchor='w').pack(fill='x')
            return
        if not rows:
            tk.Label(self.plist, text='现在没有程序在出声', bg=PANEL, fg=MUTED, anchor='w').pack(fill='x')
            return
        for pid, name, act, on in rows:
            v = tk.BooleanVar(value=on)
            tk.Checkbutton(self.plist, text=('● ' if act else '○ ') + name + '   ' + str(pid),
                           variable=v, bg=PANEL, fg=FG, selectcolor=PANEL2,
                           activebackground=PANEL, activeforeground=FG,
                           font=('Microsoft YaHei UI', 10), anchor='w', bd=0,
                           highlightthickness=0, padx=2).pack(fill='x', anchor='w')
            self.pchecks.append((v, pid, name))

    def clear(self):
        self.txt.configure(state='normal')
        self.txt.delete('1.0', 'end')
        self.txt.configure(state='disabled')
        self.live = False
        self.live_from = ''
        self.n = 0
        self.cnt.configure(text='')

    def 自动开(self):
        """点一下电视就能听 —— 但**只听你勾的那些**，绝不替你勾。

        返回 (开没开, 一句人话)。没勾就**不硬开**，把话说清楚让人知道下一步干嘛。
        ⭐ 0.1.2：以前「没勾就自动把正在出声的全勾上」，不行。
        现在只认两种勾选来源：① 这次勾的；② 上次听的那几个（`save_targets` 记住的）。
        """
        try:
            self.refresh()
        except Exception:
            pass
        已勾 = [name for v, pid, name in self.pchecks if v.get()]
        if not 已勾:
            self.status.configure(text='先在左边勾一个要听的程序（勾一次，下次会自动记住）')
            return False, '先在左边「正在发声」里勾一个要听的程序'
        self.start()
        开 = bool(getattr(self, 'cap', None))
        if 开:
            self.status.configure(text='正在听 %d 个程序：%s（想换，就在左边改勾选）'
                                  % (len(已勾), '、'.join(已勾[:4])))
        return 开, (('正在听：' + '、'.join(已勾[:3])) if 开 else '开不起来')

    def start(self):
        picked = [(pid, name) for v, pid, name in self.pchecks if v.get()]
        if not picked:
            self.status.configure(text='先在左边勾选要听的进程（可多选）')
            return
        if self.cap:
            self.cap.stop()
            self.cap = None
        save_targets([{'pid': p, 'name': n} for p, n in picked])
        # ⚠⚠ 2026-10-23 实测（真语音，6 秒一段）：
        #   Whisper small    认 6 秒要 3.16 秒 → 1.9 倍实时
        #   Whisper turbo    认 6 秒要 10.93 秒 → **0.5 倍实时，永远追不上**（CPU 直接拉满）
        #   而「实时预览」是每 1.2 秒就把最近 5 秒整段再认一遍 ——
        #   对 whisper 等于把管线彻底堵死，一句真正的字幕都出不来。
        #   → 预览只给 SenseVoice 用；别的引擎自动关掉（并给一句提示）。
        # ⭐ 0.2.4：语言固定「自动」（中日英混着看都不出错），模型固定走「高精度」那份；
        #   机器上没下高精度就自动退回 int8 —— 这些都不用再选。
        lang = 'auto'
        mode = 'chunk' if self.mode.get().startswith('连续') else 'vad'
        engine = 'auto'
        预览 = bool(self.pv.get())
        附注 = ''
        self.clear()
        self.cap = Captioner(lang=lang, mode=mode, engine=engine,
                             target_pids=[p for p, _ in picked], partial=预览,
                             on_line=lambda t, m: self._来一句(t, m),
                             on_err=lambda e: self.q.put(('err', e)),
                             on_status=lambda s: self.q.put(('status', s)))
        self.cap.start()
        # ⭐ 0.2.2：屏幕上要是有字幕，就再开一条「读字幕」的腿（比听声音准、也快）
        开字幕 = self._开OCR()
        # ⭐ 0.3.0：时不时抽一帧给她看（带时间点 + 那会儿的台词）
        开抽帧 = self._开抽帧()
        self.btn_stop.configure(state='normal')
        self.btn_start.configure(state='disabled')
        # ⭐ 1.1.6：跟插件说「陪看开了」，它才允许自己开口
        self._通知插件(True)
        self.status_text = '正在听  %s ｜ %s%s%s%s' % ('、'.join(n for _, n in picked),
                                                   self.mode.get(), 附注,
                                                   '｜也在读字幕' if 开字幕 else '',
                                                   '｜也会抽帧给她看' if 开抽帧 else '')
        self.status.configure(text='正在加载模型…')

    def _开OCR(self):
        """框过头就同时读字幕。返回有没有开起来。"""
        try:
            import ocr
        except Exception as e:
            diag('字幕 OCR 没起来：%s' % e)
            return False
        配置 = paths.读配置()
        框 = list(配置.get('ocr_box') or [])
        if not 配置.get('ocr开') or len(框) < 4:
            return False
        if not ocr.就绪():
            self.q.put(('status', '框了字幕区，但少了 OCR 模型 —— 这次先只听声音'))
            return False
        if self.ocr停:
            self.ocr停.set()
        停 = threading.Event()
        self.ocr停 = 停
        self.最后OCR = 0.0

        def 跑():
            认器 = ocr.识别器()
            断 = ocr.断句器()
            先 = True
            while not 停.is_set():
                if not 先:
                    time.sleep(0.3)
                先 = False
                图 = ocr.抓(框)
                if 图 is None:
                    continue
                try:
                    文, _ = 认器.认(图)
                except Exception as e:
                    diag('字幕 OCR 出错：%s' % e)
                    time.sleep(1.0)
                    continue
                if ocr.算字(文) >= 2:
                    self.最近有字幕 = time.time()      # ⭐ 0.4.9：看到字了，听来的那句让路
                好 = 断.喂(文)
                if 好:
                    self.最后OCR = time.time()
                    self.q.put(('line', 好, 'final', 'ocr'))

        threading.Thread(target=跑, daemon=True).start()
        return True

    def _开抽帧(self):
        """时不时抽一帧给她看：随机间隔、本地压好、带时间点和那会儿的台词。

        看番/打游戏时随机抽几帧；2K 原图太大，本地压完再发。
        实测：抓 52ms、压到 1280 宽 45ms（91KB），一分钟一张对看片毫无影响。
        """
        try:
            import frames
        except Exception as e:
            diag('抽帧没起来：%s' % e)
            return False
        配置 = paths.读配置()
        if not 配置.get('抽帧开'):
            return False
        try:
            秒 = float(配置.get('抽帧秒') or 45)
        except Exception:
            秒 = 45.0
        秒 = max(10.0, min(秒, 1800.0))
        if self.帧停:
            self.帧停.set()
        停 = threading.Event()
        self.帧停 = 停
        端口 = int(配置.get('dsh_port') or 8777)
        try:
            屏宽 = self.root.winfo_screenwidth()
            屏高 = self.root.winfo_screenheight()
        except Exception:
            屏宽, 屏高 = 1920, 1080
        # ⭐ 0.2.9：抽帧也能只截「框过的那一块」——跟框字幕同一套操作，
        #   没框就截整屏。
        try:
            框 = [int(v) for v in (配置.get('抽帧框') or [])]
        except Exception:
            框 = []
        # ⭐ 0.3.3：框太小就当没框 —— 手抖画了个 147×41 的框，
        #   之后每张图都是 160×45、932 字节，界面上看着像「截了一张 0KB 的图」。
        if len(框) < 4 or 框[2] < 200 or 框[3] < 120:
            小框 = (len(框) >= 4 and 框[2] >= 16 and 框[3] >= 16)
            try:
                屏宽 = self.root.winfo_screenwidth()
                屏高 = self.root.winfo_screenheight()
            except Exception:
                屏宽, 屏高 = 1920, 1080
            if 小框:
                self.q.put(('sys', '· 抽帧框太小了（%d×%d），这次按整屏截 —— 想只截一块就重新框' % (框[2], 框[3])))
            diag('抽帧：框太小或没框（%s），按整屏 %dx%d' % (框, 屏宽, 屏高))
            框 = [0, 0, 屏宽, 屏高]
        else:
            框 = 框[:4]
        框 = tuple(框)

        def 跑():
            import random
            while not 停.is_set():
                间隔 = max(8.0, 秒 * (0.6 + 0.8 * random.random()))
                睡到 = time.time() + 间隔
                while time.time() < 睡到 and not 停.is_set():
                    time.sleep(0.5)
                if 停.is_set():
                    return
                此刻 = time.time()
                图 = frames.抓(框)
                if 图 is None:
                    continue
                字节, 尺寸 = frames.压(图, 1280, 75)
                路 = frames.存(字节)
                词 = frames.配台词(list(self.最近字幕), 此刻)
                好, 说 = frames.发(端口, 字节, {
                    '时间点': int(此刻 * 1000),
                    '尺寸': '%dx%d' % 尺寸,
                    '台词': [{'差': d, '文': t} for d, t in 词],
                })
                diag('抽帧：%dKB %s（%d 句台词）→ %s｜%s'
                     % (len(字节) // 1024, '%dx%d' % 尺寸, len(词), 'ok' if 好 else '失败', 说[:60]))
                # ⭐ 0.3.3：截了就写一行，发没发出去也写
                #   带上尺寸 —— 只有「0KB」看不出是框太小还是图糊了
                try:
                    大小 = ('%dB' % len(字节)) if len(字节) < 1024 else ('%dKB' % (len(字节) // 1024))
                    尺寸说 = '%dx%d' % 尺寸
                    if 好:
                        self.q.put(('sys', '· 截了一张图（%s，%s，带 %d 句台词）' % (尺寸说, 大小, len(词))))
                    else:
                        self.q.put(('sys', '· 截了图但没发出去（%s，%s）：%s' % (尺寸说, 大小, str(说)[:60])))
                except Exception:
                    pass

        try:
            threading.Thread(target=跑, daemon=True).start()
        except Exception:
            return False
        return True

    # ---------- 0.3.0：在这块面板上直接框选（字幕区 / 抽帧区） ----------
    def 框字幕(self):
        self._框一个('ocr_box', True)

    def 框抽帧(self):
        self._框一个('抽帧框', False)

    def 不要字幕(self):
        """跟设置页那个「不要字幕」一样：关掉读字幕，只听声音。"""
        try:
            c = dict(paths.读配置())
            c['ocr开'] = False
            c.pop('ocr_box', None)
            存上 = paths.写配置(c)
        except Exception as e:
            diag('不要字幕：写配置失败 %s' % e)
            存上 = False
        if not 存上:
            self.status.configure(text='没改成（配置写不进去）')
            return
        if self.ocr停:
            self.ocr停.set()
            self.ocr停 = None
        self._刷框说明()
        self.q.put(('status', '好，不看字幕了，只听声音'))

    def 整屏(self):
        """跟设置页那个「整屏」一样：抽帧改回截整个屏幕。"""
        try:
            c = dict(paths.读配置())
            c.pop('抽帧框', None)
            存上 = paths.写配置(c)
        except Exception as e:
            diag('整屏：写配置失败 %s' % e)
            存上 = False
        if not 存上:
            self.status.configure(text='没改成（配置写不进去）')
            return
        self._刷框说明()
        self.q.put(('status', '截图改回整屏'))
        if self.cap:
            if self.帧停:
                self.帧停.set()
            self._开抽帧()

    def _框一个(self, 键, 是字幕):
        try:
            import ocr
        except Exception as e:
            self.status.configure(text='加载框选失败：' + str(e)[:80])
            return
        if 是字幕 and not ocr.就绪():
            self.status.configure(text='少了 OCR 模型，先装模型再框字幕')
            return
        try:
            self.root.withdraw()          # 先把自己藏起来，别挡着要框的画面
        except Exception:
            pass

        def 好了(框):
            try:
                c = dict(paths.读配置())
                c[键] = [int(v) for v in 框]
                if 是字幕:
                    c['ocr开'] = True
                存上 = paths.写配置(c)
            except Exception as e:
                diag('框选保存失败：%s' % e)
                存上 = False
            try:
                self.root.deiconify()
            except Exception:
                pass
            if not 存上:
                self.status.configure(text='框好了，但没存进配置')
                return
            self._刷框说明()
            if 是字幕:
                self.q.put(('status', '字幕区框好了：%d × %d' % (框[2], 框[3])))
            else:
                self.q.put(('status', '截图区域框好了：%d × %d' % (框[2], 框[3])))
            self._按新框重开(是字幕)

        def 算了():
            try:
                self.root.deiconify()
            except Exception:
                pass

        self.root.after(120, lambda: ocr.开框选(self.root, 好了, 算了))

    def _按新框重开(self, 是字幕):
        """正在听的时候改了框：把那一条腿按新框重开，不用先停再开。"""
        if not self.cap:
            return
        if 是字幕:
            if self.ocr停:
                self.ocr停.set()
            if self._开OCR():
                self.q.put(('status', '字幕区换了，已经按新框在读'))
        else:
            if self.帧停:
                self.帧停.set()
            if self._开抽帧():
                self.q.put(('status', '截图区域换了，抽帧按新框来'))
            else:
                self.q.put(('status', '截图区域存好了（抽帧本身没开，开了就按这块截）'))

    def _刷框说明(self):
        try:
            c = paths.读配置()
        except Exception:
            c = {}
        字幕框 = list(c.get('ocr_box') or [])
        if len(字幕框) >= 4 and c.get('ocr开'):
            字幕说 = '字幕 %d×%d' % (字幕框[2], 字幕框[3])
        else:
            字幕说 = '字幕没框'
        帧框 = list(c.get('抽帧框') or [])
        帧说 = ('抽帧 %d×%d' % (帧框[2], 帧框[3])) if len(帧框) >= 4 else '抽帧整屏'
        if not c.get('抽帧开'):
            帧说 += '（没开）'
        try:
            self.框说明.configure(text='现在：' + 字幕说 + ' ｜ ' + 帧说)
        except Exception:
            pass

    def stop(self):
        if self.帧停:
            self.帧停.set()
            self.帧停 = None
        if self.ocr停:
            self.ocr停.set()
            self.ocr停 = None
        if self.cap:
            self.cap.stop()
            self.cap = None
        self.btn_stop.configure(state='disabled')
        self.btn_start.configure(state='normal')
        self.status.configure(text='已停止')
        # ⭐ 1.1.1：陪看停了要跟插件说一声 —— 不然那边攒着还没发出去的字幕，
        #   会在后面几轮里继续往会话里灌（表现就是「关了陪看还在发字幕」）。
        self._通知插件(False)

    def _通知插件(self, 开着):
        """⭐ 1.1.6：告诉插件「陪看开/停了」—— 它靠这个决定能不能自己开口。"""
        try:
            import json as _j
            import urllib.request as _u
            端口 = int(paths.读配置().get('dsh_port') or 8777)
            体 = _j.dumps({'watch': bool(开着)}, ensure_ascii=False).encode('utf-8')
            请求 = _u.Request('http://127.0.0.1:%d/hands/watch' % 端口, data=体,
                             headers={'Content-Type': 'application/json'})
            无代理 = _u.build_opener(_u.ProxyHandler({}))
            with 无代理.open(请求, timeout=3) as r:
                r.read()
            diag('已告诉插件：陪看%s' % ('开了' if 开着 else '停了（攒着的字幕清掉）'))
        except Exception as e:
            try:
                diag('告诉插件「陪看停了」没成：%s' % e)
            except Exception:
                pass

    def _write(self, text, ev):
        replace = bool(self.live) or (ev == 'merge')
        self.txt.configure(state='normal')
        if replace:
            # 预览那行现在可能很长、会自动折成好几行 —— 按「上一次插入的起点」整块删，
            # 别再拿 'end-2l' 只删一行（那样折行后会留下半截旧字）。
            if self.live_from:
                self.txt.delete(self.live_from, 'end')
            else:
                self.txt.delete('end-2l', 'end-1l')
        self.live_from = self.txt.index('end-1c')
        self.txt.insert('end', time.strftime('%H:%M:%S') + '  ', 't')
        # ⭐ 0.3.3：三色分开 —— 片子字幕（默认）/ 你自己说的（phone）/ 提示（sys）
        标 = {'phone': 'phone', 'sys': 'sys'}.get(ev, 's')
        self.txt.insert('end', text + (' …' if ev == 'partial' else '') + '\n', 标)
        self.live = (ev == 'partial')
        if not self.live:
            self.live_from = ''
        self.txt.see('end')
        self.txt.configure(state='disabled')
        if ev == 'final':
            self.n += 1
            self.cnt.configure(text='共 %d 句' % self.n)

    # ⭐ 每句**定稿**的字幕顺手推给鱼搭子插件（它挂成「白板」，不写进对话历史）
    def _来一句(self, 文, 种):
        """识别线程里来的每一句：显示走队列，**推给插件就在这个线程里推**。

        ⚠ 2026-10-27：
        以前定稿要靠主线程的 tick() 去推；电话和陪看一起开时主线程被两边 ASR 挤住，
        tick 就慢了/停了 → 字幕堆在队列里不发，界面还显示「在听」。
        推的动作本身会把活丢给线程，所以在这里调用是安全的。
        """
        self.q.put(('line', 文, 种, 'asr'))
        if 种 == 'final':
            # ⭐ 0.4.9：语音只是兜底 —— 屏幕上正读着字幕，就不把听来的那句也发出去
            #   语音识别只是**兜底** —— 屏幕上正读着字幕，就不该把听来的这句也发出去。
            #   以前这道检查写死在主线程的 tick 里，可 0.3.3 把推送搬到了这个线程，就绕过去了。
            if time.time() - getattr(self, '最近有字幕', 0.0) < 5.0:
                return
            try:
                self._推字幕(文)
            except Exception as e:
                diag('推字幕失败：%s' % e)

    def _定稿字幕(self, 文):
        """⭐ 0.4.9：中文行立刻发；日文行先挂 2 秒。 —— 这 2 秒里来了中文，就把日文丢掉。
        （日文字幕常常比中文早出来半秒；直接发就成了同一句两条。）
        真的只有日文字幕的片子，挂满 2 秒会在 tick() 里补发。
        """
        文 = str(文 or '').strip()
        if not 文:
            return
        try:
            日 = ocr.是日文(文)
        except Exception:
            日 = False
        if not 日:
            self.待发 = None
            self._推字幕(文)
            return
        self.待发 = {'文': 文, '时': time.time()}

    def _推字幕(self, 文):
        try:
            if not paths.读配置().get('字幕送给大肥鱼', True):
                return
        except Exception:
            pass
        try:
            端口 = int(paths.读配置().get('dsh_port') or 8777)
        except Exception:
            端口 = 8777

        def 跑():
            结果 = ''
            try:
                # ⭐ 带上「多久自己说一句」（秒）——插件那边据此决定要不要开口，
                #    不然设置页里改了它也不知道（以前两边各存一份，改了没反应）。
                搭话秒 = 0
                c = {}
                try:
                    c = paths.读配置()
                    搭话秒 = int(c.get('随机搭话秒') or 0)
                except Exception:
                    搭话秒 = 0
                # ⭐ 2026-10-27：节奏这几个数也一起报上去 ——
                #   设置只留在挂件这边，插件照着这几个数走（两边各存一份最容易改不动）。
                带 = {'text': str(文)[:300], '随机搭话秒': 搭话秒}
                for 键, 默认 in (('搭话最多秒', 0), ('冷却最短秒', 60), ('冷却最长秒', 150), ('安静秒', 8)):
                    try:
                        带[键] = int(c.get(键, 默认) or 默认)
                    except Exception:
                        带[键] = 默认
                体 = _json.dumps(带, ensure_ascii=False).encode('utf-8')
                req = _urllib.Request('http://127.0.0.1:%d/hands/subtitle' % 端口, data=体,
                                      headers={'Content-Type': 'application/json'})
                回 = _本机直连.open(req, timeout=3).read()
                结果 = 'ok ' + str(回[:80])
            except Exception as e:
                结果 = '失败 ' + str(e)[:80]   # 插件没开 / 没绑会话：不打扰看片子，但要留下证据
            _记一句字幕日志(文, 结果)

        try:
            threading.Thread(target=跑, daemon=True).start()
        except Exception:
            pass

    def tick(self):
        try:
            while True:
                kind, payload, *rest = self.q.get_nowait()
                if kind == 'line':
                    ev = rest[0] if rest else 'final'
                    来源 = rest[1] if len(rest) > 1 else 'asr'
                    # ⭐ 0.2.2 / 0.4.9：屏幕上有字幕的时候，听来的那句不显示也不发（字幕更准）
                    if ev == 'final' and 来源 == 'asr' and (time.time() - self.最近有字幕) < 5.0:
                        continue
                    self._write(payload, ev)
                    if ev == 'final':
                        # ⚠ 'asr' 的定稿已经在识别线程里推过了（见 _来一句），这里别再推一遍
                        if 来源 != 'asr':
                            self._定稿字幕(payload)
                        # ⭐ 0.3.0：抽帧要配台词 —— 这一句也记进最近的列表
                        try:
                            self.最近字幕.append({'时': time.time(), '文': str(payload)})
                            if len(self.最近字幕) > 80:
                                del self.最近字幕[:-80]
                        except Exception:
                            pass
                elif kind == 'phone':
                    # ⭐ 0.3.3：电话里说的话也显示在这一页上，不用两头看
                    self._write('你：' + str(payload), 'phone')
                elif kind == 'sys':
                    self._write(str(payload), 'sys')
                elif kind == 'err':
                    diag('陪看出错：' + str(payload))
                    self.status.configure(text='出错：' + payload)
                else:
                    self.status.configure(text=payload if payload else self.status_text)
        except queue.Empty:
            pass
        # ⭐ 0.4.9：日文挂了 2 秒还没中文顶上 → 这片子就是只有日文字幕，把日文发出去
        待 = getattr(self, '待发', None)
        if 待 and time.time() - 待.get('时', 0.0) >= 2.0:
            self.待发 = None
            try:
                self._推字幕(待.get('文') or '')
            except Exception as e:
                diag('补发日文字幕失败：%s' % e)
        # 设置页那边改了框，这边两秒内跟着变（别每 250 毫秒读一次配置文件）
        if time.time() - getattr(self, '_上次刷框', 0) > 2.0:
            self._上次刷框 = time.time()
            try:
                self._刷框说明()
            except Exception:
                pass
        self.root.after(250, self.tick)


if __name__ == '__main__':
    # ⚠ 桌面快捷方式用的是 pythonw（不带黑窗）—— 那样崩了会**什么都看不到**，
    #   所以在这里兜一层：错误写进 diag.log，再弹个框告诉你。
    try:
        root = tk.Tk()
        App(root)
        root.mainloop()
    except Exception:
        import traceback
        错 = traceback.format_exc()
        diag('启动失败：\n' + 错)
        try:
            from tkinter import messagebox
            messagebox.showerror('陪看打不开', '出错了，详细信息已经写进 diag.log：\n\n' + 错[-900:])
        except Exception:
            pass
