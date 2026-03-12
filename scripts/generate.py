"""Stage 1: Generate letter images using analyzed style template.

Two modes:
  A) Reference-based: analyze folder → master prompt → generate all letters
  B) Direct prompt: manual style prompt (legacy, backward-compatible)
"""
import base64
import json
import os
import time
from pathlib import Path

from google import genai
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from config.settings import (
    GEMINI_API_KEY, IMAGEN_MODEL, CHARSET, UPPERCASE, DIGITS,
    IMAGE_SIZE, OUTPUT_DIR
)
from scripts.analyze import (
    analyze_references, build_letter_prompt, encode_image,
    LETTER_INTERACTIONS, FONT_KNOWLEDGE
)

console = Console()

# Characters to generate (uppercase + digits first)
DEFAULT_CHARSET = UPPERCASE + DIGITS


def get_simple_prompt(letter: str, style: str) -> str:
    """Build simple prompt (legacy mode, no reference)."""
    interaction = LETTER_INTERACTIONS.get(letter, f"artistic decoration following the letter geometry")
    return (
        f"A single letter '{letter}' in {style} style. "
        f"The artistic elements: {interaction}. "
        f"Isolated on pure white background, centered, square composition, "
        f"high detail, the letter must be clearly readable. "
        f"ONLY the letter '{letter}', no other text or characters."
        f"\n\n{FONT_KNOWLEDGE}"
    )


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
    ref_images_b64 = []

    if ref_dir or analysis:
        if not analysis:
            console.print(f"\n[bold cyan]Analyzing reference images: {ref_dir}[/bold cyan]")
            analysis = analyze_references(ref_dir, font_name)

        master_prompt = analysis.get("master_prompt_with_font_knowledge") or analysis.get("master_prompt", "")
        console.print(f"[green]Using style: {analysis.get('style_name_en', 'analyzed')}[/green]")
        console.print(f"[dim]Material: {analysis.get('material_keyword')} | Mood: {analysis.get('mood_keyword')}[/dim]")

        # Load reference images for visual guidance
        if ref_dir:
            ref_path = Path(ref_dir)
            for ext in ["*.png", "*.jpg", "*.jpeg", "*.webp"]:
                for f in sorted(ref_path.glob(ext))[:3]:  # Max 3 ref images
                    b64, mime = encode_image(f)
                    ref_images_b64.append((b64, mime))

    client = genai.Client(api_key=GEMINI_API_KEY)
    failed = []

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
                    # Generate with Imagen 3
                    response = client.models.generate_images(
                        model=IMAGEN_MODEL,
                        prompt=prompt,
                        config=genai.types.GenerateImagesConfig(
                            number_of_images=1,
                            aspect_ratio="1:1",
                        ),
                    )

                    if response.generated_images:
                        img_data = response.generated_images[0].image.image_bytes
                        filepath.write_bytes(img_data)
                        success = True
                        break
                    else:
                        console.print(f"[yellow]No image for '{char}' (attempt {attempt+1})[/yellow]")

                except Exception as e:
                    err_msg = str(e)
                    if "429" in err_msg or "quota" in err_msg.lower():
                        console.print(f"[yellow]Rate limited, waiting 10s...[/yellow]")
                        time.sleep(10)
                    else:
                        console.print(f"[yellow]Error '{char}' attempt {attempt+1}: {e}[/yellow]")

                time.sleep(1)  # Small delay between calls

            if not success:
                failed.append(char)

            progress.advance(task)

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
