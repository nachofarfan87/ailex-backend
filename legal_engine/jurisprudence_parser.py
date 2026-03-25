"""
AILEX -- heuristic parser for Argentine judicial decisions.

This parser is intentionally conservative:
- it works on plain text already extracted from the decision;
- it detects recurring structural blocks using maintainable heuristics;
- it never fabricates missing content;
- it returns a structure compatible with the local jurisprudence corpus.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


SECTION_PATTERNS = {
    "autos_y_vistos": re.compile(
        r"^\s*(autos\s+y\s+vistos|autos\s+y\s+visto)\s*:?\s*$",
        re.IGNORECASE,
    ),
    "resulta": re.compile(r"^\s*(resulta|antecedentes)\s*:?\s*$", re.IGNORECASE),
    "considerando": re.compile(r"^\s*considerando\s*:?\s*$", re.IGNORECASE),
    "fundamentos": re.compile(r"^\s*fundamentos\s*:?\s*$", re.IGNORECASE),
    "resuelve": re.compile(
        r"^\s*((r\s*e\s*s\s*u\s*e\s*l\s*v\s*e)|resuelve|resuelvo|por\s+ello|parte\s+dispositiva)\s*:?\s*$",
        re.IGNORECASE,
    ),
}

MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

ACTION_HINTS = (
    ("cuidado_personal", ("cuidado personal", "regimen de cuidado", "atribucion del cuidado")),
    ("alimentos_hijos", ("alimentos", "cuota alimentaria", "cuota provisoria", "alimento provisorio")),
    ("sucesion_ab_intestato", ("sucesion", "sucesorio", "declaratoria de herederos", "ab intestato")),
    ("divorcio", ("divorcio", "vinculo matrimonial", "propuesta reguladora")),
)

CASE_NAME_PREFIXES = (
    "divorcio",
    "sucesorio",
    "sucesorio ab-intestato",
    "sucesorio ab intestato",
    "alimentos",
    "cuidado personal",
)

ARTICLE_CONTEXT_RE = re.compile(
    r"\b(art(?:s|\.)?\.?|articulos?)\s+([0-9]{1,4}(?:\s*(?:,|;|/|y|e|-)\s*[0-9]{1,4})*)",
    re.IGNORECASE,
)

NOISY_ARTICLE_CONTEXT_HINTS = (
    "ley ",
    "ley no",
    "ley n°",
    "ley nº",
    "uma",
    "honorario",
    "honorarios",
    "arancel",
    "tasa activa",
    "iva",
    "%",
    "por ciento",
    "pesos ",
    "$",
    "valuacion",
    "valuación",
    "perito",
)

HEADER_NOISE_HINTS = (
    "poder judicial",
    "san salvador de jujuy",
    "provincia de jujuy",
    "republica argentina",
    "república argentina",
    "independencia no",
    "coronel puch",
    "general paz",
)


@dataclass
class ParsedJurisprudenceCase:
    case_name: str = ""
    court: str = ""
    jurisdiction: str = ""
    forum: str = ""
    year: int | None = None
    date: str = ""
    document_type: str = ""
    procedural_stage: str = ""
    action_slug: str = ""
    legal_issue: str = ""
    facts_summary: str = ""
    decision_summary: str = ""
    key_reasoning: str = ""
    holding: str = ""
    outcome: str = ""
    topics: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    applied_articles: list[str] = field(default_factory=list)
    strategic_value: str = ""
    full_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_corpus_dict(
        self,
        *,
        case_id: str,
        source: str,
        source_url: str = "",
        dataset_kind: str = "seed",
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = dict(self.metadata)
        if isinstance(extra_metadata, dict):
            metadata.update(extra_metadata)
        return {
            "case_id": case_id,
            "court": self.court,
            "jurisdiction": self.jurisdiction,
            "forum": self.forum,
            "year": self.year,
            "case_name": self.case_name,
            "source": source,
            "source_url": source_url,
            "legal_issue": self.legal_issue,
            "facts_summary": self.facts_summary,
            "decision_summary": self.decision_summary,
            "key_reasoning": self.key_reasoning,
            "holding": self.holding,
            "outcome": self.outcome,
            "topics": list(self.topics),
            "keywords": list(self.keywords),
            "applied_articles": list(self.applied_articles),
            "procedural_stage": self.procedural_stage,
            "document_type": self.document_type,
            "action_slug": self.action_slug,
            "strategic_value": self.strategic_value,
            "date": self.date,
            "full_text": self.full_text,
            "dataset_kind": dataset_kind,
            "metadata": metadata,
        }


class JurisprudenceParser:
    def parse(self, text: str) -> ParsedJurisprudenceCase:
        clean_text = self._normalize_input(text)
        lines = self._split_lines(clean_text)
        sections = self._extract_sections(lines)

        case_name = self._extract_case_name(lines, clean_text)
        court = self._extract_court(lines)
        date = self._extract_date(clean_text)
        year = self._extract_year(date, clean_text)
        forum = self._extract_forum(clean_text, court)
        jurisdiction = self._extract_jurisdiction(clean_text, court)
        document_type = self._extract_document_type(clean_text)
        procedural_stage = self._extract_procedural_stage(clean_text, court)
        action_slug = self._extract_action_slug(clean_text, case_name)
        applied_articles = self._extract_articles(clean_text)
        facts_summary = self._build_facts_summary(sections, lines)
        reasoning_summary = self._summarize_section(
            sections.get("considerando") or sections.get("fundamentos") or ""
        )
        resolutive_text = self._extract_resolutive_text(sections, lines)
        decision_summary = self._summarize_section(resolutive_text or sections.get("considerando") or "")
        holding = self._extract_holding(resolutive_text, reasoning_summary)
        outcome = self._extract_outcome(resolutive_text, decision_summary)
        legal_issue = self._build_legal_issue(
            action_slug=action_slug,
            facts_summary=facts_summary,
            holding=holding,
            outcome=outcome,
            reasoning_summary=reasoning_summary,
        )
        topics = self._extract_topics(action_slug, clean_text)
        keywords = self._build_keywords(case_name, action_slug, applied_articles, clean_text)

        metadata = {
            "parser": "heuristic_jurisprudence_parser_v2",
            "detected_sections": sorted(name for name, value in sections.items() if value),
            "missing_sections": sorted(name for name in SECTION_PATTERNS if not sections.get(name)),
            "parsed_at": datetime.utcnow().date().isoformat(),
        }

        return ParsedJurisprudenceCase(
            case_name=case_name,
            court=court,
            jurisdiction=jurisdiction,
            forum=forum,
            year=year,
            date=date,
            document_type=document_type,
            procedural_stage=procedural_stage,
            action_slug=action_slug,
            legal_issue=legal_issue,
            facts_summary=facts_summary,
            decision_summary=decision_summary,
            key_reasoning=reasoning_summary,
            holding=holding,
            outcome=outcome,
            topics=topics,
            keywords=keywords,
            applied_articles=applied_articles,
            strategic_value="",
            full_text=clean_text,
            metadata=metadata,
        )

    @staticmethod
    def _normalize_input(text: str) -> str:
        normalized = unicodedata.normalize("NFKC", str(text or ""))
        normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
        normalized = re.sub(r"[ \t]+", " ", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()

    @staticmethod
    def _split_lines(text: str) -> list[str]:
        return [line.strip() for line in text.splitlines() if line.strip()]

    def _extract_sections(self, lines: list[str]) -> dict[str, str]:
        sections: dict[str, list[str]] = {name: [] for name in SECTION_PATTERNS}
        current_section = ""
        for line in lines:
            matched_section = self._match_section(line)
            if matched_section:
                current_section = matched_section
                continue
            if current_section:
                sections[current_section].append(line)
        return {name: "\n".join(content).strip() for name, content in sections.items()}

    @staticmethod
    def _match_section(line: str) -> str:
        for name, pattern in SECTION_PATTERNS.items():
            if pattern.match(line):
                return name
        return ""

    def _extract_case_name(self, lines: list[str], text: str) -> str:
        candidates: list[tuple[int, str]] = []
        search_lines = lines[:50]

        for index, line in enumerate(search_lines):
            compact = self._clean_case_candidate(line)
            if not compact:
                continue
            score = self._score_case_candidate(compact, index)
            if score > 0:
                candidates.append((score, compact))

        text_candidates = [
            self._extract_caratulado_from_text(text),
            self._extract_case_line_from_header(search_lines),
        ]
        for candidate in text_candidates:
            compact = self._clean_case_candidate(candidate)
            if compact:
                candidates.append((self._score_case_candidate(compact, 0) + 5, compact))

        if not candidates:
            return ""

        candidates.sort(key=lambda item: (-item[0], len(item[1])))
        return candidates[0][1]

    def _extract_court(self, lines: list[str]) -> str:
        for line in lines[:20]:
            if re.search(r"\b(juzgado|tribunal|camara|superior tribunal|sala)\b", line, re.IGNORECASE):
                return " ".join(line.split())
        return ""

    def _extract_date(self, text: str) -> str:
        header_window = text[:1800]
        match_numeric = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", header_window)
        if match_numeric:
            day, month, year = match_numeric.groups()
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

        normalized = self._normalize_for_matching(header_window)
        match_textual = re.search(r"\b(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(\d{4})\b", normalized)
        if match_textual:
            day, month_name, year = match_textual.groups()
            month = MONTHS.get(month_name, 0)
            if month:
                return f"{int(year):04d}-{month:02d}-{int(day):02d}"

        upper_match = re.search(
            r"\b(\d{1,2})\s+de\s+([A-Z]+)\s+de\s+([0-9]{4}|2\.[0-9]{3})\b",
            header_window,
        )
        if upper_match:
            day, month_name, year = upper_match.groups()
            month = MONTHS.get(self._normalize_for_matching(month_name), 0)
            normalized_year = year.replace(".", "")
            if month and normalized_year.isdigit():
                return f"{int(normalized_year):04d}-{month:02d}-{int(day):02d}"
        return ""

    def _extract_year(self, date_text: str, full_text: str) -> int | None:
        if date_text and re.match(r"^\d{4}-\d{2}-\d{2}$", date_text):
            return int(date_text[:4])
        match = re.search(r"\b(20\d{2}|19\d{2})\b", full_text[:2000])
        return int(match.group(1)) if match else None

    def _extract_document_type(self, text: str) -> str:
        normalized = self._normalize_for_matching(text)
        if "sentencia" in normalized:
            return "sentencia"
        if "resolucion" in normalized:
            return "resolucion"
        if "auto interlocutorio" in normalized:
            return "auto_interlocutorio"
        return "sentencia"

    def _extract_procedural_stage(self, text: str, court: str) -> str:
        normalized = self._normalize_for_matching(" ".join([text[:1500], court]))
        if "apelacion" in normalized or "camara" in normalized or "camara" in court.lower():
            return "apelacion"
        return "primera_instancia"

    def _extract_action_slug(self, text: str, case_name: str) -> str:
        normalized = self._normalize_for_matching(" ".join([case_name, text[:2500]]))
        for slug, hints in ACTION_HINTS:
            if any(hint in normalized for hint in hints):
                return slug
        return ""

    def _extract_forum(self, text: str, court: str) -> str:
        normalized = self._normalize_for_matching(" ".join([court, text[:1200]]))
        if "familia" in normalized or "cuidado personal" in normalized:
            return "familia"
        if "sucesion" in normalized or "sucesorio" in normalized:
            return "civil"
        if "civil" in normalized:
            return "civil"
        return ""

    def _extract_jurisdiction(self, text: str, court: str) -> str:
        normalized = self._normalize_for_matching(" ".join([court, text[:1200]]))
        for jurisdiction in ("jujuy", "salta", "tucuman", "mendoza", "cordoba", "buenos aires"):
            if jurisdiction in normalized:
                return jurisdiction
        return ""

    def _extract_articles(self, text: str) -> list[str]:
        articles: list[str] = []
        for match in ARTICLE_CONTEXT_RE.finditer(text):
            start, end = match.start(), match.end()
            context = self._extract_article_context(text, start, end)
            prefix_window = text[max(0, start - 60): start]
            if self._is_noisy_article_context(context) or self._is_noisy_article_context(prefix_window):
                continue
            for article in self._parse_article_group(match.group(2)):
                if article not in articles:
                    articles.append(article)
        return articles

    def _extract_resolutive_text(self, sections: dict[str, str], lines: list[str]) -> str:
        if sections.get("resuelve"):
            return sections["resuelve"]

        tail = "\n".join(lines[-20:])
        numbered = re.findall(r"(?m)^(?:[IVXLC]+|\d+)[\)\.-]\s+.+$", tail)
        if numbered:
            return "\n".join(numbered)
        return ""

    def _extract_holding(self, resolutive_text: str, reasoning_summary: str) -> str:
        for candidate in (resolutive_text, reasoning_summary):
            sentence = self._first_meaningful_sentence(candidate)
            if sentence:
                return sentence
        return ""

    def _extract_outcome(self, resolutive_text: str, decision_summary: str) -> str:
        lowered = self._normalize_for_matching(resolutive_text)
        if any(marker in lowered for marker in ("hacer lugar", "hace lugar", "rechazar", "rechaza", "confirma", "confirmar", "declarar", "otorgar", "fijar")):
            return self._first_meaningful_sentence(resolutive_text)
        return self._first_meaningful_sentence(decision_summary)

    def _build_legal_issue(
        self,
        *,
        action_slug: str,
        facts_summary: str,
        holding: str,
        outcome: str,
        reasoning_summary: str,
    ) -> str:
        pieces: list[str] = []
        action_label = action_slug.replace("_", " ").strip()
        if action_label:
            pieces.append(action_label)

        for candidate in (holding, outcome, facts_summary, reasoning_summary):
            cleaned = self._clean_summary_text(candidate)
            if cleaned and cleaned not in pieces:
                pieces.append(cleaned)
            if len(" ".join(pieces)) >= 180:
                break

        if not pieces:
            return ""

        first = pieces[0]
        rest = [piece for piece in pieces[1:] if piece]
        legal_issue = first.capitalize()
        if rest:
            legal_issue = f"{legal_issue}: {' '.join(rest)}"
        return self._trim_text(legal_issue, 220)

    def _extract_topics(self, action_slug: str, text: str) -> list[str]:
        topics: list[str] = []
        if action_slug:
            topics.append(action_slug.replace("_", " "))
        normalized = self._normalize_for_matching(text[:2500])
        extra_topics = (
            ("cuota provisoria", "cuota provisoria"),
            ("cuidado personal", "cuidado personal"),
            ("declaratoria de herederos", "declaratoria de herederos"),
            ("efectos accesorios", "efectos accesorios"),
        )
        for marker, label in extra_topics:
            if marker in normalized and label not in topics:
                topics.append(label)
        return topics

    def _build_keywords(
        self,
        case_name: str,
        action_slug: str,
        applied_articles: list[str],
        text: str,
    ) -> list[str]:
        candidates: list[str] = []
        if action_slug:
            candidates.append(action_slug.replace("_", " "))
        for article in applied_articles[:4]:
            candidates.append(f"art {article}")
        normalized = self._normalize_for_matching(" ".join([case_name, text[:1500]]))
        for token in ("divorcio", "alimentos", "sucesion", "cuidado", "personal", "provisoria"):
            if token in normalized and token not in candidates:
                candidates.append(token)
        return candidates[:8]

    def _build_facts_summary(self, sections: dict[str, str], lines: list[str]) -> str:
        for candidate in (
            sections.get("resulta"),
            sections.get("autos_y_vistos"),
            self._extract_fact_block_from_header(lines),
        ):
            summary = self._summarize_section(candidate or "")
            cleaned = self._clean_summary_text(summary)
            if cleaned:
                return cleaned
        return ""

    def _summarize_section(self, text: str, *, max_sentences: int = 2) -> str:
        if not text:
            return ""
        sentences = self._split_sentences(text)
        cleaned = [self._clean_summary_text(sentence) for sentence in sentences]
        cleaned = [sentence for sentence in cleaned if sentence]
        return " ".join(cleaned[:max_sentences]).strip()

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        cleaned = " ".join(str(text).split())
        if not cleaned:
            return []
        parts = re.split(r"(?<=[\.\!\?;])\s+|(?<=\.)\s+(?=[IVXLC0-9][\)\.-])", cleaned)
        return [part.strip() for part in parts if part.strip()]

    def _first_meaningful_sentence(self, text: str) -> str:
        for sentence in self._split_sentences(text):
            cleaned = self._clean_summary_text(sentence)
            if cleaned:
                return cleaned
        return ""

    @staticmethod
    def _normalize_for_matching(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(text).lower())
        normalized = "".join(char for char in normalized if not unicodedata.combining(char))
        return re.sub(r"\s+", " ", normalized)

    def _extract_caratulado_from_text(self, text: str) -> str:
        patterns = (
            r'caratulado\s*:?\s*["](.+?)["]',
            r"caratulado\s*:?\s*(.+?)(?:;|\n|$)",
            r"expediente.+?s/\s*(.+?)(?:\n|$)",
        )
        for pattern in patterns:
            match = re.search(pattern, text[:2500], re.IGNORECASE | re.DOTALL)
            if match:
                candidate = self._clean_case_candidate(match.group(1))
                if candidate:
                    return candidate
        return ""

    def _extract_case_line_from_header(self, lines: list[str]) -> str:
        for line in lines[:25]:
            compact = self._clean_case_candidate(line)
            if compact and self._looks_like_case_name(compact):
                return compact
        return ""

    def _score_case_candidate(self, candidate: str, index: int) -> int:
        normalized = self._normalize_for_matching(candidate)
        score = 0
        if any(prefix in normalized for prefix in CASE_NAME_PREFIXES):
            score += 4
        if " c/ " in normalized or normalized.startswith("c/"):
            score += 4
        if " s/ " in normalized:
            score += 2
        if "caratulado" in normalized:
            score -= 3
        if any(noise in normalized for noise in HEADER_NOISE_HINTS):
            score -= 5
        if re.search(r"\bexpte\b|\bexpediente\b|\bdni\b", normalized):
            score -= 3
        if len(candidate) > 140:
            score -= 2
        score += max(0, 5 - index // 4)
        return score

    def _looks_like_case_name(self, candidate: str) -> bool:
        normalized = self._normalize_for_matching(candidate)
        return (
            " c/ " in normalized
            or any(prefix in normalized for prefix in CASE_NAME_PREFIXES)
            or (" s/ " in normalized and not any(noise in normalized for noise in HEADER_NOISE_HINTS))
        )

    def _clean_case_candidate(self, text: str) -> str:
        candidate = " ".join(str(text or "").replace("“", '"').replace("”", '"').split())
        candidate = candidate.strip(" ;:-")
        candidate = re.sub(r"^(?:expte\.?\s*[^,;:]+[,;:]?\s*)", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"^(?:los de estos?\s+)?(?:autos y vistos:?\s*)?", "", candidate, flags=re.IGNORECASE)
        if ":" in candidate:
            prefix, suffix = candidate.split(":", 1)
            if self._normalize_for_matching(prefix) in CASE_NAME_PREFIXES:
                candidate = f"{prefix.strip()}: {suffix.strip()}"
        candidate = candidate.strip(' "\'')
        if not candidate:
            return ""
        if len(candidate) < 6:
            return ""
        return candidate

    def _extract_fact_block_from_header(self, lines: list[str]) -> str:
        capture: list[str] = []
        for line in lines[:20]:
            normalized = self._normalize_for_matching(line)
            if self._looks_like_case_name(line):
                continue
            if any(noise in normalized for noise in HEADER_NOISE_HINTS):
                continue
            if re.search(r"\b(juzgado|tribunal|camara|sala|secretaria)\b", normalized):
                continue
            if re.search(r"\b(\d{1,2}/\d{1,2}/\d{4}|san salvador de jujuy)\b", normalized):
                continue
            if len(line.split()) >= 6:
                capture.append(line)
            if len(capture) >= 2:
                break
        return " ".join(capture)

    def _clean_summary_text(self, text: str) -> str:
        cleaned = " ".join(str(text or "").split())
        if not cleaned:
            return ""
        cleaned = re.sub(r"^(?:[IVXLC]+|\d+)[\)\.-]\s*", "", cleaned)
        cleaned = re.sub(r"^(?:que|i+)\s*[-.,:]\s*", "", cleaned, flags=re.IGNORECASE)
        normalized = self._normalize_for_matching(cleaned)
        if any(noise in normalized for noise in HEADER_NOISE_HINTS):
            return ""
        if re.search(r"\b(expte|dni|cuil)\b", normalized):
            cleaned = re.sub(r"\b(?:DNI|CUIL)\b[^,.;:]*", "", cleaned, flags=re.IGNORECASE)
        return self._trim_text(cleaned.strip(" -;:,"), 320)

    def _parse_article_group(self, group: str) -> list[str]:
        values: list[str] = []
        for raw_article in re.split(r"\s*(?:,|;|/|y|e|-)\s*", group):
            article = raw_article.strip()
            if not article or not article.isdigit():
                continue
            if len(article) > 4:
                continue
            if article.startswith("0"):
                article = str(int(article))
            if article not in values:
                values.append(article)
        return values

    def _is_noisy_article_context(self, context: str) -> bool:
        normalized = self._normalize_for_matching(context)
        return any(hint in normalized for hint in NOISY_ARTICLE_CONTEXT_HINTS)

    @staticmethod
    def _extract_article_context(text: str, start: int, end: int) -> str:
        left_candidates = [text.rfind(separator, 0, start) for separator in (".", "\n", ";", ":")]
        right_candidates = [text.find(separator, end) for separator in (".", "\n", ";")]
        left = max([-1, *left_candidates]) + 1
        valid_right = [position for position in right_candidates if position != -1]
        right = min(valid_right) if valid_right else len(text)
        return text[left:right]

    @staticmethod
    def _trim_text(text: str, max_len: int) -> str:
        compact = " ".join(str(text or "").split())
        if len(compact) <= max_len:
            return compact
        trimmed = compact[:max_len].rstrip(" ,;:-")
        last_space = trimmed.rfind(" ")
        if last_space >= max_len * 0.6:
            trimmed = trimmed[:last_space]
        return trimmed.rstrip(" ,;:-") + "."
