import streamlit as st
import requests
import pandas as pd
from supabase import create_client

# --- 1. INITIALIZATION & CONNECTION ---
st.set_page_config(page_title="CodeMaster: Classroom Edition", layout="wide")

# Connect to Supabase
try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    supabase = create_client(url, key)
except Exception as e:
    st.error(f"Missing Supabase Secrets: {e}")
    st.stop()

PISTON_URL = "https://emkc.org/api/v2/piston/execute"

# --- 2. THE SANDBOX ENGINE ---
def run_code_in_sandbox(code, test_input):
    """Executes code in a secure container."""
    payload = {
        "language": "python",
        "version": "3.10.0",
        "files": [{"content": code}],
        "stdin": str(test_input) + "\n" # The '\n' simulates hitting Enter
    }
    try:
        response = requests.post(PISTON_URL, json=payload, timeout=10)
        res = response.json()
        run_info = res.get('run', {})
        stdout = run_info.get('output', "").strip()
        stderr = run_info.get('stderr', "").strip()

        if stderr:
            # Detect common student errors for the leaderboard
            if "SyntaxError" in stderr: return "SYNTAX_ERR", stderr
            if "IndentationError" in stderr: return "INDENT_ERR", stderr
            return "RUNTIME_ERR", stderr
        
        if not stdout:
            return "NO_PRINT", "Code ran but printed nothing. Use print()!"
            
        return "SUCCESS", stdout
    except:
        return "TIMEOUT", "Execution took too long!"

# --- 3. DATABASE HELPERS ---
def get_task(c_name, p_num):
    res = supabase.table("current_task").select("*").eq("class_name", c_name).eq("period", p_num).execute()
    return res.data[0] if res.data else {"goal_input": "", "expected_output": ""}

def update_task(c_name, p_num, in_val, out_val):
    supabase.table("current_task").upsert({
        "class_name": c_name, "period": p_num, 
        "goal_input": in_val, "expected_output": out_val
    }, on_conflict="class_name, period").execute()

# --- 4. SIDEBAR: CLASS SETUP ---
with st.sidebar:
    st.title("🏫 Class Setup")
    t_name = st.text_input("Teacher Name", value="Grom")
    
    # Fetch classes linked to this teacher
    roster_res = supabase.table("rosters").select("class_name").eq("teacher_name", t_name).execute().data
    unique_classes = list(set([r['class_name'] for r in roster_res])) if roster_res else ["Intro to CS"]
    
    sel_class = st.selectbox("Select Class", unique_classes)
    sel_period = st.selectbox("Select Period", ["1", "2", "3", "4", "5", "6", "7", "8"])

    st.divider()
    with st.expander("📋 Manage Roster"):
        st.write("Paste list of names (one per line):")
        bulk_names = st.text_area("Names:")
        if st.button("Update Roster"):
            name_list = [n.strip() for n in bulk_names.split("\n") if n.strip()]
            bulk_data = [{"teacher_name": t_name, "class_name": sel_class, "period": sel_period, "student_name": n} for n in name_list]
            supabase.table("rosters").upsert(bulk_data).execute()
            st.success(f"Added {len(name_list)} students.")
            st.rerun()

# Global variables based on selection
current_task = get_task(sel_class, sel_period)

# --- 5. THE MAIN UI ---
tab_student, tab_leaderboard, tab_teacher = st.tabs(["📝 Student", "🏆 Leaderboard", "👨‍🏫 Teacher"])

