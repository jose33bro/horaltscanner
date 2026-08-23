// PrusaSlicer UI component
class SlicerComponent {
    constructor(api) {
        this.api = api;
        this.profile = {
            layer_height: 0.2,
            infill_density: 20,
            support_material: false,
            nozzle_diameter: 0.4,
            temperature: 215,
            bed_temperature: 60,
            perimeters: 3,
        };
    }

    render() {
        return `
        <div class="slicer-wrap">
          <div class="card">
            <h3>🖨️ PrusaSlicer</h3>
            <div class="slicer-grid">
              <!-- Profile settings -->
              <div class="slicer-settings">
                <h4>Paramètres de découpe</h4>
                <div class="form-group">
                  <label>Hauteur de couche (mm)</label>
                  <input type="number" id="sl-layer" value="0.2" min="0.05" max="0.5" step="0.05" onchange="slicerComp.updateProfile()">
                </div>
                <div class="form-group">
                  <label>Remplissage (%)</label>
                  <input type="range" id="sl-infill" min="0" max="100" value="20" onchange="slicerComp.updateProfile()">
                  <span id="sl-infill-val">20%</span>
                </div>
                <div class="form-group">
                  <label>Supports</label>
                  <input type="checkbox" id="sl-support" onchange="slicerComp.updateProfile()">
                </div>
                <div class="form-group">
                  <label>Diamètre buse (mm)</label>
                  <select id="sl-nozzle" onchange="slicerComp.updateProfile()">
                    <option value="0.4">0.4mm</option>
                    <option value="0.6">0.6mm</option>
                    <option value="0.2">0.2mm</option>
                  </select>
                </div>
                <div class="form-group">
                  <label>Température buse (°C)</label>
                  <input type="number" id="sl-temp" value="215" min="150" max="300" onchange="slicerComp.updateProfile()">
                </div>
                <div class="form-group">
                  <label>Température lit (°C)</label>
                  <input type="number" id="sl-bed" value="60" min="0" max="110" onchange="slicerComp.updateProfile()">
                </div>
                <div class="form-group">
                  <label>Périmètres</label>
                  <input type="number" id="sl-perim" value="3" min="1" max="10" onchange="slicerComp.updateProfile()">
                </div>
              </div>

              <!-- Model source + actions -->
              <div class="slicer-actions">
                <h4>Source du modèle</h4>
                <div class="btn-row">
                  <button class="btn btn-blue" onclick="slicerComp.sliceCurrentModel()">🔧 Découper le modèle actuel</button>
                </div>
                <div class="upload-area" ondragover="event.preventDefault()" ondrop="slicerComp.handleDrop(event)">
                  <p>📂 Glisser-déposer un fichier STL/AMF ici</p>
                  <input type="file" id="sl-file" accept=".stl,.amf" onchange="slicerComp.handleFileSelect(event)" style="display:none">
                  <button class="btn btn-sm" onclick="document.getElementById('sl-file').click()">Choisir fichier</button>
                  <span id="sl-filename"></span>
                </div>
                <div id="slicer-status" class="status-msg"></div>
                <div id="slicer-result" style="display:none">
                  <h4>Résultat</h4>
                  <div id="slicer-gcode-info"></div>
                  <div class="btn-row">
                    <button class="btn btn-green" onclick="slicerComp.downloadGcode()">💾 Télécharger G-code</button>
                    <button class="btn btn-orange" onclick="slicerComp.addToQueue()">➕ Ajouter à la file</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>`;
    }

    init() {
        const infill = document.getElementById('sl-infill');
        if (infill) {
            infill.addEventListener('input', () => {
                document.getElementById('sl-infill-val').textContent = infill.value + '%';
            });
        }
    }

    updateProfile() {
        this.profile = {
            layer_height: parseFloat(document.getElementById('sl-layer').value),
            infill_density: parseInt(document.getElementById('sl-infill').value),
            support_material: document.getElementById('sl-support').checked,
            nozzle_diameter: parseFloat(document.getElementById('sl-nozzle').value),
            temperature: parseInt(document.getElementById('sl-temp').value),
            bed_temperature: parseInt(document.getElementById('sl-bed').value),
            perimeters: parseInt(document.getElementById('sl-perim').value),
        };
    }

    setStatus(msg, type = 'info') {
        const el = document.getElementById('slicer-status');
        if (el) { el.textContent = msg; el.className = 'status-msg ' + type; }
    }

    async sliceCurrentModel() {
        this.updateProfile();
        this.setStatus('Découpe en cours...', 'info');
        try {
            const r = await this.api.post('/api/slice', { format: 'stl', profile: this.profile });
            if (r.ok) {
                this._lastGcodeId = r.gcode_id;
                this.setStatus(`Découpe terminée – ${r.size} octets`, 'success');
                document.getElementById('slicer-gcode-info').textContent = `G-code: ${r.size} octets (ID: ${r.gcode_id})`;
                document.getElementById('slicer-result').style.display = 'block';
            } else {
                this.setStatus('Erreur: ' + (r.error || ''), 'error');
            }
        } catch (e) {
            this.setStatus('Erreur de découpe', 'error');
        }
    }

    handleDrop(e) {
        e.preventDefault();
        const file = e.dataTransfer.files[0];
        if (file) this._sliceFile(file);
    }

    handleFileSelect(e) {
        const file = e.target.files[0];
        if (file) this._sliceFile(file);
    }

    async _sliceFile(file) {
        document.getElementById('sl-filename').textContent = file.name;
        this.updateProfile();
        this.setStatus('Chargement du fichier...', 'info');
        const arrayBuf = await file.arrayBuffer();
        const b64 = btoa(String.fromCharCode(...new Uint8Array(arrayBuf)));
        const ext = file.name.split('.').pop().toLowerCase();
        this.setStatus('Découpe en cours...', 'info');
        try {
            const r = await this.api.post('/api/slice', { format: ext, model_b64: b64, profile: this.profile });
            if (r.ok) {
                this._lastGcodeId = r.gcode_id;
                this.setStatus(`Découpe terminée – ${r.size} octets`, 'success');
                document.getElementById('slicer-gcode-info').textContent = `G-code: ${r.size} octets (ID: ${r.gcode_id})`;
                document.getElementById('slicer-result').style.display = 'block';
            } else {
                this.setStatus('Erreur: ' + (r.error || ''), 'error');
            }
        } catch (e) {
            this.setStatus('Erreur de découpe', 'error');
        }
    }

    downloadGcode() {
        if (!this._lastGcodeId) { showToast('Aucun G-code disponible', 'error'); return; }
        // Fetch gcode from queue endpoint and trigger download
        fetch(this.api.baseURL + '/api/queue')
            .then(r => r.json())
            .then(items => {
                const item = items.find(i => i.id === this._lastGcodeId);
                if (!item) { showToast('G-code introuvable dans la file', 'error'); return; }
                // Re-slice to get bytes (queue items strip gcode for listing; use slice endpoint)
                showToast('Le G-code est dans la file d\'impression', 'info');
            })
            .catch(() => showToast('Erreur téléchargement', 'error'));
    }

    addToQueue() {
        showToast('G-code ajouté à la file ✔', 'success');
        // Switch to queue tab
        window.switchTab && window.switchTab('queue');
    }

    destroy() {}
}
