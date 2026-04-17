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

    .block-container { padding-top: 1.5rem !important; }

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
AST_CATEGORIES = {
    "Control Flow": ["If / Elif / Else", "For Loop", "While Loop", "Function (def)", "Class (class)", "Return"],
    "Operators": ["Addition (+)", "Subtraction (-)", "Multiplication (*)", "Division (/)", "Modulo (%)", "Equality (==)", "Not Equal (!=)", "Greater Than (>)", "Less Than (<)", "Logical AND", "Logical OR", "Logical NOT"],
    "Data Structures": ["List []", "Dictionary {}", "Tuple ()", "Set {}"],
    "Built-in Functions": ["input()", "print()", "int()", "float()", "str()", "list()", "dict()", "set()", "len()", "range()"],
    "String Methods": [".lower()", ".upper()", ".strip()", ".split()", ".replace()", ".join()"],
    "Libraries": ["Regex (re)", "Math (math)", "Random (random)"]
}

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
    if not requirements: return True, ""
    try: tree = ast.parse(student_code)
    except SyntaxError: return False, "Syntax Error: Code cannot be parsed for structural check."

    found_nodes, found_funcs, found_methods, found_libs = set(), set(), set(), set()

    for node in ast.walk(tree):
        found_nodes.add(type(node))
        if isinstance(node, ast.BinOp): found_nodes.add(type(node.op))
        elif isinstance(node, ast.Compare):
            for op in node.ops: found_nodes.add(type(op))
        elif isinstance(node, ast.BoolOp): found_nodes.add(type(node.op))
        elif isinstance(node, ast.UnaryOp): found_nodes.add(type(node.op))
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name): found_funcs.add(node.func.id)
            elif isinstance(node.func, ast.Attribute): found_methods.add(node.func.attr)
        elif isinstance(node, ast.Import):
            for alias in node.names: found_libs.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module: found_libs.add(node.module.split('.')[0])

    missing = []
    for category, items in requirements.items():
        for item in items:
            if item in NODE_MAP and NODE_MAP[item] not in found_nodes: missing.append(item)
            elif item in FUNC_MAP and FUNC_MAP[item] not in found_funcs: missing.append(item)
            elif item in METHOD_MAP and METHOD_MAP[item] not in found_methods: missing.append(item)
            elif item in LIB_MAP and LIB_MAP[item] not in found_libs: missing.append(item)

    if missing: return False, f"Missing required structures: {', '.join(missing)}"
    return True, "Structure valid!"

def execute_test_cases(code, test_cases, ast_requirements, override_ast=False, setup_code="", teardown_code=""):
    status = "PASSED ✅"
    actual_display = ""
    error_display = ""
    
    # Combine the code invisibly for execution only
    executable_code = f"{setup_code}\n\n{code}\n\n{teardown_code}".strip()
    
    if not test_cases:
        test_cases = [{"input": "", "expected_output": "", "is_hidden": False}]
        
    for i, tc in enumerate(test_cases):
        target_in = str(tc.get('input', ''))
        target_out = str(tc.get('expected_output', '')).strip()
        is_hidden = tc.get('is_hidden', False)
        
        try:
            sb_res = requests.post(
                f"{PUBLIC_MIRROR}/submissions?wait=true", 
                json={"source_code": executable_code, "language_id": 71, "stdin": target_in}, 
                timeout=15
            ).json()
            
            actual = str(sb_res.get("stdout", "")).strip()
            if actual == "None": actual = ""
            
            err_out = str(sb_res.get("stderr", "")).strip()
            if err_out == "None": err_out = ""
            comp_out = str(sb_res.get("compile_output", "")).strip()
            if comp_out == "None": comp_out = ""
            
            error_output = err_out if err_out else comp_out
            
            if error_output:
                status = "RUNTIME ERROR ⚠️"
                error_display = error_output
                break
            elif actual != target_out:
                status = "WRONG OUTPUT ❌"
                if is_hidden:
                    actual_display = "❌ Failed on a hidden test case."
                else:
                    actual_display = f"❌ Failed Test Case {i+1}:\nInput: {target_in}\nExpected: {target_out}\nGot: {actual}"
                break
            else:
                if i == 0:
                    actual_display = actual
                    
        except Exception as e:
            return "RUNTIME ERROR ⚠️", "", f"System Execution Error: {e}", ""
            
    ast_msg = ""
    if status == "PASSED ✅":
        # Make sure AST checker only evaluates the student's raw code
        ast_passed, ast_msg = validate_code_structure(code, ast_requirements)
        if not ast_passed:
            status = "MANUAL REVIEW 🔍" if override_ast else "AST MISSING 🧩"
            
    return status, actual_display, error_display, ast_msg

