# wall_panel_cost_final.py
# -*- coding: utf-8 -*-
# 벽판 원가 계산 (Step 3 of 3)
# 바닥판 → 벽판 규격 → 타일 개수 → 벽판 원가

from __future__ import annotations
import io
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

import pandas as pd
import streamlit as st

# --- Common Styles ---
from common_styles import apply_common_styles, set_page_config
from common_sidebar import render_chatbot_sidebar

# --- Authentication ---
import auth

# =========================================
# Page Configuration
# =========================================
set_page_config(page_title="벽판 원가 계산", layout="wide")
apply_common_styles()
auth.require_auth()

# 사이드바에 시방서 분석 결과 표시
render_chatbot_sidebar()

# =========================================
# Session State Keys (공유 데이터)
# =========================================
# 바닥판에서 받아오는 키
FLOOR_DONE_KEY = "floor_done"
SHARED_EXCEL_KEY = "shared_excel_file"
SHARED_EXCEL_NAME_KEY = "shared_excel_filename"
SHARED_BATH_SHAPE_KEY = "shared_bath_shape"

# 벽판 규격에서 받아오는 키
WALL_SPEC_DONE_KEY = "wall_spec_done"
SHARED_WALL_PANELS_KEY = "shared_wall_panels"  # [(W,H), ...] 벽판 치수 리스트
SHARED_WALL_HEIGHT_KEY = "shared_wall_height"  # 벽 높이
SHARED_JENDAI_ENABLED_KEY = "shared_jendai_enabled"
SHARED_JENDAI_STEP_KEY = "shared_jendai_step"  # 단차 여부
SHARED_JENDAI_HEIGHT_KEY = "shared_jendai_height"  # 젠다이 높이 (mm)

# 타일 개수에서 받아오는 키
TILE_CALC_DONE_KEY = "tile_calc_done"
SHARED_AVG_TILES_PER_PANEL_KEY = "shared_avg_tiles_per_panel"  # 패널당 평균 타일 개수

# 벽판 원가 완료 키
WALL_COST_DONE_KEY = "wall_cost_done"
SHARED_WALL_COST_RESULT_KEY = "shared_wall_cost_result"


# =========================================
# 상수 및 원가 계산 로직 (wall_panel_cost.py 기반)
# =========================================
@dataclass
class ExcelConsts:
    frame_unit_price: float        # 원/m
    pu_unit_price: float           # 원/㎡
    clip_unit_price: float         # 원/판넬(1세트)
    equip_depr_unit: float         # 원/판넬
    manuf_overhead_unit: float     # 원/판넬
    tile_mgmt_unit_price: float    # 원/타일(장)
    ship_rack_unit: float          # 원/판넬
    labor_cost_per_day: float      # 원/일
    loss_rate: float = 1.02
    wall_height_default_m: float = 2.3
    prod_qty_le_1_5: int = 325
    prod_qty_1_51_1_89: int = 300
    prod_qty_ge_1_9: int = 275


def _to_num(x) -> float:
    if x is None:
        return float("nan")
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if s == "":
        return float("nan")
    return float(s.replace(",", ""))


def _normalize_two_col_df(df: pd.DataFrame) -> pd.DataFrame:
    cols = [str(c).strip() for c in df.columns]
    if {"variable", "value"}.issubset(set(cols)):
        return df
    if len(cols) < 2:
        raise ValueError("상수 시트('벽판')는 최소 2개 컬럼(변수명/값)이 필요합니다.")
    df2 = df.iloc[:, :2].copy()
    df2.columns = ["variable", "value"]
    return df2


