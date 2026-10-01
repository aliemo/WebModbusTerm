const $ = (id) => document.getElementById(id);

const els = {
  mode: $("mode"),
  serialFields: $("serialFields"),
  tcpFields: $("tcpFields"),
  modbusSend: $("modbusSend"),
  port: $("port"),
  baudrate: $("baudrate"),
  bytesize: $("bytesize"),
  parity: $("parity"),
  stopbits: $("stopbits"),
  host: $("host"),
  tcpPort: $("tcpPort"),
  unitId: $("unitId"),
  connectBtn: $("connectBtn"),
  disconnectBtn: $("disconnectBtn"),
  connBadge: $("connBadge"),
  log: $("log"),
  autoscroll: $("autoscroll"),
  clearLog: $("clearLog"),
  logBuffer: $("logBuffer"),
  encoding: $("encoding"),
  lineEnding: $("lineEnding"),
  payload: $("payload"),
  sendBtn: $("sendBtn"),
  appendCrc: $("appendCrc"),
  crcPreview: $("crcPreview"),
  mbFunction: $("mbFunction"),
  mbAddress: $("mbAddress"),
  mbQuantity: $("mbQuantity"),
  mbValues: $("mbValues"),
  mbSendBtn: $("mbSendBtn"),
  refreshPorts: $("refreshPorts"),
  configSelect: $("configSelect"),
  refreshConfigs: $("refreshConfigs"),
  loadConfigBtn: $("loadConfigBtn"),
  configDesc: $("configDesc"),
  predefinedSelect: $("predefinedSelect"),
  runPredefinedBtn: $("runPredefinedBtn"),
  refreshCommands: $("refreshCommands"),
  predefinedPreview: $("predefinedPreview"),
  cmdId: $("cmdId"),
  cmdTitle: $("cmdTitle"),
  cmdValue: $("cmdValue"),
  cmdEncoding: $("cmdEncoding"),
  cmdLineEnding: $("cmdLineEnding"),
  cmdConfirm: $("cmdConfirm"),
  cmdImportFile: $("cmdImportFile"),
  cmdImportBrowse: $("cmdImportBrowse"),
  cmdImportName: $("cmdImportName"),
  cmdImportMode: $("cmdImportMode"),
  cmdImportBtn: $("cmdImportBtn"),
  cmdSaveBtn: $("cmdSaveBtn"),
  cmdNewBtn: $("cmdNewBtn"),
  cmdDeleteBtn: $("cmdDeleteBtn"),
};

let commands = [];
let crcTimer = null;
const LOG_BUFFER_KEY = "webmodbusterm.logBuffer";

