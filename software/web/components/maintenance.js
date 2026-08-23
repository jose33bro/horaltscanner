/**
 * Maintenance - System Dashboard component
 */

const MaintenanceUI = (() => {
  let _pollTimer = null;

  function init() {
    refresh();
    _pollTimer = setInterval(refresh, 10000);

    const updateBtn = document.getElementById('btn-system-update');
    if (updateBtn) updateBtn.addEventListener('click', _doUpdate);
  }

  async function refresh() {
    try {
      const [statusResp, tempResp] = await Promise.all([
        fetch('/api/status'),
        fetch('/api/temperature'),
      ]);
      const status = await statusResp.json();
      const temp   = await tempResp.json();

      _set('maint-temp', temp.temperature_c != null ? `${temp.temperature_c} °C` : 'N/A');
      _set('maint-disk-free', `${status.disk_free_gb} GB free / ${status.disk_total_gb} GB total`);
      _set('maint-scan-status', status.scanning ? '🔴 Scanning' : '⚪ Idle');
      _set('maint-lidar',       status.lidar_connected ? '✅ Connected' : '❌ Disconnected');
      _set('maint-logitech',    status.logitech_open   ? '✅ Open'      : '❌ Closed');
      _set('maint-picam',       status.picam_open      ? '✅ Open'      : '❌ Closed');
      _set('maint-slicer',      status.slicer_available ? '✅ Available' : '❌ Not found');
      _set('maint-gpio',        status.gpio_available  ? '✅ Available' : '⚠️ Simulated');
    } catch (e) {
      _set('maint-temp', 'API unreachable');
    }
  }

  async function _doUpdate() {
    _set('maint-update-log', 'Running git pull + pip install…');
    try {
      const resp = await fetch('/api/update', { method: 'POST' });
      const result = await resp.json();
      const log = [
        result.ok ? '✅ Update successful' : '❌ Update failed',
        '--- git ---',
        result.git_output,
        '--- pip ---',
        result.pip_output,
      ].join('\n');
      _set('maint-update-log', log);
    } catch (e) {
      _set('maint-update-log', `Error: ${e.message}`);
    }
  }

  function _set(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  function destroy() {
    if (_pollTimer) clearInterval(_pollTimer);
  }

  return { init, refresh, destroy };
})();
