#!/usr/bin/env python3
"""Tony AI Font Factory — Web UI (Flask)."""
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from flask import Flask, render_template, jsonify, request, send_from_directory, Response
from config.settings import OUTPUT_DIR, PROJECT_ROOT

app = Flask(__name__, static_folder="static", template_folder="templates")

# Active pipeline jobs
jobs = {}
job_lock = threading.Lock()


def sizeof_fmt(num):
    for unit in ("B", "KB", "MB"):
        if abs(num) < 1024:
            return f"{num:.1f}{unit}"
        num /= 1024
    return f"{num:.1f}GB"


# ── Pages ──────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


# ── API: Dashboard Stats ──────────────────────────────────────────────
@app.route("/api/stats")
def dashboard_stats():
    """Overall dashboard statistics."""
    total = done = glyphs = total_size = 0
    running = len([j for j in jobs.values() if j["status"] == "running"])

    if OUTPUT_DIR.exists():
        for d in OUTPUT_DIR.iterdir():
            if not d.is_dir() or d.name.startswith("."):
                continue
            if not (d / "images").exists() and not (d / "svgs").exists():
                continue
            total += 1
            if (d / "fonts").exists() and list((d / "fonts").glob("*.*")):
                done += 1
            if (d / "images").exists():
                glyphs += len(list((d / "images").glob("*.png")))
            if (d / "fonts").exists():
                for f in (d / "fonts").iterdir():
                    total_size += f.stat().st_size

    return jsonify({
        "total": total,
        "done": done,
        "running": running,
        "glyphs": glyphs,
        "total_size": sizeof_fmt(total_size),
        "categories": len(list((PROJECT_ROOT / "prompts").iterdir())) if (PROJECT_ROOT / "prompts").exists() else 0,
    })


