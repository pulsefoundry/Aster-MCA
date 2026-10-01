"use strict";

const $ = (id) => document.getElementById(id);
const nf = new Intl.NumberFormat("zh-CN");
const state = {
  connected: false,
  info: null,
  stats: null,
  spectrum: new Array(4096).fill(0),
  autoRefresh: true,
  refreshMs: 5000,
  pollTimer: null,
  busy: false,
  xMin: 0,
  xMax: 4095,
  roi: null,
  dragStart: null,
  hoverChannel: null,
  lastRateSample: null,
  instantCps: 0,
  timedDeadline: null,
  timedTimer: null,
  finalizingTimed: false,
  lastSnapshotTimestamp: null,
};

const modeNames = ["peak", "area", "area2", "area4", "area8", "trapezoid4", "trapezoid8", "trapezoid16"];

function supportsEnergyModes() {
  return Boolean(state.info && (state.info.features & 0x20));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    headers: {"Content-Type": "application/json"},
    ...options,
  });
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function setMessage(text, kind = "") {
  const node = $("message");
  node.textContent = text;
  node.className = kind;
}

function setConnected(connected) {
  state.connected = connected;
  $("connectionPill").className = `status-pill ${connected ? "online" : "offline"}`;
  $("connectionText").textContent = connected ? "仪器在线" : "未连接";
  $("connectButton").textContent = connected ? "断开" : "连接仪器";
  for (const id of ["newAcquisition", "timedStart", "applyConfig", "saveCsv", "savePng"]) {
    $(id).disabled = !connected;
  }
  if (!connected) {
    state.lastRateSample = null;
    state.instantCps = 0;
  }
}

function fmtNumber(value, digits = 0) {
  if (value === undefined || value === null || !Number.isFinite(Number(value))) return "—";
  return Number(value).toLocaleString("zh-CN", {maximumFractionDigits: digits, minimumFractionDigits: digits});
}

