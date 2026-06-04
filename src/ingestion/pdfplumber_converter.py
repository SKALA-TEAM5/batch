from __future__ import annotations

import re
import time
from pathlib import Path

import pdfplumber

from src.ingestion.breadcrumb import inject_breadcrumbs
from src.ingestion.restructure import restructure_markdown

TITLE = "건설업 산업안전 보건관리비 해설 및 질의회시집"

PAGE_HEADER_LINES = {
    "건설업 산업안전보건관리비 해설 및 질의회시집",
    "건설업 산업안전 보건관리비 해설 및 질의회시집",
    "건설업 산업안전보건관리비 계상 및 사용기준",
    "산업안전보건관리비 항목별 사용 불가내역(개정내용)",
    "항 목 사 용 불 가 내 역",
}

# 법제처 N 국가법령정보센터 등 페이지 하단 푸터 패턴
_PAGE_FOOTER_RE = re.compile(r"^법제처\s+\d+\s+국가법령정보센터$")
# 해설집 내 장 번호 단독 페이지 헤더: "1. 해설집", "2. 고시문" 등
_CHAPTER_HEADER_RE = re.compile(r"^\d+\.\s+(해설집|고시문|질의회신|Q&A)$")

CHAPTER_RE = re.compile(r"^제\d+장\s+.+$")
ARTICLE_RE = re.compile(r"^(?:\[LEGAL_CITE:[^\]]+\]\s*)?제\d+조(?:의\d+)?\(.+\)")
APPENDIX_RE = re.compile(r"^【별표\s*\d+(?:의\d+)?】|^\[(별표|별지)\s*\d+(?:의\d+)?\]")
CATEGORY_RE = re.compile(r"^([1-9]|10)\.\s+(.+)$")
QUESTION_RE = re.compile(r"^(\d+)\)\s+(.+)$")
PAGE_NO_RE = re.compile(r"^\d{1,3}$")
DOT_LEADER_RE = re.compile(r"[·.]{5,}")

# 해설집 본문 전용 heading 패턴 (고시문/Q&A 섹션에서는 비활성화)
# 로마 숫자 대단원: Ⅰ, Ⅱ, ... 단독 줄 → 다음 줄이 제목
ROMAN_RE = re.compile(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]$")
# 가나다라 중단원: 단일 한글 가나다라순 문자 + 공백 + 짧은 제목 (최대 15자)
# 예: "가 목 적", "나 정 의", "다 대상액 산정", "라 공사종류의 적용"
HANGUL_SECTION_RE = re.compile(r"^([가나다라마바사아자차카타파하])\s+(.{1,13})$")

# PDF 내 "주요 질의회신 Q&A" 섹션 제목 1~10번.
# 1~9: 사용 가능 항목 카테고리, 10: 공사 진척/수급인 관련 별도 섹션.
# CATEGORY_RE("^([1-9]|10)\.\s+")와 함께 heading으로 인식하는 데 쓰임.
QA_SECTION_HEADINGS = {
    1: "안전관리자·보건관리자 임금 등",
    2: "안전시설비 등(스마트안전 장비 구입·임대등)",
    3: "보호구 등(안전인증보호구, 안전·보건관리자 피복 등)",
    4: "안전보건진단비 등",
    5: "안전보건교육비 등",
    6: "근로자 건강장해예방비 등",
    7: "본사 전담조직 근로자 임금 등",
    8: "위험성평가 등을 통해 사용 가능한 비용",
    9: "사용불가 항목",
    10: "공사진척에 따른 사용기준 및 관계수급인 사용",
}



def normalize(line: str) -> str:
    line = line.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", line).strip()


def strip_toc_leader(line: str) -> str:
    line = normalize(line)
    return re.sub(r"\s*[·.]{4,}.*?(?:\s+\d+)?\s*$", "", line).strip()


def is_toc_like(line: str) -> bool:
    clean = normalize(line)
    if not clean:
        return False
    return bool(DOT_LEADER_RE.search(clean) or (re.search(r"\s+\d{1,3}$", clean) and "··" in clean))


def is_noise(line: str) -> bool:
    clean = normalize(line)
    if not clean:
        return True
    if clean in PAGE_HEADER_LINES:
        return True
    if PAGE_NO_RE.match(clean):
        return True
    if DOT_LEADER_RE.search(clean):
        return True
    if _PAGE_FOOTER_RE.match(clean):
        return True
    if _CHAPTER_HEADER_RE.match(clean):
        return True
    if clean in {"CONTENTS", "질의", "회시"}:
        return True
    return False