# ── API: Fonts ─────────────────────────────────────────────────────────
@app.route("/api/fonts")
def list_fonts():
    """List all fonts with their status."""
    fonts = []
    if OUTPUT_DIR.exists():
        for d in sorted(OUTPUT_DIR.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            if not (d / "images").exists() and not (d / "svgs").exists():
                continue

            imgs = len(list((d / "images").glob("*.png"))) if (d / "images").exists() else 0
            svgs = len(list((d / "svgs").glob("*.svg"))) if (d / "svgs").exists() else 0
            font_files = list((d / "fonts").glob("*.*")) if (d / "fonts").exists() else []
            mocks = len(list((d / "mockups").glob("*.png"))) if (d / "mockups").exists() else 0
            specimens = list((d / "specimens").glob("*.png")) if (d / "specimens").exists() else []
            nobg = len(list((d / "nobg").glob("*.png"))) if (d / "nobg").exists() else 0

            # Determine stages completed
            stages = {
                "generate": imgs > 0,
                "process": svgs > 0,
                "assemble": len(font_files) > 0,
                "qa": len(specimens) > 0,
                "mockup": mocks > 0,
            }
            completed = sum(1 for v in stages.values() if v)

            # Current stage label
            if mocks > 0:
                stage = "done"
            elif len(specimens) > 0:
                stage = "qa"
            elif len(font_files) > 0:
                stage = "assembled"
            elif svgs > 0:
                stage = "processed"
            elif imgs > 0:
                stage = "generated"
            else:
                stage = "empty"

            # Font file sizes
            font_info = []
            for f in font_files:
                font_info.append({
                    "name": f.name,
                    "ext": f.suffix,
                    "size": sizeof_fmt(f.stat().st_size),
                })

            # Preview images
            preview = None
            if mocks > 0:
                mp = d / "mockups"
                hero = mp / f"{d.name}_hero_dark.png"
                preview = f"/output/{d.name}/mockups/{hero.name}" if hero.exists() else f"/output/{d.name}/mockups/{sorted(mp.glob('*.png'))[0].name}"
            elif len(specimens) > 0:
                preview = f"/output/{d.name}/specimens/{specimens[0].name}"

            # Check running
            job = jobs.get(d.name)
            is_running = job and job["status"] == "running"

            # Created time
            created = d.stat().st_ctime

            fonts.append({
                "name": d.name,
                "images": imgs,
                "svgs": svgs,
                "fonts": len(font_files),
                "font_info": font_info,
                "mockups": mocks,
                "nobg": nobg,
                "stage": stage,
                "stages": stages,
                "completed": completed,
                "has_specimen": len(specimens) > 0,
                "preview": preview,
                "is_running": is_running,
                "running_stage": job["stage"] if is_running else None,
                "created": created,
            })
    # Sort: running first, then by created desc
    fonts.sort(key=lambda f: (not f["is_running"], -f["created"]))
    return jsonify(fonts)


@app.route("/api/fonts/<name>")
def get_font(name):
    """Get details for a specific font."""
    font_dir = OUTPUT_DIR / name
    if not font_dir.exists():
        return jsonify({"error": "Not found"}), 404

    data = {"name": name, "files": {}, "analysis": None, "ref_dir": None}

    # Load style analysis if exists
    analysis_file = font_dir / "style_analysis.json"
    if analysis_file.exists():
        try:
            data["analysis"] = json.loads(analysis_file.read_text())
        except Exception:
            pass

    # Check ref dir
    ref_dir = font_dir / "references"
    if ref_dir.exists():
        data["ref_dir"] = str(ref_dir)
        data["files"]["references"] = []
        for f in sorted(ref_dir.iterdir()):
            if f.name.startswith("."):
                continue
            data["files"]["references"] = data["files"].get("references", [])
            data["files"]["references"].append({
                "name": f.name,
                "size": sizeof_fmt(f.stat().st_size),
                "url": f"/output/{name}/references/{f.name}",
            })

    for sub in ["images", "nobg", "svgs", "fonts", "mockups", "specimens"]:
        sub_dir = font_dir / sub
        if sub_dir.exists():
            files = []
            for f in sorted(sub_dir.iterdir()):
                if f.name.startswith("."):
                    continue
                files.append({
                    "name": f.name,
                    "size": sizeof_fmt(f.stat().st_size),
                    "url": f"/output/{name}/{sub}/{f.name}",
                })
            data["files"][sub] = files
        else:
            data["files"][sub] = []

    # Check if has a .woff2 or .ttf for live preview
    font_sub = font_dir / "fonts"
    data["preview_font"] = None
    if font_sub.exists():
        for ext in [".woff2", ".ttf", ".otf"]:
            ff = list(font_sub.glob(f"*{ext}"))
            if ff:
                data["preview_font"] = f"/output/{name}/fonts/{ff[0].name}"
                break

    return jsonify(data)


@app.route("/api/fonts/<name>/delete", methods=["POST"])
def delete_font(name):
    """Delete a font and all its files."""
    import shutil
    font_dir = OUTPUT_DIR / name
    if not font_dir.exists():
        return jsonify({"error": "Not found"}), 404
    shutil.rmtree(font_dir)
    return jsonify({"ok": True})


@app.route("/api/fonts/<name>/rerun", methods=["POST"])
def rerun_stage(name):
    """Re-run a specific pipeline stage."""
    data = request.json or {}
    stage = data.get("stage")
    style = data.get("style", "")

    if not stage:
        return jsonify({"error": "stage required"}), 400

    with job_lock:
        if name in jobs and jobs[name]["status"] == "running":
            return jsonify({"error": f"{name} is already running"}), 409
        jobs[name] = {
            "status": "running",
            "stage": stage,
            "started": time.time(),
            "log": [],
            "error": None,
        }

    def run_stage():
        job = jobs[name]
        try:
            job["log"].append(f"Re-running stage: {stage}")
            if stage == "generate":
                from scripts.generate import generate_font_images
                generate_font_images(style, name)
            elif stage == "process":
                from scripts.process import process_font_images
                process_font_images(name)
            elif stage == "assemble":
                from scripts.assemble import assemble_font
                family = data.get("family") or name.replace("_", " ").replace("-", " ")
                assemble_font(name, family)
            elif stage == "qa":
                from scripts.qa import qa_font
                qa_font(name)
            elif stage == "mockup":
                from scripts.mockup import generate_mockups
                generate_mockups(name)
            job["status"] = "done"
            job["log"].append(f"{stage} complete!")
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)
            job["log"].append(f"ERROR: {e}")

    threading.Thread(target=run_stage, daemon=True).start()
    return jsonify({"ok": True})


