/*
 * starsky.js —— 「星辰大海」星野生成器（v1.6.27，纯装饰层）
 *
 * 对齐小程序标准条 0d2200c5/901a18df 的工程做法：mulberry32 **固定种子**
 * PRNG 生成星点与行星群——种子不变则每次加载同一片天（小程序里 14 页
 * 共用同一片星空即靠这个机制）。零依赖、零网络、不碰 huijian.js 任何
 * 数据路径；容器缺失即整体静默跳过（防御式，装饰层永不反噬功能层）。
 *
 * 数量与参数均取标准终版：
 *  - 星点双层视差（far 细小慢闪 / near 稍亮），明灭单峰触零；
 *  - 行星 16 颗：3/4/6px 三档、辉光宁淡（α.35，晕 4~7px）、60% 压进
 *    左下星云区偏置；双层独立时钟：漂移 55~75s（≈1.5px/s 级）与明灭
 *    3.5~7s 解耦（耦合同一动画在标准评审里被否）。
 */
(function () {
    'use strict';

    // mulberry32：32bit 状态 PRNG，短小且跨引擎逐位确定
    function mulberry32(seed) {
        var a = seed >>> 0;
        return function () {
            a = (a + 0x6D2B79F5) >>> 0;
            var t = a;
            t = Math.imul(t ^ (t >>> 15), 1 | t);
            t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
        };
    }

    // 固定种子＝本仓库的"那一片天"（改动会让全体用户换星空，勿动）
    var rnd = mulberry32(0x5EA7C0DE);
    function between(min, max) { return min + rnd() * (max - min); }
    function pick(arr) { return arr[Math.floor(rnd() * arr.length)]; }

    var SKY_SEED = 0x5EA7C0DE; // （文档性常量：回归测试锚定其存在）

    function el(cls, parent) {
        var n = document.createElement('div');
        n.className = cls;
        parent.appendChild(n);
        return n;
    }

    function makeStars(containerId, count, sizeMin, sizeMax, durMin, durMax, peakMin, peakMax) {
        var host = document.getElementById(containerId);
        if (!host) return;
        var frag = document.createDocumentFragment();
        for (var i = 0; i < count; i++) {
            var s = document.createElement('i');
            var size = between(sizeMin, sizeMax).toFixed(2);
            s.style.cssText =
                'left:' + (rnd() * 100).toFixed(2) + '%;' +
                'top:' + (rnd() * 100).toFixed(2) + '%;' +
                'width:' + size + 'px;height:' + size + 'px;' +
                '--dur:' + between(durMin, durMax).toFixed(2) + 's;' +
                '--delay:-' + between(0, durMax).toFixed(2) + 's;' +
                '--peak:' + between(peakMin, peakMax).toFixed(2) + ';';
            frag.appendChild(s);
        }
        host.appendChild(frag);
    }

    function makePlanets() {
        var host = document.getElementById('planets');
        if (!host) return;
        var palette = ['#7dd3fc', '#38bdf8', '#0ea5e9', '#e0f2fe'];
        var frag = document.createDocumentFragment();
        for (var i = 0; i < 16; i++) {
            var inNebula = (i % 10) < 6;   // 60% 压进左下星云区（标准偏置）
            var x = inNebula ? between(2, 52) : between(2, 96);
            var y = inNebula ? between(52, 96) : between(2, 96);
            var size = pick([3, 3, 4, 4, 6]);       // 三档，小星占多
            var drift = between(55, 75);            // 漂移一圈 55~75s
            var twk = between(3.5, 7);              // 明灭单周期 3.5~7s
            var ang = rnd() * Math.PI * 2;
            var dist = between(18, 42);             // 位移幅度→≈0.5~1.2px/s，宁慢
            var wrap = el('orbit-wrap', frag);
            wrap.style.cssText =
                'left:' + x.toFixed(2) + '%;top:' + y.toFixed(2) + '%;' +
                '--drift:' + drift.toFixed(1) + 's;' +
                '--delay:-' + between(0, drift).toFixed(1) + 's;' +
                '--dx:' + (Math.cos(ang) * dist).toFixed(1) + 'px;' +
                '--dy:' + (Math.sin(ang) * dist * 0.7).toFixed(1) + 'px;';
            var p = document.createElement('span');
            p.className = 'planet';
            p.style.cssText =
                '--sz:' + size + 'px;' +
                '--pc:' + pick(palette) + ';' +
                '--twk:' + twk.toFixed(2) + 's;' +
                '--blur:' + (size + between(1, 3)).toFixed(1) + 'px;' +   // 晕 4~7px 档
                '--halo:' + (size >= 6 ? 3 : 2) + 'px;' +
                '--peak:' + between(0.6, 0.95).toFixed(2) + ';';
            wrap.appendChild(p);
        }
        host.appendChild(frag);
    }

    makeStars('starsFar', 70, 0.6, 1.4, 4, 9, 0.35, 0.6);
    makeStars('starsNear', 36, 1.2, 2.2, 3.5, 7, 0.5, 0.8);
    makePlanets();
})();
