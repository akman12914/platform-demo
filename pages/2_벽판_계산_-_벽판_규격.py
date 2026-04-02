import streamlit as st
import runpy

st.set_page_config(page_title="2 벽판계산 - 벽판 규격", layout="wide")
st.title("2 벽판계산 - 벽판 규격")
st.markdown("벽판 규격 계산 페이지입니다. 아래에서 입력 후 다음 단계로 진행하세요.")

# 기존 벽판 규격 스크립트 실행
runpy.run_path("wall_panel_spec.py", run_name="__main__")
