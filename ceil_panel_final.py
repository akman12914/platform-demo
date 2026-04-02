# -*- coding: utf-8 -*-
# 통합: 천장판 계산 UI + 엔진 + 엑셀 카탈로그 로딩 + m×n 확장설치 + 도면/행렬 스케치 + 표 + JSON
# 역이식: 다운로드 파일 형식 + 인증시스템 + session state + common_styles
# 실행: streamlit run ceil_panel_final.py

from __future__ import annotations

import io
import json
import math
import os
from dataclasses import dataclass
from typing import List, Tuple, Optional, Literal, Dict, Set
from collections import Counter, defaultdict
from datetime import datetime

import streamlit as st
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

# --- Common Styles ---
from common_styles import apply_common_styles, set_page_config
from common_sidebar import render_chatbot_sidebar

# --- Authentication ---
import auth

# =========================================
# 페이지 설정 및 인증
# =========================================
set_page_config(page_title="천장판 계산 프로그램 (통합)", layout="wide")
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

# 공유 카탈로그 세션 키 (모든 페이지에서 공통 사용)
SHARED_EXCEL_KEY = "shared_excel_file"
SHARED_EXCEL_NAME_KEY = "shared_excel_filename"

# 공유 욕실 정보 세션 키 (바닥판에서 입력, 벽판/천장판에서 사용)
SHARED_BATH_SHAPE_KEY = "shared_bath_shape"  # 욕실 형태: "사각형" or "코너형"
SHARED_BATH_WIDTH_KEY = "shared_bath_width"  # 욕실 폭 (W)
SHARED_BATH_LENGTH_KEY = "shared_bath_length"  # 욕실 길이 (L)
SHARED_SINK_WIDTH_KEY = "shared_sink_width"  # 세면부 폭 (경계선 정보, split용)
SHARED_MATERIAL_KEY = "shared_floor_material"  # 바닥판 재료

# 코너형 치수 공유 키 (v3, v4, v5, v6) - 바닥판에서 입력, 천장판/벽판에서 사용
SHARED_CORNER_V3_KEY = "shared_corner_v3"  # 세면부 길이
SHARED_CORNER_V4_KEY = "shared_corner_v4"  # 오목 세로
SHARED_CORNER_V5_KEY = "shared_corner_v5"  # 샤워부 길이
SHARED_CORNER_V6_KEY = "shared_corner_v6"  # 샤워부 폭

# =========================================
# 전역 상수
# =========================================
CUT_COST_BODY = 1500  # 바디 절단 비용 기본값 (천장판타공 시트에서 로드 시 덮어씀)
CUT_COST_SIDE = 1500  # 사이드 절단 비용 기본값
STEP_MM = 50
BODY_MAX_W = 1450  # BODY: 허용 최대 '길이'(L′)
SIDE_MAX_W = 1200  # SIDE: 허용 최대 '길이'(L′)

# =========================================
# 유틸
# =========================================
def iround(x: float) -> int:
    return int(math.floor(x + 0.5))


