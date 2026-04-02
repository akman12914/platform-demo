# wall_panel_spec.py
# -*- coding: utf-8 -*-
# 벽판 규격/개수 계산 (Step 1 of 3)
# 바닥판 → 벽판 규격 → 타일 개수 → 벽판 원가

from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Any

import streamlit as st
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

# --- Common Styles ---
from common_styles import apply_common_styles, set_page_config
from common_sidebar import render_chatbot_sidebar

# --- Authentication ---
import auth

# =========================================
# Page Configuration
# =========================================
set_page_config(page_title="벽판 규격/개수 산출", layout="wide")
apply_common_styles()
auth.require_auth()

# 사이드바에 시방서 분석 결과 표시
render_chatbot_sidebar()

# =========================================
# Session State Keys (공유 데이터)
# =========================================
# 바닥판에서 받아오는 키
FLOOR_DONE_KEY = "floor_done"
FLOOR_RESULT_KEY = "floor_result"
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
SHARED_BOUNDARY_KEY = "shared_boundary"

# 코너형 치수 공유 키
SHARED_CORNER_V3_KEY = "shared_corner_v3"
SHARED_CORNER_V4_KEY = "shared_corner_v4"
SHARED_CORNER_V5_KEY = "shared_corner_v5"
SHARED_CORNER_V6_KEY = "shared_corner_v6"

# 벽판 규격에서 내보내는 키 (타일 개수 페이지로 전달)
WALL_SPEC_DONE_KEY = "wall_spec_done"
SHARED_WALL_PANELS_KEY = "shared_wall_panels"  # [(W,H), ...] 벽판 치수 리스트
SHARED_WALL_TILE_TYPE_KEY = "shared_wall_tile_type"  # "300x600" 등
SHARED_WALL_HEIGHT_KEY = "shared_wall_height"  # 벽 높이
SHARED_FLOOR_TYPE_KEY = "shared_floor_type"  # PVE/기타

# 젠다이 정보 공유 키 (벽판 원가 페이지로 전달)
SHARED_JENDAI_ENABLED_KEY = "shared_jendai_enabled"
SHARED_JENDAI_STEP_KEY = "shared_jendai_step"  # 단차 여부
SHARED_JENDAI_HEIGHT_KEY = "shared_jendai_height"  # 젠다이 높이 (mm)

# =========================================================
# 공통 유틸
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
# Layout 계산 엔진
# =========================================================
def iround(x: float) -> int:
    """Half-up 반올림(ROUND)."""
    return int(math.floor(x + 0.5))

class RuleError(Exception):
    pass

@dataclass
class PanelCell:
    col: int
    row: int
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

def hb2_split(width: int, TW: int) -> Tuple[int, int, str]:
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
    cols: List[Dict] = []
    if 80 < W <= 1000:
        cols.append({"width": W, "tags": ("VSTRIP",), "col_note": "W<=1000 → VSTRIP 1열"})
        return cols, "VERTICAL STRIP ONLY (80<W<=1000)"
    if W <= 2400:
        cols.append({"width": W, "tags": tuple(), "col_note": "SINGLE COLUMN (1000<W<=2400)"})
        return cols, "SINGLE COLUMN (1000<W<=2400)"
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
    if W <= 4800:
        L, R, note = hb2_split(W, TW)
        cols.append({"width": L, "tags": ("HB",), "col_note": note})
        cols.append({"width": R, "tags": ("HB",), "col_note": note})
        return cols, "HB2 (3400<W<=4800)"
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
    if W <= 7200:
        rest = W - 2400
        L, R, note = hb2_split(rest, TW)
        cols.append({"width": 2400, "tags": tuple(), "col_note": "MODULE 2400"})
        cols.append({"width": L, "tags": ("HB",), "col_note": f"HB2 on rest: {note}"})
        cols.append({"width": R, "tags": ("HB",), "col_note": f"HB2 on rest: {note}"})
        return cols, f"2400 + HB2(W-2400), rest={rest}"
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
    if W <= 9600:
        rest = W - 4800
        L, R, note = hb2_split(rest, TW)
        cols.append({"width": 2400, "tags": tuple(), "col_note": "MODULE 2400"})
        cols.append({"width": 2400, "tags": tuple(), "col_note": "MODULE 2400"})
        cols.append({"width": L, "tags": ("HB",), "col_note": f"HB2 on rest: {note}"})
        cols.append({"width": R, "tags": ("HB",), "col_note": f"HB2 on rest: {note}"})
        return cols, f"2400×2 + HB2(W-4800), rest={rest}"
    raise RuleError("WIDTH_OUT_OF_RANGE")

