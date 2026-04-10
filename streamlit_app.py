import streamlit as st
import requests
import pandas as pd
import time
from supabase import create_client
from streamlit_autorefresh import st_autorefresh
from code_editor import code_editor

# --- 1. INITIALIZATION & PERSISTENCE ---
st.set_page_config(page_title="CodeMaster LMS", layout="wide")

# Check query params to persist login across refreshes
if "authenticated" not in st.session_state:
    # Query params return strings; we check for existence
    if st.query_params.get("user_email"):
        st.session_state.authenticated = True
        st.session_state.user_info = {
            "email": st.query_params["user_email"],
            "name": st.query_params["user_name"],
            "role": st.query_params["user_role"]
        }
    else:
        st.session_state.authenticated = False

if "user_info" not in st.session_state:
    st.session_state.user_info = {}

try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    supabase = create_client(url, key)
except Exception:
    st.error("🚨 Configuration Error: Check Streamlit Secrets.")
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
                    # Set query params for persistence
                    st.query_params["user_email"] = user['email']
                    st.query_params["user_name"] = user['full_name']
                    st.query_params["user_role"] = user['role']
                    st.success("Login successful!")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("Invalid email or password.")
            except Exception as e:
                st.error(f"Auth Error: {e}")

if not st.session_state.authenticated:
    login_ui()
    st.stop()

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
        if stderr: 
            return "RUNTIME_ERR", stderr
        return "SUCCESS", (stdout.strip() if stdout else "NO_PRINT")
    except Exception:
        return "CONN_ERR", "Offline"

# --- 4. SIDEBAR & LOGIC ---
with st.sidebar:
    st.header(f"👋 {role.title()} Portal")
    st.info(f"User: **{user_fullname}**")
    
    if role == "teacher":
        res = supabase.table("rosters").select("class_name, period").eq("teacher_name", user_fullname).execute().data
        if res:
            available_classes = sorted(list(set([r['class_name'] for r in res])))
            sel_class = st.selectbox("Current Class:", available_classes)
            periods = sorted(list(set([str(r['period']) for r in res if r['class_name'] == sel_class])))
            sel_period = st.selectbox("Period:", periods)
        else:
            sel_class = "No Classes"
            sel_period = "0"
    else:
        res = supabase.table("rosters").select("class_name, period").eq("student_name", user_fullname).execute().data
        if res:
            available_classes = sorted(list(set([r['class_name'] for r in res])))
            sel_class = st.selectbox("Current Class:", available_classes)
            match = next((item for item in res if item["class_name"] == sel_class), None)
            sel_period = str(match["period"]) if match else "1"
            st.success(f"📌 Locked to Period: **{sel_period}**")
        else:
            sel_class = "Unassigned"
            sel_period = "0"
            st.warning("No roster found.")
    
    st.divider()
    if st.button("🚪 Logout"):
        st.session_state.authenticated = False
        st.session_state.user_info = {}
        st.query_params.clear()
        st.rerun()

def get_task():
    try:
        res = supabase.table("current_task").select("*").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
        if res:
            return res[0]
        return {"goal_input": "", "expected_output": "", "task_description": "No assignment set yet."}
    except Exception:
        return {"goal_input": "", "expected_output": "", "task_description": "Setup Required"}

task = get_task()