def step_floor(x: int, step: int = STEP_MM) -> int:
    return (int(x) // step) * step


def step_ceil(x: int, step: int = STEP_MM) -> int:
    v = int(x)
    return ((v + step - 1) // step) * step


def _save_json(path: str, data: dict):
    """JSON 파일 저장"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =========================================
# 치수 계산(전제: 가로=길이 L, 세로=폭 W)
# =========================================
def rect_zones_and_installed(W: int, L: int, split: int) -> Dict[str, Dict[str, int]]:
    """
    사각형: L=가로(길이축), W=세로(폭축), split=길이축 경계점(세면길이까지)
    세면부: 길이=split, 폭=W
    샤워부: 길이=L-split, 폭=W
    설치공간: 길이(+25), 폭(+50)
    """
    W = int(W)
    L = int(L)
    split = int(split)

    # 세면부: 길이=split, 폭=W
    sink_L, sink_W = split, W
    # 샤워부: 길이=L-split, 폭=W
    shower_L, shower_W = L - split, W

    return {
        "sink": {
            "L": sink_L,
            "W": sink_W,
            "L_inst": sink_L + 25,
            "W_inst": sink_W + 50,
        },
        "shower": {
            "L": shower_L,
            "W": shower_W,
            "L_inst": shower_L + 25,
            "W_inst": shower_W + 50,
        },
    }


def corner_zones_and_installed(v3: int, v4: int, v5: int, v6: int) -> Dict[str, Dict[str, int]]:
    """
    코너형: 1=길이=v3+v5, 2=폭=v4+v6
    세면부: 길이=v3, 폭=v4+v6 (v4는 오목부이지만 전체 폭에 포함)
    샤워부: 길이=v5, 폭=v6

    설치공간:
      - 세면부 길이(+50, 샤워부쪽으로 확장)
      - 세면부 폭(+50)
      - 샤워부 길이(+0)
      - 샤워부 폭(+50)
    """
    v3, v4, v5, v6 = map(int, (v3, v4, v5, v6))
    v1 = v3 + v5  # 길이
    v2 = v4 + v6  # 폭

    return {
        "sink": {"L": v3, "W": v4 + v6, "L_inst": v3 + 50, "W_inst": v4 + v6 + 50},
        "shower": {"L": v5, "W": v6, "L_inst": v5, "W_inst": v6 + 50},
        "v1": v1,
        "v2": v2,
        "v4_notch": v4,  # 오목부 크기
    }


# =========================================
# 카탈로그
# =========================================
@dataclass(frozen=True)
class Panel:
    name: str
    kind: Literal["BODY", "SIDE", "HATCH"]
    w: int   # 제품 '폭'(세로 방향)
    l: int   # 제품 '길이'(가로 방향)
    price: int


def _to_int(x):
    if isinstance(x, str):
        x = x.replace(",", "")
    return int(float(x))


@st.cache_data
def load_ceiling_panel_data(file_data: bytes) -> Tuple[List[Panel], List[Panel], List[Panel], int, int]:
    """
    천장판 엑셀 파일을 로드하고 카탈로그를 파싱합니다.
    Streamlit cache를 사용하여 반복 로딩을 방지합니다.

    Args:
        file_data: 업로드된 파일의 바이트 데이터

    Returns:
        (BODY 리스트, SIDE 리스트, HATCH 리스트, CUT_COST_BODY, CUT_COST_SIDE)
    """
    xls = pd.ExcelFile(file_data)

    # 천장판 시트 로딩
    if "천장판" not in xls.sheet_names:
        raise ValueError("'천장판' 시트를 찾을 수 없습니다.")

    df_cat = pd.read_excel(xls, sheet_name="천장판")
    body, side, hatch = load_catalog_from_excel(df_cat)

    # 절단 비용 로딩 (천장판타공 시트에서 바디/사이드 각각)
    cut_cost_body = CUT_COST_BODY  # 기본값
    cut_cost_side = CUT_COST_SIDE  # 기본값
    try:
        if "천장판타공" in xls.sheet_names:
            df_drill = pd.read_excel(xls, sheet_name="천장판타공")
            for _, row in df_drill.iterrows():
                name = str(row.get("품목", "")).strip()
                price = pd.to_numeric(row.get("단가", 0), errors="coerce") or 0
                if name == "바디":
                    cut_cost_body = int(price)
                elif name == "사이드":
                    cut_cost_side = int(price)
    except Exception:
        pass  # 실패 시 기본값 사용

    return body, side, hatch, cut_cost_body, cut_cost_side


def load_catalog_from_excel(df: pd.DataFrame) -> Tuple[List[Panel], List[Panel], List[Panel]]:
    req = {"판넬/점검구", "품명", "폭", "길이", "소계"}
    if not req.issubset(set(df.columns)):
        raise ValueError(f"시트 컬럼이 다릅니다. 필요: {req}, 현재: {set(df.columns)}")

    body: List[Panel] = []
    side: List[Panel] = []
    hatch: List[Panel] = []

    for _, r in df.iterrows():
        kind_raw = str(r["판넬/점검구"]).strip()
        name = str(r["품명"]).strip()
        w_raw = _to_int(r["폭"])
        l_raw = _to_int(r["길이"])
        price = _to_int(r["소계"])

        if "바디" in kind_raw:
            body.append(Panel(name or "NONAME", "BODY", w_raw, l_raw, price))

        elif "사이드" in kind_raw:
            nm = name if name.startswith("SIDE-") else f"SIDE-{name}"

            # -------- 안전한 스왑 규칙 시작 --------
            w, l = w_raw, l_raw
            if name.lower() == "900b":
                w, l = w_raw, l_raw
            elif name.isdigit():
                N = int(name)
                SMALL_LEN_SET = {700, 750, 800, 900, 1000, 1100, 1200}
                if N in SMALL_LEN_SET:
                    # 정상 패턴: l == N 이고 w는 큰 값(>=1500 정도)
                    if (l_raw == N) and (w_raw >= 1500):
                        w, l = w_raw, l_raw
                    # 뒤집힌 패턴: w == N 이고 l는 큰 값(>=1500)
                    elif (w_raw == N) and (l_raw >= 1500):
                        w, l = l_raw, w_raw
                    else:
                        w, l = w_raw, l_raw
                else:
                    w, l = w_raw, l_raw
            # -------- 안전한 스왑 규칙 끝 --------

            side.append(Panel(nm, "SIDE", w, l, price))

        else:
            hatch.append(Panel(name, "HATCH", w_raw, l_raw, price))

    return body, side, hatch


# =========================================
# 선택/비용 엔진 (전치 매핑 + 기존 행 단위 엔진용)
# =========================================
def pick_best_body_1x1(
    body_cat: List[Panel],
    L_inst: int,   # 설치길이 L′
    W_inst: int,   # 설치폭 W′
) -> Optional[Tuple[Panel, bool, int, int]]:
    """
    1×1 영역을 BODY 1판으로 덮는 특수 선택 함수.
    반환값: (선택된 패널, rotated, cuts, cost)
    """
    candidates = []

    for p in body_cat:
        # 정방향
        if p.l >= L_inst and p.w >= W_inst:
            cuts = (1 if p.l > L_inst else 0) + (1 if p.w > W_inst else 0)
            slack = (p.l - L_inst) + (p.w - W_inst)
            cost = p.price + cuts * CUT_COST
            candidates.append((p, False, cuts, cost, slack))

        # 회전
        if p.w >= L_inst and p.l >= W_inst:
            cuts = (1 if p.w > L_inst else 0) + (1 if p.l > W_inst else 0)
            slack = (p.w - L_inst) + (p.l - W_inst)
            cost = p.price + cuts * CUT_COST
            candidates.append((p, True, cuts, cost, slack))

    if not candidates:
        return None

    p_sel, rot, cuts_sel, cost_sel, slack_sel = min(
        candidates,
        key=lambda x: (x[2], x[3], x[4])
    )
    return p_sel, rot, cuts_sel, cost_sel


def max_length_capable(catalog: List[Panel], need_L: int) -> int:
    Ws = [p.w for p in catalog if p.l >= need_L]  # l >= need_L 인 패널의 폭 최대
    return max(Ws) if Ws else 0


def pick_best_panel(
    body_cat: List[Panel],
    side_cat: List[Panel],
    kind: Literal["BODY", "SIDE"],
    need_L: int,
    row_W: int,
    row_idx: int,
    notch: bool = False,
    cut_cost_body: int = CUT_COST_BODY,
    cut_cost_side: int = CUT_COST_SIDE,
) -> Optional[Tuple[Panel, bool, int, int]]:
    """
    kind ("BODY" or "SIDE") 카탈로그에서 need_L × row_W 이상을 만족하는 패널 중
    절단횟수 + 비용 + slack 기준으로 최적 선택.

    2D 규칙 기반 카탈로그 선택:
      · (need_L > SIDE_MAX_W) and (row_W > SIDE_MAX_W) 이면 BODY 사용
      · 그 외는 SIDE 사용 (SIDE는 회전 가능하므로 유연함)

    - BODY : 회전 사용하지 않음 (l → L축, w → W축 고정)
    - SIDE : 회전 허용 → 폭(w)이 길이(L′) 역할을 할 수 있도록 사용 가능
    """
    need_L = int(need_L)
    row_W = int(row_W)

    # ─────────────────────────────────────────
    # 2D 규칙 기반 실제 kind 결정
    # ─────────────────────────────────────────
    # 호출자가 BODY를 요청했더라도, 2D 조건을 만족하지 않으면 SIDE로 강등
    eff_kind: Literal["BODY", "SIDE"] = kind
    if kind == "BODY":
        # 둘 다 SIDE_MAX_W(1200)을 초과해야만 BODY 사용
        # 하나라도 1200 이하면 → SIDE로 변경
        if not (need_L > SIDE_MAX_W and row_W > SIDE_MAX_W):
            eff_kind = "SIDE"

    # 여기서부터는 eff_kind 기준으로 진행
    catalog = body_cat if eff_kind == "BODY" else side_cat
    best: Optional[Tuple[Panel, bool, int, int]] = None
    best_key: Optional[Tuple[int, int, int]] = None  # (cuts, cost, slack)

    # 바디/사이드에 따라 절단 비용 결정
    cut_cost = cut_cost_body if eff_kind == "BODY" else cut_cost_side

    for p in catalog:
        # -----------------------------
        # 1) 비회전 후보 (공통)
        #    L축 ← p.l, W축 ← p.w
        # -----------------------------
        if (p.l >= need_L) and (p.w >= row_W):
            cuts = (1 if p.l > need_L else 0) + (1 if p.w > row_W else 0)
            extra = (2 if notch else 0)
            total_cuts = cuts + extra
            cost = p.price + total_cuts * cut_cost
            slack = (p.l - need_L) + (p.w - row_W)
            key = (total_cuts, cost, slack)

            if (best_key is None) or (key < best_key):
                best = (p, False, total_cuts, cost)
                best_key = key

        # -----------------------------
        # 2) 회전 후보 (SIDE 전용)
        #    L축 ← p.w, W축 ← p.l
        #    → 폭이 길이 역할을 하도록 회전
        # -----------------------------
        if eff_kind == "SIDE" and (p.w >= need_L) and (p.l >= row_W):
            cuts = (1 if p.w > need_L else 0) + (1 if p.l > row_W else 0)
            extra = (2 if notch else 0)
            total_cuts = cuts + extra
            cost = p.price + total_cuts * cut_cost
            slack = (p.w - need_L) + (p.l - row_W)
            key = (total_cuts, cost, slack)

            # 같은 패널이라도, 회전했을 때 slack이 더 작으면 회전 쪽을 선택
            if (best_key is None) or (key < best_key):
                best = (p, True, total_cuts, cost)
                best_key = key

    return best


# =========================================
# 배치 단위(기존: 행 단위, 새: 셀 단위)
# =========================================
@dataclass
class RowPlacement:
    zone: str
    kind: Literal["BODY", "SIDE"]
    panel: Panel
    rotated: bool
    need_w: int  # 설치 L′
    need_l: int  # 설치 W′ (행 높이)
    cuts: int
    cost: int
    # 셀 단위 엔진용 추가 필드
    row: int = 0  # 1-based
    col: int = 0  # 1-based



# =========================================
# PlacementPack (공통)
# =========================================
@dataclass
class PlacementPack:
    rows: List[RowPlacement]
    total_cost: int
    row_lengths: List[int]
    pattern: List[Tuple[str, int, str]]  # (kind, Lpart, label)




# =========================================
# (새 엔진) 사각형용 셀 단위 BODY/SIDE 배치
# =========================================
def split_sink_length(sink_L: int) -> List[Tuple[str, int]]:
    """
    세면부 길이 방향 분할 (L′).
    결과: [("SIDE"/"BODY"/"RBP_BODY", L_part), ...] (왼→오)
    - 마지막 원소는 항상 "RBP_BODY" (샤워부와 맞닿는 세면부 마지막 열)
    - 남는 길이 ≤ SIDE_MAX_W(1200)이면 그 남은 조각은 항상 '가장자리'에 위치하도록 정렬
      (BODY-SIDE-BODY 같은 패턴이 나오지 않게 함)
    """
    sink_L = int(sink_L)
    cols: List[Tuple[str, int]] = []

    # 전체가 BODY 한 판이면 RBP_BODY 하나로 끝
    if sink_L <= BODY_MAX_W:
        cols.append(("RBP_BODY", sink_L))
        return cols

    # 오른쪽(샤워부 쪽)에는 항상 RBP BODY를 한 칸 둔다.
    rbp_L = BODY_MAX_W
    remain = sink_L - rbp_L  # RBP_BODY 왼쪽에 채워야 할 길이

    # RBP 왼쪽 구간을 "오른쪽에서 왼쪽"으로 채운 뒤, 나중에 뒤집어서 사용
    segments_rev: List[Tuple[str, int]] = []  # 오른쪽(=RBP 인접)에서 왼쪽으로 쌓는 리스트

    while remain > 0:
        if remain <= SIDE_MAX_W:
            # 남은 길이가 1200 이하 → 이 조각은 SIDE로, 가장자리 한쪽에만 위치
            segments_rev.append(("SIDE", remain))
            remain = 0
        elif remain <= BODY_MAX_W:
            # 남은 길이가 BODY_MAX_W 이하이면 BODY 한 판으로 처리
            segments_rev.append(("BODY", remain))
            remain = 0
        else:
            # 아직 길이가 크면 BODY_MAX_W만큼 BODY를 하나 더 붙이고 계속
            segments_rev.append(("BODY", BODY_MAX_W))
            remain -= BODY_MAX_W

    # segments_rev 는 "RBP 바로 옆 → 바깥쪽" 순서이므로, 이를 뒤집어서 왼→오 순서로 만든다.
    pre_cols = list(reversed(segments_rev))

    cols.extend(pre_cols)
    cols.append(("RBP_BODY", rbp_L))
    return cols


def split_shower_length(shower_L: int) -> List[int]:
    """
    샤워부 길이 방향 분할 (SIDE 전용).
    SIDE_MAX_W 이하로 잘라서 여러 열로 구성.
    """
    shower_L = int(shower_L)
    parts: List[int] = []
    remain = shower_L
    while remain > 0:
        use = min(SIDE_MAX_W, remain)
        parts.append(use)
        remain -= use
    return parts


def build_rect_columns(sink_L: int, shower_L: int):
    """
    사각형 욕실의 가로(L) 방향 열 정보 구성.
    반환:
      columns: [
        {"zone": "sink"/"shower", "kind_tag": "SIDE"/"BODY"/"RBP_BODY", "L": L_part},
        ...
      ]
      pattern: 스케치용 [(kind_for_view, L_part, label), ...]
      last_sink_col_idx: 세면부 마지막 열 인덱스(1-based) = RBP 열
    """
    columns: List[Dict] = []
    pattern: List[Tuple[str, int, str]] = []

    sink_cols = split_sink_length(sink_L)
    for i, (tag, Lp) in enumerate(sink_cols, start=1):
        Lp = int(Lp)
        columns.append({"zone": "sink", "kind_tag": tag, "L": Lp})
        view_kind = "BODY" if tag != "SIDE" else "SIDE"
        pattern.append((view_kind, Lp, f"세면-열{i}"))

    last_sink_col_idx = len(sink_cols)

    shower_parts = split_shower_length(shower_L)
    for j, Lp in enumerate(shower_parts, start=1):
        Lp = int(Lp)
        columns.append({"zone": "shower", "kind_tag": "SIDE", "L": Lp})
        pattern.append(("SIDE", Lp, f"샤워-열{j}"))

    return columns, pattern, last_sink_col_idx


def build_columns_with_length_side_aux(
    sink_L: int,
    shower_L: int,
) -> Tuple[List[Dict], List[Tuple[str, int, str]], int, bool]:
    """
    길이방향 사이드 보조 규칙을 우선 적용하여 열(column) 정보를 만든다.

    조건:
      1) 세면부 설치길이 sink_L > BODY_MAX_W (바디 한 판으로 안 끝날 때)
      2) 전체 설치길이 L_total = sink_L + shower_L <= BODY_MAX_W + SIDE_MAX_W (1450+1200=2650)
      3) R = L_total - BODY_MAX_W 가
         · 샤워부 설치길이 shower_L 이상
         · SIDE_MAX_W(=1200) 이하

    위 조건을 만족하면:
      - 열1: 세면부 BODY, 길이 = BODY_MAX_W
      - 열2: 샤워부 SIDE, 길이 = R (세면부 잔여 + 샤워부 전체를 한 번에 덮는 사이드 보조)

    반환:
      columns, pattern, last_sink_col_idx, used_aux
    """
    sink_L = int(sink_L)
    shower_L = int(shower_L)
    L_total = sink_L + shower_L

    # 사이드 보조 길이방향 조건
    if (sink_L > BODY_MAX_W) and (L_total <= BODY_MAX_W + SIDE_MAX_W):
        R = L_total - BODY_MAX_W
        if (shower_L <= R <= SIDE_MAX_W):
            columns: List[Dict] = []
            pattern: List[Tuple[str, int, str]] = []

            # 열 1: 세면부 BODY (RBP 역할)
            columns.append({"zone": "sink", "kind_tag": "BODY", "L": BODY_MAX_W})
            pattern.append(("BODY", BODY_MAX_W, "세면-열1(바디)"))

            # 열 2: 샤워부 SIDE (세면 잔여 + 샤워부 전체를 포함하는 사이드 보조)
            columns.append({"zone": "shower", "kind_tag": "SIDE", "L": R})
            pattern.append(("SIDE", R, "샤워-열1(사이드보조)"))

            last_sink_col_idx = 1  # 세면부 마지막 열(RBP)은 1번 열
            return columns, pattern, last_sink_col_idx, True

    # 조건을 만족하지 못하면 기존 규칙 사용
    columns, pattern, last_sink_col_idx = build_rect_columns(sink_L, shower_L)
    return columns, pattern, last_sink_col_idx, False


def max_panel_height(body_cat: List[Panel], side_cat: List[Panel]) -> int:
    """
    패널이 커버할 수 있는 폭(W′) 방향 최대값.
    BODY/SIDE의 (w, l) 중 큰 값들 중에서 최대를 사용.
    """
    vals = []
    for p in body_cat + side_cat:
        vals.append(int(p.w))
        vals.append(int(p.l))
    return max(vals) if vals else 2000


def max_panel_height_for_length(catalog: List[Panel], need_L: int) -> int:
    """
    특정 길이(need_L)를 커버할 수 있는 패널들에 대해,
    폭(W 방향)으로 사용할 수 있는 최대 높이를 계산한다.
    - 정방향: l >= need_L 인 패널들의 w
    - 회전:   w >= need_L 인 패널들의 l
    둘 중 가능한 것들을 모두 모아 최댓값을 반환.
    없으면 0.
    """
    need_L = int(need_L)
    heights: List[int] = []

    for p in catalog:
        # 정방향: L축으로 l 사용, W축으로 w 사용
        if p.l >= need_L:
            heights.append(int(p.w))
        # 회전:   L축으로 w 사용, W축으로 l 사용
        if p.w >= need_L:
            heights.append(int(p.l))

    return max(heights) if heights else 0


def split_rows_by_max_height(total_W: int, max_h: int) -> List[int]:
    """
    total_W를 '패널이 커버할 수 있는 최대 높이(max_h)'로 위에서부터 잘라 내려가고,
    마지막에 남은 만큼만 한 행으로 두는 함수.
    - 균등분할이 아니라, max_h, max_h, ..., remainder 형태
    - 수직 절단 횟수 최소화
    """
    total_W = int(total_W)
    if total_W <= 0:
        return []

    # 한 행으로 충분히 커버되면 그대로
    if total_W <= max_h:
        return [total_W]

    parts: List[int] = []
    remain = total_W

    # max_h 단위로 자르기
    while remain > max_h:
        parts.append(max_h)
        remain -= max_h

    # 마지막 잔여 폭
    if remain > 0:
        parts.append(remain)

    return parts


def split_bath_height(
    total_W: int,
    body_cat: List[Panel],
    side_cat: List[Panel],
    body_L_limit: Optional[int] = None,
    side_L_limit: Optional[int] = None,
) -> List[int]:
    """
    욕실 전체 폭(W′)을 패널이 커버할 수 있는 최대 높이 이하로 여러 행으로 분할.

    - 기본은 BODY+SIDE 전체에서 가능한 최대 높이(max_panel_height)를 사용.
    - body_L_limit 이 주어지면,
      · 해당 길이(예: RBP 세면 길이 L′)를 덮을 수 있는 BODY 패널의 최대 높이도 함께 고려하여
      · 전체 max_h를 더 작게(보수적으로) 제한한다.
      → RBP BODY가 들어가야 하는 행의 높이가 과도하게 커지지 않도록 안전하게 제한.
    - side_L_limit 이 주어지면,
      · 해당 길이(예: 샤워부 길이 L′)를 덮을 수 있는 SIDE 패널의 최대 높이도 함께 고려하여
      · 전체 max_h를 더 작게(보수적으로) 제한한다.
      → 샤워부 SIDE 패널이 과도한 높이의 행에 들어가지 않도록 안전하게 제한.

    행 분할 방식은:
      max_h, max_h, ..., remainder  형태로 위에서부터 잘라 내려가며
      수직 절단 횟수를 최소화한다.
    """
    total_W = int(total_W)
    if total_W <= 0:
        return []

    # 1) 전역 최대 높이 (BODY+SIDE 전체 기준)
    max_h = max_panel_height(body_cat, side_cat)

    # 2) RBP BODY 제약 반영 (필요한 경우)
    if body_L_limit is not None:
        body_L_limit = int(body_L_limit)
        body_max_h = max_panel_height_for_length(body_cat, body_L_limit)
        if body_max_h > 0:
            # BODY가 실제로 덮을 수 있는 높이보다 큰 행이 나오지 않도록 clamp
            max_h = min(max_h, body_max_h)
        # body_max_h == 0 인 경우:
        #  - 애초에 해당 길이를 BODY로 덮을 수 없는 카탈로그이므로
        #  - 여기서 강제로 에러를 내기보다, 이후 pick_best_panel 단계에서
        #    자연스럽게 "배치 실패"가 나도록 둔다.

    # 3) 샤워부 SIDE 제약 반영 (필요한 경우)
    if side_L_limit is not None:
        side_L_limit = int(side_L_limit)
        side_max_h = max_panel_height_for_length(side_cat, side_L_limit)
        if side_max_h > 0:
            # SIDE가 실제로 덮을 수 있는 높이보다 큰 행이 나오지 않도록 clamp
            max_h = min(max_h, side_max_h)
        # side_max_h == 0 인 경우:
        #  - 애초에 해당 길이를 SIDE로 덮을 수 없는 카탈로그이므로
        #  - 여기서 강제로 에러를 내기보다, 이후 pick_best_panel 단계에서
        #    자연스럽게 "배치 실패"가 나도록 둔다.

    return split_rows_by_max_height(total_W, max_h)


def decide_cell_kind_rect(
    zone: str,
    row_idx: int,
    col_idx: int,
    columns: List[Dict],
    last_sink_col_idx: int,
) -> Literal["BODY", "SIDE"]:
    """
    사각형 셀 단위 kind 결정:
    - 샤워부: 항상 SIDE
    - 세면부:
      - (row=1, col=last_sink_col_idx) = RBP 셀 → BODY
      - 그 외: 열 kind_tag가 SIDE면 SIDE, 아니면 BODY
    """
    col = columns[col_idx - 1]
    kind_tag = col["kind_tag"]

    if zone == "shower":
        return "SIDE"

    if row_idx == 1 and col_idx == last_sink_col_idx:
        return "BODY"

    if kind_tag == "SIDE":
        return "SIDE"
    else:
        return "BODY"


def solve_rect_cellwise(
    BODY: List[Panel],
    SIDE: List[Panel],
    sink_Wi: int,
    sink_Li: int,
    show_Wi: int,
    show_Li: int,
    cut_cost_body: int = CUT_COST_BODY,
    cut_cost_side: int = CUT_COST_SIDE,
) -> PlacementPack:
    """
    사각형 욕실용 셀 단위 엔진.

    규칙 요약:
    1) build_columns_with_length_side_aux()에서
       · 세면부+샤워부 전체 길이에 대해
       · 길이방향 사이드 보조(바디+사이드 2열 패턴)를 우선 시도
       → 가능하면 세면부 RBP BODY + 사이드 보조(SIDE) 2열로 고정
    2) 샤워부 zone은 항상 SIDE 사용
    3) 세면부는 열 kind_tag(SIDE/BODY)와 RBP 위치에 따라 BODY/SIDE 결정
       (폭방향 사이드 보조 규칙은 제거됨)
    """

    sink_Wi = int(sink_Wi)
    sink_Li = int(sink_Li)
    show_Wi = int(show_Wi)
    show_Li = int(show_Li)

    # 1) 가로 방향(길이 L′) 열 정보: 세면부+샤워부
    #    - 먼저 길이방향 사이드 보조 규칙을 적용해 보고,
    #      안 되면 기존 build_rect_columns 사용
    columns, pattern, last_sink_col_idx, used_side_aux = \
        build_columns_with_length_side_aux(sink_Li, show_Li)

    # 2) 세로 방향(폭 W′) 행 정보: 욕실 전체 폭을 분할
    if sink_Wi != show_Wi:
        W_total = max(sink_Wi, show_Wi)
    else:
        W_total = sink_Wi

    # RBP BODY 열의 길이 L′ (세면부 마지막 열)
    rbp_L = columns[last_sink_col_idx - 1]["L"]

    # 샤워부 열들의 길이들을 추출하여 SIDE 제약 계산
    shower_L_list = [int(c["L"]) for c in columns if c["zone"] == "shower"]
    side_L_limit = max(shower_L_list) if shower_L_list else None

    # RBP BODY가 실제로 덮을 수 있는 최대 높이 + SIDE가 덮을 수 있는 최대 높이를 고려해서 행 분할
    row_heights = split_bath_height(
        W_total,
        BODY,
        SIDE,
        body_L_limit=rbp_L,
        side_L_limit=side_L_limit,
    )
    n_rows = len(row_heights)

    rows: List[RowPlacement] = []
    total_cost = 0

    for r_idx, row_h in enumerate(row_heights, start=1):
        W_part = int(row_h)
        is_last_row = (r_idx == n_rows)

        for c_idx, col in enumerate(columns, start=1):
            zone = col["zone"]      # "sink" or "shower"
            L_part = int(col["L"])
            kind_tag = col["kind_tag"]  # "SIDE", "BODY", "RBP_BODY" 등

            # ───────────────────────────────────────
            # ① 셀 종류(kind) 결정
            # ───────────────────────────────────────
            if zone == "shower":
                # 샤워부는 어떤 경우에도 SIDE
                forced_kind: Literal["BODY", "SIDE"] = "SIDE"

            else:
                # zone == "sink" (세면부)
                if (r_idx == 1) and (c_idx == last_sink_col_idx):
                    # RBP: 1행, 세면부 마지막 열은 기본 BODY
                    forced_kind = "BODY"
                else:
                    # 그 외는 열의 kind_tag에 따라 기본 선택
                    forced_kind = "SIDE" if kind_tag == "SIDE" else "BODY"

            # ───────────────────────────────────────
            # ② 패널 선택
            # ───────────────────────────────────────
            pick = pick_best_panel(
                BODY,
                SIDE,
                forced_kind,
                need_L=L_part,
                row_W=W_part,
                row_idx=r_idx,
                notch=False,
                cut_cost_body=cut_cost_body,
                cut_cost_side=cut_cost_side,
            )
            if pick is None:
                # 이 셀을 만족하는 패널이 없으면 전체 배치 실패
                return PlacementPack([], 10**12, [], [])

            p, rotated, cuts, cost = pick
            total_cost += cost

            rows.append(
                RowPlacement(
                    zone=f"{zone}/행{r_idx}열{c_idx}",
                    kind=forced_kind,
                    panel=p,
                    rotated=rotated,
                    need_w=L_part,
                    need_l=W_part,
                    cuts=cuts,
                    cost=cost,
                    row=r_idx,
                    col=c_idx,
                )
            )

    return PlacementPack(
        rows=rows,
        total_cost=total_cost,
        row_lengths=row_heights,
        pattern=pattern,
    )


# =========================================
# (새 엔진) 코너형 높이 분할 함수
# =========================================
def split_corner_height(
    sink_Wi: int,
    show_Wi: int,
    notch_W: int,
    body_cat: List[Panel],
    side_cat: List[Panel],
    body_L_limit: Optional[int] = None,
    side_L_limit: Optional[int] = None,
) -> Tuple[List[int], int]:
    """
    코너형 욕실의 폭(W′)을 위쪽 오목부 영역 + 아래 실제 샤워 영역으로 분할.

    - 전체 설치 폭: sink_Wi
    - 샤워 설치 폭: show_Wi
    - 오목부 폭: notch_W (= sink_Wi - show_Wi 와 같아야 함)
    - body_L_limit 이 주어지면,
      · 해당 길이(예: RBP 세면 길이 L′)를 덮을 수 있는 BODY 패널의 최대 높이도 함께 고려하여
      · 전체 max_h를 더 작게(보수적으로) 제한한다.
    - side_L_limit 이 주어지면,
      · 해당 길이(예: 샤워부 길이 L′)를 덮을 수 있는 SIDE 패널의 최대 높이도 함께 고려하여
      · 전체 max_h를 더 작게(보수적으로) 제한한다.

    반환:
      row_heights: 각 행의 높이 리스트
      first_shower_row_idx: 샤워부가 실제 시작되는 첫 행 index (1-based)
    """
    sink_Wi = int(sink_Wi)
    show_Wi = int(show_Wi)
    notch_W = int(notch_W)

    # 안전 검사: 이론상 sink_Wi - show_Wi == notch_W 여야 함
    if sink_Wi - show_Wi != notch_W:
        notch_W = max(0, sink_Wi - show_Wi)

    # 1) 전역 최대 높이
    max_h = max_panel_height(body_cat, side_cat)

    # 2) RBP BODY 제약 반영 (필요한 경우)
    if body_L_limit is not None:
        body_L_limit = int(body_L_limit)
        body_max_h = max_panel_height_for_length(body_cat, body_L_limit)
        if body_max_h > 0:
            max_h = min(max_h, body_max_h)

    # 3) 샤워부 SIDE 제약 반영 (필요한 경우)
    if side_L_limit is not None:
        side_L_limit = int(side_L_limit)
        side_max_h = max_panel_height_for_length(side_cat, side_L_limit)
        if side_max_h > 0:
            max_h = min(max_h, side_max_h)

    # 4) 위쪽 오복부 영역 (샤워 X, 세면만 존재)
    rows_top: List[int] = []
    if notch_W > 0:
        rows_top = split_rows_by_max_height(notch_W, max_h)

    # 5) 아래쪽 공통 영역 (세면 + 샤워 모두 존재)
    common_W = sink_Wi - notch_W
    rows_bottom = split_rows_by_max_height(common_W, max_h)

    row_heights = rows_top + rows_bottom
    first_shower_row_idx = len(rows_top) + 1  # 이 행부터 샤워부 패널 설치

    return row_heights, first_shower_row_idx


# =========================================
# (새 엔진) 코너형 1행 전용 지오메트리
# =========================================
@dataclass
class CornerRowGeom:
    idx: int
    sink_W: int      # 세면부 이 행의 설치폭(W′)
    shower_W: int    # 샤워부 이 행의 설치폭(W′) (0이면 샤워 없음 = 오목부 행)
    is_notch_row: bool = False  # True이면 샤워 X, 세면만 존재(오목부)

def plan_corner_first_row(
    body_cat: List[Panel],
    side_cat: List[Panel],
    sink_Wi: int,       # 세면부 전체 설치폭 W′
    show_Wi: int,       # 샤워부 전체 설치폭 W′
    notch_W: int,       # 오목부 폭(세면부폭 - 샤워부폭)
    rbp_L: int,         # RBP BODY 열의 길이 L′
    shower_L_limit: Optional[int],  # 샤워부 열들 중 최대 L′
) -> Optional[int]:
    """
    코너형 '첫 샤워 행'에서 사용할 RBP BODY 폭 H_body 를 결정한다.

    조건:
      - notch_W < H_body <= sink_Wi
      - H_body 를 덮을 수 있는 BODY(길이 rbp_L 이상)가 존재
      - '샤워부 첫 행 폭' = H_body - notch_W 가
        해당 샤워 길이에서 SIDE가 커버 가능한 최대 폭 이하
    """
    sink_Wi = int(sink_Wi)
    show_Wi = int(show_Wi)
    notch_W = int(notch_W)

    # 이론상 show_Wi == sink_Wi - notch_W 여야 함 (corner_zones_and_installed 구조상)
    if sink_Wi - show_Wi != notch_W:
        # 약간 어긋나도 큰 문제는 아니지만, 일단 보정
        notch_W = max(0, sink_Wi - show_Wi)

    # RBP가 덮을 수 있는 최대 높이
    body_max_h = max_panel_height_for_length(body_cat, rbp_L)
    if body_max_h <= notch_W:
        return None  # BODY 자체가 오목부보다 큰 높이를 만들 수 없음

    # 샤워부 SIDE가 덮을 수 있는 최대 높이
    side_max_h = 0
    if shower_L_limit is not None:
        side_max_h = max_panel_height_for_length(side_cat, shower_L_limit)
    else:
        # 길이 제약 없이 전체 SIDE 기준
        side_max_h = max_panel_height_for_length(side_cat, 0)

    if side_max_h <= 0:
        return None  # 샤워부를 덮을 수 있는 SIDE가 없음

    # H_body는 다음을 만족해야 함:
    #   notch_W < H_body <= sink_Wi
    #   H_body <= body_max_h
    #   H_body - notch_W <= side_max_h  →  H_body <= notch_W + side_max_h
    upper = min(sink_Wi, body_max_h, notch_W + side_max_h)
    if upper <= notch_W:
        return None

    # 가장 큰 H_body를 선택해서 1행을 최대한 크게 사용 (행 수 최소화)
    H_body = upper
    return H_body


def plan_corner_rows(
    BODY: List[Panel],
    SIDE: List[Panel],
    sink_Wi: int,
    show_Wi: int,
    notch_W: int,
    rbp_L: int,
    shower_L_limit: Optional[int],
) -> Tuple[List[CornerRowGeom], bool]:
    """
    코너형 전체 행 지오메트리 생성.

    우선 ① 코너형 1행 전용 규칙(plan_corner_first_row)을 시도하고,
    실패하면 ② 기존 split_corner_height 기반 fallback 으로 분할한다.

    반환:
      - rows: CornerRowGeom 리스트 (위에서부터 1,2,... 순서)
      - used_special: True 이면 1행 특수 규칙 사용, False 이면 fallback
    """
    sink_Wi = int(sink_Wi)
    show_Wi = int(show_Wi)
    notch_W = int(notch_W)

    rows: List[CornerRowGeom] = []

    # ① 코너형 1행 특수 규칙 시도
    H_body = plan_corner_first_row(
        BODY, SIDE,
        sink_Wi, show_Wi, notch_W,
        rbp_L=rbp_L,
        shower_L_limit=shower_L_limit,
    )

    if H_body is not None and H_body < sink_Wi:
        # 1행: 세면부 H_body, 샤워부 H_body - notch_W
        shower_top = max(0, H_body - notch_W)
        rows.append(
            CornerRowGeom(
                idx=1,
                sink_W=H_body,
                shower_W=shower_top,
                is_notch_row=False,
            )
        )

        # 남은 부분은 세면/샤워 공통 영역 (행 여러 개로 나눌 수 있음)
        remain = sink_Wi - H_body  # = show_Wi - shower_top 이 성립
        if remain > 0:
            # 남은 영역은 세면/샤워 폭이 동일하므로 split_bath_height 사용
            bottom_parts = split_bath_height(
                remain,
                BODY,
                SIDE,
                body_L_limit=rbp_L,
                side_L_limit=shower_L_limit,
            )
            start_idx = len(rows) + 1
            for i, h in enumerate(bottom_parts):
                rows.append(
                    CornerRowGeom(
                        idx=start_idx + i,
                        sink_W=int(h),
                        shower_W=int(h),
                        is_notch_row=False,
                    )
                )
        return rows, True

    # ② 1행 특수 규칙이 불가능하면, 기존 split_corner_height 로 fallback
    row_heights, first_shower_row_idx = split_corner_height(
        sink_Wi, show_Wi, notch_W,
        BODY, SIDE,
        body_L_limit=rbp_L,
        side_L_limit=shower_L_limit,
    )

    rows = []
    for r_idx, h in enumerate(row_heights, start=1):
        h = int(h)
        if r_idx < first_shower_row_idx:
            # 오목부만 존재하는 윗부분: 세면부만 있고 샤워는 없음
            rows.append(
                CornerRowGeom(
                    idx=r_idx,
                    sink_W=h,
                    shower_W=0,
                    is_notch_row=True,
                )
            )
        else:
            # 세면/샤워 공통 영역
            rows.append(
                CornerRowGeom(
                    idx=r_idx,
                    sink_W=h,
                    shower_W=h,
                    is_notch_row=False,
                )
            )
    return rows, False


# =========================================
# (새 엔진) 코너형 셀 단위 배치 엔진
# =========================================
def find_best_corner_body_height(
    body_cat: List[Panel],
    sink_Li: int,   # 세면부 설치 길이 L′ (예: 1050)
    notch_W: int,
    sink_Wi: int,   # 세면부 설치 폭 W′ 전체 (예: 1550)
) -> Optional[Tuple[int, Panel]]:
    """
    코너형 1행용 바디 높이(H_body)를 선택.

    개념:
    - H_body는 "세면부 1행의 설치 폭"이다.
    - 조건:
      · 오목부(notch_W)보다 크고
      · 세면 전체 설치폭(sink_Wi) 이하
      · H_body를 덮을 수 있는 BODY 패널이 존재해야 한다
        (l ≥ sink_Li, w ≥ H_body)
    - 가능한 한 큰 H_body를 선택해서
      1행으로 끝낼 수 있으면 1행(행=1), 안 되면 2행 이상.
    """
    sink_Li = int(sink_Li)
    notch_W = int(notch_W)
    sink_Wi = int(sink_Wi)

    # 1) 이 길이(sink_Li)를 덮을 수 있는 BODY 중에서, 오목부보다 큰 폭을 가진 것만 후보
    eligible_widths: List[int] = []
    for p in body_cat:
        if p.l >= sink_Li and p.w > notch_W:
            eligible_widths.append(int(p.w))

    if not eligible_widths:
        # 아예 적당한 BODY가 없으면 코너 특수 1행 모드를 못 쓰고 fallback으로 간다.
        return None

    # 2) 쓸 수 있는 최대 높이 = 후보 폭의 최댓값
    max_w = max(eligible_widths)

    # 3) 행 높이 H_body는 "세면 설치폭(sink_Wi)와 max_w 중 작은 값"
    #    → 패널이 커버할 수 있는 최대 높이를 넘지 않으면서,
    #       가능한 한 크게 (행 수를 줄이도록) 잡는다.
    H_body = min(sink_Wi, max_w)

    # 안전 검사: 여전히 오목부보다 커야 함
    if H_body <= notch_W:
        return None

    # 4) 실제로 이 H_body를 덮을 수 있는 패널 하나 골라서 반환
    best_panel: Optional[Panel] = None
    for p in body_cat:
        if p.l >= sink_Li and p.w >= H_body:
            best_panel = p
            break

    if best_panel is None:
        # 이론상 거의 안 나와야 하지만, 안전하게 체크
        return None

    return H_body, best_panel



def solve_corner_cellwise(
    BODY: List[Panel],
    SIDE: List[Panel],
    sink_Wi: int,
    sink_Li: int,
    show_Wi: int,
    show_Li: int,
    notch_W: int,
    cut_cost_body: int = CUT_COST_BODY,
    cut_cost_side: int = CUT_COST_SIDE,
) -> PlacementPack:
    """
    코너형 욕실용 셀 단위 엔진.

    규칙 요약:
    1) build_columns_with_length_side_aux()에서
       · 세면부+샤워부 전체 길이에 대해
       · 길이방향 사이드 보조(바디+사이드 2열 패턴)를 우선 시도
    2) 샤워부는 항상 SIDE 사용
    3) 세면부 마지막 열(RBP)은 1행에서 BODY 강제
    4) plan_corner_rows()를 이용해
       - 코너형 1행의 세면/샤워 폭 차이(오복부) 반영,
       - 패널 최대 폭 제약을 만족하도록 행 분할.
    """

    sink_Wi = int(sink_Wi)
    sink_Li = int(sink_Li)
    show_Wi = int(show_Wi)
    show_Li = int(show_Li)
    notch_W = int(notch_W)

    # 🔹 코너형 길이방향 사이드 보조 조건
    # 욕실 설치길이 = 세면부 설치길이 + 샤워부 설치길이
    bath_install_L = sink_Li + show_Li
    side_aux_mode = (
        (bath_install_L <= BODY_MAX_W + SIDE_MAX_W)  # ≤ 1450 + 1200 = 2650
        and (sink_Li > BODY_MAX_W)                   # 세면부 설치길이 > BODY_MAX_W(1450)
    )

    # 1) 가로 방향 열 구성 (세면부 + 샤워부)
    #    - 길이방향 사이드 보조 규칙을 우선 적용
    columns, pattern, last_sink_col_idx, used_side_aux = \
        build_columns_with_length_side_aux(sink_Li, show_Li)

    # RBP 열 길이와 샤워 열 길이들
    rbp_L = int(columns[last_sink_col_idx - 1]["L"])
    shower_L_list = [int(c["L"]) for c in columns if c["zone"] == "shower"]
    side_L_limit = max(shower_L_list) if shower_L_list else None

    # ─────────────────────────────────────────────
    # 1-1) 먼저 "한 행으로 전체를 덮을 수 있는지" 검사
    #      - 세면 전체 폭 sink_Wi 를 덮을 수 있는 BODY가 있고
    #      - 샤워 전체 폭 show_Wi 를 덮을 수 있는 SIDE가 있으면
    #        → 1행×2열로 처리 (오복부를 별도 행으로 쪼개지 않음)
    # ─────────────────────────────────────────────
    body_max_full = max_panel_height_for_length(BODY, rbp_L)
    side_max_full = max_panel_height_for_length(SIDE, side_L_limit or 0)

    if (body_max_full >= sink_Wi) and (side_max_full >= show_Wi):
        # 한 행만 사용하는 코너형 배치
        row_geoms = [
            CornerRowGeom(
                idx=1,
                sink_W=int(sink_Wi),
                shower_W=int(show_Wi),
                is_notch_row=False,
            )
        ]
        used_special = True
    else:
        # 2) 위 조건에서 안 되면 기존 plan_corner_rows 로 분할
        row_geoms, used_special = plan_corner_rows(
            BODY,
            SIDE,
            sink_Wi,
            show_Wi,
            notch_W,
            rbp_L=rbp_L,
            shower_L_limit=side_L_limit,
        )

    if not row_geoms:
        return PlacementPack([], 10**12, [], [])

    rows: List[RowPlacement] = []
    total_cost = 0
    n_rows = len(row_geoms)  # 전체 행 수

    for row_pos, geom in enumerate(row_geoms, start=1):
        r_idx = geom.idx
        sink_row_W = int(geom.sink_W)
        shower_row_W = int(geom.shower_W)
        is_last_row = (row_pos == n_rows)  # 마지막 행 여부

        for c_idx, col in enumerate(columns, start=1):
            zone = col["zone"]      # "sink" or "shower"
            L_part = int(col["L"])
            kind_tag = col["kind_tag"]  # "SIDE", "BODY", "RBP_BODY" 등

            # ─────────────────────────────
            # ① 이 셀에서 필요한 폭(row_W) 결정
            # ─────────────────────────────
            if zone == "sink":
                row_W = sink_row_W
            else:  # zone == "shower"
                # 샤워부가 없는 행(오복부 행)이면 패널 배치하지 않음
                if shower_row_W <= 0:
                    continue
                row_W = shower_row_W

            # ─────────────────────────────
            # ② kind 결정
            # ─────────────────────────────
            if zone == "shower":
                # 샤워는 항상 SIDE
                forced_kind: Literal["BODY", "SIDE"] = "SIDE"
            else:
                # 세면부
                if (r_idx == 1) and (c_idx == last_sink_col_idx):
                    # 1행 + 세면부 마지막 열(RBP)은 BODY 강제
                    forced_kind = "BODY"
                elif kind_tag == "SIDE":
                    forced_kind = "SIDE"
                else:
                    forced_kind = "BODY"

            # ─────────────────────────────
            # ③ 패널 선택
            # ─────────────────────────────
            # 🔹 (1,2) 위치의 SIDE 패널에만 notch=True 적용
            #    (코너형 + 길이방향 사이드 보조 모드 + 샤워부 + SIDE)
            use_notch = (
                side_aux_mode
                and r_idx == 1
                and zone == "shower"
                and forced_kind == "SIDE"
                and c_idx == 2
            )

            pick = pick_best_panel(
                BODY,
                SIDE,
                forced_kind,
                need_L=L_part,
                row_W=row_W,
                row_idx=r_idx,
                notch=use_notch,
                cut_cost_body=cut_cost_body,
                cut_cost_side=cut_cost_side,
            )
            if pick is None:
                # 이 셀을 만족하는 패널이 없으면 전체 배치 실패
                return PlacementPack([], 10**12, [], [])

            p, rotated, cuts, cost = pick
            total_cost += cost

            rows.append(
                RowPlacement(
                    zone=f"{zone}/행{r_idx}열{c_idx}",
                    kind=forced_kind,
                    panel=p,
                    rotated=rotated,
                    need_w=L_part,
                    need_l=row_W,
                    cuts=cuts,
                    cost=cost,
                    row=r_idx,
                    col=c_idx,
                )
            )

    # pack.row_lengths 는 "세면부 기준 각 행 폭"을 사용
    row_lengths = [int(g.sink_W) for g in row_geoms]

    return PlacementPack(
        rows=rows,
        total_cost=total_cost,
        row_lengths=row_lengths,
        pattern=pattern,
    )


# =========================================
# 스케치
# =========================================
def draw_rect_plan(
    W: int,
    L: int,
    split: Optional[int] = None,
    canvas_w: int = 760,
    canvas_h: int = 540,
    margin: int = 20,
) -> Image.Image:
    CANVAS_W, CANVAS_H, MARGIN = int(canvas_w), int(canvas_h), int(margin)
    sx = (CANVAS_W - 2 * MARGIN) / max(1.0, float(L))
    sy = (CANVAS_H - 2 * MARGIN) / max(1.0, float(W))
    s = min(sx, sy)

    img = Image.new("RGB", (CANVAS_W, CANVAS_H), "white")
    drw = ImageDraw.Draw(img)
    x0, y0 = MARGIN, MARGIN
    x1 = x0 + int(L * s)
    y1 = y0 + int(W * s)

    dx = (CANVAS_W - 2 * MARGIN - int(L * s)) // 2
    dy = (CANVAS_H - 2 * MARGIN - int(W * s)) // 2
    x0 += dx
    x1 += dx
    y0 += dy
    y1 += dy

    drw.rectangle([x0, y0, x1, y1], outline="black", width=3)

    if split is not None:
        gx = x0 + int(split * s)
        drw.line([gx, y0, gx, y1], fill="blue", width=3)

    return img


def draw_corner_plan(
    v1: int,
    v2: int,
    v3: int,
    v4: int,
    v5: int,
    v6: int,
    canvas_w: int = 760,
    canvas_h: int = 540,
    margin: int = 20,
) -> Image.Image:
    """
    코너형: 세면부(검은색)와 샤워부(파란색) 두 사각형을 가로로 나란히 배치
    """
    CANVAS_W, CANVAS_H, MARGIN = int(canvas_w), int(canvas_h), int(margin)
    sx = (CANVAS_W - 2 * MARGIN) / max(1.0, float(v1))
    sy = (CANVAS_H - 2 * MARGIN) / max(1.0, float(v2))
    s = min(sx, sy)

    img = Image.new("RGB", (CANVAS_W, CANVAS_H), "white")
    drw = ImageDraw.Draw(img)

    dx = (CANVAS_W - 2 * MARGIN - int(v1 * s)) // 2
    dy = (CANVAS_H - 2 * MARGIN - int(v2 * s)) // 2
    x0, y0 = MARGIN + dx, MARGIN + dy

    def X(mm): return int(round(x0 + mm * s))
    def Y(mm): return int(round(y0 + mm * s))

    drw.rectangle([X(0), Y(0), X(v3), Y(v2)], outline="black", width=3)

    shower_x0 = v3
    shower_x1 = v3 + v5
    shower_y0 = v2 - v6
    shower_y1 = v2
    drw.rectangle([X(shower_x0), Y(shower_y0), X(shower_x1), Y(shower_y1)], outline="blue", width=3)

    return img


def draw_dashed_line(draw, xy_start, xy_end, dash_length=8, gap_length=5, width=2, fill="black"):
    """PIL에는 dash 옵션이 없어서, 짧은 선분들을 이어서 점선을 구현."""
    x0, y0 = xy_start
    x1, y1 = xy_end
    x0, y0, x1, y1 = float(x0), float(y0), float(x1), float(y1)

    dx = x1 - x0
    dy = y1 - y0
    dist = math.hypot(dx, dy)
    if dist == 0:
        return

    ux = dx / dist
    uy = dy / dist

    pos = 0.0
    while pos < dist:
        start_x = x0 + ux * pos
        start_y = y0 + uy * pos
        end_pos = min(pos + dash_length, dist)
        end_x = x0 + ux * end_pos
        end_y = y0 + uy * end_pos
        draw.line([(start_x, start_y), (end_x, end_y)], fill=fill, width=width)
        pos += dash_length + gap_length


def draw_matrix_sketch(
    col_lengths_mm: List[int],
    row_widths_mm: List[int],
    cell_labels: Optional[Dict[Tuple[int, int], str]] = None,
    canvas_w: int = 760,
    canvas_h: int = 540,
    margin_px: int = 20,
    origin: Literal["top", "bottom"] = "top",
    sink_cols: Optional[List[int]] = None,
    merge_sink_rows: bool = False,
    notch_L_mm: Optional[int] = None,   # 추가: 오복부 좌측 경계 (v3)
    notch_W_mm: Optional[int] = None,   # 추가: 오복부 하단 경계 (v4)
) -> Image.Image:
    """
    행렬 스케치를 그린다.
    sink_cols: 세면부 열 index (1-based column indices)
    merge_sink_rows: True이면 세면부 열의 위/아래 행을 하나로 병합하여 표현
    """
    Lmm = int(sum(col_lengths_mm))
    Wmm = int(sum(row_widths_mm))

    avail_w = max(1, int(canvas_w) - 2 * int(margin_px))
    avail_h = max(1, int(canvas_h) - 2 * int(margin_px))
    sx = avail_w / max(1.0, float(Lmm))
    sy = avail_h / max(1.0, float(Wmm))
    s = min(sx, sy)

    draw_w = int(round(Lmm * s))
    draw_h = int(round(Wmm * s))

    img_w = max(canvas_w, draw_w + 2 * margin_px)
    img_h = max(canvas_h, draw_h + 2 * margin_px)

    img = Image.new("RGB", (img_w, img_h), "white")
    draw = ImageDraw.Draw(img)

    x0 = (img_w - draw_w) // 2
    y0 = (img_h - draw_h) // 2
    x1 = x0 + draw_w
    y1 = y0 + draw_h

    # 바깥 테두리
    draw.rectangle([x0, y0, x1, y1], outline="black", width=3)

    cum_L = [0]
    for v in col_lengths_mm:
        cum_L.append(cum_L[-1] + int(v))
    cum_W = [0]
    for v in row_widths_mm:
        cum_W.append(cum_W[-1] + int(v))

    light_gray = "#DDDDDD"

    # ---- 셀 단위 그리기 ----
    for r in range(len(row_widths_mm)):
        for c in range(len(col_lengths_mm)):
            cx0 = x0 + int(round(cum_L[c] * s))
            cx1 = x0 + int(round(cum_L[c + 1] * s))
            if origin == "top":
                cy0 = y0 + int(round(cum_W[r] * s))
                cy1 = y0 + int(round(cum_W[r + 1] * s))
            else:
                cy1 = y1 - int(round(cum_W[r] * s))
                cy0 = y1 - int(round(cum_W[r + 1] * s))

            label = cell_labels.get((r + 1, c + 1), "") if cell_labels else ""
            is_sink_col = (sink_cols is not None) and ((c + 1) in sink_cols)

            # 세면부: 옅은 회색으로 채우고 격자선 유지
            # X 셀도 일반 셀처럼 처리 (검정색 제거)
            if is_sink_col:
                draw.rectangle(
                    [cx0, cy0, cx1, cy1],
                    fill=light_gray,
                    outline="#666666",
                    width=2,
                )
            else:
                draw.rectangle(
                    [cx0, cy0, cx1, cy1],
                    outline="#666666",
                    width=2,
                )

            # 텍스트 라벨(있을 경우, X는 표시하지 않음)
            if label and label != "X":
                tx = (cx0 + cx1) // 2
                ty = (cy0 + cy1) // 2
                try:
                    draw.text((tx, ty), label, fill="black", anchor="mm")
                except TypeError:
                    draw.text((tx - 20, ty - 8), label, fill="black")

    # ==== 🔹 오복부 경계 점선 표시 (코너형 전용) ====
    if notch_L_mm is not None and notch_W_mm is not None:
        # mm → pixel 변환
        x_notch = x0 + int(round(notch_L_mm * s))   # 세로 점선 (좌측 경계, v3)
        y_notch = y0 + int(round(notch_W_mm * s))   # 가로 점선 (하단 경계, v4)

        # 1) 오복부 좌측 경계: 위쪽 테두리에서 오복부 하단까지
        draw_dashed_line(
            draw,
            (x_notch, y0),
            (x_notch, y_notch),
            dash_length=10,
            gap_length=6,
            width=2,
            fill="black",
        )

        # 2) 오복부 하단 경계:
        #    (v3, v4) → 전체 오른쪽 끝까지 (샤워 영역 아래쪽)
        draw_dashed_line(
            draw,
            (x_notch, y_notch),
            (x1, y_notch),
            dash_length=10,
            gap_length=6,
            width=2,
            fill="black",
        )

    return img


# =========================================
# 요약/테이블
# =========================================
@dataclass
class PatternCost:
    pattern: List[Tuple[str, int, str]]
    rows: List[RowPlacement]
    total_cost: int
    fail_reason: Optional[str] = None
    row_lengths: Optional[List[int]] = None


def summarize_rows(rows: List[RowPlacement]) -> Tuple[pd.DataFrame, pd.DataFrame, Dict]:
    total_panels = len(rows)
    total_cuts = sum(r.cuts for r in rows)
    total_cost = sum(r.cost for r in rows)
    body_cnt = sum(1 for r in rows if r.kind == "BODY")
    side_cnt = total_panels - body_cnt

    mix_counter = Counter(
        f"{r.panel.name}{'(rot)' if r.rotated else ''} {r.panel.w}x{r.panel.l}"
        for r in rows
    )
    kind_size_counter: Dict[str, int] = defaultdict(int)
    for r in rows:
        k = f"{r.kind}:{r.panel.w}x{r.panel.l}"
        kind_size_counter[k] += 1

    df_elements = pd.DataFrame([
        {
            "행": (r.row if getattr(r, "row", 0) else idx + 1),
            "열": (r.col if getattr(r, "col", 0) else None),
            "zone": r.zone,
            "kind": r.kind,
            "품명": r.panel.name + ("(rot)" if r.rotated else ""),
            "설치길이(L)": r.need_w,
            "설치폭(W)": r.need_l,
            "패널길이(l)": r.panel.l,
            "패널폭(w)": r.panel.w,
            "절단횟수": r.cuts,
            "판넬소계": r.panel.price,
            "절단포함": r.cost,
        }
        for idx, r in enumerate(rows)
    ])

    df_summary = pd.DataFrame([{
        "배치행렬(총개수)": total_panels,
        "바디개수": body_cnt,
        "사이드개수": side_cnt,
        "크기별개수": dict(mix_counter),
        "총절단수": total_cuts,
        "총단가합계": total_cost,
    }])

    json_parts = {
        "총개수": int(total_panels),
        "총절단": int(total_cuts),
        "총단가": int(total_cost),
        "kind_size_counts": dict(kind_size_counter),
    }
    return df_summary, df_elements, json_parts


# =========================================
# UI 시작
# =========================================
st.title("천장판 계산 프로그램 (UI + 엔진 통합)")

# ========== 바닥판 계산 의존성 체크 ==========
floor_done = st.session_state.get(FLOOR_DONE_KEY, False)
floor_result = st.session_state.get(FLOOR_RESULT_KEY)

if not floor_done or not floor_result:
    st.warning("⚠️ 천장판 계산을 진행하려면 먼저 **바닥판 계산**을 완료해야 합니다.")

    # 안내 카드
    st.markdown(
        """
    <div style="
        border: 1px solid #f59e0b;
        border-radius: 12px;
        padding: 20px;
        margin: 16px 0;
        background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    ">
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 12px;">
            <span style="font-size: 24px;">📋</span>
            <h3 style="margin: 0; color: #0f172a; font-weight: 700;">연속 계산 순서</h3>
        </div>
        <p style="margin: 0 0 12px 36px; color: #78350f; line-height: 1.6;">
            시스템은 순차적인 계산 흐름을 따릅니다:
        </p>
        <div style="margin-left: 36px; padding: 12px; background: white; border-radius: 8px; border: 1px solid #f59e0b;">
            <p style="margin: 0; color: #92400e; font-size: 0.95rem; line-height: 1.6;">
                <strong>1단계:</strong> 🟦 바닥판 계산<br>
                <strong>2단계:</strong> 🟩 벽판 계산<br>
                <strong>3단계:</strong> 🟨 천장판 계산 ← <em>현재 페이지</em><br>
                <strong>4단계:</strong> 📋 견적서 생성
            </p>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    # 바닥판 계산 페이지로 이동 버튼
    col_spacer, col_btn, col_spacer2 = st.columns([1, 2, 1])
    with col_btn:
        st.page_link(
            "pages/1_바닥판_계산.py", label="🟦 바닥판 계산 시작하기", icon=None
        )

    st.stop()  # 바닥판 미완료 시 이후 UI 차단

