import streamlit as st
import requests
import pandas as pd
from supabase import create_client

# --- 1. INITIALIZATION ---
st.set_page_config(page_title="CodeMaster LMS", layout="wide")

# Database Connection
try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    supabase = create_client(url, key)
except Exception as e:
    st.error("🚨 Configuration Error: Secrets not found!")
    st.info("Ensure you have a .streamlit/secrets.toml file locally or Secrets configured in Streamlit Cloud.")
    st.stop()

PISTON_URL = "https://emkc.org/api/v2/piston/execute"

# --- 2. THE ENGINE ---
def run_code_in_sandbox(code, test_input):
    """Executes Python code safely via Piston API."""
    payload = {
        "language": "python",
        "version": "3.10.0",
        "files": [{"content": code}],
        "stdin": str(test_input) + "\n"
    }
    try:
        response = requests.post(PISTON_URL, json=payload, timeout=12)
        res = response.json()
        run_data = res.get('run', {})
        stdout = run_data.get('output', "").strip()
        stderr = run_data.get('stderr', "").strip()

        if stderr:
            if "SyntaxError" in stderr: return "SYNTAX_ERR", stderr
            if "IndentationError" in stderr: return "INDENT_ERR", stderr
            return "RUNTIME_ERR", stderr
        
        if not stdout:
            return "NO_PRINT", "Code ran but printed nothing. Use print()!"
            
        return "SUCCESS", stdout
    except Exception as e:
        return "TIMEOUT", f"Execution failed: {e}"

# --- 3. DATABASE LOGIC ---
def get_current_task(c_name, p_num):
    res = supabase.table("current_task").select("*").eq("class_name", c_name).eq("period", p_num).execute()
    if res.data:
        return res.data[0]
    return {"goal_input": "", "expected_output": "", "task_description": "No instructions provided yet."}

# --- 4. SIDEBAR: LMS CONTROLS ---
with st.sidebar:
    st.header("🏫 Class Management")
    teacher = st.text_input("Teacher Name", value="Grom")
    
    # Dynamic Class Selection
    roster_check = supabase.table("rosters").select("class_name").eq("teacher_name", teacher).execute().data
    classes = list(set([r['class_name'] for r in roster_check])) if roster_check else ["Python 101"]
    
    sel_class = st.selectbox("Select Class", classes)
    sel_period = st.selectbox("Select Period", ["1", "2", "3", "4", "5", "6", "7", "8"])

    st.divider()
    with st.expander("📋 Bulk Roster Upload"):
        st.write("Paste names (one per line):")
        raw_names = st.text_area("Student Names", height=150)
        if st.button("Save Roster"):
            name_list = [n.strip() for n in raw_names.split("\n") if n.strip()]
            bulk_data = [
                {"teacher_name": teacher, "class_name": sel_class, "period": sel_period, "student_name": n} 
                for n in name_list
            ]
            supabase.table("rosters").upsert(bulk_data).execute()
            st.success(f"Loaded {len(name_list)} students!")
            st.rerun()

# Get Global Task for this specific Class/Period
task = get_current_task(sel_class, sel_period)

# --- 5. APP TABS ---
tab_student, tab_leaderboard, tab_teacher = st.tabs(["📝 Student View", "🏆 Leaderboard", "👨‍🏫 Teacher Tools"])

# --- STUDENT TAB ---
with tab_student:
    st.title(f"{sel_class} - Period {sel_period}")
    
    # Display the Teacher's Instructions
    with st.container(border=True):
        st.subheader("📋 Instructions")
        st.markdown(task.get('task_description', "No instructions provided yet."))
        st.divider()
        col_in, col_out = st.columns(2)
        col_in.metric("Goal Input", f"`{task['goal_input']}`")
        col_out.metric("Expected Output", f"`{task['expected_output']}`")
    
    # Roster Selection
    roster_res = supabase.table("rosters").select("student_name").eq("class_name", sel_class).eq("period", sel_period).execute().data
    names = [r['student_name'] for r in roster_res] if roster_res else ["Roster Empty"]
    
    current_user = st.selectbox("Select Your Name:", names)
    code_in = st.text_area("Python Editor:", height=300, placeholder="# Write your code here...")
    
    if st.button("🚀 Run & Submit"):
        status, output = run_code_in_sandbox(code_in, task['goal_input'])
        
        # Space-insensitive grading
        clean_out = str(output).replace(" ", "").strip()
        clean_target = str(task['expected_output']).replace(" ", "").strip()
        
        final_status = status
        if status == "SUCCESS":
            final_status = "PASSED ✅" if clean_out == clean_target else "WRONG OUTPUT ❌"

        # Record Submission
        supabase.table("submissions").upsert({
            "name": current_user, "class_name": sel_class, "period": sel_period,
            "code": code_in, "status": final_status, "output": output
        }, on_conflict="name, class_name, period").execute()
        
        if "PASSED" in final_status: st.success(f"Result: {output}")
        else: st.warning(f"Status: {final_status} | Result: {output}")