_HWP_CHAR_SPACE_RE = re.compile(r"(?<=\S) (?=\S)")  # 한 글자 간 공백 감지용

def _fix_hwp_char_spacing(text: str) -> str:
    """HWP→PDF 변환 시 발생하는 한 글자씩 띄어진 텍스트 복원.

    예) '안 전 관 리 자' → '안전관리자', '1 . 안 전' → '1. 안전'
    단어 경계가 아닌 단순 글자 간 공백이므로 전체 공백 제거 후 재결합.
    """
    # 공백으로 분리된 각 토큰이 모두 1~2글자이면 HWP 글자간 공백으로 판단
    tokens = text.split()
    if not tokens:
        return text
    if all(len(t) <= 2 for t in tokens) and len(tokens) >= 3:
        return "".join(tokens)
    return text


def _table_to_lines(tables: list) -> list[str]:
    """pdfplumber 테이블을 마크다운 pipe 행 목록으로 변환."""
    lines: list[str] = []
    for tbl in tables:
        for row in tbl:
            cells = [_fix_hwp_char_spacing((c or "").replace("\n", " ").strip()) for c in row]
            if any(cells):
                lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    return lines


def extract_pages(pdf_path: Path, use_tables: bool = False) -> list[list[str]]:
    pages: list[list[str]] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        total = len(pdf.pages)
        for idx, page in enumerate(pdf.pages, start=1):
            if use_tables:
                tables = page.extract_tables()
                if tables:
                    lines = _table_to_lines(tables)
                else:
                    # 표 구조 인식 실패 시 layout=True로 컬럼 분리 시도
                    text = page.extract_text(layout=True) or ""
                    lines = [
                        _fix_hwp_char_spacing(normalize(line))
                        for line in text.splitlines()
                        if normalize(line)
                    ]
            else:
                text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
                lines = [normalize(line) for line in text.splitlines()]
            pages.append(lines)
            if idx == 1 or idx % 25 == 0 or idx == total:
                print(f"[pdfplumber] page {idx}/{total}", flush=True)
    return pages


def _cells(row: list, n: int) -> list[str]:
    """row에서 n개 셀을 꺼내 빈 문자열로 패딩."""
    return [(row[i] or "").strip() if i < len(row) else "" for i in range(n)]


def extract_appendix_table_rows(pdf_path: Path) -> dict[str, list[str]]:
    """별표 1 / 별표 3을 pdfplumber.extract_tables()로 동적 추출해 pipe row 목록 반환.

    페이지 번호 하드코딩 없이 텍스트에서 '【별표 1】' / '【별표 3】' 패턴으로 페이지를 탐색.
    추출 실패 시 해당 별표는 결과에서 생략한다 (빈 dict 반환 가능).
    """
    result: dict[str, list[str]] = {}
    _appendix_label_re = re.compile(r"【별표\s*([13])】")

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            m = _appendix_label_re.search(text)
            if not m:
                continue
            label_num = m.group(1)

            tables = page.extract_tables()
            if not tables:
                continue

            try:
                if label_num == "1":
                    tbl = tables[0]
                    # 공사종류 4개가 \n으로 묶인 행 탐색
                    data = None
                    for row in tbl:
                        if row and (row[0] or "").strip().count("\n") >= 1:
                            data = row
                            break
                    if data is None:
                        data = tbl[-1]
                    n_cols = len(data)
                    split_cols = [(data[c] or "").strip().split("\n") for c in range(n_cols)]
                    n_rows = max(len(col) for col in split_cols)
                    rows: list[str] = []
                    for i in range(n_rows):
                        cells = [
                            split_cols[c][i].strip() if i < len(split_cols[c]) else ""
                            for c in range(n_cols)
                        ]
                        if cells[0]:
                            rows.append("| " + " | ".join(cells) + " |")
                    if rows:
                        result["별표 1"] = rows

                elif label_num == "3":
                    tbl = tables[-1]  # 마지막 테이블이 계상기준표
                    if len(tbl) < 3:
                        continue
                    h0 = _cells(tbl[0], 4)
                    h1 = _cells(tbl[1], 4)
                    header = [f"{a} {b}".strip() if b else a for a, b in zip(h0, h1)]
                    data_row = _cells(tbl[2], 4)
                    result["별표 3"] = [
                        "| " + " | ".join(header) + " |",
                        "| " + " | ".join(data_row) + " |",
                    ]
            except Exception:
                continue  # 해당 별표 추출 실패 시 생략

    return result