function fmtDuration(seconds) {
  if (!Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return h ? `${h}:${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}` : `${m}:${String(s).padStart(2,"0")}`;
}

function spectrumAnalysis(low = state.roi?.[0] ?? state.xMin, high = state.roi?.[1] ?? state.xMax) {
  low = Math.max(0, Math.min(4095, Math.round(low)));
  high = Math.max(low, Math.min(4095, Math.round(high)));
  let total = 0, weighted = 0, peak = low, peakValue = -1;
  for (let i = low; i <= high; i++) {
    const count = state.spectrum[i] || 0;
    total += count;
    weighted += i * count;
    if (count > peakValue) { peakValue = count; peak = i; }
  }
  if (peakValue <= 0) return {low, high, total, centroid: null, peak: null, peakValue: 0, fwhm: null, resolution: null};
  const half = peakValue / 2;
  let left = peak, right = peak;
  while (left > low && state.spectrum[left] >= half) left--;
  while (right < high && state.spectrum[right] >= half) right++;
  let leftCross = left;
  let rightCross = right;
  if (left < peak) {
    const y0 = state.spectrum[left], y1 = state.spectrum[left + 1];
    if (y1 !== y0) leftCross = left + (half - y0) / (y1 - y0);
  }
  if (right > peak) {
    const y0 = state.spectrum[right - 1], y1 = state.spectrum[right];
    if (y1 !== y0) rightCross = right - 1 + (half - y0) / (y1 - y0);
  }
  const fwhm = Math.max(0, rightCross - leftCross);
  return {
    low, high, total,
    centroid: total ? weighted / total : null,
    peak, peakValue, fwhm,
    resolution: peak > 0 ? fwhm / peak * 100 : null,
  };
}

function updateRate(stats) {
  const current = {accepted: stats.accepted, live: stats.live_samples};
  const previous = state.lastRateSample;
  if (previous && current.live > previous.live && current.accepted >= previous.accepted) {
    state.instantCps = (current.accepted - previous.accepted) / ((current.live - previous.live) / 10_000_000);
  }
  state.lastRateSample = current;
}

function consumeSnapshot(data) {
  setConnected(true);
  if (data.info) state.info = data.info;
  if (data.stats) {
    updateRate(data.stats);
    state.stats = data.stats;
  }
  if (Array.isArray(data.histogram)) state.spectrum = data.histogram;
  state.lastSnapshotTimestamp = data.timestamp || Date.now() / 1000;
  syncControlsFromDevice();
  updateReadouts();
  drawSpectrum();
}

function syncControlsFromDevice() {
  if (!state.stats) return;
  $("threshold").value = state.stats.threshold;
  $("polarity").value = state.stats.polarity ? "negative" : "positive";
  $("energyMode").value = modeNames[state.stats.energy_mode] || "peak";
  $("energyMode").disabled = !supportsEnergyModes();
  $("energyMode").title = supportsEnergyModes()
    ? "固件支持峰高与脉冲面积能量估计"
    : "当前固件仅支持峰高模式";
}

function updateReadouts() {
  const stats = state.stats;
  const info = state.info;
  const analysis = spectrumAnalysis();
  const total = state.spectrum.reduce((sum, value) => sum + value, 0);

  $("totalEvents").textContent = state.connected ? nf.format(total) : "—";
  $("instantRate").textContent = state.connected ? fmtNumber(state.instantCps, 2) : "—";
  const live = stats ? stats.live_samples / 10_000_000 : NaN;
  const average = stats && live ? stats.accepted / live : 0;
  $("averageRate").textContent = stats ? fmtNumber(average, 2) : "—";
  $("liveTime").textContent = stats ? fmtDuration(live) : "—";
  $("peakChannel").textContent = analysis.peak === null ? "—" : nf.format(analysis.peak);
  $("resolution").textContent = analysis.resolution === null ? "—" : `${analysis.resolution.toFixed(2)}%`;

  $("adcCurrent").textContent = stats ? `${stats.sample} / ${stats.baseline}` : "—";
  $("adcRange").textContent = stats ? `${stats.adc_min} / ${stats.adc_max}` : "—";
  $("lastPeak").textContent = stats ? nf.format(stats.last_peak) : "—";
  $("lastEnergy").textContent = stats ? nf.format(stats.last_energy) : "—";
  $("triggerAccepted").textContent = stats ? `${nf.format(stats.triggers)} / ${nf.format(stats.accepted)}` : "—";
  $("rejectedSaturated").textContent = stats ? `${nf.format(stats.rejected)} / ${nf.format(stats.saturated)}` : "—";
  $("dropped").textContent = stats ? nf.format(stats.dropped) : "—";
  $("uartErrors").textContent = stats ? nf.format(stats.uart_errors) : "—";

  $("firmwareVersion").textContent = info ? `v${info.version}` : "—";
  $("adcInfo").textContent = info ? `${info.adc_bits} bit @ ${(info.sample_rate / 1e6).toFixed(0)} MSPS` : "—";
  $("histogramInfo").textContent = info ? `${info.channels} × 32 bit` : "—";
  $("uartInfo").textContent = info ? `${nf.format(info.baud)} baud` : "—";

  if (state.roi) {
    const roi = spectrumAnalysis(state.roi[0], state.roi[1]);
    const centroid = roi.centroid === null ? "—" : roi.centroid.toFixed(1);
    $("roiReadout").textContent = `${roi.low}–${roi.high} · ${nf.format(roi.total)} counts · μ ${centroid}`;
  } else {
    $("roiReadout").textContent = "未选择";
  }
}

async function connectOrDisconnect() {
  if (state.busy) return;
  state.busy = true;
  try {
    if (state.connected) {
      await api("/api/disconnect", {method: "POST", body: "{}"});
      setConnected(false);
      setMessage("仪器已断开。", "success");
      drawSpectrum();
    } else {
      setMessage("正在连接 CH347T 与 FPGA…");
      await api("/api/connect", {method: "POST", body: "{}"});
      const snapshot = await api("/api/snapshot?histogram=1");
      consumeSnapshot(snapshot);
      setMessage(`已连接，固件 v${snapshot.info.version}。`, "success");
      schedulePoll(0);
    }
  } catch (error) {
    setConnected(false);
    setMessage(`连接失败：${error.message}`, "error");
  } finally { state.busy = false; }
}

async function refreshSnapshot({quiet = false, force = false} = {}) {
  if (!state.connected || (state.busy && !force)) return;
  state.busy = true;
  try {
    const snapshot = await api("/api/snapshot?histogram=1");
    consumeSnapshot(snapshot);
    if (!quiet) setMessage(`谱图已更新 · ${new Date().toLocaleTimeString("zh-CN")}`, "success");
  } catch (error) {
    setMessage(`读取失败：${error.message}`, "error");
  } finally { state.busy = false; }
}

function schedulePoll(delay = state.refreshMs) {
  clearTimeout(state.pollTimer);
  if (!state.autoRefresh || !state.connected) return;
  state.pollTimer = setTimeout(async () => {
    await refreshSnapshot({quiet: true});
    schedulePoll();
  }, delay);
}

async function clearAcquisition() {
  if (!state.connected || state.busy) return false;
  state.busy = true;
  try {
    const snapshot = await api("/api/clear", {method: "POST", body: "{}"});
    state.lastRateSample = null;
    state.instantCps = 0;
    state.roi = null;
    consumeSnapshot(snapshot);
    setMessage("直方图和统计计数已清零，新的采集已经开始。", "success");
    return true;
  } catch (error) {
    setMessage(`清零失败：${error.message}`, "error");
    return false;
  } finally { state.busy = false; schedulePoll(); }
}

async function applyConfig() {
  if (!state.connected || state.busy) return;
  const payload = {
    threshold: Number($("threshold").value),
    polarity: $("polarity").value,
  };
  if (supportsEnergyModes()) payload.energy_mode = $("energyMode").value;
  state.busy = true;
  try {
    const snapshot = await api("/api/config", {method: "POST", body: JSON.stringify(payload)});
    state.lastRateSample = null;
    state.instantCps = 0;
    state.roi = null;
    consumeSnapshot(snapshot);
    setMessage(
      supportsEnergyModes()
        ? "算法设置已写入 FPGA。若能量模式发生变化，原谱已按协议清空。"
        : "阈值和极性已写入 FPGA；当前固件保持峰高模式。",
      "success",
    );
  } catch (error) { setMessage(`设置失败：${error.message}`, "error"); }
  finally { state.busy = false; schedulePoll(); }
}

async function startTimedAcquisition() {
  const seconds = Number($("duration").value);
  if (!Number.isFinite(seconds) || seconds <= 0) {
    setMessage("定时时间必须大于 0 秒。", "error");
    return;
  }
  if (!await clearAcquisition()) return;
  state.timedDeadline = Date.now() + seconds * 1000;
  state.finalizingTimed = false;
  state.autoRefresh = true;
  $("autoRefresh").checked = true;
  tickTimedAcquisition();
  schedulePoll(0);
  setMessage(`已开始 ${seconds} 秒定时采集。`, "success");
}

function tickTimedAcquisition() {
  clearTimeout(state.timedTimer);
  if (!state.timedDeadline) {
    $("timerDisplay").innerHTML = "<span>READY</span><strong>—</strong>";
    return;
  }
  const remaining = Math.max(0, (state.timedDeadline - Date.now()) / 1000);
  $("timerDisplay").innerHTML = `<span>${remaining > 0 ? "RUNNING" : "FINALIZING"}</span><strong>${fmtDuration(remaining)}</strong>`;
  if (remaining > 0) {
    state.timedTimer = setTimeout(tickTimedAcquisition, Math.min(250, remaining * 1000));
  } else if (!state.finalizingTimed) {
    state.finalizingTimed = true;
    finalizeTimedAcquisition();
  }
}

async function finalizeTimedAcquisition() {
  clearTimeout(state.pollTimer);
  await refreshSnapshot({quiet: true, force: true});
  state.autoRefresh = false;
  $("autoRefresh").checked = false;
  state.timedDeadline = null;
  state.finalizingTimed = false;
  $("timerDisplay").innerHTML = "<span>COMPLETE</span><strong>已冻结显示</strong>";
  setMessage("定时采集完成，当前显示快照已冻结；FPGA 仍会继续累计事件。", "success");
}

function filename(extension) {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  return `aster-mca-${stamp}.${extension}`;
}

function downloadBlob(blob, name) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function saveCsv() {
  if (!state.connected) return;
  const rows = ["channel,counts"];
  state.spectrum.forEach((count, channel) => rows.push(`${channel},${count}`));
  downloadBlob(new Blob([rows.join("\n") + "\n"], {type: "text/csv;charset=utf-8"}), filename("csv"));
  setMessage("已导出当前 4096 道 CSV 快照。", "success");
}

function savePng() {
  const canvas = $("spectrumCanvas");
  canvas.toBlob((blob) => {
    if (blob) downloadBlob(blob, filename("png"));
  }, "image/png");
  setMessage("已导出当前谱图 PNG。", "success");
}

function plotGeometry(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(600, Math.round(canvas.clientWidth));
  const height = Math.max(360, Math.round(canvas.clientHeight));
  if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return {ctx, width, height, left: 66, right: 20, top: 22, bottom: 46, dpr};
}

function drawSpectrum() {
  const canvas = $("spectrumCanvas");
  const g = plotGeometry(canvas);
  const {ctx, width, height, left, right, top, bottom} = g;
  const plotW = width - left - right, plotH = height - top - bottom;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#060e0c"; ctx.fillRect(0, 0, width, height);

  const low = state.xMin, high = state.xMax;
  const values = state.spectrum.slice(low, high + 1);
  const logScale = $("logScale").checked;
  const transformY = (v) => logScale ? Math.log10(v + 1) : v;
  let yMaxRaw = Math.max(1, ...values);
  let yMax = transformY(yMaxRaw);
  if (!logScale) yMax = niceCeil(yMax);

  ctx.lineWidth = 1;
  ctx.font = "10px ui-monospace, SFMono-Regular, Menlo, monospace";
  ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (let i = 0; i <= 5; i++) {
    const y = top + plotH * i / 5;
    ctx.strokeStyle = "rgba(109, 156, 136, .13)";
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(width - right, y); ctx.stroke();
    const transformed = yMax * (1 - i / 5);
    const label = logScale ? Math.round(Math.pow(10, transformed) - 1) : transformed;
    ctx.fillStyle = "#688177"; ctx.fillText(compactNumber(label), left - 9, y);
  }
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  for (let i = 0; i <= 8; i++) {
    const x = left + plotW * i / 8;
    const channel = Math.round(low + (high - low) * i / 8);
    ctx.strokeStyle = "rgba(109, 156, 136, .10)";
    ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, top + plotH); ctx.stroke();
    ctx.fillStyle = "#688177"; ctx.fillText(String(channel), x, top + plotH + 10);
  }

  if (state.roi) {
    const roiLeft = left + (Math.max(low, state.roi[0]) - low) / Math.max(1, high - low) * plotW;
    const roiRight = left + (Math.min(high, state.roi[1]) - low) / Math.max(1, high - low) * plotW;
    ctx.fillStyle = "rgba(231, 199, 120, .09)";
    ctx.fillRect(roiLeft, top, Math.max(0, roiRight - roiLeft), plotH);
  }

  const columns = Math.max(1, Math.floor(plotW));
  const aggregate = new Array(columns).fill(0);
  for (let index = 0; index < values.length; index++) {
    const column = Math.min(columns - 1, Math.floor(index / Math.max(1, values.length - 1) * (columns - 1)));
    aggregate[column] = Math.max(aggregate[column], values[index]);
  }
  ctx.beginPath();
  ctx.moveTo(left, top + plotH);
  aggregate.forEach((value, column) => {
    const x = left + column / Math.max(1, columns - 1) * plotW;
    const y = top + plotH * (1 - transformY(value) / Math.max(1e-9, yMax));
    ctx.lineTo(x, y);
  });
  ctx.lineTo(left + plotW, top + plotH); ctx.closePath();
  const gradient = ctx.createLinearGradient(0, top, 0, top + plotH);
  gradient.addColorStop(0, "rgba(101,230,167,.38)");
  gradient.addColorStop(1, "rgba(101,230,167,.015)");
  ctx.fillStyle = gradient; ctx.fill();

  ctx.beginPath();
  aggregate.forEach((value, column) => {
    const x = left + column / Math.max(1, columns - 1) * plotW;
    const y = top + plotH * (1 - transformY(value) / Math.max(1e-9, yMax));
    if (column === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = "#65e6a7"; ctx.lineWidth = 1.35; ctx.stroke();

  const analysis = spectrumAnalysis();
  if (analysis.peak !== null) {
    const px = left + (analysis.peak - low) / Math.max(1, high - low) * plotW;
    ctx.setLineDash([4, 4]); ctx.strokeStyle = "rgba(231,199,120,.75)";
    ctx.beginPath(); ctx.moveTo(px, top); ctx.lineTo(px, top + plotH); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = "#e7c778"; ctx.textAlign = "left"; ctx.textBaseline = "top";
    ctx.fillText(`peak ${analysis.peak}`, Math.min(px + 7, width - right - 70), top + 7);
  }

  ctx.fillStyle = "#718b80"; ctx.textAlign = "center"; ctx.textBaseline = "bottom";
  ctx.fillText("CHANNEL", left + plotW / 2, height - 7);
  ctx.save(); ctx.translate(13, top + plotH / 2); ctx.rotate(-Math.PI / 2);
  ctx.fillText(logScale ? "COUNTS · LOG₁₀" : "COUNTS", 0, 0); ctx.restore();

  if (state.hoverChannel !== null && state.hoverChannel >= low && state.hoverChannel <= high) {
    const x = left + (state.hoverChannel - low) / Math.max(1, high - low) * plotW;
    ctx.strokeStyle = "rgba(238,249,243,.32)"; ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, top + plotH); ctx.stroke();
  }
}

function niceCeil(value) {
  if (value <= 0) return 1;
  const magnitude = Math.pow(10, Math.floor(Math.log10(value)));
  const scaled = value / magnitude;
  const nice = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10;
  return nice * magnitude;
}

function compactNumber(value) {
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(value >= 1e4 ? 0 : 1)}k`;
  return String(Math.max(0, Math.round(value)));
}

function channelFromPointer(event) {
  const canvas = $("spectrumCanvas");
  const rect = canvas.getBoundingClientRect();
  const left = 66, right = 20;
  const x = Math.max(left, Math.min(rect.width - right, event.clientX - rect.left));
  return Math.round(state.xMin + (x - left) / Math.max(1, rect.width - left - right) * (state.xMax - state.xMin));
}

function updateTooltip(event) {
  const channel = channelFromPointer(event);
  state.hoverChannel = channel;
  const tooltip = $("plotTooltip");
  tooltip.hidden = false;
  tooltip.textContent = `CH ${channel}  ·  ${nf.format(state.spectrum[channel] || 0)} counts`;
  const shell = tooltip.parentElement.getBoundingClientRect();
  tooltip.style.left = `${Math.min(event.clientX - shell.left + 13, shell.width - 170)}px`;
  tooltip.style.top = `${Math.max(8, event.clientY - shell.top - 36)}px`;
  drawSpectrum();
}

function applyRange() {
  let low = Math.max(0, Math.min(4095, Number($("xMin").value)));
  let high = Math.max(0, Math.min(4095, Number($("xMax").value)));
  if (low > high) [low, high] = [high, low];
  if (high - low < 8) high = Math.min(4095, low + 8);
  state.xMin = Math.round(low); state.xMax = Math.round(high);
  $("xMin").value = state.xMin; $("xMax").value = state.xMax;
  updateReadouts(); drawSpectrum();
}

function bindEvents() {
  $("connectButton").addEventListener("click", connectOrDisconnect);
  $("newAcquisition").addEventListener("click", clearAcquisition);
  $("timedStart").addEventListener("click", startTimedAcquisition);
  $("applyConfig").addEventListener("click", applyConfig);
  $("saveCsv").addEventListener("click", saveCsv);
  $("savePng").addEventListener("click", savePng);
  $("logScale").addEventListener("change", drawSpectrum);
  $("refreshInterval").addEventListener("change", (event) => {
    state.refreshMs = Number(event.target.value); schedulePoll();
  });
  $("autoRefresh").addEventListener("change", (event) => {
    state.autoRefresh = event.target.checked; schedulePoll(state.autoRefresh ? 0 : undefined);
  });
  $("applyRange").addEventListener("click", applyRange);
  $("fullRange").addEventListener("click", () => {
    state.xMin = 0; state.xMax = 4095; $("xMin").value = 0; $("xMax").value = 4095;
    drawSpectrum();
  });
  $("clearRoi").addEventListener("click", () => { state.roi = null; updateReadouts(); drawSpectrum(); });
  window.addEventListener("resize", drawSpectrum);

  const canvas = $("spectrumCanvas");
  canvas.addEventListener("pointermove", (event) => {
    updateTooltip(event);
    if (state.dragStart !== null) {
      const channel = channelFromPointer(event);
      state.roi = [Math.min(state.dragStart, channel), Math.max(state.dragStart, channel)];
      updateReadouts(); drawSpectrum();
    }
  });
  canvas.addEventListener("pointerdown", (event) => {
    state.dragStart = channelFromPointer(event);
    state.roi = [state.dragStart, state.dragStart];
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointerup", (event) => {
    if (state.dragStart !== null) {
      const channel = channelFromPointer(event);
      state.roi = [Math.min(state.dragStart, channel), Math.max(state.dragStart, channel)];
      state.dragStart = null; updateReadouts(); drawSpectrum();
    }
  });
  canvas.addEventListener("pointerleave", () => {
    if (state.dragStart === null) {
      state.hoverChannel = null; $("plotTooltip").hidden = true; drawSpectrum();
    }
  });
  canvas.addEventListener("dblclick", () => {
    state.roi = null; state.xMin = 0; state.xMax = 4095;
    $("xMin").value = 0; $("xMax").value = 4095;
    updateReadouts(); drawSpectrum();
  });
}

async function initialise() {
  bindEvents(); setConnected(false); drawSpectrum();
  try {
    const status = await api("/api/status");
    if (status.connected) {
      const snapshot = await api("/api/snapshot?histogram=1");
      consumeSnapshot(snapshot);
      setMessage(`已连接，固件 v${snapshot.info.version}。`, "success");
      schedulePoll();
    }
  } catch (error) { setMessage(`本地服务异常：${error.message}`, "error"); }
}

initialise();
