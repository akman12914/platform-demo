# tile.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw


# =========================================================
# Data models (WALL)
# =========================================================
@dataclass
class Panel:
    idx: int
    W: int  # mm
    H: int  # mm


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


# =========================================================
# Data models (FLOOR)
# =========================================================
@dataclass
class FloorPlan:
    idx: int
    has_split: bool  # True: sink+shower, False: single area
    # sink area
    sink_L: int
    sink_W: int
    # shower area (optional)
    shower_L: int = 0
    shower_W: int = 0


@dataclass
class FloorAreaResult:
    area_name: str  # "SINK" / "SHOWER" / "FLOOR"
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
class FloorPlanResult:
    idx: int
    has_split: bool
    tile: str
    tile_w: int
    tile_h: int
    # totals
    full_total: int
    large_total: int
    small_total: int
    piece_equiv_total: int
    total_tiles: int
    # per-area
    areas: List[FloorAreaResult]


# =========================================================
# Shared math (tile filling on rectangle)
# =========================================================
def classify_piece_area(piece_area: int, tile_area: int) -> str:
    # "Large" if strictly greater than half
    return "L" if piece_area > (tile_area / 2) else "S"


def compute_rect_tiles(L: int, W: int, tile_h: int, tile_w: int, area_name: str, tile_name: str) -> FloorAreaResult:
    """
    Rectangle fill with top->bottom, left->right grid.
    NOTE: we keep the SAME leftover model as wall:
      - right strip: r_w x tile_h repeated n_h
      - bottom strip: tile_w x r_h repeated n_w
      - bottom-right corner: r_w x r_h
    Here we treat:
      horizontal axis = "W" (width), vertical axis = "L" (length)
    so:
      n_w = W // tile_w, r_w = W % tile_w
      n_h = L // tile_h, r_h = L % tile_h
    """
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

    # right strip pieces
    if r_w > 0 and n_h > 0:
        a_r = tile_h * r_w
        if classify_piece_area(a_r, tile_area) == "L":
            large_pieces += n_h
        else:
            small_pieces += n_h

    # bottom strip pieces
    if r_h > 0 and n_w > 0:
        a_b = r_h * tile_w
        if classify_piece_area(a_b, tile_area) == "L":
            large_pieces += n_w
        else:
            small_pieces += n_w

    # corner
    if r_w > 0 and r_h > 0:
        a_c = r_w * r_h
        if classify_piece_area(a_c, tile_area) == "L":
            large_pieces += 1
        else:
            small_pieces += 1

    piece_tiles_equiv = large_pieces + math.ceil(small_pieces / 2)
    total_tiles = full_tiles + piece_tiles_equiv

    return FloorAreaResult(
        area_name=area_name,
        L=L, W=W,
        tile=tile_name,
        tile_w=tile_w, tile_h=tile_h,
        n_w=n_w, n_h=n_h,
        r_w=r_w, r_h=r_h,
        full_tiles=full_tiles,
        large_pieces=large_pieces,
        small_pieces=small_pieces,
        piece_tiles_equiv=piece_tiles_equiv,
        total_tiles=total_tiles
    )


# =========================================================
# WALL math
# =========================================================
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
        idx=-1,
        W=W, H=H,
        tile_w=tile_w, tile_h=tile_h,
        n_w=n_w, n_h=n_h,
        r_w=r_w, r_h=r_h,
        full_tiles=full_tiles,
        large_pieces=large_pieces,
        small_pieces=small_pieces,
        piece_tiles_equiv=piece_tiles_equiv,
        total_tiles=total_tiles
    )


# =========================================================
# Drawing (generic grid)
# =========================================================
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

    d.text((pad, 4), title, fill=(0, 0, 0))
    return im


# =========================================================
# Random generators
# =========================================================
def generate_wall_panels(n: int, seed_value: int) -> List[Panel]:
    rng = random.Random(int(seed_value))
    return [Panel(idx=i, W=rng.randint(81, 2400), H=rng.randint(81, 2400)) for i in range(1, n + 1)]


def generate_floor_plans(n: int, seed_value: int, split_ratio: float = 0.6) -> List[FloorPlan]:
    """
    Random floor plans:
      - with probability split_ratio => has_split True (sink+shower)
      - else => single area (no split)
    All dims 81..2400 (as requested).
    """
    rng = random.Random(int(seed_value) + 777)
    plans: List[FloorPlan] = []
    for i in range(1, n + 1):
        has_split = (rng.random() < split_ratio)

        if not has_split:
            L = rng.randint(81, 2400)
            W = rng.randint(81, 2400)
            plans.append(FloorPlan(idx=i, has_split=False, sink_L=L, sink_W=W))
        else:
            sink_L = rng.randint(81, 2400)
            sink_W = rng.randint(81, 2400)
            shower_L = rng.randint(81, 2400)
            shower_W = rng.randint(81, 2400)
            plans.append(FloorPlan(idx=i, has_split=True, sink_L=sink_L, sink_W=sink_W, shower_L=shower_L, shower_W=shower_W))
    return plans


