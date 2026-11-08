/**
 * Ripple-mod - Unified Modern Frontend Controller
 */

const API_BASE = '/api.cgi';
let isLogAutoRefresh = true;
let logPollTimer = null;
let currentHwnatState = true;

// Toast Notification Engine
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    toast.style.transition = 'all 0.2s';
    setTimeout(() => toast.remove(), 200);
  }, 3500);
}

// Robust Fetch with Timeout, Error Handling, and Post Body Support
async function apiCall(endpoint, params = {}, timeoutMs = 8000, postBody = null) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  let url = endpoint;
  const fetchOptions = {
    method: postBody ? 'POST' : 'GET',
    headers: { 'Accept': 'application/json' },
    signal: controller.signal
  };

  if (postBody) {
    const query = new URLSearchParams(params).toString();
    url = query ? `${endpoint}?${query}` : endpoint;
    fetchOptions.headers['Content-Type'] = 'application/x-www-form-urlencoded';
    fetchOptions.body = postBody;
  } else {
    const query = new URLSearchParams(params).toString();
    url = query ? `${endpoint}?${query}` : endpoint;
  }

  try {
    const response = await fetch(url, fetchOptions);
    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const text = await response.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch (e) {
      console.warn('API returned non-JSON:', text);
      throw new Error('设备响应格式异常');
    }
    return data;
  } catch (err) {
    clearTimeout(timeoutId);
    if (err.name === 'AbortError') {
      throw new Error(`请求超时 (${Math.round(timeoutMs/1000)}s)，设备未响应`);
    }
    throw err;
  }
}

