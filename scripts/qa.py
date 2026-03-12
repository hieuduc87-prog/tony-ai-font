"""Stage 4: QA — fontbakery validation + specimen rendering."""
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from rich.console import Console

from config.settings import OUTPUT_DIR

console = Console()

PANGRAM = "THE QUICK BROWN FOX JUMPS OVER THE LAZY DOG"
TEST_PAIRS = ["AV", "AW", "AT", "FA", "TA", "VA", "WA", "YA", "LT", "PA"]


def run_fontbakery(font_path: Path) -> bool:
    """Run fontbakery checks on a font file."""
    try:
        result = subprocess.run(
            ["fontbakery", "check-universal", str(font_path), "--no-progress"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        report_path = font_path.parent / f"{font_path.stem}_qa_report.txt"
        report_path.write_text(result.stdout + "\n" + result.stderr)
        console.print(f"[green]fontbakery report: {report_path}[/green]")

        if "FAIL" in result.stdout:
            console.print("[yellow]fontbakery found FAILs — review report[/yellow]")
            return False
        return True
    except FileNotFoundError:
        console.print("[yellow]fontbakery not installed, skipping[/yellow]")
        return True
    except subprocess.TimeoutExpired:
        console.print("[yellow]fontbakery timed out[/yellow]")
        return True


def render_specimen(font_path: Path, output_dir: Path | None = None) -> Path:
    """Render a specimen image for visual QA."""
    spec_dir = output_dir or font_path.parent.parent / "specimens"
    spec_dir.mkdir(parents=True, exist_ok=True)

    width, height = 2400, 1600
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    try:
        font_large = ImageFont.truetype(str(font_path), 120)
        font_medium = ImageFont.truetype(str(font_path), 72)
        font_small = ImageFont.truetype(str(font_path), 48)
    except Exception as e:
        console.print(f"[red]Cannot load font for specimen: {e}[/red]")
        return spec_dir

    y = 40

    # Title
    draw.text((40, y), font_path.stem, fill="black", font=font_large)
    y += 160

    # Full alphabet
    draw.text((40, y), "ABCDEFGHIJKLM", fill="black", font=font_medium)
    y += 100
    draw.text((40, y), "NOPQRSTUVWXYZ", fill="black", font=font_medium)
    y += 100

    # Digits
    draw.text((40, y), "0123456789", fill="black", font=font_medium)
    y += 100

    # Pangram
    draw.text((40, y), PANGRAM, fill="#333333", font=font_small)
    y += 80

    # Kerning test pairs
    pairs_text = "  ".join(TEST_PAIRS)
    draw.text((40, y), pairs_text, fill="#666666", font=font_medium)
    y += 120

    # Size samples
    for size in [96, 72, 48, 36, 24]:
        try:
            f = ImageFont.truetype(str(font_path), size)
            draw.text((40, y), f"{size}px — {PANGRAM[:30]}", fill="black", font=f)
            y += size + 20
        except Exception:
            pass

    spec_path = spec_dir / f"{font_path.stem}_specimen.png"
    img.save(spec_path, quality=95)
    console.print(f"[green]Specimen: {spec_path}[/green]")
    return spec_path


def qa_font(font_name: str, output_dir: Path | None = None) -> dict:
    """Run full QA on a font.

    Returns:
        dict with qa results
    """
    base = (output_dir or OUTPUT_DIR) / font_name
    font_dir = base / "fonts"

    results = {"fontbakery": None, "specimen": None}

    # Find font files
    otf = font_dir / f"{font_name}.otf"
    ttf = font_dir / f"{font_name}.ttf"
    font_file = otf if otf.exists() else (ttf if ttf.exists() else None)

    if not font_file:
        console.print(f"[red]No font file found in {font_dir}[/red]")
        return results

    console.print(f"QA for: {font_file.name}")

    # fontbakery
    results["fontbakery"] = run_fontbakery(font_file)

    # Specimen
    results["specimen"] = render_specimen(font_file)

    return results


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python qa.py <font_name>")
        sys.exit(1)
    qa_font(sys.argv[1])
