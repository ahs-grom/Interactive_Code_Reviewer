import streamlit as st
import requests
import pandas as pd
import time
import re
from datetime import datetime, timezone
from supabase import create_client
from streamlit_autorefresh import st_autorefresh
from code_editor import code_editor

# --- 1. INITIALIZATION & PERSISTENCE ---
st.set_page_config(page_title="American Heritage LMS", layout="wide", page_icon="🏫")

# --- BRANDING & CSS INJECTION ---
# Colors: Black (#000000), Dark Tangerine (#fbb215), Dolphin (#74747a), Endeavor (#1d5c9d)
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Dancing+Script:wght@600&family=EB+Garamond:wght@400;600&display=swap');

    /* Body Text - Helvetica */
    html, body, [class*="css"] {
        font-family: 'Helvetica', sans-serif;
    }

    /* Headlines - Garamond in Endeavor Blue */
    h1, h2, h3, h4, h5, h6 {
        font-family: 'EB Garamond', 'Times New Roman', serif !important;
        color: #1d5c9d !important; 
    }

    /* Custom Accent Text - Dancing Script */
    .accent-text {
        font-family: 'Dancing Script', cursive !important;
        color: #fbb215 !important;
        font-size: 28px;
        margin-bottom: 10px;
    }
    
    .sub-accent {
        color: #74747a !important; /* Dolphin Grey */
        font-size: 18px;
        font-weight: bold;
    }

    /* Button Styling */
    .stButton>button {
        background-color: #1d5c9d !important;
        color: white !important;
        border: 2px solid #1d5c9d !important;
    }
    .stButton>button:hover {
        background-color: #fbb215 !important;
        color: #000000 !important;
        border: 2px solid #fbb215 !important;
    }
    </style>