function nowTs() {
  const d = new Date();
  const pad = (n, w = 2) => String(n).padStart(w, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;
}

function eventTs(ev) {
  return (ev && ev.ts) || nowTs();
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatDetail(data) {
  if (!data) return "request failed";
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
  return data.error || data.last_error || JSON.stringify(data);
}

function getLogBufferLimit() {
  const n = Number(els.logBuffer.value || 200);
  return Number.isFinite(n) && n > 0 ? n : 200;
}

let pendingActionTitle = "TX";

function setPendingAction(title) {
  pendingActionTitle = title || "TX";
}

function trimLog() {
  const limit = getLogBufferLimit();
  while (els.log.childElementCount > limit) {
    els.log.removeChild(els.log.firstChild);
  }
}

function appendLog(cls, text) {
  const line = document.createElement("div");
  line.className = cls;
  line.textContent = text;
  els.log.appendChild(line);
  trimLog();
  if (els.autoscroll.checked) els.log.scrollTop = els.log.scrollHeight;
}

function appendLogHtml(cls, html) {
  const line = document.createElement("div");
  line.className = cls;
  line.innerHTML = html;
  els.log.appendChild(line);
  trimLog();
  if (els.autoscroll.checked) els.log.scrollTop = els.log.scrollHeight;
}

function logMsg(cls, text) {
  appendConsoleRow({
    cls,
    ts: nowTs(),
    action: cls === "err" ? "Error" : "Info",
    hex: "-",
    ascii: text.replace(/^\[[^\]]+\]\s*/, ""),
  });
}

function setConnected(connected, detail = "") {
  els.connBadge.textContent = connected ? `Connected${detail ? " · " + detail : ""}` : "Disconnected";
  els.connBadge.classList.toggle("on", connected);
  els.connBadge.classList.toggle("off", !connected);
  els.connectBtn.disabled = connected;
  els.disconnectBtn.disabled = !connected;
}

function syncModeUi() {
  const mode = els.mode.value;
  const isTcp = mode === "modbus_tcp";
  const isModbus = mode === "modbus_rtu" || mode === "modbus_tcp";
  els.serialFields.classList.toggle("hidden", isTcp);
  els.tcpFields.classList.toggle("hidden", !isTcp);
  els.modbusSend.classList.toggle("hidden", !isModbus);
}

function ensureSelectValue(selectEl, value) {
  if (value === undefined || value === null || value === "") return;
  const str = String(value);
  if (![...selectEl.options].some((o) => o.value === str)) {
    const opt = document.createElement("option");
    opt.value = str;
    opt.textContent = str;
    selectEl.appendChild(opt);
  }
  selectEl.value = str;
}

function applyConnectionToForm(conn) {
  if (!conn) return;
  if (conn.mode) {
    els.mode.value = conn.mode;
    syncModeUi();
  }
  if (conn.port) ensureSelectValue(els.port, conn.port);
  ensureSelectValue(els.baudrate, conn.baudrate);
  ensureSelectValue(els.bytesize, conn.bytesize);
  if (conn.parity) els.parity.value = String(conn.parity).toUpperCase();
  ensureSelectValue(els.stopbits, conn.stopbits);
  if (conn.host) els.host.value = conn.host;
  if (conn.tcp_port !== undefined) els.tcpPort.value = conn.tcp_port;
  if (conn.unit_id !== undefined) els.unitId.value = conn.unit_id;
}

function sanitizeHexInput(text) {
  return String(text || "")
    .toUpperCase()
    .replace(/[^0-9A-F\s]/g, "")
    .replace(/\s+/g, " ")
    .replace(/^\s+/, "");
}

function isHexEncoding(selectEl) {
  return selectEl.value === "hex";
}

function enforceHexField(inputEl, encodingSelect) {
  if (!isHexEncoding(encodingSelect)) return false;
  const cleaned = sanitizeHexInput(inputEl.value);
  if (cleaned === inputEl.value) return false;
  const start = inputEl.selectionStart;
  const end = inputEl.selectionEnd;
  const diff = inputEl.value.length - cleaned.length;
  inputEl.value = cleaned;
  if (typeof start === "number") {
    const pos = Math.max(0, start - Math.max(0, diff));
    try {
      inputEl.setSelectionRange(pos, Math.max(0, end - Math.max(0, diff)));
    } catch (_) {
      /* ignore */
    }
  }
  return true;
}

function syncHexPlaceholders() {
  els.payload.placeholder = isHexEncoding(els.encoding) ? "01 03 00 00 00 0A" : "Type text…";
  els.cmdValue.placeholder = isHexEncoding(els.cmdEncoding) ? "01 03 00 00 00 0A" : "Type text…";
}

function parseHexLocal(text) {
  const cleaned = sanitizeHexInput(text).trim();
  if (!cleaned) return [];
  const out = [];
  for (const part of cleaned.split(/\s+/)) {
    let p = part;
    if (p.length % 2 === 1) p = "0" + p;
    for (let i = 0; i < p.length; i += 2) {
      const n = parseInt(p.slice(i, i + 2), 16);
      if (Number.isFinite(n)) out.push(n);
    }
  }
  return out;
}

function modbusCrc16Local(bytes) {
  let crc = 0xffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let i = 0; i < 8; i++) {
      crc = crc & 1 ? (crc >>> 1) ^ 0xa001 : crc >>> 1;
    }
  }
  return crc & 0xffff;
}

function bytesToHexLocal(bytes) {
  return bytes.map((b) => b.toString(16).toUpperCase().padStart(2, "0")).join(" ");
}

function crcHexLocal(bytes) {
  const crc = modbusCrc16Local(bytes);
  return `${(crc & 0xff).toString(16).toUpperCase().padStart(2, "0")} ${((crc >> 8) & 0xff)
    .toString(16)
    .toUpperCase()
    .padStart(2, "0")}`;
}

function getCrcMode() {
  const v = (els.appendCrc.value || "modbus").trim();
  if (v === "on") return "modbus";
  if (v === "off") return "none";
  return v;
}

function isCrcEnabled() {
  return getCrcMode() !== "none";
}