# 바닥판 완료 시 성공 메시지
st.success("✅ 바닥판 계산이 완료되었습니다. 천장판 계산을 진행할 수 있습니다.")

# -------- 카탈로그 업로드 --------
with st.sidebar:
    st.header("천장판 데이터 로딩")
    st.info("📂 바닥판에서 업로드한 Excel 카탈로그를 사용합니다.")

    # 바닥판에서 공유된 데이터 표시
    shared_shape = st.session_state.get(SHARED_BATH_SHAPE_KEY)
    shared_width = st.session_state.get(SHARED_BATH_WIDTH_KEY)
    shared_length = st.session_state.get(SHARED_BATH_LENGTH_KEY)
    shared_sink_w = st.session_state.get(SHARED_SINK_WIDTH_KEY)

    if shared_shape:
        st.success(f"✅ 바닥판 데이터 사용 중\n- 형태: {shared_shape}\n- 폭×길이: {shared_width}×{shared_length}mm\n- 세면부 폭: {shared_sink_w}mm")

    st.header("욕실유형")
    # 바닥판 데이터가 있으면 자동 설정, 없으면 수동 선택
    if shared_shape:
        bath_type_map = {"사각형": "사각형 욕실", "코너형": "코너형 욕실"}
        bath_type = bath_type_map.get(shared_shape, "사각형 욕실")
        st.radio("욕실유형 (바닥판 자동 반영)", [bath_type], horizontal=False, disabled=True)
    else:
        bath_type = st.radio("욕실유형", ["사각형 욕실", "코너형 욕실"], horizontal=False)