""", unsafe_allow_html=True)

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

# --- HELPER FUNCTION: PARSE ERRORS ---
def format_python_error(err_text):
    if not err_text: return ""
    lines = err_text.strip().split('\n')
    line_num = "Unknown"
    code_snippet = ""
    error_msg = lines[-1].strip() 
    
    for i, line in enumerate(lines):
        match = re.search(r'File ".*?", line (\d+)', line)
        if match:
            line_num = match.group(1)
            if i + 1 < len(lines):
                code_snippet = lines[i+1].strip()
                
    if line_num != "Unknown":
        return f"Line {line_num}:  {code_snippet}\n\n{error_msg}"
    return err_text

# --- 2. AUTHENTICATION UI ---
def login_ui():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        try:
            st.image("images/AHS Horizontal Logo with Motto (Clear_No Background).png", use_container_width=True)
        except Exception:
            st.warning("Logo image not found in images directory.")
            
        st.markdown("<h1 style='text-align: center;'>Secure Login</h1>", unsafe_allow_html=True)
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
    try:
        st.image("images/AHS Emblem (Clear_No Background).jpg", width=150)
    except Exception:
        pass # Silently pass if emblem is missing
        
    st.markdown(f"<p class='accent-text'>Welcome,</p>", unsafe_allow_html=True)
    st.markdown(f"**{user_fullname}**<br><span class='sub-accent'>{role.title()} Portal</span>", unsafe_allow_html=True)
    st.divider()
    
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

    st.divider()
    if st.button("🚪 Logout", use_container_width=True):
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
    st_autorefresh(interval=20000, key="datarefresh")
    st.title(f"Dashboard: {sel_class} - P{sel_period}")
    
    t1, t2 = st.tabs(["🏆 Leaderboard", "⚙️ Setup"])
    
    with t1:
        roster_data = supabase.table("rosters").select("student_name").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
        
        if roster_data:
            roster_df = pd.DataFrame(roster_data).rename(columns={"student_name": "name"})
            subs = supabase.table("submissions").select("*").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
            
            if subs:
                subs_df = pd.DataFrame(subs)
                df = pd.merge(roster_df, subs_df, on="name", how="left")
            else:
                df = roster_df.copy()
                df['status'] = None
                df['output'] = None
                df['code'] = None
                df['updated_at'] = pd.NaT
            
            df['status'] = df['status'].fillna("Not Started ⏳")
            df['output'] = df['output'].fillna("")
            df['code'] = df['code'].fillna("")
            
            status_rank = {
                "PASSED ✅": 1,
                "WRONG OUTPUT ❌": 2,
                "RUNTIME ERROR ⚠️": 2,
                "Not Started ⏳": 3
            }
            df['rank'] = df['status'].map(status_rank).fillna(4)
            
            if 'updated_at' in df.columns:
                df['updated_at'] = pd.to_datetime(df['updated_at'], errors='coerce')
            else:
                df['updated_at'] = pd.NaT
            
            df = df.sort_values(by=['rank', 'updated_at', 'name'], ascending=[True, True, True]).reset_index(drop=True)
            
            display_df = df[['name', 'status', 'output']]
            
            selection_event = st.dataframe(
                display_df, 
                hide_index=True, 
                use_container_width=True,
                on_select="rerun",
                selection_mode="single-row"
            )
            
            if selection_event.selection.rows:
                selected_idx = selection_event.selection.rows[0]
                selected_student = df.iloc[selected_idx]
                
                st.markdown(f"### 💻 Code: {selected_student['name']}")
                
                if selected_student['status'] == "Not Started ⏳":
                    st.info("This student has not submitted any code yet.")
                else:
                    st.code(selected_student['code'], language="python")
        else:
            st.info("No students found in the roster for this class/period.")

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
    col1, col2 = st.columns([3, 1])
    with col1:
        st.title(f"{sel_class} - P{sel_period}")
    with col2:
        try:
            st.image("AHS Square Name & Motto (Clear_No Background).png", width=120)
        except:
            pass

    if current_task.get('task_description'):
        st.markdown(current_task['task_description'])
        
    code_key = f"student_code_{sel_class}_{sel_period}"
    
    if code_key not in st.session_state:
        existing_sub = supabase.table("submissions").select("code").eq("name", user_fullname).eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
        if existing_sub:
            st.session_state[code_key] = existing_sub[0]['code']
        else:
            st.session_state[code_key] = ""
    
    editor_btns = [{
        "name": "Run & Submit",
        "feather": "Play",
        "primary": True,
        "hasText": True,
        "showWithIcon": True,
        "commands": ["submit"],
        "style": {"bottom": "15px", "right": "15px", "position": "absolute"}
    }]
    
    response = code_editor(st.session_state[code_key], lang="python", buttons=editor_btns, key="student_editor_instance")
    
    if response and response.get("type") == "submit":
        code = response.get("text", "")
        st.session_state[code_key] = code 
        
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
                    
                    err_out = str(sb_res.get("stderr", "")).strip()
                    if err_out == "None": err_out = ""
                    comp_out = str(sb_res.get("compile_output", "")).strip()
                    if comp_out == "None": comp_out = ""
                    
                    error_output = err_out if err_out else comp_out
                    target = str(current_task.get('expected_output', '')).strip()
                    
                    status = "PASSED ✅" if actual == target else "WRONG OUTPUT ❌"
                    if error_output: 
                        status = "RUNTIME ERROR ⚠️"
                    
                    sub_payload = {
                        "name": user_fullname, 
                        "class_name": sel_class, 
                        "period": str(sel_period),
                        "code": code, 
                        "status": status, 
                        "output": actual,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }
                    
                    existing_sub_check = supabase.table("submissions").select("*").eq("name", user_fullname).eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
                    if existing_sub_check:
                        supabase.table("submissions").update(sub_payload).eq("name", user_fullname).eq("class_name", sel_class).eq("period", str(sel_period)).execute()
                    else:
                        supabase.table("submissions").insert(sub_payload).execute()
                        
                    st.success(f"Result: {status}")
                    
                    st.markdown("### 🖥️ Execution Output")
                    if actual:
                        st.code(actual, language="text")
                    elif not error_output:
                        st.info("No standard output produced.")
                        
                    if error_output:
                        st.markdown("### ⚠️ Error Messages")
                        formatted_err = format_python_error(error_output)
                        st.error(formatted_err)
                    
                except Exception as e:
                    st.error(f"Execution Error: {e}")