def vb_round(H: int, TH: int) -> Tuple[int, int]:
    m = iround(H / (2 * TH))
    top = m * TH
    bot = H - top
    return top, bot

def split_heights_general(H: int, TH: int) -> Tuple[List[Tuple[int, Tuple[str, ...]]], str, str]:
    heights: List[Tuple[int, Tuple[str, ...]]] = []
    note = ""
    if TH == 300:
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
    elif TH == 250:
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
    if TH == 300:
        if H <= 2400:
            return [(H, tuple())], "VSTRIP 300x600: H<=2400 → 1판"
        if H <= 4800:
            top, bot = vb_round(H, 300)
            return [(top, ('VB',)), (bot, ('VB',))], f"VSTRIP 300x600: 2판 VB (top={top}, bot={bot})"
        if H <= 7200:
            rem = H - 1200
            top2, bot2 = vb_round(rem, 300)
            return [(1200, tuple()), (top2, ('VB',)), (bot2, ('VB',))], f"VSTRIP 300x600: 3판"
        rem = H - 2400
        top2, bot2 = vb_round(rem, 300)
        return [(1200, tuple()), (1200, tuple()), (top2, ('VB',)), (bot2, ('VB',))], f"VSTRIP 300x600: 4판"
    elif TH == 250:
        if H <= 2200:
            return [(H, tuple())], "VSTRIP 250x400: H<=2200 → 1판"
        if H <= 4200:
            top, bot = vb_round(H, 250)
            return [(top, ('VB',)), (bot, ('VB',))], f"VSTRIP 250x400: 2판 VB (top={top}, bot={bot})"
        if H <= 6200:
            rem = H - 1000
            top2, bot2 = vb_round(rem, 250)
            return [(1000, tuple()), (top2, ('VB',)), (bot2, ('VB',))], f"VSTRIP 250x400: 3판"
        rem = H - 2000
        top2, bot2 = vb_round(rem, 250)
        return [(1000, tuple()), (1000, tuple()), (top2, ('VB',)), (bot2, ('VB',))], f"VSTRIP 250x400: 4판"
    else:
        raise RuleError("UNSUPPORTED_TILE_HEIGHT")

def layout_report(W: int, H: int, TH: int, TW: int) -> Dict[str, Any]:
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
    return {
        "inputs": {"W": W, "H": H, "TH": TH, "TW": TW},
        "horiz_branch": horiz_branch,
        "columns": col_meta,
        "panels": [p.as_dict() for p in panels],
        "counts": {"n_cols": n_cols, "n_cols_vstrip": n_vstrip, "n_cols_hb": n_hbcols, "n_panels": len(panels)}
    }

# =========================================================
# Face 모델
# =========================================================
@dataclass
class FaceSpec:
    wall_id: int
    wall_label: str
    face_idx: int
    face_label: str
    x0: int; x1: int
    y0: int; y1: int
    width_mm: int
    height_mm: int
    note: str

def wall_label(shape: str, wall_id: int) -> str:
    return f"W{wall_id}"

