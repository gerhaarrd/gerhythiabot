"""Utility module to generate premium graphical profile cards for Rhythia players."""

from __future__ import annotations

import io
import math
from typing import Any
from PIL import Image, ImageDraw, ImageFont, ImageFilter

import os

FONT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts", "DroidSans.ttf")

def load_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()

def draw_gradient_back(width: int, height: int) -> Image.Image:
    """Creates a beautiful dark gradient background."""
    base = Image.new("RGBA", (width, height), (15, 23, 42, 255)) # Dark slate base
    draw = ImageDraw.Draw(base)
    # Draw vertical gradient (dark blue-indigo to dark slate)
    for y in range(height):
        r = int(24 + (10 - 24) * (y / height))
        g = int(20 + (15 - 20) * (y / height))
        b = int(64 + (30 - 64) * (y / height))
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))
    return base

def draw_radar_chart(card: Image.Image, cx: float, cy: float, max_r: float, values: list[float], labels: list[str]) -> None:
    """Draws a premium 5-axis radar chart with labels and a filled polygon."""
    num_axes = len(values)
    angle_step = 2 * math.pi / num_axes
    font = load_font(12)
    draw = ImageDraw.Draw(card)

    # 1. Draw web circles (concentric rings)
    for r_factor in [0.25, 0.5, 0.75, 1.0]:
        r = max_r * r_factor
        points = []
        for i in range(num_axes):
            angle = i * angle_step - math.pi / 2
            x = cx + r * math.cos(angle)
            y = cy + r * math.sin(angle)
            points.append((x, y))
        draw.polygon(points, outline=(255, 255, 255, 30), fill=None)

    # 2. Draw axis lines
    for i in range(num_axes):
        angle = i * angle_step - math.pi / 2
        x_outer = cx + max_r * math.cos(angle)
        y_outer = cy + max_r * math.sin(angle)
        draw.line([(cx, cy), (x_outer, y_outer)], fill=(255, 255, 255, 30), width=1)

    # 3. Plot the data polygon on a transparent overlay
    poly_points = []
    for i, val in enumerate(values):
        val_clamped = max(0.05, min(1.0, val)) # avoid completely flat lines
        r = max_r * val_clamped
        angle = i * angle_step - math.pi / 2
        x = cx + r * math.cos(angle)
        y = cy + r * math.sin(angle)
        poly_points.append((x, y))

    if len(poly_points) >= 3:
        overlay = Image.new("RGBA", card.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        # Semi-transparent filled polygon
        overlay_draw.polygon(poly_points, fill=(139, 92, 246, 100), outline=(139, 92, 246, 255))
        card.alpha_composite(overlay)
        
        # Highlight points
        for pt in poly_points:
            draw.ellipse([pt[0] - 3, pt[1] - 3, pt[0] + 3, pt[1] + 3], fill=(255, 255, 255, 255), outline=(139, 92, 246, 255), width=2)

    # 4. Draw labels
    for i, label in enumerate(labels):
        angle = i * angle_step - math.pi / 2
        # Offset label slightly outward from the max radius
        x_lbl = cx + (max_r + 20) * math.cos(angle)
        y_lbl = cy + (max_r + 12) * math.sin(angle)
        # Center align label text
        try:
            bbox = draw.textbbox((0, 0), label, font=font)
            lbl_w = bbox[2] - bbox[0]
            lbl_h = bbox[3] - bbox[1]
        except Exception:
            lbl_w, lbl_h = 40, 10
        draw.text((x_lbl - lbl_w / 2, y_lbl - lbl_h / 2), label, fill=(243, 244, 246, 255), font=font)


def generate_profile_card(profile_data: dict[str, Any], avatar_bytes: bytes | None = None, flag_bytes: bytes | None = None) -> io.BytesIO:
    """Generates the premium profile card and returns it as a bytes stream."""
    width, height = 800, 400
    card = draw_gradient_back(width, height)
    
    # Create an overlay layer for blurred light effects
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    
    # Faint neon ambient glow under avatar and radar chart (Violet & Blue)
    glow_draw.ellipse([50 - 20, 60 - 20, 50 + 150 + 20, 60 + 150 + 20], fill=(139, 92, 246, 45))
    glow_draw.ellipse([660 - 110, 200 - 110, 660 + 110, 200 + 110], fill=(59, 130, 246, 35))
    
    # Apply blur to the glow layer
    glow = glow.filter(ImageFilter.GaussianBlur(18))
    card.alpha_composite(glow)

    draw = ImageDraw.Draw(card)

    user = profile_data.get("user") or {}
    username = user.get("username") or user.get("computedUsername") or "Unknown"
    if len(username) > 16:
        username = username[:16]
    clan = user.get("clan")
    clan_tag = f" [{clan['acronym']}]" if isinstance(clan, dict) and clan.get("acronym") else ""
    
    # Glassmorphic Box with dual-tone neon highlight border
    draw.rounded_rectangle([250, 40, 520, 360], radius=15, fill=(15, 23, 42, 180))
    draw.rounded_rectangle([250, 40, 520, 360], radius=15, outline=(139, 92, 246, 60), width=2)

    # 1. Avatar rendering
    avatar_size = 150
    if avatar_bytes:
        try:
            avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
        except Exception:
            avatar_img = Image.new("RGBA", (avatar_size, avatar_size), (139, 92, 246, 255)) # Violet fallback
    else:
        avatar_img = Image.new("RGBA", (avatar_size, avatar_size), (139, 92, 246, 255))

    # Mask to circular avatar
    mask = Image.new("L", (avatar_size, avatar_size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse([0, 0, avatar_size, avatar_size], fill=255)
    
    circular_avatar = Image.new("RGBA", (avatar_size, avatar_size))
    circular_avatar.paste(avatar_img, (0, 0), mask)
    
    # Paste avatar on the left
    card.paste(circular_avatar, (50, 60), circular_avatar)
    
    # Avatar circular border with glowing gradient effect (Violet + Blue)
    draw.ellipse([47, 57, 50 + avatar_size + 3, 60 + avatar_size + 3], outline=(139, 92, 246, 255), width=3)
    draw.ellipse([46, 56, 50 + avatar_size + 4, 60 + avatar_size + 4], outline=(59, 130, 246, 100), width=1)

    # 2. Draw user identity info
    font_title = load_font(20) if len(username) > 12 else load_font(26)
    font_sub = load_font(13)
    font_bold = load_font(18)
    font_badge = load_font(10)
    
    full_name = f"{username}{clan_tag}"
    draw.text((50, 230), full_name, fill=(255, 255, 255, 255), font=font_title)
    
    user_id_text = f"ID: {user.get('id', '—')}"
    draw.text((50, 272), user_id_text, fill=(156, 163, 175, 255), font=font_sub)
    
    # Draw country flag
    country_code = (user.get("flag") or "US").upper()
    if flag_bytes:
        try:
            flag_img = Image.open(io.BytesIO(flag_bytes)).convert("RGBA")
            # Resize flag to fit nicely
            flag_img = flag_img.resize((26, 17), Image.Resampling.LANCZOS)
            card.paste(flag_img, (50, 303), flag_img)
            draw.text((84, 301), country_code, fill=(209, 213, 219, 255), font=font_sub)
        except Exception:
            draw.text((50, 301), f"Country: {country_code}", fill=(209, 213, 219, 255), font=font_sub)
    else:
        draw.text((50, 301), f"Country: {country_code}", fill=(209, 213, 219, 255), font=font_sub)

    # 2b. Draw Badges as colored pill tags (Filtered to specific badges only)
    allowed_badges = {"Global Moderator", "Tester", "RCT", "Bug Hunter", "Content Creator", "Team Ranked"}
    badges = [b for b in (user.get("badges") or []) if b in allowed_badges]
    
    priority_order = {
        "Global Moderator": 0,
        "RCT": 1,
        "Team Ranked": 2,
        "Content Creator": 3,
        "Tester": 4,
        "Bug Hunter": 5,
    }
    
    sorted_badges = sorted(badges, key=lambda b: priority_order.get(b, 100))
    
    badge_colors = {
        "Global Moderator": (239, 110, 110, 255),     # Light Red
        "Tester": (134, 239, 172, 255),               # Light Green
        "RCT": (251, 146, 60, 255),                   # Orange-Yellow
        "Team Ranked": (251, 146, 60, 255),           # Orange-Yellow     
        "Bug Hunter": (234, 179, 8, 255),             # Strong Yellow
        "Content Creator": (168, 85, 247, 255),       # Purple
    }
    
    badge_x = 50
    badge_y = 332
    max_badge_x = 240
    
    for badge_name in sorted_badges:
        color = badge_colors.get(badge_name, (100, 116, 139, 200))
        
        try:
            bbox = draw.textbbox((0, 0), badge_name, font=font_badge)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
        except Exception:
            tw, th = len(badge_name) * 6, 8
            
        pad_x, pad_y = 6, 3
        badge_w = tw + pad_x * 2
        badge_h = 18
        
        if badge_x + badge_w > max_badge_x:
            if badge_y == 332:
                badge_x = 50
                badge_y = 356
            else:
                break
                
        draw.rounded_rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + badge_h], radius=4, fill=color)
        
        # Text color: dark gray/black for very light backgrounds (like light green/yellow) to ensure readability
        text_color = (15, 23, 42, 255) if badge_name in {"Tester", "Bug Hunter", "RCT", "Team Ranked"} else (255, 255, 255, 255)
        draw.text((badge_x + pad_x, badge_y + (badge_h - th) / 2 - 1), badge_name, fill=text_color, font=font_badge)
        
        badge_x += badge_w + 6

    # 3. Draw statistics in the central box
    stats_y_start = 65
    stats_step = 60
    
    metrics = [
        ("Skill Points", f"{user.get('skill_points', 0.0):,.2f} RP", (139, 92, 246, 255)),
        ("Spin Points", f"{user.get('spin_skill_points', 0.0):,.2f} SP", (236, 72, 153, 255)),
        ("Play Count", f"{user.get('play_count', 0):,}", (59, 130, 246, 255)),
        ("Global Rank", f"#{user.get('position', 0):,}" if user.get('position') else "—", (251, 191, 36, 255)),
        ("Country Rank", f"#{user.get('country_position', 0):,}" if user.get('country_position') else "—", (16, 185, 129, 255)),
    ]
    
    for idx, (label, val, col) in enumerate(metrics):
        y = stats_y_start + idx * stats_step
        # Draw small color badge/indicator
        draw.rounded_rectangle([270, y + 4, 276, y + 16], radius=2, fill=col)
        draw.text((290, y), label, fill=(156, 163, 175, 255), font=font_sub)
        draw.text((290, y + 18), val, fill=(255, 255, 255, 255), font=font_bold)

    # 4. Draw Radar Chart on the right
    # Normalize values for the radar chart
    rp = float(user.get("skill_points") or 0.0)
    spin_sp = float(user.get("spin_skill_points") or 0.0)
    plays = float(user.get("play_count") or 0.0)
    g_rank = float(user.get("position") or 10000.0)
    c_rank = float(user.get("country_position") or 1000.0)
    
    norm_rp = min(1.0, rp / 8000.0)
    norm_spin = min(1.0, spin_sp / 8000.0)
    norm_plays = min(1.0, plays / 1700.0)
    norm_g_rank = max(0.05, min(1.0, 1.0 - (math.log10(max(1.0, g_rank)) / 4.0) * 0.8))
    norm_c_rank = max(0.05, min(1.0, 1.0 - (math.log10(max(1.0, c_rank)) / 3.0) * 0.8))
    
    radar_values = [norm_rp, norm_spin, norm_plays, norm_g_rank, norm_c_rank]
    radar_labels = ["RP", "Spin", "Plays", "Global", "Country"]
    
    draw_radar_chart(card, cx=660, cy=200, max_r=100, values=radar_values, labels=radar_labels)

    # Outer decorative glow border for the entire card (Violet & Blue Style)
    draw.rounded_rectangle([4, 4, width - 5, height - 5], radius=18, outline=(139, 92, 246, 90), width=2)
    draw.rounded_rectangle([3, 3, width - 4, height - 4], radius=18, outline=(59, 130, 246, 50), width=1)

    # Return stream
    output = io.BytesIO()
    card.save(output, format="PNG")
    output.seek(0)
    return output


def draw_compare_radar_chart(
    card: Image.Image,
    cx: float, 
    cy: float, 
    max_r: float, 
    p1_values: list[float], 
    p2_values: list[float], 
    labels: list[str]
) -> None:
    """Draws a comparative hexagonal radar chart showing two polygons overlaid."""
    num_axes = len(labels)
    angle_step = 2 * math.pi / num_axes
    font = load_font(12)
    draw = ImageDraw.Draw(card)

    # 1. Draw web circles (concentric rings)
    for r_factor in [0.25, 0.5, 0.75, 1.0]:
        r = max_r * r_factor
        points = []
        for i in range(num_axes):
            angle = i * angle_step - math.pi / 2
            x = cx + r * math.cos(angle)
            y = cy + r * math.sin(angle)
            points.append((x, y))
        draw.polygon(points, outline=(255, 255, 255, 30), fill=None)

    # 2. Draw axis lines
    for i in range(num_axes):
        angle = i * angle_step - math.pi / 2
        x_outer = cx + max_r * math.cos(angle)
        y_outer = cy + max_r * math.sin(angle)
        draw.line([(cx, cy), (x_outer, y_outer)], fill=(255, 255, 255, 30), width=1)

    # 3. Calculate points
    p1_points = []
    for i, val in enumerate(p1_values):
        val_clamped = max(0.05, min(1.0, val))
        r = max_r * val_clamped
        angle = i * angle_step - math.pi / 2
        x = cx + r * math.cos(angle)
        y = cy + r * math.sin(angle)
        p1_points.append((x, y))

    p2_points = []
    for i, val in enumerate(p2_values):
        val_clamped = max(0.05, min(1.0, val))
        r = max_r * val_clamped
        angle = i * angle_step - math.pi / 2
        x = cx + r * math.cos(angle)
        y = cy + r * math.sin(angle)
        p2_points.append((x, y))

    # 4. Draw transparent overlaid polygons on separate overlay layers to get true blending
    if len(p1_points) >= 3:
        overlay1 = Image.new("RGBA", card.size, (0, 0, 0, 0))
        overlay_draw1 = ImageDraw.Draw(overlay1)
        overlay_draw1.polygon(p1_points, fill=(139, 92, 246, 75), outline=(139, 92, 246, 200))
        card.alpha_composite(overlay1)
        
    if len(p2_points) >= 3:
        overlay2 = Image.new("RGBA", card.size, (0, 0, 0, 0))
        overlay_draw2 = ImageDraw.Draw(overlay2)
        overlay_draw2.polygon(p2_points, fill=(59, 130, 246, 75), outline=(59, 130, 246, 200))
        card.alpha_composite(overlay2)

    # Draw highlights (dots) on top
    if len(p1_points) >= 3:
        for pt in p1_points:
            draw.ellipse([pt[0] - 3, pt[1] - 3, pt[0] + 3, pt[1] + 3], fill=(255, 255, 255, 255), outline=(139, 92, 246, 255), width=1)
    if len(p2_points) >= 3:
        for pt in p2_points:
            draw.ellipse([pt[0] - 3, pt[1] - 3, pt[0] + 3, pt[1] + 3], fill=(255, 255, 255, 255), outline=(59, 130, 246, 255), width=1)

    # 5. Draw labels
    for i, label in enumerate(labels):
        angle = i * angle_step - math.pi / 2
        x_lbl = cx + (max_r + 20) * math.cos(angle)
        y_lbl = cy + (max_r + 12) * math.sin(angle)
        try:
            bbox = draw.textbbox((0, 0), label, font=font)
            lbl_w = bbox[2] - bbox[0]
            lbl_h = bbox[3] - bbox[1]
        except Exception:
            lbl_w, lbl_h = 40, 10
        draw.text((x_lbl - lbl_w / 2, y_lbl - lbl_h / 2), label, fill=(243, 244, 246, 255), font=font)


def generate_compare_card(
    p1_data: dict[str, Any], 
    p2_data: dict[str, Any], 
    p1_avatar: bytes | None = None, 
    p2_avatar: bytes | None = None,
    p1_flag: bytes | None = None,
    p2_flag: bytes | None = None
) -> io.BytesIO:
    """Generates a premium 2-player graphical comparison card."""
    width, height = 900, 400
    card = draw_gradient_back(width, height)
    
    # Glow layer
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    
    # Glow under player avatars (P1: Violet, P2: Blue)
    glow_draw.ellipse([80 - 20, 50 - 20, 80 + 100 + 20, 50 + 100 + 20], fill=(139, 92, 246, 50))
    glow_draw.ellipse([720 - 20, 50 - 20, 720 + 100 + 20, 50 + 100 + 20], fill=(59, 130, 246, 50))
    
    glow = glow.filter(ImageFilter.GaussianBlur(15))
    card.alpha_composite(glow)

    draw = ImageDraw.Draw(card)
    
    u1 = p1_data.get("user") or {}
    u2 = p2_data.get("user") or {}
    
    # Draw stats summary containers on left & right
    # Left container (P1)
    draw.rounded_rectangle([30, 170, 230, 370], radius=10, fill=(15, 23, 42, 180), outline=(139, 92, 246, 50), width=1)
    # Right container (P2)
    draw.rounded_rectangle([670, 170, 870, 370], radius=10, fill=(15, 23, 42, 180), outline=(59, 130, 246, 50), width=1)

    # Fonts
    font_title = load_font(20)
    font_sub = load_font(12)
    font_bold = load_font(14)
    font_stat = load_font(15)

    # Render circular avatars (Size 100x100)
    def make_circular_avatar(avatar_bytes: bytes | None, border_color: tuple[int, int, int, int]) -> Image.Image:
        sz = 100
        if avatar_bytes:
            try:
                img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((sz, sz), Image.Resampling.LANCZOS)
            except Exception:
                img = Image.new("RGBA", (sz, sz), border_color)
        else:
            img = Image.new("RGBA", (sz, sz), border_color)
        mask = Image.new("L", (sz, sz), 0)
        md = ImageDraw.Draw(mask)
        md.ellipse([0, 0, sz, sz], fill=255)
        circular = Image.new("RGBA", (sz, sz))
        circular.paste(img, (0, 0), mask)
        return circular

    av1 = make_circular_avatar(p1_avatar, (139, 92, 246, 255))
    av2 = make_circular_avatar(p2_avatar, (59, 130, 246, 255))
    
    card.paste(av1, (80, 25), av1)
    card.paste(av2, (720, 25), av2)
    
    # Avatar borders
    draw.ellipse([78, 23, 80 + 100 + 2, 25 + 100 + 2], outline=(139, 92, 246, 255), width=3)
    draw.ellipse([718, 23, 720 + 100 + 2, 25 + 100 + 2], outline=(59, 130, 246, 255), width=3)

    # Render names and flags
    c1 = (u1.get("flag") or "US").upper()
    c2 = (u2.get("flag") or "US").upper()
    
    # P1 Name
    p1_name = u1.get("username", "P1")
    if len(p1_name) > 16:
        p1_name = p1_name[:16]
    p1_font = load_font(15) if len(p1_name) > 12 else font_title
    draw.text((30, 135), p1_name, fill=(139, 92, 246, 255), font=p1_font)
    if p1_flag:
        try:
            flg = Image.open(io.BytesIO(p1_flag)).convert("RGBA").resize((22, 14), Image.Resampling.LANCZOS)
            card.paste(flg, (190, 140), flg)
        except Exception:
            draw.text((190, 138), c1, fill=(156, 163, 175, 255), font=font_sub)
    else:
        draw.text((190, 138), c1, fill=(156, 163, 175, 255), font=font_sub)

    # P2 Name
    p2_name = u2.get("username", "P2")
    if len(p2_name) > 16:
        p2_name = p2_name[:16]
    p2_font = load_font(15) if len(p2_name) > 12 else font_title
    draw.text((670, 135), p2_name, fill=(59, 130, 246, 255), font=p2_font)
    if p2_flag:
        try:
            flg = Image.open(io.BytesIO(p2_flag)).convert("RGBA").resize((22, 14), Image.Resampling.LANCZOS)
            card.paste(flg, (830, 140), flg)
        except Exception:
            draw.text((830, 138), c2, fill=(156, 163, 175, 255), font=font_sub)
    else:
        draw.text((830, 138), c2, fill=(156, 163, 175, 255), font=font_sub)

    # Write stats inside left/right boxes with beautiful key-value layout
    labels_list = ["Skill Points", "Spin Points", "Play Count", "Global Rank", "Country Rank"]
    
    p1_vals = [
        f"{u1.get('skill_points', 0.0):,.2f} RP",
        f"{u1.get('spin_skill_points', 0.0):,.2f} SP",
        f"{u1.get('play_count', 0):,}",
        f"#{u1.get('position', 0):,}" if u1.get('position') else "—",
        f"#{u1.get('country_position', 0):,}" if u1.get('country_position') else "—"
    ]
    
    p2_vals = [
        f"{u2.get('skill_points', 0.0):,.2f} RP",
        f"{u2.get('spin_skill_points', 0.0):,.2f} SP",
        f"{u2.get('play_count', 0):,}",
        f"#{u2.get('position', 0):,}" if u2.get('position') else "—",
        f"#{u2.get('country_position', 0):,}" if u2.get('country_position') else "—"
    ]
    
    # Render stats
    for idx, label in enumerate(labels_list):
        y = 185 + idx * 36
        
        # Player 1 (Left Box)
        draw.text((42, y + 2), label, fill=(156, 163, 175, 255), font=font_sub)
        val1 = p1_vals[idx]
        try:
            bbox = draw.textbbox((0, 0), val1, font=font_stat)
            w1 = bbox[2] - bbox[0]
        except Exception:
            w1 = len(val1) * 8
        draw.text((218 - w1, y), val1, fill=(255, 255, 255, 255), font=font_stat)
        
        # Player 2 (Right Box)
        draw.text((682, y + 2), label, fill=(156, 163, 175, 255), font=font_sub)
        val2 = p2_vals[idx]
        try:
            bbox = draw.textbbox((0, 0), val2, font=font_stat)
            w2 = bbox[2] - bbox[0]
        except Exception:
            w2 = len(val2) * 8
        draw.text((858 - w2, y), val2, fill=(255, 255, 255, 255), font=font_stat)

    # Normalize values for comparative hexagonal radar chart
    # P1
    rp1 = float(u1.get("skill_points") or 0.0)
    spin1 = float(u1.get("spin_skill_points") or 0.0)
    plays1 = float(u1.get("play_count") or 0.0)
    hits1 = float(u1.get("squares_hit") or 0.0)
    g_rank1 = float(u1.get("position") or 10000.0)
    c_rank1 = float(u1.get("country_position") or 1000.0)
    
    # P2
    rp2 = float(u2.get("skill_points") or 0.0)
    spin2 = float(u2.get("spin_skill_points") or 0.0)
    plays2 = float(u2.get("play_count") or 0.0)
    hits2 = float(u2.get("squares_hit") or 0.0)
    g_rank2 = float(u2.get("position") or 10000.0)
    c_rank2 = float(u2.get("country_position") or 1000.0)
    
    p1_vals_norm = [
        min(1.0, rp1 / 8000.0),
        min(1.0, spin1 / 8000.0),
        min(1.0, plays1 / 1700.0),
        min(1.0, hits1 / 3000000.0),
        max(0.05, min(1.0, 1.0 - (math.log10(max(1.0, g_rank1)) / 4.0) * 0.8)),
        max(0.05, min(1.0, 1.0 - (math.log10(max(1.0, c_rank1)) / 3.0) * 0.8))
    ]
    
    p2_vals_norm = [
        min(1.0, rp2 / 8000.0),
        min(1.0, spin2 / 8000.0),
        min(1.0, plays2 / 1700.0),
        min(1.0, hits2 / 3000000.0),
        max(0.05, min(1.0, 1.0 - (math.log10(max(1.0, g_rank2)) / 4.0) * 0.8)),
        max(0.05, min(1.0, 1.0 - (math.log10(max(1.0, c_rank2)) / 3.0) * 0.8))
    ]
    
    labels = ["RP", "Spin", "Plays", "Hits", "Global", "Country"]
    draw_compare_radar_chart(
        card, 
        cx=450, 
        cy=220, 
        max_r=110, 
        p1_values=p1_vals_norm, 
        p2_values=p2_vals_norm, 
        labels=labels
    )

    # Outer decorative glow borders
    draw.rounded_rectangle([4, 4, width - 5, height - 5], radius=18, outline=(139, 92, 246, 90), width=2)
    draw.rounded_rectangle([3, 3, width - 4, height - 4], radius=18, outline=(59, 130, 246, 50), width=1)

    output = io.BytesIO()
    card.save(output, format="PNG")
    output.seek(0)
    return output
