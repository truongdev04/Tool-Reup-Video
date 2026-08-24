const $ = (sel) => document.querySelector(sel);

const STAGE_LABELS = {
  ingest: "ingest", analyze: "analyze", separate: "separate", stt: "stt",
  diarize: "diarize", segment_plan: "segment_plan", translate: "translate",
  duration_fit: "duration_fit", tts: "tts", forced_align: "forced_align",
  timeline_assembly: "timeline_assembly", subtitle: "subtitle",
  onscreen_text: "onscreen_text", lipsync: "lipsync", compose: "compose",
  render: "render", qc: "qc", publish: "publish",
};

function pill(status) {
  return `<span class="pill ${status}">${status}</span>`;
}

async function loadStatus() {
  const res = await fetch("/api/status");
  const data = await res.json();

  const ffmpegLine = data.ffmpeg_ok
    ? `<div class="provider-line"><span><span class="dot ok"></span>ffmpeg</span><span>đủ khả năng</span></div>`
    : `<div class="error-box">ffmpeg thiếu: ${data.ffmpeg_missing.join(", ")}</div>`;

  const providerLines = (list) =>
    list.map(p =>
      `<div class="provider-line"><span><span class="dot ${p.configured ? "ok" : "no"}"></span>${p.id}</span>
       <span>${p.configured ? "sẵn sàng" : "thiếu key"}</span></div>`
    ).join("");

  $("#status-body").innerHTML = `
    ${ffmpegLine}
    <div class="status-grid" style="margin-top:12px">
      <div><h4>Provider dịch</h4>${providerLines(data.translation_providers)}</div>
      <div><h4>Provider TTS</h4>${providerLines(data.tts_providers)}</div>
    </div>
  `;

  $("#locale-checks").innerHTML = data.locales.map(loc => `
    <label><input type="checkbox" name="locale" value="${loc}" ${loc === "es-ES" || loc === "ja-JP" ? "checked" : ""}> ${loc}</label>
  `).join("");

  const fillSelect = (sel, list, preferred) => {
    sel.innerHTML = list.map(p =>
      `<option value="${p.id}" ${!p.configured ? "data-unconfigured=\"1\"" : ""}>${p.id}${p.configured ? "" : " (thiếu key)"}</option>`
    ).join("");
    const match = list.find(p => p.id === preferred && p.configured);
    if (match) sel.value = match.id;
  };
  fillSelect($("#translation-provider"), data.translation_providers, "mock");
  fillSelect($("#tts-provider"), data.tts_providers, "macos_say");
}

function toggleUploadInput() {
  const isUpload = document.querySelector('input[name="source"]:checked').value === "upload";
  $("#video-file").disabled = !isUpload;
}
document.addEventListener("change", (e) => {
  if (e.target.name === "source") toggleUploadInput();
});

async function runPipeline(e) {
  e.preventDefault();
  const locales = [...document.querySelectorAll('input[name="locale"]:checked')].map(el => el.value);
  if (locales.length === 0) {
    alert("chọn ít nhất một ngôn ngữ đích");
    return;
  }

  const useFixture = document.querySelector('input[name="source"]:checked').value === "fixture";
  const form = new FormData();
  form.set("locales", locales.join(","));
  form.set("translation_provider", $("#translation-provider").value);
  form.set("tts_provider", $("#tts-provider").value);
  form.set("source_locale", $("#source-locale").value || "en-US");
  form.set("use_fixture", useFixture ? "true" : "false");
  if (!useFixture) {
    const file = $("#video-file").files[0];
    if (!file) { alert("chọn một file video"); return; }
    form.set("video", file);
  }

  $("#run-btn").disabled = true;
  $("#run-spinner").classList.remove("hidden");
  $("#run-result").innerHTML = "";

  try {
    const res = await fetch("/api/run", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) {
      $("#run-result").innerHTML = `<div class="error-box">${data.detail || "lỗi không rõ"}</div>`;
      return;
    }
    renderRunResult(data);
    await loadJobs();
  } catch (err) {
    $("#run-result").innerHTML = `<div class="error-box">${err}</div>`;
  } finally {
    $("#run-btn").disabled = false;
    $("#run-spinner").classList.add("hidden");
  }
}

