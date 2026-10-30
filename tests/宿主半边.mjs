// 鱼搭子 · 宿主那半边的自测
// 用法: node tests/宿主半边.mjs
//
// 不碰真实的 DSH：用临时 DSH_HOME + 假 ctx，真的起一个小口子，真的发 HTTP 过去。

import { mkdtempSync, writeFileSync, readFileSync, rmSync, existsSync, utimesSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const 结果 = []
const 查 = (名, 过, 附言) => {
  结果.push({ 名, 过: !!过 })
  console.log((过 ? 'PASS ' : 'FAIL ') + 名 + (过 ? '' : '  ← ' + (附言 || '')))
}
const 等 = (毫秒) => new Promise((r) => setTimeout(r, 毫秒))

// ---------- 临时家目录 ----------
const 家 = mkdtempSync(join(tmpdir(), 'fishbuddy-'))
process.env.DSH_HOME = 家
process.env.DSH_FISHBUDDY_NO_LAUNCH = '1'   // 自测里别真的把挂件拉起来
const 端口 = 18777
writeFileSync(join(家, 'fish-buddy-config.json'), JSON.stringify({
  总开关: true, 端口, 会话: 'session-abc', 回调: 'http://127.0.0.1:1/reply', 带上来源: true,
}), 'utf8')

// ---------- 假宿主 ----------
const 调用 = { followup: [], 路由: new Map(), 事件: new Map(), 清理: [] }
const 挂的白板 = []
const agent = {
  session: { id: 'abc' },
  followup: async (m) => { 调用.followup.push(m) },
  ctx: {
    systemPrompt: {
      // ⭐ 0.1.5：白板改走 context()（每轮都变的内容不能放系统提示词，会把整段历史弄成未缓存）
      context: (o) => { 挂的白板.push(o); return () => { o.__卸了 = true } },
      section: (o) => { 挂的白板.push(o); return () => { o.__卸了 = true } },
    },
  },
}

const ctx = {
  interval: (fn) => { return () => {} },
  get(名) {
    if (名 === 'sessions') return { list: () => [{ id: 'abc' }, { id: 'def' }], flush: async () => {} }
    if (名 === 'sessionTitle') return { get: (s) => ({ title: '会话' + s.id }) }
    if (名 === 'agents') return { get: (id) => (String(id).includes('abc') ? agent : undefined) }
    return undefined
  },
  on(名, 处理) {
    调用.事件.set(名, 处理)
    return () => 调用.事件.delete(名)
  },
  effect(工) {
    const 清 = 工()
    if (typeof 清 === 'function') 调用.清理.push(清)
    return 清
  },
  webServer: {
    register(项) {
      调用.路由.set(项.path, 项.handler)
      return () => 调用.路由.delete(项.path)
    },
  },
  agents: { get: (id) => (String(id).includes('abc') ? agent : undefined) },
  sessions: { list: () => [{ id: 'abc' }], flush: async () => {} },
  sessionTitle: { get: () => ({ title: '测试会话' }) },
}

// ---------- 装上 ----------
const 插件 = await import('../lib/host.js')
插件.apply(ctx, {})
await 等(300)

查('插件导出了 apply', typeof 插件.apply === 'function')
// ⭐ 0.4.10：必需服务只在 required 里，别的都是可选 —— 宿主缺某个服务也不该让插件挂不起来
查('inject 只把 agents / webServer 当必需', (() => {
  const i = 插件.inject
  if (Array.isArray(i)) return i.length === 2 && i.includes('agents') && i.includes('webServer')
  return Boolean(i && Array.isArray(i.required) && i.required.length === 2
    && i.required.includes('agents') && i.required.includes('webServer'))
})())

// ---------- 0.4.1：配置文件名换了，老的得能搬过来 ----------
{
  const 老家 = mkdtempSync(join(tmpdir(), 'fish-buddy-搬-'))
  writeFileSync(join(老家, 'fishbuddy-config.json'),
    JSON.stringify({ 端口: 18888, 会话: 'session-xyz' }), 'utf8')
  查('老名字的配置搬到了新名字', 插件.搬老配置(老家) === true)
  const 新原文 = readFileSync(join(老家, 'fish-buddy-config.json'), 'utf8')
  查('搬过去的内容一点没变', JSON.parse(新原文).会话 === 'session-xyz' && JSON.parse(新原文).端口 === 18888, 新原文)
  查('老文件还在（只搬不删）', readFileSync(join(老家, 'fishbuddy-config.json'), 'utf8').includes('session-xyz'))
  查('再搬一次不会重复搬', 插件.搬老配置(老家) === false)
  const 空家 = mkdtempSync(join(tmpdir(), 'fish-buddy-空-'))
  查('什么都没有的时候不搬', 插件.搬老配置(空家) === false)
  rmSync(老家, { recursive: true, force: true })
  rmSync(空家, { recursive: true, force: true })
}

// ---------- 真的发一句话进去 ----------
const 发 = async (体, 路径 = '/hands/say') => {
  const r = await fetch('http://127.0.0.1:' + 端口 + 路径, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(体),
  })
  return { 码: r.status, 体: await r.json() }
}