# -------- read Excel file (shared state only) ----------
# 바닥판에서 공유된 Excel 파일 사용
excel_file = st.session_state.get(SHARED_EXCEL_KEY)
excel_filename = st.session_state.get(SHARED_EXCEL_NAME_KEY, "알 수 없음")

if excel_file:
    try:
        # 캐시된 함수로 데이터 로드
        excel_file.seek(0)  # 파일 포인터를 처음으로 리셋
        file_bytes = excel_file.read()
        BODY, SIDE, HATCH, CUT_COST_BODY_LOADED, CUT_COST_SIDE_LOADED = load_ceiling_panel_data(file_bytes)

        # 공유 카탈로그 표시
        st.info(f"📂 공유 카탈로그 사용 중: {excel_filename} — BODY {len(BODY)}종, SIDE {len(SIDE)}종, 점검구 {len(HATCH)}종")

        # 절단비가 기본값이 아니면 표시
        if CUT_COST_BODY_LOADED != CUT_COST_BODY or CUT_COST_SIDE_LOADED != CUT_COST_SIDE:
            st.info(f"천장판타공 시트에서 절단비 로드됨 — 바디: {CUT_COST_BODY_LOADED:,}원, 사이드: {CUT_COST_SIDE_LOADED:,}원")

    except Exception as e:
        st.error(f"엑셀 파싱 실패: {e}")
        st.stop()