// Button Debounce & Loading State Wrapper
async function withButtonLoading(btn, asyncFn) {
  if (!btn || btn.disabled) return;
  const originalHtml = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span> 处理中...`;
  try {
    await asyncFn();
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalHtml;
  }
}

// Navigation Tabs
function initTabs() {
  const tabs = document.querySelectorAll('.nav-tab');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const targetId = tab.dataset.target;
      switchTab(targetId);
    });
  });
}

// Switch Tab programmatically
function switchTab(targetId) {
  const tabs = document.querySelectorAll('.nav-tab');
  const panels = document.querySelectorAll('.tab-content');
  tabs.forEach(t => {
    t.classList.toggle('active', t.dataset.target === targetId);
  });
  panels.forEach(p => {
    p.classList.toggle('active', p.id === targetId);
  });

  if (targetId === 'tab-network') loadNetworkSettings();
  if (targetId === 'tab-wifi') loadWifiSettings();
  if (targetId === 'tab-clients') loadClientList();
  if (targetId === 'tab-adblock') loadAdblockRules();
  if (targetId === 'tab-system') loadCronTasks();
  if (targetId === 'tab-logs') fetchLiveLogs();

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function openPluginGui(id) {
  const tabMap = {
    'hosts_adblock_dns': 'tab-adblock',
    'custom_userscript': 'tab-system',
    'entware_package_mgr': 'tab-system'
  };
  const target = tabMap[id];
  if (target) {
    switchTab(target);
    showToast(`已转入【${id}】管理控制台`, 'info');
  } else {
    showToast(`插件 ${id} 暂无独立 GUI 页面`, 'info');
  }
}

// System Overview
async function refreshSysInfo() {
  try {
    const res = await apiCall(API_BASE, { action: 'sysinfo' });
    if (res.status === 0 && res.system) {
      const s = res.system;

      // Kernel & Hostname
      const elKernel = document.getElementById('sys-kernel');
      if (elKernel) elKernel.textContent = s.kernel || 'Linux 5.10.70';

      // Uptime
      const elUptime = document.getElementById('sys-uptime');
      if (elUptime && s.uptime_seconds) {
        const d = Math.floor(s.uptime_seconds / 86400);
        const h = Math.floor((s.uptime_seconds % 86400) / 3600);
        const m = Math.floor((s.uptime_seconds % 3600) / 60);
        elUptime.textContent = d > 0 ? `${d}天 ${h}小时 ${m}分` : `${h}小时 ${m}分`;
      }

      // CPU Load & Progress Bar
      const cpuPct = s.cpu ? s.cpu.load_percent : Math.min(100, Math.round(parseFloat(s.load_average || 0) * 50));
      const elCpuPct = document.getElementById('sys-cpu-pct');
      const elCpuBar = document.getElementById('sys-cpu-bar');
      const elCpuLoad = document.getElementById('sys-load');
      const elCpuStatus = document.getElementById('sys-cpu-status');
      if (elCpuPct) elCpuPct.textContent = `${cpuPct}%`;
      if (elCpuLoad) elCpuLoad.textContent = (s.cpu && s.cpu.load_average) ? s.cpu.load_average : (s.load_average || '--');
      if (elCpuBar) {
        elCpuBar.style.width = `${cpuPct}%`;
        elCpuBar.className = `progress-bar ${cpuPct > 80 ? 'danger' : (cpuPct > 50 ? 'warning' : '')}`;
      }
      if (elCpuStatus) {
        elCpuStatus.textContent = cpuPct > 80 ? '高负荷' : (cpuPct > 50 ? '繁忙' : '正常');
        elCpuStatus.style.color = cpuPct > 80 ? 'var(--danger)' : (cpuPct > 50 ? 'var(--warning)' : 'var(--success)');
      }

      // Memory & Progress Bar
      let memTotal = s.memory ? s.memory.total_kb : s.memory_total_kb;
      let memFree = s.memory ? s.memory.free_kb : s.memory_free_kb;
      let memUsed = s.memory ? s.memory.used_kb : (memTotal - memFree);
      let memPct = s.memory ? s.memory.percent : Math.round((memUsed / (memTotal || 1)) * 100);
      const elMemPct = document.getElementById('sys-mem-pct');
      const elMemBar = document.getElementById('sys-mem-bar');
      const elMemDetail = document.getElementById('sys-mem-detail');
      const elMemFree = document.getElementById('sys-mem-free');
      if (elMemPct) elMemPct.textContent = `${memPct}%`;
      if (elMemBar) {
        elMemBar.style.width = `${memPct}%`;
        elMemBar.className = `progress-bar ${memPct > 85 ? 'danger' : (memPct > 70 ? 'warning' : '')}`;
      }
      if (elMemDetail) elMemDetail.textContent = `${Math.round(memUsed / 1024)} / ${Math.round(memTotal / 1024)} MB`;
      if (elMemFree) elMemFree.textContent = `${Math.round(memFree / 1024)} MB 可用`;

      // Storage & Progress Bar
      let stTotal = s.storage ? s.storage.total_kb : 26624;
      let stUsed = s.storage ? s.storage.used_kb : 13312;
      let stFree = s.storage ? s.storage.free_kb : (s.storage_free_kb || 13312);
      let stPct = s.storage ? s.storage.percent : Math.round((stUsed / (stTotal || 1)) * 100);
      const elStPct = document.getElementById('sys-storage-pct');
      const elStBar = document.getElementById('sys-storage-bar');
      const elStDetail = document.getElementById('sys-storage-detail');
      const elStFree = document.getElementById('sys-storage-free');
      if (elStPct) elStPct.textContent = `${stPct}%`;
      if (elStBar) {
        elStBar.style.width = `${stPct}%`;
        elStBar.className = `progress-bar ${stPct > 90 ? 'danger' : ''}`;
      }
      if (elStDetail) elStDetail.textContent = `${(stUsed / 1024).toFixed(1)} / ${(stTotal / 1024).toFixed(1)} MB`;
      if (elStFree) elStFree.textContent = `${(stFree / 1024).toFixed(1)} MB 可用`;

      // Wi-Fi Status
      if (s.wifi) {
        if (s.wifi.wifi_5g && s.wifi.wifi_5g.ssid) {
          const elW5Ssid = document.getElementById('wifi5-ssid');
          const elW5Ch = document.getElementById('wifi5-ch');
          if (elW5Ssid) elW5Ssid.textContent = s.wifi.wifi_5g.ssid;
          if (elW5Ch) elW5Ch.textContent = `${s.wifi.wifi_5g.channel} (160 MHz)`;
        }
        if (s.wifi.wifi_2g && s.wifi.wifi_2g.ssid) {
          const elW2Ssid = document.getElementById('wifi2-ssid');
          const elW2Ch = document.getElementById('wifi2-ch');
          if (elW2Ssid) elW2Ssid.textContent = s.wifi.wifi_2g.ssid;
          if (elW2Ch) elW2Ch.textContent = `${s.wifi.wifi_2g.channel} (40 MHz)`;
        }
      }

      // Network & Clients
      const elWanIp = document.getElementById('sys-wan-ip');
      if (elWanIp) elWanIp.textContent = (s.network && s.network.wan_ip) ? s.network.wan_ip : (s.wan_ip || '未分配');
      const elLanIp = document.getElementById('sys-lan-ip');
      if (elLanIp && s.network) elLanIp.textContent = s.network.lan_ip || '192.168.10.1';
      const elLanClients = document.getElementById('sys-lan-clients');
      if (elLanClients && s.network) elLanClients.textContent = `${s.network.lan_clients || 1} 台 (点击查看)`;

      // Services status
      if (s.services) {
        const sSsh = document.getElementById('status-ssh');
        if (sSsh) {
          sSsh.textContent = s.services.ssh ? '监听 :22' : '已停止';
          sSsh.style.color = s.services.ssh ? 'var(--success)' : 'var(--text-muted)';
        }
        const sCrond = document.getElementById('status-crond');
        if (sCrond) {
          sCrond.textContent = s.services.crond ? '运行中' : '已停止';
          sCrond.style.color = s.services.crond ? 'var(--success)' : 'var(--text-muted)';
        }
        const pyStatus = document.getElementById('status-python');
        if (pyStatus) {
          pyStatus.textContent = s.services.python ? `已就绪 (${s.services.python_version || 'v3'})` : '未安装';
          pyStatus.style.color = s.services.python ? 'var(--success)' : 'var(--text-muted)';
        }
      }

      // HWNAT Status button
      if (s.network && s.network.hwnat !== undefined) {
        currentHwnatState = s.network.hwnat;
        const btnHwnat = document.getElementById('btn-toggle-hwnat');
        if (btnHwnat) {
          btnHwnat.textContent = currentHwnatState ? '⚡ 硬件加速: ON' : '⚡ 硬件加速: OFF';
          btnHwnat.className = `btn btn-sm ${currentHwnatState ? 'btn-secondary' : 'btn-warning'}`;
        }
      }
    }
  } catch (err) {
    console.warn('System status poll failed:', err);
  }
}

// Plugin List
async function refreshPlugins() {
  const listEl = document.getElementById('plugin-list-container');
  if (!listEl) return;
  try {
    const res = await apiCall(API_BASE, { action: 'plugin_list' });
    if (res.status === 0 && res.plugins) {
      if (res.plugins.length === 0) {
        listEl.innerHTML = '<div class="text-muted" style="padding: 20px; text-align: center;">暂无已安装插件</div>';
        return;
      }
      listEl.innerHTML = res.plugins.map(p => `
        <div class="card" style="margin-bottom: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px;">
            <div style="flex: 1; min-width: 240px;">
              <div style="font-weight: 600; font-size: 15px; display: flex; align-items: center; gap: 8px;">
                <span>${p.name}</span>
                <span class="brand-badge">v${p.version}</span>
                <span class="status-badge ${p.running ? 'online' : 'offline'}" style="font-size: 11px; padding: 2px 8px;">
                  ${p.running ? '运行中' : '已停止'}
                </span>
              </div>
              <div style="font-size: 13px; color: var(--text-muted); margin-top: 6px; line-height: 1.4;">${p.description || ''}</div>
            </div>
            <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center;">
              <button class="btn btn-primary btn-sm" onclick="openPluginGui('${p.id}')">
                打开面板
              </button>
              <button class="btn btn-secondary btn-sm" onclick="togglePlugin('${p.id}', '${p.running ? 'restart' : 'start'}')">
                ${p.running ? '重启' : '启动'}
              </button>
              ${p.running ? `<button class="btn btn-secondary btn-sm" onclick="togglePlugin('${p.id}', 'stop')">停止</button>` : ''}
              <button class="btn btn-secondary btn-sm" onclick="togglePluginAutostart('${p.id}', ${!p.enabled})">
                ${p.enabled ? '已自启' : '未自启'}
              </button>
            </div>
          </div>
        </div>
      `).join('');
    }
  } catch (err) {
    listEl.innerHTML = `<div style="color: var(--danger); padding: 10px;">插件加载失败: ${err.message}</div>`;
  }
}

function togglePluginInstallDrawer() {
  const drawer = document.getElementById('plugin-install-drawer');
  if (drawer) {
    drawer.style.display = drawer.style.display === 'none' ? 'block' : 'none';
  }
}

async function uploadPluginFile(btn) {
  const fileInput = document.getElementById('plugin-upload-file');
  if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
    showToast('请先选择要上传的插件压缩包 (.tar.gz)', 'warning');
    return;
  }
  const file = fileInput.files[0];
  await withButtonLoading(btn, async () => {
    const base64Data = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result;
        const b64 = result.includes(',') ? result.split(',')[1] : result;
        resolve(b64);
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });

    const body = new URLSearchParams({
      action: 'plugin_install_base64',
      name: file.name,
      data: base64Data
    }).toString();

    const res = await apiCall(API_BASE, {}, 60000, body);
    if (res.status === 0) {
      showToast(res.message || '插件安装成功！', 'success');
      togglePluginInstallDrawer();
      fileInput.value = '';
      refreshPlugins();
    } else {
      throw new Error(res.error || res.message || '插件安装失败');
    }
  });
}

async function installPluginFromUrl(btn) {
  const urlInput = document.getElementById('plugin-url-input');
  if (!urlInput || !urlInput.value.trim()) {
    showToast('请输入有效的插件直链 URL', 'warning');
    return;
  }
  const url = urlInput.value.trim();
  await withButtonLoading(btn, async () => {
    const res = await apiCall(API_BASE, {
      action: 'plugin_install_url',
      url: url
    }, 60000);
    if (res.status === 0) {
      showToast(res.message || '远程插件安装成功！', 'success');
      togglePluginInstallDrawer();
      urlInput.value = '';
      refreshPlugins();
    } else {
      throw new Error(res.error || res.message || '插件下载安装失败');
    }
  });
}

async function togglePlugin(id, act) {
  try {
    const res = await apiCall(API_BASE, { action: `plugin_${act}`, plugin: id });
    showToast(res.message || `插件 ${id} ${act} 成功`, res.status === 0 ? 'success' : 'error');
    refreshPlugins();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function togglePluginAutostart(id, enable) {
  try {
    const act = enable ? 'plugin_enable' : 'plugin_disable';
    const res = await apiCall(API_BASE, { action: act, plugin: id });
    showToast(res.message || '自启设置已更新', 'success');
    refreshPlugins();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// Wi-Fi Settings
async function loadWifiSettings() {
  try {
    const res = await apiCall(API_BASE, { action: 'wifi_get' });
    if (res.status === 0) {
      if (res.wifi_2g) {
        const w2 = res.wifi_2g;
        const elSsid = document.getElementById('wifi-ssid-2g');
        const elPass = document.getElementById('wifi-pass-2g');
        const elCh = document.getElementById('wifi-ch-2g');
        const elBw = document.getElementById('wifi-bw-2g');
        const elHide = document.getElementById('wifi-hide-2g');
        const elEnable = document.getElementById('wifi-enable-2g');
        if (elSsid) elSsid.value = w2.ssid || '';
        if (elPass) elPass.value = w2.password || '';
        if (elCh) elCh.value = String(w2.channel || 0);
        if (elBw) elBw.value = String(w2.bandwidth || 1);
        if (elHide) elHide.checked = !!w2.hidden;
        if (elEnable) elEnable.checked = !!w2.enabled;
      }
      if (res.wifi_5g) {
        const w5 = res.wifi_5g;
        const elSsid5 = document.getElementById('wifi-ssid-5g');
        const elPass5 = document.getElementById('wifi-pass-5g');
        const elCh5 = document.getElementById('wifi-ch-5g');
        const elBw5 = document.getElementById('wifi-bw-5g');
        const elHide5 = document.getElementById('wifi-hide-5g');
        const elEnable5 = document.getElementById('wifi-enable-5g');
        if (elSsid5) elSsid5.value = w5.ssid || '';
        if (elPass5) elPass5.value = w5.password || '';
        if (elCh5) elCh5.value = String(w5.channel || 0);
        if (elBw5) elBw5.value = String(w5.bandwidth || 3);
        if (elHide5) elHide5.checked = !!w5.hidden;
        if (elEnable5) elEnable5.checked = !!w5.enabled;
      }
    }
  } catch (err) {
    console.warn('Load Wi-Fi settings failed:', err);
  }
}

async function saveWifiSettings(event, band) {
  if (event) event.preventDefault();
  const btn = band === '2g' ? document.getElementById('btn-save-w2') : document.getElementById('btn-save-w5');
  await withButtonLoading(btn, async () => {
    const params = { action: 'wifi_set' };
    if (band === '2g') {
      params.ssid_2g = document.getElementById('wifi-ssid-2g').value.trim();
      params.pass_2g = document.getElementById('wifi-pass-2g').value.trim();
      params.ch_2g = document.getElementById('wifi-ch-2g').value;
      params.bw_2g = document.getElementById('wifi-bw-2g').value;
      params.hide_2g = document.getElementById('wifi-hide-2g').checked ? '1' : '0';
      params.enable_2g = document.getElementById('wifi-enable-2g').checked ? '1' : '0';
    } else {
      params.ssid_5g = document.getElementById('wifi-ssid-5g').value.trim();
      params.pass_5g = document.getElementById('wifi-pass-5g').value.trim();
      params.ch_5g = document.getElementById('wifi-ch-5g').value;
      params.bw_5g = document.getElementById('wifi-bw-5g').value;
      params.hide_5g = document.getElementById('wifi-hide-5g').checked ? '1' : '0';
      params.enable_5g = document.getElementById('wifi-enable-5g').checked ? '1' : '0';
    }

    const res = await apiCall(API_BASE, params, 15000);
    showToast(res.message || `${band.toUpperCase()} Wi-Fi 配置已生效！`, 'success');
    refreshSysInfo();
  });
}

function togglePassVisibility(inputId) {
  const el = document.getElementById(inputId);
  if (el) {
    el.type = el.type === 'password' ? 'text' : 'password';
  }
}

// Connected Clients Management
async function loadClientList() {
  const tbody = document.getElementById('clients-table-body');
  if (!tbody) return;
  try {
    const res = await apiCall(API_BASE, { action: 'client_list' });
    if (res.status === 0 && res.clients) {
      if (res.clients.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 20px;">暂无在线终端设备</td></tr>';
        return;
      }
      tbody.innerHTML = res.clients.map(c => `
        <tr>
          <td style="font-weight: 600; color: var(--primary);">${c.ip}</td>
          <td><code style="font-size: 12px;">${c.mac}</code></td>
          <td>${c.hostname || '局域网设备'}</td>
          <td><span class="brand-badge">${c.interface || 'br0'}</span></td>
          <td><span class="status-badge online" style="font-size: 11px;">在线</span></td>
          <td>
            <button class="btn btn-secondary btn-sm" onclick="pingClient('${c.ip}')">Ping</button>
          </td>
        </tr>
      `).join('');
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="color: var(--danger); padding: 14px;">加载终端列表失败: ${err.message}</td></tr>`;
  }
}

