# -*- coding: utf-8 -*-
"""陪看时「时不时抽一帧」给大肥鱼看（0.3.0 起）。

设计要求（2026-10-27 凌晨）：
  · 看番 / 打游戏的时候，**随机抽几帧**发过去，别一直发；
  · 每帧要**带上时间点 + 那会儿对应的字幕**；
  · 2K 屏全屏看，原图一张 10.5MB，肯定不能直接发 —— **本地先压**，而且要快、跟得上。

实测（这台机器、2K 全屏）：
    抓一张 52ms（10.5MB）
    缩到 1280 宽 + JPEG 75 → 38ms、131KB
    缩到 1024 宽 + JPEG 75 → 44ms、 90KB
    ⇒ 抽一帧总共不到 0.1 秒，一分钟抽一张对看片毫无影响。

图先落在 `%LOCALAPPDATA%\\鱼搭子\\frames\\`（只留最近 20 张），同时 POST 给插件。
"""
import base64
import io
import json
import os
import time
import urllib.request

from PIL import Image, ImageDraw, ImageGrab, ImageFont

import paths

本机直连 = urllib.request.build_opener(urllib.request.ProxyHandler({}))
默认宽度 = 1280
默认质量 = 75
最多留几张 = 20


def 目录():
    路 = os.path.join(paths.用户目录(), 'frames')
    try:
        os.makedirs(路, exist_ok=True)
    except Exception:
        pass
    return 路


def 抓(框):
    """框 = (x, y, 宽, 高)。返回 PIL 图；失败返回 None。"""
    try:
        x, y, w, h = [int(v) for v in 框]
        if w < 8 or h < 8:
            return None
        return ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).convert('RGB')
    except Exception:
        return None


def 压(图, 宽=默认宽度, 质=默认质量):
    """压成 JPEG 字节。返回 (字节, 实际尺寸)。"""
    w, h = 图.size
    宽 = max(160, min(int(宽), w))
    高 = max(1, int(round(h * 宽 / float(w))))
    小 = 图 if (宽, 高) == (w, h) else 图.resize((宽, 高), Image.LANCZOS)
    缓 = io.BytesIO()
    小.save(缓, 'JPEG', quality=int(质), optimize=False, subsampling=2)
    return 缓.getvalue(), 小.size


def 存(字节, 前缀='帧'):
    """落一张到 frames 目录，返回路径。只留最近 20 张。"""
    名 = '%s-%s.jpg' % (前缀, time.strftime('%H%M%S'))
    路 = os.path.join(目录(), 名)
    try:
        with open(路, 'wb') as f:
            f.write(字节)
        旧 = sorted((os.path.join(目录(), x) for x in os.listdir(目录()) if x.lower().endswith('.jpg')),
                    key=os.path.getmtime)
        for p in 旧[:-最多留几张]:
            try:
                os.remove(p)
            except Exception:
                pass
    except Exception:
        return ''
    return 路


def 配台词(字幕们, 时, 左右=2):
    """从最近的字幕里挑「这一帧前后」的几句。

    字幕们 = [{'时': 时间戳, '文': 文本}]（按时间排好）。
    返回 [(差几秒, 文本)]：负数 = 帧之前说的，正数 = 帧之后说的。
    取法：**帧那一刻正在说的那句**，往前 2 句、往后 2 句。
    """
    if not 字幕们:
        return []
    到这儿 = -1
    for i, x in enumerate(字幕们):
        if (x.get('时') or 0) <= 时:
            到这儿 = i
    if 到这儿 < 0:
        到这儿 = 0
    起 = max(0, 到这儿 - 左右)
    止 = min(len(字幕们), 到这儿 + 左右 + 1)
    return [(int(round((x.get('时') or 0) - 时)), (x.get('文') or '').strip())
            for x in 字幕们[起:止]]


def 发(端口, 字节, 元=None, 超时=6):
    """POST 给插件。返回 (成不成, 一句人话)。"""
    元 = dict(元 or {})
    元['图片'] = base64.b64encode(字节).decode('ascii')
    try:
        体 = json.dumps(元, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request('http://127.0.0.1:%d/hands/frame' % int(端口), data=体,
                                     headers={'Content-Type': 'application/json'})
        with 本机直连.open(req, timeout=超时) as r:
            return True, r.read()[:120].decode('utf-8', 'replace')
    except Exception as e:
        return False, str(e)[:80]


# ---------- ⭐ 1.6.0：把几张画面拼成一条（竖着排） ----------

def 拼一条(张们, 每格宽=1280, 质量=78):
    """把几张图竖着拼成一根长条，每格左上角写一句标注。

    张们 = [{'路径': '…jpg', '标': '· 3 分钟前'}, …]
    返回 (JPEG 字节, 宽, 高)；一张都读不出来就返回 (b'', 0, 0)。
    """
    图们 = []
    for x in (张们 or []):
        路 = ''
        标 = ''
        if isinstance(x, dict):
            路 = str(x.get('路径') or '')
            标 = str(x.get('标') or '')
        elif x:
            路 = str(x)
        try:
            if not 路 or not os.path.exists(路):
                continue
            图 = Image.open(路).convert('RGB')
            if 图.width != 每格宽:
                高 = max(1, int(round(图.height * 每格宽 / float(图.width))))
                图 = 图.resize((每格宽, 高), Image.LANCZOS)
            图们.append((图, 标))
        except Exception:
            continue
    if not 图们:
        return b'', 0, 0
    字号 = max(16, int(round(每格宽 / 46.0)))
    字体 = None
    for 名字 in ('msyh.ttc', 'simhei.ttf', 'simsun.ttc'):
        try:
            字体 = ImageFont.truetype(os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts', 名字), 字号)
            break
        except Exception:
            字体 = None
    if 字体 is None:
        try:
            字体 = ImageFont.load_default()
        except Exception:
            字体 = None
    总高 = sum(图.height for 图, _ in 图们)
    条 = Image.new('RGB', (每格宽, 总高), 'black')
    y = 0
    for 图, 标 in 图们:
        条.paste(图, (0, y))
        if 标 and 字体 is not None:
            画 = ImageDraw.Draw(条, 'RGBA')
            框 = 画.textbbox((0, 0), 标, font=字体)
            宽标 = (框[2] - 框[0]) if 框 else 0
            高标 = (框[3] - 框[1]) if 框 else 字号
            画.rectangle([0, y, min(每格宽, 宽标 + 字号), y + 高标 + 字号 * 0.7], fill=(0, 0, 0, 150))
            画.text((字号 * 0.5, y + 字号 * 0.25), 标, font=字体, fill=(255, 255, 255, 255))
        y += 图.height
    缓 = io.BytesIO()
    条.save(缓, 'JPEG', quality=int(质量), optimize=False, subsampling=2)
    return 缓.getvalue(), 条.width, 条.height
