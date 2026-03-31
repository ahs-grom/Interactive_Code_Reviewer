import streamlit as st
import requests
import pandas as pd
import time
from supabase import create_client

# --- 1. INITIALIZATION ---
st.set_page_config(page_title="CodeMaster LMS", layout="wide")

# Attempt to load secrets
try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    supabase = create_client(url, key)
    T_PASS = st.secrets["TEACHER_PASSWORD"]
    S_PASS = st.secrets["STUDENT_PASSWORD"]
except Exception as e:
    st.error("🚨 Configuration Error: Missing Secrets (Passwords or Supabase URL/Key).")
    st.stop()

# Public Sandbox Engine
PUBLIC_MIRROR = "https://ce.judge0.com" 

# --- 2. AUTHENTICATION ---
if "role" not in st.session_state:
    st.session_state.role = None

def login():
    st.title("🔐 CodeMaster Login")
    choice = st.radio("I am a:", ["Student", "Teacher"])
    password = st.text_input("Enter Access Password:", type="password")
    
    if st.button("Login"):
        if choice == "Teacher" and password == T_PASS:
            st.session_state.role = "teacher"
            st.rerun()
        elif choice == "Student" and password == S_PASS:
            st.session_state.role = "student"
            st.rerun()
        else:
            st.error("Invalid Password")

if st.session_state.role is None:
    login()
    st.stop()

# --- 3. SANDBOX ENGINE ---
def run_code_in_sandbox(code, test_input):
    payload = {
        "source_code": code, 
        "language_id": 71, # Python 3
        "stdin": str(test_input) if test_input else ""
    }
    try:
        res = requests.post(f"{PUBLIC_MIRROR}/submissions?wait=true", json=payload, timeout=20)
        data = res.json()
        stdout = data.get("stdout")
        stderr = data.get("stderr")
        if stderr: return "RUNTIME_ERR", stderr
        return "SUCCESS", (stdout.strip() if stdout else "NO_PRINT")
    except:
        return "CONN_ERR", "Sandbox Offline"

# --- 4. SIDEBAR & NAVIGATION ---
with st.sidebar:
    st.header(f"👋 {st.session_state.role.title()} Portal")
    teacher_name = st.text_input("Instructor Name:", value="Grom")
    
    # Load available classes from roster
    res = supabase.table("rosters").select("class_name").eq("teacher_name", teacher_name).execute().data
    available_classes = sorted(list(set([r['class_name'] for r in res]))) if res else ["No Classes Found"]
    
    sel_class = st.selectbox("Current Class:", available_classes)
    sel_period = st.selectbox("Period:", ["1", "2", "3", "4", "5", "6", "7", "8"])
    
    st.divider()
    if st.button("🚪 Logout"):
        st.session_state.role = None
        st.rerun()

# Database Helper for Tasks
def get_task():
    res = supabase.table("current_task").select("*").eq("class_name", sel_class).eq("period", sel_period).execute().data
    return res[0] if res else {"goal_input": "", "expected_output": "", "task_description": ""}

task = get_task()

# --- 5. MAIN INTERFACE ---