function pingClient(ip) {
  switchTab('tab-runtime');
  const input = document.getElementById('ping-target-input');
  if (input) {
    input.value = ip;
    const btn = document.querySelector("button[onclick='runPingTest(this)']");
    if (btn) runPingTest(btn);
  }
}

// System Operations
async function systemDropCaches(btn) {
  await withButtonLoading(btn, async () => {
    const res = await apiCall(API_BASE, { action: 'system_drop_caches' });
    showToast(res.message || '内存深度释放完成', 'success');
    refreshSysInfo();
  });
}

async function toggleHwnat(btn) {
  await withButtonLoading(btn, async () => {
    const nextState = !currentHwnatState;
    const res = await apiCall(API_BASE, { action: 'system_hwnat_toggle', enable: nextState ? '1' : '0' });
    currentHwnatState = nextState;
    showToast(res.message || '硬件加速状态已更新', 'success');
    btn.textContent = currentHwnatState ? '⚡ 硬件加速: ON' : '⚡ 硬件加速: OFF';
    btn.className = `btn btn-sm ${currentHwnatState ? 'btn-secondary' : 'btn-warning'}`;
  });
}

function confirmReboot() {
  const modal = document.getElementById('modal-reboot');
  if (modal) modal.style.display = 'flex';
}

function closeRebootModal() {
  const modal = document.getElementById('modal-reboot');
  if (modal) modal.style.display = 'none';
}

