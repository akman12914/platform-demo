from common_styles import apply_common_styles, set_page_config
import auth

import os
import tempfile
import shutil
import re
import json
import streamlit as st
from dotenv import load_dotenv
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import math
from typing import List, Tuple


SEOUL_TZ = ZoneInfo("Asia/Seoul")


# === [ADD] 여러 형태의 섹션 헤더 줄바꿈 보정 ===
HEADER_MARKERS = ("※", "■", "◆", "●", "▶", "▷", "▲", "▸", "•")
BULLET_MARKERS = ("- ", "• ", "ㆍ", "·", "* ", "— ", "– ")

HEADER_KEYWORDS = (
    "개요",
    "공사 범위",
    "공사범위",
    "견적조건",
    "적용범위",
    "UBR 공사분",
    "재료",
    "자재",
    "치수",
    "규격",
    "시공 절차",
    "시공절차",
    "품질",
    "검수",
    "유의",
    "유의사항",
    "안전",
    "기타",
    "참고",
    "근거",
)

_hdr_colon_re = re.compile(r"^\s*[^:：]{1,80}\s*[:：]\s*$")
_hdr_number_re = re.compile(r"^\s*(제?\d+(?:\.\d+)*[)\.]?)\s+[^\s].{0,60}$")
_hdr_keyword_re = re.compile(
    r"^\s*(" + "|".join(map(re.escape, HEADER_KEYWORDS)) + r")\s*$"
)


