"""Read bounded local candidates. The host decides relevance and research depth.

Canvas matches, Wiki knowledge and archived sources are independent retrieval
channels. This module never fetches, rejects literal matches or starts a task.
"""
import json
import re
from datetime import datetime, timezone

from bookmark_index import BookmarkIndex, question_urls
from settings import Settings

FRESH_TERMS = re.compile(r"最近|最新|本周|本月|今年|当前|现在|变化|更新|latest|recent|current|today|now", re.I)


class ResearchPlan:
    def __init__(self, index=None, settings=None, wiki=None, raw=None):
        self.index = index
        self.settings = settings if settings is not None else Settings()
        self.wiki_store = wiki
        self.raw_library = raw

    question_urls = staticmethod(question_urls)

    def _preferences(self):
        return self.settings.load()

    @staticmethod
    def _time(value):
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

    def freshness(self, scope, question):
        """Local freshness as data: any time, high-confidence time, and a flag."""
        prefs = self._preferences()
        try:
            days = int(prefs.get("freshness_days", 30))
        except (TypeError, ValueError):
            days = 30
        cards = scope.get("cards") or []
        any_times = [(self._time(card.get("newest_added_at")), card.get("newest_added_at"))
                     for card in cards if card.get("newest_added_at")]
        high_times = [(self._time(card.get("newest_high_added_at")), card.get("newest_high_added_at"))
                      for card in cards if card.get("newest_high_added_at")]
        newest_any = max((value for value, _ in any_times if value), default=None)
        newest_high = max((value for value, _ in high_times if value), default=None)
        now = datetime.now(timezone.utc)
        stale = None
        if newest_any is not None:
            stale = (now - newest_any).total_seconds() > days * 86400
        confidence = "high" if newest_high is not None else ("low" if newest_any is not None else None)
        reasons = []
        if FRESH_TERMS.search(question or ""):
            reasons.append("question asks for current or recent material")
        if confidence == "low":
            reasons.append("newest local time is low confidence")
        if newest_any is None:
            reasons.append("no local added_at for the selected cards")
        if stale is True:
            reasons.append("older than %d days" % days)
        elif stale is False:
            reasons.append("within %d days" % days)
        return {"intent": bool(FRESH_TERMS.search(question or "")),
                "newest_any": newest_any.isoformat() if newest_any else None,
                "newest_high": newest_high.isoformat() if newest_high else None,
                "confidence": confidence, "stale": stale, "days": days,
                "reason": "; ".join(reasons) or "no freshness signal"}

    def _wiki(self):
        if self.wiki_store is None:
            from wiki import WikiStore
            self.wiki_store = WikiStore(settings=self.settings)
        return self.wiki_store

    def _raw(self):
        if self.raw_library is None:
            from raw_library import RawLibrary
            self.raw_library = RawLibrary(settings=self.settings)
        return self.raw_library

    def wiki_preflight(self, terms, limit=3):
        if not terms:
            return [], None
        try:
            return self._wiki().search_terms(terms, limit=limit), None
        except Exception as exc:  # local optional check; never hide the bookmark scope
            return [], "Wiki preflight unavailable: " + str(exc)

    def archive_preflight(self, terms, limit=5):
        if not terms:
            return [], None
        try:
            return self._raw().search_terms(terms, limit=limit), None
        except Exception as exc:
            return [], "Archive preflight unavailable: " + str(exc)

    @staticmethod
    def _bounded(result, max_characters):
        def size():
            return len(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        truncated = bool(result.get("truncated"))
        # Keep at least one pointer from each matching channel before removing
        # the final one; original text remains available through its reader.
        for minimum in (1, 0):
            for key in ("canvas_matches", "archive", "wiki", "urls", "cards"):
                while size() + 100 > max_characters and len(result.get(key, [])) > minimum:
                    result[key].pop()
                    if key == "canvas_matches":
                        result["canvas_matches_truncated"] = True
                    truncated = True
        truncated = truncated or size() + 100 > max_characters
        result["preflight_budget"] = {"characters": size() + 100,
                                      "max_characters": max_characters, "truncated": truncated}
        result["preflight_budget"]["characters"] = size()
        return result

    def build(self, source_id=None, question=None, max_cards=3, max_urls=8,
              include_wiki=True, include_archive=True, max_wiki=3, max_archive=5):
        prefs = self._preferences()
        terms = BookmarkIndex.plan_terms(question)
        if source_id:
            if self.index is None:
                raise ValueError("source_id requires an indexed source")
            scope = self.index.plan_scope(source_id, question, max_cards=max_cards, max_urls=max_urls,
                                          homepage_limit=prefs["plan"]["homepage_limit"])
            matches = self.index._canvas_matches(source_id, terms)
        else:
            scope = {"source_id": None, "terms": terms, "cards": [], "urls": [],
                     "truncated": False, "errors": []}
            matches = []
        wiki, wiki_error = self.wiki_preflight(terms, max_wiki) if (
            include_wiki and prefs.get("wiki_preflight", True)) else ([], None)
        archive, archive_error = self.archive_preflight(terms, max_archive) if include_archive else ([], None)
        merged = {}
        for row in matches:
            identity = (row["kind"], row["canvas_path"], row.get("node_id") or row.get("edge_id"))
            candidate = merged.setdefault(identity, {key: value for key, value in row.items() if key != "target"})
            matched = candidate.setdefault("matched_terms", [])
            if row.get("target") and row["target"] not in matched:
                matched.append(row["target"])
        canvas = []
        for row in list(merged.values())[:12]:
            row = dict(row)
            if len(row.get("text") or "") > 1200:
                row.update(text=row["text"][:1200], text_truncated=True)
            canvas.append(row)
        result = {**scope, "question_urls": question_urls(question), "canvas_matches": canvas,
                  "canvas_matches_truncated": len(merged) > len(canvas),
                  "wiki": wiki, "archive": archive, "freshness": self.freshness(scope, question),
                  "next_action": {"reason": "Assess these literal candidates in context. Read known URLs directly; "
                                  "use host or plugin search for missing evidence. No match in one store does not "
                                  "establish absence in another store.", "execution_owner": "host"}}
        errors = [error for error in (wiki_error, archive_error) if error]
        if errors:
            result["preflight_errors"] = errors
        return self._bounded(result, prefs["plan"]["max_characters"])
