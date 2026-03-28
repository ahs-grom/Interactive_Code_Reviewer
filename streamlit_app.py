import streamlit as st
import requests
import pandas as pd
from supabase import create_client

# --- 1. CONFIG & CONNECTIONS ---
st.set_page_config(page_title="CodeHub Live", layout="wide")

# Connect to Supabase
try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    supabase = create_client(url, key)
except Exception as e:
    st.error("Missing Supabase Credentials in Secrets!")

# Piston API Config (The Sandbox)
PISTON_URL = "https://emkc.org/api/v2/piston/execute"

def run_code_in_sandbox(code):
    """Sends code to Piston API and returns the result."""
    payload = {
        "language": "python",
        "version": "3.10.0",
        "files": [{"content": code}]
    }
    response = requests.post(PISTON_URL, json=payload)
    result = response.json()
    # Combine standard output and standard error
    output = result.get('run', {}).get('output', 'No output.')
    return output

# --- 2. THE UI TABS ---
tab_student, tab_leaderboard, tab_teacher = st.tabs([
    "📝 Student Editor", "🏆 Live Leaderboard", "👨‍🏫 Teacher Review"
])

# --- STUDENT TAB ---
with tab_student:
    st.header("Python Workspace")
    student_name = st.selectbox("Select Your Name:", [
        "Barrett", "Behura", "Chen", "Crowe", "Grom", "Gupta", 
        "Mentada", "Muzzarelli", "Pillai", "Sahay", "Sandkovsky", 
        "Shandalingam", "Shih", "Teegavarapu", "Vasylchuk", "Wang", "Yablon", "Zhu"
    ])
    
    code_input = st.text_area("Write your code here:", height=300, placeholder="print('Hello World')")
    
    if st.button("🚀 Run & Submit"):
        with st.spinner("Executing in sandbox..."):
            # 1. Run in Sandbox
            raw_output = run_code_in_sandbox(code_input)
            
            # 2. Determine Status (Basic Check)
            status = "Success" if "Error" not in raw_output else "Failed"
            
            # 3. Save to Supabase (Upsert based on name)
            data = {
                "name": student_name,
                "code": code_input,
                "status": status,
                "output": raw_output
            }
            supabase.table("submissions").upsert(data).execute()
            
            st.code(raw_output, language="text")
            st.success("Code submitted to Teacher!")

# --- LEADERBOARD TAB ---
with tab_leaderboard:
    st.header("Class Progress")
    if st.button("🔄 Refresh Board"):
        # Fetch all submissions
        response = supabase.table("submissions").select("name, status, updated_at").execute()
        df = pd.DataFrame(response.data)
        
        if not df.empty:
            def color_status(val):
                color = '#2ecc71' if val == 'Success' else '#e74c3c'
                return f'background-color: {color}; color: white; font-weight: bold'
            
            st.dataframe(df.style.applymap(color_status, subset=['status']), use_container_width=True)
        else:
            st.info("No submissions yet!")

# --- TEACHER TAB ---
with tab_teacher:
    st.header("Instructor Command Center")
    
    # Fetch full data for teacher
    all_data = supabase.table("submissions").select("*").execute().data
    
    if all_data:
        teacher_df = pd.DataFrame(all_data)
        target_student = st.selectbox("Inspect Student:", teacher_df['name'].tolist())
        
        if target_student:
            student_row = teacher_df[teacher_df['name'] == target_student].iloc[0]
            
            col_left, col_right = st.columns(2)
            
            with col_left:
                st.subheader("Student's Code")
                # Teacher can edit the code directly here
                edited_code = st.text_area("Live Edit/Debug:", student_row['code'], height=300)
                
                if st.button("💾 Save Changes & Comment"):
                    new_comment = st.session_state.get('t_comment', "")
                    supabase.table("submissions").update({
                        "code": edited_code,
                        "teacher_comment": new_comment
                    }).eq("name", target_student).execute()
                    st.success("Update pushed to student!")

            with col_right:
                st.subheader("Output & Feedback")
                st.info(f"Last Output: {student_row['output']}")
                st.text_input("Teacher Comment:", 
                             value=student_row.get('teacher_comment', ""), 
                             key='t_comment')
    else:
        st.warning("Wait for students to submit code.")
