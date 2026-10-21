"""Suggest a research route from one question and the local package scope.

Local only. It reads the indexed package, ranks the cards and bookmarks the
question touches, and forwards that to the same route vocabulary
``research_route`` uses, so the two entrypoints cannot drift apart. It never
fetches, never starts a research session and never widens the requested scope.

The preflight also checks the authored Wiki and the saved-page archive, but only
with literal terms: an entire natural-language question is not a search key for
either store. Both extra checks are optional and their failures never hide the
bookmark scope.
"""

import json
import re
from datetime import datetime, timezone

from bookmark_index import question_urls
from routing import ResearchRouting
from settings import Settings


DOCUMENTATION_HOSTS = ("github.com", "gitlab.com", "docs.python.org", "developer.mozilla.org", "readthedocs.io")
DEPTH_TERMS = ("深度", "核验", "核实", "报告", "对比", "比较", "审查", "评估",
               "deep", "report", "verify", "audit", "compare", "evaluate", "benchmark")

# Terms that describe the question's shape rather than its subject. They may
# match a card incidentally, but they cannot keep a question alive by themselves.
GENERIC_TERMS = frozenset((
    "中的", "的应", "应用", "哪些", "有哪", "些变", "什么", "怎么", "如何",
    "变化", "最新", "最近", "本周", "本月", "今年", "当前", "现在",
    "the", "and", "for", "with", "about", "what", "which", "how", "does", "did",
    "current", "latest", "recent", "today", "now", "new", "update", "updates",
))
FRESH_TERMS = re.compile(r"最近|最新|本周|本月|今年|当前|现在|变化|变更|更新|新增|发布|改版|latest|recent|current|today|now", re.I)

# A single CJK character is often the whole entity (书, 车, 钱), but very common
# function characters would pass the score floor in a tiny card by accident.
SINGLE_CJK_STOP = frozenset("的了和在与是有我你他她它这那中上下个不也就都而及或为以于对从到把被给让使等着过吗呢吧啊呀")


