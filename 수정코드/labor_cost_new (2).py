# -*- coding: utf-8 -*-
# labor_cost_new.py
# Streamlit app: 입력조건 기반 시스템욕실 설치 인건비 계산 (엑셀 카탈로그 기반)
# 실행: streamlit run labor_cost_new.py

from __future__ import annotations
import math
import re
from typing import Dict, Any, Tuple, List
import pandas as pd
import streamlit as st

st.set_page_config(page_title="인건비 계산", layout="wide")
st.title("인건비 계산")

# ------------------------------
# Constants & Helpers
# ------------------------------
BUCKETS = ["≤49", "≤99", "≤149", "≤199", "≤299", "≥300"]

# ★ 사이드바에서 조절할 옵션 (기본값)
include_meals = True          # 식대·숙박비 포함 여부
include_oji_extra = True      # 유류비(오지) 추가비 포함 여부

def parse_code_to_area(code: str) -> float:
    """
    예: '1520' → 특정 면적코드에 따라 ㎡ 계산.
    (기존 labor_cost2.py의 로직 그대로 사용)
    """
    if not code:
        return 0.0
    s = str(code).strip()
    # 기존 규칙: 뒤 2자리가 폭, 앞부분이 길이 (예: 1520 → 1500×2000 같은 룰)
    try:
        if len(s) >= 3:
            w_code = int(s[-2:])
            l_code = int(s[:-2])
            w = w_code * 100
            l = l_code * 100
            return (w * l) / 1_000_000
    except ValueError:
        pass
    # fallback: 숫자 그대로 면적으로 해석
    try:
        return float(s)
    except ValueError:
        return 0.0

def get_bucket(units: int) -> str:
    if units <= 49: return "≤49"
    if units <= 99: return "≤99"
    if units <= 149: return "≤149"
    if units <= 199: return "≤199"
    if units <= 299: return "≤299"
    return "≥300"

def fmt_money(v: float) -> str:
    return f"{int(round(v)):,.0f}원"

def area_adjust(material: str, area: float, area_rules: Dict[str, Dict[str, Any]]) -> int:
    """경계 포함. 기준 이하 -30,000, 이상 +30,000, 범위 내 0"""
    rule = area_rules.get(material.upper(), None)
    if not rule:
        return 0
    lo = float(rule["min"])
    hi = float(rule["max"])
    if area < lo:
        return int(rule["delta_below"])
    if area > hi:
        return int(rule["delta_above"])
    return 0

# ------------------------------
# 엑셀 파싱 유틸 (250905_시스템욕실 설치비 내역서 전용)
# ------------------------------

def bucket_label_to_code(label: str) -> str:
    """'1 ~ 49세대 이하', '◎ 코너형 ◎ 49세대 이하' 같은 문자열 → BUCKET 코드로 변환"""
    # 큰 숫자부터 체크
    if "300세대" in label or ("300" in label and "이상" in label):
        return "≥300"
    if "299세대" in label:
        return "≤299"
    if "199세대" in label:
        return "≤199"
    if "149세대" in label:
        return "≤149"
    if "99세대" in label:
        return "≤99"
    if "49세대" in label:
        return "≤49"
    # 다른 형식(1 ~ 49 등)도 허용
    if "1 ~ 49" in label:
        return "≤49"
    if "50 ~ 99" in label:
        return "≤99"
    if "100 ~ 149" in label:
        return "≤149"
    if "150 ~ 199" in label:
        return "≤199"
    if "200 ~ 299" in label:
        return "≤299"
    return label


def _extract_area_range(row: pd.Series) -> Tuple[float, float]:
    """
    한 행 전체 문자열에서 '2.5 ~ 2.9' 같은 패턴을 찾아 면적 하한/상한을 뽑는다.
    예: '◎ 바닥판 면적기준: 2.5 ~ 2.9㎡ 이하'
    """
    text = " ".join(str(x) for x in row if isinstance(x, str))
    m = re.search(r'(\d+(?:\.\d+)?)\s*~\s*(\d+(?:\.\d+)?)', text)
    if m:
        return float(m.group(1)), float(m.group(2))
    return 2.5, 2.9  # fallback


def _extract_area_deltas(text: str) -> Tuple[int, int]:
    """
    '기준면적 이하일때 -30,000원, 이상일때 +30,000원' 같은 문장에서 보정값 추출
    """
    m = re.search(r'이하일때\s*([+-]?\d[\d,]*)원.*이상일때\s*([+-]?\d[\d,]*)원', text)
    if m:
        below = int(m.group(1).replace(",", ""))
        above = int(m.group(2).replace(",", ""))
        return below, above
    return -30000, 30000  # fallback


