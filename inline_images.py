"""Images embedded in authored Markdown.

Content references an uploaded material of its own topic by filename:

    ![Kältepack](material:modul-03-kaeltepack.jpg)

Nothing here knows about Flask, sessions or the database. The caller passes a
`resolve(src, alt)` function that decides what an image becomes; this module
only finds the images and applies the decision. The importer uses
`material_refs()` from here too, so "what counts as a reference" is defined once.
"""
import re
from collections import namedtuple

from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

MATERIAL_PREFIX = 'material:'
IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# What an image turns into when it is not shown as an image: a line of text.
# css_class may be None (plain alt text for students).
Placeholder = namedtuple('Placeholder', 'text css_class')

_MATERIAL_REF_RE = re.compile(r'!\[[^\]]*\]\(\s*' + re.escape(MATERIAL_PREFIX) + r'([^)\s]+)')


def material_refs(text):
    """Filenames referenced as `![...](material:<name>)` in text, in order."""
    return _MATERIAL_REF_RE.findall(text or '')


def is_image_name(filename):
    return filename.rsplit('.', 1)[-1].lower() in IMAGE_EXTENSIONS if '.' in filename else False


def image_src_kind(src):
    """Classify an image src from authored content.

    Returns 'material' (a reference to be resolved against the topic's
    materials), 'local' (a path on our own origin, e.g. /static/...) or
    'blocked' (anything that would make the student's browser load from
    elsewhere, or that we do not understand).
    """
    src = (src or '').strip()
    if src.startswith(MATERIAL_PREFIX):  # case as in material_refs(), which the importer checks
        return 'material'
    # Browsers read "/\host" and "/<tab>/host" like "//host" (another server),
    # so a local path must be one slash followed by no backslash, whitespace
    # or control character anywhere.
    if (src.startswith('/') and not src.startswith('//')
            and not any(c == '\\' or c.isspace() or ord(c) < 32 for c in src)):
        return 'local'
    return 'blocked'


class _ImageTreeprocessor(Treeprocessor):
    def __init__(self, md, resolve):
        super().__init__(md)
        self.resolve = resolve

    def run(self, root):
        for img in root.iter('img'):
            result = self.resolve(img.get('src', ''), img.get('alt', ''))
            if isinstance(result, Placeholder):
                # Turn the <img> into a <span> in place: keeps its position and
                # the text that follows it (tail) without touching the parent.
                img.tag = 'span'
                img.attrib.clear()
                if result.css_class:
                    img.set('class', result.css_class)
                img.text = result.text
            else:
                img.set('src', result)
                img.set('loading', 'lazy')


class InlineImageExtension(Extension):
    def __init__(self, resolve, **kwargs):
        self.resolve = resolve
        super().__init__(**kwargs)

    def extendMarkdown(self, md):
        # Low priority: runs after inline patterns have produced the <img> elements.
        md.treeprocessors.register(_ImageTreeprocessor(md, self.resolve), 'inline_images', 0)
