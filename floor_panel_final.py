# floor_panel_final.py
# -*- coding: utf-8 -*-
# Floor base (바닥판) matching + costing + plan preview (사각/코너) + 통합 플랫폼 연동

from __future__ import annotations
import io
import os
import json
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List

import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw

# --- Common Styles ---
from common_styles import apply_common_styles, set_page_config
from common_sidebar import render_chatbot_sidebar

# --- Authentication ---
import auth

# =========================================
# Page Configuration
# =========================================
set_page_config(page_title="바닥판 계산 프로그램 (통합)", layout="wide")
apply_common_styles()
auth.require_auth()

# 사이드바에 시방서 분석 결과 표시
render_chatbot_sidebar()

# =========================================
# Session State Keys
# =========================================
EXPORT_DIR = "exports"
os.makedirs(EXPORT_DIR, exist_ok=True)

FLOOR_DONE_KEY = "floor_done"
FLOOR_RESULT_KEY = "floor_result"
CEIL_DONE_KEY = "ceil_done"
CEIL_RESULT_KEY = "ceil_result"
WALL_DONE_KEY = "wall_done"
WALL_RESULT_KEY = "wall_result"

# 공유 데이터 키
SHARED_EXCEL_KEY = "shared_excel_file"
SHARED_EXCEL_NAME_KEY = "shared_excel_filename"
SHARED_BATH_SHAPE_KEY = "shared_bath_shape"
SHARED_BATH_WIDTH_KEY = "shared_bath_width"
SHARED_BATH_LENGTH_KEY = "shared_bath_length"
SHARED_SINK_WIDTH_KEY = "shared_sink_width"
SHARED_SINK_LENGTH_KEY = "shared_sink_length"
SHARED_SHOWER_WIDTH_KEY = "shared_shower_width"
SHARED_SHOWER_LENGTH_KEY = "shared_shower_length"
SHARED_MATERIAL_KEY = "shared_floor_material"

# 코너형 치수 공유 키 (v3, v4, v5, v6)
SHARED_CORNER_V3_KEY = "shared_corner_v3"  # 세면부 길이
SHARED_CORNER_V4_KEY = "shared_corner_v4"  # 오목 세로
SHARED_CORNER_V5_KEY = "shared_corner_v5"  # 샤워부 길이
SHARED_CORNER_V6_KEY = "shared_corner_v6"  # 샤워부 폭

