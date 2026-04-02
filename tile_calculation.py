# tile_calculation.py
# -*- coding: utf-8 -*-
# 타일 개수 계산 (Step 2 of 3)
# 바닥판 → 벽판 규격 → 타일 개수 → 벽판 원가

from __future__ import annotations
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import streamlit as st
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
import os

# --- Common Styles ---
from common_styles import apply_common_styles, set_page_config
from common_sidebar import render_chatbot_sidebar

# --- Authentication ---
import auth

# =========================================
# Page Configuration
# =========================================
set_page_config(page_title="타일 개수 계산", layout="wide")
apply_common_styles()
auth.require_auth()

# 사이드바에 시방서 분석 결과 표시
render_chatbot_sidebar()

# =========================================
# Session State Keys
# =========================================
# 바닥판에서 받아오는 키
FLOOR_DONE_KEY = "floor_done"
FLOOR_RESULT_KEY = "floor_result"
SHARED_SINK_WIDTH_KEY = "shared_sink_width"
SHARED_SINK_LENGTH_KEY = "shared_sink_length"
SHARED_SHOWER_WIDTH_KEY = "shared_shower_width"
SHARED_SHOWER_LENGTH_KEY = "shared_shower_length"
SHARED_BOUNDARY_KEY = "shared_boundary"

# 벽판 규격에서 받아오는 키
WALL_SPEC_DONE_KEY = "wall_spec_done"
SHARED_WALL_PANELS_KEY = "shared_wall_panels"
SHARED_WALL_TILE_TYPE_KEY = "shared_wall_tile_type"

# 타일 개수에서 내보내는 키 (벽판 원가 페이지로 전달)
TILE_CALC_DONE_KEY = "tile_calc_done"
SHARED_AVG_TILES_PER_PANEL_KEY = "shared_avg_tiles_per_panel"
SHARED_TOTAL_FLOOR_TILES_KEY = "shared_total_floor_tiles"
SHARED_SINK_FLOOR_TILES_KEY = "shared_sink_floor_tiles"
SHARED_SHOWER_FLOOR_TILES_KEY = "shared_shower_floor_tiles"
SHARED_TOTAL_WALL_TILES_KEY = "shared_total_wall_tiles"

# =========================================================
# 타일 계산 로직 (tile1.py에서 가져옴)
# =========================================================
@dataclass
class PanelResult:
    idx: int
    W: int
    H: int
    tile_w: int
    tile_h: int
    n_w: int
    n_h: int
    r_w: int
    r_h: int
    full_tiles: int
    large_pieces: int
    small_pieces: int
    piece_tiles_equiv: int
    total_tiles: int

@dataclass
class FloorAreaResult:
    area_name: str
    L: int
    W: int
    tile: str
    tile_w: int
    tile_h: int
    n_w: int
    n_h: int
    r_w: int
    r_h: int
    full_tiles: int
    large_pieces: int
    small_pieces: int
    piece_tiles_equiv: int
    total_tiles: int

@dataclass
class TileCalculationResult:
    """타일 계산 결과"""
    avg_tiles_per_panel: float
    total_floor_tiles: int
    sink_floor_tiles: int
    shower_floor_tiles: int
    total_wall_tiles: int

def classify_piece_area(piece_area: int, tile_area: int) -> str:
    return "L" if piece_area > (tile_area / 2) else "S"

def compute_wall_panel(W: int, H: int, tile_h: int, tile_w: int) -> PanelResult:
    if W < 81 or H < 81:
        raise ValueError("패널 치수는 최소 81mm 이상이어야 합니다.")
    if W > 2400 or H > 2400:
        raise ValueError("패널 치수는 최대 2400mm 이하여야 합니다.")

    n_w = W // tile_w
    r_w = W % tile_w
    n_h = H // tile_h
    r_h = H % tile_h

    full_tiles = n_w * n_h
    tile_area = tile_h * tile_w

    large_pieces = 0
    small_pieces = 0

    if r_w > 0 and n_h > 0:
        a_r = tile_h * r_w
        if classify_piece_area(a_r, tile_area) == "L":
            large_pieces += n_h
        else:
            small_pieces += n_h

    if r_h > 0 and n_w > 0:
        a_b = r_h * tile_w
        if classify_piece_area(a_b, tile_area) == "L":
            large_pieces += n_w
        else:
            small_pieces += n_w

    if r_w > 0 and r_h > 0:
        a_c = r_w * r_h
        if classify_piece_area(a_c, tile_area) == "L":
            large_pieces += 1
        else:
            small_pieces += 1

    piece_tiles_equiv = large_pieces + math.ceil(small_pieces / 2)
    total_tiles = full_tiles + piece_tiles_equiv

    return PanelResult(
        idx=-1, W=W, H=H,
        tile_w=tile_w, tile_h=tile_h,
        n_w=n_w, n_h=n_h, r_w=r_w, r_h=r_h,
        full_tiles=full_tiles,
        large_pieces=large_pieces,
        small_pieces=small_pieces,
        piece_tiles_equiv=piece_tiles_equiv,
        total_tiles=total_tiles
    )

