"""Stage 1: Generate letter images using Gemini Flash image generation.

Uses gemini-3.1-flash-image-preview via REST API (same as tony-ai-art).
Supports reference image mode and direct prompt mode.
"""
import base64
import json
import os
import time
from pathlib import Path

import requests
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from config.settings import (
    GEMINI_API_KEY, GEMINI_IMAGE_MODEL, GEMINI_API_URL,
    CHARSET, UPPERCASE, DIGITS, OUTPUT_DIR
)
from scripts.analyze import (
    analyze_references, build_letter_prompt, encode_image,
    LETTER_INTERACTIONS, FONT_KNOWLEDGE
)

console = Console()

DEFAULT_CHARSET = UPPERCASE + DIGITS


def get_simple_prompt(letter: str, style: str) -> str:
    """Build simple prompt (legacy mode, no reference)."""
    interaction = LETTER_INTERACTIONS.get(letter, f"artistic decoration following the letter geometry")
    return (
        f"Generate an image of a single letter '{letter}' in {style} style. "
        f"The artistic elements: {interaction}. "
        f"Isolated on pure white background, centered, square composition, "
        f"high detail, the letter must be clearly readable. "
        f"ONLY the letter '{letter}', no other text or characters."
        f"\n\n{FONT_KNOWLEDGE}"
    )


def gemini_generate_image(prompt: str, api_key: str, ref_image: tuple | None = None) -> bytes | None:
    """Call Gemini REST API to generate image. Same pattern as tony-ai-art.

    Args:
        prompt: Text prompt
        api_key: Gemini API key
        ref_image: Optional (base64_data, mime_type) for reference-based generation

    Returns:
        Image bytes or None
    """
    model = GEMINI_IMAGE_MODEL
    url = f"{GEMINI_API_URL}/{model}:generateContent?key={api_key}"

    # Build parts — reference image first (if any), then text
    parts = []
    if ref_image:
        b64_data, mime_type = ref_image
        parts.append({"inlineData": {"mimeType": mime_type, "data": b64_data}})
    parts.append({"text": prompt})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE", "TEXT"],
        },
    }

    resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=120)

    if not resp.ok:
        err = resp.text[:300]
        raise Exception(f"Gemini API error {resp.status_code}: {err}")

    data = resp.json()

    # Check blocked
    if data.get("promptFeedback", {}).get("blockReason"):
        raise Exception(f"Gemini blocked: {data['promptFeedback']['blockReason']}")

    # Extract image from response
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if part.get("inlineData", {}).get("data"):
                img_b64 = part["inlineData"]["data"]
                return base64.b64decode(img_b64)

    return None


def generate_font_images(
    style: str,
    font_name: str,
    charset: str | None = None,
    output_dir: Path | None = None,
    ref_dir: str | Path | None = None,
    analysis: dict | None = None,
    retries: int = 2,
) -> Path:
    """Generate all letter images for a font.

    Args:
        style: Style description (used if no ref_dir/analysis)
        font_name: Font name (folder name)
        charset: Characters to generate (default: A-Z + 0-9)
        output_dir: Override output directory
        ref_dir: Path to reference images folder (triggers analysis mode)
        analysis: Pre-computed analysis result (skip re-analysis)
        retries: Retries per failed letter

    Returns:
        Path to generated images directory
    """
    if not GEMINI_API_KEY:
        console.print("[red]ERROR: GEMINI_API_KEY not set in .env[/red]")
        raise SystemExit(1)

    charset = charset or DEFAULT_CHARSET
    base_dir = (output_dir or OUTPUT_DIR) / font_name
    img_dir = base_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    # ── Mode A: Reference-based (analyze → template → generate)
    master_prompt = None
    ref_image = None  # Single ref image (b64, mime) for Gemini

    if ref_dir or analysis:
        if not analysis:
            console.print(f"\n[bold cyan]Analyzing reference images: {ref_dir}[/bold cyan]")
            analysis = analyze_references(ref_dir, font_name)

        master_prompt = analysis.get("master_prompt_with_font_knowledge") or analysis.get("master_prompt", "")
        console.print(f"[green]Using style: {analysis.get('style_name_en', 'analyzed')}[/green]")
        console.print(f"[dim]Material: {analysis.get('material_keyword')} | Mood: {analysis.get('mood_keyword')}[/dim]")

        # Load first reference image for visual guidance (same as tony-ai-art: 1 ref best)
        if ref_dir:
            ref_path = Path(ref_dir)
            for ext in ["*.png", "*.jpg", "*.jpeg", "*.webp"]:
                for f in sorted(ref_path.glob(ext))[:1]:
                    b64, mime = encode_image(f)
                    ref_image = (b64, mime)
                    console.print(f"[dim]Reference image: {f.name}[/dim]")
                    break
                if ref_image:
                    break

    failed = []

    console.print(f"[dim]Model: {GEMINI_IMAGE_MODEL} (REST API)[/dim]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"Generating {font_name}", total=len(charset))

        for char in charset:
            # Safe filename
            if char.isalnum():
                fname = f"{char}.png"
            else:
                fname = f"char_{ord(char):04x}.png"

            filepath = img_dir / fname
            if filepath.exists():
                progress.advance(task)
                continue

            # Build prompt
            if master_prompt:
                prompt = build_letter_prompt(master_prompt, char)
            else:
                prompt = get_simple_prompt(char, style)

            success = False

            for attempt in range(retries + 1):
                try:
                    img_data = gemini_generate_image(prompt, GEMINI_API_KEY, ref_image)

                    if img_data:
                        filepath.write_bytes(img_data)
                        success = True
                        break
                    else:
                        console.print(f"[yellow]No image for '{char}' (attempt {attempt+1})[/yellow]")

                except Exception as e:
                    err_msg = str(e)
                    if "429" in err_msg or "quota" in err_msg.lower() or "rate" in err_msg.lower():
                        wait = 15 * (attempt + 1)
                        console.print(f"[yellow]Rate limited, waiting {wait}s...[/yellow]")
                        time.sleep(wait)
                    else:
                        console.print(f"[yellow]Error '{char}' attempt {attempt+1}: {e}[/yellow]")
                        time.sleep(2)

            if not success:
                failed.append(char)

            progress.advance(task)
            time.sleep(0.5)

    if failed:
        console.print(f"[red]Failed characters: {failed}[/red]")
    else:
        console.print(f"[green]All {len(charset)} characters generated![/green]")

    console.print(f"Output: {img_dir}")
    return img_dir


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if not args:
        print("Usage:")
        print("  Reference mode: python generate.py --ref <folder> --name <FontName>")
        print("  Direct mode:    python generate.py --style 'botanical floral' --name <FontName>")
        sys.exit(1)

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", help="Reference images folder")
    parser.add_argument("--style", help="Style description (direct mode)")
    parser.add_argument("--name", required=True, help="Font name")
    parsed = parser.parse_args(args)

    generate_font_images(
        style=parsed.style or "",
        font_name=parsed.name,
        ref_dir=parsed.ref,
    )
