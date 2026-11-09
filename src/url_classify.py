"""Cheap URL classification used by fetch routing and duplicate reports."""
from urllib.parse import urlsplit

# Base domains whose page is a search session, not a document: fetching the page
# only returns the same result list a fresh search would produce.
SEARCH_DOMAINS = (
    "bing.com", "google.com", "google.com.hk", "duckduckgo.com",
    "search.yahoo.com", "search.brave.com", "baidu.com", "yandex.com",
    "yandex.ru", "sogou.com", "so.com", "startpage.com", "ecosia.org",
    "search.naver.com",
)


def host_of(url):
    try:
        return (urlsplit(url).hostname or "").casefold()
    except (ValueError, TypeError):
        return ""


def _matches(host, domain):
    return host == domain or host.endswith("." + domain)


def is_search_result_url(url):
    """True for search-engine result pages (query pages), not documents."""
    if not isinstance(url, str) or not url:
        return False
    host = host_of(url)
    if not host or not any(_matches(host, domain) for domain in SEARCH_DOMAINS):
        return False
    parts = urlsplit(url)
    path = (parts.path or "").casefold()
    query = parts.query or ""
    if _matches(host, "google.com") or _matches(host, "google.com.hk"):
        return path in ("/search", "/url", "/webhp") or "q=" in query
    if _matches(host, "bing.com"):
        return path.startswith("/search") or "q=" in query
    if _matches(host, "baidu.com"):
        return path.startswith("/s") or "wd=" in query
    if _matches(host, "duckduckgo.com"):
        return True
    if _matches(host, "yandex.com") or _matches(host, "yandex.ru"):
        return "text=" in query or "q=" in query
    return path in ("/search", "/s", "/web") or "q=" in query
