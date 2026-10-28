"""设置页：分页的，不再堆成一长条。

左列点哪页就显示哪页：**语音 / 陪看 / 游戏 / 连接 / 桌面 / 关于**；
每一页都能上下滚（鼠标滚轮也行），窗口拉大拉小都跟着变。

1) 语音（电话和陪看共用一套，只装**一种**模型：SenseVoice）+ 麦克风
2) 连接（端口 / 会话 id / 回话递回）
3) 陪看（字幕送不送 / 要不要带麦克风 / 多久自己说一句）
4) 桌面（快捷方式 / 开机就浮出来）
5) 关于（版本、模型放哪、配置放哪）

界面这块只读配置、只写配置；真正干活（下载、建快捷方式）都在别的地方。
"""
import os
import subprocess
import sys
import tkinter as tk

import models
import paths
import version

淡底 = '#dcebf3'
淡卡 = '#edf5fa'
淡线 = '#b6cbd8'
字深 = '#304858'
字次 = '#718797'
绿 = '#2f8f63'
红 = '#c0566a'
蓝 = '#2f7fb8'

字号 = 9
字标 = 10


def 建桌面快捷方式(应用名='鱼搭子', 目标=None, 参数='', 图标=''):
    """在桌面放一个快捷方式；打包后指 exe，源码跑的时候指 pythonw + ball.py。"""
    桌面 = os.path.join(os.path.expanduser('~'), 'Desktop')
    if not os.path.isdir(桌面):
        桌面 = os.path.join(os.environ.get('USERPROFILE', ''), 'Desktop')
    快捷 = os.path.join(桌面, 应用名 + '.lnk')
    目标 = 目标 or sys.executable
    脚本 = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
        "$s.TargetPath='{exe}';$s.Arguments='{args}';$s.WorkingDirectory='{wd}';"
        "{ico}$s.Save()"
    ).format(
        lnk=快捷.replace("'", "''"),
        exe=目标.replace("'", "''"),
        args=参数.replace("'", "''"),
        wd=paths.程序目录().replace("'", "''"),
        ico=("$s.IconLocation='%s';" % 图标.replace("'", "''")) if 图标 else '',
    )
    try:
        完成 = subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', 脚本],
            capture_output=True, timeout=25, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        return (完成.returncode == 0 and os.path.exists(快捷)), 快捷
    except Exception as e:
        return False, str(e)