const 一 = await 发({ text: '大肥鱼你在吗' })
查('口子通了', 一.码 === 200, JSON.stringify(一))
查('话被塞进会话', 调用.followup.length === 1)
查('塞进去的是「挂件里说的话」+ 原话',
  调用.followup[0] && String(JSON.stringify(调用.followup[0].content)).includes('大肥鱼你在吗'))
// ⭐ 0.7.7：source 改成 user —— 只有 kind=user 的消息，聊天界面才会把图片块正常渲染出来
查('来源标成了 user（图才渲染得出来）', 调用.followup[0] && 调用.followup[0].source && 调用.followup[0].source.kind === 'user')

const 二 = await 发({ text: '   ' })
查('空的一句被挡回去', 二.码 === 400)

const 三 = await 发({ text: '换个地址' }, '/nope')
查('别的地址 404', 三.码 === 404)

const 四 = await fetch('http://127.0.0.1:' + 端口 + '/hands/ping')
查('ping 有回应', (await 四.json()).ok === true)

// ---------- 她的回话递回挂件 ----------
const 递回 = []
const 原fetch = globalThis.fetch
globalThis.fetch = async (地址, 选项) => {
  递回.push({ 地址, 体: 选项 && 选项.body })
  return { ok: true, status: 200, json: async () => ({}) }
}
const 处理事件 = 调用.事件.get('session/event')
查('监听了 session/event', typeof 处理事件 === 'function')

// 刚发过一句话，插件已经把它们塞进绑定的那间（会话 abc）了
处理事件({ id: 'abc' }, { type: 'assistant/message', data: { turn: 7, message: { content: [{ type: 'text', text: '我在的' }] } } })
处理事件({ id: 'abc' }, { type: 'turn/end', data: { turn: 7, reason: { kind: 'completed' } } })
await 等(120)
查('回话被递回挂件', 递回.length === 1, '递回了 ' + 递回.length + ' 次')
查('递回的是她那句', 递回[0] && String(递回[0].体).includes('我在的'))

// 0.4.2：这间绑着挂件，**不管谁起的头**都要递回去（以前只递挂件叫起来的那一轮）
处理事件({ id: 'abc' }, { type: 'assistant/message', data: { turn: 8, message: { content: [{ type: 'text', text: '我自己说的' }] } } })
处理事件({ id: 'abc' }, { type: 'turn/end', data: { turn: 8, reason: { kind: 'completed' } } })
await 等(120)
查('绑定的会话里，不是挂件叫的那一轮也递回', 递回.length === 2, '递回了 ' + 递回.length + ' 次')
查('递回的就是那一轮最后那句', 递回[1] && String(递回[1].体).includes('我自己说的'))

// 别的会话不该往外递（挂件只绑了一间）
处理事件({ id: 'def' }, { type: 'assistant/message', data: { turn: 9, message: { content: [{ type: 'text', text: '别的会话' }] } } })
处理事件({ id: 'def' }, { type: 'turn/end', data: { turn: 9, reason: { kind: 'completed' } } })
await 等(120)
查('没绑的会话一句都不往外递', 递回.length === 2, '递回了 ' + 递回.length + ' 次')

globalThis.fetch = 原fetch

