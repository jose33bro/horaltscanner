// ─────────────────────────────────────────────
// HoralScanner PRO – Main application
// ─────────────────────────────────────────────

const API_BASE_DEFAULT = window.location.origin;

// ── API helper ────────────────────────────────
class HoralAPI {
    constructor(baseURL) {
        this.baseURL = baseURL.replace(/\/$/, '');
    }

    async _fetch(endpoint, method = 'GET', body = null) {
        const opts = { method, headers: { 'Content-Type': 'application/json' } };
        if (body) opts.body = JSON.stringify(body);
        const r = await fetch(this.baseURL + endpoint, opts);
        if (!r.ok) {
            const err = await r.json().catch(() => ({ error: r.statusText }));
            throw err;
        }
        return r.json();
    }

    get(ep) { return this._fetch(ep); }
    post(ep, body) { return this._fetch(ep, 'POST', body || {}); }
}

// ── Toast notifications ───────────────────────
function showToast(msg, type = 'info') {
    const c = document.getElementById('toast-container');
    const t = document.createElement('div');
    t.className = `toast toast-${type}`;
    t.textContent = msg;
    c.appendChild(t);
    setTimeout(() => t.classList.add('show'), 10);
    setTimeout(() => { t.classList.remove('show'); setTimeout(() => t.remove(), 300); }, 3500);
}

// ── Tab switching ─────────────────────────────
let activeTab = 'scanner';
const componentMap = {};

function switchTab(name) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + name));
    activeTab = name;
    const comp = componentMap[name];
    if (comp && comp.init && !comp._initialized) {
        comp.init();
        comp._initialized = true;
    }
}
window.switchTab = switchTab;

// ── Init ──────────────────────────────────────
let api;
let scannerComp, viewer3dComp, slicerComp, queueComp, settingsComp;

function initApp() {
    api = new HoralAPI(API_BASE_DEFAULT);

    // Instantiate components
    scannerComp = new ScannerComponent(api);
    viewer3dComp = new Viewer3DComponent(api);
    slicerComp = new SlicerComponent(api);
    queueComp = new QueueComponent(api);
    settingsComp = new SettingsComponent(api);

    window.scannerComp = scannerComp;
    window.viewer3dComp = viewer3dComp;
    window.slicerComp = slicerComp;
    window.queueComp = queueComp;
    window.settingsComp = settingsComp;

    componentMap['scanner'] = scannerComp;
    componentMap['viewer3d'] = viewer3dComp;
    componentMap['slicer'] = slicerComp;
    componentMap['queue'] = queueComp;
    componentMap['settings'] = settingsComp;

    // Render all panels
    document.getElementById('tab-scanner').innerHTML = scannerComp.render();
    document.getElementById('tab-viewer3d').innerHTML = viewer3dComp.render();
    document.getElementById('tab-slicer').innerHTML = slicerComp.render();
    document.getElementById('tab-queue').innerHTML = queueComp.render();
    document.getElementById('tab-settings').innerHTML = settingsComp.render();

    // Tab click listeners
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    // Init active component
    scannerComp.init();
    scannerComp._initialized = true;

    // Poll system status
    pollStatus();
    setInterval(pollStatus, 5000);
}

async function pollStatus() {
    try {
        const s = await api.get('/api/status');
        const badge = document.getElementById('conn-status');
        if (badge) {
            if (s.klipper_connected) {
                badge.textContent = '✅ Klipper connecté';
                badge.className = 'conn-badge conn-ok';
            } else {
                badge.textContent = '⚠ Klipper déconnecté';
                badge.className = 'conn-badge conn-warn';
            }
        }
    } catch (e) {
        const badge = document.getElementById('conn-status');
        if (badge) {
            badge.textContent = '❌ API hors ligne';
            badge.className = 'conn-badge conn-error';
        }
    }
}

document.addEventListener('DOMContentLoaded', initApp);
