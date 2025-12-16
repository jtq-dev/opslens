const $ = (id) => document.getElementById(id);

let runs = [];
let selectedRunId = null;
let trendChart = null;

function fmt(ts) {
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(txt || `HTTP ${res.status}`);
  }
  return res.json();
}

function setTheme() {
  const html = document.documentElement;
  const isDark = html.classList.contains("dark");
  const next = isDark ? "light" : "dark";
  html.classList.toggle("dark", next === "dark");
  localStorage.setItem("theme", next);
}

$("themeBtn").addEventListener("click", setTheme);

async function refreshRuns() {
  runs = await api("/api/runs?limit=100");
  renderRuns();
  fillCompare();
}

function renderRuns() {
  const wrap = $("runsList");
  wrap.innerHTML = "";
  if (!runs.length) {
    wrap.innerHTML = `<div class="text-sm text-zinc-500">No runs yet. Upload a .tar.gz to begin.</div>`;
    return;
  }
  for (const r of runs) {
    const btn = document.createElement("button");
    btn.className =
      "w-full rounded-2xl border border-zinc-200 bg-white/50 px-3 py-3 text-left text-sm hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950/30 dark:hover:bg-zinc-900";
    btn.innerHTML = `
      <div class="flex items-start justify-between gap-2">
        <div>
          <div class="font-semibold">${r.host}</div>
          <div class="text-xs text-zinc-500 dark:text-zinc-400">${fmt(r.created_at)}</div>
        </div>
        <div class="text-xs text-zinc-500">${r.archive_name}</div>
      </div>
    `;
    btn.onclick = () => loadRun(r.id);
    wrap.appendChild(btn);
  }
}

function fillCompare() {
  const a = $("compareA");
  const b = $("compareB");
  a.innerHTML = "";
  b.innerHTML = "";
  for (const r of runs) {
    const optA = document.createElement("option");
    optA.value = r.id;
    optA.textContent = `${r.host} — ${fmt(r.created_at)}`;
    a.appendChild(optA);

    const optB = document.createElement("option");
    optB.value = r.id;
    optB.textContent = `${r.host} — ${fmt(r.created_at)}`;
    b.appendChild(optB);
  }
  // default: newest vs previous
  if (runs.length >= 2) {
    a.value = runs[1].id;
    b.value = runs[0].id;
  }
}

async function loadRun(runId) {
  selectedRunId = runId;
  const data = await api(`/api/runs/${runId}`);
  const run = data.run;
  const metrics = data.metrics;

  $("runMeta").textContent = `${run.host} • ${fmt(run.created_at)} • ${run.archive_name}`;

  const grid = $("metricsGrid");
  grid.innerHTML = "";
  for (const m of metrics) {
    const card = document.createElement("div");
    card.className =
      "rounded-2xl border border-zinc-200 bg-white/60 p-3 text-sm dark:border-zinc-800 dark:bg-zinc-950/40";
    const v = (m.unit === "pct") ? `${m.value}%` : `${m.value}`;
    card.innerHTML = `
      <div class="text-xs font-semibold text-zinc-500 dark:text-zinc-400">${m.key}</div>
      <div class="mt-1 text-lg font-semibold">${v}</div>
    `;
    grid.appendChild(card);
  }

  const log = await api(`/api/runs/${runId}/artifact?name=log_tail.txt`);
  $("artifactLog").textContent = log.content || "(empty)";

  const failed = await api(`/api/runs/${runId}/artifact?name=systemd_failed_units.txt`);
  $("artifactFailed").textContent = failed.content || "(empty)";
}

function renderChart(labels, v, rolling7) {
  const ctx = $("trendChart");
  if (trendChart) trendChart.destroy();
  trendChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "daily avg", data: v, tension: 0.3 },
        { label: "rolling 7", data: rolling7, tension: 0.3 },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: true } },
      scales: { y: { beginAtZero: false } },
    },
  });
}

$("loadTrendBtn").addEventListener("click", async () => {
  if (!selectedRunId) return alert("Select a run first.");
  const run = runs.find((x) => x.id === selectedRunId);
  if (!run) return;

  const key = $("metricKey").value;
  const series = await api(`/api/analytics/rolling?host=${encodeURIComponent(run.host)}&key=${encodeURIComponent(key)}&days=90`);
  const labels = series.map((x) => x.d);
  const v = series.map((x) => x.v);
  const rolling7 = series.map((x) => x.rolling7);
  renderChart(labels, v, rolling7);
});

$("compareBtn").addEventListener("click", async () => {
  const a = $("compareA").value;
  const b = $("compareB").value;
  if (!a || !b) return;
  const diff = await api(`/api/compare?run_a=${encodeURIComponent(a)}&run_b=${encodeURIComponent(b)}`);

  const top = diff
    .filter((d) => d.delta !== null)
    .sort((x, y) => Math.abs(y.delta) - Math.abs(x.delta))
    .slice(0, 12);

  $("compareOut").innerHTML = top.map(d => {
    const sign = d.delta > 0 ? "+" : "";
    return `<div class="flex items-center justify-between border-b border-zinc-200 py-1 dark:border-zinc-800">
      <span class="font-semibold">${d.key}</span>
      <span class="text-zinc-600 dark:text-zinc-300">${d.a} → ${d.b} <span class="font-semibold">(${sign}${d.delta})</span></span>
    </div>`;
  }).join("");
});

$("refreshBtn").addEventListener("click", refreshRuns);

$("uploadBtn").addEventListener("click", async () => {
  const inp = $("fileInput");
  const msg = $("uploadMsg");
  msg.textContent = "";
  if (!inp.files || !inp.files[0]) return alert("Choose a .tar.gz file first.");

  const fd = new FormData();
  fd.append("file", inp.files[0]);

  try {
    msg.textContent = "Uploading…";
    const out = await api("/api/upload", { method: "POST", body: fd });
    msg.textContent = `✅ Uploaded. Host: ${out.host} • Health score: ${out.health_score}`;
    await refreshRuns();
    await loadRun(out.run_id);
  } catch (e) {
    msg.textContent = `❌ Upload failed: ${e.message}`;
  }
});

// boot
refreshRuns().catch(console.error);
