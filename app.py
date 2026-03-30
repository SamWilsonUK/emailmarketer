import os
import re
import json
import colorsys
from urllib.parse import urljoin, urlparse
from collections import Counter

import anthropic
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ---------------------------------------------------------------------------
# Colour extraction
# ---------------------------------------------------------------------------

HEX_RE = re.compile(r"#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b")
RGB_RE = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})")

# Very common "non-brand" colours we want to filter out
GENERIC_COLORS = {
    "#ffffff", "#000000", "#fffffe", "#fefefe", "#fdfdfd",
    "#111111", "#222222", "#333333", "#444444", "#555555",
    "#666666", "#777777", "#888888", "#999999", "#aaaaaa",
    "#bbbbbb", "#cccccc", "#dddddd", "#eeeeee", "#f0f0f0",
    "#f5f5f5", "#f8f8f8", "#fafafa", "#e0e0e0", "#d9d9d9",
    "#transparent",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def is_near_grey(hex_color: str, threshold: float = 0.08) -> bool:
    try:
        r, g, b = hex_to_rgb(hex_color)
        _, s, _ = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        return s < threshold
    except Exception:
        return True


def normalise_hex(hex_color: str) -> str:
    h = hex_color.lower().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return f"#{h}"


def extract_colors_from_css_text(css_text: str) -> list[str]:
    colors: list[str] = []
    for m in HEX_RE.finditer(css_text):
        colors.append(normalise_hex(m.group()))
    for m in RGB_RE.finditer(css_text):
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        colors.append(rgb_to_hex(r, g, b))
    return colors


def fetch_brand_colors(url: str, max_colors: int = 6) -> dict:
    """
    Fetch a webpage and its linked stylesheets, extract the most-used
    non-generic, non-grey hex colours, and return them as a dict with
    semantic labels (primary, secondary, accent …).
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except Exception as exc:
        return {"error": str(exc), "colors": []}

    soup = BeautifulSoup(resp.text, "html.parser")
    all_colors: list[str] = []

    # 1. Inline <style> blocks
    for tag in soup.find_all("style"):
        all_colors.extend(extract_colors_from_css_text(tag.get_text()))

    # 2. Inline style attributes
    for tag in soup.find_all(style=True):
        all_colors.extend(extract_colors_from_css_text(tag["style"]))

    # 3. External stylesheets (first 3 to avoid slow scrapes)
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    css_links = [
        tag.get("href")
        for tag in soup.find_all("link", rel=lambda r: r and "stylesheet" in r)
        if tag.get("href")
    ]
    for href in css_links[:3]:
        css_url = href if href.startswith("http") else urljoin(base, href)
        try:
            cr = requests.get(css_url, headers=HEADERS, timeout=8)
            all_colors.extend(extract_colors_from_css_text(cr.text))
        except Exception:
            pass

    # 4. Meta theme-color
    theme = soup.find("meta", attrs={"name": "theme-color"})
    if theme and theme.get("content", "").startswith("#"):
        all_colors.insert(0, normalise_hex(theme["content"]))

    # Filter and rank
    filtered = [
        c for c in all_colors
        if c not in GENERIC_COLORS and not is_near_grey(c)
    ]
    ranked = Counter(filtered).most_common(max_colors * 3)
    top = []
    for color, _ in ranked:
        if color not in top:
            top.append(color)
        if len(top) >= max_colors:
            break

    labels = ["primary", "secondary", "accent", "highlight", "dark", "light"]
    named = {labels[i]: top[i] for i in range(min(len(top), len(labels)))}

    return {"colors": top, "named": named, "error": None}


# ---------------------------------------------------------------------------
# Email generation via Claude
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert HTML email designer.
You create beautiful, responsive, production-ready HTML email templates.

Rules:
- Use inline CSS only (email clients strip <style> blocks)
- Keep the email width max 600px centred in a full-width wrapper
- Use web-safe fonts with sensible fallbacks; Google Fonts are fine via <link>
- Include a plain-text visible pre-header (hidden preview text)
- Structure: header/logo area, hero, body sections, CTA button, footer
- The CTA button must be a bulletproof VML button for Outlook compatibility
- Output ONLY the complete HTML document, no markdown fences, no commentary
"""

def generate_email(brief: str, brand_colors: dict, brand_url: str = "") -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    color_context = ""
    if brand_colors.get("named"):
        color_context = "Brand colours to use:\n" + "\n".join(
            f"  {k}: {v}" for k, v in brand_colors["named"].items()
        )
    elif brand_colors.get("colors"):
        color_context = "Brand colours to use: " + ", ".join(brand_colors["colors"])

    user_message = f"""Marketing brief:
{brief}

{color_context}

{"Brand website: " + brand_url if brand_url else ""}

Design a complete, polished HTML email based on this brief using the brand colours.
Output only the full HTML document."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    html = message.content[0].text.strip()
    # Strip any accidental markdown code fences
    html = re.sub(r"^```[a-z]*\n?", "", html)
    html = re.sub(r"\n?```$", "", html)
    return html.strip()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/extract-colors", methods=["POST"])
def api_extract_colors():
    data = request.get_json(force=True)
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    if not url.startswith("http"):
        url = "https://" + url
    result = fetch_brand_colors(url)
    return jsonify(result)


@app.route("/api/generate", methods=["POST"])
def api_generate():
    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY environment variable not set"}), 500

    data = request.get_json(force=True)
    brief = data.get("brief", "").strip()
    brand_url = data.get("brand_url", "").strip()
    colors = data.get("colors", {})

    if not brief:
        return jsonify({"error": "Marketing brief is required"}), 400

    # If colors weren't pre-fetched but a URL was supplied, fetch now
    if not colors.get("colors") and brand_url:
        if not brand_url.startswith("http"):
            brand_url = "https://" + brand_url
        colors = fetch_brand_colors(brand_url)

    try:
        html = generate_email(brief, colors, brand_url)
        return jsonify({"html": html})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