else:
    st.warning("⚠️ 바닥판 페이지에서 엑셀 파일을 먼저 업로드해주세요.")
    st.info("💡 바닥판에서 업로드한 Excel 카탈로그가 천장판과 벽판에 자동으로 공유됩니다.")
    st.stop()

# 카탈로그 확인 UI (Expander)
with st.expander("📋 카탈로그 확인 (업로드 데이터)", expanded=False):
    st.markdown("### 점검구 카탈로그")
    df_check_display = pd.DataFrame(
        [{"이름": h.name, "폭": h.w, "길이": h.l, "가격": h.price} for h in HATCH]
    )
    st.dataframe(df_check_display, use_container_width=True)
    st.caption(f"총 {len(HATCH)}개 항목")

    st.markdown("### 바디판넬 카탈로그")
    df_body_display = pd.DataFrame(
        [{"이름": b.name, "폭": b.w, "길이": b.l, "가격": b.price} for b in BODY]
    )
    st.dataframe(df_body_display, use_container_width=True)
    st.caption(f"총 {len(BODY)}개 항목")

    st.markdown("### 사이드판넬 카탈로그")
    df_side_display = pd.DataFrame(
        [{"이름": s.name, "폭": s.w, "길이": s.l, "가격": s.price} for s in SIDE]
    )
    st.dataframe(df_side_display, use_container_width=True)
    st.caption(f"총 {len(SIDE)}개 항목")

    # 통계 요약
    st.markdown("---")
    st.markdown("#### 📊 카탈로그 통계")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("점검구", f"{len(HATCH)}종")
    with col2:
        st.metric("바디판넬", f"{len(BODY)}종")
    with col3:
        st.metric("사이드판넬", f"{len(SIDE)}종")

