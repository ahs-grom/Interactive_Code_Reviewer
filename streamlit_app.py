import streamlit as st
import requests
import pandas as pd
from supabase import create_client

# --- 1. INITIALIZATION ---
st.set_page_config(page_title="CodeMaster LMS", layout="wide")

try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    supabase = create_client(url, key)
except Exception as e:
    st.error("🚨 Configuration Error: Supabase secrets missing.")
    st.stop()

PUBLIC_MIRROR = "https://ce.judge0.com" 

def run_code_in_sandbox(code, test_input):
    payload = {"source_code": code, "language_id": 71, "stdin": str(test_input) if test_input else ""}
    try:
        res = requests.post(f"{PUBLIC_MIRROR}/submissions?wait=true", json=payload, timeout=20)
        data = res.json()
        stdout, stderr, status = data.get("stdout"), data.get("stderr"), data.get("status", {}).get("description", "")
        if stderr: return "RUNTIME_ERR", stderr
        if status == "Accepted":
            output = stdout.strip() if stdout else ""
            return "SUCCESS", (output or "NO_PRINT")
        return "ERROR", f"Status: {status}"
    except Exception as e:
        return "CONN_ERR", str(e)

def get_current_task(c_name, p_num):
    try:
        res = supabase.table("current_task").select("*").eq("class_name", c_name).eq("period", p_num).execute()
        if res.data: return res.data[0]
    except: pass
    return {"goal_input": "", "expected_output": "", "task_description": ""}

# --- 2. SIDEBAR ---
with st.sidebar:
    st.header("🏫 Class Management")
    teacher = st.text_input("Teacher Name", value="Grom")
    roster_raw = supabase.table("rosters").select("class_name").eq("teacher_name", teacher).execute().data
    classes = list(set([r['class_name'] for r in roster_raw])) if roster_raw else ["Python 101"]
    sel_class = st.selectbox("Select Class", classes)
    sel_period = st.selectbox("Select Period", ["1", "2", "3", "4", "5", "6", "7", "8"])

task = get_current_task(sel_class, sel_period)

# --- 3. APP TABS ---
tab_student, tab_leaderboard, tab_teacher = st.tabs(["📝 Student View", "🏆 Leaderboard & Review", "👨‍🏫 Settings"])

# --- TAB 1: STUDENT ---
with tab_student:
    st.title(f"{sel_class} - P{sel_period}")
    if task.get('task_description'):
        with st.container(border=True):
            st.markdown(task['task_description'])
            st.caption(f"Input: {task['goal_input']} | Expected: {task['expected_output']}")
    
    roster_res = supabase.table("rosters").select("student_name").eq("class_name", sel_class).eq("period", sel_period).execute().data
    names = [r['student_name'] for r in roster_res] if roster_res else ["Roster Empty"]
    current_user = st.selectbox("Your Name:", names)
    code_in = st.text_area("Python Editor:", height=300)
    
    if st.button("🚀 Run & Submit"):
        with st.spinner("Running..."):
            status, output = run_code_in_sandbox(code_in, task.get('goal_input', ''))
        clean_out, clean_target = str(output).replace(" ", "").strip(), str(task.get('expected_output', '')).replace(" ", "").strip()
        final_status = status
        if status == "SUCCESS":
            final_status = "PASSED ✅" if clean_out == clean_target else "WRONG OUTPUT ❌"

        supabase.table("submissions").upsert({
            "name": current_user, "class_name": sel_class, "period": sel_period,
            "code": code_in, "status": final_status, "output": str(output)
        }, on_conflict="name, class_name, period").execute()
        if "PASSED" in final_status: st.success(output)
        else: st.warning(f"{final_status}: {output}")

# --- TAB 2: LEADERBOARD & INTEGRATED REVIEW ---
with tab_leaderboard:
    st.header(f"Live Standings: {sel_class}")
    
    # Fetch Data
    r_df = pd.DataFrame(roster_res) if roster_res else pd.DataFrame(columns=['student_name'])
    s_raw = supabase.table("submissions").select("*").eq("class_name", sel_class).eq("period", sel_period).execute().data
    s_df = pd.DataFrame(s_raw) if s_raw else pd.DataFrame(columns=['name', 'status', 'code', 'output'])
    
    if not r_df.empty:
        merged = pd.merge(r_df, s_df, left_on='student_name', right_on='name', how='left')
        merged['status'] = merged['status'].fillna("NOT SUBMITTED ⚪")
        
        # Display Table
        def style_status(val):
            color = '#2ecc71' if 'PASSED' in val else ('#e74c3c' if 'ERR' in val else ('#f39c12' if 'WRONG' in val else '#95a5a6'))
            return f'background-color: {color}; color: white; font-weight: bold'
        
        st.dataframe(merged[['student_name', 'status']].style.applymap(style_status, subset=['status']), use_container_width=True)
        
        st.divider()
        
        # --- THE "CLICK ON STUDENT" LOGIC ---
        st.subheader("🔦 Quick Code Review")
        # Only show students who actually submitted code
        submitted_names = s_df['name'].tolist()
        if submitted_names:
            review_target = st.selectbox("Select a student from the list above to view their work:", submitted_names)
            student_data = s_df[s_df['name'] == review_target].iloc[0]
            
            col_a, col_b = st.columns([2, 1])
            with col_a:
                st.markdown(f"**{review_target}'s Code:**")
                st.code(student_data['code'], language="python")
            with col_b:
                st.markdown("**Last Output:**")
                st.info(student_data['output'])
                st.markdown(f"**Status:** {student_data['status']}")
        else:
            st.info("No submissions to review yet.")
    else:
        st.warning("Upload a roster in the sidebar first.")

# --- TAB 3: TEACHER SETTINGS ---
with tab_teacher:
    st.header("Teacher Controls")
    with st.expander("🎯 Set Assignment", expanded=True):
        new_desc = st.text_area("Instructions:", value=task.get('task_description', ""), height=150)
        c1, c2 = st.columns(2)
        goal_in = c1.text_input("Expected Input:", value=task.get('goal_input', ""))
        goal_out = c2.text_input("Expected Output:", value=task.get('expected_output', ""))
        if st.button("Broadcast"):
            supabase.table("current_task").upsert({
                "class_name": sel_class, "period": sel_period,
                "task_description": new_desc, "goal_input": goal_in, "expected_output": goal_out
            }, on_conflict="class_name, period").execute()
            st.rerun()

    if st.button("🧨 Clear All Data (Current Period)"):
        supabase.table("submissions").delete().eq("class_name", sel_class).eq("period", sel_period).execute()
        st.rerun()