def load_consts_from_sheet(excel_bytes: bytes, angle: int, sheet_name: str = "벽판") -> ExcelConsts:
    raw = pd.read_excel(io.BytesIO(excel_bytes), sheet_name=sheet_name)
    df = _normalize_two_col_df(raw)

    kv: Dict[str, float] = {}
    for _, r in df.iterrows():
        k = str(r["variable"]).strip()
        if not k or k.lower() in {"nan", "none"}:
            continue
        kv[k] = _to_num(r["value"])

    def req(key: str) -> float:
        if key not in kv or pd.isna(kv[key]):
            raise ValueError(f"상수 시트('{sheet_name}')에 필수 변수 '{key}'가 없습니다(또는 값이 비어있음).")
        return float(kv[key])

    def opt(key: str, default: float) -> float:
        v = kv.get(key, default)
        return default if pd.isna(v) else float(v)

    return ExcelConsts(
        frame_unit_price=req(f"프레임단가_{angle}각"),
        pu_unit_price=req(f"P_U단가_{angle}각"),
        clip_unit_price=req("조립클립단가"),
        equip_depr_unit=req("설비감가비"),
        manuf_overhead_unit=req("제조경비_판넬당"),
        tile_mgmt_unit_price=req("타일관리비_단가"),
        ship_rack_unit=req("출고_렉입고_단가"),
        labor_cost_per_day=req("생산인건비_일단가"),
        loss_rate=opt("프레임_LOSS_배수", 1.02),
        wall_height_default_m=opt("벽체높이_기본_m", 2.3),
        prod_qty_le_1_5=int(opt("기준생산량_1_5이하", 325)),
        prod_qty_1_51_1_89=int(opt("기준생산량_1_51_1_89", 300)),
        prod_qty_ge_1_9=int(opt("기준생산량_1_9이상", 275)),
    )


def production_qty_from_avg_area(avg_area_m2: float, consts: ExcelConsts) -> int:
    if avg_area_m2 <= 1.5:
        return consts.prod_qty_le_1_5
    if avg_area_m2 <= 1.89:
        return consts.prod_qty_1_51_1_89
    return consts.prod_qty_ge_1_9


