import streamlit as st
import runpy

st.set_page_config(page_title="3 벽판계산 - 타일 개수", layout="wide")
st.title("3 벽판계산 - 타일 개수 + 원가")
st.markdown("벽판 타일 개수 계산 및 벽판 원가가 함께 처리됩니다.")

# 타일 개수 계산 (벽판 계산 포함)
runpy.run_path("tile_calculation.py", run_name="__main__")

# 벽판 원가 계산 코드 포함
runpy.run_path("wall_panel_cost_final.py", run_name="__main__")
