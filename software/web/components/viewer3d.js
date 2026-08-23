/**
 * Viewer3D - Three.js 3D viewer for point clouds and meshes
 * Loaded by index.html when the "3D Viewer" tab is active.
 */

const Viewer3D = (() => {
  let _scene, _camera, _renderer, _controls;
  let _pointCloud = null;
  let _mesh = null;
  let _animFrame = null;
  let _container = null;

  // -----------------------------------------------------------------------
  // Initialisation
  // -----------------------------------------------------------------------
  function init(containerId) {
    _container = document.getElementById(containerId);
    if (!_container) return;
    if (typeof THREE === 'undefined') {
      _container.innerHTML = '<p class="viewer-error">Three.js not loaded</p>';
      return;
    }

    // Scene
    _scene = new THREE.Scene();
    _scene.background = new THREE.Color(0x1a1a2e);

    // Camera
    const w = _container.clientWidth || 800;
    const h = _container.clientHeight || 500;
    _camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 10000);
    _camera.position.set(0, 100, 200);

    // Renderer
    _renderer = new THREE.WebGLRenderer({ antialias: true });
    _renderer.setSize(w, h);
    _renderer.setPixelRatio(window.devicePixelRatio);
    _container.innerHTML = '';
    _container.appendChild(_renderer.domElement);

    // Lights
    _scene.add(new THREE.AmbientLight(0xffffff, 0.5));
    const dir = new THREE.DirectionalLight(0xffffff, 1);
    dir.position.set(100, 200, 100);
    _scene.add(dir);

    // Grid
    const grid = new THREE.GridHelper(200, 20, 0x444466, 0x333355);
    _scene.add(grid);

    // Controls (OrbitControls if available)
    if (typeof THREE.OrbitControls !== 'undefined') {
      _controls = new THREE.OrbitControls(_camera, _renderer.domElement);
      _controls.enableDamping = true;
    }

    window.addEventListener('resize', _onResize);
    _animate();
  }

  function _onResize() {
    if (!_container || !_renderer || !_camera) return;
    const w = _container.clientWidth;
    const h = _container.clientHeight;
    _camera.aspect = w / h;
    _camera.updateProjectionMatrix();
    _renderer.setSize(w, h);
  }

  function _animate() {
    _animFrame = requestAnimationFrame(_animate);
    if (_controls) _controls.update();
    if (_renderer && _scene && _camera) _renderer.render(_scene, _camera);
  }

  // -----------------------------------------------------------------------
  // Point cloud display
  // -----------------------------------------------------------------------
  function showPointCloud(data) {
    if (!_scene) return;
    if (_pointCloud) {
      _scene.remove(_pointCloud);
      _pointCloud.geometry.dispose();
      _pointCloud.material.dispose();
      _pointCloud = null;
    }
    const points = data.points || [];
    const colors = data.colors || [];
    if (points.length === 0) return;

    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(points.length * 3);
    const colorArr = new Float32Array(points.length * 3);

    for (let i = 0; i < points.length; i++) {
      positions[i * 3]     = points[i][0];
      positions[i * 3 + 1] = points[i][1];
      positions[i * 3 + 2] = points[i][2];
      if (colors[i]) {
        colorArr[i * 3]     = colors[i][0];
        colorArr[i * 3 + 1] = colors[i][1];
        colorArr[i * 3 + 2] = colors[i][2];
      } else {
        colorArr[i * 3] = colorArr[i * 3 + 1] = colorArr[i * 3 + 2] = 0.7;
      }
    }

    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colorArr, 3));

    const material = new THREE.PointsMaterial({ size: 1.5, vertexColors: true });
    _pointCloud = new THREE.Points(geometry, material);
    _scene.add(_pointCloud);
  }

  // -----------------------------------------------------------------------
  // STL mesh display
  // -----------------------------------------------------------------------
  function showSTL(stlArrayBuffer) {
    if (!_scene || typeof THREE.STLLoader === 'undefined') return;
    if (_mesh) {
      _scene.remove(_mesh);
      _mesh.geometry.dispose();
      _mesh.material.dispose();
      _mesh = null;
    }
    const loader = new THREE.STLLoader();
    const geometry = loader.parse(stlArrayBuffer);
    geometry.computeVertexNormals();
    const material = new THREE.MeshPhongMaterial({ color: 0x00aaff, side: THREE.DoubleSide });
    _mesh = new THREE.Mesh(geometry, material);
    _scene.add(_mesh);

    // Center and fit camera
    geometry.computeBoundingBox();
    const box = geometry.boundingBox;
    const center = new THREE.Vector3();
    box.getCenter(center);
    _mesh.position.sub(center);
    const size = new THREE.Vector3();
    box.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z);
    _camera.position.set(0, maxDim, maxDim * 2);
    _camera.lookAt(0, 0, 0);
  }

  // -----------------------------------------------------------------------
  // Mode switcher
  // -----------------------------------------------------------------------
  function setMode(mode) {
    // mode: 'points' | 'wireframe' | 'solid'
    if (_mesh) {
      _mesh.material.wireframe = (mode === 'wireframe');
      _mesh.visible = (mode !== 'points');
    }
    if (_pointCloud) {
      _pointCloud.visible = (mode === 'points');
    }
  }

  // -----------------------------------------------------------------------
  // Export helpers
  // -----------------------------------------------------------------------
  function downloadModel(format) {
    const url = `/api/model/current?format=${format}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = `model.${format}`;
    a.click();
  }

  // -----------------------------------------------------------------------
  // Polling – auto-refresh point cloud during scan
  // -----------------------------------------------------------------------
  let _pollTimer = null;

  function startPolling(intervalMs = 1000) {
    if (_pollTimer) return;
    _pollTimer = setInterval(async () => {
      try {
        const resp = await fetch('/api/scan/pointcloud');
        const data = await resp.json();
        showPointCloud(data);
      } catch (e) { /* network error – ignore */ }
    }, intervalMs);
  }

  function stopPolling() {
    if (_pollTimer) {
      clearInterval(_pollTimer);
      _pollTimer = null;
    }
  }

  // -----------------------------------------------------------------------
  // Public API
  // -----------------------------------------------------------------------
  return { init, showPointCloud, showSTL, setMode, downloadModel, startPolling, stopPolling };
})();
