"""程序这边：配置读写 / 设置页保存 / 模型就绪判断 —— 用临时 LOCALAPPDATA 跑，不碰她真实配置。

跑法： python tests/配置与设置.py
"""
import os
import sys
import tempfile

临时 = tempfile.mkdtemp(prefix='fishbuddy-')
os.environ['LOCALAPPDATA'] = 临时
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app'))

import paths          # noqa: E402
import settings       # noqa: E402
import tkinter as tk  # noqa: E402

结果 = []


def 查(名, 过, 附=''):
    结果.append(bool(过))
    print(('PASS ' if 过 else 'FAIL ') + 名 + ('' if 过 else '  ← ' + str(附)))


查('用户目录落在临时目录里', paths.用户目录().startswith(临时), paths.用户目录())
配置 = paths.读配置()
查('第一次读会给出默认配置（端口 8777）', 配置.get('dsh_port') == 8777, 配置.get('dsh_port'))
查('默认配置里没有开发机专用键', not any(k in 配置 for k in ('voice_libs', 'asr_models', 'watch_app')), list(配置))
查('临时目录里当然还没装语音', paths.语音就绪() is False)

写 = paths.写配置({**配置, 'dsh_port': 8899, 'session': 'session-abc', 'api_回调': 'http://127.0.0.1:8778/hands/reply'})
查('写配置成功', 写 is True)
回 = paths.读配置()
查('端口存住了', 回.get('dsh_port') == 8899, 回.get('dsh_port'))
查('会话存住了', 回.get('session') == 'session-abc', 回.get('session'))
查('回调存住了', 回.get('api_回调') == 'http://127.0.0.1:8778/hands/reply', 回.get('api_回调'))

# 设置页：改三栏 → 点保存 → 文件里真的变了
根 = tk.Tk()
根.withdraw()


class 假应用:
    配置 = dict(回)


应 = 假应用()
页 = settings.设置页(根, 应)
根.update_idletasks()
查('设置页建起来了', 页.框.winfo_exists() == 1)
页.端口.set('8890')
页.会话.set('session-zzz')
页.回调.set('http://127.0.0.1:9999/x')
页._保存配置()
根.update_idletasks()
再回 = paths.读配置()
查('设置页保存后端口改了', 再回.get('dsh_port') == 8890, 再回.get('dsh_port'))
查('设置页保存后会话改了', 再回.get('session') == 'session-zzz', 再回.get('session'))
查('设置页保存后回调改了', 再回.get('api_回调') == 'http://127.0.0.1:9999/x', 再回.get('api_回调'))
查('内存里的配置也跟着改了', 应.配置.get('dsh_port') == 8890, 应.配置.get('dsh_port'))
查('写完会说一句「存好了」', '存好了' in 页.说.get(), 页.说.get())

页.销毁()
根.destroy()

失败 = sum(1 for x in 结果 if not x)
print('\n共 %d 项，失败 %d 项' % (len(结果), 失败))
sys.exit(失败)
