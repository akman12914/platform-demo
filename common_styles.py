"""
common_styles.py
통합 시스템 공통 스타일 모듈
모든 페이지에서 일관된 디자인을 적용하기 위한 스타일 함수
"""

import streamlit as st


def apply_common_styles():
    """
    통합 시스템 전역 스타일 적용
    - 다크 사이드바 (네이비 배경, 밝은 텍스트)
    - 통일된 버튼, 입력 필드, 셀렉트박스 스타일
    - 메인 페이지 라벨 변경
    """
    st.markdown(
        """
    <style>
      :root{
        /* Sidebar dark palette */
        --sb-bg:#0b1220;         /* 다크 네이비 */
        --sb-fg:#e2e8f0;         /* 본문 텍스트 */
        --sb-muted:#cbd5e1;      /* 보조 텍스트 */
        --sb-line:#1f2a44;       /* 경계선 */

        --accent:#f1f5f9;        /* 버튼 그라데이션 상단 (거의 흰색) */
        --accent-2:#cbd5e1;      /* 버튼 그라데이션 하단 (밝은 회색) */

        /* Main content neutrals */
        --ink:#0f172a;           /* 본문 텍스트 (메인 영역) */
        --muted:#475569;         /* 보조 텍스트 (메인 영역) */
        --line:#e2e8f0;          /* 경계선 (메인 영역) */
      }

      /* ========== Sidebar Dark Theme ========== */
      section[data-testid="stSidebar"]{
        background:var(--sb-bg)!important;
        color:var(--sb-fg)!important;
        border-right:1px solid var(--sb-line);
      }
      section[data-testid="stSidebar"] *{
        color:var(--sb-fg)!important;
      }
      section[data-testid="stSidebar"] h1,
      section[data-testid="stSidebar"] h2,
      section[data-testid="stSidebar"] h3{
        color:var(--sb-fg)!important;
      }

      /* 보조 텍스트/라벨 */
      section[data-testid="stSidebar"] .stMarkdown p,
      section[data-testid="stSidebar"] label,
      section[data-testid="stSidebar"] .stSelectbox label{
        color:var(--sb-muted)!important;
        font-weight:600!important;
      }

      /* Inputs in sidebar */
      section[data-testid="stSidebar"] input,
      section[data-testid="stSidebar"] textarea,
      section[data-testid="stSidebar"] select,
      section[data-testid="stSidebar"] .stTextInput input,
      section[data-testid="stSidebar"] .stNumberInput input{
        background:rgba(255,255,255,0.06)!important;
        border:1px solid var(--sb-line)!important;
        color:#000000!important;
      }

      /* ========== Slider cutoff fix ========== */
      section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{
        padding-right:12px;
      }
      section[data-testid="stSidebar"] div[data-testid="stSlider"]{
        padding-right:12px;
        margin-right:2px;
        overflow:visible;
      }
      section[data-testid="stSidebar"] div[role="slider"]{
        box-shadow:0 0 0 2px rgba(20,184,166,0.25);
        border-radius:999px;
      }

      /* ========== Radio Buttons ========== */
      input[type="radio"]{
        accent-color: var(--accent);
      }
      div[role="radiogroup"] label{
        display:flex;
        align-items:center;
        gap:.5rem;
        line-height:1.2;
        margin: .1rem 0;
      }
      div[role="radiogroup"] input[type="radio"]{
        transform: translateY(0px);
      }

      /* ========== Buttons ========== */
      section[data-testid="stSidebar"] .stButton>button,
      [data-testid="stAppViewContainer"] .stButton>button{
        background:linear-gradient(180deg,var(--accent),var(--accent-2))!important;
        color:#001018!important;
        border:0!important;
        font-weight:800!important;
        letter-spacing:.2px;
        border-radius:10px;
        padding:.55rem 1rem;
      }
      section[data-testid="stSidebar"] .stButton>button:hover,
      [data-testid="stAppViewContainer"] .stButton>button:hover{
        filter:brightness(1.05);
      }

      /* Primary button text color */
      button[data-testid="stBaseButton-primary"] p {
        color: var(--ink) !important;
        font-weight: 700 !important;
      }

      /* ========== Image spacing ========== */
      [data-testid="stImage"]{
        margin:6px 0 18px!important;
      }
      [data-testid="stImage"] img{
        display:block;
      }

      /* ========== Page label rename (메인) ========== */
      span[label="app main"] {
        font-size: 0 !important;
        position: relative;
      }
      span[label="app main"]::after {
        content: "메인";
        font-size: 1rem !important;
        color: #fff !important;
        font-weight: 700 !important;
        position: absolute;
        left: 0;
        top: 0;
      }

      /* ========== NumberInput stepper buttons ========== */
      button[data-testid="stNumberInputStepUp"] svg,
      button[data-testid="stNumberInputStepDown"] svg {
        color: #000000 !important;
        fill: #000000 !important;
      }
      button[data-testid="stNumberInputStepUp"]:hover svg,
      button[data-testid="stNumberInputStepDown"]:hover svg {
        color: #000000 !important;
        fill: #000000 !important;
      }

      /* ========== Selectbox styling ========== */
      div[data-baseweb="select"] div[role="combobox"],
      div[data-baseweb="select"] div[role="combobox"] input,
      div[data-baseweb="select"] div[value] {
        color: var(--sb-muted) !important;
        font-weight: 600 !important;
      }
      div[data-baseweb="select"] svg {
        color: var(--sb-muted) !important;
        fill: var(--sb-muted) !important;
      }
      div[data-baseweb="select"]:hover div[value],
      div[data-baseweb="select"]:hover svg {
        color: var(--sb-muted) !important;
        fill: var(--sb-muted) !important;
      }

      /* ========== FileUploader styling ========== */
      section[data-testid="stFileUploaderDropzone"] {
        border: 2px dashed var(--sb-line) !important;
        background: rgba(255,255,255,0.03) !important;
        color: var(--sb-muted) !important;
        border-radius: 10px !important;
        padding: 12px !important;
      }
      section[data-testid="stFileUploaderDropzone"] svg {
        color: var(--sb-muted) !important;
        fill: var(--sb-muted) !important;
      }
      section[data-testid="stFileUploaderDropzone"] span {
        color: var(--sb-muted) !important;
        font-weight: 600 !important;
      }
      section[data-testid="stFileUploaderDropzone"] button {
        background: linear-gradient(180deg,var(--accent),var(--accent-2)) !important;
        color: #001018 !important;
        border: 0 !important;
        font-weight: 700 !important;
        border-radius: 8px !important;
        padding: .4rem .9rem !important;
      }
      section[data-testid="stFileUploaderDropzone"] button:hover {
        filter: brightness(1.05);
      }

      /* ========== Image container (prevent upscaling) ========== */
      div[data-testid="stImage"] {
        display: block !important;
        max-width: 100% !important;
        margin: 2rem auto !important;
        text-align: center !important;
        position: relative !important;
      }
      div[data-testid="stImage"] img {
        width: auto !important;
        height: auto !important;
      }

      /* Image caption spacing */
      div[data-testid="stImageCaption"] {
        margin-top: 1rem !important;
      }

      /* ========== Sidebar Alert styling ========== */
      section[data-testid="stSidebar"] div[data-testid="stAlertContainer"] {
        background: transparent !important;
        border: 1px solid #555 !important;
        color: #e2e2e2 !important;
        border-radius: 6px !important;
        padding: 0.6rem !important;
      }
      section[data-testid="stSidebar"] div[data-testid="stAlertContainer"] * {
        color: inherit !important;
        fill: inherit !important;
      }
      section[data-testid="stSidebar"] div[data-testid="stAlertContainer"] svg {
        color: #bbb !important;
        fill: #bbb !important;
      }

      /* ========== Hero card (main page) ========== */
      .hero{
        border:1px solid var(--line);
        border-radius:18px;
        padding:28px 26px;
        margin:12px 0 32px;
        background:linear-gradient(180deg,#f8fafc, #f1f5f9);
      }
      .hero h1{
        margin:0 0 .5rem 0;
        color:var(--ink);
        font-size:1.6rem;
      }
      .hero p{
        margin:.25rem 0 0;
        color:var(--muted);
      }

      /* ========== Tile styling (for page links) ========== */
      .tile:hover{
        transform: translateY(-1px);
        box-shadow: 0 6px 14px rgba(0, 0, 0, .08) !important;
      }
      .tile{
        border:1px solid var(--line);
        border-radius:16px;
        padding:18px;
        background:#fff;
        transition: transform .08s ease, box-shadow .2s ease;
        box-shadow:0 1px 3px rgba(0,0,0,.06);
      }
      .tile h3{
        margin:.25rem 0 .5rem;
        font-size:1.05rem;
        color:#0f172a;
      }
      .tile p{
        margin:0;
        color:#475569;
        font-size:.95rem;
      }
      .tile .cta{
        margin-top:12px;
      }

      /* Page link styling */
      div[data-testid^="stPageLink"] > *,
      div[data-testid="stPageLink"] > *{
        display:block;
        border:1px solid var(--line) !important;
        border-radius:16px !important;
        padding:18px !important;
        background:#fff !important;
        box-shadow:0 1px 3px rgba(0,0,0,.06) !important;
        transition: transform .08s ease, box-shadow .2s ease !important;
      }
      div[data-testid^="stPageLink"] a,
      div[data-testid^="stPageLink"] p,
      div[data-testid="stPageLink"] a,
      div[data-testid="stPageLink"] p,
      div[data-testid^="stPageLink"] > *,
      div[data-testid="stPageLink"] > * {
        color:var(--ink) !important;
        white-space:pre-line !important;
        font-size:.95rem !important;
        margin:0 !important;
        cursor:pointer !important;
        text-decoration:none !important;
      }

      .stpagelink div[data-testid="stPageLink"]:hover > * {
        transform: translateY(-1px);
        box-shadow: 0 6px 14px rgba(0, 0, 0, .08) !important;
      }

      /* First line emphasis */
      div[data-testid^="stPageLink"] a::first-line,
      div[data-testid^="stPageLink"] p::first-line,
      div[data-testid="stPageLink"] a::first-line,
      div[data-testid="stPageLink"] p::first-line,
      div[data-testid^="stPageLink"] > *::first-line,
      div[data-testid="stPageLink"] > *::first-line {
        font-weight:800;
        font-size:1.08rem;
      }

      /* ========== Summary card (chatbot) ========== */
      .summary-card{
        border:1px solid var(--line);
        border-radius:14px;
        padding:16px 20px;
        background:#ffffff;
        margin-top:.5rem;
        margin-bottom:3.5rem;
      }
      .summary-card h1, .summary-card h2, .summary-card h3{
        margin-top:.6rem;
      }
      .summary-card hr{
        border:none;
        border-top:1px solid #e5e7eb;
        margin:12px 0;
      }
      .summary-card details{
        margin-top:.5rem;
        background:#f8fafc;
        border:1px solid #e2e8f0;
        border-radius:10px;
        padding:.5rem .75rem;
      }
      .summary-card summary{
        cursor:pointer;
        font-weight:700;
      }
    </style>
    """,
        unsafe_allow_html=True,
    )


def set_page_config(page_title: str, layout: str = "wide", page_icon: str = "⚙️"):
    """
    Streamlit 페이지 설정 (중복 호출 시 오류 방지)

    Args:
        page_title: 페이지 제목
        layout: 레이아웃 ("wide" 또는 "centered")
        page_icon: 페이지 아이콘
    """
    try:
        st.set_page_config(page_title=page_title, page_icon=page_icon, layout=layout)
    except Exception:
        # 이미 설정된 경우 무시
        pass
