// 鱼搭子 · DSH 这半边（基座）
//
// 干三件事，没有界面上的花活：
//   ① 在本机开一个口（默认 127.0.0.1:8777），收桌面挂件发来的话 → 送进她绑定的那间会话
//   ② 她那间会话说完一轮 → 把回话递回挂件（POST 到挂件给的回调地址）
//   ③ 给设置页提供状态：绑哪间、收了几条、最近几条日志、最后一句回话
//
// ⚠ 为什么自己开一个端口、不用 DSH 的 webServer：
//    挂件是独立程序，不该知道 DSH 跑在哪个端口上；固定 8777 它才好发。
//    （设置页那几条路由仍然走 DSH 的 webServer，那是浏览器在用。）

import { spawn } from 'node:child_process'
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, writeFileSync, createWriteStream, renameSync, rmSync, readdirSync, statSync, unlinkSync } from 'node:fs'
import { homedir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { randomUUID } from 'node:crypto'

export const name = 'fish-buddy'

/**
 * 需要宿主提供什么。
 *
 * ⭐ 0.4.10：**能可有可无的一律别写成必需**。
 *   以前 6 个全写成必需（agents / sessions / sessionTitle / webServer / timer / attachments）。
 *   Cordis 里「必需服务缺失」会让这个插件挂不起来，装在一个没有 `attachments`（或没有 `timer`）的
 *   宿主上时，整个 profile 的组装都可能跟着失败 —— 表现就是「装完 DSH 起不来」。
 *   现在只把真正离不开的两个写成必需，其余都是可选（代码里本来就有 `ctx.get(...)` 的兜底）。
 */
// 这个宿主（Cordis）只认**数组**形式的 inject：数组里每一项都是「必需服务」。
//   ⚠ 写成 { required, optional } 会被当成两个叫「required」「optional」的服务名，
//   插件就一直 pending 挂不起来 —— 所以只能写数组，只放真正离不开的两个。
//   其余（sessions / sessionTitle / timer / attachments）一律不声明，用 ctx.get(...) 现取现用，
//   拿不到就降级（列不出会话 / 发不了图），而不是让整个插件挂掉。
export const inject = ['agents', 'webServer']

// ---------- 常量 ----------

const 目录 = process.env.DSH_HOME || join(homedir(), '.dsh')
const 配置文件 = join(目录, 'fish-buddy-config.json')
const 路由前缀 = '/dsh-fish-buddy'
// GitHub 问不到「最新 Release」时用这个兜底（版本号变了要跟着改）
const 下载兜底地址 = 'https://github.com/Yuuyuko-uu/dsh-fish-buddy/releases/latest/download/fish-buddy-v1.0.9.exe'
const 日志上限 = 60

const 默认配置 = {
  总开关: true,          // 关掉 = 挂件发什么都不往里塞（调试用）
  端口: 8777,            // 挂件往这个端口发
  会话: '',              // 绑哪一间（'session-…' 或裸 id 都认）
  回调: '',              // 她的回话递到哪：'http://127.0.0.1:8778/hands/reply'
  带上来源: false,       // 塞进会话时前面加一句「（你说的）」。默认关：电话里说的话就该像本人说的
  挂件路径: '',          // 那个 exe 在哪；留空就自动找几个常见位置
  下载地址: '',          // 「去下载挂件」按钮跳到哪（填 Release 页面地址）
  // ⭐ 0.0.7：DSH 一起来就把挂件打开（默认开着，不然每次都得手动点）
  自动开挂件: true,
  // 挂件回话口的端口（回调没填时拿它探活；挂件默认 8778）
  回话端口: 8778,
  // ⭐ 0.0.5：陪看时让她自己开口 —— 0 = 关；0.0.8 起单位是**秒**
  // ⭐ 0.6.1：**游戏模式**里主动说一句的间隔（秒）。0 = 不说。
  //   ⚠ 只在「截图怎么送 = 攒着」时生效；「每张都说」那一档截图本来就会叫醒她，不叠这个。
  游戏搭话秒: 180,
  // ⭐ 0.7.9：插件自己攒的截图（陪看抽帧、开口/带图那几张）会一直堆着不清。
  //   这两个数管自动清：留几天 / 最多几张，0 = 那一条不限（两条都 0 = 不清）。
  //   只删插件自己这个目录里的图，别的地方不动。
  截图保留天: 30,
  截图最多张: 800,
  随机搭话秒: 600,       // 陪看时每多少秒找机会说一句（0 = 只看不说）
  搭话最多秒: 0,         // 随机间隔的上限（0 = 自动 = max(下限×4, 120)）
  冷却最短秒: 60,        // 两条自发消息（发图 / 搭话）之间至少隔多久
  冷却最长秒: 150,       // ……最多隔多久（每次都在这两个数之间重掷）
  安静秒: 8,             // 多久没有对话就算「她没在说话」（这时截图直接发）
  随机搭话概率: 0.35,    // 掷中的概率（纯骰子，不花 token）
}

/**
 * ⭐ 0.7.9：清掉插件自己攒的旧截图。
 *
 * 陪看抽帧、开口那张、说话带的那张，全落在 `~/.dsh/fish-buddy-frames`；
 * 以前只进不出，用久了能堆到几十上百 MB。这里按两条清：
 *   · 比「留几天」更老的删掉（0 = 按天数不限）
 *   · 从新到旧数下去，超过「最多几张」的删掉（0 = 按张数不限）
 * 两条都 0 就什么都不做。只认图片后缀，别的一律不碰。
 *
 * 返回 `{ 删了, 剩 }`；目录还不存在也算正常（返回 0/0）。
 */

/**
 * ⭐ 1.6.0：哪些图该拼 —— **只拼 1 分钟以前的**，老的够 2 张就拼。
 * 刚截的那张（还有她自己截图说话发的那张）一律不拼，单发。
 * 纯函数，方便单测。
 */
export function 该拼哪几张(张们, 现在毫秒) {
  const 现在_ = Number.isFinite(Number(现在毫秒)) ? Number(现在毫秒) : Date.now()
  const 老的 = []
  const 新的 = []
  for (const x of (Array.isArray(张们) ? 张们 : [])) {
    if (!x || !x.路) continue
    const 时 = Number((x && x.时) || 0)
    if (时 > 0 && 现在_ - 时 >= 60 * 1000) 老的.push(x)
    else 新的.push(x)
  }
  return { 老的, 新的, 该拼: 老的.length >= 2 }
}

export function 清旧截图(目录, 保留天 = 0, 最多张 = 0, 现在毫秒 = Date.now()) {
  const 结果 = { 删了: 0, 剩: 0 }
  let 名们 = []
  try {
    名们 = readdirSync(目录).filter((x) => /\.(jpg|jpeg|png)$/i.test(String(x)))
  } catch (error) {
    return 结果
  }
  const 项们 = []
  for (const 名 of 名们) {
    try {
      const 资 = statSync(join(目录, 名))
      if (!资.isFile()) continue
      项们.push({ 路: join(目录, 名), 时: 资.mtimeMs })
    } catch (error) {
      // 刚好被删 / 没权限：跳过，不影响别的
    }
  }
  项们.sort((a, b) => b.时 - a.时)               // 新 → 旧
  const 天 = 24 * 60 * 60 * 1000
  const 要删 = []
  项们.forEach((项, i) => {
    const 太老 = 保留天 > 0 && 现在毫秒 - 项.时 > 保留天 * 天
    const 太多 = 最多张 > 0 && i >= 最多张
    if (太老 || 太多) 要删.push(项.路)
  })
  for (const 路 of 要删) {
    try {
      unlinkSync(路)
      结果.删了 += 1
    } catch (error) {
      // 删不掉就算了，下一轮再来
    }
  }
  结果.剩 = 项们.length - 结果.删了
  return 结果
}

/**
 * 0.4.1 改了插件名，配置文件名跟着从 fishbuddy-config.json 换成 fish-buddy-config.json。
 * 新文件还没有、老文件还在 → 原样搬一份过去（老文件留着不动）。
 * 返回：搬了 true / 没搬 false（新文件已存在、没有老文件、老文件是坏的 —— 都算没搬）。
 */
export function 搬老配置(家目录) {
  const 新 = join(家目录, 'fish-buddy-config.json')
  const 老 = join(家目录, 'fishbuddy-config.json')
  try {
    if (existsSync(新) || !existsSync(老)) return false
    const 原文 = readFileSync(老, 'utf8').replace(/^\uFEFF/, '')
    JSON.parse(原文)                    // 坏的就不搬：宁可走默认值，也别写一份坏配置过去
    mkdirSync(家目录, { recursive: true })
    writeFileSync(新, 原文, 'utf8')
    return true
  } catch (error) {
    return false
  }
}

// ---------- 小工具 ----------

const 会话键 = (v) => {
  const s = String(v == null ? '' : v).trim()
  return s.startsWith('session-') ? s.slice('session-'.length) : s
}

const 现在 = () => Date.now()

/** 取消息正文（正文块优先，兼容几种摆放） */
/**
 * ⭐ 0.0.5：这一下该不该让它自己开口。纯函数，方便自测。
 * ⭐ 0.0.8：间隔改成**秒**；老的「间隔分钟」还认，别把老配置弄坏。
 * 条件：开着（间隔 > 0）、有字幕在流（不对着黑屏说话）、距上次够久、骰子掷中。
 */
export function 要搭话(o) {
  let 间隔秒 = Number((o && o.间隔秒) || 0)
  if (!(间隔秒 > 0)) 间隔秒 = Number((o && o.间隔分钟) || 0) * 60
  if (!(间隔秒 > 0)) return false
  if (!(o && o.有字幕)) return false
  const 现 = Number(o.现在) || 0
  const 上次 = Number(o.上次) || 0
  // ⭐ 1.0.3（「固定 30 秒会显得很规律」）：在设定的间隔上再随机浮动 ±35%。
  //   填 30 秒 → 实际大概 20~40 秒之间才轮到；测试不传「浮」时按 0.5 算（等于原来的间隔，不会飘）。
  //
  // ⭐⭐ 0.2.4（2026-10-27）：
  //   ±35% 还是太规律 —— 现在是**范围内真随机**：
  //     下限 = 设定秒数（最小 20 秒），上限 = max(下限×4, 120 秒)。
  //   下限填 15 → 实际落在 20~120 秒之间，偶尔很快、偶尔很久，没有"到点"的感觉。
  //   `浮` 传 0~1 时仍按旧算法（测试靠它得到确定值），不传才是真随机。
  const 浮 = Number.isFinite(o && o.浮) ? Math.max(0, Math.min(1, Number(o.浮))) : null
  let 有效间隔
  if (浮 === null) {
    // 下限就是填的那个数（最少 5 秒）—— 填多少就至少隔多久，别偷偷改成 20
    const 下限 = Math.max(5, 间隔秒)
    const 上限 = Math.max(下限 * 4, 120)
    有效间隔 = 下限 + (上限 - 下限) * Math.random()
  } else {
    有效间隔 = 间隔秒 * (0.65 + 0.7 * 浮)
  }
  if (上次 && 现 - 上次 < 有效间隔 * 1000) return false
  const 概率 = Math.max(0, Math.min(1, Number(o.概率 == null ? 0.35 : o.概率)))
  const 骰 = typeof o.骰子 === 'number' ? o.骰子 : Math.random()
  return 骰 < 概率
}

const 取正文 = (message) => {
  const 节点们 = [message, message && message.content]
  for (const 节点 of 节点们) {
    if (!节点) continue
    if (typeof 节点 === 'string') return 节点
    if (Array.isArray(节点)) {
      const 段 = 节点.filter((b) => b && b.type === 'text' && typeof b.text === 'string').map((b) => b.text)
      if (段.length) return 段.join('\n')
    }
  }
  return ''
}

export function apply(ctx, inlineConfig) {
  // ---------- 配置 ----------
  const 进制规整 = (o) => {
    const 合 = { ...默认配置, ...(o && typeof o === 'object' ? o : {}) }
    合.端口 = Math.max(1024, Math.min(65535, Number(合.端口) || 默认配置.端口))
    合.会话 = String(合.会话 || '').trim()
    合.回调 = String(合.回调 || '').trim()
    合.总开关 = 合.总开关 !== false
    合.带上来源 = 合.带上来源 === true  // 默认不开（以前是默认开，见 0.2.8 那条注释）
    // ⭐ 0.0.8：老配置是「分钟」，现在统一用「秒」
    const 原 = (o && typeof o === 'object') ? o : {}
    if (!('随机搭话秒' in 原) && '随机搭话分钟' in 原) {
      合.随机搭话秒 = Math.max(0, Number(原.随机搭话分钟) || 0) * 60
    }
    合.随机搭话秒 = Math.max(0, Math.min(14400, Number(合.随机搭话秒) || 0))
    合.游戏搭话秒 = Math.max(0, Math.min(14400, Number(合.游戏搭话秒) || 0))
    合.搭话最多秒 = Math.max(0, Math.min(14400, Number(合.搭话最多秒) || 0))
    合.冷却最短秒 = Math.max(10, Math.min(3600, Number(合.冷却最短秒) || 60))
    合.冷却最长秒 = Math.max(合.冷却最短秒, Math.min(7200, Number(合.冷却最长秒) || 150))
    合.安静秒 = Math.max(1, Math.min(600, Number(合.安静秒) || 8))
    合.截图保留天 = Math.max(0, Math.min(3650, Number(合.截图保留天) || 0))
    合.截图最多张 = Math.max(0, Math.min(200000, Number(合.截图最多张) || 0))
    delete 合.随机搭话分钟
    return 合
  }

  const 读配置 = () => {
    搬老配置(目录)   // 0.4.1 换了文件名：第一次读之前先把老配置搬过来
    try {
      // ⚠ 配置是用户手改过的：可能带 BOM（PowerShell 写的），先削掉再解析
      const 原文 = readFileSync(配置文件, 'utf8').replace(/^\uFEFF/, '')
      return 进制规整(JSON.parse(原文))
    } catch (error) {
      return 进制规整(inlineConfig)
    }
  }

  const 写配置 = (o) => {
    const 合 = 进制规整(o)
    try {
      mkdirSync(目录, { recursive: true })
      writeFileSync(配置文件, JSON.stringify(合, null, 2), 'utf8')
    } catch (error) {
      记账('配置没写进去：' + 说(error))
    }
    return 合
  }

  const 说 = (e) => String((e && e.message) || e)

  // ---------- 内存状态 ----------
  const 状态 = {
    收到条数: 0,
    送出条数: 0,
    递回条数: 0,
    最后收到: 0,          // 挂件最后一次发话的时间（判断「连上了没」）
    最后回话: { 会话: '', 文本: '', 时: 0 },
    日志: [],
    口子: { 起没起: false, 端口: 0, 错: '' },
    下载: null,           // ⭐ 0.4.7：下载挂件的进度
  }

  const 记账 = (话) => {
    状态.日志.unshift({ 时: 现在(), 说: String(话 || '') })
    if (状态.日志.length > 日志上限) 状态.日志.length = 日志上限
  }

  /**
   * ⭐ 0.5.2：取一个**没写进 inject** 的宿主服务。
   *
   * cordis 的 ctx 代理在读 `ctx.xxx` / `ctx.get('xxx')` 时，**只要 xxx 没在 inject 里声明就直接抛**
   * （`cannot get property "timer" without inject`）—— 所以「用 typeof 探测在不在」这条路走不通，
   * 探测本身就是抛错。唯一安全的办法是包 try/catch。
   */
  const 取服务 = (名) => {
    try {
      return ctx.get(名) || null
    } catch (error) {
      return null
    }
  }

  // ---------- 会话清单（设置页的下拉用） ----------
  const 会话清单 = () => {
    const 出 = []
    try {
      const 会话服务 = 取服务('sessions')
      const 标题服务 = 取服务('sessionTitle')
      if (会话服务 && typeof 会话服务.list === 'function') {
        for (const s of 会话服务.list()) {
          let 标题 = ''
          try {
            const 快照 = 标题服务 && typeof 标题服务.get === 'function' ? 标题服务.get(s) : undefined
            标题 = 快照 && 快照.title ? String(快照.title) : ''
          } catch (error) {}
          出.push({ id: String(s.id), 标题 })
        }
      }
    } catch (error) {
      记账('列会话出错：' + 说(error))
    }
    return 出
  }

  // ---------- ① 把话送进会话 ----------
  // ⭐ 0.4.2：绑了会话就整间都算 —— 回话一律递回挂件（以前只递「挂件叫起来的那一轮」，
  //   结果光挂着悬浮窗、或者它自己搭话，回话都递不出去，气泡/弹幕就永远不冒）。
  // ⭐ 1.1.6：陪看到底开着没 —— 挂件每次开/停都会来说一声。
  //   以前不看这个，光凭「最近有字幕」就自己开口：陪看早关了，旧字幕还在 30 秒窗口里，
  //   于是就冒出一句「你俩正一起看着」（人根本没在看）。
  let 陪看开着 = false
  // ⭐ 1.0.3：「陪看时它自己开口」的上一次时间。放在这么前面，是因为 turn/end 那边也要用它
  //   （任何一轮结束都重开计时，免得刚回完话又到点自己说一句）。
  let 上次搭话 = 0
  // ⭐ 1.0.3：绑的会话没开着时只记一次，别每 5 秒刷一行
  let 说过了没活着 = false
  // ⭐ 0.2.1：抽帧队列（声明放前面 —— 搭话和 turn/end 都要用它）
  //   [{序, 时, 文件, 大小, 尺寸, 台词, 已发}]
  const 帧账 = []

  const 送进会话 = async (正文, 指定会话) => {
    const 配置 = 读配置()
    if (!配置.总开关) return { ok: false, 说: '总开关关着，没往里送' }
    const 目标 = String(指定会话 || 配置.会话 || '').trim()
    if (!目标) return { ok: false, 说: '还没绑定会话 —— 去 DSH 设置 → 鱼搭子 里选一间' }

    let agent
    try {
      agent = ctx.agents.get(目标)
      if (agent === undefined) agent = ctx.agents.get('session-' + 会话键(目标))
    } catch (error) {
      return { ok: false, 说: '找不到那间会话：' + 说(error) }
    }
    if (!agent) return { ok: false, 说: '那间会话没开着（DSH 里先把它打开一次）' }

    // ⭐ 0.2.8：以前写成「（挂件里说的话）」，电话里说的话也这么标，
    //   看着很怪 —— 那是在说话，不是「挂件在说话」。默认干脆不加；要加也只说「你说的」。
    const 文本 = 配置.带上来源 ? '（你说的）' + 正文 : 正文
    const 内容 = [{ type: 'text', text: 文本 }]
    try {
      // ⚠ 必须 await：followup 返回 Promise，不接住的话 reject 会变成未处理异常，把整个宿主带走
      await agent.followup({ id: randomUUID(), role: 'user', content: 内容, source: { kind: 'user' } })
    } catch (error) {
      return { ok: false, 说: '塞进去失败了：' + 说(error) }
    }

    状态.送出条数 += 1
    try {
      const 会话服务 = 取服务('sessions')
      if (会话服务 && typeof 会话服务.flush === 'function') await 会话服务.flush(agent.session)
    } catch (error) {}
    记账('挂件说的话送进会话了：' + 正文.slice(0, 40) + (正文.length > 40 ? '…' : ''))
    return { ok: true, 说: '送进去了' }
  }

  // ---------- ② 她的回话递回挂件 ----------
  // ⭐ 0.4.2：现在每轮都递，挂件没开着的时候别每轮都去撞一遍 —— 失败后静音 30 秒再试。
  let 递回静音到 = 0
  const 递回 = async (文本) => {
    const 配置 = 读配置()
    if (!配置.回调) return { ok: false, 说: '没配回调地址（设置页里填）' }
    if (现在() < 递回静音到) return { ok: false, 说: '挂件刚才没接住，过一会儿再试' }
    try {
      const r = await fetch(配置.回调, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: 文本, session: 配置.会话 }),
      })
      if (!r.ok) throw new Error('HTTP ' + r.status)
      递回静音到 = 0
      状态.递回条数 += 1
      return { ok: true, 说: '递回去了' }
    } catch (error) {
      递回静音到 = 现在() + 30000
      记账('回话没递到挂件：' + 说(error))
      return { ok: false, 说: 说(error) }
    }
  }

  // 一轮里她说的最后一段（同一间会话分开记，两间同时说话也不会串）
  const 本轮 = new Map()
  const 已递 = new Set()
  // ⭐ 0.3.2：没动静的时候，图直接发过去；有字幕在流的时候，图才排进字幕里。
  let 最近动静 = 0
  // ⭐ 0.3.4：一张图只能出现一次 —— 路径行看过的、直接发过的，都记在这里
  const 已发帧 = new Set()
  // ⭐ 0.3.5：截图直发 和 自动搭话 会「左脚踩右脚」—— 两条共用一个冷却，
  //   任何一条自发消息之后 90 秒内，另一条不发（图改走字幕批，不丢）。
  let 上次自发 = 0
  // ⭐ 0.3.6：冷却不能是死板的 90 秒 —— 那又变成「固定节奏」了。
  //   每次自发消息（发图 / 搭话）之后，**重新掷一个 60~150 秒**的冷却。
  let 下次自发最早 = 0
  // ⭐ 0.3.9：别再分成四个数 —— 就一个「多久说一句」的区间，
  //   发图 和 自己开口 共用它：谁刚发过，下一次就重掷一个落在这个区间里的时间。
  const 掷冷却 = () => {
    const c = 读配置()
    const 报的 = 挂件搭话秒()
    const 下限 = Math.max(5, Number(报的 === null ? c.随机搭话秒 : 报的) || 5)
    const 上限 = Math.max(下限, 节奏('搭话最多秒', Number(c.搭话最多秒) || 0) || Math.max(下限 * 4, 120))
    return 现在() + (下限 + Math.random() * (上限 - 下限)) * 1000
  }

  const 解绑监听 = ctx.on('session/event', (session, event) => {
    const 键 = 会话键(session && session.id)
    const 配置 = 读配置()
    if (!键 || 键 !== 会话键(配置.会话)) return
    最近动静 = 现在()   // 有字幕在流 / 它在回话，都算「有动静」
    const 类型 = event && event.type
    const 数据 = (event && event.data) || {}

    if (类型 === 'assistant/message') {
      if (数据.interrupted) {
        本轮.delete(键)
        return
      }
      const 文 = String(取正文(数据.message) || '').trim()
      if (文) 本轮.set(键, { 轮号: 数据.turn, 文本: 文 })
      return
    }

    if (类型 === 'turn/end') {
      // ⭐ 0.0.9：这一轮真的结束了 → 把字幕游标推到本轮拼到的位置（下一轮只发新的）
      字幕这轮发完了(键)
      // ⭐ 1.0.3：**只要有一轮对话结束，就把「自己开口」的计时重开** ——
      //   说完话、它刚回完又到点自己说一句，会像"连着说"。从这一刻重新计时。
      上次搭话 = 现在()
      const 完成 = !!(数据.reason && 数据.reason.kind === 'completed')
      const 攒的 = 本轮.get(键)
      const 标记 = 键 + ':' + String(数据.turn)
      本轮.delete(键)
      if (!完成 || !攒的 || 攒的.轮号 !== 数据.turn || 已递.has(标记)) return
      已递.add(标记)
      if (已递.size > 500) 已递.clear()

      状态.最后回话 = { 会话: 配置.会话, 文本: 攒的.文本, 时: 现在() }
      // 这间会话绑着挂件：一轮说完就把最后那句递回去（气泡 / 弹幕都靠它）。
      // 不管这轮是谁起的头 —— 电话、它自己搭话、你在 DSH 里直接打字，都一样。
      void 递回(攒的.文本)
    }
  })

  ctx.effect(() => () => {
    try {
      解绑监听()
    } catch (error) {}
  })

  // ---------- 陪看：字幕白板（游标式增量投递）----------
  //  ⭐ 0.0.9（2026-10-26）：游标式投递 —— 上一轮发到哪儿结束，下一轮就从没发的继续，不漏也不多发。
  //    所以这里不是「按时间窗截一段」而是**排队 + 游标**：
  //      · 每条字幕进队列时拿一个递增的「序号」；
  //      · 白板只拼「序号 > 已发到」的那些；
  //      · 等这一轮真正结束（turn/end）才把「已发到」推到本轮拼到的位置。
  //    好处：中间我隔一小时没说话也不丢句；同一句不会被塞两遍；全程本地数字运算，不花 token。
  const chr10 = String.fromCharCode(10)
  const 队列上限 = 400         // 最多存这么多条（再多从最旧的丢，并记「丢了 N 句」）
  const 单轮最多 = 80          // 一轮最多拼这么多句（太长就只发最近这些，并标明前面还有几句）
  const 字幕们 = new Map()      // 会话键 -> { 行: [{序, 时, 文}], 下一条: n, 已发到: 0, 本轮到: 0, 丢: 0, 最后: 0 }

  const 拿字幕桶 = (键) => {
    let 桶 = 字幕们.get(键)
    if (!桶) {
      桶 = { 行: [], 下一条: 1, 已发到: 0, 本轮到: 0, 丢: 0, 最后: 0 }
      字幕们.set(键, 桶)
    }
    return 桶
  }

  /**
   * ⭐ 1.1.1：陪看停了 —— 缸里攒的、还没发出去的字幕全扔掉。
   * 只清内容，不重置序号（游标跟着「下一条」走，免得下一轮又把旧的当成新的）。
   */
  const 清空字幕桶 = () => {
    const 键 = 会话键(读配置().会话)
    const 桶 = 字幕们.get(键)
    if (!桶) return 0
    const 丢了几条 = 桶.行.filter((x) => x.序 > 桶.已发到).length
    桶.行.length = 0
    桶.已发到 = 桶.下一条
    桶.本轮到 = 0
    return 丢了几条
  }

  const 收一句字幕 = (键, 文, 时) => {
    const 桶 = 拿字幕桶(键)
    const 净 = String(文 || '').trim()
    if (!净) return
    // 同一句重复推上来（挂件那边断句抖动）就别写两遍
    if (桶.行.length && 桶.行[桶.行.length - 1].文 === 净) return
    桶.行.push({ 序: 桶.下一条++, 时: Number(时) || 现在(), 文: 净.slice(0, 300) })
    桶.最后 = 现在()
    while (桶.行.length > 队列上限) {
      const 丢的 = 桶.行.shift()
      if (丢的 && 丢的.序 > 桶.已发到) 桶.丢 += 1      // 没发过就被挤掉的，记一笔
    }
  }

  /**
   * ⭐ 0.3.1：**截图不是单独一条消息** ——
   *   它是在那两句字幕之间截的，就该像字幕一样排进同一批、同一条消息里。
   *   图本身塞不进「白板」（白板只能是文字），所以这里给的是**本地文件路径 + 尺寸大小**。
   */
  const 收一帧行 = (键, 条) => {
    const 桶 = 拿字幕桶(键)
    if (!桶) return
    桶.行.push({
      序: 桶.下一条++,
      时: Number(条 && 条.时) || 现在(),
      文: '',
      帧: { 文件: String((条 && 条.文件) || ''), 尺寸: String((条 && 条.尺寸) || ''), 大小: Number((条 && 条.大小) || 0) },
    })
    桶.最后 = 现在()
    while (桶.行.length > 队列上限) {
      const 丢的 = 桶.行.shift()
      if (丢的 && 丢的.序 > 桶.已发到) 桶.丢 += 1
    }
  }

  /** 一句字幕是「多久以前」说的（相对时间比钟点有用，而且每轮现拼所以永远新鲜） */
  const 多久前 = (时) => {
    const 秒 = Math.max(0, Math.round((现在() - (Number(时) || 0)) / 1000))
    if (秒 <= 3) return '刚刚'
    if (秒 < 60) return 秒 + ' 秒前'
    const 分 = Math.round(秒 / 60)
    return 分 + ' 分钟前'
  }

  /** 还没有「发到」的那些（游标之后） */
  const 待发字幕 = (键) => {
    const 桶 = 字幕们.get(键)
    if (!桶) return []
    return 桶.行.filter((x) => x.序 > 桶.已发到)
  }

  /**
   * 每轮拼的那一段（没有新字幕时返回空串 —— 空串不占上下文）。
   * ⚠ 这里**只标记「本轮到哪儿」，不推进「已发到」** —— 推进放在 turn/end，
   *   否则同一轮里 text() 被调用两次就会把内容吃掉。
   */
  const 字幕白板 = (键) => {
    const 桶 = 字幕们.get(键)
    if (!桶) {
      记账('白板：这间会话还没有字幕桶（可能是刚重启、或者字幕绑到别处去了）')
      return ''
    }
    const 待 = 待发字幕(键)
    if (!待.length) {
      // ⭐ 0.1.6（排查「番那几段一句没收到」）：空的时候也留一行证据，
      //   不然「是没收到」还是「白板根本没给」就永远分不清。
      记账('白板：这一轮没有新字幕（已发到 ' + 桶.已发到 + ' / 共 ' + 桶.行.length + ' 句）')
      return ''
    }
    const 发 = 待.length > 单轮最多 ? 待.slice(待.length - 单轮最多) : 待
    const 跳过 = 待.length - 发.length
    桶.本轮到 = 发[发.length - 1].序
    记账('白板：这一轮贴了 ' + 发.length + ' 句（序 ' + 发[0].序 + '~' + 发[发.length - 1].序
      + '，共 ' + 桶.行.length + ' 句）第一句：「' + String(发[0].文).slice(0, 24) + '」')
    const 头 = '【你正在听的】（视频里的声音，不是你俩说的话'
      + (跳过 > 0 ? '；前面还有 ' + 跳过 + ' 句太长没贴' : '')
      + (桶.丢 > 0 ? '；再早还有 ' + 桶.丢 + ' 句被挤掉了' : '') + '）'
    const 行们 = 发.map((x) => {
      if (x.帧) {
        // ⚠ 0.3.4：这张图要是已经直接发过去（或已经贴过），就别再出现第二次
        if (已发帧.has(String(x.帧.文件 || ''))) return null
        const 大小 = x.帧.大小 >= 1024 ? Math.round(x.帧.大小 / 1024) + 'KB' : (x.帧.大小 || 0) + 'B'
        return '· ' + 多久前(x.时) + '｜〔这一句是画面〕截了一张图（' + (x.帧.尺寸 || '?')
          + '，' + 大小 + '）—— 想看到这张画面，就打开这个文件：' + x.帧.文件
      }
      return '· ' + 多久前(x.时) + '｜' + x.文
    }).filter(Boolean)
    // 贴出去的帧行就算用过了，后面不再重贴
    for (const x of 发) if (x.帧) 已发帧.add(String(x.帧.文件 || ''))
    return 头 + chr10 + 行们.join(chr10)
      + chr10 + '（上面这些是片子里的字幕。）'
  }

  /** 一轮真正结束：把游标推到这一轮拼到的位置（没拼过的轮次不动） */
  const 字幕这轮发完了 = (键) => {
    const 桶 = 字幕们.get(键)
    if (!桶 || !桶.本轮到) return
    const 前 = 桶.已发到
    桶.已发到 = Math.max(桶.已发到, 桶.本轮到)
    桶.本轮到 = 0
    if (桶.已发到 !== 前) 记账('白板：这一轮说完，字幕游标 ' + 前 + ' → ' + 桶.已发到)
  }

  // 挂在绑定会话上的「白板」——按会话挂，会话没了就卸掉
  const 白板挂着 = new Map()   // 会话键 -> 卸下函数
  const 挂白板 = () => {
    const 配置 = 读配置()
    const 目标键 = 会话键(配置.会话)
    if (!目标键) return
    const 桶 = 字幕们.get(目标键)
    if (!桶 || !桶.行.length) {
      const 卸 = 白板挂着.get(目标键)
      if (卸) {
        try { 卸() } catch (error) {}
        白板挂着.delete(目标键)
      }
      return
    }
    if (白板挂着.has(目标键)) return
    let agent = null
    try {
      agent = ctx.agents.get(配置.会话)
      if (!agent) agent = ctx.agents.get('session-' + 目标键)
    } catch (error) {}
    if (!agent || !agent.ctx || !agent.ctx.systemPrompt || typeof agent.ctx.systemPrompt.context !== 'function') return
    try {
      // 🔴 2026-10-26 深夜（排查「缓存命中只有 3%」时查出来的）：
      //   白板**必须用 context()，不能用 section()**。
      //   section 拼在系统提示词里，而白板每轮都在变（每句都带「12 秒前」这种相对时间）
      //   → 系统提示词一变，后面整段对话历史全成了「未缓存输入」（实测 20k 未缓存 / 640 已缓存）。
      //   context() 是 DSH 给「每轮都变」准备的那条路：作为一条消息追加到对话末尾，前缀不受影响。
      const 卸 = agent.ctx.systemPrompt.context({
        name: 'watch-subtitles',
        order: 900,
        // 🔴 2026-10-27：**这段是纯文本，不许宿主当提示词模板解析**。
        //   宿主默认会对 context/section 做变量替换：字幕里只要出现 `{{…}}`（台词、代码片段、
        //   游戏里的模板文字都可能有），就会被当成变量名去查，查不到直接抛
        //   `unknown prompt variable` —— 那一轮整轮失败，还会一直失败到字幕换掉为止。
        //   `interpolate: false` 是宿主自己给的开关（dsh-tools / working-directory 也在用）。
        interpolate: false,
        text: () => 字幕白板(目标键),
      })
      白板挂着.set(目标键, typeof 卸 === 'function' ? 卸 : (() => {}))
      记账('陪看字幕挂上白板了（' + 目标键.slice(0, 6) + '）')
    } catch (error) {
      记账('白板挂不上：' + 说(error))
    }
  }

  // ⭐ 0.0.8：挂件会把它自己配置里的「随机搭话秒」随每句话带上来 ——
  //   这样在挂件设置页改了就立刻生效（以前两边各存一份，改了等于没改）。
  let 挂件报的搭话秒 = null
  const 记住搭话秒 = (v) => {
    const 数 = Number(v)
    if (Number.isFinite(数) && 数 >= 0) 挂件报的搭话秒 = 数
  }
  const 挂件搭话秒 = () => 挂件报的搭话秒

  // ⭐ 0.3.7：节奏这几个数**只存在挂件那边**，由挂件随每条消息带上来 ——
  //   插件不自己存一份，省得两边改不到一起。
  const 挂件报的节奏 = {}
  const 记住节奏 = (体) => {
    for (const 键 of ['搭话最多秒', '冷却最短秒', '冷却最长秒', '安静秒']) {
      const 数 = Number(体 && 体[键])
      if (Number.isFinite(数) && 数 >= 0) 挂件报的节奏[键] = 数
    }
  }
  const 节奏 = (键, 默认) => {
    const v = Number(挂件报的节奏[键])
    return Number.isFinite(v) && v > 0 ? v : 默认
  }

  /** 一帧的说明：几点、那会儿在说什么（画面本身在图里） */
  const 帧说明 = (帧们) => 帧们.map((f) => {
    let 时 = ''
    try {
      时 = new Date(Number(f.时) || Date.now()).toLocaleTimeString('zh-CN', { hour12: false })
    } catch (error) { 时 = '' }
    const 词 = (f.台词 || []).map((x) => {
      const d = Number(x.差) || 0
      const 前 = d < 0 ? Math.abs(d) + ' 秒前' : (d === 0 ? '这会儿' : d + ' 秒后')
      return '· ' + 前 + '：' + String(x.文 || '')
    }).join(chr10)
    return '【' + 时 + ' 那一帧】' + (词 ? chr10 + 词 : '')
  }).join(chr10 + chr10)

  /**
   * ⭐ 1.1.1：让她自己开口的时候，先跟挂件要一张「当下的画面」（跟按住说话带图一个口径）。
   * 挂件没开 / 拍不了就返回空串，这一轮就只说话。
   */
  const 问挂件要张图 = async () => {
    const 配置 = 读配置()
    let 基 = ''
    try {
      const 址 = String(配置.回调 || '').trim()
      if (址) 基 = new URL(址).origin
    } catch (error) {}
    if (!基) {
      const 备 = Number(配置.回话端口) || 8778
      基 = 'http://127.0.0.1:' + 备
    }
    const 控 = new AbortController()
    const 停 = setTimeout(() => 控.abort(), 4000)
    try {
      const r = await fetch(基 + '/hands/shot', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: '{}',
        signal: 控.signal,
      })
      clearTimeout(停)
      if (!r.ok) return ''
      const j = await r.json()
      const 图 = String((j && j.图片) || '')
      if (!图) return ''
      mkdirSync(帧目录, { recursive: true })
      const 路 = join(帧目录, '开口-' + Date.now() + '.jpg')
      writeFileSync(路, Buffer.from(图, 'base64'))
      也许清截图()
      return 路
    } catch (error) {
      clearTimeout(停)
      return ''
    }
  }

  /** ⭐ 0.0.5：陪看时她自己开口 —— 走到 DSH 自己的回合（不是假装一段上下文） */
  /**
   * ⭐ 0.6.1：游戏模式也要能主动搭话 —— 不然「攒着」的截图没人看，每次还得她自己先开口，
   *   那就不是陪玩了。
   *
   * ⚠ 只在 **截图送法 = 攒着** 时生效：每张都说那一档，截图本来就会叫醒她，
   *   再叠加搭话等于一轮变两轮、白花钱。
   */
  const 游戏搭话 = () => {
    try {
      if (!游戏模式.开) return false
      const 配置 = 读配置()
      if (String(配置.截图送法 || '每张') !== '攒着') return false   // ← 只跟「攒着」配合
      const 间隔 = Math.max(0, Number(配置.游戏搭话秒) || 0)
      if (间隔 <= 0) return false
      const 键 = 会话键(配置.会话)
      if (!键) return false
      // 刚进游戏模式先安静一会儿，别一进去就开口
      if (现在() - (游戏模式.时 || 0) < Math.min(间隔, 60) * 1000) return false
      if (!要搭话({
        间隔秒: 间隔,
        最多秒: 0,
        概率: Number(配置.随机搭话概率) || 0.35,
        有字幕: false,
        上次: 上次搭话,
        现在: 现在(),
        浮: Math.random(),
      })) return false
      let agent = null
      try {
        agent = ctx.agents.get(配置.会话) || ctx.agents.get('session-' + 键)
      } catch (error) {}
      if (!agent) return false
      上次搭话 = 现在()
      void (async () => {
        try {
          const 内容 = [{ type: 'text', text: '（她正在打游戏，你顺手看了一眼画面，想说就说一句；不想说也可以不说。）' }]
          // 攒着的图一起带上；一张都没攒就问挂件要张现在的
          let 张们 = 取出攒图(键)
          if (!张们.length) {
            const 图路 = await 问挂件要张图()
            if (图路) 张们 = [{ 路: 图路, 时: 现在() }]
          }
          // ⭐ 1.6.0：**只拼 1 分钟以前的**，够 2 张就拼；刚截的那张单发不拼
          const 分 = 该拼哪几张(张们, 现在())
          let 拼好了 = false
          if (分.该拼) {
            const 拼这几张 = 分.老的.slice(-3)
            const 拼图 = await 请挂件拼图(拼这几张)
            if (拼图) {
              try {
                内容.push({ type: 'text', text: '（这 ' + 拼这几张.length + ' 张画面拼成了一张，从上到下；每格左上角是多久前）' })
                内容.push(await 做图片块从字节(Buffer.from(拼图, 'base64'), '游戏画面'))
                拼好了 = true
              } catch (error) {
                记账('拼好的那张没贴进去（退回单张）：' + 说(error))
              }
            }
            if (拼好了) {
              for (const x of 分.老的.slice(0, -3)) {
                try { 内容.push(await 做图片块(x.路, '游戏画面')) } catch (error) {}
              }
            }
          }
          for (const x of (拼好了 ? 分.新的 : 张们)) {
            if (!x || !x.路) continue
            const 差 = Math.abs(现在() - Number(x.时 || 0))
            if (差 > 45000) 内容.push({ type: 'text', text: '（下面这张是 ' + 多久前(x.时) + '的画面）' })
            try {
              内容.push(await 做图片块(x.路, '游戏画面'))
            } catch (error) {}
          }
          try {
            await agent.followup({
              id: randomUUID(), role: 'user',
              content: 内容,
              source: { kind: 'fishbuddy' },
            })
          } catch (error) {
            还回攒图(键, 张们)   // ⭐ 0.7.3：没送出去就把图放回去，下次还能带
            throw error
          }
          记账('游戏模式：主动看了一眼' + (内容.length > 1 ? ('（带 ' + (内容.length - 1) + ' 段图/说明）') : '（没有图）'))
        } catch (error) {
          记账('游戏模式搭话失败（' + 说(error) + '）')
        }
      })()
      return true
    } catch (error) {
      return false
    }
  }

  const 可能搭话 = () => {
    try {
      // ⭐ 0.7.7：在打游戏就别走「一起看片子」那条搭话 —— 两套提示词会打架
      if (游戏模式.开 && 现在() - (游戏模式.时 || 0) < 6 * 3600 * 1000) {
        return
      }
      if (!陪看开着) {
        // ⭐ 0.6.1：不在陪看，但可能在游戏模式 —— 那条路只跟「攒着」配合
        try { 游戏搭话() } catch (error) {}
        return
      }
      const 配置 = 读配置()
      const 键 = 会话键(配置.会话)
      if (!键) return
      const 桶 = 字幕们.get(键)
      const 行 = 桶 ? 桶.行 : []
      const 有字幕 = 行.length > 0 && 现在() - (桶.最后 || 0) < 30000
      if (!要搭话({
        间隔秒: 挂件搭话秒() ?? 配置.随机搭话秒,
        最多秒: 节奏('搭话最多秒', Number(配置.搭话最多秒) || 0),
        概率: 配置.随机搭话概率,
        有字幕,
        上次: 上次搭话,
        现在: 现在(),
        浮: Math.random(),          // ⭐ 1.0.3：每次重新掷，别像秒表
      })) return
      let agent = null
      try {
        agent = ctx.agents.get(配置.会话) || ctx.agents.get('session-' + 键)
      } catch (error) {}
      if (!agent) {
        // ⭐ 1.0.3：以前这里静默 return，看起来就像"随机开口坏了" —— 现在留一句证据
        if (!说过了没活着) {
          说过了没活着 = true
          记账('陪看：想自己开口，但绑的会话没开着（' + 配置.会话.slice(0, 20) + '…）—— 打开那间会话就好了')
        }
        return
      }
      说过了没活着 = false
      // ⭐ 0.3.5：刚发过图（90 秒内）就让路 —— 不然「发图 → 立刻自己说一句」会连着说话
      if (现在() < (下次自发最早 || 0)) return
      上次搭话 = 现在()
      上次自发 = 现在()
      下次自发最早 = 掷冷却()
      // ⭐ 0.2.4（2026-10-27）：「不许硬凑」不能写成命令，
      //   但得让它知道「安静着也是可以的」。只说这是什么、允许什么都不说。
      // ⭐ 0.2.6：上一版列了四五条「什么时候开口」，那更像命令、条条框框太多。
      //   → 只留**这一句**：说明画面里那些字是什么。要不要说话，让它自己看着办。
      const 文案 = '（你俩正一起看着，上面那些是片子里的字幕。）'
      // ⭐ 0.2.1：**截了帧不马上发**，攒着，等她开口这一轮一起给她看；
      //   看过的帧标成已发，下一轮不再重复（跟字幕一个道理）。
      void (async () => {
        try {
          // ⭐ 0.3.1：不再单独附图 —— 帧已经排进字幕队列，白板这一轮会连字幕一起带上
          // ⭐ 1.1.1：她开口的时候要带一张「当下」的画面（跟按住说话带图一样的口径）
          const 图路 = await 问挂件要张图()
          const 内容 = [{ type: 'text', text: 文案 }]
          // ⚠ 0.7.7：陪看搭话**只带它自己那张「当下」的画面**。
          //   以前这里会把「游戏模式攒的截图」也一起捞走 —— 于是游戏里攒的图
          //   被挂到「你俩正一起看着片子」这句提示词下面发出去，口径全乱了。
          if (图路) {
            try {
              内容.push(await 做图片块(图路, '一起看时的画面'))
            } catch (error) {
              记账('陪看：图没拼进去（' + 说(error) + '）')
            }
          }
          await agent.followup({
            id: randomUUID(), role: 'user',
            content: 内容,
            source: { kind: 'fishbuddy' },
          })
          记账('陪看：掷中了，让她自己开口说一句' + (内容.length > 1 ? '（带了一张图）' : ''))
        } catch (error) {
          记账('陪看：自己开口失败（' + 说(error) + '）')
        }
      })()
    } catch (error) {}
  }

  const 白板心跳 = () => {
    try { 挂白板() } catch (error) {}
    try { 可能搭话() } catch (error) {}
  }

  // ---------- ③ 本机口子（挂件往这里发） ----------
  const 回 = (res, 码, o) => {
    try {
      res.statusCode = 码
      res.setHeader('content-type', 'application/json; charset=utf-8')
      res.end(JSON.stringify(o))
    } catch (error) {}
  }

  const 读体 = async (req) => {
    let 串 = ''
    try {
      for await (const 块 of req) 串 += 块
    } catch (error) {}
    try {
      return JSON.parse(串 || '{}')
    } catch (error) {
      return {}
    }
  }

  // ⚠ 抽帧的处理器在下面才定义（要用帧账/帧目录），这里先留个口子：
  //   程序 POST 的是 `${dsh_port}/hands/frame`（跟字幕同一个口），
  //   所以必须挂在**这个 8777 服务**上 —— 0.2.1/0.2.2 只把它挂到了 DSH 的
  //   `/dsh-fish-buddy/frame`，程序打 /hands/frame，结果一律 404（0.2.3 修的）。
  let 处理帧 = null
  /**
   * ⭐ 0.6.0：**攒图** —— 游戏截图「攒着等说话」那一档用。
   * 键 = 会话键；值 = [{ 路, 时 }]，最多 3 张（新的挤掉最旧的）。
   * 图只存本地、**不叫醒**；等她说话（或她自己搭话）时，一次带过去。
   */
  // ⭐ 0.6.1：挂件会告诉我们「现在在不在游戏模式」—— 游戏模式也要能主动搭话
  const 游戏模式 = { 开: false, 时: 0 }
  const 攒图 = new Map()
  // ⭐ 0.7.2：**不限制张数**（以前的「最多 3 张、新的挤掉最旧的」是错的 ——
  //   挤掉的图等于白截了）。攒着就一直留着，等她说话 / 她自己看一眼时**全部**带过去。
  //   ⚠ 只有个上限 60 张防跑飞（一小时 30 秒一张也就 120 张，实际轮不到）。
  const 攒图上限 = 60
  const 收一张攒图 = (键, 路, 时) => {
    if (!键) return
    const 排 = 攒图.get(键) || []
    排.push({ 路, 时: Number(时) || 现在() })
    while (排.length > 攒图上限) 排.shift()
    攒图.set(键, 排)
  }
  const 取出攒图 = (键) => {
    const 排 = (攒图.get(键) || []).slice()
    攒图.delete(键)
    return 排
  }
  /** ⭐ 0.7.3：发失败了就把图**放回去**（发成功才真的算看过） */
  const 还回攒图 = (键, 张们) => {
    if (!键 || !Array.isArray(张们) || !张们.length) return
    const 排 = (张们 || []).filter((x) => x && x.路)
    if (!排.length) return
    const 现 = 攒图.get(键) || []
    攒图.set(键, 排.concat(现))
  }

  ctx.effect(() => {
    const 配置 = 读配置()
    const 口 = createServer(async (req, res) => {
      const 路径 = String((req.url || '').split('?')[0])
      // 陪看：挂件每出来一句字幕就推过来（不当作消息，进白板）
      if (路径 === '/hands/subtitle') {
        if (req.method !== 'POST') return 回(res, 405, { ok: false, 说: '要 POST' })
        const 体 = await 读体(req)
        const 配置 = 读配置()
        记住搭话秒(体.随机搭话秒)
        记住节奏(体)
        const 键 = 会话键(体.session || 配置.会话)
        if (!键) return 回(res, 409, { ok: false, 说: '还没绑定会话 —— 去设置里选一间' })
        const 行们 = Array.isArray(体.lines) ? 体.lines : [体.text]
        let 收了几条 = 0
        for (const 一 of 行们) {
          const 文 = typeof 一 === 'string' ? 一 : (一 && (一.text || 一.文))
          if (!文) continue
          收一句字幕(键, 文, 一 && 一.ts)
          收了几条 += 1
        }
        挂白板()   // 有字幕了就把白板挂上（没挂的话）
        return 回(res, 200, { ok: true, 说: '收到 ' + 收了几条 + ' 句', 缓存: (字幕们.get(键) || {}).行 ? 字幕们.get(键).行.length : 0 })
      }
      // ⭐ 0.4.4：按住说话 —— 一句话（可能还带一张图）一起发进会话
      if (路径 === '/hands/talk') {
        if (req.method !== 'POST') return 回(res, 405, { ok: false, 说: '要 POST' })
        const 体2 = await 读体(req)
        const 话 = String(体2.text || 体2.正文 || '').trim()
        const 图2 = String(体2.图片 || '')
        if (!话 && !图2) return 回(res, 400, { ok: false, 说: '空的' })
        状态.收到条数 += 1
        状态.最后收到 = 现在()
        // ⭐ 0.6.0：说话时把**攒着的截图**一起带过去（她说的「开麦说话时图也会跟着送」）
        let 攒的 = []
        try {
          攒的 = 取出攒图(会话键(读配置().会话))
        } catch (error) {}
        const 张们 = 攒的.slice()
        let 路2 = ''
        if (图2) {
          try {
            mkdirSync(帧目录, { recursive: true })
            路2 = join(帧目录, '说-' + Date.now() + '.jpg')
            writeFileSync(路2, Buffer.from(图2, 'base64'))
            也许清截图()
            张们.push({ 路: 路2, 时: 现在() })
          } catch (error) {
            return 回(res, 500, { ok: false, 说: '带图发失败：' + 说(error) })
          }
        }
        if (!张们.length) {
          const 结果0 = await 送进会话(话, 体2.session)
          return 回(res, 结果0.ok ? 200 : 409, 结果0)
        }
        try {
          // 有攒着的自动截图 → 别冒充她；只有热键那张 → 就是她发的
          const 结果1 = await 发说话那一轮(张们, 话, 攒的.length ? 'fishbuddy' : 'user')
          // ⚠ 发失败时发说话那一轮 会「返回一句话」不是抛错，这里按字面判断
          if (/失败|没开着|绑会话|总开关/.test(String(结果1))) {
            还回攒图(会话键(读配置().会话), 张们)
            return 回(res, 200, { ok: false, 说: 结果1 })
          }
          return 回(res, 200, { ok: true, 说: 结果1, 带图: 张们.length })
        } catch (error) {
          还回攒图(会话键(读配置().会话), 张们)
          return 回(res, 500, { ok: false, 说: '带图发失败：' + 说(error) })
        }
      }
      // ⭐ 1.1.1：陪看停了 —— 把还没发出去的字幕清掉，别在后面的轮次里继续往会话里灌
      if (路径 === '/hands/watch') {
        if (req.method !== 'POST') return 回(res, 405, { ok: false, 说: '要 POST' })
        const 体0 = await 读体(req)
        // ⚠ 1.1.1：键名同时认 `watch`（ASCII）和 `开` —— 有些客户端在传送时会把中文键弄坏
        const 开着 = !(体0 && (体0.watch === false || 体0.开 === false))
        陪看开着 = 开着
        if (!开着) {
          try {
            清空字幕桶()
          } catch (error) {}
          记账('陪看停了：攒着没发的字幕已经清掉，不再往会话里灌')
        }
        return 回(res, 200, { ok: true, 说: 开着 ? '知道了' : '字幕清了' })
      }
      // 挂件那边对外的宽接口：/hands/say（老）和 /say（短）
      if (路径 === '/hands/mode') {
        if (req.method !== 'POST') return 回(res, 405, { ok: false, 说: '要 POST' })
        const 体3 = await 读体(req)
        // ⭐ 0.7.5：挂件重开时把攒图清掉 —— 那些图是上一次的，重开就不该还挂着
        if (体3 && 体3.重置攒图) {
          try {
            const 键1 = 会话键(读配置().会话)
            const 清掉 = (攒图.get(键1) || []).length
            攒图.delete(键1)
            return 回(res, 200, { ok: true, 说: '攒图清了（' + 清掉 + ' 张）' })
          } catch (error) {}
        }
        游戏模式.开 = !(体3 && (体3.游戏 === false || 体3.开 === false))
        游戏模式.时 = 现在()
        return 回(res, 200, { ok: true, 说: 游戏模式.开 ? '好，游戏模式' : '好，不在游戏模式了' })
      }
      if (路径 === '/hands/frame') {
        if (req.method !== 'POST') return 回(res, 405, { ok: false, 说: '要 POST' })
        if (!处理帧) return 回(res, 503, { ok: false, 说: '还没准备好，等一秒再发' })
        return 处理帧(req, res)
      }
      if (路径 !== '/hands/say' && 路径 !== '/say') {
        if (路径 === '/hands/ping') return 回(res, 200, { ok: true, 说: '鱼搭子在这儿' })
        return 回(res, 404, { ok: false, 说: '没这个地址' })
      }
      if (req.method !== 'POST') return 回(res, 405, { ok: false, 说: '要 POST' })
      const 体 = await 读体(req)
      记住搭话秒(体.随机搭话秒)
      记住节奏(体)
      const 正文 = String(体.text || 体.正文 || '').trim()
      if (!正文) return 回(res, 400, { ok: false, 说: '空的一句话' })
      // ⭐ 0.7.5：**不带图说话也要把攒着的截图带出去** ——
      //   以前只有 /hands/talk（带图说话）会取攒图，所以按一次只说话键，攒的图一张都没发。
      try {
        const 键0 = 会话键(读配置().会话)
        const 攒的0 = 取出攒图(键0)
        if (攒的0.length) {
          const 结果 = await 发说话那一轮(攒的0, 正文)
          if (/失败|没开着|绑会话|总开关/.test(String(结果))) {
            还回攒图(键0, 攒的0)
            return 回(res, 200, { ok: false, 说: 结果 })
          }
          return 回(res, 200, { ok: true, 说: 结果, 带图: 攒的0.length })
        }
      } catch (error) {}
      状态.收到条数 += 1
      状态.最后收到 = 现在()
      const 结果 = await 送进会话(正文, 体.session)
      return 回(res, 结果.ok ? 200 : 409, 结果)
    })

    口.on('error', (error) => {
      状态.口子 = { 起没起: false, 端口: 配置.端口, 错: 说(error) }
      if (String(error && error.code) === 'EADDRINUSE') {
        记账('端口 ' + 配置.端口 + ' 被别人占了 —— 换个端口，或关掉占它的程序')
      } else {
        记账('口子起不来：' + 说(error))
      }
    })

    口.listen(配置.端口, '127.0.0.1', () => {
      状态.口子 = { 起没起: true, 端口: 配置.端口, 错: '' }
      记账('本机口子开着：127.0.0.1:' + 配置.端口 + '/hands/say')
    })

    return () => {
      try {
        口.close()
      } catch (error) {}
      状态.口子 = { 起没起: false, 端口: 配置.端口, 错: '' }
    }
  })

  ctx.effect(() => {
    const 做 = () => { try { 白板心跳() } catch (error) {} }
    // ⭐ 0.5.1：宿主的 `timer` 服务不再写进 inject（有的宿主没有），这里**现取现用**：
    //   摸 `ctx.interval` 会直接抛 `cannot get property "timer" without inject`，整插件激活失败。
    const 计 = 取服务('timer')
    if (计 && typeof 计.interval === 'function') {
      const 定 = 计.interval(做, 5000)
      return () => { try { if (typeof 定 === 'function') 定() } catch (error) {} }
    }
    const 定2 = setInterval(做, 5000)
    return () => clearInterval(定2)
  }, 'fishbuddy: 字幕白板心跳')

  // ---------- 检查更新（⭐ 0.7.0）----------
  /**
   * 查两样：**插件自己**（仓库 main 上的 package.json）和**挂件 exe**（最新 release 的 tag）。
   *
   * ⚠ 插件对 `link:` 装的人永远是「本地最新」，所以那种情况直接标「本地开发版」，
   *   不催他去改版本号。
   */
  const 比版本 = (a, b) => {
    const 拆 = (x) => String(x || '').replace(/^v/i, '').split(/[.+-]/).map((n) => Number(n) || 0)
    const A = 拆(a)
    const B = 拆(b)
    for (let i = 0; i < Math.max(A.length, B.length); i++) {
      const d = (A[i] || 0) - (B[i] || 0)
      if (d) return d > 0 ? 1 : -1
    }
    return 0
  }

  const 检查更新 = async () => {
    const 出 = { ok: true, 插件: {}, 挂件: {} }
    const 仓库 = 'Yuuyuko-uu/dsh-fish-buddy'
    // ① 插件：本地 package.json vs 仓库 main 的 package.json
    let 本地插件 = ''
    try {
      本地插件 = String(JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'package.json'), 'utf8')).version || '')
    } catch (error) {}
    出.插件.本地 = 本地插件
    try {
      const r = await fetch('https://raw.githubusercontent.com/' + 仓库 + '/main/package.json',
        { headers: { 'user-agent': 'dsh-fish-buddy' }, signal: AbortSignal.timeout(8000) })
      if (r.ok) {
        const j = await r.json()
        出.插件.最新 = String(j.version || '')
      }
    } catch (error) {
      出.插件.错 = String((error && error.message) || error)
    }
    出.插件.有新版 = Boolean(出.插件.最新 && 本地插件 && 比版本(出.插件.最新, 本地插件) > 0)
    出.插件.本地开发版 = Boolean(出.插件.最新 && 本地插件 && 比版本(本地插件, 出.插件.最新) > 0)

    // ② 挂件：问 8778 它自己是哪个版本；最新版看 release
    try {
      const 端口 = Number(读配置().回调 && /:(\d+)/.exec(String(读配置().回调))?.[1]) || 8778
      const r = await fetch('http://127.0.0.1:' + 端口 + '/hands/devices', { signal: AbortSignal.timeout(3000) })
      if (r.ok) {
        const j = await r.json()
        出.挂件.本地 = String((j && j.版本) || '')
      }
    } catch (error) {
      出.挂件.错 = '问不到挂件（它没开着？）'
    }
    try {
      const r = await fetch('https://api.github.com/repos/' + 仓库 + '/releases/latest',
        { headers: { 'user-agent': 'dsh-fish-buddy', accept: 'application/vnd.github+json' }, signal: AbortSignal.timeout(8000) })
      if (r.ok) {
        const j = await r.json()
        出.挂件.最新 = String(j.tag_name || '')
        const 资产 = (j.assets || []).find((a) => /\.exe$/i.test(String(a.name || '')))
        if (资产) 出.挂件.下载 = String(资产.browser_download_url || '')
      }
    } catch (error) {
      出.挂件.错2 = String((error && error.message) || error)
    }
    出.挂件.有新版 = Boolean(出.挂件.最新 && 出.挂件.本地 && 比版本(出.挂件.最新, 出.挂件.本地) > 0)
    if (!出.挂件.本地) 出.挂件.说明 = '挂件没开着，量不到它现在是什么版本'
    return 出
  }

  // ---------- 设置页用的路由 ----------
  const 路线 = (路径, handler) =>
    ctx.effect(() =>
      ctx.webServer.register({
        kind: 'exact',
        path: 路径,
        handler: async (req, res) => {
          try {
            await handler(req, res)
          } catch (error) {
            回(res, 200, { ok: false, 说: 说(error) })
          }
        },
      }),
    )

  // ---------- 挂件在哪（设置页显示 + 一键打开） ----------
  const 找挂件 = () => {
    const 配置 = 读配置()
    const 试 = []
    if (配置.挂件路径) 试.push(String(配置.挂件路径))
    试.push(join(目录, '鱼搭子', '鱼搭子.exe'))
    试.push(join(homedir(), 'Desktop', '鱼搭子.exe'))
    for (const p of 试) {
      try {
        if (p && existsSync(p)) return p
      } catch (error) {}
    }
    return ''
  }

  // ⭐ 0.4.7：设置页那个「下载挂件」按钮
  // ⭐ 0.7.0：检查更新（插件 + 挂件）
  路线(`${路由前缀}/update-check`, async (req, res) => {
    try {
      return 回(res, 200, await 检查更新())
    } catch (error) {
      return 回(res, 200, { ok: false, 说: '查不了：' + 说(error) })
    }
  })

  路线(`${路由前缀}/fetch`, async (req, res) => {
    const r = await 下载挂件()
    return 回(res, 200, r)
  })

  路线(`${路由前缀}/launch`, async (req, res) => {
    const 路径 = 找挂件()
    if (!路径) return 回(res, 200, { ok: false, 说: '没找到挂件程序 —— 在下面填一下它的位置（那个 exe）' })
    try {
      const 子 = spawn(路径, [], { detached: true, stdio: 'ignore', windowsHide: false })
      // ⚠ 0.7.4：**必须挂 'error'** —— 打开失败（比如那个 exe 要求管理员、DSH 却是普通权限）
      //   子进程会发 error 事件，没人接就会把整个 Node 进程（DSH）带下去。
      子.on('error', (错) => { 记账('挂件没打开：' + 说(错) + '（要管理员的话，自己右键用管理员启动它）') })
      子.unref()
      记账('把挂件打开了：' + 路径)
      return 回(res, 200, { ok: true, 说: '挂件开了，看屏幕右边' })
    } catch (error) {
      return 回(res, 200, { ok: false, 说: '打不开：' + 说(error) })
    }
  })

  路线(`${路由前缀}/state`, async (req, res) => {
    const 配置 = 读配置()
    const 清单 = 会话清单()
    const 挂件 = 找挂件()
    const 多久没说话 = 状态.最后收到 ? Math.round((现在() - 状态.最后收到) / 1000) : -1
    return 回(res, 200, {
      ok: true,
      配置: {
        总开关: 配置.总开关, 端口: 配置.端口, 会话: 配置.会话, 回调: 配置.回调,
        带上来源: 配置.带上来源, 挂件路径: 配置.挂件路径, 下载地址: 配置.下载地址,
        自动开挂件: 配置.自动开挂件 !== false,
      },
      会话清单: 清单.map((x) => ({ 值: x.id, 名: (x.标题 || '（没标题）') + ' · ' + x.id.slice(-6) })),
      口子: 状态.口子,
      挂件: { 找到: !!挂件, 路径: 挂件, 最后说话秒前: 多久没说话 },
      下载: 状态.下载,
      搭话: {
        秒: 挂件搭话秒() === null ? 配置.随机搭话秒 : 挂件搭话秒(),
        概率: 配置.随机搭话概率,
      },
      '收到条数': 状态.收到条数,
      '送出条数': 状态.送出条数,
      递回条数: 状态.递回条数,
      最后回话: 状态.最后回话,
      字幕: (() => {
        try {
          const 键 = 会话键(配置.会话)
          const 桶 = 键 ? 字幕们.get(键) : null
          const 行 = 桶 ? 桶.行 : []
          return { 条数: 行.length, 滚掉: 桶 ? 桶.滚掉 : 0, 丢: 桶 ? 桶.丢 : 0, 已发到: 桶 ? 桶.已发到 : 0, 待发: 桶 ? Math.max(0, 桶.行.filter((x) => x.序 > 桶.已发到).length) : 0, 最后: 桶 ? 桶.最后 : 0, 白板挂着: 白板挂着.has(键) }
        } catch (error) {
          return { 条数: 0, 滚掉: 0, 丢: 0, 已发到: 0, 待发: 0, 最后: 0, 白板挂着: false }
        }
      })(),
      日志: 状态.日志.slice(0, 40),
    })
  })

  路线(`${路由前缀}/config`, async (req, res) => {
    const 体 = await 读体(req)
    const 新 = 写配置({ ...读配置(), ...(体 && typeof 体 === 'object' ? 体 : {}) })
    记账('设置改了：绑会话=' + (新.会话 || '（空）') + '、端口=' + 新.端口 + '、回调=' + (新.回调 || '（空）'))
    return 回(res, 200, { ok: true, 说: '存好了（改端口要重启 DSH 才生效）', 配置: 新 })
  })

  路线(`${路由前缀}/sessions`, async (req, res) => {
    return 回(res, 200, { ok: true, 清单: 会话清单() })
  })

  // ---------- 麦克风：真正的设备在挂件那头，这里只做转发 ----------
  // 为什么要绕：只有本机进程能枚举/打开麦克风；DSH 是网页，拿不到。
  const 挂件基址 = () => {
    const 址 = String(读配置().回调 || '').trim()
    if (!址) return ''
    try {
      const u = new URL(址)
      return u.origin
    } catch (error) {
      return ''
    }
  }

  路线(`${路由前缀}/mic`, async (req, res) => {
    const 基 = 挂件基址()
    if (!基) return 回(res, 200, { ok: false, 说: '还没填「回话递回」地址 —— 挂件的口子不知道在哪' })
    try {
      const r = await fetch(基 + '/hands/devices')
      const 数据 = await r.json()
      return 回(res, 200, { ok: true, ...数据 })
    } catch (error) {
      return 回(res, 200, { ok: false, 说: '挂件没应声（它开着了没？）：' + 说(error), 设备: [] })
    }
  })

  路线(`${路由前缀}/mic/set`, async (req, res) => {
    const 基 = 挂件基址()
    if (!基) return 回(res, 200, { ok: false, 说: '还没填「回话递回」地址' })
    const 体 = await 读体(req)
    const 号 = 体 && (体.index === 0 || 体.index) ? 体.index : null
    const 名 = String((体 && 体.name) || '')
    try {
      const r = await fetch(基 + '/hands/device', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ index: 号, name: 名 }),
      })
      const 数据 = await r.json()
      记账('麦克风换成：' + (名 || '系统默认'))
      return 回(res, 200, { ok: !!(数据 && 数据.ok), ...数据 })
    } catch (error) {
      return 回(res, 200, { ok: false, 说: '换不了（挂件没应声）：' + 说(error) })
    }
  })

  路线(`${路由前缀}/last-reply`, async (req, res) => {
    return 回(res, 200, { ok: true, ...状态.最后回话 })
  })

  // ---------- ③ 陪看时「时不时抽一帧」给她看（0.3.0）----------
  //  看番/打游戏时随机抽几帧，带时间点 + 那会儿的台词；2K 原图太大，程序那边先压好再发。
  const 帧目录 = join(目录, 'fish-buddy-frames')

  // ⭐ 0.7.9：截图自动清理。十分钟最多查一次，别每次写图都把目录扫一遍。
  let 上次清截图 = 0
  const 也许清截图 = () => {
    const 配置 = 读配置()
    const 保留天 = Number(配置.截图保留天) || 0
    const 最多张 = Number(配置.截图最多张) || 0
    if (!保留天 && !最多张) return
    if (现在() - 上次清截图 < 10 * 60 * 1000) return
    上次清截图 = 现在()
    try {
      const 果 = 清旧截图(帧目录, 保留天, 最多张)
      if (果.删了 > 0) 记账('截图清理：删了 ' + 果.删了 + ' 张，还剩 ' + 果.剩 + ' 张')
    } catch (error) {
      记账('截图清理没成：' + 说(error))
    }
  }
  也许清截图()      // 插件一起来先清一次（上次清截图是 0，这一下一定会真的跑）

  /** ⭐ 0.7.10：报一下现在攒了多少张、多大 —— 设置页要显示，也得能手动清空。 */
  const 截图家底 = () => {
    const 果 = { 张数: 0, 兆: 0, 目录: 帧目录 }
    try {
      for (const 名 of readdirSync(帧目录)) {
        if (!/\.(jpg|jpeg|png)$/i.test(String(名))) continue
        try {
          const 资 = statSync(join(帧目录, 名))
          if (!资.isFile()) continue
          果.张数 += 1
          果.兆 += 资.size
        } catch (error) { /* 刚好被删掉，跳过 */ }
      }
    } catch (error) { /* 目录还没有 = 0 张 */ }
    果.兆 = Math.round((果.兆 / 1048576) * 10) / 10
    return 果
  }

  路线(`${路由前缀}/shots`, async (req, res) => 回(res, 200, { ok: true, ...截图家底() }))

  路线(`${路由前缀}/shots/clear`, async (req, res) => {
    let 删了 = 0
    try {
      for (const 名 of readdirSync(帧目录)) {
        if (!/\.(jpg|jpeg|png)$/i.test(String(名))) continue
        try {
          unlinkSync(join(帧目录, 名))
          删了 += 1
        } catch (error) { /* 删不掉就算了 */ }
      }
    } catch (error) { /* 目录不存在 */ }
    记账('手动清空截图：删了 ' + 删了 + ' 张')
    return 回(res, 200, { ok: true, 删了, ...截图家底() })
  })
  /**
   * ⭐ 1.0.5：图片块要**先存成附件**，再引用它。
   *   宿主只认 `{ type:'image', attachment: { attachmentId, … } }`。
   */

  /** 请挂件把几张拼成一竖条，返回 base64；不成返回空串 */
  const 请挂件拼图 = async (张们) => {
    if (!Array.isArray(张们) || 张们.length < 2) return ''
    const 控 = new AbortController()
    const 停 = setTimeout(() => 控.abort(), 15000)
    try {
      const r = await fetch(挂件基址() + '/hands/stitch', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ 帧们: 张们.map((x) => ({ 路径: x.路, 标: '· ' + 多久前(x.时) })) }),
        signal: 控.signal,
      })
      clearTimeout(停)
      if (!r.ok) return ''
      const j = await r.json()
      if (!j || !j.ok || !j.图片) {
        记账('拼图没成：' + String((j && j.说) || '挂件没回图片'))
        return ''
      }
      return String(j.图片)
    } catch (error) {
      记账('拼图请求失败：' + String((error && error.message) || error))
      return ''
    } finally {
      clearTimeout(停)
    }
  }

  const 做图片块从字节 = async (字节, 名) => {
    const 附件服务 = 取服务('attachments')
    if (!附件服务 || typeof 附件服务.saveImage !== 'function') {
      throw new Error('这个宿主没给 attachments 服务，图片发不进去')
    }
    const ref = await 附件服务.saveImage({
      data: new Uint8Array(字节),
      mediaType: 'image/jpeg',
      name: 名 || '画面',
    })
    return { type: 'image', attachment: ref }
  }

  const 做图片块 = async (路, 名) => {
    const 附件服务 = 取服务('attachments')
    if (!附件服务 || typeof 附件服务.saveImage !== 'function') {
      throw new Error('这个宿主没给 attachments 服务，图片发不进去')
    }
    const 字节 = readFileSync(路)
    const ref = await 附件服务.saveImage({
      data: new Uint8Array(字节),
      mediaType: 'image/jpeg',
      name: 名 || '画面',
    })
    return { type: 'image', attachment: ref }
  }

  /**
   * ⭐ 0.4.3：把一张图**当场**发一轮（带文字 + 图片块），让她真的看得见画面。
   * 返回一句给人看的结果。
   */
  /**
   * ⭐ 0.7.8：**谁能装成「她发的」**，按来源分：
   *   · 热键截的（她自己按的）→ `source.kind = 'user'`，界面照常渲染成她发的图；
   *   · 自动截图（游戏间隔截、攒着待发、陪看帧）→ `'fishbuddy'`，
   *     界面显示成「未知内容块」（渲染不出来），但**文字和时间标记照样在**，也不会冒充她。
   */
  const 发截图那一轮 = async (路, 源) => {
    const 配置 = 读配置()
    if (!配置.总开关) return '总开关关着，没发'
    const 目标 = String(配置.会话 || '').trim()
    if (!目标) return '还没绑会话，发不出去'
    let agent
    try {
      agent = ctx.agents.get(目标)
      if (agent === undefined) agent = ctx.agents.get('session-' + 会话键(目标))
    } catch (error) {
      return '找不到那间会话：' + 说(error)
    }
    if (!agent) return '那间会话没开着'
    const 话 = 源 === '游戏' ? '（这是我游戏里的画面）' : '（这是我现在的屏幕）'
    try {
      await agent.followup({
        id: randomUUID(),
        role: 'user',
        content: [{ type: 'text', text: 话 }, await 做图片块(路, '画面')],
        source: { kind: 源 === '热键' ? 'user' : 'fishbuddy' },
      })
      状态.送出条数 += 1
      return '发过去了'
    } catch (error) {
      return '发失败了：' + 说(error)
    }
  }

  /**
   * ⭐ 0.4.4：按住说话带图 —— 用「她说的那句话」+ 图片块发一轮。
   */
  const 发说话那一轮 = async (路们, 话, 来源类别 = 'user') => {
    const 配置 = 读配置()
    if (!配置.总开关) return '总开关关着，没发'
    const 目标 = String(配置.会话 || '').trim()
    if (!目标) return '还没绑会话'
    let agent
    try {
      agent = ctx.agents.get(目标)
      if (agent === undefined) agent = ctx.agents.get('session-' + 会话键(目标))
    } catch (error) {
      return '找不到那间会话：' + 说(error)
    }
    if (!agent) return '那间会话没开着'
    try {
      // ⭐ 0.6.0：可以带**多张**（攒着的几张一起给）；不是刚截的，前面标一句「几分钟前」
      const 内容 = [{ type: 'text', text: 话 || '（看这个）' }]
      const 原们 = Array.isArray(路们) ? 路们 : [{ 路: 路们, 时: 现在() }]
      const 张们 = 原们.map((x) => (typeof x === 'string' ? { 路: x, 时: 现在() } : { 路: x && x.路, 时: (x && x.时) || 现在() }))
        .filter((x) => x.路)
      // ⭐ 1.6.0：**只拼 1 分钟以前的**，够 2 张就拼；刚截的那张（还有她自己截图发的那张）单发不拼
      const 分 = 该拼哪几张(张们, 现在())
      let 拼好了 = false
      if (分.该拼) {
        const 拼这几张 = 分.老的.slice(-3)          // 最多拼 3 张（取最新的 3 张老图；2 张就全带上）
        const 拼图 = await 请挂件拼图(拼这几张)
        if (拼图) {
          try {
            内容.push({ type: 'text', text: '（这 ' + 拼这几张.length + ' 张画面拼成了一张，从上到下；每格左上角是多久前）' })
            内容.push(await 做图片块从字节(Buffer.from(拼图, 'base64'), '说话时的画面'))
            拼好了 = true
          } catch (error) {
            记账('拼好的那张没贴进去（退回单张）：' + 说(error))
          }
        }
        if (拼好了) {
          for (const x of 分.老的.slice(0, -3)) {
            try { 内容.push(await 做图片块(x.路, '说话时的画面')) } catch (error) {}
          }
        }
      }
      for (const x of (拼好了 ? 分.新的 : 张们)) {
        try {
          const 差 = Math.abs(现在() - Number(x.时 || 0))
          if (差 > 45000) 内容.push({ type: 'text', text: '（上面那张是 ' + 多久前(x.时) + '的画面）' })
          内容.push(await 做图片块(x.路, '说话时的画面'))
        } catch (error) {
          记账('这一张没拼进去（' + 说(error) + '）')
        }
      }
      await agent.followup({
        id: randomUUID(),
        role: 'user',
        content: 内容,
        source: { kind: 来源类别 },
      })
      状态.送出条数 += 1
      return '发过去了'
    } catch (error) {
      return '发失败了：' + 说(error)
    }
  }

  const 收一帧 = async (req, res) => {
    const 体 = await 读体(req)
    const 图 = String((体 && 体.图片) || '')
    if (!图) return 回(res, 400, { ok: false, 说: '没带图' })
    try {
      mkdirSync(帧目录, { recursive: true })
      const 字节 = Buffer.from(图, 'base64')
      const 名 = '帧-' + Date.now() + '.jpg'
      const 路 = join(帧目录, 名)
      writeFileSync(路, 字节)
      也许清截图()
      const 条 = {
        序: (帧账.length ? 帧账[帧账.length - 1].序 : 0) + 1,
        时: Number((体 && 体.时间点) || Date.now()) || Date.now(),
        文件: 路,
        大小: 字节.length,
        尺寸: String((体 && 体.尺寸) || ''),
        台词: Array.isArray(体 && 体.台词) ? 体.台词.slice(0, 10) : [],
      }
      帧账.push(条)
      // 一帧只发一次。队列别无限长 —— 攒太多就把最旧的丢掉。
      while (帧账.length > 8) 帧账.shift()
      // ⭐ 0.4.0（2026-10-28）：图**不单独发** —— 只跟着字幕一起出去。
      //   以前安静 8 秒就自己发一张：跟「字幕那一批」撞成两层，同一张图还可能出两次。
      //   现在：图先存本地、排进字幕队列；字幕在流的时候，跟那批字幕一起到。
      try {
        收一帧行(会话键(读配置().会话), 条)
      } catch (error) {}
      // ⭐ 0.4.3：游戏模式 / 热键截的图是**立刻**发一轮的 —— 她要的是「她真看见画面」，
      //   而且没画面她也没法说点什么。陪看那一路还是排队等字幕。
      // ⭐ 0.6.0：**存档**（游戏截图「攒着」那一档）→ 只排队，不叫醒
      if (Number((体 && 体.存档) || 0) === 1) {
        try {
          收一张攒图(会话键(读配置().会话), 路, (体 && 体.时间点) || 现在())
        } catch (error) {}
        return 回(res, 200, { ok: true, 说: '攒着了（说话时一起给你看）', 攒: (攒图.get(会话键(读配置().会话)) || []).length })
      }
      const 立刻 = Number((体 && 体.立即) || 0) === 1
      if (立刻) {
        const 源 = String((体 && 体.来源) || '截图')
        const 结果 = await 发截图那一轮(路, 源)
        记账('收图（' + 源 + '）：' + Math.round(条.大小 / 1024) + 'KB → ' + 结果)
        return 回(res, 200, { ok: true, 说: 结果, 存: 条.文件 })
      }
      记账('收到一帧画面（' + Math.round(条.大小 / 1024) + 'KB' + (条.尺寸 ? '，' + 条.尺寸 : '')
        + '）—— 排进字幕里，下一轮跟字幕一起发')
      return 回(res, 200, { ok: true, 说: '收到 1 帧', 存: 条.文件, 帧数: 帧账.length })
    } catch (error) {
      return 回(res, 500, { ok: false, 说: '存帧失败：' + 说(error) })
    }
  }
  // ⭐ 0.4.7：设置页里直接下载挂件（不用自己去 Release 页面翻）
  const 挂件下载目录 = () => {
    const 家 = join(目录, '鱼搭子')
    try { mkdirSync(家, { recursive: true }) } catch (error) {}
    return 家
  }

  const 取最新exe地址 = async () => {
    // 先问 GitHub「最新 Release 里哪个附件是 .exe」，失败就用固定兜底地址
    try {
      const r = await fetch('https://api.github.com/repos/Yuuyuko-uu/dsh-fish-buddy/releases/latest', {
        headers: { accept: 'application/vnd.github+json', 'user-agent': 'dsh-fish-buddy' },
      })
      if (r.ok) {
        const j = await r.json()
        const 件 = (j.assets || []).find((a) => String(a.name || '').toLowerCase().endsWith('.exe'))
        if (件 && 件.browser_download_url) return { 址: 件.browser_download_url, 版: String(j.tag_name || '') }
      }
    } catch (error) {}
    return { 址: 下载兜底地址, 版: '' }
  }

  const 下载挂件 = async () => {
    if (状态.下载 && 状态.下载.在下载) return { ok: false, 说: '正在下，等它下完' }
    状态.下载 = { 在下载: true, 百分比: 0, 说: '正在问 GitHub 要地址…', 出错: '', 路径: '', 版: '' }
    try {
      const { 址, 版 } = await 取最新exe地址()
      if (!址) throw new Error('没找到下载地址')
      状态.下载.版 = 版
      状态.下载.说 = '正在下载 ' + (版 ? 版 + ' ' : '') + '…'
      记账('开始下载挂件：' + 址)
      const r = await fetch(址, { redirect: 'follow' })
      if (!r.ok) throw new Error('HTTP ' + r.status)
      const 总 = Number(r.headers.get('content-length') || 0)
      const 临时 = join(挂件下载目录(), '鱼搭子.exe.下载中')
      const 目标 = join(挂件下载目录(), '鱼搭子.exe')
      const 出 = createWriteStream(临时)
      let 收 = 0
      for await (const 块 of r.body) {
        收 += 块.length
        出.write(块)
        状态.下载.百分比 = 总 ? Math.min(99, Math.round((收 / 总) * 100)) : 0
        状态.下载.说 = 总
          ? '正在下载：' + Math.round(收 / 1048576) + ' / ' + Math.round(总 / 1048576) + ' MB'
          : '正在下载：' + Math.round(收 / 1048576) + ' MB'
      }
      await new Promise((好, 坏) => { 出.end(() => 好()); 出.on('error', 坏) })
      try { if (existsSync(目标)) rmSync(目标) } catch (error) {}
      renameSync(临时, 目标)
      // 记进配置：**原来那个还能用就不动它**（别把别人的开发路径悄悄改掉）
      const 旧配置 = 读配置()
      const 老路径 = String(旧配置.挂件路径 || '').trim()
      const 老的还在 = !!老路径 && existsSync(老路径)
      写配置({ ...旧配置, 挂件路径: 老的还在 ? 老路径 : 目标 })
      状态.下载 = { 在下载: false, 百分比: 100, 说: '下好了：' + 目标, 出错: '', 路径: 目标, 版 }
      记账('挂件下载完成：' + 目标 + '（' + Math.round(收 / 1048576) + 'MB）')
      return { ok: true, 说: '下好了', 路径: 目标 }
    } catch (error) {
      状态.下载 = { 在下载: false, 百分比: 0, 说: '没下成', 出错: 说(error), 路径: '', 版: '' }
      记账('挂件没下成：' + 说(error))
      return { ok: false, 说: 说(error) }
    }
  }

  // 两个口都用同一个处理器：程序打 8777 的 /hands/frame，设置页/调试可以打 DSH 的 /dsh-fish-buddy/frame
  处理帧 = 收一帧
  路线(`${路由前缀}/frame`, 收一帧)
  路线(`${路由前缀}/frames`, async (req, res) => {
    return 回(res, 200, { ok: true, 帧们: 帧账.slice(-10) })
  })

  // ---------- DSH 起来时把挂件拉起来 ----------
  // 默认就该开着，不然每次都要自己去点。设置里能关掉。
  const 挂件端口 = () => {
    const 配置 = 读配置()
    const 址 = String(配置.回调 || '').trim()
    if (址) {
      try {
        const 号 = Number(new URL(址).port)
        if (号 > 0) return 号
      } catch (error) {}
    }
    const 备 = Number(配置.回话端口)
    return 备 > 0 ? 备 : 8778
  }

  const 挂件在跑吗 = async () => {
    const 控 = new AbortController()
    const 停 = setTimeout(() => 控.abort(), 1200)
    try {
      const r = await fetch('http://127.0.0.1:' + 挂件端口() + '/hands/reply', { signal: 控.signal })
      return r.status < 500
    } catch (error) {
      return false
    } finally {
      clearTimeout(停)
    }
  }

  const 自动开挂件 = async () => {
    if (读配置().自动开挂件 === false) {
      记账('自动打开挂件是关着的（设置里能开回来）')
      return false
    }
    if (await 挂件在跑吗()) {
      记账('挂件本来就在跑，不重复开')
      return false
    }
    const 路径 = 找挂件()
    if (!路径) {
      记账('想自动打开挂件，但没找到它在哪 —— 设置里填一下它的位置')
      return false
    }
    try {
      const 子 = spawn(路径, [], { detached: true, stdio: 'ignore', windowsHide: false })
      // ⚠ 0.7.4：同上 —— 不挂 'error' 的话，打不开会把 DSH 一起带走
      子.on('error', (错) => { 记账('自动打开挂件没成：' + 说(错) + "（要管理员的话，自己右键用管理员启动它）") })
      子.unref()
      记账('顺手把挂件打开了：' + 路径)
      return true
    } catch (error) {
      记账('自动打开挂件失败：' + 说(error))
      return false
    }
  }

  // 等 DSH 自己站稳（8 秒）再去开挂件；测试环境用环境变量关掉，别真拉起程序。
  if (!process.env.DSH_FISHBUDDY_NO_LAUNCH) {
    ctx.effect(() => {
      const 定 = setTimeout(() => { void 自动开挂件() }, 8000)
      return () => clearTimeout(定)
    })
  }

  记账('鱼搭子起来了 · 本机口子端口 ' + 读配置().端口)
}
