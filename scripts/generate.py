"""Stage 1: Generate letter images using Gemini Imagen 3 API."""
import os
import asyncio
from pathlib import Path
from google import genai
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from config.settings import (
    GEMINI_API_KEY, IMAGEN_MODEL, CHARSET, UPPERCASE, IMAGE_SIZE, OUTPUT_DIR
)

console = Console()


def get_prompt(letter: str, style: str) -> str:
    """Build generation prompt for a single letter."""
    return (
        f"The letter {letter} in {style} style, "
        f"isolated on pure white background, centered, "
        f"high detail, square composition, no other text or objects"
    )


def generate_font_images(
    style: str,
    font_name: str,
    charset: str = UPPERCASE,
    output_dir: Path | None = None,
    retries: int = 2,
) -> Path:
    """Generate all letter images for a font style.

    Args:
        style: Style description (e.g. "botanical floral watercolor")
        font_name: Name for the font (used as folder name)
        charset: Characters to generate
        output_dir: Override output directory
        retries: Number of retries per failed letter

    Returns:
        Path to the generated images directory
    """
    if not GEMINI_API_KEY:
        console.print("[red]ERROR: GEMINI_API_KEY not set in .env[/red]")
        raise SystemExit(1)

    client = genai.Client(api_key=GEMINI_API_KEY)
    img_dir = (output_dir or OUTPUT_DIR) / font_name / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

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

            prompt = get_prompt(char, style)
            success = False

            for attempt in range(retries + 1):
                try:
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
                    console.print(f"[yellow]Error '{char}' attempt {attempt+1}: {e}[/yellow]")

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
    if len(sys.argv) < 3:
        print("Usage: python generate.py <style> <font_name>")
        print('Example: python generate.py "botanical floral watercolor" BotanicalBloom')
        sys.exit(1)
    generate_font_images(sys.argv[1], sys.argv[2])