def _parse_grp_summary_250905(df: pd.DataFrame):
    """
    시트: '설치비 내역_수량(GRP, FRP)'
    → (base_grp, vehicles_tbl, region_names, area_rules_grp, meals_std)
    """
    # 1) 버킷 행 찾기
    bucket_rows: List[int] = []
    for idx, val in df.iloc[:, 0].items():
        s = str(val)
        if "세대" in s and ("이하" in s or "이상" in s):
            bucket_rows.append(idx)

    # 2) 버킷별 Base + 차량/유류비
    buckets, prices, vehicles, fuel = [], [], [], []
    for i in bucket_rows:
        label = str(df.iloc[i, 0])
        bcode = bucket_label_to_code(label)
        buckets.append(bcode)
        prices.append(int(df.iloc[i, 1]))      # 기준단가(세대당)
        vehicles.append(float(df.iloc[i, 10])) # 차량대수
        fuel.append(float(df.iloc[i, 11]))     # 차량당 유류비

    base_grp = pd.DataFrame({"bucket": buckets, "base_price": prices})
    vehicles_tbl = pd.DataFrame({
        "bucket": buckets,
        "vehicles": vehicles,
        "fuel_per_vehicle": fuel,
    })

    # 3) 면적 기준/보정
    lo, hi = _extract_area_range(df.iloc[0])
    below, above = _extract_area_deltas(str(df.iloc[11, 0]))
    area_rules_grp = {
        "min": lo,
        "max": hi,
        "delta_below": below,
        "delta_above": above,
    }

    # 4) 외곽/오지 지역명
    region_names: List[str] = []
    start = None
    for idx, val in df.iloc[:, 0].items():
        s = str(val)
        if "외곽지역" in s:
            # 바로 다음 줄은 '구 분'이라 2줄 뒤부터 실제 지역명이 나옴
            start = idx + 2
            continue
        if start is not None and idx >= start:
            if pd.isna(val):
                break
            region_names.append(str(val).strip())

    # 5) 숙식비 기본값 (첫 버킷 행 기준)
    if bucket_rows:
        i0 = bucket_rows[0]
        crew_count = int(df.iloc[i0, 2])
        meal_unit = int(df.iloc[i0, 3])
        lodging_unit = int(df.iloc[i0, 6])
    else:
        crew_count, meal_unit, lodging_unit = 4, 10000, 25000

    meals_std = {
        "included_in_base": False,   # 기준단가에 숙식비 미포함 가정
        "crew_count": crew_count,
        "meal_unit": meal_unit,
        "lodging_unit": lodging_unit,
        "days": 1,
        "override_toggle": False,
    }

    return base_grp, vehicles_tbl, region_names, area_rules_grp, meals_std


def _parse_ppe_summary_250905(df: pd.DataFrame):
    """
    시트: '설치비 내역_수량(PP,PE)'
    → (base_ppe, area_rules_ppe)
    """
    bucket_rows: List[int] = []
    for idx, val in df.iloc[:, 0].items():
        s = str(val)
        if "세대" in s and ("이하" in s or "이상" in s):
            bucket_rows.append(idx)

    buckets, prices = [], []
    for i in bucket_rows:
        label = str(df.iloc[i, 0])
        buckets.append(bucket_label_to_code(label))
        prices.append(int(df.iloc[i, 1]))

    base_ppe = pd.DataFrame({"bucket": buckets, "base_price": prices})

    lo, hi = _extract_area_range(df.iloc[0])
    below, above = _extract_area_deltas(str(df.iloc[11, 0]))
    area_rules_ppe = {
        "min": lo,
        "max": hi,
        "delta_below": below,
        "delta_above": above,
    }

    return base_ppe, area_rules_ppe


def _make_adjust_default_table() -> pd.DataFrame:
    """
    형상/세대유형 보정 기본값 (엑셀 설명문 기반)
    - 사각형: 코너형 기준 +10,000
    - 주거약자: 코너형 기준 +30,000 (사각형이면 +40,000)
    """
    rows = []
    for mat in ["GRP", "FRP", "PP/PE"]:
        rows.append({"material": mat, "shape": "코너형", "user_type": "일반", "delta": 0})
        rows.append({"material": mat, "shape": "사각형", "user_type": "일반", "delta": 10000})
        rows.append({"material": mat, "shape": "코너형", "user_type": "주거약자", "delta": 30000})
        rows.append({"material": mat, "shape": "사각형", "user_type": "주거약자", "delta": 40000})
    return pd.DataFrame(rows)


