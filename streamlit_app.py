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
            "email": st.query_params.get("user_email"),
            "name": st.query_params.get("user_name"),
            "role": st.query_params.get("user_role")
        }
    else:
        st.session_state.authenticated = False

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
                    st.session_state.user_info = {"email": user['email'], "name": user['full_name'], "role": user['role']}
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

if not st.session_state.get("authenticated"):
    login_ui()
    st.stop()

user_data = st.session_state.get("user_info", {})
role = user_data.get('role', 'student')
user_fullname = user_data.get('name', 'User')

# --- 3. SANDBOX ENGINE ---
def run_code_in_sandbox(code, test_input):
    payload = {"source_code": code, "language_id": 71, "stdin": str(test_input) if test_input else ""}
    try:
        res = requests.post(f"{PUBLIC_MIRROR}/submissions?wait=true", json=payload, timeout=20)
        data = res.json()
        stdout, stderr = data.get("stdout"), data.get("stderr")
        if stderr: return "RUNTIME_ERR", stderr
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
        else:
            sel_class, sel_period = "Unassigned", "0"
    
    if st.button("🚪 Logout"):
        st.query_params.clear()
        st.session_state.clear()
        st.rerun()

def get_task():
    try:
        res = supabase.table("current_task").select("*").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
        return res[0] if res else None
    except Exception:
        return None

task_record = get_task()
task_display = task_record if task_record else {"goal_input": "", "expected_output": "", "task_description": ""}

# --- 5. MAIN INTERFACE ---
if role == "teacher":
    st_autorefresh(interval=30000, key="datarefresh")
    t1, t2 = st.tabs(["🏆 Leaderboard", "⚙️ Assignment Tools"])
    
    with t1:
        st.header(f"Live Status: {sel_class} P{sel_period}")
        subs = supabase.table("submissions").select("*").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
        if subs:
            df = pd.DataFrame(subs)
            st.dataframe(df[['name', 'status', 'output']], hide_index=True)
        else:
            st.info("No submissions yet.")

    with t2:
        st.header("Assignment Configuration")
        with st.form("teacher_task_form"):
            new_desc = st.text_area("Instructions:", value=task_display.get('task_description', ''))
            gi = st.text_input("Expected Input:", value=task_display.get('goal_input', ''))
            go = st.text_input("Expected Output:", value=task_display.get('expected_output', ''))
            
            if st.form_submit_button("🚀 Update Assignment"):
                try:
                    # STEP 1: Delete any existing task for this specific class/period
                    # This clears the way so we don't have to worry about ID conflicts.
                    supabase.table("current_task").delete().eq("class_name", sel_class).eq("period", str(sel_period)).execute()
                    
                    # STEP 2: Insert the fresh task. 
                    # We do NOT send an ID. The database will pick the next valid available ID.
                    payload = {
                        "class_name": sel_class,
                        "period": str(sel_period),
                        "task_description": new_desc,
                        "goal_input": gi,
                        "expected_output": go
                    }
                    supabase.table("current_task").insert(payload).execute()
                    
                    st.success("Task Updated!")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"Database Error: {e}")

else: # STUDENT VIEW
    st.title(f"🚀 {sel_class} - P{sel_period}")
    if task_display.get('task_description'):
        st.markdown(task_display['task_description'])
        st.caption(f"Input: `{task_display.get('goal_input')}` | Expected: `{task_display.get('expected_output')}`")
    
    btns = [{"name": "Run & Submit", "feather": "Play", "primary": True, "show_name": True, "always_on": True}]
    response = code_editor("# Write code here...", lang="python", theme="monokai", buttons=btns)
    
    if response.get("type") == "submit" and response.get("text"):
        code_input = response["text"]
        with st.spinner("Testing..."):
            status, output = run_code_in_sandbox(code_input, task_display.get('goal_input', ''))
        
        c_out = str(output).replace(" ", "").strip()
        c_target = str(task_display.get('expected_output', '')).replace(" ", "").strip()
        f_status = "PASSED ✅" if (status == "SUCCESS" and c_out == c_target) else "FAILED ❌"
        
        try:
            # Similar logic for students: Delete old submission and insert new to avoid ID issues
            supabase.table("submissions").delete().eq("name", user_fullname).eq("class_name", sel_class).eq("period", str(sel_period)).execute()
            
            sub_payload = {
                "name": user_fullname, 
                "class_name": sel_class, 
                "period": str(sel_period), 
                "code": code_input, 
                "status": f_status, 
                "output": str(output)
            }
            supabase.table("submissions").insert(sub_payload).execute()
            st.success(f"Graded: {f_status}")
        except Exception as e:
            st.error(f"Submission Error: {e}")