def compute_avg_cost(
    panels: pd.DataFrame,
    consts: ExcelConsts,
    bath_type: str,
    zendae_step: bool,
    zendae_h_mm: float,
    wall_h_mm: float,
    tiles_per_panel: float,
):
    """
    panels: DataFrame with columns ['패널폭(mm)', '패널높이(mm)', '수량']
    """
    df = panels.copy()
    df["패널폭(mm)"] = pd.to_numeric(df["패널폭(mm)"], errors="coerce")
    df["패널높이(mm)"] = pd.to_numeric(df["패널높이(mm)"], errors="coerce")
    df["수량"] = pd.to_numeric(df["수량"], errors="coerce").fillna(0).astype(int)
    df = df.dropna(subset=["패널폭(mm)", "패널높이(mm)"])
    df = df[df["수량"] > 0]
    if df.empty:
        raise ValueError("패널 리스트가 비어있습니다(수량>0).")

    total_panels = int(df["수량"].sum())

    # mm를 m로 변환하여 면적 계산
    df["패널폭(m)"] = df["패널폭(mm)"] / 1000.0
    df["패널높이(m)"] = df["패널높이(mm)"] / 1000.0
    zendae_h_m = zendae_h_mm / 1000.0
    wall_h_m = wall_h_mm / 1000.0

    df["패널면적(㎡)"] = df["패널폭(m)"] * df["패널높이(m)"]
    total_area = float((df["패널면적(㎡)"] * df["수량"]).sum())
    avg_area = total_area / total_panels

    df["패널둘레(m/장)"] = 2.0 * (df["패널폭(m)"] + df["패널높이(m)"])
    base_frame_total = float((df["패널둘레(m/장)"] * df["수량"]).sum())

    if bath_type == "사각형" and (not zendae_step):
        add_len = 0.0
    elif bath_type == "사각형" and zendae_step:
        add_len = 2.0 * zendae_h_m
    elif bath_type == "코너형" and (not zendae_step):
        add_len = wall_h_m
    else:
        add_len = zendae_h_m + wall_h_m

    frame_total = base_frame_total + add_len
    frame_total_loss = frame_total * consts.loss_rate
    avg_frame_len_loss = frame_total_loss / total_panels

    frame_cost = avg_frame_len_loss * consts.frame_unit_price
    pu_cost = avg_area * consts.pu_unit_price
    clip_cost = consts.clip_unit_price
    material_M = frame_cost + pu_cost + clip_cost

    prod_qty = production_qty_from_avg_area(avg_area, consts)
    sets_per_panel = prod_qty / total_panels
    labor_P = consts.labor_cost_per_day / sets_per_panel

    equip_S = consts.equip_depr_unit
    manuf_V = consts.manuf_overhead_unit
    tile_Y = tiles_per_panel * consts.tile_mgmt_unit_price
    ship_AB = consts.ship_rack_unit

    cost_AD = material_M + labor_P + equip_S + manuf_V + tile_Y + ship_AB
    total_set_cost = cost_AD * total_panels

    summary = {
        "총판넬수": float(total_panels),
        "총면적(㎡)": float(total_area),
        "평균면적(㎡/장)": float(avg_area),
        "기본프레임총길이(m)": float(base_frame_total),
        "추가프레임길이(m)": float(add_len),
        "Loss적용프레임총길이(m)": float(frame_total_loss),
        "후레임평균(m/장,Loss)": float(avg_frame_len_loss),
        "생산량(기준)": float(prod_qty),
        "판넬1장당_평균가공세트수": float(sets_per_panel),
        "판넬1장당_생산인건비(P)": float(labor_P),
        "판넬1장당_생산원가계(AD)": float(cost_AD),
        "욕실1세트_생산원가계(AD)": float(total_set_cost),
    }

    breakdown = pd.DataFrame(
        [
            ("재료비(M)-프레임", "원/장", frame_cost, frame_cost * total_panels),
            ("재료비(M)-P/U", "원/장", pu_cost, pu_cost * total_panels),
            ("재료비(M)-조립클립", "원/장", clip_cost, clip_cost * total_panels),
            ("재료비(M) 합계", "원/장", material_M, material_M * total_panels),
            ("생산인건비(P)", "원/장", labor_P, labor_P * total_panels),
            ("설비감가비(S)", "원/장", equip_S, equip_S * total_panels),
            ("제조경비(V)", "원/장", manuf_V, manuf_V * total_panels),
            ("타일관리비(Y)", "원/장", tile_Y, tile_Y * total_panels),
            ("출고·렉입고비(AB)", "원/장", ship_AB, ship_AB * total_panels),
            ("생산원가계(AD)", "원/장", cost_AD, total_set_cost),
        ],
        columns=["항목", "단위", "판넬 1장(평균) 원가", "욕실 1세트(총) 원가"],
    )

    return df, summary, breakdown


def wall_panels_to_dataframe(wall_panels: List[Tuple[int, int]]) -> pd.DataFrame:
    """
    [(W, H), (W, H), ...] 형태의 벽판 리스트를 DataFrame으로 변환
    동일한 (W, H) 조합은 수량으로 집계
    """
    from collections import Counter
    counts = Counter(wall_panels)
    rows = []
    for (w, h), qty in counts.items():
        rows.append({"패널폭(mm)": int(w), "패널높이(mm)": int(h), "수량": qty})
    return pd.DataFrame(rows)


# =========================================
# UI
# =========================================
st.title("벽판 원가 계산")
st.caption("벽판 규격 → 타일 개수 → **벽판 원가** (Step 3/3)")

# --- 이전 단계 완료 여부 확인 ---
floor_done = st.session_state.get(FLOOR_DONE_KEY, False)
wall_spec_done = st.session_state.get(WALL_SPEC_DONE_KEY, False)
tile_calc_done = st.session_state.get(TILE_CALC_DONE_KEY, False)

if not floor_done:
    st.warning("먼저 [1. 바닥판 계산] 페이지에서 바닥판 계산을 완료해주세요.")
    st.stop()

if not wall_spec_done:
    st.warning("먼저 [2. 벽판 규격] 페이지에서 벽판 규격 계산을 완료해주세요.")
    st.stop()

if not tile_calc_done:
    st.warning("먼저 [3. 타일 개수] 페이지에서 타일 개수 계산을 완료해주세요.")
    st.stop()

