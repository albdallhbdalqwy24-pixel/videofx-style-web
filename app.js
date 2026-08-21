const API_BASE = ""; // المعالجة محلية بالكامل داخل Termux
const input = document.querySelector("#fileInput");
const dropzone = document.querySelector("#dropzone");
const fileCard = document.querySelector("#fileCard");
const processBtn = document.querySelector("#processBtn");
const clearBtn = document.querySelector("#clearBtn");
const progressCard = document.querySelector("#progressCard");
const resultCard = document.querySelector("#resultCard");
const errorBox = document.querySelector("#errorBox");
let selectedFile = null;
let objectUrl = null;

const show = (el, value = true) => el.classList.toggle("hidden", !value);
const setError = (message) => { errorBox.textContent = message; show(errorBox, true); };
const clearError = () => show(errorBox, false);
const setProgress = (value, text) => {
  document.querySelector("#progressBar").style.width = `${value}%`;
  document.querySelector("#progressValue").textContent = `${Math.round(value)}%`;
  if (text) document.querySelector("#statusText").textContent = text;
};
const formatSize = (bytes) => `${(bytes / 1024 / 1024).toFixed(1)} MB`;

function chooseFile(file) {
  if (!file || !file.type.startsWith("video/")) return setError("اختر ملف فيديو بصيغة MP4 أو MOV أو WebM.");
  if (file.size > 450 * 1024 * 1024) return setError("الملف أكبر من الحد الآمن للخدمة حالياً. جرّب نسخة أصغر من 450MB.");
  selectedFile = file;
  document.querySelector("#fileName").textContent = file.name;
  document.querySelector("#fileSize").textContent = formatSize(file.size);
  document.querySelector("#dropTitle").textContent = "تم اختيار الفيديو";
  show(fileCard, true); processBtn.disabled = false; clearError(); show(resultCard, false);
}

input.addEventListener("change", () => chooseFile(input.files?.[0]));
["dragenter", "dragover"].forEach((event) => dropzone.addEventListener(event, (e) => { e.preventDefault(); dropzone.classList.add("dragging"); }));
["dragleave", "drop"].forEach((event) => dropzone.addEventListener(event, (e) => { e.preventDefault(); dropzone.classList.remove("dragging"); }));
dropzone.addEventListener("drop", (e) => chooseFile(e.dataTransfer.files?.[0]));
clearBtn.addEventListener("click", () => { selectedFile = null; input.value = ""; show(fileCard, false); processBtn.disabled = true; document.querySelector("#dropTitle").textContent = "اختر فيديو من جهازك"; });

async function request(url, options = {}, timeout = 90000) {
  const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), timeout);
  try { const response = await fetch(url, { ...options, signal: controller.signal }); if (!response.ok) throw new Error(`HTTP ${response.status}`); return response; }
  finally { clearTimeout(timer); }
}

async function processVideo() {
  if (!selectedFile) return;
  processBtn.disabled = true; clearError(); show(progressCard, true); show(resultCard, false); setProgress(5, "جاري تجهيز الملف لفلتر 96618...");
  try {
    const probeForm = new FormData(); probeForm.append("file", selectedFile, selectedFile.name);
    const probe = await request(`${API_BASE}/probe`, { method: "POST", body: probeForm });
    const meta = await probe.json();
    if (!meta.ok) throw new Error(meta.error || "تعذر تحليل الملف.");
    setProgress(18, `تم التحليل: ${meta.width || "؟"}×${meta.height || "؟"} — بدء تطبيق فلتر 96618...`);
    const startForm = new FormData(); startForm.append("file", selectedFile, selectedFile.name);
    const startResponse = await request(`${API_BASE}/start`, { method: "POST", body: startForm });
    const start = await startResponse.json();
    if (!start.job) throw new Error(start.error || "لم تبدأ المعالجة.");
    await poll(start.job);
  } catch (error) {
    setError(error.name === "AbortError" ? "انتهت مهلة الاتصال. جرّب ملفاً أصغر أو أعد المحاولة." : `تعذر تجهيز الفيديو: ${error.message}`);
    show(progressCard, false); processBtn.disabled = false;
  }
}

async function poll(jobId) {
  for (;;) {
    const response = await request(`${API_BASE}/progress?id=${encodeURIComponent(jobId)}`, {}, 30000);
    const job = await response.json(); const progress = Number(job.progress || 0);
    setProgress(Math.max(20, progress), job.message || "جاري تطبيق فلتر 96618 المتخصص...");
    if (job.state === "done") {
      setProgress(100, "اكتملت المعالجة");
      objectUrl = `${API_BASE}/download?id=${encodeURIComponent(jobId)}`;
      const link = document.querySelector("#downloadBtn"); link.href = objectUrl; link.download = job.output_name || "VideoFX_96618.mp4";
      document.querySelector("#resultMeta").textContent = `${job.output_name || "VideoFX_96618.mp4"} — جاهز للتنزيل.`;
      show(resultCard, true); processBtn.disabled = false; return;
    }
    if (job.state === "error") throw new Error(job.error || "فشلت المعالجة على الخادم.");
    await new Promise((resolve) => setTimeout(resolve, 1400));
  }
}
processBtn.addEventListener("click", processVideo);