async function executeReboot() {
  closeRebootModal();
  showToast('重启指令已发送，正在重启路由器...', 'warning');
  try {
    await apiCall(API_BASE, { action: 'system_reboot' });
  } catch (e) {
    // Expected during reboot
  }

  // Show Countdown Overlay
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(15,23,42,0.85);color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:99999;';
  overlay.innerHTML = `
    <div style="font-size: 48px; margin-bottom: 16px;">🔄</div>
    <h2 style="margin-bottom: 12px;">路由器正在重启中</h2>
    <p style="font-size: 15px; color: #94a3b8; margin-bottom: 24px;">请耐心等待网络射频与系统核心初始化恢复</p>
    <div style="font-size: 28px; font-weight: 700; color: #38bdf8;" id="reboot-countdown">55s</div>
  `;
  document.body.appendChild(overlay);

  let seconds = 55;
  const timer = setInterval(() => {
    seconds--;
    const el = document.getElementById('reboot-countdown');
    if (el) el.textContent = `${seconds}s`;
    if (seconds <= 0) {
      clearInterval(timer);
      window.location.reload();
    }
  }, 1000);
}

async function runPingTest(btn) {
  const input = document.getElementById('ping-target-input');
  const viewer = document.getElementById('ping-output-viewer');
  if (!input || !viewer) return;
  const target = input.value.trim() || '223.5.5.5';

  await withButtonLoading(btn, async () => {
    viewer.textContent = `正在向 ${target} 发起 3 次 ICMP Ping 探测...`;
    const res = await apiCall(API_BASE, { action: 'system_ping', target: target }, 15000);
    viewer.textContent = res.output || '探测未返回输出';
  });
}

