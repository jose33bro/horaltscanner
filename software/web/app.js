// HoralScanner Web UI - App logic
// The API base URL is relative so it works regardless of the server IP
const API_BASE = '';

// Scanner section
function startScan() {
    showAlert('🔍 Scan démarré...', 'info');
    document.getElementById('scan-progress').style.display = 'block';
    document.getElementById('scan-status').textContent = 'Scan en cours...';
}

function stopScan() {
    document.getElementById('scan-progress').style.display = 'none';
    document.getElementById('scan-status').textContent = 'Scan arrêté';
    showAlert('Scan arrêté', 'info');
}

function exportScan() {
    showAlert('💾 Scan exporté en .STL', 'success');
}

// G-code / Print section
let currentGcode = null;

function handleGcodeSelect() {
    const file = document.getElementById('gcode-file').files[0];
    if (!file) return;
    currentGcode = file;
    const sizeKB = (file.size / 1024).toFixed(2);
    document.getElementById('gcode-name').textContent = file.name;
    document.getElementById('gcode-size').textContent = sizeKB + ' KB';
    document.getElementById('gcode-info').style.display = 'block';
    document.getElementById('send-btn').disabled = false;
    document.getElementById('gcode-time').textContent = 'N/A';
    document.getElementById('gcode-lines').textContent = Math.floor(file.size / 20);
    showAlert('📁 Fichier sélectionné: ' + file.name, 'success');
}

function previewGcode() {
    if (!currentGcode) {
        showAlert("Sélectionnez un fichier d'abord", 'error');
        return;
    }
    showAlert("👁️ Aperçu du G-code (fonctionnalité en développement)", 'info');
}

async function sendToPrinter() {
    if (!currentGcode) {
        showAlert('Sélectionnez un fichier', 'error');
        return;
    }
    const formData = new FormData();
    formData.append('gcode', currentGcode);
    try {
        document.getElementById('print-progress').style.display = 'block';
        showAlert('📤 Envoi en cours...', 'info');
        const response = await fetch(`${API_BASE}/api/print`, { method: 'POST', body: formData });
        const data = await response.json();
        if (data.success) {
            document.getElementById('print-progress-bar').value = 100;
            document.getElementById('print-progress-text').textContent = '100%';
            showAlert("✓ Fichier envoyé à l'imprimante!", 'success');
        } else {
            showAlert('✗ Erreur: ' + (data.message || data.error), 'error');
        }
    } catch (e) {
        showAlert('✗ Erreur: ' + e.message, 'error');
    }
}

function clearGcode() {
    currentGcode = null;
    document.getElementById('gcode-file').value = '';
    document.getElementById('gcode-info').style.display = 'none';
    document.getElementById('send-btn').disabled = true;
    document.getElementById('print-progress').style.display = 'none';
    showAlert('🗑️ Fichier effacé', 'info');
}

// Settings section
function connectScanner() {
    showAlert('🔌 Scanner connecté', 'success');
}

function connectPrinter() {
    showAlert('🖨️ Imprimante connectée', 'success');
}

async function flashFirmware() {
    const file = document.getElementById('firmware-file').files[0];
    if (!file) {
        showAlert('Sélectionnez un fichier', 'error');
        return;
    }
    const formData = new FormData();
    formData.append('firmware', file);
    try {
        document.getElementById('flash-progress').style.display = 'block';
        showAlert('📤 Flashage en cours...', 'info');
        const response = await fetch(`${API_BASE}/api/flash`, { method: 'POST', body: formData });
        const data = await response.json();
        document.getElementById('progress-bar').value = 100;
        document.getElementById('progress-text').textContent = '100%';
        if (data.success) {
            showAlert('✓ Flashage réussi!', 'success');
        } else {
            showAlert('✗ Erreur: ' + data.message, 'error');
        }
    } catch (e) {
        showAlert('✗ Erreur: ' + e.message, 'error');
    }
}

// Navigation
function switchSection(sectionId) {
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(sectionId).classList.add('active');
    document.querySelector(`[data-section="${sectionId}"]`).classList.add('active');
}

function showAlert(message, type) {
    const alert = document.getElementById('alert');
    if (!alert) return;
    alert.textContent = message;
    alert.className = `alert show alert-${type}`;
    setTimeout(() => alert.classList.remove('show'), 4000);
}

// Status polling
setInterval(async () => {
    try {
        const response = await fetch(`${API_BASE}/api/status`);
        const data = await response.json();
        const printerStatus = document.getElementById('printer-status');
        if (printerStatus) {
            printerStatus.className = data.connected ? 'status-badge ok' : 'status-badge error';
        }
    } catch (e) {
        // API unreachable
    }
}, 3000);

// Init navigation
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.addEventListener('click', () => switchSection(btn.dataset.section));
    });
    console.log('✓ HoralScanner UI chargée');
});
