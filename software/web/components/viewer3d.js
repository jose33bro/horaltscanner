// Three.js 3D viewer component
class Viewer3DComponent {
    constructor(api) {
        this.api = api;
        this.scene = null;
        this.camera = null;
        this.renderer = null;
        this.controls = null;
        this.pointCloud = null;
        this.mesh = null;
        this.animFrame = null;
        this.pollInterval = null;
    }

    render() {
        return `
        <div class="viewer3d-wrap">
          <div class="card viewer3d-controls">
            <h3>🎨 Modèle 3D</h3>
            <div class="btn-row">
              <button class="btn btn-blue" onclick="viewer3dComp.loadPointCloud()">☁ Point Cloud</button>
              <button class="btn btn-purple" onclick="viewer3dComp.reconstruct()">🔧 Reconstruire</button>
              <button class="btn btn-green" onclick="viewer3dComp.exportSTL()">💾 Export STL</button>
              <button class="btn btn-orange" onclick="viewer3dComp.exportAMF()">💾 Export AMF3D</button>
            </div>
            <div class="view-mode-row">
              <button class="btn btn-sm" onclick="viewer3dComp.setViewMode('points')">Points</button>
              <button class="btn btn-sm" onclick="viewer3dComp.setViewMode('wireframe')">Wireframe</button>
              <button class="btn btn-sm" onclick="viewer3dComp.setViewMode('solid')">Solide</button>
              <button class="btn btn-sm" onclick="viewer3dComp.resetCamera()">↺ Réinitialiser</button>
            </div>
            <div id="viewer3d-status" class="viewer-status">En attente de scan...</div>
          </div>
          <div id="viewer3d-container" class="viewer3d-container"></div>
        </div>`;
    }

    init() {
        this._initThreeJS();
        this.pollInterval = setInterval(() => this.autoRefreshPointCloud(), 3000);
    }

    _initThreeJS() {
        const container = document.getElementById('viewer3d-container');
        if (!container) return;

        // Scene
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(0x1a1a2e);

        // Camera
        const w = container.clientWidth || 800;
        const h = container.clientHeight || 600;
        this.camera = new THREE.PerspectiveCamera(60, w / h, 0.1, 10000);
        this.camera.position.set(0, 0, 300);

        // Renderer
        this.renderer = new THREE.WebGLRenderer({ antialias: true });
        this.renderer.setSize(w, h);
        this.renderer.setPixelRatio(window.devicePixelRatio);
        container.appendChild(this.renderer.domElement);

        // Lights
        const ambient = new THREE.AmbientLight(0xffffff, 0.6);
        this.scene.add(ambient);
        const dir = new THREE.DirectionalLight(0xffffff, 0.8);
        dir.position.set(100, 200, 100);
        this.scene.add(dir);

        // Grid
        const grid = new THREE.GridHelper(400, 20, 0x444466, 0x333355);
        this.scene.add(grid);

        // Axes
        const axes = new THREE.AxesHelper(50);
        this.scene.add(axes);

        // OrbitControls (from CDN)
        if (typeof THREE.OrbitControls !== 'undefined') {
            this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
            this.controls.enableDamping = true;
        }

        // Resize observer
        const ro = new ResizeObserver(() => {
            const w2 = container.clientWidth;
            const h2 = container.clientHeight;
            this.renderer.setSize(w2, h2);
            this.camera.aspect = w2 / h2;
            this.camera.updateProjectionMatrix();
        });
        ro.observe(container);

        this._animate();
    }

    _animate() {
        this.animFrame = requestAnimationFrame(() => this._animate());
        if (this.controls) this.controls.update();
        if (this.renderer && this.scene && this.camera) {
            this.renderer.render(this.scene, this.camera);
        }
    }

