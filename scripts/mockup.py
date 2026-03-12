"""Stage 5: Mockup Generation — render font into templates."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from rich.console import Console

from config.settings import OUTPUT_DIR, MOCKUP_TEMPLATES_DIR

console = Console()

# Built-in mockup configs (no template files needed)
BUILTIN_MOCKUPS = [
    {
        "name": "hero_dark",
        "bg": "#1a1a2e",
        "text_color": "#ffffff",
        "size": (2400, 1200),
        "text": "DISPLAY\nFONT",
        "font_size": 200,
        "position": "center",
    },
    {
        "name": "hero_light",
        "bg": "#f5f0e8",
        "text_color": "#2d2d2d",
        "size": (2400, 1200),
        "text": "ELEGANT\nTYPOGRAPHY",
        "font_size": 180,
        "position": "center",
    },
    {
        "name": "alphabet_grid",
        "bg": "#ffffff",
        "text_color": "#333333",
        "size": (2400, 2400),
        "text": "grid",  # special: render A-Z grid
        "font_size": 160,
        "position": "grid",
    },
    {
        "name": "poster_style",
        "bg": "#0d1117",
        "text_color": "#e6b800",
        "size": (1600, 2400),
        "text": "CREATIVE\nART\nSTUDIO",
        "font_size": 160,
        "position": "center",
    },
    {
        "name": "minimal_white",
        "bg": "#ffffff",
        "text_color": "#000000",
        "size": (2400, 1200),
        "text": "Aa Bb Cc",
        "font_size": 200,
        "position": "center",
    },
]


def render_centered_text(draw, text, font, position, img_size, color):
    """Render centered text on image."""
    lines = text.split("\n")
    total_height = sum(font.getbbox(line)[3] - font.getbbox(line)[1] for line in lines)
    total_height += (len(lines) - 1) * 20

    y = (img_size[1] - total_height) // 2
    for line in lines:
        bbox = font.getbbox(line)
        w = bbox[2] - bbox[0]
        x = (img_size[0] - w) // 2
        draw.text((x, y), line, fill=color, font=font)
        y += bbox[3] - bbox[1] + 20


def render_grid(draw, font, img_size, color):
    """Render A-Z alphabet grid."""
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    cols = 6
    rows = 5  # 26 letters, 5 rows of 5-6

    cell_w = img_size[0] // (cols + 1)
    cell_h = img_size[1] // (rows + 1)

    for i, letter in enumerate(letters):
        row = i // cols
        col = i % cols
        x = cell_w // 2 + col * cell_w
        y = cell_h // 2 + row * cell_h
        bbox = font.getbbox(letter)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        draw.text((x - w // 2, y - h // 2), letter, fill=color, font=font)


def generate_mockups(font_name: str, output_dir: Path | None = None) -> list[Path]:
    """Generate mockup images for a font.

    Returns:
        List of mockup image paths
    """
    base = (output_dir or OUTPUT_DIR) / font_name
    font_dir = base / "fonts"
    mockup_dir = base / "mockups"
    mockup_dir.mkdir(parents=True, exist_ok=True)

    # Find font
    otf = font_dir / f"{font_name}.otf"
    ttf = font_dir / f"{font_name}.ttf"
    font_file = otf if otf.exists() else (ttf if ttf.exists() else None)

    if not font_file:
        console.print(f"[red]No font found in {font_dir}[/red]")
        return []

    mockup_paths = []

    for config in BUILTIN_MOCKUPS:
        try:
            img = Image.new("RGB", config["size"], config["bg"])
            draw = ImageDraw.Draw(img)
            font = ImageFont.truetype(str(font_file), config["font_size"])

            if config["position"] == "grid":
                render_grid(draw, font, config["size"], config["text_color"])
            else:
                render_centered_text(
                    draw, config["text"], font,
                    config["position"], config["size"], config["text_color"]
                )

            path = mockup_dir / f"{font_name}_{config['name']}.png"
            img.save(path, quality=95)
            mockup_paths.append(path)
            console.print(f"  Mockup: {config['name']}")
        except Exception as e:
            console.print(f"[yellow]Mockup {config['name']} failed: {e}[/yellow]")

    console.print(f"[green]{len(mockup_paths)} mockups generated![/green]")
    return mockup_paths


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python mockup.py <font_name>")
        sys.exit(1)
    generate_mockups(sys.argv[1])