# -------- 입력 ----------

calc_btn = None
if bath_type == "사각형 욕실":
    c1, c2, c3 = st.columns(3)
    with c1:
        # 공유 데이터가 있으면 자동 설정, 없으면 기본값
        default_w = shared_width if shared_width else 1600
        W = st.number_input("욕실폭 W (세로, mm)", min_value=500, value=default_w, step=50,
                           disabled=bool(shared_width),
                           help="바닥판에서 자동 반영" if shared_width else None)
    with c2:
        default_l = shared_length if shared_length else 2000
        L = st.number_input("욕실길이 L (가로, mm)", min_value=500, value=default_l, step=50,
                           disabled=bool(shared_length),
                           help="바닥판에서 자동 반영" if shared_length else None)
    with c3:
        # 공유 경계선 정보가 있으면 자동으로 "있음" 선택
        if shared_sink_w:
            split_on = "있음"
            st.radio("세면/샤워 경계선 (바닥판 자동 반영)", [split_on], horizontal=True, disabled=True)
        else:
            split_on = st.radio("세면/샤워 경계선", ["없음", "있음"], horizontal=True)

    split = None
    if split_on == "있음":
        # 공유 세면부 폭이 있으면 자동 설정
        if shared_sink_w:
            split = shared_sink_w
            st.slider(
                "경계선 X (mm, 가로 기준) - 바닥판 자동 반영",
                min_value=100,
                max_value=int(L),
                step=50,
                value=split,
                disabled=True
            )
        else:
            split = st.slider(
                "경계선 X (mm, 가로 기준)",
                min_value=100,
                max_value=int(L),
                step=50,
                value=min(1100, int(L)),
            )

    # 평면도
    st.subheader("도면 미리보기 — 사각")
    st.image(draw_rect_plan(W, L, split), use_container_width=False)

    calc_btn = st.button("계산 실행", type="primary")

