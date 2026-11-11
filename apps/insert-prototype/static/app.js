const fields = [
  "length", "width", "height", "thickness", "kerf", "finger_length",
];

let dimMode = "inside";
let lidMode = "none";
let tabFit = "inner";
let slideDir = "back";
let slideCount = 2;
let latchCount = 1;
let latchSide = "front";

function roundMm(n) {
  return Math.round(n * 100) / 100;
}

function el(id) {
  return document.getElementById(id);
}

function readParams() {
  const params = {};
  for (const f of fields) {
    const v = el(f).value;
    params[f] = parseFloat(v);
  }
  params.floor = el("floor").checked;
  const wallT = params.thickness;
  if (dimMode === "inside") {
    params.length += 2 * wallT;
    params.width += 2 * wallT;
    if (params.floor) params.height += wallT;
  }
  params.lid = lidMode;
  let side = parseFloat(el("lid-height").value);
  if (!Number.isFinite(side)) side = 15;
  if (dimMode === "outside") side -= wallT;
  params.lid_height = Math.min(80, Math.max(wallT, side));
  params.lid_tabs = el("lid-tabs-on").checked;
  const tabHeight = parseFloat(el("lid-tab-height").value);
  params.lid_tab_height = Math.min(40, Math.max(wallT, Number.isFinite(tabHeight) ? tabHeight : 12));
  params.lid_tab_fit = tabFit;
  params.lid_tab_corners = [...document.querySelectorAll("#lid-tab-corners input:checked")].map(
    (input) => input.dataset.corner
  );
  params.lid_slide = slideDir;
  params.lid_slide_count = slideCount;
  const slideTab = parseFloat(el("lid-slide-tab").value);
  params.lid_slide_tab = Math.min(80, Math.max(wallT, Number.isFinite(slideTab) ? slideTab : 20));
  params.lid_latch_side = latchSide;
  params.lid_latch_count = latchCount === 2 ? 2 : 1;
  const latchLoops = parseInt(el("lid-latch-loops").value, 10);
  params.lid_latch_loops = Math.min(8, Math.max(2, Number.isFinite(latchLoops) ? latchLoops : 4));
  const latchBeam = parseFloat(el("lid-latch-beam").value);
  params.lid_latch_beam = Math.min(4, Math.max(1, Number.isFinite(latchBeam) ? latchBeam : 2));
  const latchWidth = parseFloat(el("lid-latch-width").value);
  params.lid_latch_width = Math.min(80, Math.max(14, Number.isFinite(latchWidth) ? latchWidth : 30));
  params.dividers = [];
  const wall = params.thickness;
  document.querySelectorAll("#dividers .divider-row").forEach((row) => {
    const num = (cls) => parseFloat(row.querySelector(cls).value);
    const gap = (cls) => {
      const n = num(cls);
      const value = Number.isFinite(n) ? Math.max(0, n) : 0;
      if (row.dataset.heightUnit === "pct") return (value / 100) * params.height;
      return value;
    };
    params.dividers.push({
      x1: num(".x1") + wall,
      y1: num(".y1") + wall,
      x2: num(".x2") + wall,
      y2: num(".y2") + wall,
      bottom: gap(".h-bottom"),
      top: gap(".h-top"),
      tilt: Math.max(-75, Math.min(75, Number.isFinite(num(".h-tilt")) ? num(".h-tilt") : 0)),
      floor_fingers: row.querySelector(".h-floor-fingers").checked,
      top_fingers: row.querySelector(".h-top-fingers").checked,
      label: (row.dataset.label || "").replace(/\s+/g, " ").trim().slice(0, 40),
    });
  });
  return params;
}

function updateDimLabels() {
  const inside = dimMode === "inside";
  el("dim-inside").setAttribute("aria-pressed", inside ? "true" : "false");
  el("dim-outside").setAttribute("aria-pressed", inside ? "false" : "true");
  el("length-label").textContent = inside ? "Length ID (mm)" : "Length OD (mm)";
  el("width-label").textContent = inside ? "Width ID (mm)" : "Width OD (mm)";
  el("tip-length").textContent = inside
    ? "Inside length, measured between the inner faces of the walls. The outside length is this plus twice the material thickness."
    : "Outside length, measured across the outside of the walls. The inside length is this minus twice the material thickness.";
  el("tip-width").textContent = inside
    ? "Inside width, measured between the inner faces of the walls. The outside width is this plus twice the material thickness."
    : "Outside width, measured across the outside of the walls. The inside width is this minus twice the material thickness.";
  el("height-label").textContent = inside ? "Height ID (mm)" : "Height OD (mm)";
  el("tip-height").textContent = inside
    ? "Inside height, from the top of the floor to the top of the walls. The outside height is this plus the material thickness. With no floor, inside and outside height are the same. When a lid makes the box taller, the note under this box shows the overall outside height."
    : "Outside height, from the bottom of the box to the top of the walls. With a floor, the inside height is this minus the material thickness. With no floor, they are the same. When a lid makes the box taller, the note under this box shows the overall outside height.";
  el("side-height-label").textContent = inside ? "Side height ID (mm)" : "Side height OD (mm)";
}

function outsideHeight() {
  const shown = parseFloat(el("height").value);
  const height = Number.isFinite(shown) ? shown : 0;
  if (dimMode === "inside" && el("floor").checked) return height + materialThickness();
  return height;
}

function syncDimLimits() {
  const t = materialThickness();
  const inside = dimMode === "inside";
  const floorT = el("floor").checked ? t : 0;
  el("height").min = String(roundMm(Math.max(0.1, 10 - (inside ? floorT : 0))));
  el("lid-height").min = String(roundMm(inside ? t : 2 * t));
  el("lid-height").max = String(roundMm(inside ? 80 : 80 + t));
  el("lid-tab-height").min = String(roundMm(t));
  updateDimLabels();
}

function enforceLidMins() {
  const t = materialThickness();
  const sideMin = dimMode === "inside" ? t : 2 * t;
  const side = parseFloat(el("lid-height").value);
  if (Number.isFinite(side) && side < sideMin) el("lid-height").value = roundMm(sideMin);
  const tab = parseFloat(el("lid-tab-height").value);
  if (Number.isFinite(tab) && tab < t) el("lid-tab-height").value = roundMm(t);
}

function slideTabLimit() {
  const t = materialThickness();
  const inside = dimMode === "inside";
  const add = inside ? 2 * t : 0;
  const length = parseFloat(el("length").value) + add;
  const width = parseFloat(el("width").value) + add;
  const along = slideDir === "left" || slideDir === "right" ? length : width;
  const span = along - t;
  const usable = span - 1 - 4 * t;
  const max = usable / (2.1 * slideCount);
  const fit = Number.isFinite(max) ? Math.max(1, max) : 20;
  return { min: Math.min(2 * t, fit), max: Math.min(80, fit) };
}

function enforceSlideTab() {
  const limit = slideTabLimit();
  const input = el("lid-slide-tab");
  input.min = String(roundMm(limit.min));
  input.max = String(roundMm(limit.max));
  const value = parseFloat(input.value);
  if (!Number.isFinite(value)) return;
  if (value > limit.max) input.value = roundMm(limit.max);
  if (value < limit.min) input.value = roundMm(limit.min);
}

function syncLidFields() {
  const on = lidMode === "cap" || lidMode === "top";
  el("lid-height-row").hidden = !on;
  el("lid-tab-row").hidden = lidMode !== "top";
  el("lid-tab-fields").hidden = lidMode !== "top" || !el("lid-tabs-on").checked;
  el("lid-slide-row").hidden = lidMode !== "slide";
  el("lid-latch-row").hidden = lidMode !== "latch";
  el("lid").value = lidMode;
  dividerRows().forEach(syncTopJoint);
  el("latch-tabs-1").setAttribute("aria-pressed", latchCount === 1 ? "true" : "false");
  el("latch-tabs-2").setAttribute("aria-pressed", latchCount === 2 ? "true" : "false");
  for (const side of ["front", "back", "left", "right"]) {
    el(`latch-${side}`).setAttribute("aria-pressed", latchSide === side ? "true" : "false");
  }
  el("tab-inner").setAttribute("aria-pressed", tabFit === "inner" ? "true" : "false");
  el("tab-outer").setAttribute("aria-pressed", tabFit === "outer" ? "true" : "false");
  for (const dir of ["back", "front", "left", "right"]) {
    el(`slide-${dir}`).setAttribute("aria-pressed", slideDir === dir ? "true" : "false");
  }
  el("slide-tabs-2").setAttribute("aria-pressed", slideCount === 2 ? "true" : "false");
  el("slide-tabs-3").setAttribute("aria-pressed", slideCount === 3 ? "true" : "false");
}

function knownLid(value) {
  return value === "cap" || value === "top" || value === "slide" || value === "latch" || value === "closed"
    ? value
    : "none";
}

function setLidMode(next) {
  lidMode = knownLid(next);
  syncLidFields();
  draw();
}

function setLatchCount(next) {
  const count = next === 2 ? 2 : 1;
  if (count === latchCount) return;
  latchCount = count;
  syncLidFields();
  draw();
}

function setLatchSide(next) {
  if (!["front", "back", "left", "right"].includes(next) || next === latchSide) return;
  latchSide = next;
  syncLidFields();
  draw();
}

function lidInsideSide() {
  const shown = parseFloat(el("lid-height").value);
  const side = Number.isFinite(shown) ? shown : 15;
  return dimMode === "outside" ? side - materialThickness() : side;
}

function overallOutsideHeight() {
  const box = outsideHeight();
  const thickness = materialThickness();
  if (lidMode === "slide" || lidMode === "latch") return box + 2 * thickness;
  if (lidMode === "cap") return box + thickness;
  if (lidMode === "top") return box + Math.max(0, lidInsideSide()) + thickness;
  return box;
}

function syncHeightOverall() {
  const note = el("height-overall");
  const box = outsideHeight();
  const overall = roundMm(overallOutsideHeight());
  if (!(overall > box + 0.05)) {
    note.hidden = true;
    note.textContent = "";
    return;
  }
  note.hidden = false;
  note.textContent = `Overall OD ${overall} mm`;
}

function setSlideDir(next) {
  if (!["back", "front", "left", "right"].includes(next) || next === slideDir) return;
  slideDir = next;
  enforceSlideTab();
  syncLidFields();
  draw();
}

function setSlideCount(next) {
  const count = next === 3 ? 3 : 2;
  if (count === slideCount) return;
  slideCount = count;
  enforceSlideTab();
  syncLidFields();
  draw();
}

function setDimMode(next) {
  if (next === dimMode) return;
  const thickness = parseFloat(el("thickness").value);
  if (Number.isNaN(thickness)) return;
  const sign = next === "outside" ? 1 : -1;
  el("length").value = roundMm(parseFloat(el("length").value) + sign * 2 * thickness);
  el("width").value = roundMm(parseFloat(el("width").value) + sign * 2 * thickness);
  if (el("floor").checked) {
    el("height").value = roundMm(parseFloat(el("height").value) + sign * thickness);
  }
  el("lid-height").value = roundMm(parseFloat(el("lid-height").value) + sign * thickness);
  dimMode = next;
  syncDimLimits();
  enforceLidMins();
  enforceSlideTab();
  enforceAllDividerGaps();
  draw();
}