# --- 세션에서 데이터 로드 ---
wall_panels = st.session_state.get(SHARED_WALL_PANELS_KEY, [])
wall_height = st.session_state.get(SHARED_WALL_HEIGHT_KEY, 2300)
avg_tiles_per_panel = st.session_state.get(SHARED_AVG_TILES_PER_PANEL_KEY, 10.0)
bath_shape = st.session_state.get(SHARED_BATH_SHAPE_KEY, "사각형")
excel_file = st.session_state.get(SHARED_EXCEL_KEY)
excel_name = st.session_state.get(SHARED_EXCEL_NAME_KEY, "")

# UploadedFile을 bytes로 변환
excel_bytes = None
if excel_file is not None:
    try:
        # UploadedFile인 경우 read()로 bytes 변환
        if hasattr(excel_file, 'read'):
            excel_file.seek(0)  # 파일 포인터 초기화
            excel_bytes = excel_file.read()
            excel_file.seek(0)  # 다른 곳에서 재사용 가능하도록 다시 초기화
        elif isinstance(excel_file, bytes):
            excel_bytes = excel_file
    except Exception as e:
        st.error(f"엑셀 파일 읽기 오류: {e}")

if not wall_panels:
    st.error("벽판 데이터가 없습니다. 벽판 규격 페이지에서 계산을 완료해주세요.")
    st.stop()

# 벽판 리스트를 DataFrame으로 변환
panels_df = wall_panels_to_dataframe(wall_panels)

# --- Sidebar ---
with st.sidebar:
    st.header("원가 계산 설정")

    # 엑셀 상수 로드
    st.subheader("상수 엑셀")
    if excel_bytes:
        st.success(f"바닥판에서 업로드된 파일 사용: {excel_name}")
        use_shared_excel = st.checkbox("바닥판 엑셀 사용", value=True)
    else:
        use_shared_excel = False
        st.info("바닥판 엑셀이 없습니다. 별도 업로드하세요.")

    if not use_shared_excel:
        const_uploaded = st.file_uploader(
            "상수 엑셀 업로드(.xlsx) — '벽판' 시트",
            type=["xlsx"],
            key="wall_cost_excel"
        )
        if const_uploaded:
            excel_bytes = const_uploaded.read()

    if not excel_bytes:
        st.warning("상수 엑셀을 업로드하세요.")
        st.stop()

    st.divider()

    # 프레임 각도
    angle = st.radio("프레임 선정", [15, 16, 19], format_func=lambda x: f"{x}각", horizontal=True)

    # 상수 로드
    try:
        consts = load_consts_from_sheet(excel_bytes, angle=int(angle), sheet_name="벽판")
    except Exception as e:
        st.error(f"상수 로딩 실패: {e}")
        st.stop()

    st.divider()

    # 욕실 형태 (바닥판에서 받아온 값 고정 표시)
    st.subheader("욕실형태유형")
    st.text_input("욕실 형태", value=bath_shape, disabled=True)
    bath_type = bath_shape  # 바닥판에서 받아온 값 그대로 사용

    # 젠다이 설정 (벽판 규격에서 받아온 값 고정 표시)
    st.subheader("젠다이 설정")
    saved_jendai_enabled = st.session_state.get(SHARED_JENDAI_ENABLED_KEY, False)
    saved_jendai_step = st.session_state.get(SHARED_JENDAI_STEP_KEY, False)
    saved_jendai_height = st.session_state.get(SHARED_JENDAI_HEIGHT_KEY, 0)

    zendae_step = saved_jendai_step
    zendae_h_mm = float(saved_jendai_height) if saved_jendai_step else 0.0

    st.text_input("젠다이 단차여부", value="있음" if zendae_step else "없음", disabled=True)
    if zendae_step:
        st.text_input("젠다이 높이 (mm)", value=str(int(zendae_h_mm)), disabled=True)

    st.divider()

    # 타일 개수 (타일 계산 페이지에서 자동 로드)
    st.subheader("타일 정보")
    st.info(f"타일 계산 페이지에서 계산된 값: **{avg_tiles_per_panel:.1f}장/패널**")
    tiles_per_panel = st.number_input(
        "벽판 1장당 타일 개수 (수정 가능)",
        min_value=0.0,
        value=float(avg_tiles_per_panel),
        step=0.1,
        format="%.1f",
    )

    st.divider()

    # 고급 설정
    with st.expander("고급 설정"):
        loss_rate = st.number_input(
            "프레임 Loss율(배수)",
            min_value=1.0,
            max_value=1.2,
            value=float(consts.loss_rate),
            step=0.005
        )
        consts.loss_rate = float(loss_rate)