def _build_detail_from_250905(df: pd.DataFrame) -> pd.DataFrame:
    """
    '세부 설치비 내역(GRP)', '세부 설치비 내역(PP,PE)' 시트에서
    세부 설치비 카탈로그를 추출해
    컬럼: 품목, 사양, 규격, 기본수량, ≤49, ≤99, ≤149, ≤199, ≤299, ≥300
    형태로 변환.
    """
    # 1) 버킷별 (수량, 단가, 금액) 컬럼 위치 찾기
    bucket_cols: Dict[str, Tuple[int, int, int]] = {}
    for col_idx in range(len(df.columns)):
        h2 = str(df.iloc[4, col_idx])  # '수량' / '단가' / '금액'
        h1 = str(df.iloc[3, col_idx])  # '◎ 코너형 ◎ 49세대 이하' 등
        if h2 == "수량" and "세대" in h1:
            bcode = bucket_label_to_code(h1)
            # (수량컬럼, 단가컬럼, 금액컬럼)
            bucket_cols[bcode] = (col_idx, col_idx + 1, col_idx + 2)

    # 2) 데이터 영역: 품목~기타 항목까지만
    start_row = 5
    stop_row = len(df)
    for i, val in enumerate(df.iloc[:, 0]):
        if isinstance(val, str) and "세트당 단가" in val:
            stop_row = i
            break

    sub = df.iloc[start_row:stop_row].copy()

    # 첫 번째 컬럼(품목) ffill: 바닥판 아래 서브항목들에 '바닥판' 채워 넣기
    sub.iloc[:, 0] = sub.iloc[:, 0].ffill()

    records: List[Dict[str, Any]] = []
    for idx, row in sub.iterrows():
        item = row.iloc[0]
        spec = row.iloc[1]
        spec2 = row.iloc[2]

        s_item = "" if pd.isna(item) else str(item).strip()
        s_spec = "" if pd.isna(spec) else str(spec).strip()
        s_spec2 = "" if pd.isna(spec2) else str(spec2).strip()

        if not s_item and not s_spec:
            continue
        # 합계/헤더류는 제외
        if s_item in ("품목", "합 계") or "합계" in s_item:
            continue

        rec: Dict[str, Any] = {
            "품목": s_item,
            "사양": s_spec,
            "규격": s_spec2,
        }

        # 기본수량: ≤99 버킷의 '수량'을 대표값으로 사용 (없으면 1)
        qty = 1.0
        if "≤99" in bucket_cols:
            qcol = bucket_cols["≤99"][0]
            qval = row.iloc[qcol]
            try:
                q = float(qval)
                if not math.isnan(q) and q > 0:
                    qty = q
            except (TypeError, ValueError):
                pass
        rec["기본수량"] = qty

        # 각 버킷별 단가(= 엑셀의 '단가' 컬럼 값)
        for b in BUCKETS:
            if b in bucket_cols:
                ucol = bucket_cols[b][1]
                val = row.iloc[ucol]
                try:
                    rec[b] = float(val) if not pd.isna(val) else 0.0
                except (TypeError, ValueError):
                    rec[b] = 0.0
            else:
                rec[b] = 0.0

        records.append(rec)

    return pd.DataFrame(records)


def load_tables_from_excel(file) -> tuple:
    """
    250905_시스템욕실 설치비 내역서.xlsx 형식 파싱
    반환: (base_grp, base_ppe, adjust, area_rules, vehicles, oji_tbl, meals_std, detail_catalogs)
    """
    xls = pd.ExcelFile(file)
    sheet_names = xls.sheet_names

    # 250905 전용 포맷
    if "설치비 내역_수량(GRP, FRP)" in sheet_names:
        # 1) GRP/FRP 요약
        grp_summary = pd.read_excel(xls, "설치비 내역_수량(GRP, FRP)", header=None)
        base_grp, vehicles_tbl, region_names, area_rules_grp, meals_std = _parse_grp_summary_250905(grp_summary)

        # 2) PP/PE 요약
        ppe_summary = pd.read_excel(xls, "설치비 내역_수량(PP,PE)", header=None)
        base_ppe, area_rules_ppe = _parse_ppe_summary_250905(ppe_summary)

        # 3) 면적 보정 규칙 통합
        area_rules = {
            "GRP": area_rules_grp,
            "FRP": area_rules_grp,   # FRP는 GRP와 동일 취급
            "PP/PE": area_rules_ppe,
        }

        # 4) 외곽/오지 지역 테이블
        oji_tbl = pd.DataFrame({"region": region_names})

        # 5) 형상/세대유형 보정 (엑셀 설명문 기준 기본값)
        adjust_tbl = _make_adjust_default_table()

        # 6) 세부 설치비 카탈로그
        detail_grp = _build_detail_from_250905(pd.read_excel(xls, "세부 설치비 내역(GRP)"))
        detail_ppe = _build_detail_from_250905(pd.read_excel(xls, "세부 설치비 내역(PP,PE)"))
        detail_catalogs = {"GRP": detail_grp, "PP/PE": detail_ppe}

        return (
            base_grp,
            base_ppe,
            adjust_tbl,
            area_rules,
            vehicles_tbl,
            oji_tbl,
            meals_std,
            detail_catalogs,
        )
    else:
        raise ValueError("지원하지 않는 엑셀 포맷입니다. 250905_시스템욕실 설치비 내역서 형식인지 확인하세요.")


