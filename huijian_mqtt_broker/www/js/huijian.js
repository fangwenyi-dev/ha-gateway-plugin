        const DOMAIN = 'window_controller_gateway';

        // v1.6.3：页头/页脚的初始版本号不再硬编码——脚本在 body 末尾，
        // 启动即与 CURRENT_VERSION 常量同步；之后 /api/version 拉到真实版本再刷新。
        // 旧实现硬编码 v1.5.1，/api/version 失败时页面永远显示过期版本号。
        document.getElementById('addonVersion').textContent = 'v' + CURRENT_VERSION;
        document.getElementById('footerVersion').textContent = 'v' + CURRENT_VERSION;

        // Ingress 下页面路径形如 /api/hassio_ingress/<token>/index.html（或带尾斜杠），
        // 直连插件端口 8099 时为 /index.html。去掉最后一段得到部署基路径。
        const INGRESS_BASE = window.location.pathname.replace(/\/[^/]*$/, '/');
        // 各配置条目的网关 SN（控制操作后刷新设备用，避免空 SN 误匹配首个实体）
        const GATEWAY_SN_BY_ENTRY = {};

        // ========== 初始化 ==========
        async function init() {
            // 静态徽章先落当前内置版本（防 /api/version 失败时页面顶部空白/陈旧）
            document.getElementById('addonVersion').textContent = 'v' + CURRENT_VERSION;
            document.getElementById('footerVersion').textContent = 'v' + CURRENT_VERSION;
            try {
                // v1.6.6：显式禁缓存——插件更新后浏览器启发式缓存仍供旧
                // version.json/index.html 导致页面版本号陈旧（1.6.4→1.6.5 实锤）
                const verResp = await fetchT(INGRESS_BASE + 'api/version', { cache: 'no-store' }, 8000);
                if (verResp.ok) {
                    const verData = await verResp.json();
                    CURRENT_VERSION = verData.addon_version || CURRENT_VERSION;
                    document.getElementById('addonVersion').textContent = 'v' + CURRENT_VERSION;
                    document.getElementById('footerVersion').textContent = 'v' + CURRENT_VERSION;
                }
            } catch (e) { console.log('版本获取失败:', e); }
            await refreshAll();
            // v1.6.4：自动静默检查一次更新（只点亮徽章不打扰）。
            // v1.6.9：间隔 10→30 分钟；函数内含跨标签页去重 + 不可见跳过，
            // 多标签/后台页不再叠加 GitHub 匿名限流（60/h/IP）压力
            silentUpdateCheck();
            setInterval(silentUpdateCheck, 30 * 60 * 1000);
        }

        // ========== 刷新所有 ==========
        async function refreshAll() {
            await checkServiceStatus();
            await loadGateways();
        }

        // ========== 无感刷新（只更新状态值，不重建 DOM）==========
        // v1.6.10（审计 N6）：带超时仍可能上一周期未走完被 30s 定时器再入，
        // 并发周期会交错写 DOM/集合比对误判——防重入：忙则跳过本周期
        let _silentRefreshing = false;
        async function silentRefresh() {
            if (_silentRefreshing) return;
            _silentRefreshing = true;
            try {
            await checkServiceStatus();
            // 遍历页面上已有的网关卡片，只更新设备状态
            const container = document.getElementById('gatewayContainer');
            if (!container) return;
            const gwItems = container.querySelectorAll('.gateway-item');
            // v1.6.9（外部审计确认）：网关级增删也要被检测——此前只在卡片为
            // 0 时重建，HA 里新增第二台网关页面永远不出现（与 v1.6.6 设备级
            // 自动增删不对称）。比对 config_entries 集合，不一致才整建。
            // v1.6.10（审计 B5）：检测拉取失败不得阻断本轮设备状态刷新——
            // 此前 catch 里直接 return，config_entries 一次瞬断让整页窗口状态
            // 少刷一周期。现改为 needRebuild 标志：失败=跳过重建判定、继续更新
            let needRebuild = false;
            try {
                const resp = await haApi('/config/config_entries/entry?domain=' + DOMAIN);
                if (resp.ok) {
                    const entries = await resp.json();
                    const ids = new Set(entries.map(e => e.entry_id));
                    const rendered = new Set(Array.from(gwItems).map(el => el.id.replace('gw-', '')));
                    let same = ids.size === rendered.size;
                    if (same) for (const id of ids) { if (!rendered.has(id)) { same = false; break; } }
                    if (!same) needRebuild = true;
                } else if (gwItems.length === 0) {
                    needRebuild = true; // 无卡片可更新：退回重建（旧行为）
                }
            } catch (e) {
                if (gwItems.length === 0) needRebuild = true;
                // 有卡片：检测失败视为"无增删"，继续走下方状态更新
            }
            if (needRebuild) { await loadGateways(); return; }
            if (gwItems.length === 0) return; // 无网关且无卡片：无事可做
            for (const gwItem of gwItems) {
                const entryId = gwItem.id.replace('gw-', '');
                const gatewaySn = GATEWAY_SN_BY_ENTRY[entryId] || '';
                await updateGatewayDevices(entryId, gatewaySn);
            }
            } finally {
                _silentRefreshing = false;
            }
        }

        // ========== 检查服务状态 ==========
        async function checkServiceStatus() {  /* v1.6.22 定案：不展示 credentials 状态项——密码轮换须与
        LoRa 网关固件同步，终端用户无处置能力，提示只会造成困惑（UI 钉桩负向防复活）*/
            // 1. MQTT Broker 状态 — nginx 直接返回，不依赖 HA API
            try {
                const resp = await fetchT(INGRESS_BASE + 'api/status', { cache: 'no-store' }, 8000);
                if (resp.ok) {
                    const data = await resp.json();
                    if (data.status === 'running') {
                        setStatusDot('mqttStatus', 'ok', '运行中');
                    } else {
                        setStatusDot('mqttStatus', 'err', '已停止');
                    }
                } else {
                    setStatusDot('mqttStatus', 'err', 'HTTP ' + resp.status);
                }
            } catch (e) {
                setStatusDot('mqttStatus', 'err', '无法连接');
            }
            // 2. 网关集成检测 — 插件本地事实（run.sh 安装集成后写入 integration.json），
            //    不经 /api/ha/ 代理调 HA Core API（Core 会拒绝插件 token，报 401）
            try {
                const resp = await fetchT(INGRESS_BASE + 'api/integration', { cache: 'no-store' }, 8000);
                if (!resp.ok) {
                    setStatusDot('integrationStatus', 'err', 'HTTP ' + resp.status);
                } else {
                    const info = await resp.json();
                    setStatusDot('integrationStatus', info.installed ? 'ok' : 'warn',
                        info.installed ? '已安装 v' + (info.version || '?') : '未安装');
                }
            } catch (e) {
                setStatusDot('integrationStatus', 'err', '无法读取');
            }
            // 3. HA MQTT 连接检测 — broker 实际连接数（broker_status.json 由后台循环刷新）
            try {
                const resp = await fetchT(INGRESS_BASE + 'api/broker', { cache: 'no-store' }, 8000);
                if (!resp.ok) {
                    setStatusDot('haMqttStatus', 'err', 'HTTP ' + resp.status);
                } else {
                    const info = await resp.json();
                    setStatusDot('haMqttStatus', info.clients > 0 ? 'ok' : 'warn',
                        info.clients > 0 ? '已连接 (' + info.clients + ')' : '未连接');
                }
            } catch (e) {
                setStatusDot('haMqttStatus', 'err', '无法读取');
            }
        }

        function setStatusDot(elementId, status, text) {
            const el = document.getElementById(elementId);
            el.textContent = text;
            el.parentElement.querySelector('.dot').className = 'dot dot-' + status;
        }

        // ========== 带超时的 fetch 封装（v1.6.10 审计 N6；v1.6.12 第五轮审计修正）==========
        // 此前全部请求无 AbortController：HA Core 挂起时一次刷新周期可无限
        // 卡住并与 30s 定时器叠跑竞态。默认 12s：HA REST 慢查询容忍上限；
        // 本地 nginx 静态 JSON 8s；外部更新源（github/gitee 经代理）20s。
        // v1.6.12 两处修正：
        // ① abort reason 必须是 Error 对象——规范规定 fetch 以 reason 原值
        //    reject，字符串 reason 会让所有消费 e.message 的 toast 显示
        //    "undefined"（v1.6.10 用字符串，"显示人话"的目标实际未达成）；
        // ② 超时须覆盖 body 读取——原 .finally 在响应头到达即清定时器，
        //    代理"回头不 Body"时 resp.json() 无限悬挂，silentRefresh 防重入
        //    标志永不自愈。定时器延后到 json()/text() 结算再清理；调用方
        //    不读 body 时定时器自然到期（对已完成响应 abort 无害）。
        function fetchT(url, opts = {}, timeoutMs = 12000) {
            const ctrl = new AbortController();
            const timer = setTimeout(() => ctrl.abort(new Error('请求超时')), timeoutMs);
            const clearTimer = () => clearTimeout(timer);
            return fetch(url, Object.assign({}, opts, { signal: ctrl.signal }))
                .then(resp => {
                    const origJson = resp.json.bind(resp);
                    resp.json = () => origJson().finally(clearTimer);
                    const origText = resp.text.bind(resp);
                    resp.text = () => origText().finally(clearTimer);
                    return resp;
                })
                .catch(e => { clearTimer(); throw e; });
        }

        // ========== HA API 调用 ==========
        async function haApi(path, method = 'GET', body = null) {
            const opts = { method, headers: { 'Content-Type': 'application/json' }, cache: 'no-store' };
            if (body) opts.body = JSON.stringify(body);
            return await fetchT(INGRESS_BASE + 'api/ha/' + path.replace(/^\//, ''), opts);
        }

        // ========== 加载网关列表 ==========
        async function loadGateways() {
            const container = document.getElementById('gatewayContainer');
            try {
                const resp = await haApi('/config/config_entries/entry?domain=' + DOMAIN);
                if (!resp.ok) throw new Error('HA API ' + resp.status);
                const entries = await resp.json();
                if (!entries || entries.length === 0) {
                    container.innerHTML = '<div class="empty-state"><div class="icon">📡</div><p>暂无网关</p><p class="hint">LoRa 网关上电后自动发现，或手动添加集成</p></div>';
                    return;
                }
                let html = '';
                for (const entry of entries) {
                    const gwSn = (entry.data && entry.data.gateway_sn) || '未知';
                    const gwName = entry.title || '慧尖网关';
                    html += renderGateway(gwName, gwSn, entry.entry_id);
                }
                container.innerHTML = html;
                for (const entry of entries) {
                    GATEWAY_SN_BY_ENTRY[entry.entry_id] = (entry.data && entry.data.gateway_sn) || '';
                    await loadGatewayDevices(entry.entry_id, GATEWAY_SN_BY_ENTRY[entry.entry_id]);
                }
            } catch (e) {
                if (String(e).includes('HA API 401')) {
                    container.innerHTML = '<div class="empty-state"><div class="icon">⚠️</div><p>面板无权直接读取网关列表</p><p class="hint">请在 HA → 设置 → 设备与服务 → 「慧尖」集成中管理网关</p></div>';
                } else {
                    container.innerHTML = '<div class="empty-state"><div class="icon">📡</div><p>无法连接 HA API</p><p class="hint">请确保通过 HA 侧边栏访问</p></div>';
                }
                container.innerHTML += '<div class="info-box"><h3>使用说明</h3><p>1. 重启 HA → 添加「慧尖」集成<br>2. 在网关设备上点击「配对」按钮添加子设备<br>3. 在 HA 设备页面控制子设备</p></div>';
            }
        }

        function renderGateway(name, sn, entryId) {
            const safeName = escapeHtml(name);
            const safeSn = escapeHtml(sn);
            const safeEntryId = escapeHtml(entryId);
            // 事件属性统一 jsAttr（先 JS 转义后 HTML 转义，v1.6.3）；
            // SN 不再烘焙进 onclick——按钮触发时实时读 GATEWAY_SN_BY_ENTRY，
            // 避免渲染时 SN 未知/变更导致把「未知」当真实 SN 发给服务（假成功）
            return '<div class="gateway-item" id="gw-' + safeEntryId + '">' +
                '<div class="gateway-header"><div class="gw-id"><span class="gw-avatar">📡</span><div class="gw-meta">' +
                '<span class="gateway-name">' + safeName + '</span>' +
                '<span class="gateway-sn">SN: ' + safeSn + '</span>' +
                '</div></div><div style="display:flex;align-items:center;gap:8px;">' +
                '<span class="badge badge-info" id="gw-status-' + safeEntryId + '">检测中</span>' +
                '<button class="btn btn-success btn-sm" onclick="startPairing(\'' + jsAttr(entryId) + '\')">🔗 配对</button>' +
                '<button class="btn btn-slate btn-sm" onclick="checkGatewayStatus(\'' + jsAttr(entryId) + '\')" title="检查网关连接状态">状态</button>' +
                '</div></div>' +
                '<div class="device-list" id="devices-' + safeEntryId + '"><div class="loading"><div class="spinner" style="width:16px;height:16px;"></div></div></div>' +
                '</div>';
        }

        async function loadGatewayDevices(entryId, gatewaySn) {
            const deviceListEl = document.getElementById('devices-' + entryId);
            const statusEl = document.getElementById('gw-status-' + entryId);
            if (!deviceListEl) return;
            try {
                const resp = await haApi('/window_controller_gateway/devices?config_entry_id=' + entryId);
                if (!resp.ok) throw new Error('HA API ' + resp.status);
                const devices = await resp.json();
                if (!devices || devices.length === 0) {
                    deviceListEl.innerHTML = '<p class="empty-hint">暂无子设备，点击「配对」按钮添加</p>';
                    updateGatewayStatus(statusEl, 'offline');
                    return;
                }
                let subDevices = [];
                let gwDevice = null;
                for (const dev of devices) {
                    if (dev.via_device_id) subDevices.push(dev);
                    else gwDevice = dev;  // 网关（parent）设备
                }
                // 2026-08-28 修复：从网关设备 identifiers 提取真实 SN，
                // 更新网关卡片 SN 显示（解决 "SN: 未知"，无 SN 等待模式
                // 下 entry.data.gateway_sn 为空，但设备注册表中已有真实 SN）。
                let gwSn = gatewaySn || '';
                // v1.6.3：占位符「未知」不是真实 SN（调用方可能透传），视为空；
                // 回退提取按本集成 DOMAIN 匹配 identifiers，不再依赖 [0] 位置假设
                if (!gwSn || gwSn === '未知') gwSn = deviceSnOf(gwDevice) || '';
                if (gwSn) {
                    GATEWAY_SN_BY_ENTRY[entryId] = gwSn;
                    const snEl = document.querySelector('#gw-' + entryId + ' .gateway-sn');
                    if (snEl) snEl.textContent = 'SN: ' + gwSn;
                }
                try {
                    const stateResp = await haApi('/states');
                    if (!stateResp.ok) throw new Error('HA API ' + stateResp.status);
                    const states = await stateResp.json();
                    // 网关在线状态：优先用 API 的 gateway_online 字段
                    // （mqtt_handler.connected 实时值 = 收到网关上报即在线），
                    // 不依赖 binary_sensor 实体（实体未创建/匹配失败时不再显示"未知"）。
                    let gwStatus = 'unknown';
                    if (gwDevice && typeof gwDevice.gateway_online === 'boolean') {
                        gwStatus = gwDevice.gateway_online ? 'online' : 'offline';
                    } else {
                        // 兼容旧 API：回退到 binary_sensor online 实体精确查找
                        const gwEntity = findEntityByUniqueId(gwDevice, 'binary_sensor', 'online');
                        const gwSensor = gwEntity ? (states.find(s => s.entity_id === gwEntity.entity_id) || null) : null;
                        gwStatus = gwSensor ? (gwSensor.state === 'on' ? 'online' : 'offline') : 'unknown';
                    }
                    updateGatewayStatus(statusEl, gwStatus);
                    if (subDevices.length === 0) {
                        deviceListEl.innerHTML = '<p class="empty-hint">暂无子设备，点击「配对」按钮添加</p>';
                        return;
                    }
                    let html = '';
                    for (const dev of subDevices) html += renderDevice(dev, entryId, states);
                    deviceListEl.innerHTML = html;
                    for (const dev of subDevices) loadDeviceState(dev, states);
                } catch (e) {
                    // 状态获取失败：仍用 API 的 gateway_online（若有）显示网关在线状态
                    if (gwDevice && typeof gwDevice.gateway_online === 'boolean') {
                        updateGatewayStatus(statusEl, gwDevice.gateway_online ? 'online' : 'offline');
                    } else {
                        updateGatewayStatus(statusEl, 'unknown');
                    }
                    if (subDevices.length === 0) {
                        deviceListEl.innerHTML = '<p class="empty-hint">暂无子设备，点击「配对」按钮添加</p>';
                        return;
                    }
                    let html = '';
                    for (const dev of subDevices) html += renderDevice(dev, entryId, []);
                    deviceListEl.innerHTML = html;
                }
            } catch (e) {
                deviceListEl.innerHTML = '<p class="err-text">加载设备失败: ' + escapeHtml(e.message) + '</p>';
            }
        }

        // 无感刷新：获取最新设备数据，只更新状态值，不重建 DOM
        // 与 loadGatewayDevices 的区别：不 innerHTML 重建，只 loadDeviceState 更新
        async function updateGatewayDevices(entryId, gatewaySn) {
            const deviceListEl = document.getElementById('devices-' + entryId);
            const statusEl = document.getElementById('gw-status-' + entryId);
            if (!deviceListEl) return;
            try {
                const resp = await haApi('/window_controller_gateway/devices?config_entry_id=' + entryId);
                if (!resp.ok) return;
                const devices = await resp.json();
                if (!devices || devices.length === 0) {
                    // v1.6.6：服务端一个设备都没有、页面上却还渲染着设备行
                    // （整体被移除等）→ 升级为完整重建，否则残留行永不消失
                    if (deviceListEl.querySelector('.device-item')) {
                        await loadGatewayDevices(entryId, GATEWAY_SN_BY_ENTRY[entryId] || gatewaySn);
                    }
                    return;
                }
                let subDevices = [];
                let gwDevice = null;
                for (const dev of devices) {
                    if (dev.via_device_id) subDevices.push(dev);
                    else gwDevice = dev;
                }
                let gwSn = gatewaySn || '';
                // v1.6.3：占位符「未知」不是真实 SN（调用方可能透传），视为空；
                // 回退提取按本集成 DOMAIN 匹配 identifiers，不再依赖 [0] 位置假设
                if (!gwSn || gwSn === '未知') gwSn = deviceSnOf(gwDevice) || '';
                if (gwSn) {
                    GATEWAY_SN_BY_ENTRY[entryId] = gwSn;
                    const snEl = document.querySelector('#gw-' + entryId + ' .gateway-sn');
                    if (snEl) snEl.textContent = 'SN: ' + gwSn;
                }
                // v1.6.6：无感刷新兼管设备集合变化检测。旧逻辑只更新页面上
                // 已有的 dev-* 元素（新子设备没有对应 DOM，循环直接跳过），
                // 导致「集成里已出现的新设备，Web 界面永远等不到，只能手动
                // 刷新」。现在每轮比对服务端设备 id 集合与已渲染集合，
                // 有增/删即升级为 loadGatewayDevices 完整重建（该方法会
                // 重建设备列表 DOM 并渲染新行）。
                const serverIds = subDevices.map(d => d.id).sort().join(',');
                // .device-item 行 id 形如 dev-<rawId>；DOM 读取 el.id 返回
                // 属性解析后的原始 id（escapeHtml 编码已在解析时还原），
                // 与服务端 d.id 直接可比
                const renderedIds = Array.from(deviceListEl.querySelectorAll('.device-item'))
                    .map(el => el.id.slice('dev-'.length)).sort().join(',');
                if (serverIds !== renderedIds) {
                    await loadGatewayDevices(entryId, gwSn || gatewaySn);
                    return;
                }
                try {
                    const stateResp = await haApi('/states');
                    if (!stateResp.ok) return;
                    const states = await stateResp.json();
                    let gwStatus = 'unknown';
                    if (gwDevice && typeof gwDevice.gateway_online === 'boolean') {
                        gwStatus = gwDevice.gateway_online ? 'online' : 'offline';
                    } else {
                        const gwEntity = findEntityByUniqueId(gwDevice, 'binary_sensor', 'online');
                        const gwSensor = gwEntity ? (states.find(s => s.entity_id === gwEntity.entity_id) || null) : null;
                        gwStatus = gwSensor ? (gwSensor.state === 'on' ? 'online' : 'offline') : 'unknown';
                    }
                    updateGatewayStatus(statusEl, gwStatus);
                    // 只更新已有设备元素的状态，不重建 DOM
                    for (const dev of subDevices) {
                        const devEl = document.getElementById('dev-' + dev.id);
                        if (devEl) loadDeviceState(dev, states);
                    }
                } catch (e) {
                    if (gwDevice && typeof gwDevice.gateway_online === 'boolean') {
                        updateGatewayStatus(statusEl, gwDevice.gateway_online ? 'online' : 'offline');
                    }
                }
            } catch (e) { /* 静默失败，不干扰用户 */ }
        }

        function updateGatewayStatus(el, status) {
            // v1.6.3：卡片可能被重渲染移除（await 后 DOM 已换），空引用防护
            if (!el) return;
            if (status === 'online') { el.className = 'badge badge-ok'; el.textContent = '在线'; }
            else if (status === 'pairing') { el.className = 'badge badge-warn'; el.textContent = '配对中'; }
            else if (status === 'offline') { el.className = 'badge badge-err'; el.textContent = '离线'; }
            else { el.className = 'badge badge-gray'; el.textContent = '未知'; }
        }

        function renderDevice(dev, entryId, states) {
            const devName = dev.name_by_user || dev.name || '未命名设备';
            const devId = dev.id;
            const sn = deviceSnOf(dev) || '未知';
            const supportsWindLock = sn.startsWith('5005');
            const coverEntity = findEntityState(dev, 'cover', 'cover', states);
            const onlineEntity = findEntityState(dev, 'binary_sensor', 'online', states);
            const batteryEntity = findEntityState(dev, 'sensor', 'battery', states);
            const speedEntity = findEntityState(dev, 'number', 'speed', states);
            const strengthEntity = findEntityState(dev, 'number', 'strength', states);
            const rawPos = coverEntity ? coverEntity.attributes.position : undefined;
            const currentPos = (rawPos === undefined || rawPos === null) ? '--' : rawPos;
            const safeName = escapeHtml(devName);
            const safeSn = escapeHtml(sn);
            const safeDevId = escapeHtml(devId);
            const safeEntryId = escapeHtml(entryId);
            const isOnline = onlineEntity ? (onlineEntity.state === 'on') : false;
            let batteryText = '';
            if (batteryEntity && batteryEntity.state && batteryEntity.state !== 'unknown' && batteryEntity.state !== 'unavailable') {
                const bUnit = batteryEntity.attributes.unit_of_measurement || 'V';
                batteryText = escapeHtml(batteryEntity.state + bUnit);
            } else if (coverEntity && coverEntity.attributes.voltage) {
                batteryText = escapeHtml(coverEntity.attributes.voltage) + 'V';
            }
            const speedMin = speedEntity && speedEntity.attributes.min !== undefined ? speedEntity.attributes.min : 0;
            const speedMax = speedEntity && speedEntity.attributes.max !== undefined ? speedEntity.attributes.max : 100;
            const speedValid = speedEntity && speedEntity.state && speedEntity.state !== 'unknown' && speedEntity.state !== 'unavailable';
            const speedUnit = (speedEntity && speedEntity.attributes.unit_of_measurement) || '';
            const strengthMin = strengthEntity && strengthEntity.attributes.min !== undefined ? strengthEntity.attributes.min : 0;
            const strengthMax = strengthEntity && strengthEntity.attributes.max !== undefined ? strengthEntity.attributes.max : 100;
            const strengthValid = strengthEntity && strengthEntity.state && strengthEntity.state !== 'unknown' && strengthEntity.state !== 'unavailable';
            const strengthUnit = (strengthEntity && strengthEntity.attributes.unit_of_measurement) || '';

            // === 顶部行：设备信息 + 管理按钮（重命名/移除） ===
            let html = '<div class="device-item" id="dev-' + safeDevId + '">' +
                '<div class="device-top">' +
                '<div class="device-info"><div class="device-name dev-name">' +
                '<span class="dev-dot ' + (isOnline ? 'dot-online' : 'dot-offline') + '" id="dev-dot-' + safeDevId + '"></span>' +
                safeName + '</div>' +
                '<div class="device-sn">SN: ' + safeSn + '</div>' +
                '<div class="device-status" id="dev-state-' + safeDevId + '">状态: 加载中' + (batteryText ? ' | 电压: ' + batteryText : '') + '</div></div>' +
                '<div class="device-actions">' +
                '<button class="btn btn-slate btn-sm" onclick="renameDevice(\'' + jsAttr(devId) + '\',\'' + jsAttr(entryId) + '\',\'' + jsAttr(devName) + '\')" title="重命名设备">改名</button>' +
                '<button class="btn btn-danger btn-sm" title="移除设备" onclick="controlDevice(\'' + jsAttr(devId) + '\',\'remove\',\'' + jsAttr(entryId) + '\')">移除</button>' +
                '</div></div>';

            // === 主控制区：开/关/停（5005 含内倒） ===
            html += '<div class="control-section">' +
                '<div class="control-row">' +
                '<button class="btn btn-success btn-sm" onclick="controlDevice(\'' + jsAttr(devId) + '\',\'open\',\'' + jsAttr(entryId) + '\')">开</button>' +
                '<button class="btn btn-danger btn-sm" onclick="controlDevice(\'' + jsAttr(devId) + '\',\'close\',\'' + jsAttr(entryId) + '\')">关</button>' +
                '<button class="btn btn-warn btn-sm" onclick="controlDevice(\'' + jsAttr(devId) + '\',\'stop\',\'' + jsAttr(entryId) + '\')">停</button>';
            if (supportsWindLock) {
                html += '<button class="btn btn-tilt btn-sm" onclick="controlDevice(\'' + jsAttr(devId) + '\',\'a\',\'' + jsAttr(entryId) + '\')">内倒</button>';
            }
            html += '</div>';

            // === 滑块区：位置 / 速度 / 力度 ===
            html += '<div class="slider-group">' +
                '<div class="slider-row"><span class="slider-label">位置</span>' +
                '<input type="range" class="position-slider" min="0" max="100" value="' + (currentPos === '--' ? 0 : escapeHtml(currentPos)) + '"' +
                ' oninput="this.nextElementSibling.textContent=this.value+\'%\'"' +
                ' onchange="controlDevicePosition(\'' + jsAttr(devId) + '\', this.value, \'' + jsAttr(entryId) + '\')">' +
                '<span class="slider-value position-value">' + escapeHtml(currentPos) + (currentPos === '--' ? '' : '%') + '</span></div>' +
                '<div class="slider-row"><span class="slider-label">速度</span>' +
                '<input type="range" class="speed-slider" min="' + escapeHtml(speedMin) + '" max="' + escapeHtml(speedMax) + '" value="' + escapeHtml(speedValid ? speedEntity.state : speedMin) + '"' +
                ' oninput="this.nextElementSibling.textContent=this.value' + (speedUnit ? '+\'' + jsAttr(speedUnit) + '\'' : '') + '"' +
                ' onchange="controlDevice(\'' + jsAttr(devId) + '\',\'set_speed\',\'' + jsAttr(entryId) + '\', this.value)">' +
                '<span class="slider-value speed-value">' + (speedValid ? escapeHtml(speedEntity.state + speedUnit) : '--') + '</span></div>' +
                '<div class="slider-row"><span class="slider-label">力度</span>' +
                '<input type="range" class="strength-slider" min="' + escapeHtml(strengthMin) + '" max="' + escapeHtml(strengthMax) + '" value="' + escapeHtml(strengthValid ? strengthEntity.state : strengthMin) + '"' +
                ' oninput="this.nextElementSibling.textContent=this.value' + (strengthUnit ? '+\'' + jsAttr(strengthUnit) + '\'' : '') + '"' +
                ' onchange="controlDevice(\'' + jsAttr(devId) + '\',\'set_strength\',\'' + jsAttr(entryId) + '\', this.value)">' +
                '<span class="slider-value strength-value">' + (strengthValid ? escapeHtml(strengthEntity.state + strengthUnit) : '--') + '</span></div>' +
                '</div>';

            // === 模式切换区（仅 5005）：内倒模式 / 平开模式 ===
            if (supportsWindLock) {
                html += '<div class="control-row">' +
                    '<button class="btn btn-mode-a btn-sm" style="flex:1;" onclick="controlDevice(\'' + jsAttr(devId) + '\',\'wind_lock_tilt\',\'' + jsAttr(entryId) + '\')">内倒模式</button>' +
                    '<button class="btn btn-mode-b btn-sm" style="flex:1;" onclick="controlDevice(\'' + jsAttr(devId) + '\',\'wind_lock_flat\',\'' + jsAttr(entryId) + '\')">平开模式</button>' +
                    '</div>';
            }

            html += '</div>'; // close control-section
            html += '</div>'; // close device-item
            return html;
        }

        function loadDeviceState(dev, states) {
            const stateEl = document.getElementById('dev-state-' + dev.id);
            if (!stateEl) return;
            try {
                // 2026-08-28 修复：用 API 返回的精确实体列表按 unique_id 锚点查找
                const coverEntity = findEntityState(dev, 'cover', 'cover', states);
                // 在线状态点: binary_sensor.*online*
                const onlineEntity = findEntityState(dev, 'binary_sensor', 'online', states);
                const dot = document.querySelector('#dev-' + dev.id + ' .dev-dot');
                if (dot) {
                    if (onlineEntity) {
                        dot.className = 'dev-dot ' + (onlineEntity.state === 'on' ? 'dot-online' : 'dot-offline');
                    } else if (coverEntity) {
                        dot.className = 'dev-dot ' + (coverEntity.state === 'unavailable' ? 'dot-offline' : 'dot-online');
                    }
                }
                // 电池电压: sensor.*battery*
                const batteryEntity = findEntityState(dev, 'sensor', 'battery', states);
                // 速度/力度: number.*speed* / number.*strength*
                const speedEntity = findEntityState(dev, 'number', 'speed', states);
                const strengthEntity = findEntityState(dev, 'number', 'strength', states);
                // 更新速度/力度滑块：始终可用（与 HA 集成 number 实体一致），
                // 有上报数据时回显当前值，无数据时保持默认值 0 且可拖动。
                const speedSlider = document.querySelector('#dev-' + dev.id + ' .speed-slider');
                if (speedSlider) {
                    speedSlider.disabled = false;
                    if (speedEntity && speedEntity.state !== 'unknown' && speedEntity.state !== 'unavailable') {
                        const unit = speedEntity.attributes.unit_of_measurement || '';
                        speedSlider.value = speedEntity.state;
                        const valEl = document.querySelector('#dev-' + dev.id + ' .speed-value');
                        if (valEl) valEl.textContent = speedEntity.state + unit;
                    }
                }
                const strengthSlider = document.querySelector('#dev-' + dev.id + ' .strength-slider');
                if (strengthSlider) {
                    strengthSlider.disabled = false;
                    if (strengthEntity && strengthEntity.state !== 'unknown' && strengthEntity.state !== 'unavailable') {
                        const unit = strengthEntity.attributes.unit_of_measurement || '';
                        strengthSlider.value = strengthEntity.state;
                        const valEl = document.querySelector('#dev-' + dev.id + ' .strength-value');
                        if (valEl) valEl.textContent = strengthEntity.state + unit;
                    }
                }
                // 状态文本
                let statusText;
                if (coverEntity) {
                    const pos = coverEntity.attributes.position;
                    const state = coverEntity.state;
                    const devStatus = coverEntity.attributes.device_status;
                    if (state === 'open') statusText = '状态: 打开';
                    else if (state === 'closed' || state === 'close') statusText = '状态: 关闭';
                    else if (state === 'opening') statusText = '状态: 正在打开';
                    else if (state === 'closing') statusText = '状态: 正在关闭';
                    // v1.6.8：state 为 unknown 时按 device_status 属性兜底，
                    // 避免直接暴露英文 unknown/unavailable 给用户
                    else if (devStatus === 'open') statusText = '状态: 打开';
                    else if (devStatus === 'closed') statusText = '状态: 关闭';
                    // 用户定案：状态与位置同步——status 缺失但上报了 position 时，
                    // 按位置推导（0=关闭，>0=打开），避免「待上报 + 位置 65%」矛盾
                    else if (pos !== undefined && pos !== null && pos !== '') statusText = '状态: ' + (Number(pos) > 0 ? '打开' : '关闭');
                    else if (state === 'unavailable') statusText = '状态: 离线';
                    else if (devStatus === 'connected' || state === 'unknown' || devStatus === 'unknown') statusText = '状态: 待上报';
                    else statusText = '状态: ' + state;
                    if (pos !== undefined) statusText += ' | 位置: ' + pos + '%';
                    const slider = document.querySelector('#dev-' + dev.id + ' .position-slider');
                    if (slider && pos !== undefined) {
                        slider.value = pos;
                        slider.nextElementSibling.textContent = pos + '%';
                    }
                } else {
                    statusText = '状态: 无数据';
                }
                if (onlineEntity) statusText += ' | ' + (onlineEntity.state === 'on' ? '在线' : '离线');
                if (batteryEntity && batteryEntity.state && batteryEntity.state !== 'unknown' && batteryEntity.state !== 'unavailable') {
                    const bUnit = batteryEntity.attributes.unit_of_measurement || 'V';
                    statusText += ' | 电压: ' + batteryEntity.state + bUnit;
                } else if (coverEntity && coverEntity.attributes.voltage) {
                    statusText += ' | 电压: ' + coverEntity.attributes.voltage + 'V';
                }
                stateEl.textContent = statusText;
            } catch (e) {
                stateEl.textContent = '状态: 加载失败';
            }
        }

        async function startPairing(entryId) {
            if (!confirm('确定要启动网关配对模式吗？\n配对期间请将子设备靠近网关。')) return;
            const statusEl = document.getElementById('gw-status-' + entryId);
            updateGatewayStatus(statusEl, 'pairing');
            // v1.6.3：SN 实时读 map，不再用渲染时烘焙的旧值/占位符
            const gatewaySn = GATEWAY_SN_BY_ENTRY[entryId] || '';
            try {
                const resp = await haApi('/window_controller_gateway/devices?config_entry_id=' + entryId);
                if (!resp.ok) throw new Error('HA API ' + resp.status);
                const devices = await resp.json();
                const gwDevice = devices.find(d => !d.via_device_id);
                if (!gwDevice) { showToast('未找到网关设备', 'err'); updateGatewayStatus(statusEl, 'unknown'); return; }
                const pairResp = await haApi('/services/window_controller_gateway/start_pairing', 'POST', {
                    device_id: gwDevice.id, duration: 60
                });
                if (!pairResp.ok) throw new Error('HA API ' + pairResp.status);
                showToast('配对模式已启动（60秒），请操作子设备', 'ok');
                setTimeout(() => loadGatewayDevices(entryId, gatewaySn), 10000);
                setTimeout(() => loadGatewayDevices(entryId, gatewaySn), 60000);
            } catch (e) {
                showToast('配对启动失败: ' + e.message, 'err');
                // v1.6.3：失败不硬标 online（设备可能确实离线），回到未知由下次刷新判定
                updateGatewayStatus(statusEl, 'unknown');
            }
        }

        async function checkGatewayStatus(entryId) {
            // v1.6.3：SN 实时读 map；拿不到真实 SN 时明确报错，
            // 不再把占位符发给服务端静默 no-op 后弹「已发送」假成功
            const gatewaySn = GATEWAY_SN_BY_ENTRY[entryId] || '';
            if (!gatewaySn || gatewaySn === '未知') {
                showToast('该网关 SN 尚未识别，无法检查状态（稍后重试或点配对刷新）', 'err');
                return;
            }
            showToast('正在检查网关状态...', 'warn');
            try {
                const resp = await haApi('/services/window_controller_gateway/check_gateway_status', 'POST', { gateway_sn: gatewaySn });
                if (!resp.ok) throw new Error('HA API ' + resp.status);
                showToast('状态检查已发送', 'ok');
                setTimeout(() => loadGatewayDevices(entryId, gatewaySn), 2000);
            } catch (e) {
                showToast('状态检查失败: ' + e.message, 'err');
                // v1.6.4：失败（含服务端"未找到网关"非 2xx）不保留旧徽标结论，
                // 回到"未知"由下次刷新重新判定
                updateGatewayStatus(document.getElementById('gw-status-' + entryId), 'unknown');
            }
        }

        async function renameDevice(deviceId, entryId, currentName) {
            const newName = prompt('请输入新设备名称:', currentName);
            if (!newName || newName === currentName) return;
            showToast('正在重命名...', 'warn');
            try {
                const resp = await haApi('/services/window_controller_gateway/rename_device', 'POST', {
                    device_id: deviceId, name: newName
                });
                if (!resp.ok) throw new Error('HA API ' + resp.status);
                showToast('重命名成功: ' + newName, 'ok');
                setTimeout(() => loadGatewayDevices(entryId, GATEWAY_SN_BY_ENTRY[entryId] || ''), 2000);
            } catch (e) {
                showToast('重命名失败: ' + e.message, 'err');
            }
        }

        // v1.6.3：删除 transferDevice/refreshDevices 死代码——
        // 二者无任何调用点（页面无按钮），且字段有误：transfer_device 服务
        // 参数为 new_gateway_sn（services.yaml），旧代码发 target_gateway_sn；
        // refresh_devices 需要必填 device_id，旧代码发空 payload 必然 400。
        // 需要该功能时按正确字段重新接线，勿直接恢复旧实现。

        async function controlDevice(deviceId, command, entryId, value) {
            if (command === 'remove' && !confirm('确定要删除该子设备吗？\n将移除该设备在 HA 中的全部实体。')) return;
            showToast('正在发送命令: ' + command + '...', 'warn');
            try {
                // v1.6.3：删除无用的全量 /states 拉取——本函数只按 devices API
                // 的实体列表定位；旧实现拉回后从未使用，且 !ok 抛错会拦死控制
                const devResp = await haApi('/window_controller_gateway/devices?config_entry_id=' + entryId);
                if (!devResp.ok) throw new Error('HA API ' + devResp.status);
                const devices = await devResp.json();
                const dev = devices.find(d => d.id === deviceId);
                // 2026-08-28 修复：用 API 返回的精确实体列表按 unique_id 锚点查找，
                // 不再用 SN 后 6 位模糊匹配 entity_id（设备名只有后 4 位，模糊匹配必然失败）。
                const coverEntity = findEntityByUniqueId(dev, 'cover', 'cover');
                if (command === 'open' || command === 'close' || command === 'stop') {
                    if (!coverEntity) {
                        showToast('未找到设备 cover 实体', 'warn');
                    } else {
                        let service = '';
                        if (command === 'open') service = 'open_cover';
                        else if (command === 'close') service = 'close_cover';
                        else if (command === 'stop') service = 'stop_cover';
                        const r = await haApi('/services/cover/' + service, 'POST', { entity_id: coverEntity.entity_id });
                        if (!r.ok) throw new Error('HA API ' + r.status);
                        showToast('命令已发送: ' + command, 'ok');
                    }
                } else if (command === 'a') {
                    // 内倒（toggle）：与 wind_lock 相同模式，按 button 实体 unique_id 后缀 _a 查找
                    const btnEntity = findEntityByUniqueId(dev, 'button', 'a');
                    if (btnEntity) {
                        const r = await haApi('/services/button/press', 'POST', { entity_id: btnEntity.entity_id });
                        if (!r.ok) throw new Error('HA API ' + r.status);
                        showToast('内倒命令已发送', 'ok');
                    } else {
                        showToast('未找到内倒按钮实体', 'warn');
                    }
                } else if (command === 'wind_lock_tilt' || command === 'wind_lock_flat') {
                    const btnSuffix = command === 'wind_lock_tilt' ? 'wind_lock_tilt' : 'wind_lock_flat';
                    const btnEntity = findEntityByUniqueId(dev, 'button', btnSuffix);
                    if (btnEntity) {
                        const r = await haApi('/services/button/press', 'POST', { entity_id: btnEntity.entity_id });
                        if (!r.ok) throw new Error('HA API ' + r.status);
                        showToast('模式切换: ' + (command === 'wind_lock_tilt' ? '内倒' : '平开'), 'ok');
                    } else {
                        showToast('未找到模式按钮实体', 'warn');
                    }
                } else if (command === 'set_speed' || command === 'set_strength') {
                    const numSuffix = command === 'set_speed' ? 'speed' : 'strength';
                    const numEntity = findEntityByUniqueId(dev, 'number', numSuffix);
                    if (numEntity) {
                        const numVal = parseFloat(value);
                        if (isNaN(numVal)) throw new Error('无效数值: ' + value);
                        const r = await haApi('/services/number/set_value', 'POST', { entity_id: numEntity.entity_id, value: numVal });
                        if (!r.ok) throw new Error('HA API ' + r.status);
                        showToast((command === 'set_speed' ? '速度' : '力度') + '设置: ' + value, 'ok');
                    } else {
                        showToast('未找到' + (command === 'set_speed' ? '速度' : '力度') + '实体', 'warn');
                    }
                } else if (command === 'remove') {
                    // 删除按钮实体挂在网关设备下（不在子设备实体列表），
                    // 用 findRemoveButtonEntity 在整个设备列表中按 unique_id 锚点查找
                    const btnEntity = findRemoveButtonEntity(dev, devices);
                    if (btnEntity) {
                        const r = await haApi('/services/button/press', 'POST', { entity_id: btnEntity.entity_id });
                        if (!r.ok) throw new Error('HA API ' + r.status);
                        showToast('删除命令已发送', 'ok');
                    } else {
                        showToast('未找到删除按钮实体', 'warn');
                    }
                } else {
                    showToast('未知命令: ' + command, 'warn');
                }
                setTimeout(() => loadGatewayDevices(entryId, GATEWAY_SN_BY_ENTRY[entryId] || ''), 2000);
            } catch (e) {
                showToast('控制失败: ' + e.message, 'err');
            }
        }

        async function controlDevicePosition(deviceId, position, entryId) {
            try {
                // v1.6.3：钳制 0-100 并拒绝 NaN（服务 schema 范围 0-100，越界会被 400 拒绝）
                const pos = Math.round(Number(position));
                if (!Number.isFinite(pos) || pos < 0 || pos > 100) {
                    showToast('无效位置: ' + position, 'err');
                    return;
                }
                // v1.6.3：删除无用的全量 /states 拉取（同上，仅用 devices API 实体列表）
                const devResp = await haApi('/window_controller_gateway/devices?config_entry_id=' + entryId);
                if (!devResp.ok) throw new Error('HA API ' + devResp.status);
                const devices = await devResp.json();
                const dev = devices.find(d => d.id === deviceId);
                // 2026-08-28 修复：精确查找 cover 实体（仅作存在性判断，
                // 实际服务为 window_controller_gateway.set_position）
                const coverEntity = findEntityByUniqueId(dev, 'cover', 'cover');
                if (coverEntity) {
                    // 集成未注册 cover.set_cover_position（cover.py 无 SET_POSITION 特性标志），
                    // 实际服务为 window_controller_gateway.set_position：字段 device_id（设备注册表ID）+ position
                    const r = await haApi('/services/window_controller_gateway/set_position', 'POST', {
                        device_id: deviceId, position: pos
                    });
                    if (!r.ok) throw new Error('HA API ' + r.status);
                    showToast('位置设置: ' + pos + '%', 'ok');
                } else {
                    showToast('未找到设备 cover 实体', 'warn');
                }
            } catch (e) {
                showToast('位置设置失败: ' + e.message, 'err');
            }
        }

        // ========== 检查更新 ==========
        // v1.6.4：拆出 fetchLatestRelease() 核心——自动静默检查与手动检查
        // 共用同一数据源逻辑。v1.6.7 起：Gitee+GitHub 双源并集取版本号最大者
        // （不信 /releases/latest 的过期数据；也不单信 Gitee——其 Release 需
        // 手动同步、版本会陈旧），tag 必须匹配 数字.数字[.数字...]，
        // 防 1.6.4-beta 之类后缀让 compareVersions 出 NaN。
        async function fetchLatestRelease() {
            // v1.6.7：双源并集取最大。旧逻辑「Gitee 有数据就只用 Gitee」有洞：
            // gitee Release 并非 CI 自动创建（只有 GitHub 有），gitee 最大版本
            // 会陈旧（2026-08-29 实测停在 1.3.0），把「最新发布版」误判成旧值、
            // 升级徽章永不点亮。现两源都拉、合并取最大版本号，单源失败不互碍。
            // GitHub 先入列：同版本时优先取其条目（html_url 详情页更全）。
            const all = [];
            try {
                const ghResp = await fetchT(INGRESS_BASE + 'api/github/repos/fangwenyi-dev/ha-gateway-plugin/releases?per_page=100', { cache: 'no-store' }, 20000);
                if (ghResp.ok) {
                    const d = await ghResp.json();
                    if (Array.isArray(d)) all.push(...d);
                }
            } catch (e) { /* GitHub 限流/异常，Gitee 仍可独立工作 */ }
            try {
                const giteeResp = await fetchT(INGRESS_BASE + 'api/gitee/repos/fangwenyi-dev/ha-gateway-plugin/releases?per_page=100', { cache: 'no-store' }, 20000);
                if (giteeResp.ok) {
                    const d = await giteeResp.json();
                    if (Array.isArray(d)) all.push(...d);
                }
            } catch (e) { /* Gitee 网络异常，GitHub 仍可独立工作 */ }
            if (all.length === 0) throw new Error('更新源不可用（Gitee/GitHub 均无数据）');
            let latestVersion = '0.0.0';
            let latestRelease = null;
            for (const r of all) {
                const ver = (r.tag_name || '').replace(/^v/, '');
                if (/^\d+(\.\d+)+$/.test(ver) && compareVersions(ver, latestVersion) > 0) {
                    latestVersion = ver;
                    latestRelease = r;
                }
            }
            if (!latestRelease) throw new Error('未找到任何 Release');
            return { latestVersion, latestRelease };
        }

        // 头部「检查更新」按钮徽章：发现新版变绿显示「⬆️ 有可用升级 vX.Y.Z」
        function renderUpdateBadge(latestVersion) {
            const btn = document.getElementById('checkUpdateBtn');
            if (!btn) return;
            if (latestVersion && compareVersions(latestVersion, CURRENT_VERSION) > 0) {
                btn.textContent = '⬆️ 有可用升级 v' + latestVersion;
                btn.classList.remove('btn-primary');
                btn.classList.add('btn-success');
                btn.title = '点击查看详情与升级引导';
            } else {
                btn.textContent = '检查更新';
                btn.classList.remove('btn-success');
                btn.classList.add('btn-primary');
                btn.title = '';
            }
        }

        // 静默自动检查（init 时一次 + 每 10 分钟一次）：只更新徽章，
        // 不弹卡片不打扰；任何失败仅 console，不污染页面
        async function silentUpdateCheck() {
            // v1.6.9：三重限流（此前 10min×每标签页×双源都打 GitHub，多标签
            // 页逼近匿名 60/h/IP 限流）。① 跨标签页去重——localStorage 时间戳，
            // 5 分钟内其它标签已查过就跳过；② 页面不可见跳过（同 silentRefresh）；
            // ③ 复查间隔 10→30 分钟（升级徽章无需 10 分钟新鲜度）。
            // localStorage 读写包 try/catch：HA ingress 为三方 iframe，
            // 个别浏览器存储策略会直接抛异常，限流优化不能反杀检查本身
            if (document.hidden) return;
            try {
                const last = Number(localStorage.getItem('huijian_last_update_check') || 0);
                if (Date.now() - last < 5 * 60 * 1000) return;
                localStorage.setItem('huijian_last_update_check', String(Date.now()));
            } catch (e) { /* 存储不可用则退化为不去重 */ }
            try {
                const { latestVersion } = await fetchLatestRelease();
                renderUpdateBadge(latestVersion);
            } catch (e) {
                console.log('自动检查更新失败:', e.message);
                // 失败也保留时间戳，避免限流/断网时其他标签立刻重试放大压力
            }
        }

        async function checkForUpdates() {
            const card = document.getElementById('updateCard');
            const content = document.getElementById('updateContent');
            card.style.display = 'block';
            content.innerHTML = '<div class="loading"><div class="spinner"></div><p>正在检查更新...</p></div>';
            try {
                const { latestVersion, latestRelease } = await fetchLatestRelease();
                renderUpdateBadge(latestVersion);
                const hasUpdate = compareVersions(latestVersion, CURRENT_VERSION) > 0;
                if (hasUpdate) {
                    const body = latestRelease.body || '暂无变更日志';
                    const truncatedBody = body.length > 800 ? body.substring(0, 800) + '...' : body;
                    content.innerHTML = '<div class="update-box"><div class="update-info">' +
                        '<div class="update-title">发现新版本 v' + escapeHtml(latestVersion) + '</div>' +
                        '<div class="update-desc">当前版本 v' + CURRENT_VERSION + '</div></div>' +
                        '<button class="btn btn-success" onclick="doUpgrade()">去加载项页面更新</button>' +
                        '<a class="btn btn-primary" href="' + escapeHtml(latestRelease.html_url) + '" target="_blank">查看详情</a></div>' +
                        '<div style="margin-top:10px;font-size:12px;color:var(--text-muted);white-space:pre-wrap;">' + escapeHtml(truncatedBody) + '</div>' +
                        '<div style="margin-top:8px;font-size:12px;color:var(--text-muted);">' +
                        '提示：Supervisor 安全设计禁止插件通过 API 自我更新（一键升级会返回 403/400）。' +
                        '请使用上方按钮跳转到 Supervisor 加载项页面，以管理员身份点击「更新」。' +
                        '<br>若跳转后提示「App huijian_mqtt_broker does not exist in the store」，' +
                        '说明本加载项已与加载项商店失去关联（安装后被删除仓库，或商店刷新失败——国内网络访问 GitHub 不通时常见）。' +
                        '恢复方法：设置 → 加载项 → 加载项商店 → ⋮ → 仓库，重新添加 ' +
                        'https://github.com/fangwenyi-dev/ha-gateway-plugin 并更新商店，再回到本页重试。</div>';
                } else {
                    content.innerHTML = '<div class="update-box update-ok"><div class="update-info">' +
                        '<div class="update-title">✅ 已是最新版本 v' + CURRENT_VERSION + '</div>' +
                        '<div class="update-desc">发布源最新版本: v' + escapeHtml(latestVersion) + '</div></div></div>';
                }
            } catch (e) {
                content.innerHTML = '<div class="update-box update-err"><div class="update-info">' +
                    '<div class="update-title">检查更新失败</div>' +
                    '<div class="update-desc">' + escapeHtml(e.message) + '</div></div></div>';
            }
        }

        // ========== 升级引导（跳转 Supervisor 加载项页面） ==========
        // Supervisor 安全设计（2025 年引入）禁止 add-on 通过 API 更新自己：
        //   - /addons/self/update 与 /store/addons/{slug}/update 均检查 REQUEST_FROM，
        //     插件 token 调自己必然 403（"can't update itself"）；
        //   - hassio.addon_update（HA Core 服务）实测返回 400 空响应（add-on token
        //     调 HA Core 服务 API 权限不足，aiohttp HTTPBadRequest）。
        // 因此"一键升级"在官方设计上不可行，唯一可靠路径是管理员在
        // Supervisor 加载项页面点击「更新」（设置 → 加载项 → 慧尖 LoRa 网关）。
        // 本函数直接跳转到该页面，不再发起注定失败的 API 调用。
        // v1.6.16 补充：新版 Supervisor（App 架构）中，已安装加载项的详情页与
        // 「更新」接口都依赖商店条目（App.app_store = store.get(slug)）；若客户
        // 删除过仓库或商店刷新失败，跳转后会报
        // "App huijian_mqtt_broker does not exist in the store"（StoreAppNotFoundError）。
        // 这不是本插件的 bug，须重新添加仓库并更新商店才能恢复，故在文案中给出指引。
        async function doUpgrade() {
            const openAddon = confirm(
                'Supervisor 安全设计禁止插件通过 API 自我更新（一键升级会返回 403/400），\n' +
                '请以管理员身份在 Supervisor 加载项页面点击「更新」。\n\n' +
                '现在为你打开加载项页面？\n\n' +
                '若打开后提示 "does not exist in the store"：请到 设置→加载项→\n' +
                '加载项商店→⋮→仓库 重新添加插件仓库并更新商店后再试。'
            );
            if (openAddon) {
                // ingress iframe 的 origin 即 HA 前端 origin，可跳转到加载项详情页
                window.open(window.location.origin + '/hassio/addon/huijian_mqtt_broker', '_blank');
            }
        }

        // ========== 工具函数 ==========
        function compareVersions(v1, v2) {
            const parts1 = v1.split('.').map(Number);
            const parts2 = v2.split('.').map(Number);
            for (let i = 0; i < Math.max(parts1.length, parts2.length); i++) {
                const p1 = parts1[i] || 0, p2 = parts2[i] || 0;
                if (p1 > p2) return 1;
                if (p1 < p2) return -1;
            }
            return 0;
        }

        function escapeHtml(text) {
            if (text === null || text === undefined) return '';
            return String(text).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
        }

        // ========== 实体精确定位（2026-08-28 修复） ==========
        // 背景：Web UI 之前用设备 SN 后 6 位模糊匹配 entity_id，但设备显示名
        // 只含 SN 后 4 位（"开窗器 1207-0603 (#01)"），HA 生成的 entity_id
        // 里没有后 6 位 → 永远匹配不上 → "未找到设备 cover 实体"。
        // 现在 API（/window_controller_gateway/devices）为每个设备返回精确实体
        // 列表（entity_id/domain/unique_id），这里按 unique_id 精确查找：
        //   unique_id 格式：{gateway_sn}_{device_sn}_{suffix}
        // 用 device_sn（设备 SN）做唯一锚点匹配，天然精确、无前缀歧义。
        // 从 HA 设备 identifiers 中取本集成的 SN（v1.6.3）：
        // identifiers 是 (config_entry 命名空间, 值) 的集合，顺序不保证且可能
        // 含其它命名空间（如 mqtt 发现条目的 (DOMAIN, topic) 形式），
        // 取 identifiers[0] 是位置假设——必须按本集成 DOMAIN 匹配。
        function deviceSnOf(dev) {
            if (!dev || !Array.isArray(dev.identifiers)) return null;
            for (const ident of dev.identifiers) {
                if (Array.isArray(ident) && ident.length > 1 && ident[0] === DOMAIN) return ident[1];
            }
            return null;
        }

        function findEntityByUniqueId(dev, domain, suffix) {
            if (!dev || !dev.entities || !dev.entities.length) return null;
            const deviceSn = deviceSnOf(dev);
            if (!deviceSn) return null;
            // 常规实体 unique_id 为 {gw}_{device_sn}_{suffix}，锚点 _ {device_sn} _ {suffix}。
            // 删除按钮 special：unique_id 为 {gw}_remove_{device_sn}（remove 在 device_sn 前，
            // gateway.py:228），锚点应为 _remove_ {device_sn}——2026-08-28 修复。
            const anchors = [
                '_' + deviceSn + '_' + suffix,   // 常规布局
                '_' + suffix + '_' + deviceSn,   // 删除按钮布局（{gw}_remove_{sn}）
            ];
            for (const e of dev.entities) {
                if (e.domain !== domain || !e.unique_id) continue;
                if (anchors.some(a => e.unique_id.endsWith(a))) return e;
            }
            return null;
        }

        function findEntityByDomain(dev, domain) {
            if (!dev || !dev.entities || !dev.entities.length) return null;
            return dev.entities.find(e => e.domain === domain) || null;
        }

        // 删除按钮实体特殊归属：GatewayDeviceRemoveButton.device_info 用网关 SN
        // （gateway.py identifiers={(DOMAIN, gateway_sn)}），实体挂在网关设备下，
        // 不在子设备 dev.entities 里。v1.5.5 起 remove 分支只在子设备实体列表中
        // 按 unique_id 查找，导致恒报"未找到删除按钮实体"（v1.5.9 双锚点仍未
        // 跳出子设备实体列表，方向不对）。
        // 修复：先按常规路径在子设备实体列表中找（兼容未来实体归属调整），
        // 找不到时用目标子设备 SN 构造 _remove_{sn} 锚点（删除按钮 unique_id
        // 固定为 {gw}_remove_{sn}，gateway.py:228），在 API 返回的整个设备列表
        // （网关 parent + 子设备）中搜索——一定能命中网关设备下的删除按钮。
        function findRemoveButtonEntity(dev, devices) {
            const direct = findEntityByUniqueId(dev, 'button', 'remove');
            if (direct) return direct;
            const deviceSn = deviceSnOf(dev);
            if (!deviceSn || !devices || !devices.length) return null;
            const anchor = '_remove_' + deviceSn;
            for (const d of devices) {
                if (!d || !d.entities) continue;
                const hit = d.entities.find(e =>
                    e.domain === 'button' && e.unique_id && e.unique_id.endsWith(anchor)
                );
                if (hit) return hit;
            }
            return null;
        }

        // 按 unique_id 锚点找到实体，再返回其在 states 中对应的 state 对象
        // （含 entity_id/state/attributes，供渲染与控制使用）。
        // 找不到实体或 states 中无此实体时返回 null。
        function findEntityState(dev, domain, suffix, states) {
            const ent = findEntityByUniqueId(dev, domain, suffix);
            if (!ent || !ent.entity_id) return null;
            return states.find(s => s.entity_id === ent.entity_id) || null;
        }

        // HTML 解析器会在 JS 编译前解码 &#39;，实体转义保护不了单引号包裹的 onclick/onchange 参数，需额外转义
        function jsQuote(v) {
            return String(v == null ? '' : v).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
        }

        // onclick/onchange 等事件属性的正确转义顺序（v1.6.3 修复）：
        // 必须先 jsQuote（JS 层转义单引号）再 escapeHtml（HTML 属性层）。
        // 反序（jsQuote(escapeHtml(x))）时 `'` 已变成 `&#39;`，jsQuote 找不到
        // 裸引号可转义，而浏览器解析属性时会把 `&#39;` 还原成 `'` 再交给 JS 引擎
        // ——单引号字符串被闭合，用户可控值（设备昵称可重命名）可注入任意 JS。
        // 仅限事件属性；文本节点仍然只用 escapeHtml。
        function jsAttr(v) {
            return escapeHtml(jsQuote(v));
        }

        function showToast(message, type) {
            const toast = document.createElement('div');
            toast.className = 'toast toast-' + (type || 'ok');
            toast.textContent = message;
            document.body.appendChild(toast);
            setTimeout(() => {
                toast.style.opacity = '0';
                toast.style.transition = 'opacity 0.3s';
                setTimeout(() => toast.remove(), 300);
            }, 3000);
        }

        // ========== 启动 ==========
        init();
        // 定时无感刷新：只更新状态值，不重建 DOM，避免页面闪烁。
        // v1.6.3：页面不可见（后台标签/手机锁屏内嵌页）时跳过——
        // 每轮每个网关各拉一次全量 /states，隐藏页轮询纯耗 Home Assistant 资源
        setInterval(() => {
            if (document.hidden) return;
            silentRefresh();
        }, 30000);