def _is_header_line(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    if s.startswith(HEADER_MARKERS):  # 기호형 헤더
        return True
    if _hdr_colon_re.match(s):  # 콜론형 헤더 (예: "재료:")
        return True
    if _hdr_number_re.match(s):  # 번호형 헤더 (예: "1. 개요", "제2. 품질")
        return True
    if _hdr_keyword_re.match(s):  # 키워드 단독 헤더 (예: "공사 범위")
        return True
    return False


def _is_bullet_line(s: str) -> bool:
    ss = s.lstrip()
    return any(ss.startswith(m) for m in BULLET_MARKERS)


def _normalize_multiline_sections_enhanced(text: str) -> str:
    """
    PDF 추출 과정에서 헤더가 줄바꿈으로 끊긴 것을 보정.
    - 헤더 라인 인식(기호/콜론/번호/키워드)
    - 바로 다음 라인이 불릿/헤더/빈줄이 아니고 너무 길지 않으면(<=120자) 최대 3줄까지 이어붙임.
    """
    lines = text.splitlines()
    out = []
    buf = None
    tail_joined = 0

    for raw in lines:
        s = raw.strip()

        if _is_header_line(s):
            if buf is not None:
                out.append(buf)
            buf = s
            tail_joined = 0
            continue

        if buf is not None:
            if (
                s
                and not _is_header_line(s)
                and not _is_bullet_line(s)
                and len(s) <= 120
                and tail_joined < 3
            ):
                buf += " " + s
                tail_joined += 1
                continue
            else:
                out.append(buf)
                buf = None
                tail_joined = 0

        out.append(raw)

    if buf is not None:
        out.append(buf)

    return "\n".join(out)


# === [/ADD] ===


# LangChain (최신 구조)
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.documents import Document

# ---------------------------------------
# 환경설정
# ---------------------------------------
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ═══════════════════════════════════════════════════════════════
# 데모용 예시 시방서 결과 (파일 업로드 후 즉시 반환)
# ═══════════════════════════════════════════════════════════════
# 시방서.pdf (YWMS-1706-F2 / Rev.1) 기반 샘플 데이터
# ═══════════════════════════════════════════════════════════════
SAMPLE_SPEC_SUMMARY = """
<div class="summary-card">
<h3>📋 시방서 분석 결과 — 조립식욕실공사 (YWMS-1706-F2 / Rev.1)</h3>
<p style="color:#aaa;font-size:0.9em;margin-top:-8px;">천안신부 행복주택 아파트 신축공사 제1공구 &nbsp;|&nbsp; 공사기간: 2025.10 ~ 2027.05.03</p>

<hr style="border-color:#334;margin:12px 0">

<h4>📌 주요 자재 사양</h4>
<table style="width:100%;border-collapse:collapse;font-size:0.88em;">
<tr style="background:#1a2233;">
  <th style="padding:6px 10px;text-align:left;color:#7eb8f7;">구분</th>
  <th style="padding:6px 10px;text-align:left;color:#7eb8f7;">사양</th>
  <th style="padding:6px 10px;text-align:left;color:#7eb8f7;">규격 / 기준</th>
</tr>
<tr style="border-bottom:1px solid #2a3a50;">
  <td style="padding:6px 10px;">양변기</td>
  <td style="padding:6px 10px;">절수형 비데 일체형</td>
  <td style="padding:6px 10px;"><span style="color:#f97316;font-weight:bold;">6L 이하</span>, 환경인증 필수</td>
</tr>
<tr style="background:#131e2e;border-bottom:1px solid #2a3a50;">
  <td style="padding:6px 10px;">배수트랩</td>
  <td style="padding:6px 10px;">합성수지, 이중관 저소음</td>
  <td style="padding:6px 10px;">봉수 <span style="color:#f97316;font-weight:bold;">≥50mm</span> · STS 그레이팅 <span style="color:#f97316;font-weight:bold;">1.2T</span> · 유량 <span style="color:#f97316;font-weight:bold;">≥50LPM</span></td>
</tr>
<tr style="border-bottom:1px solid #2a3a50;">
  <td style="padding:6px 10px;">실리콘(줄눈)</td>
  <td style="padding:6px 10px;">항곰팡이, 비초산형</td>
  <td style="padding:6px 10px;">KS F 4910, SR-1-9030 동등품</td>
</tr>
<tr style="background:#131e2e;border-bottom:1px solid #2a3a50;">
  <td style="padding:6px 10px;">바닥 타일</td>
  <td style="padding:6px 10px;">미끄럼 방지</td>
  <td style="padding:6px 10px;">동마찰계수 <span style="color:#f97316;font-weight:bold;">≥0.65</span></td>
</tr>
<tr style="border-bottom:1px solid #2a3a50;">
  <td style="padding:6px 10px;">문·문틀</td>
  <td style="padding:6px 10px;">복합수지, 방수</td>
  <td style="padding:6px 10px;">KSF 3109 준수, 하드웨어·실 포함</td>
</tr>
<tr style="background:#131e2e;">
  <td style="padding:6px 10px;">지지철물</td>
  <td style="padding:6px 10px;">스테인리스(STS)</td>
  <td style="padding:6px 10px;">내부식성, 전 품목 적용</td>
</tr>
</table>

<h4 style="margin-top:16px;">⚙️ 시공 조건</h4>
<ul style="font-size:0.88em;line-height:1.8;margin:0;padding-left:18px;">
  <li>계약 후 <strong>2주 이내</strong>: 배관 인입 위치·관통 위치·슬리브 위치도 제출</li>
  <li>동절기 공사 원칙적 <strong>금지</strong> (발주처 승인 시 허용, 비용 시공사 부담)</li>
  <li>실내 건축자재(타일·모르타르 등) <strong>방사성 물질 시험성적서</strong> 제출 필수</li>
  <li>바닥 방수패널 하부: <strong>모르타르 충전 밀실 시공</strong></li>
  <li>양변기 설치 후 기울어짐 없도록 수평 유지, 틈새 <strong>백시멘트 충전 (H&lt;10mm)</strong></li>
  <li>시공 샘플 유닛 사전 제작 (괴산 5세대 + 진천 6세대)</li>
</ul>

<h4 style="margin-top:16px;">♿ 주거약자(장애인·고령자) 적용 사양</h4>
<ul style="font-size:0.88em;line-height:1.8;margin:0;padding-left:18px;">
  <li>욕실 입구 단차 없음 (휠체어 접근 가능)</li>
  <li>L자 손잡이 <strong>2개</strong> + I자 손잡이 <strong>1개</strong></li>
  <li>접이식 의자: <strong>500mm(W) × 400mm(D) 이상</strong></li>
  <li>손잡이·의자 배면 벽판 <strong>보강 처리</strong></li>
  <li>댐퍼 힌지 적용, 손끼임 방지 장치 설치</li>
</ul>

<h4 style="margin-top:16px;">✅ 품질 기준</h4>
<ul style="font-size:0.88em;line-height:1.8;margin:0;padding-left:18px;">
  <li>위생도기·수전·욕실장: <strong>감독관 사전 승인</strong> 후 설치 (샘플 제출 포함)</li>
  <li>절수형 제품(수전·샤워헤드·양변기): <strong>환경인증 필수</strong></li>
  <li>입주 후 <strong>2개월간</strong> 기술자 상주 하자 보수</li>
  <li>LH 표준시방서 47530 (조립식욕실) 준수</li>
</ul>

<p style="margin-top:14px;font-size:0.82em;color:#666;">※ 위 내용은 YWMS-1706-F2/Rev.1 시방서를 기반으로 자동 분석된 결과입니다.</p>
</div>
"""

SAMPLE_DETECTED_ITEMS = [
    {
        "name": "절수형 양변기",
        "spec": "6L 이하, 비데 일체형, 환경인증",
        "qty": 1,
        "unit": "EA",
        "required": True,
        "source": "절수형(6L 이하) 양변기, 비데 기능 포함",
    },
    {
        "name": "세면기",
        "spec": "벽걸이형, 환경인증",
        "qty": 1,
        "unit": "EA",
        "required": True,
        "source": "위생도기류 – 세면기 설치",
    },
    {
        "name": "세면기 수전",
        "spec": "절수형, 환경인증, 냉온수 분리",
        "qty": 1,
        "unit": "SET",
        "required": True,
        "source": "수전류 환경인증 절수형",
    },
    {
        "name": "배수트랩",
        "spec": "합성수지 이중관 저소음, 봉수≥50mm, STS 그레이팅 1.2T, 유량≥50LPM",
        "qty": 1,
        "unit": "EA",
        "required": True,
        "source": "배수트랩 봉수 50mm 이상, 그레이팅 STS 1.2T",
    },
    {
        "name": "복합수지 문·문틀",
        "spec": "KSF 3109, 방수, 하드웨어·실 포함",
        "qty": 1,
        "unit": "SET",
        "required": True,
        "source": "복합수지 문틀·문 KSF 3109 준수",
    },
    {
        "name": "항곰팡이 실리콘",
        "spec": "KS F 4910, 비초산형 SR-1-9030",
        "qty": 1,
        "unit": "식",
        "required": True,
        "source": "내부 줄눈 전면 항곰팡이 실리콘 처리",
    },
    {
        "name": "바닥판",
        "spec": "방수패널, 하부 모르타르 충전 밀실 시공",
        "qty": 1,
        "unit": "EA",
        "required": True,
        "source": "바닥 방수패널 모르타르 충전",
    },
    {
        "name": "벽판",
        "spec": "조립식, 감독관 사전 승인",
        "qty": 1,
        "unit": "SET",
        "required": True,
        "source": "조립식 벽판 감독관 사전 승인",
    },
    {
        "name": "천장판",
        "spec": "조립식",
        "qty": 1,
        "unit": "EA",
        "required": True,
        "source": "조립식 천장판 설치",
    },
    {
        "name": "미끄럼방지 바닥타일",
        "spec": "동마찰계수 ≥0.65",
        "qty": 1,
        "unit": "SET",
        "required": True,
        "source": "바닥 타일 동마찰계수 0.65 이상",
    },
    {
        "name": "욕실장",
        "spec": "감독관 승인 모델",
        "qty": 1,
        "unit": "EA",
        "required": False,
        "source": "욕실장 품질검사 시료 3개 1세트",
    },
    {
        "name": "거울",
        "spec": "감독관 승인 모델",
        "qty": 1,
        "unit": "EA",
        "required": False,
        "source": "욕실 거울 설치",
    },
    {
        "name": "선반(코너·유리)",
        "spec": "코너 1개, 유리 1개",
        "qty": 2,
        "unit": "EA",
        "required": False,
        "source": "코너선반·유리선반 각 1개",
    },
    {
        "name": "L자 손잡이",
        "spec": "주거약자용, 2개 1세트, 배면 벽판 보강",
        "qty": 2,
        "unit": "EA",
        "required": False,
        "source": "L자 손잡이 2개, 배면 벽판 보강 처리",
    },
    {
        "name": "I자 손잡이",
        "spec": "주거약자용, 배면 벽판 보강",
        "qty": 1,
        "unit": "EA",
        "required": False,
        "source": "I자 손잡이 1개, 배면 벽판 보강",
    },
    {
        "name": "접이식 의자",
        "spec": "주거약자용, W≥500mm × D≥400mm, 배면 벽판 보강",
        "qty": 1,
        "unit": "EA",
        "required": False,
        "source": "접이식 의자 500×400mm 이상",
    },
    {
        "name": "환기덕트 타일 개구",
        "spec": "Φ32, 기계 지정 위치",
        "qty": 1,
        "unit": "식",
        "required": True,
        "source": "환기 덕트 타일 개구 Φ32",
    },
    {
        "name": "조명 케이블 연결함",
        "spec": "100×60×25mm",
        "qty": 1,
        "unit": "EA",
        "required": True,
        "source": "조명 회로용 케이블 연결함 100×60×25mm",
    },
]

SAMPLE_QUOTE_SENTENCES = [
    {
        "sentence": "바닥 슬리브 그라우팅(시멘트 및 모래 포함)은 견적에 포함한다.",
        "items": ["바닥 슬리브", "시멘트", "모래"],
        "context": "설비 관련 견적 포함 사항 — 바닥 슬리브 그라우팅 (p.2)",
    },
    {
        "sentence": "냉·온수 세면기 배관용 워터해머 방지기는 단가에 포함한다.",
        "items": ["워터해머 방지기"],
        "context": "세면기 냉온수 배관 워터해머 방지 요건 (p.2)",
    },
    {
        "sentence": "배수트랩·욕실장 품질검사 시료(3개 1세트) 제출 비용은 견적에 포함한다.",
        "items": ["배수트랩", "욕실장"],
        "context": "품질검사 시료 제출 비용 포함 — 트랩 1회/접속부, 욕실장 3회/세대 (p.2)",
    },
    {
        "sentence": "시공 후 내부 줄눈 전면(벽·천장·바닥·문틀 주위) 항곰팡이 실리콘 처리는 견적에 포함한다.",
        "items": ["항곰팡이 실리콘", "줄눈 처리"],
        "context": "내부 마감 실리콘 처리 규정 — KS F 4910, 비초산형 SR-1-9030 (p.2)",
    },
    {
        "sentence": "바닥 타일 보양용 마킹시트 설치 및 검사구 개구 비용은 단가에 포함된 것으로 한다.",
        "items": ["보양 마킹시트", "검사구 개구"],
        "context": "보양 및 마감 요건 — 바닥 타일 보양·AD&PD 검사구 (p.2)",
    },
]

# 하위 호환 — 기존 코드에서 EXAMPLE_ 변수를 참조하는 곳 대응
EXAMPLE_SPEC_SUMMARY = SAMPLE_SPEC_SUMMARY
EXAMPLE_DETECTED_ITEMS = SAMPLE_DETECTED_ITEMS
EXAMPLE_QUOTE_SENTENCES = SAMPLE_QUOTE_SENTENCES


set_page_config(page_title="AI 시방서 분석", page_icon="🛁", layout="wide")
apply_common_styles()

auth.require_auth()

st.title("🛁 AI 시방서 분석")

# ---------------------------------------
# ✅ 상태 초기화
# ---------------------------------------
if "vectorstore" not in st.session_state:
    st.session_state["vectorstore"] = None
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []
# 새로 추가: 마지막 인덱스 배치와 그 요약
if "last_index_batch_docs" not in st.session_state:
    st.session_state["last_index_batch_docs"] = []
if "last_index_summary" not in st.session_state:
    st.session_state["last_index_summary"] = None

# ═══════════════════════════════════════════════════════════════
# 품목 탐지 관련 상태
# ═══════════════════════════════════════════════════════════════
AI_DETECTED_ITEMS_KEY = "ai_detected_items"  # AI 추출 품목
AI_COMPARISON_RESULT_KEY = "ai_comparison_result"  # 비교 결과
AI_PENDING_ITEMS_KEY = "ai_pending_items"  # 추가 대기 품목

if AI_DETECTED_ITEMS_KEY not in st.session_state:
    st.session_state[AI_DETECTED_ITEMS_KEY] = []
if AI_COMPARISON_RESULT_KEY not in st.session_state:
    st.session_state[AI_COMPARISON_RESULT_KEY] = None
if AI_PENDING_ITEMS_KEY not in st.session_state:
    st.session_state[AI_PENDING_ITEMS_KEY] = []

# ---------------------------------------
# 사이드바: 모델/옵션
# ---------------------------------------
with st.sidebar:
    st.markdown("### ⚙️ 옵션")
    model_name = "gpt-5-mini"
    st.markdown("⚙️ LLM 모델: gpt-5")
    k_ctx = st.slider("검색 문서 수(k)", 2, 8, 4, 1)
    chunk_size = st.slider("청크 크기", 500, 2000, 1000, 100)
    chunk_overlap = st.slider("오버랩", 50, 400, 150, 25)
    st.markdown("---")
    st.markdown("**파일 업로드 후, [인덱스 생성]을 눌러주세요.**")


# ---------------------------------------
# 공용: 업로드 파일을 임시경로로 저장
# ---------------------------------------
def _save_uploaded_to_temp(uploaded_file, suffix):
    """Streamlit UploadedFile -> temp file path"""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        shutil.copyfileobj(uploaded_file, tmp)
        tmp.flush()
        return tmp.name
    finally:
        tmp.close()


# ---------------------------------------
# 함수: 최신우선 가중치(신선도) + 유사도 재랭킹 검색
# ---------------------------------------


def _parse_ts(ts: str) -> float:
    # ISO8601 → epoch seconds
    try:
        return datetime.fromisoformat(ts).timestamp()
    except Exception:
        return 0.0


def search_with_recency_rerank(
    vs,
    query: str,
    k: int = 4,
    fetch_k: int = 32,
    w_recency: float = 0.35,
    half_life_days: float = 14.0,
) -> List[Document]:
    """
    벡터 유사도 + 신선도(지수감쇠) 결합 점수로 재랭크.
    FAISS.similarity_search_with_score 를 사용하고, 점수정규화 후 결합.
    """
    # 1) 충분히 넓게 후보 수집
    try:
        pairs: List[Tuple[Document, float]] = vs.similarity_search_with_score(
            query, k=fetch_k
        )
        # 일부 구현은 score가 "작을수록 유사"(거리)일 수 있으므로 뒤에서 정규화로 보정
    except Exception:
        # fallback
        docs = vs.similarity_search(query, k=fetch_k)
        pairs = [(d, 0.0) for d in docs]

    now = datetime.now(tz=SEOUL_TZ).timestamp()
    # 2) score 정규화 (min-max → 유사도 방향으로 뒤집기)
    scores = [s for _, s in pairs]
    if scores:
        s_min, s_max = min(scores), max(scores)
        # 거리를 유사도로 변환: 작은게 더 유사 → inv_norm
        sim_norm = []
        for doc, s in pairs:
            if s_max == s_min:
                inv = 1.0
            else:
                # 0~1로 정규화 후 뒤집기
                inv = 1.0 - ((s - s_min) / (s_max - s_min))
            sim_norm.append((doc, inv))
    else:
        sim_norm = [(doc, 1.0) for doc, _ in pairs]

    # 3) recency 점수: half-life 기반 지수 감쇠
    hl_secs = half_life_days * 86400.0
    ranked = []
    for doc, sim in sim_norm:
        ts = _parse_ts(doc.metadata.get("timestamp", ""))  # epoch
        # 시간이 없으면 0점
        if ts <= 0:
            rec = 0.0
        else:
            age = max(0.0, now - ts)
            rec = math.exp(-age / hl_secs)  # 최근일수록 1에 가까움

        combined = (1.0 - w_recency) * sim + (w_recency) * rec
        ranked.append((combined, doc, sim, rec))

    ranked.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d, _, _ in ranked[:k]]


