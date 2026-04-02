# 공통 컴포넌트 - 시방서 요약 및 품목 탐지 결과 표시
import streamlit as st


def render_chatbot_sidebar():
    """시방서 요약 + 품목 탐지 결과를 페이지 상단에 expander로 표시"""
    summary = st.session_state.get("last_index_summary")
    comparison = st.session_state.get("ai_comparison_result")
    pending = st.session_state.get("ai_pending_items", [])

    if summary or comparison or pending:
        # 페이지 상단에 expander로 표시
        with st.expander("📋 시방서 분석 결과 (클릭하여 펼치기)", expanded=False):
            # 시방서 요약 (접이식)
            if summary:
                with st.expander("📄 시방서 요약", expanded=False):
                    st.markdown(summary)

            # 품목 탐지 결과 (접이식)
            if comparison:
                to_add = comparison.get("to_add", [])
                if to_add:
                    with st.expander(f"🔍 품목 탐지 결과 ({len(to_add)}개)", expanded=True):
                        for item in to_add:
                            priority_icon = "🔴" if item.get("priority") == "high" else "🟡"
                            name = item.get('name', '')
                            source = item.get('source', '')[:50] if item.get('source') else ''
                            st.write(f"{priority_icon} **{name}** - {source}")

            # 추가 대기 품목 수
            if pending:
                st.success(f"📌 추가 대기: **{len(pending)}개** (견적서 페이지에서 최종 추가)")
