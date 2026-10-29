// 鱼搭子 · 网页半边
//
// 在 **DSH 设置** 左侧栏加一项「鱼搭子」。这里只干一件事：
// 告诉 DSH「挂件说的话，要送进哪一间会话」，顺便看看口子通不通、最近发生了什么。
// 挂件自己是独立的桌面程序，不在这页里。

window.__ModuleLoader__.load({
  id: 'dsh-fish-buddy',
  factory: (require) => {
    var module = { exports: {} }
    var exports = module.exports

    const React = require('react')
    const inject = ['slots']

    const B = '/dsh-fish-buddy'
    const get = (p) => fetch(B + p, { cache: 'no-store' }).then((r) => r.json()).catch(() => null)
    const post = (p, body) =>
      fetch(B + p, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body || {}) })
        .then((r) => r.json())
        .catch(() => null)

    const h = React.createElement

    const S = {
      包: {
        padding: '12px 14px 28px',
        fontSize: 13,
        lineHeight: 1.7,
        background: 'var(--dsw-alias-bg-layer-1, rgba(255,255,255,.92))',
        border: '1px solid var(--dsw-alias-border-l1, rgba(0,0,0,.08))',
        borderRadius: 12,
      },
      小字: { opacity: 0.62, fontSize: 12 },
      卡: {
        border: '1px solid var(--dsw-alias-border-l2, rgba(0,0,0,.1))',
        borderRadius: 10,
        padding: '12px 14px',
        marginBottom: 12,
      },
      行: { display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 },
      输入: {
        flex: 1,
        minWidth: 200,
        padding: '6px 9px',
        fontSize: 13,
        borderRadius: 8,
        border: '1px solid var(--dsw-alias-border-l2, rgba(0,0,0,.14))',
        background: 'var(--dsw-alias-bg-layer-2, #fff)',
        color: 'inherit',
      },
      按钮: (主) => ({
        padding: '7px 16px',
        fontSize: 13,
        borderRadius: 8,
        cursor: 'pointer',
        border: '1px solid ' + (主 ? 'transparent' : 'var(--dsw-alias-border-l2, rgba(0,0,0,.14))'),
        background: 主 ? '#2f7fb8' : 'transparent',
        color: 主 ? '#fff' : 'inherit',
        fontWeight: 主 ? 600 : 400,
      }),
      日志行: { display: 'flex', gap: 8, padding: '3px 0', borderBottom: '1px dashed rgba(128,128,128,.18)' },
    }

    // 设置页表单的「最新值」镜像 + 自动保存定时器（放模块级：组件重渲染也不会丢）
let 镜像 = null
let 存定时 = null

function Section() {
      const [态, 设态] = React.useState(null)
      const [配置, 设配置] = React.useState({ 总开关: true, 端口: 8777, 会话: '', 回调: '', 带上来源: false })
      const [忙, 设忙] = React.useState(false)
      const [页, 设页] = React.useState('打电话')
      const [话, 设话] = React.useState('')
      // ⭐ 麦克风：设备在挂件那头，这边只列 + 发号施令
      const [麦, 设麦] = React.useState({ 列表: [], 当前: {}, 话: '', 读没读到: false })

      // ⭐ 0.1.1（换了会话、重启之后又变回去）：以前 5 秒一次自动刷新，
      //   会把**刚改还没保存**的选择直接刷回旧值，于是点保存存进去的还是旧的。
      //   现在：有没保存的改动时，刷新只更新状态、不动表单；存成功才清「脏」。
      const [脏, 设脏] = React.useState(false)
      // ⭐ 0.7.0：检查更新（插件自己 + 挂件 exe）
      const [更新, 设更新] = React.useState(null)
      const [查着, 设查着] = React.useState(false)
      const 查更新 = async () => {
        设查着(true)
        try {
          const r = await get('/update-check')
          设更新(r || { ok: false, 说: '查不到（网络？）' })
        } catch (error) {
          设更新({ ok: false, 说: String(error && error.message) })
        } finally {
          设查着(false)
        }
      }

      const 拉 = React.useCallback(async () => {
        const r = await get('/state')
        if (!r || !r.ok) {
          设话('读不到状态 —— 插件可能还没起来')
          return
        }
        设态(r)
        if (!脏) {
          设配置(r.配置)
          镜像 = r.配置
        }
      }, [脏])

      React.useEffect(() => {
        void 拉()
        const 定时 = setInterval(() => void 拉(), 5000)
        return () => clearInterval(定时)
      }, [拉])

      const 存 = async (体, 静默) => {
        设忙(true)
        const r = await post('/config', 体 || 镜像 || 配置)
        if (r && r.ok) 设脏(false)
        if (!静默 || !(r && r.ok)) {
          设话(r && r.ok ? '存好了' + (r.配置 && r.配置.端口 !== (态 && 态.口子 && 态.口子.端口) ? '（端口改了要重启 DSH）' : '') : (r && r.说) || '没存上')
        }
        设忙(false)
        void 拉()
      }

      // ⭐ 0.1.2（改了就实时保存）：不再需要点保存 —— 改动后 450ms 自动存一次。
      //   输入框连续打字只在停下来之后存一次，不会每敲一下发一个请求。
      const 改 = (键, 值) => {
        设脏(true)
        const 新 = { ...(镜像 || 配置), [键]: 值 }
        镜像 = 新
        设配置(新)
        if (存定时) clearTimeout(存定时)
        存定时 = setTimeout(() => { void 存(镜像, true) }, 450)
      }

      const 拉麦克风 = React.useCallback(async () => {
        const r = await get('/mic')
        设麦((前) => ({
          ...前,
          读没读到: true,
          列表: (r && r.设备 && r.设备.列表) || [],
          当前: (r && r.设备 && r.设备.当前) || {},
          话: (r && r.ok === false && r.说) || '',
        }))
      }, [])

      const 换麦克风 = async (值) => {
        let 号 = null
        let 名 = ''
        if (值 !== '') {
          const 项 = (麦.列表 || [])[Number(值)]
          if (项) { 号 = 项.编号; 名 = 项.名字 }
        }
        设麦((前) => ({ ...前, 话: '换着呢…' }))
        const r = await post('/mic/set', { index: 号, name: 名 })
        设麦((前) => ({ ...前, 话: (r && r.说) || (r && r.ok ? '换好了' : '没换成') }))
        void 拉麦克风()
      }

      // 进「设置」页才去问挂件（免得一打开面板就敲它的门）
      React.useEffect(() => {
        if (页 === '设置' && !麦.读没读到) void 拉麦克风()
      }, [页, 麦.读没读到, 拉麦克风])

      const 麦选中 = () => {
        const 列表 = 麦.列表 || []
        const 现在号 = 麦.当前 && 麦.当前.编号
        const 现在名 = (麦.当前 && 麦.当前.名字) || ''
        if (现在号 !== null && 现在号 !== undefined && 现在号 !== '') {
          for (let i = 0; i < 列表.length; i += 1) {
            if (String(列表[i].编号) === String(现在号)) return String(i)
          }
        }
        if (现在名) {
          for (let i = 0; i < 列表.length; i += 1) {
            if (列表[i].名字 === 现在名) return String(i)
          }
        }
        return ''
      }

      const 开挂件 = async () => {
        const r = await post('/launch', {})
        设话((r && r.说) || '没反应')
        void 拉()
      }

      const 口子 = (态 && 态.口子) || {}
      const 挂件 = (态 && 态.挂件) || {}
      const 秒前 = Number(挂件.最后说话秒前)
      const 清单 = (态 && 态.会话清单) || []
      const 日志 = (态 && 态.日志) || []

      return h('div', { style: S.包 },
        h('div', { style: { fontSize: 15, fontWeight: 600, marginBottom: 4 } }, '鱼搭子'),
        h('div', { style: S.小字 }, '桌面那个小鱼挂件是**独立的程序**，不在这页里；这页只管接线和开关。'),

        h('div', { style: { display: 'flex', gap: 6, margin: '12px 0 4px', flexWrap: 'wrap' } },
          ['打电话', '陪看', '打游戏', '设置'].map((名) => h('button', {
            key: 名,
            style: {
              padding: '5px 12px',
              fontSize: 13,
              borderRadius: 999,
              cursor: 'pointer',
              border: '1px solid ' + (页 === 名 ? '#2f7fb8' : 'var(--dsw-alias-border-l2, rgba(0,0,0,.14))'),
              background: 页 === 名 ? 'rgba(47,127,184,.14)' : 'transparent',
              color: 'inherit',
              fontWeight: 页 === 名 ? 600 : 400,
            },
            onClick: () => 设页(名),
          }, 名))),

        页 === '陪看' ? h('div', { style: S.卡 },
          h('div', { style: { fontWeight: 600, marginBottom: 6 } }, '陪看（字幕白板）'),
          h('div', { style: S.小字 },
            '挂件放视频/直播时，字幕会一句句推到这里。它**不写进对话历史**，只是每轮临时拼进去 —— '
            + '所以她一眼就能看到最近这段，想说的时候再说，不会越看越厚。'),
          态 && 态.字幕
            ? h('div', { style: { marginTop: 8 } },
              h('div', { style: S.小字 },
                '现在缓存 ' + 态.字幕.条数 + ' 句'
                + (态.字幕.滚掉 ? '（前面还有 ' + 态.字幕.滚掉 + ' 句已经翻过去了）' : '')
                + '　白板：' + (态.字幕.白板挂着 ? '● 挂着' : '○ 还没挂（没字幕时不占地方）')))
            : h('div', { style: S.小字 }, '还没有字幕。'),
        ) : null,

        页 === '打游戏' ? h('div', null,
          h('div', { style: S.卡 },
            h('div', { style: { fontWeight: 600, marginBottom: 6 } }, '截图怎么送'),
            h('div', { style: S.小字 }, '这些在挂件的「设置 → 游戏」里调；这里只是说明现在是什么样。'),
            h('div', { style: { marginTop: 6 } }, '● 每张都说一遍：截一张就说一次（花钱多）'),
            h('div', null, '● 攒着，说话时一起看：最多留 3 张，你说话时一起带过去（省钱）'),
            h('div', { style: { ...S.小字, marginTop: 6 } },
              '攒着那一档还能让她「主动看一眼」（隔几分钟自己开口），也只在那一档生效 ——'
              + '「每张都说」时截图本来就叫醒她，再叠一层白花钱。'),
          ),
          // ⭐ 0.7.0：检查更新（插件 + 挂件 exe）
          h('div', { style: { ...S.卡, marginTop: 14 } },
            h('div', { style: { fontWeight: 600, marginBottom: 6 } }, '检查更新'),
            h('div', { style: S.行 },
              h('button', {
                onClick: 查更新,
                disabled: 查着,
                style: { padding: '6px 14px', cursor: 查着 ? 'default' : 'pointer' },
              }, 查着 ? '查着…' : '查一下'),
              h('span', { style: { ...S.小字, marginLeft: 10 } }, '查插件本身 + 挂件 exe 有没有新版'),
            ),
            更新 ? h('div', { style: { marginTop: 8, lineHeight: 1.7 } },
              h('div', null, '插件：' + ((更新.插件 && 更新.插件.本地) || '?')
                + (更新.插件 && 更新.插件.最新 ? ('　最新：' + 更新.插件.最新) : '　（查不到线上版本）')
                + (更新.插件 && 更新.插件.有新版 ? '　→ 有新版' : '　→ 最新')
                + (更新.插件 && 更新.插件.本地开发版 ? '　（你这台是本地开发版，比线上还新）' : '')),
              h('div', null, '挂件：' + ((更新.挂件 && 更新.挂件.本地) || '?')
                + (更新.挂件 && 更新.挂件.最新 ? ('　最新：' + 更新.挂件.最新) : '　（查不到最新版）')
                + (更新.挂件 && 更新.挂件.有新版 ? '　→ 有新版' : '　→ 最新')),
              更新.挂件 && 更新.挂件.有新版 && 更新.挂件.下载
                ? h('div', { style: { marginTop: 6 } },
                    h('a', { href: 更新.挂件.下载, target: '_blank', rel: 'noreferrer' },
                      '下载新版挂件（替换掉旧的那个 exe 就行）'))
                : null,
              更新.挂件 && 更新.挂件.说明 ? h('div', { style: S.小字 }, 更新.挂件.说明) : null,
              !更新.ok ? h('div', { style: S.小字 }, '没查到：' + (更新.说 || '不知道为啥')) : null,
            ) : null,
          ),
        ) : null,

        h('div', { style: { display: 页 === '打电话' ? 'block' : 'none' } },
        h('div', { style: { ...S.卡, marginTop: 14 } },
          h('div', { style: S.行 },
            h('label', { style: { display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer' } },
              h('input', {
                type: 'checkbox',
                checked: 配置.总开关 !== false,
                onChange: (e) => 改('总开关', e.target.checked),
              }),
              h('span', null, '开着（关掉之后挂件发什么都不往里送）'),
            ),
          ),
          h('div', { style: S.行 },
            h('label', { style: { display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer' } },
              h('input', {
                type: 'checkbox',
                checked: 配置.自动开挂件 !== false,
                onChange: (e) => 改('自动开挂件', e.target.checked),
              }),
              h('span', null, 'DSH 起来时自动把挂件打开（默认开着；关掉就得自己点）'),
            ),
          ),
          h('div', { style: S.行 },
            h('span', { style: { minWidth: 84 } }, '送到哪一间'),
            h('select', {
              style: S.输入,
              value: 配置.会话 || '',
              onChange: (e) => 改('会话', e.target.value),
            },
              h('option', { value: '' }, '（还没选）'),
              ...清单.map((x) => h('option', { key: x.值, value: x.值 }, x.名)),
            ),
          ),
          h('div', { style: S.行 },
            h('span', { style: { minWidth: 84 } }, '本机口子'),
            h('input', {
              style: { ...S.输入, maxWidth: 110 },
              value: 配置.端口,
              onChange: (e) => 改('端口', e.target.value.replace(/[^0-9]/g, '')),
            }),
            h('span', { style: S.小字 }, '挂件往 127.0.0.1:' + (配置.端口 || 8777) + '/hands/say 发话'),
            h('span', {
              style: {
                marginLeft: 'auto',
                fontWeight: 600,
                color: 口子.起没起 ? '#2f8f63' : '#c0392b',
              },
            }, 口子.起没起 ? '● 开着' : '○ 没开' + (口子.错 ? '（' + 口子.错 + '）' : '')),
          ),
          h('div', { style: S.行 },
            h('span', { style: { minWidth: 84 } }, '回话递回'),
            h('input', {
              style: S.输入,
              placeholder: '例如 http://127.0.0.1:8778/hands/reply（挂件那边留的口子，没有就空着）',
              value: 配置.回调 || '',
              onChange: (e) => 改('回调', e.target.value),
            }),
          ),
          h('div', { style: S.行 },
            h('label', { style: { display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer' } },
              h('input', {
                type: 'checkbox',
                checked: 配置.带上来源 === true,
                onChange: (e) => 改('带上来源', e.target.checked),
              }),
              h('span', null, '塞进会话时前面标一句「（你说的）」（一般不用勾）'),
            ),
          ),
          h('div', { style: { ...S.行, marginBottom: 0 } },
            h('button', { style: S.按钮(true), onClick: () => void 存(镜像, false), disabled: 忙 }, 忙 ? '存…' : '立即保存'),
            脏 ? h('span', { style: { ...S.小字, color: '#c0392b', fontWeight: 600 } }, '有改动还没保存') : null,
            h('span', { style: S.小字 }, '改动会自动保存，这个按钮只是兜底'),
            话 ? h('span', { style: S.小字 }, 话) : null,
          ),
        ),
        ),

        h('div', { style: { display: 页 === '设置' ? 'block' : 'none' } },
        h('div', { style: S.卡 },
          h('div', { style: { fontWeight: 600, marginBottom: 6 } }, '麦克风'),
          h('div', { style: S.小字 },
            '电话用的是这台电脑的麦克风。不填就跟着系统默认走；'
            + '换台机器、插了耳机 / 麦克风之后，系统默认常常不是你想用的那只 —— 在这里挑。'),
          h('div', { style: { ...S.行, marginTop: 8, marginBottom: 0 } },
            h('select', {
              style: { ...S.输入, maxWidth: 360 },
              value: 麦选中(),
              onChange: (e) => void 换麦克风(e.target.value),
            },
              h('option', { value: '' }, '（系统默认）'),
              (麦.列表 || []).map((x, i) => h('option', { key: i, value: String(i) },
                x.名字 + (x.默认 ? '　● 系统默认' : ''))),
            ),
            h('button', { style: S.按钮(false), onClick: () => void 拉麦克风() }, '刷新'),
            麦.话 ? h('span', { style: S.小字 }, 麦.话) : null,
          ),
          (麦.读没读到 && !(麦.列表 || []).length)
            ? h('div', { style: { ...S.小字, color: '#c0392b' } },
              '挂件没报上来设备 —— 它开着了没？（挂件里也能改：点上面那块 → 麦克风）')
            : null,
        ),

        h('div', { style: S.卡 },
          h('div', { style: { fontWeight: 600, marginBottom: 6 } }, '挂件程序'),
          h('div', { style: S.小字 },
            '桌面那个小鱼是独立程序（不是网页）。它没开着的时候，这边收不到任何话。'),
          h('div', { style: { ...S.行, marginTop: 8, marginBottom: 0 } },
            h('span', {
              style: { fontWeight: 600, color: (秒前 >= 0 && 秒前 < 120) ? '#2f8f63' : '#c0392b' },
            }, 秒前 >= 0 && 秒前 < 120
              ? ('● 刚说过话（' + 秒前 + ' 秒前）')
              : (秒前 >= 0 ? ('○ 上次说话是 ' + Math.round(秒前 / 60) + ' 分钟前') : '○ 还没听到它说话')),
            h('span', { style: S.小字 }, 挂件.找到 ? ('路径：' + 挂件.路径) : '还没找到它的 exe'),
            h('button', { style: S.按钮(true), onClick: 开挂件 }, '打开挂件'),
            h('button', {
              style: S.按钮(false),
              disabled: !!((态 && 态.下载) && 态.下载.在下载),
              onClick: async () => {
                try {
                  const r = await post('/fetch', {})
                  设话(r && r.ok ? '下好了，点「打开挂件」' : '没下成：' + ((r && r.说) || '不知道为啥'))
                } catch (e) {
                  设话('没下成：' + String(e && e.message ? e.message : e))
                }
              },
            }, (态 && 态.下载 && 态.下载.在下载) ? '正在下载…' : '下载挂件'),
          ),
          (态 && 态.下载)
            ? h('div', {
              style: {
                ...S.小字,
                color: 态.下载.出错 ? '#c0392b' : '#2f8f63',
                marginTop: 4,
              },
            }, 态.下载.出错 ? ('出错：' + 态.下载.出错) : (态.下载.说 || ''))
            : null,
          h('div', { style: S.行 },
            h('span', { style: { minWidth: 84 } }, '下载页'),
            h('input', {
              style: S.输入,
              placeholder: 'Release 页面地址（留空就用仓库默认的）',
              value: 配置.下载地址 || '',
              onChange: (e) => 改('下载地址', e.target.value),
            }),
            h('button', {
              style: S.按钮(false),
              onClick: () => {
                const 址 = String(配置.下载地址 || '').trim()
                  || 'https://github.com/Yuuyuko-uu/dsh-fish-buddy/releases'
                window.open(址, '_blank', 'noopener')
              },
            }, '打开下载页'),
          ),

          h('div', { style: S.行 },
            h('span', { style: { minWidth: 84 } }, '挂件位置'),
            h('input', {
              style: S.输入,
              placeholder: '没找到就手动填：鱼搭子.exe 的完整路径',
              value: 配置.挂件路径 || '',
              onChange: (e) => 改('挂件路径', e.target.value),
            }),
          ),
        ),

        h('div', { style: S.卡 },
          h('div', { style: { fontWeight: 600, marginBottom: 6 } }, '最近怎么样'),
          h('div', { style: S.小字 },
            '挂件发来 ' + ((态 && 态['收到条数']) || 0) + ' 条 · 送进会话 ' + ((态 && 态['送出条数']) || 0) + ' 条 · 回话递回 ' + ((态 && 态.递回条数) || 0) + ' 次'),
          态 && 态.最后回话 && 态.最后回话.文本
            ? h('div', { style: { marginTop: 8, padding: '8px 10px', background: 'rgba(47,127,184,.08)', borderRadius: 8 } },
              h('div', { style: S.小字 }, '她最近说的一句'),
              h('div', null, 态.最后回话.文本.slice(0, 200)))
            : null,
        ),

        h('div', { style: S.卡 },
          h('div', { style: { fontWeight: 600, marginBottom: 6 } }, '日志'),
          日志.length
            ? 日志.slice(0, 30).map((x, i) => h('div', { key: i, style: S.日志行 },
              h('span', { style: { ...S.小字, minWidth: 58 } }, new Date(x.时).toTimeString().slice(0, 8)),
              h('span', null, x.说)))
            : h('div', { style: S.小字 }, '还没有记录。'),
        ),

        h('div', { style: { ...S.小字, marginTop: 4 } },
          '挂件那边（外面那个程序）只要往 127.0.0.1:' + (配置.端口 || 8777) + '/hands/say POST 一段话就行，',
          '参数是 {"text": "说了什么"}；陪看的字幕推到 /hands/subtitle。'),
        ),
      )
    }

    function apply(ctx) {
      const slots = ctx.get('slots')
      if (slots === undefined) return
      slots.inject('settings.section', () =>
        slots.register(
          { name: 'settings.section', id: 'fish-buddy', order: 56, label: () => '鱼搭子' },
          Section,
        ),
      )
    }

    exports.apply = apply
    exports.inject = inject
    return module.exports
  },
})
