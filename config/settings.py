"""Tony AI Font Factory — Configuration."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", PROJECT_ROOT / "output"))
MOCKUP_TEMPLATES_DIR = Path(os.getenv("MOCKUP_TEMPLATES_DIR", PROJECT_ROOT / "assets/mockup_templates"))

# Font specs
UPM = 1000          # Units per em
ASCENDER = 800
DESCENDER = -200
GLYPH_SIZE = 1000   # Normalize SVGs to this
IMAGE_SIZE = 1024    # Generated image size

# Character set — uppercase first
UPPERCASE = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DIGITS = "0123456789"
PUNCTUATION = ".,;:!?'-\"()&@#"
CHARSET = UPPERCASE + DIGITS + PUNCTUATION

# Spacing rules (multiplier of sidebearing base)
SIDEBEARING_BASE = 50  # units
SPACING_RULES = {
    "straight": 1.0,    # H, I, M, N, etc.
    "round": 0.85,      # O, C, G, Q, etc.
    "diagonal": 0.7,    # A, V, W, X, etc.
}
STRAIGHT_CHARS = set("BDEFHIJKLMNPRU")
ROUND_CHARS = set("CDGOQSU")
DIAGONAL_CHARS = set("AVWXYZ")

# Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.0-flash-exp-image-generation")

# APIs
GUMROAD_ACCESS_TOKEN = os.getenv("GUMROAD_ACCESS_TOKEN", "")
ETSY_API_KEY = os.getenv("ETSY_API_KEY", "")
ETSY_API_SECRET = os.getenv("ETSY_API_SECRET", "")