function renderRunResult(data) {
  const blocks = data.reports.map(r => `
    <div class="stage-block">
      <h3>${r.locale} — ${r.ok ? "✓ xong" : "✗ có lỗi"} · ${r.total_ms}ms · ${r.cached_count} stage cache
        <button class="ghost" style="margin-left:8px;padding:3px 10px;font-size:12px" onclick="showJob('${r.job_id}')">Xem chi tiết</button>
      </h3>
      <table>
        <thead><tr><th>Stage</th><th>Trạng thái</th><th>Thời gian</th><th>Ghi chú</th></tr></thead>
        <tbody>
          ${r.outcomes.map(o => `
            <tr>
              <td class="mono">${STAGE_LABELS[o.stage] || o.stage}</td>
              <td>${pill(o.status)}</td>
              <td class="mono">${o.cached ? "cache" : o.duration_ms + "ms"}</td>
              <td>${o.note || ""}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `).join("");
  $("#run-result").innerHTML = blocks;
}

async function loadJobs() {
  const res = await fetch("/api/jobs");
  const jobs = await res.json();
  if (jobs.length === 0) {
    $("#jobs-list").innerHTML = "chưa có job nào";
    return;
  }
  $("#jobs-list").innerHTML = `
    <table>
      <thead><tr><th>Locale</th><th>Nguồn</th><th>Trạng thái</th><th>Stage hiện tại</th><th>Tạo lúc</th></tr></thead>
      <tbody>
        ${jobs.map(j => `
          <tr class="job-row" onclick="showJob('${j.id}')">
            <td class="mono">${j.locale}</td>
            <td>${j.source_filename || ""}</td>
            <td>${pill(j.status)}</td>
            <td class="mono">${j.current_stage || ""}</td>
            <td class="mono">${new Date(j.created_at).toLocaleTimeString("vi-VN")}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

async function showJob(jobId) {
  const res = await fetch(`/api/jobs/${jobId}`);
  const job = await res.json();

  $("#detail-card").classList.remove("hidden");
  $("#detail-locale").textContent = `— ${job.locale} (${job.status})`;

  let html = "";

  if (job.final_video_url) {
    html += `
      <div class="stage-block">
        <h3>Video cuối cùng ${job.qc_verdict ? pill(job.qc_verdict) : ""}</h3>
        <video controls src="${job.final_video_url}" style="width:100%;max-width:360px;border-radius:8px"></video>
        ${job.qc_findings.length ? `
          <table style="margin-top:10px">
            <thead><tr><th>Check</th><th>Verdict</th><th>Ghi chú</th></tr></thead>
            <tbody>
              ${job.qc_findings.map(f => `
                <tr>
                  <td class="mono">${f.check}</td>
                  <td>${pill(f.verdict)}</td>
                  <td>${f.message}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        ` : ""}
      </div>
    `;
  }

  if (job.units.length === 0) {
    html += "<p>Chưa có translation_units — pipeline chưa chạy tới segment_plan.</p>";
  } else {
    html += `
      <table>
        <thead>
          <tr>
            <th>#</th><th>Khung gốc</th><th>Gốc / Dịch</th><th>Budget</th>
            <th>TTS đọc</th><th>Chiến lược</th><th>Drift dồn</th><th>Nghe thử</th>
          </tr>
        </thead>
        <tbody>
          ${job.units.map(u => `
            <tr>
              <td class="mono">${u.idx}${u.needs_transcreation ? ' <span title="hook/CTA — dịch thoáng">★</span>' : ""}</td>
              <td class="mono">${u.duration_ms}ms</td>
              <td>
                <div class="unit-source">${u.source_text}</div>
                <div class="unit-translated">${u.translated_text || "(chưa dịch)"}</div>
              </td>
              <td class="mono">${u.char_budget ?? "–"}</td>
              <td class="mono">${u.timing ? u.timing.actual_duration_ms + "ms" : "–"}</td>
              <td class="mono">${u.timing ? u.timing.fit_strategy : "–"}${u.timing && u.timing.needs_manual_review ? ' <span class="warn-inline">⚠</span>' : ""}</td>
              <td class="mono">${u.timing ? u.timing.cumulative_drift_ms + "ms" : "–"}</td>
              <td>${u.audio_url ? `<audio controls src="${u.audio_url}"></audio>` : "–"}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;
  }

  $("#detail-body").innerHTML = html;
  $("#detail-card").scrollIntoView({ behavior: "smooth", block: "start" });
}
window.showJob = showJob;

$("#run-form").addEventListener("submit", runPipeline);
$("#refresh-jobs").addEventListener("click", loadJobs);

loadStatus();
loadJobs();