def 放启动项(应用名='鱼搭子'):
    """放到「启动」文件夹里 —— 开机就浮出来（不是注册表，卸载就是删这个文件）。"""
    启动 = os.path.join(os.environ.get('APPDATA', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
    if not os.path.isdir(启动):
        return False, '找不到「启动」文件夹'
    快捷 = os.path.join(启动, 应用名 + '.lnk')
    桌面快捷, _ = 建桌面快捷方式(应用名, 图标=os.path.join(paths.资源目录(), 'assets', '鱼搭子.ico'))
    if not 桌面快捷:
        return False, '快捷方式没建出来'
    import shutil
    try:
        shutil.copyfile(os.path.join(os.path.expanduser('~'), 'Desktop', 应用名 + '.lnk'), 快捷)
        return True, 快捷
    except Exception as e:
        return False, str(e)


class 设置页:
    """分页设置：左列点页签，右边一页一页看，每页都能滚。"""

    页名 = ('语音', '陪看', '游戏', '全局', '连接', '关于')

    def __init__(self, 父, 应用):
        self.父 = 父
        self.应用 = 应用
        self.配置 = dict(应用.配置)
        self.下载 = models.一下载器()
        self.说 = tk.StringVar(value='')
        self.框 = tk.Frame(父, bg=淡底)
        self.页们 = {}          # 页名 -> (外套, 内容框)
        self.按钮们 = {}
        self.画们 = []          # 每页那个 Canvas（自测要看有没有滚）
        self.当前 = ''
        self._建()

    # ---------- 外壳 ----------
    def _建(self):
        self.框.pack(fill='both', expand=True)

        顶 = tk.Frame(self.框, bg=淡底)
        顶.pack(fill='x', padx=12, pady=(8, 2))
        tk.Label(顶, text='鱼搭子', bg=淡底, fg=字深, anchor='w',
                 font=('Microsoft YaHei UI', 13, 'bold')).pack(side='left')
        tk.Label(顶, text='v' + version.版本号, bg=淡底, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left', padx=(8, 0), pady=(5, 0))
        tk.Label(顶, text='点左边一项，改那一项', bg=淡底, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='right', pady=(5, 0))

        身 = tk.Frame(self.框, bg=淡底)
        身.pack(fill='both', expand=True, padx=(8, 10), pady=(4, 0))

        左 = tk.Frame(身, bg=淡底)
        左.pack(side='left', fill='y', padx=(0, 8), pady=(2, 0))
        self.右 = tk.Frame(身, bg=淡底)
        self.右.pack(side='left', fill='both', expand=True)

        for 名 in self.页名:
            b = tk.Button(左, text=名, command=lambda n=名: self._切(n),
                          bg=淡底, fg=字深, relief='flat', anchor='w', padx=12, pady=4,
                          activebackground=淡卡, activeforeground=字深,
                          font=('Microsoft YaHei UI', 字标), width=5)
            b.pack(fill='x', pady=1)
            self.按钮们[名] = b

        self._建语音()
        self._建陪看()
        self._建游戏()
        self._建全局()
        self._建连接()
        self._建关于()

        self.说标签 = tk.Label(self.框, textvariable=self.说, bg=淡底, fg=字次, anchor='w',
                              font=('Microsoft YaHei UI', 8), wraplength=520, justify='left')
        self.说标签.pack(fill='x', padx=12, pady=(2, 8))

        self._切('语音')
        self._刷语音状态()
        self._刷麦克风()
        self._轮询()

    def _切(self, 名):
        for 外套, _ in self.页们.values():
            外套.pack_forget()
        self.页们[名][0].pack(fill='both', expand=True)
        for k, b in self.按钮们.items():
            b.configure(bg=(淡卡 if k == 名 else 淡底), fg=(蓝 if k == 名 else 字深))
        self.当前 = 名
        # ⭐ 0.6.3：没有滚动条了，滚轮就是唯一的滚法 —— 挂到整窗上，鼠标在哪个控件上都能滚
        try:
            画 = self.画们[self.页名.index(名)]
            self.框.bind_all('<MouseWheel>', lambda e, c=画: c.yview_scroll(-1 * int(getattr(e, 'delta', 0) / 120), 'units'))
        except Exception:
            pass

    def _新页(self, 名):
        """一页 = 一个能上下滚的容器（内容比窗口高也能看全）。

        ⭐ 0.6.3：**不画滚动条**了 —— 滚轮 / 触控板照样能滚。
        """
        外套 = tk.Frame(self.右, bg=淡底)
        画 = tk.Canvas(外套, bg=淡底, highlightthickness=0, bd=0)
        画.pack(side='left', fill='both', expand=True)
        内 = tk.Frame(画, bg=淡底)
        窗 = 画.create_window((0, 0), window=内, anchor='nw')

        def 修(*_):
            try:
                画.configure(scrollregion=画.bbox('all'))
            except Exception:
                pass

        内.bind('<Configure>', 修)
        画.bind('<Configure>', lambda e: (画.itemconfigure(窗, width=e.width), 修()))

        def 滚(e):
            try:
                画.yview_scroll(-1 * int(getattr(e, 'delta', 0) / 120), 'units')
            except Exception:
                pass

        # 鼠标在页上滚 = 滚这一页（Tk 不会把滚轮事件转给父控件，只能进出时挂/摘）
        画.bind('<Enter>', lambda e: 画.bind_all('<MouseWheel>', 滚))
        画.bind('<Leave>', lambda e: 画.unbind_all('<MouseWheel>'))

        self.页们[名] = (外套, 内)
        self.画们.append(画)
        return 内

    def _标题(self, 父, 文):
        tk.Label(父, text=文, bg=淡底, fg=字深, anchor='w', justify='left', wraplength=460,
                 font=('Microsoft YaHei UI', 字标, 'bold')).pack(fill='x', pady=(10, 4))

    def _卡(self, 父):
        卡 = tk.Frame(父, bg=淡卡, padx=10, pady=8)
        卡.pack(fill='x', pady=(0, 6))
        return 卡

    # ---------- 1 语音 ----------
    def _建语音(self):
        框 = self._新页('语音')
        self._标题(框, '语音')
        卡 = self._卡(框)
        self.语音状态 = tk.Label(卡, text='', bg=淡卡, fg=字次, anchor='w', justify='left',
                                 wraplength=430, font=('Microsoft YaHei UI', 字号))
        self.语音状态.pack(fill='x')
        self.进度条 = tk.Canvas(卡, height=8, bg='#d5e3ee', highlightthickness=0, bd=0)
        self.进度条.pack(fill='x', pady=(6, 4))
        self.进度件 = self.进度条.create_rectangle(0, 0, 0, 8, fill=蓝, width=0)
        self.语音说明 = tk.Label(卡, text='', bg=淡卡, fg=字次, anchor='w', justify='left',
                                 wraplength=430, font=('Microsoft YaHei UI', 8))
        self.语音说明.pack(fill='x')
        行 = tk.Frame(卡, bg=淡卡)
        行.pack(fill='x', pady=(8, 0))
        self.装钮 = tk.Button(行, text='装语音（约 240MB，只下一次）', command=self._点装,
                            bg=蓝, fg='#ffffff', relief='flat', font=('Microsoft YaHei UI', 字号), pady=4)
        self.装钮.pack(side='left')
        self.停钮 = tk.Button(行, text='停', command=self._点停,
                            bg='#cbdae5', fg=字深, relief='flat', font=('Microsoft YaHei UI', 字号), pady=4)
        self.停钮.pack(side='left', padx=(8, 0))
        # ⭐ 麦克风：默认跟着系统走；别人的机器上系统默认常常不是他想用的那只
        卡麦 = self._卡(框)
        麦头 = tk.Frame(卡麦, bg=淡卡)
        麦头.pack(fill='x')
        tk.Label(麦头, text='麦克风（电话用哪只）', bg=淡卡, fg=字深, anchor='w',
                 font=('Microsoft YaHei UI', 字标, 'bold')).pack(side='left')
        tk.Button(麦头, text='刷新', command=self._刷麦克风, bg='#cbdae5', fg=字深,
                  relief='flat', font=('Microsoft YaHei UI', 8), pady=1).pack(side='right')
        行麦 = tk.Frame(卡麦, bg=淡卡)
        行麦.pack(fill='x', pady=(6, 0))
        self.麦表 = {}
        self.麦选 = tk.StringVar(value='（系统默认）')
        self.麦框 = tk.OptionMenu(行麦, self.麦选, '（系统默认）')
        self.麦框.configure(bg='#ffffff', fg=字深, activebackground='#e8f1f7',
                            relief='flat', anchor='w', highlightthickness=1,
                            highlightbackground=淡线, font=('Microsoft YaHei UI', 字号))
        try:
            self.麦框['menu'].configure(bg='#ffffff', fg=字深,
                                       font=('Microsoft YaHei UI', 字号))
        except Exception:
            pass
        self.麦框.pack(side='left', fill='x', expand=True, ipady=1)
        self.麦说明 = tk.Label(卡麦, text='', bg=淡卡, fg=字次, anchor='w', justify='left',
                             wraplength=430, font=('Microsoft YaHei UI', 8))
        self.麦说明.pack(fill='x', pady=(4, 0))

        # ⭐ 0.5.0：说完之后安静多久才算一句
        卡断 = self._卡(框)
        tk.Label(卡断, text='怎么算「一句话说完」', bg=淡卡, fg=字深, anchor='w',
                 font=('Microsoft YaHei UI', 字标, 'bold')).pack(fill='x')
        行断 = tk.Frame(卡断, bg=淡卡)
        行断.pack(fill='x', pady=(6, 0))
        tk.Label(行断, text='安静', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 字号)).pack(side='left')
        self.静音秒 = tk.StringVar(value=str(self.配置.get('断句静音秒', 2.0)))
        框静 = tk.Entry(行断, textvariable=self.静音秒, width=5, bg='#ffffff', relief='flat',
                       font=('Microsoft YaHei UI', 字号), highlightthickness=1,
                       highlightbackground=淡线)
        框静.pack(side='left', padx=6, ipady=3)
        tk.Label(行断, text='秒不动，就算这句说完了', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 字号)).pack(side='left')
        self.断已存 = tk.Label(行断, text='', bg=淡卡, fg='#3f7a4f',
                              font=('Microsoft YaHei UI', 9))
        self.断已存.pack(side='left', padx=(8, 0))
        框静.bind('<Return>', lambda e: (self._存语音(), self._闪存好(self.断已存), 'break')[-1])
        框静.bind('<FocusOut>', lambda e: self._存语音())
        框静.bind('<KeyRelease>', lambda e: self._排存(self.断已存, self._存语音))
        tk.Label(卡断, text='想事情、换口气停一两秒，都还算同一句；开小了会一句话被切成两半。'
                          '电话和陪看里「听声音」都用这个数（0.4～8 秒）。',
                 bg=淡卡, fg=字次, anchor='w', justify='left', wraplength=430,
                 font=('Microsoft YaHei UI', 8)).pack(fill='x', pady=(6, 0))

    # ---------- 2 连接 ----------
    def _建连接(self):
        框 = self._新页('连接')
        self._标题(框, '接到哪间会话')
        卡 = self._卡(框)
        self.端口 = self._输入(卡, '端口', str(self.配置.get('dsh_port', 8777)), 100)
        self.会话 = self._输入(卡, '会话 id', str(self.配置.get('session', '')), 240)
        self.回调 = self._输入(卡, '回话递回', str(self.配置.get('api_回调', '')), 240)
        tk.Label(卡, text='会话 id 可以留空：留空时由 DSH 那边绑定的会话决定。',
                 bg=淡卡, fg=字次, anchor='w', justify='left', wraplength=430,
                 font=('Microsoft YaHei UI', 8)).pack(fill='x')
        # ⭐ 0.1.3：改完离开输入框 / 按回车就存，不用再找保存按钮
        for 变 in (self.端口, self.会话, self.回调):
            try:
                变.trace_add('write', lambda *a: self._存连接_去抖())
            except Exception:
                pass

        卡2 = self._卡(框)
        tk.Label(卡2, text='回话接收', bg=淡卡, fg=字深, anchor='w',
                 font=('Microsoft YaHei UI', 字标, 'bold')).pack(fill='x')
        口 = getattr(self.应用, '回话口', None)
        开 = bool(口 and 口.状态.get('起没起'))
        址 = 口.地址() if 口 else ('http://127.0.0.1:%s/hands/reply' % (self.配置.get('回话端口') or 8778))
        tk.Label(卡2, text=('● 开着' if 开 else '○ 没开'), bg=淡卡,
                 fg=(绿 if 开 else 红), anchor='w', font=('Microsoft YaHei UI', 8)).pack(fill='x')
        tk.Label(卡2, text=址, bg=淡卡, fg=字次, anchor='w', justify='left', wraplength=430,
                 font=('Consolas', 8)).pack(fill='x', pady=(0, 4))
        tk.Button(卡2, text='用这个地址填进「回话递回」', command=self._填回话地址, bg='#cbdae5', fg=字深,
                  relief='flat', font=('Microsoft YaHei UI', 8), pady=2).pack(anchor='w')

        行 = tk.Frame(框, bg=淡底)
        行.pack(fill='x', pady=(4, 10))
        tk.Button(行, text='立即保存', command=self._保存配置, bg=蓝, fg='#ffffff', relief='flat',
                  font=('Microsoft YaHei UI', 字标), pady=4, padx=18).pack(side='left')
        tk.Label(行, text='　改动会自动保存，这个按钮只是兜底', bg=淡底, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')

    # ---------- 3 陪看 ----------
    def _建陪看(self):
        框 = self._新页('陪看')
        self._标题(框, '陪看')
        卡 = self._卡(框)
        self.字幕勾 = tk.BooleanVar(value=bool(self.配置.get('字幕送给大肥鱼', True)))
        self.麦克风勾 = tk.BooleanVar(value=bool(self.配置.get('陪看带麦克风', True)))
        tk.Checkbutton(卡, text='字幕也送给她', variable=self.字幕勾,
                       command=self._存陪看, bg=淡卡, fg=字深, activebackground=淡卡,
                       selectcolor=淡卡, anchor='w', font=('Microsoft YaHei UI', 字号)).pack(fill='x')
        tk.Checkbutton(卡, text='开陪看时，顺手把电话（麦克风）也打开', variable=self.麦克风勾,
                       command=self._存陪看, bg=淡卡, fg=字深, activebackground=淡卡,
                       selectcolor=淡卡, anchor='w', font=('Microsoft YaHei UI', 字号)).pack(fill='x')
        行3 = tk.Frame(卡, bg=淡卡)
        行3.pack(fill='x', pady=(8, 0))
        tk.Label(行3, text='多久让她自己说一句', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 字号)).pack(side='left')
        self.搭话秒 = tk.StringVar(value=str(self.配置.get('随机搭话秒', 600)))
        框2 = tk.Entry(行3, textvariable=self.搭话秒, width=6, bg='#ffffff', relief='flat',
                      font=('Microsoft YaHei UI', 字号), highlightthickness=1, highlightbackground=淡线)
        框2.pack(side='left', padx=(6, 4), ipady=2)
        tk.Label(行3, text='～', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 字号)).pack(side='left', padx=(0, 4))
        # ⭐ 0.3.9：只留这一个数 —— 下限～上限，随机。
        #   发图 和 自己开口 共用这一个区间，不再另设冷却/安静那几项。
        self.搭话上限 = tk.StringVar(value=str(self.配置.get('搭话最多秒') or 120))
        框2b = tk.Entry(行3, textvariable=self.搭话上限, width=6, bg='#ffffff', relief='flat',
                        font=('Microsoft YaHei UI', 字号), highlightthickness=1, highlightbackground=淡线)
        框2b.pack(side='left', padx=(0, 4), ipady=2)
        tk.Label(行3, text='秒之间随机', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        self.搭话提示 = tk.Label(行3, text='', bg=淡卡, fg='#2f8f63',
                              font=('Microsoft YaHei UI', 8))
        self.搭话提示.pack(side='left', padx=(8, 0))
        self._秒框接上(框2, self.搭话提示)
        self._秒框接上(框2b, self.搭话提示)

        # ⭐ 0.3.9：节奏只要一个数就够了 —— 「多久让它说一句」的区间。
        #   截图 和 自己开口 共用它（谁刚发过，下一次就在这个区间里重掷），
        #   「多久算安静」固定 8 秒，不进设置页（少一个看不懂的旋钮）。

        卡2 = self._卡(框)
        tk.Label(卡2, text='点那颗电视就能开始听：会自动挑「正在出声」的程序。',
                 bg=淡卡, fg=字次, anchor='w', justify='left', wraplength=430,
                 font=('Microsoft YaHei UI', 8)).pack(fill='x', pady=(0, 2))

        # ---------- 陪看：时不时抽一帧给她看（0.3.0） ----------
        卡4 = self._卡(框)
        self.抽帧勾 = tk.BooleanVar(value=bool(self.配置.get('抽帧开')))
        tk.Checkbutton(卡4, text='时不时抽一帧给她看（带时间点和那会儿的台词）', variable=self.抽帧勾,
                       command=self._存陪看, bg=淡卡, fg=字深, activebackground=淡卡,
                       selectcolor=淡卡, anchor='w', font=('Microsoft YaHei UI', 字号)).pack(fill='x')
        行4 = tk.Frame(卡4, bg=淡卡)
        行4.pack(fill='x', pady=(6, 0))
        tk.Label(行4, text='大概多久抽一张', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 字号)).pack(side='left')
        self.抽帧秒 = tk.StringVar(value=str(self.配置.get('抽帧秒', 45)))
        框4 = tk.Entry(行4, textvariable=self.抽帧秒, width=6, bg='#ffffff', relief='flat',
                      font=('Microsoft YaHei UI', 字号), highlightthickness=1, highlightbackground=淡线)
        框4.pack(side='left', padx=(6, 4), ipady=2)
        tk.Label(行4, text='秒（实际会随机早一点 / 晚一点）', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        self.抽帧提示 = tk.Label(行4, text='', bg=淡卡, fg='#2f8f63',
                              font=('Microsoft YaHei UI', 8))
        self.抽帧提示.pack(side='left', padx=(8, 0))
        self._秒框接上(框4, self.抽帧提示)
        tk.Label(卡4, text='画面在本地先压过再发（2K 一帧约 90KB），不会一帧一帧地刷。',
                 bg=淡卡, fg=字次, anchor='w', justify='left', wraplength=430,
                 font=('Microsoft YaHei UI', 8)).pack(fill='x', pady=(4, 0))
        行5 = tk.Frame(卡4, bg=淡卡)
        行5.pack(fill='x', pady=(6, 0))
        tk.Button(行5, text='框一下只截哪一块', command=self._框抽帧, bg='#cbdae5', fg=字深, relief='flat',
                  font=('Microsoft YaHei UI', 字号), pady=3).pack(side='left')
        tk.Button(行5, text='整屏', command=self._清抽帧框, bg='#e7eef4', fg=字次, relief='flat',
                  font=('Microsoft YaHei UI', 8), pady=3).pack(side='left', padx=(6, 0))
        self.抽帧框说 = tk.Label(卡4, text='', bg=淡卡, fg=字次, anchor='w', justify='left',
                              wraplength=430, font=('Microsoft YaHei UI', 8))
        self.抽帧框说.pack(fill='x', pady=(4, 0))
        self._刷抽帧框说明()


        卡3 = self._卡(框)
        tk.Label(卡3, text='读屏幕上的字幕（比听声音准、也快）', bg=淡卡, fg=字深, anchor='w',
                 font=('Microsoft YaHei UI', 字号, 'bold')).pack(fill='x')
        tk.Label(卡3,
                 text='框一次**字幕那一行**（松手框就消失，不会一直挡在你屏幕上）。\n'
                      '之后陪看就优先读它：框里有字就用字幕，框里连续没字才退回听声音。',
                 bg=淡卡, fg=字次, anchor='w', justify='left', wraplength=430,
                 font=('Microsoft YaHei UI', 8)).pack(fill='x', pady=(2, 6))
        行 = tk.Frame(卡3, bg=淡卡)
        行.pack(fill='x')
        tk.Button(行, text='框一下字幕', command=self._框字幕, bg='#cbdae5', fg=字深, relief='flat',
                  font=('Microsoft YaHei UI', 字号), pady=3).pack(side='left')
        tk.Button(行, text='不要字幕', command=self._清字幕框, bg='#e7eef4', fg=字次, relief='flat',
                  font=('Microsoft YaHei UI', 8), pady=3).pack(side='left', padx=(6, 0))
        self.字幕框说 = tk.Label(卡3, text='', bg=淡卡, fg=字次, anchor='w', justify='left',
                                wraplength=430, font=('Microsoft YaHei UI', 8))
        self.字幕框说.pack(fill='x', pady=(4, 0))
        self._刷字幕框说明()

    def _刷抽帧框说明(self):
        框 = list(self.配置.get('抽帧框') or [])
        try:
            if len(框) < 4:
                self.抽帧框说.configure(text='现在截整屏。想只截画面那一块，就点「框一下只截哪一块」。')
            else:
                self.抽帧框说.configure(text='只截这一块：(%d, %d)，%d × %d。想改就再框一次。'
                                        % (框[0], 框[1], 框[2], 框[3]))
        except Exception:
            pass

    def _框抽帧(self):
        try:
            import ocr
        except Exception as e:
            self.抽帧框说.configure(text='⚠ 加载框选失败：' + str(e)[:80])
            return
        根 = self.应用.根
        try:
            根.withdraw()
        except Exception:
            pass

        def 好了(框):
            c = dict(paths.读配置() or {})
            c['抽帧框'] = [int(v) for v in 框]
            if paths.写配置(c):
                self.应用.配置.update(c)
                self.配置.update(c)
            self._刷抽帧框说明()
            self.说.set('截图区域框好了：%d × %d' % (框[2], 框[3]))
            try:
                根.deiconify()
            except Exception:
                pass

        def 算了():
            try:
                根.deiconify()
            except Exception:
                pass

        根.after(120, lambda: ocr.开框选(根, 好了, 算了))

    def _清抽帧框(self):
        c = dict(paths.读配置() or {})
        c.pop('抽帧框', None)
        if paths.写配置(c):
            self.应用.配置.update(c)
            self.配置.update(c)
        self._刷抽帧框说明()
        self.说.set('截图改回整屏')


    def _刷字幕框说明(self):
        框 = list(self.配置.get('ocr_box') or [])
        try:
            import ocr
            模型齐 = ocr.就绪()
        except Exception:
            模型齐 = False
        if not 模型齐:
            self.字幕框说.configure(text='⚠ 少了 OCR 模型（应该在 %s 里）——「更准的字幕」暂时用不了，'
                                        '现在只能听声音。' % (os.path.join(paths.用户目录(), 'ocr')))
        elif len(框) < 4:
            self.字幕框说.configure(text='还没框 —— 现在只能听声音。点「框一下字幕」把字幕那一行框住。')
        else:
            self.字幕框说.configure(text='已框好：(%d, %d)，%d × %d。想重新框就再点一次。'
                                        % (框[0], 框[1], 框[2], 框[3]))

    def _框字幕(self):
        try:
            import ocr
        except Exception as e:
            self.字幕框说.configure(text='⚠ 加载 OCR 模块失败：' + str(e)[:80])
            return
        if not ocr.就绪():
            self.字幕框说.configure(text='⚠ 少了 OCR 模型，先装模型再框。')
            return
        根 = self.应用.根
        try:
            根.withdraw()          # 先把自己藏起来，别挡着要框的画面
        except Exception:
            pass

        def 框好了(框):
            c = dict(paths.读配置() or {})
            c['ocr_box'] = [int(v) for v in 框]
            c['ocr开'] = True
            if paths.写配置(c):
                self.应用.配置.update(c)
                self.配置.update(c)
            self._刷字幕框说明()
            self.说.set('字幕区框好了：%d × %d' % (框[2], 框[3]))
            try:
                根.deiconify()
            except Exception:
                pass

        def 算了():
            try:
                根.deiconify()
            except Exception:
                pass
            self.字幕框说.configure(text='这次没框。')

        # 延一点点再开遮罩，等主窗口真的收起来
        根.after(120, lambda: ocr.开框选(根, 框好了, 算了))

    def _清字幕框(self):
        c = dict(paths.读配置() or {})
        c['ocr开'] = False
        c.pop('ocr_box', None)
        if paths.写配置(c):
            self.应用.配置.update(c)
        self._刷字幕框说明()
        self.说.set('不用字幕了，只听话音')

    # ---------- 3.5 游戏（0.7.0：弹幕 + 弹幕框） ----------
    def _建游戏(self):
        框 = self._新页('游戏')
        self._标题(框, '游戏')
        卡 = self._卡(框)
        tk.Label(卡, text='点悬浮窗上那颗手柄，球就藏起来 —— 屏幕上只剩她的弹幕滑过去，'
                          '和右边那块会累积的弹幕框。双击弹幕框回球。',
                 bg=淡卡, fg=字次, anchor='w', justify='left', wraplength=430,
                 font=('Microsoft YaHei UI', 8)).pack(fill='x', pady=(0, 6))

        self.弹幕勾 = tk.BooleanVar(value=bool(self.配置.get('弹幕开', True)))
        tk.Checkbutton(卡, text='她说的话变成弹幕，从屏幕上滑过去', variable=self.弹幕勾,
                       command=self._存游戏, bg=淡卡, fg=字深, activebackground=淡卡,
                       selectcolor=淡卡, anchor='w',
                       font=('Microsoft YaHei UI', 字号)).pack(fill='x')

        行速 = tk.Frame(卡, bg=淡卡)
        行速.pack(fill='x', pady=(6, 0))
        tk.Label(行速, text='滑完一屏要', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 字号)).pack(side='left')
        self.弹幕速 = tk.StringVar(value=str(self.配置.get('弹幕速度秒') or 6))
        框速 = tk.Entry(行速, textvariable=self.弹幕速, width=4, bg='#ffffff', relief='flat',
                       font=('Microsoft YaHei UI', 字号), highlightthickness=1, highlightbackground=淡线)
        框速.pack(side='left', padx=6, ipady=2)
        tk.Label(行速, text='秒（越小越快）', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')

        行字 = tk.Frame(卡, bg=淡卡)
        行字.pack(fill='x', pady=(6, 0))
        tk.Label(行字, text='字多大', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 字号)).pack(side='left')
        self.弹幕字 = tk.StringVar(value=str(self.配置.get('弹幕字号') or 26))
        框字 = tk.Entry(行字, textvariable=self.弹幕字, width=4, bg='#ffffff', relief='flat',
                       font=('Microsoft YaHei UI', 字号), highlightthickness=1, highlightbackground=淡线)
        框字.pack(side='left', padx=6, ipady=2)
        tk.Label(行字, text='像素，同屏最多', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        self.弹幕多 = tk.StringVar(value=str(self.配置.get('弹幕最多') or 10))
        框多 = tk.Entry(行字, textvariable=self.弹幕多, width=3, bg='#ffffff', relief='flat',
                       font=('Microsoft YaHei UI', 字号), highlightthickness=1, highlightbackground=淡线)
        框多.pack(side='left', padx=6, ipady=2)
        tk.Label(行字, text='条', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        # ⭐ 0.9.2：打回车 / 点到别处就存，跟桌面那几项一样（以前只能点「存」）
        for 框们 in (框速, 框字, 框多):
            框们.bind('<Return>', lambda e: (self._存游戏(), 'break')[-1])
            框们.bind('<FocusOut>', lambda e: self._存游戏())

        # ⭐ 1.0.0：每秒画几帧
        行帧 = tk.Frame(卡, bg=淡卡)
        行帧.pack(fill='x', pady=(6, 0))
        tk.Label(行帧, text='每秒画', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 字号)).pack(side='left')
        self.弹幕帧 = tk.StringVar(value='120 FPS' if int(self.配置.get('弹幕帧率') or 60) >= 100 else '60 FPS')
        菜帧 = tk.OptionMenu(行帧, self.弹幕帧, '60 FPS', '120 FPS',
                             command=lambda *_: self._存游戏())
        菜帧.configure(bg='#ffffff', fg=字深, relief='flat', highlightthickness=1,
                       highlightbackground=淡线, font=('Microsoft YaHei UI', 字号))
        菜帧.pack(side='left', padx=6)
        tk.Label(行帧, text='（120 更顺，但更费电）', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')

        # ⭐ 0.8.0
        行位2 = tk.Frame(卡, bg=淡卡)
        行位2.pack(fill='x', pady=(6, 0))
        tk.Label(行位2, text='飘在哪', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        self.弹幕位置 = tk.StringVar(value=str(self.配置.get('弹幕位置') or '全屏'))
        菜位 = tk.OptionMenu(行位2, self.弹幕位置, '全屏', '上半屏', '下半屏',
                             command=lambda *_: self._存游戏())
        菜位.configure(bg='#ffffff', fg=字深, relief='flat', highlightthickness=1,
                       highlightbackground=淡线, font=('Microsoft YaHei UI', 8))
        菜位.pack(side='left', padx=6)
        tk.Label(行位2, text='　字色', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        self.弹幕色块 = tk.Label(行位2, text='　　　', bg=str(self.配置.get('弹幕颜色') or '#ffffff'),
                              relief='flat')
        self.弹幕色块.pack(side='left', padx=(2, 2))
        tk.Button(行位2, text='选色', command=self._选弹幕色, bg='#e7eef4', fg=字深, relief='flat',
                  font=('Microsoft YaHei UI', 8), pady=1, padx=6).pack(side='left')
        tk.Label(行位2, text='　描边', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        self.弹幕边块 = tk.Label(行位2, text='　　　', bg=str(self.配置.get('弹幕描边') or '#28283c'),
                              relief='flat')
        self.弹幕边块.pack(side='left', padx=(2, 2))
        tk.Button(行位2, text='选色', command=self._选弹幕边色, bg='#e7eef4', fg=字深, relief='flat',
                  font=('Microsoft YaHei UI', 8), pady=1, padx=6).pack(side='left')

        行体 = tk.Frame(卡, bg=淡卡)
        行体.pack(fill='x', pady=(6, 0))
        tk.Label(行体, text='飘的字', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        self.弹幕字体 = tk.StringVar(value=str(self.配置.get('弹幕字体') or '站酷快乐体'))
        self.弹幕字体钮 = tk.Button(
            行体, text=self.弹幕字体.get(), relief='flat', bg='#e7eef4', fg=字深,
            highlightthickness=0, font=('Microsoft YaHei UI', 8), padx=6,
            command=lambda: self._选字体(self.弹幕字体.get(), self._定弹幕字体))
        self.弹幕字体钮.pack(side='left', padx=6)
        tk.Label(行体, text='　框里字号', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        self.框字号 = tk.StringVar(value=str(self.配置.get('框字号') or 20))
        框字号框 = tk.Entry(行体, textvariable=self.框字号, width=3, bg='#ffffff', relief='flat',
                          font=('Microsoft YaHei UI', 8), highlightthickness=1,
                          highlightbackground=淡线)
        框字号框.pack(side='left', padx=(2, 4), ipady=2)
        框字号框.bind('<Return>', lambda e: (self._存游戏(), 'break')[-1])
        框字号框.bind('<FocusOut>', lambda e: self._存游戏())
        self.框字体 = tk.StringVar(value=str(self.配置.get('框字体') or '站酷快乐体'))
        self.框字体钮 = tk.Button(
            行体, text=self.框字体.get(), relief='flat', bg='#e7eef4', fg=字深,
            highlightthickness=0, font=('Microsoft YaHei UI', 8), padx=6,
            command=lambda: self._选字体(self.框字体.get(), self._定框字体))
        self.框字体钮.pack(side='left', padx=(2, 4))

        卡2 = self._卡(框)
        self.弹幕框勾 = tk.BooleanVar(value=bool(self.配置.get('弹幕框开', True)))
        tk.Checkbutton(卡2, text='角上放一块弹幕框（累积最近几句，能拖）', variable=self.弹幕框勾,
                       command=self._存游戏, bg=淡卡, fg=字深, activebackground=淡卡,
                       selectcolor=淡卡, anchor='w',
                       font=('Microsoft YaHei UI', 字号)).pack(fill='x')
        行位 = tk.Frame(卡2, bg=淡卡)
        行位.pack(fill='x', pady=(6, 0))
        tk.Label(行位, text='放哪', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 字号)).pack(side='left')
        self.框位置 = tk.StringVar(value=str(self.配置.get('弹幕框位置') or '右下'))
        菜 = tk.OptionMenu(行位, self.框位置, '左上', '右上', '左下', '右下', command=lambda *_: self._存游戏())
        菜.configure(bg='#ffffff', fg=字深, relief='flat', highlightthickness=1,
                     highlightbackground=淡线, font=('Microsoft YaHei UI', 字号))
        try:
            菜['menu'].configure(bg='#ffffff', fg=字深, font=('Microsoft YaHei UI', 字号))
        except Exception:
            pass
        菜.pack(side='left', padx=6)

        # ⭐ 1.0.2：截图 —— 游戏模式自己截 / 一个键随时截
        卡拍 = self._卡(框)
        self.游戏截图勾 = tk.BooleanVar(value=bool(self.配置.get('游戏截图开', False)))
        tk.Checkbutton(卡拍, text='游戏模式里，隔一会儿自己截一张给她看', variable=self.游戏截图勾,
                       command=self._存截图, bg=淡卡, fg=字深, activebackground=淡卡,
                       selectcolor=淡卡, anchor='w',
                       font=('Microsoft YaHei UI', 字号)).pack(fill='x')
        行拍 = tk.Frame(卡拍, bg=淡卡)
        行拍.pack(fill='x', pady=(6, 0))
        tk.Label(行拍, text='每隔', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        self.截短 = tk.StringVar(value=str(int(self.配置.get('游戏截图最短秒') or 45)))
        框短 = tk.Entry(行拍, textvariable=self.截短, width=4, bg='#ffffff', relief='flat',
                        font=('Microsoft YaHei UI', 9), highlightthickness=1, highlightbackground=淡线)
        框短.pack(side='left', padx=(4, 2), ipady=2)
        tk.Label(行拍, text='～', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 9)).pack(side='left')
        self.截长 = tk.StringVar(value=str(int(self.配置.get('游戏截图最长秒') or 120)))
        框长 = tk.Entry(行拍, textvariable=self.截长, width=4, bg='#ffffff', relief='flat',
                        font=('Microsoft YaHei UI', 9), highlightthickness=1, highlightbackground=淡线)
        框长.pack(side='left', padx=(2, 4), ipady=2)
        tk.Label(行拍, text='秒随机', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        for 框们 in (框短, 框长):
            框们.bind('<Return>', lambda e: (self._存截图(), 'break')[-1])
            框们.bind('<FocusOut>', lambda e: self._存截图())
        行拍框 = tk.Frame(卡拍, bg=淡卡)
        行拍框.pack(fill='x', pady=(6, 0))
        tk.Button(行拍框, text='框一下只截哪块', command=lambda: self._框截图('游戏截图框'),
                  bg='#cbdae5', fg=字深, relief='flat',
                  font=('Microsoft YaHei UI', 8), pady=2, padx=8).pack(side='left')
        tk.Button(行拍框, text='整屏', command=lambda: self._清截图框('游戏截图框'),
                  bg='#e7eef4', fg=字次, relief='flat',
                  font=('Microsoft YaHei UI', 8), pady=2, padx=8).pack(side='left', padx=(6, 0))
        self.拍框说 = tk.Label(卡拍, text='', bg=淡卡, fg=字次, anchor='w', justify='left',
                            font=('Microsoft YaHei UI', 8), wraplength=460)
        self.拍框说.pack(fill='x', pady=(4, 0))

        卡3 = self._卡(框)
        tk.Button(卡3, text='现在就进游戏模式', command=self._试游戏, bg='#cbdae5', fg=字深,
                  relief='flat', font=('Microsoft YaHei UI', 字号), pady=3, padx=12).pack(side='left')
        tk.Label(卡3, text='　', bg=淡卡).pack(side='left')
        tk.Button(卡3, text='试一条弹幕', command=self._试弹幕, bg='#cbdae5', fg=字深,
                  relief='flat', font=('Microsoft YaHei UI', 8), pady=2, padx=8).pack(side='left')
        tk.Label(卡3, text='　（塞一条「这是一条弹幕」看效果；双击弹幕框就回球）', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')

        # ⭐ 1.1.3：游戏模式里也要能说话
        卡麦 = self._卡(框)
        self.游戏麦勾 = tk.BooleanVar(value=bool(self.配置.get('游戏开麦克风', False)))
        tk.Checkbutton(卡麦, text='进游戏模式也开着麦克风（游戏里说话也发得出去）',
                       variable=self.游戏麦勾, command=self._存游戏麦, bg=淡卡, fg=字深,
                       activebackground=淡卡, selectcolor=淡卡, anchor='w',
                       font=('Microsoft YaHei UI', 字号)).pack(fill='x')
        tk.Label(卡麦, text='不开也行：按住说话那个键哪个模式都能用。', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(fill='x', pady=(4, 0))

    def _存游戏麦(self):
        c = dict(paths.读配置() or {})
        c['游戏开麦克风'] = bool(self.游戏麦勾.get())
        if paths.写配置(c):
            self.应用.配置.update(c)
            self.配置.update(c)
            self.说.set('游戏模式里的麦克风：' + ('开' if c['游戏开麦克风'] else '关'))

    def _定弹幕字体(self, 名):
        self.弹幕字体.set(名 or '站酷快乐体')
        try:
            self.弹幕字体钮.configure(text=self.弹幕字体.get())
        except Exception:
            pass
        self._存游戏()

    def _定框字体(self, 名):
        self.框字体.set(名 or '站酷快乐体')
        try:
            self.框字体钮.configure(text=self.框字体.get())
        except Exception:
            pass
        self._存游戏()

    def _选色到(self, 键, 块, 默认):
        try:
            from tkinter import colorchooser
            选 = colorchooser.askcolor(color=str(self.配置.get(键) or 默认), parent=self.框)[1]
        except Exception:
            选 = None
        if not 选:
            return
        c = dict(paths.读配置() or {})
        c[键] = 选
        try:
            if paths.写配置(c):
                self.应用.配置.update(c)
        except Exception:
            pass
        self.配置[键] = 选
        try:
            块.configure(bg=选)
        except Exception:
            pass
        self.说.set('颜色改好了（下次进游戏模式生效）')

    def _选弹幕色(self):
        self._选色到('弹幕颜色', self.弹幕色块, '#ffffff')

    def _选弹幕边色(self):
        self._选色到('弹幕描边', self.弹幕边块, '#28283c')

    def _存游戏(self):
        c = dict(paths.读配置() or {})
        c['弹幕开'] = bool(self.弹幕勾.get())
        c['弹幕框开'] = bool(self.弹幕框勾.get())
        c['弹幕框位置'] = str(self.框位置.get() or '右下')
        c['弹幕位置'] = str(self.弹幕位置.get() or '全屏')
        c['弹幕字体'] = str(self.弹幕字体.get() or '站酷快乐体')
        c['框字体'] = str(self.框字体.get() or '站酷快乐体')
        c['弹幕颜色'] = str(self.配置.get('弹幕颜色') or '#ffffff')
        c['弹幕描边'] = str(self.配置.get('弹幕描边') or '#28283c')
        c['弹幕帧率'] = 120 if str(self.弹幕帧.get()).startswith('120') else 60
        try:
            c['框字号'] = max(10, min(48, int(str(self.框字号.get()).strip() or 20)))
        except Exception:
            c['框字号'] = 20
        try:
            c['弹幕速度秒'] = max(1.0, min(30.0, float(str(self.弹幕速.get()).strip() or 6)))
        except Exception:
            c['弹幕速度秒'] = 6
        try:
            c['弹幕字号'] = max(12, min(72, int(str(self.弹幕字.get()).strip() or 26)))
        except Exception:
            c['弹幕字号'] = 26
        try:
            c['弹幕最多'] = max(1, min(30, int(str(self.弹幕多.get()).strip() or 10)))
        except Exception:
            c['弹幕最多'] = 10
        try:
            落 = paths.写配置(c)
        except Exception:
            落 = False
        if 落:
            self.应用.配置.update(c)
            self.说.set('存好了')
            # ⭐ 0.9.2：正在游戏模式里就**当场**按新的来（以前是退出再进，字号改了像没反应）
            try:
                if getattr(self.应用, '游戏模式', False):
                    节 = getattr(self.应用, '_游戏设置变了', None)
                    if callable(节):
                        节()
                    self.说.set('存好了（弹幕按新的来了：字号 %s）' % c.get('弹幕字号'))
            except Exception as e:
                self.说.set('存好了，但游戏模式没跟上：%s' % e)
        else:
            self.说.set('没存上 —— 看看配置目录能不能写')

    def _试游戏(self):
        try:
            self.应用._进游戏模式()
            self.说.set('进了游戏模式 —— 双击弹幕框就回来')
        except Exception as e:
            self.说.set('没进去：%s' % e)

    def _试弹幕(self):
        try:
            试 = getattr(self.应用, '_试弹幕', None)
            self.说.set(试() if callable(试) else '先点手柄进游戏模式')
        except Exception as e:
            self.说.set('塞不进去：%s' % e)

    # ---------- 4 全局（气泡、截图、悬浮窗、开机）----------
    def _建全局(self):
        框 = self._新页('全局')
        self._标题(框, '全局')
        卡 = self._卡(框)
        行1 = tk.Frame(卡, bg=淡卡)
        行1.pack(fill='x')
        tk.Button(行1, text='放个桌面快捷方式', command=self._建快捷, bg='#cbdae5', fg=字深,
                  relief='flat', font=('Microsoft YaHei UI', 字号), pady=3).pack(side='left')
        self.开机勾 = tk.BooleanVar(value=bool(self.配置.get('开机启动')))
        tk.Checkbutton(行1, text='开机就浮出来', variable=self.开机勾, command=self._切开机,
                       bg=淡卡, fg=字深, activebackground=淡卡, selectcolor=淡卡,
                       font=('Microsoft YaHei UI', 字号)).pack(side='left', padx=(12, 0))

        # ⭐ 屏幕缩放（远程放大过系统缩放时，鱼不会自己变大 → 这里能跟着走，也能手动调）
        卡2 = self._卡(框)
        tk.Label(卡2, text='悬浮窗大小', bg=淡卡, fg=字深, anchor='w',
                 font=('Microsoft YaHei UI', 字标, 'bold')).pack(fill='x')
        tk.Label(卡2, text='屏幕缩放（比如远程把 125% 调成 150%）变了，它会自己跟着变大变小；'
                          '觉得不合适就在这儿手动调。',
                 bg=淡卡, fg=字次, anchor='w', justify='left', wraplength=430,
                 font=('Microsoft YaHei UI', 8)).pack(fill='x')
        行2 = tk.Frame(卡2, bg=淡卡)
        行2.pack(fill='x', pady=(6, 0))
        tk.Button(行2, text='小一点', command=lambda: self._调大小(-0.1), bg='#cbdae5', fg=字深,
                  relief='flat', font=('Microsoft YaHei UI', 字号), pady=2, padx=10).pack(side='left')
        self.大小标签 = tk.Label(行2, text=self._大小文字(), bg=淡卡, fg=字次,
                              font=('Microsoft YaHei UI', 字号))
        self.大小标签.pack(side='left', padx=6)
        tk.Button(行2, text='大一点', command=lambda: self._调大小(0.1), bg='#cbdae5', fg=字深,
                  relief='flat', font=('Microsoft YaHei UI', 字号), pady=2, padx=10).pack(side='left')
        tk.Button(行2, text='跟着系统', command=self._跟系统, bg='#cbdae5', fg=字深,
                  relief='flat', font=('Microsoft YaHei UI', 8), pady=2, padx=8).pack(side='left', padx=(6, 0))
        # ⭐ 0.6.1：默认纯像素，勾了才跟系统缩放
        self.跟随勾 = tk.BooleanVar(value=bool(self.配置.get('跟随系统缩放')))
        tk.Checkbutton(卡2, text='跟着系统缩放变大变小（不勾 = 固定像素，换台机器也一样大）',
                       variable=self.跟随勾, command=self._存跟随, bg=淡卡, fg=字次,
                       activebackground=淡卡, selectcolor=淡卡, anchor='w',
                       font=('Microsoft YaHei UI', 8)).pack(fill='x', pady=(6, 0))

        # ⭐ 2026-10-27：不装朗读桥 / TTS，也要能看见她说了什么 —— 冒个气泡
        卡3 = self._卡(框)
        self.气泡勾 = tk.BooleanVar(value=bool(self.配置.get('气泡开', True)))
        tk.Checkbutton(卡3, text='她说话时，在鱼旁边冒个气泡显示那句话', variable=self.气泡勾,
                       command=self._存气泡, bg=淡卡, fg=字深, activebackground=淡卡,
                       selectcolor=淡卡, anchor='w', font=('Microsoft YaHei UI', 字号)).pack(fill='x')
        行3 = tk.Frame(卡3, bg=淡卡)
        行3.pack(fill='x', pady=(6, 0))
        tk.Label(行3, text='显示', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 字号)).pack(side='left')
        self.气泡秒 = tk.StringVar(value=str(self.配置.get('气泡秒') or 6))
        框3 = tk.Entry(行3, textvariable=self.气泡秒, width=5, bg='#ffffff', relief='flat',
                      font=('Microsoft YaHei UI', 字号), highlightthickness=1, highlightbackground=淡线)
        框3.pack(side='left', padx=(6, 4), ipady=2)
        tk.Label(行3, text='秒（到点自己淡掉；气泡不挡鼠标）', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        self.气泡提示 = tk.Label(行3, text='', bg=淡卡, fg='#2f8f63', font=('Microsoft YaHei UI', 8))
        self.气泡提示.pack(side='left', padx=(8, 0))
        框3.bind('<Return>', lambda e: (self._存气泡(), 'break')[-1])
        框3.bind('<FocusOut>', lambda e: self._存气泡())

        # ⭐ 0.9.2：话太长就分页，一页页翻完；最后一页停够上面那个秒数才淡掉
        行3b = tk.Frame(卡3, bg=淡卡)
        行3b.pack(fill='x', pady=(6, 0))
        tk.Label(行3b, text='话多的时候每页停', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 字号)).pack(side='left')
        self.气泡换页 = tk.StringVar(value=str(self.配置.get('气泡换页秒') or 4))
        框3b = tk.Entry(行3b, textvariable=self.气泡换页, width=5, bg='#ffffff', relief='flat',
                        font=('Microsoft YaHei UI', 字号), highlightthickness=1, highlightbackground=淡线)
        框3b.pack(side='left', padx=(6, 4), ipady=2)
        tk.Label(行3b, text='秒（放不下就分页，一页页显示完才淡掉）', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        框3b.bind('<Return>', lambda e: (self._存气泡(), 'break')[-1])
        框3b.bind('<FocusOut>', lambda e: self._存气泡())

        行4 = tk.Frame(卡3, bg=淡卡)
        行4.pack(fill='x', pady=(8, 0))
        tk.Label(行4, text='字色', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        self.气泡字色 = tk.StringVar(value=str(self.配置.get('气泡字色') or '#1c3a52'))
        self.色块 = tk.Label(行4, text='    ', bg=self.气泡字色.get(), relief='flat',
                          font=('Microsoft YaHei UI', 8))
        self.色块.pack(side='left', padx=(4, 2))
        tk.Button(行4, text='选色', command=self._选字色, bg='#e7eef4', fg=字深, relief='flat',
                  font=('Microsoft YaHei UI', 8), padx=8, pady=1).pack(side='left', padx=(0, 10))
        tk.Label(行4, text='描边', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        self.气泡描边 = tk.StringVar(value=str(self.配置.get('气泡描边', 2)))
        框5 = tk.Entry(行4, textvariable=self.气泡描边, width=4, bg='#ffffff', relief='flat',
                      font=('Microsoft YaHei UI', 9), highlightthickness=1, highlightbackground=淡线)
        框5.pack(side='left', padx=(4, 10), ipady=2)
        tk.Label(行4, text='字体', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        self.气泡字体 = tk.StringVar(value=str(self.配置.get('气泡字体') or '站酷快乐体'))
        self.气泡字体钮 = tk.Button(
            行4, text=self.气泡字体.get(), relief='flat', bg='#e7eef4', fg=字深,
            highlightthickness=0, font=('Microsoft YaHei UI', 8), padx=6,
            command=lambda: self._选字体(self.气泡字体.get(), self._定气泡字体))
        self.气泡字体钮.pack(side='left', padx=(4, 0))
        提示2 = tk.Label(行4, text='', bg=淡卡, fg='#2f8f63', font=('Microsoft YaHei UI', 8))
        提示2.pack(side='left', padx=(8, 0))
        # ⭐ 0.8.4：直接给个大小百分比，自己拖到合适
        行大 = tk.Frame(卡3, bg=淡卡)
        行大.pack(fill='x', pady=(6, 0))
        tk.Label(行大, text='气泡大小', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        self.气泡大小 = tk.StringVar(value=str(self.配置.get('气泡大小') or 85))
        框大 = tk.Entry(行大, textvariable=self.气泡大小, width=4, bg='#ffffff', relief='flat',
                       font=('Microsoft YaHei UI', 9), highlightthickness=1, highlightbackground=淡线)
        框大.pack(side='left', padx=(4, 4), ipady=2)
        tk.Label(行大, text='%（50～160，100 = 标准大小）', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        框大.bind('<Return>', lambda e: (self._存气泡(), 'break')[-1])
        框大.bind('<FocusOut>', lambda e: self._存气泡())
        框5.bind('<Return>', lambda e: (self._存气泡(), 'break')[-1])
        框5.bind('<FocusOut>', lambda e: self._存气泡())
        self.气泡字提示 = 提示2

        # ⭐ 1.1.0：气泡淡入淡出按帧率走
        行帧2 = tk.Frame(卡3, bg=淡卡)
        行帧2.pack(fill='x', pady=(6, 0))
        tk.Label(行帧2, text='每秒画', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        self.气泡帧 = tk.StringVar(value='120 FPS' if int(self.配置.get('气泡帧率') or 60) >= 100 else '60 FPS')
        菜帧2 = tk.OptionMenu(行帧2, self.气泡帧, '60 FPS', '120 FPS', command=lambda *_: self._存气泡())
        菜帧2.configure(bg='#ffffff', fg=字深, relief='flat', highlightthickness=1,
                        highlightbackground=淡线, font=('Microsoft YaHei UI', 8))
        菜帧2.pack(side='left', padx=6)
        tk.Label(行帧2, text='（冒出来和消失的顺滑度；120 更顺、更费电）', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')

        # ⭐ 2026-10-27：设置页里得能**打字试一下**，
        #   不然改完颜色/描边根本不知道长什么样，只能等真回话。
        行5 = tk.Frame(卡3, bg=淡卡)
        行5.pack(fill='x', pady=(8, 0))
        tk.Label(行5, text='试一句', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        self.气泡试文 = tk.StringVar(value='这一集她一直没说话，光是听着你念叨那道菜的做法。')
        框6 = tk.Entry(行5, textvariable=self.气泡试文, bg='#ffffff', relief='flat',
                      font=('Microsoft YaHei UI', 9), highlightthickness=1, highlightbackground=淡线)
        框6.pack(side='left', fill='x', expand=True, padx=(4, 6), ipady=3)
        框6.bind('<Return>', lambda e: (self._试气泡(), 'break')[-1])
        tk.Button(行5, text='试一下', command=self._试气泡, bg='#cbdae5', fg=字深, relief='flat',
                  font=('Microsoft YaHei UI', 8), pady=3, padx=10).pack(side='left')

        # ⭐ 1.0.3：按住说话 —— 电话没开也行，松开就把这句（可能还有一张图）发过去
        卡热 = self._卡(框)
        tk.Label(卡热, text='按住说话（电话没开也能用）', bg=淡卡, fg=字深, anchor='w',
                 font=('Microsoft YaHei UI', 字号)).pack(fill='x')
        行键1 = tk.Frame(卡热, bg=淡卡)
        行键1.pack(fill='x', pady=(6, 0))
        tk.Button(行键1, text='录一个键', command=lambda: self._录键('按住说键', '按住说名', '键说1'),
                  bg='#cbdae5', fg=字深, relief='flat',
                  font=('Microsoft YaHei UI', 8), pady=2, padx=10).pack(side='left')
        self.键说1 = tk.Label(行键1, text=self._键名('按住说键', '按住说名'), bg=淡卡, fg=字次,
                             font=('Microsoft YaHei UI', 9))
        self.键说1.pack(side='left', padx=(8, 0))
        tk.Label(行键1, text='　只说话，不带图', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        行键2 = tk.Frame(卡热, bg=淡卡)
        行键2.pack(fill='x', pady=(6, 0))
        tk.Button(行键2, text='录一个键', command=lambda: self._录键('按住说图键', '按住说图名', '键说2'),
                  bg='#cbdae5', fg=字深, relief='flat',
                  font=('Microsoft YaHei UI', 8), pady=2, padx=10).pack(side='left')
        self.键说2 = tk.Label(行键2, text=self._键名('按住说图键', '按住说图名'), bg=淡卡, fg=字次,
                             font=('Microsoft YaHei UI', 9))
        self.键说2.pack(side='left', padx=(8, 0))
        tk.Label(行键2, text='　说话 + 顺手截一张屏', bg=淡卡, fg=字次,
                 font=('Microsoft YaHei UI', 8)).pack(side='left')
        行热框 = tk.Frame(卡热, bg=淡卡)
        行热框.pack(fill='x', pady=(6, 0))
        tk.Button(行热框, text='带图时只截哪块', command=lambda: self._框截图('热键截图框'),
                  bg='#e7eef4', fg=字深, relief='flat',
                  font=('Microsoft YaHei UI', 8), pady=2, padx=8).pack(side='left')
        tk.Button(行热框, text='整屏', command=lambda: self._清截图框('热键截图框'),
                  bg='#e7eef4', fg=字次, relief='flat',
                  font=('Microsoft YaHei UI', 8), pady=2, padx=8).pack(side='left', padx=(6, 0))
        tk.Button(行热框, text='现在截一张试试', command=self._试截图,
                  bg='#cbdae5', fg=字深, relief='flat',
                  font=('Microsoft YaHei UI', 8), pady=2, padx=10).pack(side='left', padx=(10, 0))
        self.热框说 = tk.Label(卡热, text='', bg=淡卡, fg=字次, anchor='w', justify='left',
                            font=('Microsoft YaHei UI', 8), wraplength=460)
        self.热框说.pack(fill='x', pady=(4, 0))

        self._刷截图说明()

    # ---------- 截图（1.0.2） ----------
    def _键名(self, 键项='按住说键', 名项='按住说名'):
        名 = str(self.配置.get(名项) or '').strip()
        键 = int(self.配置.get(键项) or 0)
        if 键 <= 0:
            return '还没设'
        return '现在是：%s' % (名 or ('键码 %d' % 键))

    def _刷截图说明(self):
        for 键, 标签 in (('游戏截图框', getattr(self, '拍框说', None)),
                         ('热键截图框', getattr(self, '热框说', None))):
            if 标签 is None:
                continue
            try:
                框 = [int(v) for v in (self.配置.get(键) or [])]
            except Exception:
                框 = []
            if len(框) < 4:
                标签.configure(text='现在：整个屏幕')
            else:
                标签.configure(text='现在：只截 (%d, %d) 起 %d×%d 那块'
                                   % (框[0], 框[1], 框[2], 框[3]))

    def _存截图(self):
        c = dict(paths.读配置() or {})
        c['游戏截图开'] = bool(self.游戏截图勾.get())
        try:
            c['游戏截图最短秒'] = max(5, min(3600, int(str(self.截短.get()).strip() or 45)))
        except Exception:
            c['游戏截图最短秒'] = 45
        try:
            c['游戏截图最长秒'] = max(c['游戏截图最短秒'] + 1,
                                   min(7200, int(str(self.截长.get()).strip() or 120)))
        except Exception:
            c['游戏截图最长秒'] = 120
        if paths.写配置(c):
            self.应用.配置.update(c)
            self.配置.update(c)
            self.说.set('截图：%s，每隔 %d～%d 秒一张'
                      % ('开' if c['游戏截图开'] else '关', c['游戏截图最短秒'], c['游戏截图最长秒']))
            try:
                if getattr(self.应用, '游戏模式', False):
                    self.应用._开游戏截图()
            except Exception:
                pass
        else:
            self.说.set('没存上 —— 看看配置目录能不能写')

    def _框截图(self, 键):
        try:
            import ocr
        except Exception as e:
            self.说.set('框选没起来：%s' % e)
            return

        def 完成(框):
            try:
                c = dict(paths.读配置() or {})
                c[键] = [int(v) for v in 框]
                if paths.写配置(c):
                    self.应用.配置.update(c)
                    self.配置.update(c)
                    self.说.set('框好了：%d×%d' % (框[2], 框[3]))
                    self._刷截图说明()
            except Exception as e:
                self.说.set('框好了但没存上：%s' % e)

        try:
            self.父.withdraw()
        except Exception:
            pass
        try:
            ocr.开框选(self.父, 完成)
        except Exception as e:
            self.说.set('框选取不了：%s' % e)
        try:
            self.父.after(300, self.父.deiconify)
        except Exception:
            pass

    def _清截图框(self, 键):
        c = dict(paths.读配置() or {})
        c.pop(键, None)
        if paths.写配置(c):
            self.应用.配置.update(c)
            self.配置.update(c)
            self.说.set('改成整个屏幕了')
            self._刷截图说明()

    def _录键(self, 键项='按住说键', 名项='按住说名', 标签名='键说1'):
        try:
            窗 = tk.Toplevel(self.父)
            窗.title('按一下你要用的键')
            窗.configure(bg=淡底)
            窗.geometry('360x140')
            窗.attributes('-topmost', True)
            提示 = tk.Label(窗, text='现在按一下你要用的键\n（按 Esc 取消）', bg=淡底, fg=字深,
                          font=('Microsoft YaHei UI', 12))
            提示.pack(expand=True)

            def 按(e):
                if str(e.keysym) == 'Escape':
                    窗.destroy()
                    return
                键 = int(getattr(e, 'keycode', 0) or 0)
                if 键 <= 0:
                    return
                c = dict(paths.读配置() or {})
                c[键项] = 键
                c[名项] = str(getattr(e, 'keysym', '') or '')
                if paths.写配置(c):
                    self.应用.配置.update(c)
                    self.配置.update(c)
                    try:
                        标签 = getattr(self, 标签名, None)
                        if 标签 is not None:
                            标签.configure(text=self._键名(键项, 名项))
                    except Exception:
                        pass
                    self.说.set('记下了：以后按住这个键就能说话')
                窗.destroy()

            窗.bind('<KeyPress>', 按)
            提示.bind('<KeyPress>', 按)
            # ⚠ 一定要等窗真显示出来再抢焦点，不然按键落到别处（点了没反应就是这个）
            def 抢焦():
                try:
                    窗.lift()
                    窗.focus_force()
                    提示.focus_set()
                except Exception:
                    pass
            窗.after(120, 抢焦)
            窗.after(400, 抢焦)
        except Exception as e:
            self.说.set('录键没起来：%s' % e)

    def _试截图(self):
        try:
            import threading
            self.说.set('截一张看看…')
            threading.Thread(target=self.应用._截一张, args=('热键',), daemon=True).start()
        except Exception as e:
            self.说.set('截不了：%s' % e)

    def _选字色(self):
        try:
            from tkinter import colorchooser
            现在 = str(self.气泡字色.get() or '#1c3a52')
            选了 = colorchooser.askcolor(color=现在, title='气泡里的字用什么颜色')
            色 = (选了 or (None, None))[1]
            if 色:
                self.气泡字色.set(色.upper())
                try:
                    self.色块.configure(bg=色)
                except Exception:
                    pass
                self._存气泡()
        except Exception as e:
            self.说.set('选不了颜色：%s' % e)

    def _试气泡(self):
        """用现在填的这句、现在这些设置，直接把气泡弹出来看一眼。"""
        try:
            文 = str(self.气泡试文.get()).strip() or '（随便说一句试试）'
            self._存气泡()
            self.应用._冒气泡(文, 重建=True)
            self.说.set('试了一下：这句话会显示在鱼旁边的气泡里')
        except Exception as e:
            self.说.set('试不出来：%s' % e)

    def _定气泡字体(self, 名):
        self.气泡字体.set(名 or '站酷快乐体')
        try:
            self.气泡字体钮.configure(text=self.气泡字体.get())
        except Exception:
            pass
        self._存气泡()

    # ---------- 选字体（弹个小窗口，能打字筛） ----------
    def _选字体(self, 当前, 回调):
        try:
            import 字体表
            名字们 = ['站酷快乐体'] + 字体表.名字们()
        except Exception as e:
            try:
                self.说.set('字体表读不出来：%s' % e)
            except Exception:
                pass
            return
        窗 = tk.Toplevel(self.框)
        窗.title('选字体')
        窗.geometry('380x480')
        窗.configure(bg=淡底)
        try:
            窗.transient(self.框)
        except Exception:
            pass
        行 = tk.Frame(窗, bg=淡底)
        行.pack(fill='x', padx=10, pady=(10, 4))
        tk.Label(行, text='找', bg=淡底, fg=字次, font=('Microsoft YaHei UI', 字号)).pack(side='left')
        搜 = tk.StringVar(value='')
        框搜 = tk.Entry(行, textvariable=搜, bg='#ffffff', relief='flat',
                        font=('Microsoft YaHei UI', 字号), highlightthickness=1,
                        highlightbackground=淡线)
        框搜.pack(side='left', fill='x', expand=True, padx=(6, 0), ipady=3)
        列框 = tk.Frame(窗, bg=淡底)
        列框.pack(fill='both', expand=True, padx=10, pady=(4, 6))
        列 = tk.Listbox(列框, bg='#ffffff', fg=字深, relief='flat', highlightthickness=1,
                        highlightbackground=淡线, font=('Microsoft YaHei UI', 字号))
        # ⭐ 0.8.3：加竖滚动条 + 滚轮
        条 = tk.Scrollbar(列框, orient='vertical', command=列.yview)
        列.configure(yscrollcommand=条.set)
        条.pack(side='right', fill='y')
        列.pack(side='left', fill='both', expand=True)

        def 滚(e):
            try:
                列.yview_scroll(-1 * int(getattr(e, 'delta', 0) / 120), 'units')
            except Exception:
                pass

        列.bind('<MouseWheel>', 滚)
        窗.bind('<MouseWheel>', 滚)
        底 = tk.Frame(窗, bg=淡底)
        底.pack(fill='x', padx=10, pady=(0, 10))
        说明 = tk.Label(底, text='', bg=淡底, fg=字次, font=('Microsoft YaHei UI', 8))
        说明.pack(side='left')

        def 刷(*_):
            关键 = 搜.get().strip().lower()
            列.delete(0, 'end')
            for 名 in 名字们:
                if not 关键 or 关键 in 名.lower():
                    列.insert('end', 名)
            if 当前 in 名字们:
                try:
                    i = list(列.get(0, 'end')).index(当前)
                    列.selection_set(i)
                    列.see(i)
                except Exception:
                    pass
            说明.configure(text='共 %d 个' % 列.size())

        def 选了(*_):
            选 = 列.curselection()
            if not 选:
                return
            名 = 列.get(选[0])
            try:
                回调(名)
            except Exception:
                pass
            窗.destroy()

        搜.trace_add('write', 刷)
        列.bind('<Double-Button-1>', 选了)
        列.bind('<Return>', 选了)
        框搜.bind('<Return>', lambda e: (列.focus_set(), 选了(), 'break')[-1])
        tk.Button(底, text='用这个', command=选了, bg='#cbdae5', fg=字深, relief='flat',
                  font=('Microsoft YaHei UI', 字号), pady=2, padx=10).pack(side='right')
        tk.Button(底, text='算了', command=窗.destroy, bg='#e7eef4', fg=字深, relief='flat',
                  font=('Microsoft YaHei UI', 字号), pady=2, padx=10).pack(side='right', padx=(0, 6))
        刷()
        框搜.focus_set()

    def _存气泡(self):
        c = dict(paths.读配置() or {})
        c['气泡开'] = bool(self.气泡勾.get())
        try:
            c['气泡字色'] = str(self.气泡字色.get()).strip() or '#1c3a52'
        except Exception:
            c['气泡字色'] = '#1c3a52'
        try:
            c['气泡描边'] = max(0, min(4, int(str(self.气泡描边.get()).strip() or 2)))
        except Exception:
            c['气泡描边'] = 2
        try:
            c['气泡字体'] = str(self.气泡字体.get()).strip() or '站酷快乐体'
        except Exception:
            c['气泡字体'] = '站酷快乐体'
        try:
            c['气泡秒'] = max(1, min(60, int(str(self.气泡秒.get()).strip() or 6)))
        except Exception:
            c['气泡秒'] = 6
        try:
            c['气泡大小'] = max(50, min(160, int(str(self.气泡大小.get()).strip() or 85)))
        except Exception:
            c['气泡大小'] = 85
        try:
            c['气泡换页秒'] = max(1, min(60, int(str(getattr(self, '气泡换页', None).get()).strip() or 4)))
        except Exception:
            c['气泡换页秒'] = 4
        try:
            c['气泡帧率'] = 120 if str(getattr(self, '气泡帧', None).get()).startswith('120') else 60
        except Exception:
            c['气泡帧率'] = 60
        if paths.写配置(c):
            self.应用.配置.update(c)
            self.配置.update(c)
            self.说.set('气泡：%s，显示 %d 秒，大小 %d%%'
                      % ('开' if c['气泡开'] else '关', c['气泡秒'], c['气泡大小']))
            try:
                self.应用.气泡 = None      # 颜色/描边/字体改了 → 下次按新设置重建
            except Exception:
                pass
            try:
                self.气泡提示.configure(text='已存 ✓')
                self.应用.根.after(1600, lambda: self.气泡提示.configure(text=''))
            except Exception:
                pass

    # ---------- 5 关于 ----------
    def _建关于(self):
        框 = self._新页('关于')
        self._标题(框, '关于')
        卡 = self._卡(框)
        tk.Label(卡, text='鱼搭子 v%s' % version.版本号, bg=淡卡, fg=字深, anchor='w',
                 font=('Microsoft YaHei UI', 字号)).pack(fill='x')
        tk.Label(卡, text='模型放这：' + paths.模型目录(), bg=淡卡, fg=字次, anchor='w',
                 justify='left', wraplength=430, font=('Microsoft YaHei UI', 8)).pack(fill='x')
        tk.Label(卡, text='配置放这：' + paths.配置路径(), bg=淡卡, fg=字次, anchor='w',
                 justify='left', wraplength=430, font=('Microsoft YaHei UI', 8)).pack(fill='x')
        tk.Label(卡, text='语音识别全在本机做，不录音、不上传。', bg=淡卡, fg=字次, anchor='w',
                 justify='left', wraplength=430, font=('Microsoft YaHei UI', 8)).pack(fill='x', pady=(6, 0))

    def _输入(self, 父, 名, 值, 宽):
        行 = tk.Frame(父, bg=淡卡)
        行.pack(fill='x', pady=2)
        tk.Label(行, text=名, bg=淡卡, fg=字次, width=8, anchor='w',
                 font=('Microsoft YaHei UI', 字号)).pack(side='left')
        变 = tk.StringVar(value=值)
        框 = tk.Entry(行, textvariable=变, width=0, bg='#ffffff', relief='flat',
                      font=('Microsoft YaHei UI', 字号), highlightthickness=1,
                      highlightbackground=淡线)
        框.pack(side='left', fill='x', expand=True, ipady=3)
        setattr(框, '_变', 变)
        return 变

    # ---------- 麦克风 ----------
    def _刷麦克风(self):
        try:
            import ear as 耳朵模块
            设备 = 耳朵模块.列输入设备()
        except Exception:
            设备 = []
        菜单 = self.麦框['menu']
        try:
            菜单.delete(0, 'end')
        except Exception:
            pass
        self.麦表 = {}
        菜单.add_command(label='（系统默认）', command=lambda: self._选麦克风(None, ''))

        现在号 = self.配置.get('mic_device')
        现在名 = str(self.配置.get('mic_device_name') or '')
        当前 = None
        for d in 设备:
            标签 = d['名字'] + ('　● 系统默认' if d['默认'] else '')
            self.麦表[标签] = d
            菜单.add_command(label=标签, command=lambda d=d: self._选麦克风(d['编号'], d['名字']))
            if 当前 is None:
                if 现在号 not in (None, '') and str(现在号) == str(d['编号']):
                    当前 = 标签
                elif 现在名 and d['名字'] == 现在名:
                    当前 = 标签
        self.麦选.set(当前 or '（系统默认）')

        if not 设备:
            self.麦说明.configure(text='这台机器没找到能录的麦克风 —— 电话开起来会报「麦克风打不开」。',
                                 fg=红)
            return
        用了 = 当前 or '（系统默认）'
        提示 = '现在用：' + 用了 + '　（共 %d 个能录的；换了要重新开一次电话才生效）' % len(设备)
        if 当前 is None and (现在号 not in (None, '') or 现在名):
            提示 = '原来选的那个麦克风不在了，先用系统默认。' + 提示
        self.麦说明.configure(text=提示, fg=字次)

    def _选麦克风(self, 编号, 名字):
        c = dict(paths.读配置() or {})
        c['mic_device'] = 编号
        c['mic_device_name'] = 名字 or ''
        if not paths.写配置(c):
            self.说.set('没存上 —— 看看配置目录有没有写权限：' + paths.配置路径())
            return
        self.应用.配置.update(c)
        self.配置.update(c)
        换 = getattr(self.应用, '换麦克风', None)
        if callable(换) and getattr(self.应用, '通话', False):
            说 = 换(编号, 名字 or '')
            self.说.set('麦克风换了：%s —— 电话已经重新打开（%s）' % (名字 or '系统默认', 说 or '好了'))
        else:
            self.说.set('麦克风换成：%s%s' % (名字 or '系统默认',
                                            '（下次开电话就用这个）' if not getattr(self.应用, '通话', False)
                                            else '（电话开着，挂断再点一次才换）'))
        self._刷麦克风()

    # ---------- 语音 ----------
    def _刷语音状态(self):
        就绪 = paths.语音就绪()
        self.语音状态.configure(
            text=('● 已经装好了，电话和陪看都能用' if 就绪 else '○ 还没装 —— 点下面这个按钮，一次装好'),
            fg=(绿 if 就绪 else 字次))
        self.语音说明.configure(
            text=('模型：SenseVoice（最准的那份，894MB）。文件在 %s' % paths.模型目录()) if 就绪
            else '只下一个模型（约 894MB）+ 词表；下完电话和陪看都能用，不用再下第二次。')
        self.装钮.configure(text=('重新装' if 就绪 else '装语音（约 894MB，只下一次）'))

    def _点装(self):
        if not paths.语音就绪():
            paths.补内置语音()
        if self.下载.开始():
            self.说.set('开始下载了，可以关掉这个设置页去看别的，进度会接着走')
        self._轮询()

    def _点停(self):
        self.下载.停()
        
        self.说.set('停下了；再点「装语音」会接着下（已经下的不浪费）')

    # ---------- 悬浮窗大小 ----------
    def _大小文字(self):
        try:
            径 = int(getattr(self.应用, '球径', 0) or 0)
        except Exception:
            径 = 0
        try:
            手动 = float(self.应用.配置.get('ui_scale') or 1.0)
        except Exception:
            手动 = 1.0
        try:
            屏幕 = int(round(float(getattr(self.应用, '显示缩放', 1.0) or 1.0) * 100))
        except Exception:
            屏幕 = 100
        return '%d px · %d%%' % (径, int(round(手动 * 100)))

    def _调大小(self, 增减):
        调 = getattr(self.应用, '调大小', None)
        if callable(调):
            try:
                self.说.set(调(增减))
            except Exception as e:
                self.说.set('没调成：%s' % e)
        self._刷大小()

    def _跟系统(self):
        跟 = getattr(self.应用, '跟系统缩放', None)
        if callable(跟):
            try:
                self.说.set(跟())
            except Exception as e:
                self.说.set('没切成跟系统：%s' % e)
        self._刷大小()

    def _刷大小(self):
        try:
            self.大小标签.configure(text=self._大小文字())
        except Exception:
            pass

    # ⭐ 0.6.1：勾了「跟着系统缩放」才会乘屏幕缩放（默认不勾 = 纯像素）
    def _存跟随(self):
        c = dict(paths.读配置() or {})
        c['跟随系统缩放'] = bool(self.跟随勾.get())
        try:
            落 = paths.写配置(c)
        except Exception:
            落 = False
        if 落:
            self.应用.配置.update(c)
            try:
                self.应用.重排()
            except Exception as e:
                self.说.set('重排没成：%s' % e)
        self._刷大小()

    # ---------- 配置 ----------
    def _存连接_去抖(self):
        """输入框变一下就排队存一次（600ms 内只存最后一次，别每敲一个字就写盘）。"""
        try:
            if getattr(self, '_存定时', None):
                try:
                    self.框.after_cancel(self._存定时)
                except Exception:
                    pass
            self._存定时 = self.框.after(600, self._保存配置静默)
        except Exception:
            pass

    def _保存配置静默(self):
        旧 = self.说.get()
        self._保存配置()
        if '存好了' in self.说.get():
            self.说.set('已经自动存好了')

    def _保存配置(self):
        c = dict(paths.读配置() or {})
        try:
            c['dsh_port'] = max(1024, min(65535, int(self.端口.get() or 8777)))
        except Exception:
            c['dsh_port'] = 8777
        c['session'] = str(self.会话.get() or '').strip()
        c['api_回调'] = str(self.回调.get() or '').strip()
        落 = paths.写配置(c)
        if 落:
            self.应用.配置.update(c)
            self.说.set('存好了')
        else:
            self.说.set('没存上 —— 看看配置目录有没有写权限：' + paths.配置路径())

    def _填回话地址(self):
        口 = getattr(self.应用, '回话口', None)
        址 = 口.地址() if 口 else ('http://127.0.0.1:%s/hands/reply' % (self.配置.get('回话端口') or 8778))
        self.回调.set(址)
        self._保存配置()
        self.说.set('填好了：这个地址也该填进 DSH 设置 → 鱼搭子 →「回话递回」，她那句话就会回到这个窗里。')

    # ---------- 秒数输入框：改了自动存、回车也存、旁边亮一下「已存」 ----------
    #   填完秒数按回车没反应、也没有保存按钮，
    #   得跟刷B站插件那样「改了就存，存完有个提示」。
    def _秒框接上(self, 框, 提示位):
        框.bind('<Return>', lambda e: (self._存陪看(), self._闪存好(提示位), 'break')[-1])
        框.bind('<FocusOut>', lambda e: self._存陪看())
        框.bind('<KeyRelease>', lambda e: self._排存(提示位))

    def _排存(self, 提示位, 存=None):
        """边打字边存太频繁，停手 0.6 秒再存一次。"""
        try:
            if getattr(self, '_存定时', None):
                self.应用.根.after_cancel(self._存定时)
        except Exception:
            pass
        try:
            self._存定时 = self.应用.根.after(
                600, lambda: ((存 or self._存陪看)(), self._闪存好(提示位)))
        except Exception:
            self._存定时 = None

    # ---------- 语音：安静几秒算一句（0.5.0） ----------
    def _存语音(self):
        """把「安静几秒算一句」存进配置；电话正开着就让主线程重开一次耳朵，立刻生效。"""
        c = dict(paths.读配置() or {})
        try:
            v = float(str(self.静音秒.get()).strip() or 2.0)
        except Exception:
            v = 2.0
        c['断句静音秒'] = max(0.4, min(8.0, round(v, 1)))
        try:
            落 = paths.写配置(c)
        except Exception:
            落 = False
        if 落:
            self.应用.配置.update(c)
            try:
                self.说.set('存好了：安静 %s 秒算一句' % c['断句静音秒'])
            except Exception:
                pass
        # ⚠ 1.1.3：这里以前会发「换麦」→ 挂断再开通话。
        #   只是改「安静几秒算一句」，却把正在打电话的电话毙掉，重开还可能失败。
        #   现在只存数字（新值下一次开麦时生效），不动正在跑的电话。

    def _闪存好(self, 提示位):
        try:
            提示位.configure(text='已存 ✓')
            if getattr(self, '_闪定时', None):
                self.应用.根.after_cancel(self._闪定时)
        except Exception:
            return
        try:
            self._闪定时 = self.应用.根.after(1800, lambda: 提示位.configure(text=''))
        except Exception:
            pass

    def _存陪看(self):
        c = dict(paths.读配置() or {})
        c['字幕送给大肥鱼'] = bool(self.字幕勾.get())
        c['陪看带麦克风'] = bool(self.麦克风勾.get())
        try:
            c['随机搭话秒'] = max(0, min(14400, int(str(self.搭话秒.get()).strip() or 0)))
        except Exception:
            c['随机搭话秒'] = 0
        c.pop('随机搭话分钟', None)
        try:
            c['抽帧开'] = bool(self.抽帧勾.get())
        except Exception:
            pass
        try:
            c['抽帧秒'] = max(10, min(1800, int(str(self.抽帧秒.get()).strip() or 45)))
        except Exception:
            c['抽帧秒'] = 45
        # ⭐ 0.3.9：节奏只有一个区间（下限 = 随机搭话秒，上限 = 搭话最多秒）
        try:
            c['搭话最多秒'] = max(0, min(14400, int(str(self.搭话上限.get()).strip() or 120)))
        except Exception:
            c['搭话最多秒'] = 120
        if c['搭话最多秒'] and c['搭话最多秒'] < c['随机搭话秒']:
            c['搭话最多秒'] = c['随机搭话秒']
        # 「多久算安静」不进设置页了，固定 8 秒就够
        c.setdefault('安静秒', 8)
        if paths.写配置(c):
            self.应用.配置.update(c)
            self.说.set('存好了' + ('（陪看时它每 ' + str(c['随机搭话秒']) + ' 秒里找机会说一句）'
                                  if c['随机搭话秒'] else '（陪看时它只看不说）')
                        + ('（还会大概每 %s 秒抽一帧给她看）' % c.get('抽帧秒') if c.get('抽帧开') else ''))

    def _建快捷(self):
        目标 = sys.executable
        参数 = '' if getattr(sys, 'frozen', False) else '"%s"' % os.path.join(paths.程序目录(), 'ball.py')
        图标 = os.path.join(paths.资源目录(), 'assets', '鱼搭子.ico')
        ok, 哪 = 建桌面快捷方式('鱼搭子', 目标, 参数, 图标)
        self.说.set(('桌面上有了：' + 哪) if ok else ('没建出来：' + str(哪)))

    def _切开机(self):
        if self.开机勾.get():
            ok, 哪 = 放启动项('鱼搭子')
            self.说.set(('以后开机就浮出来了' if ok else ('没放成：' + str(哪))))
            if not ok:
                self.开机勾.set(False)
                return
        else:
            启动 = os.path.join(os.environ.get('APPDATA', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup', '鱼搭子.lnk')
            try:
                if os.path.exists(启动):
                    os.remove(启动)
                self.说.set('不再开机自启了')
            except Exception as e:
                self.说.set('删不掉：' + str(e))
                return
        c = dict(paths.读配置() or {})
        c['开机启动'] = bool(self.开机勾.get())
        paths.写配置(c)
        self.应用.配置.update(c)

    # ---------- 轮询 ----------
    def _轮询(self):
        try:
            p = self.下载.进度()
            总 = p.get('总字节') or 0
            已 = p.get('已下字节') or 0
            宽 = max(1, self.进度条.winfo_width())
            比 = 0 if not 总 else max(0.0, min(1.0, 已 / 总))
            self.进度条.coords(self.进度件, 0, 0, int(宽 * 比), 8)
            if p.get('进行中'):
                self.装钮.configure(state='disabled')
                self.停钮.configure(state='normal')
                兆 = lambda b: '%.1f' % (b / 1048576.0)
                速 = p.get('速度') or 0
                self.语音说明.configure(text='%s　%s/%s MB　%s MB/s' % (
                    p.get('说') or '下载中', 兆(已), 兆(总) if 总 else '?', '%.2f' % (速 / 1048576.0)))
            else:
                self.装钮.configure(state='normal')
                self.停钮.configure(state='disabled')
                if p.get('完成'):
                    self.说.set('语音装好了，去点电话试试')
                elif p.get('出错'):
                    self.说.set(p['出错'])
                self._刷语音状态()
        except Exception:
            pass
        try:
            self.框.after(400, self._轮询)
        except Exception:
            pass

    # ---------- 给外面用 ----------
    def 销毁(self):
        try:
            self.下载.停()
        except Exception:
            pass
        try:
            self.框.unbind_all('<MouseWheel>')
        except Exception:
            pass
        try:
            self.框.destroy()
        except Exception:
            pass
