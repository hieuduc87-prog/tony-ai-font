"""Stage 2: Image Processing — rembg + crop + vectorize + optimize."""
import subprocess
import shutil
from pathlib import Path
from PIL import Image
from rembg import remove
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from config.settings import OUTPUT_DIR, GLYPH_SIZE

console = Console()


def remove_background(img_path: Path, out_path: Path) -> None:
    """Remove background using rembg."""
    with open(img_path, "rb") as f:
        input_data = f.read()
    output_data = remove(input_data)
    out_path.write_bytes(output_data)


def crop_and_normalize(img_path: Path, size: int = GLYPH_SIZE) -> None:
    """Auto-crop to tight bounding box, center in square canvas."""
    img = Image.open(img_path).convert("RGBA")
    bbox = img.getbbox()
    if not bbox:
        return

    cropped = img.crop(bbox)

    # Fit into square canvas with padding
    max_dim = max(cropped.size)
    scale = (size * 0.85) / max_dim  # 85% fill
    new_w = int(cropped.width * scale)
    new_h = int(cropped.height * scale)
    cropped = cropped.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x = (size - new_w) // 2
    y = (size - new_h) // 2
    canvas.paste(cropped, (x, y), cropped)
    canvas.save(img_path)


def vectorize_png(png_path: Path, svg_path: Path) -> bool:
    """Convert PNG to SVG using vtracer Python API."""
    try:
        import vtracer
        svg_str = vtracer.convert_raw_image_to_svg(
            png_path.read_bytes(),
            img_format="png",
            colormode="binary",
            filter_speckle=4,
            corner_threshold=60,
            length_threshold=4.0,
            splice_threshold=45,
            mode="spline",
        )
        svg_path.write_text(svg_str)
        return True
    except ImportError:
        console.print("[red]vtracer not installed. Run: pip install vtracer[/red]")
        return False
    except Exception as e:
        console.print(f"[red]vtracer error: {e}[/red]")
        return False


def optimize_svg(svg_path: Path) -> bool:
    """Optimize SVG using svgo."""
    try:
        subprocess.run(
            ["svgo", str(svg_path), "-o", str(svg_path), "--multipass"],
            check=True,
            capture_output=True,
        )
        return True
    except FileNotFoundError:
        console.print("[yellow]svgo not found. Install: npm i -g svgo[/yellow]")
        return False
    except subprocess.CalledProcessError:
        return False


def process_font_images(font_name: str, output_dir: Path | None = None) -> Path:
    """Full image processing pipeline for a font.

    Pipeline: rembg → crop/normalize → vtracer → svgo

    Returns:
        Path to SVG output directory
    """
    base = (output_dir or OUTPUT_DIR) / font_name
    img_dir = base / "images"
    nobg_dir = base / "nobg"
    svg_dir = base / "svgs"

    nobg_dir.mkdir(parents=True, exist_ok=True)
    svg_dir.mkdir(parents=True, exist_ok=True)

    pngs = sorted(img_dir.glob("*.png"))
    if not pngs:
        console.print(f"[red]No images found in {img_dir}[/red]")
        raise SystemExit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        # Step 1: Remove backgrounds
        task1 = progress.add_task("Removing backgrounds", total=len(pngs))
        for png in pngs:
            nobg_path = nobg_dir / png.name
            if not nobg_path.exists():
                remove_background(png, nobg_path)
            progress.advance(task1)

        # Step 2: Crop & normalize
        nobg_pngs = sorted(nobg_dir.glob("*.png"))
        task2 = progress.add_task("Cropping & normalizing", total=len(nobg_pngs))
        for png in nobg_pngs:
            crop_and_normalize(png)
            progress.advance(task2)

        # Step 3: Vectorize
        task3 = progress.add_task("Vectorizing to SVG", total=len(nobg_pngs))
        for png in nobg_pngs:
            svg_path = svg_dir / png.with_suffix(".svg").name
            if not svg_path.exists():
                vectorize_png(png, svg_path)
            progress.advance(task3)

        # Step 4: Optimize SVGs
        svgs = sorted(svg_dir.glob("*.svg"))
        task4 = progress.add_task("Optimizing SVGs", total=len(svgs))
        for svg in svgs:
            optimize_svg(svg)
            progress.advance(task4)

    console.print(f"[green]Processing complete! SVGs: {svg_dir}[/green]")
    return svg_dir


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python process.py <font_name>")
        sys.exit(1)
    process_font_images(sys.argv[1])
