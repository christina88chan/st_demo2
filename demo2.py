import streamlit as st
import google.generativeai as genai
import io
import os
from streamlit_mic_recorder import mic_recorder
from google.api_core.exceptions import GoogleAPIError
import psycopg2
from datetime import datetime
import json

st.set_page_config(page_title="Message Drop", layout="centered")

st.markdown(
    """
    <style>
    /* General input fields like text_input, text_area, number_input */
    div.stTextInput > div > div > input,
    div.stTextArea > div > div > textarea,
    div.stNumberInput > div > div > input {
        background-color: #FDDDE6; /* Light baby pink */
        color: #262730; /* Keep text color dark for readability */
        border: 1px solid #FFC0CB; /* A slightly darker pink border */
        border-radius: 5px; /* Optional: adds rounded corners */
        padding: 10px; /* Optional: adds padding inside the input */
    }

    /* For selectbox, which has a different structure */
    div.stSelectbox > div > label + div {
        background-color: #FFD9E9; /* Light baby pink */
        border: 1px solid #FFC0CB; /* Border */
        border-radius: 5px;
    }
    div.stSelectbox > div > label + div > div {
         background-color: #FFD9E9; /* Inner part of selectbox */
    }

    /* Style for the password input field specifically (often similar to text input) */
    div.stTextInput input[type="password"] {
        background-color: #FFD9E9; /* Light baby pink */
        color: #262730;
        border: 1px solid #FFC0CB;
        border-radius: 5px;
        padding: 10px;
    }

    /* Optional: Style for focus state */
    div.stTextInput > div > div > input:focus,
    div.stTextArea > div > div > textarea:focus,
    div.stNumberInput > div > div > input:focus,
    div.stSelectbox > div > label + div:focus-within, /* For selectbox focus */
    div.stTextInput input[type="password"]:focus {
        border-color: #FF69B4; /* Hot pink border on focus */
        box-shadow: 0 0 0 0.1rem rgba(255, 105, 180, 0.25); /* Subtle pink glow */
        outline: none;
    }

    </style>
    """,
    unsafe_allow_html=True
)

st.title("leave a me a message! 💌🦔") 
st.markdown("record a message, get it transcribed, and send. only i can see the messages!")

st.warning("ensure your audio recordings are clear and the language is primarily English for best results.")


# --- Initialize Session State Variables ---
# Only need for recorded audio and transcription text (for editing)
if 'recorded_audio_bytes' not in st.session_state:
    st.session_state.recorded_audio_bytes = None
if 'edited_transcription_text' not in st.session_state:
    st.session_state.edited_transcription_text = ""
if 'show_editor' not in st.session_state:
    st.session_state.show_editor = False # Control visibility of the editor

# --- PostgreSQL Database Connection ---
@st.cache_resource
def init_db_connection():
    try:
        conn_string = st.secrets["SUPABASE_PG_CONN_STRING"]
        conn = psycopg2.connect(conn_string)
        st.success("Database connected!")
        print("DEBUG: Database connection established successfully.") # DEBUG
        return conn
    except KeyError:
        st.error("Supabase PostgreSQL connection string not found in Streamlit secrets. Please check your `.streamlit/secrets.toml` file.")
        st.stop()
    except Exception as e:
        st.error(f"Failed to connect to Supabase PostgreSQL: {e}")
        st.info("Please ensure your database credentials are correct and your database is accessible (check network restrictions).")
        st.stop()

db_conn = init_db_connection()

# --- Database Operation to Save Message ---
def save_message(visitor_id, message_text, audio_filename, metadata=None):
    print("\n--- DEBUG: Inside save_message function ---") # DEBUG
    print(f"DEBUG: Input visitor_id: '{visitor_id}'") # DEBUG
    print(f"DEBUG: Input message_text (first 100 chars): '{message_text[:100]}'") # DEBUG
    print(f"DEBUG: Input audio_filename: '{audio_filename}'") # DEBUG
    print(f"DEBUG: Input metadata: {metadata}") # DEBUG

    try:
        cur = db_conn.cursor()
        print("DEBUG: Cursor created.") # DEBUG

        # Convert metadata dict to JSON string if it's not already, and handle None
        metadata_json = json.dumps(metadata) if metadata is not None else None
        print(f"DEBUG: Metadata as JSON: {metadata_json}") # DEBUG

        # Check for empty mandatory fields (if your DB columns are NOT NULL)
        if not visitor_id or not visitor_id.strip():
            print("ERROR: visitor_id is empty or just whitespace.") # DEBUG
            st.error("Please enter a valid Name / ID.")
            return # Stop execution if ID is invalid

        if not message_text or not message_text.strip():
            print("ERROR: message_text is empty or just whitespace.") # DEBUG
            st.error("Message content cannot be empty.")
            return # Stop execution if message is invalid

        if not audio_filename or not audio_filename.strip():
            print("ERROR: audio_filename is empty or just whitespace.") # DEBUG
            st.error("Audio filename cannot be empty.")
            return # Stop execution if filename is invalid


        cur.execute(
            """
            INSERT INTO transcriptions (audio_filename, transcription_text, user_id, metadata)
            VALUES (%s, %s, %s, %s);
            """,
            (audio_filename, message_text, visitor_id, metadata_json) # Use metadata_json here
        )
        print("DEBUG: SQL INSERT executed.") # DEBUG

        db_conn.commit() # Commit the transaction
        print("DEBUG: Database commit successful.") # DEBUG
        cur.close()
        print("DEBUG: Cursor closed.") # DEBUG
        st.success("Your message has been saved!")
    except Exception as e:
        db_conn.rollback() # Always rollback on error
        print(f"ERROR: An exception occurred during save_message: {e}") # DEBUG
        st.error(f"Failed to save message to database: {e}")
        st.exception(e) # This will print the full traceback in Streamlit
    finally:
        print("--- DEBUG: save_message function finished ---") # DEBUG
        
