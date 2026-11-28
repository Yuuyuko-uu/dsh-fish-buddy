"""运行 python tests/像话吗.py —— 「听到但没送出」那批真句子的回归。

用户报的四句（2026-11-26 / 11-28 实测被吞的原文），必须照发；
重复的字（结巴 / 拖音）也一律照发 —— 1.8.5 把「同一个字重复」那条整个删了；
只有「明显不是话」的才拦。
"""
import sys
import unittest
from pathlib import Path

应用 = Path(__file__).resolve().parents[1] / 'app'
sys.path.insert(0, str(应用))
from ball import 鱼搭子

# ⚠ 原文照抄，一个字都别改 —— 这就是被吞的那几句
被吞过的真句子 = [
    '是美骨湖啊，然后那个呃要的话，我其实每次都去铃铛那儿，他都会给自动给我补满的。',
    '你把漏掉的那几句，你给我说一下，我去给那个谁发过去吧。',
    '我说的角色名字9元，然后你你你帮我搜一下呀，哪个礼物性价比比较高。',
    '真的是以后至少要首先想清楚我是在问什么呀。',
]

# 重复的字一律照发：结巴、拖音、数字里的三连，全是「人在说话」
重复也照发 = [
    '然后你你你帮我搜一下呀',
    '就就就那个礼物性价比高一点吧',
    '啊啊啊啊',
    '嗯嗯嗯',
    '好好好好好好',
    '把截图上限设置成8000',
]

真噪声 = [
    '。',
    '，。；、',
    '我',           # 单字、又不是语气词
    '%$#@!',
]


class 像话吗(unittest.TestCase):
    def test_被吞过的长句都要照发(self):
        for 句 in 被吞过的真句子:
            with self.subTest(句=句):
                要, 理由 = 鱼搭子._像话吗(句)
                self.assertTrue(要, '整句被挡掉了：%s（%s）' % (句, 理由))

    def test_重复的字一律照发(self):
        for 句 in 重复也照发:
            with self.subTest(句=句):
                要, 理由 = 鱼搭子._像话吗(句)
                self.assertTrue(要, '重复的字又被拦了：%s（%s）' % (句, 理由))

    def test_真噪声还是挡住(self):
        for 文本 in 真噪声:
            with self.subTest(文本=文本):
                self.assertFalse(鱼搭子._像话吗(文本)[0])

    def test_空的和纯空白(self):
        for 文本 in ('', '   ', '\n', None):
            with self.subTest(文本=文本):
                self.assertFalse(鱼搭子._像话吗(文本)[0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