def emit_heading(out: list[str], level: int, text: str, context: str | None = None) -> None:
    text = strip_toc_leader(text)
    if not text:
        return
    out.append("")
    out.append(f"{'#' * level} {text}")
    out.append(f"<!-- context: {context or f'{TITLE} > {text}'} -->")
    out.append("")


def emit_body(out: list[str], line: str) -> None:
    line = normalize(line)
    if not line or is_noise(line):
        return
    # 행정 문체 완곡 표현을 단정 표현으로 정규화.
    # 검색 시 "사용이 가능함"으로 일관되게 매칭되도록 의미를 보존한 채 축약한다.
    line = line.replace("사용이 가능할 것으로 사료됨", "사용이 가능함.")
    line = line.replace("사용이 가능할 것으로 판단됨", "사용이 가능함.")
    line = line.replace("사용 가능할 것으로 판단됨", "사용이 가능함.")
    line = line.replace("사용 가능할 것으로 사료됨", "사용이 가능함.")
    if line.startswith("[LEGAL_CITE:") or ARTICLE_RE.match(line):
        if out and out[-1].strip():
            out.append("")
        out.append(line)
        return
    out.append(line)


def looks_like_question(line: str) -> bool:
    match = QUESTION_RE.match(line)
    if not match:
        return False
    question = match.group(2)
    return any(token in question for token in ("사용 가능한지", "가능한지", "무엇인지", "되는지", "있는지", "인지", "방법은", "기준은"))


def join_question(lines: list[str], start: int) -> tuple[str, int]:
    question = normalize(lines[start])
    i = start + 1
    while i < len(lines):
        nxt = normalize(lines[i])
        if not nxt or nxt in {"회시", "질의"}:
            break
        if QUESTION_RE.match(nxt) or CATEGORY_RE.match(nxt) or CHAPTER_RE.match(nxt):
            break
        if len(question) > 150 or any(token in question for token in ("사용 가능한지", "가능한지", "무엇인지", "되는지", "있는지", "인지", "방법은", "기준은")):
            break
        question = f"{question} {nxt}"
        i += 1
    return question, i


def category_from_line(line: str) -> tuple[int, str] | None:
    match = CATEGORY_RE.match(strip_toc_leader(line))
    if not match:
        return None
    number = int(match.group(1))
    title = match.group(2).strip()
    if number in QA_SECTION_HEADINGS and any(key in title for key in ("안전관리자", "안전시설", "보호구", "진단비", "교육비", "건강장해", "본사", "위험성평가", "사용불가", "공사진척")):
        return number, title
    return None


def is_split_boundary(line: str) -> bool:
    clean = normalize(re.sub(r"^\[LEGAL_CITE:[^\]]+\]\s*", "", line))
    if not clean:
        return False
    if clean.startswith(("", "※", "-", "○")):
        return True
    if re.match(r"^\d+[.)]\s+", clean):
        return True
    if re.match(r"^[가-힣][.)]\s+", clean):
        return True
    if re.match(r"^【고시\s+제\d+조", clean):
        return True
    if any(token in clean for token in ("사용 가능한지", "사용이 가능한지", "가능한지", "불가한지")):
        return True
    return clean.endswith(("다.", "함.", "됨.", "음.", "임.", "다", "함", "됨", "음", "임"))


def split_corpus_blocks(markdown_text: str, target_chars: int = 260) -> str:
    output: list[str] = []
    pending_body_chars = 0

    def reset_body() -> None:
        nonlocal pending_body_chars
        pending_body_chars = 0

    def ensure_blank_before() -> None:
        if output and output[-1].strip():
            output.append("")

    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            if output and output[-1].strip():
                output.append("")
            reset_body()
            continue
        if stripped.startswith("#") or stripped.startswith("<!--"):
            ensure_blank_before()
            output.append(line)
            reset_body()
            continue

        clean = normalize(re.sub(r"^\[LEGAL_CITE:[^\]]+\]\s*", "", stripped))
        starts_new_semantic_unit = (
            re.match(r"^(?:\[LEGAL_CITE:[^\]]+\]\s*)?【고시\s+제\d+조", stripped)
            or re.match(r"^(?:\[LEGAL_CITE:[^\]]+\]\s*)?[가-힣]\s+[가-힣].{0,35}$", stripped)
            or looks_like_question(clean)
        )
        if pending_body_chars >= 120 and starts_new_semantic_unit:
            ensure_blank_before()
            reset_body()

        output.append(line)
        pending_body_chars += len(clean)
        if pending_body_chars >= target_chars and is_split_boundary(stripped):
            output.append("")
            reset_body()

    return re.sub(r"\n{4,}", "\n\n\n", "\n".join(output).strip() + "\n")


