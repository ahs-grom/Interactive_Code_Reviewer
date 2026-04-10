import streamlit as st
import requests
import pandas as pd
import time
from supabase import create_client
from streamlit_autorefresh import st_autorefresh
from code_editor import code_editor

# --- 1. INITIALIZATION & PERSISTENCE ---
st.set_page_config(page_title="CodeMaster LMS", layout="wide")

if "authenticated" not in st.session_state:
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
            sel_class, sel_period = "No Classes", "0"
    else:
        res = supabase.table("rosters").select("class_name, period").eq("student_name", user_fullname).execute().data
        if res:
            available_classes = sorted(list(set([r['class_name'] for r in res])))
            sel_class = st.selectbox("Current Class:", available_classes)
            match = next((item for item in res if item["class_name"] == sel_class), None)
            sel_period = str(match["period"]) if match else "1"
            st.success(f"📌 Period: **{sel_period}**")
        else:
            sel_class, sel_period = "Unassigned", "0"
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
        return res[0] if res else {"goal_input": "", "expected_output": "", "task_description": "No assignment set yet."}
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
                try: s_df['created_at'] = s_df['created_at'].dt.tz_convert('US/Eastern')
                except Exception: pass
            else:
                s_df = pd.DataFrame(columns=['name', 'status', 'code', 'output', 'created_at'])

            merged = pd.merge(r_df, s_df, left_on='student_name', right_on='name', how='left')
            merged['Time'] = merged['created_at'].dt.strftime('%H:%M:%S').fillna("--") if 'created_at' in merged else "--"
            merged['status'] = merged['status'].fillna("NOT SUBMITTED ⚪")
            
            def style_status(val):
                color = '#2ecc71' if 'PASSED' in val else ('#e74c3c' if 'ERR' in val else ('#f39c12' if 'WRONG' in val else '#95a5a6'))
                return f'background-color: {color}; color: white; font-weight: bold'

            st.dataframe(merged[['student_name', 'Time', 'status']].style.map(style_status, subset=['status']), hide_index=True)
        else:
            st.warning("No students in roster.")

    with tab_settings:
        st.header("🛠️ Management")
        with st.expander("🎯 Set Assignment Details"):
            new_desc = st.text_area("Instructions:", value=task.get('task_description', ''))
            gi = st.text_input("Test Input:", value=task.get('goal_input', ''))
            go = st.text_input("Expected Output:", value=task.get('expected_output', ''))
            if st.button("🚀 Push to Students"):
                payload = {"class_name": sel_class, "period": str(sel_period), "task_description": new_desc, "goal_input": gi, "expected_output": go}
                if task.get("id"): payload["id"] = task["id"]
                supabase.table("current_task").upsert(payload, on_conflict="class_name, period").execute()
                st.success("Updated!"); time.sleep(0.5); st.rerun()

else: # STUDENT VIEW
    st.title(f"🚀 {sel_class} - P{sel_period}")
    if task.get('task_description'):
        with st.container(border=True):
            st.markdown(task['task_description'])
            st.caption(f"Input: `{task.get('goal_input', '')}` | Expected: `{task.get('expected_output', '')}`")
    
    st.write("### Python Editor")
    
    # We use a single integrated button to avoid sync issues
    custom_btns = [{"name": "Run & Submit", "feather": "Play", "primary": True, "show_name": True, "always_on": True}]
    response = code_editor("# Write code here...", lang="python", theme="monokai", buttons=custom_btns)
    
    # Check if the internal button was clicked
    if response.get("type") == "submit" and response.get("text"):
        code_input = response["text"]
        with st.spinner("Testing..."):
            status, output = run_code_in_sandbox(code_input, task.get('goal_input', ''))
            
        clean_out = str(output).replace(" ", "").strip()
        clean_target = str(task.get('expected_output', '')).replace(" ", "").strip()
        f_status = "PASSED ✅" if (status == "SUCCESS" and clean_out == clean_target) else status
        if status == "SUCCESS" and clean_out != clean_target: f_status = "WRONG OUTPUT ❌"
        
        try:
            sub_payload = {
                "name": user_fullname, "class_name": sel_class, "period": str(sel_period), 
                "code": code_input, "status": f_status, "output": str(output)
            }
            supabase.table("submissions").upsert(sub_payload, on_conflict="name, class_name, period").execute()
            st.toast(f"Result: {f_status}")
            if "PASSED" in f_status: st.success(f_status)
            else: st.warning(f_status)
        except Exception as e:
            st.error(f"Save failed: {e}")