def rect_wall_width_of(wall_id: int, BW: int, BL: int) -> int:
    if wall_id == 1: return BL
    if wall_id == 2: return BW
    if wall_id == 3: return BL
    if wall_id == 4: return BW
    raise ValueError("사각형 문벽 번호는 1~4 범위여야 합니다.")

def corner_wall_width_of(wall_id: int, w: Dict[int, int]) -> int:
    if wall_id not in w:
        raise ValueError("코너형 문/젠다이 벽 번호는 1~6 범위여야 합니다.")
    return w[wall_id]

def normalize_door(W: int, s: float, d: float) -> Tuple[float, float, float, float, int]:
    if d <= 0 or d > W:
        raise ValueError("문 폭(d)이 유효하지 않습니다.")
    s = max(0.0, min(float(s), float(W)))
    if s == W:
        s = float(W - d)
    e = s + d
    if e > W:
        raise ValueError("문 범위(s+d)가 문벽 폭(W)을 초과합니다.")
    L = s
    R = W - e
    n_faces = (1 if L > 0 else 0) + (1 if R > 0 else 0)
    return s, e, L, R, n_faces

def build_faces_for_wall(
    shape: str,
    wall_id: int,
    width_mm: int,
    height_mm: int,
    door_tuple: Optional[Tuple[float, float]] = None,
    j_enabled: bool = False,
    j_wall: Optional[int] = None,
    j_has_step: bool = False,
    j_h: int = 1000,
    j_depth: int = 0,
    j_lower_segments: Optional[List[int]] = None,
) -> List[FaceSpec]:
    wl = wall_label(shape, wall_id)
    faces: List[FaceSpec] = []

    if door_tuple is not None:
        s_mm = int(round(door_tuple[0]))
        e_mm = int(round(door_tuple[1]))
        L = max(0, s_mm)
        R = max(0, width_mm - e_mm)
        fi = 1
        if L > 0:
            faces.append(FaceSpec(wall_id, wl, fi, f"{wl}F{fi}", 0, L, 0, height_mm, L, height_mm, "door-left"))
            fi += 1
        if R > 0:
            faces.append(FaceSpec(wall_id, wl, fi, f"{wl}F{fi}", e_mm, e_mm + R, 0, height_mm, R, height_mm, "door-right"))
        return faces

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
                faces.append(FaceSpec(wall_id, wl, fi, f"{wl}F{fi}", acc, acc + seg_w, 0, band_h, seg_w, band_h, "jendai-lower"))
                acc += seg_w
                fi += 1
            upper_h = max(0, int(height_mm) - band_h)
            if upper_h > 0:
                faces.append(FaceSpec(wall_id, wl, fi, f"{wl}F{fi}", 0, int(width_mm), band_h, band_h + upper_h, int(width_mm), upper_h, "jendai-upper"))
        else:
            faces.append(FaceSpec(wall_id, wl, fi, f"{wl}F{fi}", 0, int(width_mm), 0, band_h, int(width_mm), band_h, "jendai-lower"))
            fi += 1
            upper_h = max(0, int(height_mm) - band_h)
            if upper_h > 0:
                faces.append(FaceSpec(wall_id, wl, fi, f"{wl}F{fi}", 0, int(width_mm), band_h, band_h + upper_h, int(width_mm), upper_h, "jendai-upper"))
        return faces

    faces.append(FaceSpec(wall_id, wl, 1, f"{wl}F1", 0, int(width_mm), 0, int(height_mm), int(width_mm), int(height_mm), "single"))
    return faces

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
            shape=shape, wall_id=int(wid), width_mm=int(Wk), height_mm=int(H_eff),
            door_tuple=door_tuple, j_enabled=j_enabled,
            j_wall=(int(j_wall) if j_wall is not None else None),
            j_has_step=j_has_step, j_h=int(j_h), j_depth=int(j_depth),
            j_lower_segments=j_lower_segments_map.get(int(wid), None),
        )
        all_faces.extend(faces)
    return all_faces