# --- 2. AUTHENTICATION UI ---
def login_ui():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        try: st.image("images/AHS Horizontal Logo with Motto (Clear_No Background).png", use_container_width=True)
        except Exception: pass
            
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
                except Exception as e: st.error(f"Auth Error: {e}")

if not st.session_state.get("authenticated"):
    login_ui()
    st.stop()

user_data = st.session_state.get("user_info", {})
role = user_data.get('role') or 'student'
user_fullname = user_data.get('name') or 'User'

# --- 3. SIDEBAR ---
with st.sidebar:
    try: st.image("images/AHS Emblem (Clear_No Background).png", width=150)
    except Exception: pass 
        
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
                try: task['ast_requirements'] = json.loads(ast_req)
                except Exception: task['ast_requirements'] = {}
            elif not isinstance(ast_req, dict):
                task['ast_requirements'] = {}
                
            tc = task.get('test_cases')
            if isinstance(tc, str):
                try: task['test_cases'] = json.loads(tc)
                except: task['test_cases'] = []
            elif not isinstance(tc, list):
                task['test_cases'] = []
                
            return task
        return {"title": "", "task_description": "", "test_cases": [], "ast_requirements": {}, "setup_code": "", "teardown_code": ""}
    except Exception:
        return {"title": "", "task_description": "", "test_cases": [], "ast_requirements": {}, "setup_code": "", "teardown_code": ""}

current_task = get_task()

