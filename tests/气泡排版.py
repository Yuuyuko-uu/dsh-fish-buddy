"""运行 python tests/气泡排版.py，直接用挂件的气泡图和字体验证。"""
import queue
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image, ImageChops

应用 = Path(__file__).resolve().parents[1] / 'app'
sys.path.insert(0, str(应用))
from ball import 鱼搭子
from bubble import 气泡


尾字回归 = '把这句话完整地显示在气泡里，第二行还有空位，最后几个字也要留在第一页上放。'
资源 = 应用 / 'assets'
字体 = 资源 / '字体' / 'ZCOOLKuaiLe-Regular.ttf'


class 定时器:
    def __init__(self):
        self.编号 = 0
        self.任务 = {}

    def after(self, 毫秒, 回调):
        self.编号 += 1
        self.任务[self.编号] = (毫秒, 回调)
        return self.编号

    def after_cancel(self, 编号):
        self.任务.pop(编号, None)

    def 到时(self, 编号, 应等):
        毫秒, 回调 = self.任务.pop(编号)
        assert 毫秒 == 应等
        回调()


def 建气泡(宽=363, 描边=2, 根=None):
    return 气泡(根, 资源 / '气泡框.png', str(字体), 宽=宽, 描边=描边)


class 气泡排版(unittest.TestCase):
    def test_中间行用满宽度而且尾字还在第一页(self):
        泡 = 建气泡()
        页们, _, _, _ = 泡.排页(尾字回归)
        self.assertEqual(len(页们), 1)
        首, 中, 末 = 页们[0]
        self.assertGreater(len(中), len(首))
        self.assertTrue(末.endswith('上放。'))
        self.assertEqual(首 + 中 + 末, 尾字回归)

    def test_小框少掉一页大框少掉一条短尾行(self):
        for 宽, 行数 in ((300, 3), (500, 2)):
            with self.subTest(宽=宽):
                泡 = 建气泡(宽)
                页们, _, _, 号 = 泡.排页(尾字回归)
                self.assertEqual(len(页们), 1)
                self.assertEqual(len(页们[0]), 行数)
                self.assertEqual(''.join(页们[0]), 尾字回归)
                self.assertGreaterEqual(号, 15)
                self.assertGreater(泡.排页('嗯。')[-1], 号)

    def test_分页保留文字并且翻转前后像素都在框内(self):
        文本 = ('这台机器 87.5% 的电量还算可以，DeepSeek 说「小火慢炖」就好。♡✧\n'
              + '接着是一个很长的单词 ' + 'W' * 120 + '。')
        泡 = 建气泡(描边=4)
        页们, 体, 行高, _ = 泡.排页(文本)
        行们 = [行 for 页 in 页们 for 行 in 页]
        self.assertGreater(len(页们), 1)
        self.assertEqual(''.join(行们), 文本.replace('\n', ''))
        for 词 in ('87.5%', 'DeepSeek'):
            self.assertTrue(any(词 in 行 for 行 in 行们), 词)
        self.assertFalse(any(行.lstrip().startswith(('，', '。', '」')) for 行 in 行们))
        白表 = 泡._量宽()
        for 页 in 页们:
            for 翻转 in (False, True):
                底 = 泡.图.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if 翻转 else 泡.图
                图 = 泡.合成页(页, 体, 行高, 翻转)
                差 = ImageChops.difference(底, 图).convert('RGB')
                框 = 差.getbbox()
                self.assertIsNotNone(框)
                for y in range(框[1], 框[3]):
                    字边 = 差.crop((0, y, 泡.宽, y + 1)).getbbox()
                    if 字边:
                        左, 右 = 白表[y]
                        if 翻转:
                            左, 右 = 泡.宽 - 1 - 右, 泡.宽 - 1 - 左
                        self.assertGreaterEqual(字边[0], 左)
                        self.assertLessEqual(字边[2], 右 + 1)

    def test_下一条等最后一页停够(self):
        根 = 定时器()
        泡 = 建气泡(根=根)
        泡.窗 = Mock()
        泡._淡入 = Mock()
        泡._淡出 = Mock()
        搭 = SimpleNamespace(气泡=泡, 配置={'气泡秒': 1}, _回复队=['下一条'], 待显示=queue.Queue())
        self.assertTrue(泡.显示(尾字回归 * 4, 秒=1, 换页秒=2,
                             位置=(40, 40), 球径=132, 大小=0.85))
        self.assertGreater(len(泡.页们), 1)
        for i in range(len(泡.页们)):
            鱼搭子._送下一条(搭)
            self.assertTrue(搭.待显示.empty())
            self.assertEqual(泡._第几页, i)
            根.到时(泡._藏定时, 1000 if i == len(泡.页们) - 1 else 2000)
        鱼搭子._送下一条(搭)
        self.assertEqual(搭.待显示.get_nowait(), ('回复', '下一条'))


if __name__ == '__main__':
    unittest.main()