# =========================================================
# Streamlit UI
# =========================================================
st.set_page_config(page_title="벽/바닥 타일 개수 테스트", layout="wide")
st.title("벽판넬 + 바닥판 타일 개수 계산 테스트 (격자 시각화 포함)")

with st.sidebar:
    st.header("공통 설정")

    wall_tile_type = st.selectbox("벽타일 종류", ["300x600", "250x400", "600x300"], index=0)
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

    N = st.slider("샘플 개수 N", min_value=10, max_value=20, value=12, step=1)
    seed = st.number_input("랜덤 시드(seed)", min_value=0, max_value=10_000_000, value=42, step=1)

    st.header("바닥판 생성 옵션")
    split_ratio = st.slider("세면/샤워 구분 비율", 0.0, 1.0, 0.6, 0.05)
    regen = st.button("임의 데이터 생성/재생성", use_container_width=True)


# ---- session state init / regen
if "wall_panels" not in st.session_state or "floor_plans" not in st.session_state:
    st.session_state.wall_panels = generate_wall_panels(N, seed)
    st.session_state.floor_plans = generate_floor_plans(N, seed, split_ratio)

if regen or len(st.session_state.wall_panels) != N or len(st.session_state.floor_plans) != N:
    st.session_state.wall_panels = generate_wall_panels(N, seed)
    st.session_state.floor_plans = generate_floor_plans(N, seed, split_ratio)

wall_panels: List[Panel] = st.session_state.wall_panels
floor_plans: List[FloorPlan] = st.session_state.floor_plans

# =========================================================
# WALL: compute + table
# =========================================================
wall_results: List[PanelResult] = []
for p in wall_panels:
    rr = compute_wall_panel(p.W, p.H, tile_h=wall_tile_h, tile_w=wall_tile_w)
    rr.idx = p.idx
    wall_results.append(rr)

wall_df = pd.DataFrame([{
    "idx": r.idx,
    "W(mm)": r.W,
    "H(mm)": r.H,
    "온타일(F)": r.full_tiles,
    "큰조각(L)": r.large_pieces,
    "작은조각(S)": r.small_pieces,
    "조각환산": r.piece_tiles_equiv,
    "총 타일": r.total_tiles,
} for r in wall_results])

wall_full_total = int(wall_df["온타일(F)"].sum())
wall_L_total = int(wall_df["큰조각(L)"].sum())
wall_S_total = int(wall_df["작은조각(S)"].sum())
wall_piece_equiv = wall_L_total + math.ceil(wall_S_total / 2)
wall_total_tiles = wall_full_total + wall_piece_equiv

# =========================================================
# FLOOR: compute + table
# =========================================================
floor_results: List[FloorPlanResult] = []
for fp in floor_plans:
    areas: List[FloorAreaResult] = []
    if not fp.has_split:
        areas.append(compute_rect_tiles(fp.sink_L, fp.sink_W, floor_tile_h, floor_tile_w, "FLOOR", floor_tile_name))
    else:
        areas.append(compute_rect_tiles(fp.sink_L, fp.sink_W, floor_tile_h, floor_tile_w, "SINK", floor_tile_name))
        areas.append(compute_rect_tiles(fp.shower_L, fp.shower_W, floor_tile_h, floor_tile_w, "SHOWER", floor_tile_name))

    full_total = sum(a.full_tiles for a in areas)
    large_total = sum(a.large_pieces for a in areas)
    small_total = sum(a.small_pieces for a in areas)
    piece_equiv_total = large_total + math.ceil(small_total / 2)
    total_tiles = full_total + piece_equiv_total

    floor_results.append(FloorPlanResult(
        idx=fp.idx,
        has_split=fp.has_split,
        tile=floor_tile_name,
        tile_w=floor_tile_w,
        tile_h=floor_tile_h,
        full_total=full_total,
        large_total=large_total,
        small_total=small_total,
        piece_equiv_total=piece_equiv_total,
        total_tiles=total_tiles,
        areas=areas
    ))

floor_df = pd.DataFrame([{
    "idx": fr.idx,
    "구분": "세면+샤워" if fr.has_split else "구분없음",
    "바닥타일": fr.tile,
    "온타일(F)": fr.full_total,
    "큰조각(L)": fr.large_total,
    "작은조각(S)": fr.small_total,
    "조각환산": fr.piece_equiv_total,
    "총 타일": fr.total_tiles,
} for fr in floor_results])

floor_full_total = int(floor_df["온타일(F)"].sum())
floor_L_total = int(floor_df["큰조각(L)"].sum())
floor_S_total = int(floor_df["작은조각(S)"].sum())
floor_piece_equiv = floor_L_total + math.ceil(floor_S_total / 2)
floor_total_tiles = floor_full_total + floor_piece_equiv

