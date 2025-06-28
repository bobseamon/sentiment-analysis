import streamlit as st
import requests
import json
import re
import time

# --- CONFIGURATION ---
# IMPORTANT: Replace this with the Invoke URL of your API Gateway deployment (Stage: v1)
API_GATEWAY_URL = "https://z8eof5hub5.execute-api.us-east-1.amazonaws.com/v1"

# --- API HELPER FUNCTIONS ---

def get_model_status():
    """Calls the /status endpoint to check if the model is running."""
    try:
        response = requests.get(f"{API_GATEWAY_URL}/status")
        response.raise_for_status()  # Raise an exception for bad status codes
        return response.json().get('is_running', False)
    except requests.exceptions.RequestException as e:
        st.error(f"Error checking model status: {e}")
        return False

def start_model_service(name, phone):
    """Calls the /start endpoint to deploy the model."""
    try:
        payload = {"name": name, "phone": phone}
        response = requests.post(f"{API_GATEWAY_URL}/start", json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error starting model service: {e}")
        return None

def get_prediction(text):
    """Calls the /predict endpoint to get a sentiment prediction."""
    try:
        payload = {"text": text}
        response = requests.post(f"{API_GATEWAY_URL}/predict", json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error getting prediction: {e}")
        return None

# --- STREAMLIT UI ---

st.set_page_config(page_title="Sentiment Analyzer", layout="wide")
st.title("On-Demand Sentiment Analysis Engine")
st.markdown("This application demonstrates an end-to-end, cost-effective MLOps system using a serverless, event-driven architecture on AWS.")

# --- INITIALIZE SESSION STATE ---
if 'model_status' not in st.session_state:
    st.session_state.model_status = get_model_status()
    st.session_state.show_startup_message = False

# --- STATUS INDICATOR ---
status_placeholder = st.empty()

def draw_status_indicator():
    """Displays the current model status with an icon and a refresh button."""
    with status_placeholder.container():
        status_text = "IN SERVICE" if st.session_state.model_status else "STOPPED"
        status_icon = "✅" if st.session_state.model_status else "⛔"
        
        col1, col2 = st.columns([1, 5])
        with col1:
            st.metric(label="Sentiment Model Status", value=status_text, delta_color="off")
        with col2:
            st.write("") # for vertical alignment
            if st.button("Refresh Status"):
                with st.spinner("Checking status..."):
                    st.session_state.model_status = get_model_status()
                    st.rerun()

draw_status_indicator()

st.markdown("---")


# --- CONDITIONAL UI ---

if st.session_state.model_status:
    # --- PREDICTION INTERFACE (If model is running) ---
    st.header("Analyze a Review")
    st.info("This model was trained on Amazon reviews for musical instruments")
    st.info("The purpose is to determine whether the sentiment of a user's review is positive or negative")
    user_input = st.text_area("Enter a review text for a musical instrument:", "This piano has a rich, resonant tone that I absolutely love!", height=150)

    if st.button("Analyze Sentiment"):
        if user_input:
            with st.spinner("Analyzing..."):
                prediction_result = get_prediction(user_input)
                if prediction_result:
                    label = "POSITIVE" if prediction_result[0]['label'] == 'LABEL_1' else "NEGATIVE"
                    score = prediction_result[0]['score']

                    if label == "POSITIVE":
                        st.success(f"Prediction: **{label}** (Confidence: {score:.2%})")
                    else:
                        st.error(f"Prediction: **{label}** (Confidence: {score:.2%})")
        else:
            st.warning("Please enter some text to analyze.")
            
else:
    # --- START-UP INTERFACE (If model is stopped) ---
    st.header("Start the Sentiment Model")
    st.info("For cost-saving purposes, the SageMaker model endpoint is not running 24/7. Click the button below to start it up.")
    st.markdown("""
    When you start the model:
    1.  A request is sent to an AWS Lambda function via API Gateway.
    2.  The Lambda function initiates the SageMaker endpoint deployment (which takes 5-15 minutes depending on demand).
    3.  You will receive an SMS notification when the model is ready to use with a URL back to this page.
    4.  The model will automatically shut down after 30 minutes of inactivity.
    """)

    if st.session_state.show_startup_message:
        st.success("Request received! The model is starting up. You will receive an SMS at the number you provided shortly. You can press 'Refresh Status' above to check.")
    else:
        with st.form("startup_form"):
            st.write("Enter your details to be notified when the model is ready.")
            user_name = st.text_input("First Name:")
            phone_number = st.text_input("North American Phone Number (e.g., 855-555-1212):")
            submitted = st.form_submit_button("Start Model & Notify Me")

            if submitted:
                # Basic validation for North American phone numbers
                phone_pattern = re.compile(r"^[2-9][0-8]\d{1}-\d{3}-\d{4}$")
                if user_name and phone_pattern.match(phone_number):
                    with st.spinner("Sending startup request..."):
                        phone_number = phone_number.replace('-', '')
                        start_model_service(user_name, phone_number)
                        st.session_state.show_startup_message = True
                        # Give a moment for the user to see the spinner before re-running
                        time.sleep(2) 
                        st.rerun()
                else:
                    st.error("Please provide a valid name and a North American phone number in the format 855-555-1212.")