    async loadPointCloud() {
        try {
            const data = await this.api.get('/api/scan/pointcloud');
            if (!data.points || data.points.length === 0) {
                this._setStatus('Aucun point cloud disponible');
                return;
            }
            this._renderPointCloud(data.points, data.colors);
            this._setStatus(`${data.count} points chargés`);
        } catch (e) {
            this._setStatus('Erreur chargement point cloud');
        }
    }

    _renderPointCloud(points, colors) {
        if (this.pointCloud) {
            this.scene.remove(this.pointCloud);
            this.pointCloud.geometry.dispose();
        }

        const geo = new THREE.BufferGeometry();
        const flat = [];
        const clrFlat = [];
        for (let i = 0; i < points.length; i++) {
            flat.push(...points[i]);
            if (colors && colors[i]) clrFlat.push(...colors[i]);
            else clrFlat.push(0.2, 0.8, 1.0);
        }
        geo.setAttribute('position', new THREE.Float32BufferAttribute(flat, 3));
        geo.setAttribute('color', new THREE.Float32BufferAttribute(clrFlat, 3));

        const mat = new THREE.PointsMaterial({ size: 1, vertexColors: true });
        this.pointCloud = new THREE.Points(geo, mat);
        this.scene.add(this.pointCloud);
    }

    async reconstruct() {
        this._setStatus('Reconstruction en cours...');
        const r = await this.api.get('/api/model/reconstruct');
        if (r.ok) {
            this._setStatus(`Modèle reconstruit – STL: ${r.stl_size} octets`);
            await this.loadSTLMesh();
        } else {
            this._setStatus('Reconstruction échouée: ' + (r.error || ''));
        }
    }

    async loadSTLMesh() {
        try {
            const url = this.api.baseURL + '/api/model/current?format=stl';
            const loader = new THREE.STLLoader();
            loader.load(url, (geo) => {
                if (this.mesh) {
                    this.scene.remove(this.mesh);
                    this.mesh.geometry.dispose();
                }
                geo.computeVertexNormals();
                const mat = new THREE.MeshPhongMaterial({
                    color: 0x2196f3, specular: 0x888888,
                    shininess: 80, side: THREE.DoubleSide
                });
                this.mesh = new THREE.Mesh(geo, mat);
                this.scene.add(this.mesh);
                this._setStatus('Modèle STL chargé');
            });
        } catch (e) {
            this._setStatus('Erreur chargement STL');
        }
    }

    setViewMode(mode) {
        if (!this.mesh) return;
        const mat = this.mesh.material;
        if (mode === 'wireframe') {
            mat.wireframe = true;
        } else if (mode === 'solid') {
            mat.wireframe = false;
        } else if (mode === 'points') {
            if (this.pointCloud) this.scene.add(this.pointCloud);
        }
    }

    resetCamera() {
        this.camera.position.set(0, 0, 300);
        this.camera.lookAt(0, 0, 0);
        if (this.controls) this.controls.reset();
    }

    exportSTL() {
        this._downloadModel('stl');
    }

    exportAMF() {
        this._downloadModel('amf');
    }

    async _downloadModel(fmt) {
        try {
            const response = await fetch(this.api.baseURL + '/api/model/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ format: fmt })
            });
            if (!response.ok) { showToast('Aucun modèle disponible', 'error'); return; }
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = `model.${fmt}`; a.click();
            URL.revokeObjectURL(url);
        } catch (e) {
            showToast('Export échoué', 'error');
        }
    }

    async autoRefreshPointCloud() {
        try {
            const s = await this.api.get('/api/scan/status');
            if (s.scanning && s.points > 0) {
                await this.loadPointCloud();
            }
        } catch (e) {}
    }

    _setStatus(msg) {
        const el = document.getElementById('viewer3d-status');
        if (el) el.textContent = msg;
    }

    destroy() {
        if (this.pollInterval) clearInterval(this.pollInterval);
        if (this.animFrame) cancelAnimationFrame(this.animFrame);
        if (this.renderer) this.renderer.dispose();
    }
}
