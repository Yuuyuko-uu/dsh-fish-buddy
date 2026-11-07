"""悬浮球该落在哪块屏上 —— issue #7 的回归。

跑：cd app && python ../tests/球别落空.py

用的是 issue 里那位用户的真实屏幕布局（三块屏非矩形拼接，右边一大块空洞）。
不碰 tkinter、不碰真显卡，纯算坐标。
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(os.path.dirname(HERE), 'app')
sys.path.insert(0, APP)

import 球位置 as q  # noqa: E402

# issue #7 里贴的布局
三屏 = [
    (0, 0, 1920, 1080),        # DISPLAY1 主
    (-1504, 0, 1003, 1504),    # DISPLAY2
    (-311, -1080, 2560, 1080),  # DISPLAY3
]


def 在屏里(屏, x, y, 边长=168):
    sx, sy, sw, sh = 屏
    return sx <= x and x + 边长 <= sx + sw and sy <= y and y + 边长 <= sy + sh


def 落在任何屏上(屏们, x, y, 边长=168):
    return any(在屏里(p, x, y, 边长) for p in 屏们)


class 球别落空(unittest.TestCase):
    def test_1_默认位置必须落在真的屏上(self):
        x, y = q.默认位置(三屏, 168)
        self.assertTrue(落在任何屏上(三屏, x, y), '默认位置落在了没有显示器的空洞里：%s' % ((x, y),))

    def test_2_旧的老位置会被拉回屏里(self):
        # 那位用户实测抓到的窗口坐标
        x, y = q.限位置(三屏, 168, 2033, 754)
        self.assertTrue(落在任何屏上(三屏, x, y), '存下来的空洞坐标没有被拉回来：%s' % ((x, y),))

    def test_3_空洞里挑最近的屏(self):
        屏 = q.落哪块屏(三屏, 2033, 754)
        self.assertEqual(屏, (0, 0, 1920, 1080), '右边的空洞离主屏最近，应该拉回主屏')

    def test_4_点在屏上就留在那块(self):
        屏 = q.落哪块屏(三屏, -1000, 100)
        self.assertEqual(屏, (-1504, 0, 1003, 1504))

    def test_5_主屏是原点那块(self):
        self.assertEqual(q.主屏(三屏), (0, 0, 1920, 1080))

    def test_6_单屏也不会被推出去(self):
        单 = [(0, 0, 1920, 1080)]
        x, y = q.限位置(单, 168, -500, 5000)
        self.assertTrue(在屏里(单[0], x, y), '单屏时也不许越界：%s' % ((x, y),))

    def test_7_兜底不会崩(self):
        x, y = q.限位置([], 168, 100, 100)
        self.assertEqual((x, y), (100, 100))


if __name__ == '__main__':
    unittest.main(verbosity=2)