# --- STUDENT TAB ---
with tab_student:
    st.header(f"Assignment: {sel_class} (P{sel_period})")
    st.info(f"🎯 **Goal:** Produce `{current_task['expected_output']}` using input `{current_task['goal_input']}`")
    
    # Get names only for THIS class
    class_roster = supabase.table("rosters").select("student_name").eq("class_name", sel_class).eq("period", sel_period).execute().data
    student_options = [r['student_name'] for r in class_roster] if class_roster else ["No Roster Found"]
    
    s_name = st.selectbox("Select Your Name:", student_options)
    s_code = st.text_area("Your Python Code:", height=250, placeholder="import ast\ns = input()...")
    
    if st.button("🚀 Run & Submit"):
        with st.spinner("Executing..."):
            status_type, result = run_code_in_sandbox(s_code, current_task['goal_input'])
            
            # Grade Logic (Space Insensitive)
            final_status = status_type
            clean_res = str(result).replace(" ", "").strip()
            clean_target = str(current_task['expected_output']).replace(" ", "").strip()
            
            if status_type == "SUCCESS":
                final_status = "PASSED ✅" if clean_res == clean_target else "WRONG OUTPUT ❌"

            # Upsert Submission
            supabase.table("submissions").upsert({
                "name": s_name, "class_name": sel_class, "period": sel_period,
                "code": s_code, "status": final_status, "output": result
            }, on_conflict="name, class_name, period").execute()
            
            if "PASSED" in final_status: st.success(f"Output: {result}")
            else: st.warning(f"Status: {final_status} | Output: {result}")

# --- LEADERBOARD TAB ---
with tab_leaderboard:
    st.header(f"Live Progress - P{sel_period}")
    if st.button("🔄 Refresh Board"):
        # Data Merge (Left Join)
        roster_df = pd.DataFrame(class_roster)
        subs_raw = supabase.table("submissions").select("*").eq("class_name", sel_class).eq("period", sel_period).execute().data
        subs_df = pd.DataFrame(subs_raw) if subs_raw else pd.DataFrame(columns=['name', 'status'])
        
        if not roster_df.empty:
            merged = pd.merge(roster_df, subs_df, left_on='student_name', right_on='name', how='left')
            merged['status'] = merged['status'].fillna("NO SUBMISSION ⚪")
            
            # Sort: Passed first, Errors second, Not Submitted last
            def sort_rank(val):
                if "PASSED" in val: return 0
                if "❌" in val or "ERR" in val: return 1
                return 2
            merged['rank'] = merged['status'].apply(sort_rank)
            merged = merged.sort_values('rank')

            # Display
            def color_rows(val):
                c = '#2ecc71' if 'PASSED' in val else ('#e74c3c' if 'ERR' in val else ('#f39c12' if 'WRONG' in val else '#95a5a6'))
                return f'background-color: {c}; color: white; font-weight: bold'
            
            st.dataframe(merged[['student_name', 'status']].style.applymap(color_rows, subset=['status']), use_container_width=True)

# --- TEACHER TAB ---
with tab_teacher:
    st.header("Instructional Controls")
    
    # 1. SET TASK
    with st.expander("🎯 Set Current Task", expanded=True):
        col1, col2 = st.columns(2)
        new_in = col1.text_input("Input (Stdin):", value=current_task['goal_input'])
        new_out = col2.text_input("Expected Result:", value=current_task['expected_output'])
        if st.button("Update Class Task"):
            update_task(sel_class, sel_period, new_in, new_out)
            st.success("Updated!")
            st.rerun()

    # 2. PROJECTOR MODE (The "Share Knowledge" Tool)
    st.divider()
    st.subheader("🔦 Projector Mode / Code Review")
    
    # Get all submitted code
    submissions = supabase.table("submissions").select("*").eq("class_name", sel_class).eq("period", sel_period).execute().data
    if submissions:
        sub_df = pd.DataFrame(submissions)
        target = st.selectbox("Select Student to Feature:", sub_df['name'].tolist())
        student_data = sub_df[sub_df['name'] == target].iloc[0]
        
        projector_on = st.toggle("Enable Fullscreen Projector")
        
        if projector_on:
            st.title(f"Code Analysis: {target}")
            st.code(student_data['code'], language="python")
            st.info(f"Program Result: {student_data['output']}")
            st.write(f"Current Status: {student_data['status']}")
        else:
            st.code(student_data['code'])
            st.text_input("Private Comment to Student:", value=student_data.get('teacher_comment', ""))
    
    # 3. RESET
    st.divider()
    if st.button("🧨 Clear All Period Submissions"):
        supabase.table("submissions").delete().eq("class_name", sel_class).eq("period", sel_period).execute()
        st.warning("Database Cleared for this period.")
        st.rerun()