function computeCrcTailLocal(bytes, mode) {
  const m = getCrcMode() && mode ? mode : getCrcMode();
  const use = mode || getCrcMode();
  if (use === "none") return [];
  if (use === "modbus") {
    const crc = modbusCrc16Local(bytes);
    return [crc & 0xff, (crc >> 8) & 0xff];
  }
  if (use === "0x0000") return [0x00, 0x00];
  if (use === "0x00") return [0x00];
  if (use === "0xffff" || use === "0xFFFF") return [0xff, 0xff];
  if (use === "0xff" || use === "0xFF") return [0xff];
  if (use === "sum8") return [bytes.reduce((a, b) => (a + b) & 0xff, 0)];
  if (use === "xor8") return [bytes.reduce((a, b) => a ^ b, 0)];
  return [];
}

function formatCommandPreview(value, encoding, crcMode) {
  const enc = (encoding || "hex").toLowerCase();
  const mode = crcMode || getCrcMode();
  if (!value) return "";
  let body;
  let label;
  if (enc === "hex") {
    body = parseHexLocal(value);
    if (!body.length) return "";
    label = `hex: ${escapeHtml(bytesToHexLocal(body))}`;
  } else {
    body = Array.from(new TextEncoder().encode(value));
    label = `${escapeHtml(enc)}: ${escapeHtml(value)} → ${escapeHtml(bytesToHexLocal(body))}`;
  }
  if (mode === "none") return label;
  const tail = computeCrcTailLocal(body, mode);
  if (!tail.length) return label;
  return `${label} <span class="crc-part">${escapeHtml(bytesToHexLocal(tail))}</span>`;
}

function refreshCrcPreview() {
  const payload = els.payload.value.trim();
  const mode = getCrcMode();
  const encoding = els.encoding.value;

  els.crcPreview.classList.remove("hidden");
  if (!payload) {
    els.crcPreview.innerHTML =
      mode === "none"
        ? `${escapeHtml(encoding)}: <span class="hint-inline">type bytes</span>`
        : `${escapeHtml(encoding)}: <span class="hint-inline">type bytes — ${escapeHtml(mode)} trailer appears here</span>`;
    return;
  }

  els.crcPreview.innerHTML = formatCommandPreview(payload, encoding, mode) || "";
}

function scheduleCrcPreview() {
  clearTimeout(crcTimer);
  crcTimer = setTimeout(() => {
    refreshCrcPreview();
    refreshPredefinedCrcPreview();
  }, 80);
}

function onPayloadInput() {
  if (isHexEncoding(els.encoding)) enforceHexField(els.payload, els.encoding);
  syncSendBtn();
  scheduleCrcPreview();
}

function syncSendBtn() {
  els.sendBtn.disabled = !els.payload.value.trim();
}

function onEncodingChange() {
  if (isHexEncoding(els.encoding)) enforceHexField(els.payload, els.encoding);
  syncHexPlaceholders();
  syncSendBtn();
  scheduleCrcPreview();
}

function onCmdValueInput() {
  if (isHexEncoding(els.cmdEncoding)) enforceHexField(els.cmdValue, els.cmdEncoding);
}

function onCmdEncodingChange() {
  if (isHexEncoding(els.cmdEncoding)) enforceHexField(els.cmdValue, els.cmdEncoding);
  syncHexPlaceholders();
}

async function refreshPorts() {
  const res = await fetch("/api/ports");
  const data = await res.json();
  const current = els.port.value;
  els.port.innerHTML = "";
  for (const p of data.ports || []) {
    const opt = document.createElement("option");
    opt.value = p.device;
    opt.textContent = `${p.device} — ${p.description || "serial"}`;
    els.port.appendChild(opt);
  }
  if ([...els.port.options].some((o) => o.value === current)) els.port.value = current;
  if (!els.port.options.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No ports found";
    els.port.appendChild(opt);
  }
}

async function refreshConfigs() {
  const res = await fetch("/api/configs");
  const data = await res.json();
  const current = els.configSelect.value;
  els.configSelect.innerHTML = `<option value="">— select —</option>`;
  for (const c of data.configs || []) {
    const opt = document.createElement("option");
    opt.value = c.id;
    opt.textContent = c.name + (c.description ? ` — ${c.description}` : "");
    els.configSelect.appendChild(opt);
  }
  if (current && [...els.configSelect.options].some((o) => o.value === current)) {
    els.configSelect.value = current;
  }
}

