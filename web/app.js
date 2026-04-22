const cpuMemChart = echarts.init(document.getElementById("cpuMemChart"));
const gpuChart = echarts.init(document.getElementById("gpuChart"));
const rangeSelect = document.getElementById("rangeSelect");
const statusLine = document.getElementById("statusLine");
const processTableBody = document.getElementById("processTableBody");
const gpuProcessTableBody = document.getElementById("gpuProcessTableBody");
const gpuDeviceTableBody = document.getElementById("gpuDeviceTableBody");
const cmdlineTooltip = document.getElementById("cmdlineTooltip");
const sortableHeaders = document.querySelectorAll("th.sortable");
let configText = "";
let currentCpuProcesses = [];
let currentGpuProcesses = [];
let cpuSortState = { key: "cpu_percent", order: "desc" };
let gpuSortState = { key: "used_gpu_memory_mb", order: "desc" };

function escAttr(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function renderNameCell(name, cmdline) {
  const safeName = escAttr(name || "-");
  const rawTooltip = cmdline || name || "-";
  const safeTooltip = escAttr(rawTooltip);
  return `<td class="name-cell" data-tooltip="${safeTooltip}">${safeName}</td>`;
}

function showCmdlineTooltip(text, mouseX, mouseY) {
  const raw = text || "-";
  cmdlineTooltip.innerHTML = `<pre><code>${renderCommandHighlight(raw)}</code></pre>`;
  cmdlineTooltip.style.display = "block";
  const margin = 14;
  const width = cmdlineTooltip.offsetWidth;
  const height = cmdlineTooltip.offsetHeight;
  const maxX = window.innerWidth - width - margin;
  const maxY = window.innerHeight - height - margin;
  const left = Math.min(maxX, mouseX + 16);
  const top = Math.min(maxY, mouseY + 16);
  cmdlineTooltip.style.left = `${Math.max(margin, left)}px`;
  cmdlineTooltip.style.top = `${Math.max(margin, top)}px`;
}

function hideCmdlineTooltip() {
  cmdlineTooltip.style.display = "none";
}

function classifyToken(token, index) {
  if (index === 0) return "cmdline-token-exec";
  if (/^--?[a-zA-Z0-9][a-zA-Z0-9_-]*/.test(token)) return "cmdline-token-flag";
  if (/^['"].*['"]$/.test(token)) return "cmdline-token-string";
  if (/^-?\d+(\.\d+)?$/.test(token)) return "cmdline-token-number";
  return "cmdline-token-plain";
}

function renderCommandHighlight(raw) {
  const chunks = (raw.match(/'[^']*'|\"[^\"]*\"|\S+/g) || [raw]).map((token, index) => {
    const klass = classifyToken(token, index);
    return `<span class="${klass}">${escAttr(token)}</span>`;
  });
  return chunks.join('<span class="cmdline-token-plain"> </span>');
}

function fmt(num, digits = 1) {
  if (num === null || num === undefined || Number.isNaN(num)) return "-";
  return Number(num).toFixed(digits);
}

function toLocalTime(ts) {
  return new Date(ts).toLocaleTimeString();
}

function renderCpuMem(points) {
  const x = points.map((p) => toLocalTime(p.timestamp));
  const cpu = points.map((p) => p.cpu_usage);
  const mem = points.map((p) => p.mem_usage);
  cpuMemChart.setOption({
    tooltip: { trigger: "axis" },
    legend: { data: ["CPU%", "内存%"], textStyle: { color: "#e2e8f0" } },
    xAxis: { type: "category", data: x, axisLabel: { color: "#94a3b8" } },
    yAxis: { type: "value", min: 0, max: 100, axisLabel: { color: "#94a3b8" } },
    series: [
      { name: "CPU%", type: "line", smooth: true, data: cpu },
      { name: "内存%", type: "line", smooth: true, data: mem },
    ],
  });
}

function renderGpu(points) {
  const x = points.map((p) => toLocalTime(p.timestamp));
  const gpuUtil = points.map((p) => (p.gpu_util === null ? null : p.gpu_util));
  const gpuMemPct = points.map((p) =>
    p.gpu_mem_total_mb ? (p.gpu_mem_used_mb / p.gpu_mem_total_mb) * 100 : null
  );
  gpuChart.setOption({
    tooltip: { trigger: "axis" },
    legend: { data: ["GPU%", "显存%"], textStyle: { color: "#e2e8f0" } },
    xAxis: { type: "category", data: x, axisLabel: { color: "#94a3b8" } },
    yAxis: { type: "value", min: 0, max: 100, axisLabel: { color: "#94a3b8" } },
    series: [
      { name: "GPU%", type: "line", smooth: true, data: gpuUtil },
      { name: "显存%", type: "line", smooth: true, data: gpuMemPct },
    ],
  });
}

function renderProcesses(processes) {
  processTableBody.innerHTML = "";
  for (const p of processes) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${p.pid}</td>
      ${renderNameCell(p.name, p.cmdline)}
      <td>${fmt(p.cpu_percent, 1)}</td>
      <td>${fmt(p.rss_mb, 1)}</td>
      <td>${p.user_name || "-"}</td>
    `;
    processTableBody.appendChild(tr);
  }
}

function renderGpuProcesses(rows) {
  gpuProcessTableBody.innerHTML = "";
  if (!rows.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = '<td colspan="5" class="muted">当前无 GPU 进程或 NVML 不可用</td>';
    gpuProcessTableBody.appendChild(tr);
    return;
  }
  for (const g of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${g.gpu_index}</td>
      <td>${g.pid}</td>
      ${renderNameCell(g.process_name, g.cmdline)}
      <td>${g.user_name || "-"}</td>
      <td>${fmt(g.used_gpu_memory_mb, 1)}</td>
    `;
    gpuProcessTableBody.appendChild(tr);
  }
}

function sortRows(rows, key, order) {
  const direction = order === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = a?.[key];
    const bv = b?.[key];
    const aMissing = av === null || av === undefined;
    const bMissing = bv === null || bv === undefined;
    if (aMissing && bMissing) return 0;
    if (aMissing) return 1;
    if (bMissing) return -1;
    if (typeof av === "number" && typeof bv === "number") {
      return (av - bv) * direction;
    }
    return String(av).localeCompare(String(bv), "zh-CN", { sensitivity: "base" }) * direction;
  });
}