let selectedDivider = null;

function dividerRows() {
  return [...document.querySelectorAll("#dividers .divider-row")];
}

function selectedDividerIndex() {
  if (!selectedDivider || !selectedDivider.isConnected) return -1;
  return dividerRows().indexOf(selectedDivider);
}

function dividerDisplayName(row, index) {
  const raw = (row.dataset.label || "").replace(/\s+/g, " ").trim();
  if (raw && !(raw.startsWith("d") && /^\d+$/.test(raw.slice(1)))) return raw;
  return `Divider ${index + 1}`;
}

function refreshDividerLabels() {
  dividerRows().forEach((row, i) => {
    const name = dividerDisplayName(row, i);
    const btn = row.querySelector(".divider-select");
    btn.textContent = "Select";
    btn.setAttribute("aria-label", `Highlight ${name} in the plan and 3D preview`);
    const input = row.querySelector(".d-name");
    if (input) input.placeholder = `Divider ${i + 1}`;
  });
}

function applyDividerSelection() {
  dividerRows().forEach((item) => {
    const on = item === selectedDivider;
    item.classList.toggle("is-selected", on);
    item.querySelector(".divider-select").setAttribute("aria-pressed", on ? "true" : "false");
  });
  redraw();
}

function setDividerSelection(row) {
  selectedDivider = row && row.isConnected ? row : null;
  applyDividerSelection();
}

function selectDivider(row) {
  setDividerSelection(selectedDivider === row ? null : row);
}

function insideSize() {
  const thickness = parseFloat(el("thickness").value) || 0;
  let length = parseFloat(el("length").value);
  let width = parseFloat(el("width").value);
  if (dimMode === "outside") {
    length -= 2 * thickness;
    width -= 2 * thickness;
  }
  return {
    length: Math.max(0, roundMm(length)),
    width: Math.max(0, roundMm(width)),
  };
}

function newDividerDefaults() {
  const size = insideSize();
  const x = roundMm(size.length / 2);
  return { x1: x, y1: 0, x2: x, y2: size.width, label: "", bottom: 0, top: 0, tilt: 0 };
}

function syncFloorJoint(row) {
  const input = row.querySelector(".h-floor-fingers");
  const gap = parseFloat(row.querySelector(".h-bottom").value);
  const raised = Number.isFinite(gap) && gap > 0;
  const noFloor = !el("floor").checked;
  input.disabled = raised || noFloor;
  const note = noFloor
    ? "There is no floor panel to joint into."
    : raised
      ? "This divider is raised off the floor, so it is not jointed into it."
      : "Uncheck to rest this divider on the floor with a straight edge and no slots in the floor.";
  input.title = note;
  input.closest("label").title = note;
}

function syncTopJoint(row) {
  const input = row.querySelector(".h-top-fingers");
  if (!input) return;
  const label = input.closest("label");
  const gap = parseFloat(row.querySelector(".h-top").value);
  const short = Number.isFinite(gap) && gap > 0;
  const open = lidMode !== "closed";
  if (label) label.hidden = open;
  input.disabled = short || open;
  const note = short
    ? "This divider stops below the top, so it is not jointed into the lid."
    : "Uncheck to stop this divider under the lid with a straight edge and no slots in the lid.";
  input.title = note;
  if (label) label.title = note;
}

function syncHeightUnit(row) {
  const pct = row.dataset.heightUnit === "pct";
  const unit = pct ? "%" : "mm";
  row.querySelector(".h-bottom-name").textContent = `From floor (${unit})`;
  row.querySelector(".h-top-name").textContent = `From top (${unit})`;
  row.querySelectorAll(".divider-height [data-unit]").forEach((btn) => {
    const on = btn.dataset.unit === (pct ? "pct" : "mm");
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  });
}

function dividerGapMax() {
  const height = parseFloat(el("height").value);
  if (!Number.isFinite(height)) return 0;
  return roundMm(Math.max(0, height - materialThickness()));
}

function enforceDividerGaps(row) {
  const warn = row.querySelector(".gap-warn");
  const inputs = [
    [".h-bottom", "From floor"],
    [".h-top", "From top"],
  ];
  if (row.dataset.heightUnit === "pct") {
    inputs.forEach(([cls]) => row.querySelector(cls).removeAttribute("max"));
    if (warn) {
      warn.hidden = true;
      warn.textContent = "";
    }
    return;
  }
  const max = dividerGapMax();
  const limited = [];
  for (const [cls, name] of inputs) {
    const input = row.querySelector(cls);
    input.max = String(max);
    const n = parseFloat(input.value);
    if (!Number.isFinite(n) || n <= max + 1e-6) continue;
    input.value = String(max);
    limited.push(name);
  }
  if (!warn) return;
  if (!limited.length) {
    warn.hidden = true;
    warn.textContent = "";
    return;
  }
  const what = limited.length === 2 ? "From floor and from top" : limited[0];
  const name = (row.dataset.label || "").trim();
  const prefix = name ? `${name}: ` : "";
  warn.hidden = false;
  warn.textContent = `${prefix}${what} can't be more than ${max} mm, the box height minus the material thickness, so it was set to ${max} mm.`;
}

function enforceAllDividerGaps() {
  dividerRows().forEach((row) => enforceDividerGaps(row));
}

function setHeightUnit(row, next) {
  const current = row.dataset.heightUnit === "pct" ? "pct" : "mm";
  if (next === current) return;
  const height = outsideHeight();
  if (!(height > 0)) return;
  row.querySelectorAll(".h-bottom, .h-top").forEach((input) => {
    const n = parseFloat(input.value);
    const value = Number.isFinite(n) ? n : 0;
    input.value = next === "pct"
      ? roundMm((value / height) * 100)
      : roundMm((value / 100) * height);
  });
  row.dataset.heightUnit = next;
  syncHeightUnit(row);
  enforceDividerGaps(row);
  syncFloorJoint(row);
  syncTopJoint(row);
  draw();
}

function addDividerRow(d) {
  const divider = d || newDividerDefaults();
  const row = document.createElement("div");
  row.className = "divider-row";
  row.dataset.label = divider.label || "";
  row.dataset.heightUnit = divider.heightUnit === "pct" ? "pct" : "mm";
  const bottom = Number.isFinite(divider.bottom) ? divider.bottom : 0;
  const top = Number.isFinite(divider.top) ? divider.top : 0;
  const tilt = Number.isFinite(divider.tilt) ? divider.tilt : 0;
  const floorFingers = divider.floor_fingers !== false;
  const topFingers = divider.top_fingers !== false;
  row.innerHTML = `
    <div class="divider-head">
      <button type="button" class="divider-select" aria-pressed="false">Select</button>
      <label>Name<input class="d-name" type="text" maxlength="40" spellcheck="false" autocomplete="off" /></label>
    </div>
    <label>x1<input class="x1" type="number" step="0.1" value="${divider.x1}" /></label>
    <label>y1<input class="y1" type="number" step="0.1" value="${divider.y1}" /></label>
    <button type="button" class="danger" aria-label="Remove divider">Remove</button>
    <label>x2<input class="x2" type="number" step="0.1" value="${divider.x2}" /></label>
    <label>y2<input class="y2" type="number" step="0.1" value="${divider.y2}" /></label>
    <div class="divider-height">
      <label><span class="h-bottom-name">From floor (mm)</span><input class="h-bottom" type="number" step="0.1" min="0" value="${bottom}" /></label>
      <label><span class="h-top-name">From top (mm)</span><input class="h-top" type="number" step="0.1" min="0" value="${top}" /></label>
      <div class="seg" role="group" aria-label="Divider height units">
        <button type="button" data-unit="mm">mm</button>
        <button type="button" data-unit="pct">%</button>
      </div>
      <label class="check floor-fingers">
        <input class="h-floor-fingers" type="checkbox"${floorFingers ? " checked" : ""} />
        <span>Finger joint to floor</span>
      </label>
      <label class="check top-fingers">
        <input class="h-top-fingers" type="checkbox"${topFingers ? " checked" : ""} />
        <span>Finger joint to top</span>
      </label>
      <p class="gap-warn" role="alert" hidden></p>
    </div>
    <div class="divider-tilt">
      <label>Tilt (°)<input class="h-tilt" type="number" step="1" min="-75" max="75" value="${tilt}" /></label>
    </div>
  `;
  const nameInput = row.querySelector(".d-name");
  nameInput.value = divider.label || "";
  nameInput.title = "Shown on this divider in the 2D drawing";
  nameInput.addEventListener("input", () => {
    row.dataset.label = nameInput.value;
    refreshDividerLabels();
    if (row === selectedDivider) paintPlan();
  });
  syncHeightUnit(row);
  enforceDividerGaps(row);
  syncFloorJoint(row);
  syncTopJoint(row);
  row.querySelector(".divider-select").addEventListener("click", () => selectDivider(row));
  row.querySelectorAll(".divider-height [data-unit]").forEach((btn) => {
    btn.addEventListener("click", () => setHeightUnit(row, btn.dataset.unit));
  });
  row.querySelector(".danger").addEventListener("click", () => {
    if (selectedDivider === row) selectedDivider = null;
    row.remove();
    refreshDividerLabels();
    draw();
  });
  row.querySelectorAll(".h-bottom, .h-top").forEach((input) => {
    input.addEventListener("input", () => {
      enforceDividerGaps(row);
      if (input.classList.contains("h-bottom")) syncFloorJoint(row);
      if (input.classList.contains("h-top")) syncTopJoint(row);
    });
  });
  row.querySelectorAll("input").forEach((inp) => inp.addEventListener("input", draw));
  el("dividers").appendChild(row);
  refreshDividerLabels();
}

// Front of the box (low Y) sits at the lower right. Pitch stays looking down.
const orbit = { yaw: Math.PI - 0.75, pitch: 0.62, zoom: 1 };
let lastPreview = null;
let previewTimer = null;
let previewAbort = null;
let previewBusy = false;
let previewGen = 0;
let planDrag = null;
const drawingView = { zoom: 1, panX: 0, panY: 0 };
let drawingFrame = null;

function fitCanvas(canvas) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.max(1, canvas.clientWidth);
  const h = Math.max(1, canvas.clientHeight);
  const bw = Math.round(w * dpr);
  const bh = Math.round(h * dpr);
  if (canvas.width !== bw || canvas.height !== bh) {
    canvas.width = bw;
    canvas.height = bh;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}

function sub3(a, b) {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
}

function cross3(a, b) {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

function dot3(a, b) {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

function norm3(a) {
  const len = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0] / len, a[1] / len, a[2] / len];
}

function cameraBasis() {
  const cp = Math.cos(orbit.pitch);
  const sp = Math.sin(orbit.pitch);
  const cy = Math.cos(orbit.yaw);
  const sy = Math.sin(orbit.yaw);
  const eye = [sy * cp, cy * cp, sp];
  const forward = [-eye[0], -eye[1], -eye[2]];
  const right = norm3(cross3([0, 0, 1], forward));
  const up = norm3(cross3(forward, right));
  return { eye, forward, right, up };
}

