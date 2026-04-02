import streamlit as st
from st_pages import Page, add_page_title, hide_pages
import auth


# 안전한 set_page_config
try:
    st.set_page_config(page_title="플랫폼 데모", page_icon="⚙️", layout="wide")
except Exception:
    pass


# 기본 Streamlit 페이지 네비게이션을 통합메인으로 전환하기 위해 숨김 처리
hide_pages(
    [
        "관리자",
        "로그인",
        "천장판 계산",
        "견적서 생성",
        "인건비 계산",
        "ERP 품목코드 생성",
    ]
)


# streamlit 1.x 사이드바 전체 기본 페이지 메뉴가 자동 표시될 때, CSS로 숨김
def hide_default_streamlit_page_nav():
    st.markdown(
        """
        <style>
          section[data-testid='stSidebar'] [role='navigation'] { display: none !important; }
          section[data-testid='stSidebar'] div[data-testid='stSidebarNav'] { display: none !important; }
          section[data-testid='stSidebar'] ul { display:none !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


hide_default_streamlit_page_nav()

# 로그인 체크

auth.require_auth()


# --- reuse the sidebar dark/pro mood from other pages (paste once per app) ---
def _sidebar_dark_and_slider_fix():
    st.markdown(
        """
    <style>
      :root{ --sb-bg:#0b1220; --sb-fg:#e2e8f0; --sb-muted:#cbd5e1; --sb-line:#1f2a44;
             --accent:#22d3ee; --accent-2:#06b6d4; --ink:#0f172a; --muted:#475569; --line:#e2e8f0; }
      section[data-testid="stSidebar"]{ background:var(--sb-bg)!important; color:var(--sb-fg)!important; border-right:1px solid var(--sb-line); }
      section[data-testid="stSidebar"] *{ color:var(--sb-fg)!important; }
      section[data-testid="stSidebar"] .stMarkdown p, section[data-testid="stSidebar"] label{ color:var(--sb-muted)!important; font-weight:600!important; }
      [data-testid="stAppViewContainer"] .stButton>button{
        background:linear-gradient(180deg,var(--accent),var(--accent-2))!important; color:#001018!important;
        border:0!important; font-weight:800!important; letter-spacing:.2px;
      }
      [data-testid="stAppViewContainer"] .stButton>button:hover{ filter:brightness(1.05); }
      .hero{
        border:1px solid var(--line); border-radius:18px; padding:28px 26px; margin:12px 0 32px;
        background:linear-gradient(180deg,#f8fafc, #f1f5f9);
      }
      .hero h1{ margin:0 0 .5rem 0; color:var(--ink); font-size:1.8rem; font-weight:800; }
      .hero p{ margin:.25rem 0 0; color:var(--muted); font-size:1.05rem; }

      /* ========== 섹션 타이틀 스타일 ========== */
      h3 {
        color:var(--ink) !important;
        font-weight:700 !important;
        margin-top:2rem !important;
        margin-bottom:1rem !important;
        position:relative;
        padding-bottom:0.5rem;
      }
      h3::after {
        content:'';
        position:absolute;
        bottom:0;
        left:0;
        width:60px;
        height:3px;
        background:linear-gradient(90deg, var(--accent), var(--accent-2));
        border-radius:2px;
      }

      .tile:hover{
        transform: translateY(-1px);
        box-shadow: 0 6px 14px rgba(0, 0, 0, .08) !important;
      }
      .tile{
        border:1px solid var(--line); border-radius:16px; padding:18px; background:#fff;
        transition: transform .08s ease, box-shadow .2s ease;
        box-shadow:0 1px 3px rgba(0,0,0,.06);
      }
      .tile h3{ margin:.25rem 0 .5rem; font-size:1.05rem; color:#0f172a; }
      .tile p{ margin:0; color:#475569; font-size:.95rem; }
      .tile .cta{ margin-top:12px; }

  /* ========== 페이지 링크 카드 스타일 ========== */
  div[data-testid^="stPageLink"] > *,
  div[data-testid="stPageLink"] > *{
    display:block;
    border:1px solid var(--line) !important;
    border-radius:16px !important;
    padding:20px !important;
    background:#fff !important;
    box-shadow:0 2px 8px rgba(0,0,0,.08) !important;
    transition: all .2s ease !important;
    position:relative;
    overflow:hidden;
  }

  /* 왼쪽 컬러 액센트 바 */
  div[data-testid^="stPageLink"] > *::before {
    content: '';
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 4px;
    background: linear-gradient(180deg, var(--accent), var(--accent-2));
    opacity: 0;
    transition: opacity 0.2s ease;
  }

  div[data-testid^="stPageLink"]:hover > *::before,
  div[data-testid="stPageLink"]:hover > *::before {
    opacity: 1;
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
    padding-left:12px !important;
    cursor:pointer !important;
    text-decoration:none !important;
    line-height:1.6 !important;
  }

  div[data-testid^="stPageLink"]:hover > *,
  div[data-testid="stPageLink"]:hover > * {
    transform: translateY(-2px);
    box-shadow: 0 8px 20px rgba(0, 0, 0, .12) !important;
  }

  /* 첫 줄(타이틀) 강조 */
  div[data-testid^="stPageLink"] a::first-line,
  div[data-testid^="stPageLink"] p::first-line,
  div[data-testid="stPageLink"] a::first-line,
  div[data-testid="stPageLink"] p::first-line,
  div[data-testid^="stPageLink"] > *::first-line,
  div[data-testid="stPageLink"] > *::first-line {
    font-weight:800;
    font-size:1.15rem;
    letter-spacing: -0.02em;
  }

  /* 두 번째 줄(설명) 스타일 */
  div[data-testid^="stPageLink"] a,
  div[data-testid="stPageLink"] a {
    display:block !important;
  }


  span[label="app main"] {
      font-size: 0 !important;          /* 기존 글자 숨김 */
      position: relative;
  }
  span[label="app main"]::after {
      content: "메인";                  /* 원하는 표시 이름 */
      font-size: 1rem !important;       /* 기본 폰트 크기로 복원 */
      color: #fff !important;           /* 사이드바 글씨 색 (흰색) */
      font-weight: 700 !important;      /* 굵게 */
      position: absolute;
      left: 0;
      top: 0;
  }
  section[data-testid="stSidebarNav"] a[aria-label*="관리자"],
  section[data-testid="stSidebarNav"] a[aria-label*="로그인"] {
      display: none !important;
  }

    </style>
    """,
        unsafe_allow_html=True,
    )


_sidebar_dark_and_slider_fix()
# --- end reuse ---

# Sidebar: 사용자 정보 및 로그아웃
with st.sidebar:
    st.markdown("---")
    current_user = auth.get_current_user()
    user_info = auth.get_user_info(current_user)

    if user_info:
        st.markdown(f"**👤 {user_info['name']}**")
        role_text = "관리자" if user_info["role"] == "admin" else "사용자"
        st.caption(f"{role_text} • {user_info['username']}")

        if st.button("🚪 로그아웃", use_container_width=True):
            auth.logout()
            st.rerun()

# Hero
st.markdown(
    """
<div class="hero">
  <h1>통합 시스템</h1>
  <p>바닥/벽/천장 계산 도구로 바로 이동하세요.</p>
</div>
""",
    unsafe_allow_html=True,
)

# 섹션 제목
st.markdown("### 🔧 계산 도구")
st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# Row 1: AI 시방서, 바닥판, 벽판 규격
c1, c2, c3 = st.columns(3, gap="medium")

with c1:
    st.page_link(
        "pages/0_AI_시방서_분석.py",
        label="💬 0 AI 시방서 분석\n시방서 업로드 + 항목 탐지",
        icon=None,
    )

with c2:
    st.page_link(
        "pages/1_바닥판_계산.py",
        label="🟦 1 바닥판 계산\n욕실 바닥 규격 산출",
        icon=None,
    )

with c3:
    st.page_link(
        "pages/2_벽판_계산_-_벽판_규격.py",
        label="🟥 2 벽판 계산\n욕실 벽판 규격 산출",
        icon=None,
    )

st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

# Row 2: 벽판 타일+원가 통합
c4, c5, c6 = st.columns(3, gap="medium")

with c4:
    st.page_link(
        "pages/5_천장판_계산.py",
        label="🟧 3 천장판 계산\n욕실 천장판 규격 산출",
        icon=None,
    )

with c5:
    st.write("")

st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