# --- Main Content ---
st.subheader("입력된 벽판 정보")
st.info(f"벽판 규격 페이지에서 계산된 **{len(wall_panels)}장**의 벽판")

# 편집 가능한 데이터 에디터
edited_df = st.data_editor(
    panels_df,
    use_container_width=True,
    num_rows="dynamic",
    column_config={
        "패널폭(mm)": st.column_config.NumberColumn(min_value=100, max_value=2000, step=10, format="%d"),
        "패널높이(mm)": st.column_config.NumberColumn(min_value=100, max_value=3500, step=10, format="%d"),
        "수량": st.column_config.NumberColumn(min_value=1, max_value=999, step=1),
    },
)

# 원가 계산
try:
    clean_df, summary, breakdown = compute_avg_cost(
        panels=edited_df,
        consts=consts,
        bath_type=bath_type,
        zendae_step=zendae_step,
        zendae_h_mm=float(zendae_h_mm),
        wall_h_mm=float(wall_height),
        tiles_per_panel=float(tiles_per_panel),
    )

    # 결과 저장
    st.session_state[WALL_COST_DONE_KEY] = True
    st.session_state[SHARED_WALL_COST_RESULT_KEY] = summary

except Exception as e:
    st.error(f"계산 실패: {e}")
    st.stop()

st.divider()
st.subheader("원가 계산 결과")

# 요약 지표
c1, c2, c3, c4 = st.columns(4)
c1.metric("총 판넬 수", f"{summary['총판넬수']:,.0f}")
c1.metric("총 면적(㎡)", f"{summary['총면적(㎡)']:,.3f}")
c2.metric("평균 면적(㎡/장)", f"{summary['평균면적(㎡/장)']:,.3f}")
c2.metric("후레임 평균(m/장,Loss)", f"{summary['후레임평균(m/장,Loss)']:,.3f}")
c3.metric("생산량(기준)", f"{summary['생산량(기준)']:,.0f}")
c3.metric("판넬 1장당 생산인건비(P)", f"{summary['판넬1장당_생산인건비(P)']:,.0f}")
c4.metric("판넬 1장당 생산원가계(AD)", f"{summary['판넬1장당_생산원가계(AD)']:,.0f}")
c4.metric("욕실 1세트 생산원가계(AD)", f"{summary['욕실1세트_생산원가계(AD)']:,.0f}")

# 프레임 길이 상세
with st.expander("프레임 길이 상세", expanded=False):
    st.write(f"- 기본프레임 총길이(m): **{summary['기본프레임총길이(m)']:,.3f}**")
    st.write(f"- 추가프레임 길이(m): **{summary['추가프레임길이(m)']:,.3f}**")
    st.write(f"- Loss 적용 프레임 총길이(m): **{summary['Loss적용프레임총길이(m)']:,.3f}**")
    st.caption("※ 평균 프레임 길이(장당)는 (Loss적용프레임총길이 / 총판넬수) 입니다.")

# 원가 구성표
st.subheader("원가 구성(평균 1장 vs 욕실 1세트)")
st.dataframe(
    breakdown,
    use_container_width=True,
    height=420,
    column_config={
        "판넬 1장(평균) 원가": st.column_config.NumberColumn(format="%.0f"),
        "욕실 1세트(총) 원가": st.column_config.NumberColumn(format="%.0f"),
    },
)

# 입력 패널 리스트
with st.expander("입력 패널(정리된 리스트)"):
    st.dataframe(clean_df, use_container_width=True, height=320)