function paint3d(triangles, parts) {
  const canvas = el("view3d");
  const { ctx, w, h } = fitCanvas(canvas);
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#101613";
  ctx.fillRect(0, 0, w, h);
  if (!triangles || !triangles.length) return;

  let min = [Infinity, Infinity, Infinity];
  let max = [-Infinity, -Infinity, -Infinity];
  for (const tri of triangles) {
    for (const v of tri) {
      for (let i = 0; i < 3; i++) {
        min[i] = Math.min(min[i], v[i]);
        max[i] = Math.max(max[i], v[i]);
      }
    }
  }
  const center = [(min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2];
  const radius = Math.max(Math.hypot(max[0] - min[0], max[1] - min[1], max[2] - min[2]) / 2, 1);
  const dist = radius * 2.7 / orbit.zoom;
  const basis = cameraBasis();
  const focal = Math.min(w, h) * 1.15;

  function project(v) {
    const d = [v[0] - center[0] - basis.eye[0] * dist, v[1] - center[1] - basis.eye[1] * dist, v[2] - center[2] - basis.eye[2] * dist];
    const x = dot3(d, basis.right);
    const y = dot3(d, basis.up);
    const z = dot3(d, basis.forward);
    const s = focal / Math.max(z, 0.1);
    return [w / 2 + x * s, h / 2 - y * s, z];
  }

  const quant = (v) => `${Math.round(v[0] * 50)},${Math.round(v[1] * 50)},${Math.round(v[2] * 50)}`;
  const edgeCount = new Map();
  const edgeOf = (a, b) => {
    const ka = quant(a);
    const kb = quant(b);
    return ka < kb ? `${ka}|${kb}` : `${kb}|${ka}`;
  };
  for (const tri of triangles) {
    for (let i = 0; i < 3; i++) {
      const key = edgeOf(tri[i], tri[(i + 1) % 3]);
      edgeCount.set(key, (edgeCount.get(key) || 0) + 1);
    }
  }

  const lidFaces = new Set();
  if (parts) {
    const lidPart = parts.find((item) => item.name === "lid");
    if (lidPart) {
      for (let i = 0; i < lidPart.count; i++) lidFaces.add(lidPart.start + i);
    }
  }
  const highlight = new Set();
  const picked = selectedDividerIndex();
  if (picked >= 0 && parts) {
    const part = parts.find((item) => item.name === `divider-${picked}`);
    if (part) {
      for (let i = 0; i < part.count; i++) highlight.add(part.start + i);
    }
  }

  const faces = triangles.map((tri, index) => {
    const pts = tri.map(project);
    const depth = (pts[0][2] + pts[1][2] + pts[2][2]) / 3;
    const n = norm3(cross3(sub3(tri[1], tri[0]), sub3(tri[2], tri[0])));
    const viewN = [
      dot3(n, basis.right),
      dot3(n, basis.up),
      dot3(n, basis.forward),
    ];
    const light = Math.abs(dot3(norm3(viewN), norm3([0.25, 0.75, 0.45])));
    const edges = [0, 1, 2].filter((i) => edgeCount.get(edgeOf(tri[i], tri[(i + 1) % 3])) > 1);
    return { pts, depth, light, edges, hot: highlight.has(index), lid: lidFaces.has(index) };
  });
  faces.sort((a, b) => a.depth - b.depth);

  const lines = [];
  const hotLines = [];
  for (const face of faces) {
    const shade = 0.35 + 0.65 * face.light;
    ctx.beginPath();
    ctx.moveTo(face.pts[0][0], face.pts[0][1]);
    ctx.lineTo(face.pts[1][0], face.pts[1][1]);
    ctx.lineTo(face.pts[2][0], face.pts[2][1]);
    ctx.closePath();
    ctx.fillStyle = face.hot
      ? `rgba(${Math.round(230 * shade)}, ${Math.round(176 * shade)}, ${Math.round(64 * shade)}, 0.95)`
      : face.lid
        ? `rgba(${Math.round(214 * shade)}, ${Math.round(164 * shade)}, ${Math.round(74 * shade)}, 0.78)`
        : `rgba(${Math.round(36 * shade)}, ${Math.round(196 * shade)}, ${Math.round(176 * shade)}, 0.55)`;
    ctx.fill();
    const bucket = face.hot ? hotLines : lines;
    for (const i of face.edges) {
      const a = face.pts[i];
      const b = face.pts[(i + 1) % 3];
      bucket.push([a[0], a[1], b[0], b[1]]);
    }
  }
  ctx.lineWidth = 1.1;
  ctx.strokeStyle = "rgba(186, 255, 242, 0.7)";
  for (const [x1, y1, x2, y2] of lines) {
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
  }
  ctx.lineWidth = 1.6;
  ctx.strokeStyle = "rgba(255, 214, 120, 0.95)";
  for (const [x1, y1, x2, y2] of hotLines) {
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
  }
}

function paint2d(panels) {
  const canvas = el("drawing");
  const { ctx, w, h } = fitCanvas(canvas);
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#101613";
  ctx.fillRect(0, 0, w, h);
  if (!panels || !panels.length) return;

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  const placed = panels.map((panel) => {
    const shift = (pt) => [panel.origin[0] + pt[0], panel.origin[1] + pt[1]];
    const outline = panel.outline.map(shift);
    const holes = (panel.holes || []).map((hole) => hole.map(shift));
    for (const pt of outline) {
      minX = Math.min(minX, pt[0]);
      minY = Math.min(minY, pt[1]);
      maxX = Math.max(maxX, pt[0]);
      maxY = Math.max(maxY, pt[1]);
    }
    return { ...panel, outline, holes };
  });

  const pad = 28;
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(maxY - minY, 1);
  const base = Math.min((w - 2 * pad) / spanX, (h - 2 * pad) / spanY);
  const scale = base * drawingView.zoom;
  const ox = (w - spanX * scale) / 2 + drawingView.panX;
  const oy = (h - spanY * scale) / 2 + drawingView.panY;
  drawingFrame = { minX, minY, spanX, spanY, base, w, h };
  const sx = (x) => ox + (x - minX) * scale;
  const sy = (y) => oy + (y - minY) * scale;

  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.strokeStyle = "#5ee0d0";
  ctx.fillStyle = "#d9fff6";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";

  for (const panel of placed) {
    const stroke = (poly) => {
      if (poly.length < 2) return;
      ctx.beginPath();
      ctx.moveTo(sx(poly[0][0]), sy(poly[0][1]));
      for (let i = 1; i < poly.length; i++) ctx.lineTo(sx(poly[i][0]), sy(poly[i][1]));
      ctx.closePath();
      ctx.stroke();
    };
    ctx.lineWidth = 1.4;
    stroke(panel.outline);
    ctx.lineWidth = 1;
    for (const hole of panel.holes) stroke(hole);

    const xs = panel.outline.map((pt) => pt[0]);
    const ys = panel.outline.map((pt) => pt[1]);
    const bw = (Math.max(...xs) - Math.min(...xs)) * scale;
    const bh = (Math.max(...ys) - Math.min(...ys)) * scale;
    const text = panel.label || panel.name;
    let font = Math.min(15, bh * 0.28, bw / Math.max(text.length, 1) / 0.55);
    font = Math.max(8, font);
    ctx.font = `${font}px "Segoe UI", sans-serif`;
    const at = panel.label_at;
    const x = at ? panel.origin[0] + at[0] : (Math.min(...xs) + Math.max(...xs)) / 2;
    const y = at ? panel.origin[1] + at[1] : (Math.min(...ys) + Math.max(...ys)) / 2;
    ctx.fillText(text, sx(x), sy(y));
  }
}

const PLAN_PAD = 28;
const PLAN_SNAP = 6;
const PLAN_HANDLE_PX = 7;
const PLAN_BODY_PX = 4;
const PLAN_CURSORS = ["is-slide", "is-sliding", "is-ew", "is-ns", "is-nwse", "is-nesw"];

function dividerEnds(row) {
  const num = (cls) => {
    const n = parseFloat(row.querySelector(cls).value);
    return Number.isFinite(n) ? n : 0;
  };
  return { x1: num(".x1"), y1: num(".y1"), x2: num(".x2"), y2: num(".y2") };
}

function writeDividerEnds(row, x1, y1, x2, y2) {
  row.querySelector(".x1").value = roundMm(x1);
  row.querySelector(".y1").value = roundMm(y1);
  row.querySelector(".x2").value = roundMm(x2);
  row.querySelector(".y2").value = roundMm(y2);
}

function dividerAxis(ends) {
  const dx = ends.x2 - ends.x1;
  const dy = ends.y2 - ends.y1;
  const len = Math.hypot(dx, dy);
  if (len < 1e-6) return { ux: 1, uy: 0, nx: 0, ny: 1, len: 0 };
  return { ux: dx / len, uy: dy / len, nx: -dy / len, ny: dx / len, len };
}

function planMetrics() {
  const size = insideSize();
  const thickness = parseFloat(el("thickness").value);
  const wall = Number.isFinite(thickness) ? Math.max(0, thickness) : 0;
  return {
    wall,
    innerL: size.length,
    innerW: size.width,
    minX: -wall,
    minY: -wall,
    maxX: size.length + wall,
    maxY: size.width + wall,
  };
}

function planView() {
  const canvas = el("plan");
  const { ctx, w, h } = fitCanvas(canvas);
  const m = planMetrics();
  const spanX = Math.max(m.maxX - m.minX, 1);
  const spanY = Math.max(m.maxY - m.minY, 1);
  const scale = Math.min(
    Math.max(w - 2 * PLAN_PAD, 1) / spanX,
    Math.max(h - 2 * PLAN_PAD, 1) / spanY,
  );
  const ox = (w - spanX * scale) / 2;
  const oy = (h - spanY * scale) / 2;
  return {
    ...m,
    ctx,
    w,
    h,
    scale,
    // Looking down on the top. Rotated so the front (y = 0) is at the bottom.
    sx: (x) => ox + (m.maxX - x) * scale,
    sy: (y) => oy + (m.maxY - y) * scale,
    toMm(clientX, clientY) {
      const rect = canvas.getBoundingClientRect();
      const px = clientX - rect.left;
      const py = clientY - rect.top;
      return {
        x: m.maxX - (px - ox) / scale,
        y: m.maxY - (py - oy) / scale,
      };
    },
  };
}

function pointSegDist(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len2 = dx * dx + dy * dy;
  if (len2 < 1e-12) return Math.hypot(px - x1, py - y1);
  let t = ((px - x1) * dx + (py - y1) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

function lengthCursorClass(ux, uy) {
  // The plan is rotated 180°, so both screen axes oppose the model axes.
  const screenX = -ux;
  const screenY = -uy;
  if (Math.abs(screenX) > Math.abs(screenY) * 2) return "is-ew";
  if (Math.abs(screenY) > Math.abs(screenX) * 2) return "is-ns";
  return screenX * screenY >= 0 ? "is-nwse" : "is-nesw";
}

function setPlanCursor(name) {
  const canvas = el("plan");
  for (const cls of PLAN_CURSORS) canvas.classList.toggle(cls, cls === name);
}

function materialThickness() {
  const thickness = parseFloat(el("thickness").value);
  return Number.isFinite(thickness) ? Math.max(0, thickness) : 0;
}

function plateSpan(row) {
  // Same pivot as the 3D plate: the bottom edge, or the bottom of a floor tongue.
  const H = outsideHeight();
  const T = materialThickness();
  const gap = (cls) => {
    const n = parseFloat(row.querySelector(cls).value);
    const value = Number.isFinite(n) ? Math.max(0, n) : 0;
    return row.dataset.heightUnit === "pct" ? (value / 100) * H : value;
  };
  const bottom = gap(".h-bottom");
  const top = gap(".h-top");
  const floorOn = el("floor").checked;
  const fingers = row.querySelector(".h-floor-fingers").checked;
  const z0 = (floorOn ? T : 0) + bottom;
  const z1 = H - top;
  if (!(z1 > z0 + 0.5)) return null;
  const anchor = bottom <= 1e-6 && fingers ? 0 : z0;
  return { z0, z1, anchor };
}

function topLeanShift(row) {
  const span = plateSpan(row);
  const tilt = parseFloat(row.querySelector(".h-tilt").value);
  if (!span || !Number.isFinite(tilt) || Math.abs(tilt) <= 0.05) return null;
  const degrees = Math.max(-75, Math.min(75, tilt));
  return (span.z1 - span.anchor) * Math.tan((degrees * Math.PI) / 180);
}

function followAlong(row, ends, atStart) {
  // How far this end's top moves along the divider to stay on a tilted one.
  const span = plateSpan(row);
  const axis = dividerAxis(ends);
  if (!span || axis.len < 1e-6) return 0;
  const px = atStart ? ends.x1 : ends.x2;
  const py = atStart ? ends.y1 : ends.y2;
  const margin = Math.max(materialThickness(), 2);
  let best = 0;
  let bestDist = 1.5;
  let found = false;
  for (const other of dividerRows()) {
    if (other === row || topLeanShift(other) == null) continue;
    const otherEnds = dividerEnds(other);
    const otherAxis = dividerAxis(otherEnds);
    if (otherAxis.len < 1e-6) continue;
    const along = (px - otherEnds.x1) * otherAxis.ux + (py - otherEnds.y1) * otherAxis.uy;
    const dist = Math.abs((px - otherEnds.x1) * otherAxis.nx + (py - otherEnds.y1) * otherAxis.ny);
    if (dist > bestDist || along <= margin || along >= otherAxis.len - margin) continue;
    const dot = axis.ux * otherAxis.nx + axis.uy * otherAxis.ny;
    if (Math.abs(dot) < 0.25) continue;
    const otherSpan = plateSpan(other);
    if (!otherSpan) continue;
    const tilt = parseFloat(other.querySelector(".h-tilt").value);
    const degrees = Math.max(-75, Math.min(75, Number.isFinite(tilt) ? tilt : 0));
    best = (Math.tan((degrees * Math.PI) / 180) / dot) * (span.z1 - otherSpan.anchor);
    bestDist = dist;
    found = true;
  }
  return found ? best : 0;
}

function topCorners(ends, row) {
  const axis = dividerAxis(ends);
  const own = topLeanShift(row) || 0;
  const d1 = followAlong(row, ends, true);
  const d2 = followAlong(row, ends, false);
  if (axis.len < 1e-6) return null;
  if (Math.abs(own) < 0.8 && Math.abs(d1) < 0.8 && Math.abs(d2) < 0.8) return null;
  const at = (atStart, along) => {
    const x = atStart ? ends.x1 : ends.x2;
    const y = atStart ? ends.y1 : ends.y2;
    return [x + axis.ux * along + axis.nx * own, y + axis.uy * along + axis.ny * own];
  };
  return { axis, own, d1, d2, top1: at(true, d1), top2: at(false, d2) };
}

function paintLeanFill(view, ends, row) {
  const mark = topCorners(ends, row);
  if (!mark || Math.abs(mark.own) < 0.8) return;
  const { ctx, sx, sy } = view;
  const half = Math.max(view.wall, 0.4) / 2;
  const sign = mark.own >= 0 ? 1 : -1;
  const edge = (x, y) => [x + mark.axis.nx * half * sign, y + mark.axis.ny * half * sign];
  const b1 = edge(ends.x1, ends.y1);
  const b2 = edge(ends.x2, ends.y2);
  const hot = row === selectedDivider;
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(sx(b1[0]), sy(b1[1]));
  ctx.lineTo(sx(b2[0]), sy(b2[1]));
  ctx.lineTo(sx(mark.top2[0]), sy(mark.top2[1]));
  ctx.lineTo(sx(mark.top1[0]), sy(mark.top1[1]));
  ctx.closePath();
  ctx.fillStyle = hot ? "rgba(230, 176, 64, 0.18)" : "rgba(94, 224, 208, 0.16)";
  ctx.fill();
  ctx.restore();
}

function paintTopDash(view, ends, row) {
  const mark = topCorners(ends, row);
  if (!mark) return;
  const { ctx, sx, sy } = view;
  const hot = row === selectedDivider;
  const half = Math.max(view.wall, 0.4) / 2;
  const leaning = Math.abs(mark.own) >= 0.8;
  const sign = mark.own >= 0 ? 1 : -1;
  ctx.save();
  ctx.setLineDash([5, 4]);
  ctx.lineWidth = 1.25;
  ctx.strokeStyle = hot ? "rgba(255, 214, 120, 0.9)" : "rgba(186, 255, 242, 0.8)";
  ctx.beginPath();
  ctx.moveTo(sx(mark.top1[0]), sy(mark.top1[1]));
  ctx.lineTo(sx(mark.top2[0]), sy(mark.top2[1]));
  if (leaning) {
    const edge = (x, y) => [x + mark.axis.nx * half * sign, y + mark.axis.ny * half * sign];
    const b1 = edge(ends.x1, ends.y1);
    const b2 = edge(ends.x2, ends.y2);
    ctx.moveTo(sx(b1[0]), sy(b1[1]));
    ctx.lineTo(sx(mark.top1[0]), sy(mark.top1[1]));
    ctx.moveTo(sx(b2[0]), sy(b2[1]));
    ctx.lineTo(sx(mark.top2[0]), sy(mark.top2[1]));
  } else {
    const tick = (at, along) => {
      if (Math.abs(along) < 0.8) return;
      ctx.moveTo(sx(at[0] - mark.axis.nx * half), sy(at[1] - mark.axis.ny * half));
      ctx.lineTo(sx(at[0] + mark.axis.nx * half), sy(at[1] + mark.axis.ny * half));
    };
    tick(mark.top1, mark.d1);
    tick(mark.top2, mark.d2);
  }
  ctx.stroke();
  ctx.restore();
}

function paintDividerStrip(view, ends, hot) {
  const { ctx, sx, sy } = view;
  const axis = dividerAxis(ends);
  const half = Math.max(view.wall, 0.4) / 2;
  const corners = [
    [ends.x1 + axis.nx * half, ends.y1 + axis.ny * half],
    [ends.x2 + axis.nx * half, ends.y2 + axis.ny * half],
    [ends.x2 - axis.nx * half, ends.y2 - axis.ny * half],
    [ends.x1 - axis.nx * half, ends.y1 - axis.ny * half],
  ];
  ctx.beginPath();
  ctx.moveTo(sx(corners[0][0]), sy(corners[0][1]));
  for (let i = 1; i < corners.length; i++) ctx.lineTo(sx(corners[i][0]), sy(corners[i][1]));
  ctx.closePath();
  ctx.fillStyle = hot ? "rgba(230, 176, 64, 0.92)" : "rgba(36, 196, 176, 0.72)";
  ctx.fill();
  ctx.lineWidth = hot ? 1.6 : 1;
  ctx.strokeStyle = hot ? "rgba(255, 214, 120, 0.95)" : "rgba(186, 255, 242, 0.85)";
  ctx.stroke();
  if (!hot) return;
  ctx.fillStyle = "#fff6df";
  ctx.strokeStyle = "#c4a35a";
  ctx.lineWidth = 1.5;
  for (const [x, y] of [[ends.x1, ends.y1], [ends.x2, ends.y2]]) {
    ctx.beginPath();
    ctx.arc(sx(x), sy(y), PLAN_HANDLE_PX, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
}

function paintPlan() {
  const canvas = el("plan");
  if (!canvas) return;
  const view = planView();
  const { ctx, w, h, sx, sy, wall, innerL, innerW } = view;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#101613";
  ctx.fillRect(0, 0, w, h);

  const box = (x0, y0, x1, y1) => {
    const left = Math.min(sx(x0), sx(x1));
    const top = Math.min(sy(y0), sy(y1));
    const right = Math.max(sx(x0), sx(x1));
    const bottom = Math.max(sy(y0), sy(y1));
    return [left, top, right - left, bottom - top];
  };
  const outer = box(-wall, -wall, innerL + wall, innerW + wall);
  const inner = box(0, 0, innerL, innerW);
  ctx.fillStyle = "#1a2e28";
  ctx.fillRect(...outer);
  ctx.fillStyle = "#101613";
  ctx.fillRect(...inner);
  ctx.lineWidth = 1.25;
  ctx.strokeStyle = "#3d5244";
  ctx.strokeRect(...outer);
  ctx.strokeStyle = "#5ee0d0";
  ctx.strokeRect(...inner);
  ctx.fillStyle = "#9aafa0";
  ctx.font = "12px \"Segoe UI\", sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillText("front", sx(innerL / 2), sy(-wall) + 4);

  const rows = dividerRows();
  const marked = rows.some((row) => topCorners(dividerEnds(row), row));
  ctx.textBaseline = "bottom";
  ctx.fillText(
    marked ? "Solid bar: bottom face    Dashed line: top" : "Solid bar: bottom face",
    sx(innerL / 2),
    sy(innerW + wall) - 6,
  );
  const picked = selectedDividerIndex();
  const order = rows.map((_, i) => i).sort((a, b) => (a === picked) - (b === picked));
  for (const i of order) paintLeanFill(view, dividerEnds(rows[i]), rows[i]);
  for (const i of order) paintDividerStrip(view, dividerEnds(rows[i]), i === picked);
  for (const i of order) paintTopDash(view, dividerEnds(rows[i]), rows[i]);
  placePlanName(view);
}

function placePlanName(view) {
  const tag = el("plan-name");
  const canvas = el("plan");
  if (!tag || !canvas) return;
  const index = selectedDividerIndex();
  const row = selectedDivider;
  if (!row || index < 0) {
    tag.hidden = true;
    tag.textContent = "";
    return;
  }
  tag.textContent = dividerDisplayName(row, index);
  tag.hidden = false;
  const ends = dividerEnds(row);
  const axis = dividerAxis(ends);
  const mx = (ends.x1 + ends.x2) / 2;
  const my = (ends.y1 + ends.y2) / 2;
  const tw = tag.offsetWidth;
  const th = tag.offsetHeight;
  let best = null;
  for (const sign of [1, -1]) {
    const left = view.sx(mx) - axis.nx * sign * (tw / 2 + 12);
    const top = view.sy(my) - axis.ny * sign * (th / 2 + 12);
    const x = left - tw / 2;
    const y = top - th / 2;
    const overflow =
      Math.max(0, 6 - x) + Math.max(0, x + tw - (view.w - 6)) +
      Math.max(0, 6 - y) + Math.max(0, y + th - (view.h - 6));
    if (!best || overflow < best.overflow) best = { left, top, overflow };
  }
  const left = Math.min(view.w - 6 - tw / 2, Math.max(6 + tw / 2, best.left));
  const top = Math.min(view.h - 6 - th / 2, Math.max(6 + th / 2, best.top));
  const frame = tag.offsetParent || canvas.parentElement;
  const canvasRect = canvas.getBoundingClientRect();
  const frameRect = frame.getBoundingClientRect();
  tag.style.left = `${canvasRect.left - frameRect.left + canvas.clientLeft + left}px`;
  tag.style.top = `${canvasRect.top - frameRect.top + canvas.clientTop + top}px`;
}

function planHit(view, x, y) {
  const handleR = PLAN_HANDLE_PX / view.scale;
  const limit = view.wall / 2 + PLAN_BODY_PX / view.scale;
  const picked = selectedDivider;
  if (picked && picked.isConnected) {
    const ends = dividerEnds(picked);
    const d1 = Math.hypot(x - ends.x1, y - ends.y1);
    const d2 = Math.hypot(x - ends.x2, y - ends.y2);
    if (d1 <= handleR || d2 <= handleR) {
      return { row: picked, part: d1 <= d2 ? "end1" : "end2" };
    }
  }
  let best = null;
  let bestD = Infinity;
  for (const row of dividerRows()) {
    const ends = dividerEnds(row);
    const dist = pointSegDist(x, y, ends.x1, ends.y1, ends.x2, ends.y2);
    if (dist <= limit && dist < bestD) {
      bestD = dist;
      best = { row, part: "body" };
    }
  }
  return best;
}

function offsetRange(points, nx, ny, innerL, innerW) {
  let lo = -Infinity;
  let hi = Infinity;
  for (const [x, y] of points) {
    const limits = [[x, nx, 0, innerL], [y, ny, 0, innerW]];
    for (const [p, n, min, max] of limits) {
      if (Math.abs(n) < 1e-8) {
        if (p < min - 1e-4 || p > max + 1e-4) return [0, 0];
        continue;
      }
      const a = (min - p) / n;
      const b = (max - p) / n;
      lo = Math.max(lo, Math.min(a, b));
      hi = Math.min(hi, Math.max(a, b));
    }
  }
  if (!(lo <= hi)) return [0, 0];
  return [lo, hi];
}

function snapWholeMm() {
  const box = el("snap-mm");
  return !!(box && box.checked);
}

function snapScalar(raw, lo, hi, targets) {
  const clamped = Math.min(hi, Math.max(lo, raw));
  let best = clamped;
  let bestD = PLAN_SNAP + 1e-6;
  let targeted = false;
  for (const target of [lo, hi, ...targets]) {
    if (target < lo - 1e-4 || target > hi + 1e-4) continue;
    const dist = Math.abs(raw - target);
    if (dist < bestD && dist <= PLAN_SNAP) {
      bestD = dist;
      best = target;
      targeted = true;
    }
  }
  return { value: best, targeted };
}

function snapTravel(ox, oy, ux, uy, t, lo, hi) {
  const clamp = (v) => Math.min(hi, Math.max(lo, v));
  t = clamp(t);
  if (!snapWholeMm()) return t;
  const x = ox + ux * t;
  const y = oy + uy * t;
  let best = t;
  let bestDist = Infinity;
  const ix0 = Math.round(x);
  const iy0 = Math.round(y);
  for (let ix = ix0 - 1; ix <= ix0 + 1; ix++) {
    for (let iy = iy0 - 1; iy <= iy0 + 1; iy++) {
      const cand = clamp((ix - ox) * ux + (iy - oy) * uy);
      const px = ox + ux * cand;
      const py = oy + uy * cand;
      if (Math.hypot(px - ix, py - iy) > 0.02) continue;
      const dist = Math.abs(cand - t);
      if (dist < bestDist) {
        bestDist = dist;
        best = cand;
      }
    }
  }
  if (bestDist < Infinity) return best;
  if (Math.abs(ux) >= Math.abs(uy) && Math.abs(ux) > 1e-6) return clamp((Math.round(x) - ox) / ux);
  if (Math.abs(uy) > 1e-6) return clamp((Math.round(y) - oy) / uy);
  return t;
}

function slideSnapTargets(row, ends, axis) {
  const targets = [];
  for (const other of dividerRows()) {
    if (other === row) continue;
    const otherEnds = dividerEnds(other);
    for (const [px, py] of [[otherEnds.x1, otherEnds.y1], [otherEnds.x2, otherEnds.y2]]) {
      const along = (px - ends.x1) * axis.ux + (py - ends.y1) * axis.uy;
      if (along < -PLAN_SNAP || along > axis.len + PLAN_SNAP) continue;
      targets.push((px - ends.x1) * axis.nx + (py - ends.y1) * axis.ny);
    }
  }
  return targets;
}

function lengthLimit(fx, fy, ux, uy, innerL, innerW) {
  let hi = Infinity;
  const dims = [[fx, ux, 0, innerL], [fy, uy, 0, innerW]];
  for (const [p, n, min, max] of dims) {
    if (Math.abs(n) < 1e-9) {
      if (p < min - 1e-4 || p > max + 1e-4) return 0;
      continue;
    }
    const tMin = Math.min((min - p) / n, (max - p) / n);
    const tMax = Math.max((min - p) / n, (max - p) / n);
    if (0 < tMin - 1e-4 || 0 > tMax + 1e-4) return 0;
    hi = Math.min(hi, tMax);
  }
  if (!Number.isFinite(hi) || hi < 0) return 0;
  return hi;
}

function crossingLengths(fx, fy, ux, uy, row) {
  const hits = [];
  for (const other of dividerRows()) {
    if (other === row) continue;
    const ends = dividerEnds(other);
    const sx = ends.x2 - ends.x1;
    const sy = ends.y2 - ends.y1;
    const den = ux * sy - uy * sx;
    if (Math.abs(den) < 1e-9) continue;
    const qx = ends.x1 - fx;
    const qy = ends.y1 - fy;
    const t = (qx * sy - qy * sx) / den;
    const s = (qx * uy - qy * ux) / den;
    if (s >= -1e-3 && s <= 1 + 1e-3) hits.push(t);
  }
  return hits;
}

function abuttingEnds(row, ends) {
  // Other dividers whose endpoint lies on this one. Sliding keeps those ends attached.
  const axis = dividerAxis(ends);
  if (axis.len < 1e-6) return [];
  const tol = 2;
  const hits = [];
  for (const other of dividerRows()) {
    if (other === row) continue;
    const o = dividerEnds(other);
    const candidates = [
      ["end1", o.x1, o.y1, o.x2, o.y2],
      ["end2", o.x2, o.y2, o.x1, o.y1],
    ];
    for (const [end, x, y, fx, fy] of candidates) {
      const along = (x - ends.x1) * axis.ux + (y - ends.y1) * axis.uy;
      const dist = Math.abs((x - ends.x1) * axis.nx + (y - ends.y1) * axis.ny);
      if (dist > tol || along <= tol || along >= axis.len - tol) continue;
      const dx = x - fx;
      const dy = y - fy;
      const len = Math.hypot(dx, dy);
      if (len < 1e-6) continue;
      hits.push({ row: other, end, fixed: { x: fx, y: fy }, ux: dx / len, uy: dy / len });
    }
  }
  return hits;
}

function applySlide(drag, x, y) {
  const { row, ends, axis, innerL, innerW } = drag;
  let offset = (x - drag.x0) * axis.nx + (y - drag.y0) * axis.ny;
  const [lo, hi] = offsetRange(
    [[ends.x1, ends.y1], [ends.x2, ends.y2]],
    axis.nx,
    axis.ny,
    innerL,
    innerW,
  );
  const snapped = snapScalar(offset, lo, hi, slideSnapTargets(row, ends, axis));
  offset = snapped.targeted
    ? snapped.value
    : snapTravel(ends.x1, ends.y1, axis.nx, axis.ny, snapped.value, lo, hi);
  writeDividerEnds(
    row,
    ends.x1 + axis.nx * offset,
    ends.y1 + axis.ny * offset,
    ends.x2 + axis.nx * offset,
    ends.y2 + axis.ny * offset,
  );
  const moved = dividerEnds(row);
  const movedAxis = dividerAxis(moved);
  for (const hit of drag.attached) {
    const den = hit.ux * movedAxis.uy - hit.uy * movedAxis.ux;
    if (Math.abs(den) < 1e-6 || movedAxis.len < 1e-6) continue;
    const qx = moved.x1 - hit.fixed.x;
    const qy = moved.y1 - hit.fixed.y;
    let s = (qx * movedAxis.uy - qy * movedAxis.ux) / den;
    const maxS = lengthLimit(hit.fixed.x, hit.fixed.y, hit.ux, hit.uy, innerL, innerW);
    const floor = Math.min(drag.minLen, maxS);
    const cap = Math.max(floor, maxS);
    s = Math.min(cap, Math.max(floor, s));
    const mx = hit.fixed.x + hit.ux * s;
    const my = hit.fixed.y + hit.uy * s;
    if (hit.end === "end1") writeDividerEnds(hit.row, mx, my, hit.fixed.x, hit.fixed.y);
    else writeDividerEnds(hit.row, hit.fixed.x, hit.fixed.y, mx, my);
  }
}

function applyLength(drag, x, y) {
  const { row, fixed, anchor, ux, uy, innerL, innerW, minLen, end } = drag;
  let t = (x - fixed.x) * ux + (y - fixed.y) * uy;
  const maxT = lengthLimit(fixed.x, fixed.y, ux, uy, innerL, innerW);
  const floor = Math.min(minLen, maxT);
  const hi = Math.max(floor, maxT);
  const snapped = snapScalar(t, floor, hi, [...crossingLengths(fixed.x, fixed.y, ux, uy, row), maxT]);
  t = snapped.targeted
    ? snapped.value
    : snapTravel(fixed.x, fixed.y, ux, uy, snapped.value, floor, hi);
  const mx = fixed.x + ux * t;
  const my = fixed.y + uy * t;
  if (end === "end1") writeDividerEnds(row, mx, my, anchor.x, anchor.y);
  else writeDividerEnds(row, anchor.x, anchor.y, mx, my);
}

function hoverPlan(view, x, y) {
  const hit = planHit(view, x, y);
  if (!hit) {
    setPlanCursor("");
    return;
  }
  if (hit.part === "body") {
    setPlanCursor("is-slide");
    return;
  }
  const axis = dividerAxis(dividerEnds(hit.row));
  const sign = hit.part === "end1" ? -1 : 1;
  setPlanCursor(lengthCursorClass(axis.ux * sign, axis.uy * sign));
}

function bindPlan() {
  const canvas = el("plan");

  canvas.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    const view = planView();
    const p = view.toMm(event.clientX, event.clientY);
    const hit = planHit(view, p.x, p.y);
    if (!hit) {
      if (selectedDivider) setDividerSelection(null);
      return;
    }
    if (selectedDivider !== hit.row) setDividerSelection(hit.row);
    const ends = dividerEnds(hit.row);
    const axis = dividerAxis(ends);
    if (hit.part === "end1" || hit.part === "end2") {
      const movingFirst = hit.part === "end1";
      const fixed = movingFirst ? { x: ends.x2, y: ends.y2 } : { x: ends.x1, y: ends.y1 };
      let ux = axis.ux;
      let uy = axis.uy;
      if (axis.len < 1e-6) {
        ux = movingFirst ? -1 : 1;
        uy = 0;
      } else if (movingFirst) {
        ux = -axis.ux;
        uy = -axis.uy;
      }
      planDrag = {
        mode: "length",
        end: hit.part,
        row: hit.row,
        fixed,
        anchor: { x: fixed.x, y: fixed.y },
        ux,
        uy,
        innerL: view.innerL,
        innerW: view.innerW,
        minLen: Math.max(10, 2 * view.wall),
      };
      setPlanCursor(lengthCursorClass(ux, uy));
    } else {
      planDrag = {
        mode: "slide",
        row: hit.row,
        ends,
        axis,
        x0: p.x,
        y0: p.y,
        innerL: view.innerL,
        innerW: view.innerW,
        minLen: Math.max(10, 2 * view.wall),
        attached: abuttingEnds(hit.row, ends),
      };
      setPlanCursor("is-sliding");
    }
    canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener("pointermove", (event) => {
    const view = planView();
    const p = view.toMm(event.clientX, event.clientY);
    if (!planDrag) {
      hoverPlan(view, p.x, p.y);
      return;
    }
    if (planDrag.mode === "slide") applySlide(planDrag, p.x, p.y);
    else applyLength(planDrag, p.x, p.y);
    paintPlan();
    kickPreview();
  });

  const endDrag = (event) => {
    if (!planDrag) return;
    planDrag = null;
    draw();
    const view = planView();
    const p = view.toMm(event.clientX, event.clientY);
    hoverPlan(view, p.x, p.y);
  };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);
}

function redraw() {
  paintPlan();
  if (!lastPreview) return;
  paint3d(lastPreview.triangles, lastPreview.parts);
  paint2d(lastPreview.panels);
}

function caption(p, pieceCount) {
  const ol = p.length;
  const ow = p.width;
  const pieces = pieceCount == null ? "" : ` · ${pieceCount} pieces`;
  el("dims").textContent =
    `Insert outer ${ol.toFixed(1)} × ${ow.toFixed(1)} mm · wall ${p.thickness} mm · H ${p.height} mm` +
    (p.floor ? " · floor ON" : " · floorless") + pieces;
}

function kickPreview() {
  if (previewBusy || previewTimer != null) return;
  previewTimer = setTimeout(refreshPreview, 60);
}

function draw() {
  syncHeightOverall();
  paintPlan();
  clearTimeout(previewTimer);
  previewTimer = setTimeout(refreshPreview, 60);
}

async function refreshPreview() {
  previewTimer = null;
  const gen = ++previewGen;
  previewBusy = true;
  try {
    const p = readParams();
    if (fields.some((f) => Number.isNaN(p[f]))) return;
    caption(p);
    if (previewAbort) previewAbort.abort();
    previewAbort = new AbortController();
    const res = await fetch("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p),
      signal: previewAbort.signal,
    });
    if (gen !== previewGen) return;
    if (!res.ok) throw new Error(await res.text());
    lastPreview = await res.json();
    if (gen !== previewGen) return;
    caption(p, lastPreview.panels.length);
    redraw();
  } catch (err) {
    if (gen !== previewGen) return;
    if (err.name !== "AbortError") {
      el("dims").textContent = `Preview failed: ${err.message || err}`;
    }
  } finally {
    if (gen === previewGen) {
      previewBusy = false;
      if (planDrag) kickPreview();
    }
  }
}

function bindOrbit() {
  const canvas = el("view3d");
  let drag = null;
  canvas.addEventListener("pointerdown", (event) => {
    drag = { x: event.clientX, y: event.clientY, yaw: orbit.yaw, pitch: orbit.pitch };
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!drag) return;
    orbit.yaw = drag.yaw - (event.clientX - drag.x) * 0.008;
    orbit.pitch = Math.max(-1.2, Math.min(1.2, drag.pitch + (event.clientY - drag.y) * 0.008));
    redraw();
  });
  const end = () => { drag = null; };
  canvas.addEventListener("pointerup", end);
  canvas.addEventListener("pointercancel", end);
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    orbit.zoom = Math.max(0.55, Math.min(2.8, orbit.zoom * (event.deltaY > 0 ? 0.92 : 1.08)));
    redraw();
  }, { passive: false });
}

