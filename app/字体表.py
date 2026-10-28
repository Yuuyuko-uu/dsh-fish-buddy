"""本机字体：名字 → 文件路径。

不写死字体列表：
    · 扫 %WINDIR%\\Fonts，用 PIL 读每个字体文件的内部名字；
    · 再从注册表补中文名（微软雅黑 / 宋体 / 等线…）；
    · 还有几个常见名字直接对文件（兜底）。
结果缓存，第二次调用瞬间返回。
"""

import os
import threading

_锁 = threading.Lock()
_表 = None

别名 = {
    '微软雅黑': 'msyh.ttc', '微软雅黑 light': 'msyhl.ttc',
    '等线': 'Deng.ttf', '等线 light': 'DengL.ttf',
    '黑体': 'simhei.ttf', '新宋体': 'simsun.ttc', '楷体': 'simkai.ttf',
    '仿宋': 'simfang.ttf', '幼圆': 'SIMYOU.TTF',
}


def _字体目录():
    return os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')


def _读名字(路):
    """一个字体文件里能认出的所有名字。"""
    名们 = []
    try:
        from PIL import ImageFont
        字 = ImageFont.truetype(路, 12)
        族, _风格 = 字.getname()
        if 族:
            名们.append(str(族))
        try:
            名们.append(str(字.font.family))
        except Exception:
            pass
    except Exception:
        pass
    基 = os.path.splitext(os.path.basename(路))[0]
    if 基:
        名们.append(基)
    return 名们


def _注册表的名字():
    """注册表里的字体名（这里才有中文名）。"""
    出 = []
    try:
        import winreg
        键 = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts')
    except Exception:
        return 出
    try:
        数 = winreg.QueryInfoKey(键)[1]
        for i in range(数):
            try:
                名, 值, _ = winreg.EnumValue(键, i)
            except Exception:
                continue
            名 = str(名 or '')
            for 去 in ('(TrueType)', '(OpenType)', '(All res)'):
                名 = 名.replace(去, '')
            for 一 in 名.split('&'):
                一 = 一.strip()
                if 一:
                    出.append((一, str(值 or '')))
    except Exception:
        pass
    finally:
        try:
            键.Close()
        except Exception:
            pass
    return 出


def 全部():
    """{名字: 路径}（第一次扫，之后走缓存）。"""
    global _表
    with _锁:
        if _表 is not None:
            return _表
        表 = {}
        目录 = _字体目录()
        try:
            文件们 = [f for f in os.listdir(目录) if f.lower().endswith(('.ttf', '.ttc', '.otf'))]
        except Exception:
            文件们 = []
        for f in sorted(文件们):
            路 = os.path.join(目录, f)
            for 名 in _读名字(路):
                名 = 名.strip()
                if 名 and 名 not in 表:
                    表[名] = 路
        for 名, 值 in _注册表的名字():
            路 = 值 if os.path.isabs(值) else os.path.join(目录, os.path.basename(值))
            if os.path.isfile(路) and 名 not in 表:
                表[名] = 路
        for 名, 文件 in 别名.items():
            路 = os.path.join(目录, 文件)
            if os.path.isfile(路) and 名 not in 表:
                表[名] = 路
        _表 = 表
        return 表


def 找(名字):
    """名字（或路径 / 文件名）→ 路径；找不到返回 None。"""
    名 = str(名字 or '').strip()
    if not 名:
        return None
    if os.path.isfile(名):
        return 名
    表 = 全部()
    if 名 in 表:
        return 表[名]
    低 = 名.lower()
    for k, v in 表.items():
        if k.lower() == 低:
            return v
    for k, v in 表.items():
        if 低 in k.lower():
            return v
    return None


def 名字们(只中文=True):
    """给设置页用的名字列表。

    ⭐ 0.8.3：默认**只留带中文的名字**
    （Arial / Agency 那堆排下来根本找不到东西）。
    """
    表 = 全部()
    名们 = list(表.keys())
    if 只中文:
        名们 = [n for n in 名们 if any('\u4e00' <= c <= '\u9fff' for c in n)]
    return sorted(名们)
