import streamlit as st
import requests
import pandas as pd
from supabase import create_client

# --- 1. CONFIG & CONNECTIONS ---
st.set_page_config(page_title="CodeMaster Hub", layout="wide")

# Connect to Supabase
try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    supabase = create_client(url, key)
except Exception as e:
    st.error(f"Missing/Invalid Secrets: {e}")
    st.stop()

PISTON_URL = "https://emkc.org/api/v2/piston/execute"

def run_code_in_sandbox(code, test_input=""):
    """Sends code to Piston API and returns (status, content)."""
    payload = {
        "language": "python",
        "version": "3.10.0",
        "files": [{"content": code}],
        "stdin": test_input + "\n"  # Add the "Enter" key automatically
    }
    try:
        response = requests.post(PISTON_URL, json=payload, timeout=8)
        res = response.json()
        run_res = res.get('run', {})
        
        stdout = run_res.get('output', "").strip()
        stderr = run_res.get('stderr', "").strip()

        if stderr:
            # Check for common student errors
            if "SyntaxError" in stderr: return "SYNTAX_ERR", stderr
            if "IndentationError" in stderr: return "INDENT_ERR", stderr
            if "NameError" in stderr: return "NAME_ERR", stderr
            return "RUNTIME_ERR", stderr
        
        if not stdout:
            return "NO_PRINT", "Code ran but nothing was printed. Did you forget print()?"
            
        return "SUCCESS", stdout
    except:
        return "TIMEOUT", "Execution took too long!"

# --- 2. PERSISTENT SETTINGS ---
# Using session state to bridge the gap between Teacher and Student tabs
if 'target_in' not in st.session_state: st.session_state.target_in = ""
if 'target_out' not in st.session_state: st.session_state.target_out = ""

# --- 3. UI TABS ---
tab_student, tab_leaderboard, tab_teacher = st.tabs(["📝 Student", "🏆 Leaderboard", "👨‍🏫 Teacher"])

# --- STUDENT TAB ---
with tab_student:
    st.header("Daily Coding Challenge")
    st.markdown(f"**Goal Input:** `{st.session_state.target_in or 'None'}`")
    st.markdown(f"**Expected Output:** `{st.session_state.target_out or 'None'}`")

    student_name = st.selectbox("Identify Yourself:", [
        "Barrett", "Behura", "Chen", "Crowe", "Grom", "Gupta", "Mentada", "Muzzarelli", 
        "Pillai", "Sahay", "Sandkovsky", "Shandalingam", "Shih", "Teegavarapu", 
        "Vasylchuk", "Wang", "Yablon", "Zhu"
    ])
    
    code = st.text_area("Your Python Code:", height=300)
    
    if st.button("🚀 Run & Submit"):
        status_type, result = run_code_in_sandbox(code, st.session_state.target_in)
        
        # Grading Logic
        final_status = status_type
        if status_type == "SUCCESS":
            if result == st.session_state.target_out:
                final_status = "PASSED ✅"
            else:
                final_status = "WRONG OUTPUT ❌"

        # Push to Supabase
        supabase.table("submissions").upsert({
            "name": student_name, "code": code, "status": final_status, "output": result
        }).execute()
        
        st.subheader("Console Result:")
        if "PASSED" in final_status: st.success(result)
        else: st.warning(result)

# --- LEADERBOARD TAB ---
with tab_leaderboard:
    st.header("Class Progress")
    if st.button("🔄 Refresh Data"):
        data = supabase.table("submissions").select("name, status, updated_at").execute().data
        if data:
            df = pd.DataFrame(data).sort_values('updated_at', ascending=False)
            
            def color_cells(val):
                if "PASSED" in val: color = '#2ecc71' # Green
                elif "ERR" in val: color = '#e74c3c'    # Red
                elif "WRONG" in val: color = '#f39c12'  # Orange
                else: color = '#95a5a6'                 # Grey
                return f'background-color: {color}; color: white; font-weight: bold'

            st.dataframe(df.style.applymap(color_cells, subset=['status']), use_container_width=True)
        else:
            st.info("No submissions yet.")

# --- TEACHER TAB ---
with tab_teacher:
    st.header("Instructional Controls")
    
    # 1. SET THE PROBLEM
    c1, c2 = st.columns(2)
    with c1:
        st.session_state.target_in = st.text_input("Set Logic Input (Stdin):", value=st.session_state.target_in)
    with c2:
        st.session_state.target_out = st.text_input("Set Expected Result (Stdout):", value=st.session_state.target_out)

    # 2. THE NUCLEAR OPTION (Reset)
    st.divider()
    if st.button("🧨 RESET CLASS (Delete All Submissions)"):
        # Supabase delete requires a filter; 'neq' name to empty string clears everything
        supabase.table("submissions").delete().neq("name", "").execute()
        st.success("Database wiped! Ready for a new lesson.")
        st.rerun()

    # 3. CODE INSPECTOR
    st.divider()
    all_data = supabase.table("submissions").select("*").execute().data
    if all_data:
        teacher_df = pd.DataFrame(all_data)
        choice = st.selectbox("Inspect Student:", teacher_df['name'].tolist())
        student_row = teacher_df[teacher_df['name'] == choice].iloc[0]
        
        st.subheader(f"Reviewing: {choice}")
        st.code(student_row['code'], language="python")
        st.write(f"**Last Status:** {student_row['status']}")
        st.write(f"**Last Output:** `{student_row['output']}`")
    else:
        st.write("No data to review.")