// Crontab Tasks
async function loadCronTasks() {
  const editor = document.getElementById('crontab-editor');
  if (!editor) return;
  try {
    const res = await apiCall(API_BASE, { action: 'cron_get' });
    if (res.status === 0 && res.crontab !== undefined) {
      editor.value = res.crontab;
    }
  } catch (err) {
    console.warn('Load crontab failed:', err);
  }
}

async function saveCronTasks(btn) {
  const editor = document.getElementById('crontab-editor');
  if (!editor) return;
  await withButtonLoading(btn, async () => {
    const body = new URLSearchParams({
      action: 'cron_set',
      crontab: editor.value
    }).toString();
    const res = await apiCall(API_BASE, {}, 8000, body);
    showToast(res.message || '定时任务已保存', 'success');
  });
}

function addCronPreset(type) {
  const editor = document.getElementById('crontab-editor');
  if (!editor) return;
  const presets = {
    reboot: '0 4 * * * /sbin/reboot',
    drop_caches: '30 * * * * sync && echo 3 > /proc/sys/vm/drop_caches'
  };
  const line = presets[type];
  if (line) {
    editor.value = (editor.value.trim() ? editor.value.trim() + '\n' : '') + line + '\n';
    showToast('已追加计划任务，点击【保存定时任务】生效', 'info');
  }
}

// Python & Entware Actions
async function installEntware(btn) {
  await withButtonLoading(btn, async () => {
    const res = await apiCall(API_BASE, {
      action: 'plugin_call',
      plugin: 'entware_package_mgr',
      cmd: 'bootstrap_entware'
    }, 60000);
    showToast(res.message || 'Entware 部署操作已完成', 'success');
    refreshSysInfo();
  });
}

async function installPython(btn) {
  await withButtonLoading(btn, async () => {
    const res = await apiCall(API_BASE, {
      action: 'plugin_call',
      plugin: 'entware_package_mgr',
      cmd: 'install_python'
    }, 120000);
    showToast(res.message || 'Python 3 运行环境就绪', 'success');
    refreshSysInfo();
  });
}

async function installPkg(btn, pkgName) {
  await withButtonLoading(btn, async () => {
    const res = await apiCall(API_BASE, {
      action: 'plugin_call',
      plugin: 'entware_package_mgr',
      cmd: 'opkg_install',
      args: pkgName
    }, 60000);
    showToast(`软件包 ${pkgName} 安装完成`, 'success');
  });
}

// --- Network Settings Engine ---
let currentOpMode = 0;
let portFwRules = [];

function selectOpMode(mode, userClick = true) {
  currentOpMode = parseInt(mode, 10);
  const card0 = document.getElementById('opmode-card-0');
  const card1 = document.getElementById('opmode-card-1');
  const r0 = document.getElementById('opmode-radio-0');
  const r1 = document.getElementById('opmode-radio-1');

  if (card0 && card1 && r0 && r1) {
    if (currentOpMode === 1) {
      card1.style.border = '2px solid var(--primary)';
      card1.style.background = '#f8fafc';
      card0.style.border = '1px solid var(--border)';
      card0.style.background = '#ffffff';
      r1.checked = true;
      r0.checked = false;
    } else {
      card0.style.border = '2px solid var(--primary)';
      card0.style.background = '#f8fafc';
      card1.style.border = '1px solid var(--border)';
      card1.style.background = '#ffffff';
      r0.checked = true;
      r1.checked = false;
    }
  }
}

