"""游戏模式「立即截图」键 + 电话被静音那个 bug —— issue #13 的回归。

跑：python tests/手动截图键.py

不碰 tkinter、不碰显卡、不碰麦克风，纯算键码和那个「松手还听不听」的判定。
"""
import inspect
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(os.path.dirname(HERE), 'app')
sys.path.insert(0, APP)

import ball  # noqa: E402
import paths  # noqa: E402


class 手动截图键(unittest.TestCase):
    def test_小键盘跟上排数字不是一个键(self):
        饰, 码 = ball.鱼搭子._解析组合键('小键盘8')
        self.assertEqual(码, 0x68, '小键盘 8 应该是 0x68')
        self.assertEqual(饰, {'ctrl': False, 'alt': False, 'shift': False})
        _, 上排 = ball.鱼搭子._解析组合键('8')
        self.assertEqual(上排, 0x38, '上排 8 应该是 0x38')
        self.assertNotEqual(码, 上排)

    def test_小键盘各个数字(self):
        for n in range(10):
            _, 码 = ball.鱼搭子._解析组合键('小键盘%d' % n)
            self.assertEqual(码, 0x60 + n, '小键盘 %d 应该是 0x%02X' % (n, 0x60 + n))

    def test_小键盘也能配修饰键(self):
        饰, 码 = ball.鱼搭子._解析组合键('Alt+小键盘5')
        self.assertEqual(码, 0x65)
        self.assertTrue(饰['alt'])
        self.assertFalse(饰['ctrl'])

    def test_乱七八糟的不认(self):
        for 文 in ('小键盘', '小键盘x', '小键盘88', '小键盘99'):
            _, 码 = ball.鱼搭子._解析组合键(文)
            self.assertEqual(码, 0, '「%s」不该解析出键码' % 文)

    def test_原有键位没被改坏(self):
        _, 码 = ball.鱼搭子._解析组合键('Alt+G')
        self.assertEqual(码, ord('G'))
        _, 码 = ball.鱼搭子._解析组合键('F9')
        self.assertEqual(码, 0x78)

    def test_截图能跳过去重(self):
        参 = inspect.signature(ball.鱼搭子._截一张).parameters
        self.assertIn('跳过去重', 参, '手动截图要能跳过去重（跟上张一样也留）')

    def test_立即截图键默认是空的(self):
        默认 = paths.默认配置
        self.assertIn('游戏立即截图键', 默认)
        self.assertEqual(str(默认.get('游戏立即截图键') or ''), '',
                         '默认不绑，让用户自己录')


class 电话不该被按住说话弄聋(unittest.TestCase):
    """按住说话/带图 借的是电话那只耳朵；松手不能把它一起静音。"""

    def test_电话开着要继续听(self):
        self.assertTrue(ball.松手后还听吗(True))

    def test_电话没开要闭嘴(self):
        self.assertFalse(ball.松手后还听吗(False))

    def test_空值当没开(self):
        self.assertFalse(ball.松手后还听吗(None))


if __name__ == '__main__':
    unittest.main(verbosity=2)
