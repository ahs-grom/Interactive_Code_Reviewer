import streamlit as st
import requests
import pandas as pd
import time
from supabase import create_client
from streamlit_autorefresh import st_autorefresh

# --- 1. INITIALIZATION ---
st.set_page_config(page_title="CodeMaster LMS", layout="wide")

# Persistent Session State
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_info" not in st.session_state:
    st.session_state.user_info = {}

try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    supabase = create_client(url, key)
except Exception as e:
    st.error("🚨 Configuration Error: Supabase Secrets missing.")
    st.stop()

PUBLIC_MIRROR = "https://ce.judge0.com" 

# --- 2. AUTHENTICATION UI ---
def login_ui():
    st.title("🔐 CodeMaster Secure Login")
    st.markdown("Please enter your school credentials to access the workspace.")
    
    # Using a form container to handle 'Enter' key submissions
    with st.form("login_form"):
        email = st.text_input("School Email:").lower().strip()
        password = st.text_input("Password:", type="password")
        submit = st.form_submit_button("Login")
        
        if submit:
            # Query the database for the user
            try:
                res = supabase.table("users").select("*").eq("email", email).eq("password", password).execute().data
                if res:
                    user = res[0]
                    st.session_state.authenticated = True
                    st.session_state.user_info = {
                        "email": user['email'],
                        "name": user['full_name'],
                        "role": user['role']
                    }
                    st.success(f"Login successful! Loading {user['full_name']}...")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("Invalid email or password. Please try again.")
            except Exception as e:
                st.error(f"Authentication Error: {e}")

# Gatekeeper: If not logged in, stop everything else and show login
if not st.session_state.authenticated:
    login_ui()
    st.stop()

# Helper Variables
role = st.session_state.user_info['role']
user_fullname = st.session_state.user_info['name']

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
    st.header(f"👋 {role.title()} Portal")
    st.info(f"User: **{user_fullname}**")
    
    # Dynamic Class List based on Roster
    if role == "teacher":
        res = supabase.table("rosters").select("class_name").eq("teacher_name", user_fullname).execute().data
    else:
        res = supabase.table("rosters").select("class_name").eq("student_name", user_fullname).execute().data
    
    available_classes = sorted(list(set([r['class_name'] for r in res]))) if res else ["No Classes Found"]
    
    sel_class = st.selectbox("Current Class:", available_classes)
    sel_period = st.selectbox("Period:", ["1", "2", "3", "4", "5", "6", "7", "8"])
    
    st.divider()
    if st.button("🚪 Logout"):
        st.session_state.authenticated = False
        st.session_state.user_info = {}
        st.rerun()

def get_task():
    try:
        res = supabase.table("current_task").select("*").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
        return res[0] if res else {"goal_input": "", "expected_output": "", "task_description": ""}
    except:
        return {"goal_input": "", "expected_output": "", "task_description": "Initial Setup..."}

task = get_task()

# --- 5. MAIN INTERFACE ---

