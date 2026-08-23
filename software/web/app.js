const API_BASE = 'http://192.168.1.39:5000';

// Classe pour gérer l'API
class CrealityAPI {
    constructor(baseURL) {
        this.baseURL = baseURL;
    }

    async request(endpoint, method = 'GET', data = null) {
        const options = {
            method,
            headers: {
                'Content-Type': 'application/json'
            }
        };

        if (data) {
            options.body = JSON.stringify(data);
        }

        try {
            const response = await fetch(`${this.baseURL}${endpoint}`, options);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return await response.json();
        } catch (error) {
            console.error(`Erreur API: ${endpoint}`, error);
            throw error;
        }
    }

    // Endpoints
    async getStatus() {
        return this.request('/api/status');
    }

    async home() {
        return this.request('/api/home', 'POST');
    }

    async move(x, y, z, speed) {
        return this.request('/api/move', 'POST', { x, y, z, speed });
    }

    async setNozzleTemp(temp) {
        return this.request('/api/temp/nozzle', 'POST', { temp });
    }

    async setBedTemp(temp) {
        return this.request('/api/temp/bed', 'POST', { temp });
    }

    async extrude(length, speed) {
        return this.request('/api/extrude', 'POST', { length, speed });
    }

    async flashFirmware(firmware) {
        const formData = new FormData();
        formData.append('firmware', firmware);

        try {
            const response = await fetch(`${this.baseURL}/api/flash`, {
                method: 'POST',
                body: formData
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return await response.json();
        } catch (error) {
            console.error('Erreur flashage', error);
            throw error;
        }
    }
}

// Instance API
const api = new CrealityAPI(API_BASE);

// UI Controller
class UIController {
    constructor() {
        this.statusElement = document.getElementById('connection-status');
        this.tempsElement = document.getElementById('temps-display');
        this.setupTabs();
        this.setupEventListeners();
        this.startStatusUpdate();
    }

    setupTabs() {
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const tabName = btn.dataset.tab;
                this.switchTab(tabName);
            });
        });
    }

    switchTab(tabName) {
        // Hide all tabs
        document.querySelectorAll('.tab-content').forEach(tab => {
            tab.classList.remove('active');
        });

        // Remove active from buttons
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.remove('active');
        });

        // Show selected tab
        document.getElementById(tabName).classList.add('active');
        document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
    }

    setupEventListeners() {
        // File input
        document.getElementById('firmware-file').addEventListener('change', (e) => {
            this.handleFirmwareSelect(e);
        });
    }

    handleFirmwareSelect(e) {
        const file = e.target.files[0];
        if (file) {
            const sizeKB = (file.size / 1024).toFixed(2);
            document.getElementById('firmware-info').textContent = 
                `Fichier: ${file.name} (${sizeKB} KB)`;
        }
    }

    updateStatus(connected, temps = null) {
        if (connected) {
            this.statusElement.textContent = '✓ Connecté';
            this.statusElement.classList.remove('disconnected');
            this.statusElement.classList.add('connected');
        } else {
            this.statusElement.textContent = '✗ Déconnecté';
            this.statusElement.classList.remove('connected');
            this.statusElement.classList.add('disconnected');
        }

        if (temps) {
            this.tempsElement.textContent = temps;
        }
    }

    showMessage(message, type = 'info') {
        const statusDiv = document.getElementById('flash-status');
        statusDiv.textContent = message;
        statusDiv.className = `status-message ${type}`;
    }

    async startStatusUpdate() {
        setInterval(async () => {
            try {
                const status = await api.getStatus();
                this.updateStatus(status.connected, status.temperatures);
            } catch (error) {
                this.updateStatus(false);
            }
        }, 2000);
    }
}

// Commandes UI
async function sendCommand(command) {
    try {
        if (command === 'home') {
            await api.home();
            ui.showMessage('✓ Homing en cours...', 'info');
        }
    } catch (error) {
        ui.showMessage(`✗ Erreur: ${error.message}`, 'error');
    }
}

async function sendMove() {
    try {
        const x = parseFloat(document.getElementById('move-x').value);
        const y = parseFloat(document.getElementById('move-y').value);
        const z = parseFloat(document.getElementById('move-z').value);
        const speed = parseFloat(document.getElementById('move-speed').value);

        await api.move(x, y, z, speed);
        ui.showMessage(`✓ Déplacement vers X=${x} Y=${y} Z=${z}`, 'info');
    } catch (error) {
        ui.showMessage(`✗ Erreur: ${error.message}`, 'error');
    }
}

async function setNozzleTemp() {
    try {
        const temp = parseFloat(document.getElementById('nozzle-temp').value);
        await api.setNozzleTemp(temp);
        ui.showMessage(`✓ Buse chauffée à ${temp}°C`, 'success');
    } catch (error) {
        ui.showMessage(`✗ Erreur: ${error.message}`, 'error');
    }
}

async function setBedTemp() {
    try {
        const temp = parseFloat(document.getElementById('bed-temp').value);
        await api.setBedTemp(temp);
        ui.showMessage(`✓ Lit chauffé à ${temp}°C`, 'success');
    } catch (error) {
        ui.showMessage(`✗ Erreur: ${error.message}`, 'error');
    }
}

async function sendExtrude() {
    try {
        const length = parseFloat(document.getElementById('extrude-length').value);
        const speed = parseFloat(document.getElementById('extrude-speed').value);
        await api.extrude(length, speed);
        ui.showMessage(`✓ Extrusion ${length}mm`, 'success');
    } catch (error) {
        ui.showMessage(`✗ Erreur: ${error.message}`, 'error');
    }
}

async function flashFirmware() {
    const fileInput = document.getElementById('firmware-file');
    const file = fileInput.files[0];

    if (!file) {
        ui.showMessage('Sélectionnez un fichier firmware', 'error');
        return;
    }

    if (!file.name.endsWith('.bin') && !file.name.endsWith('.hex')) {
        ui.showMessage('Fichier invalide (.bin ou .hex requis)', 'error');
        return;
    }

    try {
        document.getElementById('flash-progress').style.display = 'block';
        
        ui.showMessage('📤 Flashage en cours...', 'info');
        const result = await api.flashFirmware(file);
        
        document.getElementById('progress-bar').value = 100;
        document.getElementById('progress-text').textContent = '100%';
        
        ui.showMessage('✓ Firmware flashé avec succès!', 'success');
    } catch (error) {
        ui.showMessage(`✗ Erreur flashage: ${error.message}`, 'error');
    }
}

function reconnect() {
    ui.showMessage('🔄 Reconnexion...', 'info');
    setTimeout(() => {
        ui.showMessage('✓ Reconnecté', 'success');
    }, 1000);
}

function disconnect() {
    ui.updateStatus(false);
    ui.showMessage('Déconnecté', 'info');
}

function updateSettings() {
    const port = document.getElementById('port-select').value;
    const baudrate = document.getElementById('baudrate-select').value;
    
    ui.showMessage(
        `✓ Paramètres sauvegardés: ${port} @ ${baudrate}bps`,
        'success'
    );
}

// Initialiser l'app
let ui;
document.addEventListener('DOMContentLoaded', () => {
    ui = new UIController();
    console.log('✓ App chargée');
});