# --- TEACHER VIEW ---
if st.session_state.role == "teacher":
    tab_leader, tab_settings = st.tabs(["🏆 Leaderboard & Review", "⚙️ Management"])
    
    with tab_leader:
        st.header(f"Live Dashboard: {sel_class} P{sel_period}")
        
        # Load Data
        roster = supabase.table("rosters").select("student_name").eq("class_name", sel_class).eq("period", sel_period).execute().data
        subs = supabase.table("submissions").select("*").eq("class_name", sel_class).eq("period", sel_period).execute().data
        
        if roster:
            r_df = pd.DataFrame(roster)
            s_df = pd.DataFrame(subs) if subs else pd.DataFrame(columns=['name', 'status', 'code', 'output'])
            merged = pd.merge(r_df, s_df, left_on='student_name', right_on='name', how='left').fillna("NOT SUBMITTED ⚪")
            
            # Styling for the status column
            def style_status(val):
                color = '#2ecc71' if 'PASSED' in val else ('#e74c3c' if 'ERR' in val else ('#f39c12' if 'WRONG' in val else '#95a5a6'))
                return f'background-color: {color}; color: white; font-weight: bold'

            # Modern Streamlit 2026 Dataframe
            st.dataframe(
                merged[['student_name', 'status']].style.map(style_status, subset=['status']), 
                width="stretch"
            )
            st.divider()
            
            if not s_df.empty:
                target = st.selectbox("🔍 Inspect Student Code:", s_df['name'].tolist())
                student_row = s_df[s_df['name'] == target].iloc[0]
                col1, col2 = st.columns([2,1])
                with col1:
                    st.code(student_row['code'], language="python")
                with col2:
                    st.info(f"**Output:**\n{student_row['output']}")
                    st.write(f"Status: {student_row['status']}")
        else:
            st.warning("No students found. Add them in Management tab.")

    with tab_settings:
        st.header("🛠️ Class Administration")
        
        # 1. NEW CLASS & PERIOD CREATION
        with st.expander("🆕 Create New Class / Period"):
            c1, c2 = st.columns(2)
            new_c_name = c1.text_input("New Class Name:")
            new_c_period = c2.selectbox("For Period:", ["1", "2", "3", "4", "5", "6", "7", "8"], key="create_p")
            
            if st.button("Add Class/Period"):
                if new_c_name:
                    # Create anchor in rosters
                    supabase.table("rosters").insert({
                        "teacher_name": teacher_name, 
                        "class_name": new_c_name, 
                        "period": str(new_c_period), 
                        "student_name": "Teacher_Admin"
                    }).execute()
                    st.success("Created! Refreshing...")
                    time.sleep(1)
                    st.rerun()

        # 2. ASSIGNMENT BROADCAST (Delete-then-Insert logic)
        with st.expander("🎯 Set Assignment for Current Period", expanded=True):
            new_desc = st.text_area("Task (Markdown):", value=task['task_description'])
            ca, cb = st.columns(2)
            gi = ca.text_input("Expected Input:", value=task['goal_input'])
            go = cb.text_input("Expected Output:", value=task['expected_output'])
            
            if st.button("Broadcast to Students"):
                supabase.table("current_task").delete().eq("class_name", sel_class).eq("period", sel_period).execute()
                supabase.table("current_task").insert({
                    "class_name": sel_class, "period": sel_period,
                    "task_description": new_desc, "goal_input": gi, "expected_output": go
                }).execute()
                st.success("Broadcast successful!")
                time.sleep(1)
                st.rerun()

        # 3. ROSTER MANAGEMENT
        with st.expander("👥 Manage Student Roster"):
            st.caption(f"Editing roster for {sel_class} - Period {sel_period}")
            raw_names = st.text_area("Paste names (one per line):")
            if st.button("Save Roster"):
                names_list = [n.strip() for n in raw_names.split("\n") if n.strip()]
                if names_list:
                    data = [{"teacher_name": teacher_name, "class_name": sel_class, "period": sel_period, "student_name": n} for n in names_list]
                    supabase.table("rosters").delete().eq("class_name", sel_class).eq("period", sel_period).execute()
                    supabase.table("rosters").insert(data).execute()
                    st.success(f"Saved {len(names_list)} students.")
                    time.sleep(1)
                    st.rerun()

        if st.button("🧨 Reset Submissions for this Period"):
            supabase.table("submissions").delete().eq("class_name", sel_class).eq("period", sel_period).execute()
            st.rerun()

# --- STUDENT VIEW ---
else:
    st.title(f"📝 {sel_class} - P{sel_period}")
    if task['task_description']:
        with st.container(border=True):
            st.markdown(task['task_description'])
            st.caption(f"Input Target: `{task['goal_input']}` | Expected: `{task['expected_output']}`")
    
    roster_data = supabase.table("rosters").select("student_name").eq("class_name", sel_class).eq("period", sel_period).execute().data
    names = [r['student_name'] for r in roster_data] if roster_data else ["Roster Not Found"]
    
    current_student = st.selectbox("Select Your Name:", names)
    code_input = st.text_area("Python Editor:", height=300)
    
    if st.button("🚀 Run & Submit"):
        with st.spinner("Processing..."):
            status, output = run_code_in_sandbox(code_input, task['goal_input'])
            
        clean_out = str(output).replace(" ", "").strip()
        clean_target = str(task['expected_output']).replace(" ", "").strip()
        
        f_status = status
        if status == "SUCCESS":
            f_status = "PASSED ✅" if clean_out == clean_target else "WRONG OUTPUT ❌"
        
        supabase.table("submissions").upsert({
            "name": current_student, "class_name": sel_class, "period": sel_period,
            "code": code_input, "status": f_status, "output": str(output)
        }, on_conflict="name, class_name, period").execute()
        
        if "PASSED" in f_status:
            st.success(f"Success! Output: {output}")
        else:
            st.warning(f"Result: {f_status} | Output: {output}")