// ---------- 设置页的路由 ----------
const 状态路由 = 调用.路由.get('/dsh-fish-buddy/state')
查('有状态路由', typeof 状态路由 === 'function')
const 抓住 = () => {
  const 桶 = {}
  return { 桶, res: { setHeader() {}, end(串) { 桶.体 = JSON.parse(串) } } }
}
const s1 = 抓住()
await 状态路由({ url: '/dsh-fish-buddy/state', method: 'GET' }, s1.res)
查('状态里带配置和日志', s1.桶.体 && s1.桶.体.ok && Array.isArray(s1.桶.体.日志))
查('状态里报了口子开着', s1.桶.体 && s1.桶.体.口子 && s1.桶.体.口子.起没起 === true)

const 配置路由 = 调用.路由.get('/dsh-fish-buddy/config')
查('有配置路由', typeof 配置路由 === 'function')

// ---------- 总开关 ----------
const 关勒 = JSON.parse(JSON.stringify({ 总开关: false, 端口, 会话: 'session-abc', 回调: '', 带上来源: true }))
writeFileSync(join(家, 'fish-buddy-config.json'), JSON.stringify(关勒), 'utf8')
const 五 = await 发({ text: '关着的时候' })
查('总开关关着时不往里塞', 五.码 === 409 && 调用.followup.length === 1)

// ---------- 挂件：认不认得它、能不能一键打开 ----------
writeFileSync(join(家, 'fish-buddy-config.json'), JSON.stringify({
  总开关: true, 端口, 会话: 'session-abc', 回调: '', 挂件路径: '',
}), 'utf8')
const 态2 = 抓住()
await 状态路由({ url: '/dsh-fish-buddy/state', method: 'GET' }, 态2.res)
查('状态里带「下载地址」这一项', 态2.桶.体 && 态2.桶.体.配置 && '下载地址' in 态2.桶.体.配置,
  JSON.stringify(态2.桶.体 && 态2.桶.体.配置))
查('状态里报了挂件在不在', 态2.桶.体 && 态2.桶.体.ok && 态2.桶.体.挂件 && typeof 态2.桶.体.挂件.找到 === 'boolean',
  JSON.stringify(态2.桶.体 && 态2.桶.体.挂件))
查('状态里记得它刚说过话（秒数不为负）', 态2.桶.体 && 态2.桶.体.挂件.最后说话秒前 >= 0, String(态2.桶.体 && 态2.桶.体.挂件.最后说话秒前))
查('「DSH 起来自动开挂件」默认是开的',
   !!(态2.桶.体 && 态2.桶.体.配置 && 态2.桶.体.配置.自动开挂件 === true),
   JSON.stringify(态2.桶.体 && 态2.桶.体.配置 && 态2.桶.体.配置.自动开挂件))

// 关掉之后状态里要如实说关着（默认开、但自己能关）
writeFileSync(join(家, 'fish-buddy-config.json'), JSON.stringify({
  总开关: true, 端口, 会话: 'session-abc', 自动开挂件: false,
}), 'utf8')
const 态关 = 抓住()
await 状态路由({ url: '/dsh-fish-buddy/state', method: 'GET' }, 态关.res)
查('关掉自动开挂件之后状态里是 false',
   !!(态关.桶.体 && 态关.桶.体.配置 && 态关.桶.体.配置.自动开挂件 === false),
   JSON.stringify(态关.桶.体 && 态关.桶.体.配置))
writeFileSync(join(家, 'fish-buddy-config.json'), JSON.stringify({
  总开关: true, 端口, 会话: 'session-abc', 回调: '', 挂件路径: '',
}), 'utf8')

const 开路由 = 调用.路由.get('/dsh-fish-buddy/launch')
查('有「打开挂件」的路由', typeof 开路由 === 'function')
const 开回 = 抓住()
await 开路由([JSON.stringify({})], 开回.res)
查('找不到 exe 时说人话（不乱启动）',
  !!(开回.桶.体 && 开回.桶.体.ok === false && String(开回.桶.体.说).includes('没找到挂件程序')),
  JSON.stringify(开回.桶.体))

