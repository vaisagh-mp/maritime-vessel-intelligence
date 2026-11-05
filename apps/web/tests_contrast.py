"""
apps/web/tests_contrast.py
WCAG 2.1 AA color contrast compliance tests for design tokens in tokens.css.
Computes relative luminance and contrast ratios across Light and Dark themes.
"""

import os
import re
from pathlib import Path
from django.conf import settings
from django.test import SimpleTestCase


def parse_hex_color(hex_str: str):
    """Parse a 3 or 6 digit hex string to (r, g, b) in [0.0, 1.0]."""
    hex_str = hex_str.strip().lstrip("#")
    if len(hex_str) == 3:
        hex_str = "".join([c * 2 for c in hex_str])
    r = int(hex_str[0:2], 16) / 255.0
    g = int(hex_str[2:4], 16) / 255.0
    b = int(hex_str[4:6], 16) / 255.0
    return r, g, b


def relative_luminance(rgb):
    """Calculate WCAG 2.1 relative luminance for an sRGB tuple."""
    def channel_lum(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = [channel_lum(c) for c in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(color1: str, color2: str) -> float:
    """Calculate WCAG 2.1 contrast ratio between two hex colors: (L1 + 0.05) / (L2 + 0.05)."""
    lum1 = relative_luminance(parse_hex_color(color1))
    lum2 = relative_luminance(parse_hex_color(color2))
    l_max = max(lum1, lum2)
    l_min = min(lum1, lum2)
    return (l_max + 0.05) / (l_min + 0.05)


def parse_css_vars(block: str) -> dict:
    """Extract CSS custom properties (--var: value;) from a CSS rule block."""
    vars_dict = {}
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("--") and ":" in line:
            parts = line.split(":", 1)
            k = parts[0].strip()
            v = parts[1].split(";")[0].strip()
            vars_dict[k] = v
    return vars_dict


def resolve_var(v: str, theme_vars: dict) -> str:
    """Recursively resolve var(--name) references."""
    while v.startswith("var("):
        inner = v[4:-1].strip()
        v = theme_vars.get(inner, v)
    return v


class TestTokenContrast(SimpleTestCase):
    """Test WCAG AA contrast compliance of design tokens in tokens.css."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        tokens_path = os.path.join(settings.BASE_DIR, "apps", "web", "static", "web", "css", "tokens.css")
        with open(tokens_path, "r", encoding="utf-8") as f:
            content = f.read()

        root_match = re.search(r":root\s*\{([^}]+)\}", content)
        dark_match = re.search(r"@media\s*\(prefers-color-scheme:\s*dark\)\s*\{\s*:root\s*\{([^}]+)\}", content)

        assert root_match, "Could not find :root block in tokens.css"
        assert dark_match, "Could not find dark prefers-color-scheme block in tokens.css"

        cls.light_vars = parse_css_vars(root_match.group(1))
        cls.dark_vars = {**cls.light_vars, **parse_css_vars(dark_match.group(1))}

    def _check_pair(self, theme_vars, c1_name, c2_name, min_ratio, label, theme_name):
        c1 = resolve_var(theme_vars[c1_name], theme_vars)
        c2 = resolve_var(theme_vars[c2_name], theme_vars)
        self.assertTrue(c1.startswith("#"), f"{c1_name} must resolve to a hex color in {theme_name}")
        self.assertTrue(c2.startswith("#"), f"{c2_name} must resolve to a hex color in {theme_name}")

        ratio = contrast_ratio(c1, c2)
        self.assertGreaterEqual(
            ratio,
            min_ratio,
            f"[{theme_name}] {label} ({c1_name} on {c2_name}: {c1} on {c2}) "
            f"contrast ratio {ratio:.2f}:1 is below required {min_ratio}:1",
        )

    def test_contrast_pairs_light_theme(self):
        """Check all required token pairs in Light Theme."""
        v = self.light_vars
        # 1. body text on background (>= 4.5:1)
        self._check_pair(v, "--color-text", "--color-bg", 4.5, "body text on background", "LIGHT")
        # 2. body text on surface (>= 4.5:1)
        self._check_pair(v, "--color-text", "--color-surface", 4.5, "body text on surface", "LIGHT")
        # 3. muted text on surface (>= 4.5:1)
        self._check_pair(v, "--color-text-muted", "--color-surface", 4.5, "muted text on surface", "LIGHT")
        # 4. primary button text on primary button fill (>= 4.5:1)
        self._check_pair(v, "--color-btn-primary-text", "--color-accent", 4.5, "primary button text on fill", "LIGHT")
        # 5. link colour on surface (>= 4.5:1)
        self._check_pair(v, "--color-accent", "--color-surface", 4.5, "link colour on surface", "LIGHT")
        # 6. error text on surface (>= 4.5:1)
        self._check_pair(v, "--color-danger", "--color-surface", 4.5, "error text on surface", "LIGHT")
        # 7. four band badge text colours on badge fills (>= 4.5:1)
        self._check_pair(v, "--band-hot-text", "--band-hot-bg", 4.5, "HOT badge text on fill", "LIGHT")
        self._check_pair(v, "--band-high-text", "--band-high-bg", 4.5, "HIGH badge text on fill", "LIGHT")
        self._check_pair(v, "--band-medium-text", "--band-medium-bg", 4.5, "MEDIUM badge text on fill", "LIGHT")
        self._check_pair(v, "--band-low-text", "--band-low-bg", 4.5, "LOW badge text on fill", "LIGHT")
        # 8. borders against surface (>= 3.0:1)
        self._check_pair(v, "--color-border", "--color-surface", 3.0, "border against surface", "LIGHT")
        # 9. focus ring against surface (>= 3.0:1)
        self._check_pair(v, "--color-focus-outline", "--color-surface", 3.0, "focus ring against surface", "LIGHT")

    def test_contrast_pairs_dark_theme(self):
        """Check all required token pairs in Dark Theme."""
        v = self.dark_vars
        # 1. body text on background (>= 4.5:1)
        self._check_pair(v, "--color-text", "--color-bg", 4.5, "body text on background", "DARK")
        # 2. body text on surface (>= 4.5:1)
        self._check_pair(v, "--color-text", "--color-surface", 4.5, "body text on surface", "DARK")
        # 3. muted text on surface (>= 4.5:1)
        self._check_pair(v, "--color-text-muted", "--color-surface", 4.5, "muted text on surface", "DARK")
        # 4. primary button text on primary button fill (>= 4.5:1)
        self._check_pair(v, "--color-btn-primary-text", "--color-accent", 4.5, "primary button text on fill", "DARK")
        # 5. link colour on surface (>= 4.5:1)
        self._check_pair(v, "--color-accent", "--color-surface", 4.5, "link colour on surface", "DARK")
        # 6. error text on surface (>= 4.5:1)
        self._check_pair(v, "--color-danger", "--color-surface", 4.5, "error text on surface", "DARK")
        # 7. four band badge text colours on badge fills (>= 4.5:1)
        self._check_pair(v, "--band-hot-text", "--band-hot-bg", 4.5, "HOT badge text on fill", "DARK")
        self._check_pair(v, "--band-high-text", "--band-high-bg", 4.5, "HIGH badge text on fill", "DARK")
        self._check_pair(v, "--band-medium-text", "--band-medium-bg", 4.5, "MEDIUM badge text on fill", "DARK")
        self._check_pair(v, "--band-low-text", "--band-low-bg", 4.5, "LOW badge text on fill", "DARK")
        # 8. borders against surface (>= 3.0:1)
        self._check_pair(v, "--color-border", "--color-surface", 3.0, "border against surface", "DARK")
        # 9. focus ring against surface (>= 3.0:1)
        self._check_pair(v, "--color-focus-outline", "--color-surface", 3.0, "focus ring against surface", "DARK")