def build_semantic_markdown(
    pages: list[list[str]],
    appendix_rows: dict[str, list[str]] | None = None,
    pdf_path: Path | None = None,
    title: str | None = None,
    is_commentary: bool = False,
) -> str:
    _appendix = appendix_rows or {}
    out: list[str] = []
    _title = title or TITLE
    emit_heading(out, 1, _title, _title)

    # 해설집 전용 섹션 구조. 비해설집 PDF는 빈 문자열로 시작해 오탐 방지.
    current_part = "해설집" if is_commentary else ""
    current_chapter = ""
    current_category_title = ""
    qa_mode = False
    pending_question: str | None = None
    answer_lines: list[str] = []

    def current_context(extra: str | None = None) -> str:
        parts = [_title]
        for part in (current_part, current_chapter, current_category_title, extra):
            if part:
                parts.append(part)
        return " > ".join(parts)

    def flush_qa() -> None:
        nonlocal pending_question, answer_lines
        if pending_question and answer_lines:
            emit_heading(out, 4, pending_question, current_context(pending_question))
            for answer in answer_lines:
                emit_body(out, answer)
            # 질의회신 출처 연도 마커 — PDF 파일명에서 연도 추출, 없으면 생략
            _year_m = re.search(r"(20\d{2})", pdf_path.name if isinstance(pdf_path, Path) else "")
            if _year_m:
                out.append(f"({_year_m.group(1)}년)")
            out.append("")
        pending_question = None
        answer_lines = []

    for page_index, lines in enumerate(pages, start=1):
        out.append(f"<!-- page:{page_index} -->")
        i = 0
        while i < len(lines):
            line = normalize(lines[i])
            if not line:
                i += 1
                continue

            clean = strip_toc_leader(line)
            if page_index <= 12 and (is_toc_like(line) or QUESTION_RE.match(clean) or CHAPTER_RE.match(clean) or category_from_line(clean) or "주요 질의" in clean):
                i += 1
                continue

            # page 55~: 해설 본문 끝, 고시문 섹션 시작 (이 PDF 기준 고정 페이지 오프셋)
            if (line.startswith("02 ") or line == "산업안전보건관리비 고시문") and page_index >= 55:
                flush_qa()
                current_part = "산업안전보건관리비 고시문"
                current_chapter = ""
                current_category_title = ""
                qa_mode = False
                emit_heading(out, 2, current_part, current_context())
                i += 1
                continue

            # page 70~: Q&A 섹션 시작 (이 PDF 기준 고정 페이지 오프셋)
            if "주요 질의" in line and "Q&A" in line and page_index >= 70 and not is_toc_like(line):
                flush_qa()
                current_part = "주요 질의회신 Q&A"
                current_chapter = ""
                current_category_title = ""
                qa_mode = True
                emit_heading(out, 2, current_part, current_context())
                i += 1
                continue

            # 해설집 로마 숫자 대단원: "Ⅰ" 단독 줄, 다음 줄이 제목
            if ROMAN_RE.match(clean) and current_part == "해설집":
                j = i + 1
                while j < len(lines) and not normalize(lines[j]):
                    j += 1
                if j < len(lines):
                    section_title = normalize(lines[j])
                    if section_title and not is_noise(section_title) and len(section_title) <= 20:
                        full = f"{clean} {section_title}"
                        flush_qa()
                        current_chapter = full
                        current_category_title = ""
                        emit_heading(out, 2, full, current_context(full))
                        i = j + 1
                        continue

            # 해설집 가나다라 중단원: "가 목 적", "나 계상 시기" 등
            if HANGUL_SECTION_RE.match(clean) and current_part == "해설집" and not is_toc_like(line):
                flush_qa()
                current_category_title = clean
                emit_heading(out, 3, clean, current_context(clean))
                i += 1
                continue

            if CHAPTER_RE.match(clean):
                flush_qa()
                current_chapter = clean
                current_category_title = ""
                emit_heading(out, 2 if current_part == "산업안전보건관리비 고시문" else 3, clean, current_context(clean))
                i += 1
                continue

            cat = category_from_line(clean) if not is_toc_like(line) else None
            if cat:
                flush_qa()
                _, current_category_title = cat
                emit_heading(out, 3, f"{cat[0]}. {cat[1]}", current_context(cat[1]))
                i += 1
                continue

            if APPENDIX_RE.match(clean) and not is_toc_like(line) and (page_index >= 55 or clean.startswith("【")):
                flush_qa()
                current_chapter = clean
                emit_heading(out, 3, clean, current_context(clean))
                if clean.startswith("【별표"):
                    out.append(clean)
                    if clean == "【별표 1】":
                        out.extend(_appendix.get("별표 1", []))
                        i = len(lines)  # 이 페이지 raw text는 표와 중복 → 스킵
                        continue
                    elif clean == "【별표 3】":
                        out.extend(_appendix.get("별표 3", []))
                        i = len(lines)  # 동일
                        continue
                i += 1
                continue

            if ARTICLE_RE.match(clean):
                flush_qa()
                emit_heading(out, 3, re.sub(r"^\[LEGAL_CITE:[^\]]+\]\s*", "", clean), current_context(clean))
                emit_body(out, clean)
                i += 1
                continue

            if line == "질의":
                flush_qa()
                j = i + 1
                while j < len(lines) and not normalize(lines[j]):
                    j += 1
                if j < len(lines) and looks_like_question(normalize(lines[j])):
                    pending_question, next_i = join_question(lines, j)
                    i = next_i
                    continue

            if line == "회시":
                i += 1
                continue

            if pending_question:
                if QUESTION_RE.match(clean):
                    possible_question, next_i = join_question(lines, i)
                    flush_qa()
                    if looks_like_question(possible_question):
                        pending_question = possible_question
                        i = next_i
                        continue
                    emit_body(out, line)
                    i += 1
                    continue
                if clean.startswith("(건설산재예방정책과") or re.match(r"^\(20\d{2}년", clean):
                    flush_qa()
                    i += 1
                    continue
                answer_lines.append(line)
                i += 1
                continue

            if current_chapter.startswith("【별표 1의3】") and clean.startswith("○ "):
                emit_body(out, f"- {clean[2:].strip()}")
                i += 1
                continue

            if QUESTION_RE.match(clean) and (qa_mode or page_index >= 70) and not is_toc_like(line):
                possible_question, next_i = join_question(lines, i)
                if looks_like_question(possible_question):
                    flush_qa()
                    pending_question = possible_question
                    i = next_i
                    continue

            if looks_like_question(clean) and (qa_mode or page_index >= 70) and not is_toc_like(line):
                flush_qa()
                pending_question, next_i = join_question(lines, i)
                i = next_i
                continue

            emit_body(out, line)
            i += 1

    flush_qa()
    return re.sub(r"\n{4,}", "\n\n\n", "\n".join(out).strip() + "\n")


def convert_pdf_to_final_markdown(pdf_path: str | Path) -> str:
    pdf_path = Path(pdf_path)
    started = time.perf_counter()
    print(f"[{pdf_path}] PDF 변환 시작 (pdfplumber)...")

    import unicodedata as _ud
    _name = _ud.normalize("NFC", pdf_path.name)
    is_commentary = any(keyword in _name for keyword in ("해설", "질의회시"))
    is_appendix_table = any(keyword in _name for keyword in ("불가내역", "부록"))
    pages = extract_pages(pdf_path, use_tables=is_appendix_table)
    appendix_rows = extract_appendix_table_rows(pdf_path) if is_commentary else None
    semantic = build_semantic_markdown(pages, appendix_rows, pdf_path=pdf_path, title=pdf_path.stem, is_commentary=is_commentary)

    restructured = restructure_markdown(semantic)
    split_markdown = split_corpus_blocks(restructured)
    final = inject_breadcrumbs(split_markdown)
    print(f"[{pdf_path}] PDF 변환 완료 (pdfplumber, {time.perf_counter() - started:.2f}s)")
    return final
