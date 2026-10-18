"""Suggest a research route from one question and the local package scope.

Local only. It reads the indexed package, ranks the cards and bookmarks the
question touches, and forwards that to the same route vocabulary
``research_route`` uses, so the two entrypoints cannot drift apart. It never
fetches, never starts a research session and never widens the requested scope.
"""

import re

from bookmark_index import question_urls
from routing import ResearchRouting
from settings import Settings


DOCUMENTATION_HOSTS = ("github.com", "gitlab.com", "docs.python.org", "developer.mozilla.org", "readthedocs.io")
DEPTH_TERMS = ("深度", "核验", "核实", "报告", "对比", "比较", "审查", "评估",
               "deep", "report", "verify", "audit", "compare", "evaluate", "benchmark")


class ResearchPlan:
    """Compose ``BookmarkIndex.plan_scope`` with the existing router."""

    def __init__(self, index, settings=None, routing=None):
        self.index = index
        self.settings = settings if settings is not None else Settings()
        self.routing = routing if routing is not None else ResearchRouting(self.settings)

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

    def task_shape(self, question, urls, term_cards=None):
        """Which of the router's three task shapes the question describes.

        A documentation or repository bookmark only makes this a ``lookup`` when
        the question names it: some term of the question reaches exactly one
        canonical tree (``term_cards``) and that term matched the URL's own rows.
        An incidental docs hit next to a broad topic question stays evidence and
        does not downgrade the route.
        """
        if self.question_urls(question):
            return "lookup", "The question already contains a URL"
        naming = {term for term, count in (term_cards or {}).items() if count == 1}
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

    def build(self, source_id, question, max_cards=3, max_urls=8):
        scope = self.index.plan_scope(source_id, question, max_cards=max_cards, max_urls=max_urls)
        urls = self.question_urls(question)
        shape, reason = self.task_shape(question, scope["urls"], scope.get("term_cards"))
        base = {**scope, "question_urls": urls, "task_shape": shape, "task_shape_reason": reason}
        if not scope["cards"] and not urls:
            # Nothing in the package matches and the question carries no URL:
            # suggest no route at all, so the host reports the miss instead of
            # silently widening the scope (contract: cards [] -> route null).
            return {**base, "depth": None, "route": None, "route_id": None, "entrypoint": None,
                    "next_action": {"reason": "No card in this source matches the question terms. "
                    "Report that the package has nothing on them and ask before widening the scope."}}
        # depth=None lets the router read the saved research.depth preference.
        route = self.routing.route(task_shape=shape, host="unknown", depth=None)
        selected = route["selected"]
        return {**base, "depth": route["depth"], "route": selected["route"] if selected else None,
                "route_id": selected["route_id"] if selected else None,
                "entrypoint": selected.get("entrypoint") if selected else None,
                "next_action": route["next_action"]}