def panels_for_faces_new_engine(faces: List[FaceSpec], TH: int, TW: int):
    rows, errs = [], []
    for f in faces:
        if int(f.width_mm) <= 0 or int(f.height_mm) <= 0:
            errs.append({"벽": f.wall_label, "벽면": f.face_label, "error": "INVALID_FACE_SIZE"})
            continue
        try:
            rpt = layout_report(int(f.width_mm), int(f.height_mm), TH, TW)
            horiz = rpt.get("horiz_branch", "")
            for p in rpt.get("panels", []):
                rows.append({
                    "벽": f.wall_label, "벽면": f.face_label, "타일": f"{TH} x {TW}",
                    "가로분해": horiz, "세로규칙": p.get("row_note","") or "",
                    "열": p["col"], "행": p["row"],
                    "panel_w": int(p["panel_w"]), "panel_h": int(p["panel_h"]),
                    "col_tags": p.get("col_tags",""), "row_tags": p.get("row_tags",""),
                    "face_w": int(f.width_mm), "face_h": int(f.height_mm),
                })
        except Exception as ex:
            errs.append({"벽": f.wall_label, "벽면": f.face_label, "error": str(ex)})
    return rows, errs

def compute_jendai_side_panels(shape: str, j_enabled: bool, j_has_step: bool, j_depth: int, j_h: int):
    if not (j_enabled and j_has_step):
        return []
    cnt = 2 if shape == "사각형" else 1
    return [{
        "벽": "젠다이옆벽", "벽면": f"JEND_SIDE_{i+1}", "타일": "",
        "가로분해": "SIDE-PANEL", "세로규칙": "SIDE-PANEL",
        "열": 1, "행": 1,
        "panel_w": int(j_depth), "panel_h": int(j_h),
        "col_tags": "", "row_tags": "",
        "face_w": int(j_depth), "face_h": int(j_h),
    } for i in range(cnt)]

# =========================================================
# 도면 렌더링
# =========================================================
def draw_rect_preview(BL: int, BW: int, has_split: bool, X: Optional[int], door_info=None) -> Image.Image:
    if BW > BL:
        BL, BW = BW, BL
    CANVAS_W = 760
    MARGIN = 60
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 18)
    except Exception:
        font = ImageFont.load_default()
    try:
        bbox = font.getbbox("W1")
        label_h = bbox[3] - bbox[1]
    except Exception:
        label_h = 14
    sx = (CANVAS_W - 2 * MARGIN) / max(1.0, float(BL))
    sy = sx
    rect_h_px = BW * sy
    CANVAS_H = int(rect_h_px + 2 * MARGIN + label_h)
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), "white")
    drw = ImageDraw.Draw(img)
    x0, y0 = MARGIN, MARGIN
    x1, y1 = x0 + int(BL * sx), y0 + int(BW * sy)
    drw.rectangle([x0, y0, x1, y1], outline="black", width=3)
    if has_split and X is not None:
        gx = x0 + int(X * sx)
        drw.line([gx, y0, gx, y1], fill="blue", width=3)
    if door_info:
        wall_id, s, e, W_wall = door_info
        if wall_id == 1:
            xs = x0 + int(s * sx); xe = x0 + int(e * sx)
            drw.line([xs, y1, xe, y1], fill="red", width=5)
        elif wall_id == 3:
            xs = x0 + int(s * sx); xe = x0 + int(e * sx)
            drw.line([xs, y0, xe, y0], fill="red", width=5)
        elif wall_id == 2:
            ys = y0 + int(s * sy); ye = y0 + int(e * sy)
            drw.line([x1, ys, x1, ye], fill="red", width=5)
        elif wall_id == 4:
            ys = y0 + int(s * sy); ye = y0 + int(e * sy)
            drw.line([x0, ys, x0, ye], fill="red", width=5)
    def draw_centered(text, cx, cy):
        try:
            bbox = font.getbbox(text)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
        except:
            tw, th = 20, 14
        drw.text((cx - tw / 2, cy - th / 2), text, font=font, fill="black")
    draw_centered("W1", (x0 + x1) / 2, y1 + 10 + label_h / 2)
    draw_centered("W3", (x0 + x1) / 2, y0 - 10 - label_h / 2)
    draw_centered("W2", x1 + 10 + label_h / 2, (y0 + y1) / 2)
    draw_centered("W4", x0 - 10 - label_h / 2, (y0 + y1) / 2)
    return img