// ---------- 一起看：字幕进白板（不进历史） ----------
{
  writeFileSync(join(家, 'fish-buddy-config.json'), JSON.stringify({
    总开关: true, 端口, 会话: 'session-abc', 回调: '', 挂件路径: '',
  }), 'utf8')
  const 推 = async (体) => {
    const r = await fetch('http://127.0.0.1:' + 端口 + '/hands/subtitle', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(体),
    })
    return { 码: r.status, 体: await r.json() }
  }

  const 一 = await 推({ text: '你别走' })
  查('字幕：一句话推得进去', 一.码 === 200 && 一.体.ok === true, JSON.stringify(一.体))
  await 推({ text: '我偏走' })
  await 推({ text: '站住！' })
  await 推({ text: '站住！' })          // 同一句连着来两遍（断句抖动）：只写一次
  await 推({ lines: ['外面下雨了', '伞我拿走了'] })

  // ⭐ 0.2.3：抽帧必须能从**同一个口**（8777 的 /hands/frame）进来。
  //   0.2.1/0.2.2 只把它挂到了 DSH 的 /dsh-fish-buddy/frame，程序打 /hands/frame 全 404（0.2.3 修的）。
  // 让「最近有动静」成立 → 这张帧走「排进字幕里」那条路（有字幕在流时的走法）
  try {
    调用.事件.get('session/event')({ id: 'abc' }, { type: 'turn/end', data: { turn: 77, reason: { kind: 'completed' } } })
  } catch (error) {}
  const 帧回 = await fetch('http://127.0.0.1:' + 端口 + '/hands/frame', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      图片: Buffer.from([0xff, 0xd8, 0xff, 0xd9]).toString('base64'),
      时间点: Date.now(), 尺寸: '2x2', 台词: [{ 差: 0, 文: '你别走' }],
    }),
  })
  const 帧体 = await 帧回.json()
  查('抽帧：程序打 /hands/frame 能进来（不是 404）', 帧回.status === 200 && 帧体.ok === true, JSON.stringify(帧体))
  查('抽帧：收下之后进队列等着她开口', Number(帧体.帧数) >= 1, JSON.stringify(帧体))
  // ⭐ 0.3.1：图不单独发一轮，要**排进字幕里** —— 下一轮白板里应该看到这一行
  {
    const 取白板 = () => {
      const b = 挂的白板.find((o) => o.name === 'watch-subtitles')
      return b ? b.text() : ''
    }
    await 推({ text: '再看一眼这张' })
    const 段 = 取白板()
    查('帧：排进了字幕里（白板里有一行「截了一张图」）', 段.includes('截了一张图'), 段.slice(-200))
    查('帧：那一行带本地文件路径，并说明「想看到就打开这个文件」', 段.includes('就打开这个文件：') && 段.includes('.jpg'), 段.slice(-200))
    查('帧：跟字幕在同一段里（不是另起一轮）', 段.includes('再看一眼这张') && 段.includes('截了一张图'), 段.slice(-200))
  }


  const 白板 = 挂的白板.find((o) => o.name === 'watch-subtitles')
  查('字幕：白板挂上了', Boolean(白板), 挂的白板.map((o) => o.name).join(','))
  // 2026-10-27：白板是纯文本，标了 interpolate:false —— 否则字幕里出现 {{…}} 会被宿主当变量解析，整轮报错
  查('白板标了 interpolate: false（台词里有 {{ }} 也不会炸）', Boolean(白板) && 白板.interpolate === false, 白板 && String(白板.interpolate))
  const 段 = 白板 ? 白板.text() : ''
  查('白板里有最近那几句', ['你别走', '我偏走', '站住！', '外面下雨了', '伞我拿走了'].every((x) => 段.includes(x)), 段.slice(0, 200))
  查('连着重复的一句只出现一次', (段.match(/站住！/g) || []).length === 1, '出现 ' + (段.match(/站住！/g) || []).length + ' 次')
  查('白板没把字幕当消息塞进会话', 调用.followup.length === 1, 'followup=' + 调用.followup.length)
  // ⭐ 0.1.8（不要命令式，只说明「这是什么」）：尾巴只说明是字幕，不下禁令
  查('白板尾巴只说「上面这些是片子里的字幕」', 段.includes('上面这些是片子里的字幕'), 段.slice(-60))
  // ⭐ 0.0.9：头部要说清这是片子里的声音；每句带「多久以前」
  查('头部写清「视频里的声音，不是你俩说的话」', 段.includes('视频里的声音'), 段.slice(0, 80))
  查('每句都带时间（刚刚 / N 秒前 / N 分钟前）', (段.match(/·\s*(刚刚|\d+ 秒前|\d+ 分钟前)｜/g) || []).length >= 4, 段.slice(0, 220))
  查('「刚刚」这种时间真的会出现（刚推的）', /·\s*刚刚｜/.test(段), 段.slice(0, 160))
  // ⭐ 0.3.4：图只出现一次 —— 这张路径贴过以后，下一轮不该再来一遍
  {
    const 取白板2 = () => {
      const b = 挂的白板.find((o) => o.name === 'watch-subtitles')
      return b ? b.text() : ''
    }
    调用.事件.get('session/event')({ id: 'abc' }, { type: 'turn/end', data: { turn: 78, reason: { kind: 'completed' } } })
    await 推({ text: '帧之后的一句' })
    const 段后 = 取白板2()
    查('帧：同一张图的路径不会在下一轮再出现一次', !段后.includes('截了一张图'), 段后.slice(-200))
  }

  const 态3 = 抓住()
  await 状态路由({ url: '/dsh-fish-buddy/state', method: 'GET' }, 态3.res)
  查('状态里能看到字幕条数', Boolean(态3.桶.体 && 态3.桶.体.字幕 && 态3.桶.体.字幕.条数 >= 5), JSON.stringify(态3.桶.体 && 态3.桶.体.字幕))

  const 空 = await 推({ text: '   ' })
  查('空的一句不收', 空.码 === 200 && 空.体.缓存 >= 5, JSON.stringify(空.体))

  // ⭐ 0.0.9：游标式增量投递 —— 上一轮发到哪儿，下一轮从没发的继续，不漏也不重
  const 白板取 = () => {
    const b = 挂的白板.find((o) => o.name === 'watch-subtitles')
    return b ? b.text() : ''
  }
  const 结束一轮 = () => 调用.事件.get('session/event')({ id: 'abc' }, { type: 'turn/end', data: { turn: 1, reason: { kind: 'completed' } } })

  结束一轮()                                   // 把前面那 5 句算「已经发过」
  查('这一轮结束后，白板变空（没有新字幕就不占上下文）', 白板取() === '', 白板取().slice(0, 80))

  await 推({ text: '新来的一句' })
  const 只有新的 = 白板取()
  查('下一轮只发新那句', 只有新的.includes('新来的一句'), 只有新的.slice(0, 120))
  查('不会把已经发过的再发一遍', !只有新的.includes('你别走') && !只有新的.includes('伞我拿走了'), 只有新的.slice(0, 160))

  const 同轮第一次 = 白板取()
  const 同轮第二次 = 白板取()
  查('同一轮里拼两次，内容一样（不会把字幕吃掉）', 同轮第一次 === 同轮第二次, 同轮第一次.slice(0, 80))

  结束一轮()
  查('再结束一轮后又是空的', 白板取() === '', 白板取().slice(0, 80))

  // 一堆没发过的（模拟「隔很久才说话」）：全都算待发，但一轮最多贴 80 句，多的标出来
  for (let i = 1; i <= 90; i++) await 推({ text: '第' + i + '句' })
  const 一大段 = 白板取()
  查('待发太多时只贴最近 80 句，并说明前面还有几句', 一大段.includes('太长没贴') && 一大段.includes('第90句'), 一大段.slice(0, 120))
  结束一轮()
  查('跳过的那批也算发过（不会下一轮又重复挤进来）', 白板取() === '', 白板取().slice(0, 80))
}

