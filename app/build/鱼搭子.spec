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
EXE = EXE(
    PYZ,
    分析.scripts,
    分析.binaries,
    分析.datas,
    [],
    name='鱼搭子',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 无黑窗
    disable_windowed_traceback=False,
    icon=os.path.join(根, 'assets', '鱼搭子.ico'),
)