# --- 5. MAIN INTERFACE ---
if role == "teacher":
    st_autorefresh(interval=20000, key="datarefresh")
    
    def refresh_btn_click():
        if 'l_key' not in st.session_state: st.session_state.l_key = 0
        if 'r_key' not in st.session_state: st.session_state.r_key = 0
        st.session_state.l_key += 1
        st.session_state.r_key += 1
        st.session_state.last_action = 'none'

    header_logo_col, header_title_col, header_btn_col = st.columns([0.6, 6, 1.5])
    
    with header_logo_col:
        try: 
            st.markdown("<div style='padding-top: 5px;'>", unsafe_allow_html=True)
            st.image("images/AHS Square Name & Motto (Clear_No Background).png", width=60)
            st.markdown("</div>", unsafe_allow_html=True)
        except Exception: pass

    with header_title_col:
        st.markdown(f"<h3>{sel_class} - P{sel_period}</h3>", unsafe_allow_html=True)

    with header_btn_col:
        st.write("") 
        st.write("") 
        st.button("🔄 Refresh Data", use_container_width=True, on_click=refresh_btn_click)
        
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
            
            status_rank = {"PASSED ✅": 1, "MANUAL REVIEW 🔍": 2, "WRONG OUTPUT ❌": 3, "RUNTIME ERROR ⚠️": 3, "AST MISSING 🧩": 4, "Not Started ⏳": 5}
            df['rank'] = df['status'].map(status_rank).fillna(6)
            
            if 'updated_at' in df.columns: 
                df['updated_at'] = pd.to_datetime(df['updated_at'], errors='coerce')
                try: df['updated_at'] = df['updated_at'].dt.tz_convert('America/New_York')
                except TypeError: pass 
            else: 
                df['updated_at'] = pd.NaT
            
            df = df.sort_values(by=['rank', 'updated_at', 'name'], ascending=[True, True, True]).reset_index(drop=True)
            
            passed_df = df[df['status'] == "PASSED ✅"].reset_index(drop=True)
            others_df = df[df['status'] != "PASSED ✅"].reset_index(drop=True)
            
            passed_disp = passed_df[['name', 'updated_at']].copy()
            passed_disp['name'] = passed_disp['name'].apply(lambda x: str(x)[:15] + "..." if len(str(x)) > 15 else str(x))
            passed_disp['Time'] = passed_disp['updated_at'].apply(
                lambda x: x.strftime('%I:%M:%S.%f')[:-3] + x.strftime(' %p') if pd.notnull(x) else "--:--"
            )
            passed_disp = passed_disp[['name', 'Time']]
            
            if 'l_key' not in st.session_state: st.session_state.l_key = 0
            if 'r_key' not in st.session_state: st.session_state.r_key = 0
            if 'last_action' not in st.session_state: st.session_state.last_action = 'none'

            col_left, col_right = st.columns([2, 1])
            
            with col_left:
                st.markdown("**Needs Attention / In Progress**")
                left_event = st.dataframe(
                    others_df[['name', 'status', 'output']], 
                    hide_index=True, use_container_width=True, 
                    on_select="rerun", selection_mode="single-row", 
                    height=210, key=f"left_board_{st.session_state.l_key}",
                    column_config={
                        "name": st.column_config.TextColumn("name", width="small")
                    }
                )
                
            with col_right:
                st.markdown("**Passed ✅**")
                right_event = st.dataframe(
                    passed_disp, 
                    hide_index=True, use_container_width=True, 
                    on_select="rerun", selection_mode="single-row", 
                    height=210, key=f"right_board_{st.session_state.r_key}",
                    column_config={
                        "name": st.column_config.TextColumn("name", width="small")
                    }
                )
                
            l_sel = left_event.selection.rows
            r_sel = right_event.selection.rows
            
            if l_sel and st.session_state.last_action != 'left':
                st.session_state.last_action = 'left'
                st.session_state.r_key += 1
                st.rerun()
                
            elif r_sel and st.session_state.last_action != 'right':
                st.session_state.last_action = 'right'
                st.session_state.l_key += 1
                st.rerun()
                
            if not l_sel and st.session_state.last_action == 'left':
                st.session_state.last_action = 'none'
            if not r_sel and st.session_state.last_action == 'right':
                st.session_state.last_action = 'none'
                
            selected_student = None
            if st.session_state.last_action == 'left' and l_sel:
                selected_student = others_df.iloc[l_sel[0]]
            elif st.session_state.last_action == 'right' and r_sel:
                selected_student = passed_df.iloc[r_sel[0]]
                
            if selected_student is not None:
                st.markdown("---")
                st.markdown(f"### 💻 Code: {selected_student['name']}")
                
                if selected_student['status'] == "Not Started ⏳":
                    st.info("This student has not submitted any code yet.")
                else:
                    st.code(selected_student['code'], language="python")
                    
                    if st.button("🔄 Re-evaluate Code Against Current Rules", key=f"reeval_{selected_student['name']}"):
                        with st.spinner(f"Re-evaluating {selected_student['name']}'s code..."):
                            try:
                                code = selected_student['code']
                                reqs = current_task.get('ast_requirements', {})
                                test_cases = current_task.get('test_cases', [])
                                setup_code = current_task.get('setup_code', '')
                                teardown_code = current_task.get('teardown_code', '')
                                is_override = selected_student['status'] == "MANUAL REVIEW 🔍"
                                
                                new_status, actual_display, _, _ = execute_test_cases(code, test_cases, reqs, override_ast=is_override, setup_code=setup_code, teardown_code=teardown_code)
                                            
                                supabase.table("submissions").update({
                                    "status": new_status,
                                    "output": actual_display,
                                    "updated_at": datetime.now(timezone.utc).isoformat()
                                }).eq("name", selected_student['name']).eq("class_name", sel_class).eq("period", str(sel_period)).execute()
                                
                                st.success(f"Successfully re-evaluated! New Status: {new_status}")
                                time.sleep(1)
                                st.rerun()
                            except Exception as e: st.error(f"Re-evaluation failed: {e}")
        else:
            st.info("No students found in the roster for this class/period.")

    with t2:
        st.markdown("### 📚 Question Bank")
        try:
            bank_data = supabase.table("question_bank").select("*").execute().data
        except Exception:
            bank_data = []

        colA, colB = st.columns([3, 1])
        with colA:
            if bank_data:
                bank_options = {f"{q['title']} (by {q.get('teacher_name', 'Unknown')})": q for q in bank_data}
                selected_bank_q = st.selectbox("Load from Question Bank:", ["-- Select a Template --"] + list(bank_options.keys()))
                
                colA1, colA2 = st.columns([1, 1])
                with colA1:
                    if st.button("⬇️ Load Selected", use_container_width=True):
                        if selected_bank_q != "-- Select a Template --":
                            st.session_state['draft_task'] = bank_options[selected_bank_q]
                            st.success("Loaded into draft below!")
                with colA2:
                    if st.button("🗑️ Delete from Bank", use_container_width=True):
                        if selected_bank_q != "-- Select a Template --":
                            selected_q_data = bank_options[selected_bank_q]
                            if selected_q_data.get('teacher_name') == user_fullname:
                                supabase.table("question_bank").delete().eq("title", selected_q_data['title']).eq("teacher_name", user_fullname).execute()
                                st.success(f"Deleted '{selected_q_data['title']}' from your bank.")
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error("❌ You can only delete templates that you created!")
            else:
                st.info("Your question bank is empty. Save tasks below to build your library!")
                
        with colB:
            st.markdown("**OR** Upload JSON")
            uploaded_file = st.file_uploader("", type=["json"], label_visibility="collapsed")
            if uploaded_file is not None:
                if st.session_state.get('last_processed_file_id') != uploaded_file.file_id:
                    try:
                        ai_data = json.load(uploaded_file)
                        
                        if isinstance(ai_data, list):
                            inserted_count = 0
                            with st.spinner("Importing tasks directly into Question Bank..."):
                                for task in ai_data:
                                    if "title" not in task: continue
                                    
                                    clean_title = re.sub(r'^\d+[\.\-\)]?\s*', '', task["title"]).strip()
                                    
                                    bank_payload = {
                                        "title": clean_title,
                                        "teacher_name": user_fullname, 
                                        "tags": task.get("tags", ""),
                                        "task_description": task.get("task_description", ""),
                                        "test_cases": task.get("test_cases", []),
                                        "ast_requirements": json.dumps(task.get("ast_requirements", {})),
                                        "setup_code": task.get("setup_code", ""),
                                        "teardown_code": task.get("teardown_code", "")
                                    }
                                    
                                    existing = supabase.table("question_bank").select("title").eq("title", clean_title).eq("teacher_name", user_fullname).execute().data
                                    if existing:
                                        supabase.table("question_bank").update(bank_payload).eq("title", clean_title).eq("teacher_name", user_fullname).execute()
                                    else:
                                        supabase.table("question_bank").insert(bank_payload).execute()
                                        
                                    inserted_count += 1
                                    
                            st.session_state['last_processed_file_id'] = uploaded_file.file_id
                            st.success(f"Successfully imported {inserted_count} tasks into your Question Bank!")
                            time.sleep(1.5)
                            st.rerun()
                        else:
                            st.session_state['draft_task'] = ai_data
                            st.session_state['last_processed_file_id'] = uploaded_file.file_id
                            st.success("JSON loaded! Review below.")
                    except Exception as e: 
                        st.error(f"Error reading JSON: {e}")
                
        draft = st.session_state.get('draft_task', current_task)
        
        st.markdown("---")
        st.markdown("### 📝 Assignment Setup & Preview")
        
        with st.form("task_setup"):
            new_title = st.text_input("Assignment Title:", value=draft.get('title', ''))
            new_tags = st.text_input("Tags (comma separated, for bank filtering):", value=draft.get('tags', ''))
            new_desc = st.text_area("Markdown Instructions:", value=draft.get('task_description', ''), height=150)
            
            st.markdown("### 🧪 Test Cases")
            
            default_tc = pd.DataFrame([{"input": "", "expected_output": "", "is_hidden": False}])
            
            raw_tc = draft.get("test_cases", [])
            if isinstance(raw_tc, str):
                try: raw_tc = json.loads(raw_tc)
                except: raw_tc = []
            
            if raw_tc and isinstance(raw_tc, list):
                default_tc = pd.DataFrame(raw_tc)
                
            edited_tc = st.data_editor(default_tc, num_rows="dynamic", use_container_width=True, hide_index=True)
            
            st.markdown("### ⚙️ Hidden Setup & Teardown (Optional)")
            new_setup = st.text_area("Hidden Setup Code (Runs BEFORE student code. Good for creating files):", value=draft.get('setup_code', ''), height=100)
            new_teardown = st.text_area("Hidden Teardown Code (Runs AFTER student code. Good for asserting file contents):", value=draft.get('teardown_code', ''), height=100)
            
            st.markdown("### 🌳 Required AST Structures")
            
            selected_ast = {}
            loaded_ast = draft.get('ast_requirements')
            if isinstance(loaded_ast, str):
                try: loaded_ast = json.loads(loaded_ast)
                except Exception: loaded_ast = {}
            if not isinstance(loaded_ast, dict): loaded_ast = {}
            
            for category, items in AST_CATEGORIES.items():
                with st.expander(f"{category}"):
                    selected_ast[category] = []
                    for item in items:
                        is_checked = item in loaded_ast.get(category, [])
                        if st.checkbox(item, value=is_checked, key=f"ast_{category}_{item}"):
                            selected_ast[category].append(item)

            st.markdown("---")
            save_to_bank = st.checkbox("💾 Save/Update this template in the Question Bank", value=True)
            allow_overwrite = st.checkbox("⚠️ Overwrite existing template if my title matches (Leave unchecked to save as a new copy if warned)", value=False)
            
            if st.form_submit_button("Deploy Assignment to Students"):
                if not new_title.strip():
                    st.error("Please provide an Assignment Title.")
                else:
                    final_ast = {k: v for k, v in selected_ast.items() if v}
                    clean_tc = edited_tc.dropna(subset=['expected_output']).to_dict('records')
                    
                    conflict_detected = False
                    if save_to_bank:
                        existing_mine = supabase.table("question_bank").select("title").eq("title", new_title).eq("teacher_name", user_fullname).execute().data
                        if existing_mine and not allow_overwrite:
                            conflict_detected = True
                            
                    if conflict_detected:
                        st.error(f"⚠️ You already have a template named '{new_title}' in the bank. Please check the 'Overwrite existing template' box below to update it, or change the title.")
                    else:
                        payload = {
                            "class_name": sel_class, "period": str(sel_period),
                            "title": new_title,
                            "task_description": new_desc, 
                            "test_cases": clean_tc, 
                            "ast_requirements": json.dumps(final_ast),
                            "setup_code": new_setup,
                            "teardown_code": new_teardown
                        }
                        try:
                            existing = supabase.table("current_task").select("id").eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
                            if existing:
                                supabase.table("current_task").update(payload).eq("id", existing[0]['id']).execute()
                            else:
                                supabase.table("current_task").insert(payload).execute()
                                
                            supabase.table("submissions").delete().eq("class_name", sel_class).eq("period", str(sel_period)).execute()
                            
                            if save_to_bank:
                                bank_payload = {
                                    "title": new_title,
                                    "teacher_name": user_fullname, 
                                    "tags": new_tags,
                                    "task_description": new_desc,
                                    "test_cases": clean_tc,
                                    "ast_requirements": json.dumps(final_ast),
                                    "setup_code": new_setup,
                                    "teardown_code": new_teardown
                                }
                                existing_bank = supabase.table("question_bank").select("title").eq("title", new_title).eq("teacher_name", user_fullname).execute().data
                                if existing_bank:
                                    supabase.table("question_bank").update(bank_payload).eq("title", new_title).eq("teacher_name", user_fullname).execute()
                                else:
                                    supabase.table("question_bank").insert(bank_payload).execute()
                                
                            st.success("Assignment Deployed & Student Data Cleared!")
                            if 'draft_task' in st.session_state: del st.session_state['draft_task']
                            time.sleep(1.5)
                            st.rerun()
                        except Exception as e: st.error(f"Save failed: {e}")