// ---------- 麦克风：插件只做转发（设备只有本机进程能枚举） ----------
{
  const { createServer } = await import('node:http')
  const 收到 = []
  const 假挂件 = createServer((req, res) => {
    let 体 = ''
    req.on('data', (c) => { 体 += c })
    req.on('end', () => {
      收到.push({ 路径: req.url, 体 })
      res.setHeader('content-type', 'application/json')
      if (req.url === '/hands/devices') {
        res.end(JSON.stringify({
          ok: true,
          设备: {
            列表: [{ 编号: 3, 名字: '麦克风阵列', 声道: 2, 默认: false },
              { 编号: 7, 名字: 'Steam Streaming Microphone', 声道: 8, 默认: true }],
            当前: { 编号: 3, 名字: '麦克风阵列' },
            通话: false,
          },
        }))
        return
      }
      res.end(JSON.stringify({ ok: true, 说: '换好了' }))
    })
  })
  const 挂端口 = await new Promise((好) => 假挂件.listen(0, '127.0.0.1', () => 好(假挂件.address().port)))
  writeFileSync(join(家, 'fish-buddy-config.json'), JSON.stringify({
    总开关: true, 端口, 会话: 'session-abc', 回调: 'http://127.0.0.1:' + 挂端口 + '/hands/reply',
  }), 'utf8')

  const 麦路由 = 调用.路由.get('/dsh-fish-buddy/mic')
  const 设路由 = 调用.路由.get('/dsh-fish-buddy/mic/set')
  查('有列麦克风的路由', typeof 麦路由 === 'function')
  查('有换麦克风的路由', typeof 设路由 === 'function')

  const a = 抓住()
  await 麦路由({ url: '/dsh-fish-buddy/mic', method: 'GET' }, a.res)
  查('列麦克风走的是挂件那头',
    !!(a.桶.体 && a.桶.体.ok && a.桶.体.设备 && a.桶.体.设备.列表.length === 2), JSON.stringify(a.桶.体))
  查('拿回来的是挂件报的设备', 收到.some((x) => x.路径 === '/hands/devices'))
  查('设备里带着「现在用的是哪个」',
    !!(a.桶.体 && a.桶.体.设备 && a.桶.体.设备.当前 && a.桶.体.设备.当前.编号 === 3),
    JSON.stringify(a.桶.体 && a.桶.体.设备 && a.桶.体.设备.当前))

  const b = 抓住()
  await 设路由([JSON.stringify({ index: 7, name: 'Steam Streaming Microphone' })], b.res)
  查('换麦克风把选择转发给了挂件',
    !!(b.桶.体 && b.桶.体.ok && 收到.some((x) => x.路径 === '/hands/device' && x.体.includes('Steam Streaming Microphone'))),
    JSON.stringify(b.桶.体))

  const b2 = 抓住()
  await 设路由([JSON.stringify({ index: null, name: '' })], b2.res)
  const 默认请求 = 收到.filter((x) => x.路径 === '/hands/device').pop()
  查('选「系统默认」也说得过去（发的是 null）', !!(b2.桶.体 && b2.桶.体.ok && 默认请求 && 默认请求.体.includes('"index":null')),
    String(默认请求 && 默认请求.体))

  // 没填回调地址 → 明说不知道挂件在哪，别瞎报错
  writeFileSync(join(家, 'fish-buddy-config.json'), JSON.stringify({
    总开关: true, 端口, 会话: 'session-abc', 回调: '',
  }), 'utf8')
  const c = 抓住()
  await 麦路由({ url: '/dsh-fish-buddy/mic', method: 'GET' }, c.res)
  查('没填回调地址时说得明白',
    !!(c.桶.体 && c.桶.体.ok === false && String(c.桶.体.说).includes('回话递回')), JSON.stringify(c.桶.体))

  假挂件.close()
  await 等(50)
}

