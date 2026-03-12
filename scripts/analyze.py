"""Stage 0: Analyze reference images → extract style + build master prompt.

Giống art-factory.ts của tony-ai-art:
- Phân tích 20 tiêu chí thị giác
- Trích xuất material, lighting, color palette, texture, mood
- Tạo master prompt template với {LETTER} placeholder
- Bổ sung font-specific knowledge (kerning, spacing, proportion)
"""
import base64
import json
import os
import sys
from pathlib import Path

from google import genai
from rich.console import Console

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import GEMINI_API_KEY, PROJECT_ROOT

console = Console()

# ── Font Technical Knowledge ──────────────────────────────────────────
FONT_KNOWLEDGE = """
FONT TECHNICAL REQUIREMENTS (CRITICAL — follow exactly):

1. LETTER ISOLATION: Each letter must be ALONE, perfectly centered on pure white/transparent background.
   NO other letters, NO text, NO words. ONLY the single character specified.

2. LETTER PROPORTIONS (Display Font Standard):
   - Cap height: Letter fills ~80% of canvas height
   - All letters share consistent visual weight (stroke thickness)
   - Round letters (O, C, G, Q, S) extend ~2% beyond cap height (optical correction)
   - Pointed letters (A, V, W, M) apex extends ~3% beyond cap height
   - Flat-top letters (H, E, F, T, I) align exactly at cap height

3. COUNTER SPACE (internal white space):
   - Open counters (C, G, S, U) must have clear, readable openings
   - Closed counters (A, B, D, O, P, Q, R) must have visible internal space
   - The artistic elements must NOT fill/block the counter space
   - Letters must remain READABLE even with heavy decoration

4. STROKE CONSISTENCY:
   - Main strokes should have consistent visual weight across all letters
   - Vertical strokes slightly thicker than horizontal (standard optical trick)
   - Diagonal strokes (A, V, W, X, K, Z) maintain visual weight balance
   - Junctions (where strokes meet) may thin slightly to prevent ink trap effect

5. LETTER-SPECIFIC GEOMETRY:
   - STRAIGHT letters (H, I, L, E, F, T): vertical/horizontal strokes dominant
   - ROUND letters (O, C, G, Q, D, U, S): curved strokes, slightly wider than straight
   - DIAGONAL letters (A, V, W, X, K, Z, M, N): angular strokes, widest letters
   - Letters with BOWLS (B, P, R, D): curved + straight combination

6. SIDEBEARING SPACE (space around each letter):
   - Leave ~10% blank on left and right sides for future kerning
   - Straight-sided letters (H, I, M, N): standard sidebearing
   - Round-sided letters (O, C, D): slightly less sidebearing (optical)
   - Open-sided letters (L, T, J): asymmetric sidebearing

7. CONSISTENT ART STYLE ACROSS ALL LETTERS:
   - Same material finish, lighting direction, color palette
   - Same level of detail/decoration density
   - Same background treatment
   - Same artistic elements (if flowers: same flower types; if creatures: same creature)
   - Variation in HOW art interacts with each letter's shape, NOT in art style
"""

# ── Letter Interaction Maps ───────────────────────────────────────────
LETTER_INTERACTIONS = {
    "A": "art elements frame the pointed apex, decorations cascade down both diagonal strokes, detail visible through triangular counter below crossbar",
    "B": "art wraps along two curved bowls, decoration fills space between top and bottom curves, vertical spine acts as anchor",
    "C": "art follows the open curve, decorative elements emerge from both terminal points, negative space in opening preserved",
    "D": "art traces the large curved bowl, decoration anchors on vertical spine, internal counter space clear",
    "E": "art adorns three horizontal arms, decoration cascades from top to bottom, vertical spine as backbone",
    "F": "art crowns the top horizontal arm, decoration descends along vertical stroke, open bottom area",
    "G": "art follows the curved form, decorative element rests on horizontal bar, internal counter visible",
    "H": "art connects the two vertical pillars, decoration drapes across crossbar, symmetrical arrangement",
    "I": "art wraps the single vertical stroke, decoration extends outward from serifs/terminals, compact",
    "J": "art follows the curved hook at bottom, decoration cascades down vertical stroke, open top area",
    "K": "art meets at the junction point, decoration splits along diagonal arm and leg, dynamic asymmetry",
    "L": "art rests on the horizontal base, decoration rises along vertical stroke, open right side",
    "M": "art crowns both peaks, decoration drapes between the two arches, widest letter composition",
    "N": "art follows the diagonal stroke connecting two verticals, decoration balanced on both sides",
    "O": "art wraps the full circular/elliptical form, decoration follows the continuous curve, ouroboros-like",
    "P": "art fills the upper bowl, decoration anchors on vertical descender, open bottom half",
    "Q": "art encircles the round form, decorative tail element extends from bottom right, distinctive feature",
    "R": "art fills the upper bowl and follows the diagonal leg, decoration at junction point",
    "S": "art follows the double-curve path, decoration at both terminals, snake-like flow",
    "T": "art crowns the horizontal top bar, decoration descends along vertical center stroke, symmetrical",
    "U": "art fills the curved bottom, decoration rises along both vertical strokes, open top",
    "V": "art converges at the bottom apex, decoration spreads along both diagonal strokes, inverted triangle",
    "W": "art fills both valleys, decoration spans the widest letter, double-V composition",
    "X": "art meets at the center crossing point, decoration radiates along all four strokes, symmetrical",
    "Y": "art crowns the fork junction, decoration descends along the vertical tail, open top area",
    "Z": "art follows the zigzag path, decoration at both horizontal bars and diagonal, dynamic angles",
    "0": "art wraps the oval/circular numeral, similar to O but more vertical",
    "1": "art adorns the single vertical stroke with base, compact and vertical",
    "2": "art follows the curved top into diagonal into horizontal base, flowing",
    "3": "art traces the double curve, similar to B but open on left side",
    "4": "art highlights the angular junction of vertical and horizontal with diagonal",
    "5": "art follows horizontal top into curve bottom, decoration at style points",
    "6": "art follows the descending curve into closed bottom bowl",
    "7": "art adorns the horizontal top bar and diagonal descender",
    "8": "art wraps the double loop figure-eight form, balanced composition",
    "9": "art fills the upper bowl with descending curved tail",
}