# =========================================
# Utility Functions
# =========================================
def _save_json(path: str, data: dict):
    """JSON 파일 저장"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# =========================================
# App & Sidebar
# =========================================
st.title("바닥판 계산 프로그램 (통합)")

with st.sidebar:
    st.header("① 데이터 업로드")
    uploaded = st.file_uploader("엑셀 업로드 (필수 시트: '바닥판', 'PVE' / 선택: '시공비')", type=["xlsx", "xls"])

    st.header("② 기본 입력")
    units = st.number_input("시공 세대수", min_value=1, step=1, value=100)
    # ★ 유형에 '타일일체형' 추가
    user_type  = st.radio("유형", ["기본형", "중앙배수", "타일일체형"], horizontal=True)
    shape      = st.radio("형태", ["사각형", "코너형"], horizontal=True)
    usage      = st.radio("용도", ["샤워형", "욕조형"], horizontal=True)
    is_access  = st.radio("주거약자 여부", ["아니오(일반형)", "예(주거약자)"], horizontal=True)
    boundary   = st.radio("경계", ["구분", "구분없음"], horizontal=True)

    st.header("③ 치수 입력 (mm)")

    # 기본 변수 초기화
    split = None
    sw = sl = shw = shl = None
    v3 = v4 = v5 = v6 = None

    if shape == "사각형":
        # 길이 = 가로(밑변), 폭 = 세로
        L = st.number_input("욕실 길이 L (가로, 밑변)", min_value=400, step=10, value=2100)
        W = st.number_input("욕실 폭   W (세로)",       min_value=400, step=10, value=1400)

        # 구분 선택 시에만 경계점 입력
        if boundary == "구분":
            st.caption("세면/샤워 경계점 위치(가로 기준, 0<경계점<L)")
            split = st.slider("세면/샤워 경계점 X (mm)", min_value=100, max_value=int(L)-100, step=50, value=min(1300, int(L)-100))
            # 세면/샤워 치수 계산
            sw, sl = W, split    # 세면부: 폭=W, 길이=split
            shw, shl = W, L - split
        # 구분없음: 욕실 크기만 사용

    else:  # 코너형
        # 구분 선택 시 4변 입력, 구분없음 시 욕실크기만 입력
        if boundary == "구분":
            st.caption("코너형 규칙: 1=3+5, 2=4+6 / 세면부(폭=2, 길이=3), 샤워부(폭=6, 길이=5)")
            colA, colB = st.columns(2)
            with colA:
                v3 = st.number_input("3번 변 (세면부 길이)",        min_value=200, step=50, value=1300)
                v5 = st.number_input("5번 변 (샤워부 길이)", min_value=200, step=50, value=900)
                v1 = int(v3 + v5)  # 1=3+5
                st.text_input("1번 = 3번 + 5번 (욕실 길이 L)", value=str(v1), disabled=True)
            with colB:
                v4 = st.number_input("4번 변 (오목 세로)", min_value=200, step=50, value=600)
                v6 = st.number_input("6번 변 (샤워부 폭)", min_value=200, step=50, value=900)
                v2 = int(v4 + v6)  # 2=4+6
                st.text_input("2번 = 4번 + 6번 (욕실 폭 W)", value=str(v2), disabled=True)

            L, W = v1, v2
            # 4변 입력 시 세면/샤워 세부 치수 설정
            sw, sl = W, v3
            shw, shl = v6, v5
        else:
            # 구분없음: 욕실크기만 입력
            L = st.number_input("욕실 길이 L (가로, 밑변)", min_value=400, step=10, value=2100)
            W = st.number_input("욕실 폭   W (세로)",       min_value=400, step=10, value=1400)

    st.write("---")
    do_calc = st.button("계산하기", type="primary")


# =========================================
# Helpers: Data
# =========================================
REQ_COLS = ["소재","유형","형태","용도","경계","욕실폭","욕실길이",
            "세면부폭","세면부길이","샤워부폭","샤워부길이",
            "세면부바닥판 단가","샤워부바닥판 단가","소계"]

def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # 보장 컬럼 생성
    for c in REQ_COLS:
        if c not in df.columns:
            df[c] = np.nan

    # 텍스트 표준화
    df["유형"]  = df["유형"].astype(str).str.strip()
    df["형태"]  = df["형태"].astype(str).str.strip().replace({"샤각형":"사각형"})
    df["용도"]  = df["용도"].astype(str).str.strip()
    if "경계" in df.columns:
        df["경계"]  = df["경계"].astype(str).str.strip()

    # 숫자 컬럼 정규화
    num_cols = ["욕실폭","욕실길이","세면부폭","세면부길이","샤워부폭","샤워부길이",
                "세면부바닥판 단가","샤워부바닥판 단가","소계"]
    for c in num_cols:
        df[c] = (
            df[c]
            .astype(str)
            .str.replace(",", "", regex=False)
            .replace({"nan":np.nan,"NaN":np.nan,"None":np.nan,"":np.nan})
        )
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


# =========================================
# PVE 비용 기본값 및 엑셀 로드
# =========================================
DEFAULT_PVE_COSTS = {
    "raw_unit_cost": 12000,  # 원/㎡
    "process_costs": {
        "일반형": 24331,
        "욕실선반형": 31159,
    }
}


def get_pve_process_cost(df_cost: pd.DataFrame) -> Optional[int]:
    """
    '시공비' 시트에서 항목=바닥판 이고 공정에 'PVE'가 포함된 행의 '시공비'를 반환.
    없으면 None.
    """
    df = df_cost.copy()
    df.columns = [str(c).strip() for c in df.columns]

    # 컬럼 매핑(유연 대응)
    col_map = {}
    for c in df.columns:
        cs = str(c).strip()
        if cs in ["항목", "Item"]:
            col_map["항목"] = c
        elif cs in ["공정", "공사", "Process"]:
            col_map["공정"] = c
        elif cs in ["시공비", "금액", "Cost"]:
            col_map["시공비"] = c

    if not {"항목","공정","시공비"}.issubset(col_map.keys()):
        return None

    def _clean_num(x):
        if pd.isna(x): return None
        s = str(x).replace(",", "").strip()
        try: return int(float(s))
        except: return None

    df["__항목"] = df[col_map["항목"]].astype(str).str.strip()
    df["__공정"] = df[col_map["공정"]].astype(str).str.strip()
    df["__시공비"] = df[col_map["시공비"]].apply(_clean_num)

    hit = df[
        (df["__항목"] == "바닥판") &
        (df["__공정"].str.contains("PVE", case=False, na=False))
    ]

    vals = hit["__시공비"].dropna()
    return int(vals.iloc[0]) if not vals.empty else None


def load_pve_costs_from_excel(xls: pd.ExcelFile) -> Dict[str, Any]:
    """'PVE' 시트에서 PVE 원재료비(㎡당)와 가공비(형태별)를 로드합니다."""
    out = {
        "raw_unit_cost": DEFAULT_PVE_COSTS["raw_unit_cost"],
        "process_costs": dict(DEFAULT_PVE_COSTS["process_costs"]),
        "source": "DEFAULT",
    }

    if "PVE" not in xls.sheet_names:
        return out

    try:
        df = pd.read_excel(xls, sheet_name="PVE")
    except Exception:
        return out

    if df is None or df.empty:
        return out

    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    type_col = None
    raw_col = None
    proc_col = None
    for c in df.columns:
        cs = str(c).strip()
        if type_col is None and ("유형" in cs or "타입" in cs or "Type" in cs):
            type_col = c
        if raw_col is None and ("원재료" in cs or "원가" in cs or "Raw" in cs):
            raw_col = c
        if proc_col is None and ("가공" in cs or "공정" in cs or "Process" in cs):
            proc_col = c

    # fallback: 첫 3개 컬럼 가정
    if type_col is None and len(df.columns) >= 1:
        type_col = df.columns[0]
    if raw_col is None and len(df.columns) >= 2:
        raw_col = df.columns[1]
    if proc_col is None and len(df.columns) >= 3:
        proc_col = df.columns[2]

    def _to_int(x) -> Optional[int]:
        if pd.isna(x):
            return None
        s = str(x).replace(",", "").strip()
        try:
            return int(float(s))
        except Exception:
            return None

    process_costs: Dict[str, int] = {}
    raw_unit_cost: Optional[int] = None

    for _, r in df.iterrows():
        t = str(r.get(type_col, "")).strip()
        if not t or t.lower() in ("nan", "none"):
            continue

        rv = _to_int(r.get(raw_col, None))
        pv = _to_int(r.get(proc_col, None))

        if rv is not None and raw_unit_cost is None:
            raw_unit_cost = rv
        if pv is not None:
            process_costs[t] = pv

    if raw_unit_cost is not None or process_costs:
        out["source"] = "PVE"
        if raw_unit_cost is not None:
            out["raw_unit_cost"] = int(raw_unit_cost)
        if process_costs:
            out["process_costs"] = {str(k).strip(): int(v) for k, v in process_costs.items()}

    return out


@st.cache_data
def load_floor_panel_data(file_data: bytes) -> Tuple[pd.DataFrame, Dict[str, Any], Optional[int]]:
    """바닥판 엑셀 로드 + 정규화 + PVE 비용정보 로드."""
    xls = pd.ExcelFile(io.BytesIO(file_data))

    missing_sheets = [s for s in ["바닥판", "PVE"] if s not in xls.sheet_names]
    if missing_sheets:
        raise ValueError(f"필수 시트 누락: {missing_sheets}")

    df_raw = pd.read_excel(xls, sheet_name="바닥판")
    df = normalize_df(df_raw)

    # 1) PVE 시트(우선)
    pve_costs = load_pve_costs_from_excel(xls)

    # 2) (호환) 시공비 시트에서 단일 PVE 공정비
    try:
        df_cost = pd.read_excel(xls, sheet_name="시공비")
        pve_process_cost_legacy = get_pve_process_cost(df_cost)
    except Exception:
        pve_process_cost_legacy = None

    return df, pve_costs, pve_process_cost_legacy


def exact_series(s: pd.Series, v: Optional[float]) -> pd.Series:
    if v is None:
        return pd.Series(True, index=s.index)
    return (~s.isna()) & (s.astype(float) == float(v))

# =========================================
# Helpers: Matching + Pricing
# =========================================
def compute_subtotal_from_row(row: pd.Series) -> Tuple[Optional[int], Optional[int], int]:
    """행에서 세면/샤워 단가 및 소계 계산."""
    sink = row.get("세면부바닥판 단가", np.nan)
    shower = row.get("샤워부바닥판 단가", np.nan)
    subtotal = row.get("소계", np.nan)

    sink_v = None if pd.isna(sink) else int(sink)
    shower_v = None if pd.isna(shower) else int(shower)

    if not pd.isna(subtotal):
        return sink_v, shower_v, int(subtotal)

    # 소계 없다면 계산
    if sink_v is not None and shower_v is not None:
        return sink_v, shower_v, int(sink_v + shower_v)

    # 그래도 없으면 0
    return sink_v, shower_v, 0

def pve_quote(
    W: int,
    L: int,
    is_access: bool,
    pve_costs: Dict[str, Any],
    process_type: str,
    pve_process_cost_legacy: Optional[int] = None,
) -> Dict[str, int | str]:
    """PVE 원가 산정 (PVE 시트 기반)."""
    add = 480 if is_access else 380
    Wm = (W + add) / 1000.0
    Lm = (L + add) / 1000.0
    area = Wm * Lm

    raw_unit = int(pve_costs.get("raw_unit_cost", DEFAULT_PVE_COSTS["raw_unit_cost"]))
    raw = int(round(area * raw_unit))

    proc_map = pve_costs.get("process_costs", {}) or {}
    process = proc_map.get(process_type)

    if process is None and pve_process_cost_legacy is not None:
        process = int(pve_process_cost_legacy)

    if process is None:
        process = DEFAULT_PVE_COSTS["process_costs"].get(
            process_type, DEFAULT_PVE_COSTS["process_costs"]["일반형"]
        )

    subtotal = int(raw + int(process))
    return {
        "소재": "PVE",
        "PVE가공형태": str(process_type),
        "원재료비": int(raw),
        "가공비": int(process),
        "소계": int(subtotal),
    }


def sidebar_pve_process_selector(decision_log: List[str]) -> str:
    """PVE로 결정된 경우, 사이드바에서 가공형태를 선택하게 하고 선택 로그를 남깁니다."""
    st.sidebar.markdown("---")
    st.sidebar.header("④ PVE 옵션")

    # session_state에 기본값이 없으면 초기화
    if "pve_process_type_selection" not in st.session_state:
        st.session_state["pve_process_type_selection"] = "일반형"

    pve_process_type = st.sidebar.radio(
        "PVE 가공 형태",
        ["일반형", "욕실선반형"],
        horizontal=True,
        key="pve_process_type_selection",
    )
    decision_log.append(f"PVE 가공형태 선택: {pve_process_type}")
    return pve_process_type

def match_exact(df: pd.DataFrame,
                user_type:str, shape:str, usage:str, boundary:Optional[str],
                W:int, L:int,
                sw:Optional[int], sl:Optional[int], shw:Optional[int], shl:Optional[int]) -> Optional[pd.Series]:
    """완전일치 매칭 규칙:
       공통키: 유형, 형태, 용도, 경계(사각형), 욕실폭, 욕실길이
       기본형(경계있음): + (세면부폭, 세면부길이, 샤워부폭, 샤워부길이)
       기본형(경계없음)/중앙배수: 욕실폭, 욕실길이만 일치
    """
    base = df[(df["유형"]==user_type) & (df["형태"]==shape) & (df["용도"]==usage)]

    # 경계 컬럼 확인 (boundary가 전달되면 해당 값으로 필터링)
    if boundary is not None:
        base = base[base["경계"].astype(str).str.strip() == boundary.strip()]

    if base.empty:
        return None

    c = exact_series(base["욕실폭"], W) & exact_series(base["욕실길이"], L)

    # 기본형이면서 세면/샤워 치수가 있는 경우만 추가 조건 검사
    if user_type == "기본형" and sw is not None:
        # 세면/샤워도 완전일치
        for col, val in [
            ("세면부폭", sw), ("세면부길이", sl),
            ("샤워부폭", shw), ("샤워부길이", shl)
        ]:
            c = c & exact_series(base[col], val)

    hit = base[c]
    if hit.empty:
        return None
    # 일치 다수면 소계 최소 선택
    hit2 = hit.sort_values("소계", ascending=True)
    return hit2.iloc[0]


def find_replacement_integrated(df: pd.DataFrame, material: str,
                               shape: str, usage: str,
                               W: int, L: int) -> Optional[Dict[str, Any]]:
    """
    GRP 기본형 매칭 성공 후, 같은 욕실 크기(W, L)의 GRP 일체형 찾기.
    찾으면 일체형으로 대체.
    """
    # 같은 욕실 크기의 일체형 찾기
    alt_df = df[
        (df["소재"] == material) &
        (df["유형"] == "일체형") &
        (df["형태"] == shape) &
        (df["용도"] == usage) &
        (exact_series(df["욕실폭"], W)) &
        (exact_series(df["욕실길이"], L))
    ]

    if alt_df.empty:
        return None

    # 소계 최소값 선택
    alt_df_sorted = alt_df.sort_values("소계", ascending=True)
    row = alt_df_sorted.iloc[0]

    sink, shower, subtotal = compute_subtotal_from_row(row)
    return {
        "유형": row["유형"],
        "형태": row["형태"],
        "세면부단가": sink,
        "샤워부단가": shower,
        "소계": subtotal,
        "row": row
    }

# =========================================
# Helpers: Drawing (PIL) — 비례 스케일
# =========================================
def draw_rect_plan(W:int, L:int, split: Optional[int]=None,
                   canvas_w:int=720, margin:int=18) -> Image.Image:
    """사각형: 길이 L=가로(밑변), 폭 W=세로. split는 가로 기준 경계점."""
    CANVAS_W = int(canvas_w)
    MARGIN   = int(margin)

    sx = (CANVAS_W - 2*MARGIN) / max(1.0, float(L))
    sy = sx
    CANVAS_H = int(W * sy + 2*MARGIN)

    img = Image.new("RGB", (CANVAS_W, CANVAS_H), "white")
    drw = ImageDraw.Draw(img)

    x0, y0 = MARGIN, MARGIN
    x1 = x0 + int(L * sx)
    y1 = y0 + int(W * sy)

    # 외곽
    drw.rectangle([x0, y0, x1, y1], outline="black", width=3)

    # 경계점(선택)
    if split is not None:
        gx = x0 + int(split * sx)
        drw.line([gx, y0, gx, y1], fill="blue", width=3)

    return img

def draw_corner_plan(v1:int, v2:int, v3:int, v4:int, v5:int, v6:int,
                     show_split: bool=True,
                     canvas_w:int=720, margin:int=18) -> Image.Image:
    """
    코너형: 전체 L=v1(가로), W=v2(세로)
      우상단 오목부 notch 크기 = (가로 v5, 세로 v6)
      샤워부는 오른쪽 하단에 위치시키며, 크기 = (가로 v5, 세로 v6)  ← 오목부와 동일 치수
      세면/샤워 경계점(옵션)은 v3 위치에 수직선
    """
    CANVAS_W = int(canvas_w)
    MARGIN   = int(margin)

    sx = (CANVAS_W - 2*MARGIN) / max(1.0, float(v1))
    sy = sx
    CANVAS_H = int(v2 * sy + 2*MARGIN)

    img = Image.new("RGB", (CANVAS_W, CANVAS_H), "white")
    drw = ImageDraw.Draw(img)

    x0, y0 = MARGIN, MARGIN
    def X(mm): return int(round(x0 + mm * sx))
    def Y(mm): return int(round(y0 + mm * sy))

    # 전체 외곽
    drw.rectangle([X(0), Y(0), X(v1), Y(v2)], outline="black", width=3)

    # 1) 우상단 오목부(VOID) : (가로 v5, 세로 v6)
    notch_x0, notch_x1 = v1 - v5, v1
    notch_y0, notch_y1 = 0, v6
    # 내부 지우기(흰색)
    drw.rectangle([X(notch_x0), Y(notch_y0), X(notch_x1), Y(notch_y1)],
                  fill="white", outline="white")
    # 오목 경계선(수직) 표시
    drw.line([X(notch_x0), Y(0),     X(notch_x0), Y(v6)], fill="black", width=3)

    # 2) 샤워부(오른쪽 하단) : 오목부와 동일 치수 (가로 v5, 세로 v6)
    shower_x0, shower_x1 = v1 - v5, v1
    shower_y0, shower_y1 = v2 - v6, v2
    drw.rectangle([X(shower_x0), Y(shower_y0), X(shower_x1), Y(shower_y1)],
                  outline="blue", width=3)

    # (선택) 세면/샤워 경계점: v3 위치 수직선
    if show_split:
        drw.line([X(v3), Y(0), X(v3), Y(v2)], fill="blue", width=3)

    return img


# =========================================
# Execution
# =========================================
if not uploaded:
    st.info("왼쪽에서 엑셀 파일(시트: **바닥판**, **PVE**)을 업로드한 뒤 **계산하기**를 눌러주세요. (※ **시공비** 시트는 있으면 호환용으로 추가 참고)")
    st.stop()

# --- 엑셀 파일 비교 및 선택 ---
from excel_compare import render_excel_comparison_ui

# 모든 시트 비교 (바닥판 계산이 첫 진입점이므로 여기서 전체 비교)
ALL_TARGET_SHEETS = ["바닥판", "바닥판단가", "천장판", "천장판타공", "자재단가내역", "벽판", "PVE"]

# 비교 UI 렌더링 (이전 파일과 비교, 선택에 따라 file_bytes 반환)
file_bytes = render_excel_comparison_ui(uploaded, ALL_TARGET_SHEETS, page_name="floor")

# 엑셀 파일을 세션에 저장 (다른 페이지에서 재사용)
if uploaded is not None:
    st.session_state[SHARED_EXCEL_KEY] = uploaded
    st.session_state[SHARED_EXCEL_NAME_KEY] = uploaded.name

# 엑셀 로딩 (캐시된 파싱 사용)
try:
    df, pve_costs, pve_process_cost_legacy = load_floor_panel_data(file_bytes)
except ValueError as e:
    st.error(f"필수 시트 누락: {e} — 엑셀에 '바닥판' 및 'PVE' 시트가 있는지 확인하세요.")
    st.stop()
except Exception as e:
    st.error(f"엑셀 파싱 실패: {e}")
    st.stop()

# ----- 계산 버튼 상태 관리 -----
if "floor_calc_done" not in st.session_state:
    st.session_state["floor_calc_done"] = False

if do_calc:
    st.session_state["floor_calc_done"] = True

if not st.session_state["floor_calc_done"]:
    st.info("사이드바에서 값을 입력한 뒤 **계산하기** 버튼을 눌러주세요.")
    st.stop()

# ===== 여기부터는 calc_done == True 일 때 항상 실행됨 =====

# 입력 유효성
if units < 1:
    st.error("세대수는 1 이상이어야 합니다.")
    st.stop()


# GRP 기본형 + 경계=구분 인 경우에만 세면/샤워 치수 체크
if user_type == "기본형" and boundary == "구분" and (
    sw is None or sl is None or shw is None or shl is None
):
    st.error("유형=기본형이고 경계=구분 인 경우 세면/샤워 치수가 필요합니다. 사이드바에서 경계 정보를 확인하세요.")
    st.stop()

decision_log: List[str] = []
selected_alternative = None
matched_user_type = user_type

# GRP 기본/코너형용 후보 저장
base_grp_result: Optional[Dict[str, Any]] = None
integrated_grp_result: Optional[Dict[str, Any]] = None

result: Optional[Dict[str, Any]] = None

# 0) 세대수 < 100 → PVE 강제
if units < 100:
    decision_log.append(f"세대수={units} (<100) → PVE 강제 선택")

    pve_process_type = sidebar_pve_process_selector(decision_log)
    pve = pve_quote(
        W, L,
        is_access=(is_access == "예(주거약자)"),
        pve_costs=pve_costs,
        process_type=pve_process_type,
        pve_process_cost_legacy=pve_process_cost_legacy,
    )
    result = {
        "소재": "PVE",
        "세면부단가": None,
        "샤워부단가": None,
        "PVE가공형태": pve.get("PVE가공형태"),
        "원재료비": pve.get("원재료비"),
        "가공비": pve.get("가공비"),
        "소계": pve["소계"],
    }

else:
    # 1) GRP 매칭
    # 타일일체형은 경계를 신경 쓰지 않고 욕실폭/길이만으로 매칭
    if user_type == "타일일체형":
        boundary_val = None
    else:
        boundary_val = boundary  # "구분" 또는 "구분없음" 그대로 전달

    grp_df = df[df["소재"].astype(str).str.startswith("GRP", na=False)]
    r_grp = match_exact(
        grp_df,
        user_type, shape, usage, boundary_val,
        W, L, sw, sl, shw, shl
    )

    if r_grp is not None:
        # GRP 기본/코너형인 경우: 일체형 후보까지 같이 계산하고,
        # 최종 선택은 아래에서 라디오 버튼으로 결정
        if user_type == "기본형":
            decision_log.append("GRP 기본/코너형 매칭 성공 (완전일치)")
            sink, shower, subtotal = compute_subtotal_from_row(r_grp)
            base_grp_result = {
                "소재": "GRP",
                "세면부단가": sink,
                "샤워부단가": shower,
                "소계": subtotal,
            }

            # 같은 욕실 크기의 GRP 일체형 찾기
            integrated_match = find_replacement_integrated(df, "GRP", shape, usage, W, L)
            if integrated_match is not None:
                decision_log.append("같은 욕실 크기의 GRP 일체형 데이터 발견")
                sink2, shower2, subtotal2 = (
                    integrated_match["세면부단가"],
                    integrated_match["샤워부단가"],
                    integrated_match["소계"],
                )
                integrated_grp_result = {
                    "소재": "GRP",
                    "세면부단가": sink2,
                    "샤워부단가": shower2,
                    "소계": subtotal2,
                }
            else:
                decision_log.append("같은 욕실 크기의 GRP 일체형 없음")

        else:
            # 중앙배수, 타일일체형 등: 대체 없이 그대로 사용
            decision_log.append("GRP 매칭 성공 (완전일치, 대체 없음)")
            sink, shower, subtotal = compute_subtotal_from_row(r_grp)
            result = {
                "소재": "GRP",
                "세면부단가": sink,
                "샤워부단가": shower,
                "소계": subtotal,
            }

    else:
        decision_log.append("GRP 매칭 실패 → FRP 탐색")
        # 2) FRP 매칭
        r_frp = match_exact(
            df[df["소재"] == "FRP"],
            user_type, shape, usage, boundary_val,
            W, L, sw, sl, shw, shl
        )
        if r_frp is not None:
            decision_log.append("FRP 매칭 성공 (완전일치)")
            sink, shower, subtotal = compute_subtotal_from_row(r_frp)
            result = {
                "소재": "FRP",
                "세면부단가": sink,
                "샤워부단가": shower,
                "소계": subtotal,
            }
        else:
            decision_log.append("FRP 매칭 실패")
            # 3) FRP도 안 맞으면 PVE
            if user_type == "중앙배수":
                decision_log.append("유형=중앙배수 → 매칭 실패로 PVE 계산")
            else:
                decision_log.append("GRP/FRP 모두 매칭 실패 → PVE 계산")

            pve_process_type = sidebar_pve_process_selector(decision_log)
            pve = pve_quote(
                W, L,
                is_access=(is_access == "예(주거약자)"),
                pve_costs=pve_costs,
                process_type=pve_process_type,
                pve_process_cost_legacy=pve_process_cost_legacy,
            )
            result = {
                "소재": "PVE",
                "세면부단가": None,
                "샤워부단가": None,
                "PVE가공형태": pve.get("PVE가공형태"),
                "원재료비": pve.get("원재료비"),
                "가공비": pve.get("가공비"),
                "소계": pve["소계"],
            }

# =========================================
# 도면 미리보기 (단가 확정 전에도 가능)
# =========================================
st.subheader("도면 미리보기")
if shape == "사각형":
    img = draw_rect_plan(W=W, L=L, split=(split if split is not None else None))
else:
    img = draw_corner_plan(
        v1=L, v2=W, v3=(sl if boundary == "구분" else 0),
        v4=(W - (shw if boundary == "구분" else 0)),
        v5=(shl if boundary == "구분" else 0),
        v6=(shw if boundary == "구분" else 0),
        show_split=(boundary == "구분")
    )
st.image(img, caption=f"{shape} (L={L}mm, W={W}mm)", use_container_width=False)
st.caption("※ 사각형: 길이 L=가로(밑변), 폭 W=세로 스케일 비례 렌더링 / 코너형: 우상단 오목부를 파내어 표기")

# =========================================
# GRP 기본/코너형 vs 일체형 선택 (필요할 때만)
# =========================================
if result is None and base_grp_result is not None:
    if integrated_grp_result is not None:
        st.subheader("GRP 단가 기준 선택")
        st.write(
            f"- GRP 기본/코너형 소계: {base_grp_result['소계']:,} 원\n"
            f"- GRP 일체형 소계: {integrated_grp_result['소계']:,} 원"
        )
        grp_price_mode = st.radio(
            "어떤 단가를 floor.json에 반영할까요?",
            ["GRP 기본/코너형 소계 사용", "GRP 일체형 소계 사용"],
            index=1,  # 기본값: 일체형 (예전 동작과 동일)
            horizontal=True,
        )
        if "일체형" in grp_price_mode:
            decision_log.append("사용자 선택: GRP 일체형 소계 사용")
            result = integrated_grp_result
            matched_user_type = "일체형"
            selected_alternative = True  # 대체 사용 여부 표시용
        else:
            decision_log.append("사용자 선택: GRP 기본/코너형 소계 사용")
            result = base_grp_result
            matched_user_type = "기본형"
    else:
        # 일체형 데이터가 없으면 기본/코너형만 사용
        result = base_grp_result
        matched_user_type = "기본형"

if result is None:
    st.error("단가 계산 결과를 결정하지 못했습니다. 입력값과 엑셀 데이터를 확인하세요.")
    st.stop()

# =========================================
# 출력 (매칭·단가 결과 + 로그 + JSON)
# =========================================
st.markdown("---")
st.subheader("매칭·단가 결과")

display_type = user_type
if selected_alternative is not None:
    display_type = f"{user_type} → {matched_user_type} (대체)"

# 결과를 딕셔너리 리스트로 구성
result_data = [
    {"항목": "세대수", "값": str(units)},
    {"항목": "유형/형태/용도", "값": f"{display_type} / {shape} / {usage}"},
    {"항목": "치수", "값": f"L={L:,} mm, W={W:,} mm"},
]

# 경계 구분 시 세면/샤워 치수 추가
if boundary == "구분" and (sw is not None and sl is not None and shw is not None and shl is not None):
    result_data.append({"항목": "세면부", "값": f"폭={sw:,} mm, 길이={sl:,} mm"})
    result_data.append({"항목": "샤워부", "값": f"폭={shw:,} mm, 길이={shl:,} mm"})

# 단가 정보
result_data.append({"항목": "소재(선택)", "값": result["소재"]})

# PVE 상세(선택) 표기
if result.get("소재") == "PVE":
    if result.get("PVE가공형태"):
        result_data.append({"항목": "PVE 가공형태", "값": str(result.get("PVE가공형태"))})
    if result.get("원재료비") is not None:
        result_data.append({"항목": "PVE 원재료비", "값": f"{int(result.get('원재료비')):,} 원"})
    if result.get("가공비") is not None:
        result_data.append({"항목": "PVE 가공비", "값": f"{int(result.get('가공비')):,} 원"})

if result["세면부단가"] is not None:
    result_data.append({"항목": "세면부바닥판 단가", "값": f"{result['세면부단가']:,} 원"})
if result["샤워부단가"] is not None:
    result_data.append({"항목": "샤워부바닥판 단가", "값": f"{result['샤워부단가']:,} 원"})

result_data.append({"항목": "소계", "값": f"{result['소계']:,} 원"})

# 표로 표시
result_df = pd.DataFrame(result_data)
st.dataframe(result_df, use_container_width=True, hide_index=True)

st.info("의사결정 로그", icon="ℹ️")
log_df = pd.DataFrame([{"단계": i+1, "결정": msg} for i, msg in enumerate(decision_log)])
st.dataframe(log_df, use_container_width=True, hide_index=True)

# =========================================
# 세션 상태 저장 및 공유 데이터 설정
# =========================================

# 욕실 정보를 다른 페이지에서 사용할 수 있도록 저장
st.session_state[SHARED_BATH_SHAPE_KEY] = shape
st.session_state[SHARED_BATH_WIDTH_KEY] = W
st.session_state[SHARED_BATH_LENGTH_KEY] = L
st.session_state[SHARED_SINK_WIDTH_KEY] = sw
st.session_state[SHARED_SINK_LENGTH_KEY] = sl
st.session_state[SHARED_SHOWER_WIDTH_KEY] = shw
st.session_state[SHARED_SHOWER_LENGTH_KEY] = shl
st.session_state[SHARED_MATERIAL_KEY] = result["소재"]

# 코너형인 경우 v3, v4, v5, v6 값도 저장
if shape == "코너형" and v3 is not None:
    st.session_state[SHARED_CORNER_V3_KEY] = v3
    st.session_state[SHARED_CORNER_V4_KEY] = v4
    st.session_state[SHARED_CORNER_V5_KEY] = v5
    st.session_state[SHARED_CORNER_V6_KEY] = v6
else:
    # 사각형인 경우 코너형 값 초기화
    st.session_state[SHARED_CORNER_V3_KEY] = None
    st.session_state[SHARED_CORNER_V4_KEY] = None
    st.session_state[SHARED_CORNER_V5_KEY] = None
    st.session_state[SHARED_CORNER_V6_KEY] = None

# ====== floor.json 저장 + 다운로드 버튼 ======
floor_payload = {
    "소재": result["소재"],
    "PVE가공형태": (str(result.get("PVE가공형태")) if result.get("소재") == "PVE" and result.get("PVE가공형태") else None),
    "원재료비": (int(result.get("원재료비")) if result.get("소재") == "PVE" and result.get("원재료비") is not None else None),
    "가공비": (int(result.get("가공비")) if result.get("소재") == "PVE" and result.get("가공비") is not None else None),
    "유형": display_type,
    "형태": shape,
    "욕실폭": int(W),
    "욕실길이": int(L),
    "세면부폭": int(sw) if sw is not None else None,
    "세면부길이": int(sl) if sl is not None else None,
    "샤워부폭": int(shw) if shw is not None else None,
    "샤워부길이": int(shl) if shl is not None else None,
    "세면부바닥판 단가": (int(result["세면부단가"]) if result.get("세면부단가") is not None else None),
    "샤워부바닥판 단가": (int(result["샤워부단가"]) if result.get("샤워부단가") is not None else None),
    "소계": int(result["소계"]),
}

# 세션 상태에 결과 저장
st.session_state[FLOOR_RESULT_KEY] = {
    "section": "floor",
    "inputs": {
        "units": units,
        "user_type": user_type,
        "shape": shape,
        "usage": usage,
        "is_access": is_access,
        "boundary": boundary,
        "W": W,
        "L": L,
        "sw": sw,
        "sl": sl,
        "shw": shw,
        "shl": shl,
    },
    "result": floor_payload,
    "decision_log": decision_log,
}
st.session_state[FLOOR_DONE_KEY] = True

# JSON 파일로 저장
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
json_filename = f"floor_{timestamp}.json"
json_path = os.path.join(EXPORT_DIR, json_filename)
_save_json(json_path, st.session_state[FLOOR_RESULT_KEY])

# 다운로드 버튼
st.markdown("---")
json_bytes = json.dumps(floor_payload, ensure_ascii=False, indent=2).encode("utf-8")
st.download_button(
    label="📥 floor.json 다운로드",
    data=json_bytes,
    file_name="floor.json",
    mime="application/json",
    type="primary",
)

# (선택) 화면에서 JSON 미리보기
with st.expander("📄 저장된 JSON 미리보기", expanded=False):
    st.json(floor_payload)

st.success("✅ 계산 완료")

# 다음 단계 안내
st.info("""
**다음 단계**: 벽판 계산을 진행하세요.

좌측 사이드바에서 **벽판 계산** 페이지로 이동하여 계산을 진행할 수 있습니다.
""")
