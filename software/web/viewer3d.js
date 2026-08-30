class CADViewer {
  constructor(canvas) {
    this.canvas = canvas;
    this.context = canvas.getContext("2d");
    this.triangles = [];
    this.center = [0, 0, 0];
    this.radius = 1;
    this.yaw = -.72;
    this.pitch = -.48;
    this.zoom = 1;
    this.pan = [0, 0];
    this.mode = "solid";
    this.drag = null;
    this._bindEvents();
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas.parentElement);
    this.resize();
  }

  async load(url) {
    const response = await fetch(url);
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || `Erreur HTTP ${response.status}`);
    }
    const buffer = await response.arrayBuffer();
    this.triangles = this._parseSTL(buffer);
    if (!this.triangles.length) throw new Error("Le fichier STL ne contient aucun triangle");
    this._measure();
    this.fit();
    return {
      triangles: this.triangles.length,
      vertices: this.triangles.length * 3,
    };
  }

  _parseSTL(buffer) {
    const prefix = new TextDecoder().decode(buffer.slice(0, Math.min(buffer.byteLength, 256))).trimStart();
    if (prefix.startsWith("solid") && prefix.includes("facet")) return this._parseAsciiSTL(buffer);
    return this._parseBinarySTL(buffer);
  }

  _parseAsciiSTL(buffer) {
    const text = new TextDecoder().decode(buffer);
    const vertices = [];
    const expression = /vertex\s+([-+\deE.]+)\s+([-+\deE.]+)\s+([-+\deE.]+)/g;
    let match;
    while ((match = expression.exec(text)) !== null) {
      vertices.push([Number(match[1]), Number(match[2]), Number(match[3])]);
    }
    const triangles = [];
    for (let index = 0; index + 2 < vertices.length; index += 3) {
      triangles.push([vertices[index], vertices[index + 1], vertices[index + 2]]);
    }
    return triangles;
  }

  _parseBinarySTL(buffer) {
    if (buffer.byteLength < 84) return [];
    const view = new DataView(buffer);
    const count = Math.min(view.getUint32(80, true), Math.floor((buffer.byteLength - 84) / 50));
    const triangles = [];
    let offset = 84;
    for (let triangle = 0; triangle < count; triangle += 1) {
      offset += 12;
      const vertices = [];
      for (let vertex = 0; vertex < 3; vertex += 1) {
        vertices.push([
          view.getFloat32(offset, true),
          view.getFloat32(offset + 4, true),
          view.getFloat32(offset + 8, true),
        ]);
        offset += 12;
      }
      triangles.push(vertices);
      offset += 2;
    }
    return triangles;
  }

  _measure() {
    const minimum = [Infinity, Infinity, Infinity];
    const maximum = [-Infinity, -Infinity, -Infinity];
    this.triangles.flat().forEach(vertex => {
      for (let axis = 0; axis < 3; axis += 1) {
        minimum[axis] = Math.min(minimum[axis], vertex[axis]);
        maximum[axis] = Math.max(maximum[axis], vertex[axis]);
      }
    });
    this.center = minimum.map((value, axis) => (value + maximum[axis]) / 2);
    this.radius = Math.max(1, ...maximum.map((value, axis) => value - minimum[axis])) / 2;
  }

  setMode(mode) {
    this.mode = mode;
    this.render();
  }

  setView(view) {
    const views = {
      iso: [-.72, -.48, "Vue isometrique"],
      front: [0, 0, "Vue de face"],
      top: [0, -Math.PI / 2, "Vue de dessus"],
      right: [Math.PI / 2, 0, "Vue de droite"],
    };
    const selected = views[view] || views.iso;
    [this.yaw, this.pitch] = selected;
    this.render();
    return selected[2];
  }

  fit() {
    this.zoom = 1;
    this.pan = [0, 0];
    this.render();
  }

  resize() {
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    this.canvas.width = Math.max(1, Math.floor(rect.width * ratio));
    this.canvas.height = Math.max(1, Math.floor(rect.height * ratio));
    this.canvas.style.width = `${rect.width}px`;
    this.canvas.style.height = `${rect.height}px`;
    this.render();
  }

  _rotate(vertex) {
    return this._rotateVector([
      vertex[0] - this.center[0],
      vertex[1] - this.center[1],
      vertex[2] - this.center[2],
    ]);
  }

  _rotateVector(vector) {
    const [x, y, z] = vector;
    const cosY = Math.cos(this.yaw);
    const sinY = Math.sin(this.yaw);
    const xYaw = x * cosY + z * sinY;
    const zYaw = -x * sinY + z * cosY;
    const cosX = Math.cos(this.pitch);
    const sinX = Math.sin(this.pitch);
    return [xYaw, y * cosX - zYaw * sinX, y * sinX + zYaw * cosX];
  }

  _project(vertex) {
    const rotated = this._rotate(vertex);
    const scale = Math.min(this.canvas.width, this.canvas.height) * .38 * this.zoom / this.radius;
    return [
      this.canvas.width / 2 + this.pan[0] + rotated[0] * scale,
      this.canvas.height / 2 + this.pan[1] - rotated[1] * scale,
      rotated[2],
    ];
  }

  render() {
    const context = this.context;
    const width = this.canvas.width;
    const height = this.canvas.height;
    context.clearRect(0, 0, width, height);
    this._drawBackground();
    this._drawGrid();
    this._drawAxes();
    if (!this.triangles.length) return;

    const projected = this.triangles.map(triangle => {
      const points = triangle.map(vertex => this._project(vertex));
      return { points, depth: points.reduce((sum, point) => sum + point[2], 0) / 3 };
    }).sort((left, right) => left.depth - right.depth);

    projected.forEach(({ points, depth }) => {
      context.beginPath();
      context.moveTo(points[0][0], points[0][1]);
      context.lineTo(points[1][0], points[1][1]);
      context.lineTo(points[2][0], points[2][1]);
      context.closePath();
      if (this.mode === "points") {
        context.fillStyle = "#5de5f6";
        points.forEach(point => context.fillRect(point[0] - 1.5, point[1] - 1.5, 3, 3));
        return;
      }
      const cross = (points[1][0] - points[0][0]) * (points[2][1] - points[0][1])
        - (points[1][1] - points[0][1]) * (points[2][0] - points[0][0]);
      const shade = Math.max(24, Math.min(72, 48 + depth / this.radius * 18 + (cross > 0 ? 8 : -8)));
      if (this.mode === "solid") {
        context.fillStyle = `hsl(188 72% ${shade}%)`;
        context.fill();
      }
      context.strokeStyle = this.mode === "wireframe" ? "#61e8f7" : "rgba(4, 37, 46, .46)";
      context.lineWidth = this.mode === "wireframe" ? 1.2 : .7;
      context.stroke();
    });
  }

  _drawBackground() {
    const gradient = this.context.createLinearGradient(0, 0, 0, this.canvas.height);
    gradient.addColorStop(0, "#162631");
    gradient.addColorStop(1, "#071016");
    this.context.fillStyle = gradient;
    this.context.fillRect(0, 0, this.canvas.width, this.canvas.height);
  }

  _drawGrid() {
    const context = this.context;
    const spacing = Math.max(30, Math.min(this.canvas.width, this.canvas.height) / 14);
    context.strokeStyle = "rgba(92, 144, 162, .18)";
    context.lineWidth = 1;
    for (let x = this.canvas.width / 2 % spacing; x < this.canvas.width; x += spacing) {
      context.beginPath(); context.moveTo(x, 0); context.lineTo(x, this.canvas.height); context.stroke();
    }
    for (let y = this.canvas.height / 2 % spacing; y < this.canvas.height; y += spacing) {
      context.beginPath(); context.moveTo(0, y); context.lineTo(this.canvas.width, y); context.stroke();
    }
  }

  _drawAxes() {
    const origin = [78, this.canvas.height - 72];
    const axes = [
      { vector: this._rotateVector([1, 0, 0]), color: "#ff5f6d", label: "X" },
      { vector: this._rotateVector([0, 1, 0]), color: "#42d392", label: "Y" },
      { vector: this._rotateVector([0, 0, 1]), color: "#4f8dff", label: "Z" },
    ];
    axes.forEach(axis => {
      const end = [origin[0] + axis.vector[0] * 42, origin[1] - axis.vector[1] * 42];
      this.context.beginPath();
      this.context.moveTo(...origin);
      this.context.lineTo(...end);
      this.context.strokeStyle = axis.color;
      this.context.lineWidth = 3;
      this.context.stroke();
      this.context.fillStyle = axis.color;
      this.context.font = "bold 14px sans-serif";
      this.context.fillText(axis.label, end[0] + 5, end[1] - 4);
    });
  }

  _bindEvents() {
    this.canvas.addEventListener("pointerdown", event => {
      this.canvas.setPointerCapture(event.pointerId);
      this.drag = {
        x: event.clientX,
        y: event.clientY,
        pan: event.shiftKey || event.button === 1 || event.button === 2,
      };
    });
    this.canvas.addEventListener("pointermove", event => {
      if (!this.drag) return;
      const dx = event.clientX - this.drag.x;
      const dy = event.clientY - this.drag.y;
      this.drag.x = event.clientX;
      this.drag.y = event.clientY;
      if (this.drag.pan) {
        this.pan[0] += dx * (window.devicePixelRatio || 1);
        this.pan[1] += dy * (window.devicePixelRatio || 1);
      } else {
        this.yaw += dx * .009;
        this.pitch = Math.max(-Math.PI / 2, Math.min(Math.PI / 2, this.pitch + dy * .009));
      }
      this.render();
    });
    const endDrag = () => { this.drag = null; };
    this.canvas.addEventListener("pointerup", endDrag);
    this.canvas.addEventListener("pointercancel", endDrag);
    this.canvas.addEventListener("contextmenu", event => event.preventDefault());
    this.canvas.addEventListener("wheel", event => {
      event.preventDefault();
      this.zoom = Math.max(.15, Math.min(12, this.zoom * Math.exp(-event.deltaY * .001)));
      this.render();
    }, { passive: false });
  }
}
