import streamlit as st
import requests
import pandas as pd
import time
from supabase import create_client

# --- 1. INITIALIZATION ---
st.set_page_config(page_title="CodeMaster LMS", layout="wide")

try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    supabase = create_client(url, key)
except Exception as e:
    st.error("🚨 Configuration Error: Supabase secrets missing.")
    st.stop()

# --- 2. THE STABLE COMMUNITY ENGINE ---
# We use a public Judge0 Community Edition mirror
JUDGE0_API_URL = "https://judge0-ce.p.rapidapi.com" # If you get a key later
# ALTERNATIVE: Use a direct open mirror if available, but for now let's stick to a robust request flow
# If Glot/Piston are out, we use the 'Subprocess' style logic if running locally, 
# but for Streamlit Cloud, let's try this specific public mirror:
PUBLIC_MIRROR = "https://ce.judge0.com" 

def run_code_in_sandbox(code, test_input):
    # Prepare the payload for Judge0
    payload = {
        "source_code": code,
        "language_id": 71, # Python 3
        "stdin": str(test_input) if test_input else ""
    }
    
    try:
        # 1. Submit the code
        # We'll try the direct community endpoint first
        res = requests.post(f"{PUBLIC_MIRROR}/submissions?wait=true", json=payload, timeout=20)
        data = res.json()
        
        # Judge0 '?wait=true' returns the result immediately if it's fast
        stdout = data.get("stdout")
        stderr = data.get("stderr")
        compile_output = data.get("compile_output")
        status = data.get("status", {}).get("description", "")

        if stderr: return "RUNTIME_ERR", stderr
        if compile_output: return "COMPILE_ERR", compile_output
        
        if status == "Accepted":
            output = stdout.strip() if stdout else ""
            if not output: return "NO_PRINT", "Code ran but printed nothing."
            return "SUCCESS", output
        
        return "ERROR", f"Status: {status}"

    except Exception as e:
        return "CONN_ERR", f"Sandbox unavailable: {str(e)}"

# --- 3. DATABASE LOGIC ---
def get_current_task(c_name, p_num):
    try:
        res = supabase.table("current_task").select("*").eq("class_name", c_name).eq("period", p_num).execute()
        if res.data: return res.data[0]
    except: pass
    return {"goal_input": "", "expected_output": "", "task_description": ""}

# --- 4. SIDEBAR & APP TABS (Standard Logic) ---
with st.sidebar:
    st.header("🏫 Class Management")
    teacher = st.text_input("Teacher Name", value="Grom")
    roster_check = supabase.table("rosters").select("class_name").eq("teacher_name", teacher).execute().data
    classes = list(set([r['class_name'] for r in roster_check])) if roster_check else ["Python 101"]
    sel_class = st.selectbox("Select Class", classes)
    sel_period = st.selectbox("Select Period", ["1", "2", "3", "4", "5", "6", "7", "8"])

task = get_current_task(sel_class, sel_period)
tab_student, tab_leaderboard, tab_teacher = st.tabs(["📝 Student View", "🏆 Leaderboard", "👨‍🏫 Teacher Tools"])

with tab_student:
    st.title(f"{sel_class} - P{sel_period}")
    if task.get('task_description'):
        with st.container(border=True):
            st.markdown(task['task_description'])
            st.caption(f"Goal Input: {task['goal_input']} | Expected: {task['expected_output']}")
    
    roster_res = supabase.table("rosters").select("student_name").eq("class_name", sel_class).eq("period", sel_period).execute().data
    names = [r['student_name'] for r in roster_res] if roster_res else ["Empty"]
    current_user = st.selectbox("Name:", names)
    code_in = st.text_area("Python Editor:", height=300)
    
    if st.button("🚀 Run & Submit"):
        with st.spinner("Processing..."):
            status, output = run_code_in_sandbox(code_in, task['goal_input'])
        
        # Grading
        clean_out = str(output).replace(" ", "").strip()
        clean_target = str(task['expected_output']).replace(" ", "").strip()
        final_status = status
        if status == "SUCCESS":
            final_status = "PASSED ✅" if clean_out == clean_target else "WRONG OUTPUT ❌"

        supabase.table("submissions").upsert({
            "name": current_user, "class_name": sel_class, "period": sel_period,
            "code": code_in, "status": final_status, "output": str(output)
        }, on_conflict="name, class_name, period").execute()
        
        if "PASSED" in final_status: st.success(output)
        else: st.warning(f"{final_status}: {output}")

# --- (Keep Teacher/Leaderboard tabs the same as previous version) ---