else:
    # 코너형: 바닥판에서 저장된 치수를 고정으로 사용
    shared_v3 = st.session_state.get(SHARED_CORNER_V3_KEY)
    shared_v4 = st.session_state.get(SHARED_CORNER_V4_KEY)
    shared_v5 = st.session_state.get(SHARED_CORNER_V5_KEY)
    shared_v6 = st.session_state.get(SHARED_CORNER_V6_KEY)

    # 바닥판에서 코너형 치수를 입력하지 않은 경우 안내
    if shared_v3 is None or shared_v4 is None or shared_v5 is None or shared_v6 is None:
        st.error("❌ 바닥판에서 코너형 치수(v3, v4, v5, v6)를 먼저 입력해주세요.")
        st.info("바닥판 계산 페이지에서 '코너형' 형태를 선택하고 계산을 실행하면 치수가 자동으로 공유됩니다.")
        st.stop()

    # 바닥판에서 가져온 값을 고정으로 사용
    v3 = int(shared_v3)
    v4 = int(shared_v4)
    v5 = int(shared_v5)
    v6 = int(shared_v6)

    st.info(f"ℹ️ 바닥판에서 가져온 코너형 치수 (고정값)")

    body_max_width = max((p.w for p in BODY), default=2000)

    colA, colB = st.columns(2)
    with colA:
        st.text_input("3번 (세면 길이, mm)", value=str(v3), disabled=True)
        st.text_input("5번 (샤워 길이, mm)", value=str(v5), disabled=True)
    with colB:
        st.text_input("4번 (오목 폭, mm)", value=str(v4), disabled=True)
        st.text_input("6번 (샤워 폭, mm)", value=str(v6), disabled=True)

    v1, v2 = v3 + v5, v4 + v6
    st.text_input("1번=L=3+5", value=str(v1), disabled=True)
    st.text_input("2번=W=4+6", value=str(v2), disabled=True)

    if v4 >= body_max_width:
        st.error(f"❌ 오목부 폭(v4={v4}mm)은 BODY 패널의 최대 폭({body_max_width}mm)보다 작아야 합니다.")
        st.stop()

    st.subheader("도면 미리보기 — 코너")
    st.image(draw_corner_plan(v1, v2, v3, v4, v5, v6), use_container_width=False)

    st.caption("세로 적층: 아래 방향, 1행 회전 금지, 2행부터 SIDE-900b 회전 절감 조건 적용")

    calc_btn = st.button("계산 실행", type="primary")

