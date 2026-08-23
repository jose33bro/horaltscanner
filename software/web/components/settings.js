/**
 * Settings - Configuration Panel component
 */

const SettingsUI = (() => {
  function init() {
    _loadFromServer();
    const saveBtn = document.getElementById('btn-settings-save');
    const testBtn = document.getElementById('btn-moonraker-test');
    if (saveBtn) saveBtn.addEventListener('click', _save);
    if (testBtn) testBtn.addEventListener('click', _testMoonraker);
  }

  async function _loadFromServer() {
    try {
      const resp = await fetch('/api/settings');
      const cfg = await resp.json();
      _fillField('settings-moonraker-url', cfg.moonraker?.url || '');
      _fillField('settings-moonraker-key', '');  // never pre-fill key
      _fillField('settings-layer-height', cfg.slicer?.layer_height ?? 0.2);
      _fillField('settings-infill', cfg.slicer?.infill ?? 20);
      _fillField('settings-nozzle-temp', cfg.slicer?.nozzle_temp ?? 200);
      _fillField('settings-laser-power', cfg.scanner?.laser_power ?? 100);
      _fillField('settings-resolution', cfg.scanner?.resolution ?? '1920x1080');

      // Also persist to localStorage for queue.js
      if (cfg.moonraker?.url) localStorage.setItem('moonraker_url', cfg.moonraker.url);
    } catch (e) { /* no-op */ }
  }

  async function _save() {
    const url = _val('settings-moonraker-url');
    const key = _val('settings-moonraker-key');

    const payload = {
      moonraker: { url },
      slicer: {
        layer_height: parseFloat(_val('settings-layer-height') || '0.2'),
        infill: parseInt(_val('settings-infill') || '20', 10),
        nozzle_temp: parseInt(_val('settings-nozzle-temp') || '200', 10),
      },
      scanner: {
        laser_power: parseInt(_val('settings-laser-power') || '100', 10),
        resolution: _val('settings-resolution') || '1920x1080',
      },
    };
    if (key) payload.moonraker.api_key = key;

    const resp = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const result = await resp.json();
    _setStatus(result.ok ? '✅ Settings saved' : `❌ ${result.error}`);

    if (url) localStorage.setItem('moonraker_url', url);
    // Note: API key is NOT stored in localStorage for security reasons
  }

  async function _testMoonraker() {
    const url = _val('settings-moonraker-url');
    const key = _val('settings-moonraker-key');
    _setStatus('Testing connection…');
    const resp = await fetch('/api/moonraker/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, key }),
    });
    const result = await resp.json();
    _setStatus(result.ok
      ? `✅ Connected – Moonraker ${result.version}`
      : `❌ ${result.error}`);
  }

  function _fillField(id, value) {
    const el = document.getElementById(id);
    if (el) el.value = value;
  }

  function _val(id) {
    return document.getElementById(id)?.value || '';
  }

  function _setStatus(msg) {
    const el = document.getElementById('settings-status');
    if (el) el.textContent = msg;
  }

  return { init };
})();
