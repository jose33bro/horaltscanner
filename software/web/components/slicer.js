/**
 * Slicer - PrusaSlicer UI component
 */

const SlicerUI = (() => {
  let _gcodeb64 = '';

  function init() {
    const sliceBtn = document.getElementById('btn-slice');
    const downloadBtn = document.getElementById('btn-download-gcode');
    const addQueueBtn = document.getElementById('btn-add-queue');

    if (sliceBtn) sliceBtn.addEventListener('click', _doSlice);
    if (downloadBtn) downloadBtn.addEventListener('click', _downloadGcode);
    if (addQueueBtn) addQueueBtn.addEventListener('click', _addToQueue);
  }

  async function _doSlice() {
    // Get current model from reconstruction
    const modelResp = await fetch('/api/model/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ format: 'stl' }),
    });
    if (!modelResp.ok) {
      _setStatus('No model available – scan and reconstruct first.');
      return;
    }
    const modelData = await modelResp.json();

    const layerHeight = parseFloat(document.getElementById('slicer-layer-height')?.value || '0.2');
    const infill      = parseInt(document.getElementById('slicer-infill')?.value || '20', 10);
    const support     = document.getElementById('slicer-support')?.checked || false;
    const nozzleTemp  = parseInt(document.getElementById('slicer-nozzle-temp')?.value || '200', 10);

    _setStatus('Slicing… please wait');

    const resp = await fetch('/api/slice', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model_data: modelData.data_b64,
        layer_height: layerHeight,
        infill,
        support,
        nozzle_temp: nozzleTemp,
      }),
    });
    const result = await resp.json();
    if (result.ok) {
      _gcodeb64 = result.gcode_b64;
      _setStatus('✅ Slicing complete – G-code ready');
      document.getElementById('btn-download-gcode')?.removeAttribute('disabled');
      document.getElementById('btn-add-queue')?.removeAttribute('disabled');
    } else {
      _setStatus(`❌ Slice error: ${result.error}`);
    }
  }

  function _downloadGcode() {
    if (!_gcodeb64) return;
    const blob = new Blob([atob(_gcodeb64)], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'model.gcode';
    a.click();
    URL.revokeObjectURL(url);
  }

  async function _addToQueue() {
    if (!_gcodeb64) return;
    const name = `scan_${new Date().toISOString().slice(0, 19)}.gcode`;
    const resp = await fetch('/api/queue/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gcode_b64: _gcodeb64, name }),
    });
    const result = await resp.json();
    if (result.ok) {
      _setStatus(`✅ Added to queue (id: ${result.id})`);
      if (typeof QueueUI !== 'undefined') QueueUI.refresh();
    } else {
      _setStatus(`❌ ${result.error}`);
    }
  }

  function _setStatus(msg) {
    const el = document.getElementById('slicer-status');
    if (el) el.textContent = msg;
  }

  return { init };
})();