// ---------- 图片块：宿主要的是「附件引用」，不是内联 base64 ----------
//   以前把 `{type:'image', data:'/9j/…'}` 直接塞进 content，宿主读 part.attachment.attachmentId
//   直接炸，那串 base64 还会整段灌进会话。现在必须走 ctx.attachments.saveImage()。
{
  const 源码 = readFileSync(new URL('../lib/host.js', import.meta.url), 'utf8')
  查('图：不再拼内联 base64 的图片块', !/type:\s*'image',\s*data:/.test(源码), '')
  查('图：走 attachments.saveImage 换附件引用', 源码.includes('.saveImage('), '')
  查('图：content 里带的是 attachment 引用',
    /type:\s*'image',\s*attachment:/.test(源码), '')
}

// ---------- 收摊 ----------
for (const 清 of 调用.清理) { try { 清() } catch (e) {} }
await 等(100)
// ⭐ 0.5.1：**rc.3 那种「没有 timer / attachments」的宿主也不能崩**
//   （真机报过：inject 里写不存在的服务 → 插件加载失败 → DSH 自愈砍清单 → 反复崩）
{
  // ⚠ 真机证据（DSH 0.2.1-rc.3）：cordis 的 ctx 代理在读**没在 inject 里声明**的服务时会**直接抛**
  //   `cannot get property "timer" without inject` —— 返回 undefined 是不对的模拟。
  //   所以这里照那个行为抛，才能验出「靠 typeof 探测」那种写法。
  const 精简 = {
    on: () => () => {},
    effect: (工) => { const 清 = 工(); return 清 },
    webServer: { register: () => () => {} },
    agents: { get: () => undefined, list: () => [] },
    get(名) {
      throw new Error('cannot get property "' + 名 + '" without inject')
    },
  }
  let 崩了 = ''
  try {
    插件.apply(精简, {})
  } catch (e) {
    崩了 = String((e && e.message) || e)
  }
  查('没有 timer / attachments 的宿主也能装上（不抛错）', 崩了 === '', 崩了)
  await 等(150)
  查('inject 数组里不含 timer / attachments',
    (Array.isArray(插件.inject) ? 插件.inject : []).every((x) => x !== 'timer' && x !== 'attachments'),
    JSON.stringify(插件.inject))
}


