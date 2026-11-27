const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value).replace(/[&<>"']/g, (char) => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
const address = (value) => '0x' + value.toString(16).toUpperCase().padStart(8, '0');
const typeLabel = (symbol) => symbol.type === 'bool' ? 'bool' : ['f32','i32','u32','i16','u16','i8','u8'][symbol.type_id];
const icons = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
  star: '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3l-5.6 2.9 1.1-6.2L3 9.6l6.2-.9Z"/>',
  connect: '<rect x="3" y="8" width="6" height="8" rx="2"/><rect x="15" y="8" width="6" height="8" rx="2"/><path d="M9 12h6M6 5v3m12-3v3M6 16v3m12-3v3"/>',
  settings: '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="currentColor"/><circle cx="16" cy="17" r="3" fill="currentColor"/>',
  reload: '<path d="M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 13 3M18 18A8 8 0 0 1 5 15"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
  bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
  file: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9ZM14 3v6h6M8 13h8m-8 4h5"/>',
  copy: '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>'
};
document.querySelectorAll('[data-icon]').forEach((el) => { el.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[el.dataset.icon]}</svg>`; });
let state = null;
let outputFormat = 'hex';
let currentView = 'workspace';
let busy = false;
let dragging = null;
let toastTimer;
let lastSnapshot = '';
let workspaceGeneration = null;
let workspaceDialogAction = 'open';
const openBranches = new Set();
const searchBranchOverrides = new Map();

function toast(message) {
  $('#toast').textContent = message;
  $('#toast').classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('#toast').classList.add('hidden'), 5000);
}

async function request(action, data = {}) {
  const response = await fetch('/api', { method: 'POST', headers: {'Content-Type': 'application/json', 'X-Api-Token': $('meta[name="api-token"]').content}, body: JSON.stringify({action, data}) });
  if (!response.ok) throw new Error(`Backend returned ${response.status}`);
  const result = await response.json();
  if (result.request_error) throw new Error(result.request_error);
  return result;
}

async function api(action, data = {}, silent = false) {
  if (busy) return;
  busy = true;
  try {
    const next = await request(action, data);
    const serialized = JSON.stringify(next);
    if (serialized !== lastSnapshot) {
      const oldError = state?.error;
      const wasChanged = state?.changed;
      const workspaceOnly = state && JSON.stringify({...state, workspace:undefined}) === JSON.stringify({...next, workspace:undefined});
      state = next;
      lastSnapshot = serialized;
      if (workspaceOnly) renderWorkspace();
      else render();
      if (state.error && state.error !== oldError) toast(state.error);
      if (state.changed && !wasChanged) openReparseDialog();
    }
    return next;
  } catch (error) {
    if (!silent) toast(error.message);
  } finally {
    busy = false;
  }
}

function symbolMap() { return new Map((state?.firmware?.symbols || []).map((s) => [s.path, s])); }
function matches(symbol, path) {
  const query = $('#search').value.toLowerCase().trim();
  return !query || path.toLowerCase().includes(query) || (symbol && (address(symbol.address).toLowerCase().includes(query) || symbol.type.includes(query)));
}
function pill(label, tone = '') { return `<span class="pill"><b class="status-dot ${tone}"></b>${esc(label)}</span>`; }
function empty(text) { return `<div class="empty-note">${esc(text)}</div>`; }
function render() {
  renderWorkspace();
  const firmware = state.firmware;
  const symbols = symbolMap();
  $('#firmware-pill').innerHTML = `<b class="status-dot ${firmware ? '' : 'gray'}"></b>${firmware ? `${esc(firmware.name)} · ${address(firmware.fingerprint)}` : 'No firmware'}`;
  $('#firmware-pill').title = firmware ? `${firmware.name} · ${address(firmware.fingerprint)}` : 'No firmware';
  $('#load-state').textContent = state.loading ? 'Parsing DWARF in background…' : firmware ? `${firmware.symbols.length} variables · ${firmware.fingerprint_source}` : 'ELF + DWARF · ARM Cortex';
  ['#load', '#browse', '#demo', '#reload'].forEach((id) => { $(id).disabled = state.loading; });
  $('#change-alert .dot').classList.toggle('hidden', !state.changed);
  $('#change-alert').title = state.changed ? '固件已更新，请确认已烧录后重新解析' : '固件文件未变更';
  $('#fingerprint').textContent = firmware ? address(firmware.fingerprint) : '0x————————';
  $('#fingerprint-source').textContent = firmware ? firmware.fingerprint_source : '等待加载固件';
  $('#frame-status').outerHTML = `<span id="frame-status">${pill(state.frame ? 'Valid' : state.slots.length ? 'Invalid' : 'Empty', state.frame ? '' : state.slots.length ? 'amber' : 'gray')}</span>`;
  $('#metric-channels').innerHTML = `${state.slots.length} <small>/ ${state.settings.max_channels}</small>`;
  $('#metric-size').innerHTML = state.frame ? `${state.frame.size} <small>B</small>` : '—';
  $('#metric-crc').textContent = state.frame?.crc || '—';
  $('#metric-ram').textContent = !state.slots.length ? '—' : state.slots.every((p) => symbols.get(p)?.valid) ? 'Pass' : 'Warning';
  $('#channel-preview').textContent = state.slots.length ? state.slots.map((p) => p.split('.').pop()).join(' · ') : 'Select symbols to get started';
  $('#channel-preview').title = state.slots.join('\n');
  $('#favorites-count').textContent = state.favorites.length;
  renderFavorites(symbols);
  $('#presets-list').innerHTML = Object.entries(state.presets).map(([name, paths]) => `<div class="preset"><button data-action="preset" data-name="${esc(name)}">${esc(name)}</button><span>${paths.length} channels</span><button data-action="delete-preset" data-name="${esc(name)}" aria-label="删除预设">×</button></div>`).join('') || empty('保存通道组合，快速切换调试场景。');
  renderTree();
  $('#slots-list').innerHTML = state.slots.map((path, index) => {
    const s = symbols.get(path);
    return `<div class="slot-row" draggable="true" data-index="${index}"><span class="grip">⠿</span><span class="ch-label">CH${index}</span><div class="variable-info"><div class="variable-name ${!s ? 'missing' : ''}" title="${esc(path)}">${esc(path)}</div><div class="variable-address">${s ? `${address(s.address)} · ${s.type}${s.valid ? '' : ' · Outside RAM'}` : 'Missing'}</div></div><button data-action="up" data-index="${index}" aria-label="上移通道" ${index === 0 ? 'disabled' : ''}>↑</button><button data-action="down" data-index="${index}" aria-label="下移通道" ${index === state.slots.length - 1 ? 'disabled' : ''}>↓</button><button data-action="remove-slot" data-index="${index}" aria-label="删除通道">×</button></div>`;
  }).join('') || empty('点击变量旁的 +，加入第一个通道。');
  $('#frame-error').textContent = state.frame_error;
  $('#byte-count').textContent = state.frame ? ` / ${state.frame.size} BYTES` : '';
  renderPayload();
  const transport = state.transport && typeof state.transport === 'object' ? state.transport : null;
  $('#send').disabled = !state.frame || !transport?.connected;
  $('#send-label').textContent = transport?.kind === 'serial' ? '串口发送' : transport?.kind === 'tcp' ? 'TCP 发送' : '模拟发送';
  $('#transport-status').textContent = transport ? transport.status : 'Backend outdated · 请关闭旧窗口并重新运行 start.bat';
  renderConnections();
  $('#log-count').textContent = state.logs.length;
  $('#log-output').textContent = state.logs.length ? state.logs.map((line, i) => `${i + 1}. ${line}`).join('\n') : '尚无发送记录。';
}

function renderConnections() {
  const transport = state.transport;
  if (!transport || typeof transport !== 'object') {
    $('#serial-state').innerHTML = '<b class="status-dot red"></b>Backend outdated';
    $('#tcp-state').innerHTML = '<b class="status-dot red"></b>Backend outdated';
    $('#proxy-state').innerHTML = '<b class="status-dot red"></b>Backend outdated';
    $('#serial-error').textContent = '当前窗口由旧版后端进程提供服务。请关闭所有 Axon 窗口，再重新运行 start.bat。';
    $('#tcp-error').textContent = '';
    $('#proxy-error').textContent = '';
    $('#serial-ports-status').textContent = '后端版本过旧，无法枚举串口。';
    ['#serial-port', '#serial-port-select', '#serial-baud', '#serial-data-bits',
     '#tcp-host', '#tcp-port', '#proxy-host', '#proxy-port'].forEach((selector) => { $(selector).disabled = true; });
    ['#serial-connect', '#serial-disconnect', '#tcp-connect', '#tcp-disconnect',
     '#proxy-start', '#proxy-stop', '#use-mock'].forEach((selector) => { $(selector).disabled = true; });
    return;
  }
  const serialConnected = transport.kind === 'serial' && transport.connected;
  const serialSelected = transport.kind === 'serial';
  const serialLabel = serialConnected ? 'Serial connected' : serialSelected ? 'Serial disconnected' : 'Serial not selected';
  $('#serial-state').innerHTML = `<b class="status-dot ${serialConnected ? '' : serialSelected ? 'amber' : 'gray'}"></b>${esc(serialLabel)}`;
  $('#serial-error').textContent = serialSelected ? transport.error || '' : '';
  ['#serial-port', '#serial-port-select', '#serial-baud', '#serial-data-bits'].forEach((selector) => { $(selector).disabled = serialConnected; });
  $('#serial-connect').disabled = serialConnected;
  $('#serial-disconnect').disabled = !serialConnected;

  const tcpConnected = transport.kind === 'tcp' && transport.connected;
  const tcpSelected = transport.kind === 'tcp';
  const tcpLabel = tcpConnected ? 'TCP connected' : tcpSelected ? 'TCP disconnected' : 'TCP not selected';
  $('#tcp-state').innerHTML = `<b class="status-dot ${tcpConnected ? '' : tcpSelected ? 'amber' : 'gray'}"></b>${esc(tcpLabel)}`;
  $('#tcp-error').textContent = tcpSelected ? transport.error || '' : '';
  ['#tcp-host', '#tcp-port'].forEach((selector) => { $(selector).disabled = tcpConnected; });
  $('#tcp-connect').disabled = tcpConnected;
  $('#tcp-disconnect').disabled = !tcpConnected;

  const proxy = transport.proxy || {};
  const proxyRunning = !!proxy.running;
  const proxyError = proxy.error || '';
  const proxyLabel = proxyRunning ? `Proxy listening · ${proxy.clients || 0}` : proxyError ? 'Proxy error' : 'Proxy stopped';
  $('#proxy-state').innerHTML = `<b class="status-dot ${proxyRunning ? '' : proxyError ? 'red' : 'gray'}"></b>${esc(proxyLabel)}`;
  $('#proxy-error').textContent = proxyError;
  ['#proxy-host', '#proxy-port'].forEach((selector) => { $(selector).disabled = proxyRunning; });
  $('#proxy-start').disabled = proxyRunning;
  $('#proxy-stop').disabled = !proxyRunning;

  $('#use-mock').disabled = transport.kind === 'mock' && transport.connected;
}

function populateConnectionForm() {
  if (!state || !state.transport || typeof state.transport !== 'object') return;
  const serial = state.transport.serial || {};
  $('#serial-port').value = serial.port || 'COM3';
  $('#serial-baud').value = serial.baudrate || 115200;
  $('#serial-data-bits').value = String(serial.data_bits || 8);
  const tcp = state.transport.tcp || {};
  $('#tcp-host').value = tcp.host || '';
  $('#tcp-port').value = tcp.port || 9000;
  const proxy = state.transport.proxy || {};
  $('#proxy-host').value = proxy.host || '127.0.0.1';
  $('#proxy-port').value = proxy.port || 9000;
}

async function refreshSerialPorts(silent = false) {
  try {
    const result = await request('serial_ports');
    const ports = result.ports || [];
    const options = ports.map((port) => `<option value="${esc(port.device)}">${esc(port.device)} · ${esc(port.description || '')}</option>`).join('');
    $('#serial-ports').innerHTML = options;
    $('#serial-port-select').innerHTML = '<option value="">选择检测到的端口…</option>' + options;
    $('#serial-ports-status').textContent = ports.length ? `检测到 ${ports.length} 个串口` : '未检测到串口，请检查 USB 驱动或设备管理器。';
    const current = $('#serial-port').value.trim();
    $('#serial-port-select').value = ports.some((port) => port.device === current) ? current : '';
  } catch (error) {
    $('#serial-ports-status').textContent = `枚举失败：${error.message}`;
    if (!silent) toast(error.message);
  }
}

function openReparseDialog() {
  if (!state?.changed) {
    toast('固件文件未变更');
    return;
  }
  const dialog = $('#reparse-dialog');
  if (dialog.open) return;
  if (document.querySelector('dialog[open]')) {
    toast('检测到 .axf 更新，请先关闭当前对话框后处理。');
    return;
  }
  $('#reparse-file').textContent = state.workspace?.firmware_path || state.firmware?.name || '当前固件';
  $('#reparse-fingerprint').textContent = state.firmware ? address(state.firmware.fingerprint) : '—';
  dialog.showModal();
}

function renderFavorites(symbols) {
  $('#favorites-list').innerHTML = state.favorites.filter((path) => matches(symbols.get(path), path)).map((path) => {
    const s = symbols.get(path), selected = state.slots.includes(path);
    return `<div class="favorite-row"><span class="type-icon ${s?.type_id ? 'int' : ''}">${s ? typeLabel(s) : '?'}</span><div class="variable-info"><div class="variable-name ${!s ? 'missing' : ''}" title="${esc(path)}">${esc(path)}</div><div class="variable-address">${s ? `${address(s.address)} · ${s.type}` : 'Missing · 等待符号重新匹配'}</div></div><button class="pill ${selected ? 'selected' : ''}" data-action="toggle-slot" data-path="${esc(path)}" ${!s || !s.valid ? 'disabled' : ''}><b class="status-dot ${!s || !s.valid ? 'amber' : selected ? '' : 'gray'}"></b>${!s ? 'Missing' : !s.valid ? 'RAM' : selected ? 'Added' : '＋ Add'}</button><button class="remove-fav" data-action="favorite" data-path="${esc(path)}" title="取消收藏" aria-label="取消收藏">×</button></div>`;
  }).join('') || empty(state.favorites.length ? '没有匹配的收藏变量。' : '点击变量旁的 ☆，收藏常用变量。');
}

function renderTree() {
  if (!state.firmware) {
    $('#symbol-tree').innerHTML = empty(state.loading ? '正在后台解析工作区固件…' : '加载固件或示例符号，开始配置。');
    $('#symbol-count').textContent = '0 symbols';
    $('#parser-notes').textContent = '';
    return;
  }
  const query = $('#search').value.toLowerCase().trim();
  const all = state.firmware.symbols.filter((s) => matches(s, s.path));
  const filtered = all.slice(0, 500);
  $('#symbol-count').textContent = `${all.length} symbols`;
  const root = {children: new Map()};
  filtered.forEach((s) => {
    const parts = s.path.match(/[^.[\]]+|\[[^\]]+\]/g) || [s.path];
    let parent = root;
    parts.forEach((part, index) => {
      if (!parent.children.has(part)) parent.children.set(part, {children: new Map()});
      parent = parent.children.get(part);
      if (index === parts.length - 1) parent.symbol = s;
    });
  });
  const build = (node, prefix = '', pathPrefix = '', ancestorMatched = false) => [...node.children].map(([label, child]) => {
    const key = prefix + '/' + label;
    const branchPath = pathPrefix + (pathPrefix && !label.startsWith('[') ? '.' : '') + label;
    if (child.symbol) {
      const s = child.symbol, favorite = state.favorites.includes(s.path), selected = state.slots.includes(s.path);
      return `<div class="leaf"><span class="leaf-type">${typeLabel(s)}</span><div class="variable-info"><div class="variable-name" title="${esc(s.path)}">${esc(label)}</div><div class="variable-address ${s.valid ? '' : 'warning-address'}">${address(s.address)}${s.valid ? '' : ' · Outside RAM'}</div></div><button data-action="favorite" data-path="${esc(s.path)}" class="${favorite ? 'selected' : ''}" aria-label="${favorite ? '取消收藏' : '收藏'} ${esc(s.path)}">${favorite ? '★' : '☆'}</button><button data-action="toggle-slot" data-path="${esc(s.path)}" class="plus ${selected ? 'selected' : ''}" aria-label="${selected ? '移出' : '添加'} ${esc(s.path)}" ${!s.valid ? 'disabled title="地址不在合法 RAM 内"' : ''}>${selected ? '✓' : '+'}</button></div>`;
    }
    const nameMatched = ancestorMatched || (query && branchPath.toLowerCase().includes(query));
    const isOpen = query ? (searchBranchOverrides.get(key) ?? !nameMatched) : openBranches.has(key);
    return `<details data-branch="${esc(key)}" ${isOpen ? 'open' : ''}><summary><span class="folder-mark">▱</span>${esc(label)}<span class="tiny muted">${child.children.size}</span></summary><div class="tree-branch">${build(child, key, branchPath, nameMatched)}</div></details>`;
  }).join('');
  $('#symbol-tree').innerHTML = build(root) || empty('没有匹配的符号。');
  const notes = [...state.firmware.warnings];
  if (all.length > 500) notes.unshift(`显示前 500 / ${all.length} 个叶子，请搜索缩小范围。`);
  $('#parser-notes').textContent = notes.slice(0, 3).join(' · ') + (notes.length > 3 ? ` · 另有 ${notes.length - 3} 条解析提示（悬停查看前 50 条）` : '');
  $('#parser-notes').title = notes.slice(0, 50).join('\n');
  $('#symbol-tree').querySelectorAll('details').forEach((el) => {
    const initialOpen = el.open;
    el.addEventListener('toggle', () => {
      if (!el.isConnected) return;
      if (query) {
        if (el.open !== initialOpen || searchBranchOverrides.has(el.dataset.branch)) {
          searchBranchOverrides.set(el.dataset.branch, el.open);
        }
      } else if (el.open) openBranches.add(el.dataset.branch);
      else openBranches.delete(el.dataset.branch);
    });
  });
}

function renderPayload() {
  if (!state.frame) { $('#payload').textContent = state.frame_error ? '请修复通道配置后重新生成。' : '等待选择通道…'; return; }
  if (outputFormat !== 'hex') { $('#payload').textContent = state.frame[outputFormat]; return; }
  const segments = state.frame.segments;
  $('#payload').innerHTML = segments.map((segment, i) => `<span class="segment-${i < 2 ? 'header' : i === 2 ? 'fingerprint' : i === 3 ? 'count' : i === segments.length - 1 ? 'crc' : 'slot'}">${esc(segment.toUpperCase())}</span>`).join('');
}

async function copy(format) {
  const result = await api('generate');
  if (!result?.frame) return;
  try { await navigator.clipboard.writeText(result.frame[format]); toast('已复制到剪贴板'); }
  catch { toast('剪贴板不可用，请从帧透视区手动复制。'); }
}

function setView(view) {
  currentView = view;
  const isWorkspace = view === 'workspace' || view === 'favorites';
  $('#workspace').classList.toggle('hidden', !isWorkspace);
  $('#connections-view').classList.toggle('hidden', view !== 'connections');
  $('#settings-view').classList.toggle('hidden', view !== 'settings');
  $('.heading').classList.toggle('hidden', !isWorkspace);
  document.querySelectorAll('.nav[data-view]').forEach((el) => el.classList.toggle('active', el.dataset.view === view));
  if (view === 'favorites') { $('.favorites-section').scrollIntoView({behavior:'smooth', block:'center'}); }
  if (view === 'settings' && state) {
    $('#setting-header').value = state.settings.header;
    $('#setting-max').value = state.settings.max_channels;
    $('#setting-ram').value = state.settings.ranges.map(([a, b]) => `${address(a)}-${address(b)}`).join('\n');
  }
  if (view === 'connections' && state) {
    populateConnectionForm();
    refreshSerialPorts(true);
  }
}

function renderWorkspace() {
  const workspace = state.workspace;
  if (!workspace) return;
  if (workspaceGeneration !== workspace.generation) {
    workspaceGeneration = workspace.generation;
    openBranches.clear();
    searchBranchOverrides.clear();
    $('#search').value = '';
    $('#firmware-path').value = workspace.firmware_path || '';
    if (currentView === 'settings') setView('settings');
    if (currentView === 'connections') {
      populateConnectionForm();
      refreshSerialPorts(true);
    }
  }
  $('#workspace-name').textContent = workspace.name;
  $('#workspace-save-dot').className = `status-dot ${workspace.status === 'pending' ? 'amber' : workspace.status === 'error' ? 'red' : ''}`;
  const status = workspace.status === 'error' ? '保存失败' : workspace.status === 'pending' ? '等待保存…' : '已保存';
  $('#workspace-save-label').textContent = status;
  $('#workspace-toggle').title = `${workspace.name} · ${status}\n${workspace.path || '尚未选择保存位置'}`;
  $('#workspace-location').textContent = workspace.path || '尚未选择保存位置，请另存为';
  $('#workspace-save-error').textContent = workspace.save_error;
  $('#recent-workspaces').innerHTML = workspace.recent.map((path) => `<button data-workspace-action="open" data-workspace-path="${esc(path)}" class="recent-workspace ${path === workspace.path ? 'current' : ''}" title="${esc(path)}"><span>${esc(path.split(/[\\/]/).pop())}</span><small>${esc(path)}</small></button>`).join('') || '<div class="workspace-location">暂无最近工作区</div>';
}

async function workspaceAction(action, path) {
  $('#workspace-menu').classList.add('hidden');
  $('#workspace-toggle').setAttribute('aria-expanded', 'false');
  if (path || state?.workspace.native_dialog || ['save', 'reveal'].includes(action)) {
    const result = await api(`workspace_${action}`, path ? {path} : {});
    if (result && action !== 'reveal') toast('工作区已更新');
    return;
  }
  workspaceDialogAction = action;
  $('#workspace-dialog-title').textContent = {new:'新建工作区', open:'打开工作区', save_as:'工作区另存为'}[action];
  $('#workspace-name-label').classList.toggle('hidden', action !== 'new');
  $('#new-workspace-name').required = action === 'new';
  $('#new-workspace-name').value = '';
  $('#workspace-file-path').value = action === 'save_as' ? state.workspace.path || '' : '';
  $('#workspace-dialog').showModal();
}

document.addEventListener('click', async (event) => {
  const target = event.target.closest('button');
  if (!target) return;
  if (target.dataset.workspaceAction) return workspaceAction(target.dataset.workspaceAction, target.dataset.workspacePath);
  if (target.dataset.view) return setView(target.dataset.view);
  if (target.dataset.format) {
    outputFormat = target.dataset.format;
    document.querySelectorAll('[data-format]').forEach((el) => el.classList.toggle('selected', el === target));
    return state && renderPayload();
  }
  const action = target.dataset.action;
  if (!action || !state) return;
  const path = target.dataset.path;
  if (action === 'favorite') return api('favorite', {path});
  if (action === 'preset') return api('load_preset', {name:target.dataset.name});
  if (action === 'delete-preset') return api('delete_preset', {name:target.dataset.name});
  const paths = [...state.slots];
  const index = Number(target.dataset.index);
  if (action === 'toggle-slot') {
    const existing = paths.indexOf(path);
    if (existing >= 0) paths.splice(existing, 1); else paths.push(path);
  } else if (action === 'remove-slot') paths.splice(index, 1);
  else if (action === 'up' && index > 0) [paths[index - 1], paths[index]] = [paths[index], paths[index - 1]];
  else if (action === 'down' && index < paths.length - 1) [paths[index + 1], paths[index]] = [paths[index], paths[index + 1]];
  else return;
  await api('slots', {paths});
});
$('#demo').onclick = () => api('demo');
$('#empty-demo').onclick = () => api('demo');
$('#load').onclick = () => api('load', {path:$('#firmware-path').value.trim().replace(/^"|"$/g, '')});
$('#firmware-path').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('#load').click(); });
$('#browse').onclick = () => api('browse');
$('#reload').onclick = () => { if (state?.changed) openReparseDialog(); else api('reload'); };
$('#change-alert').onclick = () => { if (state?.changed) openReparseDialog(); else toast('固件文件未变更'); };
$('#ignore-reparse').onclick = async () => {
  $('#reparse-dialog').close();
  const result = await api('ignore_change');
  if (result) toast('已忽略本次更新；文件再次变化时会重新提示。');
};
$('#confirm-reparse').onclick = async () => {
  $('#reparse-dialog').close();
  await api('reload', {confirmed:true});
};
$('#search').addEventListener('input', () => {
  searchBranchOverrides.clear();
  if (state) { renderFavorites(symbolMap()); renderTree(); }
});
document.addEventListener('keydown', (e) => { if (e.key === '/' && !['INPUT','TEXTAREA'].includes(document.activeElement.tagName)) { e.preventDefault(); $('#search').focus(); } });
$('#clear-slots').onclick = () => api('slots', {paths:[]});
$('#copy-hex').onclick = () => copy('hex');
$('#copy-c').onclick = () => copy('c_array');
$('#copy-output').onclick = () => copy(outputFormat);
$('#send').onclick = async () => {
  const result = await api('send');
  if (!result) return;
  if (result.transport.kind === 'serial') toast(`已通过串口发送 ${result.frame?.size ?? 0} 字节`);
  else if (result.transport.kind === 'tcp') toast(`已通过 TCP 发送 ${result.frame?.size ?? 0} 字节`);
  else toast('模拟发送成功 · 未发送到真实设备');
};
$('#serial-connect').onclick = async () => {
  const config = {port:$('#serial-port').value.trim(), baudrate:Number($('#serial-baud').value), data_bits:Number($('#serial-data-bits').value)};
  const proxy = {host:$('#proxy-host').value.trim(), port:Number($('#proxy-port').value)};
  const result = await api('transport_connect', {kind:'serial', config, proxy});
  if (!result) return;
  const error = result.transport.error || result.transport.proxy?.error;
  if (error) toast(error);
  else if (result.transport.connected) toast(`串口 ${config.port} 已连接`);
};
$('#serial-disconnect').onclick = async () => { const result = await api('transport_disconnect'); if (result) toast('串口已断开'); };
$('#tcp-connect').onclick = async () => {
  const config = {host:$('#tcp-host').value.trim(), port:Number($('#tcp-port').value)};
  const proxy = {host:$('#proxy-host').value.trim(), port:Number($('#proxy-port').value)};
  const result = await api('transport_connect', {kind:'tcp', config, proxy});
  if (!result) return;
  const error = result.transport.error || result.transport.proxy?.error;
  if (error) toast(error);
  else if (result.transport.connected) toast(`TCP ${config.host}:${config.port} 已连接`);
};
$('#tcp-disconnect').onclick = async () => { const result = await api('transport_disconnect'); if (result) toast('TCP 与本地代理已断开'); };
$('#proxy-start').onclick = async () => {
  const config = {host:$('#proxy-host').value.trim(), port:Number($('#proxy-port').value)};
  const result = await api('proxy_start', {config});
  if (!result) return;
  if (result.transport.proxy.error) toast(result.transport.proxy.error);
  else if (result.transport.proxy.running) toast(`本地代理已监听 ${config.host}:${config.port}`);
};
$('#proxy-stop').onclick = async () => { const result = await api('proxy_stop'); if (result) toast('本地代理已停止'); };
$('#use-mock').onclick = async () => { const result = await api('transport_connect', {kind:'mock'}); if (result) toast('已切换到模拟发送'); };
$('#serial-refresh').onclick = () => refreshSerialPorts();
$('#serial-port-select').onchange = () => {
  const value = $('#serial-port-select').value;
  if (value) $('#serial-port').value = value;
};
$('#save-preset').onclick = () => { if (!state?.slots.length) return toast('请先选择通道'); $('#preset-dialog').showModal(); $('#preset-name').focus(); };
$('#cancel-preset').onclick = () => $('#preset-dialog').close();
$('#preset-form').onsubmit = async (e) => { e.preventDefault(); if (await api('save_preset', {name:$('#preset-name').value})) { $('#preset-dialog').close(); toast('预设已保存'); } };
$('#settings-form').onsubmit = async (e) => {
  e.preventDefault();
  try {
    const ranges = $('#setting-ram').value.trim().split('\n').map((line) => {
      const match = line.trim().match(/^(0x[\da-f]+|\d+)\s*-\s*(0x[\da-f]+|\d+)$/i);
      if (!match) throw new Error('RAM 格式错误，使用 0x20000000-0x20020000');
      return [Number(match[1]), Number(match[2])];
    });
    if (await api('settings', {header:$('#setting-header').value, max_channels:Number($('#setting-max').value), ranges})) toast('协议配置已保存');
  } catch (error) { toast(error.message); }
};
$('#slots-list').addEventListener('dragstart', (e) => { const row = e.target.closest('.slot-row'); if (!row) return; dragging = Number(row.dataset.index); row.classList.add('dragging'); e.dataTransfer.setData('text/plain', String(dragging)); e.dataTransfer.effectAllowed = 'move'; });
$('#slots-list').addEventListener('dragover', (e) => { if (dragging !== null) e.preventDefault(); });
$('#slots-list').addEventListener('drop', async (e) => {
  e.preventDefault(); const row = e.target.closest('.slot-row');
  if (row && dragging !== null) { const paths = [...state.slots]; const [moved] = paths.splice(dragging, 1); paths.splice(Number(row.dataset.index), 0, moved); dragging = null; await api('slots', {paths}); }
});
$('#slots-list').addEventListener('dragend', () => { dragging = null; document.querySelectorAll('.dragging').forEach((el) => el.classList.remove('dragging')); });
$('#dropzone').addEventListener('dragover', (e) => e.preventDefault());
$('#dropzone').addEventListener('drop', (e) => {
  e.preventDefault();
  const file = e.dataTransfer.files[0];
  if (file?.path) { $('#firmware-path').value = file.path; $('#load').click(); }
  else if (file && window.pywebview) { /* Native DOM drop callback resolves the full path. */ }
  else {
    const text = e.dataTransfer.getData('text/plain');
    if (text && !text.startsWith('file:')) { $('#firmware-path').value = text.trim(); $('#load').click(); }
    else toast('浏览器不会暴露文件绝对路径，请使用桌面浏览按钮或粘贴本地路径。');
  }
});
$('#workspace-toggle').onclick = () => {
  const closed = $('#workspace-menu').classList.toggle('hidden');
  $('#workspace-toggle').setAttribute('aria-expanded', String(!closed));
};
document.addEventListener('click', (event) => {
  if (!event.target.closest('.workspace-switcher')) {
    $('#workspace-menu').classList.add('hidden');
    $('#workspace-toggle').setAttribute('aria-expanded', 'false');
  }
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    $('#workspace-menu').classList.add('hidden');
    $('#workspace-toggle').setAttribute('aria-expanded', 'false');
  }
});
$('#cancel-workspace').onclick = () => $('#workspace-dialog').close();
$('#workspace-form').onsubmit = async (event) => {
  event.preventDefault();
  const data = {path:$('#workspace-file-path').value.trim(), name:$('#new-workspace-name').value.trim()};
  if (await api(`workspace_${workspaceDialogAction}`, data)) {
    $('#workspace-dialog').close();
    toast('工作区已更新');
  }
};

let integrationKind = 'firmware';
let integrationRevision = 0;
let generatedRevision = -1;
let integrationBusy = false;

function markIntegrationChanged() {
  integrationRevision += 1;
  $('#copy-integration').disabled = true;
  $('#integration-status').textContent = '选项已变化，请生成 / 刷新提示词。';
}

async function refreshIntegrationPrompt() {
  if (integrationBusy) return;
  const revision = integrationRevision;
  integrationBusy = true;
  $('#generate-integration').disabled = true;
  $('#copy-integration').disabled = true;
  $('#integration-status').textContent = '正在读取当前协议与工作区快照…';
  try {
    const result = await request('integration_prompt', {
      kind: integrationKind, project: $('#integration-project').value,
      mcu: $('#integration-mcu').value, link: $('#integration-link').value,
      include_context: $('#integration-context').checked
    });
    if (revision !== integrationRevision) return;
    $('#integration-output').value = result.prompt;
    $('#integration-output').scrollTop = 0;
    $('#integration-length').textContent = `${result.prompt.length.toLocaleString()} 字符`;
    generatedRevision = revision;
    $('#integration-status').textContent = '已在本地生成。请先预览，再复制到已打开客户工程的 AI 助手；配置变化后需刷新。';
  } catch (error) {
    generatedRevision = -1;
    $('#integration-status').textContent = error.message;
  } finally {
    integrationBusy = false;
    $('#generate-integration').disabled = false;
    $('#copy-integration').disabled = generatedRevision !== integrationRevision;
  }
}

$('#open-integration').onclick = () => {
  $('#integration-dialog').showModal();
  markIntegrationChanged();
  refreshIntegrationPrompt();
};
$('#close-integration').onclick = () => $('#integration-dialog').close();
document.querySelectorAll('[data-prompt-kind]').forEach((button) => {
  button.onclick = () => {
    integrationKind = button.dataset.promptKind;
    document.querySelectorAll('[data-prompt-kind]').forEach((item) => {
      item.classList.toggle('selected', item === button);
      item.setAttribute('aria-pressed', String(item === button));
    });
    markIntegrationChanged();
    refreshIntegrationPrompt();
  };
});
['#integration-project', '#integration-mcu', '#integration-link', '#integration-context'].forEach((selector) => {
  $(selector).addEventListener('input', markIntegrationChanged);
});
$('#generate-integration').onclick = refreshIntegrationPrompt;
$('#copy-integration').onclick = async () => {
  const preview = $('#integration-output');
  preview.focus();
  preview.select();
  try {
    // Preserve the click's user activation in embedded desktop browsers.
    if (!document.execCommand('copy')) {
      await Promise.race([
        navigator.clipboard.writeText(preview.value),
        new Promise((_, reject) => setTimeout(() => reject(new Error('Clipboard timeout')), 1500))
      ]);
    }
    toast('已复制接入提示词，可粘贴到你的 AI 编程助手。');
  } catch {
    $('#integration-status').textContent = '剪贴板不可用，已选中全文，请按 Ctrl+C 复制。';
  }
};
api('state');
setInterval(() => { if (!busy) api('state', {}, true); }, 1200);
