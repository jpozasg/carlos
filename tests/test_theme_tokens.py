"""static/css/tokens.css: Auto mode (no data-mode) must carry the same light tokens as data-mode=light, and the token pairs
must meet WCAG 2.x AA (text 4.5:1; borders of controls, focus ring and chart marks 3:1) in light and dark. Standard library only."""
import re, unittest
from pathlib import Path

CSS = (Path(__file__).resolve().parent.parent / 'static' / 'css' / 'tokens.css').read_text(encoding='utf8')


def block(selector):
    m = re.search(re.escape(selector) + r'\s*\{(.*?)\n\s*\}', CSS, re.S)
    assert m, selector
    return dict(re.findall(r'(--[\w-]+):([^;}]+);?', re.sub(r'/\*.*?\*/', '', m.group(1), flags=re.S)))


DARK_SEL = ':root[data-theme="cluster"]'
LIGHT = block(':root[data-theme="cluster"][data-mode="light"]')
AUTO = block('@media (prefers-color-scheme:light){\n:root[data-theme="cluster"]:not([data-mode])')
DARK = {**block(':root'), **block(DARK_SEL)}


def lum(h):
    if len(h) == 4:
        h = '#' + ''.join(ch * 2 for ch in h[1:])
    c =[int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def ratio(a, b):
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class ThemeTokens(unittest.TestCase):
    def test_auto_block_equals_light_block(self):
        self.assertEqual(AUTO, LIGHT)

    def test_contrast_aa(self):
        for name, T in (('light', LIGHT), ('dark', DARK)):
            surfaces = [T['--bg'], T['--surface'], T['--surface-2']]
            for fg in ('--text', '--text-2', '--text-3'):
                for s in surfaces:
                    self.assertGreaterEqual(ratio(T[fg], s), 4.5, f'{name} {fg} on {s}')
            for fg, bg in (('--accent-contrast', '--accent'), ('--bad-contrast', '--bad'), ('--accent-ink', '--accent-soft'),
                           ('--good-ink', '--good-soft'), ('--warn-ink', '--warn-soft'), ('--bad-ink', '--bad-soft')):
                self.assertGreaterEqual(ratio(T[fg], T[bg]), 4.5, f'{name} {fg} on {bg}')
            for fg in ('--field-border', '--accent'):  # control borders (WCAG 1.4.11) and the focus ring
                for s in surfaces:
                    self.assertGreaterEqual(ratio(T[fg], s), 3.0, f'{name} {fg} on {s}')
            for i in range(1, 10):  # chart marks sit on cards (--surface)
                self.assertGreaterEqual(ratio(T[f'--s{i}'], T['--surface']), 3.0, f'{name} --s{i}')


if __name__ == '__main__':
    unittest.main()