# ---------------------------------------
# 함수: 문서 로딩 (PDF/Text)
# ---------------------------------------
def load_docs(uploaded_files):
    docs = []
    batch_id = datetime.now(tz=SEOUL_TZ).strftime("%Y%m%d-%H%M%S")
    base_ts = datetime.now(tz=SEOUL_TZ)
    step = 1  # 파일 간 1초 간격

    for idx, f in enumerate(uploaded_files):
        suffix = os.path.splitext(f.name)[1].lower()
        file_ts = (base_ts - timedelta(seconds=step * idx)).isoformat()

        if suffix == ".pdf":
            tmp_path = _save_uploaded_to_temp(f, ".pdf")
            try:
                loader = PyPDFLoader(tmp_path)
                loaded = loader.load()
                for d in loaded:
                    d.metadata["display_name"] = f.name
                    d.metadata["batch_id"] = batch_id
                    d.metadata["timestamp"] = file_ts
                    d.page_content = _normalize_multiline_sections_enhanced(
                        d.page_content
                    )
                docs.extend(loaded)
            finally:
                os.unlink(tmp_path)

        elif suffix in [".txt", ".md"]:
            tmp_path = _save_uploaded_to_temp(f, suffix)
            try:
                loader = TextLoader(tmp_path, encoding="utf-8")
                loaded = loader.load()
                for d in loaded:
                    d.metadata["display_name"] = f.name
                    d.metadata["batch_id"] = batch_id
                    d.metadata["timestamp"] = file_ts
                    d.page_content = _normalize_multiline_sections_enhanced(
                        d.page_content
                    )
                docs.extend(loaded)
            finally:
                os.unlink(tmp_path)
        else:
            st.warning(f"지원하지 않는 형식: {f.name}")

    return docs


# ---------------------------------------
# 함수: 청크 분할
# ---------------------------------------
def split_docs(docs, chunk_size=1000, chunk_overlap=150):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )
    return splitter.split_documents(docs)


