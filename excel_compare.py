# excel_compare.py
# -*- coding: utf-8 -*-
# 엑셀 파일 비교 및 버전 관리 모듈

from __future__ import annotations
import os
import glob
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Any

import pandas as pd
import streamlit as st

# =========================================
# 상수
# =========================================
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 비교 대상 시트 목록 (전체)
ALL_SHEETS = [
    "바닥판",
    "바닥판단가",
    "천장판",
    "천장판타공",
    "자재단가내역",
    "벽판",
    "PVE",
]


# =========================================
# 유틸리티 함수
# =========================================
def get_latest_saved_excel() -> Optional[str]:
    """uploads/ 폴더에서 가장 최근 엑셀 파일 경로 반환"""
    pattern = os.path.join(UPLOAD_DIR, "excel_*.xlsx")
    files = glob.glob(pattern)
    if not files:
        return None
    # 파일명 기준 정렬 (타임스탬프 포함이므로 최신이 마지막)
    files.sort()
    return files[-1]


def save_excel_with_timestamp(file_bytes: bytes) -> str:
    """excel_YYYYMMDD_HHMMSS.xlsx 형식으로 저장, 경로 반환"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"excel_{timestamp}.xlsx"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(file_bytes)
    return filepath


def load_excel_bytes(filepath: str) -> bytes:
    """파일 경로에서 bytes 로드"""
    with open(filepath, "rb") as f:
        return f.read()


# =========================================
# 비교 로직
# =========================================
def compare_sheets(old_df: pd.DataFrame, new_df: pd.DataFrame, sheet_name: str) -> List[Dict[str, Any]]:
    """
    두 DataFrame 비교하여 변경사항 리스트 반환
    - 추가된 행: new에만 존재
    - 삭제된 행: old에만 존재
    - 수정된 셀: 같은 위치, 다른 값
    """
    changes = []

    # 컬럼 정규화
    old_df = old_df.copy()
    new_df = new_df.copy()
    old_df.columns = [str(c).strip() for c in old_df.columns]
    new_df.columns = [str(c).strip() for c in new_df.columns]

    # 공통 컬럼
    common_cols = list(set(old_df.columns) & set(new_df.columns))

    # 행 개수 비교
    old_rows = len(old_df)
    new_rows = len(new_df)

    # 공통 행 범위에서 셀 비교
    min_rows = min(old_rows, new_rows)
    for row_idx in range(min_rows):
        for col in common_cols:
            old_val = old_df.iloc[row_idx][col]
            new_val = new_df.iloc[row_idx][col]

            # NaN 처리
            old_is_nan = pd.isna(old_val)
            new_is_nan = pd.isna(new_val)

            if old_is_nan and new_is_nan:
                continue

            # 값 비교 (문자열로 변환하여 비교)
            old_str = "" if old_is_nan else str(old_val).strip()
            new_str = "" if new_is_nan else str(new_val).strip()

            if old_str != new_str:
                changes.append({
                    "시트": sheet_name,
                    "행": row_idx + 2,  # 엑셀 행 번호 (헤더 포함)
                    "변경유형": "수정",
                    "컬럼": col,
                    "이전값": old_str if old_str else "(비어있음)",
                    "새값": new_str if new_str else "(비어있음)",
                })

    # 추가된 행
    if new_rows > old_rows:
        for row_idx in range(old_rows, new_rows):
            # 첫 번째 비어있지 않은 셀 값 가져오기
            row_data = new_df.iloc[row_idx]
            first_val = None
            for col in common_cols[:3]:  # 처음 3개 컬럼만 확인
                if not pd.isna(row_data.get(col)):
                    first_val = str(row_data.get(col))[:30]
                    break
            changes.append({
                "시트": sheet_name,
                "행": row_idx + 2,
                "변경유형": "추가",
                "컬럼": "-",
                "이전값": "-",
                "새값": first_val or "(새 행)",
            })

    # 삭제된 행
    if old_rows > new_rows:
        for row_idx in range(new_rows, old_rows):
            row_data = old_df.iloc[row_idx]
            first_val = None
            for col in common_cols[:3]:
                if not pd.isna(row_data.get(col)):
                    first_val = str(row_data.get(col))[:30]
                    break
            changes.append({
                "시트": sheet_name,
                "행": row_idx + 2,
                "변경유형": "삭제",
                "컬럼": "-",
                "이전값": first_val or "(기존 행)",
                "새값": "-",
            })

    # 새로 추가된 컬럼
    new_cols = set(new_df.columns) - set(old_df.columns)
    for col in new_cols:
        changes.append({
            "시트": sheet_name,
            "행": "-",
            "변경유형": "컬럼추가",
            "컬럼": col,
            "이전값": "-",
            "새값": "(새 컬럼)",
        })

    # 삭제된 컬럼
    removed_cols = set(old_df.columns) - set(new_df.columns)
    for col in removed_cols:
        changes.append({
            "시트": sheet_name,
            "행": "-",
            "변경유형": "컬럼삭제",
            "컬럼": col,
            "이전값": "(기존 컬럼)",
            "새값": "-",
        })

    return changes


def compare_excel_files(
    old_bytes: bytes,
    new_bytes: bytes,
    target_sheets: Optional[List[str]] = None
) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    """
    두 엑셀 파일의 지정된 시트들 비교

    Returns:
        changes: 변경사항 리스트
        added_sheets: 새로 추가된 시트 목록
        removed_sheets: 삭제된 시트 목록
    """
    if target_sheets is None:
        target_sheets = ALL_SHEETS

    old_xls = pd.ExcelFile(old_bytes)
    new_xls = pd.ExcelFile(new_bytes)

    old_sheet_names = set(old_xls.sheet_names)
    new_sheet_names = set(new_xls.sheet_names)

    # 대상 시트 중 존재하는 것만 필터
    target_in_old = set(target_sheets) & old_sheet_names
    target_in_new = set(target_sheets) & new_sheet_names

    # 시트 추가/삭제
    added_sheets = list(target_in_new - target_in_old)
    removed_sheets = list(target_in_old - target_in_new)

    # 공통 시트 비교
    common_sheets = target_in_old & target_in_new

    all_changes = []
    for sheet_name in common_sheets:
        try:
            old_df = pd.read_excel(old_xls, sheet_name=sheet_name)
            new_df = pd.read_excel(new_xls, sheet_name=sheet_name)
            changes = compare_sheets(old_df, new_df, sheet_name)
            all_changes.extend(changes)
        except Exception as e:
            st.warning(f"시트 '{sheet_name}' 비교 중 오류: {e}")

    return all_changes, added_sheets, removed_sheets


# =========================================
# UI 렌더링
# =========================================
def render_excel_comparison_ui(
    uploaded_file,
    target_sheets: Optional[List[str]] = None,
    page_name: str = ""
) -> Optional[bytes]:
    """
    업로드된 파일과 이전 파일 비교 UI 렌더링

    Args:
        uploaded_file: st.file_uploader에서 반환된 파일 객체
        target_sheets: 비교할 시트 목록 (None이면 ALL_SHEETS 사용)
        page_name: 페이지 식별자 (세션 키 구분용)

    Returns:
        사용할 파일의 bytes (새 파일 또는 이전 파일)
        None이면 아직 선택 전
    """
    if target_sheets is None:
        target_sheets = ALL_SHEETS

    # 세션 키
    decision_key = f"excel_decision_{page_name}"
    file_bytes_key = f"excel_bytes_{page_name}"

    # 새 파일 bytes
    uploaded_file.seek(0)
    new_bytes = uploaded_file.read()
    uploaded_file.seek(0)

    # 이전 파일 확인
    latest_path = get_latest_saved_excel()

    # 첫 업로드인 경우
    if latest_path is None:
        st.info("첫 번째 엑셀 파일 업로드입니다. 파일을 저장합니다.")
        saved_path = save_excel_with_timestamp(new_bytes)
        st.success(f"저장 완료: `{os.path.basename(saved_path)}`")
        return new_bytes

    # 이전 파일과 비교
    old_bytes = load_excel_bytes(latest_path)

    # 이미 결정된 경우
    if decision_key in st.session_state:
        decision = st.session_state[decision_key]
        if decision == "new":
            return st.session_state.get(file_bytes_key, new_bytes)
        elif decision == "old":
            return old_bytes

    # 비교 수행
    changes, added_sheets, removed_sheets = compare_excel_files(
        old_bytes, new_bytes, target_sheets
    )

    # 변경 없음
    if not changes and not added_sheets and not removed_sheets:
        st.success(f"이전 파일(`{os.path.basename(latest_path)}`)과 동일합니다.")
        return new_bytes

    # 변경사항 표시
    st.warning(f"이전 파일(`{os.path.basename(latest_path)}`)과 차이점이 발견되었습니다.")

    # 시트 추가/삭제 표시
    if added_sheets:
        st.info(f"새로 추가된 시트: {', '.join(added_sheets)}")
    if removed_sheets:
        st.error(f"삭제된 시트: {', '.join(removed_sheets)}")

    # 변경사항 테이블
    if changes:
        with st.expander(f"변경사항 상세 ({len(changes)}건)", expanded=True):
            changes_df = pd.DataFrame(changes)
            st.dataframe(changes_df, use_container_width=True, hide_index=True)

    # 선택 버튼
    col1, col2 = st.columns(2)
    with col1:
        if st.button("새 파일 반영", type="primary", key=f"btn_new_{page_name}"):
            saved_path = save_excel_with_timestamp(new_bytes)
            st.success(f"새 파일 저장 완료: `{os.path.basename(saved_path)}`")
            st.session_state[decision_key] = "new"
            st.session_state[file_bytes_key] = new_bytes
            st.rerun()

    with col2:
        if st.button("이전 파일 유지", key=f"btn_old_{page_name}"):
            st.info(f"이전 파일 사용: `{os.path.basename(latest_path)}`")
            st.session_state[decision_key] = "old"
            st.rerun()

    # 아직 선택 전이면 None 반환 (계산 진행 안 함)
    st.stop()
    return None
