import logging
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from shared import models
from . import vector_db
from .subject_utils import normalize_subject

logger = logging.getLogger(__name__)

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_+#.-]+|[\u4e00-\u9fff]{1,}")
FORMULA_PATTERN = re.compile(r"(\$[^$]+\$|\\(?:frac|sqrt|int|sum|sin|cos|tan|log|ln)[^\n]{0,120}|[A-Za-z0-9]+\s*[=≤≥]\s*[A-Za-z0-9]+)")
CHOICE_PATTERN = re.compile(r"[A-HＡ-Ｈ]")
KNOWLEDGE_ANCHOR_TYPES = [
    "knowledge_point",
    "knowledge_block",
    "knowledge_atom",
    "question_knowledge",
    "knowledge_question_bridge",
    "knowledge_derivative",
]


class ExamSessionMatchingService:
    def match_exam_session(
        self,
        db: Session,
        exam_session_id: int,
        top_k: int = 5,
        accept_threshold: float = 0.78,
        min_gap: float = 0.05,
    ) -> Dict[str, object]:
        exam_session = db.query(models.ExamSession).filter(models.ExamSession.id == exam_session_id).first()
        if not exam_session:
            raise ValueError(f"ExamSession {exam_session_id} 不存在")

        exam_questions = (
            db.query(models.ExamSessionQuestion)
            .filter(models.ExamSessionQuestion.exam_session_id == exam_session_id)
            .order_by(models.ExamSessionQuestion.id.asc())
            .all()
        )
        if not exam_questions:
            raise ValueError(f"ExamSession {exam_session_id} 没有可匹配的题目")

        exam_session.matching_status = "running"
        db.commit()

        exam_question_ids = [question.id for question in exam_questions]
        db.query(models.QuestionMatchResult).filter(models.QuestionMatchResult.exam_question_id.in_(exam_question_ids)).delete(
            synchronize_session=False
        )
        db.commit()

        matched_count = 0
        pending_review_count = 0
        dominant_paper_scores: Dict[int, float] = defaultdict(float)
        question_summaries: List[Dict[str, object]] = []

        try:
            for exam_question in exam_questions:
                question_summary = self._match_single_question(
                    db=db,
                    exam_session=exam_session,
                    exam_question=exam_question,
                    top_k=top_k,
                    accept_threshold=accept_threshold,
                    min_gap=min_gap,
                )
                question_summaries.append(question_summary)

                if question_summary.get("accepted_question_item_id"):
                    matched_count += 1
                    paper_id = question_summary.get("accepted_paper_id")
                    if paper_id:
                        dominant_paper_scores[int(paper_id)] += float(question_summary.get("accepted_score") or 0.0)
                else:
                    pending_review_count += 1

            exam_session.matched_paper_id = (
                max(dominant_paper_scores.items(), key=lambda item: item[1])[0] if dominant_paper_scores else None
            )
            exam_session.matching_status = "completed"
            db.commit()
            return {
                "status": "success",
                "exam_session_id": exam_session_id,
                "matched_paper_id": exam_session.matched_paper_id,
                "matched_question_count": matched_count,
                "pending_review_count": pending_review_count,
                "question_count": len(exam_questions),
                "questions": question_summaries,
            }
        except Exception:
            exam_session.matching_status = "failed"
            db.commit()
            logger.exception("Failed to match exam session %s", exam_session_id)
            raise

    def _match_single_question(
        self,
        db: Session,
        exam_session: models.ExamSession,
        exam_question: models.ExamSessionQuestion,
        top_k: int,
        accept_threshold: float,
        min_gap: float,
    ) -> Dict[str, object]:
        query_text = self._build_query_text(exam_question)
        attempts = (
            db.query(models.StudentAttempt)
            .filter(models.StudentAttempt.exam_question_id == exam_question.id)
            .order_by(models.StudentAttempt.id.asc())
            .all()
        )
        primary_attempt = attempts[0] if attempts else None
        normalized_subject = normalize_subject(exam_session.subject)

        exam_question.question_item_id = None
        exam_question.match_confidence = None

        if not query_text:
            exam_question.review_status = "needs_review"
            self._sync_attempt(primary_attempt, None)
            db.commit()
            anchor_pack = {
                "primary_anchor_type": "unanchored",
                "exact_match": None,
                "structural_matches": [],
                "knowledge_anchors": [],
                "diagnostics": {"status": "empty_query", "exact_failure_reason": "empty_query"},
            }
            return {
                "exam_question_id": exam_question.id,
                "source_question_no": exam_question.source_question_no,
                "status": "skipped",
                "accepted_question_item_id": None,
                "accepted_paper_id": None,
                "accepted_score": None,
                "reason": "empty_query",
                "match_anchors": anchor_pack,
            }

        search_results = vector_db.db.hybrid_search_with_scores(
            query_text,
            n_results=max(top_k * 6, top_k),
            entity_types=["question_stem"],
            metadata_filters={"subject": normalized_subject} if normalized_subject else None,
        )
        candidates = self._build_candidate_scores(
            db=db,
            exam_session=exam_session,
            exam_question=exam_question,
            query_text=query_text,
            search_results=search_results,
            top_k=top_k,
        )
        accepted_candidate = self._pick_accepted_candidate(candidates, accept_threshold=accept_threshold, min_gap=min_gap)
        structural_matches = self._pick_structural_matches(candidates, accepted_candidate=accepted_candidate)
        knowledge_anchors = self._build_knowledge_anchors(query_text=query_text, subject=normalized_subject)
        anchor_pack = self._build_match_anchor_pack(
            query_text=query_text,
            candidates=candidates,
            accepted_candidate=accepted_candidate,
            structural_matches=structural_matches,
            knowledge_anchors=knowledge_anchors,
            exact_failure_reason=self._diagnose_exact_rejection(
                candidates=candidates,
                accepted_candidate=accepted_candidate,
                accept_threshold=accept_threshold,
                min_gap=min_gap,
            ),
        )
        structural_ids = {int(item["candidate_question_id"]) for item in structural_matches}

        for candidate in candidates:
            match_type = "exact_candidate"
            if accepted_candidate and candidate["candidate_question_id"] == accepted_candidate["candidate_question_id"]:
                match_type = "exact_match"
            elif candidate["candidate_question_id"] in structural_ids:
                match_type = "structural_candidate"
            db.add(
                models.QuestionMatchResult(
                    exam_question_id=exam_question.id,
                    candidate_question_id=candidate["candidate_question_id"],
                    match_type=match_type,
                    text_score=candidate["text_score"],
                    vector_score=candidate["vector_score"],
                    formula_score=candidate["formula_score"],
                    final_score=candidate["final_score"],
                    accepted=False,
                )
            )
        db.flush()

        if accepted_candidate:
            accepted_row = (
                db.query(models.QuestionMatchResult)
                .filter(models.QuestionMatchResult.exam_question_id == exam_question.id)
                .filter(models.QuestionMatchResult.candidate_question_id == accepted_candidate["candidate_question_id"])
                .first()
            )
            if accepted_row:
                accepted_row.accepted = True

            exam_question.question_item_id = accepted_candidate["candidate_question_id"]
            exam_question.match_confidence = accepted_candidate["final_score"]
            exam_question.review_status = "matched"
            matched_item = accepted_candidate["candidate_question"]
            self._sync_attempt(primary_attempt, matched_item)
            db.commit()
            return {
                "exam_question_id": exam_question.id,
                "source_question_no": exam_question.source_question_no,
                "status": "matched",
                "accepted_question_item_id": accepted_candidate["candidate_question_id"],
                "accepted_paper_id": accepted_candidate.get("paper_id"),
                "accepted_score": accepted_candidate["final_score"],
                "match_anchors": anchor_pack,
            }

        exam_question.review_status = "needs_review"
        exam_question.match_confidence = candidates[0]["final_score"] if candidates else None
        self._sync_attempt(primary_attempt, None)
        db.commit()
        return {
            "exam_question_id": exam_question.id,
            "source_question_no": exam_question.source_question_no,
            "status": "needs_review",
            "accepted_question_item_id": None,
            "accepted_paper_id": None,
            "accepted_score": candidates[0]["final_score"] if candidates else None,
            "match_anchors": anchor_pack,
        }

    def _build_candidate_scores(
        self,
        db: Session,
        exam_session: models.ExamSession,
        exam_question: models.ExamSessionQuestion,
        query_text: str,
        search_results: List[Dict[str, object]],
        top_k: int,
    ) -> List[Dict[str, object]]:
        del exam_question
        deduped_hits: Dict[int, Dict[str, object]] = {}
        for raw_hit in search_results:
            metadata = raw_hit.get("metadata") or {}
            entity_type = metadata.get("entity_type")
            if entity_type != "question_stem":
                continue
            candidate_question_id = self._safe_int(metadata.get("entity_id"))
            if not candidate_question_id:
                continue
            hit_subject = normalize_subject(metadata.get("subject"))
            exam_subject = normalize_subject(exam_session.subject)
            if exam_subject and hit_subject and hit_subject != exam_subject:
                continue
            current_score = float(raw_hit.get("score") or 0.0)
            previous = deduped_hits.get(candidate_question_id)
            if not previous or current_score > float(previous.get("score") or 0.0):
                deduped_hits[candidate_question_id] = raw_hit

        candidate_ids = list(deduped_hits.keys())
        if not candidate_ids:
            return []

        question_items = (
            db.query(models.QuestionItem)
            .filter(models.QuestionItem.id.in_(candidate_ids))
            .all()
        )
        question_item_map = {item.id: item for item in question_items}

        candidate_paper_rows = (
            db.query(models.PaperQuestion.question_item_id, models.PaperQuestion.paper_id)
            .filter(models.PaperQuestion.question_item_id.in_(candidate_ids))
            .all()
        )
        paper_map: Dict[int, int] = {}
        for question_item_id, paper_id in candidate_paper_rows:
            paper_map.setdefault(question_item_id, paper_id)

        query_tokens = self._tokenize(query_text)
        query_formula_signatures = self._extract_formula_signatures(query_text)
        scored_candidates: List[Dict[str, object]] = []
        for candidate_question_id, raw_hit in deduped_hits.items():
            question_item = question_item_map.get(candidate_question_id)
            if not question_item:
                continue

            reranker_score = raw_hit.get("reranker_score")
            has_reranker = reranker_score is not None
            vector_score = round(float(raw_hit.get("vector_score") or 0.0), 4)
            bm25_score = round(float(raw_hit.get("text_score") or 0.0), 4)
            overlap_score = round(
                self._text_overlap_score(query_tokens, self._tokenize(question_item.stem_plain_text or "")),
                4,
            )
            text_score = round((bm25_score * 0.55) + (overlap_score * 0.45), 4)
            formula_score = round(
                self._formula_overlap_score(
                    query_formula_signatures,
                    self._extract_formula_signatures(question_item.stem_plain_text or ""),
                ),
                4,
            )
            if has_reranker:
                # Cross-encoder score (0-1 scale) replaces RRF contributions which are
                # compressed into ~[0.012, 0.017] and incompatible with the 0.78 threshold.
                final_score = round((float(reranker_score) * 0.70) + (overlap_score * 0.20) + (formula_score * 0.10), 4)
                # Surface the reranker score as vector_score so similarity_reason works.
                vector_score = round(float(reranker_score), 4)
            else:
                final_score = round((vector_score * 0.58) + (text_score * 0.32) + (formula_score * 0.10), 4)
            scored_candidates.append(
                {
                    "candidate_question_id": candidate_question_id,
                    "candidate_question": question_item,
                    "paper_id": paper_map.get(candidate_question_id),
                    "match_type": "exact_candidate",
                    "text_score": text_score,
                    "vector_score": vector_score,
                    "overlap_score": overlap_score,
                    "formula_score": formula_score,
                    "final_score": final_score,
                    "similarity_reason": self._build_similarity_reason(
                        overlap_score=overlap_score,
                        formula_score=formula_score,
                        vector_score=vector_score,
                    ),
                }
            )

        return sorted(scored_candidates, key=lambda item: item["final_score"], reverse=True)[:top_k]


    def _pick_accepted_candidate(
        self,
        candidates: Sequence[Dict[str, object]],
        accept_threshold: float,
        min_gap: float,
    ) -> Optional[Dict[str, object]]:
        if not candidates:
            return None

        best_candidate = candidates[0]
        best_score = float(best_candidate.get("final_score") or 0.0)
        second_score = float(candidates[1].get("final_score") or 0.0) if len(candidates) > 1 else 0.0
        overlap_score = float(best_candidate.get("overlap_score") or 0.0)
        if best_score < accept_threshold:
            return None
        if len(candidates) > 1:
            gap = best_score - second_score
            # Scale-adaptive gap: the cross-encoder produces reliable confidence scores
            # in [0,1].  Near-duplicate questions in the bank all score similarly — when
            # absolute confidence is high, any of the top candidates is a valid match.
            if best_score >= 0.78:
                effective_min_gap = 0.0   # threshold-level confidence: gap irrelevant
            elif best_score >= 0.65:
                effective_min_gap = 0.02
            else:
                effective_min_gap = float(min_gap)
            if gap < effective_min_gap:
                return None
        # 向量高但字面重合过低时容易把”同学科同题型”误绑成标准题。
        if overlap_score < 0.45:
            return None
        return best_candidate

    def _pick_structural_matches(
        self,
        candidates: Sequence[Dict[str, object]],
        *,
        accepted_candidate: Optional[Dict[str, object]],
        limit: int = 3,
    ) -> List[Dict[str, object]]:
        accepted_id = accepted_candidate["candidate_question_id"] if accepted_candidate else None
        structural: List[Dict[str, object]] = []
        for candidate in candidates:
            if accepted_id and candidate["candidate_question_id"] == accepted_id:
                continue
            final_score = float(candidate.get("final_score") or 0.0)
            overlap_score = float(candidate.get("overlap_score") or 0.0)
            formula_score = float(candidate.get("formula_score") or 0.0)
            if final_score < 0.6 and overlap_score < 0.3 and formula_score <= 0.0:
                continue
            structural.append(candidate)
            if len(structural) >= limit:
                break
        return structural

    def _build_knowledge_anchors(
        self,
        *,
        query_text: str,
        subject: Optional[str],
        limit: int = 4,
    ) -> List[Dict[str, object]]:
        if not self._normalize_text(query_text):
            return []
        try:
            hits = vector_db.db.hybrid_search_with_scores(
                query_text,
                n_results=max(limit * 2, limit),
                entity_types=KNOWLEDGE_ANCHOR_TYPES,
                metadata_filters={"subject": subject} if subject else None,
            )
        except Exception:
            logger.exception("Failed to build knowledge anchors")
            return []

        anchors: List[Dict[str, object]] = []
        seen = set()
        for hit in hits:
            metadata = hit.get("metadata") or {}
            dedupe_key = (
                str(metadata.get("entity_type") or ""),
                str(metadata.get("entity_id") or hit.get("id") or ""),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            anchors.append(
                {
                    "anchor_type": "knowledge_anchor",
                    "source_type": str(metadata.get("entity_type") or hit.get("source_type") or "knowledge"),
                    "source_id": str(metadata.get("entity_id") or hit.get("id") or ""),
                    "title": str(
                        metadata.get("title")
                        or metadata.get("canonical_name")
                        or metadata.get("source")
                        or metadata.get("entity_type")
                        or "knowledge_anchor"
                    ),
                    "snippet": self._truncate_text(hit.get("snippet") or hit.get("content") or "", max_length=180),
                    "score": round(float(hit.get("score") or 0.0), 4),
                    "knowledge_point_id": self._safe_int(metadata.get("knowledge_point_id")),
                    "metadata": metadata,
                }
            )
            if len(anchors) >= limit:
                break
        return anchors

    def _build_match_anchor_pack(
        self,
        *,
        query_text: str,
        candidates: Sequence[Dict[str, object]],
        accepted_candidate: Optional[Dict[str, object]],
        structural_matches: Sequence[Dict[str, object]],
        knowledge_anchors: Sequence[Dict[str, object]],
        exact_failure_reason: Optional[str],
    ) -> Dict[str, object]:
        exact_match = self._format_question_anchor(accepted_candidate, anchor_type="exact_match") if accepted_candidate else None
        structural = [
            self._format_question_anchor(item, anchor_type="structural_match")
            for item in structural_matches
        ]
        primary_anchor_type = "unanchored"
        if exact_match:
            primary_anchor_type = "exact_match"
        elif structural:
            primary_anchor_type = "structural_match"
        elif knowledge_anchors:
            primary_anchor_type = "knowledge_anchor"
        return {
            "primary_anchor_type": primary_anchor_type,
            "exact_match": exact_match,
            "structural_matches": structural,
            "knowledge_anchors": list(knowledge_anchors),
            "diagnostics": {
                "query_text": self._truncate_text(query_text, max_length=220),
                "exact_candidate_count": len(candidates),
                "structural_match_count": len(structural),
                "knowledge_anchor_count": len(knowledge_anchors),
                "exact_failure_reason": exact_failure_reason,
                "top_exact_score": round(float(candidates[0].get("final_score") or 0.0), 4) if candidates else None,
            },
        }

    def _format_question_anchor(
        self,
        candidate: Optional[Dict[str, object]],
        *,
        anchor_type: str,
    ) -> Optional[Dict[str, object]]:
        if not candidate:
            return None
        question_item = candidate.get("candidate_question")
        return {
            "anchor_type": anchor_type,
            "question_item_id": int(candidate["candidate_question_id"]),
            "paper_id": self._safe_int(candidate.get("paper_id")),
            "final_score": round(float(candidate.get("final_score") or 0.0), 4),
            "text_score": round(float(candidate.get("text_score") or 0.0), 4),
            "vector_score": round(float(candidate.get("vector_score") or 0.0), 4),
            "overlap_score": round(float(candidate.get("overlap_score") or 0.0), 4),
            "formula_score": round(float(candidate.get("formula_score") or 0.0), 4),
            "candidate_subject": getattr(question_item, "subject", None),
            "candidate_grade": getattr(question_item, "grade", None),
            "candidate_question_type": getattr(question_item, "question_type", None),
            "candidate_stem": getattr(question_item, "stem_plain_text", None),
            "candidate_answer": getattr(question_item, "answer_text", None),
            "similarity_reason": candidate.get("similarity_reason"),
        }

    def _diagnose_exact_rejection(
        self,
        *,
        candidates: Sequence[Dict[str, object]],
        accepted_candidate: Optional[Dict[str, object]],
        accept_threshold: float,
        min_gap: float,
    ) -> Optional[str]:
        if accepted_candidate:
            return None
        if not candidates:
            return "no_exact_candidates"
        best_score = float(candidates[0].get("final_score") or 0.0)
        second_score = float(candidates[1].get("final_score") or 0.0) if len(candidates) > 1 else 0.0
        overlap_score = float(candidates[0].get("overlap_score") or 0.0)
        if best_score < accept_threshold:
            return "below_exact_threshold"
        if len(candidates) > 1:
            gap = best_score - second_score
            if best_score >= 0.78:
                effective_min_gap = 0.0
            elif best_score >= 0.65:
                effective_min_gap = 0.02
            else:
                effective_min_gap = float(min_gap)
            if gap < effective_min_gap:
                return "exact_gap_too_small"
        if overlap_score < 0.45:
            return "overlap_too_low"
        return "exact_not_accepted"

    def _build_similarity_reason(
        self,
        *,
        overlap_score: float,
        formula_score: float,
        vector_score: float,
    ) -> str:
        reasons: List[str] = []
        if overlap_score >= 0.6:
            reasons.append("题干关键词重合较高")
        elif overlap_score >= 0.4:
            reasons.append("题干关键词有一定重合")
        if formula_score >= 0.5:
            reasons.append("公式骨架接近")
        if vector_score >= 0.8:
            reasons.append("语义检索相似度高")
        return "；".join(reasons) or "题型/语义相近"

    def build_anchor_pack_from_persisted_candidates(
        self,
        db: Session,
        *,
        exam_session: models.ExamSession,
        exam_question: models.ExamSessionQuestion,
        candidates: Optional[Sequence[Dict[str, object]]] = None,
    ) -> Dict[str, object]:
        query_text = self._build_query_text(exam_question)
        candidate_payloads = list(candidates or self._load_persisted_candidates(db, exam_question.id, query_text=query_text))
        accepted_candidate = next((item for item in candidate_payloads if item.get("accepted")), None)
        structural_matches = self._pick_structural_matches(candidate_payloads, accepted_candidate=accepted_candidate)
        knowledge_anchors = self._build_knowledge_anchors(
            query_text=query_text,
            subject=normalize_subject(exam_session.subject),
        )
        return self._build_match_anchor_pack(
            query_text=query_text,
            candidates=candidate_payloads,
            accepted_candidate=accepted_candidate,
            structural_matches=structural_matches,
            knowledge_anchors=knowledge_anchors,
            exact_failure_reason=self._diagnose_exact_rejection(
                candidates=candidate_payloads,
                accepted_candidate=accepted_candidate,
                accept_threshold=0.78,
                min_gap=0.05,
            ),
        )

    def _load_persisted_candidates(self, db: Session, exam_question_id: int, *, query_text: str) -> List[Dict[str, object]]:
        rows = (
            db.query(models.QuestionMatchResult)
            .filter(models.QuestionMatchResult.exam_question_id == exam_question_id)
            .order_by(models.QuestionMatchResult.final_score.desc())
            .all()
        )
        candidate_ids = list({row.candidate_question_id for row in rows})
        question_item_map = {
            item.id: item for item in db.query(models.QuestionItem).filter(models.QuestionItem.id.in_(candidate_ids)).all()
        } if candidate_ids else {}
        paper_rows = (
            db.query(models.PaperQuestion.question_item_id, models.PaperQuestion.paper_id)
            .filter(models.PaperQuestion.question_item_id.in_(candidate_ids))
            .all()
        ) if candidate_ids else []
        paper_map: Dict[int, int] = {}
        for question_item_id, paper_id in paper_rows:
            paper_map.setdefault(question_item_id, paper_id)

        query_tokens = self._tokenize(query_text)
        query_formula_signatures = self._extract_formula_signatures(query_text)
        payloads: List[Dict[str, object]] = []
        for row in rows:
            question_item = question_item_map.get(row.candidate_question_id)
            overlap_score = self._text_overlap_score(query_tokens, self._tokenize(question_item.stem_plain_text or "")) if question_item else 0.0
            formula_score = self._formula_overlap_score(
                query_formula_signatures,
                self._extract_formula_signatures(question_item.stem_plain_text or "") if question_item else [],
            )
            payloads.append(
                {
                    "candidate_question_id": int(row.candidate_question_id),
                    "candidate_question": question_item,
                    "paper_id": paper_map.get(int(row.candidate_question_id)),
                    "match_type": row.match_type,
                    "text_score": float(row.text_score or 0.0),
                    "vector_score": float(row.vector_score or 0.0),
                    "overlap_score": round(overlap_score, 4),
                    "formula_score": round(float(row.formula_score or formula_score), 4),
                    "final_score": float(row.final_score or 0.0),
                    "accepted": bool(row.accepted),
                    "similarity_reason": self._build_similarity_reason(
                        overlap_score=overlap_score,
                        formula_score=formula_score,
                        vector_score=float(row.vector_score or 0.0),
                    ),
                }
            )
        return payloads

    def _sync_attempt(self, attempt: Optional[models.StudentAttempt], matched_question: Optional[models.QuestionItem]) -> None:
        if not attempt:
            return
        attempt.question_item_id = matched_question.id if matched_question else None
        attempt.is_correct = self._infer_correctness(
            attempt.student_answer_raw,
            matched_question.answer_text if matched_question else None,
        ) if matched_question else None

    def _infer_correctness(self, student_answer_raw: Optional[str], standard_answer: Optional[str]) -> Optional[bool]:
        if not student_answer_raw or not standard_answer:
            return None

        student_choice = self._normalize_choice_answer(student_answer_raw)
        standard_choice = self._normalize_choice_answer(standard_answer)
        if student_choice and standard_choice:
            return student_choice == standard_choice

        normalized_student = self._normalize_text(student_answer_raw)
        normalized_standard = self._normalize_text(standard_answer)
        if not normalized_student or not normalized_standard:
            return None
        return normalized_student == normalized_standard

    def _build_query_text(self, exam_question: models.ExamSessionQuestion) -> str:
        return self._normalize_text(exam_question.recognized_text or "")

    def _tokenize(self, text: str) -> List[str]:
        return [token.lower() for token in TOKEN_PATTERN.findall(text or "") if token.strip()]

    def _text_overlap_score(self, query_tokens: Sequence[str], candidate_tokens: Sequence[str]) -> float:
        if not query_tokens or not candidate_tokens:
            return 0.0
        query_set = set(query_tokens)
        candidate_set = set(candidate_tokens)
        if not query_set:
            return 0.0
        return len(query_set & candidate_set) / len(query_set)

    def _extract_formula_signatures(self, text: str) -> List[str]:
        signatures = []
        for raw_formula in FORMULA_PATTERN.findall(text or ""):
            normalized = re.sub(r"\s+", "", raw_formula).lower()
            if normalized and normalized not in signatures:
                signatures.append(normalized)
        return signatures

    def _formula_overlap_score(self, query_formulas: Sequence[str], candidate_formulas: Sequence[str]) -> float:
        if not query_formulas:
            return 0.0
        query_set = set(query_formulas)
        candidate_set = set(candidate_formulas)
        if not query_set or not candidate_set:
            return 0.0
        return len(query_set & candidate_set) / len(query_set)

    def _normalize_choice_answer(self, text: str) -> str:
        normalized = text.translate(str.maketrans("ＡＢＣＤＥＦＧＨａｂｃｄｅｆｇｈ", "ABCDEFGHabcdefgh"))
        choices = CHOICE_PATTERN.findall(normalized.upper())
        return "".join(sorted(set(choice.upper() for choice in choices)))

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    def _truncate_text(self, text: str, max_length: int = 180) -> str:
        normalized = self._normalize_text(text)
        if len(normalized) <= max_length:
            return normalized
        return normalized[: max_length - 3] + "..."

    def _safe_int(self, value: object) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


service = ExamSessionMatchingService()
