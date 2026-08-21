#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
JOBS = {}
LOCK = threading.Lock()


def run_json(command):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "تعذر قراءة الفيديو")
    return json.loads(result.stdout)


def rate(value):
    try:
        a, b = value.split("/")
        return round(float(a) / float(b), 3) if float(b) else 0
    except Exception:
        return 0


def probe(path):
    data = run_json([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,duration:format=duration,size,bit_rate",
        "-of", "json", str(path)
    ])
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video:
        raise RuntimeError("الملف لا يحتوي على فيديو صالح")
    fmt = data.get("format", {})
    duration = float(video.get("duration") or fmt.get("duration") or 0)
    size = int(fmt.get("size") or path.stat().st_size)
    fps = rate(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1")
    return {
        "width": int(video.get("width") or 0), "height": int(video.get("height") or 0),
        "fps": fps, "codec": video.get("codec_name", "?"), "duration": round(duration, 3),
        "size_bytes": size, "bitrate_mbps": round(int(fmt.get("bit_rate") or 0) / 1_000_000, 2),
    }


def update(job_id, **values):
    with LOCK:
        JOBS[job_id].update(values)


def process(job_id, source, output):
    try:
        meta = probe(source)
        update(job_id, state="processing", progress=5, message="تطبيق الفلاتر والحدة والنعومة محلياً...")
        # Visual-only chain: dimensions, orientation and frame timing are not changed.
        vf = "hqdn3d=1.0:1.0:2.0:2.0,eq=contrast=1.16:saturation=1.18:brightness=0.01,unsharp=5:5:0.55:5:5:0,format=yuv420p"
        source_rate = meta.get("bitrate_mbps") or 6
        maxrate = max(3.0, min(16.0, source_rate * 1.18))
        command = [
            "ffmpeg", "-hide_banner", "-y", "-i", str(source), "-map", "0:v:0", "-map", "0:a?",
            "-vf", vf, "-c:v", "libx264", "-preset", "superfast", "-crf", "17",
            "-maxrate", f"{maxrate:.1f}M", "-bufsize", f"{maxrate * 2:.1f}M",
            "-profile:v", "high", "-pix_fmt", "yuv420p", "-c:a", "copy",
            "-movflags", "+faststart", "-fps_mode", "passthrough", "-progress", "pipe:1", "-nostats", str(output)
        ]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        for line in process.stdout:
            if line.startswith("out_time_ms="):
                try:
                    seconds = int(line.split("=", 1)[1]) / 1_000_000
                    progress = min(94, 5 + int(seconds / max(meta["duration"], 0.1) * 89))
                    update(job_id, progress=progress, message="جاري تطبيق VideoFX Style محلياً...")
                except ValueError:
                    pass
        if process.wait() != 0 or not output.exists():
            raise RuntimeError("فشل FFmpeg في معالجة الفيديو")
        final = probe(output)
        update(job_id, state="done", progress=100, message="اكتملت المعالجة محلياً مع الحفاظ على FPS والأبعاد والاتجاه.", output=str(output), output_name=output.name, info=final)
    except Exception as exc:
        update(job_id, state="error", progress=0, message=str(exc))
    finally:
        source.unlink(missing_ok=True)


def read_upload(handler):
    content_type = handler.headers.get("Content-Type", "")
    if "boundary=" not in content_type:
        raise RuntimeError("صيغة رفع غير صالحة")
    boundary = content_type.split("boundary=", 1)[1].strip().strip('"').encode()
    length = int(handler.headers.get("Content-Length", "0"))
    body = handler.rfile.read(length)
    marker = b"--" + boundary
    for part in body.split(marker):
        if b"filename=" not in part or b"\r\n\r\n" not in part:
            continue
        headers, payload = part.split(b"\r\n\r\n", 1)
        filename_line = next((line for line in headers.split(b"\r\n") if b"filename=" in line), b"")
        filename = filename_line.split(b"filename=", 1)[1].strip().strip(b'"').decode("utf-8", "ignore") or "video.mp4"
        return filename, payload.rstrip(b"\r\n-")
    raise RuntimeError("لم يتم اختيار فيديو")


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload, code=200):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path in ("/", "/index.html"):
            data = (ROOT / "index.html").read_bytes()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
        if url.path in ("/app.js", "/styles.css"):
            path = ROOT / url.path.lstrip("/")
            data = path.read_bytes(); self.send_response(200); self.send_header("Content-Type", "text/javascript" if path.suffix == ".js" else "text/css"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
        if url.path == "/progress":
            self.send_json(JOBS.get(query.get("id", [""])[0], {"state": "error", "message": "المهمة غير موجودة"})); return
        if url.path == "/download":
            job = JOBS.get(query.get("id", [""])[0]); output = Path(job.get("output", "")) if job and job.get("state") == "done" else None
            if not output or not output.exists(): self.send_json({"error": "الناتج غير جاهز"}, 404); return
            self.send_response(200); self.send_header("Content-Type", "video/mp4"); self.send_header("Content-Length", str(output.stat().st_size)); self.send_header("Content-Disposition", f'attachment; filename="{output.name}"'); self.end_headers()
            with output.open("rb") as stream:
                shutil.copyfileobj(stream, self.wfile)
            return
        self.send_error(404)

    def do_POST(self):
        if self.path not in ("/probe", "/start"):
            self.send_error(404); return
        filename, upload = read_upload(self)
        source = Path(tempfile.mkstemp(prefix="videofx_", suffix=Path(filename).suffix or ".mp4")[1])
        source.write_bytes(upload)
        try:
            if self.path == "/probe":
                self.send_json({"ok": True, **probe(source)}); return
            job_id = uuid.uuid4().hex
            output = ROOT / f"{Path(filename).stem}_VideoFX_Style.mp4"
            with LOCK: JOBS[job_id] = {"state": "queued", "progress": 0, "message": "في الانتظار..."}
            threading.Thread(target=process, args=(job_id, source, output), daemon=True).start()
            self.send_json({"ok": True, "job": job_id})
        except Exception as exc:
            source.unlink(missing_ok=True); self.send_json({"error": str(exc)}, 400)

    def log_message(self, *_):
        return


if __name__ == "__main__":
    print("VideoFX Style محلياً على http://127.0.0.1:5000")
    ThreadingHTTPServer(("0.0.0.0", 5000), Handler).serve_forever()