async function loadDefaults() {
  const res = await fetch("/api/defaults");
  const d = await res.json();
  dimMode = "inside";
  updateDimLabels();
  for (const f of fields) el(f).value = d[f];
  const wall = d.thickness || 0;
  el("length").value = roundMm(d.length - 2 * wall);
  el("width").value = roundMm(d.width - 2 * wall);
  el("height").value = roundMm(d.height - (d.floor ? wall : 0));
  el("floor").checked = !!d.floor;
  lidMode = knownLid(d.lid);
  latchCount = d.lid_latch_count === 2 ? 2 : 1;
  latchSide = ["front", "back", "left", "right"].includes(d.lid_latch_side) ? d.lid_latch_side : "front";
  el("lid-latch-loops").value = d.lid_latch_loops ?? 4;
  el("lid-latch-beam").value = d.lid_latch_beam ?? 2;
  el("lid-latch-width").value = d.lid_latch_width ?? 30;
  slideDir = ["front", "left", "right", "back"].includes(d.lid_slide) ? d.lid_slide : "back";
  slideCount = d.lid_slide_count === 3 ? 3 : 2;
  tabFit = d.lid_tab_fit === "outer" ? "outer" : "inner";
  el("lid-height").value = d.lid_height ?? 15;
  el("lid-slide-tab").value = d.lid_slide_tab ?? 20;
  el("lid-tabs-on").checked = !!d.lid_tabs;
  el("lid-tab-height").value = d.lid_tab_height ?? 12;
  const corners = new Set(d.lid_tab_corners || ["front-left", "back-right"]);
  document.querySelectorAll("#lid-tab-corners input").forEach((input) => {
    input.checked = corners.has(input.dataset.corner);
  });
  syncLidFields();
  syncDimLimits();
  enforceSlideTab();
  el("dividers").innerHTML = "";
  (d.dividers || []).forEach((div) => addDividerRow({
    ...div,
    x1: div.x1 - wall,
    y1: div.y1 - wall,
    x2: div.x2 - wall,
    y2: div.y2 - wall,
  }));
  draw();
}

