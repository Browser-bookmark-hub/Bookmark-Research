"""Archive actual fetch responses and conservatively identified page extracts."""

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from settings import Settings


# Content state is the page's own shape, independent of how it was fetched:
# transport and parse problems stay in extraction_status, and a page is only
# "usable" when it carries prose a claim could quote.
CONTENT_MINIMUM = 400
# A rendered shell can carry thousands of characters of navigation before any
# content arrives, so this bound is generous; the prose test is the real filter.
SHELL_MAXIMUM = 4000
PAYWALL_MAXIMUM = 600
EMPTY_MARKERS = ("no additional info available", "no content available", "no information available")
CHALLENGE_MARKERS = ("enable javascript and cookies to continue", "just a moment...", "checking your browser",
                     "cf-browser-verification", "verify you are human", "captcha-delivery.com")
PAYWALL_MARKERS = ("subscribe to continue", "this article is for subscribers", "subscribers only",
                   "create a free account to keep reading", "订阅后继续阅读", "订阅以继续")
# A login wall is neither a paywall nor a JavaScript shell: the page loaded, it
# just refuses the body. An SSO redirect is what slipped through the R4
# acceptance run, so it gets its own state instead of counting as usable prose.
LOGIN_MARKERS = ("sign in to continue", "log in to continue", "sign in to view", "login required",
                 "authentication required", "single sign-on", "please sign in",
                 "请登录", "登录后继续", "登录以继续", "统一身份认证", "无权访问")
LOGIN_PROSE_MAXIMUM = 400
NOT_FOUND_MARKERS = ("page not found", "404 not found", "the page you are looking for", "页面不存在",
                     "找不到页面", "该页面已被删除")
NO_BODY_STATES = ("request_failed", "provider_error", "unrecognized_or_not_returned")
# A marker near the top belongs to the page's own chrome; the same words deep
# in a long body are the page talking about the topic, so only the head counts.
SOFT_MARKER_WINDOW = 300
SHELL_PROSE_MINIMUM = 120
SENTENCE_MARKS = ("。", "！", "？", "．", "!", "?")
LINK_OR_URL = re.compile(r"!?\[[^\]]*\]\([^)]*\)|https?://\S+|www\.\S+")

# Published-at is read in three tiers: what the provider says, what the page
# says about itself in a labelled field, then a bare date near the top. A bare
# date is the only tier that can be a misread, so it is the only one that must
# not be later than the fetch, and the only one reported with low confidence.
PUBLISHED_AT_SOURCES = {"provider_metadata": "high", "structured_metadata": "high", "body_date": "low"}
PUBLISHED_KEYS = re.compile(r'"(?:datePublished|dateCreated|dateModified|published_time)"\s*:\s*"([^"]{4,40})"', re.I)
PUBLISHED_META = re.compile(r"<meta[^>]+(?:article:published_time|property=\"og:published_time\"|"
                            r"name=\"(?:pubdate|publishdate|date)\")[^>]+content=\"([^\"]{4,40})\"", re.I)
PUBLISHED_TIME_TAG = re.compile(r"<time[^>]+datetime=\"([^\"]{4,40})\"", re.I)
PUBLISHED_LINE = re.compile(r"^[>\s*]*(published|posted|last updated|发布日期|发布时间|更新于)\s*[:：]\s*\**\s*(\S[^\n]{3,40})",
                            re.I | re.M)
# The not-a-digit guards let an ISO timestamp such as 2026-09-08T10:00:00Z still
# match, while a longer number cannot donate its first digits to a fake date.
DATE_PATTERNS = (re.compile(r"(?<!\d)((?:19|20)\d{2})-(\d{1,2})-(\d{1,2})(?!\d)"),
                 re.compile(r"(?<!\d)((?:19|20)\d{2})/(\d{1,2})/(\d{1,2})(?!\d)"),
                 re.compile(r"((?:19|20)\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"))
DATE_TEXT = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+((?:19|20)\d{2})\b", re.I)
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
MONTH_DAYS = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
BODY_DATE_WINDOW = 1500


def _day(year, month, day, ceiling=None):
    """A validated YYYY-MM-DD, or None; a bare date must not be after the fetch."""
    year, month, day = int(year), int(month), int(day)
    if not 1990 <= year <= 2100 or not 1 <= month <= 12 or not 1 <= day <= MONTH_DAYS[month - 1]:
        return None
    value = "%04d-%02d-%02d" % (year, month, day)
    return None if ceiling is not None and value > ceiling else value