def draw_wall_elevation_with_faces(wall_label_str, width_mm, height_mm, faces, target_h_px=280, margin=16, scale=None):
    usable_h = target_h_px - 2 * margin
    s = scale if scale is not None else usable_h / max(1.0, float(height_mm))
    W = int(round(width_mm * s))
    H = int(round(height_mm * s))
    CANVAS_W = int(W + 2 * margin)
    CANVAS_H = int(target_h_px + 28)
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), "white")
    drw = ImageDraw.Draw(img)
    x0, y0 = margin, margin + 20
    x1, y1 = x0 + W, y0 + H
    drw.text((margin, 4), f"{wall_label_str} : {width_mm} x {height_mm} mm", fill="black")
    drw.rectangle([x0, y0, x1, y1], outline="black", width=3)
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

# =========================================================
# UI
# =========================================================
st.title("벽판 규격/개수 산출 (Step 1)")

# 바닥판 완료 확인
floor_done = st.session_state.get(FLOOR_DONE_KEY, False)
if not floor_done:
    st.warning("벽판 계산을 진행하려면 먼저 **바닥판 계산**을 완료해야 합니다.")
    st.info("좌측 사이드바에서 **바닥판 계산** 페이지로 이동하여 계산을 먼저 진행해 주세요.")
    st.stop()

# 바닥판에서 넘어온 값
floor_result = st.session_state.get(FLOOR_RESULT_KEY, {})
floor_inputs = floor_result.get("inputs", {})
floor_shape = floor_inputs.get("shape", "사각형")
floor_W = floor_inputs.get("W", 1600)
floor_L = floor_inputs.get("L", 2000)
floor_sw = floor_inputs.get("sw", 1500)
floor_sl = floor_inputs.get("sl", 1300)
floor_shw = floor_inputs.get("shw", 900)
floor_shl = floor_inputs.get("shl", 900)
floor_usage = floor_inputs.get("usage", "PVE")
floor_boundary_type = floor_inputs.get("boundary", None)
floor_boundary = floor_sl if floor_boundary_type == "구분" else None

errors: List[str] = []

with st.sidebar:
    st.header("기본 입력")

    shape = floor_shape
    st.text_input("욕실형태 (바닥판 기준)", value=shape, disabled=True)

    split_kind = "구분 있음" if floor_boundary is not None else "구분 없음"
    st.text_input("세면/샤워 구분 (바닥판 기준)", value=split_kind, disabled=True)

    H = st.number_input("벽 높이 H (mm)", min_value=300, value=2200, step=50)

    floor_type = "PVE" if floor_usage == "PVE" else "그외(GRP/FRP)"
    st.text_input("바닥판 유형 (바닥판 기준)", value=floor_type, disabled=True)

    # 타일 선택 selectbox 검은색 텍스트 - CSS 변수 재정의
    st.markdown("""
    <style>
    div[data-testid="stSelectbox"] {
        --sb-muted: #000000;
    }
    div[data-testid="stSelectbox"] div[data-baseweb="select"] * {
        color: #000000 !important;
        -webkit-text-fill-color: #000000 !important;
    }
    </style>
    """, unsafe_allow_html=True)
    tile = st.selectbox("벽타일 규격", ["300×600", "250×400", "600×300"])
    # 바닥타일 자동 매핑 (검은색 강조)
    if tile in ["300×600", "600×300"]:
        floor_tile_display = "300×300"
    else:
        floor_tile_display = "200×200"
    st.markdown(f"<span style='color: black; font-weight: bold;'>→ 바닥타일: {floor_tile_display}</span>", unsafe_allow_html=True)
    H_eff = effective_height(H, floor_type)

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
                w1 = st.number_input("하부 ① 폭 (mm)", min_value=0, value=600, step=10)
                w2 = st.number_input("하부 ② 폭 (mm)", min_value=0, value=600, step=10)
                w3 = st.number_input("하부 ③ 폭 (mm)", min_value=0, value=600, step=10)
                j_lower_segments_map[int(j_wall)] = [int(w1), int(w2), int(w3)]
            else:
                w1 = st.number_input("하부 ① 폭 (mm)", min_value=0, value=600, step=10, key="corner_step1")
                w2 = st.number_input("하부 ② 폭 (mm)", min_value=0, value=600, step=10, key="corner_step2")
                j_lower_segments_map[int(j_wall)] = [int(w1), int(w2)]

    st.divider()
    calc = st.button("계산 & 미리보기", type="primary")