function asNumber(value, fallback) {
  const n = typeof value === "number" ? value : parseFloat(value);
  return Number.isFinite(n) ? n : fallback;
}

const DESIGN_VERSION = 2;

function designConfig() {
  return {
    version: DESIGN_VERSION,
    measure: dimMode === "outside" ? "outside" : "inside",
    snap: el("snap-mm").checked,
    length: asNumber(el("length").value, 0),
    width: asNumber(el("width").value, 0),
    height: asNumber(el("height").value, 0),
    thickness: asNumber(el("thickness").value, 3),
    kerf: asNumber(el("kerf").value, 0),
    finger_length: asNumber(el("finger_length").value, 10),
    floor: el("floor").checked,
    lid: lidMode,
    lid_height: asNumber(el("lid-height").value, 15),
    lid_tabs: el("lid-tabs-on").checked,
    lid_tab_height: asNumber(el("lid-tab-height").value, 12),
    lid_tab_fit: tabFit,
    lid_tab_corners: [...document.querySelectorAll("#lid-tab-corners input:checked")].map(
      (input) => input.dataset.corner
    ),
    lid_slide: slideDir,
    lid_slide_count: slideCount,
    lid_slide_tab: asNumber(el("lid-slide-tab").value, 20),
    lid_latch_side: latchSide,
    lid_latch_count: latchCount === 2 ? 2 : 1,
    lid_latch_loops: parseInt(el("lid-latch-loops").value, 10) || 4,
    lid_latch_beam: asNumber(el("lid-latch-beam").value, 2),
    lid_latch_width: asNumber(el("lid-latch-width").value, 30),
    dividers: dividerRows().map((row) => {
      const n = (cls) => asNumber(row.querySelector(cls).value, 0);
      return {
        label: (row.dataset.label || "").replace(/\s+/g, " ").trim().slice(0, 40),
        x1: n(".x1"),
        y1: n(".y1"),
        x2: n(".x2"),
        y2: n(".y2"),
        bottom: n(".h-bottom"),
        top: n(".h-top"),
        heightUnit: row.dataset.heightUnit === "pct" ? "pct" : "mm",
        tilt: n(".h-tilt"),
        floor_fingers: row.querySelector(".h-floor-fingers").checked,
        top_fingers: row.querySelector(".h-top-fingers").checked,
      };
    }),
  };
}

