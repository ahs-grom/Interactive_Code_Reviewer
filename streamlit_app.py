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
    st.error("🚨 Configuration Error: Secrets not found!")
    st.stop()

PISTON_URL = "https://emkc.org/api/v2/piston/execute"

# --- 2. THE ENGINE (REBUILT FOR STABILITY) ---
def run_code_in_sandbox(code, test_input):
    # Fallback to a newline if input is empty to avoid EOFError
    safe_input = str(test_input) + "\n" if test_input else "\n"
    
    payload = {
        "language": "python",
        "version": "3.10.0",
        "files": [{"content": code}],
        "stdin": safe_input
    }
    
    try:
        response = requests.post(PISTON_URL, json=payload, timeout=15)
        response.raise_for_status() # Check for HTTP errors
        res = response.json()
        
        # Piston structure: res['run']['output'], res['run']['stderr'], etc.
        run_data = res.get('run', {})
        stdout = run_data.get('stdout', "") # Use 'stdout' specifically
        stderr = run_data.get('stderr', "")
        output = run_data.get('output', "") # Combined output
        
        # 1. Handle Runtime/Compile Errors
        if stderr:
            return "RUNTIME_ERR", stderr
        
        # 2. Handle Case where code ran but produced literally nothing
        # We check stdout specifically to see if a print() happened
        if not stdout.strip():
            # If there's an 'output' but no 'stdout', it might be a weird API quirk
            if output.strip():
                return "SUCCESS", output.strip()
            return "NO_PRINT", "The sandbox received your code but no text was printed to the console."
            
        return "SUCCESS", stdout.strip()

    except requests.exceptions.Timeout:
        return "TIMEOUT", "The code took too long to run (Infinite loop?)"
    except Exception as e:
        return "API_ERROR", f"Sandbox Communication Error: {str(e)}"

# --- 3. DATABASE LOGIC ---
def get_current_task(c_name, p_num):
    try:
        res = supabase.table("current_task").select("*").eq("class_name", c_name).eq("period", p_num).execute()
        if res.data:
            return res.data[0]
    except:
        pass
    return {"goal_input": "", "expected_output": "", "task_description": ""}

# --- 4. SIDEBAR: LMS CONTROLS ---
with st.sidebar:
    st.header("🏫 Class Management")
    teacher = st.text_input("Teacher Name", value="Grom")
    
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
            st.success("Roster updated!")
            st.rerun()

task = get_current_task(sel_class, sel_period)

# --- 5. APP TABS ---
tab_student, tab_leaderboard, tab_teacher = st.tabs(["📝 Student View", "🏆 Leaderboard", "👨‍🏫 Teacher Tools"])

# --- STUDENT TAB ---
with tab_student:
    st.title(f"{sel_class} - Period {sel_period}")
    
    if task.get('task_description') or task.get('expected_output'):
        with st.container(border=True):
            st.subheader("📋 Instructions")
            st.markdown(task.get('task_description', "No description provided."))
            st.divider()
            col_in, col_out = st.columns(2)
            display_in = task.get('goal_input') if task.get('goal_input') else "None"
            col_in.metric("Goal Input", f"`{display_in}`")
            col_out.metric("Expected Output", f"`{task.get('expected_output', '')}`")
    else:
        st.warning("No assignment posted for this period yet.")
    
    roster_res = supabase.table("rosters").select("student_name").eq("class_name", sel_class).eq("period", sel_period).execute().data
    names = [r['student_name'] for r in roster_res] if roster_res else ["Roster Empty"]
    
    current_user = st.selectbox("Select Your Name:", names)
    code_in = st.text_area("Python Editor:", height=300, key="editor")
    
    if st.button("🚀 Run & Submit"):
        if not code_in.strip():
            st.error("Please write some code before running!")
        else:
            with st.spinner("Executing on server..."):
                status, output = run_code_in_sandbox(code_in, task.get('goal_input', ''))
            
            clean_out = str(output).replace(" ", "").strip()
            clean_target = str(task.get('expected_output', '')).replace(" ", "").strip()
            
            final_status = status
            if status == "SUCCESS":
                final_status = "PASSED ✅" if clean_out == clean_target else "WRONG OUTPUT ❌"

            # Record Submission
            try:
                supabase.table("submissions").upsert({
                    "name": current_user, "class_name": sel_class, "period": sel_period,
                    "code": code_in, "status": final_status, "output": output
                }, on_conflict="name, class_name, period").execute()
            except Exception as e:
                st.error(f"Failed to save to database: {e}")
            
            if "PASSED" in final_status: 
                st.success(f"Result: {output}")
            elif "ERR" in final_status:
                st.error(f"Execution Error: \n{output}")
            else: 
                st.warning(f"Status: {final_status} | Result: {output}")

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
            rank_map = {"PASSED ✅": 0, "WRONG OUTPUT ❌": 1, "RUNTIME_ERR": 1, "NO_PRINT": 1, "TIMEOUT": 1}
            merged['rank'] = merged['status'].apply(lambda x: rank_map.get(x, 2))
            merged = merged.sort_values('rank')

            def style_status(val):
                color = '#2ecc71' if 'PASSED' in val else ('#e74c3c' if 'ERR' in val or 'TIMEOUT' in val else ('#f39c12' if 'WRONG' in val else '#95a5a6'))
                return f'background-color: {color}; color: white; font-weight: bold'

            st.dataframe(merged[['student_name', 'status']].style.applymap(style_status, subset=['status']), use_container_width=True)

# --- TEACHER TAB ---
with tab_teacher:
    st.header("Teacher Dashboard")
    
    with st.expander("🎯 Set Daily Assignment", expanded=True):
        new_desc = st.text_area("Task Description:", value=task.get('task_description', ""), height=150)
        c1, c2 = st.columns(2)
        goal_in = c1.text_input("Goal Input (Optional):", value=task.get('goal_input', ""))
        goal_out = c2.text_input("Expected Output:", value=task.get('expected_output', ""))
        
        if st.button("Broadcast Task"):
            try:
                supabase.table("current_task").upsert({
                    "class_name": sel_class, "period": sel_period,
                    "task_description": new_desc,
                    "goal_input": goal_in, "expected_output": goal_out
                }, on_conflict="class_name, period").execute()
                st.success("Task updated!")
                st.rerun()
            except Exception as e:
                st.error(f"Database Error: {e}")

    st.divider()
    active_subs = supabase.table("submissions").select("*").eq("class_name", sel_class).eq("period", sel_period).execute().data
    if active_subs:
        as_df = pd.DataFrame(active_subs)
        target_student = st.selectbox("Select Student to Review:", as_df['name'].tolist())
        row = as_df[as_df['name'] == target_student].iloc[0]
        if st.toggle("🚀 Enter Fullscreen Projector Mode"):
            st.title(f"Code Analysis: {target_student}")
            st.code(row['code'], language="python")
            st.info(f"Output: {row['output']}")
        else:
            st.code(row['code'])
    
    if st.button("🧨 Clear Period Submissions"):
        supabase.table("submissions").delete().eq("class_name", sel_class).eq("period", sel_period).execute()
        st.rerun()