def make_empty_tables() -> tuple:
    """엑셀을 아직 업로드하지 않았을 때 사용할 빈 기본 구조."""
    empty_base = pd.DataFrame({"bucket": BUCKETS, "base_price": [0]*len(BUCKETS)})
    empty_adjust = pd.DataFrame(columns=["material","shape","user_type","delta"])
    empty_vehicles = pd.DataFrame({
        "bucket": BUCKETS,
        "vehicles": [0]*len(BUCKETS),
        "fuel_per_vehicle": [0]*len(BUCKETS),
    })
    empty_oji = pd.DataFrame({"region": []})
    empty_area_rules: Dict[str, Dict[str, Any]] = {}
    empty_meals = {
        "included_in_base": False,
        "crew_count": 0,
        "meal_unit": 0,
        "lodging_unit": 0,
        "days": 0,
        "override_toggle": False,
    }
    empty_detail_catalogs = {"GRP": pd.DataFrame(), "PP/PE": pd.DataFrame()}
    return (
        empty_base,
        empty_base.copy(),
        empty_adjust,
        empty_area_rules,
        empty_vehicles,
        empty_oji,
        empty_meals,
        empty_detail_catalogs,
    )

# 세션 기본값 초기화
if "tables" not in st.session_state:
    st.session_state.tables = make_empty_tables()
if "config_loaded" not in st.session_state:
    st.session_state.config_loaded = False
if "config_filename" not in st.session_state:
    st.session_state.config_filename = None

# 세션에 저장된 테이블 언팩
(base_grp, base_ppe, adjust_tbl, area_rules,
 vehicles_tbl, oji_tbl, meals_std, detail_catalogs) = st.session_state.tables

# ------------------------------
# 계산용 함수들 (Base/보정/세부설치비)
# ------------------------------
def pick_base(material: str, bucket: str) -> Tuple[int, str]:
    """2025 세부표(Base)만 사용."""
    mat = material.upper()
    if mat in ["GRP", "FRP"]:
        df = base_grp
    else:
        df = base_ppe

    row = df.loc[df["bucket"] == bucket]
    if row.empty:
        return 0, "해당 버킷 Base 없음"
    base = int(row["base_price"].iloc[0])
    return base, f"{mat} / {bucket} Base"

def shape_adjust(material: str, shape: str, user_type: str, adjust_tbl: pd.DataFrame) -> int:
    mat = material.upper()
    row = adjust_tbl[
        (adjust_tbl["material"].str.upper()==mat) &
        (adjust_tbl["shape"]==shape) &
        (adjust_tbl["user_type"]==user_type)
    ]
    if row.empty:
        return 0
    return int(row["delta"].iloc[0])

def fuel_surcharge(bucket: str, vehicles_tbl: pd.DataFrame) -> int:
    row = vehicles_tbl.loc[vehicles_tbl["bucket"]==bucket]
    if row.empty:
        return 0
    v = float(row["vehicles"].iloc[0])
    cost = float(row["fuel_per_vehicle"].iloc[0])
    return int(v * cost)

def meals_amount(meals_std: Dict[str, Any]) -> int:
    """
    세대당 숙식비.
    crew * (식대 + 숙박비) * 세대당 일수
    """
    crew = int(meals_std.get("crew_count", 0))
    meal = int(meals_std.get("meal_unit", 0))
    lodge = int(meals_std.get("lodging_unit", 0))
    days = int(meals_std.get("days", 0))
    return int(crew * (meal + lodge) * days)

def detail_cost(material: str, bucket: str, detail_catalogs: Dict[str, pd.DataFrame]) -> Tuple[int, List[str]]:
    logs: List[str] = []
    mat = material.upper()
    cat_key = "PP/PE" if mat=="PP/PE" else "GRP"
    df = detail_catalogs.get(cat_key, pd.DataFrame()).copy()
    if df.empty:
        return 0, ["세부설치비 카탈로그 없음"]

    if "적용" not in df.columns:
        df["적용"] = True
    # bucket 별 단가 컬럼에서 금액 가져오기
    if bucket not in df.columns:
        return 0, [f"카탈로그에 {bucket} 버킷 단가 컬럼이 없습니다."]

    use = df[df["적용"]==True].copy()
    if use.empty:
        return 0, ["적용된 세부설치비 항목 없음"]

    use["단가"] = use[bucket].fillna(0)
    use["수량"] = use.get("기본수량", 1)
    use["금액"] = (use["단가"] * use["수량"]).round()
    subtotal = int(use["금액"].sum())
    logs.append(f"세부설치비(선택 합계): {fmt_money(subtotal)}")
    # 모든 항목 로그 출력
    for r in use[["품목","사양","규격","수량","단가","금액"]].to_dict(orient="records"):
        q = int(r["수량"]) if float(r["수량"]).is_integer() else r["수량"]
        logs.append(f"  - {r['품목']} / {r['사양']} / {r.get('규격','')}: {q} × {fmt_money(r['단가'])} = {fmt_money(r['금액'])}")
    return subtotal, logs

