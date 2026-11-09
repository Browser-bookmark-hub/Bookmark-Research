"""Read the canvas card's HTML export (Netscape bookmark format).

The canvas right-click export writes ``<!DOCTYPE NETSCAPE-Bookmark-file-1>`` with
``<DT><H3>`` folders and ``<DT><A HREF>`` bookmarks, so the same reader also
accepts a Chrome bookmark export.  Anything else falls back to plain ``<a href>``
links, mirroring the canvas app's own import.
"""
import json
from html.parser import HTMLParser

MAX_ITEMS = 20000


class _NetscapeParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = [[]]
        self.pending_folder = None
        self.mode = None
        self.buffer = []
        self.href = ""
        self.pending_title = ""
        self.count = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "dl":
            if self.pending_folder is not None:
                self.stack.append(self.pending_folder["children"])
                self.pending_folder = None
            else:
                self.stack.append(self.stack[-1])
        elif tag == "h3":
            self.mode, self.buffer = "h3", []
        elif tag == "a":
            self.mode, self.buffer = "a", []
            values = dict(attrs)
            self.href = (values.get("href") or "").strip()
        elif tag == "title" and not self.pending_title:
            self.mode, self.buffer = "title", []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "dl":
            if len(self.stack) > 1:
                self.stack.pop()
        elif tag == "h3" and self.mode == "h3":
            title = "".join(self.buffer).strip()
            folder = {"title": title or "Folder", "url": "", "type": "folder", "children": []}
            self.stack[-1].append(folder)
            self.pending_folder = folder
            self.mode, self.buffer = None, []
        elif tag == "a" and self.mode == "a":
            title = "".join(self.buffer).strip()
            if self.href:
                self.stack[-1].append({"title": title or self.href, "url": self.href,
                                       "type": "bookmark", "children": []})
                self.count += 1
                if self.count > MAX_ITEMS:
                    raise ValueError("HTML export has too many bookmarks")
            self.mode, self.buffer, self.href = None, [], ""
        elif tag == "title" and self.mode == "title":
            self.pending_title = "".join(self.buffer).strip()
            self.mode, self.buffer = None, []

    def handle_data(self, data):
        if self.mode is not None:
            self.buffer.append(data)


def section_from_html(text, title=""):
    """Parse a Netscape bookmark export into a temporary section payload."""
    parser = _NetscapeParser()
    parser.feed(text)
    parser.close()
    items = parser.stack[0]
    if not items:
        # Some exports are plain HTML; keep every anchor as a flat bookmark.
        fallback = _links_only(text)
        items = fallback
    if not items:
        raise ValueError("No bookmark links found in this HTML export")
    return {"format": "bookmark-canvas-section", "schemaVersion": 2,
            "sectionType": "temporary", "title": title or "Imported bookmarks",
            "label": "导入", "tempKind": "special", "source": "import-html",
            "items": items}


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []
        self.href = None
        self.buffer = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            values = dict(attrs)
            href = (values.get("href") or "").strip()
            if href.startswith(("http://", "https://")):
                self.href, self.buffer = href, []

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.href:
            title = "".join(self.buffer).strip() or self.href
            self.items.append({"title": title, "url": self.href, "type": "bookmark",
                               "children": []})
            self.href, self.buffer = None, []

    def handle_data(self, data):
        if self.href is not None:
            self.buffer.append(data)


def _links_only(text):
    parser = _LinkParser()
    parser.feed(text)
    parser.close()
    return parser.items


def encode(section):
    return json.dumps(section, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")
