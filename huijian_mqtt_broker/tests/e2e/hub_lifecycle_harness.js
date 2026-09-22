// hub 生命周期 e2e 的进程壳：按参数端口/storeFile 真起一个 hub（复用 hub 仓源码，
// 不复制协议实现——复制一份就是一份会漂移的影子契约）。
// HUB_REPO 指到 huijian-cloud-hub 仓根；本文件只做"起/停"，业务断言全在 driver.py。
const path = require('path')
const repo = process.env.HUB_REPO
if (!repo) { console.error('HUB_REPO 未设置'); process.exit(2) }
const { createHub } = require(path.join(repo, 'src', 'server.js'))

const port = Number(process.argv[2])
const storeFile = process.argv[3]
const installKey = process.env.HUB_INSTALL_KEY || 'e2e-install-key'
const quiet = process.env.HUB_VERBOSE ? console : { log() {}, error() {}, warn() {} }

const hub = createHub({ storeFile, installKey, cmdTimeoutMs: 800, pingIntervalMs: 60000, logger: quiet })
hub.listen(port, () => console.log('HUB_READY ' + port + ' ' + storeFile))

// storeFile 被删（＝容器重启后本地盘空了）时不需要特殊处理：hub 每次读写都按当前文件走，
// 真栈场景里"抹盘"是**重启进程**完成的，与线上同形。
process.on('SIGTERM', () => process.exit(0))
