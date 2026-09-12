"""Offline coverage of frozen research inputs, separate from host execution."""


class ResearchCoverage:
    """Recheck current evidence rather than trusting a saved completion flag."""

    FILTERS = ("all", "missing", "unread", "unreviewed", "blocked", "excluded", "reviewed")
    ACTIVE_RUNS = ("pending", "queued", "in_progress", "unknown_outcome")

    def __init__(self, state, read_body):
        self.state = state
        self.read_body = read_body
        self.sources = {row["id"]: row for row in state["sources"]}
        self.claims = {row["id"]: row for row in state["claims"]}
        self.questions = {row["id"]: row for row in state["questions"]}
        self.bodies = {}

    def _body(self, identifier):
        if identifier not in self.bodies:
            source = self.sources.get(identifier)
            try:
                if source is None:
                    raise ValueError("Unknown evidence source: " + str(identifier))
                self.bodies[identifier] = (self.read_body(source), None)
            except (OSError, ValueError, UnicodeError) as error:
                self.bodies[identifier] = (None, str(error))
        return self.bodies[identifier]

    def source_issues(self, identifier, inventory_id=None, accepted=False):
        source = self.sources.get(identifier)
        body, error = self._body(identifier)
        issues = [error] if error else []
        if source is None:
            return issues
        verdict = source.get("review", {}).get("verdict", "unreviewed")
        if verdict == "rejected" or (accepted and verdict != "accepted"):
            issues.append("Source %s is not accepted after content review" % identifier)
        if inventory_id is not None:
            if source.get("evidence_kind", "page") == "external_report":
                issues.append("An external report does not establish that its cited original page was read")
            if inventory_id not in source.get("inventory_ids", []):
                issues.append("Source %s is not linked to this original URL" % identifier)
        return issues

    def citation_issues(self, citation, accepted=False):
        identifier = citation["source_id"]
        issues = self.source_issues(identifier, accepted=accepted)
        body, error = self._body(identifier)
        if not error and citation["quote"] not in body:
            issues.append("Quote is absent from saved source " + identifier)
        source = self.sources.get(identifier)
        if source and citation.get("source_sha256", source["sha256"]) != source["sha256"]:
            issues.append("Citation snapshot changed for source " + identifier)
        return issues

    def claim_issues(self, identifier, accepted=False):
        claim = self.claims.get(identifier)
        if claim is None:
            return ["Unknown claim: " + str(identifier)]
        if claim.get("status") == "retracted":
            return ["Retracted claim: " + identifier]
        issues = []
        for citation in claim["citations"]:
            issues.extend(self.citation_issues(citation, accepted=accepted))
        if not claim["citations"]:
            issues.append("Claim has no citations: " + identifier)
        return issues

    def review_issues(self, review):
        if review["disposition"] != "reviewed":
            return []
        issues = []
        identifier = review["inventory_id"]
        for source_id in review["source_ids"]:
            issues.extend(self.source_issues(source_id, inventory_id=identifier, accepted=True))
        for question_id in review["question_ids"]:
            if question_id not in self.questions:
                issues.append("Unknown review question: " + question_id)
        for citation in review["citations"]:
            if citation["source_id"] not in review["source_ids"]:
                issues.append("A review citation must refer to its declared original-page sources")
            issues.extend(self.citation_issues(citation, accepted=True))
        for claim_id in review["claim_ids"]:
            issues.extend(self.claim_issues(claim_id, accepted=True))
            claim = self.claims.get(claim_id)
            if claim is not None:
                if claim["question_id"] not in review["question_ids"]:
                    issues.append("Review claims must belong to its declared questions")
                if not any(citation["source_id"] in review["source_ids"] for citation in claim["citations"]):
                    issues.append("A review claim must cite this original page")
        if not review["source_ids"] or not review["question_ids"] or not (review["citations"] or review["claim_ids"]):
            issues.append("Substantive review needs a question, accepted original-page text and a quoted judgment")
        return list(dict.fromkeys(issues))

    @staticmethod
    def _metric(count, total):
        return {"count": count, "total": total, "rate": count / total if total else None}

    def evaluate(self):
        reviews = {row["inventory_id"]: row for row in self.state.get("inventory_reviews", [])}
        rows = []
        for entry in self.state.get("inventory", []):
            identifier = entry["id"]
            review = reviews.get(identifier)
            source_ids = [source["id"] for source in self.sources.values()
                          if identifier in source.get("inventory_ids", [])
                          and source.get("evidence_kind", "page") != "external_report"]
            usable_ids = [source_id for source_id in source_ids
                          if not self.source_issues(source_id, inventory_id=identifier, accepted=True)]
            issues = self.review_issues(review) if review else []
            disposition = review["disposition"] if review else "unreviewed"
            excluded = disposition == "excluded"
            substantive = disposition == "reviewed" and not issues
            accounted = bool(review or source_ids)
            rows.append({"id": identifier, "original_url": entry["original_url"],
                         "source_ids": source_ids, "usable_source_ids": usable_ids,
                         "disposition": disposition, "review": review, "issues": issues,
                         "accounted_for": accounted, "usable_text": bool(usable_ids),
                         "substantive_review": substantive,
                         "missing": not accounted, "unread": not excluded and not usable_ids,
                         "unreviewed": not excluded and not substantive,
                         "blocked": disposition == "blocked" or bool(issues),
                         "excluded": excluded, "reviewed": substantive})
        question_rows = []
        for question in self.questions.values():
            issues = []
            if question["status"] == "answered":
                if not question["claim_ids"]:
                    issues.append("The answer has no supporting claim")
                for claim_id in question["claim_ids"]:
                    issues.extend(self.claim_issues(claim_id))
            question_rows.append({"id": question["id"], "status": question["status"],
                "complete": question["status"] == "answered" and not issues,
                "gap": question.get("gap"), "issues": list(dict.fromkeys(issues))})
        metrics = {key: self._metric(sum(bool(row[key]) for row in rows), len(rows))
                   for key in ("accounted_for", "usable_text", "substantive_review")}
        metrics["question_completion"] = self._metric(sum(row["complete"] for row in question_rows), len(question_rows))
        scope = self.state.get("source_scope")
        blockers = []
        if scope is None and self.state.get("source_ids"):
            blockers.append("Legacy session has no frozen inventory; whole-input coverage is unavailable")
        if rows:
            if any(row["unreviewed"] for row in rows):
                blockers.append("Original input URLs still need substantive review")
            if not any(row["substantive_review"] for row in rows):
                blockers.append("No original input has a substantive, evidence-backed review")
        if any(not row["complete"] for row in question_rows):
            blockers.append("Research questions remain unanswered or their evidence is invalid")
        if any(row["status"] == "open" for row in self.state["conflicts"]):
            blockers.append("Unresolved evidence conflicts remain")
        if any(row["status"] == "pending" for row in self.state["operations"]):
            blockers.append("An interrupted operation needs acknowledgement")
        if any(row["status"] in self.ACTIVE_RUNS for row in self.state.get("external_runs", [])):
            blockers.append("An external run still has a pending or unknown outcome")
        return {"available": scope is not None, "source_scope": scope,
                "legacy_note": None if scope is not None else "No input snapshot was captured by this legacy session; no scope is inferred from its previews or labels.",
                "metrics": metrics, "difference_counts": {key: sum(bool(row[key]) for row in rows)
                    for key in self.FILTERS if key != "all"},
                "completion_ready": not blockers, "completion_blockers": blockers,
                "questions": question_rows, "rows": rows}
