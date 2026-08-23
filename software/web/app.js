'use strict';

const API_BASE = '';  // Same-origin: served by horalscanner_api.py

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------
class HoralScannerAPI {
    constructor(baseURL) {
        this.baseURL = baseURL;
    }

    async request(endpoint, method = 'GET', data = null) {
        const options = { method, headers: { 'Content-Type': 'application/json' } };
        if (data !== null) options.body = JSON.stringify(data);
        const response = await fetch(`${this.baseURL}${endpoint}`, options);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
    }

    getStatus()                     { return this.request('/api/status'); }
    home()                          { return this.request('/api/home', 'POST'); }
    moveAxis(axis, mm, speed)       { return this.request(`/api/move/${axis}`, 'POST', { mm, speed }); }
    move(x, y, z, speed)            { return this.request('/api/move', 'POST', { x, y, z, speed }); }
    setLaser(left, right)           { return this.request('/api/laser', 'POST', { left, right }); }
    captureFrame()                  { return this.request('/api/camera/capture', 'POST'); }
    readLidar()                     { return this.request('/api/lidar'); }
    setLed(r, g, b)                 { return this.request('/api/led', 'POST', { r, g, b }); }
    ledOff()                        { return this.request('/api/led/off', 'POST'); }
    setFan(fan1, fan2)              { return this.request('/api/fan', 'POST', { fan1, fan2 }); }
    scanStep(x_mm, sync_token)      { return this.request('/api/scan/step', 'POST', { x_mm, sync_token }); }
    scanStart()                     { return this.request('/api/scan/start', 'POST'); }
    scanStop()                      { return this.request('/api/scan/stop', 'POST'); }
    scanProgress()                  { return this.request('/api/scan/progress'); }
}

const api = new HoralScannerAPI(API_BASE);

// ---------------------------------------------------------------------------
// Scan point cloud for live preview
// ---------------------------------------------------------------------------
const scanPoints = [];

// ---------------------------------------------------------------------------
// Logging
// ---------------------------------------------------------------------------
function log(msg, level = 'info') {
    const el = document.getElementById('log');
    const ts = new Date().toLocaleTimeString();
    const div = document.createElement('div');
    div.className = `log-line log-${level}`;
    div.textContent = `[${ts}] ${msg}`;
    el.prepend(div);
    if (el.children.length > 200) el.removeChild(el.lastChild);
}

function clearLog() {
    document.getElementById('log').innerHTML = '';
}

// ---------------------------------------------------------------------------
// Status polling
// ---------------------------------------------------------------------------
async function pollStatus() {
    try {
        const s = await api.getStatus();

        // Connection badge
        const badge = document.getElementById('connection-status');
        badge.textContent = '⬤ Connecté';
        badge.className = 'status-badge connected';

        // Position
        const p = s.position || {};
        document.getElementById('pos-display').textContent =
            `X:${(p.x||0).toFixed(1)}  Y:${(p.y||0).toFixed(1)}  Z:${(p.z||0).toFixed(1)} mm`;
        document.getElementById('telem-x').textContent = `${(p.x||0).toFixed(1)} mm`;
        document.getElementById('telem-y').textContent = `${(p.y||0).toFixed(1)} mm`;
        document.getElementById('telem-z').textContent = `${(p.z||0).toFixed(1)} mm`;

        // LIDAR
        const lidar = s.last_lidar_mm;
        document.getElementById('telem-lidar').textContent =
            lidar != null ? `${lidar.toFixed(1)} mm` : '— mm';

        // Temperature
        const temp = s.temperature;
        document.getElementById('telem-temp').textContent =
            temp != null ? `${temp.toFixed(1)} °C` : '— °C';
        document.getElementById('temp-display').textContent =
            temp != null ? `${temp.toFixed(1)} °C` : '— °C';

        // Scan state
        document.getElementById('telem-scan').textContent =
            s.scan_active ? 'Actif' : 'Non';

        // Laser checkboxes (sync from server state without firing onchange)
        if (s.lasers) {
            setCheckboxSilent('laser-left', s.lasers.left);
            setCheckboxSilent('laser-right', s.lasers.right);
        }

        // Fan checkboxes
        if (s.fans) {
            setCheckboxSilent('fan1', s.fans.fan1);
            setCheckboxSilent('fan2', s.fans.fan2);
        }

        // LED sliders
        if (s.led) {
            document.getElementById('led-r').value = s.led.r;
            document.getElementById('led-g').value = s.led.g;
            document.getElementById('led-b').value = s.led.b;
            document.getElementById('led-r-val').textContent = s.led.r;
            document.getElementById('led-g-val').textContent = s.led.g;
            document.getElementById('led-b-val').textContent = s.led.b;
            updateLedPreview();
        }

    } catch {
        const badge = document.getElementById('connection-status');
        badge.textContent = '⬤ Déconnecté';
        badge.className = 'status-badge disconnected';
    }
}

