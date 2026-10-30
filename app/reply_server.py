"""接话：大肥鱼说的话，由 DSH 那边 POST 到本机这个小口子。

    POST http://127.0.0.1:8778/hands/reply    {"text": "她那句"}
    GET  http://127.0.0.1:8778/hands/devices   → 这台机器能录的麦克风
    POST http://127.0.0.1:8778/hands/device    {"index": 3, "name": "..."} 换麦克风

只监听 127.0.0.1（外网连不进来）。收到就交给界面显示。
端口可以在设置里改；改了之后要重启一次挂件。
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class 回话口:
    def __init__(self, on_text, 端口=8778, on_devices=None, on_device=None, on_shot=None):
        self.on_text = on_text
        self.on_devices = on_devices        # () -> [{'编号','名字','声道','默认'}, ...]
        self.on_device = on_device          # (编号, 名字) -> 一句人话
        self.on_shot = on_shot              # ⭐ 1.1.1：() -> (图字节, 尺寸) 或 None（她要自己开口时先要张图）
        self.端口 = int(端口 or 8778)
        self.状态 = {'起没起': False, '端口': self.端口, '错': '', '收到': 0}
        self._服务 = None

    def 地址(self):
        return 'http://127.0.0.1:%d/hands/reply' % self.端口

    def 开始(self):
        if self._服务 is not None:
            return True
        回调 = self.on_text
        列设备 = self.on_devices
        设设备 = self.on_device
        拍一张 = self.on_shot
        状态 = self.状态

        class 处理(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def _回(self, 码, 内容):
                try:
                    体 = json.dumps(内容, ensure_ascii=False).encode('utf-8')
                    self.send_response(码)
                    self.send_header('content-type', 'application/json; charset=utf-8')
                    self.send_header('content-length', str(len(体)))
                    self.end_headers()
                    self.wfile.write(体)
                except Exception:
                    pass

            def _读体(self):
                try:
                    长 = int(self.headers.get('content-length') or 0)
                except Exception:
                    长 = 0
                try:
                    原 = self.rfile.read(长) if 长 else b'{}'
                    return json.loads(原.decode('utf-8') or '{}')
                except Exception:
                    return {}

            def do_GET(self):
                if self.path.startswith('/hands/devices'):
                    try:
                        设备 = 列设备() if callable(列设备) else []
                    except Exception as e:
                        self._回(200, {'ok': False, '设备': [], '说': '列不出来：%s' % e})
                        return
                    版本 = ''
                    try:
                        import version as _v
                        版本 = str(getattr(_v, '版本号', '') or '')
                    except Exception:
                        pass
                    self._回(200, {'ok': True, '设备': 设备, '版本': 版本})
                    return
                # ⭐ 1.4.2：报一下自己的版本 —— 插件的「检查更新」要靠它知道挂件旧不旧
                版本 = ''
                try:
                    import version as _v
                    版本 = str(getattr(_v, '版本号', '') or '')
                except Exception:
                    pass
                self._回(200, {'ok': True, '说': '鱼搭子的回话口在这儿', '版本': 版本})

            def do_POST(self):
                数据 = self._读体() if self.path.startswith(('/hands/reply', '/hands/device', '/hands/stitch')) else {}

                if self.path.startswith('/hands/device'):
                    if not callable(设设备):
                        self._回(200, {'ok': False, '说': '这个版本的挂件还不能在这儿换麦克风'})
                        return
                    号 = 数据.get('index', 数据.get('编号'))
                    名 = str(数据.get('name') or 数据.get('名字') or '')
                    if 号 in ('', 'default', '默认'):
                        号 = None
                    try:
                        号 = None if 号 is None else int(号)
                    except Exception:
                        号 = None
                    try:
                        说法 = 设设备(号, 名)
                    except Exception as e:
                        说法 = ''
                        self._回(200, {'ok': False, '说': '换不了：%s' % e})
                        return
                    状态['收到'] += 1
                    self._回(200, {'ok': True, '说': 说法 or '换好了'})
                    return

                if self.path.startswith('/hands/stitch'):
                    # ⭐ 1.6.0：插件要发「攒着的 3 张」时，请这里拼成一竖条
                    try:
                        import frames as _帧
                        字节, 宽, 高 = _帧.拼一条(数据.get('帧们') or [])
                    except Exception as e:
                        self._回(200, {'ok': False, '说': '拼不了：%s' % e})
                        return
                    if not 字节:
                        self._回(200, {'ok': False, '说': '这几张读不出来，拼不了'})
                        return
                    import base64 as _b64
                    self._回(200, {'ok': True, '图片': _b64.b64encode(字节).decode('ascii'),
                                  '宽': 宽, '高': 高})
                    return

                if self.path.startswith('/hands/shot'):
                    if not callable(拍一张):
                        self._回(200, {'ok': False, '说': '这个版本的挂件还不能拍照'})
                        return
                    try:
                        结果 = 拍一张()
                    except Exception as e:
                        self._回(200, {'ok': False, '说': '拍不了：%s' % e})
                        return
                    if not 结果:
                        self._回(200, {'ok': False, '说': '这一下没抓到画面'})
                        return
                    字节, 尺寸 = 结果
                    import base64 as _b64
                    self._回(200, {'ok': True, '图片': _b64.b64encode(字节).decode('ascii'),
                                  '尺寸': '%dx%d' % (尺寸[0], 尺寸[1])})
                    return

                if not self.path.startswith('/hands/reply'):
                    self._回(404, {'ok': False, '说': '没这个地址'})
                    return
                文 = str(数据.get('text') or 数据.get('正文') or '').strip()
                self._回(200, {'ok': True, '说': '收到了'})
                if 文:
                    状态['收到'] += 1
                    try:
                        回调(文)
                    except Exception:
                        pass

            def log_message(self, *args):
                pass

        class 只开一次(ThreadingHTTPServer):
            # Windows 上 SO_REUSEADDR 允许多个程序抢同一个端口 —— 关掉它，
            # 不然挂件开了两份，回话会一半进这个、一半进那个。
            allow_reuse_address = False

        try:
            self._服务 = 只开一次(('127.0.0.1', self.端口), 处理)
        except Exception as e:
            self._服务 = None
            self.状态.update({'起没起': False, '错': str(e)})
            return False
        threading.Thread(target=self._服务.serve_forever, daemon=True).start()
        self.状态.update({'起没起': True, '错': ''})
        return True

    def 停(self):
        if self._服务 is None:
            return
        try:
            self._服务.shutdown()
            self._服务.server_close()
        except Exception:
            pass
        self._服务 = None
        self.状态.update({'起没起': False})