# 메인 영역
if shape == "사각형":
    BL = floor_L
    BW = floor_W
    X = floor_boundary

    st.subheader("사각형 욕실 치수 (바닥판 기준)")
    col1, col2, col3 = st.columns(3)
    col1.metric("욕실 길이 (BL)", f"{BL} mm")
    col2.metric("욕실 폭 (BW)", f"{BW} mm")
    col3.metric("경계 위치 (X)", f"{X} mm" if X else "없음")

    door_W = rect_wall_width_of(int(door_wall), int(BW), int(BL))

    if calc:
        try:
            s, e, L, R, n = normalize_door(int(door_W), float(door_s), float(door_d))
            door_draw_info = (int(door_wall), s, e, int(door_W))
        except Exception as ex:
            errors.append(str(ex))
            door_draw_info = None

        if errors:
            for msg in errors:
                st.error(msg)
        else:
            preview_img = draw_rect_preview(BL=int(BL), BW=int(BW), has_split=(floor_boundary is not None), X=(int(X) if X else None), door_info=door_draw_info)
            st.image(preview_img, caption="사각형 도면(평면) 미리보기", use_container_width=False)

            widths = {1:int(BL), 2:int(BW), 3:int(BL), 4:int(BW)}
            TH, TW = parse_tile(tile)

            TARGET_H = 280
            MARGIN = 16
            global_scale = (TARGET_H - 2 * MARGIN) / float(H_eff)

            all_faces: List[FaceSpec] = []
            cols = st.columns(2)
            for i, wid in enumerate([1,2,3,4]):
                Wk = widths[wid]
                door_tuple = (float(s), float(e)) if (door_draw_info and int(door_wall)==wid) else None
                faces = collect_all_faces(
                    shape="사각형", widths={wid: Wk}, H_eff=int(H_eff),
                    door_wall=(wid if door_tuple else None),
                    door_s=(door_tuple[0] if door_tuple else None),
                    door_e=(door_tuple[1] if door_tuple else None),
                    j_enabled=j_enabled,
                    j_wall=(int(j_wall) if j_enabled else None),
                    j_has_step=j_has_step, j_h=int(j_h), j_depth=int(j_depth),
                    j_lower_segments_map=j_lower_segments_map,
                )
                faces = [f for f in faces if f.wall_id == wid]
                all_faces.extend(faces)
                img = draw_wall_elevation_with_faces(wall_label("사각형", wid), Wk, int(H_eff), faces, scale=global_scale)
                with cols[i%2]:
                    st.image(img, caption=f"{wall_label('사각형', wid)} (벽면 {len(faces)}개)", use_container_width=False)

            st.subheader("벽면별 벽판 산출")
            rows, errs = panels_for_faces_new_engine(all_faces, TH, TW)
            if j_enabled and j_has_step and int(j_depth) > 0 and int(j_h) > 0:
                side_rows = compute_jendai_side_panels("사각형", j_enabled, j_has_step, int(j_depth), int(j_h))
                for r in side_rows:
                    r["타일"] = f"{TH} x {TW}"
                rows.extend(side_rows)

            if rows:
                df = pd.DataFrame(rows).rename(columns={
                    "face_w": "벽면폭", "face_h": "벽면높이",
                    "panel_w": "벽판폭", "panel_h": "벽판높이",
                })
                st.dataframe(df, use_container_width=True)

                st.markdown("**동일 치수 벽판 수량 집계**")
                order = df.groupby(["벽판폭","벽판높이"], as_index=False).size().rename(columns={"size":"qty"})
                order["치수"] = order["벽판폭"].astype(int).astype(str) + "×" + order["벽판높이"].astype(int).astype(str)
                st.dataframe(order[["치수","qty","벽판폭","벽판높이"]], use_container_width=True)
                st.markdown(f"**총 벽판 개수:** {len(df)} 장")

                # ★ session_state에 벽판 치수 리스트 저장 (타일 개수 페이지로 전달)
                wall_panels_list = [(int(r["벽판폭"]), int(r["벽판높이"])) for _, r in df.iterrows()]
                st.session_state[SHARED_WALL_PANELS_KEY] = wall_panels_list
                st.session_state[SHARED_WALL_TILE_TYPE_KEY] = tile.replace("×", "x")
                st.session_state[SHARED_WALL_HEIGHT_KEY] = H
                st.session_state[SHARED_FLOOR_TYPE_KEY] = floor_type
                # 젠다이 정보 저장 (벽판 원가 페이지로 전달)
                st.session_state[SHARED_JENDAI_ENABLED_KEY] = j_enabled
                st.session_state[SHARED_JENDAI_STEP_KEY] = j_has_step
                st.session_state[SHARED_JENDAI_HEIGHT_KEY] = int(j_h) if j_enabled else 0
                st.session_state[WALL_SPEC_DONE_KEY] = True

                st.success(f"벽판 {len(df)}장의 치수가 저장되었습니다. **타일 개수 계산** 페이지로 이동하세요.")

            if errs:
                st.warning("규칙 적용 실패/제약 위반 벽면")
                st.dataframe(pd.DataFrame(errs), use_container_width=True)

