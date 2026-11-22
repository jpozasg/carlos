"""The HTML pages the app serves itself: the app shell and sign-in (with the source-code link, AGPL-3.0 section 13),
/privacy and /impressum. The imprint text is the operator's file DATA_DIR/impressum.txt, never part of the repository."""
import html
from . import config

IMPRINT_MAX_BYTES = 20_000  # shortcut: a plain-text imprint; a longer file is cut here, the page says nothing more


def page(name):
    """A page of static/ with its source-code link filled in ({{SOURCE_URL}} is the only placeholder in the templates)."""
    return (config.STATIC / name).read_bytes().replace(b'{{SOURCE_URL}}', html.escape(config.SOURCE_URL, quote=True).encode())


def imprint():
    """/impressum: the operator's text, escaped, or a placeholder the page translates (id imp-missing)."""
    f = config.DATA_DIR / 'impressum.txt'
    text = f.read_bytes()[:IMPRINT_MAX_BYTES].decode('utf-8', errors='replace').strip() if f.is_file() else ''
    body = f'<pre class="imprint">{html.escape(text)}</pre>' if text else \
        '<p class="imprint-missing" id="imp-missing">No imprint text is set for this instance yet.</p>'
    return page('impressum.html').replace(b'{{IMPRINT}}', body.encode())
