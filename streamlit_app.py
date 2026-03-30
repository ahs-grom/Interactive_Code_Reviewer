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
    T_PASS = st.secrets["TEACHER_PASSWORD"]
    S_PASS = st.secrets["STUDENT_PASSWORD"]
except Exception as e:
    st.error("🚨 Configuration Error: Missing Secrets (Passwords or Supabase).")
    st.stop()

PUBLIC_MIRROR = "https://ce.judge0.com" 

# --- 2. AUTHENTICATION SESSION STATE ---
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

# --- 3. THE SANDBOX ENGINE ---
def run_code_in_sandbox(code, test_input):
    payload = {"source_code": code, "language_id": 71, "stdin": str(test_input) if test_input else ""}
    try:
        res = requests.post(f"{PUBLIC_MIRROR}/submissions?wait=true", json=payload, timeout=20)
        data = res.json()
        stdout, stderr = data.get("stdout"), data.get("stderr")
        if stderr: return "RUNTIME_ERR", stderr
        return "SUCCESS", (stdout.strip() if stdout else "NO_PRINT")
    except:
        return "CONN_ERR", "Sandbox Offline"

# --- 4. SIDEBAR & CLASS LOADING ---
with st.sidebar:
    st.header(f"👋 Welcome, {st.session_state.role.title()}")
    teacher_name = st.text_input("Instructor Name:", value="Grom")
    
    # Dynamic Class Loading
    res = supabase.table("rosters").select("class_name").eq("teacher_name", teacher_name).execute().data
    available_classes = sorted(list(set([r['class_name'] for r in res]))) if res else ["Demo Class"]
    
    sel_class = st.selectbox("Current Class:", available_classes)
    sel_period = st.selectbox("Period:", ["1", "2", "3", "4", "5", "6", "7", "8"])
    
    if st.button("🚪 Logout"):
        st.session_state.role = None
        st.rerun()

# Database Helper
def get_task():
    res = supabase.table("current_task").select("*").eq("class_name", sel_class).eq("period", sel_period).execute().data
    return res[0] if res else {"goal_input": "", "expected_output": "", "task_description": ""}

task = get_task()

# --- 5. INTERFACE LOGIC ---

# TEACHER VIEW
if st.session_state.role == "teacher":
    tab_leader, tab_settings = st.tabs(["🏆 Leaderboard & Review", "⚙️ Teacher Settings"])
    
    with tab_leader:
        st.header(f"Live Review: {sel_class}")
        roster = supabase.table("rosters").select("student_name").eq("class_name", sel_class).eq("period", sel_period).execute().data
        subs = supabase.table("submissions").select("*").eq("class_name", sel_class).eq("period", sel_period).execute().data
        
        if roster:
            r_df = pd.DataFrame(roster)
            s_df = pd.DataFrame(subs) if subs else pd.DataFrame(columns=['name', 'status', 'code', 'output'])
            merged = pd.merge(r_df, s_df, left_on='student_name', right_on='name', how='left').fillna("NOT SUBMITTED ⚪")
            
            st.dataframe(merged[['student_name', 'status']], use_container_width=True)
            st.divider()
            
            if not s_df.empty:
                target = st.selectbox("🔍 Select Student Code to Inspect:", s_df['name'].tolist())
                student_row = s_df[s_df['name'] == target].iloc[0]
                col1, col2 = st.columns([2,1])
                col1.code(student_row['code'])
                col2.info(f"**Output:**\n{student_row['output']}")
        else:
            st.warning("No students in this class yet. Go to Settings to add them.")

    with tab_settings:
        st.header("🛠️ Management Tools")
        
        # ADD NEW CLASS (THE FIX YOU ASKED FOR)
        with st.expander("🆕 Create New Class"):
            new_c_name = st.text_input("New Class Name (e.g. AP CSA):")
            if st.button("Add Class to Dropdown"):
                # We insert a dummy entry into rosters to "initialize" the class name
                supabase.table("rosters").insert({"teacher_name": teacher_name, "class_name": new_c_name, "period": "1", "student_name": "Teacher_Admin"}).execute()
                st.success(f"{new_c_name} created! Refreshing...")
                st.rerun()

        # BROADCAST TASK
        with st.expander("🎯 Set Daily Assignment", expanded=True):
            new_desc = st.text_area("Markdown Instructions:", value=task['task_description'])
            c1, c2 = st.columns(2)
            gi = c1.text_input("Goal Input:", value=task['goal_input'])
            go = c2.text_input("Expected Output:", value=task['expected_output'])
            if st.button("Update Assignment"):
                supabase.table("current_task").upsert({"class_name": sel_class, "period": sel_period, "task_description": new_desc, "goal_input": gi, "expected_output": go}, on_conflict="class_name, period").execute()
                st.success("Updated!")

        # ROSTER UPLOAD
        with st.expander("👥 Manage Roster"):
            raw = st.text_area("Paste Student Names (one per line):")
            if st.button("Save Roster"):
                names = [n.strip() for n in raw.split("\n") if n.strip()]
                data = [{"teacher_name": teacher_name, "class_name": sel_class, "period": sel_period, "student_name": n} for n in names]
                supabase.table("rosters").upsert(data).execute()
                st.rerun()

# STUDENT VIEW
else:
    st.title(f"📝 {sel_class} - P{sel_period}")
    if task['task_description']:
        with st.container(border=True):
            st.markdown(task['task_description'])
            st.caption(f"Input: {task['goal_input']} | Expected: {task['expected_output']}")
    
    roster_res = supabase.table("rosters").select("student_name").eq("class_name", sel_class).eq("period", sel_period).execute().data
    names = [r['student_name'] for r in roster_res] if roster_res else ["Roster Not Found"]
    current_user = st.selectbox("Select Your Name:", names)
    code_in = st.text_area("Write Python Code:", height=300)
    
    if st.button("🚀 Run & Submit"):
        status, output = run_code_in_sandbox(code_in, task['goal_input'])
        clean_out, clean_target = str(output).replace(" ", "").strip(), str(task['expected_output']).replace(" ", "").strip()
        f_status = status
        if status == "SUCCESS": f_status = "PASSED ✅" if clean_out == clean_target else "WRONG OUTPUT ❌"
        
        supabase.table("submissions").upsert({"name": current_user, "class_name": sel_class, "period": sel_period, "code": code_in, "status": f_status, "output": str(output)}, on_conflict="name, class_name, period").execute()
        st.info(f"Result: {output}")