async function loadYamlConfig() {
  const id = els.configSelect.value;
  if (!id) {
    logMsg("err", "[err] Select a YAML config first");
    return;
  }
  const res = await fetch(`/api/configs/${encodeURIComponent(id)}/load`, { method: "POST" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    logMsg("err", `[err] ${formatDetail(data)}`);
    return;
  }
  const cfg = data.config;
  els.configDesc.textContent = cfg.description || cfg.file || "";
  applyConnectionToForm(cfg.connection);
  logMsg("sys", `Loaded YAML config: ${cfg.name}`);
}

function selectedCommand() {
  return commands.find((c) => c.id === els.predefinedSelect.value) || null;
}

function refreshPredefinedCrcPreview() {
  const cmd = selectedCommand();
  if (!cmd || !cmd.value) {
    els.predefinedPreview.classList.add("hidden");
    els.predefinedPreview.textContent = "";
    return;
  }
  els.predefinedPreview.classList.remove("hidden");
  els.predefinedPreview.innerHTML = formatCommandPreview(
    cmd.value,
    cmd.encoding || "hex",
    getCrcMode()
  );
}

function renderPredefinedDropdown() {
  const current = els.predefinedSelect.value;
  els.predefinedSelect.innerHTML = "";
  if (!commands.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No commands in commands.yml";
    els.predefinedSelect.appendChild(opt);
    els.predefinedPreview.classList.add("hidden");
    els.predefinedPreview.textContent = "";
    return;
  }
  for (const cmd of commands) {
    const opt = document.createElement("option");
    opt.value = cmd.id;
    opt.textContent = cmd.title || cmd.id;
    els.predefinedSelect.appendChild(opt);
  }
  if (current && commands.some((c) => c.id === current)) els.predefinedSelect.value = current;
  updatePredefinedPreview();
}

function updatePredefinedPreview() {
  const cmd = selectedCommand();
  if (!cmd) {
    els.predefinedPreview.classList.add("hidden");
    els.predefinedPreview.textContent = "";
    return;
  }
  els.cmdId.value = cmd.id || "";
  els.cmdTitle.value = cmd.title || "";
  els.cmdValue.value = cmd.value || "";
  els.cmdEncoding.value = cmd.encoding || "hex";
  els.cmdLineEnding.value = cmd.line_ending || "none";
  els.cmdConfirm.checked = !!cmd.confirm;
  if (isHexEncoding(els.cmdEncoding)) enforceHexField(els.cmdValue, els.cmdEncoding);
  syncHexPlaceholders();
  refreshPredefinedCrcPreview();
}

async function refreshCommands() {
  const res = await fetch("/api/commands");
  const data = await res.json();
  commands = data.commands || [];
  renderPredefinedDropdown();
}

async function runPredefined() {
  const cmd = selectedCommand();
  if (!cmd) {
    logMsg("err", "[err] No predefined command selected");
    return;
  }
  if (cmd.confirm && !window.confirm(`Send “${cmd.title}”?`)) return;
  setPendingAction(cmd.title || cmd.id || "CMD");
  const res = await fetch("/api/commands/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      command_id: cmd.id,
      confirmed: !!cmd.confirm,
      append_crc: isCrcEnabled(),
      crc_mode: getCrcMode(),
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    logMsg("err", `[err] ${formatDetail(data)}`);
    return;
  }
  logMsg("sys", `Predefined OK: ${cmd.title}`);
}

function clearCommandForm() {
  els.cmdId.value = "";
  els.cmdTitle.value = "";
  els.cmdValue.value = "";
  els.cmdEncoding.value = "hex";
  els.cmdLineEnding.value = "none";
  els.cmdConfirm.checked = false;
  syncHexPlaceholders();
}

async function saveCommand() {
  const id = els.cmdId.value.trim();
  const title = els.cmdTitle.value.trim();
  if (!id || !title) {
    logMsg("err", "[err] ID and Title are required");
    return;
  }
  if (isHexEncoding(els.cmdEncoding)) {
    enforceHexField(els.cmdValue, els.cmdEncoding);
    if (!els.cmdValue.value.trim()) {
      logMsg("err", "[err] HEX value is empty or invalid");
      return;
    }
  }
  const body = {
    id,
    title,
    value: els.cmdValue.value,
    encoding: els.cmdEncoding.value,
    line_ending: els.cmdLineEnding.value,
    confirm: els.cmdConfirm.checked,
    append_crc: true,
  };
  const res = await fetch("/api/commands", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    logMsg("err", `[err] ${formatDetail(data)}`);
    return;
  }
  commands = data.commands || [];
  renderPredefinedDropdown();
  els.predefinedSelect.value = id;
  updatePredefinedPreview();
  logMsg("sys", `Saved to commands.yml: ${title}`);
}

async function deleteCommand() {
  const id = els.cmdId.value.trim() || els.predefinedSelect.value;
  if (!id) {
    logMsg("err", "[err] Select a command to delete");
    return;
  }
  if (!window.confirm(`Delete “${id}” from commands.yml?`)) return;
  const res = await fetch(`/api/commands/${encodeURIComponent(id)}`, { method: "DELETE" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    logMsg("err", `[err] ${formatDetail(data)}`);
    return;
  }
  commands = data.commands || [];
  clearCommandForm();
  renderPredefinedDropdown();
  logMsg("sys", `Deleted from commands.yml: ${id}`);
}

async function connect() {
  const mode = els.mode.value;
  const body = {
    mode,
    port: els.port.value,
    baudrate: Number(els.baudrate.value),
    bytesize: Number(els.bytesize.value),
    parity: els.parity.value,
    stopbits: Number(els.stopbits.value),
    host: els.host.value.trim(),
    tcp_port: Number(els.tcpPort.value),
    unit_id: Number(els.unitId.value),
  };
  const res = await fetch("/api/connect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    logMsg("err", `[err] ${formatDetail(data)}`);
    return;
  }
  const detail = mode === "modbus_tcp" ? `${data.host}:${data.tcp_port}` : `${data.port} @ ${data.baudrate}`;
  setConnected(true, detail);
}

async function disconnect() {
  await fetch("/api/disconnect", { method: "POST" });
  setConnected(false);
}

async function sendRaw() {
  if (isHexEncoding(els.encoding)) {
    enforceHexField(els.payload, els.encoding);
    if (!els.payload.value.trim()) {
      logMsg("err", "[err] HEX payload is empty or invalid");
      return;
    }
  }
  setPendingAction("Raw Send");
  const res = await fetch("/api/send", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      payload: els.payload.value,
      encoding: els.encoding.value,
      line_ending: els.lineEnding.value,
      append_crc: isCrcEnabled(),
      crc_mode: getCrcMode(),
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) logMsg("err", `[err] ${formatDetail(data)}`);
}

function parseValues(text) {
  if (!text.trim()) return [];
  return text.split(",").map((p) => {
    const t = p.trim().toLowerCase();
    if (t === "true" || t === "on" || t === "1") return 1;
    if (t === "false" || t === "off" || t === "0") return 0;
    return Number(t);
  });
}

async function sendModbus() {
  setPendingAction(`Modbus ${els.mbFunction.value}`);
  const res = await fetch("/api/modbus", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      function: els.mbFunction.value,
      address: Number(els.mbAddress.value),
      quantity: Number(els.mbQuantity.value),
      values: parseValues(els.mbValues.value),
      unit_id: Number(els.unitId.value),
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) logMsg("err", `[err] ${formatDetail(data)}`);
}

function appendConsoleRow({ cls, ts, action, hex, ascii, hexHtml }) {
  const time = ts || nowTs();
  const actionText = action || "-";
  const hexText = hex || "-";
  const asciiText = ascii || "-";
  const hexCell = hexHtml
    ? hexHtml
    : `<span class="c-hex">${escapeHtml(hexText)}</span>`;
  appendLogHtml(
    cls || "sys",
    `<span class="c-time">${escapeHtml(time)}</span>` +
      `<span class="c-action">${escapeHtml(actionText)}</span>` +
      hexCell +
      `<span class="c-ascii">${escapeHtml(asciiText)}</span>`
  );
}

function normalizeHexCompact(text) {
  return String(text || "")
    .toUpperCase()
    .replace(/[^0-9A-F]/g, "");
}

function commandFrameVariants(cmd) {
  const encoding = (cmd.encoding || "hex").toLowerCase();
  const variants = new Set();
  if (encoding === "hex") {
    const body = parseHexLocal(cmd.value || "");
    if (!body.length) return variants;
    const bodyHex = normalizeHexCompact(bytesToHexLocal(body));
    variants.add(bodyHex);
    // Also try matching with active CRC mode trailer
    const mode = getCrcMode();
    if (mode !== "none" && encoding === "hex") {
      const body = parseHexLocal(cmd.value || "");
      if (body.length) {
        const withCrc = normalizeHexCompact(bytesToHexLocal(body.concat(computeCrcTailLocal(body, mode))));
        variants.add(withCrc);
      }
    }
  } else {
    const body = Array.from(new TextEncoder().encode(String(cmd.value || "")));
    if (!body.length) return variants;
    const bodyHex = normalizeHexCompact(bytesToHexLocal(body));
    variants.add(bodyHex);
    variants.add(bodyHex + normalizeHexCompact(crcHexLocal(body)));
    const mode = getCrcMode();
    if (mode !== "none") {
      variants.add(normalizeHexCompact(bytesToHexLocal(body.concat(computeCrcTailLocal(body, mode)))));
    }
  }
  return variants;
}

function matchCommandFromFrame(ev) {
  const frame = normalizeHexCompact(ev.frame_hex || ev.hex || "");
  const bodyOnly = normalizeHexCompact(ev.payload_hex || "");
  if (!frame && !bodyOnly) return null;

  for (const cmd of commands) {
    const variants = commandFrameVariants(cmd);
    if (
      (frame && variants.has(frame)) ||
      (bodyOnly && variants.has(bodyOnly)) ||
      (frame && bodyOnly && variants.has(bodyOnly))
    ) {
      return cmd.title || cmd.id || null;
    }
    // Also match if RX is a normal Modbus response echoing request FC/address
    // Keep strict frame match only for now.
  }
  return null;
}

function formatFrameLog(dir, ev) {
  const ts = eventTs(ev);
  const isTx = dir === "tx";
  let action;
  if (isTx) {
    action = pendingActionTitle || "TX";
    pendingActionTitle = "TX";
  } else {
    action = matchCommandFromFrame(ev) || "--";
  }

  let hexHtml;
  if (ev.crc_hex) {
    const crcClass = ev.crc_ok === false ? "crc-bad" : "crc-part";
    hexHtml =
      `<span class="c-hex">${escapeHtml(ev.payload_hex || "")} ` +
      `<span class="${crcClass}">${escapeHtml(ev.crc_hex)}</span></span>`;
  } else {
    hexHtml = `<span class="c-hex">${escapeHtml(ev.frame_hex || ev.hex || "-")}</span>`;
  }

  appendConsoleRow({
    cls: dir,
    ts,
    action,
    ascii: ev.ascii || "-",
    hexHtml,
  });
}

function handleEvent(ev) {
  const ts = eventTs(ev);
  if (ev.type === "rx") {
    formatFrameLog("rx", ev);
  } else if (ev.type === "tx") {
    formatFrameLog("tx", ev);
  } else if (ev.type === "modbus") {
    const action = ev.ok
      ? `Modbus ${ev.function}`
      : `Modbus ${ev.function} FAIL`;
    appendConsoleRow({
      cls: ev.ok ? "mb" : "err",
      ts,
      action,
      hex: `addr=${ev.address} qty=${ev.quantity} unit=${ev.unit_id}`,
      ascii: ev.ok ? JSON.stringify(ev.values) : ev.error || "error",
    });
  } else if (ev.type === "command") {
    // TX row already carries the command title/hex/ascii
    return;
  } else if (ev.type === "config") {
    appendConsoleRow({
      cls: "sys",
      ts,
      action: "Config",
      hex: "-",
      ascii: ev.message || "config",
    });
  } else if (ev.type === "error") {
    appendConsoleRow({
      cls: "err",
      ts,
      action: "Error",
      hex: "-",
      ascii: ev.message || "error",
    });
    setConnected(false);
  } else if (ev.type === "status" || ev.type === "hello") {
    appendConsoleRow({
      cls: "sys",
      ts,
      action: "Status",
      hex: "-",
      ascii: ev.message || "status",
    });
    if (typeof ev.connected === "boolean") {
      const detail =
        ev.mode === "modbus_tcp"
          ? `${ev.host}:${ev.tcp_port}`
          : ev.port
            ? `${ev.port} @ ${ev.baudrate}`
            : "";
      setConnected(ev.connected, detail);
    }
  } else {
    appendConsoleRow({
      cls: "sys",
      ts,
      action: ev.type || "Event",
      hex: "-",
      ascii: JSON.stringify(ev),
    });
  }
}

function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (msg) => {
    try {
      handleEvent(JSON.parse(msg.data));
    } catch (e) {
      logMsg("err", String(e));
    }
  };
  ws.onclose = () => {
    logMsg("sys", "WebSocket closed — reconnecting…");
    setTimeout(connectWs, 1500);
  };
  setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) ws.send("ping");
  }, 20000);
}

