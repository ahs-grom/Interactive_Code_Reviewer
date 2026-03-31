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
    T_PASS = st.secrets["TEACHER_PASSWORD"]
    S_PASS = st.secrets["STUDENT_PASSWORD"]
except Exception as e:
    st.error("🚨 Configuration Error: Check your Streamlit Secrets.")
    st.stop()

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
    payload = {"source_code": code, "language_id": 71, "stdin": str(test_input) if test_input else ""}
    try:
        res = requests.post(f"{PUBLIC_MIRROR}/submissions?wait=true", json=payload, timeout=20)
        data = res.json()
        stdout = data.get("stdout")
        stderr = data.get("stderr")
        if stderr: return "RUNTIME_ERR", stderr
        return "SUCCESS", (stdout.strip() if stdout else "NO_PRINT")
    except:
        return "CONN_ERR", "Sandbox Offline"

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header(f"👋 {st.session_state.role.title()} Portal")
    teacher_name = st.text_input("Instructor Name:", value="Grom")
    
    res = supabase.table("rosters").select("class_name").eq("teacher_name", teacher_name).execute().data
    available_classes = sorted(list(set([r['class_name'] for r in res]))) if res else ["No Classes Found"]
    
    sel_class = st.selectbox("Current Class:", available_classes)
    sel_period = st.selectbox("Period:", ["1", "2", "3", "4", "5", "6", "7", "8"])
    
    st.divider()
    if st.button("🚪 Logout"):
        st.session_state.role = None
        st.rerun()

def get_task():
    try:
        res = supabase.table("current_task").select("*").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
        return res[0] if res else {"goal_input": "", "expected_output": "", "task_description": ""}
    except:
        return {"goal_input": "", "expected_output": "", "task_description": "Setup Required"}

task = get_task()

# --- 5. MAIN INTERFACE ---

if st.session_state.role == "teacher":
    tab_leader, tab_settings = st.tabs(["🏆 Leaderboard & Review", "⚙️ Management"])
    
    with tab_leader:
        st.header(f"Live Dashboard: {sel_class} P{sel_period}")
        roster = supabase.table("rosters").select("student_name").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
        subs = supabase.table("submissions").select("*").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
        
        if roster:
            r_df = pd.DataFrame(roster)
            s_df = pd.DataFrame(subs) if subs else pd.DataFrame(columns=['name', 'status', 'code', 'output'])
            merged = pd.merge(r_df, s_df, left_on='student_name', right_on='name', how='left').fillna("NOT SUBMITTED ⚪")
            
            def style_status(val):
                color = '#2ecc71' if 'PASSED' in val else ('#e74c3c' if 'ERR' in val else ('#f39c12' if 'WRONG' in val else '#95a5a6'))
                return f'background-color: {color}; color: white; font-weight: bold'

            st.dataframe(merged[['student_name', 'status']].style.map(style_status, subset=['status']), width="stretch")
            st.divider()
            
            if not s_df.empty:
                target = st.selectbox("🔍 Inspect Student Code:", s_df['name'].tolist())
                student_row = s_df[s_df['name'] == target].iloc[0]
                c1, c2 = st.columns([2,1])
                c1.code(student_row['code'])
                c2.info(f"**Output:**\n{student_row['output']}")
        else:
            st.warning("No students found in this period.")

    with tab_settings:
        st.header("🛠️ Class Administration")
        
        with st.expander("🆕 Create New Class / Period"):
            c1, c2 = st.columns(2)
            nc_name = c1.text_input("New Class Name:")
            nc_period = c2.selectbox("For Period:", ["1", "2", "3", "4", "5", "6", "7", "8"], key="cp_new")
            if st.button("Add Class/Period"):
                supabase.table("rosters").insert({
                    "teacher_name": teacher_name, 
                    "class_name": nc_name, 
                    "period": str(nc_period), 
                    "student_name": "Teacher_Admin"
                }).execute()
                st.success("New Class Initialized!")
                time.sleep(0.5)
                st.rerun()

        with st.expander("🎯 Set/Update Assignment", expanded=True):
            st.write(f"Editing: **{sel_class} - Period {sel_period}**")
            new_desc = st.text_area("Markdown Instructions:", value=task['task_description'], height=200)
            ca, cb = st.columns(2)
            gi = ca.text_input("Expected Input (STDIN):", value=task['goal_input'])
            go = cb.text_input("Expected Output:", value=task['expected_output'])
            
            if st.button("🚀 Broadcast to Students"):
                try:
                    # UPSERT handles both new tasks and updates to existing tasks
                    task_payload = {
                        "class_name": sel_class, 
                        "period": str(sel_period),
                        "task_description": new_desc, 
                        "goal_input": gi, 
                        "expected_output": go
                    }
                    # We specify the columns that define the "conflict"
                    supabase.table("current_task").upsert(task_payload, on_conflict="class_name, period").execute()
                    st.success("Task updated for all students!")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

        with st.expander("👥 Manage Student Roster"):
            raw_names = st.text_area("Names (one per line):", help="Overwrites the current roster for this period.")
            if st.button("Save Roster"):
                names_list = [n.strip() for n in raw_names.split("\n") if n.strip()]
                data = [{"teacher_name": teacher_name, "class_name": sel_class, "period": str(sel_period), "student_name": n} for n in names_list]
                supabase.table("rosters").delete().eq("class_name", sel_class).eq("period", str(sel_period)).execute()
                supabase.table("rosters").insert(data).execute()
                st.success(f"Roster updated for P{sel_period}!")
                time.sleep(0.5)
                st.rerun()

else: # STUDENT VIEW
    st.title(f"📝 {sel_class} - P{sel_period}")
    if task['task_description']:
        with st.container(border=True):
            st.markdown(task['task_description'])
            st.caption(f"Input Target: `{task['goal_input']}` | Expected: `{task['expected_output']}`")
    else:
        st.info("Waiting for teacher to post instructions...")
    
    roster_data = supabase.table("rosters").select("student_name").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
    names = [r['student_name'] for r in roster_data] if roster_data else ["Roster Not Found"]
    current_student = st.selectbox("Select Your Name:", names)
    code_input = st.text_area("Python Editor:", height=300, key="std_editor")
    
    if st.button("🚀 Run & Submit"):
        with st.spinner("Executing..."):
            status, output = run_code_in_sandbox(code_input, task['goal_input'])
            
        clean_out = str(output).replace(" ", "").strip()
        clean_target = str(task['expected_output']).replace(" ", "").strip()
        
        f_status = status
        if status == "SUCCESS":
            f_status = "PASSED ✅" if clean_out == clean_target else "WRONG OUTPUT ❌"
        
        supabase.table("submissions").upsert({
            "name": current_student, "class_name": sel_class, "period": str(sel_period),
            "code": code_input, "status": f_status, "output": str(output)
        }, on_conflict="name, class_name, period").execute()
        
        if "PASSED" in f_status:
            st.success(f"Output: {output}")
        else:
            st.warning(f"Status: {f_status} | Output: {output}")