def compute():
    """
    세대당 인건비와 로그, breakdown 반환.
    - 기준설치비 = Base + 형상/세대/재질 보정 + 면적 보정
    - 숙식비(세대당) 별도 가산
    - (오지일 경우) 유류비 별도 가산
    - 세부설치비(세대당)는 '참고용'만 표시, 계산에는 미포함
    """
    logs: List[str] = []

    # 1) 기준설치비 구성
    base, base_note = pick_base(material, bucket)
    logs.append(f"Base 선택: {base_note} → {fmt_money(base)}")

    delta_shape = shape_adjust(material, shape, user_type, adjust_tbl)
    logs.append(f"형상/세대/재질 보정: {material}, {shape}, {user_type} → {fmt_money(delta_shape)}")

    d_area = area_adjust(material, area, area_rules)
    logs.append(f"면적 보정: 면적={area:.2f}㎡ → {fmt_money(d_area)}")

    base_install = base + delta_shape + d_area
    logs.append(f"기준설치비 합계(세대당): {fmt_money(base_install)}")

    # 2) 숙식비 (기준단가에 포함되지 않음 → 항상 추가)
    meals_info = meals_amount(meals_std)
    logs.append(
        f"숙식비(세대당): crew={meals_std.get('crew_count',0)}, "
        f"식대={fmt_money(meals_std.get('meal_unit',0))}, "
        f"숙박={fmt_money(meals_std.get('lodging_unit',0))}, "
        f"일수={meals_std.get('days',0)} → {fmt_money(meals_info)}"
    )

    subtotal = base_install + meals_info
    logs.append(f"기준단가 합계(세대당, 유류비 제외): {fmt_money(subtotal)}")

    # 3) 제주 예외 처리
    fuel = 0
    if region == "제주":
        logs.append("제주: 별도 산정 (자동 계산 중단)")
        breakdown = {
            "base_raw": base,
            "shape_adj": delta_shape,
            "area_adj": d_area,
            "base_install": base_install,
            "meals": meals_info,
            "subtotal_ex_fuel": subtotal,
            "fuel": 0,
            "detail_per_unit": 0,
            "final": None,
        }
        return None, logs, breakdown

    # 4) 외곽/오지 유류비
    if is_oji:
        fuel = fuel_surcharge(bucket, vehicles_tbl)
        logs.append(f"유류비 추가비(세대당): 버킷={bucket} → {fmt_money(fuel)}")
    else:
        logs.append("유류비 추가비: 미적용 (외곽/오지 아님)")

    # 5) 세부 설치비 (프로젝트 전체 → 세대당 환산) - 참고용만, 계산에는 미포함
    d_detail, dlogs = detail_cost(material, bucket, detail_catalogs)
    logs.extend(dlogs)
    detail_per_unit = d_detail / max(units, 1)
    logs.append(f"세부설치비(세대당 환산, 참고용/계산 미포함): {fmt_money(detail_per_unit)}")

    # ⚠ 최종 인건비 계산에서 세부설치비는 제외
    final_price = subtotal + fuel

    logs.append(f"최종 세대당 인건비(세부설치비 미포함): {fmt_money(final_price)}")

    breakdown = {
        "base_raw": base,
        "shape_adj": delta_shape,
        "area_adj": d_area,
        "base_install": base_install,
        "meals": meals_info,
        "subtotal_ex_fuel": subtotal,
        "fuel": fuel,
        "detail_per_unit": detail_per_unit,  # 참고용
        "final": final_price,
    }

    return int(round(final_price)), logs, breakdown

# ------------------------------
# Sidebar: 입력조건
# ------------------------------
with st.sidebar:
    st.header("설치비 설정 엑셀")
    cfg_file = st.file_uploader("labor_cost_defaults.xlsx 업로드", type=["xlsx","xls"])
    if cfg_file is not None:
        try:
            tables = load_tables_from_excel(cfg_file)
            (base_grp, base_ppe, adjust_tbl, area_rules,
             vehicles_tbl, oji_tbl, meals_std, detail_catalogs) = tables
            st.session_state.tables = tables
            st.session_state.config_loaded = True
            st.session_state.config_filename = cfg_file.name
            st.success(f"엑셀 설정 로드 완료: {cfg_file.name}")
        except Exception as e:
            st.error(f"엑셀 설정 파일을 불러오지 못했습니다: {e}")
    else:
        if not st.session_state.get("config_loaded", False):
            st.warning("먼저 설치비 설정 엑셀 파일을 업로드하세요.")
        else:
            st.info(f"사용 중인 설정 파일: {st.session_state.get('config_filename')}")

    st.markdown("---")
    st.header("입력조건")
    units = st.number_input("세대수 (프로젝트 전체)", min_value=1, step=1, value=49)
    material = st.selectbox("재질", ["GRP", "FRP", "PP/PE"], index=0)
    shape = st.selectbox("형상", ["코너형", "사각형"], index=0)
    user_type = st.selectbox("세대유형", ["일반", "주거약자"], index=0)
    code = st.text_input("규격 코드 (예: 1520, 1623...)", value="1520")
    area = st.number_input("면적(㎡)", value=float(parse_code_to_area(code)), help="규격코드에서 자동 계산값. 수동 수정 가능.")
    region = st.selectbox("지역", ["수도권", "지방", "제주"], index=0)
    is_oji = st.checkbox("외곽/오지 지역 여부", value=False, help="강화도/고성/통영/거제/남해/고흥/완도/진도/신안 등")

    # ★ 식대·숙박비 포함 여부 (합계(세대) 기준단가)
    include_meals = st.checkbox(
        "식대·숙박비 포함 합계(세대) 기준단가",
        value=True,
        help="체크 시 crew·식대·숙박비·일수를 반영한 숙식비를 세대당 인건비에 포함합니다."
    )

    # ★ 유류비(오지) 추가비 포함 여부
    include_oji_extra = st.checkbox(
        "유류비(오지) 추가비 포함",
        value=True,
        help="체크 시 외곽/오지 차량 유류비를 세대당 인건비에 포함합니다."
    )

    bucket = get_bucket(int(units))

    st.markdown("---")
    st.markdown("**기준단가(Base) 소스: 2025 세부표 사용 (숙식비 미포함)**")

    st.markdown("---")
    if st.button("계산 실행", type="primary", use_container_width=True):
        result, log_lines, breakdown = compute()
        st.session_state["calc_result"] = result
        st.session_state["calc_logs"] = log_lines
        st.session_state["calc_breakdown"] = breakdown
        st.success("계산을 완료했습니다. ⑥ 결과/근거 로그 탭을 확인하세요.")

