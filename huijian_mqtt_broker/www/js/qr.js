// www/js/qr.js —— 零依赖二维码编码器（字节模式，版本 1–6，L/M/Q/H）。
//
// v1.7.38：加载项面板要在 logo 旁直接显示绑定码二维码。ingress iframe 有 CSP、
// 且本仓前端从不连外网——所以不能引 CDN 库，必须自带实现（本文件不 import、
// 不 fetch、不发任何网络请求，守卫钉死）。
//
// 正确性口径：算法按 ISO/IEC 18004 实现（模式/填充/RS 纠错/分块交织/格式信息
// BCH(15,5)/八种掩码+罚分选优），并用 Python `qrcode`（独立实现）的矩阵做黄金
// 对照——tests/test_v1738_qr.py 逐格比对，改坏即红。
//
// 导出：浏览器挂 window.HjQr；node 下走 module.exports（测试用）。
(function (root, factory) {
    if (typeof module === 'object' && module.exports) module.exports = factory()
    else root.HjQr = factory()
})(typeof self !== 'undefined' ? self : this, function () {
    'use strict'

    // 分块表 [块数, 块总码字, 数据码字]（版本 1–6 × L/M/Q/H，取自 ISO 18004 表 13-22）
    var RS_BLOCKS = {
        '1L': [[1, 26, 19]], '1M': [[1, 26, 16]], '1Q': [[1, 26, 13]], '1H': [[1, 26, 9]],
        '2L': [[1, 44, 34]], '2M': [[1, 44, 28]], '2Q': [[1, 44, 22]], '2H': [[1, 44, 16]],
        '3L': [[1, 70, 55]], '3M': [[1, 70, 44]], '3Q': [[2, 35, 17]], '3H': [[2, 35, 13]],
        '4L': [[1, 100, 80]], '4M': [[2, 50, 32]], '4Q': [[2, 50, 24]], '4H': [[4, 25, 9]],
        '5L': [[1, 134, 108]], '5M': [[2, 67, 43]], '5Q': [[2, 33, 15], [2, 34, 16]], '5H': [[2, 33, 11], [2, 34, 12]],
        '6L': [[2, 86, 68]], '6M': [[4, 43, 27]], '6Q': [[4, 43, 19]], '6H': [[4, 43, 15]]
    }
    var ALIGN = [[], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34]]
    // 格式信息里的纠错级别编码（标准表：L=01 M=00 Q=11 H=10）
    var ECC_BITS = { L: 1, M: 0, Q: 3, H: 2 }

    // ── GF(2^8) ────────────────────────────────────────────────────
    var EXP = new Array(256), LOG = new Array(256)
    ;(function () {
        var x = 1
        for (var i = 0; i < 255; i++) { EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 0x100) x ^= 0x11d }
        for (var j = 255; j < 256; j++) EXP[j] = EXP[j - 255]
        LOG[0] = undefined
    })()
    function gmul(a, b) { return (a === 0 || b === 0) ? 0 : EXP[(LOG[a] + LOG[b]) % 255] }

    function rsGenPoly(ecLen) {
        var p = [1]
        for (var i = 0; i < ecLen; i++) {
            var next = new Array(p.length + 1)
            for (var k = 0; k < next.length; k++) next[k] = 0
            for (var j = 0; j < p.length; j++) {
                next[j] ^= p[j]
                next[j + 1] ^= gmul(p[j], EXP[i])
            }
            p = next
        }
        return p
    }

    function rsRemainder(data, ecLen) {
        var gen = rsGenPoly(ecLen)
        var res = data.concat(new Array(ecLen))
        for (var i = 0; i < data.length; i++) {
            var coef = res[i]
            if (!coef) continue
            for (var j = 0; j < gen.length; j++) res[i + j] ^= gmul(gen[j], coef)
        }
        return res.slice(data.length)
    }

    // ── 数据码字 ───────────────────────────────────────────────────
    function utf8Bytes(text) {
        var out = []
        for (var i = 0; i < text.length; i++) {
            var c = text.charCodeAt(i)
            if (c < 0x80) out.push(c)
            else if (c < 0x800) { out.push(0xc0 | (c >> 6), 0x80 | (c & 0x3f)) }
            else if (c >= 0xd800 && c <= 0xdbff && i + 1 < text.length) {
                var c2 = text.charCodeAt(++i)
                var cp = 0x10000 + ((c - 0xd800) << 10) + (c2 - 0xdc00)
                out.push(0xf0 | (cp >> 18), 0x80 | ((cp >> 12) & 0x3f), 0x80 | ((cp >> 6) & 0x3f), 0x80 | (cp & 0x3f))
            } else { out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 0x3f), 0x80 | (c & 0x3f)) }
        }
        return out
    }

    function dataCodewordCount(version, ecc) {
        var groups = RS_BLOCKS[version + ecc]
        var n = 0
        for (var i = 0; i < groups.length; i++) n += groups[i][0] * groups[i][2]
        return n
    }

    /** 字节模式位流：0100 + 长度(8bit, 版本1-9) + 数据 + 终止符 + 字节对齐 + 填充 EC/11 */
    function buildDataCodewords(text, version, ecc) {
        var bytes = utf8Bytes(text)
        var capacity = dataCodewordCount(version, ecc)          // 码字数
        var needBits = 4 + 8 + bytes.length * 8
        if (needBits > capacity * 8) throw new Error('qr: payload too long for version ' + version + ecc)
        var bits = []
        var push = function (val, len) { for (var i = len - 1; i >= 0; i--) bits.push((val >> i) & 1) }
        push(4, 4)                                              // 字节模式
        push(bytes.length, 8)
        for (var i = 0; i < bytes.length; i++) push(bytes[i], 8)
        var term = Math.min(4, capacity * 8 - bits.length)
        push(0, term)
        while (bits.length % 8 !== 0) bits.push(0)
        var codewords = []
        for (var b = 0; b < bits.length; b += 8) {
            var v = 0
            for (var k = 0; k < 8; k++) v = (v << 1) | bits[b + k]
            codewords.push(v)
        }
        var pad = [0xec, 0x11], p = 0
        while (codewords.length < capacity) codewords.push(pad[p++ % 2])
        return codewords
    }

    /** 分块 + RS 纠错 + 交织（数据块间轮转，再纠错块间轮转） */
    function interleaveWithEcc(codewords, version, ecc) {
        var groups = RS_BLOCKS[version + ecc]
        var blocks = [], pos = 0
        for (var g = 0; g < groups.length; g++) {
            for (var n = 0; n < groups[g][0]; n++) {
                var total = groups[g][1], dataLen = groups[g][2]
                var data = codewords.slice(pos, pos + dataLen)
                pos += dataLen
                blocks.push({ data: data, ecc: rsRemainder(data, total - dataLen) })
            }
        }
        var maxData = 0, maxEcc = 0
        for (var i = 0; i < blocks.length; i++) {
            maxData = Math.max(maxData, blocks[i].data.length)
            maxEcc = Math.max(maxEcc, blocks[i].ecc.length)
        }
        var out = []
        for (var c = 0; c < maxData; c++) {
            for (var b = 0; b < blocks.length; b++) if (c < blocks[b].data.length) out.push(blocks[b].data[c])
        }
        for (var c2 = 0; c2 < maxEcc; c2++) {
            for (var b2 = 0; b2 < blocks.length; b2++) if (c2 < blocks[b2].ecc.length) out.push(blocks[b2].ecc[c2])
        }
        return out
    }

    // ── 矩阵 ───────────────────────────────────────────────────────
    function makeMatrix(size) {
        var m = []
        for (var i = 0; i < size; i++) { m.push(new Array(size)); for (var j = 0; j < size; j++) m[i][j] = null }
        m.size = size
        return m
    }

    function placeFinder(m, row, col) {
        for (var r = -1; r <= 7; r++) {
            for (var c = -1; c <= 7; c++) {
                var rr = row + r, cc = col + c
                if (rr < 0 || rr >= m.size || cc < 0 || cc >= m.size) continue
                var on = (r >= 0 && r <= 6 && (c === 0 || c === 6)) ||
                    (c >= 0 && c <= 6 && (r === 0 || r === 6)) ||
                    (r >= 2 && r <= 4 && c >= 2 && c <= 4)
                m[rr][cc] = on ? 1 : 0
            }
        }
    }

    function placeAlignment(m, version) {
        var pos = ALIGN[version - 1]
        for (var i = 0; i < pos.length; i++) {
            for (var j = 0; j < pos.length; j++) {
                var row = pos[i], col = pos[j]
                if (m[row][col] !== null) continue                 // 与定位图案重叠处跳过
                for (var r = -2; r <= 2; r++) {
                    for (var c = -2; c <= 2; c++) {
                        var on = Math.max(Math.abs(r), Math.abs(c)) !== 1
                        m[row + r][col + c] = on ? 1 : 0
                    }
                }
            }
        }
    }

    function placeTiming(m) {
        for (var i = 8; i < m.size - 8; i++) {
            var on = i % 2 === 0 ? 1 : 0
            if (m[6][i] === null) m[6][i] = on
            if (m[i][6] === null) m[i][6] = on
        }
    }

    function bchTypeInfo(data) {          // (15,5) BCH，生成多项式 0x537，掩码 0x5412
        var v = data << 10
        for (var i = 4; i >= 0; i--) if (v & (1 << (i + 10))) v ^= 0x537 << i
        return ((data << 10) | v) ^ 0x5412
    }

    function placeFormatInfo(m, ecc, mask) {
        var bits = bchTypeInfo((ECC_BITS[ecc] << 3) | mask)
        for (var i = 0; i < 15; i++) {
            var on = (bits >> i) & 1
            if (i < 6) m[i][8] = on
            else if (i < 8) m[i + 1][8] = on
            else m[m.size - 15 + i][8] = on
            if (i < 8) m[8][m.size - i - 1] = on
            else if (i < 9) m[8][15 - i - 1 + 1] = on
            else m[8][15 - i - 1] = on
        }
        m[m.size - 8][8] = 1                                   // 固定暗模块
    }

    function maskFn(mask, r, c) {
        switch (mask) {
            case 0: return (r + c) % 2 === 0
            case 1: return r % 2 === 0
            case 2: return c % 3 === 0
            case 3: return (r + c) % 3 === 0
            case 4: return (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0
            case 5: return ((r * c) % 2) + ((r * c) % 3) === 0
            case 6: return (((r * c) % 2) + ((r * c) % 3)) % 2 === 0
            case 7: return (((r + c) % 2) + ((r * c) % 3)) % 2 === 0
        }
    }

    function placeData(m, codewords, mask) {
        var bitIndex = 0, total = codewords.length * 8
        var upward = true
        for (var right = m.size - 1; right >= 1; right -= 2) {
            if (right === 6) right = 5                              // 跳过竖直定时列
            for (var vert = 0; vert < m.size; vert++) {
                var row = upward ? m.size - 1 - vert : vert
                for (var k = 0; k < 2; k++) {
                    var col = right - k
                    if (m[row][col] !== null) continue
                    var bit = 0
                    if (bitIndex < total) {
                        bit = (codewords[bitIndex >> 3] >> (7 - (bitIndex & 7))) & 1
                        bitIndex++
                    }
                    if (maskFn(mask, row, col)) bit ^= 1
                    m[row][col] = bit
                }
            }
            upward = !upward
        }
    }

    function penalty(m) {
        var n = m.size, score = 0, i, j, run, dark = 0
        // 规则 1：行/列同色连跑 ≥5
        for (i = 0; i < n; i++) {
            for (var dir = 0; dir < 2; dir++) {
                run = 1
                for (j = 1; j < n; j++) {
                    var cur = dir ? m[j][i] : m[i][j], prev = dir ? m[j - 1][i] : m[i][j - 1]
                    if (cur === prev) { run++; if (run === 5) score += 3; else if (run > 5) score += 1 }
                    else run = 1
                }
            }
        }
        // 规则 2：2×2 同色块
        for (i = 0; i < n - 1; i++) {
            for (j = 0; j < n - 1; j++) {
                var a = m[i][j]
                if (a === m[i][j + 1] && a === m[i + 1][j] && a === m[i + 1][j + 1]) score += 3
            }
        }
        // 规则 3：1:1:3:1:1 型（两侧留白 4）
        var pat1 = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
        var pat2 = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1]
        var matchPat = function (get, k, pat) {
            for (var t = 0; t < 11; t++) if (get(k + t) !== pat[t]) return false
            return true
        }
        for (i = 0; i < n; i++) {
            for (j = 0; j <= n - 11; j++) {
                if (matchPat(function (x) { return m[i][x] }, j, pat1)) score += 40
                if (matchPat(function (x) { return m[i][x] }, j, pat2)) score += 40
                if (matchPat(function (x) { return m[x][i] }, j, pat1)) score += 40
                if (matchPat(function (x) { return m[x][i] }, j, pat2)) score += 40
            }
        }
        // 规则 4：暗模块占比偏离 50%
        for (i = 0; i < n; i++) for (j = 0; j < n; j++) dark += m[i][j] ? 1 : 0
        var ratio = Math.abs(dark * 100 / (n * n) - 50)
        score += Math.floor(ratio / 5) * 10
        return score
    }

    function buildMatrix(text, options) {
        options = options || {}
        var ecc = options.ecc || 'M'
        if (!ECC_BITS.hasOwnProperty(ecc)) throw new Error('qr: bad ecc ' + ecc)
        var bytes = utf8Bytes(text).length
        var version = options.version || 0
        if (!version) {
            for (var v = 1; v <= 6; v++) if (4 + 8 + bytes * 8 <= dataCodewordCount(v, ecc) * 8) { version = v; break }
            if (!version) throw new Error('qr: payload too long for version <= 6')
        }
        var codewords = interleaveWithEcc(buildDataCodewords(text, version, ecc), version, ecc)
        var size = version * 4 + 17
        var masks = (typeof options.mask === 'number') ? [options.mask] : [0, 1, 2, 3, 4, 5, 6, 7]
        var best = null
        for (var i = 0; i < masks.length; i++) {
            var m = makeMatrix(size)
            placeFinder(m, 0, 0); placeFinder(m, 0, size - 7); placeFinder(m, size - 7, 0)
            placeAlignment(m, version)
            placeTiming(m)
            placeFormatInfo(m, ecc, masks[i])
            placeData(m, codewords, masks[i])
            var p = penalty(m)
            if (!best || p < best.penalty) best = { penalty: p, mask: masks[i], modules: m }
        }
        return best
    }

    /** 文本 → 模块矩阵（1/0 二维数组），供渲染与测试使用 */
    function matrix(text, options) {
        var res = buildMatrix(text, options)
        var out = []
        for (var i = 0; i < res.modules.size; i++) {
            var row = []
            for (var j = 0; j < res.modules.size; j++) row.push(res.modules[i][j] ? 1 : 0)
            out.push(row)
        }
        return { modules: out, mask: res.mask, size: res.modules.size, penalty: res.penalty }
    }

    /** 生成 SVG 字符串（含 4 模块静区；纯字符串拼接，不碰 DOM/网络） */
    function svg(text, options) {
        options = options || {}
        var quiet = options.quiet == null ? 4 : options.quiet
        var res = matrix(text, options)
        var n = res.size + quiet * 2
        return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + n + ' ' + n + '" ' +
            'shape-rendering="crispEdges" width="100%" height="100%" role="img" aria-label="绑定码二维码">' +
            '<rect width="' + n + '" height="' + n + '" fill="#fff"></rect>' +
            '<path d="' + pathData(res, quiet) + '" fill="#000"></path></svg>'
    }

    function pathData(res, quiet) {
        var path = []
        for (var r = 0; r < res.size; r++) {
            for (var c = 0; c < res.size; c++) {
                if (res.modules[r][c]) path.push('M' + (c + quiet) + ' ' + (r + quiet) + 'h1v1h-1z')
            }
        }
        return path.join('')
    }

    /** 把二维码渲染进容器（浏览器用；整块替换容器内容，点击刷新即再调一次）。
     *  走 DOM API 逐个建节点，不把任何字符串当标记解析（注入面为零）。*/
    function render(container, text, options) {
        if (!container || !container.ownerDocument) return false
        var quiet = options && options.quiet != null ? options.quiet : 4
        var res = matrix(text, options)
        var n = res.size + quiet * 2
        var doc = container.ownerDocument
        var NS = 'http://www.w3.org/2000/svg'
        var el = doc.createElementNS(NS, 'svg')
        el.setAttribute('viewBox', '0 0 ' + n + ' ' + n)
        el.setAttribute('shape-rendering', 'crispEdges')
        el.setAttribute('width', '100%')
        el.setAttribute('height', '100%')
        el.setAttribute('role', 'img')
        el.setAttribute('aria-label', '绑定码二维码')
        var bg = doc.createElementNS(NS, 'rect')
        bg.setAttribute('width', String(n))
        bg.setAttribute('height', String(n))
        bg.setAttribute('fill', '#fff')
        el.appendChild(bg)
        var path = doc.createElementNS(NS, 'path')
        path.setAttribute('d', pathData(res, quiet))
        path.setAttribute('fill', '#000')
        el.appendChild(path)
        container.replaceChildren(el)
        return true
    }

    return { matrix: matrix, svg: svg, render: render, versions: 6, eccLevels: ['L', 'M', 'Q', 'H'] }
})