async function applyOpMode(btn) {
  if (currentOpMode === 1) {
    if (!confirm('【警告】切换至 AP 桥接模式后：\n1. WAN 接口将直连并入内网 LAN；\n2. 本机的 DHCP 服务与 NAT 转换将被关闭；\n3. 终端将直接从上级主路由器统一获取 IP。\n\n是否确认切换？')) {
      return;
    }
  }
  await withButtonLoading(btn, async () => {
    const res = await apiCall(API_BASE, {
      action: 'network_set_mode',
      mode: currentOpMode
    });
    showToast(res.message || '工作模式已切换', 'success');
    loadNetworkSettings();
  });
}

function toggleDhcpInputs(val) {
  const isEn = val === '1';
  const s = document.getElementById('lan-dhcp-start');
  const e = document.getElementById('lan-dhcp-end');
  const l = document.getElementById('lan-dhcp-lease');
  if (s) s.disabled = !isEn;
  if (e) e.disabled = !isEn;
  if (l) l.disabled = !isEn;
}

function onWanProtoChange(proto) {
  const staticFields = document.getElementById('wan-static-fields');
  const pppoeFields = document.getElementById('wan-pppoe-fields');
  if (staticFields) staticFields.style.display = (proto === 'static') ? 'grid' : 'none';
  if (pppoeFields) pppoeFields.style.display = (proto === 'pppoe') ? 'grid' : 'none';
}

async function loadNetworkSettings() {
  try {
    const res = await apiCall(API_BASE, { action: 'network_get' });
    if (res.status === 0) {
      // 1. Operation Mode
      currentOpMode = res.op_mode || 0;
      selectOpMode(currentOpMode, false);
      const opBadge = document.getElementById('current-opmode-badge');
      if (opBadge) {
        opBadge.textContent = currentOpMode === 1 ? 'AP 桥接模式 (Bridge)' : '网关路由模式 (NAT)';
      }

      // 2. LAN & DHCP
      if (res.lan) {
        if (document.getElementById('lan-ip')) document.getElementById('lan-ip').value = res.lan.ip || '192.168.10.1';
        if (document.getElementById('lan-netmask')) document.getElementById('lan-netmask').value = res.lan.netmask || '255.255.255.0';
        if (document.getElementById('lan-dhcp-enabled')) document.getElementById('lan-dhcp-enabled').value = res.lan.dhcp_enabled ? '1' : '0';
        if (document.getElementById('lan-dhcp-start')) document.getElementById('lan-dhcp-start').value = res.lan.dhcp_start || '192.168.10.2';
        if (document.getElementById('lan-dhcp-end')) document.getElementById('lan-dhcp-end').value = res.lan.dhcp_end || '192.168.10.254';
        if (document.getElementById('lan-dhcp-lease')) document.getElementById('lan-dhcp-lease').value = res.lan.dhcp_lease || 86400;
        if (document.getElementById('lan-dns1')) document.getElementById('lan-dns1').value = res.lan.dns1 || '';
        if (document.getElementById('lan-dns2')) document.getElementById('lan-dns2').value = res.lan.dns2 || '';
        toggleDhcpInputs(res.lan.dhcp_enabled ? '1' : '0');
      }

      // 3. WAN
      if (res.wan) {
        const protoSelect = document.getElementById('wan-proto-select');
        if (protoSelect) {
          protoSelect.value = res.wan.proto || 'dhcp';
          onWanProtoChange(protoSelect.value);
        }
        const wanBadge = document.getElementById('wan-current-ip-badge');
        if (wanBadge) {
          wanBadge.textContent = res.wan.ip ? `在网: ${res.wan.ip}` : '未连接上行网线';
          wanBadge.className = `brand-badge ${res.wan.ip ? 'online' : ''}`;
        }
        if (document.getElementById('wan-mtu')) document.getElementById('wan-mtu').value = res.wan.mtu || 1500;
        if (document.getElementById('wan-mac')) document.getElementById('wan-mac').value = res.wan.mac || '';
        if (document.getElementById('wan-pppoe-user')) {
          document.getElementById('wan-pppoe-user').value = res.wan.pppoe_user || '';
        }
      }

      // 4. DMZ & UPnP
      if (res.nat) {
        const dmzCheck = document.getElementById('dmz-enabled-toggle');
        const dmzInput = document.getElementById('dmz-ip-input');
        if (dmzCheck) dmzCheck.checked = !!res.nat.dmz_enabled;
        if (dmzInput) {
          dmzInput.value = res.nat.dmz_ip || '';
          dmzInput.disabled = !res.nat.dmz_enabled;
        }
        const upnpCheck = document.getElementById('upnp-enabled-toggle');
        if (upnpCheck) upnpCheck.checked = !!res.nat.upnp_enabled;
      }
    }
  } catch (err) {
    console.warn('loadNetworkSettings error:', err);
    showToast('加载网络设置失败: ' + err.message, 'error');
  }
  loadPortForwardRules();
}