# ----- 계산 -----
if not calc_btn:
    st.stop()

try:
    if bath_type == "사각형 욕실":
        z = rect_zones_and_installed(int(W), int(L), int(split))
        sW, sL = z["sink"]["W_inst"], z["sink"]["L_inst"]
        hW, hL = z["shower"]["W_inst"], z["shower"]["L_inst"]

        # ✅ 사각형은 셀 단위 엔진 사용
        pack = solve_rect_cellwise(BODY, SIDE, sW, sL, hW, hL,
                                   cut_cost_body=CUT_COST_BODY_LOADED,
                                   cut_cost_side=CUT_COST_SIDE_LOADED)
        meta = {
            "유형": "사각",
            "입력": f"L={L}, W={W}, split={split}",
            "설치(세면)": f"L′={sL}, W′={sW}",
            "설치(샤워)": f"L′={hL}, W′={hW}",
        }

    else:
        z = corner_zones_and_installed(int(v3), int(v4), int(v5), int(v6))
        sW, sL = z["sink"]["W_inst"], z["sink"]["L_inst"]
        hW, hL = z["shower"]["W_inst"], z["shower"]["L_inst"]
        v1, v2 = z["v1"], z["v2"]
        notch_W = z["v4_notch"]  # 오목부 원 폭

        # ✅ 코너형용 셀 단위 엔진 사용
        pack = solve_corner_cellwise(BODY, SIDE, sW, sL, hW, hL, notch_W=notch_W,
                                     cut_cost_body=CUT_COST_BODY_LOADED,
                                     cut_cost_side=CUT_COST_SIDE_LOADED)
        meta = {
            "유형": "코너",
            "입력": f"L1={v1}, W2={v2}, L3={v3}, W4={v4}, L5={v5}, W6={v6}",
            "설치(세면)": f"L′={sL}, W′={sW}",
            "설치(샤워)": f"L′={hL}, W′={hW}",
        }

    if not pack.rows:
        st.error("배치 실패: 카탈로그/치수를 확인하세요.")
        st.stop()

    # 표/요약
    df_summary, df_elements, json_parts_core = summarize_rows(pack.rows)

    st.subheader("요소(셀별 패널/절단/비용)")
    st.dataframe(df_elements, use_container_width=True)

    st.subheader("요약")
    st.dataframe(df_summary.assign(**meta), use_container_width=True)

    # 행렬 스케치
    col_L = [w for _, w, _ in pack.pattern] if pack.pattern else []
    row_W = pack.row_lengths

    if col_L and row_W:
        labels: Dict[Tuple[int, int], str] = {}

        # ★ 세면부 / 샤워부 열 index(1-based) 추출
        # pack.pattern은 (L_part, W_part, label) 튜플 리스트
        # label은 "세면-열1", "샤워-열1" 형태
        sink_cols_idx: List[int] = []
        shower_cols_idx: List[int] = []
        for col_idx, (_, _, label) in enumerate(pack.pattern):
            if label.startswith("세면"):
                sink_cols_idx.append(col_idx + 1)  # 1-based index
            elif label.startswith("샤워"):
                shower_cols_idx.append(col_idx + 1)  # 1-based index

        # ★ 코너형이고 2행 구조일 때만 세면부 행 병합
        merge_sink_rows = (bath_type == "코너형 욕실" and len(row_W) == 2)

        # ---- 오복부 점선 좌표 (코너형 전용) ----
        notch_L_draw: Optional[int] = None
        notch_W_draw: Optional[int] = None

        if bath_type == "코너형 욕실":
            # 🔹 오복부 왼쪽 경계는 '세면부 설치길이 L′ = sL' 기준
            notch_L_draw = int(sL)
            # 🔹 오복부 깊이는 그대로 v4 사용
            notch_W_draw = int(v4)

            # ---- 코너형 오복부 X 표시 (샤워 열 + 상단 행) ----
            cum_row_W = [0]
            for rW in row_W:
                cum_row_W.append(cum_row_W[-1] + rW)

            for c_idx in shower_cols_idx:
                for r_idx in range(len(row_W)):
                    row_start = cum_row_W[r_idx]
                    row_end = cum_row_W[r_idx + 1]
                    row_mid = (row_start + row_end) / 2.0

                    # 행의 중심이 v4보다 위에 있으면 오복부 영역으로 간주
                    if row_mid < notch_W_draw:
                        labels[(r_idx + 1, c_idx)] = "X"

        sketch = draw_matrix_sketch(
            col_L,
            row_W,
            cell_labels=labels,
            canvas_w=900,
            canvas_h=600,
            origin="top",
            sink_cols=sink_cols_idx,
            merge_sink_rows=merge_sink_rows,
            notch_L_mm=notch_L_draw,   # 🔹 이제 sL 기준 (설치길이)
            notch_W_mm=notch_W_draw,   # 🔹 v4 그대로 (오복부 깊이)
        )
        st.subheader("배치행렬 스케치 (가로=L, 세로=W)")
        st.image(
            sketch,
            use_container_width=False,
            caption=f"{len(row_W)}행 × {len(col_L)}열",
        )

    # 종류·규격별 집계
    g_kind = (
        df_elements
        .assign(
            dim=lambda d: d["패널길이(l)"].astype(int).astype(str)
            + "x"
            + d["패널폭(w)"].astype(int).astype(str)
        )
        .groupby(["kind", "dim"])
        .size()
        .reset_index(name="개수")
        .rename(columns={"dim": "치수"})
    )
    st.subheader("종류·규격별 개수")
    st.dataframe(g_kind, use_container_width=True)

    # 관리비/최종가
    body_sub = int(df_elements.loc[df_elements["kind"] == "BODY", "판넬소계"].sum())
    side_sub = int(df_elements.loc[df_elements["kind"] == "SIDE", "판넬소계"].sum())

    hatch_count = 0
    hatch_price = 0
    hatch_name: Optional[str] = None
    body_models = Counter([r.panel.name for r in pack.rows if r.kind == "BODY"])
    if body_models:
        top_name, _ = max(body_models.items(), key=lambda x: x[1])
        sel_h = next((h for h in HATCH if h.name == top_name), None)
        if sel_h:
            hatch_count = 1
            hatch_price = sel_h.price
            hatch_name = sel_h.name

    subtotal_sum = body_sub + side_sub + hatch_price * hatch_count

    st.subheader("소계")
    st.dataframe(
        pd.DataFrame([{
            "바디 소계": body_sub,
            "사이드 소계": side_sub,
            "점검구 소계": int(hatch_price * hatch_count),
            "소계": int(subtotal_sum),
            "자동 점검구": hatch_name or "없음",
        }]),
        use_container_width=True,
    )

    # JSON
    export_json = {
        "meta": meta,
        "총개수": int(json_parts_core["총개수"]),
        "총절단": int(json_parts_core["총절단"]),
        "총단가": int(json_parts_core["총단가"]),
        "소계": int(subtotal_sum),
        "점검구": {"종류": hatch_name or "", "개수": int(hatch_count)},
    }

    st.subheader("JSON 미리보기")
    st.code(json.dumps(export_json, ensure_ascii=False, indent=2), language="json")

    buf = io.BytesIO(json.dumps(export_json, ensure_ascii=False, indent=2).encode("utf-8"))
    st.download_button(
        "JSON 다운로드",
        data=buf,
        file_name="ceiling_panels_order.json",
        mime="application/json",
    )

    # ====== Session State 자동저장 ======
    try:
        # PatternCost 객체를 직렬화 가능한 형태로 변환
        pattern_cost_data = {
            "pattern": pack.pattern,
            "total_cost": pack.total_cost,
            "row_lengths": pack.row_lengths,
        }

        st.session_state[CEIL_RESULT_KEY] = {
            "section": "ceil",
            "inputs": {
                "bath_type": bath_type,
                **meta,
            },
            "result": {
                "pattern_cost": pattern_cost_data,
                "summary": (
                    df_summary.to_dict("records")[0] if not df_summary.empty else {}
                ),
                "elements": (
                    df_elements.to_dict("records") if not df_elements.empty else []
                ),
                "소계": int(subtotal_sum),
                "hatch_info": {"name": hatch_name, "count": hatch_count, "price": hatch_price},
                "json_export": export_json,
            },
        }
        st.session_state[CEIL_DONE_KEY] = True

        # JSON 파일 자동 저장 (exports 폴더)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_filename = f"ceil_{timestamp}.json"
        json_path = os.path.join(EXPORT_DIR, json_filename)
        _save_json(json_path, st.session_state[CEIL_RESULT_KEY])

        st.success(f"✅ 천장 결과 자동저장 완료 (Session State + {json_filename})")
    except Exception as save_err:
        st.warning(f"⚠️ 자동저장 중 오류: {save_err}")

except Exception as e:
    st.error(f"계산 실패: {e}")
    import traceback

    st.code(traceback.format_exc())
