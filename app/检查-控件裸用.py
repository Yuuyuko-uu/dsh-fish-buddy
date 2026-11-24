# 静态检查：`self.状态` / `self.流水` 这两个控件只在「电话页」建出来时才有，
# 别的地方碰它们之前必须先确认在不在。跑法：python 检查-控件裸用.py
#
# 为什么要这个：1.7.9 修过 `流水`（issue #11），1.8.2 又冒出 `状态` —— 同一个坑修一半。
import ast
import sys

源 = open('ball.py', encoding='utf-8').read()
树 = ast.parse(源)

# 允许裸用这两个属性的地方：建控件的那一页，和专门包了一层的 _设状态
允许 = {'_建电话页', '_设状态', '_写'}

坏 = []


class 查(ast.NodeVisitor):
    def __init__(self):
        self.当前函数 = ''

    def visit_FunctionDef(self, 节):
        旧 = self.当前函数
        self.当前函数 = 节.name
        self.generic_visit(节)
        self.当前函数 = 旧

    def visit_Attribute(self, 节):
        # self.状态.xxx(...) 这种：取到 self.状态 之后又取了属性
        if isinstance(节.value, ast.Attribute):
            内 = 节.value
            if (
                isinstance(内.value, ast.Name)
                and 内.value.id == 'self'
                and 内.attr in ('状态', '流水')
                and self.当前函数 not in 允许
            ):
                坏.append((节.lineno, self.当前函数, 'self.' + 内.attr + '.' + 节.attr))
        self.generic_visit(节)


查().visit(树)

if 坏:
    print('FAIL  这些地方裸用了只有电话页才有的控件：')
    for 行, 函, 式 in 坏:
        print('       第 %d 行 %s()  %s' % (行, 函, 式))
    sys.exit(1)

print('PASS  self.状态 / self.流水 没有在电话页之外被裸用')

# 再确认 _设状态 真的被所有该用的人用上了
必须走设状态 = ['_处理一条', '_开通话', '_开耳朵_真的', '_挂断']
函数表 = {n.name: n for n in ast.walk(树) if isinstance(n, ast.FunctionDef)}
漏了 = []
for 名 in 必须走设状态:
    f = 函数表.get(名)
    if f is None:
        漏了.append(名 + '（函数都不见了）')
        continue
    有裸 = any(
        isinstance(x, ast.Attribute)
        and isinstance(x.value, ast.Name)
        and x.value.id == 'self'
        and x.attr == '状态'
        for x in ast.walk(f)
    )
    if 有裸:
        漏了.append(名 + '（里面还有直接 self.状态）')

if 漏了:
    print('FAIL  ' + '；'.join(漏了))
    sys.exit(1)
print('PASS  %d 个入口全部经 _设状态 更新状态栏' % len(必须走设状态))