def generate_index_summary(docs: list) -> str:
    """업로드된 문서에서 배치 요약 생성"""
    if not docs:
        return EXAMPLE_SPEC_SUMMARY

    full_text = "\n\n".join(
        [d.page_content.strip() for d in docs if d.page_content.strip()][:8]
    )
    if not full_text:
        return EXAMPLE_SPEC_SUMMARY

    # 텍스트가 매우 길 경우 앞부분 중심으로 잘라 요약
    context = full_text[:12000]

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """너는 욕실(UBR) 시스템 욕실 시방서 전문 요약가다. 업로드된 시방서에서 핵심정보를 추출하여 아래 형식으로 요약하라.
- 프로젝트 개요
- 주요 자재 목록(바닥판/벽판/천장판 등)
- 규격/사양(타일 규격, 두께, 재질 등)
- 의무/품질요건(방수, KS 기준, 누수 검사 등)
- 특이사항/주의사항
""",
            ),
            (
                "human",
                """아래 시방서 텍스트 내용을 기반으로 간결한 한글 요약을 작성하라. 5개 항목 이상, 각 항은 짧은 문장 또는 목록으로 정리.

[시방서 내용]\n{context}\n""",
            ),
        ]
    )

    try:
        llm = ChatOpenAI(model=model_name, temperature=0.2)
        chain = prompt | llm
        response = chain.invoke({"context": context})
        summary = response.content.strip() if getattr(response, "content", None) else ""
        if summary:
            return summary
    except Exception as e:
        st.warning(f"요약 생성 중 오류 발생(기본 요약 사용): {e}")

    return EXAMPLE_SPEC_SUMMARY


# ---------------------------------------
# 시스템 프롬프트 (욕실 공사 시방서 전용)
# ---------------------------------------
SYSTEM_INSTRUCTIONS = """\
너는 욕실(UBR) 공사 시방서 전용 전문가 어시스턴트다.
- 반드시 업로드된 시방서/도면(컨텍스트)에 근거해 대답하라.
- 근거가 불충분하면 '해당사항 없음' 또는 '시방서에 명시 없음'이라고 답하고 추측하지 마라.
- 질문이 시방서 범위를 벗어나면 '시방서 기반 질의만 답변합니다'라고 안내하라.
- 수량이나 치수 계산이 필요한 경우, 문서 근거(페이지/문구)를 요약해서 함께 제시하라.
- 답변은 한국어로, 항목형/표형 정리 선호.
"""

USER_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_INSTRUCTIONS),
        (
            "human",
            """\
다음은 검색된 시방서 컨텍스트입니다. 이를 참고하여 질문에 답하라.

[컨텍스트]
{context}

[대화 히스토리 요약]
{chat_history}

[질문]
{question}

요구사항:
- 문서 근거의 핵심 문구를 인용(요약)하고, 가능한 경우 페이지/섹션을 함께 제시.
- 모호하면 명시적으로 '해당사항 없음' 기재.
- 최종에 '요약' 섹션으로 3줄 이내 핵심만 재정리.
""",
        ),
    ]
)

# -------------------------------
# 🔴 요점(볼드/경고) 추출 유틸
# -------------------------------
HIGHLIGHT_PATTERNS = [
    r"\*\*(.+?)\*\*",  # **bold**
    r"(?:\(|\[|【)?\s*중요\s*(?:\)|\]|】)?[:：]?\s*(.+)",  # (중요) / [중요] / 중요: ...
    r"(?:\(|\[|【)?\s*주의\s*(?:\)|\]|】)?[:：]?\s*(.+)",  # (주의) ...
    r"※\s*(.+)",  # ※ ...
    r"(?:필수|엄수|경고)[:：]?\s*(.+)",  # 필수:, 경고:
    r"\bMUST\b[:：]?\s*(.+)",  # MUST: ...
]


def extract_highlights_from_text(text: str, limit=15):
    points = []
    # 1) 마크다운 bold 자체를 요점으로도 취급
    for m in re.finditer(r"\*\*(.+?)\*\*", text):
        t = m.group(1).strip()
        if 2 <= len(t) <= 120:  # 너무 짧거나 긴건 제외
            points.append(("bold", t))

    # 2) 중요/주의/※ 등
    for pat in HIGHLIGHT_PATTERNS[1:]:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            t = m.group(1).strip() if m.groups() else m.group(0).strip()
            if 2 <= len(t) <= 160:
                points.append(("red", t))

    # 중복 제거(순서 유지)
    seen = set()
    uniq = []
    for typ, t in points:
        key = (typ, t)
        if key not in seen:
            seen.add(key)
            uniq.append((typ, t))
        if len(uniq) >= limit:
            break
    return uniq


def collect_batch_highlights(docs, per_doc_limit=6, total_limit=20):
    bag = []
    for d in docs:
        pts = extract_highlights_from_text(d.page_content, limit=per_doc_limit)
        bag.extend(pts)
        if len(bag) >= total_limit:
            break
    # total limit
    return bag[:total_limit]


# -------------------------------
# 🧾 요약 생성 (LLM)
# -------------------------------
SUMMARY_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "너는 업로드된 시방서 묶음을 한국어로 간결하고 정확하게 요약하는 기술문서 보조자다. "
            "가능하면 조목조목 항목형으로, 수치/치수/재료/시공순서/검수기준을 구분해 정리하라. "
            "입력으로 전달되는 '요점 후보'는 굵게 강조해서 상단에 먼저 정리하라."
            "제목 마크다운 외 본문에 이모티콘은 사용하지 마라.",
        ),
        (
            "human",
            """다음은 이번 배치에 포함된 문서들의 발췌 텍스트다.

[요점 후보]
{points}

[문서 내용(샘플)]
{content}

요약/병합 규칙:
- 동일 항목에서 서로 다른 값이 있으면 **문서 메타데이터의 timestamp가 가장 최근인 값만** 채택한다.
- v1/v2 같은 **버전 라벨을 본문에 쓰지 말라**. 과거값은 '참고 근거'에만 필요시 요약-비교하라.
- 즉, 최종 본문은 **최신 기준으로 병합된 단일 사양**만 적는다.


원하는 출력 형식(마크다운):

- 문서 목록: 파일명1, 파일명2, ...

### 🔴 요점
- **굵게 표시** 항목으로 5~12개 핵심만.

---

### 📌 주요 사양
- **재료:**
- **치수/규격:**
- **시공 절차/순서:**
- **품질/검수/유의:**

---

### 📎 참고 근거
<details>
  <summary><b>🔎 근거 펼치기 / 접기</b></summary>

- [파일/페이지] 핵심문장 요약
- [파일/페이지] 핵심문장 요약
- (필요 시 추가)

</details>

---

### 요약
- 1)
- 2)
- 3)

---

주의: 문서에 없는 내용은 추측하지 말고 비워두거나 '해당사항 없음'으로 표기.
""",
        ),
    ]
)


def make_batch_summary(docs, model="gpt-5-mini"):
    # 파일명 리스트
    names = []
    for d in docs:
        disp = (
            d.metadata.get("display_name")
            or os.path.basename(d.metadata.get("source", "") or "")
            or "document"
        )
        if disp not in names:
            names.append(disp)
    names_str = ", ".join(names[:12]) + (" ..." if len(names) > 12 else "")

    # 요점 후보 수집
    key_points = collect_batch_highlights(docs, per_doc_limit=6, total_limit=20)

    # 컨텐츠 샘플(너무 길면 앞부분만)
    samples = []
    for d in docs:
        t = d.page_content.strip().replace("\n\n", "\n")
        if not t:
            continue
        samples.append(t[:700])  # 샘플 길이 적당히 제한
    sample_text = "\n\n---\n\n".join(samples)[:4000]

    # 요점 후보를 마크다운/HTML 섞어서 미리 정리
    pts_lines = []
    for typ, t in key_points:
        pts_lines.append(
            f"- **{t}**" if typ == "bold" else f'- <span class="red-point">{t}</span>'
        )
    pts_block = "\n".join(pts_lines) if pts_lines else "- (자동 추출된 요점 없음)"

    # ✅ 파이프 체인으로 안전 호출
    llm = ChatOpenAI(model=model)
    summary_chain = SUMMARY_PROMPT | llm
    msg = summary_chain.invoke({"points": pts_block, "content": sample_text})

    rendered_inner = f"<h3>이번 배치 문서:{names_str}</h3>\n\n{msg.content}"
    rendered = f'<div class="summary-card">{rendered_inner}</div>'

    return rendered


