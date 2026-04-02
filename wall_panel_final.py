# wall_panel_final.py
# -*- coding: utf-8 -*-
# 벽판 계산 프로그램 (통합) - wall_panel_revised.py + 공통 스타일 + 세션 관리

from __future__ import annotations
import math
import json
import os
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Any, Literal

import streamlit as st
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

# --- Common Styles ---
from common_styles import apply_common_styles, set_page_config

# --- Authentication ---
import auth

# =========================================
# Page Configuration
# =========================================
set_page_config(page_title="벽판 계산 프로그램 (통합)", layout="wide")
apply_common_styles()
auth.require_auth()

# =========================================
# Session State Keys
# =========================================
EXPORT_DIR = "exports"
os.makedirs(EXPORT_DIR, exist_ok=True)

FLOOR_DONE_KEY = "floor_done"
FLOOR_RESULT_KEY = "floor_result"
WALL_DONE_KEY = "wall_done"
WALL_RESULT_KEY = "wall_result"
CEIL_DONE_KEY = "ceil_done"
CEIL_RESULT_KEY = "ceil_result"

# 공유 데이터 키
SHARED_EXCEL_KEY = "shared_excel_file"
SHARED_EXCEL_NAME_KEY = "shared_excel_filename"
SHARED_BATH_SHAPE_KEY = "shared_bath_shape"
SHARED_BATH_WIDTH_KEY = "shared_bath_width"
SHARED_BATH_LENGTH_KEY = "shared_bath_length"
SHARED_SINK_WIDTH_KEY = "shared_sink_width"
SHARED_MATERIAL_KEY = "shared_floor_material"

