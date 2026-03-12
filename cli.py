#!/usr/bin/env python3
"""Tony AI Font Factory — CLI.

Usage:
    python cli.py run --style "botanical floral watercolor" --name BotanicalBloom
    python cli.py run --style "fantasy mythical dragon" --name DragonScript --skip-generate
    python cli.py generate --style "art deco geometric gold" --name ArtDecoGold
    python cli.py process --name BotanicalBloom
    python cli.py assemble --name BotanicalBloom --family "Botanical Bloom"
    python cli.py qa --name BotanicalBloom
    python cli.py mockup --name BotanicalBloom
"""
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


@click.group()
def cli():
    """Tony AI Font Factory — From prompt to font in 15 minutes."""
    pass


@cli.command()
@click.option("--style", default="", help="Style description (direct mode)")
@click.option("--ref", default=None, help="Reference images folder (analysis mode)")
@click.option("--name", required=True, help="Font name (no spaces)")
@click.option("--family", default=None, help="Display family name")
@click.option("--skip-generate", is_flag=True, help="Skip image generation (use existing)")
@click.option("--skip-process", is_flag=True, help="Skip image processing")
@click.option("--skip-assemble", is_flag=True, help="Skip font assembly")
@click.option("--skip-qa", is_flag=True, help="Skip QA")
@click.option("--skip-mockup", is_flag=True, help="Skip mockup generation")
def run(style, ref, name, family, skip_generate, skip_process, skip_assemble, skip_qa, skip_mockup):
    """Run full pipeline: [analyze →] generate → process → assemble → QA → mockup."""
    if not style and not ref:
        console.print("[red]Phai co --style hoac --ref[/red]")
        raise SystemExit(1)

    start = time.time()

    console.print(Panel(
        f"[bold]Font: {name}[/bold]\n"
        f"Mode: {'Reference Analysis' if ref else 'Direct Prompt'}\n"
        f"{'Ref: ' + ref if ref else 'Style: ' + style}\n"
        f"Family: {family or name}",
        title="Tony AI Font Factory",
        border_style="blue",
    ))

    stages = []
    analysis = None

    # Stage 0: Analyze references
    if ref:
        console.print("\n[bold cyan]Stage 0: Analyze Reference Images[/bold cyan]")
        from scripts.analyze import analyze_references
        analysis = analyze_references(ref, name)
        stages.append(("Analyze", "OK"))

    # Stage 1: Generate
    if not skip_generate:
        console.print("\n[bold cyan]Stage 1/5: Generate Letters[/bold cyan]")
        from scripts.generate import generate_font_images
        generate_font_images(style, name, ref_dir=ref, analysis=analysis)
        stages.append(("Generate", "OK"))
    else:
        stages.append(("Generate", "SKIPPED"))

    # Stage 2: Process
    if not skip_process:
        console.print("\n[bold cyan]Stage 2/5: Process Images[/bold cyan]")
        from scripts.process import process_font_images
        process_font_images(name)
        stages.append(("Process", "OK"))
    else:
        stages.append(("Process", "SKIPPED"))

    # Stage 3: Assemble
    if not skip_assemble:
        console.print("\n[bold cyan]Stage 3/5: Assemble Font[/bold cyan]")
        from scripts.assemble import assemble_font
        assemble_font(name, family)
        stages.append(("Assemble", "OK"))
    else:
        stages.append(("Assemble", "SKIPPED"))

    # Stage 4: QA
    if not skip_qa:
        console.print("\n[bold cyan]Stage 4/5: Quality Assurance[/bold cyan]")
        from scripts.qa import qa_font
        qa_font(name)
        stages.append(("QA", "OK"))
    else:
        stages.append(("QA", "SKIPPED"))

    # Stage 5: Mockup
    if not skip_mockup:
        console.print("\n[bold cyan]Stage 5/5: Generate Mockups[/bold cyan]")
        from scripts.mockup import generate_mockups
        generate_mockups(name)
        stages.append(("Mockup", "OK"))
    else:
        stages.append(("Mockup", "SKIPPED"))

    # Summary
    elapsed = time.time() - start
    table = Table(title="Pipeline Summary")
    table.add_column("Stage", style="cyan")
    table.add_column("Status")
    for stage, status in stages:
        color = "green" if status == "OK" else "yellow"
        table.add_row(stage, f"[{color}]{status}[/{color}]")
    table.add_row("Total Time", f"[bold]{elapsed:.1f}s[/bold]")

    console.print("\n")
    console.print(table)
    console.print(f"\n[bold green]Output: output/{name}/[/bold green]")


@cli.command()
@click.option("--style", required=True, help="Style description")
@click.option("--name", required=True, help="Font name")
def generate(style, name):
    """Stage 1: Generate letter images with Imagen 3."""
    from scripts.generate import generate_font_images
    generate_font_images(style, name)


@cli.command()
@click.option("--name", required=True, help="Font name")
def process(name):
    """Stage 2: Process images (rembg + crop + vectorize)."""
    from scripts.process import process_font_images
    process_font_images(name)


@cli.command()
@click.option("--name", required=True, help="Font name")
@click.option("--family", default=None, help="Display family name")
def assemble(name, family):
    """Stage 3: Assemble SVGs into font files."""
    from scripts.assemble import assemble_font
    assemble_font(name, family)


@cli.command()
@click.option("--name", required=True, help="Font name")
def qa(name):
    """Stage 4: Run QA checks."""
    from scripts.qa import qa_font
    qa_font(name)


@cli.command()
@click.option("--name", required=True, help="Font name")
def mockup(name):
    """Stage 5: Generate mockup images."""
    from scripts.mockup import generate_mockups
    generate_mockups(name)


@cli.command()
def list_fonts():
    """List all fonts in output directory."""
    from config.settings import OUTPUT_DIR
    if not OUTPUT_DIR.exists():
        console.print("[yellow]No output directory yet[/yellow]")
        return

    table = Table(title="Fonts")
    table.add_column("Name", style="cyan")
    table.add_column("Images")
    table.add_column("SVGs")
    table.add_column("Fonts")
    table.add_column("Mockups")

    for d in sorted(OUTPUT_DIR.iterdir()):
        if not d.is_dir():
            continue
        imgs = len(list((d / "images").glob("*.png"))) if (d / "images").exists() else 0
        svgs = len(list((d / "svgs").glob("*.svg"))) if (d / "svgs").exists() else 0
        fonts = len(list((d / "fonts").glob("*.*"))) if (d / "fonts").exists() else 0
        mocks = len(list((d / "mockups").glob("*.png"))) if (d / "mockups").exists() else 0
        table.add_row(d.name, str(imgs), str(svgs), str(fonts), str(mocks))

    console.print(table)


if __name__ == "__main__":
    cli()