if role == "teacher":
    st_autorefresh(interval=30000, key="datarefresh")
    tab_leader, tab_settings = st.tabs(["🏆 Live Leaderboard", "⚙️ Management"])
    
    with tab_leader:
        st.header(f"Live Dashboard: {sel_class} P{sel_period}")
        roster = supabase.table("rosters").select("student_name").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
        subs = supabase.table("submissions").select("*").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
        
        if roster:
            r_df = pd.DataFrame(roster)
            s_df = pd.DataFrame(subs) if subs else pd.DataFrame(columns=['name', 'status', 'code', 'output', 'created_at'])
            if not s_df.empty:
                s_df['created_at'] = pd.to_datetime(s_df['created_at']).dt.tz_convert('US/Eastern')

            merged = pd.merge(r_df, s_df, left_on='student_name', right_on='name', how='left')
            merged = merged.sort_values(by='created_at', ascending=True, na_position='last')
            merged['Time'] = merged['created_at'].dt.strftime('%H:%M:%S').fillna("--")
            merged['status'] = merged['status'].fillna("NOT SUBMITTED ⚪")
            
            def style_status(val):
                color = '#2ecc71' if 'PASSED' in val else ('#e74c3c' if 'ERR' in val else ('#f39c12' if 'WRONG' in val else '#95a5a6'))
                return f'background-color: {color}; color: white; font-weight: bold'

            st.dataframe(
                merged[['student_name', 'Time', 'status']].style.map(style_status, subset=['status']), 
                column_config={
                    "student_name": st.column_config.TextColumn("Student Name", width="medium"),
                    "Time": st.column_config.TextColumn("Time", width="small"),
                    "status": st.column_config.TextColumn("Current Status", width="medium"),
                },
                width="stretch", hide_index=True
            )
            
            if not s_df.empty:
                st.divider()
                target = st.selectbox("🔍 Inspect Student Code:", s_df['name'].tolist())
                student_row = s_df[s_df['name'] == target].iloc[0]
                c1, c2 = st.columns([2,1])
                c1.code(student_row['code'])
                c2.info(f"**Output:**\n{student_row['output']}")
        else:
            st.warning("No students in this roster yet.")

    with tab_settings:
        st.header("🛠️ Admin Tools")
        
        with st.expander("👤 Register & Add Student"):
            c1, c2 = st.columns(2)
            reg_email = c1.text_input("School Email:")
            reg_name = c2.text_input("Full Name:")
            reg_pass = st.text_input("Initial Password:", value="python2026")
            if st.button("Create Account"):
                if reg_email and reg_name:
                    supabase.table("users").upsert({"email": reg_email.lower().strip(), "password": reg_pass, "full_name": reg_name, "role": "student"}).execute()
                    supabase.table("rosters").upsert({"teacher_name": user_fullname, "class_name": sel_class, "period": str(sel_period), "student_name": reg_name}, on_conflict="class_name, period, student_name").execute()
                    st.success(f"Account for {reg_name} is active.")
                    time.sleep(0.5)
                    st.rerun()

        with st.expander("🎯 Assignment Broadcast"):
            new_desc = st.text_area("Markdown Instructions:", value=task['task_description'], height=200)
            ca, cb = st.columns(2)
            gi = ca.text_input("Target Input (STDIN):", value=task['goal_input'])
            go = cb.text_input("Target Output:", value=task['expected_output'])
            if st.button("Update Assignment"):
                supabase.table("current_task").upsert({"class_name": sel_class, "period": str(sel_period), "task_description": new_desc, "goal_input": gi, "expected_output": go}, on_conflict="class_name, period").execute()
                st.success("Updated!")

else: # STUDENT VIEW
    st.title(f"🚀 {sel_class} - P{sel_period}")
    st.write(f"Identity Verified: **{user_fullname}**")
    
    if task['task_description']:
        with st.container(border=True):
            st.markdown(task['task_description'])
            st.caption(f"Input: `{task['goal_input']}` | Expected: `{task['expected_output']}`")
    
    code_input = st.text_area("Python Editor:", height=300, key="std_editor_v11")
    
    if st.button("🚀 Run & Submit"):
        with st.spinner("Running tests..."):
            status, output = run_code_in_sandbox(code_input, task['goal_input'])
        
        clean_out, clean_target = str(output).replace(" ", "").strip(), str(task['expected_output']).replace(" ", "").strip()
        f_status = "PASSED ✅" if (status == "SUCCESS" and clean_out == clean_target) else status
        if status == "SUCCESS" and clean_out != clean_target: f_status = "WRONG OUTPUT ❌"
        
        supabase.table("submissions").upsert({
            "name": user_fullname, "class_name": sel_class, "period": str(sel_period),
            "code": code_input, "status": f_status, "output": str(output)
        }, on_conflict="name, class_name, period").execute()
        
        if "PASSED" in f_status:
            st.success(f"Result: {f_status}")
        else:
            st.warning(f"Result: {f_status}")