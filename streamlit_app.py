import streamlit as st
import requests
import pandas as pd
import time
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

# --- 2. THE SANDBOX ENGINE ---
PUBLIC_MIRROR = "https://ce.judge0.com" 

def run_code_in_sandbox(code, test_input):
    payload = {
        "source_code": code,
        "language_id": 71, # Python 3
        "stdin": str(test_input) if test_input else ""
    }
    try:
        # Use ?wait=true for immediate synchronous results
        res = requests.post(f"{PUBLIC_MIRROR}/submissions?wait=true", json=payload, timeout=20)
        data = res.json()
        
        stdout = data.get("stdout")
        stderr = data.get("stderr")
        compile_output = data.get("compile_output")
        status = data.get("status", {}).get("description", "")

        if stderr: return "RUNTIME_ERR", stderr
        if compile_output: return "COMPILE_ERR", compile_output
        
        if status == "Accepted":
            output = stdout.strip() if stdout else ""
            if not output: return "NO_PRINT", "Code ran but printed nothing."
            return "SUCCESS", output
        
        return "ERROR", f"Status: {status}"
    except Exception as e:
        return "CONN_ERR", f"Sandbox unavailable: {str(e)}"

# --- 3. DATABASE HELPER ---
def get_current_task(c_name, p_num):
    try:
        res = supabase.table("current_task").select("*").eq("class_name", c_name).eq("period", p_num).execute()
        if res.data: return res.data[0]
    except: pass
    return {"goal_input": "", "expected_output": "", "task_description": ""}

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header("🏫 Class Management")
    teacher = st.text_input("Teacher Name", value="Grom")
    
    # Fetch existing classes for this teacher
    roster_check = supabase.table("rosters").select("class_name").eq("teacher_name", teacher).execute().data
    classes = list(set([r['class_name'] for r in roster_check])) if roster_check else ["Python 101"]
    
    sel_class = st.selectbox("Select Class", classes)
    sel_period = st.selectbox("Select Period", ["1", "2", "3", "4", "5", "6", "7", "8"])

    st.divider()
    with st.expander("📋 Bulk Roster Upload"):
        raw_names = st.text_area("Student Names (One per line):", height=150)
        if st.button("Save Roster"):
            name_list = [n.strip() for n in raw_names.split("\n") if n.strip()]
            bulk_data = [{"teacher_name": teacher, "class_name": sel_class, "period": sel_period, "student_name": n} for n in name_list]
            supabase.table("rosters").upsert(bulk_data).execute()
            st.success(f"Saved {len(name_list)} students.")
            st.rerun()

# Global Task Context
task = get_current_task(sel_class, sel_period)

# --- 5. APP TABS ---
tab_student, tab_leaderboard, tab_teacher = st.tabs(["📝 Student View", "🏆 Leaderboard", "👨‍🏫 Teacher Tools"])

# --- TAB 1: STUDENT VIEW ---
with tab_student:
    st.title(f"{sel_class} - Period {sel_period}")
    
    if task.get('task_description'):
        with st.container(border=True):
            st.subheader("📋 Instructions")
            st.markdown(task['task_description'])
            st.divider()
            c1, c2 = st.columns(2)
            c1.metric("Goal Input", f"`{task.get('goal_input') or 'None'}`")
            c2.metric("Expected Output", f"`{task.get('expected_output') or 'None'}`")
    else:
        st.info("No assignment posted for this period yet.")

    # Get Roster for current period
    roster_res = supabase.table("rosters").select("student_name").eq("class_name", sel_class).eq("period", sel_period).execute().data
    names = [r['student_name'] for r in roster_res] if roster_res else ["Roster Empty"]
    
    current_user = st.selectbox("Select Your Name:", names)
    code_in = st.text_area("Python Editor:", height=300, key="editor_v6")
    
    if st.button("🚀 Run & Submit"):
        if not code_in.strip():
            st.error("Please enter some code!")
        else:
            with st.spinner("Executing on Sandbox..."):
                status, output = run_code_in_sandbox(code_in, task.get('goal_input', ''))
            
            # Grading Logic
            clean_out = str(output).replace(" ", "").strip()
            clean_target = str(task.get('expected_output', '')).replace(" ", "").strip()
            
            final_status = status
            if status == "SUCCESS":
                final_status = "PASSED ✅" if clean_out == clean_target else "WRONG OUTPUT ❌"

            # Record Submission
            supabase.table("submissions").upsert({
                "name": current_user, "class_name": sel_class, "period": sel_period,
                "code": code_in, "status": final_status, "output": str(output)
            }, on_conflict="name, class_name, period").execute()
            
            if "PASSED" in final_status: st.success(f"Result: {output}")
            else: st.warning(f"Status: {final_status} | Result: {output}")

