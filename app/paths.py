"""路径与配置：打包成 exe 之后也照这个来。

- **资源**（图、图标、内置的语音组件）在程序旁边或打包目录里，只读，跟着程序走；
- **用户的**（配置、模型、日志）在 `%LOCALAPPDATA%\\鱼搭子\\`，可写 ——
  这样程序装在 C 盘、装在 Program Files 都不会「没权限写」。

以前的配置放在 `app/config.json`（里面有开发机才有的绝对路径），
第一次跑新版时会自动搬过来，并且把那几个废键清掉。
"""
import json
import os
import shutil
import sys

应用名 = '鱼搭子'

# 这些键是开发机专用的，迁移时一律丢掉（留着只会指向不存在的路径）
废键 = ('voice_libs', 'asr_models', 'watch_app', 'engine', '引擎', '语言', '模式')


def 程序目录():
    """exe 自己所在的目录（源码跑的时候就是 app 目录）。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def 资源目录():
    """只读资源：图、图标、以及被打包进来的内置模块。"""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', 程序目录())
    return 程序目录()


def 用户目录():
    """可写目录：配置 / 模型 / 日志。"""
    根 = os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Local')
    路 = os.path.join(根, 应用名)
    try:
        os.makedirs(路, exist_ok=True)
    except Exception:
        pass
    return 路


def 配置路径():
    return os.path.join(用户目录(), 'config.json')


def 模型目录():
    路 = os.path.join(用户目录(), 'models')
    try:
        os.makedirs(路, exist_ok=True)
    except Exception:
        pass
    return 路


默认配置 = {
    'dsh_port': 8777,
    'dsh_path': '/hands/say',
    'session': '',
    'mic_device': None,        # 麦克风设备号；None = 跟着系统默认走
    'mic_device_name': '',     # 同时记名字：换电脑 / 插拔后设备号会变，靠名字找回来
    'ball_size': 168,          # ⭐ 100% 时多少像素
    'ui_scale': 1.0,           # 手动倍率（设置里「大一点 / 小一点」）：100% = 上面那个像素
    'ui_scale_base': 0,        # ⚠ 已不用（0.6.1 起）：以前是「当时屏幕缩放」的基准
    '跟随系统缩放': False,      # ⭐ 0.6.1：勾上才会再乘系统缩放（默认纯像素，不会突然变巨大）
    'opacity': 0.95,
    'ball_pos': None,
    'panel_width': 300,
    'panel_size': 560,
    '开机启动': False,
    # ⭐ 0.8.4：气泡整体大小（%，100 = 球径 × 3.24）
    '气泡大小': 92,
    # ⭐ 0.9.2：话太长就在气泡里分页，每页停几秒；最后一页停够「显示秒数」才淡掉
    '气泡换页秒': 4,
    # ⭐ 1.1.0：气泡淡入淡出的帧率（60 / 120）
    '气泡帧率': 60,
    # ⭐ 0.7.0 游戏模式：大肥鱼的话变成弹幕从屏幕上滑过去 + 一块累积的弹幕框
    '弹幕开': True,
    '弹幕速度秒': 6,        # 一条弹幕滑完一屏要几秒（越小越快）
    '弹幕字号': 26,
    '弹幕最多': 10,
    # ⭐ 1.2.7：上一条滑到屏幕的百分之几，才放下一条（越小越快接上）
    # ⭐ 1.4.6：这个数 = 上一条**还剩多少屏幕**时，下一条进来
    #   100 = 上一条刚出来就放下一条（一起涌出来）；50 = 走到屏幕正中；20 = 只剩最后 20%
    '弹幕接续': 50,
    # ⭐ 1.5.3：现在按「句」分条；这个数是「一句多长算太长」的参考线
    #   （超 2 倍才退到逗号切，超 4 倍才硬切）
    '弹幕最多字': 28,
    '弹幕帧率': 60,         # ⭐ 1.0.0：每秒画几帧（60 / 120）
    '弹幕框开': True,
    '弹幕框位置': '右下',    # 左上 / 右上 / 左下 / 右下
    '弹幕框宽': 380,    # ⭐ 1.3.4：锁住弹幕框的位置（全屏打游戏时鼠标到处划，别被拖走）
    '框锁定': True,
    # ⭐ 1.3.8：游戏模式里的两个组合键（她可以自己改）；只在游戏模式里生效
    # ⭐ 1.3.9：「截图怎么送」两档
    #   '每张' = 截一张就说一次（老行为）；'攒着' = 只存着，等她说话时一起给
    '截图送法': '每张',
    '游戏退出键': 'Alt+G',
    '游戏锁键': 'Alt+H',
    # ⭐ 1.5.1：清空「已截图待发」（那些图都不发了）
    '游戏清键': 'Alt+J',
    # ⭐ 1.5.1：跟上一张几乎一样的截图就不发（挂机省）；连续跳这么多张就强制发一张
    '截图去重': True,
    '截图去重保底': 6,
        # 宽（高按那张图的宽高比自动算）
    # ⭐ 1.0.2：截图 —— 游戏模式自己隔一会儿截一张；全局热键按一下截一张（哪个模式都能用）
    '游戏截图开': False,
    # ⭐ 1.1.3：进游戏模式也把麦克风开着（不然游戏里说话没人听）
    '游戏开麦克风': False,
    '游戏截图最短秒': 45,
    '游戏截图最长秒': 120,
    '游戏截图框': None,      # [x, y, 宽, 高]；空 = 整屏
    # ⭐ 1.0.3：按住说话 —— 两个键：只说话 / 说话 + 顺手截一张
    '按住说键': 0,
    '按住说名': '',
    '按住说图键': 0,
    '按住说图名': '',
    '热键截图框': None,      # 「说话 + 带图」那张图截哪块；空 = 整屏
    # ⭐ 0.8.0：飘的弹幕能调位置/颜色/字体；框里字号单独一套
    '弹幕位置': '全屏',      # 全屏 / 上半屏 / 下半屏
    '弹幕颜色': '#ffffff',
    '弹幕描边': '#28283c',
    '弹幕字体': '站酷快乐体',
    '框字号': 20,
    '框字体': '站酷快乐体',
    '回话端口': 8778,          # 大肥鱼的回话往这个口子送进来
    # ⭐ 1.5.9：用哪一档识别模型（int8 / fp32 / paraformer，见文件末尾「语音模型」那节）
    '语音模型': 'int8',
    '陪看带麦克风': True,      # 开陪看时顺手把电话（麦克风）也打开
    '字幕送给大肥鱼': True,    # 陪看的定稿字幕推给 DSH 插件（白板）
    '随机搭话秒': 600,         # ⭐ 陪看时每隔多少秒自己找机会说一句；0 = 只看不说
    # ⭐ 2026-10-27：陪看的节奏都在这里调，插件那边照着这几个数走
    '搭话最多秒': 0,           # 随机间隔的上限；0 = 自动（前一个数×4，至少 120 秒）
    '冷却最短秒': 60,          # 发图 和 自己开口 之间至少隔多久
    '冷却最长秒': 150,         # ……最多隔多久（每次在这两个数之间重掷）
    '安静秒': 8,               # 你多久没说话算「安静」——安静时截图直接发，否则排进字幕里
    '抽帧开': False,           # ⭐ 0.3.0 陪看时「时不时抽一帧」给她看（带时间点 + 台词）
    '抽帧秒': 45,              # 大概多久抽一张（实际会随机浮动 ±40%）
    '抽帧框': [],              # 只截这一块（跟框字幕一样的选法）；空 = 整屏
    'api_回调': '',            # 一般自动填成 http://127.0.0.1:<回话端口>/hands/reply
}


def _规整(原):
    新 = dict(默认配置)
    if isinstance(原, dict):
        for k, v in 原.items():
            if k in 废键:
                continue
            新[k] = v
    # ⭐ 老配置是「分钟」，后来改成「秒」（2026-10-26）
    if isinstance(原, dict) and '随机搭话秒' not in 原 and '随机搭话分钟' in 原:
        try:
            新['随机搭话秒'] = max(0, int(原.get('随机搭话分钟') or 0) * 60)
        except Exception:
            新['随机搭话秒'] = 默认配置['随机搭话秒']
    新.pop('随机搭话分钟', None)
    return 新


def 读配置():
    路 = 配置路径()
    if os.path.exists(路):
        try:
            with open(路, encoding='utf-8-sig') as f:
                return _规整(json.load(f))
        except Exception:
            pass
    # 第一次跑：从老位置搬一次
    旧 = os.path.join(程序目录(), 'config.json')
    if os.path.exists(旧):
        try:
            with open(旧, encoding='utf-8-sig') as f:
                搬 = _规整(json.load(f))
            写配置(搬)
            return 搬
        except Exception:
            pass
    新 = dict(默认配置)
    写配置(新)
    return 新


def 写配置(c):
    """原子写：先写 .tmp 再替换，写一半崩了不会把配置搞坏。"""
    路 = 配置路径()
    临时 = 路 + '.tmp'
    try:
        with open(临时, 'w', encoding='utf-8') as f:
            json.dump(_规整(c), f, ensure_ascii=False, indent=2)
        os.replace(临时, 路)
        return True
    except Exception:
        return False


# ---------- 语音模型 ----------

# ⭐ 1.5.9：识别模型恢复成**三档，能自己选**。以前只剩最大那一份（894MB），
#   普通电脑的 CPU 撑不住，而且没得挑。
#
#   **每一档一个目录，目录里的文件名统一是 model.onnx + tokens.txt** ——
#   接识别器的代码（ear / watch_ui）只认这两个名字，不用管底下是哪一档。
#   目录名叫 paraformer 的那一档走 from_paraformer，其余走 from_sense_voice（见 档引擎()）。
#
#   fp32 那一档就摆在 models\ 根上：老用户已经下好的 894MB 不用再下一遍。
语音模型名 = 'sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17'
paraformer模型名 = 'sherpa-onnx-paraformer-zh-small-2024-03-09'

# ⚠ '仓库' 是完整的「属主/仓库名」—— 少了属主那段，下载地址就是错的（会一直 401）
语音档们 = {
    'int8': {'名': '小（228MB）', '说': '省 CPU，够用',
             '仓库': 'csukuangfj/' + 语音模型名, '远端': 'model.int8.onnx'},
    'fp32': {'名': '大（894MB）', '说': '识别最准，吃 CPU 和内存',
             '仓库': 'csukuangfj/' + 语音模型名, '远端': 'model.onnx'},
    'paraformer': {'名': '最快（78MB）', '说': '最省，但不出标点',
                   '仓库': 'csukuangfj/' + paraformer模型名, '远端': 'model.int8.onnx'},
}
语音档顺序 = ('int8', 'fp32', 'paraformer')
默认语音档 = 'int8'
语音文件 = ('model.onnx', 'tokens.txt')          # 每档目录里都叫这两个名字
内置文件 = ('silero_vad.onnx',)                   # 这个很小，打在程序里


def 当前语音档():
    """配置里选的那一档；配错了（或者老配置没这个键）就当默认那档。"""
    档 = str(读配置().get('语音模型') or '')
    return 档 if 档 in 语音档们 else 默认语音档


def 档目录(档=''):
    """某一档的模型目录。fp32 摆在 models\\ 根上（照顾已经下好的 894MB）。"""
    档 = 档 if 档 in 语音档们 else 当前语音档()
    if 档 == 'fp32':
        return 模型目录()
    return os.path.join(模型目录(), 档)


def 档文件路(档, 名):
    return os.path.join(档目录(档), 名)


def 当前档目录():
    """**实际在用**的那一档的目录。

    ⚠ 跟 档目录() 不是一回事：档目录() 是「配置里选的那一档」（下载/检查就绪要用它），
    这里是「真正拿来说话的那一档」—— 选的那档没装、别的档装了，就用装好的那份，
    不然老用户换默认值之后会变成「没模型、不能说话」。
    """
    return 档目录(可用档() or 当前语音档())


def 档引擎(目录):
    """这个目录里的模型该用哪个识别器建 —— 纯看目录名。"""
    名 = os.path.basename(os.path.normpath(str(目录 or '')))
    return 'paraformer' if 名 == 'paraformer' else 'sense'


def 档就绪(档):
    """这一档能不能用：两个文件都在（大于 1KB 就算下完了），VAD 允许从内置那里借。"""
    if 档 not in 语音档们:
        return False
    目录 = 档目录(档)
    for 名 in 语音文件:
        路 = os.path.join(目录, 名)
        if not os.path.exists(路):
            return False
        if os.path.getsize(路) < 1024:
            return False
    if os.path.exists(os.path.join(目录, 'silero_vad.onnx')):
        return True
    return bool(内置语音('silero_vad.onnx'))


def 可用档(想要的=''):
    """实际拿哪一档去识别：想要的在就用它，不在就看哪一档已经装好。

    ⭐ 默认档换成小的了，但老用户机器上还是原来那份大模型 ——
    不能因为换默认值就变成「没装、不能说话」。
    """
    想 = 想要的 if 想要的 in 语音档们 else 当前语音档()
    if 档就绪(想):
        return 想
    for 档 in 语音档顺序:
        if 档就绪(档):
            return 档
    return ''


def 迁移旧模型():
    """把老版本摆错地方的模型搬到该在的地方（只搬不删）。返回搬没搬。"""
    搬了 = False
    for 老目录名, 档 in (('sensevoice-fp32', 'fp32'), ('paraformer', 'paraformer')):
        老 = os.path.join(模型目录(), 老目录名)
        源 = os.path.join(老, 'model.onnx')
        if not (os.path.exists(源) and os.path.getsize(源) > 1024 * 1024):
            continue
        if 档就绪(档):
            continue
        目标目录 = 档目录(档)
        try:
            os.makedirs(目标目录, exist_ok=True)
            shutil.move(源, os.path.join(目标目录, 'model.onnx'))
            老词表 = os.path.join(老, 'tokens.txt')
            if os.path.exists(老词表):
                shutil.move(老词表, os.path.join(目标目录, 'tokens.txt'))
            搬了 = True
        except Exception:
            pass
    # 0.2.x 的小模型直接摆在 models\ 根上，名字是 model.int8.onnx
    老小 = os.path.join(模型目录(), 'model.int8.onnx')
    if os.path.exists(老小) and not 档就绪('int8'):
        try:
            os.makedirs(档目录('int8'), exist_ok=True)
            shutil.move(老小, os.path.join(档目录('int8'), 'model.onnx'))
            搬了 = True
        except Exception:
            pass
    return 搬了


def 语音路径(名):
    """（老接口）models\\ 根上那个文件 —— 就是 fp32 那一档。"""
    return os.path.join(模型目录(), 名)


def 内置语音(名):
    """内置（打包进来）的语音组件；找不到就返回空。"""
    for 根 in (os.path.join(资源目录(), 'asr_models'), 资源目录()):
        路 = os.path.join(根, 名)
        if os.path.exists(路):
            return 路
    return ''


def silero路(目录=''):
    """VAD 那个小模型在哪：这一档目录里有就用它，没有就从内置那边借（别因为缺它整条路断掉）。"""
    本地 = os.path.join(目录 or 当前档目录(), 'silero_vad.onnx')
    if os.path.exists(本地):
        return 本地
    return 内置语音('silero_vad.onnx') or 本地


def 语音就绪():
    """任何一档能听就算能听。老版本留在别处的模型会先自动搬过来。"""
    try:
        迁移旧模型()
    except Exception:
        pass
    return bool(可用档())


def 补内置语音(档=''):
    """把内置的 silero_vad.onnx 拷到这一档目录里（只拷一次，缺了才拷）。"""
    目录 = 档目录(档)
    目标 = os.path.join(目录, 'silero_vad.onnx')
    if os.path.exists(目标):
        return True
    源 = 内置语音('silero_vad.onnx')
    if not 源:
        return False
    try:
        os.makedirs(目录, exist_ok=True)
        shutil.copyfile(源, 目标)
        return True
    except Exception:
        return False