async function saveLanConfig(event) {
  event.preventDefault();
  const btn = event.target.querySelector('button[type="submit"]');
  await withButtonLoading(btn, async () => {
    const params = {
      action: 'network_set_lan',
      ip: document.getElementById('lan-ip').value.trim(),
      netmask: document.getElementById('lan-netmask').value.trim(),
      dhcp_enable: document.getElementById('lan-dhcp-enabled').value,
      dhcp_start: document.getElementById('lan-dhcp-start').value.trim(),
      dhcp_end: document.getElementById('lan-dhcp-end').value.trim(),
      dhcp_lease: document.getElementById('lan-dhcp-lease').value.trim(),
      dns1: document.getElementById('lan-dns1').value.trim(),
      dns2: document.getElementById('lan-dns2').value.trim()
    };
    const res = await apiCall(API_BASE, params);
    showToast(res.message || '局域网参数已保存', 'success');
  });
}

async function saveWanConfig(event) {
  event.preventDefault();
  const btn = event.target.querySelector('button[type="submit"]');
  await withButtonLoading(btn, async () => {
    const proto = document.getElementById('wan-proto-select').value;
    const params = {
      action: 'network_set_wan',
      proto: proto,
      mtu: document.getElementById('wan-mtu').value.trim(),
      mac: document.getElementById('wan-mac').value.trim()
    };
    if (proto === 'static') {
      params.ip = document.getElementById('wan-static-ip').value.trim();
      params.netmask = document.getElementById('wan-static-mask').value.trim();
      params.gateway = document.getElementById('wan-static-gw').value.trim();
      params.dns1 = document.getElementById('wan-static-dns1').value.trim();
    } else if (proto === 'pppoe') {
      params.pppoe_user = document.getElementById('wan-pppoe-user').value.trim();
      params.pppoe_pass = document.getElementById('wan-pppoe-pass').value.trim();
    }
    const res = await apiCall(API_BASE, params);
    showToast(res.message || 'WAN 设置已应用', 'success');
  });
}

function toggleAddPortFwDrawer() {
  const d = document.getElementById('drawer-add-portfw');
  if (d) d.style.display = d.style.display === 'none' ? 'block' : 'none';
}

async function loadPortForwardRules() {
  try {
    const res = await apiCall(API_BASE, { action: 'portfw_get' });
    portFwRules = (res && res.rules) ? res.rules : [];
    renderPortFwTable();
  } catch (e) {
    portFwRules = [];
    renderPortFwTable();
  }
}

function renderPortFwTable() {
  const tbody = document.getElementById('portfw-rules-body');
  if (!tbody) return;
  if (!portFwRules || portFwRules.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 20px;">暂无端口转发规则</td></tr>';
    return;
  }
  tbody.innerHTML = portFwRules.map((r, i) => `
    <tr style="border-bottom: 1px solid var(--border);">
      <td style="padding: 10px 8px; font-weight: 600;">${r.name || 'Rule'}</td>
      <td style="padding: 10px 8px;"><span class="brand-badge">${(r.proto || 'TCP').toUpperCase()}</span></td>
      <td style="padding: 10px 8px; font-family: monospace;">${r.ext_port}</td>
      <td style="padding: 10px 8px; font-family: monospace;">${r.int_ip}</td>
      <td style="padding: 10px 8px; font-family: monospace;">${r.int_port}</td>
      <td style="padding: 10px 8px;"><span style="color: var(--success); font-weight: 500;">生效中</span></td>
      <td style="padding: 10px 8px; text-align: right;">
        <button class="btn btn-danger btn-sm" onclick="deletePortFwRule(${i})">删除</button>
      </td>
    </tr>
  `).join('');
}

async function addPortFwRule(event) {
  event.preventDefault();
  const rule = {
    name: document.getElementById('pf-name').value.trim(),
    proto: document.getElementById('pf-proto').value,
    ext_port: parseInt(document.getElementById('pf-ext-port').value, 10),
    int_ip: document.getElementById('pf-int-ip').value.trim(),
    int_port: parseInt(document.getElementById('pf-int-port').value, 10),
    enabled: true
  };
  portFwRules.push(rule);
  await savePortForwardRules();
  toggleAddPortFwDrawer();
}

async function deletePortFwRule(index) {
  if (!confirm('确认删除该端口转发规则？')) return;
  portFwRules.splice(index, 1);
  await savePortForwardRules();
}

async function savePortForwardRules() {
  const jsonStr = JSON.stringify({ status: 0, rules: portFwRules });
  const res = await apiCall(API_BASE, { action: 'portfw_set' }, 8000, `rules=${encodeURIComponent(jsonStr)}`);
  showToast(res.message || '端口转发已更新', 'success');
  renderPortFwTable();
}

function toggleDmzInput(checked) {
  const input = document.getElementById('dmz-ip-input');
  if (input) input.disabled = !checked;
}