# ------------------------------
# Main Tabs
# ------------------------------
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "① 버킷별 기준단가", "② 형상/세대/재질 보정", "③ 면적 보정", "④ 외곽/오지·유류비",
    "⑤ 숙식비 설정", "⑥ 결과/근거 로그", "⑦ 세부설치비 선택(카탈로그)"
])

# ------------------------------
# ① 버킷별 기준단가
# ------------------------------
with tab1:
    st.subheader("버킷별 기준단가 (2025)")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**GRP (코너·일반 Base)**")
        base_grp = st.data_editor(
            base_grp, num_rows="fixed", use_container_width=True,
            column_config={
                "bucket": st.column_config.TextColumn("세대수 구간", disabled=True),
                "base_price": st.column_config.NumberColumn("GRP Base", step=10000),
            }
        )
    with c2:
        st.markdown("**PP/PE (코너·일반 Base)**")
        base_ppe = st.data_editor(
            base_ppe, num_rows="fixed", use_container_width=True,
            column_config={
                "bucket": st.column_config.TextColumn("세대수 구간", disabled=True),
                "base_price": st.column_config.NumberColumn("PP/PE Base", step=10000),
            }
        )
    st.session_state.tables = (base_grp, base_ppe, adjust_tbl, area_rules, vehicles_tbl, oji_tbl, meals_std, detail_catalogs)

# ------------------------------
# ② 형상/세대/재질 보정
# ------------------------------
with tab2:
    st.subheader("형상/세대/재질 보정(원)")
    adjust_tbl = st.data_editor(
        adjust_tbl,
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "material": st.column_config.SelectboxColumn(options=["GRP","FRP","PP/PE"]),
            "shape": st.column_config.SelectboxColumn(options=["코너형","사각형"]),
            "user_type": st.column_config.SelectboxColumn(options=["일반","주거약자"]),
            "delta": st.column_config.NumberColumn("보정금액(원)", step=5000),
        }
    )
    st.session_state.tables = (base_grp, base_ppe, adjust_tbl, area_rules, vehicles_tbl, oji_tbl, meals_std, detail_catalogs)

