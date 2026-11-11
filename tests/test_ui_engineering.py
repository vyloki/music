"""
Unit tests for UI Engineering, Design Tokens, Responsive Breakpoints,
and Safe Area Layout Integrity.
"""

import unittest
import re
from pathlib import Path

class TestUIEngineering(unittest.TestCase):
    def setUp(self):
        self.root_dir = Path(__file__).resolve().parent.parent
        self.index_css = (self.root_dir / "frontend" / "css" / "index.css").read_text(encoding="utf-8")
        self.player_css = (self.root_dir / "frontend" / "css" / "player.css").read_text(encoding="utf-8")
        self.index_html = (self.root_dir / "frontend" / "index.html").read_text(encoding="utf-8")
        self.manifest_json = (self.root_dir / "frontend" / "manifest.json").read_text(encoding="utf-8")

    def test_design_tokens_palette(self):
        """Verify the Obsidian Dark palette is applied in CSS custom properties."""
        self.assertIn("--bg-primary: #08090d;", self.index_css)
        self.assertIn("--bg-secondary: #0e1017;", self.index_css)
        self.assertIn("--bg-tertiary: #141724;", self.index_css)
        self.assertIn("--bg-elevated: #181b28;", self.index_css)
        self.assertIn("--text-primary: #f8fafc;", self.index_css)
        self.assertIn("--text-secondary: #94a3b8;", self.index_css)
        self.assertIn("--accent-primary: #6366f1;", self.index_css)

    def test_no_warm_sand_artifacts(self):
        """Verify old washed-out warm sand tokens are completely absent from index.css."""
        self.assertNotIn("#faf7f2", self.index_css)
        self.assertNotIn("#f5f0e8", self.index_css)
        self.assertNotIn("#ede6d8", self.index_css)
        self.assertNotIn("#2c2418", self.index_css)
        self.assertNotIn("#c4a882", self.index_css)

    def test_theme_color_in_meta_and_manifest(self):
        """Verify theme color matches the deep dark theme in index.html and manifest.json."""
        self.assertIn('<meta name="theme-color" content="#08090d">', self.index_html)
        self.assertIn('"background_color": "#08090d"', self.manifest_json)
        self.assertIn('"theme_color": "#08090d"', self.manifest_json)

    def test_safe_area_variables(self):
        """Verify iOS / Android safe-area-inset environment variables are declared."""
        self.assertIn("env(safe-area-inset-top", self.index_css)
        self.assertIn("env(safe-area-inset-bottom", self.index_css)
        self.assertIn("--safe-bottom", self.index_css)

    def test_responsive_breakpoints(self):
        """Verify responsive breakpoints exist for mobile, small mobile, tablet, laptop, and TV/4K."""
        self.assertIn("@media (max-width: 768px)", self.index_css)
        self.assertIn("@media (max-width: 380px)", self.index_css)
        self.assertIn("@media (min-width: 769px) and (max-width: 1024px)", self.index_css)
        self.assertIn("@media (min-width: 1025px) and (max-width: 1599px)", self.index_css)
        self.assertIn("@media (min-width: 1600px)", self.index_css)

    def test_tv_and_ultrawide_constraints(self):
        """Verify TV and ultra-wide screens constrain max width and define focus visibility."""
        self.assertIn("max-width: 1720px;", self.index_css)
        self.assertIn(":focus-visible", self.index_css)
        self.assertIn("max-width: 1720px;", self.player_css)

    def test_badges_de_cluttered(self):
        """Verify badges are clean, understated metadata and not saturated pills."""
        # Check .badge styling
        badge_match = re.search(r'\.badge\s*\{([^}]+)\}', self.index_css)
        self.assertTrue(badge_match)
        badge_block = badge_match.group(1)
        self.assertIn("text-transform: uppercase", badge_block)
        self.assertIn("color: var(--text-tertiary)", badge_block)
        self.assertIn("background: transparent", badge_block)

    def test_tablet_player_time_display_visible(self):
        """Verify time display is kept visible on tablet/laptop screens."""
        start = self.player_css.find("@media (max-width: 1150px) and (min-width: 769px)")
        self.assertNotEqual(start, -1)
        end = self.player_css.find("@media (max-width: 768px)", start)
        block_text = self.player_css[start:end]
        self.assertNotIn("display: none;", block_text)
        self.assertIn("display: inline-flex;", block_text)

if __name__ == '__main__':
    unittest.main()