# =========================================
# Utility Functions
# =========================================
def _save_json(path: str, data: dict):
    """JSON 파일 저장"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# =========================================================
# 0) 공통 유틸
# =========================================================
def parse_tile(tile_str: str) -> Tuple[int, int]:
    """'300×600' 또는 '250×400' → (300, 600)"""
    a, b = tile_str.replace("x", "×").split("×")
    return int(a), int(b)

def effective_height(H: int, floor_type: str) -> int:
    """바닥판 유형이 PVE면 +50."""
    return int(H) + 50 if floor_type.upper() == "PVE" else int(H)

MIN_EDGE = 80

# =========================================================
# 1) 새 Layout 계산 엔진 (Self-contained)
# =========================================================
def iround(x: float) -> int:
    """Half-up 반올림(ROUND)."""
    return int(math.floor(x + 0.5))

class RuleError(Exception):
    pass

@dataclass
class PanelCell:
    col: int  # 1-based
    row: int  # 1-based (bottom=1)
    w: int
    h: int
    col_tags: Tuple[str, ...] = ()
    row_tags: Tuple[str, ...] = ()
    col_note: str = ""
    row_note: str = ""
    def as_dict(self) -> Dict[str, Any]:
        return {
            "col": self.col, "row": self.row,
            "panel_w": self.w, "panel_h": self.h,
            "col_tags": ",".join(self.col_tags) if self.col_tags else "",
            "row_tags": ",".join(self.row_tags) if self.row_tags else "",
            "col_note": self.col_note,
            "row_note": self.row_note,
        }

def ensure_producible_new(panels: List[PanelCell]):
    for p in panels:
        if p.w <= MIN_EDGE or p.h <= MIN_EDGE:
            raise RuleError(f"PANEL_TOO_SMALL: {p.w}x{p.h} at C{p.col}-R{p.row}")

# --------- 가로(HB/VSTRIP) 분해 ----------
def hb2_split(width: int, TW: int) -> Tuple[int, int, str]:
    """가로발란스(2분할, ROUND)."""
    if width < 2 * TW:
        raise RuleError(f"WIDTH_TOO_SMALL_FOR_BALANCE: {width} < {2*TW}")
    n = iround(width / (2 * TW))
    left = n * TW
    right = width - left
    if left <= MIN_EDGE or right <= MIN_EDGE:
        raise RuleError(f"HB2_BAD_SPLIT: {left}, {right}")
    note = f"HB2: n={n}, left={left}, right={right} (TW={TW})"
    return left, right, note

def split_columns_verbose(W: int, TW: int) -> Tuple[List[Dict], str]:
    """
    columns: [{width, tags(HB/VSTRIP), col_note}, ...]
    horiz_branch: 가로 분해 설명
    규칙: 2400 모듈, 오른쪽 2칸만 HB 허용, 잔여 dW<=80이면 (2400→2400−TW, 세로판→dW+TW)
    """
    cols: List[Dict] = []
    # 80 < W <= 1000 : VSTRIP 1열
    if 80 < W <= 1000:
        cols.append({"width": W, "tags": ("VSTRIP",), "col_note": "W<=1000 → VSTRIP 1열"})
        return cols, "VERTICAL STRIP ONLY (80<W<=1000)"
    # 1000 < W <= 2400 : 단일 열
    if W <= 2400:
        cols.append({"width": W, "tags": tuple(), "col_note": "SINGLE COLUMN (1000<W<=2400)"})
        return cols, "SINGLE COLUMN (1000<W<=2400)"

    # 2400 < W <= 3400 : 2400 + VSTRIP(dW) with ≤80mm correction
    if W <= 3400:
        dW = W - 2400
        if dW <= 80:
            cols.append({"width": 2400 - TW, "tags": tuple(), "col_note": f"2400→{2400-TW} (80mm 보정)"})
            cols.append({"width": dW + TW, "tags": ("VSTRIP",), "col_note": f"VSTRIP {dW}+{TW} (80mm 보정)"})
            return cols, f"2400 + VSTRIP(dW), dW={dW} ≤ 80 → 보정"
        else:
            cols.append({"width": 2400, "tags": tuple(), "col_note": "MODULE 2400"})
            cols.append({"width": dW, "tags": ("VSTRIP",), "col_note": f"VSTRIP dW={dW}"})
            return cols, f"2400 + VSTRIP(dW), dW={dW}"

    # 3400 < W <= 4800 : HB 2열
    if W <= 4800:
        L, R, note = hb2_split(W, TW)
        cols.append({"width": L, "tags": ("HB",), "col_note": note})
        cols.append({"width": R, "tags": ("HB",), "col_note": note})
        return cols, "HB2 (3400<W<=4800)"

    # 4800 < W <= 5800 : 2400 + 2400 + VSTRIP(dW) with ≤80mm correction
    if W <= 5800:
        dW = W - 4800
        cols.append({"width": 2400, "tags": tuple(), "col_note": "MODULE 2400"})
        if dW <= 80:
            cols.append({"width": 2400 - TW, "tags": tuple(), "col_note": f"2400→{2400-TW} (80mm 보정)"})
            cols.append({"width": dW + TW, "tags": ("VSTRIP",), "col_note": f"VSTRIP {dW}+{TW} (80mm 보정)"})
            return cols, f"2400 + 2400 + VSTRIP(dW), dW={dW} ≤ 80 → 보정"
        else:
            cols.append({"width": 2400, "tags": tuple(), "col_note": "MODULE 2400"})
            cols.append({"width": dW, "tags": ("VSTRIP",), "col_note": f"VSTRIP dW={dW}"})
            return cols, f"2400 + 2400 + VSTRIP(dW), dW={dW}"

    # 5800 < W <= 7200 : 2400 + HB2(W-2400)
    if W <= 7200:
        rest = W - 2400
        L, R, note = hb2_split(rest, TW)
        cols.append({"width": 2400, "tags": tuple(), "col_note": "MODULE 2400"})
        cols.append({"width": L, "tags": ("HB",), "col_note": f"HB2 on rest: {note}"})
        cols.append({"width": R, "tags": ("HB",), "col_note": f"HB2 on rest: {note}"})
        return cols, f"2400 + HB2(W-2400), rest={rest}"

    # 7200 < W <= 8200 : 2400×3 + VSTRIP(dW) with ≤80mm correction
    if W <= 8200:
        dW = W - 7200
        cols.append({"width": 2400, "tags": tuple(), "col_note": "MODULE 2400"})
        cols.append({"width": 2400, "tags": tuple(), "col_note": "MODULE 2400"})
        if dW <= 80:
            cols.append({"width": 2400 - TW, "tags": tuple(), "col_note": f"2400→{2400-TW} (80mm 보정)"})
            cols.append({"width": dW + TW, "tags": ("VSTRIP",), "col_note": f"VSTRIP {dW}+{TW} (80mm 보정)"})
            return cols, f"2400×3 + VSTRIP(dW), dW={dW} ≤ 80 → 보정"
        else:
            cols.append({"width": 2400, "tags": tuple(), "col_note": "MODULE 2400"})
            cols.append({"width": dW, "tags": ("VSTRIP",), "col_note": f"VSTRIP dW={dW}"})
            return cols, f"2400×3 + VSTRIP(dW), dW={dW}"

    # 8200 < W <= 9600 : 2400×2 + HB2(W-4800)
    if W <= 9600:
        rest = W - 4800
        L, R, note = hb2_split(rest, TW)
        cols.append({"width": 2400, "tags": tuple(), "col_note": "MODULE 2400"})
        cols.append({"width": 2400, "tags": tuple(), "col_note": "MODULE 2400"})
        cols.append({"width": L, "tags": ("HB",), "col_note": f"HB2 on rest: {note}"})
        cols.append({"width": R, "tags": ("HB",), "col_note": f"HB2 on rest: {note}"})
        return cols, f"2400×2 + HB2(W-4800), rest={rest}"

    raise RuleError("WIDTH_OUT_OF_RANGE")

# --------- 세로(행) 분해 ----------
def vb_round(H: int, TH: int) -> Tuple[int, int]:
    """세로발란스(ROUND): top=m*TH, bot=H-top."""
    m = iround(H / (2 * TH))
    top = m * TH
    bot = H - top
    return top, bot

def split_heights_general(H: int, TH: int) -> Tuple[List[Tuple[int, Tuple[str, ...]]], str, str]:
    """
    TH=300 → 상부 1200 모듈 반복 후 잔여(newH)에 VB(1200~2400) 또는 1장(≤1200)
    TH=250 → 상부 1000 모듈 반복, 최하부 ≤1200, 잔여(newH∈(1200,2200])는 VB
    """
    heights: List[Tuple[int, Tuple[str, ...]]] = []
    note = ""
    if TH == 300:  # 300x600
        k = max(0, math.ceil((H - 2400) / 1200))
        for _ in range(k):
            heights.append((1200, tuple()))
        newH = H - 1200 * k
        branch = f"GEN 300x600: k_upper1200={k}, newH={newH}"
        if newH > 0:
            if newH <= 1200:
                heights.append((newH, tuple()))
                note = "newH<=1200 → bottom 1장"
            else:
                top, bot = vb_round(newH, 300)
                heights.append((top, ('VB',)))
                heights.append((bot, ('VB',)))
                note = f"newH in (1200,2400] → VB ROUND (top={top}, bot={bot})"
        return heights, branch, note

    elif TH == 250:  # 250x400
        k = max(0, (H - 1200) // 1000)
        for _ in range(k):
            heights.append((1000, tuple()))
        newH = H - 1000 * k
        branch = f"GEN 250x400: k_upper1000={k}, newH={newH}"
        if newH <= 1200:
            heights.append((newH, tuple()))
            note = "newH<=1200 → bottom 1장"
        else:
            if newH > 2200:
                heights.append((1000, tuple()))
                newH -= 1000
            top, bot = vb_round(newH, 250)
            heights.append((top, ('VB',)))
            heights.append((bot, ('VB',)))
            note = f"newH in (1200,2200] → VB ROUND (top={top}, bot={bot})"
        return heights, branch, note

    else:
        raise RuleError("UNSUPPORTED_TILE_HEIGHT")

def split_heights_vstrip(H: int, TH: int) -> Tuple[List[Tuple[int, Tuple[str, ...]]], str]:
    """세로판(VSTRIP) 열의 세로 분해 (타일별 1~4판 규칙 + 아래 2판에 VB)"""
    if TH == 300:
        if H <= 2400:
            return [(H, tuple())], "VSTRIP 300x600: H<=2400 → 1판"
        if H <= 4800:
            top, bot = vb_round(H, 300)
            return [(top, ('VB',)), (bot, ('VB',))], f"VSTRIP 300x600: 2판 VB (top={top}, bot={bot})"
        if H <= 7200:
            rem = H - 1200
            top2, bot2 = vb_round(rem, 300)
            return [(1200, tuple()), (top2, ('VB',)), (bot2, ('VB',))], f"VSTRIP 300x600: 3판 (1200 + VB on {rem} → {top2},{bot2})"
        rem = H - 2400
        top2, bot2 = vb_round(rem, 300)
        return [(1200, tuple()), (1200, tuple()), (top2, ('VB',)), (bot2, ('VB',))], f"VSTRIP 300x600: 4판 (1200×2 + VB on {rem} → {top2},{bot2})"

    elif TH == 250:
        if H <= 2200:
            return [(H, tuple())], "VSTRIP 250x400: H<=2200 → 1판"
        if H <= 4200:
            top, bot = vb_round(H, 250)
            return [(top, ('VB',)), (bot, ('VB',))], f"VSTRIP 250x400: 2판 VB (top={top}, bot={bot})"
        if H <= 6200:
            rem = H - 1000
            top2, bot2 = vb_round(rem, 250)
            return [(1000, tuple()), (top2, ('VB',)), (bot2, ('VB',))], f"VSTRIP 250x400: 3판 (1000 + VB on {rem} → {top2},{bot2})"
        rem = H - 2000
        top2, bot2 = vb_round(rem, 250)
        return [(1000, tuple()), (1000, tuple()), (top2, ('VB',)), (bot2, ('VB',))], f"VSTRIP 250x400: 4판 (1000×2 + VB on {rem} → {top2},{bot2})"

    else:
        raise RuleError("UNSUPPORTED_TILE_HEIGHT")

def layout_report(W: int, H: int, TH: int, TW: int) -> Dict[str, Any]:
    """
    입력: W,H,TH,TW
    출력: {
      inputs, constraints, horiz_branch,
      columns: [{col, col_w, col_tags, col_note, vertical_rule, vertical_note}],
      panels:  [{col,row,panel_w,panel_h,col_tags,row_tags,col_note,row_note}],
      counts:  {n_cols, n_cols_vstrip, n_cols_hb, n_panels}
    }
    """
    if W <= MIN_EDGE or H <= MIN_EDGE:
        raise RuleError("W_AND_H_MUST_BE_GREATER_THAN_80")
    if (TH, TW) == (300, 600):
        if W > 9600 or H > 9600:
            raise RuleError("OUT_OF_RANGE_300x600_MAX_9600x9600")
    elif (TH, TW) == (250, 400):
        if W > 9600 or H > 8200:
            raise RuleError("OUT_OF_RANGE_250x400_MAX_9600x8200")
    else:
        raise RuleError("UNSUPPORTED_TILE_SIZE")

    cols, horiz_branch = split_columns_verbose(W, TW)

    panels: List[PanelCell] = []
    col_meta: List[Dict[str, Any]] = []
    for ci, c in enumerate(cols, start=1):
        cw, ctags, cnote = int(c["width"]), tuple(c["tags"]), c["col_note"]
        if 'VSTRIP' in ctags:
            rows, vbranch = split_heights_vstrip(H, TH)
            vbranch_general, vnote_general = "", ""
        else:
            rows, vbranch_general, vnote_general = split_heights_general(H, TH)
            vbranch = ""
        col_meta.append({
            "col": ci, "col_w": cw, "col_tags": ",".join(ctags) if ctags else "",
            "col_note": cnote,
            "vertical_rule": vbranch or vbranch_general, "vertical_note": vnote_general
        })
        for rj, (rh, rtags) in enumerate(rows, start=1):
            panels.append(PanelCell(
                col=ci, row=rj, w=cw, h=int(rh),
                col_tags=ctags, row_tags=rtags,
                col_note=cnote, row_note=(vbranch or vnote_general)
            ))

    ensure_producible_new(panels)

    n_cols = len(cols)
    n_vstrip = sum(1 for c in cols if 'VSTRIP' in c["tags"])
    n_hbcols = sum(1 for c in cols if 'HB' in c["tags"])
    out = {
        "inputs": {"W": W, "H": H, "TH": TH, "TW": TW},
        "constraints": {
            "min_edge_mm": MIN_EDGE, "range_ok": True,
            "tile_limit": "300x600: 9600×9600 / 250x400: 9600×8200"
        },
        "horiz_branch": horiz_branch,
        "columns": [{
            "col": cm["col"], "col_w": cm["col_w"],
            "col_tags": cm["col_tags"], "col_note": cm["col_note"],
            "vertical_rule": cm["vertical_rule"], "vertical_note": cm["vertical_note"],
        } for cm in col_meta],
        "panels": [p.as_dict() for p in panels],
        "counts": {"n_cols": n_cols, "n_cols_vstrip": n_vstrip, "n_cols_hb": n_hbcols, "n_panels": len(panels)}
    }
    return out

# =========================================================
# 2) 벽/벽면(Face) 모델 & 생성
# =========================================================
def validate_corner_dims(w: Dict[int, int]) -> List[str]:
    """코너형 합치 조건 검사: W1==W3+W5, W2==W4+W6, 모두>0."""
    err = []
    W1, W2, W3, W4, W5, W6 = (w[i] for i in range(1, 7))
    if any(v <= 0 for v in [W1, W2, W3, W4, W5, W6]):
        err.append("코너형 모든 벽폭(W1~W6)은 0보다 커야 합니다.")
    if W1 != W3 + W5:
        err.append(f"합치 조건 위반: W1(={W1})은 W3+W5(={W3+W5}) 이어야 합니다.")
    if W2 != W4 + W6:
        err.append(f"합치 조건 위반: W2(={W2})은 W4+W6(={W4+W6}) 이어야 합니다.")
    return err

def normalize_door(W: int, s: float, d: float) -> Tuple[float, float, float, float, int]:
    """도어 시작/폭 정규화: 반환 (s, e, L, R, n_faces)"""
    if d <= 0 or d > W:
        raise ValueError("문 폭(d)이 유효하지 않습니다. 0 < d ≤ 문벽 폭(W)을 만족해야 합니다.")
    s = max(0.0, min(float(s), float(W)))
    if s == W:
        s = float(W - d)
    e = s + d
    if e > W:
        raise ValueError("문 범위(s+d)가 문벽 폭(W)을 초과합니다. 시작점 또는 문폭을 줄이세요.")
    L = s
    R = W - e
    n_faces = (1 if L > 0 else 0) + (1 if R > 0 else 0)
    return s, e, L, R, n_faces

def rect_wall_width_of(wall_id: int, BW: int, BL: int) -> int:
    """사각형: 1=상(BL), 2=우(BW), 3=하(BL), 4=좌(BW)"""
    if wall_id == 1: return BL
    if wall_id == 2: return BW
    if wall_id == 3: return BL
    if wall_id == 4: return BW
    raise ValueError("사각형 문벽 번호는 1~4 범위여야 합니다.")

def corner_wall_width_of(wall_id: int, w: Dict[int, int]) -> int:
    """코너형: 입력 W1..W6 그대로 사용"""
    if wall_id not in w:
        raise ValueError("코너형 문/젠다이 벽 번호는 1~6 범위여야 합니다.")
    return w[wall_id]

# =========================================
# 벽판 원가 계산 엔진
# =========================================

# 각수별 프레임 단가 (원/m)
FRAME_UNIT_PRICE: Dict[int, float] = {
    15: 1440.0,  # 15각
    16: 1485.0,  # 16각
    19: 1798.0,  # 19각
}

# 각수별 P/U 단가 (원/㎡)
PU_UNIT_PRICE: Dict[int, float] = {
    15: 3162.0,
    16: 3341.0,
    19: 3930.0,
}

# 부자재(조립클립) 단가 (판넬 1장당 1세트 사용)
CLIP_UNIT_PRICE: float = 4320.0  # 원

# 생산인건비 관련 (총인건비)
TOTAL_LABOR_COST_PER_DAY: float = 269_000.0  # 도표1!E14

# 설비감가비 / 제조경비 / 타일관리비 / 출고+렉입고
EQUIP_DEPRECIATION_PER_SET: float = 830.0          # 설비감가비 (턴테이블 세트당)
MANUFACTURING_OVERHEAD_PER_SET: float = 435.0      # 제조경비(잡자재+전력+광열비+폐기물처리비)
TILE_MGMT_UNIT_PRICE: float = 60.0                 # 타일관리비(25톤 기준) 단가 (W × 60)
SHIPPING_RACK_PER_SET: float = 3_730.0             # 타일벽체 출고 + 렉입고

# 타일관리비 수량 W (사각형, 코너형) – 기본값 (엑셀에서 덮어씀)
W_RECT: Dict[str, float] = {
    "1415": 10.5, "1419": 10.5, "1420": 11.0, "1421": 11.0, "1422": 11.5, "1423": 12.0, "1424": 12.0,
    "1519": 10.5, "1520": 10.5, "1521": 11.0, "1522": 11.5, "1523": 11.5, "1524": 12.0,
    "1620": 11.5, "1621": 12.0, "1622": 12.5, "1623": 12.5, "1624": 13.0,
    "1721": 12.0, "1722": 12.5, "1723": 12.5, "1724": 13.0,
}

W_CORNER: Dict[str, float] = {
    "1419": 11.0, "1420": 11.0, "1421": 11.5, "1422": 11.5, "1423": 12.0, "1424": 12.0,
    "1519": 11.0, "1520": 11.0, "1521": 11.5, "1522": 11.5, "1523": 12.0, "1524": 12.0,
    "1620": 12.0, "1621": 12.0, "1622": 12.0, "1623": 12.0, "1624": 12.5,
    "1720": 12.0, "1721": 12.5, "1722": 12.5, "1723": 12.5, "1724": 12.5,
}

# 엑셀에서 읽어온 일일 생산량 규칙 ([(타일벽체크기 하한, 생산량), ...])
DAILY_PROD_TABLE: List[Tuple[float, int]] = []

@dataclass
class CostPanel:
    """원가 계산용 벽판넬 치수/수량 (mm 단위 입력)"""
    width_mm: float   # 판넬 폭 (mm)
    height_mm: float  # 판넬 높이 (mm)
    qty: int          # 수량 (장)

BathType = Literal["사각형", "코너형"]

def make_spec_code(bath_width_mm: int, bath_length_mm: int) -> str:
    """욕실 규격 코드 생성. 예: 폭 1400, 길이 1900 → "1419" """
    w = bath_width_mm // 100
    l = bath_length_mm // 100
    return f"{w}{l}"

def get_tile_mgmt_quantity(spec_code: str, bath_type: BathType) -> float:
    """규격 + 형태(사각형/코너형)에 따른 타일관리비 수량(W) 반환."""
    table = W_RECT if bath_type == "사각형" else W_CORNER
    try:
        return float(table[spec_code])
    except KeyError:
        raise KeyError(f"타일관리비 수량(W)이 정의되지 않은 규격입니다: {bath_type=}, {spec_code=}")

def get_daily_production_qty(avg_panel_area_m2: float) -> int:
    """평균 판넬 면적(㎡)에 따른 1일 생산량 기준."""
    global DAILY_PROD_TABLE
    if DAILY_PROD_TABLE:
        rules = sorted(DAILY_PROD_TABLE, key=lambda x: x[0])
        chosen = None
        for area_min, qty in rules:
            if avg_panel_area_m2 >= area_min:
                chosen = qty
            else:
                break
        if chosen is not None:
            return int(chosen)
    # 기본 로직
    if avg_panel_area_m2 <= 1.50:
        return 325
    elif avg_panel_area_m2 <= 1.89:
        return 300
    else:
        return 275

def compute_cost_for_bathroom(
    panels: List[CostPanel],
    frame_grade: int,  # 15 / 16 / 19
    bath_type: BathType,
    bath_width_mm: int,
    bath_length_mm: int,
    *,
    tile_set_price: float,
    tile_unit_price: float,
    total_labor_cost_per_day: float = TOTAL_LABOR_COST_PER_DAY,
) -> Dict[str, float]:
    """
    판넬 1장당 기준으로 AD_panel을 만들고,
    마지막에 × 판넬수량 → 욕실 1세트 생산원가(AD_set)를 계산하는 버전.
    P_set, S_set, V_set, Y, 출고/렉입고 모두 '판넬당'으로 해석.
    """
    if frame_grade not in FRAME_UNIT_PRICE:
        raise ValueError(f"지원하지 않는 각수(frame_grade): {frame_grade}")

    total_panels = sum(p.qty for p in panels)
    if total_panels <= 0:
        raise ValueError("총 판넬 수량(total_panels)이 0입니다.")

    # ── ① 면적 / 둘레 계열 ─────────────────────────────
    total_area_m2 = sum(
        (p.width_mm / 1000.0) * (p.height_mm / 1000.0) * p.qty
        for p in panels
    )
    avg_panel_area_m2 = total_area_m2 / total_panels

    # 프레임 사용량: 판넬 1장당 둘레(손실 2% 포함)
    total_perimeter_m = sum(
        2.0 * ((p.width_mm / 1000.0) + (p.height_mm / 1000.0)) * p.qty
        for p in panels
    )
    total_perimeter_with_loss_m = total_perimeter_m * 1.02
    frame_usage_m = total_perimeter_with_loss_m / total_panels  # (m / panel)

    frame_unit_price = FRAME_UNIT_PRICE[frame_grade]
    frame_amount = frame_usage_m * frame_unit_price            # 프레임비(판넬 1장당)

    pu_unit_price = PU_UNIT_PRICE[frame_grade]
    pu_amount = avg_panel_area_m2 * pu_unit_price              # P/U비(판넬 1장당)

    accessories_amount = CLIP_UNIT_PRICE                       # 조립클립(판넬 1장당)

    # ► 원재료 소계(판넬 1장당) = M_panel
    material_total = frame_amount + pu_amount + accessories_amount

    # ── ② 생산인건비 P_panel ───────────────────────────
    #    타일 일일 생산량을 판넬 수량으로 나눈 "판넬당 타일 수량"으로 인건비를 나눔
    daily_prod_qty = get_daily_production_qty(avg_panel_area_m2)   # 타일 일일 생산량 (개/일)
    tiles_per_panel = daily_prod_qty / total_panels                # 판넬당 타일 수량 (개/판넬)
    labor_per_panel = total_labor_cost_per_day / tiles_per_panel   # P_panel (판넬당 생산인건비)
    sets_per_day = daily_prod_qty / total_panels                   # 세트/일 (참고용)
    labor_per_set = labor_per_panel * total_panels                 # 세트당 생산인건비 (참고용)

    # ── ③ 설비감가비 S_panel / 제조경비 V_panel / 출고·렉입고 AB_panel ──
    #    ※ 값은 그대로 사용하되, "판넬당" 금액으로 해석
    equip_dep_per_panel = EQUIP_DEPRECIATION_PER_SET        # S_panel
    mfg_overhead_per_panel = MANUFACTURING_OVERHEAD_PER_SET # V_panel
    shipping_rack_per_panel = SHIPPING_RACK_PER_SET         # AB_panel

    spec_code = make_spec_code(bath_width_mm, bath_length_mm)

    # ── ④ 타일관리비 Y_panel ───────────────────────────
    if tile_set_price > 0 and tile_unit_price > 0:
        tile_total_tiles = float(tile_set_price) / float(tile_unit_price)
    else:
        tile_total_tiles = 0.0

    tile_per_panel = tile_total_tiles / float(total_panels) if total_panels > 0 else 0.0
    tile_mgmt_per_panel = tile_per_panel * TILE_MGMT_UNIT_PRICE    # Y_panel
    tile_mgmt_cost = tile_mgmt_per_panel * total_panels            # 세트 기준 (참고용)

    # ── ⑤ 판넬 1장당 생산원가계 AD_panel ─────────────────
    ad_per_panel = (
        material_total         # M_panel
        + labor_per_panel      # P_panel
        + equip_dep_per_panel  # S_panel
        + mfg_overhead_per_panel  # V_panel
        + tile_mgmt_per_panel  # Y_panel
        + shipping_rack_per_panel  # AB_panel
    )

    # 욕실 1세트당 생산원가 (AD_set)
    production_cost = ad_per_panel * total_panels

    return {
        "spec_code": spec_code,
        "bath_type": bath_type,
        "frame_grade": frame_grade,

        "total_panels": float(total_panels),
        "total_area_m2": total_area_m2,
        "avg_panel_area_m2": avg_panel_area_m2,

        "frame_usage_m": frame_usage_m,
        "frame_unit_price": float(frame_unit_price),
        "frame_amount": frame_amount,                 # 프레임비(판넬당)

        "pu_unit_price": float(pu_unit_price),
        "pu_amount": pu_amount,                       # P/U비(판넬당)

        "accessories_amount": float(accessories_amount),  # 조립클립(판넬당)
        "material_total": material_total,             # ★ 판넬 1장당 원재료 소계

        "daily_production_qty": float(daily_prod_qty),
        "sets_per_day": sets_per_day,
        "labor_per_panel": labor_per_panel,           # ★ P_panel
        "labor_per_set": labor_per_set,               # 참고용

        "equip_dep_per_panel": float(equip_dep_per_panel),     # ★ S_panel
        "mfg_overhead_per_panel": float(mfg_overhead_per_panel),  # ★ V_panel

        "tile_total_tiles": tile_total_tiles,
        "tile_per_panel": tile_per_panel,
        "tile_mgmt_per_panel": tile_mgmt_per_panel,  # ★ Y_panel
        "tile_mgmt_cost": tile_mgmt_cost,            # 세트 기준

        "shipping_rack_per_panel": float(shipping_rack_per_panel),  # ★ AB_panel
        "shipping_rack_cost": shipping_rack_per_panel * total_panels,  # 세트 기준

        "ad_per_panel": ad_per_panel,                # ★ AD_panel
        "production_cost": production_cost,          # AD_set
    }

@dataclass
class FaceSpec:
    wall_id: int
    wall_label: str  # "W1".."W6"
    face_idx: int
    face_label: str  # "W1F1".."W6F3"
    x0: int; x1: int
    y0: int; y1: int
    width_mm: int
    height_mm: int
    note: str

@st.cache_data
def parse_wall_cost_excel(file_data: bytes) -> Tuple[Dict[str, Any], pd.DataFrame]:
    """
    엑셀 파일에서 '벽판' sheet를 읽어 벽판 원가 계산에 필요한 파라미터를 추출한다.
    - FRAME_UNIT_PRICE / PU_UNIT_PRICE (각수별 단가)
    - 타일관리비수량 W (사각형/코너형, 욕실폭/길이별)
    - 타일수량단가, 출고+렉입고, 제조경비, 설비감가비, 총인건비, 조립클립단가
    - 타일벽체크기 하한 / 타일벽체생산량 → DAILY_PROD_TABLE
    """
    xls = pd.ExcelFile(file_data)
    if "벽판" not in xls.sheet_names:
        raise ValueError("'벽판' 시트를 찾지 못했습니다.")

    df_wall = pd.read_excel(xls, "벽판")

    cfg: Dict[str, Any] = {}

    # 1) 프레임 / P/U 단가 (각수별)
    frame_dict: Dict[int, float] = {}
    pu_dict: Dict[int, float] = {}
    rows_fp = df_wall.dropna(subset=["프레임종류", "프레임단가", "PU종류", "PU단가"])
    for _, r in rows_fp.iterrows():
        fg = str(r["프레임종류"])
        digits = "".join(ch for ch in fg if ch.isdigit())
        if not digits:
            continue
        grade = int(digits)
        frame_dict[grade] = float(r["프레임단가"])
        pu_dict[grade] = float(r["PU단가"])
    cfg["FRAME_UNIT_PRICE"] = frame_dict
    cfg["PU_UNIT_PRICE"] = pu_dict

    # 2) 타일관리비 수량 W (사각형, 코너형) – 욕실폭/길이별
    W_RECT_new: Dict[str, float] = {}
    W_CORNER_new: Dict[str, float] = {}
    rows_W = df_wall.dropna(subset=["타일관리비수량"])
    for _, r in rows_W.iterrows():
        w = int(r["욕실폭"])
        l = int(r["욕실길이"])
        spec_code = f"{w // 100}{l // 100}"
        typ = str(r["유형"]).strip()
        if typ == "사각형":
            W_RECT_new[spec_code] = float(r["타일관리비수량"])
        elif typ == "코너형":
            W_CORNER_new[spec_code] = float(r["타일관리비수량"])
    cfg["W_RECT"] = W_RECT_new
    cfg["W_CORNER"] = W_CORNER_new

    # 3) 항목별 단가 (타일수량단가, 출고/렉입고, 제조경비, 설비감가비, 총인건비, 조립클립단가)
    item_map = {
        "타일수량단가": "TILE_MGMT_UNIT_PRICE",
        "타일벽체 출고 및 렉입고": "SHIPPING_RACK_PER_SET",
        "제조경비": "MANUFACTURING_OVERHEAD_PER_SET",
        "설비감가비": "EQUIP_DEPRECIATION_PER_SET",
        "총인건비": "TOTAL_LABOR_COST_PER_DAY",
        "조립클립단가": "CLIP_UNIT_PRICE",
    }
    for excel_name, key in item_map.items():
        sub = df_wall[df_wall["항목"] == excel_name]
        if not sub.empty:
            cfg[key] = float(sub["단가"].iloc[0])

    # 4) 일일 생산량 규칙 (타일벽체크기 하한 / 타일벽체생산량)
    rules_rows = df_wall.dropna(subset=["타일벽체크기 하한", "타일벽체생산량"])
    rules: List[Tuple[float, int]] = []
    for _, r in rules_rows.iterrows():
        rules.append((float(r["타일벽체크기 하한"]), int(r["타일벽체생산량"])))
    # 중복 제거 + 정렬
    rules = sorted({(a, q) for (a, q) in rules}, key=lambda x: x[0])
    cfg["DAILY_PROD_TABLE"] = rules

    return cfg, df_wall


def apply_wall_cost_config(cfg: Dict[str, Any]) -> None:
    """
    parse_wall_cost_excel()에서 추출한 cfg를 전역 상수에 반영.
    """
    global FRAME_UNIT_PRICE, PU_UNIT_PRICE, CLIP_UNIT_PRICE
    global TOTAL_LABOR_COST_PER_DAY
    global EQUIP_DEPRECIATION_PER_SET, MANUFACTURING_OVERHEAD_PER_SET
    global TILE_MGMT_UNIT_PRICE, SHIPPING_RACK_PER_SET
    global W_RECT, W_CORNER, DAILY_PROD_TABLE

    if "FRAME_UNIT_PRICE" in cfg:
        FRAME_UNIT_PRICE.update(cfg["FRAME_UNIT_PRICE"])
    if "PU_UNIT_PRICE" in cfg:
        PU_UNIT_PRICE.update(cfg["PU_UNIT_PRICE"])
    if "CLIP_UNIT_PRICE" in cfg:
        CLIP_UNIT_PRICE = float(cfg["CLIP_UNIT_PRICE"])
    if "TOTAL_LABOR_COST_PER_DAY" in cfg:
        TOTAL_LABOR_COST_PER_DAY = float(cfg["TOTAL_LABOR_COST_PER_DAY"])
    if "EQUIP_DEPRECIATION_PER_SET" in cfg:
        EQUIP_DEPRECIATION_PER_SET = float(cfg["EQUIP_DEPRECIATION_PER_SET"])
    if "MANUFACTURING_OVERHEAD_PER_SET" in cfg:
        MANUFACTURING_OVERHEAD_PER_SET = float(cfg["MANUFACTURING_OVERHEAD_PER_SET"])
    if "TILE_MGMT_UNIT_PRICE" in cfg:
        TILE_MGMT_UNIT_PRICE = float(cfg["TILE_MGMT_UNIT_PRICE"])
    if "SHIPPING_RACK_PER_SET" in cfg:
        SHIPPING_RACK_PER_SET = float(cfg["SHIPPING_RACK_PER_SET"])
    if "W_RECT" in cfg and cfg["W_RECT"]:
        W_RECT = cfg["W_RECT"]
    if "W_CORNER" in cfg and cfg["W_CORNER"]:
        W_CORNER = cfg["W_CORNER"]
    if "DAILY_PROD_TABLE" in cfg and cfg["DAILY_PROD_TABLE"]:
        DAILY_PROD_TABLE = cfg["DAILY_PROD_TABLE"]


def wall_label(shape: str, wall_id: int) -> str:
    return f"W{wall_id}"

def build_faces_for_wall(
    shape: str,
    wall_id: int,
    width_mm: int,
    height_mm: int,
    door_tuple: Optional[Tuple[float, float]] = None,   # (s,e) mm
    j_enabled: bool = False,
    j_wall: Optional[int] = None,
    j_has_step: bool = False,
    j_h: int = 1000,
    j_depth: int = 0,
    j_lower_segments: Optional[List[int]] = None,
) -> List[FaceSpec]:
    """
    한 '벽'을 문/젠다이 설정에 따라 여러 FaceSpec으로 분해한다.
    """
    wl = wall_label(shape, wall_id)
    faces: List[FaceSpec] = []

    # 0) 도어 분할
    if door_tuple is not None:
        s_mm = int(round(door_tuple[0]))
        e_mm = int(round(door_tuple[1]))
        L = max(0, s_mm)
        R = max(0, width_mm - e_mm)
        fi = 1
        if L > 0:
            faces.append(FaceSpec(
                wall_id, wl, fi, f"{wl}F{fi}",
                0, L, 0, height_mm,
                L, height_mm, "door-left"
            ))
            fi += 1
        if R > 0:
            faces.append(FaceSpec(
                wall_id, wl, fi, f"{wl}F{fi}",
                e_mm, e_mm + R, 0, height_mm,
                R, height_mm, "door-right"
            ))
        return faces

    # 2) 젠다이
    if j_enabled and (j_wall is not None) and (int(j_wall) == int(wall_id)) and (j_h > 0):
        fi = 1
        band_h = min(int(j_h), int(height_mm))
        if j_has_step:
            segments = [int(v) for v in (j_lower_segments or []) if int(v) > 0]
            acc = 0
            for seg_w in segments:
                seg_w = min(seg_w, int(width_mm) - acc)
                if seg_w <= 0:
                    continue
                faces.append(FaceSpec(
                    wall_id, wl, fi, f"{wl}F{fi}",
                    acc, acc + seg_w, 0, band_h,
                    seg_w, band_h, "jendai-lower"
                ))
                acc += seg_w
                fi += 1
            upper_h = max(0, int(height_mm) - band_h)
            if upper_h > 0:
                faces.append(FaceSpec(
                    wall_id, wl, fi, f"{wl}F{fi}",
                    0, int(width_mm), band_h, band_h + upper_h,
                    int(width_mm), upper_h, "jendai-upper"
                ))
        else:
            faces.append(FaceSpec(
                wall_id, wl, fi, f"{wl}F{fi}",
                0, int(width_mm), 0, band_h,
                int(width_mm), band_h, "jendai-lower"
            ))
            fi += 1
            upper_h = max(0, int(height_mm) - band_h)
            if upper_h > 0:
                faces.append(FaceSpec(
                    wall_id, wl, fi, f"{wl}F{fi}",
                    0, int(width_mm), band_h, band_h + upper_h,
                    int(width_mm), upper_h, "jendai-upper"
                ))
        return faces

    # 3) 기본 면
    faces.append(FaceSpec(
        wall_id, wl, 1, f"{wl}F1",
        0, int(width_mm), 0, int(height_mm),
        int(width_mm), int(height_mm), "single"
    ))
    return faces

# =========================================================
# 3) 도면 렌더링
# =========================================================
def draw_rect_preview(
    BL: int, BW: int,
    has_split: bool, X: Optional[int],
    door_info: Optional[Tuple[int, float, float, int]] = None,
) -> Image.Image:
    """사각형 평면도. 라벨: W1~W4 (사각형을 조금 줄이고, 폰트는 키움)"""
    # 가로/세로 뒤집기 방지
    if BW > BL:
        BL, BW = BW, BL

    CANVAS_W = 760
    MARGIN   = 60  # 기존 20 → 60 : 사각형을 줄이고 라벨 공간 확보

    # 폰트 크게 (가능하면 DejaVuSans, 없으면 기본)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 18)  # 폰트 크기 ↑
    except Exception:
        font = ImageFont.load_default()

    # 라벨 높이/여백
    try:
        bbox = font.getbbox("W1")
        label_h = bbox[3] - bbox[1]
    except Exception:
        label_h = font.getsize("W1")[1]
    LABEL_MARGIN = 10

    # 스케일 계산 (여유 공간 남기고 사각형 축소)
    sx = (CANVAS_W - 2 * MARGIN) / max(1.0, float(BL))
    sy = sx
    rect_h_px = BW * sy
    CANVAS_H = int(rect_h_px + 2 * MARGIN + label_h)  # 아래쪽에 라벨 공간 추가

    img = Image.new("RGB", (CANVAS_W, CANVAS_H), "white")
    drw = ImageDraw.Draw(img)

    # 사각형 위치
    x0 = MARGIN
    y0 = MARGIN
    x1 = x0 + int(BL * sx)
    y1 = y0 + int(BW * sy)

    drw.rectangle([x0, y0, x1, y1], outline="black", width=3)

    # 세면/샤워 경계선
    if has_split and X is not None:
        gx = x0 + int(X * sx)
        drw.line([gx, y0, gx, y1], fill="blue", width=3)

    # 문(도어)
    if door_info:
        wall_id, s, e, W_wall = door_info
        if wall_id == 1:
            xs = x0 + int(s * sx); xe = x0 + int(e * sx); y = y1
            drw.line([xs, y, xe, y], fill="red", width=5)
        elif wall_id == 3:
            xs = x0 + int(s * sx); xe = x0 + int(e * sx); y = y0
            drw.line([xs, y, xe, y], fill="red", width=5)
        elif wall_id == 2:
            ys = y0 + int(s * sy); ye = y0 + int(e * sy); x = x1
            drw.line([x, ys, x, ye], fill="red", width=5)
        elif wall_id == 4:
            ys = y0 + int(s * sy); ye = y0 + int(e * sy); x = x0
            drw.line([x, ys, x, ye], fill="red", width=5)

    # 가운데 정렬 텍스트 유틸
    def draw_centered(text: str, cx: float, cy: float):
        try:
            bbox = font.getbbox(text)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
        except Exception:
            tw, th = font.getsize(text)
        drw.text((cx - tw / 2, cy - th / 2), text, font=font, fill="black")

    # 라벨 배치 (W1~W4)
    # 아래(W1)
    draw_centered("W1", (x0 + x1) / 2, y1 + LABEL_MARGIN + label_h / 2)
    # 위(W3)
    draw_centered("W3", (x0 + x1) / 2, y0 - LABEL_MARGIN - label_h / 2)
    # 오른쪽(W2)
    draw_centered("W2", x1 + LABEL_MARGIN + label_h / 2, (y0 + y1) / 2)
    # 왼쪽(W4)
    draw_centered("W4", x0 - LABEL_MARGIN - label_h / 2, (y0 + y1) / 2)

    return img

def draw_corner_preview(
    W: dict,
    has_split: bool,
    canvas_w: int = 760,
    margin: int = 20,
) -> Image.Image:
    """
    코너형 평면도. 라벨: W1~W6
    - W1 = W3 + W5 (가로 전체)
    - W2 = W4 + W6 (세로 전체)
    - W3: 세면부 길이
    - W5: 샤워부 길이
    - W4: 오목부 폭(위쪽 빈 영역 높이)
    - W6: 샤워부 폭(아래쪽 샤워 영역 높이)
    """
    W1, W2, W3, W4, W5, W6 = (int(W[i]) for i in range(1, 7))

    CANVAS_W = int(canvas_w)
    MARGIN   = int(margin)

    # 왼쪽에 라벨 공간 확보용 오프셋
    EXTRA_X = 96

    # 가로길이 W1을 기준으로 스케일 결정 (세로는 비율 유지)
    sx = (CANVAS_W - 2 * MARGIN) / max(1.0, float(W1))
    sy = sx
    CANVAS_H = int(W2 * sy + 2 * MARGIN)

    # 실제 이미지 폭은 오른쪽 여유(EXTRA_X)를 더 줌
    IMG_W = CANVAS_W + EXTRA_X
    img = Image.new("RGB", (IMG_W, CANVAS_H), "white")
    drw = ImageDraw.Draw(img)

    # 한글 폰트 로드
    try:
        font = ImageFont.truetype("malgun.ttf", 14)
    except Exception:
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 14)
        except Exception:
            font = ImageFont.load_default()

    # 좌표 변환 (0,0 이 욕실 왼쪽 위 모서리라고 가정)
    x0 = MARGIN + EXTRA_X
    y0 = MARGIN

    def X(mm: float) -> int:
        return int(round(x0 + mm * sx))

    def Y(mm: float) -> int:
        return int(round(y0 + mm * sy))

    # 1) 외곽(전체 직사각형: 0~W1, 0~W2)
    drw.rectangle([X(0), Y(0), X(W1), Y(W2)], outline="black", width=3)

    # 2) 오목부(오른쪽 상단 빈 영역)
    #    가로: W3~W1   (폭 = W5)
    #    세로: 0~W4    (높이 = W4)
    notch_x0, notch_x1 = W1 - W5, W1
    notch_y0, notch_y1 = 0, W4

    # 오목부는 '천장/벽 없음' 영역이라 흰색으로 지우고 경계선 다시 그림
    drw.rectangle(
        [X(notch_x0), Y(notch_y0), X(notch_x1), Y(notch_y1)],
        fill="white",
        outline="white",
    )
    drw.line([X(notch_x0), Y(0),          X(notch_x0), Y(notch_y1)], fill="black", width=3)
    drw.line([X(notch_x0), Y(notch_y1),   X(W1),      Y(notch_y1)], fill="black", width=3)

    # 3) 샤워부(오목부 바로 아래, 오른쪽 하단)
    #    가로: W3~W1           (폭 = W5)
    #    세로: W4~W2           (높이 = W6,  W2 = W4 + W6)
    shower_x0, shower_x1 = notch_x0, W1
    shower_y0, shower_y1 = notch_y1, W2   # = W4, W2

    drw.rectangle(
        [X(shower_x0), Y(shower_y0), X(shower_x1), Y(shower_y1)],
        outline="black",
        fill="#eeeeee",
        width=1,
    )

    # 샤워부 라벨 (대략 중앙)
    cx = (shower_x0 + shower_x1) / 2.0
    cy = (shower_y0 + shower_y1) / 2.0
    drw.text(
        (X(cx) - 18, Y(cy) - 7),
        "샤워부",
        fill="black",
        font=font,
    )

    # 세면부 라벨 (왼쪽 영역 중앙)
    semyen_cx = W3 / 2.0
    semyen_cy = W2 / 2.0
    drw.text(
        (X(semyen_cx) - 18, Y(semyen_cy) - 7),
        "세면부",
        fill="black",
        font=font,
    )

    # 4) 세면/샤워 경계선 (W3 위치)
    if has_split:
        drw.line([X(W3), Y(0), X(W3), Y(W2)], fill="blue", width=3)

    # 5) 라벨 W1~W6 위치
    off = 14
    off_x = 30  # 가로 방향 오프셋 (W4, W2 등 세로 라벨용)

    # W1: 바닥(가로 전체)
    drw.text((X(W1 / 2.0) - 8,       Y(W2) + off), "W1", fill="black")
    # W2: 왼쪽 세로 벽 전체
    drw.text((X(0) - off_x,          Y(W2 / 2.0) - 7), "W2", fill="black")
    # W3: 상단 왼쪽(세면부 길이)
    drw.text((X(W3 / 2.0) - 8,       Y(0) - off),  "W3", fill="black")
    # W4: 오목부 세로폭 (오목부 왼쪽 라인 중간)
    drw.text((X(notch_x0) - off_x,   Y(notch_y1 / 2.0) - 7), "W4", fill="black")
    # W5: 오목부/샤워 가로폭 (오목부/샤워 경계 아래)
    drw.text((X(W1 - W5 / 2.0) - 8,  Y(notch_y1) + off), "W5", fill="black")
    # W6: 우측 세로 벽 중 샤워부 쪽이 강조되도록 약간 아래쪽
    drw.text((X(W1) + off,           Y(W4 + W6 / 2.0) - 7),  "W6", fill="black")

    return img

def draw_wall_elevation_with_faces(
    wall_label_str: str,
    width_mm: int,
    height_mm: int,
    faces: List[FaceSpec],
    target_h_px: int = 280,
    margin: int = 16,
    overlays: Optional[List[Tuple[int,int,int,int]]] = None,
    scale: Optional[float] = None,
) -> Image.Image:
    """
    벽 정면도를 그림.
    scale이 주어지면 공통 스케일 사용 (모든 벽의 높이 기준 일관성 유지),
    아니면 개별 height_mm 기준으로 스케일 계산.
    """
    usable_h = target_h_px - 2 * margin
    s = scale if scale is not None else usable_h / max(1.0, float(height_mm))
    W = int(round(width_mm  * s))
    H = int(round(height_mm * s))
    CANVAS_W = int(W + 2 * margin)
    CANVAS_H = int(target_h_px + 28)

    img = Image.new("RGB", (CANVAS_W, CANVAS_H), "white")
    drw = ImageDraw.Draw(img)
    x0, y0 = margin, margin + 20
    x1, y1 = x0 + W, y0 + H

    drw.text((margin, 4), f"{wall_label_str} : {width_mm} x {height_mm} mm", fill="black")
    drw.rectangle([x0, y0, x1, y1], outline="black", width=3)

    if overlays:
        for (ox0, ox1, oy0, oy1) in overlays:
            fx0 = x0 + int(round(ox0 * s))
            fx1 = x0 + int(round(ox1 * s))
            fy0 = y1 - int(round(oy0 * s))
            fy1 = y1 - int(round(oy1 * s))
            drw.rectangle([fx0, fy1, fx1, fy0], outline="black", fill="black", width=2)

    for f in faces:
        fx0 = x0 + int(round(f.x0 * s))
        fx1 = x0 + int(round(f.x1 * s))
        fy0 = y1 - int(round(f.y0 * s))
        fy1 = y1 - int(round(f.y1 * s))
        drw.rectangle([fx0, fy1, fx1, fy0], outline="#666666", width=2)
        cx = (fx0 + fx1) // 2
        cy = (fy0 + fy1) // 2
        drw.text((cx - 14, cy - 7), f.face_label, fill="black")
    return img

# ### NEW: JENDAI SIDE UTIL
def compute_jendai_side_panels(shape: str, j_enabled: bool, j_has_step: bool,
                               j_depth: int, j_h: int):
    """단차가 있는 젠다이의 '옆벽판' 자동 생성.
       - 사각형: 2장, 코너형: 1장
       - 치수: (폭=젠다이 깊이, 높이=젠다이 높이)
    """
    if not (j_enabled and j_has_step):
        return []
    cnt = 2 if shape == "사각형" else 1
    return [{
        "벽": "젠다이옆벽",
        "벽면": f"JEND_SIDE_{i+1}",
        "타일": "",
        "가로분해": "SIDE-PANEL",
        "세로규칙": "SIDE-PANEL",
        "열": 1, "행": 1,
        "panel_w": int(j_depth), "panel_h": int(j_h),
        "col_tags": "", "row_tags": "",
        "face_w": int(j_depth), "face_h": int(j_h),
    } for i in range(cnt)]

# =========================================================
# 4) 통합 파이프라인
# =========================================================
def collect_all_faces(
    shape: str,
    widths: Dict[int,int],
    H_eff: int,
    door_wall: Optional[int],
    door_s: Optional[float],
    door_e: Optional[float],
    j_enabled: bool,
    j_wall: Optional[int],
    j_has_step: bool,
    j_h: int,
    j_depth: int,
    j_lower_segments_map: Dict[int, List[int]],
) -> List[FaceSpec]:
    all_faces: List[FaceSpec] = []
    for wid, Wk in widths.items():
        door_tuple = None
        if (door_wall is not None) and (int(door_wall)==wid) and (door_s is not None) and (door_e is not None):
            door_tuple = (float(door_s), float(door_e))
        faces = build_faces_for_wall(
            shape=shape,
            wall_id=int(wid),
            width_mm=int(Wk),
            height_mm=int(H_eff),
            door_tuple=door_tuple,
            j_enabled=j_enabled,
            j_wall=(int(j_wall) if j_wall is not None else None),
            j_has_step=j_has_step,
            j_h=int(j_h),
            j_depth=int(j_depth),
            j_lower_segments=j_lower_segments_map.get(int(wid), None),
        )
        all_faces.extend(faces)
    return all_faces

def panels_for_faces_new_engine(faces: List[FaceSpec], TH: int, TW: int):
    rows, errs = [], []

    for f in faces:
        if int(f.width_mm) <= 0 or int(f.height_mm) <= 0:
            errs.append({
                "벽": f.wall_label, "벽면": f.face_label,
                "face_w": int(f.width_mm), "face_h": int(f.height_mm),
                "타일": f"{TH} x {TW}", "error": "INVALID_FACE_SIZE", "분할사유": getattr(f, "note", "")
            })
            continue

        try:
            rpt = layout_report(int(f.width_mm), int(f.height_mm), TH, TW)
            horiz = rpt.get("horiz_branch", "")
            for p in rpt.get("panels", []):
                rows.append({
                    "벽": f.wall_label,
                    "벽면": f.face_label,
                    "타일": f"{TH} x {TW}",
                    "가로분해": horiz,
                    "세로규칙": p.get("row_note","") or "",
                    "열": p["col"], "행": p["row"],
                    "panel_w": int(p["panel_w"]), "panel_h": int(p["panel_h"]),
                    "col_tags": p.get("col_tags",""), "row_tags": p.get("row_tags",""),
                    "face_w": int(f.width_mm), "face_h": int(f.height_mm),
                })
        except Exception as ex:
            errs.append({
                "벽": f.wall_label, "벽면": f.face_label,
                "face_w": int(f.width_mm), "face_h": int(f.height_mm),
                "타일": f"{TH} x {TW}", "error": str(ex), "분할사유": getattr(f, "note", "")
            })

    return rows, errs

# =========================================================
# 5) UI
# =========================================================
st.title("벽판 규격/개수 산출")

# =========================================
# 바닥판 완료 확인 및 결과값 가져오기
# =========================================
floor_done = st.session_state.get(FLOOR_DONE_KEY, False)
if not floor_done:
    st.warning("벽판 계산을 진행하려면 먼저 **바닥판 계산**을 완료해야 합니다.")
    st.info("좌측 사이드바에서 **바닥판 계산** 페이지로 이동하여 계산을 먼저 진행해 주세요.")
    st.stop()

# 바닥판에서 넘어온 값 가져오기
floor_result = st.session_state.get(FLOOR_RESULT_KEY, {})
floor_inputs = floor_result.get("inputs", {})
floor_shape = floor_inputs.get("shape", "사각형")  # 욕실형태
floor_W = floor_inputs.get("W", 1600)  # 욕실폭 (사각형: 세로, 코너형: v2=v4+v6)
floor_L = floor_inputs.get("L", 2000)  # 욕실길이 (사각형: 가로, 코너형: v1=v3+v5)
# 코너형 매핑 (바닥판 floor_panel_final.py 기준):
#   sw = W (욕실폭 = v2 = v4+v6) → 세면부 폭으로 저장되지만 실제로는 욕실 전체 폭
#   sl = v3 (세면부 길이) → W3
#   shw = v6 (샤워부 폭) → W6
#   shl = v5 (샤워부 길이) → W5
floor_sw = floor_inputs.get("sw", 1500)   # 코너형: 욕실폭 W (= v2 = v4+v6)
floor_sl = floor_inputs.get("sl", 1300)   # 코너형: v3 (세면부 길이) → W3
floor_shw = floor_inputs.get("shw", 900)  # 코너형: v6 (샤워부 폭) → W6
floor_shl = floor_inputs.get("shl", 900)  # 코너형: v5 (샤워부 길이) → W5
floor_usage = floor_inputs.get("usage", "PVE")  # 바닥판 유형
floor_boundary_type = floor_inputs.get("boundary", None)  # 세면/샤워 구분 타입 ("구분" 또는 "구분없음")
floor_boundary = floor_sl if floor_boundary_type == "구분" else None  # 경계 위치는 sl 값 사용

# 세션 상태 초기화
if "wall_cost_cfg" not in st.session_state:
    st.session_state["wall_cost_cfg"] = {}
if "wall_cost_msg" not in st.session_state:
    st.session_state["wall_cost_msg"] = "기본 상수(코드 내 정의)를 사용 중입니다."

with st.sidebar:
    st.header("기본 입력")

    # 바닥판에서 업로드한 엑셀 파일 가져오기
    excel_file = st.session_state.get(SHARED_EXCEL_KEY)
    excel_filename = st.session_state.get(SHARED_EXCEL_NAME_KEY, "알 수 없음")

    if excel_file is not None:
        st.info(f"공유 엑셀 파일: **{excel_filename}**")
        try:
            excel_file.seek(0)
            file_bytes = excel_file.read()
            cfg, df_wall = parse_wall_cost_excel(file_bytes)
            apply_wall_cost_config(cfg)
            st.session_state["wall_cost_cfg"] = cfg
            st.session_state["wall_cost_msg"] = "엑셀 '벽판' 시트에서 원가 파라미터를 읽어 적용했습니다."
        except Exception as ex:
            st.session_state["wall_cost_msg"] = f"벽판 sheet 파싱 오류: {ex}"
    else:
        st.warning("바닥판에서 업로드한 엑셀 파일이 없습니다.")

    st.caption(st.session_state["wall_cost_msg"])

    # 2. 프레임 각수 선택 (15각 / 16각 / 19각)
    frame_label = st.radio("프레임 각수 선택", ["15각", "16각", "19각"], horizontal=True)
    frame_grade = int(frame_label.replace("각", ""))

    # 3. 기존 입력들 (욕실형태, 높이, 바닥판 유형, 타일규격 등)
    # 욕실형태는 바닥판에서 가져온 값으로 고정
    shape = floor_shape
    st.text_input("욕실형태 (바닥판 기준)", value=shape, disabled=True)

    # 세면/샤워 구분: 바닥판에서 boundary 값이 있으면 "구분 있음"
    split_kind = "구분 있음" if floor_boundary is not None else "구분 없음"
    st.text_input("세면/샤워 구분 (바닥판 기준)", value=split_kind, disabled=True)

    H = st.number_input("벽 높이 H (mm)", min_value=300, value=2200, step=50)

    # 바닥판 유형: 바닥판에서 가져온 값으로 고정
    floor_type = "PVE" if floor_usage == "PVE" else "그외(GRP/FRP)"
    st.text_input("바닥판 유형 (바닥판 기준)", value=floor_type, disabled=True)

    tile = st.selectbox("벽타일 규격", ["300×600", "250×400"])
    H_eff = effective_height(H, floor_type)

    # ★ 타일 가격/관리비 계산용 입력
    st.divider()
    st.subheader("타일 가격 정보")
    tile_set_price = st.number_input(
        "타일 set 가격 (원)",
        min_value=0.0,
        value=0.0,
        step=10_000.0,
        help="해당 욕실 1세트에 사용되는 타일 set의 총 가격"
    )
    tile_unit_price = st.number_input(
        "타일 1장 단가 (원)",
        min_value=0.0,
        value=0.0,
        step=100.0,
        help="타일 1장당 단가"
    )

    st.divider()
    st.subheader("문(도어) 설정")
    door_wall = st.number_input("문벽 번호", min_value=1, max_value=(4 if shape=="사각형" else 6), value=1, step=1)
    door_s = st.number_input("문 시작점 s (mm)", min_value=0.0, value=0.0, step=10.0)
    door_d = st.number_input("문 폭 d (mm)", min_value=0.0, value=800.0, step=10.0)

    st.divider()
    st.subheader("젠다이")
    j_enabled = st.checkbox("젠다이 있음")
    j_wall = None
    j_has_step = False
    j_h = 1000
    j_depth = 0
    j_lower_segments_map: Dict[int, List[int]] = {}

    if j_enabled:
        j_wall = st.number_input("젠다이 벽 번호", min_value=1, max_value=(4 if shape=="사각형" else 6), value=1, step=1)
        j_h = st.number_input("젠다이 높이 (mm)", min_value=50, value=1000, step=10)
        j_depth = st.number_input("젠다이 깊이 (mm)", min_value=0, value=300, step=10)

        j_has_step = st.radio("젠다이 단차", ["없음", "있음"], horizontal=True) == "있음"
        if j_has_step:
            if shape == "사각형":
                st.markdown("하부 분할(사각형): 왼쪽→오른쪽 순서 ①②③")
                w1 = st.number_input("하부 ① 폭 (mm)", min_value=0, value=600, step=10)
                w2 = st.number_input("하부 ② 폭 (mm)", min_value=0, value=600, step=10)
                w3 = st.number_input("하부 ③ 폭 (mm)", min_value=0, value=600, step=10)
                j_lower_segments_map[int(j_wall)] = [int(w1), int(w2), int(w3)]
            else:
                st.markdown("하부 분할(코너형): 왼쪽→오른쪽 순서 ①②")
                w1 = st.number_input("하부 ① 폭 (mm)", min_value=0, value=600, step=10, key="corner_step1")
                w2 = st.number_input("하부 ② 폭 (mm)", min_value=0, value=600, step=10, key="corner_step2")
                j_lower_segments_map[int(j_wall)] = [int(w1), int(w2)]

    st.divider()
    calc = st.button("계산 & 미리보기", type="primary")

errors: List[str] = []
preview_img: Optional[Image.Image] = None

if shape == "사각형":
    st.subheader("사각형 입력")
    # 바닥판에서 가져온 값으로 고정
    BL = int(floor_L)  # 욕실 길이
    BW = int(floor_W)  # 욕실 폭
    colA, colB = st.columns(2)
    with colA:
        st.text_input("욕실 길이 BL (mm) - 바닥판 기준", value=str(BL), disabled=True)
    with colB:
        st.text_input("욕실 폭 BW (mm) - 바닥판 기준", value=str(BW), disabled=True)

    X = None
    if split_kind == "구분 있음":
        # 바닥판에서 가져온 경계 위치 고정
        X = int(floor_boundary) if floor_boundary is not None else 800
        st.text_input("세면/샤워 경계 위치 X (mm) - 바닥판 기준", value=str(X), disabled=True)

    door_W = rect_wall_width_of(int(door_wall), int(BW), int(BL))

    # 젠다이 단차 검증
    if j_enabled and j_has_step and (j_wall is not None):
        target_w = rect_wall_width_of(int(j_wall), int(BW), int(BL))
        segs = [int(x) for x in (j_lower_segments_map.get(int(j_wall), []) or [])]
        need = 3
        if len(segs) < need:
            errors.append(f"사각형 단차: 하부 분할 폭은 {need}개가 필요합니다.")
        elif sum(segs) != target_w:
            errors.append(f"하부 분할 폭 합({sum(segs)}) ≠ 해당 벽폭({target_w})")

    if j_enabled and (int(door_wall) == int(j_wall or -999)):
        errors.append("같은 벽에 문과 젠다이를 동시에 설정할 수 없습니다.")

    if calc:
        try:
            s, e, L, R, n = normalize_door(int(door_W), float(door_s), float(door_d))
            door_draw_info = (int(door_wall), s, e, int(door_W))
        except Exception as ex:
            errors.append(str(ex))
            door_draw_info = None

        if errors:
            for msg in errors: st.error(msg)
        else:
            preview_img = draw_rect_preview(
                BL=int(BL), BW=int(BW),
                has_split=(split_kind=="구분 있음"),
                X=(int(X) if X is not None else None),
                door_info=door_draw_info
            )
            st.image(preview_img, caption="사각형 도면(평면) 미리보기", width=preview_img.width, use_container_width=False)

            widths = {1:int(BL), 2:int(BW), 3:int(BL), 4:int(BW)}
            st.subheader("벽면(정면도) / 라벨: WnF#")

            cols = st.columns(2)
            TH, TW = parse_tile(tile)

            # 공통 스케일 계산 (모든 벽의 높이 기준)
            TARGET_H = 280
            MARGIN = 16
            usable_h = TARGET_H - 2 * MARGIN
            global_scale = usable_h / float(H_eff)

            all_faces: List[FaceSpec] = []
            for i, wid in enumerate([1,2,3,4]):
                Wk = widths[wid]
                door_tuple = (float(s), float(e)) if (door_draw_info and int(door_wall)==wid) else None
                faces = collect_all_faces(
                    shape="사각형",
                    widths={wid: Wk},
                    H_eff=int(H_eff),
                    door_wall=(wid if door_tuple else None),
                    door_s=(door_tuple[0] if door_tuple else None),
                    door_e=(door_tuple[1] if door_tuple else None),
                    j_enabled=j_enabled,
                    j_wall=(int(j_wall) if j_enabled else None),
                    j_has_step=j_has_step,
                    j_h=int(j_h),
                    j_depth=int(j_depth),
                    j_lower_segments_map=j_lower_segments_map,
                )
                faces = [f for f in faces if f.wall_id == wid]
                all_faces.extend(faces)

                img = draw_wall_elevation_with_faces(
                    wall_label("사각형", wid), Wk, int(H_eff), faces,
                    target_h_px=TARGET_H,
                    margin=MARGIN,
                    scale=global_scale
                    )

                with cols[i%2]:
                    is_jendai_wall = (j_enabled and j_has_step and (j_wall is not None) and (int(j_wall) == int(wid)))
                    extra = 2 if is_jendai_wall else 0
                    caption = f"{wall_label('사각형', wid)} (벽면 {len(faces) + extra})개"
                    st.image(img, caption=caption, use_container_width=False)

            # 새 엔진으로 패널 산출
            st.subheader("벽면별 벽판 산출")
            rows, errs = panels_for_faces_new_engine(all_faces, TH, TW)
            if j_enabled and j_has_step and int(j_depth) > 0 and int(j_h) > 0:
                side_rows = compute_jendai_side_panels("사각형", j_enabled, j_has_step, int(j_depth), int(j_h))
                TH, TW = parse_tile(tile)
                for r in side_rows:
                    r["타일"] = f"{TH} x {TW}"
                rows.extend(side_rows)

            if rows:
                df = (pd.DataFrame(rows)
                      .rename(columns={
                          "face_w": "벽면폭", "face_h": "벽면높이",
                          "panel_w": "벽판폭", "panel_h": "벽판높이",
                          "가로분해": "가로분해(분기)", "세로규칙": "세로규칙(노트)"
                      }))
                show_cols = ["벽","벽면","타일","가로분해(분기)","세로규칙(노트)","열","행","벽판폭","벽판높이","벽면폭","벽면높이","col_tags","row_tags"]
                df = df[[c for c in show_cols if c in df.columns]]
                st.dataframe(df, use_container_width=True)

                # 동일 치수 벽판 수량 집계
                order = (
                    df.groupby(["벽판폭", "벽판높이"], as_index=False)
                      .size()
                      .rename(columns={"size": "qty"})
                )
                order["치수"] = (
                    order["벽판폭"].astype(int).astype(str)
                    + "×"
                    + order["벽판높이"].astype(int).astype(str)
                )
                order = order[["치수", "qty", "벽판폭", "벽판높이"]]
                st.markdown("**동일 치수 벽판 수량 집계**")
                st.dataframe(order, use_container_width=True)

                # 원가 계산용 Panel 리스트 구성
                panels_for_cost: List[CostPanel] = [
                    CostPanel(width_mm=float(r["벽판폭"]),
                              height_mm=float(r["벽판높이"]),
                              qty=int(r["qty"]))
                    for _, r in order.iterrows()
                ]

                panel_count = int(sum(p.qty for p in panels_for_cost))

                # 욕실 폭/길이 결정 (사각형: BL = 욕실길이, BW = 욕실폭)
                bath_width_mm = int(BW)
                bath_length_mm = int(BL)

                cfg = st.session_state.get("wall_cost_cfg", {})
                total_labor = cfg.get("TOTAL_LABOR_COST_PER_DAY", TOTAL_LABOR_COST_PER_DAY)

                # 원가 계산 실행
                cost_res = compute_cost_for_bathroom(
                    panels=panels_for_cost,
                    frame_grade=frame_grade,
                    bath_type=shape,  # "사각형"
                    bath_width_mm=bath_width_mm,
                    bath_length_mm=bath_length_mm,
                    tile_set_price=float(tile_set_price),
                    tile_unit_price=float(tile_unit_price),
                    total_labor_cost_per_day=float(total_labor),
                )

                # ==== 비용 요약 출력 ====
                st.markdown("#### 비용 집계 (욕실 1세트 기준)")

                st.write(f"- 벽판 수량: **{int(cost_res['total_panels'])} 장**")
                st.write(
                    f"- 총 벽체 면적: **{cost_res['total_area_m2']:.3f} ㎡** "
                    f"(판넬 1장 평균 {cost_res['avg_panel_area_m2']:.3f} ㎡)"
                )

                st.write(
                    f"- 프레임 사용량(판넬 1장당): **{cost_res['frame_usage_m']:.3f} m** × "
                    f"{int(cost_res['frame_unit_price']):,}원/m = {cost_res['frame_amount']:,.0f} 원"
                )
                st.write(
                    f"- P/U(판넬 1장당): 평균면적 {cost_res['avg_panel_area_m2']:.3f} ㎡ × "
                    f"{int(cost_res['pu_unit_price']):,}원/㎡ = {cost_res['pu_amount']:,.0f} 원"
                )
                st.write(f"- 조립클립(판넬 1장당): {int(cost_res['accessories_amount']):,} 원")
                st.write(f"- **원재료 소계(판넬 1장당)**: **{cost_res['material_total']:,.0f} 원**")

                st.write(
                    f"- 생산인건비(판넬 1장당): **{cost_res['labor_per_panel']:,.0f} 원** "
                    f"(타일 일일 생산량 {int(cost_res['daily_production_qty'])}개 / "
                    f"판넬수량 {int(cost_res['total_panels'])}장 = "
                    f"{cost_res['sets_per_day']:.2f}개/판넬)"
                )

                st.write(
                    f"- 설비감가비·제조경비(판넬 1장당): "
                    f"{int(cost_res['equip_dep_per_panel']):,} 원 + "
                    f"{int(cost_res['mfg_overhead_per_panel']):,} 원"
                )

                st.write(
                    f"- 타일관리비(판넬 1장당): {cost_res['tile_mgmt_per_panel']:,.0f} 원 "
                    f"(타일 {cost_res['tile_per_panel']:.2f} 장 × "
                    f"관리단가 {int(TILE_MGMT_UNIT_PRICE):,}원)"
                )

                st.write(
                    f"- 출고 + 렉입고(판넬 1장당): {int(cost_res['shipping_rack_per_panel']):,} 원"
                )

                st.write(
                    f"- **생산원가계(AD)**: "
                    f"판넬 1장당 {cost_res['ad_per_panel']:,.0f} 원 × "
                    f"{int(cost_res['total_panels'])} 장 = "
                    f"**{cost_res['production_cost']:,.0f} 원**"
                )

                # =========================================
                # 세션 상태 저장 및 JSON 내보내기
                # =========================================
                st.session_state[WALL_RESULT_KEY] = {
                    "section": "wall",
                    "inputs": {
                        "shape": shape,
                        "bath_width_mm": bath_width_mm,
                        "bath_length_mm": bath_length_mm,
                        "frame_grade": frame_grade,
                        "tile": tile,
                        "H": H,
                        "H_eff": H_eff,
                        "floor_type": floor_type,
                        "tile_set_price": tile_set_price,
                        "tile_unit_price": tile_unit_price,
                    },
                    "result": cost_res,
                    "panels": df.to_dict("records"),
                }
                st.session_state[WALL_DONE_KEY] = True

                # JSON 파일 자동 저장
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                json_filename = f"wall_{timestamp}.json"
                json_path = os.path.join(EXPORT_DIR, json_filename)
                _save_json(json_path, st.session_state[WALL_RESULT_KEY])

                # UI 피드백
                st.success("계산 완료")
                st.info("""