# --- LEADERBOARD TAB ---
with tab_leaderboard:
    st.header(f"Class Progress: {sel_class} P{sel_period}")
    if st.button("🔄 Refresh Standings"):
        r_df = pd.DataFrame(roster_res)
        s_raw = supabase.table("submissions").select("*").eq("class_name", sel_class).eq("period", sel_period).execute().data
        s_df = pd.DataFrame(s_raw) if s_raw else pd.DataFrame(columns=['name', 'status'])
        
        if not r_df.empty:
            merged = pd.merge(r_df, s_df, left_on='student_name', right_on='name', how='left')
            merged['status'] = merged['status'].fillna("NOT SUBMITTED ⚪")
            
            rank_map = {"PASSED ✅": 0, "WRONG OUTPUT ❌": 1, "SYNTAX_ERR": 1, "INDENT_ERR": 1, "RUNTIME_ERR": 1, "NO_PRINT": 1}
            merged['rank'] = merged['status'].apply(lambda x: rank_map.get(x, 2))
            merged = merged.sort_values('rank')

            def style_status(val):
                color = '#2ecc71' if 'PASSED' in val else ('#e74c3c' if 'ERR' in val else ('#f39c12' if 'WRONG' in val else '#95a5a6'))
                return f'background-color: {color}; color: white; font-weight: bold'

            st.dataframe(merged[['student_name', 'status']].style.applymap(style_status, subset=['status']), use_container_width=True)
        else:
            st.warning("Please upload a roster in the sidebar first.")

# --- TEACHER TAB ---
with tab_teacher:
    st.header("Teacher Dashboard")
    
    # 1. ASSIGNMENT CONTROL
    with st.expander("🎯 Set Daily Assignment", expanded=True):
        new_desc = st.text_area("Task Description (Markdown supported):", value=task.get('task_description', ""), height=150)
        c1, c2 = st.columns(2)
        goal_in = c1.text_input("Goal Input (Stdin):", value=task['goal_input'])
        goal_out = c2.text_input("Expected Output (Stdout):", value=task['expected_output'])
        
        if st.button("Broadcast Task to Students"):
            supabase.table("current_task").upsert({
                "class_name": sel_class, "period": sel_period,
                "task_description": new_desc,
                "goal_input": goal_in, "expected_output": goal_out
            }, on_conflict="class_name, period").execute()
            st.success("Task and Instructions updated!")
            st.rerun()

    # 2. PROJECTOR MODE
    st.divider()
    st.subheader("🔦 Projector Mode / Code Review")
    active_subs = supabase.table("submissions").select("*").eq("class_name", sel_class).eq("period", sel_period).execute().data
    
    if active_subs:
        as_df = pd.DataFrame(active_subs)
        target_student = st.selectbox("Select Student to Review:", as_df['name'].tolist())
        row = as_df[as_df['name'] == target_student].iloc[0]
        
        is_projecting = st.toggle("🚀 Enter Fullscreen Projector Mode")
        
        if is_projecting:
            st.title(f"Code Analysis: {target_student}")
            st.code(row['code'], language="python")
            st.info(f"Student Output: {row['output']}")
            st.write(f"Submission Status: **{row['status']}**")
        else:
            st.code(row['code'])
            st.text_area("Teacher Feedback (Saved to DB):", value=row.get('teacher_comment', ""))
    else:
        st.info("Waiting for first submission...")

    # 3. RESET
    st.divider()
    if st.button("🧨 Clear Submissions (Current Period)"):
        supabase.table("submissions").delete().eq("class_name", sel_class).eq("period", sel_period).execute()
        st.success("Period data reset.")
        st.rerun()