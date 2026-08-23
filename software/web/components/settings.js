// Settings panel component
class SettingsComponent {
    constructor(api) {
        this.api = api;
    }

    render() {
        return `
        <div class="settings-wrap">
          <div class="card">
            <h3>⚙️ Configuration Moonraker (GrandVoile)</h3>
            <div class="form-grid">
              <div class="form-group">
                <label>URL Moonraker</label>
                <input type="url" id="s-moonraker-url" placeholder="http://192.168.1.40:7125">
              </div>
              <div class="form-group">
                <label>API Token</label>
                <input type="password" id="s-moonraker-token" placeholder="token ou vide">
              </div>
              <div class="form-group">
                <label>Nom imprimante</label>
                <input type="text" id="s-printer-name" placeholder="GrandVoile" value="GrandVoile">
              </div>
            </div>
            <div class="btn-row">
              <button class="btn btn-blue" onclick="settingsComp.testMoonraker()">🔗 Tester connexion</button>
            </div>
            <div id="moonraker-test-result" class="status-msg"></div>
          </div>

          <div class="card">
            <h3>🔍 Paramètres Scanner</h3>
            <div class="form-grid">
              <div class="form-group">
                <label>Port Klipper (serial)</label>
                <input type="text" id="s-klipper-port" value="/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0">
              </div>
              <div class="form-group">
                <label>Port LIDAR (USB)</label>
                <input type="text" id="s-lidar-port" value="/dev/ttyUSB0">
              </div>
              <div class="form-group">
                <label>ID caméra Logitech</label>
                <input type="number" id="s-logi-id" value="0" min="0" max="9">
              </div>
            </div>
          </div>

          <div class="card">
            <h3>🖨️ Paramètres Slicer par défaut</h3>
            <div class="form-grid">
              <div class="form-group">
                <label>Hauteur couche (mm)</label>
                <input type="number" id="s-layer" value="0.2" min="0.05" max="0.5" step="0.05">
              </div>
              <div class="form-group">
                <label>Remplissage (%)</label>
                <input type="number" id="s-infill" value="20" min="0" max="100">
              </div>
              <div class="form-group">
                <label>Température buse (°C)</label>
                <input type="number" id="s-temp" value="215">
              </div>
            </div>
          </div>

          <div class="btn-row" style="margin-top:1rem">
            <button class="btn btn-green btn-lg" onclick="settingsComp.save()">💾 Sauvegarder</button>
            <button class="btn btn-sm" onclick="settingsComp.load()">🔄 Charger</button>
          </div>
          <div id="settings-status" class="status-msg"></div>
        </div>`;
    }

    init() {
        this.load();
    }

    async load() {
        try {
            const s = await this.api.get('/api/settings');
            this._populate(s);
        } catch (e) {}
    }

    _populate(s) {
        const set = (id, val) => {
            const el = document.getElementById(id);
            if (el && val !== undefined) el.value = val;
        };
        set('s-moonraker-url', s.moonraker_url);
        set('s-moonraker-token', s.moonraker_token === '***' ? '' : s.moonraker_token || '');
        set('s-printer-name', s.printer_name);
        set('s-klipper-port', s.klipper_port);
        set('s-lidar-port', s.lidar_port);
        set('s-logi-id', s.logi_device_id);
        set('s-layer', s.default_layer_height);
        set('s-infill', s.default_infill);
        set('s-temp', s.default_temperature);
    }

    _collect() {
        const val = (id) => document.getElementById(id)?.value;
        return {
            moonraker_url: val('s-moonraker-url'),
            moonraker_token: val('s-moonraker-token'),
            printer_name: val('s-printer-name'),
            klipper_port: val('s-klipper-port'),
            lidar_port: val('s-lidar-port'),
            logi_device_id: parseInt(val('s-logi-id')) || 0,
            default_layer_height: parseFloat(val('s-layer')) || 0.2,
            default_infill: parseInt(val('s-infill')) || 20,
            default_temperature: parseInt(val('s-temp')) || 215,
        };
    }

    async save() {
        const data = this._collect();
        const r = await this.api.post('/api/settings', data);
        const el = document.getElementById('settings-status');
        if (el) {
            el.textContent = r.ok ? 'Paramètres sauvegardés ✔' : 'Erreur';
            el.className = 'status-msg ' + (r.ok ? 'success' : 'error');
        }
        showToast(r.ok ? 'Paramètres sauvegardés ✔' : 'Erreur sauvegarde', r.ok ? 'success' : 'error');
    }

    async testMoonraker() {
        const url = document.getElementById('s-moonraker-url')?.value;
        const token = document.getElementById('s-moonraker-token')?.value;
        // Pass URL and token directly in the test request body
        const r = await this.api.post('/api/moonraker/test', { url, token });
        const el = document.getElementById('moonraker-test-result');
        if (el) {
            el.textContent = r.ok ? '✅ Connexion OK' : '❌ Échec: ' + (r.error || '');
            el.className = 'status-msg ' + (r.ok ? 'success' : 'error');
        }
    }

    destroy() {}
}