**다음 단계**: 천장판 계산을 진행하세요.
좌측 사이드바에서 **천장판 계산** 페이지로 이동하여 계산을 진행할 수 있습니다.
""")

                # JSON 다운로드
                json_str = json.dumps(cost_res, ensure_ascii=False, indent=2)
                st.download_button(
                    "원가 결과 JSON 다운로드",
                    data=json_str,
                    file_name="wall_panel_cost.json",
                    mime="application/json",
                )

            if errs:
                st.warning("규칙 적용 실패/제약 위반 벽면")
                df_err = (pd.DataFrame(errs).rename(columns={"face_w":"벽면폭","face_h":"벽면높이"}))
                st.dataframe(df_err, use_container_width=True)

else:
    # 코너형
    st.subheader("코너형 입력 (W1~W6) - 바닥판 기준")
    # 바닥판에서 가져온 값으로 고정
    # 바닥판 매핑: sl=v3(세면부길이→W3), shl=v5(샤워부길이→W5), shw=v6(샤워부폭→W6), sw=W(욕실폭=v4+v6)
    W3 = int(floor_sl)      # v3 (세면부 길이)
    W5 = int(floor_shl)     # v5 (샤워부 길이)
    W6 = int(floor_shw)     # v6 (샤워부 폭)
    W4 = int(floor_sw) - W6 # v4 = W - v6 (오목 세로 = 욕실폭 - 샤워부폭)
    W1 = W3 + W5            # v1 = v3 + v5 (욕실 길이)
    W2 = W4 + W6            # v2 = v4 + v6 (욕실 폭)

    cA, cB = st.columns(2)
    with cA:
        st.markdown("**가로(바닥) 방향**")
        st.text_input("W3 (mm)", value=str(W3), disabled=True, key="corner_w3")
        st.text_input("W5 (mm)", value=str(W5), disabled=True, key="corner_w5")
        st.text_input("W1 = W3 + W5", value=str(W1), disabled=True)
    with cB:
        st.markdown("**세로(좌우) 방향**")
        st.text_input("W4 (mm)", value=str(W4), disabled=True, key="corner_w4")
        st.text_input("W6 (mm)", value=str(W6), disabled=True, key="corner_w6")
        st.text_input("W2 = W4 + W6", value=str(W2), disabled=True)

    W = {1:int(W1), 2:int(W2), 3:int(W3), 4:int(W4), 5:int(W5), 6:int(W6)}
    door_W = corner_wall_width_of(int(door_wall), W)

    if j_enabled and j_has_step and (j_wall is not None):
        target_w = corner_wall_width_of(int(j_wall), W)
        segs = [int(x) for x in (j_lower_segments_map.get(int(j_wall), []) or [])]
        need = 2
        if len(segs) < need:
            errors.append(f"코너형 단차: 하부 분할 폭은 {need}개가 필요합니다.")
        elif sum(segs) != target_w:
            errors.append(f"하부 분할 폭 합({sum(segs)}) ≠ 해당 벽폭({target_w})")

    if j_enabled and 'j_wall' in locals() and int(door_wall) == int(j_wall):
        errors.append("같은 벽에 문과 젠다이를 동시에 설정할 수 없습니다.")

    if calc:
        errors.extend(validate_corner_dims(W))
        try:
            s, e, L, R, n = normalize_door(int(door_W), float(door_s), float(door_d))
        except Exception as ex:
            errors.append(str(ex))

        if errors:
            for msg in errors: st.error(msg)
        else:
            preview_img = draw_corner_preview(W=W, has_split=(split_kind=="구분 있음"), canvas_w=480, margin = 30)
            st.image(preview_img, caption="코너형 도면(평면) 미리보기", width=preview_img.width)

            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

            widths = {i:int(W[i]) for i in range(1,7)}
            st.subheader("벽면(정면도) / 라벨: WnF#")
            cols = st.columns(3)
            TH, TW = parse_tile(tile)

            # 공통 스케일 계산 (모든 벽의 높이 기준)
            TARGET_H = 280
            MARGIN = 16
            usable_h = TARGET_H - 2 * MARGIN
            global_scale = usable_h / float(H_eff)

            all_faces: List[FaceSpec] = []
            for i, wid in enumerate([1,2,3,4,5,6]):
                Wk = widths[wid]
                door_tuple = (float(s), float(e)) if int(door_wall)==wid else None
                faces = collect_all_faces(
                    shape="코너형",
                    widths={wid: Wk},
                    H_eff=int(H_eff),
                    door_wall=(wid if door_tuple else None),
                    door_s=(door_tuple[0] if door_tuple else None),
                    door_e=(door_tuple[1] if door_tuple else None),
                    j_enabled=j_enabled,
                    j_wall=(int(j_wall) if j_enabled else None),
                    j_has_step=j_has_step,
                    j_h=int(j_h),
                    j_depth=int(j_depth),
                    j_lower_segments_map=j_lower_segments_map,
                )
                faces = [f for f in faces if f.wall_id == wid]
                all_faces.extend(faces)

                img = draw_wall_elevation_with_faces(
                    wall_label("코너형", wid), Wk, int(H_eff), faces,
                    target_h_px=TARGET_H,
                    margin=MARGIN,
                    scale=global_scale
                    )

                with cols[i % 3]:
                    is_jendai_wall = (j_enabled and j_has_step and (j_wall is not None) and (int(j_wall) == int(wid)))
                    extra = 1 if is_jendai_wall else 0
                    caption = f"{wall_label('코너형', wid)} (벽면 {len(faces) + extra})개"
                    st.image(img, caption=caption, use_container_width=False)

            st.subheader("벽면별 벽판 산출")
            rows, errs = panels_for_faces_new_engine(all_faces, TH, TW)
            if j_enabled and j_has_step and int(j_depth) > 0 and int(j_h) > 0:
                side_rows = compute_jendai_side_panels("코너형", j_enabled, j_has_step, int(j_depth), int(j_h))
                TH, TW = parse_tile(tile)
                for r in side_rows:
                    r["타일"] = f"{TH} x {TW}"
                rows.extend(side_rows)

            if rows:
                df = (pd.DataFrame(rows)
                      .rename(columns={
                          "face_w":"벽면폭","face_h":"벽면높이",
                          "panel_w":"벽판폭","panel_h":"벽판높이",
                          "가로분해":"가로분해(분기)","세로규칙":"세로규칙(노트)"
                      }))
                show_cols = ["벽","벽면","타일","가로분해(분기)","세로규칙(노트)","열","행","벽판폭","벽판높이","벽면폭","벽면높이","col_tags","row_tags"]
                df = df[[c for c in show_cols if c in df.columns]]
                st.dataframe(df, use_container_width=True)

                # 동일 치수 벽판 수량 집계
                order = (
                    df.groupby(["벽판폭", "벽판높이"], as_index=False)
                      .size()
                      .rename(columns={"size": "qty"})
                )
                order["치수"] = (
                    order["벽판폭"].astype(int).astype(str)
                    + "×"
                    + order["벽판높이"].astype(int).astype(str)
                )
                order = order[["치수", "qty", "벽판폭", "벽판높이"]]
                st.markdown("**동일 치수 벽판 수량 집계**")
                st.dataframe(order, use_container_width=True)

                # 원가 계산용 Panel 리스트 구성
                panels_for_cost: List[CostPanel] = [
                    CostPanel(width_mm=float(r["벽판폭"]),
                              height_mm=float(r["벽판높이"]),
                              qty=int(r["qty"]))
                    for _, r in order.iterrows()
                ]

                panel_count = int(sum(p.qty for p in panels_for_cost))

                # 욕실 폭/길이 결정 (코너형: W2 = 욕실폭, W1 = 욕실길이)
                bath_width_mm = int(W2)
                bath_length_mm = int(W1)

                cfg = st.session_state.get("wall_cost_cfg", {})
                total_labor = cfg.get("TOTAL_LABOR_COST_PER_DAY", TOTAL_LABOR_COST_PER_DAY)

                # 원가 계산 실행
                cost_res = compute_cost_for_bathroom(
                    panels=panels_for_cost,
                    frame_grade=frame_grade,
                    bath_type=shape,  # "코너형"
                    bath_width_mm=bath_width_mm,
                    bath_length_mm=bath_length_mm,
                    tile_set_price=float(tile_set_price),
                    tile_unit_price=float(tile_unit_price),
                    total_labor_cost_per_day=float(total_labor),
                )

                # ==== 비용 요약 출력 ====
                st.markdown("#### 비용 집계 (욕실 1세트 기준)")

                st.write(f"- 벽판 수량: **{int(cost_res['total_panels'])} 장**")
                st.write(
                    f"- 총 벽체 면적: **{cost_res['total_area_m2']:.3f} ㎡** "
                    f"(판넬 1장 평균 {cost_res['avg_panel_area_m2']:.3f} ㎡)"
                )

                st.write(
                    f"- 프레임 사용량(판넬 1장당): **{cost_res['frame_usage_m']:.3f} m** × "
                    f"{int(cost_res['frame_unit_price']):,}원/m = {cost_res['frame_amount']:,.0f} 원"
                )
                st.write(
                    f"- P/U(판넬 1장당): 평균면적 {cost_res['avg_panel_area_m2']:.3f} ㎡ × "
                    f"{int(cost_res['pu_unit_price']):,}원/㎡ = {cost_res['pu_amount']:,.0f} 원"
                )
                st.write(f"- 조립클립(판넬 1장당): {int(cost_res['accessories_amount']):,} 원")
                st.write(f"- **원재료 소계(판넬 1장당)**: **{cost_res['material_total']:,.0f} 원**")

                st.write(
                    f"- 생산인건비(판넬 1장당): **{cost_res['labor_per_panel']:,.0f} 원** "
                    f"(타일 일일 생산량 {int(cost_res['daily_production_qty'])}개 / "
                    f"판넬수량 {int(cost_res['total_panels'])}장 = "
                    f"{cost_res['sets_per_day']:.2f}개/판넬)"
                )

                st.write(
                    f"- 설비감가비·제조경비(판넬 1장당): "
                    f"{int(cost_res['equip_dep_per_panel']):,} 원 + "
                    f"{int(cost_res['mfg_overhead_per_panel']):,} 원"
                )

                st.write(
                    f"- 타일관리비(판넬 1장당): {cost_res['tile_mgmt_per_panel']:,.0f} 원 "
                    f"(타일 {cost_res['tile_per_panel']:.2f} 장 × "
                    f"관리단가 {int(TILE_MGMT_UNIT_PRICE):,}원)"
                )

                st.write(
                    f"- 출고 + 렉입고(판넬 1장당): {int(cost_res['shipping_rack_per_panel']):,} 원"
                )

                st.write(
                    f"- **생산원가계(AD)**: "
                    f"판넬 1장당 {cost_res['ad_per_panel']:,.0f} 원 × "
                    f"{int(cost_res['total_panels'])} 장 = "
                    f"**{cost_res['production_cost']:,.0f} 원**"
                )

                # =========================================
                # 세션 상태 저장 및 JSON 내보내기
                # =========================================
                st.session_state[WALL_RESULT_KEY] = {
                    "section": "wall",
                    "inputs": {
                        "shape": shape,
                        "bath_width_mm": bath_width_mm,
                        "bath_length_mm": bath_length_mm,
                        "frame_grade": frame_grade,
                        "tile": tile,
                        "H": H,
                        "H_eff": H_eff,
                        "floor_type": floor_type,
                        "tile_set_price": tile_set_price,
                        "tile_unit_price": tile_unit_price,
                        "W": W,
                    },
                    "result": cost_res,
                    "panels": df.to_dict("records"),
                }
                st.session_state[WALL_DONE_KEY] = True

                # JSON 파일 자동 저장
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                json_filename = f"wall_{timestamp}.json"
                json_path = os.path.join(EXPORT_DIR, json_filename)
                _save_json(json_path, st.session_state[WALL_RESULT_KEY])

                # UI 피드백
                st.success("계산 완료")
                st.info("""
**다음 단계**: 천장판 계산을 진행하세요.
좌측 사이드바에서 **천장판 계산** 페이지로 이동하여 계산을 진행할 수 있습니다.
""")

                # JSON 다운로드
                json_str = json.dumps(cost_res, ensure_ascii=False, indent=2)
                st.download_button(
                    "원가 결과 JSON 다운로드",
                    data=json_str,
                    file_name="wall_panel_cost.json",
                    mime="application/json",
                )

            if errs:
                st.warning("규칙 적용 실패/제약 위반 벽면")
                st.dataframe(pd.DataFrame(errs).rename(columns={"face_w":"벽면폭","face_h":"벽면높이"}), use_container_width=True)

st.caption("※ 새 엔진 적용 + 벽판 단가/소계 자동계산 + JSON 내보내기까지 포함.")