els.mode.addEventListener("change", syncModeUi);
els.refreshPorts.addEventListener("click", refreshPorts);
els.refreshConfigs.addEventListener("click", refreshConfigs);
els.loadConfigBtn.addEventListener("click", loadYamlConfig);
els.refreshCommands.addEventListener("click", (e) => {
  e.preventDefault();
  e.stopPropagation();
  refreshCommands();
});
els.predefinedSelect.addEventListener("change", updatePredefinedPreview);
els.runPredefinedBtn.addEventListener("click", runPredefined);
els.connectBtn.addEventListener("click", connect);
els.disconnectBtn.addEventListener("click", disconnect);
els.clearLog.addEventListener("click", () => {
  els.log.innerHTML = "";
});
els.logBuffer.addEventListener("change", () => {
  localStorage.setItem(LOG_BUFFER_KEY, els.logBuffer.value);
  trimLog();
});
const savedBuffer = localStorage.getItem(LOG_BUFFER_KEY);
if (savedBuffer && [...els.logBuffer.options].some((o) => o.value === savedBuffer)) {
  els.logBuffer.value = savedBuffer;
}
els.sendBtn.addEventListener("click", sendRaw);
els.payload.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !els.sendBtn.disabled) sendRaw();
});
els.payload.addEventListener("input", onPayloadInput);
els.encoding.addEventListener("change", onEncodingChange);
els.appendCrc.addEventListener("change", scheduleCrcPreview);
els.cmdValue.addEventListener("input", onCmdValueInput);
els.cmdEncoding.addEventListener("change", onCmdEncodingChange);
els.mbSendBtn.addEventListener("click", sendModbus);
async function importCommandsFile() {
  const file = els.cmdImportFile.files && els.cmdImportFile.files[0];
  if (!file) {
    logMsg("err", "[err] Choose a YAML or CSV file first");
    return;
  }
  const body = new FormData();
  body.append("file", file);
  body.append("mode", els.cmdImportMode.value || "replace");
  const res = await fetch("/api/commands/import", { method: "POST", body });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    logMsg("err", `[err] ${formatDetail(data)}`);
    return;
  }
  commands = data.commands || [];
  renderPredefinedDropdown();
  logMsg("sys", `Imported ${data.imported || 0} commands (${data.mode}) from ${file.name}`);
  els.cmdImportFile.value = "";
  updateImportFileUi();
}