# --- Core App Logic ---
# Visitor ID Input
visitor_input_id = st.text_input("name (or anon):", key="visitor_id_input")

# Gemini API Key Input
st.subheader("your Gemini API key")
api_key = st.text_input(
    "enter your Gemini API Key:",
    type="password",
    help="This key is used only for your message transcription and is not stored.",
    key="gemini_api_key_input"
)

# --- Conditional Display based on API Key ---
if not api_key:
    st.info("please enter your Gemini API Key to enable recording and transcription.")
else:
    # Configure Gemini API
    try:
        genai.configure(api_key=api_key)
        st.success("Gemini API configured!")
    except Exception as e:
        st.error(f"Failed to configure Gemini API. Check your API key. Error: {e}")
        api_key = None # Invalidate API key for this session if configuration fails

if api_key: # Only show recording/transcription if API key is valid
    st.subheader("Record Your Message")

    # Mic Recorder
    recorded_audio_output = mic_recorder(
        start_prompt="Click to Start Recording",
        stop_prompt="Click to Stop Recording",
        use_container_width=True,
        key='audio_recorder'
    )

    if recorded_audio_output and recorded_audio_output['bytes']:
        st.session_state.recorded_audio_bytes = recorded_audio_output['bytes']
        st.audio(st.session_state.recorded_audio_bytes, format="audio/wav")
        st.info("Recorded audio ready for transcription.")
        # Trigger transcription immediately after recording is done
        st.session_state.show_editor = True # Show editor after recording


    if st.session_state.show_editor and st.session_state.recorded_audio_bytes:
        # --- Transcribe Button ---
        if st.button("transcribe recording", key="transcribe_audio_button"):
            if not visitor_input_id:
                st.warning("Please enter your Name / ID before transcribing.")
            else:
                with st.spinner("Transcribing your audio..."):
                    try:
                        mime_type = "audio/wav"
                        audio_io = io.BytesIO(st.session_state.recorded_audio_bytes)
                        audio_io.name = "recorded_audio.wav"

                        audio_file = genai.upload_file(
                            path=audio_io,
                            mime_type=mime_type,
                            display_name=f"Message_from_{visitor_input_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                        )

                        while audio_file.state.name == "PROCESSING":
                            st.info("File is still processing on Gemini's side...")
                            import time
                            time.sleep(1)
                            audio_file = genai.get_file(audio_file.name)

                        prompt = "Transcribe the given audio accurately. Provide only the spoken text."
                        model = genai.GenerativeModel('models/gemini-1.5-flash-latest') # Ensure model is available
                        response = model.generate_content([audio_file, prompt])
                        st.session_state.edited_transcription_text = response.text

                        st.success("Transcription complete! You can now edit it.")

                    except GoogleAPIError as api_err:
                        st.error(f"Gemini API Error: {api_err.message}")
                        st.info("Please check your API key validity, ensure billing is enabled, or audio is not too long.")
                        st.exception(api_err)
                    except Exception as e:
                        st.error(f"An unexpected error occurred during transcription: {e}")
                        st.info("Ensure the audio recording was successful.")
                        st.exception(e)

        # --- Transcription Editor ---
        if st.session_state.edited_transcription_text:
            st.subheader("Review and Edit Your Message:")
            st.session_state.edited_transcription_text = st.text_area(
                "Edit your transcribed message here:",
                value=st.session_state.edited_transcription_text,
                height=200,
                key="transcription_editor"
            )

            if st.button("send message", key="save_message_button"):
                if not visitor_input_id:
                    st.warning("Please enter your Name / ID before saving.")
                elif not st.session_state.edited_transcription_text.strip():
                    st.warning("Message content cannot be empty.")
                else:
                    with st.spinner("Saving your message..."):
                        # Define a unique filename for the saved message
                        save_filename = f"message_from_{visitor_input_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
                        message_metadata = {
                            "source_app": "Streamlit Personal Message Drop",
                            "gemini_model": "1.5-flash-latest",
                            "original_audio_length_bytes": len(st.session_state.recorded_audio_bytes) if st.session_state.recorded_audio_bytes else 0
                        }
                        save_message(visitor_input_id, st.session_state.edited_transcription_text, save_filename, message_metadata)
                        st.success("Message sent!")

                        # Reset for next message
                        st.session_state.recorded_audio_bytes = None
                        st.session_state.edited_transcription_text = ""
                        st.session_state.show_editor = False
                        st.rerun() # Rerun to clear forms for a new message
    else:
        st.info("record your audio message to begin transcription!")

# --- No Public Display of Messages ---
st.markdown("---")
st.info("your message has been saved securely and are not publicly displayed on this website.")