def compute_rect_tiles(L: int, W: int, tile_h: int, tile_w: int, area_name: str, tile_name: str) -> FloorAreaResult:
    if L < 81 or W < 81:
        raise ValueError("바닥 치수는 최소 81mm 이상이어야 합니다.")
    if L > 2400 or W > 2400:
        raise ValueError("바닥 치수는 최대 2400mm 이하여야 합니다.")

    n_w = W // tile_w
    r_w = W % tile_w
    n_h = L // tile_h
    r_h = L % tile_h

    full_tiles = n_w * n_h
    tile_area = tile_h * tile_w

    large_pieces = 0
    small_pieces = 0

    if r_w > 0 and n_h > 0:
        a_r = tile_h * r_w
        if classify_piece_area(a_r, tile_area) == "L":
            large_pieces += n_h
        else:
            small_pieces += n_h

    if r_h > 0 and n_w > 0:
        a_b = r_h * tile_w
        if classify_piece_area(a_b, tile_area) == "L":
            large_pieces += n_w
        else:
            small_pieces += n_w

    if r_w > 0 and r_h > 0:
        a_c = r_w * r_h
        if classify_piece_area(a_c, tile_area) == "L":
            large_pieces += 1
        else:
            small_pieces += 1

    piece_tiles_equiv = large_pieces + math.ceil(small_pieces / 2)
    total_tiles = full_tiles + piece_tiles_equiv

    return FloorAreaResult(
        area_name=area_name, L=L, W=W, tile=tile_name,
        tile_w=tile_w, tile_h=tile_h,
        n_w=n_w, n_h=n_h, r_w=r_w, r_h=r_h,
        full_tiles=full_tiles,
        large_pieces=large_pieces,
        small_pieces=small_pieces,
        piece_tiles_equiv=piece_tiles_equiv,
        total_tiles=total_tiles
    )

