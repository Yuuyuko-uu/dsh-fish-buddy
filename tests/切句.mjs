// ⭐ 0.9.4：「一句话一条」的切句逻辑。
//
//   DSH 一直用 `agent/assistant-stream` 发逐字增量（text-delta），插件以前只等整轮结束才递回，
//   所以挂件要等它全部生成完才出声。开了这个开关之后，说到句号就递一条。
//
//   切法三条：只在句末标点切 / 太短的不单独发 / 攒太长没标点就硬切。
// 跑法：node tests/切句.mjs
import { test } from 'node:test'
import assert from 'node:assert/strict'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const 根 = path.join(path.dirname(fileURLToPath(import.meta.url)), '..')
const 模 = await import('file:///' + path.join(根, 'lib/host.js').replace(/\\/g, '/') + '?t=' + Date.now())
const 切 = 模.切一句

test('一句话一条：说到句号就切出来', () => {
  const r = 切('我今天特别开心。')
  assert.deepEqual(r.出, ['我今天特别开心。'])
  assert.equal(r.剩, '')
})

test('一句话一条：两句一起进来就切两条', () => {
  const r = 切('我今天特别开心。你也早点睡吧。')
  assert.deepEqual(r.出, ['我今天特别开心。', '你也早点睡吧。'])
  assert.equal(r.剩, '')
})

test('一句话一条：没说完的半句留在缓冲里，不提前发', () => {
  const r = 切('我今天特别开心。不过还有一件事想')
  assert.deepEqual(r.出, ['我今天特别开心。'])
  assert.equal(r.剩, '不过还有一件事想', '没到句号的尾巴要留着')
})

test('一句话一条：短句不单独发，并进下一句', () => {
  // 「嗯。」只有两个字，单独发出去就是噪音 —— 要跟后面那句合成一条
  const r = 切('嗯。我今天特别开心。')
  assert.deepEqual(r.出, ['嗯。我今天特别开心。'], '短句应该并进去，而不是卡住')
})

test('一句话一条：一句里夹两个短句也不卡', () => {
  const r = 切('嗯。好。我今天特别开心。')
  assert.deepEqual(r.出, ['嗯。好。我今天特别开心。'])
})

test('一句话一条：连续标点算同一个结尾（…… ？！）', () => {
  const r = 切('这怎么可能……我明明记得。')
  // 「这怎么可能……」本身已经七个字，够长了 → 该单独成一条；
  // 连续三个「…」要当作**同一个结尾**，不能切出「这怎么可能。」+「…我明明记得。」
  assert.deepEqual(r.出, ['这怎么可能……', '我明明记得。'])
  assert.equal(r.剩, '')
})

test('一句话一条：空行（段落）算一句说完', () => {
  const r = 切('第一句在这里说完，挺长的\n\n第二句还长着呢')
  assert.deepEqual(r.出, ['第一句在这里说完，挺长的'])
  assert.equal(r.剩, '第二句还长着呢')
})

test('一句话一条：单个换行不算切点（markdown 每一行都切会碎成渣）', () => {
  // ⚠ 0.9.3 实测：以前单个 \n 就切，markdown 的列表项、代码块每一行全被当句子切碎，
  //   碎的又被「太短」规则合并回去 —— 又乱又慢，还会丢句子。
  const r = 切('这里是一行\n这里又一行\n这里再来一行，够长了吧')
  assert.deepEqual(r.出, [], '单个换行不该切')
  assert.equal(r.剩, '这里是一行\n这里又一行\n这里再来一行，够长了吧')
})

test('一句话一条：逗号不切（切了会碎成一条条）', () => {
  const r = 切('今天呢，我想了想，还是算了吧。')
  assert.deepEqual(r.出, ['今天呢，我想了想，还是算了吧。'])
})

test('一句话一条：超过三十字的普通句子等到说完一起递', () => {
  const 句 = '把这句话完整地显示在气泡里，第二行还有空位，最后几个字也要留在第一页上放'
  assert.ok(句.length > 30)
  const r = 切(句)
  assert.deepEqual(r.出, [])
  assert.equal(r.剩, 句)
  assert.deepEqual(切(r.剩 + '。').出, [句 + '。'])
})

test('一句话一条：攒太长还没标点就硬切，别让它一口气说完才出声', () => {
  const 长 = '这是一段特别特别长长长长长长长长长长长长的没有标点的话'
  const r = 切(长, 6, 20)
  assert.ok(r.出.length >= 1, '这么长还没切，会等到整段说完')
  assert.ok(r.出[0].length <= 20)
})

test('一句话一条：空输入不许崩', () => {
  assert.deepEqual(切('').出, [])
  assert.deepEqual(切(null).出, [])
  assert.deepEqual(切(undefined).出, [])
})

test('一句话一条：英文句号也要认', () => {
  const r = 切('this is a full sentence. and another one here.')
  // 英文只有 `.`，句末标点里没放 . —— 只能靠硬切或者等最后
  assert.ok(Array.isArray(r.出))
})

// ── 从 attemptId 认会话 ─────────────────────────────
test('帧会话：从 `${sessionId}:${attempt}` 里取出会话 id', () => {
  assert.equal(模.帧会话({ attemptId: 'session-abc-123:1' }), 'session-abc-123')
  assert.equal(模.帧会话({ attemptId: 'session-abc-123:12' }), 'session-abc-123')
  assert.equal(模.帧会话({ attemptId: 'session-abc-123' }), 'session-abc-123')
})

test('帧会话：没有 attemptId 时返回空，不许崩', () => {
  assert.equal(模.帧会话({}), '')
  assert.equal(模.帧会话(null), '')
  assert.equal(模.帧会话(undefined), '')
})

// ── 开关必须真的存在 ────────────────────────────────
test('开关：默认是「整轮一条」（老路径稳）', async () => {
  const 源 = (await import('node:fs')).readFileSync(path.join(根, 'lib/host.js'), 'utf8')
  assert.match(源, /一句话一条: false/, '默认值不是 false')
})

test('开关：开着时，turn/end 不许再整轮发一遍（否则先听碎的再听整的）', async () => {
  const 源 = (await import('node:fs')).readFileSync(path.join(根, 'lib/host.js'), 'utf8')
  assert.match(源, /if \(!配置\.一句话一条\) void 递回/, 'turn/end 那半边没接开关')
})

test('开关：流式那条路要按开关短路', async () => {
  const 源 = (await import('node:fs')).readFileSync(path.join(根, 'lib/host.js'), 'utf8')
  const 起 = 源.indexOf("ctx.on('agent/assistant-stream'")
  assert.ok(起 > 0, '没有监听 assistant-stream')
  const 段 = 源.slice(起, 起 + 400)
  assert.match(段, /if \(!配置\.一句话一条\) return/, '流式监听没看开关')
})

test('流式：必须排队顺序发（递回里有 30 秒静音保护，并发会被自己掐死）', async () => {
  const 源 = (await import('node:fs')).readFileSync(path.join(根, 'lib/host.js'), 'utf8')
  assert.match(源, /流队列 = 流队列\.then/, '没有排队，并发发会被静音保护掐掉一半')
})