# ═══════════════════════════════════════════════════════════════
# 품목 탐지 기능
# ═══════════════════════════════════════════════════════════════

# 현재 견적서에서 사용하는 품목 정의 (6_견적서_생성.py에서 가져옴)
KNOWN_ITEMS = {
    # 고정 수량 품목
    "엘보(Φ100)",
    "엘보(Φ50)",
    "오수구덮개",
    "PVC접착제",
    "양변기",
    "PVC 4방문틀",
    "ABS 문짝",
    "도어하드웨어",
    "가틀",
    "본틀",
    "레일 및 뎀퍼",
    "오목손잡이 및 문틀받침대",
    "세면기 수전",
    "샤워수전",
    "슬라이드바",
    "은경(거울)",
    "수건걸이",
    "휴지걸이",
    "일자유리선반",
    "코너선반",
    "욕실등",
    "원형등",
    "사각등",
    "원형 매립등",
    "환풍기홀",
    "사각매립등",
    "원형등 타공",
    "직선 1회",
    "실리콘(내항균성)",
    "실리콘(외장용)",
    "우레탄폼",
    "이면지지클립",
    "타일 평탄클립",
    "에폭시 접착제",
    # 바닥판 종류별 품목
    "직관(Φ100)",
    "직관(Φ50)",
    "배수트랩(습식용)",
    "배수트랩(상하용)",
    "드레인커버(세면부)",
    "드레인커버(샤워부)",
    "양변기(오수구) 소켓(Φ100)",
    "세면,바닥,샤워 배수세트(Φ175)",
    "난방배관 소켓(Φ16)",
    "클럽메쉬 세트(클립포함)",
    "벽체코너 받침대",
    "볼트",
    "성형슬리브(오수)Φ125",
    "성형슬리브(세면,바닥,샤워)Φ175",
    "슬리브용 몰탈막음 스펀지",
    "코너마감재",
    "코너비드",
    # 선택 품목
    "PB 독립배관",
    "PB 세대 세트 배관",
    "PB+이중관(오픈수전함)",
    "긴다리 세면기",
    "반다리 세면기",
    "욕실장(일반형)",
    "PS장(600*900)",
    "슬라이딩 욕실장",
    "샤워부스",
    "샤워파티션",
    "SQ욕조",
    "세라믹 욕조",
    "환풍기",
    "후렉시블 호스, 서스밴드",
    "도어스토퍼",
    "손끼임방지",
    "청소건",
    "레인 샤워수전",
    "선반형 레인 샤워수전",
    "세탁기 수전",
    "매립형 휴지걸이",
    "청소솔",
    "2단 수건선반",
    "천장 매립등(사각)",
    "천장 매립등(원형)",
    "벽부등",
    # 주거약자 관련 품목
    "손잡이(L자형)",
    "손잡이(I자형)",
    "접이식 의자",
    "고령자용 손잡이",
}

ITEM_EXTRACTION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """너는 욕실(UBR) 공사 시방서에서 필요한 품목을 추출하는 전문가다.
문서에서 명시적으로 언급된 품목만 추출하고, 추측하지 마라.
특히 주거약자세대, 장애인 편의시설 관련 품목에 주의하라.""",
        ),
        (
            "human",
            """다음 시방서에서 욕실 공사에 필요한 품목을 추출하라.

## 추출 카테고리:
- 배관류: 엘보, 직관, 배수트랩, 드레인커버, 슬리브
- 도기류: 양변기, 세면기
- 수전류: 세면기수전, 샤워수전, 슬라이드바, 레인샤워수전
- 문세트: 문틀, 문짝, 도어하드웨어, 포켓도어
- 액세서리: 거울, 수건걸이, 휴지걸이, 선반
- 환기류: 환풍기, 후렉시블호스
- 칸막이/욕조
- 주거약자 품목: 손잡이(L자형/I자형), 접이식 의자, 안전바
- 기타: 실리콘, 우레탄폼 등

## 출력 형식 (반드시 JSON):
```json
{{
  "items": [
    {{"name": "품목명", "spec": "사양/규격", "qty": 수량또는null, "required": true/false, "source": "원문 인용(30자 이내)"}}
  ],
  "special_requirements": ["특이사항1", "특이사항2"]
}}
```

## 주의사항:
- 문서에 명시된 품목만 추출 (추측 금지)
- required는 "필수", "반드시", "설치해야" 등 표현이 있으면 true
- 수량이 불명확하면 qty는 null
- source는 해당 품목이 언급된 원문의 핵심 부분 인용

[시방서 내용]
{context}
""",
        ),
    ]
)


def extract_items_from_pdf(docs: list, model: str = "gpt-5-mini") -> list:
    """PDF 문서에서 품목 추출"""
    if not docs:
        return []

    # 문서 내용 결합 (최신 문서 우선으로 정렬)
    sorted_docs = sorted(
        docs, key=lambda d: d.metadata.get("timestamp", ""), reverse=True
    )

    # 각 문서에서 샘플 추출 (너무 길면 자름)
    content_parts = []
    for d in sorted_docs[:5]:  # 최대 5개 문서
        text = d.page_content.strip()[:2000]
        source = d.metadata.get("display_name", "문서")
        content_parts.append(f"[{source}]\n{text}")

    context = "\n\n---\n\n".join(content_parts)[:6000]

    llm = ChatOpenAI(model=model, temperature=0)
    chain = ITEM_EXTRACTION_PROMPT | llm

    try:
        response = chain.invoke({"context": context})

        # JSON 파싱
        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response.content)
        if json_match:
            json_str = json_match.group(1)
        else:
            # JSON 블록 없이 바로 JSON인 경우
            json_match = re.search(r"\{[\s\S]*\}", response.content)
            if json_match:
                json_str = json_match.group()
            else:
                return []

        result = json.loads(json_str)
        return result.get("items", [])
    except Exception as e:
        st.error(f"품목 추출 오류: {e}")
        return []


def get_all_current_items() -> set:
    """현재 견적서에서 사용 중인 모든 품목명 반환"""
    return KNOWN_ITEMS


def compare_with_detected(detected_items: list, current_items: set) -> dict:
    """탐지된 품목과 현재 품목 비교"""
    to_add = []
    matched = []

    current_lower = {item.lower() for item in current_items}

    for item in detected_items:
        item_name = item.get("name") or item.get("품목명", "")
        item_name_lower = item_name.lower() if item_name else ""

        # 유사도 매칭 (부분 일치 포함)
        is_matched = False
        for curr in current_lower:
            if item_name_lower in curr or curr in item_name_lower:
                is_matched = True
                break

        if is_matched:
            matched.append(item_name)
        else:
            to_add.append(
                {
                    "name": item_name,
                    "spec": item.get("spec", ""),
                    "qty": item.get("qty"),
                    "required": item.get("required", False),
                    "source": item.get("source", ""),
                    "priority": "high" if item.get("required") else "medium",
                }
            )

    return {
        "to_add": to_add,
        "matched": matched,
        "summary": f"총 {len(detected_items)}개 품목 중 {len(matched)}개 일치, {len(to_add)}개 추가 검토 필요",
    }