function setCheckboxSilent(id, value) {
    const el = document.getElementById(id);
    if (el) el.checked = !!value;
}

// ---------------------------------------------------------------------------
// Axis movement
// ---------------------------------------------------------------------------
async function moveAxis(axis) {
    const inputId = `pos-${axis}`;
    const mm = parseFloat(document.getElementById(inputId).value) || 0;
    try {
        await api.moveAxis(axis, mm);
        log(`↗ Axe ${axis.toUpperCase()} → ${mm} mm`);
    } catch (e) {
        log(`Erreur déplacement ${axis}: ${e.message}`, 'error');
    }
}

async function homeAxes() {
    try {
        await api.home();
        log('⌂ Homing Y → 0');
    } catch (e) {
        log(`Erreur homing: ${e.message}`, 'error');
    }
}

// ---------------------------------------------------------------------------
// Lasers
// ---------------------------------------------------------------------------
async function setLaser() {
    const left = document.getElementById('laser-left').checked;
    const right = document.getElementById('laser-right').checked;
    try {
        await api.setLaser(left, right);
        log(`🔴 Lasers G:${left ? 'ON' : 'OFF'} D:${right ? 'ON' : 'OFF'}`);
    } catch (e) {
        log(`Erreur laser: ${e.message}`, 'error');
    }
}

// ---------------------------------------------------------------------------
// LED RGB
// ---------------------------------------------------------------------------
function updateLedPreview() {
    const r = document.getElementById('led-r').value;
    const g = document.getElementById('led-g').value;
    const b = document.getElementById('led-b').value;
    document.getElementById('led-r-val').textContent = r;
    document.getElementById('led-g-val').textContent = g;
    document.getElementById('led-b-val').textContent = b;
    document.getElementById('led-preview').style.backgroundColor = `rgb(${r},${g},${b})`;
}

async function applyLed() {
    const r = parseInt(document.getElementById('led-r').value);
    const g = parseInt(document.getElementById('led-g').value);
    const b = parseInt(document.getElementById('led-b').value);
    try {
        await api.setLed(r, g, b);
        log(`💡 LED rgb(${r},${g},${b})`);
    } catch (e) {
        log(`Erreur LED: ${e.message}`, 'error');
    }
}

async function ledOff() {
    try {
        await api.ledOff();
        document.getElementById('led-r').value = 0;
        document.getElementById('led-g').value = 0;
        document.getElementById('led-b').value = 0;
        updateLedPreview();
        log('💡 LED éteinte');
    } catch (e) {
        log(`Erreur LED: ${e.message}`, 'error');
    }
}

// ---------------------------------------------------------------------------
// Fans
// ---------------------------------------------------------------------------
async function setFan() {
    const fan1 = document.getElementById('fan1').checked;
    const fan2 = document.getElementById('fan2').checked;
    try {
        await api.setFan(fan1, fan2);
        log(`🌀 Fans F1:${fan1 ? 'ON' : 'OFF'} F2:${fan2 ? 'ON' : 'OFF'}`);
    } catch (e) {
        log(`Erreur fan: ${e.message}`, 'error');
    }
}

