# -*- coding: utf-8 -*-
# 量一下气泡实际能放几行、一行几字（不启动 Tk）
import os
import sys
from PIL import Image

基 = os.path.dirname(os.path.abspath(__file__))
图路 = os.path.join(基, 'assets', '气泡框.png')
if not os.path.exists(图路):
    print('找不到气泡图：' + 图路)
    sys.exit(1)

原 = Image.open(图路).convert('RGBA')
原宽, 原高 = 原.size
print('气泡原图: %d x %d（宽高比 %.2f）' % (原宽, 原高, 原宽 / float(原高)))

# 她的设置：球径 132、气泡大小 92%
球径 = 132
大小 = 0.92
最宽 = max(240, min(int(球径 * 3.24 * 大小), 900))
宽 = max(300, min(int(最宽), 最宽))
倍 = 宽 / float(原宽)
高 = int(原高 * 倍)
print('气泡实际: %d x %d（最宽 %d）' % (宽, 高, 最宽))

内 = (int(宽 * 0.135), int(高 * 0.560), int(宽 * 0.905), int(高 * 0.852))
高内 = 内[3] - 内[1] - 2
内宽 = 内[2] - 内[0]
print('内区: 宽 %d  高 %d' % (内宽, 高内))

顶点 = max(16, min(40, int(round(内宽 / 18.0))))
行高 = int(顶点 * 1.36)
每页行 = max(1, min(4, int(高内 // max(1, 行高))))
print('字号 %d / 行高 %d / 每页 %d 行' % (顶点, 行高, 每页行))

# 一行大概几个中文字（按字号估）
每行字 = int(内宽 / 顶点)
print('一行大约 %d 个字 → 一页大约 %d 个字' % (每行字, 每行字 * 每页行))
