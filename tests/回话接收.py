"""回话接收口：起一个真端口、真发一次 POST，看回调有没有拿到那句话。

跑法： python tests/回话接收.py
"""
import json
import os
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app'))

import reply_server  # noqa: E402

结果 = []


def 查(名, 过, 附=''):
    结果.append(bool(过))
    print(('PASS ' if 过 else 'FAIL ') + 名 + ('' if 过 else '  ← ' + str(附)))


收到 = []
端口 = 18778
口 = reply_server.回话口(lambda t: 收到.append(t), 端口=端口)
查('口子起得来', 口.开始() is True, 口.状态)
查('敲出来的地址对', 口.地址() == 'http://127.0.0.1:%d/hands/reply' % 端口, 口.地址())

直连 = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def 发(体, 路径='/hands/reply'):
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (端口, 路径),
                                 data=json.dumps(体, ensure_ascii=False).encode('utf-8'),
                                 headers={'content-type': 'application/json'})
    try:
        r = 直连.open(req, timeout=5)
        return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, {}


码, 回 = 发({'text': '我在的，你接着说'})
time.sleep(0.3)
查('POST 一句话 → 200', 码 == 200, 码)
查('回调真的拿到了那句话', 收到 and 收到[-1] == '我在的，你接着说', 收到)

码2, _ = 发({'text': ''})
time.sleep(0.2)
查('空的一句不会塞进界面', len(收到) == 1, 收到)

码3, _ = 发({'text': 'x'}, '/nope')
查('别的地址 404', 码3 == 404, 码3)

# ---------- 麦克风：设置页/DSH 要能问「有哪些设备」和「换成哪个」 ----------
接口 = reply_server.回话口(
    lambda t: 收到.append(t), 端口=18779,
    on_devices=lambda: {'列表': [{'编号': 3, '名字': '麦克风阵列', '声道': 2, '默认': False}],
                        '当前': {'编号': 3, '名字': '麦克风阵列'}, '通话': False},
    on_device=lambda 号, 名: '换好了：%s' % (名 or '系统默认'),
)
查('带设备口子的版本起得来', 接口.开始() is True, 接口.状态)
if 接口.状态.get('起没起'):
    def 发2(体, 路径):
        req = urllib.request.Request('http://127.0.0.1:18779%s' % 路径,
                                     data=json.dumps(体, ensure_ascii=False).encode('utf-8'),
                                     headers={'content-type': 'application/json'})
        r = 直连.open(req, timeout=5)
        return json.loads(r.read().decode('utf-8'))

    设备 = None
    try:
        r = 直连.open(urllib.request.Request('http://127.0.0.1:18779/hands/devices'), timeout=5)
        设备 = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        设备 = {'ok': False, '说': str(e)}
    查('能列出设备（原样转出去，不是只转键名）',
       bool(设备.get('ok') and isinstance(设备.get('设备'), dict)
            and isinstance(设备.get('设备', {}).get('列表'), list)
            and len(设备['设备']['列表']) == 1), 设备)

    换 = 发2({'index': 3, 'name': '麦克风阵列'}, '/hands/device')
    查('能换麦克风，回一句人话', bool(换.get('ok')) and '麦克风阵列' in str(换.get('说')), 换)

    默认 = 发2({'index': None, 'name': ''}, '/hands/device')
    查('选系统默认也行（index 传 null）', bool(默认.get('ok')) and '系统默认' in str(默认.get('说')), 默认)

    接口.停()
    time.sleep(0.2)

# 端口被占：再起一个应该明确失败，而不是崩
占 = reply_server.回话口(lambda t: None, 端口=端口)
查('同一端口起第二个 → 明确报错、不崩', 占.开始() is False, 占.状态)

口.停()
time.sleep(0.2)
查('停掉之后没人听了', 口.状态.get('起没起') is False, 口.状态)

失败 = sum(1 for x in 结果 if not x)
print('\n共 %d 项，失败 %d 项' % (len(结果), 失败))
sys.exit(失败)