async function saveDmzConfig(btn) {
  await withButtonLoading(btn, async () => {
    const isEn = document.getElementById('dmz-enabled-toggle').checked ? '1' : '0';
    const ip = document.getElementById('dmz-ip-input').value.trim();
    const res = await apiCall(API_BASE, {
      action: 'dmz_set',
      enable: isEn,
      ip: ip
    });
    showToast(res.message || 'DMZ 设置已保存', 'success');
  });
}

async function saveUpnpConfig(checkbox) {
  const isEn = checkbox.checked ? '1' : '0';
  try {
    const res = await apiCall(API_BASE, {
      action: 'dmz_set',
      upnp: isEn
    });
    showToast(res.message || 'UPnP 状态已变更', 'success');
  } catch (e) {
    checkbox.checked = !checkbox.checked;
    showToast('更新 UPnP 失败: ' + e.message, 'error');
  }
}

async function saveAdminPassword(event) {
  event.preventDefault();
  const p1 = document.getElementById('sys-admin-pass1').value;
  const p2 = document.getElementById('sys-admin-pass2').value;
  if (!p1 || p1.length < 5) {
    showToast('新密码长度不能少于 5 位字符', 'warning');
    return;
  }
  if (p1 !== p2) {
    showToast('两次输入的新密码不一致，请核对', 'error');
    return;
  }
  const btn = event.target.querySelector('button[type="submit"]');
  await withButtonLoading(btn, async () => {
    const res = await apiCall(API_BASE, {
      action: 'password_set',
      password: p1
    });
    if (res.status === 0) {
      showToast('管理员密码已成功修改！', 'success');
      document.getElementById('sys-admin-pass1').value = '';
      document.getElementById('sys-admin-pass2').value = '';
    } else {
      showToast(res.error || '密码修改失败', 'error');
    }
  });
}

// AdBlock DNS Actions
async function loadAdblockRules() {
  const editor = document.getElementById('adblock-rules-editor');
  if (!editor) return;
  try {
    const res = await apiCall(API_BASE, {
      action: 'plugin_call',
      plugin: 'hosts_adblock_dns',
      cmd: 'get_rules'
    });
    if (res.status === 0) {
      editor.value = res.rules || '';
    }
  } catch (err) {
    console.warn('Load AdBlock rules failed:', err);
  }
}

async function saveAdblockRules(btn) {
  const editor = document.getElementById('adblock-rules-editor');
  if (!editor) return;
  await withButtonLoading(btn, async () => {
    const body = new URLSearchParams({
      action: 'plugin_call',
      plugin: 'hosts_adblock_dns',
      cmd: 'set_rules',
      rules: editor.value
    }).toString();
    const res = await apiCall(API_BASE, {}, 8000, body);
    showToast(res.message || 'DNS 去广告规则已更新并重新加载', 'success');
  });
}

// UserScript Actions
async function loadUserScript() {
  const editor = document.getElementById('userscript-editor');
  if (!editor) return;
  try {
    const res = await apiCall(API_BASE, {
      action: 'plugin_call',
      plugin: 'custom_userscript',
      cmd: 'get_script'
    });
    if (res.status === 0) {
      editor.value = res.script || '';
    }
  } catch (err) {
    console.warn('Load UserScript failed:', err);
  }
}

async function saveUserScript(btn) {
  const editor = document.getElementById('userscript-editor');
  if (!editor) return;
  await withButtonLoading(btn, async () => {
    const body = new URLSearchParams({
      action: 'plugin_call',
      plugin: 'custom_userscript',
      cmd: 'set_script',
      script: editor.value
    }).toString();
    const res = await apiCall(API_BASE, {}, 8000, body);
    showToast(res.message || '自定义 Shell 脚本已保存', 'success');
  });
}

async function runUserScriptNow(btn) {
  await withButtonLoading(btn, async () => {
    const res = await apiCall(API_BASE, {
      action: 'plugin_call',
      plugin: 'custom_userscript',
      cmd: 'run_now'
    }, 15000);
    showToast(res.message || '脚本后台执行成功', 'success');
  });
}

// Live Logs Viewer
async function fetchLiveLogs() {
  const viewer = document.getElementById('live-log-viewer');
  if (!viewer) return;
  try {
    const res = await apiCall(API_BASE, { action: 'system_logs' });
    if (res.status === 0 && res.log) {
      viewer.textContent = res.log;
      viewer.scrollTop = viewer.scrollHeight;
    } else {
      viewer.textContent = '暂无运行日志输出';
    }
  } catch (err) {
    viewer.textContent = `读取运行日志失败: ${err.message}`;
  }
}

function toggleLogAutoRefresh() {
  isLogAutoRefresh = !isLogAutoRefresh;
  const btn = document.getElementById('btn-toggle-log');
  if (btn) {
    btn.textContent = isLogAutoRefresh ? '暂停轮询' : '恢复轮询';
  }
}

// Initialization on DOM Ready
document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  refreshSysInfo();
  refreshPlugins();

  // Periodic system poll
  setInterval(refreshSysInfo, 10000);

  // Periodic log poll
  logPollTimer = setInterval(() => {
    if (isLogAutoRefresh) {
      const activeTab = document.querySelector('.nav-tab.active');
      if (activeTab && activeTab.dataset.target === 'tab-logs') {
        fetchLiveLogs();
      }
    }
  }, 4000);
});