# ------------------------------
# ③ 면적 보정
# ------------------------------
with tab3:
    st.subheader("면적 보정 (경계 포함)")
    c1, c2, c3 = st.columns(3)
    with c1:
        rule = area_rules.get("GRP", {"min":2.5,"max":2.9,"delta_below":-30000,"delta_above":30000})
        grp_min = st.number_input("GRP 기준 하한(㎡)", value=float(rule["min"]), step=0.1, format="%.1f")
        grp_max = st.number_input("GRP 기준 상한(㎡)", value=float(rule["max"]), step=0.1, format="%.1f")
        grp_below = st.number_input("GRP 하한 미만 가산(원)", value=int(rule["delta_below"]), step=1000)
        grp_above = st.number_input("GRP 상한 초과 가산(원)", value=int(rule["delta_above"]), step=1000)
    with c2:
        rule = area_rules.get("PP/PE", {"min":2.5,"max":3.0,"delta_below":-30000,"delta_above":30000})
        ppe_min = st.number_input("PP/PE 기준 하한(㎡)", value=float(rule["min"]), step=0.1, format="%.1f")
        ppe_max = st.number_input("PP/PE 기준 상한(㎡)", value=float(rule["max"]), step=0.1, format="%.1f")
        ppe_below = st.number_input("PP/PE 하한 미만 가산(원)", value=int(rule["delta_below"]), step=1000)
        ppe_above = st.number_input("PP/PE 상한 초과 가산(원)", value=int(rule["delta_above"]), step=1000)
    with c3:
        rule = area_rules.get("FRP", {"min":2.5,"max":2.9,"delta_below":-30000,"delta_above":30000})
        frp_min = st.number_input("FRP 기준 하한(㎡)", value=float(rule["min"]), step=0.1, format="%.1f")
        frp_max = st.number_input("FRP 기준 상한(㎡)", value=float(rule["max"]), step=0.1, format="%.1f")
        frp_below = st.number_input("FRP 하한 미만 가산(원)", value=int(rule["delta_below"]), step=1000)
        frp_above = st.number_input("FRP 상한 초과 가산(원)", value=int(rule["delta_above"]), step=1000)

    area_rules = {
        "GRP":{"min":grp_min,"max":grp_max,"delta_below":grp_below,"delta_above":grp_above},
        "PP/PE":{"min":ppe_min,"max":ppe_max,"delta_below":ppe_below,"delta_above":ppe_above},
        "FRP":{"min":frp_min,"max":frp_max,"delta_below":frp_below,"delta_above":frp_above},
    }
    st.session_state.tables = (base_grp, base_ppe, adjust_tbl, area_rules, vehicles_tbl, oji_tbl, meals_std, detail_catalogs)

# ------------------------------
# ④ 외곽/오지 유류비
# ------------------------------
with tab4:
    st.subheader("외곽/오지·유류비")
    vehicles_tbl = st.data_editor(
        vehicles_tbl,
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "bucket": st.column_config.TextColumn("세대수 구간", disabled=True),
            "vehicles": st.column_config.NumberColumn("차량대수", step=0.5),
            "fuel_per_vehicle": st.column_config.NumberColumn("차량당 유류비(원)", step=5000),
        }
    )
    st.markdown("**외곽/오지 지역 리스트 (참고용)**")
    st.dataframe(oji_tbl, use_container_width=True)
    st.session_state.tables = (base_grp, base_ppe, adjust_tbl, area_rules, vehicles_tbl, oji_tbl, meals_std, detail_catalogs)

# ------------------------------
# ⑤ 숙식비 설정
# ------------------------------
with tab5:
    st.subheader("숙식비 설정 (기준단가에 미포함, 별도 가산)")
    c1, c2 = st.columns(2)
    with c1:
        meals_std["crew_count"] = st.number_input("crew 인원 수", min_value=0, step=1, value=int(meals_std.get("crew_count", 4)))
        meals_std["days"] = st.number_input("세대당 숙식 일수", min_value=0, step=1, value=int(meals_std.get("days", 1)))
    with c2:
        meals_std["meal_unit"] = st.number_input("1인 1일 식대(원)", min_value=0, step=1000, value=int(meals_std.get("meal_unit", 10000)))
        meals_std["lodging_unit"] = st.number_input("1인 1일 숙박비(원)", min_value=0, step=1000, value=int(meals_std.get("lodging_unit", 25000)))
    st.session_state.tables = (base_grp, base_ppe, adjust_tbl, area_rules, vehicles_tbl, oji_tbl, meals_std, detail_catalogs)

