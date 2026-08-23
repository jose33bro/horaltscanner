// Print queue manager component
class QueueComponent {
    constructor(api) {
        this.api = api;
        this.pollInterval = null;
    }

    render() {
        return `
        <div class="queue-wrap">
          <div class="card">
            <h3>📋 File d'impression</h3>
            <div class="btn-row">
              <button class="btn btn-blue" onclick="queueComp.refresh()">🔄 Actualiser</button>
              <div class="upload-area-small" ondragover="event.preventDefault()" ondrop="queueComp.handleDrop(event)">
                <input type="file" id="queue-file" accept=".gcode" onchange="queueComp.handleFileSelect(event)" style="display:none">
                <button class="btn btn-sm" onclick="document.getElementById('queue-file').click()">📂 Upload G-code</button>
              </div>
            </div>
            <div id="queue-list" class="queue-list">
              <p class="empty-msg">File vide</p>
            </div>
          </div>
        </div>`;
    }

    init() {
        this.refresh();
        this.pollInterval = setInterval(() => this.refresh(), 5000);
    }

    async refresh() {
        try {
            const items = await this.api.get('/api/queue');
            this._renderQueue(items);
        } catch (e) {}
    }

    _renderQueue(items) {
        const el = document.getElementById('queue-list');
        if (!el) return;
        if (!items || items.length === 0) {
            el.innerHTML = '<p class="empty-msg">File vide</p>';
            return;
        }
        el.innerHTML = items.map(item => `
          <div class="queue-item" id="qi-${item.id}">
            <div class="qi-info">
              <span class="qi-name">${item.filename}</span>
              <span class="qi-status badge badge-${item.status}">${item.status}</span>
              <span class="qi-time">${new Date(item.created_at * 1000).toLocaleTimeString()}</span>
            </div>
            <div class="qi-actions">
              <button class="btn btn-sm btn-green" onclick="queueComp.sendToGrandVoile('${item.id}')">
                📤 Envoyer à GrandVoile
              </button>
              <button class="btn btn-sm btn-red" onclick="queueComp.removeItem('${item.id}')">🗑</button>
            </div>
          </div>`).join('');
    }

    async sendToGrandVoile(id) {
        showToast('Envoi en cours...', 'info');
        try {
            const r = await this.api.post(`/api/queue/${id}/send`);
            if (r.ok) {
                showToast('Envoyé à GrandVoile ✔', 'success');
                this.refresh();
            } else {
                showToast('Erreur: ' + (r.error || 'Moonraker non configuré'), 'error');
            }
        } catch (e) {
            showToast('Erreur envoi', 'error');
        }
    }

    async removeItem(id) {
        await this.api.post(`/api/queue/${id}/remove`);
        this.refresh();
    }

    handleDrop(e) {
        e.preventDefault();
        const file = e.dataTransfer.files[0];
        if (file) this._uploadFile(file);
    }

    handleFileSelect(e) {
        const file = e.target.files[0];
        if (file) this._uploadFile(file);
    }

    async _uploadFile(file) {
        showToast('Upload en cours...', 'info');
        const formData = new FormData();
        formData.append('file', file);
        try {
            const r = await fetch(this.api.baseURL + '/api/queue/add', {
                method: 'POST', body: formData
            });
            const data = await r.json();
            if (data.ok) {
                showToast('Fichier ajouté ✔', 'success');
                this.refresh();
            } else {
                showToast('Erreur upload', 'error');
            }
        } catch (e) {
            showToast('Erreur upload', 'error');
        }
    }

    destroy() {
        if (this.pollInterval) clearInterval(this.pollInterval);
    }
}
