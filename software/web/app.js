/**
 * HoralScanner PRO – Main Orchestrator
 */

const App = (() => {
  // -----------------------------------------------------------------------
  // Tab navigation
  // -----------------------------------------------------------------------
  function _initTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const target = btn.dataset.tab;
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('tab-' + target)?.classList.add('active');

        // Lazy-init components on first visit
        if (target === 'viewer' && !_viewerInited) {
          Viewer3D.init('viewer3d-container');
          _viewerInited = true;
        }
      });
    });
  }

  let _viewerInited = false;
  let _scanTimer = null;
  let _scanStart = null;

  // -----------------------------------------------------------------------
  // Status polling
  // -----------------------------------------------------------------------
  function _pollStatus() {
    fetch('/api/status')
      .then(r => r.json())
      .then(data => {
        const dot  = document.getElementById('status-dot');
        const text = document.getElementById('status-text');
        if (dot)  { dot.className  = 'status-dot ' + (data.ok ? 'online' : 'offline'); }
        if (text) { text.textContent = data.ok ? `Online – ${data.temperature_c ?? '?'} °C` : 'API offline'; }
      })
      .catch(() => {
        const dot = document.getElementById('status-dot');
        if (dot) dot.className = 'status-dot offline';
        const text = document.getElementById('status-text');
        if (text) text.textContent = 'API unreachable';
      });
  }

  // -----------------------------------------------------------------------
  // Scan control
  // -----------------------------------------------------------------------
  function startScan() {
    fetch('/api/scan/start', { method: 'POST' }).then(() => {
      document.getElementById('btn-scan-start')?.setAttribute('disabled', '');
      document.getElementById('btn-scan-stop')?.removeAttribute('disabled');
      _scanStart = Date.now();
      _scanTimer = setInterval(_updateScanStats, 1000);
    });
  }

  function stopScan() {
    fetch('/api/scan/stop', { method: 'POST' }).then(() => {
      document.getElementById('btn-scan-start')?.removeAttribute('disabled');
      document.getElementById('btn-scan-stop')?.setAttribute('disabled', '');
      clearInterval(_scanTimer);
      _scanTimer = null;
    });
  }

  function _updateScanStats() {
    fetch('/api/scan/status')
      .then(r => r.json())
      .then(d => {
        _setText('stat-points',  d.points ?? 0);
        const elapsed = d.elapsed_s ?? 0;
        const mm = Math.floor(elapsed / 60).toString().padStart(2, '0');
        const ss = Math.floor(elapsed % 60).toString().padStart(2, '0');
        _setText('stat-time', `${mm}:${ss}`);
        _setText('stat-quality', d.quality != null ? `${d.quality.toFixed(1)} %` : '--');
      });
  }

  // -----------------------------------------------------------------------
  // Reconstruction + export
  // -----------------------------------------------------------------------
  function reconstruct() {
    _setText('stat-quality', 'Reconstructing…');
    fetch('/api/model/reconstruct')
      .then(r => r.json())
      .then(d => {
        if (d.ok) {
          _setText('stat-quality', '✅ Model ready');
          // Show in 3D viewer if already initialised
          if (_viewerInited) {
            fetch('/api/model/current?format=stl')
              .then(r => r.arrayBuffer())
              .then(buf => Viewer3D.showSTL(buf));
          }
        } else {
          _setText('stat-quality', `❌ ${d.error}`);
        }
      });
  }

  function exportModel(format) {
    const a = document.createElement('a');
    a.href = `/api/model/current?format=${format}`;
    a.download = `model.${format}`;
    a.click();
  }

  // -----------------------------------------------------------------------
  // Movement
  // -----------------------------------------------------------------------
  function moveAxis(axis) {
    const mm = parseFloat(document.getElementById(`move-${axis}-mm`)?.value || '10');
    fetch(`/api/move/${axis}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mm }),
    });
  }

  function rotate() {
    const deg = parseFloat(document.getElementById('rotate-deg')?.value || '10');
    fetch('/api/rotate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ degrees: deg }),
    });
  }

  function home(target) {
    fetch(`/api/home/${target}`, { method: 'POST' });
  }

  // -----------------------------------------------------------------------
  // Laser
  // -----------------------------------------------------------------------
  function laser(side, state) {
    fetch(`/api/laser/${side}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ state }),
    });
  }

  // -----------------------------------------------------------------------
  // LED
  // -----------------------------------------------------------------------
  function setLED() {
    const r = parseInt(document.getElementById('led-r')?.value || '0', 10);
    const g = parseInt(document.getElementById('led-g')?.value || '0', 10);
    const b = parseInt(document.getElementById('led-b')?.value || '0', 10);
    const preview = document.getElementById('led-preview');
    if (preview) preview.style.background = `rgb(${r},${g},${b})`;
    fetch('/api/led/color', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ r, g, b }),
    });
  }

  // -----------------------------------------------------------------------
  // Camera capture
  // -----------------------------------------------------------------------
  function captureFrame(cam) {
    fetch(`/api/camera/${cam}`, { method: 'POST' })
      .then(r => r.json())
      .then(d => {
        if (d.jpeg_b64) {
          const img = document.getElementById('camera-feed');
          if (img) img.src = 'data:image/jpeg;base64,' + d.jpeg_b64;
        }
      });
  }

  // -----------------------------------------------------------------------
  // Helpers
  // -----------------------------------------------------------------------
  function _setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  // -----------------------------------------------------------------------
  // Bootstrap
  // -----------------------------------------------------------------------
  function _init() {
    _initTabs();
    SlicerUI.init();
    QueueUI.init();
    SettingsUI.init();
    MaintenanceUI.init();
    _pollStatus();
    setInterval(_pollStatus, 10000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _init);
  } else {
    _init();
  }

  return { startScan, stopScan, reconstruct, exportModel, moveAxis, rotate, home, laser, setLED, captureFrame };
})();