// ---------------------------------------------------------------------------
// Camera / LIDAR
// ---------------------------------------------------------------------------
async function captureFrame() {
    try {
        const f = await api.captureFrame();
        log(`📷 Capture: LIDAR ${f.lidar_distance_mm != null ? f.lidar_distance_mm.toFixed(1) + ' mm' : 'N/A'}`);
    } catch (e) {
        log(`Erreur capture: ${e.message}`, 'error');
    }
}

async function readLidar() {
    try {
        const f = await api.readLidar();
        const d = f.lidar_distance_mm;
        document.getElementById('telem-lidar').textContent = d != null ? `${d.toFixed(1)} mm` : '— mm';
        log(`📡 LIDAR: ${d != null ? d.toFixed(1) + ' mm' : 'N/A'}`);
    } catch (e) {
        log(`Erreur LIDAR: ${e.message}`, 'error');
    }
}

// ---------------------------------------------------------------------------
// Scan acquisition
// ---------------------------------------------------------------------------
async function singleStep() {
    const x_mm = parseFloat(document.getElementById('scan-x-step').value) || 5;
    const sync_token = document.getElementById('scan-token').value || 'step0';
    try {
        const res = await api.scanStep(x_mm, sync_token);
        log(`↠ Pas scan: x=${res.x_mm} mm LIDAR=${res.lidar_distance_mm ?? 'N/A'}`);
        if (res.lidar_distance_mm != null) {
            scanPoints.push({ x: res.x_mm, d: res.lidar_distance_mm });
            drawScanPreview();
        }
    } catch (e) {
        log(`Erreur pas scan: ${e.message}`, 'error');
    }
}

async function startScan() {
    try {
        await api.scanStart();
        document.getElementById('btn-scan-start').disabled = true;
        document.getElementById('btn-scan-stop').disabled = false;
        document.getElementById('scan-progress-container').style.display = 'block';
        scanPoints.length = 0;
        drawScanPreview();
        log('▶ Scan démarré');
    } catch (e) {
        log(`Erreur démarrage scan: ${e.message}`, 'error');
    }
}

async function stopScan() {
    try {
        await api.scanStop();
        document.getElementById('btn-scan-start').disabled = false;
        document.getElementById('btn-scan-stop').disabled = true;
        log('■ Scan arrêté');
    } catch (e) {
        log(`Erreur arrêt scan: ${e.message}`, 'error');
    }
}

// ---------------------------------------------------------------------------
// Scan canvas preview
// ---------------------------------------------------------------------------
function drawScanPreview() {
    const canvas = document.getElementById('scan-canvas');
    const ctx = canvas.getContext('2d');
    const W = canvas.width;
    const H = canvas.height;

    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#0d0d0d';
    ctx.fillRect(0, 0, W, H);

    if (scanPoints.length === 0) {
        ctx.fillStyle = '#444';
        ctx.font = '14px monospace';
        ctx.textAlign = 'center';
        ctx.fillText('Aucun point de scan — lancez une acquisition', W / 2, H / 2);
        return;
    }

    const xMax = 210;
    const dMax = 1000;

    ctx.strokeStyle = '#00e5ff';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    scanPoints.forEach((pt, i) => {
        const px = (pt.x / xMax) * (W - 20) + 10;
        const py = H - ((pt.d / dMax) * (H - 20) + 10);
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
    });
    ctx.stroke();

    ctx.fillStyle = '#00e5ff';
    scanPoints.forEach(pt => {
        const px = (pt.x / xMax) * (W - 20) + 10;
        const py = H - ((pt.d / dMax) * (H - 20) + 10);
        ctx.beginPath();
        ctx.arc(px, py, 2.5, 0, 2 * Math.PI);
        ctx.fill();
    });
}

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    updateLedPreview();
    drawScanPreview();
    pollStatus();
    setInterval(pollStatus, 2000);
    log('✓ HoralScanner UI prête');
});
