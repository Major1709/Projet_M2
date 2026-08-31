"""Reduce source markup to the text a human would actually have seen.

Runs before the confinement envelope, and the order matters: this module decodes
entities, so it can produce text that looks like a control token or like our own
delimiters. ``untrusted.wrap`` neutralises those afterwards, and nothing re-parses
the result. Reversing the two would let ``&lt;|im_start|&gt;`` survive as a live
marker.

The reason this is a security control and not a tidying pass is counter-intuitive:
**stripping tags naively makes hidden text visible.** An HTML comment, a ``script``
body, a ``style`` block -- none of them are rendered, so none of them are seen by
whoever reviews the page, which is precisely why an attacker puts instructions
there. Unwrapping the markup would promote that text into the transcript with
everything else. So invisible elements are dropped *with their contents*, and only
what a reader would have seen survives. Attribute values go the same way: ``alt``
and ``title`` text is a place to hide a sentence, and we render nothing, so we need
none of it.

Applied only where markup exists. A Jira description that says ``List<String>``
is prose, and a parser let loose on it would silently eat the type parameter; the
gate below asks for a recognised tag before touching anything. On a page that is
genuinely HTML *and* mentions ``List<String>``, the type parameter is lost -- the
right trade, since that page's markup is the larger risk.

Markdown passes through as text, deliberately. Its constructs are not a boundary
anything is enforced at: link URLs are noise we do not render, and collapsing them
would cost real content -- a page citing another page -- while removing no
capability. The defence against what a link *says* is the envelope, not a rewrite.
"""

import re
from html.parser import HTMLParser

# Elements whose content a reader never sees. Dropped whole, contents included.
# ``ac:parameter`` and its siblings are Confluence storage-format macro plumbing,
# which is markup the editor writes rather than anything the author typed.
_INVISIBLE = frozenset(
    {
        "script",
        "style",
        "head",
        "noscript",
        "template",
        "ac:parameter",
        "ac:plain-text-body",
        "ri:attachment",
        "ri:page",
    }
)

# Elements that separate blocks of text. Without them a stripped document runs
# every paragraph into one line, and the model reads two unrelated sentences as
# one claim.
_BLOCK = frozenset(
    {
        "p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5",
        "h6", "blockquote", "pre", "section", "article", "table", "ul", "ol",
    }
)

# The gate. A recognised opening or closing tag, a Confluence namespaced element,
# or a comment -- anything less is prose that happens to contain an angle bracket.
_LOOKS_LIKE_MARKUP = re.compile(
    r"</?(?:[a-z]+:[a-z-]+|p|div|span|a|br|li|ul|ol|table|tr|td|th|h[1-6]"
    r"|script|style|img|pre|code|blockquote|strong|em|b|i)\b|<!--",
    re.IGNORECASE,
)

_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING_SPACE = re.compile(r"[ \t]+\n")


class _Reducer(HTMLParser):
    def __init__(self) -> None:
        # Entities are decoded into data by the parser, so a decoded "<script>"
        # arrives as text and is never re-read as a tag.
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        # Counts nested invisible elements. A flag would be reopened to visible by
        # the first closing tag, which a nested one would trigger early.
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        del attrs  # Never kept: attribute text is unrendered, so it is a hiding place.
        if tag in _INVISIBLE:
            self._hidden += 1
            return
        if tag in _BLOCK and not self._hidden:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _INVISIBLE:
            self._hidden = max(0, self._hidden - 1)
            return
        if tag in _BLOCK and not self._hidden:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self._parts.append(data)

    def handle_comment(self, data: str) -> None:
        # Dropped, never appended. This is the case the module exists for: a
        # comment is invisible to every human who reviews the page.
        del data

    def text(self) -> str:
        joined = "".join(self._parts)
        joined = _TRAILING_SPACE.sub("\n", joined)
        return _BLANK_LINES.sub("\n\n", joined).strip()


def looks_like_markup(text: str) -> bool:
    return bool(_LOOKS_LIKE_MARKUP.search(text))


def reduce_markup(text: str) -> str:
    """Return what a reader would have seen, or the text unchanged if it is prose."""

    if not looks_like_markup(text):
        return text
    reducer = _Reducer()
    try:
        reducer.feed(text)
        reducer.close()
    except Exception:
        # Malformed markup is the normal case, not the exception, and the parser is
        # lenient about it. If it fails anyway the original text is still safe to
        # show -- it goes on to be fenced and neutralised either way -- so failing
        # closed here would only lose a reader their page.
        return text
    return reducer.text()


__all__ = ["looks_like_markup", "reduce_markup"]
