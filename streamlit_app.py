import streamlit as st
import requests
import pandas as pd
import time
import re
import json
import ast
from datetime import datetime, timezone
from supabase import create_client
from streamlit_autorefresh import st_autorefresh
from code_editor import code_editor

# --- 1. INITIALIZATION & PERSISTENCE ---
st.set_page_config(page_title="American Heritage LMS", layout="wide", page_icon="🏫")

# --- BRANDING & CSS INJECTION ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Dancing+Script:wght@600&family=EB+Garamond:wght@400;600&display=swap');

    /* Shrink Streamlit's massive default top padding */
    .block-container { padding-top: 2rem !important; }

    html, body, [class*="css"] { font-family: 'Helvetica', sans-serif; }
    h1, h2, h3, h4, h5, h6 { font-family: 'EB Garamond', 'Times New Roman', serif !important; color: #1d5c9d !important; }
    .accent-text { font-family: 'Dancing Script', cursive !important; color: #fbb215 !important; font-size: 28px; margin-bottom: 10px; }
    .sub-accent { color: #74747a !important; font-size: 18px; font-weight: bold; }
    .stButton>button { background-color: #1d5c9d !important; color: white !important; border: 2px solid #1d5c9d !important; }
    .stButton>button:hover { background-color: #fbb215 !important; color: #000000 !important; border: 2px solid #fbb215 !important; }
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

# --- HELPER FUNCTIONS ---
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

# --- AST MAPPING ENGINE ---
# UI Category Structure
AST_CATEGORIES = {
    "Control Flow": ["If / Elif / Else", "For Loop", "While Loop", "Function (def)", "Class (class)", "Return"],
    "Operators": ["Addition (+)", "Subtraction (-)", "Multiplication (*)", "Division (/)", "Modulo (%)", "Equality (==)", "Not Equal (!=)", "Greater Than (>)", "Less Than (<)", "Logical AND", "Logical OR", "Logical NOT"],
    "Data Structures": ["List []", "Dictionary {}", "Tuple ()", "Set {}"],
    "Built-in Functions": ["input()", "print()", "int()", "float()", "str()", "list()", "dict()", "set()", "len()", "range()"],
    "String Methods": [".lower()", ".upper()", ".strip()", ".split()", ".replace()", ".join()"],
    "Libraries": ["Regex (re)", "Math (math)", "Random (random)"]
}

# Translation Maps
NODE_MAP = {
    "If / Elif / Else": ast.If, "For Loop": ast.For, "While Loop": ast.While,
    "Function (def)": ast.FunctionDef, "Class (class)": ast.ClassDef, "Return": ast.Return,
    "Addition (+)": ast.Add, "Subtraction (-)": ast.Sub, "Multiplication (*)": ast.Mult,
    "Division (/)": ast.Div, "Modulo (%)": ast.Mod, "Equality (==)": ast.Eq,
    "Not Equal (!=)": ast.NotEq, "Greater Than (>)": ast.Gt, "Less Than (<)": ast.Lt,
    "Logical AND": ast.And, "Logical OR": ast.Or, "Logical NOT": ast.Not,
    "List []": ast.List, "Dictionary {}": ast.Dict, "Tuple ()": ast.Tuple, "Set {}": ast.Set
}
FUNC_MAP = { 
    "input()": "input", "print()": "print", "int()": "int", "float()": "float", 
    "str()": "str", "list()": "list", "dict()": "dict", "set()": "set", "len()": "len", "range()": "range" 
}
METHOD_MAP = { 
    ".lower()": "lower", ".upper()": "upper", ".strip()": "strip", 
    ".split()": "split", ".replace()": "replace", ".join()": "join" 
}
LIB_MAP = { "Regex (re)": "re", "Math (math)": "math", "Random (random)": "random" }

def validate_code_structure(student_code, requirements):
    """Deep inspection of student code for specific logic, functions, methods, and libraries."""
    if not requirements:
        return True, ""
        
    try:
        tree = ast.parse(student_code)
    except SyntaxError:
        return False, "Syntax Error: Code cannot be parsed for structural check."

    found_nodes = set()
    found_funcs = set()
    found_methods = set()
    found_libs = set()

    for node in ast.walk(tree):
        found_nodes.add(type(node))
        
        if isinstance(node, ast.BinOp): found_nodes.add(type(node.op))
        elif isinstance(node, ast.Compare):
            for op in node.ops: found_nodes.add(type(op))
        elif isinstance(node, ast.BoolOp): found_nodes.add(type(node.op))
        elif isinstance(node, ast.UnaryOp): found_nodes.add(type(node.op))
        
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                found_funcs.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                found_methods.add(node.func.attr)
                
        elif isinstance(node, ast.Import):
            for alias in node.names: found_libs.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module: found_libs.add(node.module.split('.')[0])

    missing = []
    for category, items in requirements.items():
        for item in items:
            if item in NODE_MAP and NODE_MAP[item] not in found_nodes:
                missing.append(item)
            elif item in FUNC_MAP and FUNC_MAP[item] not in found_funcs:
                missing.append(item)
            elif item in METHOD_MAP and METHOD_MAP[item] not in found_methods:
                missing.append(item)
            elif item in LIB_MAP and LIB_MAP[item] not in found_libs:
                missing.append(item)

    if missing:
        return False, f"Missing required structures: {', '.join(missing)}"
    
    return True, "Structure valid!"

# --- 2. AUTHENTICATION UI ---
def login_ui():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        try:
            st.image("images/AHS Horizontal Logo with Motto (Clear_No Background).png", use_container_width=True)
        except Exception:
            pass
            
        st.markdown("<h1 style='text-align: center; margin-top: 0px;'>Secure Login</h1>", unsafe_allow_html=True)
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
        st.image("images/AHS Emblem (Clear_No Background).png", width=150)
    except Exception:
        pass 
        
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
        if res:
            task = res[0]
            ast_req = task.get('ast_requirements')
            
            if isinstance(ast_req, str):
                try: 
                    task['ast_requirements'] = json.loads(ast_req)
                except Exception: 
                    task['ast_requirements'] = {}
            elif not isinstance(ast_req, dict):
                task['ast_requirements'] = {}
                
            return task
        return {"task_description": "", "goal_input": "", "expected_output": "", "ast_requirements": {}}
    except Exception:
        return {"task_description": "", "goal_input": "", "expected_output": "", "ast_requirements": {}}

current_task = get_task()

# --- 5. MAIN INTERFACE ---
if role == "teacher":
    st_autorefresh(interval=20000, key="datarefresh")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"<h1 style='margin-top: -15px;'>Dashboard: {sel_class} - P{sel_period}</h1>", unsafe_allow_html=True)
    with col2:
        try:
            st.image("images/AHS Square Name & Motto (Clear_No Background).png", width=120)
        except Exception:
            pass
            
    t1, t2 = st.tabs(["🏆 Leaderboard", "⚙️ Setup"])
    
    with t1:
        colA, colB = st.columns([4, 1])
        with colA:
            st.markdown("### Submission Results")
        with colB:
            if st.button("🔄 Refresh Data", use_container_width=True):
                st.rerun()

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
                "MANUAL REVIEW 🔍": 2,
                "WRONG OUTPUT ❌": 3,
                "RUNTIME ERROR ⚠️": 3,
                "AST MISSING 🧩": 4,
                "Not Started ⏳": 5
            }
            df['rank'] = df['status'].map(status_rank).fillna(6)
            
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
                    
                    if st.button("🔄 Re-evaluate Code Against Current Rules", key=f"reeval_{selected_student['name']}"):
                        with st.spinner(f"Re-evaluating {selected_student['name']}'s code..."):
                            try:
                                code = selected_student['code']
                                
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
                                
                                if error_output: 
                                    new_status = "RUNTIME ERROR ⚠️"
                                elif actual != target:
                                    new_status = "WRONG OUTPUT ❌"
                                else:
                                    reqs = current_task.get('ast_requirements', {})
                                    ast_passed, ast_msg = validate_code_structure(code, reqs)
                                    
                                    if ast_passed:
                                        new_status = "PASSED ✅"
                                    else:
                                        if selected_student['status'] == "MANUAL REVIEW 🔍":
                                            new_status = "MANUAL REVIEW 🔍"
                                        else:
                                            new_status = "AST MISSING 🧩"
                                            
                                supabase.table("submissions").update({
                                    "status": new_status,
                                    "output": actual,
                                    "updated_at": datetime.now(timezone.utc).isoformat()
                                }).eq("name", selected_student['name']).eq("class_name", sel_class).eq("period", str(sel_period)).execute()
                                
                                st.success(f"Successfully re-evaluated! New Status: {new_status}")
                                time.sleep(1)
                                st.rerun()
                                
                            except Exception as e:
                                st.error(f"Re-evaluation failed: {e}")
        else:
            st.info("No students found in the roster for this class/period.")

    with t2:
        st.markdown("### 🤖 Import AI Task Generation")
        uploaded_file = st.file_uploader("Upload JSON Task File", type=["json"])
        
        if uploaded_file is not None:
            try:
                ai_data = json.load(uploaded_file)
                st.session_state['draft_task'] = ai_data
                st.success("JSON successfully loaded! Review and click Update Below.")
            except Exception as e:
                st.error(f"Error reading JSON: {e}")
                
        draft = st.session_state.get('draft_task', current_task)
        
        st.markdown("---")
        with st.form("task_setup"):
            new_desc = st.text_area("Markdown Instructions:", value=draft.get('task_description', ''))
            new_in = st.text_input("Target Input:", value=draft.get('goal_input', ''))
            new_out = st.text_input("Target Output:", value=draft.get('expected_output', ''))
            
            st.markdown("### 🌳 Required AST Structures")
            st.caption("Select the specific code structures students MUST use to pass.")
            
            selected_ast = {}
            
            loaded_ast = draft.get('ast_requirements')
            if isinstance(loaded_ast, str):
                try: 
                    loaded_ast = json.loads(loaded_ast)
                except Exception: 
                    loaded_ast = {}
                    
            if not isinstance(loaded_ast, dict):
                loaded_ast = {}
            
            for category, items in AST_CATEGORIES.items():
                with st.expander(f"{category}"):
                    selected_ast[category] = []
                    for item in items:
                        is_checked = item in loaded_ast.get(category, [])
                        if st.checkbox(item, value=is_checked, key=f"ast_{category}_{item}"):
                            selected_ast[category].append(item)

            if st.form_submit_button("Update Assignment"):
                final_ast = {k: v for k, v in selected_ast.items() if v}
                
                payload = {
                    "class_name": sel_class, "period": str(sel_period),
                    "task_description": new_desc, "goal_input": new_in, 
                    "expected_output": new_out, "ast_requirements": json.dumps(final_ast)
                }
                try:
                    existing = supabase.table("current_task").select("id").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
                    if existing:
                        supabase.table("current_task").update(payload).eq("id", existing[0]['id']).execute()
                    else:
                        highest = supabase.table("current_task").select("id").order("id", desc=True).limit(1).execute().data
                        payload["id"] = highest[0]['id'] + 1 if highest else 1
                        supabase.table("current_task").insert(payload).execute()
                        
                    st.success("Assignment & Structural Rules Updated!")
                    if 'draft_task' in st.session_state:
                        del st.session_state['draft_task']
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"Save failed: {e}")

else: # STUDENT VIEW
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"<h1 style='margin-top: -15px;'>{sel_class} - P{sel_period}</h1>", unsafe_allow_html=True)
    with col2:
        try:
            st.image("images/AHS Square Name & Motto (Clear_No Background).png", width=120)
        except:
            pass

    if current_task.get('task_description'):
        st.markdown(current_task['task_description'])
        
    override_ast = st.checkbox("🚩 **Override Structural Check (Flag for Manual Review)**", 
                               help="Check this if your code produces the right output but fails the AST check, and you want your teacher to review your alternative approach.")
        
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
            with st.spinner("Executing code & checking structures..."):
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
                    
                    if error_output: 
                        status = "RUNTIME ERROR ⚠️"
                    elif actual != target:
                        status = "WRONG OUTPUT ❌"
                    else:
                        reqs = current_task.get('ast_requirements', {})
                        ast_passed, ast_msg = validate_code_structure(code, reqs)
                        
                        if ast_passed:
                            status = "PASSED ✅"
                        else:
                            if override_ast:
                                status = "MANUAL REVIEW 🔍"
                            else:
                                status = "AST MISSING 🧩"
                    
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
                        
                    if status == "PASSED ✅":
                        st.success("Result: PASSED ✅ - Output and structures are correct!")
                    elif status == "MANUAL REVIEW 🔍":
                        st.info("Result: MANUAL REVIEW 🔍 - Correct output, submitted for alternative approach review.")
                    elif status == "AST MISSING 🧩":
                        st.warning(f"Result: AST MISSING 🧩 - Your code produced the right text, but didn't pass the structure check:\n\n**{ast_msg}**\n\n*If you think your approach is valid, check the Override box above and resubmit.*")
                    elif status == "WRONG OUTPUT ❌":
                        st.error("Result: WRONG OUTPUT ❌")
                    
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
                    st.error(f"System Error: {e}")