ANALYSIS_PROMPT = """You are an expert visual art analyst AND typography/font design specialist.

Analyze this reference image of an artistic letter/character with extreme precision.
Extract EVERY visual detail using these 20 criteria:

1. **Subject**: What letter/character is shown? What is the primary artistic element?
2. **Material**: Exact material properties — metal type, stone, wood, glass, organic? Metalness %, roughness %, reflectivity
3. **Color Palette**: Extract 5-8 dominant hex color codes. Primary, secondary, accent colors
4. **Lighting**: Direction (top-left, top-right, etc), intensity, shadow depth, specular highlights, rim light
5. **Texture**: Surface texture detail — smooth, rough, engraved, embossed, weathered, polished
6. **Background**: Exact background description — color, texture, gradient, depth, vignette
7. **Art Style**: Medium and technique — 3D render, watercolor, oil paint, vector, photography, mixed
8. **Decorative Elements**: What decorates the letter? Flowers, creatures, patterns, particles, effects
9. **3D Effects**: Depth, perspective, camera angle, extrusion depth, bevel style
10. **Mood/Emotion**: Elegant, powerful, playful, dark, ethereal, luxurious, organic
11. **Edge Quality**: Sharp, soft, anti-aliased, glowing, lost edges, outline style
12. **Special Effects**: Glow, particles, sparkles, smoke, fire, water, energy
13. **Contrast**: Light/dark ratio, color contrast, texture contrast
14. **Rendering Quality**: Ray-tracing, global illumination, ambient occlusion, subsurface scattering
15. **Composition**: How the letter fills the frame, margins, aspect ratio
16. **Decoration Density**: How much of the letter surface is decorated vs clean
17. **Color Harmony**: Monochromatic, complementary, analogous, triadic
18. **Scale of Details**: Fine details vs broad strokes, macro vs micro elements
19. **Interaction Pattern**: How do artistic elements interact with letter geometry?
20. **Typography Style**: Serif, sans-serif, slab, display, decorative, script characteristics

After analysis, generate a MASTER PROMPT TEMPLATE for creating MORE letters in this EXACT style.

The template must:
- Use {LETTER} as placeholder for the target letter
- Use {LETTER_INTERACTION} as placeholder for letter-specific art interaction
- Be detailed enough that another AI can reproduce the EXACT SAME visual style
- Include ALL material, lighting, color, texture, effect specifications
- Include font/typography technical specifications

OUTPUT FORMAT (JSON):
{
    "analysis": {
        "subject": "...",
        "material": "...",
        "colors": ["#hex1", "#hex2", ...],
        "lighting": "...",
        "texture": "...",
        "background": "...",
        "art_style": "...",
        "decorative_elements": "...",
        "effects_3d": "...",
        "mood": "...",
        "edge_quality": "...",
        "special_effects": "...",
        "contrast": "...",
        "rendering": "...",
        "composition": "...",
        "decoration_density": "...",
        "color_harmony": "...",
        "detail_scale": "...",
        "interaction_pattern": "...",
        "typography_style": "..."
    },
    "master_prompt": "A single letter {LETTER} rendered as ... [FULL DETAILED PROMPT TEMPLATE with exact style specs] ... {LETTER_INTERACTION} ...",
    "style_name_en": "Short English name for this style",
    "style_name_vi": "Short Vietnamese name",
    "creature_or_element": "Main decorative element type",
    "material_keyword": "Primary material (chrome/gold/jade/crystal/floral/etc)",
    "mood_keyword": "Primary mood"
}

IMPORTANT: The master_prompt must be extremely detailed (200+ words) to ensure perfect style consistency across 26+ letters.
Return ONLY valid JSON, no markdown."""


