import streamlit as st
import requests
import pandas as pd
import time
from supabase import create_client
from streamlit_autorefresh import st_autorefresh

# --- 1. INITIALIZATION ---
st.set_page_config(page_title="CodeMaster LMS", layout="wide")

# Persistent Session State to prevent logout on refresh
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
    with st.form("login_form"):
        email = st.text_input("School Email:").lower().strip()
        password = st.text_input("Password:", type="password")
        submit = st.form_submit_button("Login")
        
        if submit:
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
                    st.success(f"Login successful!")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("Invalid email or password.")
            except Exception as e:
                st.error(f"Auth Error: {e}")

if not st.session_state.authenticated:
    login_ui()
    st.stop()

# Helper Variables
role = st.session_state.user_info.get('role', 'student')
user_fullname = st.session_state.user_info.get('name', 'User')

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
        return "CONN_ERR", "Offline"

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header(f"👋 {role.title()} Portal")
    st.info(f"User: **{user_fullname}**")
    
    if role == "teacher":
        res = supabase.table("rosters").select("class_name").eq("teacher_name", user_fullname).execute().data
    else:
        res = supabase.table("rosters").select("class_name").eq("student_name", user_fullname).execute().data
    
    available_classes = sorted(list(set([r['class_name'] for r in res]))) if res else ["No Classes Found"]
    
    # FIXED: Added missing closing parenthesis below
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
        return {"goal_input": "", "expected_output": "", "task_description": "Setup Required"}

task = get_task()

# --- 5. MAIN INTERFACE ---
if role == "teacher":
    st_autorefresh(interval=30000, key="datarefresh")
    tab_leader, tab_settings = st.tabs(["🏆 Live Leaderboard", "⚙️ Admin Tools"])
    
    with tab_leader:
        st.header(f"Live Dashboard: {sel_class} P{sel_period}")
        roster = supabase.table("rosters").select("student_name").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
        subs = supabase.table("submissions").select("*").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
        
        if roster:
            r_df = pd.DataFrame(roster)
            if subs:
                s_df = pd.DataFrame(subs)
                s_df['created_at'] = pd.to_datetime(s_df['created_at'], errors='coerce')
                try:
                    s_df['created_at'] = s_df['created_at'].dt.tz_convert('US/Eastern')
                except: pass
            else:
                s_df = pd.DataFrame(columns=['name', 'status', 'code', 'output', 'created_at'])
                s_df['created_at'] = pd.to_datetime(s_df['created_at'])

            merged = pd.merge(r_df, s_df, left_on='student_name', right_on='name', how='left')
            merged = merged.sort_values(by='created_at', ascending=True, na_position='last')
            
            if not merged['created_at'].isna().all():
                merged['Time'] = merged['created_at'].dt.strftime('%H:%M:%S').fillna("--")
            else:
                merged['Time'] = "--"
                
            merged['status'] = merged['status'].fillna("NOT SUBMITTED ⚪")
            
            def style_status(val):
                color = '#2ecc71' if 'PASSED' in val else ('#e74c3c' if 'ERR' in val else ('#f39c12' if 'WRONG' in val else '#95a5a6'))
                return f'background-color: {color}; color: white; font-weight: bold'

            st.dataframe(
                merged[['student_name', 'Time', 'status']].style.map(style_status, subset=['status']), 
                column_config={
                    "student_name": st.column_config.TextColumn("Student Name", width="medium"),
                    "Time": st.column_config.TextColumn("Time", width="small"),
                    "status": st.column_config.TextColumn("Status", width="medium"),
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
            st.warning("No students in roster.")

    with tab_settings:
        st.header("🛠️ Management")
        with st.expander("👤 Register Student"):
            c1, c2 = st.columns