# ------------------------------
# ⑥ 결과/근거 로그
# ------------------------------
with tab6:
    st.subheader("결과 요약 및 근거 로그")

    result = st.session_state.get("calc_result", None)
    log_lines = st.session_state.get("calc_logs", [])
    breakdown = st.session_state.get("calc_breakdown", {})

    if "calc_result" not in st.session_state:
        st.info("좌측 사이드바에서 **'계산 실행'** 버튼을 눌러 계산을 수행하세요.")
    else:
        if result is None:
            st.error("제주 지역은 별도 산정 대상입니다.")
        else:
            st.metric("세대당 인건비", fmt_money(result))

        st.markdown("---")
        st.markdown("### ① 조건 요약")

        # 면적 기준 정보
        mat_rule = area_rules.get(material.upper(), {})
        area_min = mat_rule.get("min", None)
        area_max = mat_rule.get("max", None)
        if area_min is not None and area_max is not None:
            area_range_str = f"{area_min:.1f} ~ {area_max:.1f}"
        else:
            area_range_str = "-"

        cond_rows = [
            {"항목":"재질", "값": material},
            {"항목":"형상", "값": shape},
            {"항목":"세대유형", "값": user_type},
            {"항목":"세대수", "값": int(units)},
            {"항목":"버킷", "값": bucket},
            {"항목":"규격코드", "값": code},
            {"항목":"면적(㎡)", "값": f"{area:.2f}"},
            {"항목":"면적 기준범위(㎡)", "값": area_range_str},
            {"항목":"지역", "값": region},
            {"항목":"외곽/오지", "값": "예" if is_oji else "아니오"},
        ]
        cond_df = pd.DataFrame(cond_rows)
        st.table(cond_df)

        st.markdown("---")
        st.markdown("### ② 비용 요약 (세대당)")

        base_install = breakdown.get("base_install", None)
        meals_cost = breakdown.get("meals", None)
        fuel_cost = breakdown.get("fuel", None)
        subtotal_ex_fuel = breakdown.get("subtotal_ex_fuel", None)
        detail_per_unit = breakdown.get("detail_per_unit", None)
        final_price = breakdown.get("final", result)

        summary_rows = []
        if base_install is not None:
            summary_rows.append({"항목":"기준설치비", "금액(원)": fmt_money(base_install), "비고":"Base + 형상/세대/재질 보정 + 면적 보정"})
        if meals_cost is not None:
            summary_rows.append({"항목":"숙식비", "금액(원)": fmt_money(meals_cost), "비고":"기준단가에 미포함, 별도 가산"})
        if subtotal_ex_fuel is not None:
            summary_rows.append({"항목":"기준단가 합계", "금액(원)": fmt_money(subtotal_ex_fuel), "비고":"유류비 제외"})
        if fuel_cost is not None and fuel_cost != 0:
            summary_rows.append({"항목":"유류비 추가비", "금액(원)": fmt_money(fuel_cost), "비고":"외곽/오지일 경우"})
        # 세부설치비(세대당)는 계산에 포함되지 않으므로 요약 표에서는 제외
        if final_price is not None:
            summary_rows.append({"항목":"최종 세대당 인건비", "금액(원)": fmt_money(final_price), "비고":""})

        if summary_rows:
            summary_df = pd.DataFrame(summary_rows)
            st.table(summary_df)
        else:
            st.info("요약할 비용 정보가 없습니다.")

        st.markdown("---")
        st.markdown("### ③ 계산 근거 로그 (표)")

        if log_lines:
            log_rows = []
            for line in log_lines:
                if line.startswith("  - "):
                    kind = "세부항목"
                    text = line[4:]
                else:
                    kind = "요약"
                    text = line
                log_rows.append({"구분": kind, "내용": text})
            log_df = pd.DataFrame(log_rows)
            st.dataframe(log_df, use_container_width=True)
        else:
            st.info("근거 로그가 없습니다.")

# ------------------------------
# ⑦ 세부설치비 선택(카탈로그)
# ------------------------------
with tab7:
    st.subheader("세부설치비 선택 (엑셀 카탈로그)")
    # 재질 선택에 따라 해당 카탈로그 사용 (FRP는 GRP 기반 보정이므로 GRP 카탈로그 사용)
    cat_key = "PP/PE" if material.upper() in ["PP/PE","PPPE","PPE"] else "GRP"
    catalog_df = detail_catalogs.get(cat_key, pd.DataFrame()).copy()

    if catalog_df.empty:
        st.error("카탈로그가 비어 있습니다. 엑셀 설정 파일의 detail_catalog_* 시트를 확인하세요.")
    else:
        st.caption(f"사용 중인 카탈로그: **{cat_key}**  |  세대수 버킷: **{bucket}**  |  항목 수: {len(catalog_df)}")

        items = ["(전체)"] + sorted(catalog_df["품목"].dropna().unique().tolist())
        pick_item = st.selectbox("품목", items, index=0)
        filtered = catalog_df if pick_item == "(전체)" else catalog_df[catalog_df["품목"]==pick_item]

        specs = ["(전체)"] + sorted(filtered["사양"].dropna().unique().tolist())
        pick_spec = st.selectbox("사양", specs, index=0)
        if pick_spec != "(전체)":
            filtered = filtered[filtered["사양"]==pick_spec]

        sizes = ["(전체)"] + sorted(filtered["규격"].dropna().unique().tolist())
        pick_size = st.selectbox("규격", sizes, index=0)
        if pick_size != "(전체)":
            filtered = filtered[filtered["규격"]==pick_size]

        if "적용" not in filtered.columns:
            filtered["적용"] = True
        edited = st.data_editor(
            filtered,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "적용": st.column_config.CheckboxColumn(),
            }
        )
        # 여기서는 단순히 편집된 카탈로그를 다시 저장
        detail_catalogs[cat_key] = edited
        st.session_state.tables = (base_grp, base_ppe, adjust_tbl, area_rules, vehicles_tbl, oji_tbl, meals_std, detail_catalogs)

# ------------------------------
# 디버그 JSON
# ------------------------------
import json
with st.expander("디버그용 JSON 보기", expanded=False):
    st.code(json.dumps({
        "입력조건": {
            "세대수": int(units),
            "버킷": bucket,
            "재질": material,
            "형상": shape,
            "세대유형": user_type,
            "규격코드": code,
            "면적": area,
            "지역": region,
            "외곽오지": bool(is_oji),
            "Base소스": "2025 세부표 사용 (숙식비 미포함)",
        },
        "meals_std": meals_std,
    }, ensure_ascii=False, indent=2), language="json")
