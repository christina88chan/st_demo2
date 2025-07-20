import streamlit as st
import google.generativeai as genai
import io
import os 
from streamlit_mic_recorder import mic_recorder
from google.api_core.exceptions import GoogleAPIError # Import the specific exception class


st.set_page_config(page_title="Gemini Flash Audio Transcriber", layout="centered")

st.title("🗣️ Audio Transcription with Gemini Flash")
st.markdown("Record your audio directly from your microphone and get its transcription using Google's Gemini 1.5 Flash model. This model excels at processing long audio inputs efficiently.")

st.warning("Ensure your audio recordings are clear and the language is primarily English for best results. Gemini Flash supports a wide range of audio formats.")

# --- Gemini API Key Input ---
api_key = st.text_input(
    "Enter your Gemini API Key:", 
    type="password", 
    help="Get your API key from Google AI Studio: https://aistudio.google.com/app/apikey"
)

# Stop execution if API key is not provided
if not api_key:
    st.info("👈 Please enter your Gemini API Key to proceed.")
    st.stop()

# Configure the Gemini API with the provided key
try:
    genai.configure(api_key=api_key)
    st.success("Gemini API configured successfully!")
except Exception as e:
    st.error(f"Failed to configure Gemini API. Please check your API key for typos or validity. Error: {e}")
    st.stop()

# --- Model Initialization ---
try:
    model = genai.GenerativeModel('models/gemini-1.5-flash-latest')
    st.info("Gemini 1.5 Flash model initialized. Ready for transcription.")
except Exception as e:
    st.error(f"Failed to load Gemini model. Ensure your API key is correct and you have access to `gemini-1.5-flash-latest`. Error: {e}")
    st.exception(e)
    st.stop()

# --- Audio Recording Section ---
st.subheader("Record Your Audio")

# Initialize session state for recorded audio if it doesn't exist
if 'recorded_audio_bytes' not in st.session_state:
    st.session_state.recorded_audio_bytes = None

recorded_audio_output = mic_recorder(
    start_prompt="Click to Start Recording", 
    stop_prompt="Click to Stop Recording", 
    use_container_width=True,
    key='audio_recorder'
)

# If new audio is recorded, update the session state
if recorded_audio_output and recorded_audio_output['bytes']:
    st.session_state.recorded_audio_bytes = recorded_audio_output['bytes']
    st.audio(st.session_state.recorded_audio_bytes, format="audio/wav")
    st.info("Recorded audio ready for transcription.")
elif st.session_state.recorded_audio_bytes is None:
    st.info("Please record audio to proceed with transcription.")

audio_to_transcribe = st.session_state.recorded_audio_bytes

if audio_to_transcribe is not None:
    if st.button("Transcribe Audio", key="transcribe_button_after_record"):
        with st.spinner("Transcribing... This may take a moment depending on the audio file's length and your network speed."):
            try:
                mime_type = "audio/wav"

                # *** NEW CRITICAL CHANGE HERE ***
                # The latest stable way to upload is via genai.upload_file directly,
                # but it expects a 'path' argument (which can also be a file-like object
                # for in-memory bytes). This is the pattern seen in more recent docs.
                
                # To handle in-memory bytes, we need to create a temporary file
                # or ensure the library properly handles BytesIO for the 'path' argument.
                
                # Let's try passing BytesIO directly to 'path' as it often works implicitly
                # for methods that expect a file path or a file-like object.
                # If this fails, the next step would be to save to a temp file on disk.

                audio_io = io.BytesIO(audio_to_transcribe)
                # Assign a dummy name for the file-like object, as 'path' might inspect it
                audio_io.name = "recorded_audio.wav" 

                audio_file = genai.upload_file(
                    path=audio_io, # Pass the BytesIO object to 'path'
                    mime_type=mime_type,
                    display_name="recorded_audio.wav"
                )
                
                # Wait for the file to be processed
                while audio_file.state.name == "PROCESSING":
                    st.info("File is still processing...")
                    import time
                    time.sleep(1) 
                    # Use genai.get_file to check status (it's a top-level function)
                    audio_file = genai.get_file(audio_file.name) 

                prompt = "Transcribe the given audio accurately. Provide only the spoken text."
                
                response = model.generate_content([audio_file, prompt])
                
                st.subheader("Transcription Result:")
                st.write(response.text)
                st.success("Transcription complete!")

            except GoogleAPIError as api_err:
                st.error(f"Gemini API Error: {api_err.message}")
                st.info("Please check your API key, ensure billing is enabled on your Google Cloud project, and try again. For very long audios, you might hit model limits or need to process in chunks (advanced).")
                st.exception(api_err)
            except Exception as e:
                st.error(f"An unexpected error occurred during transcription: {e}")
                st.info("Ensure the audio recording was successful and check the `google-generativeai` library version.")
                st.exception(e)