else:
    # 코너형
    st.subheader("코너형 욕실 치수 (바닥판 기준)")
    # 코너형 치수 가져오기
    v3 = st.session_state.get(SHARED_CORNER_V3_KEY, floor_sl)  # 세면부 길이
    v4 = st.session_state.get(SHARED_CORNER_V4_KEY, 600)       # 오목 세로
    v5 = st.session_state.get(SHARED_CORNER_V5_KEY, floor_shl) # 샤워부 길이
    v6 = st.session_state.get(SHARED_CORNER_V6_KEY, floor_shw) # 샤워부 폭

    W1 = v3 + v5
    W2 = v4 + v6
    W = {1:int(W1), 2:int(W2), 3:int(v3), 4:int(v4), 5:int(v5), 6:int(v6)}

    col1, col2 = st.columns(2)
    with col1:
        st.metric("W1 (전체 길이)", f"{W1} mm")
        st.metric("W3 (세면부 길이)", f"{v3} mm")
        st.metric("W5 (샤워부 길이)", f"{v5} mm")
    with col2:
        st.metric("W2 (전체 폭)", f"{W2} mm")
        st.metric("W4 (오목 세로)", f"{v4} mm")
        st.metric("W6 (샤워부 폭)", f"{v6} mm")

    door_W = corner_wall_width_of(int(door_wall), W)

    if calc:
        try:
            s, e, L, R, n = normalize_door(int(door_W), float(door_s), float(door_d))
        except Exception as ex:
            errors.append(str(ex))

        if errors:
            for msg in errors:
                st.error(msg)
        else:
            widths = {i:int(W[i]) for i in range(1,7)}
            TH, TW = parse_tile(tile)

            TARGET_H = 280
            MARGIN = 16
            global_scale = (TARGET_H - 2 * MARGIN) / float(H_eff)

            all_faces: List[FaceSpec] = []
            cols = st.columns(3)
            for i, wid in enumerate([1,2,3,4,5,6]):
                Wk = widths[wid]
                door_tuple = (float(s), float(e)) if int(door_wall)==wid else None
                faces = collect_all_faces(
                    shape="코너형", widths={wid: Wk}, H_eff=int(H_eff),
                    door_wall=(wid if door_tuple else None),
                    door_s=(door_tuple[0] if door_tuple else None),
                    door_e=(door_tuple[1] if door_tuple else None),
                    j_enabled=j_enabled,
                    j_wall=(int(j_wall) if j_enabled else None),
                    j_has_step=j_has_step, j_h=int(j_h), j_depth=int(j_depth),
                    j_lower_segments_map=j_lower_segments_map,
                )
                faces = [f for f in faces if f.wall_id == wid]
                all_faces.extend(faces)
                img = draw_wall_elevation_with_faces(wall_label("코너형", wid), Wk, int(H_eff), faces, scale=global_scale)
                with cols[i % 3]:
                    st.image(img, caption=f"{wall_label('코너형', wid)} (벽면 {len(faces)}개)", use_container_width=False)

            st.subheader("벽면별 벽판 산출")
            rows, errs = panels_for_faces_new_engine(all_faces, TH, TW)
            if j_enabled and j_has_step and int(j_depth) > 0 and int(j_h) > 0:
                side_rows = compute_jendai_side_panels("코너형", j_enabled, j_has_step, int(j_depth), int(j_h))
                for r in side_rows:
                    r["타일"] = f"{TH} x {TW}"
                rows.extend(side_rows)

            if rows:
                df = pd.DataFrame(rows).rename(columns={
                    "face_w": "벽면폭", "face_h": "벽면높이",
                    "panel_w": "벽판폭", "panel_h": "벽판높이",
                })
                st.dataframe(df, use_container_width=True)

                st.markdown("**동일 치수 벽판 수량 집계**")
                order = df.groupby(["벽판폭","벽판높이"], as_index=False).size().rename(columns={"size":"qty"})
                order["치수"] = order["벽판폭"].astype(int).astype(str) + "×" + order["벽판높이"].astype(int).astype(str)
                st.dataframe(order[["치수","qty","벽판폭","벽판높이"]], use_container_width=True)
                st.markdown(f"**총 벽판 개수:** {len(df)} 장")

                # ★ session_state에 벽판 치수 리스트 저장
                wall_panels_list = [(int(r["벽판폭"]), int(r["벽판높이"])) for _, r in df.iterrows()]
                st.session_state[SHARED_WALL_PANELS_KEY] = wall_panels_list
                st.session_state[SHARED_WALL_TILE_TYPE_KEY] = tile.replace("×", "x")
                st.session_state[SHARED_WALL_HEIGHT_KEY] = H
                st.session_state[SHARED_FLOOR_TYPE_KEY] = floor_type
                # 젠다이 정보 저장 (벽판 원가 페이지로 전달)
                st.session_state[SHARED_JENDAI_ENABLED_KEY] = j_enabled
                st.session_state[SHARED_JENDAI_STEP_KEY] = j_has_step
                st.session_state[SHARED_JENDAI_HEIGHT_KEY] = int(j_h) if j_enabled else 0
                st.session_state[WALL_SPEC_DONE_KEY] = True

                st.success(f"벽판 {len(df)}장의 치수가 저장되었습니다. **타일 개수 계산** 페이지로 이동하세요.")

            if errs:
                st.warning("규칙 적용 실패/제약 위반 벽면")
                st.dataframe(pd.DataFrame(errs), use_container_width=True)
