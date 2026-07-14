"""
template_engine.py — posst.app Image Branding Compositing Engine
Phase 2 of Level 2 Branded Templates (v41, Jul 14 2026)

Overlays branding on AI-generated images before posting.
Standalone module — no Flask dependency. Importable by posst_api.py.

Usage:
    from template_engine import composite
    branded_bytes = composite(raw_image_bytes, {
        'business_name': 'Clippers Expert Hair Care for Dogs',
        'suburb': 'Narre Warren',
        'plan': 'Pro',
        'composition_style': 'golden_hour_action',
        'category_colours': {'primary': '#2E86AB', 'secondary': '#F5F5F5', 'text': '#FFFFFF'},
        'logo_bytes': b'...',          # Pro only, or None
        'brand_colours': None,          # Pro only, auto-extracted from logo, or None
        'contact_info': '0400 123 456', # Pro only, or None
    })
"""

import io
import logging
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter

log = logging.getLogger('posst.template_engine')

# ---------------------------------------------------------------------------
# Font paths — on server: /opt/posst/fonts/
# For local testing, override via POSST_FONTS_DIR env var
# ---------------------------------------------------------------------------
import os
FONTS_DIR = os.environ.get('POSST_FONTS_DIR', '/opt/posst/fonts')

def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a font, fall back to default if file missing."""
    path = os.path.join(FONTS_DIR, name)
    try:
        return ImageFont.truetype(path, size)
    except (OSError, IOError):
        log.warning(f'Font not found: {path}, using default')
        try:
            return ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', size)
        except (OSError, IOError):
            return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Composition style → intensity mapping
# ---------------------------------------------------------------------------
INTENSITY_MAP = {
    # FULL — bottom 15% gradient bar
    'wide_environment':    'full',
    'over_shoulder':       'full',
    'outdoor_natural':     'full',
    # MEDIUM — thin bottom strip ~8%
    'golden_hour_action':  'medium',
    'abstract_workspace':  'medium',
    'symbolic_scene':      'medium',
    # MEDIUM — these were minimal but bumped up for consistent branding
    'macro_detail':        'medium',
    'documentary_candid':  'medium',
}
DEFAULT_INTENSITY = 'medium'


# ---------------------------------------------------------------------------
# Default category colours (used when none provided)
# ---------------------------------------------------------------------------
DEFAULT_COLOURS = {
    'primary':   '#1A1A2E',   # dark navy
    'secondary': '#E8E8E8',   # light grey
    'text':      '#FFFFFF',   # white
}


def _hex_to_rgba(hex_colour: str, alpha: int = 255) -> tuple:
    """Convert '#RRGGBB' to (R, G, B, A)."""
    h = hex_colour.lstrip('#')
    if len(h) != 6:
        return (26, 26, 46, alpha)  # fallback dark navy
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


def _draw_gradient(draw: ImageDraw.Draw, img_width: int, img_height: int,
                   bar_height: int, colour: tuple):
    """Draw a vertical gradient from transparent to colour at the bottom."""
    r, g, b = colour[:3]
    for y in range(bar_height):
        progress = y / bar_height
        # Ease-in: more transparent at top, opaque at bottom
        alpha = int(progress * progress * 220)
        y_pos = img_height - bar_height + y
        draw.line([(0, y_pos), (img_width, y_pos)], fill=(r, g, b, alpha))


def _fit_text(draw: ImageDraw.Draw, text: str, font_name: str,
              max_width: int, max_size: int, min_size: int = 16) -> ImageFont.FreeTypeFont:
    """Find the largest font size that fits text within max_width."""
    for size in range(max_size, min_size - 1, -2):
        font = _font(font_name, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        if text_width <= max_width:
            return font
    return _font(font_name, min_size)


def _add_logo(base_img: Image.Image, logo_bytes: bytes,
              x: int, y: int, max_height: int) -> Image.Image:
    """Overlay a logo onto the image at (x, y), scaled to max_height."""
    try:
        logo = Image.open(io.BytesIO(logo_bytes)).convert('RGBA')
        ratio = max_height / logo.height
        new_w = int(logo.width * ratio)
        new_h = max_height
        logo = logo.resize((new_w, new_h), Image.LANCZOS)
        base_img.paste(logo, (x, y), logo)
        return base_img
    except Exception as e:
        log.warning(f'Logo overlay failed: {e}')
        return base_img


# ---------------------------------------------------------------------------
# Main compositing function
# ---------------------------------------------------------------------------
def composite(image_bytes: bytes, config: dict) -> bytes:
    """
    Apply branding overlay to an image.

    Args:
        image_bytes: Raw PNG/JPEG bytes of the generated image.
        config: Dict with keys:
            business_name (str): Required.
            suburb (str): Optional location text.
            plan (str): 'Standard' or 'Pro'.
            composition_style (str): Maps to intensity level.
            category_colours (dict): {'primary': '#hex', 'secondary': '#hex', 'text': '#hex'}
            logo_bytes (bytes|None): Pro only — logo image bytes.
            brand_colours (dict|None): Pro only — {'primary': '#hex', 'accent': '#hex'}.
            contact_info (str|None): Pro only — phone/email to display.

    Returns:
        Branded image as PNG bytes.
        On ANY error, returns the original image_bytes unchanged (failsafe).
    """
    try:
        return _composite_inner(image_bytes, config)
    except Exception as e:
        log.error(f'Compositing failed (returning raw image): {e}')
        return image_bytes


def _composite_inner(image_bytes: bytes, config: dict) -> bytes:
    """Internal compositing — raises on error (caught by composite())."""

    # Parse config
    business_name    = config.get('business_name', '').strip()
    suburb           = config.get('suburb', '').strip()
    plan             = config.get('plan', 'Standard')
    comp_style       = config.get('composition_style', '')
    colours          = config.get('category_colours') or DEFAULT_COLOURS
    logo_bytes       = config.get('logo_bytes') if plan == 'Pro' else None
    brand_colours    = config.get('brand_colours') if plan == 'Pro' else None
    contact_info     = config.get('contact_info', '').strip() if plan == 'Pro' else ''

    if not business_name:
        return image_bytes  # nothing to overlay

    # Use brand colours if available (Pro), else category colours
    primary_hex  = (brand_colours or colours).get('primary', colours.get('primary', '#1A1A2E'))
    text_hex     = colours.get('text', '#FFFFFF')
    primary_rgb  = _hex_to_rgba(primary_hex)[:3]
    text_rgba    = _hex_to_rgba(text_hex)

    # Determine intensity
    intensity = INTENSITY_MAP.get(comp_style, DEFAULT_INTENSITY)

    # Open image
    img = Image.open(io.BytesIO(image_bytes)).convert('RGBA')
    w, h = img.size

    # Create overlay layer
    overlay = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Padding
    pad_x = int(w * 0.04)  # 4% horizontal padding

    if intensity == 'full':
        _render_full(draw, w, h, pad_x, business_name, suburb, contact_info,
                     primary_rgb, text_rgba, logo_bytes, overlay)

    elif intensity == 'medium':
        _render_medium(draw, w, h, pad_x, business_name, suburb, contact_info,
                       primary_rgb, text_rgba, logo_bytes, overlay)

    elif intensity == 'minimal':
        _render_minimal(draw, w, h, pad_x, business_name,
                        primary_rgb, text_rgba)

    # Composite overlay onto image
    img = Image.alpha_composite(img, overlay)

    # Convert to RGB for PNG output (no alpha channel in final)
    img = img.convert('RGB')

    buf = io.BytesIO()
    img.save(buf, format='PNG', quality=95)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Intensity renderers
# ---------------------------------------------------------------------------

def _render_full(draw, w, h, pad_x, business_name, suburb, contact_info,
                 primary_rgb, text_rgba, logo_bytes, overlay):
    """
    FULL intensity — bottom 12% gradient bar.
    Business name (large) on top, contact info below (Pro). No suburb.
    """
    has_contact = bool(contact_info)
    bar_height = int(h * (0.12 if has_contact else 0.10))

    # Draw gradient
    _draw_gradient(draw, w, h, bar_height, primary_rgb)

    # Available text area
    text_area_left = pad_x
    text_area_right = w - pad_x

    # Logo (Pro) — positioned left, text shifts right
    if logo_bytes:
        logo_h = int(bar_height * 0.55)
        logo_y = h - bar_height + int(bar_height * 0.22)
        _add_logo(overlay, logo_bytes, pad_x, logo_y, logo_h)
        text_area_left = pad_x + logo_h + int(pad_x * 0.5)

    available_width = text_area_right - text_area_left

    # Business name
    name_font = _fit_text(draw, business_name, 'Poppins-Bold.ttf',
                          available_width, max_size=28, min_size=16)

    if has_contact:
        # Stacked: name at ~20%, contact below
        name_y = h - bar_height + int(bar_height * 0.2)
        draw.text((text_area_left, name_y), business_name,
                  font=name_font, fill=text_rgba)

        name_bbox = draw.textbbox((text_area_left, name_y), business_name, font=name_font)
        contact_y = name_bbox[3] + 4
        contact_font = _font('Poppins-Regular.ttf', 16)
        draw.text((text_area_left, contact_y), contact_info,
                  font=contact_font, fill=(*text_rgba[:3], 180))
    else:
        # No contact — vertically centre name
        name_bbox = draw.textbbox((0, 0), business_name, font=name_font)
        name_h = name_bbox[3] - name_bbox[1]
        name_y = h - bar_height + (bar_height - name_h) // 2
        draw.text((text_area_left, name_y), business_name,
                  font=name_font, fill=text_rgba)


def _render_medium(draw, w, h, pad_x, business_name, suburb, contact_info,
                   primary_rgb, text_rgba, logo_bytes, overlay):
    """
    MEDIUM intensity — bottom strip.
    Business name on top, contact info below (Pro). No suburb.
    Bar height adjusts: 8% without contact, 12% with contact.
    """
    has_contact = bool(contact_info)
    bar_height = int(h * (0.12 if has_contact else 0.08))

    _draw_gradient(draw, w, h, bar_height, primary_rgb)

    text_area_left = pad_x
    text_area_right = w - pad_x

    # Logo (Pro) — left-aligned
    if logo_bytes:
        logo_h = int(bar_height * 0.45)
        logo_y = h - bar_height + int(bar_height * 0.2)
        _add_logo(overlay, logo_bytes, pad_x, logo_y, logo_h)
        text_area_left = pad_x + logo_h + int(pad_x * 0.4)

    available_width = text_area_right - text_area_left

    # Business name only (no suburb)
    text_font = _fit_text(draw, business_name, 'Poppins-Bold.ttf',
                          available_width, max_size=28, min_size=16)
    name_bbox = draw.textbbox((0, 0), business_name, font=text_font)
    name_h = name_bbox[3] - name_bbox[1]

    if has_contact:
        # Stacked: name at ~20% of bar, contact below
        name_y = h - bar_height + int(bar_height * 0.2)
        draw.text((text_area_left, name_y), business_name,
                  font=text_font, fill=text_rgba)

        contact_font = _font('Poppins-Regular.ttf', 14)
        contact_y = name_y + name_h + 4
        draw.text((text_area_left, contact_y), contact_info,
                  font=contact_font, fill=(*text_rgba[:3], 180))
    else:
        # No contact — vertically centre name in bar
        name_y = h - bar_height + (bar_height - name_h) // 2
        draw.text((text_area_left, name_y), business_name,
                  font=text_font, fill=text_rgba)


def _render_minimal(draw, w, h, pad_x, business_name,
                    primary_rgb, text_rgba):
    """
    MINIMAL intensity — small business name at bottom edge.
    Subtle text shadow for readability, no gradient bar, no logo.
    """
    font = _font('Poppins-Regular.ttf', 16)
    text_bbox = draw.textbbox((0, 0), business_name, font=font)
    text_w = text_bbox[2] - text_bbox[0]
    text_h = text_bbox[3] - text_bbox[1]

    x = w - pad_x - text_w
    y = h - int(h * 0.03) - text_h

    # Text shadow for readability
    shadow_colour = (0, 0, 0, 140)
    draw.text((x + 1, y + 1), business_name, font=font, fill=shadow_colour)
    draw.text((x, y), business_name, font=font, fill=(*text_rgba[:3], 200))


# ---------------------------------------------------------------------------
# CLI test helper
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('Usage: python3 template_engine.py <input.png> [style] [plan]')
        print('Styles: wide_environment, golden_hour_action, macro_detail, etc.')
        sys.exit(1)

    input_path = sys.argv[1]
    style = sys.argv[2] if len(sys.argv) > 2 else 'wide_environment'
    plan = sys.argv[3] if len(sys.argv) > 3 else 'Standard'

    with open(input_path, 'rb') as f:
        raw = f.read()

    result = composite(raw, {
        'business_name': 'Clippers Expert Hair Care for Dogs',
        'suburb': 'Narre Warren',
        'plan': plan,
        'composition_style': style,
        'category_colours': {'primary': '#2E86AB', 'secondary': '#F5F5F5', 'text': '#FFFFFF'},
        'logo_bytes': None,
        'brand_colours': None,
        'contact_info': '0400 123 456' if plan == 'Pro' else '',
    })

    out_path = input_path.rsplit('.', 1)[0] + f'_branded_{style}_{plan}.png'
    with open(out_path, 'wb') as f:
        f.write(result)
    print(f'Saved: {out_path} ({len(result)} bytes)')