function updateImportFileUi() {
  const file = els.cmdImportFile.files && els.cmdImportFile.files[0];
  if (file) {
    els.cmdImportName.textContent = file.name;
    els.cmdImportName.title = file.name;
    els.cmdImportName.classList.remove("is-empty");
    els.cmdImportName.classList.add("has-file");
    els.cmdImportBtn.disabled = false;
  } else {
    els.cmdImportName.textContent = "No file selected";
    els.cmdImportName.title = "";
    els.cmdImportName.classList.add("is-empty");
    els.cmdImportName.classList.remove("has-file");
    els.cmdImportBtn.disabled = true;
  }
}

els.cmdImportBrowse.addEventListener("click", () => els.cmdImportFile.click());
els.cmdImportFile.addEventListener("change", updateImportFileUi);
els.cmdImportBtn.addEventListener("click", importCommandsFile);
els.cmdSaveBtn.addEventListener("click", saveCommand);
els.cmdNewBtn.addEventListener("click", clearCommandForm);
els.cmdDeleteBtn.addEventListener("click", deleteCommand);

syncModeUi();
syncHexPlaceholders();
syncSendBtn();
refreshPorts();
refreshConfigs();
refreshCommands();
scheduleCrcPreview();
connectWs();
fetch("/api/status")
  .then((r) => r.json())
  .then((s) => {
    if (s.connected) {
      const detail =
        s.mode === "modbus_tcp" ? `${s.host}:${s.tcp_port}` : `${s.port} @ ${s.baudrate}`;
      setConnected(true, detail);
    }
  })
  .catch(() => {});
