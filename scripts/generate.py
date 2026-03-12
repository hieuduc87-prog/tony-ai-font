"""Stage 1: Generate letter images using Gemini Flash image generation.

Two modes:
  A) Reference-based: analyze folder → master prompt → generate all letters
  B) Direct prompt: manual style prompt (legacy, backward-compatible)

Uses gemini-2.0-flash-exp-image-generation via generate_content() with IMAGE modality.
"""
import base64
import io
import json
import os
import time
from pathlib import Path

from google import genai
from google.genai import types
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from config.settings import (
    GEMINI_API_KEY, GEMINI_IMAGE_MODEL, CHARSET, UPPERCASE, DIGITS,
    IMAGE_SIZE, OUTPUT_DIR
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


def extract_image_from_response(response) -> bytes | None:
    """Extract image bytes from Gemini generate_content response."""
    if not response or not response.candidates:
        return None

    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.mime_type.startswith("image/"):
            return part.inline_data.data

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

    if ref_dir or analysis:
        if not analysis:
            console.print(f"\n[bold cyan]Analyzing reference images: {ref_dir}[/bold cyan]")
            analysis = analyze_references(ref_dir, font_name)

        master_prompt = analysis.get("master_prompt_with_font_knowledge") or analysis.get("master_prompt", "")
        console.print(f"[green]Using style: {analysis.get('style_name_en', 'analyzed')}[/green]")
        console.print(f"[dim]Material: {analysis.get('material_keyword')} | Mood: {analysis.get('mood_keyword')}[/dim]")

    client = genai.Client(api_key=GEMINI_API_KEY)
    failed = []

    console.print(f"[dim]Model: {GEMINI_IMAGE_MODEL}[/dim]")

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
                    # Generate with Gemini Flash (image generation)
                    response = client.models.generate_content(
                        model=GEMINI_IMAGE_MODEL,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_modalities=["TEXT", "IMAGE"],
                            temperature=1.0,
                        ),
                    )

                    img_data = extract_image_from_response(response)

                    if img_data:
                        # Decode base64 if needed
                        if isinstance(img_data, str):
                            img_data = base64.b64decode(img_data)
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
            time.sleep(0.5)  # Small delay to avoid rate limits

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