function designProblems(data) {
  const problems = [];
  if (!data || typeof data !== "object" || Array.isArray(data) || !Number.isInteger(data.version)) {
    return ["This file is not a saved box design."];
  }
  if (data.version > DESIGN_VERSION) {
    return ["This file was saved by a newer version of this page."];
  }
  if (data.version < 1) {
    return ["This file is not a saved box design."];
  }
  const measure = data.measure;
  if (measure !== "inside" && measure !== "outside") {
    problems.push("Sizes must be marked inside or outside.");
  }
  const thickness = asNumber(data.thickness, NaN);
  if (!Number.isFinite(thickness) || thickness < 3 || thickness > 6) {
    problems.push("Thickness must be from 3 to 6 mm.");
  }
  const length = asNumber(data.length, NaN);
  const width = asNumber(data.width, NaN);
  const height = asNumber(data.height, NaN);
  if (!Number.isFinite(length)) problems.push("Length must be a number.");
  if (!Number.isFinite(width)) problems.push("Width must be a number.");
  if (!Number.isFinite(height)) problems.push("Height must be a number.");
  if (Number.isFinite(thickness)) {
    if (Number.isFinite(length)) {
      const outside = measure === "inside" ? length + 2 * thickness : length;
      if (!(outside > 10)) problems.push("Length must be more than 10 mm on the outside.");
    }
    if (Number.isFinite(width)) {
      const outside = measure === "inside" ? width + 2 * thickness : width;
      if (!(outside > 10)) problems.push("Width must be more than 10 mm on the outside.");
    }
  }
  if (typeof data.floor !== "boolean") problems.push("Floor must be on or off.");
  if (Number.isFinite(height) && Number.isFinite(thickness) && typeof data.floor === "boolean") {
    const outside = measure === "inside" && data.floor ? height + thickness : height;
    if (!(outside >= 10)) problems.push("Height must be at least 10 mm on the outside.");
  }
  const kerf = asNumber(data.kerf, NaN);
  if (!Number.isFinite(kerf) || kerf < 0) problems.push("Kerf must be zero or a positive number.");
  const fingerLength = asNumber(data.finger_length, NaN);
  if (data.version >= 2 || data.finger_length != null) {
    if (!Number.isFinite(fingerLength) || fingerLength < 4 || fingerLength > 40) {
      problems.push("Finger length must be from 4 to 40 mm.");
    }
  } else if (!Number.isInteger(data.finger_count) || data.finger_count < 3 || data.finger_count > 15) {
    problems.push("Finger count must be a whole number from 3 to 15.");
  }
  if (!["none", "cap", "top", "slide", "latch", "closed"].includes(data.lid)) {
    problems.push("Lid must be none, a cap, sit on top, tab and slot, latch, or a closed box.");
  }
  const latchRequired = data.version >= 2;
  if (latchRequired || data.lid_latch_side != null) {
    if (!["front", "back", "left", "right"].includes(data.lid_latch_side)) {
      problems.push("Latches on must be front, back, left, or right.");
    }
  }
  if (latchRequired || data.lid_latch_count != null) {
    if (data.lid_latch_count !== 1 && data.lid_latch_count !== 2) {
      problems.push("Latch tabs must be 1 or 2.");
    }
  }
  if (latchRequired || data.lid_latch_loops != null) {
    if (!Number.isInteger(data.lid_latch_loops) || data.lid_latch_loops < 2 || data.lid_latch_loops > 8) {
      problems.push("Loops must be a whole number from 2 to 8.");
    }
  }
  if (latchRequired || data.lid_latch_beam != null) {
    const latchBeam = asNumber(data.lid_latch_beam, NaN);
    if (!Number.isFinite(latchBeam) || latchBeam < 1 || latchBeam > 4) {
      problems.push("Beam must be from 1 to 4 mm.");
    }
  }
  if (latchRequired || data.lid_latch_width != null) {
    const latchWidth = asNumber(data.lid_latch_width, NaN);
    if (!Number.isFinite(latchWidth) || latchWidth < 14 || latchWidth > 80) {
      problems.push("Spring width must be from 14 to 80 mm.");
    }
  }
  const side = asNumber(data.lid_height, NaN);
  if (!Number.isFinite(side)) {
    problems.push("Lid side height must be a number.");
  } else if (Number.isFinite(thickness)) {
    const inside = measure === "outside" ? side - thickness : side;
    if (inside + 1e-6 < thickness || inside > 80) {
      problems.push("Lid side height must be at least the material thickness on the inside, and at most 80 mm.");
    }
  }
  if (typeof data.lid_tabs !== "boolean") problems.push("Alignment tabs must be on or off.");
  const tabHeight = asNumber(data.lid_tab_height, NaN);
  if (!Number.isFinite(tabHeight) || (Number.isFinite(thickness) && (tabHeight + 1e-6 < thickness || tabHeight > 40))) {
    problems.push("Tab height must be at least the material thickness, and at most 40 mm.");
  }
  if (data.lid_tab_fit !== "inner" && data.lid_tab_fit !== "outer") {
    problems.push("Tab fit must be inner or outer.");
  }
  const cornerNames = ["front-left", "front-right", "back-left", "back-right"];
  if (!Array.isArray(data.lid_tab_corners) || data.lid_tab_corners.some((corner) => !cornerNames.includes(corner))) {
    problems.push("Alignment tab corners are not recognized.");
  }
  if (!["back", "front", "left", "right"].includes(data.lid_slide)) {
    problems.push("Slide direction must be back, front, left, or right.");
  }
  if (data.lid_slide_count !== 2 && data.lid_slide_count !== 3) {
    problems.push("Side tabs must be 2 or 3.");
  }
  const slideTab = asNumber(data.lid_slide_tab, NaN);
  if (
    !Number.isFinite(slideTab) || slideTab <= 0 || slideTab > 80
    || (Number.isFinite(thickness) && slideTab + 1e-6 < thickness)
  ) {
    problems.push("Tab length must be at least the material thickness, and at most 80 mm.");
  }
  if (data.snap != null && typeof data.snap !== "boolean") problems.push("Snap must be on or off.");
  if (!Array.isArray(data.dividers)) {
    problems.push("Dividers must be a list.");
    return problems;
  }
  data.dividers.forEach((div, index) => {
    const label = div && typeof div.label === "string" ? div.label.trim() : "";
    const name = label ? `Divider "${label}"` : `Divider ${index + 1}`;
    if (!div || typeof div !== "object" || Array.isArray(div)) {
      problems.push(`${name} is not a divider.`);
      return;
    }
    if (["x1", "y1", "x2", "y2"].some((key) => !Number.isFinite(asNumber(div[key], NaN)))) {
      problems.push(`${name} is missing its position.`);
    }
    if (div.heightUnit !== "mm" && div.heightUnit !== "pct") {
      problems.push(`${name} must measure from floor and from top in mm or %.`);
    }
    const bottom = asNumber(div.bottom, NaN);
    const top = asNumber(div.top, NaN);
    if (!Number.isFinite(bottom) || !Number.isFinite(top)) {
      problems.push(`${name} from floor and from top must be numbers.`);
    } else if (div.heightUnit === "mm" && Number.isFinite(height) && Number.isFinite(thickness)) {
      const max = roundMm(Math.max(0, height - thickness));
      if (bottom < -1e-6 || bottom > max + 1e-6) {
        problems.push(`${name} from floor must be from 0 to ${max} mm.`);
      }
      if (top < -1e-6 || top > max + 1e-6) {
        problems.push(`${name} from top must be from 0 to ${max} mm.`);
      }
    } else if (div.heightUnit === "pct") {
      if (bottom < -1e-6 || bottom > 100) problems.push(`${name} from floor must be from 0 to 100%.`);
      if (top < -1e-6 || top > 100) problems.push(`${name} from top must be from 0 to 100%.`);
    }
    const tilt = asNumber(div.tilt, NaN);
    if (!Number.isFinite(tilt) || tilt < -75 || tilt > 75) {
      problems.push(`${name} tilt must be from -75 to 75 degrees.`);
    }
    if (typeof div.floor_fingers !== "boolean") {
      problems.push(`${name} finger joint to floor must be on or off.`);
    }
    if (data.version >= 2 || div.top_fingers != null) {
      if (typeof div.top_fingers !== "boolean") {
        problems.push(`${name} finger joint to top must be on or off.`);
      }
    }
    if (div.label != null && (typeof div.label !== "string" || div.label.length > 40)) {
      problems.push(`${name} name must be 40 characters or fewer.`);
    }
  });
  return problems;
}