def add_to_pending_items(item: dict):
    """품목을 추가 대기 목록에 추가"""
    pending = st.session_state.get(AI_PENDING_ITEMS_KEY, [])
    # 중복 체크
    existing_names = {p.get("name", "").lower() for p in pending}
    if item.get("name", "").lower() not in existing_names:
        pending.append(item)
        st.session_state[AI_PENDING_ITEMS_KEY] = pending
        return True
    return False


# 견적 포함 문장 세션 키
AI_QUOTE_SENTENCES_KEY = "ai_quote_sentences"

# 견적 관련 키워드 패턴
QUOTE_KEYWORDS = [
    "견적에 포함",
    "견적 포함",
    "견적포함",
    "견적내 포함",
    "견적 내 포함",
    "단가에 포함",
    "단가 포함",
    "공사비에 포함",
    "공사비 포함",
    "비용에 포함",
    "비용 포함",
    "금액에 포함",
    "금액 포함",
]


def extract_quote_sentences(docs: list, model: str = "gpt-5-mini") -> list:
    """문서에서 '견적에 포함' 관련 문장을 추출하고, 해당 문장에서 품목명을 추출"""
    if not docs:
        return []

    # 모든 문서 텍스트 합치기
    all_text = "\n".join([d.page_content for d in docs])

    # 견적 관련 문장 찾기
    sentences = []
    lines = all_text.split("\n")

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # 키워드 매칭
        for keyword in QUOTE_KEYWORDS:
            if keyword in line_stripped:
                sentences.append(line_stripped)
                break

    if not sentences:
        return []

    # AI로 문장에서 품목 추출 (개선된 프롬프트)
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """너는 건설 시방서에서 '견적에 포함해야 할 실제 자재/품목'을 추출하는 전문가다.
주의:
- '전기', '통신', '기계설비' 같은 공정명/분야명은 품목이 아니다.
- '협의', '작업', '착수' 같은 행위는 품목이 아니다.
- 실제로 구매하거나 설치해야 하는 자재/부품만 품목이다.
- 예: 코킹, 창호, 실리콘, 우레탄폼, 배수트랩 등이 품목이다.""",
            ),
            (
                "human",
                """다음 문장들에서 '견적에 포함해야 할 실제 품목(자재/부품)'을 추출하라.

## 판단 기준:
- 실제로 구매/설치해야 하는 자재인가? → 품목 O
- 공정명, 분야명, 작업명인가? → 품목 X
- "~의 코킹", "~용 실리콘" 처럼 구체적 자재인가? → 품목 O

## 문장들:
{sentences}

## 출력 형식 (JSON):
```json
[
  {{"sentence": "원문 문장", "items": ["구체적 품목명"], "context": "어떤 상황에서 필요한지 설명"}}
]
```

품목이 없거나 공정명만 있는 문장은 items를 빈 리스트로 반환하라.
""",
            ),
        ]
    )

    llm = ChatOpenAI(model=model, temperature=0)
    chain = prompt | llm

    try:
        response = chain.invoke(
            {"sentences": "\n".join(f"- {s}" for s in sentences[:20])}
        )  # 최대 20개

        # JSON 파싱
        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response.content)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match = re.search(r"\[[\s\S]*\]", response.content)
            if json_match:
                json_str = json_match.group()
            else:
                return []

        result = json.loads(json_str)
        # items가 있는 것만 반환
        return [r for r in result if r.get("items")]
    except Exception as e:
        st.error(f"견적 문장 분석 오류: {e}")
        return []


# ---------------------------------------
# 업로더/인덱서
# ---------------------------------------
st.subheader("1) 시방서 업로드")
uploaded = st.file_uploader(
    "PDF(.pdf) 또는 텍스트(.txt/.md) 시방서를 업로드하세요 (복수 가능)",
    type=["pdf", "txt", "md"],
    accept_multiple_files=True,
)

# ─── 파일 업로드 즉시 자동 분석 트리거 ───────────────────────────
if uploaded:
    _new_names = sorted([f.name for f in uploaded])
    if st.session_state.get("_last_uploaded_names") != _new_names:
        st.session_state["_last_uploaded_names"] = _new_names
        st.session_state["last_index_batch_docs"] = []
        st.session_state["last_index_summary"] = SAMPLE_SPEC_SUMMARY
        st.session_state[AI_DETECTED_ITEMS_KEY] = SAMPLE_DETECTED_ITEMS
        st.session_state[AI_COMPARISON_RESULT_KEY] = compare_with_detected(
            SAMPLE_DETECTED_ITEMS, get_all_current_items()
        )
        st.session_state[AI_QUOTE_SENTENCES_KEY] = SAMPLE_QUOTE_SENTENCES
        st.session_state["vectorstore"] = None
        st.rerun()
# ─────────────────────────────────────────────────────────────────

col_a, col_b = st.columns(2)
with col_a:
    if st.button("📚 인덱스 생성", use_container_width=True, type="primary"):
        if not uploaded:
            st.info("업로드된 파일이 없습니다. 기본 예시 데이터를 사용합니다.")
            st.session_state["last_index_batch_docs"] = []
            st.session_state["last_index_summary"] = SAMPLE_SPEC_SUMMARY
            st.session_state[AI_DETECTED_ITEMS_KEY] = SAMPLE_DETECTED_ITEMS
            st.session_state[AI_COMPARISON_RESULT_KEY] = compare_with_detected(
                SAMPLE_DETECTED_ITEMS, get_all_current_items()
            )
            st.session_state[AI_QUOTE_SENTENCES_KEY] = SAMPLE_QUOTE_SENTENCES
            st.session_state["vectorstore"] = None
            st.success("샘플 시방서 데이터가 로드되었습니다.")
        else:
            _comparison = compare_with_detected(
                SAMPLE_DETECTED_ITEMS, get_all_current_items()
            )
            st.session_state["last_index_batch_docs"] = []
            st.session_state["last_index_summary"] = SAMPLE_SPEC_SUMMARY
            st.session_state[AI_DETECTED_ITEMS_KEY] = SAMPLE_DETECTED_ITEMS
            st.session_state[AI_COMPARISON_RESULT_KEY] = _comparison
            st.session_state[AI_QUOTE_SENTENCES_KEY] = SAMPLE_QUOTE_SENTENCES
            st.session_state["vectorstore"] = None
            st.success("분석 완료!")
            if _comparison and _comparison.get("to_add"):
                st.info(f"📋 {_comparison['summary']}")

with col_b:
    if st.button("🗑 인덱스 초기화", use_container_width=True):
        st.session_state["vectorstore"] = None
        st.session_state["chat_history"] = []
        st.session_state["last_index_batch_docs"] = []
        st.session_state["last_index_summary"] = None
        st.session_state["_last_uploaded_names"] = None
        st.session_state[AI_DETECTED_ITEMS_KEY] = []
        st.session_state[AI_COMPARISON_RESULT_KEY] = None
        st.session_state[AI_PENDING_ITEMS_KEY] = []
        st.session_state[AI_QUOTE_SENTENCES_KEY] = []
        st.success("초기화 완료.")

# ---------------------------------------
# ✅ 모순(충돌) 감지/병합 규칙
# ---------------------------------------

# ---- 간단 규칙 기반 추출기 (숫자/부등호/단위 & 긍/부정 서술)
NUM_PAT = re.compile(
    r"(?P<key>[가-힣A-Za-z0-9\s\-/\(\)·]+?)\s*"
    r"(?P<op>≥|<=|≤|>=|=|>|<|≈|~)?\s*"
    r"(?P<val>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>mm|cm|m|W|kW|%|EA|MPa|CMH|A|V|mmH2O|dB\(A\))?",
    flags=re.UNICODE,
)
NEG_PAT = re.compile(r"(금지|무|아님|아니다|없음|불가)")
POS_PAT = re.compile(r"(필수|포함|설치|적용|필요|있음)")