def _first_date(value, ceiling=None):
    """The first plausible YYYY-MM-DD in a string, or None."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            found = _day(*match.groups(), ceiling=ceiling)
            if found:
                return found
    match = DATE_TEXT.search(text)
    if match:
        return _day(match.group(3), MONTHS[match.group(1).lower()[:3]], match.group(2), ceiling=ceiling)
    return None


def published_at(text, provider_value=None, reference=None):
    """(published_at, source, confidence): provider, then labelled, then bare date.

    The value is a day-precision YYYY-MM-DD, because publication dates are the
    only thing these sources actually state. A bare date is accepted only when
    it is not later than the fetch day, so a page merely mentioning a future
    date cannot claim to have been published then.
    """
    ceiling = reference[:10] if isinstance(reference, str) and len(reference) >= 10 else None
    from_provider = _first_date(provider_value)
    if from_provider:
        return from_provider, "provider_metadata", PUBLISHED_AT_SOURCES["provider_metadata"]
    text = text if isinstance(text, str) else ""
    for pattern, group, window in ((PUBLISHED_KEYS, 1, 20000), (PUBLISHED_META, 1, BODY_DATE_WINDOW),
                                   (PUBLISHED_TIME_TAG, 1, BODY_DATE_WINDOW), (PUBLISHED_LINE, 2, BODY_DATE_WINDOW)):
        match = pattern.search(text[:window])
        if match:
            labelled = _first_date(match.group(group))
            if labelled:
                return labelled, "structured_metadata", PUBLISHED_AT_SOURCES["structured_metadata"]
    bare = _first_date(text[:BODY_DATE_WINDOW], ceiling=ceiling)
    if bare:
        return bare, "body_date", PUBLISHED_AT_SOURCES["body_date"]
    return None, None, None


def content_state(title, text, extraction_status="extracted"):
    """How usable one fetched page is, using only what the page itself shows.

    Thresholds follow the beta.15 plan, with corrections the real captures
    forced: a rendered shell can be thousands of characters of navigation, a
    challenge phrase inside a real body is the page's subject rather than its
    state, and a login wall is its own state (an SSO page is not usable prose).
    """
    if extraction_status in NO_BODY_STATES or not isinstance(text, str):
        return "unavailable"
    body = text.strip()
    lowered = body.casefold()
    head = lowered[:SOFT_MARKER_WINDOW]
    short = len(body) < SHELL_MAXIMUM
    prose = _prose_weight(body)
    # A paywall page is different: its free intro before the wall is prose too,
    # so that rule keeps the plan's plain length bound.
    if any(marker in head for marker in CHALLENGE_MARKERS) or (
            short and prose < SHELL_PROSE_MINIMUM and any(marker in lowered for marker in CHALLENGE_MARKERS)):
        return "challenge_blocked"
    # A login page is short on prose by construction (form labels and links),
    # so the marker must also sit near the top; an article about signing in
    # keeps its prose and is not classified by a phrase in its body.
    if prose < LOGIN_PROSE_MAXIMUM and any(marker in head for marker in LOGIN_MARKERS):
        return "login_required"
    if any(marker in lowered for marker in PAYWALL_MARKERS) and len(body) < PAYWALL_MAXIMUM:
        return "paywall_suspected"
    if any(marker in (title or "").casefold() for marker in NOT_FOUND_MARKERS) or any(
            marker in head for marker in NOT_FOUND_MARKERS):
        return "soft_404"
    # An explicit empty-page marker is a known statement, not a suspicion about
    # JavaScript, so it outranks the shell heuristic.
    if any(marker in lowered for marker in EMPTY_MARKERS):
        return "content_insufficient"
    if short and title and prose < SHELL_PROSE_MINIMUM:
        return "js_shell_suspected"
    if len(body) < CONTENT_MINIMUM:
        return "content_insufficient"
    return "usable"


def _prose_weight(text):
    """Characters that read as sentences rather than navigation, links or labels.

    Links, images and bare URLs are removed first: a devsite shell carries
    thousands of characters of link markdown and no prose at all, and its long
    lines are exactly those links. A line then counts when it ends a sentence,
    or when it is long enough to be a paragraph rather than a label.
    """
    weight = 0
    for line in text.splitlines():
        stripped = LINK_OR_URL.sub(" ", line).strip()
        if len(stripped) >= 12 and any(mark in stripped for mark in SENTENCE_MARKS):
            weight += len(stripped)
        elif len(stripped) >= 60 and not stripped.startswith(("@", "#", "|")):
            weight += len(stripped)
    return weight


class SourceArchive:
    """Append immutable capture directories; never invent missing page bodies.

    Layout (manifest schema_version 2)::

        <archive>/sources/<capture_id>/manifest.json   # when/what was fetched
        <archive>/sources/<capture_id>/response.json   # actual provider response
        <archive>/pages/<sha256>.md                     # page body, stored once

    Each manifest page entry records ``sha256`` and ``body_file`` relative to
    its capture directory (``../../pages/<sha256>.md``). Identical bodies from
    different captures share one content-addressed file. Schema 1 captures kept
    bodies inside the capture (``pages/<url-hash>.md``); both layouts are read.
    """

    PAGES = "pages"
    ATTRIBUTION_VERSION = 1

    def __init__(self, directory):
        self.directory = Settings.external_path(str(directory), "Archive directory")

    def _pages_directory(self):
        pages = self.directory / self.PAGES
        if pages.is_symlink() or (pages.exists() and not pages.is_dir()):
            raise ValueError("Archive page store must be a real directory: " + str(pages))
        pages.mkdir(parents=True, exist_ok=True)
        return pages

    def _store_page(self, body):
        """Write body once under pages/<sha256>.md; reuse (or repair) an existing copy."""
        data = body.encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        pages = self._pages_directory()
        target = pages / (digest + ".md")
        if target.is_file() and not target.is_symlink():
            if hashlib.sha256(target.read_bytes()).hexdigest() == digest:
                return target, digest
        # Missing, replaced or damaged: the name states the content, so an
        # atomic rewrite with exactly that content restores it.
        with tempfile.NamedTemporaryFile(dir=pages, prefix=".page-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        return target, digest

    def captures(self):
        """Yield (capture_id, capture_directory) for real capture folders inside this archive."""
        root = self.directory / "sources"
        if root.is_symlink() or not root.is_dir():
            return
        for child in sorted(root.iterdir()):
            if child.name.startswith(".") or child.is_symlink() or not child.is_dir():
                continue
            yield child.name, child

    def page_path(self, capture_directory, entry):
        """Resolve a manifest page entry's body in either layout, confined to this archive."""
        relative = entry.get("body_file") if isinstance(entry, dict) else None
        if not isinstance(relative, str) or not relative or "\x00" in relative or Path(relative).is_absolute():
            return None
        target = (Path(capture_directory) / relative).resolve()
        if self.directory not in target.parents:
            raise ValueError("Archived page body is outside the archive: " + relative)
        return target

    @classmethod
    def legacy_hashes(cls, capture_directory, manifest):
        """Recheck old extracts against their actual saved provider response."""
        if not isinstance(manifest, dict):
            raise ValueError("Invalid archive manifest")
        if manifest.get("source_attribution_version") == cls.ATTRIBUTION_VERSION or "requested_urls" not in manifest:
            return None
        directory = Path(capture_directory).resolve()
        response_path = directory / manifest.get("response_file", "response.json")
        if (response_path.is_symlink() or response_path.resolve().parent != directory
                or response_path.stat().st_size > 32 * 1024 * 1024):
            raise ValueError("Invalid archived provider response")
        raw = response_path.read_bytes()
        if manifest.get("response_sha256") and hashlib.sha256(raw).hexdigest() != manifest["response_sha256"]:
            raise ValueError("Archived provider response SHA-256 changed")
        response = json.loads(raw)
        if not isinstance(response, dict):
            raise ValueError("Invalid archived provider response")
        by_url = {}
        for row in cls._extract(response, manifest["requested_urls"]):
            try:
                by_url.setdefault(cls._key(row["url"]), []).append(row)
            except ValueError:
                continue
        hashes = {}
        if not response.get("isError"):
            for url, rows in by_url.items():
                _, body, _, _ = cls._select(rows)
                if body is not None:
                    hashes[url] = hashlib.sha256(body.encode("utf-8")).hexdigest()
        return hashes

    def read_page(self, capture_directory, entry, manifest=None):
        """Return the verified body text for a manifest page entry, or raise ValueError."""
        target = self.page_path(capture_directory, entry)
        if target is None:
            raise ValueError("Archived page has no saved body")
        data = target.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            raise ValueError("Archived page body does not match its recorded SHA-256")
        if manifest is None:
            manifest_path = Path(capture_directory) / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
        hashes = self.legacy_hashes(capture_directory, manifest)
        if hashes is not None and hashes.get(self._key(entry["requested_url"])) != entry.get("sha256"):
            raise ValueError("Legacy extract has ambiguous source attribution; fetch a new capture")
        return data.decode("utf-8")

    @staticmethod
    def _key(url):
        parts = urlsplit(url)
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or parts.username is not None or parts.password is not None
                or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in url)
                or "\\" in url):
            raise ValueError("Source URLs must be HTTP(S) without credentials or whitespace")
        host = parts.hostname.encode("idna").decode("ascii").lower()
        if ":" in host:
            host = "[" + host + "]"
        if parts.port is not None and parts.port != {"http": 80, "https": 443}[parts.scheme]:
            host += ":" + str(parts.port)
        # An anchor is not a different fetched resource; its coverage stays unverified.
        return urlunsplit((parts.scheme, host, parts.path or "/", parts.query, ""))

    @staticmethod
    def _rows(value):
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict) and isinstance(row.get("url"), str)]
        if not isinstance(value, dict):
            return []
        if isinstance(value.get("url"), str):
            return [value]
        rows = []
        for key in ("results", "items", "pages", "data", "result", "errors", "failed_results"):
            if isinstance(value.get(key), (list, dict)):
                children = SourceArchive._rows(value[key])
                rows.extend(({**row, "error": row.get("error") or row.get("message") or "Provider reported failure"}
                             if key in ("errors", "failed_results") else row) for row in children)
        # Exa /contents reports per-URL outcomes separately from extracted results.
        statuses = value.get("statuses")
        if isinstance(statuses, list):
            rows.extend({**row, "url": row["id"]} for row in statuses
                        if isinstance(row, dict) and isinstance(row.get("id"), str))
        return rows

    @classmethod
    def _extract(cls, response, requested_urls):
        rows = cls._rows(response.get("structuredContent"))
        blocks = response.get("content", [])
        if not isinstance(blocks, list):
            return rows
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "text" or not isinstance(block.get("text"), str):
                continue
            text = block["text"]
            try:
                decoded = json.loads(text)
            except ValueError:
                decoded = None
            structured = cls._rows(decoded)
            if structured:
                rows.extend(structured)
                continue
            rows.extend(cls._text_rows(text, requested_urls))
        return rows

    @classmethod
    def _carries_content(cls, response):
        """True when a response carries page-bearing payload, not just an empty envelope."""
        if not isinstance(response, dict):
            return False
        if cls._rows(response.get("structuredContent")):
            return True
        blocks = response.get("content")
        if not isinstance(blocks, list):
            return False
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "text" or not isinstance(block.get("text"), str):
                continue
            text = block["text"]
            if not text.strip():
                continue
            try:
                decoded = json.loads(text)
            except ValueError:
                return True
            if cls._rows(decoded):
                return True
        return False

    @classmethod
    def _empty_status(cls, rows, response):
        """Per-URL status when a response yields no record for a requested URL."""
        if rows:
            return "unrecognized_or_not_returned"
        return "content_present_unparsed" if cls._carries_content(response) else "no_content_returned"

    @staticmethod
    def _boundary_text(text):
        """Mask fenced examples without shifting offsets into the original text.

        An unclosed fence masks the remainder of the block: the provider may
        have truncated an example around the next page header. Callers must
        treat headers inside the mask as ambiguous (see _text_rows), never as
        records on their own.
        """
        lines, fence = [], None
        for line in text.splitlines(keepends=True):
            marker = re.match(r" {0,3}(`{3,}|~{3,})([^\r\n]*)", line)
            masked = fence is not None
            if fence is not None:
                if (marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1]
                        and not marker[2].strip()):
                    fence = None
            elif marker and (marker[1][0] == "~" or "`" not in marker[2]):
                fence = (marker[1][0], len(marker[1]))
                masked = True
            lines.append(re.sub(r"[^\r\n]", " ", line) if masked else line)
        return "".join(lines)

    @classmethod
    def _text_rows(cls, text, requested_urls=None):
        rows = []
        # Exa appends partial failures after all successful page records. Keep
        # this provider footer out of the last page's extracted body.
        footer = re.search(r"(?m)^(?:Error fetching https?://\S+: [^\n]+(?:\n|$))+\Z", text)
        if footer:
            for match in re.finditer(r"(?m)^Error fetching (https?://\S+): ([^\n]+)$", footer.group()):
                rows.append({"url": match.group(1), "error": match.group(2)})
            text = text[:footer.start()]
            if text.endswith("\n\n"):
                text = text[:-2]
        # Exa concatenates header/URL/body records into one text block for a batch.
        # Include unrequested/redirected records as boundaries, so their text
        # cannot be silently attributed to the preceding requested URL.
        # Titles may retain indented continuation lines from the source HTML.
        # Records must start the block or follow the provider's blank separator.
        boundary_text = cls._boundary_text(text)
        header = r"(?:\A|\n\n)(?:# |Title: )([^\n]+(?:\n[ \t][^\n]*)*)\nURL: (https?://[^\s]+)\n"
        matches = list(re.finditer(header, boundary_text))
        # A missed or malformed URL field could hide the next page boundary.
        # Keep the whole block raw instead of assigning that page to its neighbor.
        fields = [match.start() for match in re.finditer(r"(?m)^[ \t]*URL:", boundary_text)]
        matched_fields = [match.start(2) - len("URL: ") for match in matches]
        if fields != matched_fields:
            return rows
        try:
            keys = [cls._key(match.group(2)) for match in matches]
        except ValueError:
            return rows
        if not matches or matches[0].start() != 0 or len(set(keys)) != len(keys):
            return rows
        # A provider can truncate one page inside a fence and concatenate the
        # next page before a later fence happens to close it, or leave a fence
        # unclosed; the mask then hides real page headers. Header-shaped lines
        # inside the mask are normally ambiguous (fenced examples versus
        # records), so refuse unless the hidden records are exactly the missing
        # requested pages, each once: the response then accounts for every
        # missing page as a record instead of guessing. Anything else stays
        # raw. Complete batches still preserve fenced examples, including
        # examples referring to another URL that has its own visible record.
        expected = {cls._key(url) for url in requested_urls} if requested_urls is not None else None
        if expected is None or expected - set(keys):
            visible = {match.start() for match in matches}
            hidden = [match for match in re.finditer(header, text) if match.start() not in visible]
            if hidden:
                if expected is None:
                    return rows
                try:
                    hidden_keys = [cls._key(match.group(2)) for match in hidden]
                except ValueError:
                    return rows
                if (len(set(hidden_keys)) != len(hidden_keys)
                        or set(hidden_keys) != expected - set(keys)):
                    return rows
                matches = sorted(matches + hidden, key=lambda match: match.start())
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = text[match.end():end]
            row = {"url": match.group(2), "title": text[match.start(1):match.end(1)]}
            metadata = re.match(r"(?:(?:Published|Author): [^\n]*\n)*\n", body)
            if metadata:
                for line in metadata.group().splitlines():
                    if line.startswith("Published: "):
                        row["publishedDate"] = line[11:]
                    elif line.startswith("Author: "):
                        row["author"] = line[8:]
                body = body[metadata.end():]
            if match.group().lstrip("\n").startswith("Title: ") and body.startswith("Text: "):
                body = body[6:]
            rows.append({**row, "text": body})
        return rows

    @staticmethod
    def _page(row):
        status = row.get("status")
        if isinstance(status, str):
            status = status.lower()
        error = row.get("error") or row.get("errors")
        failed = (error or row.get("success") is False or status in ("error", "failed", "failure")
                  or (type(status) is int and status >= 400)
                  or (type(row.get("httpStatus")) is int and row["httpStatus"] >= 400))
        if failed:
            return None, "provider_error", "provider_extracted_text"
        for field in ("markdown", "text", "full_content", "raw_content", "content"):
            body = row.get(field)
            if isinstance(body, str) and body.strip():
                # Keep obvious access screens in the raw response, never as a
                # usable article. Mentions inside an article are not barriers.
                title = row.get("title") if isinstance(row.get("title"), str) else ""
                heading = body.strip().splitlines()[0].lstrip("# ").strip()
                without_notice = re.sub(r"\[CRITICAL INSTRUCTIONS FOR ALL AI ASSISTANTS[^\]]*\]"
                                        r".*?\[END INSTRUCTIONS\]", "", body, flags=re.IGNORECASE | re.DOTALL)
                if without_notice != body and not any(
                        line.strip("# \t") not in ("", title.strip(), heading)
                        for line in without_notice.splitlines()):
                    return None, "insufficient_content", "provider_extracted_text"
                for label in (title.strip(), heading):
                    if re.fullmatch(r"(?:page not found|404(?:\s*[-:]?\s*not found)?|页面不存在|页面未找到)"
                                    r"(?:\s*[-|–—].*)?", label, re.IGNORECASE):
                        return None, "not_found", "provider_extracted_text"
                    if re.fullmatch(r"(?:just a moment|access denied|verify you are human|"
                                    r"checking your browser|attention required|请完成安全验证)"
                                    r"[.!…]*(?:\s*[-|–—:].*)?", label, re.IGNORECASE):
                        return None, "access_challenge", "provider_extracted_text"
                    if re.fullmatch(r"(?:log in|login|sign in|登录|登入|请先登录)"
                                    r"(?:\s*[-|–—:].*| to .*)?", label, re.IGNORECASE):
                        return None, "login_required", "provider_extracted_text"
                return body, "extracted", "provider_extracted_text"
        excerpts = row.get("excerpts")
        if isinstance(excerpts, list) and all(isinstance(item, str) for item in excerpts) and any(excerpts):
            return "\n\n".join(excerpts), "extracted", "provider_excerpts"
        return None, "no_extract", "provider_extracted_text"

    @classmethod
    def _select(cls, rows, empty_status="unrecognized_or_not_returned"):
        """Select one extract per URL; empty_status names why no rows matched.

        Callers pass "no_content_returned" or "content_present_unparsed" when
        the whole response produced no records at all, keeping a provider that
        returned nothing distinguishable from content this parser could not
        turn into records.
        """
        if not rows:
            return None, None, empty_status, "unknown"
        candidates = [(row, *cls._page(row)) for row in rows]
        failures = [candidate for candidate in candidates if candidate[2] == "provider_error"]
        if failures:
            return failures[0]
        bodies = [candidate for candidate in candidates if candidate[1] is not None]
        if len({(candidate[1], candidate[3]) for candidate in bodies}) > 1:
            return rows[0], None, "conflicting_provider_results", "unknown"
        return (bodies or candidates)[0]

    @classmethod
    def compact_fetch(cls, fetched, max_characters=None, max_total_characters=100000, offset=0,
                      fair_share_min=0):
        """Present one selected extract per URL, retaining every attempt's provenance.

        Raw MCP responses may repeat a body in text, structured data and excerpts.
        Keep those responses in their archives (or explicit raw output), without
        repeating them in the model's ordinary reading response.
        """
        if "result" not in fetched and "attempts" not in fetched:
            return fetched
        attempts = fetched.get("attempts", [fetched])
        selected = {row["url"]: row for row in fetched.get("per_url", [])}
        pages = {}
        for attempt in attempts:
            response = attempt.get("result")
            if not isinstance(response, dict):
                continue
            by_url, rows = {}, cls._extract(response, attempt["urls"])
            for row in rows:
                try:
                    key = cls._key(row["url"])
                except (ValueError, UnicodeError):
                    continue
                by_url.setdefault(key, []).append(row)
            archive = attempt.get("archive", {})
            saved = {row["requested_url"]: row for row in archive.get("pages", [])}
            empty_status = cls._empty_status(rows, response)
            for url in attempt["urls"]:
                provider = attempt["provider"]
                if selected.get(url, {}).get("provider", provider) != provider:
                    continue
                row, body, extraction, kind = cls._select(by_url.get(cls._key(url)), empty_status)
                if response.get("isError"):
                    body, extraction = None, "provider_error"
                archived = saved.get(url, {})
                if body is not None and archive.get("status") == "saved":
                    # Serve a body only when the archive vouches for exactly
                    # these bytes. A body the manifest did not record means the
                    # capture was written by a different parser version; it
                    # must not resurface through a newer re-extraction.
                    digest = archived.get("sha256")
                    if not digest or hashlib.sha256(body.encode("utf-8")).hexdigest() != digest:
                        body, extraction = None, "source_attribution_mismatch"
                metadata = row or {}
                provider_published = metadata.get("publishedDate") or metadata.get("published_at") or metadata.get("publishedTime")
                published = published_at(body, provider_published, reference=attempt.get("retrieved_at"))
                pages[url] = {**archived, "url": url, "provider": provider,
                    "capture_id": archive.get("capture_id"),
                    "returned_url": row.get("url") if row else None,
                    "title": row.get("title") if row else None,
                    "extraction_status": extraction, "content_kind": kind,
                    "content_state": content_state(row.get("title") if row else None, body, extraction),
                    "completeness": "unknown", "retrieved_at": attempt.get("retrieved_at"),
                    "characters": len(body) if body is not None else 0,
                    "possibly_truncated": bool(archived.get("possibly_truncated") or metadata.get("truncated") or (body is not None and
                        attempt.get("character_limit_applied") and len(body) >= attempt["requested_max_characters"] - 2)),
                    "provider_published_at": provider_published,
                    "published_at": published[0], "published_at_source": published[1],
                    "published_at_confidence": published[2],
                    "provider_crawled_at": metadata.get("crawled_at") or metadata.get("crawledAt"),
                    "text": body,
                    "manifest_path": archive.get("manifest_path")}
                if body is None:
                    pages[url].update(sha256=None, body_path=None, page_body_archived=False)
        result = {key: value for key, value in fetched.items() if key not in ("result", "attempts")}
        if "attempts" in fetched:
            result["attempts"] = [{key: value for key, value in attempt.items() if key != "result"}
                                  for attempt in attempts]
        limits = [attempt.get("requested_max_characters", 12000) for attempt in attempts]
        limit = max_characters if max_characters is not None else min(limits or [12000])
        ordered = [pages[url] for url in fetched.get("urls", []) if url in pages]
        bounded = cls._bounded_pages(ordered, limit, max_total_characters, offset,
                                     fair_share_min=fair_share_min)
        with_text = sum(1 for page in bounded if (page.get("characters") or 0) > 0)
        result.update(output_format="compact", pages=bounded,
            pages_with_text=with_text, pages_without_text=len(bounded) - with_text,
            output_budget={"max_characters_per_page": limit, "max_total_characters": max_total_characters,
                           "offset": offset, "fair_share_min": fair_share_min,
                           "raw_archive_preserved": any(
                               attempt.get("archive", {}).get("status") == "saved" for attempt in attempts)})
        if "successful_url_count" in result:
            result["successful_url_count"] = with_text
        return result

    @staticmethod
    def _bounded_pages(pages, limit, total, offset, fair_share_min=0):
        for name, value, low, high in (("max_characters", limit, 100, 100000),
                                       ("max_total_characters", total, 100, 800000),
                                       ("offset", offset, 0, 100000000)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError("%s must be between %s and %s" % (name, low, high))
        if type(fair_share_min) is not int or fair_share_min < 0:
            raise ValueError("fair_share_min must be a non-negative integer")
        remaining = total
        # A multi-URL fetch used to consume the whole budget on the first pages;
        # a later page then looked "usable" with zero characters. When asked for
        # fairness, divide the remaining budget over the remaining pages. A
        # continuation (offset > 0) is one page, so the old path is exact.
        fair = fair_share_min > 0 and len(pages) > 1 and offset == 0
        text_pages = sum(1 for page in pages if page.get("text") is not None)
        text_seen = 0
        for page in pages:
            body = page.get("text")
            if body is None:
                page["read"] = False
                continue
            text_seen += 1
            start = min(offset, len(body))
            if fair:
                left = text_pages - text_seen + 1
                allowance = remaining // left if left else remaining
                allowance = min(limit, max(1, allowance), remaining) if remaining else 0
            else:
                allowance = min(limit, remaining)
            excerpt = body[start:start + allowance]
            end = start + len(excerpt)
            remaining -= len(excerpt)
            page.update(source_characters=len(body), characters=len(excerpt),
                        text=excerpt, text_sha256=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                        offset=start, next_offset=end if end < len(body) else None,
                        output_truncated=start > 0 or end < len(body), read=bool(excerpt))
            if not excerpt:
                # Do not leave an empty page looking usable: the caller cannot
                # cite text it did not receive. Preserve a more specific
                # provider state (challenge, shell, paywall) when one exists.
                if page.get("content_state") in (None, "usable"):
                    page["content_state"] = "unavailable"
                page["next_offset"] = 0
            if page["output_truncated"]:
                page["possibly_truncated"] = True
            if page["next_offset"] is not None and page.get("capture_id"):
                page["continuation"] = {"urls": [page["url"]], "capture_id": page["capture_id"],
                                        "offset": end, "max_characters": limit}
        return pages

    def read_capture(self, capture_id, urls, max_characters=12000, max_total_characters=100000, offset=0,
                     fair_share_min=0):
        """Read a stable archived extract without issuing another web request."""
        if not isinstance(capture_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", capture_id):
            raise ValueError("Invalid archive capture_id")
        if not isinstance(urls, list) or not 1 <= len(urls) <= 16:
            raise ValueError("urls must contain 1 to 16 archived URLs")
        requested = list(dict.fromkeys(urls))
        for url in requested:
            self._key(url)
        directory = self.directory / "sources" / capture_id
        if ((self.directory / "sources").is_symlink() or directory.is_symlink()
                or directory.resolve().parent != self.directory / "sources"):
            raise ValueError("Archive capture must remain in the configured archive")
        manifest_path = directory / "manifest.json"
        if manifest_path.is_symlink() or manifest_path.stat().st_size > 8000000:
            raise ValueError("Invalid archive manifest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("capture_id") != capture_id:
            raise ValueError("Archive manifest belongs to a different capture")
        saved = {self._key(page["requested_url"]): page for page in manifest["pages"]}
        pages = []
        for url in requested:
            record = saved.get(self._key(url))
            if record is None:
                raise ValueError("URL is not in the selected archive capture")
            body = self.read_page(directory, record, manifest) if record.get("body_file") else None
            pages.append({**record, "url": url, "capture_id": capture_id,
                          "provider": manifest.get("provider"), "retrieved_at": manifest.get("retrieved_at"),
                          "manifest_path": str(manifest_path), "text": body,
                          "body_path": str(self.page_path(directory, record)) if body is not None else None})
        successful = sum(1 for page in pages if page["text"])
        bounded = self._bounded_pages(pages, max_characters, max_total_characters, offset,
                                      fair_share_min=fair_share_min)
        with_text = sum(1 for page in bounded if (page.get("characters") or 0) > 0)
        return {"mode": "archive_read", "status": "ok" if successful == len(pages) else
                "partial" if successful else "error", "urls": requested, "output_format": "compact",
                "successful_url_count": with_text,
                "pages_with_text": with_text, "pages_without_text": len(bounded) - with_text,
                "network_request_performed": False,
                "pages": bounded,
                "output_budget": {"max_characters_per_page": max_characters,
                                  "max_total_characters": max_total_characters, "offset": offset,
                                  "fair_share_min": fair_share_min}}

    @staticmethod
    def _write_json(path, value):
        path.write_bytes((json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8"))

    def save(self, fetch):
        response = fetch["result"]
        rows = self._extract(response, fetch["urls"])
        # URL association is explicit. Unknown shapes or redirects are retained raw.
        by_url = {}
        for row in rows:
            try:
                key = self._key(row["url"])
            except ValueError:
                continue
            by_url.setdefault(key, []).append(row)
        archived_at = datetime.now(timezone.utc)
        capture_id = archived_at.strftime("%Y%m%dT%H%M%S%fZ-") + uuid.uuid4().hex[:12]
        captures = self.directory / "sources"
        Settings.external_path(str(captures), "Archive directory")
        if captures.is_symlink():
            raise ValueError("Archive captures must not be a symlink")
        captures.mkdir(parents=True, exist_ok=True)
        destination = captures / capture_id
        manifest = {"schema_version": 2, "capture_id": capture_id, "source_attribution_version": self.ATTRIBUTION_VERSION,
                    "archived_at": archived_at.isoformat(),
                    "provider": fetch["provider"], "tool": fetch["tool"], "retrieved_at": fetch["retrieved_at"],
                    "requested_urls": fetch["urls"], "request_arguments": fetch["request_arguments"],
                    "requested_max_characters": fetch["requested_max_characters"],
                    "character_limit_applied": any(key in fetch["request_arguments"] for key in ("maxCharacters", "max_chars")),
                    "response_file": "response.json", "page_store": "content_addressed", "pages": [],
                    "origin_freshness": "unknown", "forced_live_fetch": False,
                    "note": "Saved provider response and extracts, not original HTML or verified complete pages. Retrieval time is not publication or update time."}
        with tempfile.TemporaryDirectory(prefix=".capture-", dir=captures) as temporary:
            stage = Path(temporary) / "capture"
            stage.mkdir()
            self._write_json(stage / "response.json", response)
            manifest["response_sha256"] = hashlib.sha256((stage / "response.json").read_bytes()).hexdigest()
            bodies = {}
            empty_status = self._empty_status(rows, response)
            for url in dict.fromkeys(fetch["urls"]):
                row, body, status, kind = self._select(by_url.get(self._key(url)), empty_status)
                if response.get("isError"):
                    body, status = None, "provider_error"
                entry = {"requested_url": url, "returned_url": row.get("url") if row else None,
                         "title": row.get("title") if row else None, "extraction_status": status,
                         "content_kind": kind, "content_state": content_state(row.get("title") if row else None, body, status),
                         "body_file": None, "page_body_archived": False,
                         "completeness": "unknown", "provider_crawled_at": None,
                         "fragment_scope_verified": False, "sha256": None}
                if row:
                    entry["provider_crawled_at"] = row.get("crawled_at") or row.get("crawledAt")
                    entry["provider_published_at"] = row.get("publishedDate") or row.get("published_at") or row.get("publishedTime")
                    entry["provider_author"] = row.get("author")
                    entry["provider_status"] = row.get("status", row.get("httpStatus"))
                    if row.get("error") or row.get("errors"):
                        entry["provider_error"] = row.get("error") or row.get("errors")
                published = published_at(body, entry.get("provider_published_at"), reference=fetch.get("retrieved_at"))
                entry["published_at"], entry["published_at_source"], entry["published_at_confidence"] = published
                if body is not None:
                    # Written before the capture is published, so a manifest
                    # never points at a missing body. Identical bodies share it.
                    target, digest = self._store_page(body)
                    entry.update(body_file="../../%s/%s" % (self.PAGES, target.name), page_body_archived=True,
                                 sha256=digest, characters=len(body))
                    bodies[url] = target
                    limited = manifest["character_limit_applied"]
                    entry["possibly_truncated"] = bool((row and row.get("truncated")) or
                        (limited and len(body) >= fetch["requested_max_characters"] - 2))
                manifest["pages"].append(entry)
            self._write_json(stage / "manifest.json", manifest)
            stage.rename(destination)
        tracking = "indexed"
        try:
            from source_versions import SourceVersions
            SourceVersions(self.directory / "source-versions.sqlite3").record("capture:" + capture_id, [
                {"id": str(position), "url": page["requested_url"], "sha256": page["sha256"],
                 "retrieved_at": fetch["retrieved_at"], "provider": fetch["provider"]}
                for position, page in enumerate(manifest["pages"]) if page["page_body_archived"]])
        except (OSError, ValueError, sqlite3.Error):
            # Publishing immutable evidence succeeded. A derived index failure
            # must not turn that success into a retry of the provider request.
            tracking = "unavailable"
        return {"status": "saved", "capture_id": capture_id, "directory": str(destination),
                "knowledge_state": "archived",
                "wiki_work": {"tool": "wiki_work", "arguments": {"capture_id": capture_id}},
                "manifest_path": str(destination / "manifest.json"),
                "response_path": str(destination / "response.json"),
                "source_version_tracking": tracking,
                "pages": [{**row, "body_path": str(bodies[row["requested_url"]]) if row["body_file"] else None}
                          for row in manifest["pages"]]}