# ── API: Upload references ─────────────────────────────────────────────
@app.route("/api/fonts/<name>/upload-refs", methods=["POST"])
def upload_references(name):
    """Upload reference images for style analysis."""
    ref_dir = OUTPUT_DIR / name / "references"
    ref_dir.mkdir(parents=True, exist_ok=True)

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files"}), 400

    saved = []
    for f in files:
        if f.filename and f.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            path = ref_dir / f.filename
            f.save(str(path))
            saved.append(f.filename)

    return jsonify({"ok": True, "saved": saved, "count": len(saved)})


@app.route("/api/fonts/<name>/analyze", methods=["POST"])
def analyze_font_style(name):
    """Analyze reference images and save style analysis."""
    data = request.json or {}
    ext_ref_dir = data.get("ref_dir", "")

    # Check for external ref dir or built-in
    ref_dir = OUTPUT_DIR / name / "references"

    # If external path provided, copy images to references folder
    if ext_ref_dir and Path(ext_ref_dir).expanduser().exists():
        import shutil
        ext_path = Path(ext_ref_dir).expanduser()
        ref_dir.mkdir(parents=True, exist_ok=True)
        for ext in ["*.png", "*.jpg", "*.jpeg", "*.webp"]:
            for f in ext_path.glob(ext):
                shutil.copy2(f, ref_dir / f.name)

    if not ref_dir.exists() or not list(ref_dir.glob("*.png")) + list(ref_dir.glob("*.jpg")) + list(ref_dir.glob("*.jpeg")) + list(ref_dir.glob("*.webp")):
        return jsonify({"error": "No reference images. Upload or provide folder path."}), 400

    with job_lock:
        if name in jobs and jobs[name]["status"] == "running":
            return jsonify({"error": f"{name} is already running"}), 409
        jobs[name] = {
            "status": "running",
            "stage": "analyze",
            "started": time.time(),
            "log": ["Analyzing reference images..."],
            "error": None,
        }

    def run_analyze():
        job = jobs[name]
        try:
            from scripts.analyze import analyze_references
            result = analyze_references(str(ref_dir), name)
            job["log"].append(f"Style: {result.get('style_name_en', 'analyzed')}")
            job["log"].append(f"Material: {result.get('material_keyword', '?')}")
            job["log"].append(f"Mood: {result.get('mood_keyword', '?')}")
            job["status"] = "done"
            job["log"].append("Analysis complete!")
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)
            job["log"].append(f"ERROR: {e}")

    threading.Thread(target=run_analyze, daemon=True).start()
    return jsonify({"ok": True})