// ---------- 截图自动清理（0.7.9）----------
{
  const 图家 = mkdtempSync(join(tmpdir(), 'fishshots-'))
  const 造 = (名, 多少天前) => {
    const 路 = join(图家, 名)
    writeFileSync(路, 'x')
    const 旧 = Date.now() - 多少天前 * 24 * 60 * 60 * 1000
    utimesSync(路, new Date(旧), new Date(旧))
  }
  造('新1.jpg', 0)
  造('新2.jpg', 1)
  造('老1.jpg', 40)
  造('老2.jpg', 45)
  writeFileSync(join(图家, '别动.txt'), 'x')
  let 果 = 插件.清旧截图(图家, 30, 0)
  查('截图清理：太老的删掉、新的留着', 果.删了 === 2 && 果.剩 === 2, JSON.stringify(果))
  查('截图清理：不是图片的不动', existsSync(join(图家, '别动.txt')))
  果 = 插件.清旧截图(图家, 0, 1)
  查('截图清理：张数超了只留最新的', 果.删了 === 1 && 果.剩 === 1, JSON.stringify(果))
  果 = 插件.清旧截图(图家, 0, 0)
  查('截图清理：两条都是 0 就什么都不删', 果.删了 === 0 && 果.剩 === 1, JSON.stringify(果))
  果 = 插件.清旧截图(join(图家, '没有这个目录'), 30, 100)
  查('截图清理：目录还不存在也不报错', 果.删了 === 0 && 果.剩 === 0, JSON.stringify(果))
  rmSync(图家, { recursive: true, force: true })
}


// ---------- 拼图：只拼 1 分钟以前的、够 3 张才拼（1.6.0）----------
{
  const t0 = 1700000000000
  const 老 = (n) => ({ 路: 'old' + n + '.jpg', 时: t0 - 90000 })
  const 新 = (n) => ({ 路: 'new' + n + '.jpg', 时: t0 - 5000 })
  let r = 插件.该拼哪几张([老(1), 老(2), 老(3)], t0)
  查('拼图：3 张老的 → 该拼', r.该拼 === true && r.老的.length === 3, JSON.stringify(r))
  r = 插件.该拼哪几张([老(1), 老(2)], t0)
  查('拼图：2 张老的 → 也拼', r.该拼 === true && r.老的.length === 2, JSON.stringify(r))
  r = 插件.该拼哪几张([老(1)], t0)
  查('拼图：只有 1 张老的 → 不拼', r.该拼 === false && r.老的.length === 1, JSON.stringify(r))
  r = 插件.该拼哪几张([老(1), 老(2), 老(3), 新(1), 新(2)], t0)
  查('拼图：1 分钟内的新图不参与拼', r.该拼 === true && r.老的.length === 3 && r.新的.length === 2, JSON.stringify(r))
  r = 插件.该拼哪几张([新(1), 新(2), 新(3)], t0)
  查('拼图：全是新图 → 一张都不拼', r.该拼 === false && r.新的.length === 3, JSON.stringify(r))
  r = 插件.该拼哪几张([{ 路: '', 时: t0 - 90000 }, null, 老(1)], t0)
  查('拼图：没路径/空项直接丢掉', r.老的.length === 1 && r.该拼 === false, JSON.stringify(r))
}

rmSync(家, { recursive: true, force: true })

const 失败 = 结果.filter((x) => !x.过).length
console.log('\n共 ' + 结果.length + ' 项，失败 ' + 失败 + ' 项')
process.exit(失败 ? 1 : 0)
