# Custom Header Component
import streamlit as st
import base64

def get_base64(path):
    with open(path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode()

def personalized_header():
    # Load and encode your logo graphic
    logo_base64 = get_base64("logo_horizontal_stacked.png") # Adjust filename to image_1.png or image_2.png
    
    st.markdown(
        f"""
        <style>
        .header-container {{
            background-color: white;
            padding: 10px;
            border-bottom: 2px solid #1d5c9d; /* Endeavor Blue */
            text-align: center;
        }}
        .header-logo {{
            max-width: 400px;
        }}
        </style>
        <div class="header-container">
            <img src="data:image/png;base64,{logo_base64}" class="header-logo" alt="American Heritage Schools Logo">
        </div>
        """,
        unsafe_allow_html=True
    )