# ── API: Pipeline ──────────────────────────────────────────────────────
@app.route("/api/run", methods=["POST"])
def run_pipeline():
    """Start full pipeline for a font."""
    data = request.json or {}
    style = data.get("style", "").strip()
    name = data.get("name", "").strip()
    ref_dir = data.get("ref_dir", "").strip()
    skip = data.get("skip", [])

    if not name:
        return jsonify({"error": "name required"}), 400

    # Check if ref_dir exists in output
    actual_ref_dir = None
    built_in_ref = OUTPUT_DIR / name / "references"
    if ref_dir and Path(ref_dir).exists():
        actual_ref_dir = ref_dir
    elif built_in_ref.exists() and list(built_in_ref.glob("*.*")):
        actual_ref_dir = str(built_in_ref)

    # Need either style or ref_dir
    if not style and not actual_ref_dir:
        return jsonify({"error": "style prompt hoac reference folder can thiet"}), 400

    with job_lock:
        if name in jobs and jobs[name]["status"] == "running":
            return jsonify({"error": f"{name} is already running"}), 409
        jobs[name] = {
            "status": "running",
            "stage": "starting",
            "started": time.time(),
            "log": [],
            "error": None,
        }

    def run_in_bg():
        job = jobs[name]
        analysis = None
        try:
            # Stage 0: Analyze references (if ref mode)
            if actual_ref_dir and "analyze" not in skip:
                job["stage"] = "analyze"
                job["log"].append("Stage 0: Analyzing reference images...")
                from scripts.analyze import analyze_references
                analysis = analyze_references(actual_ref_dir, name)
                job["log"].append(f"Style: {analysis.get('style_name_en', '?')} | Material: {analysis.get('material_keyword', '?')}")

            # Also load existing analysis if skipped
            if not analysis:
                analysis_file = OUTPUT_DIR / name / "style_analysis.json"
                if analysis_file.exists():
                    analysis = json.loads(analysis_file.read_text())
                    job["log"].append(f"Loaded saved analysis: {analysis.get('style_name_en', '?')}")

            if "generate" not in skip:
                job["stage"] = "generate"
                job["log"].append("Stage 1/5: Generating letters...")
                from scripts.generate import generate_font_images
                generate_font_images(
                    style=style,
                    font_name=name,
                    ref_dir=actual_ref_dir,
                    analysis=analysis,
                )
                job["log"].append("Generate complete")

            if "process" not in skip:
                job["stage"] = "process"
                job["log"].append("Stage 2/5: Processing images...")
                from scripts.process import process_font_images
                process_font_images(name)
                job["log"].append("Process complete")

            if "assemble" not in skip:
                job["stage"] = "assemble"
                job["log"].append("Stage 3/5: Assembling font...")
                from scripts.assemble import assemble_font
                family = data.get("family") or name.replace("_", " ").replace("-", " ")
                assemble_font(name, family)
                job["log"].append("Assemble complete")

            if "qa" not in skip:
                job["stage"] = "qa"
                job["log"].append("Stage 4/5: Running QA...")
                from scripts.qa import qa_font
                qa_font(name)
                job["log"].append("QA complete")

            if "mockup" not in skip:
                job["stage"] = "mockup"
                job["log"].append("Stage 5/5: Generating mockups...")
                from scripts.mockup import generate_mockups
                generate_mockups(name)
                job["log"].append("Mockups complete")

            job["status"] = "done"
            job["stage"] = "done"
            job["log"].append("Pipeline complete!")

        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)
            job["log"].append(f"ERROR: {e}")

    threading.Thread(target=run_in_bg, daemon=True).start()
    return jsonify({"ok": True, "name": name})


@app.route("/api/run/<name>/status")
def job_status(name):
    """Get pipeline job status."""
    with job_lock:
        job = jobs.get(name)
    if not job:
        return jsonify({"status": "idle"})
    elapsed = time.time() - job["started"] if job["started"] else 0
    return jsonify({
        "status": job["status"],
        "stage": job["stage"],
        "elapsed": round(elapsed, 1),
        "log": job["log"][-50:],
        "error": job["error"],
    })


# ── API: Prompts ───────────────────────────────────────────────────────
@app.route("/api/prompts")
def list_prompts():
    """List available style prompts."""
    prompts_dir = PROJECT_ROOT / "prompts"
    result = {}
    for cat_dir in sorted(prompts_dir.iterdir()):
        if cat_dir.is_dir():
            default = cat_dir / "default.txt"
            result[cat_dir.name] = default.read_text().strip() if default.exists() else ""
    return jsonify(result)


# ── Serve output files ─────────────────────────────────────────────────
@app.route("/output/<path:filepath>")
def serve_output(filepath):
    """Serve files from output directory."""
    return send_from_directory(OUTPUT_DIR, filepath)


# ── Error handlers ─────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found"}), 404
    return render_template("index.html"), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app.run(host="0.0.0.0", port=8090, debug=True)