class ResearchPlan:
    """Compose ``BookmarkIndex.plan_scope`` with the existing router."""

    def __init__(self, index, settings=None, routing=None, wiki=None, raw=None):
        self.index = index
        self.settings = settings if settings is not None else Settings()
        self.routing = routing if routing is not None else ResearchRouting(self.settings)
        self.wiki_store = wiki
        self.raw_library = raw

    @staticmethod
    def question_urls(question):
        return question_urls(question)

    @staticmethod
    def host(url):
        match = re.match(r"https?://([^/?#]+)", url)
        return match.group(1).split("@")[-1].split(":")[0].lower() if match else ""

    @staticmethod
    def is_documentation(host):
        """A rule, not a growing list: docs.* and developer(s).* hosts are documentation."""
        return (host in DOCUMENTATION_HOSTS or host.startswith(("docs.", "developer.", "developers."))
                or ".docs." in host)

    @staticmethod
    def _time(value):
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

    @staticmethod
    def _fragments(terms):
        """CJK bigrams that are only a slice of a longer term in the question.

        ``量子纠缠`` is a term; ``量子`` is a bigram of it, not the name of the
        entity the question asks about. ASCII words keep their whole-word form.
        """
        return {term for term in terms
                if any(other != term and len(other) > len(term) and term in other for other in terms)}

    def _preferences(self):
        return self.settings.load()

    def relevance(self, scope, question):
        """Whether the literal hits are strong enough to keep the scope.

        A card that merely contains a generic bigram, or a name fragment such as
        ``quantum`` inside ``QuantumNous``, is not evidence that the package
        covers the question. The threshold is a setting, not a hidden constant.
        """
        terms = list(scope.get("terms") or [])
        cards = list(scope.get("cards") or [])
        prefs = self._preferences().get("plan", {})
        minimum = float(prefs.get("min_relevance", 0.05))
        fragments = self._fragments(terms)
        meaningful = [term for term in terms
                      if (len(term) >= 3 or (len(term) == 2 and term.isupper())
                          if term.isascii()
                          else len(term) >= 2 or (len(term) == 1 and term not in SINGLE_CJK_STOP))
                      and term.casefold() not in GENERIC_TERMS and term not in fragments]
        matched = {term for card in cards for term in (card.get("matched_terms") or [])}
        matched_meaningful = [term for term in meaningful if term in matched]

        def strong(term):
            """A single term is enough only when it is specific to a small card.

            ``Lumen`` in a one-bookmark card is a name; ``量子`` in a 1,053-item
            permanent tree is a substring. The same score threshold cannot tell
            them apart, so use the term's own hit count and the card's density.
            """
            for card in cards:
                if term not in (card.get("matched_terms") or []):
                    continue
                hits = (card.get("term_hits") or {}).get(term, 0)
                density = float(card.get("density") or 0)
                title = (str(card.get("label") or "") + " " + str(card.get("title") or "")).casefold()
                if hits >= 2 and density >= 0.02:
                    return True
                # A long literal name (unique500, EmbeddingGemma) can occur once
                # in a normal card and still be the exact thing the user asked
                # for. A token-aware title occurrence is the evidence; plain
                # density alone would hide it.
                title_hits = (card.get("term_title_hits") or {}).get(term, 0)
                if len(term) >= 4 and title_hits >= 1:
                    return True
                if density >= 0.5:
                    return True
                if term.casefold() in title:
                    return True
            return False

        best = max((float(card.get("score") or 0) for card in cards), default=0.0)
        title_terms = [term for term in matched_meaningful
                       if len(term) >= 4 and any(
                           (card.get("term_title_hits") or {}).get(term, 0) >= 1 for card in cards)]
        accepted = bool(self.question_urls(question)) or bool(
            cards and matched_meaningful and (
                title_terms or (best >= minimum and
                                (len(matched_meaningful) >= 2
                                 or any(strong(term) for term in matched_meaningful)))))
        if not cards:
            reason = ("No card in this source matches the question terms. Report that the package "
                      "has nothing on them and ask before widening the scope.")
        elif accepted and title_terms and best < minimum:
            reason = ("A title token matched a long term (%s); the low card score is only because "
                      "the card is large." % ", ".join(title_terms[:4]))
        elif best < minimum:
            reason = ("The best card score (%.3f) is below plan.min_relevance (%.3f); the hits are "
                      "incidental. Report the miss instead of widening the scope." % (best, minimum))
        elif not matched_meaningful:
            reason = ("Only generic or partial terms matched (%s); no subject term survived. "
                      "Ask before widening the scope." % ", ".join(sorted(matched))[:200])
        elif not accepted:
            reason = ("A single weak term matched (%s); it is not specific enough to keep the scope. "
                      "Ask before widening the scope." % ", ".join(matched_meaningful[:8]))
        else:
            reason = ("Matched %d meaningful term(s): %s" %
                      (len(matched_meaningful), ", ".join(matched_meaningful[:8])))
        return {"accepted": accepted, "matched_terms": sorted(matched),
                "meaningful_terms": matched_meaningful, "score": round(best, 6),
                "min_relevance": minimum, "reason": reason}

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

    def priority_terms(self, scope, meaningful=None):
        """The term that contributes most to the selected cards.

        Wiki and archive searches must not be filled by a generic companion
        term. For ``RAG 企业落地`` the subject is ``RAG``; ``企业`` and ``落地``
        are context. The weight is the same literal term weight used by
        ``plan_scope``: length over the number of cards the term reaches. Only
        terms that survived the relevance filter are eligible, so a cross-word
        bigram such as ``业落`` cannot win.
        """
        terms = list(meaningful or scope.get("terms") or [])
        counts = scope.get("term_cards") or {}
        ranked = sorted((term for term in terms if counts.get(term)),
                        key=lambda term: (-(len(term) / max(1, counts[term])), -len(term), term))
        return set(ranked[:1])

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

    def task_shape(self, question, urls, term_cards=None):
        """Which of the router's three task shapes the question describes.

        A documentation or repository bookmark only makes this a ``lookup`` when
        a meaningful term of the question reaches exactly one canonical tree and
        that term matched the URL's own rows. An incidental docs hit next to a
        broad topic question stays evidence and does not downgrade the route.
        """
        if self.question_urls(question):
            return "lookup", "The question already contains a URL"
        terms = list((term_cards or {}).keys())
        fragments = self._fragments(terms)
        naming = {term for term, count in (term_cards or {}).items()
                  if count == 1 and term not in fragments
                  and term.casefold() not in GENERIC_TERMS}
        for row in urls:
            host = self.host(row.get("url", ""))
            if not self.is_documentation(host):
                continue
            named = sorted(naming.intersection(row.get("matched_terms") or []))
            if named:
                return "lookup", ("A matched bookmark points at documentation or a repository (" + host +
                                  ") and the question names it (" + named[0] + " points at one card)")
        lowered = question.casefold()
        if any(term in lowered for term in DEPTH_TERMS):
            return "batch_research", "The question asks for depth, verification or a report"
        return "investigation", "The question needs discovery, reading and gap following"

    def _bounded(self, result, max_characters):
        """Keep the preflight a pointer layer, not a second context dump."""
        max_characters = max(1000, int(max_characters))
        def size():
            return len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode())
        truncated = False
        while size() > max_characters and result.get("wiki"):
            result["wiki"].pop()
            truncated = True
        while size() > max_characters and result.get("archive"):
            result["archive"].pop()
            truncated = True
        while size() > max_characters and len(result.get("urls") or []) > 1:
            result["urls"].pop()
            truncated = True
        result["preflight_budget"] = {"characters": size(), "max_characters": max_characters,
                                      "truncated": truncated}
        return result

    def build(self, source_id, question, max_cards=3, max_urls=8,
              include_wiki=True, include_archive=True, max_wiki=3, max_archive=5):
        prefs = self._preferences()
        scope = self.index.plan_scope(source_id, question, max_cards=max_cards, max_urls=max_urls,
                                      homepage_limit=prefs.get("plan", {}).get("homepage_limit", 2))
        urls = self.question_urls(question)
        relevance = self.relevance(scope, question)
        freshness = self.freshness(scope, question)
        preflight_terms = relevance["meaningful_terms"] if relevance["accepted"] else []
        if include_wiki and prefs.get("wiki_preflight", True) and preflight_terms:
            wiki, wiki_error = self.wiki_preflight(preflight_terms, max_wiki)
        else:
            wiki, wiki_error = [], None
        if include_archive and preflight_terms:
            archive, archive_error = self.archive_preflight(preflight_terms, max_archive)
        else:
            archive, archive_error = [], None
        priority = self.priority_terms(scope, relevance["meaningful_terms"])
        if priority:
            wiki = [row for row in wiki if set(row.get("matched_terms") or []) & priority]
            archive = [row for row in archive if set(row.get("matched_terms") or []) & priority]
        shape, reason = self.task_shape(question, scope["urls"], scope.get("term_cards"))
        fetch = {"owner": "plugin", "fallback": "host",
                 "max_total_characters": prefs.get("fetch", {}).get("max_total_characters", 24000),
                 "reason": "URLs will be cited" if scope.get("urls") else "No URL selected"}
        base = {**scope, "question_urls": urls, "relevance": relevance, "wiki": wiki,
                "archive": archive, "freshness": freshness, "fetch": fetch,
                "task_shape": shape, "task_shape_reason": reason}
        errors = [error for error in (wiki_error, archive_error) if error]
        if errors:
            base["preflight_errors"] = errors
        if not relevance["accepted"] and not urls:
            base.update(cards=[], urls=[], depth=None, route=None, route_id=None, entrypoint=None)
            base["next_action"] = {"reason": relevance["reason"]}
            return self._bounded(base, prefs.get("plan", {}).get("max_characters", 8000))
        route = self.routing.route(task_shape=shape, host="unknown", depth=None)
        selected = route["selected"]
        base.update(depth=route["depth"], route=selected["route"] if selected else None,
                    route_id=selected["route_id"] if selected else None,
                    entrypoint=selected.get("entrypoint") if selected else None,
                    next_action=route["next_action"])
        return self._bounded(base, prefs.get("plan", {}).get("max_characters", 8000))