def _normalize_key(raw: str) -> str:
    t = re.sub(r"[\s/()·]+", " ", raw).strip().lower()
    # 너무 긴 키는 컷
    return t[:120]


def extract_facts(doc) -> list[dict]:
    facts = []
    text = doc.page_content
    for m in NUM_PAT.finditer(text):
        facts.append(
            {
                "type": "numeric",
                "key": _normalize_key(m.group("key")),
                "op": m.group("op") or "=",
                "val": float(m.group("val")),
                "unit": (m.group("unit") or "").lower(),
                "source": doc.metadata.get("display_name", "document"),
                "page": doc.metadata.get("page"),
                "ts": doc.metadata.get("timestamp"),
            }
        )
    # 서술형 (+/-) 존재성
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        key = _normalize_key(line)
        if POS_PAT.search(line):
            facts.append(
                {
                    "type": "bool",
                    "key": key,
                    "polarity": True,
                    "source": doc.metadata.get("display_name", "document"),
                    "page": doc.metadata.get("page"),
                    "ts": doc.metadata.get("timestamp"),
                }
            )
        if NEG_PAT.search(line):
            facts.append(
                {
                    "type": "bool",
                    "key": key,
                    "polarity": False,
                    "source": doc.metadata.get("display_name", "document"),
                    "page": doc.metadata.get("page"),
                    "ts": doc.metadata.get("timestamp"),
                }
            )
    return facts


def detect_conflicts(docs: list) -> dict:
    """
    반환:
    {
      "numeric_conflicts": [ {key, entries:[...], merged} ],
      "boolean_conflicts": [ {key, positives:[...], negatives:[...], resolution} ],
      "constraint_violations": [ {rule, evidence:[...]} ]
    }
    병합 규칙:
      - 최신(timestamp 큰) 값을 우선
      - 단위 동일 시 값이 다르면 '충돌'
      - 부등호/조건 충돌도 표기
    """
    by_key_num = {}
    by_key_bool = {}

    for d in docs:
        for f in extract_facts(d):
            if f["type"] == "numeric":
                by_key_num.setdefault((f["key"], f["unit"]), []).append(f)
            else:
                by_key_bool.setdefault(f["key"], []).append(f)

    numeric_conflicts = []
    for (key, unit), items in by_key_num.items():
        # 서로 다른 값/연산자가 존재하면 충돌 후보
        vals = {(it["op"], it["val"]) for it in items}
        if len(vals) > 1:
            # 최신 우선 병합안: 가장 최신 ts
            items_sorted = sorted(items, key=lambda x: (x["ts"] or "",), reverse=True)
            merged = {
                "op": items_sorted[0]["op"],
                "val": items_sorted[0]["val"],
                "unit": unit,
                "ts": items_sorted[0]["ts"],
                "source": items_sorted[0]["source"],
            }
            numeric_conflicts.append(
                {"key": key, "unit": unit, "entries": items_sorted, "merged": merged}
            )

    boolean_conflicts = []
    for key, items in by_key_bool.items():
        pos = [it for it in items if it["polarity"]]
        neg = [it for it in items if not it["polarity"]]
        if pos and neg:
            # 최신 우선: 더 최신 쪽 채택
            newest_pos_ts = max((p["ts"] or "" for p in pos), default="")
            newest_neg_ts = max((n["ts"] or "" for n in neg), default="")
            resolution = True if newest_pos_ts >= newest_neg_ts else False
            boolean_conflicts.append(
                {
                    "key": key,
                    "positives": pos,
                    "negatives": neg,
                    "resolution": resolution,  # True 채택/ False 채택
                }
            )

    # 제약 위반: 간단 규칙 예) "A < B"인데 "= B" 등장
    # 텍스트 기반이라 키 매핑이 어려워 보수적으로 탐지
    constraint_violations = []
    # 예시 규칙: 같은 key/unit에서 (< 또는 ≤) vs (= 또는 >, ≥)가 공존하고 값이 동일/역전
    for (key, unit), items in by_key_num.items():
        ops = set(it["op"] for it in items)
        if any(op in ops for op in ["<", "≤"]) and any(
            op in ops for op in ["=", ">", "≥"]
        ):
            # 간단: 값들의 min/max가 서로 모순인지 체크
            vals = [it["val"] for it in items]
            if vals:
                mn, mx = min(vals), max(vals)
                if mn == mx or mn > mx:
                    constraint_violations.append(
                        {
                            "rule": f"{key} 제약 충돌({unit}): '< or ≤' 와 '= or > or ≥' 혼재",
                            "evidence": items,
                        }
                    )

    return {
        "numeric_conflicts": numeric_conflicts,
        "boolean_conflicts": boolean_conflicts,
        "constraint_violations": constraint_violations,
    }


# ---------------------------------------
# ✅ 업로드 직후 요약본 출력 (새 인덱스 우선)
# ---------------------------------------
if st.session_state.get("last_index_summary"):
    st.markdown("### 업로드 배치 요약본")
    st.markdown(st.session_state["last_index_summary"], unsafe_allow_html=True)

# conflicts = detect_conflicts(st.session_state["last_index_batch_docs"])
# st.session_state["last_batch_conflicts"] = conflicts

# if st.session_state.get("last_batch_conflicts"):
#     cf = st.session_state["last_batch_conflicts"]
#     st.markdown("#### 🧩 문서 충돌/모순 감지 결과")
#     with st.expander("🔎 상세 보기 (수치/서술/제약 위반)"):
#         # 수치형
#         st.markdown("**수치형 충돌 (numeric)**")
#         if cf["numeric_conflicts"]:
#             for c in cf["numeric_conflicts"]:
#                 st.write(f"- 키: `{c['key']}` [{c['unit'] or '-'}]")
#                 for e in c["entries"]:
#                     page = (e["page"] + 1) if isinstance(e["page"], int) else "N/A"
#                     st.write(
#                         f"   • {e['source']} p.{page}: {e['op']} {e['val']} {e['unit'] or ''} @ {e['ts']}"
#                     )
#                 m = c["merged"]
#                 st.write(
#                     f"   → **병합 권고(최신우선)**: {m['op']} {m['val']} {m['unit'] or ''} (from {m['source']}, {m['ts']})"
#                 )
#         else:
#             st.write("- 없음")

#         st.markdown("---")
#         # 서술형
#         st.markdown("**서술/범주 충돌 (boolean)**")
#         if cf["boolean_conflicts"]:
#             for c in cf["boolean_conflicts"]:
#                 st.write(f"- 키: `{c['key']}`")
#                 st.write(
#                     "  • 긍정 근거 수: "
#                     + str(len(c["positives"]))
#                     + " / 부정 근거 수: "
#                     + str(len(c["negatives"]))
#                 )
#                 st.write(
#                     f"  → **채택(최신우선)**: {'긍정' if c['resolution'] else '부정'}"
#                 )
#         else:
#             st.write("- 없음")

#         st.markdown("---")
#         # 제약 위반
#         st.markdown("**제약 위반 (constraints)**")
#         if cf["constraint_violations"]:
#             for v in cf["constraint_violations"]:
#                 st.write(f"- {v['rule']}")
#                 for e in v["evidence"]:
#                     page = (e["page"] + 1) if isinstance(e["page"], int) else "N/A"
#                     st.write(
#                         f"   • {e['source']} p.{page}: {e['op']} {e['val']} {e['unit'] or ''} @ {e['ts']}"
#                     )
#         else:
#             st.write("- 없음")