# =========================================================
# Drawing (generic grid) - tile.py에서 가져옴
# =========================================================
def _get_font(size: int = 12):
    """한글 폰트 로드"""
    font_paths = [
        os.path.join(os.path.dirname(__file__), "NanumGothic.ttf"),
        "NanumGothic.ttf",
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/gulim.ttc",
    ]
    for fp in font_paths:
        try:
            return ImageFont.truetype(fp, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def draw_grid_rect(title: str, L: int, W: int, tile_h: int, tile_w: int, scale: float) -> Image.Image:
    """
    Draw rectangle with tile grid + leftover highlight.
    Coordinate:
      x axis: width W
      y axis: length/height L
    """
    pad = 18
    img_w = int(W * scale) + pad * 2
    img_h = int(L * scale) + pad * 2

    im = Image.new("RGB", (max(1, img_w), max(1, img_h)), "white")
    d = ImageDraw.Draw(im)

    x0, y0 = pad, pad
    x1, y1 = pad + int(W * scale), pad + int(L * scale)

    d.rectangle([x0, y0, x1, y1], outline=(0, 0, 0), width=2)

    n_w = W // tile_w
    r_w = W % tile_w
    n_h = L // tile_h
    r_h = L % tile_h

    # grid
    for k in range(1, n_w + 1):
        x = x0 + int(k * tile_w * scale)
        if x < x1:
            d.line([x, y0, x, y1], fill=(160, 160, 160), width=1)

    for k in range(1, n_h + 1):
        y = y0 + int(k * tile_h * scale)
        if y < y1:
            d.line([x0, y, x1, y], fill=(160, 160, 160), width=1)

    # highlight leftovers
    if r_w > 0:
        xs = x0 + int(n_w * tile_w * scale)
        d.rectangle([xs, y0, x1, y1], fill=(245, 245, 255), outline=None)

    if r_h > 0:
        ys = y0 + int(n_h * tile_h * scale)
        d.rectangle([x0, ys, x1, y1], fill=(255, 245, 245), outline=None)

    if r_w > 0 and r_h > 0:
        xs = x0 + int(n_w * tile_w * scale)
        ys = y0 + int(n_h * tile_h * scale)
        d.rectangle([xs, ys, x1, y1], fill=(245, 255, 245), outline=None)

    # redraw outline/grid
    d.rectangle([x0, y0, x1, y1], outline=(0, 0, 0), width=2)
    for k in range(1, n_w + 1):
        x = x0 + int(k * tile_w * scale)
        if x < x1:
            d.line([x, y0, x, y1], fill=(160, 160, 160), width=1)
    for k in range(1, n_h + 1):
        y = y0 + int(k * tile_h * scale)
        if y < y1:
            d.line([x0, y, x1, y], fill=(160, 160, 160), width=1)

    font = _get_font(12)
    d.text((pad, 4), title, fill=(0, 0, 0), font=font)
    return im


def calculate_tiles(
    wall_panels: List[Tuple[int, int]],
    sink_dimensions: Optional[Tuple[int, int]] = None,
    shower_dimensions: Optional[Tuple[int, int]] = None,
    has_split: bool = True,
    wall_tile_type: str = "300x600"
) -> TileCalculationResult:
    """
    벽패널과 바닥판의 타일 개수를 계산합니다.

    Args:
        wall_panels: 벽패널 치수 리스트 [(W, H), (W, H), ...] (단위: mm)
        sink_dimensions: 세면부 치수 (L, W) (단위: mm), None이면 바닥 계산 안함
        shower_dimensions: 샤워부 치수 (L, W) (단위: mm), has_split=True일 때만 사용
        has_split: 세면부/샤워부 구분 여부
        wall_tile_type: 벽타일 종류 ("300x600", "250x400", "600x300")

    Returns:
        TileCalculationResult
    """
    # 벽타일/바닥타일 크기 결정
    if wall_tile_type == "300x600":
        wall_tile_h, wall_tile_w = 300, 600
        floor_tile_h, floor_tile_w = 300, 300
        floor_tile_name = "300x300"
    elif wall_tile_type == "250x400":
        wall_tile_h, wall_tile_w = 250, 400
        floor_tile_h, floor_tile_w = 200, 200
        floor_tile_name = "200x200"
    else:  # "600x300"
        wall_tile_h, wall_tile_w = 600, 300
        floor_tile_h, floor_tile_w = 300, 300
        floor_tile_name = "300x300"

    # 벽패널 타일 계산
    wall_total_tiles = 0
    panel_count = len(wall_panels)

    for W, H in wall_panels:
        try:
            result = compute_wall_panel(W, H, tile_h=wall_tile_h, tile_w=wall_tile_w)
            wall_total_tiles += result.total_tiles
        except ValueError:
            # 패널 크기가 범위를 벗어나면 무시
            pass

    avg_tiles_per_panel = wall_total_tiles / panel_count if panel_count > 0 else 0.0

    # 바닥 타일 계산
    sink_floor_tiles = 0
    shower_floor_tiles = 0

    if sink_dimensions is not None:
        sink_L, sink_W = sink_dimensions
        try:
            sink_result = compute_rect_tiles(sink_L, sink_W, floor_tile_h, floor_tile_w, "SINK", floor_tile_name)
            sink_floor_tiles = sink_result.total_tiles
        except ValueError:
            pass

    if has_split and shower_dimensions is not None:
        shower_L, shower_W = shower_dimensions
        try:
            shower_result = compute_rect_tiles(shower_L, shower_W, floor_tile_h, floor_tile_w, "SHOWER", floor_tile_name)
            shower_floor_tiles = shower_result.total_tiles
        except ValueError:
            pass

    total_floor_tiles = sink_floor_tiles + shower_floor_tiles

    return TileCalculationResult(
        avg_tiles_per_panel=avg_tiles_per_panel,
        total_floor_tiles=total_floor_tiles,
        sink_floor_tiles=sink_floor_tiles,
        shower_floor_tiles=shower_floor_tiles,
        total_wall_tiles=wall_total_tiles
    )

# =========================================================
# UI
# =========================================================
st.title("타일 개수 계산 (Step 2)")

# 바닥판 완료 확인
floor_done = st.session_state.get(FLOOR_DONE_KEY, False)
if not floor_done:
    st.warning("타일 계산을 진행하려면 먼저 **바닥판 계산**을 완료해야 합니다.")
    st.stop()

# 벽판 규격 완료 확인
wall_spec_done = st.session_state.get(WALL_SPEC_DONE_KEY, False)
if not wall_spec_done:
    st.warning("타일 계산을 진행하려면 먼저 **벽판 규격** 계산을 완료해야 합니다.")
    st.info("벽판 규격 페이지에서 '계산 & 미리보기' 버튼을 눌러 벽판 치수를 생성하세요.")
    st.stop()

# 데이터 가져오기
wall_panels = st.session_state.get(SHARED_WALL_PANELS_KEY, [])
saved_wall_tile_type = st.session_state.get(SHARED_WALL_TILE_TYPE_KEY, "300x600")

floor_result = st.session_state.get(FLOOR_RESULT_KEY, {})
floor_inputs = floor_result.get("inputs", {})
floor_boundary_type = floor_inputs.get("boundary", None)
has_split = floor_boundary_type == "구분"

# 바닥판 치수
floor_W = floor_inputs.get("W", 1400)
floor_L = floor_inputs.get("L", 2100)
floor_sw = floor_inputs.get("sw", floor_W)
floor_sl = floor_inputs.get("sl", 1300)
floor_shw = floor_inputs.get("shw", floor_W)
floor_shl = floor_inputs.get("shl", 800)

# 사이드바
with st.sidebar:
    st.header("타일 설정")

    # 벽타일 규격 (벽판 규격에서 받아온 값 고정 표시)
    wall_tile_type = saved_wall_tile_type
    st.text_input("벽타일 규격", value=wall_tile_type, disabled=True)

    # 바닥타일 자동 매핑 표시 (검은색 강조)
    if wall_tile_type in ["300x600", "600x300"]:
        floor_tile_display = "300x300"
    else:
        floor_tile_display = "200x200"
    st.markdown(f"<span style='color: black; font-weight: bold;'>→ 바닥타일: {floor_tile_display}</span>", unsafe_allow_html=True)

    st.divider()

    st.subheader("벽판 정보")
    st.metric("벽판 개수", f"{len(wall_panels)} 장")

    st.divider()

    st.subheader("바닥판 정보")
    st.metric("세면/샤워 구분", "있음" if has_split else "없음")

    if has_split:
        st.metric("세면부 치수", f"{floor_sl} × {floor_sw} mm")
        st.metric("샤워부 치수", f"{floor_shl} × {floor_shw} mm")
    else:
        st.metric("바닥 치수", f"{floor_L} × {floor_W} mm")

    st.divider()
    calc_btn = st.button("타일 개수 계산", type="primary", use_container_width=True)

# 메인 영역
st.subheader("벽판 치수 리스트")
if wall_panels:
    df_panels = pd.DataFrame(wall_panels, columns=["벽판폭 (mm)", "벽판높이 (mm)"])
    df_panels.index = df_panels.index + 1
    df_panels.index.name = "번호"

    # 치수별 집계
    df_grouped = df_panels.groupby(["벽판폭 (mm)", "벽판높이 (mm)"]).size().reset_index(name="수량")
    df_grouped["치수"] = df_grouped["벽판폭 (mm)"].astype(str) + " × " + df_grouped["벽판높이 (mm)"].astype(str)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**개별 벽판 목록**")
        st.dataframe(df_panels, use_container_width=True, height=300)
    with col2:
        st.markdown("**치수별 집계**")
        st.dataframe(df_grouped[["치수", "수량"]], use_container_width=True)
else:
    st.warning("벽판 치수 데이터가 없습니다.")

st.divider()

if calc_btn:
    st.subheader("타일 개수 계산 결과")

    # 바닥 치수 설정
    if has_split:
        sink_dims = (floor_sl, floor_sw)
        shower_dims = (floor_shl, floor_shw)
    else:
        sink_dims = (floor_L, floor_W)
        shower_dims = None

    # 계산 실행
    result = calculate_tiles(
        wall_panels=wall_panels,
        sink_dimensions=sink_dims,
        shower_dimensions=shower_dims,
        has_split=has_split,
        wall_tile_type=wall_tile_type
    )

    # 결과 표시
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("패널당 평균 타일", f"{result.avg_tiles_per_panel:.2f} 장")
    col2.metric("총 벽 타일", f"{result.total_wall_tiles} 장")
    col3.metric("총 바닥 타일", f"{result.total_floor_tiles} 장")

    if has_split:
        col4.metric("세면부 바닥타일", f"{result.sink_floor_tiles} 장")
        st.metric("샤워부 바닥타일", f"{result.shower_floor_tiles} 장")

    st.divider()

    # 상세 결과
    st.subheader("상세 결과")

    # 벽타일 상세
    st.markdown("**벽 타일 계산 상세**")
    if wall_tile_type == "300x600":
        wall_tile_h, wall_tile_w = 300, 600
    elif wall_tile_type == "250x400":
        wall_tile_h, wall_tile_w = 250, 400
    else:
        wall_tile_h, wall_tile_w = 600, 300

    wall_details = []
    for i, (W, H) in enumerate(wall_panels, 1):
        try:
            pr = compute_wall_panel(W, H, tile_h=wall_tile_h, tile_w=wall_tile_w)
            wall_details.append({
                "번호": i,
                "벽판 치수": f"{W}×{H}",
                "온타일": pr.full_tiles,
                "큰조각": pr.large_pieces,
                "작은조각": pr.small_pieces,
                "조각환산": pr.piece_tiles_equiv,
                "총 타일": pr.total_tiles
            })
        except ValueError as e:
            wall_details.append({
                "번호": i,
                "벽판 치수": f"{W}×{H}",
                "온타일": "-",
                "큰조각": "-",
                "작은조각": "-",
                "조각환산": "-",
                "총 타일": f"오류: {e}"
            })

    df_wall_details = pd.DataFrame(wall_details)
    st.dataframe(df_wall_details, use_container_width=True)

    # 바닥타일 상세
    st.markdown("**바닥 타일 계산 상세**")
    if wall_tile_type == "300x600" or wall_tile_type == "600x300":
        floor_tile_h, floor_tile_w = 300, 300
        floor_tile_name = "300x300"
    else:
        floor_tile_h, floor_tile_w = 200, 200
        floor_tile_name = "200x200"

    floor_details = []
    if has_split:
        if sink_dims:
            try:
                fr = compute_rect_tiles(sink_dims[0], sink_dims[1], floor_tile_h, floor_tile_w, "세면부", floor_tile_name)
                floor_details.append({
                    "영역": "세면부",
                    "치수": f"{sink_dims[0]}×{sink_dims[1]}",
                    "온타일": fr.full_tiles,
                    "큰조각": fr.large_pieces,
                    "작은조각": fr.small_pieces,
                    "조각환산": fr.piece_tiles_equiv,
                    "총 타일": fr.total_tiles
                })
            except ValueError:
                pass
        if shower_dims:
            try:
                fr = compute_rect_tiles(shower_dims[0], shower_dims[1], floor_tile_h, floor_tile_w, "샤워부", floor_tile_name)
                floor_details.append({
                    "영역": "샤워부",
                    "치수": f"{shower_dims[0]}×{shower_dims[1]}",
                    "온타일": fr.full_tiles,
                    "큰조각": fr.large_pieces,
                    "작은조각": fr.small_pieces,
                    "조각환산": fr.piece_tiles_equiv,
                    "총 타일": fr.total_tiles
                })
            except ValueError:
                pass
    else:
        if sink_dims:
            try:
                fr = compute_rect_tiles(sink_dims[0], sink_dims[1], floor_tile_h, floor_tile_w, "바닥", floor_tile_name)
                floor_details.append({
                    "영역": "바닥(전체)",
                    "치수": f"{sink_dims[0]}×{sink_dims[1]}",
                    "온타일": fr.full_tiles,
                    "큰조각": fr.large_pieces,
                    "작은조각": fr.small_pieces,
                    "조각환산": fr.piece_tiles_equiv,
                    "총 타일": fr.total_tiles
                })
            except ValueError:
                pass

    if floor_details:
        df_floor_details = pd.DataFrame(floor_details)
        st.dataframe(df_floor_details, use_container_width=True)

    # session_state에 결과 저장
    st.session_state[SHARED_AVG_TILES_PER_PANEL_KEY] = result.avg_tiles_per_panel
    st.session_state[SHARED_TOTAL_FLOOR_TILES_KEY] = result.total_floor_tiles
    st.session_state[SHARED_SINK_FLOOR_TILES_KEY] = result.sink_floor_tiles
    st.session_state[SHARED_SHOWER_FLOOR_TILES_KEY] = result.shower_floor_tiles
    st.session_state[SHARED_TOTAL_WALL_TILES_KEY] = result.total_wall_tiles
    st.session_state[TILE_CALC_DONE_KEY] = True

    st.success("타일 개수 계산이 완료되었습니다. **벽판 원가** 페이지로 이동하세요.")

    # =========================================================
    # 격자 시각화 (tile.py에서 가져옴)
    # =========================================================
    st.divider()
    st.subheader("격자 시각화")

    # 스케일 계산 (tile1.py와 동일하게 800 기준)
    max_wall_W = max(W for W, H in wall_panels) if wall_panels else 1
    max_wall_H = max(H for W, H in wall_panels) if wall_panels else 1
    wall_scale = 800 / max(max_wall_W, max_wall_H)

    # 바닥 스케일
    if has_split and sink_dims and shower_dims:
        max_floor_dim = max(sink_dims[0], sink_dims[1], shower_dims[0], shower_dims[1])
    elif sink_dims:
        max_floor_dim = max(sink_dims[0], sink_dims[1])
    else:
        max_floor_dim = 1
    floor_scale = 800 / max_floor_dim

    tab1, tab2 = st.tabs(["벽판(벽타일)", "바닥판(바닥타일)"])

    with tab1:
        cols = st.columns(2)
        for i, (W, H) in enumerate(wall_panels):
            try:
                pr = compute_wall_panel(W, H, tile_h=wall_tile_h, tile_w=wall_tile_w)
                title = f"#{i+1}  {W}x{H}mm  (tile {wall_tile_h}x{wall_tile_w})"
                im = draw_grid_rect(title, L=H, W=W, tile_h=wall_tile_h, tile_w=wall_tile_w, scale=wall_scale)
                col_idx = i % 2
                with cols[col_idx]:
                    st.image(im, use_container_width=False)
                    st.caption(
                        f"온타일 {pr.full_tiles} | 큰조각 {pr.large_pieces} | 작은조각 {pr.small_pieces} | "
                        f"조각환산 {pr.piece_tiles_equiv} | 총 {pr.total_tiles}"
                    )
            except ValueError:
                pass

    with tab2:
        cols = st.columns(2)
        if has_split:
            # 세면부
            if sink_dims:
                try:
                    fr = compute_rect_tiles(sink_dims[0], sink_dims[1], floor_tile_h, floor_tile_w, "세면부", floor_tile_name)
                    title = f"세면부 {sink_dims[0]}x{sink_dims[1]}mm  (tile {floor_tile_h}x{floor_tile_w})"
                    im = draw_grid_rect(title, L=sink_dims[0], W=sink_dims[1], tile_h=floor_tile_h, tile_w=floor_tile_w, scale=floor_scale)
                    with cols[0]:
                        st.image(im, use_container_width=False)
                        st.caption(f"[세면부] 온타일 {fr.full_tiles} | 큰조각 {fr.large_pieces} | 작은조각 {fr.small_pieces} | 총 {fr.total_tiles}")
                except ValueError:
                    pass
            # 샤워부
            if shower_dims:
                try:
                    fr = compute_rect_tiles(shower_dims[0], shower_dims[1], floor_tile_h, floor_tile_w, "샤워부", floor_tile_name)
                    title = f"샤워부 {shower_dims[0]}x{shower_dims[1]}mm  (tile {floor_tile_h}x{floor_tile_w})"
                    im = draw_grid_rect(title, L=shower_dims[0], W=shower_dims[1], tile_h=floor_tile_h, tile_w=floor_tile_w, scale=floor_scale)
                    with cols[1]:
                        st.image(im, use_container_width=False)
                        st.caption(f"[샤워부] 온타일 {fr.full_tiles} | 큰조각 {fr.large_pieces} | 작은조각 {fr.small_pieces} | 총 {fr.total_tiles}")
                except ValueError:
                    pass
        else:
            # 바닥 전체
            if sink_dims:
                try:
                    fr = compute_rect_tiles(sink_dims[0], sink_dims[1], floor_tile_h, floor_tile_w, "바닥", floor_tile_name)
                    title = f"바닥 {sink_dims[0]}x{sink_dims[1]}mm  (tile {floor_tile_h}x{floor_tile_w})"
                    im = draw_grid_rect(title, L=sink_dims[0], W=sink_dims[1], tile_h=floor_tile_h, tile_w=floor_tile_w, scale=floor_scale)
                    with cols[0]:
                        st.image(im, use_container_width=False)
                        st.caption(f"[바닥] 온타일 {fr.full_tiles} | 큰조각 {fr.large_pieces} | 작은조각 {fr.small_pieces} | 총 {fr.total_tiles}")
                except ValueError:
                    pass
