// Scanner control component
class ScannerComponent {
    constructor(api) {
        this.api = api;
        this.scanTimer = null;
        this.scanStartTime = null;
        this.statusPollInterval = null;
    }

    render() {
        return `
        <div class="scanner-grid">
          <!-- Left: Controls -->
          <div class="control-panel">
            <!-- Scan control -->
            <div class="card">
              <h3>🔍 Scan 3D</h3>
              <div class="scan-stats" id="scan-stats">
                <span>Points: <b id="stat-points">0</b></span>
                <span>Temps: <b id="stat-time">0s</b></span>
                <span>Qualité: <b id="stat-quality">0%</b></span>
              </div>
              <div class="btn-row">
                <button id="btn-scan-start" class="btn btn-green btn-lg" onclick="scannerComp.startScan()">▶ Démarrer</button>
                <button id="btn-scan-stop" class="btn btn-red btn-lg" onclick="scannerComp.stopScan()" disabled>⏹ Arrêter</button>
              </div>
              <div class="progress-bar-wrap"><div id="scan-progress" class="progress-bar" style="width:0%"></div></div>
            </div>

            <!-- Axes -->
            <div class="card">
              <h3>📍 Axes</h3>
              <div class="axis-row">
                <label>X (0–195mm)</label>
                <input type="range" id="axis-x" min="0" max="195" value="0" oninput="document.getElementById('axis-x-val').textContent=this.value+'mm'">
                <span id="axis-x-val">0mm</span>
                <button class="btn btn-sm" onclick="scannerComp.moveAxis('x')">→</button>
              </div>
              <div class="axis-row">
                <label>Z (0–270mm)</label>
                <input type="range" id="axis-z" min="0" max="270" value="0" oninput="document.getElementById('axis-z-val').textContent=this.value+'mm'">
                <span id="axis-z-val">0mm</span>
                <button class="btn btn-sm" onclick="scannerComp.moveAxis('z')">→</button>
              </div>
              <div class="axis-row">
                <label>Rotation</label>
                <input type="number" id="rotate-deg" min="0" max="360" value="45" style="width:70px">
                <span>°</span>
                <button class="btn btn-sm" onclick="scannerComp.rotate()">↻</button>
              </div>
              <button class="btn btn-orange" onclick="scannerComp.homeAll()">🏠 Home All</button>
            </div>

            <!-- Lasers -->
            <div class="card">
              <h3>🔴 Lasers</h3>
              <div class="btn-row">
                <button id="btn-laser-left" class="btn btn-laser" onclick="scannerComp.toggleLaser('left')">◀ Gauche</button>
                <button id="btn-laser-right" class="btn btn-laser" onclick="scannerComp.toggleLaser('right')">Droit ▶</button>
              </div>
            </div>

            <!-- LIDAR -->
            <div class="card">
              <h3>🔦 LIDAR</h3>
              <div class="lidar-display">
                <span id="lidar-distance">---</span> mm
              </div>
              <div class="btn-row">
                <button class="btn btn-sm" onclick="scannerComp.readLidar()">📏 Lire</button>
                <button class="btn btn-sm" onclick="scannerComp.lidarUp()">⬆</button>
                <button class="btn btn-sm" onclick="scannerComp.lidarDown()">⬇</button>
                <button class="btn btn-sm" onclick="scannerComp.lidarCalibrate()">⚙ Cal</button>
              </div>
            </div>

            <!-- LED RGB -->
            <div class="card">
              <h3>💡 LED RGB</h3>
              <div class="color-row">
                <input type="color" id="led-color" value="#ffffff" oninput="scannerComp.setLedColor(this.value)">
                <label>Couleur LED</label>
              </div>
              <div class="rgb-sliders">
                <div class="axis-row">
                  <label>R</label>
                  <input type="range" id="led-r" min="0" max="255" value="255" oninput="scannerComp.setLedRGB()">
                </div>
                <div class="axis-row">
                  <label>G</label>
                  <input type="range" id="led-g" min="0" max="255" value="255" oninput="scannerComp.setLedRGB()">
                </div>
                <div class="axis-row">
                  <label>B</label>
                  <input type="range" id="led-b" min="0" max="255" value="255" oninput="scannerComp.setLedRGB()">
                </div>
              </div>
            </div>
          </div>

          <!-- Right: Camera preview -->
          <div class="camera-panel">
            <div class="card">
              <h3>📷 Caméras</h3>
              <div class="camera-grid">
                <div class="cam-wrap">
                  <div class="cam-label">PiCam V3 NoIR</div>
                  <canvas id="cam-picam" width="640" height="360" class="cam-canvas"></canvas>
                  <button class="btn btn-sm" onclick="scannerComp.captureCam('picam')">📸 Capture</button>
                </div>
                <div class="cam-wrap">
                  <div class="cam-label">Logitech C270</div>
                  <img id="cam-logi" src="" class="cam-canvas" alt="Logitech stream">
                  <button class="btn btn-sm" onclick="scannerComp.captureCam('logi')">📸 Capture</button>
                </div>
              </div>
            </div>
            <!-- Temperature -->
            <div class="card">
              <h3>🌡️ Température board</h3>
              <div id="temp-display" class="temp-display">--</div>
            </div>
          </div>
        </div>`;
    }