# --- 5. MAIN INTERFACE ---
if role == "teacher":
    st_autorefresh(interval=30000, key="datarefresh")
    tab_leader, tab_settings = st.tabs(["🏆 Live Leaderboard", "⚙️ Admin Tools"])
    
    with tab_leader:
        st.header(f"Dashboard: {sel_class} P{sel_period}")
        roster_res = supabase.table("rosters").select("student_name").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
        subs_res = supabase.table("submissions").select("*").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
        
        if roster_res:
            r_df = pd.DataFrame(roster_res)
            r_df = r_df[r_df['student_name'] != "_Admin_"]
            
            if subs_res:
                s_df = pd.DataFrame(subs_res)
                s_df['created_at'] = pd.to_datetime(s_df['created_at'], errors='coerce')
                try: 
                    s_df['created_at'] = s_df['created_at'].dt.tz_convert('US/Eastern')
                except Exception: 
                    pass
            else:
                s_df = pd.DataFrame(columns=['name', 'status', 'code', 'output', 'created_at'])

            merged = pd.merge(r_df, s_df, left_on='student_name', right_on='name', how='left')
            merged = merged.sort_values(by='created_at', ascending=True, na_position='last')
            
            merged['Time'] = merged['created_at'].dt.strftime('%H:%M:%S').fillna("--") if 'created_at' in merged and not merged['created_at'].isna().all() else "--"
            merged['status'] = merged['status'].fillna("NOT SUBMITTED ⚪")
            
            def style_status(val):
                color = '#2ecc71' if 'PASSED' in val else ('#e74c3c' if 'ERR' in val else ('#f39c12' if 'WRONG' in val else '#95a5a6'))
                return f'background-color: {color}; color: white; font-weight: bold'

            st.dataframe(
                merged[['student_name', 'Time', 'status']].style.map(style_status, subset=['status']), 
                column_config={"student_name": "Student", "Time": "Time", "status": "Status"},
                width="stretch", hide_index=True
            )
            
            if not s_df.empty:
                st.divider()
                target = st.selectbox("🔍 Inspect Code:", s_df['name'].tolist())
                row = s_df[s_df['name'] == target].iloc[0]
                c1, c2 = st.columns(2)
                with c1:
                    st.subheader("Code")
                    st.code(row['code'])
                with c2:
                    st.subheader("Output")
                    st.info(row['output'])
        else:
            st.warning("No students in roster.")

    with tab_settings:
        st.header("🛠️ Management")
        
        with st.expander("🏫 Class & Period Management"):
            c1, c2 = st.columns(2)
            nc_name = c1.text_input("New Class Name:")
            nc_period = c2.selectbox("Period:", [str(i) for i in range(1,9)], key="nc_p")
            if st.button("Initialize Class"):
                try:
                    # Explicitly omit 'id' so Supabase doesn't conflict on auto-incrementing PKey
                    supabase.table("rosters").upsert({
                        "teacher_name": user_fullname, "class_name": nc_name, 
                        "period": str(nc_period), "student_name": "_Admin_"
                    }, on_conflict="class_name, period, student_name").execute()
                    st.success("Initialized!")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e: 
                    st.error(f"Error: {e}")

        with st.expander("👤 Register Student"):
            sc1, sc2 = st.columns(2)
            reg_email = sc1.text_input("Email:")
            reg_name = sc2.text_input("Full Name:")
            reg_pass = st.text_input("Password:", value="python2026")
            if st.button("Create Account"):
                try:
                    supabase.table("users").upsert({"email": reg_email.lower().strip(), "password": reg_pass, "full_name": reg_name, "role": "student"}).execute()
                    supabase.table("rosters").upsert({
                        "teacher_name": user_fullname, "class_name": sel_class, 
                        "period": str(sel_period), "student_name": reg_name
                    }, on_conflict="class_name, period, student_name").execute()
                    st.success("Added!")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e: 
                    st.error(f"Error: {e}")

        with st.expander("🎯 Set Assignment Details"):
            new_desc = st.text_area("Instructions (Markdown):", value=task.get('task_description', ''), height=200)
            ca, cb = st.columns(2)
            gi = ca.text_input("Test Input:", value=task.get('goal_input', ''))
            go = cb.text_input("Expected Output:", value=task.get('expected_output', ''))
            if st.button("🚀 Push to Students"):
                try:
                    payload = {
                        "class_name": sel_class, 
                        "period": str(sel_period), 
                        "task_description": new_desc, 
                        "goal_input": gi, 
                        "expected_output": go
                    }
                    # If current_task has an 'id' column as PKey, we must include it or handle correctly.
                    # We attempt to upsert based on the unique combo of class/period.
                    if task.get("id"):
                        payload["id"] = task["id"]
                    
                    supabase.table("current_task").upsert(payload, on_conflict="class_name, period").execute()
                    st.success("Assignment Updated!")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"Database Save Failed: {e}")

else: # STUDENT VIEW
    st.title(f"🚀 {sel_class} - P{sel_period}")
    
    if task.get('task_description'):
        with st.container(border=True):
            st.markdown(task['task_description'])
            st.caption(f"Input: `{task.get('goal_input', '')}` | Expected: `{task.get('expected_output', '')}`")
    
    st.write("### Python Editor")
    
    custom_btns = [{
        "name": "Submit Code",
        "feather": "Play",
        "primary": True,
        "show_name": True,
        "always_on": True
    }]
    
    response = code_editor(
        "print('Hello World')", 
        lang="python", 
        theme="monokai", 
        height=[15, 30],
        buttons=custom_btns,
        options={"tabSize": 4}
    )
    
    code_input = response.get("text", "")

    if st.button("🚀 Run & Submit"):
        if not code_input or code_input == "print('Hello World')":
            st.warning("Please write your code and click 'Submit Code' inside the editor first!")
        else:
            with st.spinner("Testing..."):
                status, output = run_code_in_sandbox(code_input, task.get('goal_input', ''))
            
            clean_out = str(output).replace(" ", "").strip()
            clean_target = str(task.get('expected_output', '')).replace(" ", "").strip()
            
            f_status = "PASSED ✅" if (status == "SUCCESS" and clean_out == clean_target) else status
            if status == "SUCCESS" and clean_out != clean_target: 
                f_status = "WRONG OUTPUT ❌"
            
            try:
                sub_payload = {
                    "name": user_fullname, 
                    "class_name": sel_class, 
                    "period": str(sel_period), 
                    "code": code_input, 
                    "status": f_status, 
                    "output": str(output)
                }
                supabase.table("submissions").upsert(sub_payload, on_conflict="name, class_name, period").execute()
                if "PASSED" in f_status: 
                    st.success(f"Result: {f_status}")
                else: 
                    st.warning(f"Result: {f_status}")
            except Exception as e:
                st.error("Submission failed.")
                st.exception(e)