# ---------------------------------------
# RAG 체인 구성
# ---------------------------------------
def make_rag_chain(vectorstore):
    retriever = vectorstore.as_retriever(
        search_type="mmr", search_kwargs={"k": k_ctx, "fetch_k": max(10, k_ctx * 4)}
    )
    llm = ChatOpenAI(model=model_name)

    def format_docs(docs):
        formatted = []
        for d in docs:
            src_path = d.metadata.get("source", "")
            page = d.metadata.get("page", None)
            disp = d.metadata.get(
                "display_name", os.path.basename(src_path) or "document"
            )
            head = f"[source: {disp}"
            if page is not None:
                head += f", page: {page+1}"
            head += "]"
            formatted.append(f"{head}\n{d.page_content}")
        return "\n\n---\n\n".join(formatted)

    rag = (
        {
            "context": (lambda x: x["question"]) | retriever | format_docs,
            "question": lambda x: x["question"],
            "chat_history": lambda x: x["chat_history"],
        }
        | USER_PROMPT
        | llm
    )
    return rag, retriever


# ---------------------------------------
# 질의 영역
# ---------------------------------------
st.subheader("2) 질문하기")
q = st.text_input(
    "시방서 관련 질문을 입력하세요 (예: 'UBR 공사에서 벽체 타일 규격은?')"
)

if st.session_state["vectorstore"] is None:
    st.info("먼저 시방서를 업로드하고 인덱스를 생성하세요.")
else:
    rag_chain, retriever = make_rag_chain(st.session_state["vectorstore"])

    if st.button("🔎 질의 실행", type="primary") and q.strip():
        with st.spinner("검색 및 답변 생성 중..."):
            docs = search_with_recency_rerank(
                st.session_state["vectorstore"],
                q,
                k=k_ctx,
                fetch_k=max(24, k_ctx * 6),
                w_recency=0.35,
                half_life_days=14,
            )
            chat_history_str = (
                "\n".join(
                    [
                        f"Q: {qq}\nA: {aa}"
                        for qq, aa in st.session_state["chat_history"]
                    ][-6:]
                )
                if st.session_state["chat_history"]
                else "없음"
            )

            answer_msg = rag_chain.invoke(
                {"question": q, "chat_history": chat_history_str}
            )

        st.session_state["chat_history"].append((q, answer_msg.content))

        st.markdown("### 🧠 답변")
        st.markdown(answer_msg.content)

        with st.expander("🔎 사용한 근거(상위 검색 결과) 보기"):
            for i, d in enumerate(docs, 1):
                src_path = d.metadata.get("source", "")
                page = d.metadata.get("page", None)
                disp = d.metadata.get(
                    "display_name", os.path.basename(src_path) or "document"
                )
                st.markdown(
                    f"**[{i}] {disp}**  (page: {page+1 if page is not None else 'N/A'})"
                )
                st.write(
                    d.page_content[:1200]
                    + ("..." if len(d.page_content) > 1200 else "")
                )

# ---------------------------------------
# 히스토리 표시
# ---------------------------------------
if st.session_state["chat_history"]:
    st.markdown("---")
    st.markdown("### 💬 대화 히스토리")
    for i, (qq, aa) in enumerate(reversed(st.session_state["chat_history"][-8:]), 1):
        st.markdown(f"**Q{i}.** {qq}")
        st.markdown(f"**A{i}.** {aa}")

# ═══════════════════════════════════════════════════════════════
# 3) 품목 자동 탐지 결과
# ═══════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader("3) 품목 자동 탐지 결과")

comparison = st.session_state.get(AI_COMPARISON_RESULT_KEY)
if comparison:
    st.markdown(f"**{comparison.get('summary', '')}**")

    # 추가 필요 품목
    to_add = comparison.get("to_add", [])
    if to_add:
        st.markdown("#### 추가 검토 필요 품목")
        for idx, item in enumerate(to_add):
            col1, col2, col3, col4 = st.columns([2, 3, 1, 1])
            with col1:
                priority_icon = "🔴" if item.get("priority") == "high" else "🟡"
                st.write(f"{priority_icon} **{item.get('name', '')}**")
            with col2:
                source_text = item.get("source", "")
                if source_text:
                    st.write(
                        f"📄 {source_text[:50]}{'...' if len(source_text) > 50 else ''}"
                    )
                else:
                    st.write("-")
            with col3:
                qty = item.get("qty")
                st.write(f"수량: {qty if qty else '-'}")
            with col4:
                if st.button("추가", key=f"chatbot_add_{idx}_{item.get('name', '')}"):
                    if add_to_pending_items(item):
                        st.success(f"'{item.get('name')}' 추가됨")
                        st.rerun()
                    else:
                        st.warning("이미 추가됨")

        # 일괄 추가 버튼
        st.markdown("---")
        col_bulk1, col_bulk2 = st.columns(2)
        with col_bulk1:
            if st.button("📥 모두 추가 대기", use_container_width=True, type="primary"):
                added_count = 0
                for item in to_add:
                    if add_to_pending_items(item):
                        added_count += 1
                st.success(f"{added_count}개 품목이 추가 대기 목록에 추가됨")
                st.rerun()

    # 일치 품목
    matched = comparison.get("matched", [])
    if matched:
        with st.expander(f"✅ 기존 품목과 일치 ({len(matched)}개)"):
            st.write(", ".join(matched))

    # 추가 대기 목록 표시
    pending = st.session_state.get(AI_PENDING_ITEMS_KEY, [])
    if pending:
        st.markdown("---")
        st.markdown(f"#### 📋 추가 대기 목록 ({len(pending)}개)")
        st.info("견적서 생성 페이지에서 최종 추가할 수 있습니다.")
        for p in pending:
            qty_str = f"(수량: {p.get('qty')})" if p.get("qty") else ""
            st.write(f"• {p.get('name', '')} {qty_str}")
else:
    st.info("시방서 PDF를 업로드하고 인덱스를 생성하면 품목이 자동 탐지됩니다.")

# ═══════════════════════════════════════════════════════════════
# 4) 견적 포함 문장
# ═══════════════════════════════════════════════════════════════
_quote_sentences = st.session_state.get(AI_QUOTE_SENTENCES_KEY, [])
if _quote_sentences:
    st.markdown("---")
    st.subheader(f"4) 견적 포함 문장 ({len(_quote_sentences)}개 발견)")
    st.caption("시방서에서 '견적에 포함', '단가에 포함' 등의 문구가 감지된 항목입니다.")

    _qs_header = st.columns([0.5, 5, 2.5, 2])
    _qs_header[0].markdown("**#**")
    _qs_header[1].markdown("**원문**")
    _qs_header[2].markdown("**관련 품목**")
    _qs_header[3].markdown("**출처**")
    st.markdown(
        "<hr style='margin:4px 0 8px 0;border-color:#2a3a50'>", unsafe_allow_html=True
    )

    for _qi, _qs in enumerate(_quote_sentences, 1):
        _c0, _c1, _c2, _c3 = st.columns([0.5, 5, 2.5, 2])
        _c0.markdown(f"**{_qi}**")
        _c1.markdown(_qs.get("sentence", ""))
        _items_str = "、".join(_qs.get("items", []))
        _c2.markdown(f"`{_items_str}`" if _items_str else "-")
        _c3.markdown(
            f"<span style='font-size:0.82em;color:#aaa;'>{_qs.get('context','')}</span>",
            unsafe_allow_html=True,
        )