else: # STUDENT VIEW
    header_logo_col, header_title_col, header_spacer_col = st.columns([0.6, 6, 1.5])
    
    with header_logo_col:
        try: 
            st.markdown("<div style='padding-top: 5px;'>", unsafe_allow_html=True)
            st.image("images/AHS Square Name & Motto (Clear_No Background).png", width=60)
            st.markdown("</div>", unsafe_allow_html=True)
        except Exception: pass

    with header_title_col:
        st.markdown(f"<h3>{sel_class} - P{sel_period}</h3>", unsafe_allow_html=True)

    if current_task.get('title'):
        st.markdown(f"## {current_task['title']}")
        
    if current_task.get('task_description'):
        st.markdown(current_task['task_description'])
        
        visible_cases = [tc for tc in current_task.get('test_cases', []) if not tc.get('is_hidden', False)]
        if visible_cases:
            st.markdown("### 🔍 Example Test Cases")
            for i, vc in enumerate(visible_cases):
                st.markdown(f"**Input:** `{vc.get('input', '')}`  \n**Expected Output:** `{vc.get('expected_output', '')}`")
        
    override_ast = st.checkbox("🚩 **Override Structural Check (Flag for Manual Review)**", help="Check this if your code produces the right output but fails the AST check, and you want your teacher to review your alternative approach.")
        
    code_key = f"student_code_{sel_class}_{sel_period}"
    if code_key not in st.session_state:
        existing_sub = supabase.table("submissions").select("code").eq("name", user_fullname).eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
        if existing_sub: st.session_state[code_key] = existing_sub[0]['code']
        else: st.session_state[code_key] = ""
    
    editor_btns = [{"name": "Run & Submit", "feather": "Play", "primary": True, "hasText": True, "showWithIcon": True, "commands": ["submit"], "style": {"bottom": "15px", "right": "15px", "position": "absolute"}}]
    
    response = code_editor(st.session_state[code_key], lang="python", buttons=editor_btns, key="student_editor_instance")
    
    if response and response.get("type") == "submit":
        code = response.get("text", "")
        st.session_state[code_key] = code 
        
        if not code.strip():
            st.warning("Please write some code before submitting.")
        else:
            with st.spinner("Executing test cases & checking structures..."):
                try:
                    reqs = current_task.get('ast_requirements', {})
                    test_cases = current_task.get('test_cases', [])
                    setup_code = current_task.get('setup_code', '')
                    teardown_code = current_task.get('teardown_code', '')
                    
                    status, actual_display, error_display, ast_msg = execute_test_cases(code, test_cases, reqs, override_ast, setup_code, teardown_code)
                    
                    sub_payload = {
                        "name": user_fullname, 
                        "class_name": sel_class, "period": str(sel_period),
                        "code": code, "status": status, "output": actual_display,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }
                    
                    existing_sub_check = supabase.table("submissions").select("*").eq("name", user_fullname).eq("class_name", sel_class).eq("period", str(sel_period)).execute().data
                    if existing_sub_check: supabase.table("submissions").update(sub_payload).eq("name", user_fullname).eq("class_name", sel_class).eq("period", str(sel_period)).execute()
                    else: supabase.table("submissions").insert(sub_payload).execute()
                        
                    if status == "PASSED ✅": st.success("Result: PASSED ✅ - All tests and structures are correct!")
                    elif status == "MANUAL REVIEW 🔍": st.info("Result: MANUAL REVIEW 🔍 - Correct output, submitted for alternative approach review.")
                    elif status == "AST MISSING 🧩": st.warning(f"Result: AST MISSING 🧩 - Your code produced the right text, but didn't pass the structure check:\n\n**{ast_msg}**\n\n*If you think your approach is valid, check the Override box above and resubmit.*")
                    elif status == "WRONG OUTPUT ❌": st.error("Result: WRONG OUTPUT ❌")
                    
                    st.markdown("### 🖥️ Execution Output")
                    if actual_display: st.code(actual_display, language="text")
                    elif not error_display: st.info("No standard output produced.")
                        
                    if error_display:
                        st.markdown("### ⚠️ Error Messages")
                        formatted_err = format_python_error(error_display)
                        st.error(formatted_err)
                    
                except Exception as e: st.error(f"System Error: {e}")