function showDesignErrors(problems) {
  const list = el("design-errors");
  const snippet = el("design-json");
  list.replaceChildren();
  snippet.replaceChildren();
  snippet.hidden = true;
  if (!problems.length) {
    list.hidden = true;
    return;
  }
  list.hidden = false;
  for (const text of problems) {
    const item = document.createElement("li");
    item.textContent = text;
    list.appendChild(item);
  }
}

function jsonLines(text) {
  const lines = [];
  let start = 0;
  for (let i = 0; i < text.length; i++) {
    if (text[i] !== "\n" && text[i] !== "\r") continue;
    lines.push({ start, text: text.slice(start, i) });
    if (text[i] === "\r" && text[i + 1] === "\n") i++;
    start = i + 1;
  }
  lines.push({ start, text: text.slice(start) });
  return lines;
}

function jsonFaultAt(text, err) {
  const message = String((err && err.message) || "");
  const at = message.match(/position (\d+)/);
  if (at) return Math.max(0, Math.min(Number(at[1]), text.length));
  const lineCol = message.match(/line (\d+) column (\d+)/);
  if (!lineCol) return text.length;
  const lines = jsonLines(text);
  const line = lines[Math.max(0, Number(lineCol[1]) - 1)];
  if (!line) return text.length;
  return Math.min(line.start + Math.max(0, Number(lineCol[2]) - 1), text.length);
}

function showJsonFault(text, err) {
  const message = String((err && err.message) || "This file is not valid JSON.");
  const where = message.replace(/\s+at position \d+( \(line \d+ column \d+\))?/, "");
  showDesignErrors([where || "This file is not valid JSON."]);
  const lines = jsonLines(text);
  const index = jsonFaultAt(text, err);
  let lineNo = lines.findIndex((line, i) => {
    const next = lines[i + 1];
    return index >= line.start && (!next || index < next.start);
  });
  if (lineNo < 0) lineNo = lines.length - 1;
  const column = index - lines[lineNo].start;
  const first = Math.max(0, lineNo - 2);
  const last = Math.min(lines.length - 1, lineNo + 2);
  const snippet = el("design-json");
  snippet.replaceChildren();
  for (let n = first; n <= last; n++) {
    const row = document.createElement("div");
    const num = document.createElement("span");
    num.className = "json-fault-line";
    num.textContent = String(n + 1);
    row.appendChild(num);
    const source = lines[n].text;
    if (n !== lineNo) {
      row.append(document.createTextNode(source));
    } else {
      const at = Math.min(column, source.length);
      row.append(document.createTextNode(source.slice(0, at)));
      const mark = document.createElement("mark");
      const ch = source[at];
      mark.textContent = ch && ch !== " " && ch !== "\t" ? ch : "\u00a0";
      row.appendChild(mark);
      if (at < source.length) row.append(document.createTextNode(source.slice(at + 1)));
    }
    snippet.appendChild(row);
  }
  snippet.hidden = false;
}

function applyDesign(data) {
  const problems = designProblems(data);
  if (problems.length) {
    const error = new Error(problems[0]);
    error.problems = problems;
    throw error;
  }

  dimMode = data.measure === "outside" ? "outside" : "inside";
  el("length").value = data.length;
  el("width").value = data.width;
  el("height").value = data.height;
  el("thickness").value = data.thickness;
  el("kerf").value = asNumber(data.kerf, 0);
  if (data.finger_length != null) {
    el("finger_length").value = asNumber(data.finger_length, 10);
  } else if (Number.isInteger(data.finger_count) && data.finger_count > 0) {
    const outside = data.measure === "inside" && data.floor ? asNumber(data.height, 0) + asNumber(data.thickness, 0) : asNumber(data.height, 0);
    el("finger_length").value = roundMm(outside / data.finger_count);
  } else {
    el("finger_length").value = 10;
  }
  el("floor").checked = !!data.floor;
  el("snap-mm").checked = data.snap !== false;

  lidMode = knownLid(data.lid);
  latchCount = data.lid_latch_count === 2 ? 2 : 1;
  latchSide = ["front", "back", "left", "right"].includes(data.lid_latch_side) ? data.lid_latch_side : "front";
  el("lid-latch-loops").value = data.lid_latch_loops ?? 4;
  el("lid-latch-beam").value = asNumber(data.lid_latch_beam, 2);
  el("lid-latch-width").value = asNumber(data.lid_latch_width, 30);
  slideDir = ["front", "left", "right", "back"].includes(data.lid_slide) ? data.lid_slide : "back";
  slideCount = data.lid_slide_count === 3 ? 3 : 2;
  tabFit = data.lid_tab_fit === "outer" ? "outer" : "inner";
  el("lid-height").value = asNumber(data.lid_height, 15);
  el("lid-slide-tab").value = asNumber(data.lid_slide_tab, 20);
  el("lid-tabs-on").checked = !!data.lid_tabs;
  el("lid-tab-height").value = asNumber(data.lid_tab_height, 12);
  const corners = new Set(data.lid_tab_corners || ["front-left", "back-right"]);
  document.querySelectorAll("#lid-tab-corners input").forEach((input) => {
    input.checked = corners.has(input.dataset.corner);
  });

  selectedDivider = null;
  el("dividers").innerHTML = "";
  (data.dividers || []).forEach((div) => addDividerRow({
    label: div.label || "",
    x1: asNumber(div.x1, 0),
    y1: asNumber(div.y1, 0),
    x2: asNumber(div.x2, 0),
    y2: asNumber(div.y2, 0),
    bottom: asNumber(div.bottom, 0),
    top: asNumber(div.top, 0),
    heightUnit: div.heightUnit === "pct" ? "pct" : "mm",
    tilt: asNumber(div.tilt, 0),
    floor_fingers: div.floor_fingers !== false,
    top_fingers: div.top_fingers !== false,
  }));

  syncLidFields();
  syncDimLimits();
  enforceLidMins();
  enforceSlideTab();
  enforceAllDividerGaps();
  draw();
}