    init() {
        this.startStatusPoll();
        this.startCameraStream();
        this.refreshTemp();
    }

    startStatusPoll() {
        if (this.statusPollInterval) clearInterval(this.statusPollInterval);
        this.statusPollInterval = setInterval(() => this.pollScanStatus(), 1000);
    }

    async pollScanStatus() {
        try {
            const s = await this.api.get('/api/scan/status');
            document.getElementById('stat-points').textContent = s.points || 0;
            const elapsed = s.elapsed_s || 0;
            document.getElementById('stat-time').textContent = elapsed + 's';
            document.getElementById('stat-quality').textContent = Math.round((s.quality || 0) * 100) + '%';
            const prog = Math.min(100, (s.points || 0) / 500 * 100);
            document.getElementById('scan-progress').style.width = prog + '%';
        } catch (e) {}
    }

    startCameraStream() {
        const logi = document.getElementById('cam-logi');
        if (logi) {
            logi.src = this.api.baseURL + '/api/camera/stream';
        }
    }

    async startScan() {
        const r = await this.api.post('/api/scan/start');
        if (r.ok) {
            document.getElementById('btn-scan-start').disabled = true;
            document.getElementById('btn-scan-stop').disabled = false;
            showToast('Scan démarré ✔', 'success');
        }
    }

    async stopScan() {
        await this.api.post('/api/scan/stop');
        document.getElementById('btn-scan-start').disabled = false;
        document.getElementById('btn-scan-stop').disabled = true;
        showToast('Scan arrêté', 'info');
    }

    async moveAxis(axis) {
        const val = parseFloat(document.getElementById(`axis-${axis}`).value);
        await this.api.post(`/api/move/${axis}`, { mm: val });
        showToast(`Axe ${axis.toUpperCase()} → ${val}mm`, 'info');
    }

    async rotate() {
        const deg = parseFloat(document.getElementById('rotate-deg').value);
        await this.api.post('/api/rotate', { degrees: deg });
        showToast(`Rotation ${deg}°`, 'info');
    }

    async homeAll() {
        showToast('Homing...', 'info');
        await this.api.post('/api/home/all');
        showToast('Home terminé ✔', 'success');
    }

    _laserStates = { left: false, right: false };

    async toggleLaser(side) {
        this._laserStates[side] = !this._laserStates[side];
        await this.api.post(`/api/laser/${side}`, { state: this._laserStates[side] });
        const btn = document.getElementById(`btn-laser-${side}`);
        if (btn) btn.classList.toggle('active', this._laserStates[side]);
    }

    async readLidar() {
        const r = await this.api.post('/api/lidar/read');
        const dist = r.distance_mm !== null ? r.distance_mm : '---';
        document.getElementById('lidar-distance').textContent = dist;
    }

    async lidarUp() { await this.api.post('/api/move/z', { mm: 10 }); }
    async lidarDown() { await this.api.post('/api/move/z', { mm: -10 }); }
    async lidarCalibrate() {
        showToast('Calibration LIDAR...', 'info');
        await this.api.post('/api/lidar/calibrate');
        showToast('Calibration terminée', 'success');
    }

    setLedColor(hex) {
        const r = parseInt(hex.slice(1,3),16);
        const g = parseInt(hex.slice(3,5),16);
        const b = parseInt(hex.slice(5,7),16);
        document.getElementById('led-r').value = r;
        document.getElementById('led-g').value = g;
        document.getElementById('led-b').value = b;
        this.api.post('/api/led/color', { r, g, b });
    }

    setLedRGB() {
        const r = parseInt(document.getElementById('led-r').value);
        const g = parseInt(document.getElementById('led-g').value);
        const b = parseInt(document.getElementById('led-b').value);
        const hex = '#' + [r,g,b].map(v => v.toString(16).padStart(2,'0')).join('');
        document.getElementById('led-color').value = hex;
        this.api.post('/api/led/color', { r, g, b });
    }

    async captureCam(cam) {
        const r = await this.api.post(`/api/camera/${cam}`);
        if (r.jpeg_b64 && cam === 'picam') {
            const canvas = document.getElementById('cam-picam');
            const ctx = canvas.getContext('2d');
            const img = new Image();
            img.onload = () => ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
            img.src = 'data:image/jpeg;base64,' + r.jpeg_b64;
        }
    }

    async refreshTemp() {
        try {
            const r = await this.api.get('/api/temperature');
            const el = document.getElementById('temp-display');
            if (el) el.textContent = r.raw || JSON.stringify(r);
        } catch (e) {}
        setTimeout(() => this.refreshTemp(), 5000);
    }

    destroy() {
        if (this.statusPollInterval) clearInterval(this.statusPollInterval);
    }
}
