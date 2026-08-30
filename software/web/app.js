const HoralScannerUI = (() => {
  const state = {
    activeTab: "scan",
    scanTimer: null,
    pointTimer: null,
    ledTimer: null,
    modelViewer: null,
  };

  const byId = id => document.getElementById(id);

  function toast(message, error = false) {
    const element = byId("toast");
    element.textContent = message;
    element.className = `show${error ? " error" : ""}`;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { element.className = ""; }, 3500);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const type = response.headers.get("content-type") || "";
    const payload = type.includes("application/json") ? await response.json() : null;
    if (!response.ok || payload?.success === false) {
      throw new Error(payload?.error || `Erreur HTTP ${response.status}`);
    }
    return payload;
  }

  function initializeTabs() {
    document.querySelectorAll(".nav-tab").forEach(button => {
      button.addEventListener("click", () => {
        const tab = button.dataset.tab;
        state.activeTab = tab;
        document.querySelectorAll(".nav-tab").forEach(item => item.classList.toggle("active", item === button));
        document.querySelectorAll(".tab-page").forEach(page => page.classList.toggle("active", page.id === `tab-${tab}`));
        if (tab === "model") {
          initializeModelViewer();
          loadModel(false);
        }
        if (tab === "camera-pi") refreshCamera("pi");
        if (tab === "camera-usb") refreshCamera("usb");
      });
    });
  }

  async function refreshSystemStatus() {
    try {
      const result = await api("/api/status");
      const status = result.status || {};
      byId("status-dot").className = "status-dot online";
      byId("status-text").textContent = `Connecte · v${status.version || "?"}`;
      updateCheck("check-api", status.api === "ok");
      updateCheck("check-gpio", status.gpio_driver);
      updateCheck("check-stm32", status.stm32_driver);
    } catch (error) {
      byId("status-dot").className = "status-dot offline";
      byId("status-text").textContent = "Scanner hors ligne";
      ["check-api", "check-gpio", "check-stm32"].forEach(id => updateCheck(id, false));
    }
  }

  function updateCheck(id, ok) {
    const element = byId(id);
    element.className = `check ${ok ? "ok" : "fail"}`;
    element.textContent = ok ? "✓" : "×";
  }

  function initializeScan() {
    byId("scan-primary").addEventListener("click", () => {
      byId("scan-start").scrollIntoView({ behavior: "smooth", block: "center" });
    });
    byId("scan-start").addEventListener("click", startScan);
    byId("scan-stop").addEventListener("click", stopScan);
    byId("scan-reconstruct").addEventListener("click", reconstruct);
    document.querySelectorAll(".export-button").forEach(button => {
      button.addEventListener("click", () => {
        window.location.href = `/api/model/current?format=${button.dataset.format}`;
      });
    });
    drawEmptyPointCloud();
  }

  async function startScan() {
    try {
      await api("/api/scan/start", { method: "POST" });
      byId("scan-start").disabled = true;
      byId("scan-stop").disabled = false;
      byId("scan-state-badge").className = "badge running";
      byId("scan-state-badge").textContent = "Acquisition";
      state.scanTimer = setInterval(refreshScanStatus, 800);
      state.pointTimer = setInterval(refreshPointCloud, 1200);
      toast("Acquisition 3D demarree");
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function stopScan() {
    try {
      await api("/api/scan/stop", { method: "POST" });
      stopScanTimers();
      byId("scan-start").disabled = false;
      byId("scan-stop").disabled = true;
      byId("scan-state-badge").className = "badge idle";
      byId("scan-state-badge").textContent = "Termine";
      await refreshScanStatus();
      await refreshPointCloud();
      toast("Acquisition arretee");
    } catch (error) {
      toast(error.message, true);
    }
  }

  function stopScanTimers() {
    clearInterval(state.scanTimer);
    clearInterval(state.pointTimer);
    state.scanTimer = null;
    state.pointTimer = null;
  }

  async function refreshScanStatus() {
    try {
      const result = await api("/api/scan/status");
      const status = result.status;
      byId("stat-points").textContent = status.points.toLocaleString("fr-FR");
      byId("stat-time").textContent = formatTime(status.elapsed_s);
      byId("stat-quality").textContent = `${Math.round(status.quality)}%`;
    } catch (_) {}
  }

  function formatTime(seconds) {
    const value = Math.max(0, Math.floor(seconds || 0));
    return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
  }

  async function refreshPointCloud() {
    try {
      const result = await api("/api/scan/pointcloud");
      drawPointCloud(result.points || []);
    } catch (_) {}
  }

  function drawEmptyPointCloud() {
    drawPointCloud([]);
    const canvas = byId("pointcloud-canvas");
    const context = canvas.getContext("2d");
    context.fillStyle = "rgba(139, 154, 172, .8)";
    context.font = "600 18px sans-serif";
    context.textAlign = "center";
    context.fillText("Le nuage de points apparaitra pendant l'acquisition", canvas.width / 2, canvas.height / 2);
  }

  function drawPointCloud(points, opacity = .85) {
    const canvas = byId("pointcloud-canvas");
    const context = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;
    context.clearRect(0, 0, width, height);
    const gradient = context.createRadialGradient(width / 2, height / 2, 0, width / 2, height / 2, width * .55);
    gradient.addColorStop(0, "#122b39");
    gradient.addColorStop(1, "#05090d");
    context.fillStyle = gradient;
    context.fillRect(0, 0, width, height);
    context.strokeStyle = "rgba(40, 91, 111, .28)";
    context.lineWidth = 1;
    for (let x = 0; x < width; x += 48) {
      context.beginPath(); context.moveTo(x, 0); context.lineTo(x, height); context.stroke();
    }
    for (let y = 0; y < height; y += 48) {
      context.beginPath(); context.moveTo(0, y); context.lineTo(width, y); context.stroke();
    }
    const scale = Math.min(width, height) / 150;
    context.fillStyle = `rgba(40, 218, 240, ${opacity})`;
    points.slice(-12000).forEach(([x, y, z]) => {
      const perspective = 1 + (z || 0) / 300;
      const px = width / 2 + x * scale * perspective;
      const py = height / 2 - y * scale * perspective;
      const size = Math.max(1, 2.2 * perspective);
      context.fillRect(px, py, size, size);
    });
  }

  async function reconstruct() {
    byId("scan-reconstruct").disabled = true;
    try {
      await api("/api/model/reconstruct", { method: "POST" });
      byId("scan-state-badge").className = "badge running";
      byId("scan-state-badge").textContent = "Modele pret";
      initializeModelViewer();
      await loadModel(false);
      toast("Reconstruction terminee");
    } catch (error) {
      toast(error.message, true);
    } finally {
      byId("scan-reconstruct").disabled = false;
    }
  }

  function initializeModelViewer() {
    if (state.modelViewer) return;
    state.modelViewer = new CADViewer(byId("model-canvas"));
    byId("model-reload").addEventListener("click", () => loadModel(true));
    byId("model-fit").addEventListener("click", () => state.modelViewer.fit());
    document.querySelectorAll("[data-render-mode]").forEach(button => {
      button.addEventListener("click", () => {
        document.querySelectorAll("[data-render-mode]").forEach(item => item.classList.toggle("active", item === button));
        state.modelViewer.setMode(button.dataset.renderMode);
      });
    });
    document.querySelectorAll("[data-view]").forEach(button => {
      button.addEventListener("click", () => {
        byId("model-view-label").textContent = state.modelViewer.setView(button.dataset.view);
      });
    });
  }

  async function loadModel(notify = true) {
    initializeModelViewer();
    byId("model-status").textContent = "Chargement...";
    try {
      const statistics = await state.modelViewer.load(`/api/model/current?format=stl&t=${Date.now()}`);
      byId("model-empty").classList.add("hidden");
      byId("model-triangle-count").textContent = `${statistics.triangles.toLocaleString("fr-FR")} triangles`;
      byId("model-vertex-count").textContent = `${statistics.vertices.toLocaleString("fr-FR")} sommets`;
      byId("model-mesh-stats").textContent = `${statistics.triangles.toLocaleString("fr-FR")} triangles`;
      byId("model-status").textContent = "Pret";
      if (notify) toast("Modele 3D charge");
    } catch (error) {
      byId("model-empty").classList.remove("hidden");
      byId("model-status").textContent = "Indisponible";
      if (notify) toast(error.message, true);
    }
  }

  function initializeWorkshop() {
    document.querySelectorAll(".move-axis").forEach(button => {
      button.addEventListener("click", () => moveAxis(button.dataset.axis));
    });
    byId("home-all").addEventListener("click", () => postSimple("/api/home/all", "Origine terminee"));
    byId("emergency-stop").addEventListener("click", emergencyStop);
    document.querySelectorAll("[data-laser]").forEach(input => {
      input.addEventListener("change", () => setLaser(input.dataset.laser, input.checked));
    });
    ["r", "g", "b"].forEach(color => {
      byId(`led-${color}`).addEventListener("input", updateLed);
    });
    byId("led-off").addEventListener("click", () => setLedValues(0, 0, 0));
    byId("lidar-read").addEventListener("click", readLidar);
    byId("lidar-calibrate").addEventListener("click", calibrateLidar);
    ["creality", "temperature"].forEach(fan => {
      byId(`fan-${fan}`).addEventListener("input", () => {
        byId(`fan-${fan}-value`).textContent = `${byId(`fan-${fan}`).value}%`;
      });
    });
    byId("apply-fans").addEventListener("click", applyFans);
  }

  async function moveAxis(axis) {
    const mm = Number(byId(`move-${axis}`).value);
    try {
      const result = await api(`/api/move/${axis}`, { method: "POST", body: JSON.stringify({ mm }) });
      updateMotorPositions(result.status);
      toast(`Axe ${axis.toUpperCase()} deplace`);
    } catch (error) { toast(error.message, true); }
  }

  function updateMotorPositions(status) {
    const positions = status?.positions || {};
    ["x", "y", "z"].forEach(axis => {
      if (positions[axis] !== undefined) byId(`pos-${axis}`).textContent = Number(positions[axis]).toFixed(2);
    });
  }

  async function emergencyStop() {
    try {
      await Promise.all([
        api("/api/motor/stop", { method: "POST", body: JSON.stringify({ axis: "all" }) }),
        setLaser("left", false),
        setLaser("right", false),
      ]);
      document.querySelectorAll("[data-laser]").forEach(input => { input.checked = false; });
      toast("Materiel arrete");
    } catch (error) { toast(error.message, true); }
  }

  async function setLaser(side, enabled) {
    try {
      return await api(`/api/laser/${side}`, {
        method: "POST",
        body: JSON.stringify({ state: enabled }),
      });
    } catch (error) {
      byId(`laser-${side}`).checked = !enabled;
      toast(error.message, true);
      throw error;
    }
  }

  function updateLed() {
    const values = ["r", "g", "b"].map(color => Number(byId(`led-${color}`).value));
    ["r", "g", "b"].forEach((color, index) => {
      byId(`led-${color}-value`).textContent = values[index];
    });
    byId("rgb-preview").style.background = `rgb(${values.join(",")})`;
    clearTimeout(state.ledTimer);
    state.ledTimer = setTimeout(() => sendLed(...values), 180);
  }

  function setLedValues(r, g, b) {
    [["r", r], ["g", g], ["b", b]].forEach(([color, value]) => { byId(`led-${color}`).value = value; });
    updateLed();
  }

  async function sendLed(r, g, b) {
    try {
      await api("/api/led/color", { method: "POST", body: JSON.stringify({ r, g, b }) });
    } catch (error) { toast(error.message, true); }
  }

  async function readLidar() {
    byId("lidar-badge").textContent = "Mesure...";
    try {
      const result = await api("/api/lidar/read", { method: "POST" });
      byId("lidar-distance").textContent = result.distance_mm.toFixed(1);
      byId("lidar-badge").className = "badge running";
      byId("lidar-badge").textContent = "Connecte";
    } catch (error) {
      byId("lidar-badge").className = "badge idle";
      byId("lidar-badge").textContent = "Erreur";
      toast(error.message, true);
    }
  }

  async function calibrateLidar() {
    const knownDistance = Number(byId("lidar-known-distance").value);
    try {
      const result = await api("/api/lidar/calibrate", {
        method: "POST",
        body: JSON.stringify({ known_distance_mm: knownDistance }),
      });
      toast(`TF-Luna calibre, offset ${result.offset_mm} mm`);
      await readLidar();
    } catch (error) { toast(error.message, true); }
  }

  async function applyFans() {
    try {
      await Promise.all(["creality", "temperature"].map(fan => api(`/api/fan/${fan}`, {
        method: "POST",
        body: JSON.stringify({ percent: Number(byId(`fan-${fan}`).value) }),
      })));
      toast("Ventilateurs Creality mis a jour");
    } catch (error) { toast(error.message, true); }
  }

  async function refreshWorkshop() {
    const results = await Promise.allSettled([
      api("/api/motor/status"),
      api("/api/fan/status"),
      api("/api/temperature/board"),
    ]);
    if (results[0].status === "fulfilled") updateMotorPositions(results[0].value.status);
    if (results[1].status === "fulfilled") {
      const status = results[1].value.status;
      const pi = status.pi || {};
      byId("fan-pi-state").textContent = pi.speed > 0 ? "Marche" : "Arret";
      byId("temp-pi").textContent = pi.cpu_temperature_c == null ? "--" : `${pi.cpu_temperature_c.toFixed(1)} °C`;
      [["creality", status.creality], ["temperature", status.temperature]].forEach(([fan, speed]) => {
        if (speed !== undefined) {
          const percent = Math.round(speed * 100);
          byId(`fan-${fan}`).value = percent;
          byId(`fan-${fan}-value`).textContent = `${percent}%`;
        }
      });
    }
    if (results[2].status === "fulfilled") {
      byId("temp-board").textContent = Number(results[2].value.status.board_c).toFixed(1);
    }
  }

  function initializeCameras() {
    document.querySelectorAll(".camera-refresh").forEach(button => {
      button.addEventListener("click", () => refreshCamera(button.dataset.camera, true));
    });
    document.querySelectorAll(".camera-test").forEach(button => {
      button.addEventListener("click", () => testCamera(button.dataset.camera));
    });
    document.querySelectorAll(".camera-calibrate").forEach(button => {
      button.addEventListener("click", () => calibrationTest(button.dataset.camera));
    });
    document.querySelectorAll(".camera-goto-pose").forEach(button => {
      button.addEventListener("click", () => gotoCameraCalibrationPose(button.dataset.camera));
    });
    document.querySelectorAll(".camera-save-pose").forEach(button => {
      button.addEventListener("click", () => saveCameraScanPose(button.dataset.camera));
    });
    document.querySelectorAll(".camera-goto-scan-pose").forEach(button => {
      button.addEventListener("click", () => gotoCameraScanPose(button.dataset.camera));
    });
    byId("align-laser-left").addEventListener("click", () => alignLaser("left"));
    byId("align-laser-right").addEventListener("click", () => alignLaser("right"));
  }

  async function refreshCamera(camera, notify = false) {
    const image = byId(`camera-${camera}-frame`);
    const badge = byId(`camera-${camera}-status`);
    badge.className = "badge idle";
    badge.textContent = "Connexion...";
    try {
      await api(`/api/camera/${camera}/status`);
      image.src = `/api/camera/${camera}/frame?t=${Date.now()}`;
      await image.decode();
      badge.className = "badge running";
      badge.textContent = "Disponible";
      if (notify) toast("Image actualisee");
    } catch (error) {
      badge.className = "badge idle";
      badge.textContent = "Indisponible";
      if (notify) toast(error.message, true);
    }
  }

  async function testCamera(camera) {
    try {
      const response = await api(`/api/camera/${camera}/test`, { method: "POST" });
      renderCameraMetrics(camera, response.result);
      toast("Analyse camera terminee");
    } catch (error) { toast(error.message, true); }
  }

  function renderCameraMetrics(camera, result) {
    const target = byId(`camera-${camera}-metrics`);
    const checkerboard = result.checkerboard_found
      ? `${result.checkerboard_columns} × ${result.checkerboard_rows}`
      : "Non detectee";
    const rows = [
      ["Resolution", `${result.width} × ${result.height}`],
      ["Luminosite", result.brightness],
      ["Nettete", result.sharpness],
      ["Mire", checkerboard],
    ];
    if (result.checkerboard_found) {
      rows.push(
        ["Decalage horizontal", `${formatSigned(result.center_offset_x_px)} px`],
        ["Decalage vertical", `${formatSigned(result.center_offset_y_px)} px`],
      );
    }
    target.replaceChildren(...rows.map(([label, value]) => {
      const row = document.createElement("div");
      const name = document.createElement("span");
      const metric = document.createElement("b");
      name.textContent = label;
      metric.textContent = value;
      row.append(name, metric);
      return row;
    }));
  }

  function formatSigned(value) {
    const number = Number(value);
    return `${number > 0 ? "+" : ""}${number.toFixed(1)}`;
  }

  async function calibrationTest(camera) {
    const result = byId("calibration-result");
    result.className = "calibration-result";
    result.textContent = "Analyse de la mire en cours...";
    try {
      const response = await api(`/api/camera/${camera}/test`, { method: "POST" });
      const data = response.result;
      result.replaceChildren();
      const title = document.createElement("h2");
      title.textContent = camera === "pi" ? "Pi Camera V3 NoIR" : "Logitech C270";
      const verdict = document.createElement("p");
      verdict.textContent = data.checkerboard_found
        ? `Mire ${data.checkerboard_columns} × ${data.checkerboard_rows} detectee.`
        : "Mire non detectee. Ajustez le cadrage, la nettete ou l'eclairage.";
      const details = document.createElement("p");
      details.className = "muted";
      details.textContent = data.checkerboard_found
        ? `Decalage du centre: horizontal ${formatSigned(data.center_offset_x_px)} px · vertical ${formatSigned(data.center_offset_y_px)} px`
        : `Resolution ${data.width} × ${data.height} · luminosite ${data.brightness} · nettete ${data.sharpness}`;
      result.append(title, verdict, details);
    } catch (error) {
      result.textContent = error.message;
      toast(error.message, true);
    }
  }

  async function alignLaser(side) {
    const resultEl = byId("laser-align-result");
    const label = side === "left" ? "gauche" : "droit";
    resultEl.className = "calibration-result";
    resultEl.textContent = `Analyse du laser ${label} en cours…`;
    try {
      const response = await api(`/api/laser/align/${side}`, { method: "POST" });
      resultEl.replaceChildren();
      const title = document.createElement("h2");
      title.textContent = `Laser ${label}`;
      const verdict = document.createElement("p");
      verdict.textContent = response.instruction;
      resultEl.append(title, verdict);
      if (response.line_detected) {
        const details = document.createElement("p");
        details.className = "muted";
        details.textContent =
          `Angle mesuré: ${formatSigned(response.angle_deg)}° · Correction: ${formatSigned(response.correction_deg)}°`;
        resultEl.append(details);
      }
    } catch (error) {
      resultEl.textContent = error.message;
      toast(error.message, true);
    }
  }

  async function postSimple(path, successMessage) {
    try {
      await api(path, { method: "POST" });
      toast(successMessage);
    } catch (error) { toast(error.message, true); }
  }

  async function gotoCameraCalibrationPose(camera) {
    const resultEl = byId("pose-result");
    const label = camera === "pi" ? "Pi Camera V3" : "Logitech C270";
    resultEl.className = "calibration-result";
    resultEl.textContent = `Déplacement vers la pose de calibration ${label}…`;
    try {
      const response = await api(`/api/camera/${camera}/goto_calibration_pose`, { method: "POST" });
      resultEl.replaceChildren();
      const title = document.createElement("h2");
      title.textContent = label;
      const verdict = document.createElement("p");
      verdict.textContent = response.instruction;
      const details = document.createElement("p");
      details.className = "muted";
      const axes = Object.entries(response.pose)
        .map(([ax, val]) => `${ax.toUpperCase()} = ${Number(val).toFixed(1)} mm`)
        .join(" · ");
      const lidar = renderLidarValidation(response, resultEl);
      details.textContent = lidar ? `${axes} · ${lidar}` : axes;
      resultEl.append(title, verdict, details);
      toast(response.instruction);
    } catch (error) {
      resultEl.textContent = error.message;
      toast(error.message, true);
    }
  }

  async function saveCameraScanPose(camera) {
    const resultEl = byId("scan-pose-result");
    const label = camera === "pi" ? "Pi Camera V3" : "Logitech C270";
    resultEl.className = "calibration-result";
    resultEl.textContent = `Mémorisation de la pose ${label}…`;
    try {
      const response = await api(`/api/camera/${camera}/save_scan_pose`, { method: "POST" });
      resultEl.replaceChildren();
      const title = document.createElement("h2");
      title.textContent = label;
      const verdict = document.createElement("p");
      verdict.textContent = response.instruction;
      const details = document.createElement("p");
      details.className = "muted";
      const axes = Object.entries(response.saved_pose)
        .map(([ax, val]) => `${ax.toUpperCase()} = ${Number(val).toFixed(1)} mm`)
        .join(" · ");
      details.textContent = axes;
      resultEl.append(title, verdict, details);
      toast(response.instruction);
    } catch (error) {
      resultEl.textContent = error.message;
      toast(error.message, true);
    }
  }

  async function gotoCameraScanPose(camera) {
    const resultEl = byId("scan-pose-result");
    const label = camera === "pi" ? "Pi Camera V3" : "Logitech C270";
    resultEl.className = "calibration-result";
    resultEl.textContent = `Retour à la pose de scan ${label}…`;
    try {
      const response = await api(`/api/camera/${camera}/goto_scan_pose`, { method: "POST" });
      resultEl.replaceChildren();
      const title = document.createElement("h2");
      title.textContent = label;
      const verdict = document.createElement("p");
      verdict.textContent = response.instruction;
      const details = document.createElement("p");
      details.className = "muted";
      const axes = Object.entries(response.pose)
        .map(([ax, val]) => `${ax.toUpperCase()} = ${Number(val).toFixed(1)} mm`)
        .join(" · ");
      const lidar = renderLidarValidation(response, resultEl);
      details.textContent = lidar ? `${axes} · ${lidar}` : axes;
      resultEl.append(title, verdict, details);
      toast(response.instruction);
    } catch (error) {
      resultEl.textContent = error.message;
      toast(error.message, true);
    }
  }

  function renderLidarValidation(response, resultEl) {
    if (response.lidar_distance_mm == null) return null;
    const tolerance = Number(response.lidar_tolerance_mm ?? 0);
    const distance = Number(response.lidar_distance_mm).toFixed(1);
    const expected = Number(response.lidar_expected_mm ?? 0).toFixed(1);
    if (response.lidar_out_of_tolerance) {
      resultEl.className = "calibration-result warning";
      return `TF-Luna ${distance} mm (cible ${expected} ±${tolerance.toFixed(1)} mm)`;
    }
    return `TF-Luna ${distance} mm`;
  }

  function initialize() {
    initializeTabs();
    initializeScan();
    initializeWorkshop();
    initializeCameras();
    byId("refresh-button").addEventListener("click", async () => {
      await Promise.all([refreshSystemStatus(), refreshWorkshop(), refreshScanStatus()]);
      toast("Donnees actualisees");
    });
    refreshSystemStatus();
    refreshWorkshop();
    refreshScanStatus();
    setInterval(refreshSystemStatus, 10000);
    setInterval(refreshWorkshop, 5000);
  }

  document.addEventListener("DOMContentLoaded", initialize);
  return { refreshSystemStatus };
})();
