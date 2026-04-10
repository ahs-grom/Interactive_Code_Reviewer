import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, timezone
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
        if st.form_submit_button("Login"):
            try:
                res = supabase.table("users").select("*").eq("email", email).eq("password", password).execute().data
                if res:
                    user = res[0]
                    st.session_state.authenticated = True
                    st.session_state.user_info = {"email": user['email'], "name": user['full_name'], "role": user['role']}
                    st.query_params["user_email"] = user['email']
                    st.query_params["user_name"] = user['full_name']
                    st.query_params["user_role"] = user['role']
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

# --- 3. SIDEBAR ---
with st.sidebar:
    st.header(f"👋 {role.title()} Portal")
    st.info(f"User: **{user_fullname}**")
    
    if role == "teacher":
        res = supabase.table("rosters").select("class_name, period").eq("teacher_name", user_fullname).execute().data
    else:
        res = supabase.table("rosters").select("class_name, period").eq("student_name", user_fullname).execute().data
    
    if res:
        classes = sorted(list(set([r['class_name'] for r in res])))
        sel_class = st.selectbox("Class:", classes)
        periods = sorted(list(set([str(r['period']) for r in res if r['class_name'] == sel_class])))
        sel_period = st.selectbox("Period:", periods)
    else:
        sel_class, sel_period = "Unassigned", "0"

    if st.button("🚪 Logout"):
        st.query_params.clear()
        st.session_state.clear()
        st.rerun()

# --- 4. DATA FETCH ---
def get_task():
    try:
        res = supabase.table("current_task").select("*").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
        return res[0] if res else {"task_description": "", "goal_input": "", "expected_output": ""}
    except Exception:
        return {"task_description": "", "goal_input": "", "expected_output": ""}

current_task = get_task()

# --- 5. MAIN INTERFACE ---
if role == "teacher":
    # Refreshes exactly every 20 seconds to prevent chaotic updates
    st_autorefresh(interval=20000, key="datarefresh")
    t1, t2 = st.tabs(["🏆 Leaderboard", "⚙️ Setup"])
    
    with t1:
        st.subheader(f"Dashboard: {sel_class} P{sel_period}")
        subs = supabase.table("submissions").select("*").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
        
        if subs:
            df = pd.DataFrame(subs)
            
            # Sort primarily by updated_at so recent submissions drop to the bottom
            if 'updated_at' in df.columns:
                df['updated_at'] = pd.to_datetime(df['updated_at'])
                df = df.sort_values('updated_at', ascending=True).reset_index(drop=True)
            elif 'created_at' in df.columns:
                df['created_at'] = pd.to_datetime(df['created_at'])
                df = df.sort_values('created_at', ascending=True).reset_index(drop=True)
            elif 'id' in df.columns:
                df = df.sort_values('id', ascending=True).reset_index(drop=True)
            
            display_df = df[['name', 'status', 'output']]
            
            # Clean leaderboard table with click-to-select enabled
            selection_event = st.dataframe(
                display_df, 
                hide_index=True, 
                use_container_width=True,
                on_select="rerun",
                selection_mode="single-row"
            )
            
            # Only display the code block if a student's row is clicked
            if selection_event.selection.rows:
                selected_idx = selection_event.selection.rows[0]
                selected_student = df.iloc[selected_idx]
                st.markdown(f"### 💻 Code: {selected_student['name']}")
                st.code(selected_student['code'], language="python")
        else:
            st.info("No submissions yet.")

    with t2:
        with st.form("task_setup"):
            new_desc = st.text_area("Markdown Instructions:", value=current_task.get('task_description', ''))
            new_in = st.text_input("Target Input:", value=current_task.get('goal_input', ''))
            new_out = st.text_input("Target Output:", value=current_task.get('expected_output', ''))
            
            if st.form_submit_button("Update Assignment"):
                payload = {
                    "class_name": sel_class, "period": str(sel_period),
                    "task_description": new_desc, "goal_input": new_in, "expected_output": new_out
                }
                try:
                    existing = supabase.table("current_task").select("id").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
                    
                    if existing:
                        supabase.table("current_task").update(payload).eq("id", existing[0]['id']).execute()
                    else:
                        highest = supabase.table("current_task").select("id").order("id", desc=True).limit(1).execute().data
                        payload["id"] = highest[0]['id'] + 1 if highest else 1
                        supabase.table("current_task").insert(payload).execute()
                        
                    st.success("Updated!")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"Save failed: {e}")

else: # STUDENT VIEW
    st.title(f"🚀 {sel_class} - P{sel_period}")
    if current_task.get('task_description'):
        st.markdown(current_task['task_description'])
    
    editor_btns = [{
        "name": "Run & Submit",
        "feather": "Play",
        "primary": True,
        "hasText": True,
        "showWithIcon": True,
        "commands": ["submit"],
        "style": {"bottom": "15px", "right": "15px", "position": "absolute"}
    }]
    
    response = code_editor("", lang="python", buttons=editor_btns, key="student_editor_instance")
    
    if response and response.get("type") == "submit":
        code = response.get("text", "")
        
        if not code.strip():
            st.warning("Please write some code before submitting.")
        else:
            with st.spinner("Executing code & updating database..."):
                try:
                    sb_res = requests.post(
                        f"{PUBLIC_MIRROR}/submissions?wait=true", 
                        json={"source_code": code, "language_id": 71, "stdin": str(current_task.get('goal_input', ''))}, 
                        timeout=15
                    ).json()
                    
                    actual = str(sb_res.get("stdout", "")).strip()
                    if actual == "None": actual = ""
                    
                    target = str(current_task.get('expected_output', '')).strip()
                    
                    status = "PASSED ✅" if actual == target else "WRONG OUTPUT ❌"
                    if sb_res.get("stderr"): 
                        status = "RUNTIME ERROR ⚠️"
                    
                    # Force updated_at to the exact second of submission
                    sub_payload = {
                        "name": user_fullname, 
                        "class_name": sel_class, 
                        "period": str(sel_period),
                        "code": code, 
                        "status": status, 
                        "output": actual,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }
                    
                    existing_sub = supabase.table("submissions").select("*").eq("name", user_fullname).eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
                    
                    if existing_sub:
                        supabase.table("submissions").update(sub_payload).eq("name", user_fullname).eq("class_name", sel_class).eq("period", str(sel_period)).execute()
                    else:
                        supabase.table("submissions").insert(sub_payload).execute()
                        
                    st.success(f"Result: {status}")
                    
                except Exception as e:
                    st.error(f"Error: {e}")
