"""Stage 3: Font Assembly — SVG → OTF/TTF/WOFF/WOFF2."""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2Pen import T2Pen
from fontTools.pens.pointPen import PointToSegmentPen
from fontTools.svgLib import SVGPath
from fontTools.ttLib import TTFont
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from config.settings import (
    OUTPUT_DIR, UPM, ASCENDER, DESCENDER,
    UPPERCASE, DIGITS, PUNCTUATION,
    SIDEBEARING_BASE, STRAIGHT_CHARS, ROUND_CHARS, DIAGONAL_CHARS,
)

console = Console()

# Glyph name mapping for punctuation
PUNCT_NAMES = {
    ".": "period", ",": "comma", ";": "semicolon", ":": "colon",
    "!": "exclam", "?": "question", "'": "quotesingle", "-": "hyphen",
    '"': "quotedbl", "(": "parenleft", ")": "parenright",
    "&": "ampersand", "@": "at", "#": "numbersign",
}


def char_to_glyphname(c: str) -> str:
    """Convert character to glyph name."""
    if c.isalpha():
        return c
    if c.isdigit():
        return f"uni{ord(c):04X}"
    return PUNCT_NAMES.get(c, f"uni{ord(c):04X}")


def get_spacing_multiplier(c: str) -> float:
    """Get sidebearing multiplier for a character."""
    if c in STRAIGHT_CHARS:
        return 1.0
    if c in ROUND_CHARS:
        return 0.85
    if c in DIAGONAL_CHARS:
        return 0.7
    return 1.0


def svg_to_charstring(svg_path: Path, glyph_width: int = UPM):
    """Parse SVG and convert to CFF CharString."""
    svg_obj = SVGPath(str(svg_path))
    return svg_obj


# Common kerning pairs
KERN_PAIRS = [
    ("A", "V", -80), ("A", "W", -60), ("A", "T", -80), ("A", "Y", -80),
    ("F", "A", -60), ("L", "T", -80), ("L", "V", -60), ("L", "Y", -60),
    ("P", "A", -60), ("T", "A", -80), ("T", "O", -40), ("V", "A", -80),
    ("V", "O", -40), ("W", "A", -60), ("W", "O", -30), ("Y", "A", -80),
    ("Y", "O", -40),
]


def assemble_font(
    font_name: str,
    family_name: str | None = None,
    style_name: str = "Regular",
    output_dir: Path | None = None,
) -> list[Path]:
    """Assemble SVGs into font files.

    Args:
        font_name: Internal name (folder name)
        family_name: Display family name
        style_name: Style (Regular, Bold, etc.)
        output_dir: Override output directory

    Returns:
        List of generated font file paths
    """
    base = (output_dir or OUTPUT_DIR) / font_name
    svg_dir = base / "svgs"
    font_dir = base / "fonts"
    font_dir.mkdir(parents=True, exist_ok=True)

    family = family_name or font_name.replace("_", " ").replace("-", " ")

    # Collect available SVGs
    charset = UPPERCASE + DIGITS + PUNCTUATION
    glyph_map = {}  # glyphname -> svg_path

    for c in charset:
        gname = char_to_glyphname(c)
        # Try different naming conventions
        for pattern in [f"{c}.svg", f"char_{ord(c):04x}.svg", f"{gname}.svg"]:
            svg_path = svg_dir / pattern
            if svg_path.exists():
                glyph_map[gname] = (c, svg_path)
                break

    if not glyph_map:
        console.print(f"[red]No SVGs found in {svg_dir}[/red]")
        raise SystemExit(1)

    console.print(f"Found {len(glyph_map)} glyphs")

    # Build glyph order
    glyph_order = [".notdef", "space"] + list(glyph_map.keys())
    cmap = {ord(" "): "space"}
    for gname, (char, _) in glyph_map.items():
        cmap[ord(char)] = gname

    # Create font
    fb = FontBuilder(UPM, isTTF=False)
    fb.setupGlyphOrder(glyph_order)
    fb.setupCharacterMap(cmap)

    # Draw glyphs
    glyph_width = UPM
    draw_dict = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        task = progress.add_task("Building glyphs", total=len(glyph_map) + 2)

        # .notdef glyph (empty box)
        draw_dict[".notdef"] = {"width": 500, "path": None}
        progress.advance(task)

        # space glyph
        draw_dict["space"] = {"width": 250, "path": None}
        progress.advance(task)

        for gname, (char, svg_path) in glyph_map.items():
            sb = int(SIDEBEARING_BASE * get_spacing_multiplier(char))
            draw_dict[gname] = {
                "width": glyph_width + sb * 2,
                "path": svg_path,
                "lsb": sb,
            }
            progress.advance(task)

    # Setup glyphs with pen
    pen_dict = {}
    for gname in glyph_order:
        info = draw_dict.get(gname, {"width": 500, "path": None})
        if info["path"]:
            try:
                svg_obj = SVGPath(str(info["path"]))
                pen_dict[gname] = svg_obj.charString
            except Exception as e:
                console.print(f"[yellow]Skipping {gname}: {e}[/yellow]")
                pen_dict[gname] = None
        else:
            pen_dict[gname] = None

    # Setup horizontal metrics
    metrics = {}
    for gname in glyph_order:
        info = draw_dict.get(gname, {"width": 500})
        lsb = info.get("lsb", 0)
        metrics[gname] = (info["width"], lsb)

    fb.setupHorizontalMetrics(metrics)

    fb.setupHorizontalHeader(ascent=ASCENDER, descent=DESCENDER)

    fb.setupNameTable({
        "familyName": family,
        "styleName": style_name,
    })

    fb.setupOs2(
        sTypoAscender=ASCENDER,
        sTypoDescender=DESCENDER,
        sTypoLineGap=0,
    )

    fb.setupPost()

    # Export
    output_files = []

    # OTF
    otf_path = font_dir / f"{font_name}.otf"
    fb.font.save(str(otf_path))
    output_files.append(otf_path)
    console.print(f"[green]OTF: {otf_path}[/green]")

    # TTF (convert)
    ttf_path = font_dir / f"{font_name}.ttf"
    try:
        from fontTools.pens.cu2quPen import Cu2QuPen
        tt = TTFont(str(otf_path))
        tt.save(str(ttf_path))
        output_files.append(ttf_path)
        console.print(f"[green]TTF: {ttf_path}[/green]")
    except Exception as e:
        console.print(f"[yellow]TTF conversion skipped: {e}[/yellow]")

    # WOFF2
    woff2_path = font_dir / f"{font_name}.woff2"
    try:
        from fontTools.ttLib.woff2 import compress
        tt = TTFont(str(otf_path))
        tt.flavor = "woff2"
        tt.save(str(woff2_path))
        output_files.append(woff2_path)
        console.print(f"[green]WOFF2: {woff2_path}[/green]")
    except Exception as e:
        console.print(f"[yellow]WOFF2 skipped: {e}[/yellow]")

    console.print(f"[green]Font assembly complete! {len(output_files)} files.[/green]")
    return output_files


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python assemble.py <font_name> [family_name]")
        sys.exit(1)
    family = sys.argv[2] if len(sys.argv) > 2 else None
    assemble_font(sys.argv[1], family)
