// 鱼搭子 · 网页半边冒烟测试 —— 假 React / 假 slots，把设置页渲染成一棵对象树。
// 验：模块 id、inject、挂到 settings.section、关键元素都渲染出来、不抛错。
// 跑法： node tests/网页半边.mjs

let 捕获 = null
globalThis.window = { __ModuleLoader__: { load: (o) => { 捕获 = o } } }

const 假状态 = {
  ok: true,
  配置: { 总开关: true, 端口: 8777, 会话: 'session-X', 回调: '', 带上来源: true, 挂件路径: '', 下载地址: '' },
  会话清单: [{ 值: 'session-X', 名: '测试会话 · abcdef' }],
  口子: { 起没起: true, 端口: 8777, 错: '' },
  挂件: { 找到: false, 路径: '', 最后说话秒前: -1 },
  收到条数: 3,
  送出条数: 2,
  递回条数: 1,
  最后回话: { 会话: 'session-X', 文本: '我在的', 时: Date.now() },
  日志: [{ 时: Date.now(), 说: '本机口子开着：127.0.0.1:8777/hands/say' }],
}

globalThis.fetch = async () => ({ json: async () => 假状态 })

let 状态槽 = []
let 下标 = 0
const 造React = () => ({
  createElement: (t, p, ...kids) => ({ t, p: p || {}, kids: kids.flat(9).filter((k) => k !== null && k !== undefined && k !== false) }),
  useState: (init) => {
    const i = 下标++
    if (!(i in 状态槽)) 状态槽[i] = init
    return [状态槽[i], (v) => { 状态槽[i] = typeof v === 'function' ? v(状态槽[i]) : v }]
  },
  useEffect: () => {},
  useCallback: (f) => f,
})
const 假require = (n) => {
  if (n === 'react') return 造React()
  throw new Error('不该 require 这个：' + n)
}

await import(new URL('../lib/client.js', import.meta.url).href)

const exports = 捕获.factory(假require)
let 挂了 = 0
const 报 = (标签, 过, 详情) => { if (!过) 挂了++; console.log(`${过 ? 'PASS' : 'FAIL'}  ${标签}${详情 ? '  :: ' + 详情 : ''}`) }

报('模块 id = dsh-fish-buddy', 捕获.id === 'dsh-fish-buddy', 捕获.id)
报('inject 只依赖 slots', Array.isArray(exports.inject) && exports.inject.join() === 'slots')

let 注册 = null
let 组件 = null
const slots = {
  inject: (n, cb) => { if (n !== 'settings.section') throw new Error('槽位名不对：' + n); cb() },
  register: (d, c) => { 注册 = d; 组件 = c; return () => {} },
}
exports.apply({ get: (n) => (n === 'slots' ? slots : undefined) })
报('挂到 settings.section，id = fish-buddy',
  注册 !== null && 注册.id === 'fish-buddy' && 注册.name === 'settings.section', JSON.stringify(注册))

// 预填「已经读到状态」的第一格，一次渲染就能出整页
下标 = 0
状态槽 = [假状态]
const 树 = 组件()
const 文 = JSON.stringify(树)
const 要有 = ['鱼搭子', '挂件程序', '送到哪一间', '本机口子', '回话递回', '立即保存', '改动会自动保存',
  '最近怎么样', '打开挂件', '还没听到它说话', '测试会话',
  '下载挂件', '打开下载页', '挂件位置']
const 缺 = 要有.filter((x) => !文.includes(x))
报('关键元素都渲染出来', 缺.length === 0, 缺.length ? '缺：' + 缺.join('、') : 文.length + ' 字节')

console.log(`\n${挂了 === 0 ? '全部通过 ✅' : `有 ${挂了} 条没过 ❌`}`)
process.exitCode = 挂了 === 0 ? 0 : 1