# --- TAB 2: LEADERBOARD ---
with tab_leaderboard:
    st.header(f"Class Progress")
    if st.button("🔄 Refresh Standings"):
        r_df = pd.DataFrame(roster_res) if roster_res else pd.DataFrame(columns=['student_name'])
        s_raw = supabase.table("submissions").select("*").eq("class_name", sel_class).eq("period", sel_period).execute().data
        s_df = pd.DataFrame(s_raw) if s_raw else pd.DataFrame(columns=['name', 'status'])
        
        if not r_df.empty:
            merged = pd.merge(r_df, s_df, left_on='student_name', right_on='name', how='left')
            merged['status'] = merged['status'].fillna("NOT SUBMITTED ⚪")
            
            # Ranking logic
            rank_map = {"PASSED ✅": 0, "WRONG OUTPUT ❌": 1, "RUNTIME_ERR": 1, "COMPILE_ERR": 1, "NO_PRINT": 1}
            merged['rank'] = merged['status'].apply(lambda x: rank_map.get(x, 2))
            merged = merged.sort_values('rank')

            def style_status(val):
                color = '#2ecc71' if 'PASSED' in val else ('#e74c3c' if 'ERR' in val else ('#f39c12' if 'WRONG' in val else '#95a5a6'))
                return f'background-color: {color}; color: white; font-weight: bold'

            st.dataframe(merged[['student_name', 'status']].style.applymap(style_status, subset=['status']), use_container_width=True)
        else:
            st.warning("No roster found for this class.")

# --- TAB 3: TEACHER TOOLS ---
with tab_teacher:
    st.header("Teacher Dashboard")
    
    with st.expander("🎯 Set Today's Assignment", expanded=True):
        new_desc = st.text_area("Task Instructions (Markdown):", value=task.get('task_description', ""), height=150)
        c1, c2 = st.columns(2)
        goal_in = c1.text_input("Expected Input:", value=task.get('goal_input', ""))
        goal_out = c2.text_input("Expected Output:", value=task.get('expected_output', ""))
        
        if st.button("Broadcast to Students"):
            supabase.table("current_task").upsert({
                "class_name": sel_class, "period": sel_period,
                "task_description": new_desc,
                "goal_input": goal_in, "expected_output": goal_out
            }, on_conflict="class_name, period").execute()
            st.success("Assignment updated!")
            st.rerun()

    st.divider()
    
    # Live Code Review
    st.subheader("🔦 Live Code Review")
    active_subs = supabase.table("submissions").select("*").eq("class_name", sel_class).eq("period", sel_period).execute().data
    
    if active_subs:
        as_df = pd.DataFrame(active_subs)
        target = st.selectbox("Select Student to Review:", as_df['name'].tolist())
        row = as_df[as_df['name'] == target].iloc[0]
        
        if st.toggle("🚀 Enter Projector Mode"):
            st.title(f"Code Analysis: {target}")
            st.code(row['code'], language="python")
            st.info(f"Student Output: {row['output']}")
        else:
            st.code(row['code'])
            st.write(f"Submission Status: **{row['status']}**")
    else:
        st.info("Waiting for first student submission...")

    if st.button("🧨 Reset All Period Data"):
        supabase.table("submissions").delete().eq("class_name", sel_class).eq("period", sel_period).execute()
        st.success("Cleared!")
        st.rerun()