# 완료 메시지
st.success("벽판 원가 계산이 완료되었습니다. 견적서 생성 페이지에서 결과를 확인하세요.")

# =========================================
# 계산 과정 상세 (테스트 UI)
# =========================================
st.divider()
with st.expander("🔍 계산 과정 상세 보기 (테스트)", expanded=False):
    st.markdown("### 1. 입력값 확인")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**기본 정보**")
        st.write(f"- 욕실 형태: `{bath_type}`")
        st.write(f"- 프레임 각도: `{angle}각`")
        st.write(f"- 젠다이 단차: `{'있음' if zendae_step else '없음'}`")
        if zendae_step:
            st.write(f"- 젠다이 높이: `{zendae_h_mm}mm`")
        st.write(f"- 벽 높이: `{wall_height}mm`")
    with col2:
        st.markdown("**패널 정보**")
        st.write(f"- 총 패널 수: `{summary['총판넬수']:.0f}장`")
        st.write(f"- 총 면적: `{summary['총면적(㎡)']:.4f}㎡`")
        st.write(f"- 평균 면적: `{summary['평균면적(㎡/장)']:.4f}㎡/장`")
        st.write(f"- 타일 개수/패널: `{tiles_per_panel:.1f}장`")
    with col3:
        st.markdown("**엑셀 상수**")
        st.write(f"- 프레임단가({angle}각): `{consts.frame_unit_price:,.0f}원/m`")
        st.write(f"- P/U단가({angle}각): `{consts.pu_unit_price:,.0f}원/㎡`")
        st.write(f"- 조립클립단가: `{consts.clip_unit_price:,.0f}원/세트`")
        st.write(f"- Loss율: `{consts.loss_rate:.3f}`")

    st.markdown("---")
    st.markdown("### 2. 프레임 길이 계산")

    st.markdown("**Step 2-1: 기본 프레임 총길이**")
    st.code(f"""
각 패널의 둘레 = 2 × (패널폭 + 패널높이)
기본프레임 총길이 = Σ(패널둘레 × 수량)
                 = {summary['기본프레임총길이(m)']:.4f} m
""")

    st.markdown("**Step 2-2: 추가 프레임 길이 (욕실형태/젠다이에 따라)**")
    if bath_type == "사각형" and not zendae_step:
        add_formula = "사각형 + 젠다이 없음 → 추가 길이 = 0"
    elif bath_type == "사각형" and zendae_step:
        add_formula = f"사각형 + 젠다이 있음 → 추가 길이 = 2 × 젠다이높이 = 2 × {zendae_h_mm/1000:.3f}m"
    elif bath_type == "코너형" and not zendae_step:
        add_formula = f"코너형 + 젠다이 없음 → 추가 길이 = 벽높이 = {wall_height/1000:.3f}m"
    else:
        add_formula = f"코너형 + 젠다이 있음 → 추가 길이 = 젠다이높이 + 벽높이 = {zendae_h_mm/1000:.3f} + {wall_height/1000:.3f}m"

    st.code(f"""
{add_formula}
추가프레임 길이 = {summary['추가프레임길이(m)']:.4f} m
""")

    st.markdown("**Step 2-3: Loss 적용 및 평균 계산**")
    st.code(f"""
프레임 총길이 = 기본프레임 + 추가프레임
             = {summary['기본프레임총길이(m)']:.4f} + {summary['추가프레임길이(m)']:.4f}
             = {summary['기본프레임총길이(m)'] + summary['추가프레임길이(m)']:.4f} m

Loss 적용 프레임 총길이 = 프레임 총길이 × Loss율
                      = {summary['기본프레임총길이(m)'] + summary['추가프레임길이(m)']:.4f} × {consts.loss_rate:.3f}
                      = {summary['Loss적용프레임총길이(m)']:.4f} m

후레임 평균(m/장) = Loss적용 프레임 총길이 / 총 패널수
                 = {summary['Loss적용프레임총길이(m)']:.4f} / {summary['총판넬수']:.0f}
                 = {summary['후레임평균(m/장,Loss)']:.4f} m/장
""")

    st.markdown("---")
    st.markdown("### 3. 재료비(M) 계산")

    frame_cost = summary['후레임평균(m/장,Loss)'] * consts.frame_unit_price
    pu_cost = summary['평균면적(㎡/장)'] * consts.pu_unit_price
    clip_cost = consts.clip_unit_price
    material_M = frame_cost + pu_cost + clip_cost

    st.code(f"""
프레임비 = 후레임평균 × 프레임단가
        = {summary['후레임평균(m/장,Loss)']:.4f} m × {consts.frame_unit_price:,.0f} 원/m
        = {frame_cost:,.0f} 원/장

P/U비 = 평균면적 × P/U단가
      = {summary['평균면적(㎡/장)']:.4f} ㎡ × {consts.pu_unit_price:,.0f} 원/㎡
      = {pu_cost:,.0f} 원/장

조립클립비 = {clip_cost:,.0f} 원/장 (고정)

재료비(M) 합계 = 프레임비 + P/U비 + 조립클립비
              = {frame_cost:,.0f} + {pu_cost:,.0f} + {clip_cost:,.0f}
              = {material_M:,.0f} 원/장
""")

    st.markdown("---")
    st.markdown("### 4. 생산인건비(P) 계산")

    st.code(f"""
평균면적 = {summary['평균면적(㎡/장)']:.4f} ㎡

생산량 기준 (평균면적 기준):
  - ≤ 1.5㎡  → {consts.prod_qty_le_1_5}장/일
  - 1.51~1.89㎡ → {consts.prod_qty_1_51_1_89}장/일
  - ≥ 1.9㎡  → {consts.prod_qty_ge_1_9}장/일

적용 생산량 = {summary['생산량(기준)']:.0f}장/일

판넬 1장당 가공 세트수 = 생산량 / 총판넬수
                      = {summary['생산량(기준)']:.0f} / {summary['총판넬수']:.0f}
                      = {summary['판넬1장당_평균가공세트수']:.4f}

생산인건비(P) = 생산인건비_일단가 / 판넬1장당 가공세트수
             = {consts.labor_cost_per_day:,.0f} / {summary['판넬1장당_평균가공세트수']:.4f}
             = {summary['판넬1장당_생산인건비(P)']:,.0f} 원/장
""")

    st.markdown("---")
    st.markdown("### 5. 기타 비용")

    tile_Y = tiles_per_panel * consts.tile_mgmt_unit_price

    st.code(f"""
설비감가비(S) = {consts.equip_depr_unit:,.0f} 원/장 (고정)
제조경비(V)  = {consts.manuf_overhead_unit:,.0f} 원/장 (고정)

타일관리비(Y) = 타일개수/패널 × 타일관리비 단가
             = {tiles_per_panel:.1f}장 × {consts.tile_mgmt_unit_price:,.0f} 원/장
             = {tile_Y:,.0f} 원/장

출고·렉입고비(AB) = {consts.ship_rack_unit:,.0f} 원/장 (고정)
""")

    st.markdown("---")
    st.markdown("### 6. 최종 원가 계산")

    st.code(f"""
생산원가계(AD) = 재료비(M) + 생산인건비(P) + 설비감가비(S) + 제조경비(V) + 타일관리비(Y) + 출고·렉입고비(AB)
             = {material_M:,.0f} + {summary['판넬1장당_생산인건비(P)']:,.0f} + {consts.equip_depr_unit:,.0f} + {consts.manuf_overhead_unit:,.0f} + {tile_Y:,.0f} + {consts.ship_rack_unit:,.0f}
             = {summary['판넬1장당_생산원가계(AD)']:,.0f} 원/장

욕실 1세트 생산원가계 = 판넬1장당 생산원가계 × 총판넬수
                     = {summary['판넬1장당_생산원가계(AD)']:,.0f} × {summary['총판넬수']:.0f}
                     = {summary['욕실1세트_생산원가계(AD)']:,.0f} 원
""")
