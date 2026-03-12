#!/usr/bin/env python3
"""Tony AI Font Factory — Web UI (Flask)."""
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from flask import Flask, render_template, jsonify, request, send_from_directory
from config.settings import OUTPUT_DIR, PROJECT_ROOT

app = Flask(__name__, static_folder="static", template_folder="templates")

# Active pipeline jobs
jobs = {}
job_lock = threading.Lock()


# ── Pages ──────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


# ── API: Fonts ─────────────────────────────────────────────────────────
@app.route("/api/fonts")
def list_fonts():
    """List all fonts with their status."""
    fonts = []
    if OUTPUT_DIR.exists():
        for d in sorted(OUTPUT_DIR.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            # Skip if not a font project dir (must have images/ or svgs/ subfolder)
            if not (d / "images").exists() and not (d / "svgs").exists():
                continue
            imgs = len(list((d / "images").glob("*.png"))) if (d / "images").exists() else 0
            svgs = len(list((d / "svgs").glob("*.svg"))) if (d / "svgs").exists() else 0
            font_files = list((d / "fonts").glob("*.*")) if (d / "fonts").exists() else []
            mocks = len(list((d / "mockups").glob("*.png"))) if (d / "mockups").exists() else 0
            specimens = list((d / "specimens").glob("*.png")) if (d / "specimens").exists() else []

            # Determine stage
            if font_files:
                stage = "done"
            elif svgs > 0:
                stage = "assembled"
            elif imgs > 0:
                stage = "generated"
            else:
                stage = "empty"

            fonts.append({
                "name": d.name,
                "images": imgs,
                "svgs": svgs,
                "fonts": len(font_files),
                "mockups": mocks,
                "stage": stage,
                "has_specimen": len(specimens) > 0,
                "font_formats": [f.suffix for f in font_files],
            })
    return jsonify(fonts)


@app.route("/api/fonts/<name>")
def get_font(name):
    """Get details for a specific font."""
    font_dir = OUTPUT_DIR / name
    if not font_dir.exists():
        return jsonify({"error": "Not found"}), 404

    data = {"name": name, "files": {}}
    for sub in ["images", "nobg", "svgs", "fonts", "mockups", "specimens"]:
        sub_dir = font_dir / sub
        if sub_dir.exists():
            data["files"][sub] = [f.name for f in sorted(sub_dir.iterdir()) if not f.name.startswith(".")]
        else:
            data["files"][sub] = []

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


# ── API: Pipeline ──────────────────────────────────────────────────────
@app.route("/api/run", methods=["POST"])
def run_pipeline():
    """Start full pipeline for a font."""
    data = request.json or {}
    style = data.get("style", "").strip()
    name = data.get("name", "").strip()
    skip = data.get("skip", [])

    if not style or not name:
        return jsonify({"error": "style and name required"}), 400

    # Check if already running
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
        try:
            # Stage 1: Generate
            if "generate" not in skip:
                job["stage"] = "generate"
                job["log"].append("Stage 1/5: Generating letters...")
                from scripts.generate import generate_font_images
                generate_font_images(style, name)
                job["log"].append("Generate complete")

            # Stage 2: Process
            if "process" not in skip:
                job["stage"] = "process"
                job["log"].append("Stage 2/5: Processing images...")
                from scripts.process import process_font_images
                process_font_images(name)
                job["log"].append("Process complete")

            # Stage 3: Assemble
            if "assemble" not in skip:
                job["stage"] = "assemble"
                job["log"].append("Stage 3/5: Assembling font...")
                from scripts.assemble import assemble_font
                family = data.get("family") or name.replace("_", " ").replace("-", " ")
                assemble_font(name, family)
                job["log"].append("Assemble complete")

            # Stage 4: QA
            if "qa" not in skip:
                job["stage"] = "qa"
                job["log"].append("Stage 4/5: Running QA...")
                from scripts.qa import qa_font
                qa_font(name)
                job["log"].append("QA complete")

            # Stage 5: Mockup
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

    t = threading.Thread(target=run_in_bg, daemon=True)
    t.start()
    return jsonify({"ok": True, "name": name})


@app.route("/api/run/<name>/status")
def job_status(name):
    """Get pipeline job status."""
    with job_lock:
        job = jobs.get(name)
    if not job:
        return jsonify({"status": "unknown"})
    elapsed = time.time() - job["started"] if job["started"] else 0
    return jsonify({
        "status": job["status"],
        "stage": job["stage"],
        "elapsed": round(elapsed, 1),
        "log": job["log"][-20:],
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


# ── Serve font files / images ──────────────────────────────────────────
@app.route("/output/<path:filepath>")
def serve_output(filepath):
    """Serve files from output directory."""
    return send_from_directory(OUTPUT_DIR, filepath)


# ── Error handlers ─────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app.run(host="0.0.0.0", port=8090, debug=True)
