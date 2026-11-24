# 「像不像话」过滤的回归：数字不能被当成「同一个字重复」。
# 跑法：python 检查-像不像话.py
import ast
import sys

源 = open('ball.py', encoding='utf-8').read()
树 = ast.parse(源)

# 从 AST 里把 `_像话吗` 这个 staticmethod 单独抠出来跑（不 import 整个 ball，省得拉 Tk/pywin32）
函数 = None
for 节 in ast.walk(树):
    if isinstance(节, ast.FunctionDef) and 节.name == '_像话吗':
        函数 = 节
        break
if 函数 is None:
    print('FAIL  找不到 _像话吗')
    sys.exit(1)

# 它引用了 `鱼搭子.语气词`，给个替身
class 鱼搭子:
    语气词 = '嗯哦啊哈呀吧呢诶喂'

模块 = ast.Module(body=[函数], type_ignores=[])
ast.fix_missing_locations(模块)
命名 = {'鱼搭子': 鱼搭子}
exec(compile(模块, '<像话吗>', 'exec'), 命名)
像话吗 = 命名['_像话吗']
# staticmethod 抠出来还是 staticmethod 对象，取回来
if isinstance(像话吗, staticmethod):
    像话吗 = 像话吗.__func__

要过的 = [
    '把截图上线设置成8000',
    '我说把8万改成8000',
    '我刚才说的是8万张图片，有点太多了，能不能改成8000张啊？',
    '8千8000',
    '这个要不要发两条',
    '嗯',
    '哈哈哈哈哈',
]
要拦的 = [
    '',
    '   ',
    '。。。',
    '！！！！',
    '啊啊啊啊啊',   # 语气词表里没有「啊」，三连同一个字 → 拦
    '└└└└└',
]

坏 = 0
for 文 in 要过的:
    过, 理由 = 像话吗(文)
    if not 过:
        print('FAIL  该发出去的被拦了：%r  → %s' % (文, 理由))
        坏 += 1
for 文 in 要拦的:
    过, 理由 = 像话吗(文)
    if 过:
        print('FAIL  该拦的放过去了：%r' % (文,))
        坏 += 1

if 坏:
    print('挂了 %d 条' % 坏)
    sys.exit(1)
print('PASS  数字句照发（%d 条），纯噪声照拦（%d 条）' % (len(要过的), len(要拦的)))