function renderProcessTables() {
  renderProcesses(sortRows(currentCpuProcesses, cpuSortState.key, cpuSortState.order));
  renderGpuProcesses(sortRows(currentGpuProcesses, gpuSortState.key, gpuSortState.order));
  refreshSortHeaderIndicators();
}

function refreshSortHeaderIndicators() {
  for (const header of sortableHeaders) {
    const table = header.dataset.table;
    const key = header.dataset.sortKey;
    const state = table === "cpu" ? cpuSortState : gpuSortState;
    const base = header.dataset.baseLabel || header.textContent.replace(/[↑↓↕]$/, "").trim();
    header.dataset.baseLabel = base;
    const indicator = key === state.key ? (state.order === "asc" ? "↑" : "↓") : "↕";
    header.textContent = `${base}${indicator}`;
  }
}

function renderGpuDevices(rows) {
  gpuDeviceTableBody.innerHTML = "";
  if (!rows.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = '<td colspan="5" class="muted">暂无每卡数据（可能无 GPU 或 NVML 不可用）</td>';
    gpuDeviceTableBody.appendChild(tr);
    return;
  }
  for (const d of rows) {
    const utilPct = Math.max(0, Math.min(100, d.gpu_util || 0));
    const memPct = d.gpu_mem_total_mb ? Math.max(0, Math.min(100, (d.gpu_mem_used_mb / d.gpu_mem_total_mb) * 100)) : 0;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>GPU ${d.gpu_index}</td>
      <td>${d.gpu_name || "-"}</td>
      <td>
        <div>${fmt(utilPct, 1)}%</div>
        <div class="bar"><span style="width:${utilPct}%"></span></div>
      </td>
      <td>${fmt(d.gpu_mem_used_mb, 0)} / ${fmt(d.gpu_mem_total_mb, 0)} MB (${fmt(memPct, 1)}%)</td>
      <td>${d.process_count ?? "-"}</td>
    `;
    gpuDeviceTableBody.appendChild(tr);
  }
}

async function loadHistory() {
  const rangeWindow = rangeSelect.value;
  const resp = await fetch(`/api/metrics/history?range_window=${encodeURIComponent(rangeWindow)}`);
  const data = await resp.json();
  renderCpuMem(data.points || []);
  renderGpu(data.points || []);
}

async function loadSnapshot() {
  const [snapshotResp, statusResp] = await Promise.all([
    fetch("/api/metrics/snapshot?limit=30"),
    fetch("/api/metrics/status"),
  ]);
  const snapshot = await snapshotResp.json();
  const status = await statusResp.json();

  currentCpuProcesses = snapshot.processes || [];
  currentGpuProcesses = snapshot.gpu_processes || [];
  renderProcessTables();
  renderGpuDevices(snapshot.gpu_devices || []);

  const host = snapshot.host;
  const ts = host?.timestamp ? new Date(host.timestamp).toLocaleString() : "暂无样本";
  const gpuMsg = status.last_gpu_error ? ` | GPU: ${status.last_gpu_error}` : "";
  const collectMsg = status.last_collection_error ? ` | 采集异常: ${status.last_collection_error}` : "";
  statusLine.textContent = `最新样本: ${ts} | 已写入样本: ${status.samples_written}${configText}${gpuMsg}${collectMsg}`;
}

async function loadConfig() {
  const configResp = await fetch("/api/metrics/config");
  const config = await configResp.json();
  if (!config.loaded) {
    configText = "";
    return;
  }
  const retentionLabel = config.retention_days === null ? "off" : `${config.retention_days}d`;
  configText = ` | 配置: ${config.server_host}:${config.server_port} interval=${config.sample_interval_seconds}s topN=${config.process_top_n} retention=${retentionLabel}`;
}

async function refreshAll() {
  try {
    await Promise.all([loadConfig(), loadHistory(), loadSnapshot()]);
  } catch (err) {
    statusLine.textContent = `数据拉取失败: ${err.message}`;
  }
}

rangeSelect.addEventListener("change", refreshAll);
for (const header of sortableHeaders) {
  header.addEventListener("click", () => {
    const table = header.dataset.table;
    const key = header.dataset.sortKey;
    if (!key) return;
    if (table === "cpu") {
      cpuSortState = {
        key,
        order: cpuSortState.key === key && cpuSortState.order === "desc" ? "asc" : "desc",
      };
    } else {
      gpuSortState = {
        key,
        order: gpuSortState.key === key && gpuSortState.order === "desc" ? "asc" : "desc",
      };
    }
    renderProcessTables();
  });
}
document.addEventListener("mousemove", (event) => {
  const eventTarget = event.target instanceof Element ? event.target : event.target?.parentElement;
  if (!eventTarget) {
    hideCmdlineTooltip();
    return;
  }
  const cell = eventTarget.closest(".name-cell");
  if (!cell) {
    hideCmdlineTooltip();
    return;
  }
  const tooltipText = cell.getAttribute("data-tooltip") || "";
  if (!tooltipText) {
    hideCmdlineTooltip();
    return;
  }
  showCmdlineTooltip(tooltipText, event.clientX, event.clientY);
});
document.addEventListener("mouseleave", hideCmdlineTooltip);
document.addEventListener("dblclick", (event) => {
  const eventTarget = event.target instanceof Element ? event.target : event.target?.parentElement;
  if (!eventTarget) return;
  if (!eventTarget.closest(".interactive-table")) return;
  event.preventDefault();
  const selection = window.getSelection();
  selection?.removeAllRanges();
});
window.addEventListener("resize", () => {
  cpuMemChart.resize();
  gpuChart.resize();
});

refreshAll();
setInterval(loadSnapshot, 5000);
setInterval(loadHistory, 15000);

