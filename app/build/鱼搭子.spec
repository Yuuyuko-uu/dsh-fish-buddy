# -*- mode: python ; coding: utf-8 -*-
"""鱼搭子 · PyInstaller 打包脚本

用法（在 app 目录里）：
    python -m PyInstaller --noconfirm --clean build/鱼搭子.spec

要点：
- **不打包模型**（230MB 的 SenseVoice 由程序第一次运行自己下），
  只把很小的 silero_vad.onnx 带进去（VAD 用，600KB）。
- 带上陪看要的音频库：sherpa-onnx / proctap / pycaw / sounddevice。
- 单文件、无控制台（pythonw 那种效果）。
"""
import os
import sys

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files

根 = os.path.abspath(SPECPATH)     # spec 就放在 app/build/ 里，往上不去了
if os.path.basename(根).lower() == 'build':
    根 = os.path.dirname(根)
os.chdir(根)

datas = [
    (os.path.join(根, 'assets'), 'assets'),
    (os.path.join(根, 'asr_models'), 'asr_models'),
]
datas += collect_data_files('sherpa_onnx')
datas += collect_data_files('proctap')
datas += collect_data_files('pycaw')

binaries = []
binaries += collect_dynamic_libs('sherpa_onnx')
binaries += collect_dynamic_libs('proctap')
binaries += collect_dynamic_libs('onnxruntime')

hiddenimports = [
    'watch_ui', 'settings', 'models', 'paths', 'version', 'ear',
    'hands', 'hands.voice',
    'sherpa_onnx', 'sounddevice', 'soundcard', 'pycaw', 'pycaw.pycaw',
    'comtypes', 'comtypes.gen', 'proctap', 'onnxruntime',
    'PIL._tkinter_finder',
]

分析 = Analysis(
    [os.path.join(根, 'ball.py')],
    pathex=[根],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=['faster_whisper', 'torch', 'matplotlib', 'scipy', 'pandas'],
    noarchive=False,
)
PYZ = PYZ(分析.pure)
# ⭐ 1.8.4：**从 onefile 改成 onedir**（目录版）。
#
#   为什么改：onefile 每次启动都会把自己解压到 %TEMP%\_MEIxxxxx（约 204MB），
#   **只有「正常退出」才会删那个目录**。DSH 重启、窗口被强关、进程树被带走 —— 都算非正常退出，
#   于是 200MB 永久留在 %TEMP%。实测攒了 266 个目录、54.35 GB（6-27 第一个，10-26~10-30 集中 200 个）。
#
#   onedir 之后：解压只发生**一次**（就是解压 zip 到安装目录那一下），
#   程序启动直接读同目录的 `_internal\`，%TEMP% 里再也不会出现 _MEI。
#
#   代价：发布物从「一个 exe」变成「一个文件夹」，得打包成 zip（插件那边下载完会解开）。
EXE = EXE(
    PYZ,
    分析.scripts,
    [],
    exclude_binaries=True,   # ← onedir：二进制和数据交给下面的 COLLECT
    name='鱼搭子',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 无黑窗
    disable_windowed_traceback=False,
    icon=os.path.join(根, 'assets', '鱼搭子.ico'),
    # ⭐ 1.2.6：**默认以管理员身份启动** —— 游戏（尤其是以管理员权限跑的游戏）
    #   会挡住普通进程读键盘状态，导致按住说话的热键在游戏里彻底失效。
    # ⭐ 1.4.5：**默认不要管理员**。
    #   以前这里是 True —— exe 的清单里写着「需要提升」，于是普通权限的 DSH 去拉起它时
    #   Windows 直接拒绝（ERROR_ELEVATION_REQUIRED），子进程发 'error' 事件；
    #   没接住的话整个 Node 进程（也就是 DSH）会跟着退出。
    #   现在默认普通启动；游戏里按键读不到的人，自己右键「以管理员身份运行」挂件。
    uac_admin=False,
)

COLLECT(
    EXE,
    分析.binaries,
    分析.datas,
    strip=False,
    upx=False,
    name='鱼搭子',
)
