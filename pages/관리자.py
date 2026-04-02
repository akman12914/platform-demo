"""
관리자 페이지
사용자 관리 기능 (관리자 전용)
- 사용자 목록 조회
- 사용자 추가
- 사용자 삭제
- 비밀번호 변경
"""

import streamlit as st
import pandas as pd
from common_styles import apply_common_styles, set_page_config
import auth

set_page_config(page_title="관리자 페이지", layout="wide")
apply_common_styles()

# 관리자 권한 확인
auth.require_admin()

st.title("⚙️ 관리자 페이지")

current_user = auth.get_current_user()
st.success(f"✅ {current_user}님 (관리자)")

# 탭 생성
tab1, tab2, tab3 = st.tabs(["👥 사용자 목록", "➕ 사용자 추가", "🔑 비밀번호 변경"])

# ========== 탭 1: 사용자 목록 ==========
with tab1:
    st.subheader("👥 사용자 목록")

    users = auth.get_all_users()

    if not users:
        st.info("등록된 사용자가 없습니다.")
    else:
        # 사용자 목록을 DataFrame으로 변환
        df = pd.DataFrame(users)
        df["역할"] = df["role"].map({"admin": "관리자", "user": "일반 사용자"})
        df = df[["username", "name", "역할", "created_at"]]
        df.columns = ["사용자 ID", "이름", "역할", "생성일시"]

        st.dataframe(df, use_container_width=True, hide_index=True)

        st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

        # 사용자 삭제
        st.markdown("### 🗑️ 사용자 삭제")

        # 삭제 가능한 사용자 목록 (관리자 제외)
        deletable_users = [u["username"] for u in users if u["username"] != auth.DEFAULT_ADMIN_USERNAME]

        if not deletable_users:
            st.info("삭제 가능한 사용자가 없습니다.")
        else:
            col1, col2 = st.columns([3, 1])
            with col1:
                user_to_delete = st.selectbox("삭제할 사용자 선택", deletable_users)
            with col2:
                st.markdown("<div style='height:30px'></div>", unsafe_allow_html=True)
                if st.button("🗑️ 삭제", type="secondary", use_container_width=True):
                    if auth.delete_user(user_to_delete):
                        st.success(f"✅ 사용자 '{user_to_delete}'가 삭제되었습니다.")
                        st.rerun()
                    else:
                        st.error("❌ 사용자 삭제에 실패했습니다.")

# ========== 탭 2: 사용자 추가 ==========
with tab2:
    st.subheader("➕ 새 사용자 추가")

    with st.form("add_user_form"):
        col1, col2 = st.columns(2)

        with col1:
            new_username = st.text_input("사용자 ID", placeholder="영문/숫자 조합")
            new_name = st.text_input("이름", placeholder="사용자 이름")

        with col2:
            new_password = st.text_input("비밀번호", type="password", placeholder="8자 이상 권장")
            new_password_confirm = st.text_input("비밀번호 확인", type="password", placeholder="비밀번호 재입력")

        new_role = st.radio("권한", ["일반 사용자", "관리자"], horizontal=True)
        role_value = "user" if new_role == "일반 사용자" else "admin"

        col_spacer, col_btn, col_spacer2 = st.columns([2, 1, 2])
        with col_btn:
            submit = st.form_submit_button("➕ 사용자 추가", use_container_width=True)

        if submit:
            # 유효성 검사
            if not new_username or not new_name or not new_password or not new_password_confirm:
                st.error("❌ 모든 필드를 입력해주세요.")
            elif new_password != new_password_confirm:
                st.error("❌ 비밀번호가 일치하지 않습니다.")
            elif len(new_password) < 6:
                st.warning("⚠️ 비밀번호는 6자 이상을 권장합니다.")
            else:
                # 사용자 추가 시도
                if auth.add_user(new_username, new_password, new_name, role_value):
                    st.success(f"✅ 사용자 '{new_username}'가 추가되었습니다.")
                    st.balloons()
                else:
                    st.error(f"❌ 사용자 ID '{new_username}'가 이미 존재합니다.")

# ========== 탭 3: 비밀번호 변경 ==========
with tab3:
    st.subheader("🔑 비밀번호 변경")

    users = auth.get_all_users()
    usernames = [u["username"] for u in users]

    with st.form("change_password_form"):
        col1, col2 = st.columns([2, 1])

        with col1:
            target_user = st.selectbox("사용자 선택", usernames)

        with col2:
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        new_pwd = st.text_input("새 비밀번호", type="password", placeholder="8자 이상 권장")
        new_pwd_confirm = st.text_input("새 비밀번호 확인", type="password", placeholder="비밀번호 재입력")

        col_spacer, col_btn, col_spacer2 = st.columns([2, 1, 2])
        with col_btn:
            submit_pwd = st.form_submit_button("🔑 비밀번호 변경", use_container_width=True)

        if submit_pwd:
            # 유효성 검사
            if not new_pwd or not new_pwd_confirm:
                st.error("❌ 새 비밀번호를 입력해주세요.")
            elif new_pwd != new_pwd_confirm:
                st.error("❌ 비밀번호가 일치하지 않습니다.")
            elif len(new_pwd) < 6:
                st.warning("⚠️ 비밀번호는 6자 이상을 권장합니다.")
            else:
                # 비밀번호 변경 시도
                if auth.update_password(target_user, new_pwd):
                    st.success(f"✅ '{target_user}'의 비밀번호가 변경되었습니다.")
                else:
                    st.error("❌ 비밀번호 변경에 실패했습니다.")

# 하단 안내
st.markdown("<div style='height:48px'></div>", unsafe_allow_html=True)
st.markdown("---")
st.info("💡 **안내:** 기본 관리자 계정(admin)은 삭제할 수 없습니다. 보안을 위해 관리자 비밀번호를 변경하는 것을 권장합니다.")