# =========================================================
# Display summaries
# =========================================================
st.subheader("요약")
c1, c2, c3, c4 = st.columns(4)
c1.metric("벽타일 총(최소)", f"{wall_total_tiles:,} 장")
c2.metric("벽 온타일", f"{wall_full_total:,} 장")
c3.metric("바닥타일 총(최소)", f"{floor_total_tiles:,} 장")
c4.metric("바닥 온타일", f"{floor_full_total:,} 장")

st.caption(f"벽타일 {wall_tile_type} → 바닥타일 {floor_tile_name} (자동 매핑)")

st.divider()

# =========================================================
# Tables
# =========================================================
st.subheader("벽판 결과표")
st.dataframe(wall_df, use_container_width=True, height=260)

st.subheader("바닥판 결과표")
st.dataframe(floor_df, use_container_width=True, height=260)

st.divider()

# =========================================================
# Drawings: global scales (keep relative size consistent)
# =========================================================
# WALL scale
max_wall_W = max(p.W for p in wall_panels)
max_wall_H = max(p.H for p in wall_panels)
wall_scale = 800 / max(max_wall_W, max_wall_H)

# FLOOR scale
# For floor, consider max among all areas (sink/shower)
max_floor_L = 1
max_floor_W = 1
for fp in floor_plans:
    if fp.has_split:
        max_floor_L = max(max_floor_L, fp.sink_L, fp.shower_L)
        max_floor_W = max(max_floor_W, fp.sink_W, fp.shower_W)
    else:
        max_floor_L = max(max_floor_L, fp.sink_L)
        max_floor_W = max(max_floor_W, fp.sink_W)
floor_scale = 800 / max(max_floor_L, max_floor_W)

st.subheader("격자 시각화")

tab1, tab2 = st.tabs(["벽판(벽타일)", "바닥판(바닥타일)"])

with tab1:
    cols = st.columns(2)
    for i, (p, r) in enumerate(zip(wall_panels, wall_results), start=1):
        title = f"#{p.idx}  {p.W}x{p.H}mm  (tile {wall_tile_h}x{wall_tile_w})"
        im = draw_grid_rect(title, L=p.H, W=p.W, tile_h=wall_tile_h, tile_w=wall_tile_w, scale=wall_scale)
        left = cols[0] if (i % 2 == 1) else cols[1]
        with left:
            st.image(im, use_container_width=False)
            st.caption(
                f"온타일 {r.full_tiles} | 큰조각 {r.large_pieces} | 작은조각 {r.small_pieces} | "
                f"조각환산 {r.piece_tiles_equiv} | 총 {r.total_tiles}"
            )

with tab2:
    cols = st.columns(2)
    for i, (fp, fr) in enumerate(zip(floor_plans, floor_results), start=1):
        left = cols[0] if (i % 2 == 1) else cols[1]
        with left:
            if not fp.has_split:
                a = fr.areas[0]
                title = f"#{fp.idx}  FLOOR {a.L}x{a.W}mm  (tile {a.tile_h}x{a.tile_w})"
                im = draw_grid_rect(title, L=a.L, W=a.W, tile_h=a.tile_h, tile_w=a.tile_w, scale=floor_scale)
                st.image(im, use_container_width=False)
                st.caption(f"[FLOOR] 온타일 {a.full_tiles} | 큰조각 {a.large_pieces} | 작은조각 {a.small_pieces} | 총 {a.total_tiles}")
            else:
                a1 = fr.areas[0]
                a2 = fr.areas[1]

                title1 = f"#{fp.idx}  SINK {a1.L}x{a1.W}mm  (tile {a1.tile_h}x{a1.tile_w})"
                im1 = draw_grid_rect(title1, L=a1.L, W=a1.W, tile_h=a1.tile_h, tile_w=a1.tile_w, scale=floor_scale)

                title2 = f"#{fp.idx}  SHOWER {a2.L}x{a2.W}mm  (tile {a2.tile_h}x{a2.tile_w})"
                im2 = draw_grid_rect(title2, L=a2.L, W=a2.W, tile_h=a2.tile_h, tile_w=a2.tile_w, scale=floor_scale)

                st.image(im1, use_container_width=False)
                st.caption(f"[SINK] 온타일 {a1.full_tiles} | 큰조각 {a1.large_pieces} | 작은조각 {a1.small_pieces} | 총 {a1.total_tiles}")

                st.image(im2, use_container_width=False)
                st.caption(f"[SHOWER] 온타일 {a2.full_tiles} | 큰조각 {a2.large_pieces} | 작은조각 {a2.small_pieces} | 총 {a2.total_tiles}")

            st.caption(
                f"바닥 합계: 온타일 {fr.full_total} | 큰조각 {fr.large_total} | 작은조각 {fr.small_total} | "
                f"조각환산 {fr.piece_equiv_total} | 총 {fr.total_tiles}"
            )
