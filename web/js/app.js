/**
 * Ripple-mod - Unified Modern Frontend Controller
 */

const API_BASE = '/api.cgi';
let isLogAutoRefresh = true;
let logPollTimer = null;

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

// Robust Fetch with Timeout and Error Handling
async function apiCall(endpoint, params = {}, timeoutMs = 8000) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  const query = new URLSearchParams(params).toString();
  const url = `${endpoint}?${query}`;

  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: { 'Accept': 'application/json' },
      signal: controller.signal
    });
    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();
    return data;
  } catch (err) {
    clearTimeout(timeoutId);
    if (err.name === 'AbortError') {
      throw new Error('请求超时 (8s)，设备未响应');
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
      document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      tab.classList.add('active');
      const targetContent = document.getElementById(targetId);
      if (targetContent) targetContent.classList.add('active');

      // Trigger lazy load
      if (targetId === 'tab-adblock') loadAdblockRules();
      if (targetId === 'tab-userscript') loadUserScript();
      if (targetId === 'tab-logs') fetchLiveLogs();
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
  if (targetId === 'tab-adblock') loadAdblockRules();
  if (targetId === 'tab-userscript') loadUserScript();
  if (targetId === 'tab-logs') fetchLiveLogs();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function openPluginGui(id) {
  const tabMap = {
    'hosts_adblock_dns': 'tab-adblock',
    'custom_userscript': 'tab-userscript',
    'entware_package_mgr': 'tab-runtime'
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
          if (elW5Ch) elW5Ch.textContent = `信道 ${s.wifi.wifi_5g.channel} (160 MHz)`;
        }
        if (s.wifi.wifi_2g && s.wifi.wifi_2g.ssid) {
          const elW2Ssid = document.getElementById('wifi2-ssid');
          const elW2Ch = document.getElementById('wifi2-ch');
          if (elW2Ssid) elW2Ssid.textContent = s.wifi.wifi_2g.ssid;
          if (elW2Ch) elW2Ch.textContent = `信道 ${s.wifi.wifi_2g.channel} (40 MHz)`;
        }
      }

      // Network & Clients
      const elWanIp = document.getElementById('sys-wan-ip');
      if (elWanIp) elWanIp.textContent = (s.network && s.network.wan_ip) ? s.network.wan_ip : (s.wan_ip || '未分配');
      const elLanIp = document.getElementById('sys-lan-ip');
      if (elLanIp && s.network) elLanIp.textContent = s.network.lan_ip || '192.168.10.1';
      const elLanClients = document.getElementById('sys-lan-clients');
      if (elLanClients && s.network) elLanClients.textContent = `${s.network.lan_clients || 1} 台`;

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
                ⚙️ 打开管理面板
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

// Python & Entware Actions
async function installEntware(btn) {
  await withButtonLoading(btn, async () => {
    const res = await apiCall(API_BASE, {
      action: 'plugin_call',
      plugin: 'entware_package_mgr',
      cmd: 'bootstrap_entware'
    }, 60000);
    showToast(res.message || 'Entware 安装完成', 'success');
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

// AdBlock DNS Actions
async function loadAdblockRules() {
  try {
    const res = await apiCall(API_BASE, {
      action: 'plugin_call',
      plugin: 'hosts_adblock_dns',
      cmd: 'get_rules'
    });
    if (res.status === 0) {
      document.getElementById('adblock-rules-editor').value = res.rules || '';
    }
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function saveAdblockRules(btn) {
  await withButtonLoading(btn, async () => {
    const rules = document.getElementById('adblock-rules-editor').value;
    const res = await apiCall(API_BASE, {
      action: 'plugin_call',
      plugin: 'hosts_adblock_dns',
      cmd: 'set_rules',
      args: `rules=${encodeURIComponent(rules)}`
    });
    showToast(res.message || '规则已应用生效', 'success');
  });
}

// Custom UserScript Actions
async function loadUserScript() {
  try {
    const res = await apiCall(API_BASE, {
      action: 'plugin_call',
      plugin: 'custom_userscript',
      cmd: 'get_script'
    });
    if (res.status === 0) {
      document.getElementById('userscript-editor').value = res.script || '';
    }
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function saveUserScript(btn) {
  await withButtonLoading(btn, async () => {
    const script = document.getElementById('userscript-editor').value;
    const res = await apiCall(API_BASE, {
      action: 'plugin_call',
      plugin: 'custom_userscript',
      cmd: 'set_script',
      args: `script=${encodeURIComponent(script)}`
    });
    showToast(res.message || '自定义脚本已保存', 'success');
  });
}

async function runUserScriptNow(btn) {
  await withButtonLoading(btn, async () => {
    const res = await apiCall(API_BASE, {
      action: 'plugin_call',
      plugin: 'custom_userscript',
      cmd: 'run_now'
    });
    showToast(res.output || '试运行完成', res.status === 0 ? 'success' : 'info');
  });
}

// Live Logs
async function fetchLiveLogs() {
  const viewer = document.getElementById('live-log-viewer');
  if (!viewer) return;
  try {
    const res = await apiCall(API_BASE, {
      action: 'plugin_call',
      plugin: 'custom_userscript',
      cmd: 'get_logs',
      args: '80'
    });
    if (res.status === 0 && res.logs) {
      viewer.textContent = res.logs;
      viewer.scrollTop = viewer.scrollHeight;
    }
  } catch (err) {
    viewer.textContent = `读取日志异常: ${err.message}`;
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