function designFileName() {
  const t = materialThickness();
  const shown = (id) => {
    const n = parseFloat(el(id).value);
    return Number.isFinite(n) ? n : 0;
  };
  const walls = dimMode === "inside" ? 2 * t : 0;
  const length = roundMm(shown("length") + walls);
  const width = roundMm(shown("width") + walls);
  const height = roundMm(outsideHeight());
  return `box-insert-${length}x${width}x${height}.json`;
}

function downloadDesign() {
  const name = designFileName();
  const blob = new Blob([JSON.stringify(designConfig(), null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
  el("status").textContent = `Downloaded ${name}`;
}

function uploadDesign(file) {
  const status = el("status");
  const reader = new FileReader();
  reader.onload = () => {
    let data;
    try {
      data = JSON.parse(String(reader.result));
    } catch (err) {
      showJsonFault(String(reader.result), err);
      const listed = el("design-errors").textContent;
      status.textContent = `Could not load that file. ${listed} The box on screen was not changed.`;
      return;
    }
    try {
      applyDesign(data);
      showDesignErrors([]);
      status.textContent = "Loaded the saved design. The settings on screen were replaced.";
    } catch (err) {
      const problems = err.problems || [err.message || "This file could not be read."];
      showDesignErrors(problems);
      status.textContent = problems.length === 1
        ? `Could not load that file. ${problems[0]} The box on screen was not changed.`
        : `Could not load that file. ${problems.length} problems. The box on screen was not changed.`;
    }
  };
  reader.onerror = () => {
    showDesignErrors(["Could not read that file."]);
    status.textContent = "Could not read that file. The box on screen was not changed.";
  };
  reader.readAsText(file);
}

async function doExport(fmt) {
  const status = el("status");
  status.textContent = `Building ${fmt.toUpperCase()}…`;
  try {
    const res = await fetch(`/api/export/${fmt}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readParams()),
    });
    if (!res.ok) throw new Error(await res.text());
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `insert.${fmt}`;
    a.click();
    URL.revokeObjectURL(a.href);
    status.textContent = `Downloaded insert.${fmt}`;
  } catch (err) {
    status.textContent = `Export failed: ${err.message || err}`;
  }
}

el("dim-inside").addEventListener("click", () => setDimMode("inside"));
el("dim-outside").addEventListener("click", () => setDimMode("outside"));
el("add-divider").addEventListener("click", () => {
  addDividerRow(newDividerDefaults());
  draw();
});

function setPreviewHeight(canvas, px) {
  const next = Math.max(140, Math.min(window.innerHeight * 0.85, px));
  canvas.style.aspectRatio = "auto";
  canvas.style.height = `${Math.round(next)}px`;
}

function bindPreviewResize(handle, canvas) {
  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    const startY = event.clientY;
    const startH = canvas.getBoundingClientRect().height;
    try { handle.setPointerCapture(event.pointerId); } catch (err) { /* drag still follows the pointer */ }
    const move = (ev) => setPreviewHeight(canvas, startH + (ev.clientY - startY));
    const end = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
  });
  handle.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    event.preventDefault();
    const delta = event.key === "ArrowDown" ? 32 : -32;
    setPreviewHeight(canvas, canvas.getBoundingClientRect().height + delta);
  });
}

function fitDrawing() {
  drawingView.zoom = 1;
  drawingView.panX = 0;
  drawingView.panY = 0;
  redraw();
}

function bindDrawing() {
  const canvas = el("drawing");
  let drag = null;
  canvas.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    drag = { x: event.clientX, y: event.clientY, panX: drawingView.panX, panY: drawingView.panY };
    try { canvas.setPointerCapture(event.pointerId); } catch (err) { /* drag still follows the pointer */ }
    canvas.classList.add("is-panning");
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!drag) return;
    drawingView.panX = drag.panX + (event.clientX - drag.x);
    drawingView.panY = drag.panY + (event.clientY - drag.y);
    redraw();
  });
  const end = () => {
    drag = null;
    canvas.classList.remove("is-panning");
  };
  canvas.addEventListener("pointerup", end);
  canvas.addEventListener("pointercancel", end);
  canvas.addEventListener("dblclick", fitDrawing);
  el("drawing-fit").addEventListener("click", fitDrawing);
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    if (!drawingFrame) return;
    const rect = canvas.getBoundingClientRect();
    const borderLeft = parseFloat(getComputedStyle(canvas).borderLeftWidth) || 0;
    const borderTop = parseFloat(getComputedStyle(canvas).borderTopWidth) || 0;
    const px = event.clientX - rect.left - borderLeft;
    const py = event.clientY - rect.top - borderTop;
    const { minX, minY, spanX, spanY, base, w, h } = drawingFrame;
    const oldScale = base * drawingView.zoom;
    const oldOx = (w - spanX * oldScale) / 2 + drawingView.panX;
    const oldOy = (h - spanY * oldScale) / 2 + drawingView.panY;
    const worldX = minX + (px - oldOx) / oldScale;
    const worldY = minY + (py - oldOy) / oldScale;
    const next = Math.max(1, Math.min(16, drawingView.zoom * (event.deltaY > 0 ? 0.92 : 1.08)));
    if (next <= 1.001) {
      drawingView.zoom = 1;
      drawingView.panX = 0;
      drawingView.panY = 0;
    } else {
      const newScale = base * next;
      drawingView.zoom = next;
      drawingView.panX = px - (worldX - minX) * newScale - (w - spanX * newScale) / 2;
      drawingView.panY = py - (worldY - minY) * newScale - (h - spanY * newScale) / 2;
    }
    redraw();
  }, { passive: false });
}
fields.forEach((f) => el(f).addEventListener("input", () => {
  if (f === "thickness") {
    syncDimLimits();
    enforceLidMins();
    enforceAllDividerGaps();
  }
  if (f === "length" || f === "width" || f === "thickness") enforceSlideTab();
  draw();
}));
el("height").addEventListener("change", enforceAllDividerGaps);
el("floor").addEventListener("change", () => {
  if (dimMode === "inside") {
    const sign = el("floor").checked ? -1 : 1;
    el("height").value = roundMm(parseFloat(el("height").value) + sign * materialThickness());
  }
  syncDimLimits();
  dividerRows().forEach(syncFloorJoint);
  dividerRows().forEach(syncTopJoint);
  enforceAllDividerGaps();
  draw();
});
el("lid").addEventListener("change", () => setLidMode(el("lid").value));
el("latch-tabs-1").addEventListener("click", () => setLatchCount(1));
el("latch-tabs-2").addEventListener("click", () => setLatchCount(2));
el("latch-front").addEventListener("click", () => setLatchSide("front"));
el("latch-back").addEventListener("click", () => setLatchSide("back"));
el("latch-left").addEventListener("click", () => setLatchSide("left"));
el("latch-right").addEventListener("click", () => setLatchSide("right"));
el("lid-latch-loops").addEventListener("input", draw);
el("lid-latch-beam").addEventListener("input", draw);
el("lid-latch-width").addEventListener("input", draw);
el("slide-back").addEventListener("click", () => setSlideDir("back"));
el("slide-front").addEventListener("click", () => setSlideDir("front"));
el("slide-left").addEventListener("click", () => setSlideDir("left"));
el("slide-right").addEventListener("click", () => setSlideDir("right"));
el("slide-tabs-2").addEventListener("click", () => setSlideCount(2));
el("slide-tabs-3").addEventListener("click", () => setSlideCount(3));
el("lid-slide-tab").addEventListener("input", draw);
el("lid-height").addEventListener("input", draw);
el("lid-tabs-on").addEventListener("change", () => { syncLidFields(); draw(); });
el("lid-tab-height").addEventListener("input", draw);
el("tab-inner").addEventListener("click", () => { tabFit = "inner"; syncLidFields(); draw(); });
el("tab-outer").addEventListener("click", () => { tabFit = "outer"; syncLidFields(); draw(); });
el("lid-tab-corners").addEventListener("change", draw);
document.querySelectorAll("[data-export]").forEach((btn) => {
  btn.addEventListener("click", () => doExport(btn.dataset.export));
});
el("design-download").addEventListener("click", downloadDesign);
el("design-upload").addEventListener("click", () => el("design-file").click());
el("design-file").addEventListener("change", () => {
  const file = el("design-file").files && el("design-file").files[0];
  el("design-file").value = "";
  if (file) uploadDesign(file);
});

function bindTips() {
  let open = null;

  function place(info) {
    const btn = info.querySelector(".info-btn");
    const tip = info.querySelector(".tip");
    const rect = btn.getBoundingClientRect();
    const margin = 8;
    const width = Math.min(260, window.innerWidth - margin * 2);
    tip.hidden = false;
    tip.style.width = `${width}px`;
    const height = tip.offsetHeight;
    let left = rect.left + rect.width / 2 - width / 2;
    left = Math.max(margin, Math.min(left, window.innerWidth - margin - width));
    let top = rect.bottom + 8;
    if (top + height > window.innerHeight - margin) {
      top = Math.max(margin, rect.top - 8 - height);
    }
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
  }

  function close(info) {
    info.querySelector(".info-btn").setAttribute("aria-expanded", "false");
    info.querySelector(".tip").hidden = true;
    if (open === info) open = null;
  }

  function show(info) {
    if (open && open !== info) close(open);
    open = info;
    info.querySelector(".info-btn").setAttribute("aria-expanded", "true");
    place(info);
  }

  document.querySelectorAll(".info").forEach((info) => {
    const btn = info.querySelector(".info-btn");
    info.addEventListener("mouseenter", () => show(info));
    info.addEventListener("mouseleave", () => close(info));
    btn.addEventListener("focus", () => show(info));
    btn.addEventListener("blur", () => close(info));
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
    });
  });

  window.addEventListener("scroll", () => { if (open) place(open); }, true);
  window.addEventListener("resize", () => { if (open) place(open); });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && open) {
      open.querySelector(".info-btn").blur();
      close(open);
    }
  });
}

loadDefaults();
bindTips();
bindOrbit();
bindPlan();
bindDrawing();
bindPreviewResize(el("plan-resize"), el("plan"));
bindPreviewResize(el("view3d-resize"), el("view3d"));
bindPreviewResize(el("drawing-resize"), el("drawing"));
const previewResize = new ResizeObserver(() => redraw());
previewResize.observe(el("plan"));
previewResize.observe(el("view3d"));
previewResize.observe(el("drawing"));
