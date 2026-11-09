"""Placeholder rows a user did not mean to save: divider searches, empty titles."""
from urllib.parse import parse_qs, urlsplit

from url_classify import is_search_result_url

SUFFIXES = (" - 搜索", " - 搜尋", " - search", " - google search",
            " - bing", " - baidu", " - 百度")


def _text_only(title):
    text = (title or "").strip()
    lowered = text.casefold()
    for suffix in SUFFIXES:
        if lowered.endswith(suffix):
            return text[: -len(suffix)].strip()
    return text


def _has_content(text):
    return any(char.isalnum() or "\u4e00" <= char <= "\u9fff" for char in text)


def is_junk(title, url=""):
    """True when a row is a separator/divider rather than a saved reference."""
    visible = _text_only(title)
    if visible and len(visible) >= 2 and not _has_content(visible):
        return True
    if url and is_search_result_url(url):
        query = parse_qs(urlsplit(url).query)
        values = query.get("q") or query.get("wd") or query.get("query") or []
        if values and not _has_content(" ".join(values)):
            return True
    return False
