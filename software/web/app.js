const HoralScannerUI = (() => {
  const state = {
    activeTab: "scan",
    scanTimer: null,
    pointTimer: null,
    ledTimer: null,
    modelViewer: null,
    cameraRequests: { pi: null, usb: null },
    cameraPollTimers: { pi: null, usb: null },
    cameraObjectUrls: { pi: null, usb: null },
  };

  const byId = id => document.getElementById(id);

  function toast(message, error = false) {
    const element = byId("toast");
    element.textContent = message;
    element.className = `show${error ? " error" : ""}`;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { element.className = ""; }, 5000);
  }

  function formatUserError(error) {
    if (!error) return "Erreur inconnue";
    if (error.hint) return `${error.message} · ${error.hint}`;
    if (error.detail) return `${error.message} · ${error.detail}`;
    return error.message;
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const type = response.headers.get("content-type") || "";
    const payload = type.includes("application/json") ? await response.json() : null;
    if (!response.ok || payload?.success === false) {
      const error = new Error(payload?.error || `Erreur HTTP ${response.status}`);
      error.detail = payload?.detail || null;
      error.hint = payload?.hint || null;
      error.status = response.status;
      throw error;
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
        stopCameraPolling();
        if (tab === "camera-pi") startCameraPolling("pi");
        if (tab === "camera-usb") startCameraPolling("usb");
      });
    });
  }

  async function refreshSystemStatus() {
    try {
      const result = await api("/api/status");
      const status = result.status || {};
      byId("status-dot").className = "status-dot online";
      const simulationSuffix = status.simulation_mode ? " · Simulation" : "";
      byId("status-text").textContent = `Connecte · v${status.version || "?"}${simulationSuffix}`;
      updateCheck("check-api", status.api === "ok");
      updateCheck("check-gpio", status.gpio_driver, status.gpio_error);
      updateCheck("check-stm32", status.stm32_driver, status.stm32_error);
    } catch (error) {
      byId("status-dot").className = "status-dot offline";
      byId("status-text").textContent = "Scanner hors ligne";
      ["check-api", "check-gpio", "check-stm32"].forEach(id => updateCheck(id, false));
    }
  }

  function updateCheck(id, ok, errorMessage) {
    const element = byId(id);
    element.className = `check ${ok ? "ok" : "fail"}`;
    element.textContent = ok ? "✓" : "×";
    element.title = ok ? "" : (errorMessage || "");
  }

  function initializeScan() {
    byId("scan-primary").addEventListener("click", () => {
      byId("scan-start").scrollIntoView({ behavior: "smooth", block: "center" });
    });
    byId("scan-start").addEventListener("click", startScan);
    byId("scan-stop").addEventListener("click", stopScan);
    byId("scan-reconstruct").addEventListener("click", reconstruct);
    document.querySelectorAll(".export-button").forEach(button => {
      button.addEventListener("click", async () => {
        const format = button.dataset.format;
        try {
          const response = await fetch(`/api/model/current?format=${format}`);
          if (!response.ok) {
            const payload = response.headers.get("content-type")?.includes("application/json") ? await response.json() : null;
            throw Object.assign(new Error(payload?.error || "Aucun modele disponible"), {
              detail: payload?.detail || null,
              hint: payload?.hint || "Lancez un scan puis reconstruisez un modele avant export.",
            });
          }
          window.location.href = `/api/model/current?format=${format}`;
        } catch (error) {
          toast(formatUserError(error), true);
        }
      });
    });
    drawEmptyPointCloud();
  }

  async function startScan() {
    try {
      const result = await api("/api/scan/start", { method: "POST" });
      byId("scan-start").disabled = true;
      byId("scan-stop").disabled = false;
      byId("scan-state-badge").className = "badge running";
      byId("scan-state-badge").textContent = result?.status?.simulation ? "Simulation" : "Acquisition";
      state.scanTimer = setInterval(refreshScanStatus, 800);
      state.pointTimer = setInterval(refreshPointCloud, 1200);
      toast(result?.hint || "Acquisition 3D demarree");
    } catch (error) {
      toast(formatUserError(error), true);
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
      toast(formatUserError(error), true);
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
      toast(formatUserError(error), true);
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

  async function refreshWorkshop() {
    const results = await Promise.allSettled([
      api("/api/motor/status"),
      api("/api/fan/status"),
      api("/api/temperature/all"),
    ]);
    if (results[0].status === "fulfilled") updateMotorPositions(results[0].value.status);
    if (results[1].status === "fulfilled") {
      const status = results[1].value.status;
      const pi = status.pi || {};
      byId("fan-pi-state").textContent = pi.speed > 0 ? "Marche" : "Arret";
      byId("temp-pi").textContent = pi.cpu_temperature_c == null ? "--" : `${pi.cpu_temperature_c.toFixed(1)} °C`;
      const boardFan = status.temperature;
      if (boardFan !== undefined) {
        byId("creality-fan-state").textContent = boardFan > 0 ? "Marche" : "Arret";
      }
    }
    if (results[2].status === "fulfilled") {
      const temperatures = results[2].value.status;
      byId("temp-board").textContent = temperatures.board_c == null
        ? "--"
        : Number(temperatures.board_c).toFixed(1);
      byId("creality-temp-state").textContent = temperatures.temperature_c == null
        ? "--"
        : `${Number(temperatures.temperature_c).toFixed(1)} °C`;
      byId("creality-fan-state").textContent = temperatures.fan_on ? "Marche" : "Arret";
      byId("creality-temp-error").textContent = temperatures.connected
        ? "OK"
        : (temperatures.error || "Sonde absente");
      byId("temp-pi").textContent = temperatures.pi_cpu_c == null
        ? "--"
        : `${Number(temperatures.pi_cpu_c).toFixed(1)} °C`;
    }
  }

  async function refreshFanPi4Status() {
    try {
      const s = await api("/api/fan/pi4/status");
      byId("fan-pi4-mode").textContent = "AUTO (Pi4)";
      byId("fan-pi4-temp").textContent = s.temp_c == null ? "--" : `${Number(s.temp_c).toFixed(1)} °C`;
      byId("fan-pi4-speed").textContent = s.fan_percent == null ? "--" : `${s.fan_percent}%`;
      byId("fan-pi4-curve").textContent = `${s.t_min}°C → ${s.t_max}°C`;
    } catch (error) {
      byId("fan-pi4-temp").textContent = "Erreur";
      byId("fan-pi4-speed").textContent = "--";
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
    byId("goto-pose-pi").addEventListener("click", () => gotoCalibrationPose("pi"));
  }

  function setCameraControlsDisabled(camera, disabled) {
    document.querySelectorAll(
      `.camera-refresh[data-camera="${camera}"], .camera-test[data-camera="${camera}"], .camera-calibrate[data-camera="${camera}"]`,
    ).forEach(element => {
      element.disabled = disabled;
    });
  }

  function beginCameraRequest(camera, operation, notifyBusy = true) {
    if (state.cameraRequests[camera]) {
      if (notifyBusy) {
        toast(`Caméra occupée (${state.cameraRequests[camera]}). Réessayez dans un instant.`, true);
      }
      return false;
    }
    state.cameraRequests[camera] = operation;
    setCameraControlsDisabled(camera, true);
    return true;
  }

  function endCameraRequest(camera) {
    state.cameraRequests[camera] = null;
    setCameraControlsDisabled(camera, false);
  }

  function stopCameraPolling(camera = null) {
    const cameras = camera ? [camera] : ["pi", "usb"];
    cameras.forEach(name => {
      clearTimeout(state.cameraPollTimers[name]);
      state.cameraPollTimers[name] = null;
    });
  }

  function scheduleCameraPolling(camera, delay = 5000) {
    stopCameraPolling(camera);
    if (state.activeTab !== `camera-${camera}`) return;
    state.cameraPollTimers[camera] = setTimeout(async () => {
      await refreshCamera(camera, false, true);
      scheduleCameraPolling(camera);
    }, delay);
  }

  function startCameraPolling(camera) {
    scheduleCameraPolling(camera, 0);
  }

  function cameraTimeoutError() {
    const error = new Error("La caméra ne répond pas dans le délai prévu.");
    error.hint = "Attendez la fin de la capture en cours, puis réessayez.";
    error.status = 504;
    return error;
  }

  function localizeCameraError(error) {
    if (error.status === 409) {
      error.message = "La caméra est occupée par une autre capture ou analyse.";
      error.hint = "Attendez un instant; l'actualisation automatique reprendra ensuite.";
    } else if (error.status === 504) {
      error.message = "La caméra a dépassé le délai de réponse.";
      error.hint = "Attendez la fin de l'opération en cours, puis réessayez.";
    }
    return error;
  }

  async function cameraApi(path, options = {}, timeoutMs = 12000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await api(path, { ...options, signal: controller.signal });
    } catch (error) {
      if (error.name === "AbortError") throw cameraTimeoutError();
      throw localizeCameraError(error);
    } finally {
      clearTimeout(timer);
    }
  }

  async function loadCameraFrame(camera, image) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    let objectUrl = null;
    try {
      const response = await fetch(`/api/camera/${camera}/frame?t=${Date.now()}`, {
        signal: controller.signal,
      });
      if (!response.ok) {
        const type = response.headers.get("content-type") || "";
        const payload = type.includes("application/json") ? await response.json() : null;
        const error = new Error(payload?.error || `Erreur HTTP ${response.status}`);
        error.status = response.status;
        throw error;
      }
      objectUrl = URL.createObjectURL(await response.blob());
      image.src = objectUrl;
      await image.decode();
      if (state.cameraObjectUrls[camera]) URL.revokeObjectURL(state.cameraObjectUrls[camera]);
      state.cameraObjectUrls[camera] = objectUrl;
      objectUrl = null;
    } catch (error) {
      if (error.name === "AbortError") throw cameraTimeoutError();
      throw localizeCameraError(error);
    } finally {
      clearTimeout(timer);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    }
  }

  async function refreshCamera(camera, notify = false, polling = false) {
    if (!beginCameraRequest(camera, "actualisation", notify && !polling)) return;
    const image = byId(`camera-${camera}-frame`);
    const badge = byId(`camera-${camera}-status`);
    badge.className = "badge idle";
    badge.textContent = "Connexion...";
    try {
      const status = await cameraApi(`/api/camera/${camera}/status`, {}, 10000);
      if (!status.available) {
        throw new Error(status.error || "Camera indisponible");
      }
      await loadCameraFrame(camera, image);
      badge.className = "badge running";
      badge.textContent = "Disponible";
      badge.title = "";
      if (notify) toast("Image actualisee");
    } catch (error) {
      badge.className = "badge idle";
      badge.textContent = error.status === 409 ? "Occupée" : error.status === 504 ? "Délai dépassé" : "Indisponible";
      badge.title = formatUserError(error);
      if (notify) toast(formatUserError(error), true);
    } finally {
      endCameraRequest(camera);
    }
  }

  async function testCamera(camera) {
    stopCameraPolling(camera);
    if (!beginCameraRequest(camera, "analyse")) {
      scheduleCameraPolling(camera);
      return;
    }
    const badge = byId(`camera-${camera}-status`);
    badge.className = "badge idle";
    badge.textContent = "Analyse...";
    try {
      const response = await cameraApi(`/api/camera/${camera}/test`, { method: "POST" });
      renderCameraMetrics(camera, response.result);
      badge.className = "badge running";
      badge.textContent = "Disponible";
      badge.title = "";
      toast("Analyse camera terminee");
    } catch (error) {
      badge.className = "badge idle";
      badge.textContent = error.status === 409 ? "Occupée" : error.status === 504 ? "Délai dépassé" : "Erreur";
      badge.title = formatUserError(error);
      toast(formatUserError(error), true);
    } finally {
      endCameraRequest(camera);
      scheduleCameraPolling(camera);
    }
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
    stopCameraPolling(camera);
    if (!beginCameraRequest(camera, "analyse")) {
      scheduleCameraPolling(camera);
      return;
    }
    const badge = byId(`camera-${camera}-status`);
    badge.className = "badge idle";
    badge.textContent = "Analyse...";
    const result = byId("calibration-result");
    result.className = "calibration-result";
    result.textContent = "Analyse de la mire en cours...";
    try {
      const response = await cameraApi(`/api/camera/${camera}/test`, { method: "POST" });
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
      badge.className = "badge running";
      badge.textContent = "Disponible";
      badge.title = "";
    } catch (error) {
      const message = formatUserError(error);
      result.textContent = message;
      badge.className = "badge idle";
      badge.textContent = error.status === 409 ? "Occupée" : error.status === 504 ? "Délai dépassé" : "Erreur";
      badge.title = message;
      toast(message, true);
    } finally {
      endCameraRequest(camera);
      scheduleCameraPolling(camera);
    }
  }

  async function gotoCalibrationPose(camera) {
    const resultEl = byId("calibration-pose-result");
    const label = camera === "pi" ? "Pi Camera V3" : camera;
    resultEl.className = "calibration-result";
    resultEl.textContent = `Deplacement vers la pose ${label} en cours…`;
    try {
      const response = await api(`/api/calibration/pose/${camera}`, { method: "POST" });
      resultEl.replaceChildren();
      const title = document.createElement("h2");
      title.textContent = response.label;
      const desc = document.createElement("p");
      desc.textContent = response.description;
      const details = document.createElement("p");
      details.className = "muted";
      const z = response.target.z_mm !== null ? ` · Z ${response.target.z_mm} mm` : "";
      details.textContent = `X ${response.target.x_mm} mm · Y ${response.target.y_mm} mm${z}`;
      resultEl.append(title, desc, details);
      toast(`Pose ${response.label} atteinte`);
    } catch (error) {
      resultEl.textContent = error.message;
      toast(error.message, true);
    }
  }

  async function alignLaser(side) {
    const resultEl = byId("laser-align-result");
    const label = side === "left" ? "gauche" : "droit";
    resultEl.className = "calibration-result";
    resultEl.textContent = `Analyse du laser ${label} en cours…`;
    try {
      const response = await cameraApi(`/api/laser/align/${side}`, { method: "POST" });
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
      const message = formatUserError(error);
      resultEl.textContent = message;
      toast(message, true);
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
    resultEl.className = "calibration-result";
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
    refreshFanPi4Status();
    setInterval(refreshSystemStatus, 10000);
    setInterval(refreshWorkshop, 5000);
    setInterval(refreshFanPi4Status, 2000);
  }

  document.addEventListener("DOMContentLoaded", initialize);
  return { refreshSystemStatus };
})();