def encode_image(path: Path) -> tuple[str, str]:
    """Encode image to base64 with mime type."""
    ext = path.suffix.lower()
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext.lstrip("."), "image/png")
    data = base64.b64encode(path.read_bytes()).decode()
    return data, mime


def analyze_references(
    ref_dir: str | Path,
    font_name: str | None = None,
) -> dict:
    """Analyze reference images and build master prompt template.

    Args:
        ref_dir: Path to folder containing reference letter images
        font_name: Optional font name for context

    Returns:
        dict with analysis, master_prompt, style metadata
    """
    ref_dir = Path(ref_dir)
    if not ref_dir.exists():
        console.print(f"[red]Reference folder not found: {ref_dir}[/red]")
        raise SystemExit(1)

    # Find reference images
    ref_images = []
    for ext in ["*.png", "*.jpg", "*.jpeg", "*.webp"]:
        ref_images.extend(ref_dir.glob(ext))
    ref_images.sort()

    if not ref_images:
        console.print(f"[red]No images found in {ref_dir}[/red]")
        raise SystemExit(1)

    console.print(f"Found {len(ref_images)} reference images in {ref_dir}")

    # Use up to 5 reference images for analysis
    samples = ref_images[:5]

    if not GEMINI_API_KEY:
        console.print("[red]GEMINI_API_KEY not set[/red]")
        raise SystemExit(1)

    client = genai.Client(api_key=GEMINI_API_KEY)

    # Build content parts with images
    parts = []
    for img_path in samples:
        b64, mime = encode_image(img_path)
        parts.append({"inline_data": {"mime_type": mime, "data": b64}})
        console.print(f"  Loaded: {img_path.name}")

    parts.append({"text": ANALYSIS_PROMPT})

    console.print("[cyan]Analyzing reference images...[/cyan]")

    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-05-20",
        contents=[{"parts": parts}],
        config=genai.types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=4096,
        ),
    )

    # Parse response
    text = response.text.strip()
    # Clean markdown code blocks if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        console.print("[red]Failed to parse analysis JSON[/red]")
        console.print(text[:500])
        raise

    # Inject font technical knowledge into master prompt
    master = result.get("master_prompt", "")
    result["master_prompt_with_font_knowledge"] = master + "\n\n" + FONT_KNOWLEDGE

    # Save analysis
    if font_name:
        from config.settings import OUTPUT_DIR
        analysis_dir = OUTPUT_DIR / font_name
        analysis_dir.mkdir(parents=True, exist_ok=True)
        analysis_file = analysis_dir / "style_analysis.json"
        analysis_file.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        console.print(f"[green]Analysis saved: {analysis_file}[/green]")

    console.print(f"[green]Style: {result.get('style_name_en', 'Unknown')}[/green]")
    console.print(f"[green]Material: {result.get('material_keyword', 'Unknown')}[/green]")
    console.print(f"[green]Mood: {result.get('mood_keyword', 'Unknown')}[/green]")

    return result


def build_letter_prompt(master_prompt: str, letter: str, with_font_knowledge: bool = True) -> str:
    """Build generation prompt for a specific letter using master template.

    Args:
        master_prompt: Master prompt template with {LETTER} and {LETTER_INTERACTION}
        letter: Target letter (A-Z, 0-9)
        with_font_knowledge: Include font technical knowledge
    """
    interaction = LETTER_INTERACTIONS.get(letter.upper(), f"art decorates the character '{letter}' following its geometry")

    prompt = master_prompt.replace("{LETTER}", letter.upper())
    prompt = prompt.replace("{LETTER_INTERACTION}", interaction)

    if with_font_knowledge and FONT_KNOWLEDGE not in prompt:
        prompt += "\n\n" + FONT_KNOWLEDGE

    # Add final enforcement
    prompt += f"""

ABSOLUTE RULES:
1. Generate ONLY the single letter/character '{letter.upper()}' — nothing else
2. The letter '{letter.upper()}' must be clearly readable and recognizable
3. Centered on PURE WHITE background
4. SQUARE composition (1:1 aspect ratio)
5. High resolution, clean edges
6. The letter MUST be the dominant visual element"""

    return prompt


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python analyze.py <ref_folder> [font_name]")
        print("Example: python analyze.py ~/Desktop/ref_botanical BotanicalBloom")
        sys.exit(1)
    name = sys.argv[2] if len(sys.argv) > 2 else None
    result = analyze_references(sys.argv[1], name)
    print(json.dumps(result, indent=2, ensure_ascii=False))
