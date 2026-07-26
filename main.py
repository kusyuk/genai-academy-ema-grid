import os
import asyncio
import logging
import json
import base64
import datetime
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Gen AI Academy APAC Edition: Protoype Submission
# • Muhammad Ku Sukry bin Muhammad Mustafa (kusyuk@gmail.com)
#
# Project Summary: EMA - Elderly Medical Assistant, a Multi-agent 
# AI-driven Elderly Medical Assistant for Elderly patients who struggle to understand complex medical jargon
# with capabilities to schedule appointment, tasks, reminder, and more
# ---------------------------------------------------------------------------

# --- 1. ENVIRONMENT CONFIGURATION ---
load_dotenv()

# --- CRITICAL: FAST-PATH CREDENTIAL CLEANUP ---
# Clears GOOGLE_APPLICATION_CREDENTIALS if the file does not exist,
# allowing the SDK to fall back to Application Default Credentials.
_creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if _creds_path and not os.path.exists(_creds_path):
    logging.info(f"Clearing missing credential path: {_creds_path}")
    os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

PROJECT_ID = os.getenv("PROJECT_ID")
LOCATION = os.getenv("LOCATION", "us-central1")

if not PROJECT_ID:
    raise ValueError("PROJECT_ID must be set in .env")

# Force regional configuration for Vertex AI
os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID
os.environ["GOOGLE_CLOUD_LOCATION"] = LOCATION
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

# --- 2. LOGGING SETUP ---
import google.cloud.logging
try:
    # google.cloud.logging.Client().setup_logging()
    pass
except Exception:
    pass
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.info("Logging initialized (Cloud Logging enabled).")

# --- 3. ADK & FASTAPI IMPORTS ---
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from google.adk.apps.app import App
from google.adk.runners import InMemoryRunner
from google.adk.sessions import InMemorySessionService
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types

from ema_agent import root_agent
from ema_agent.tools import credentials, db_client, CALENDAR_ID
from google.cloud import firestore

# Import Grid Agent
from grid_agent import root_agent as grid_root_agent

# --- 4. APP & RUNNER INITIALIZATION ---
APP_NAME = "ema-assistant"
ema_app = App(name=APP_NAME, root_agent=root_agent)
agent_runner = InMemoryRunner(app=ema_app)

GRID_APP_NAME = "ema-grid"
grid_app = App(name=GRID_APP_NAME, root_agent=grid_root_agent)
grid_runner = InMemoryRunner(app=grid_app)

# --- 5. TTS & STT HELPERS ---
import struct

# --- TTS via Google Cloud Text-to-Speech ---
from google.cloud import texttospeech_v1

tts_client = texttospeech_v1.TextToSpeechAsyncClient()

async def generate_voice_response(text: str):
    """Generates audio using Google Cloud Text-to-Speech API.
    
    Returns raw LINEAR16 (PCM) audio bytes at 24kHz for playback.
    """
    try:
        synthesis_input = texttospeech_v1.SynthesisInput(text=text)
        voice = texttospeech_v1.VoiceSelectionParams(
            language_code="en-US",
            name="en-US-Studio-O",
            ssml_gender=texttospeech_v1.SsmlVoiceGender.FEMALE,
        )
        audio_config = texttospeech_v1.AudioConfig(
            audio_encoding=texttospeech_v1.AudioEncoding.LINEAR16,
            sample_rate_hertz=24000,
        )
        response = await tts_client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        # LINEAR16 response includes a WAV header; strip it (44 bytes) for raw PCM
        audio_content = response.audio_content
        if len(audio_content) > 44:
            return audio_content[44:]
        return audio_content
    except Exception as e:
        logging.error(f"TTS Error: {e}")
        return None


def _make_wav_header(pcm_data: bytes, sample_rate: int = 16000,
                     bits_per_sample: int = 16, channels: int = 1) -> bytes:
    """Creates a valid WAV file from raw PCM bytes."""
    data_size = len(pcm_data)
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF',
        36 + data_size,
        b'WAVE',
        b'fmt ',
        16,
        1,  # PCM format
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b'data',
        data_size,
    )
    return header + pcm_data


# --- STT via Gemini Flash ---
from google.genai import Client
genai_client = Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

async def transcribe_audio(audio_bytes: bytes) -> str:
    """Transcribes audio using Gemini Flash.

    Wraps raw 16-bit PCM into a WAV container so the model
    can correctly parse sample rate/format metadata.

    Uses run_in_executor to avoid blocking the asyncio event loop
    with the synchronous Gemini SDK call.
    """
    try:
        wav_bytes = _make_wav_header(audio_bytes, sample_rate=16000)
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: genai_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
                    "Please transcribe this audio accurately. Only return the transcription text, nothing else."
                ]
            )
        )
        return response.text
    except Exception as e:
        logging.error(f"STT Error: {e}")
        return ""

# --- ACTIVE WEBSOCKETS REGISTRY FOR TELEMETRY BROADCAST ---
active_websockets = set()

# --- Post-Session Summary Helper ---
async def _save_session_summary(user_id: str, session_id: str):
    """Summarizes the conversation session, updates the patient's Firestore record,
    and streams structured telemetry into BigQuery `ema_grid.symptom_reports`.
    """
    try:
        session_obj = await agent_runner.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
        if not session_obj or not hasattr(session_obj, 'state'):
            return
            
        patient_id = session_obj.state.get("PATIENT_ID") or user_id or "patient_123"

        # Extract user messages to understand what new info was discussed
        user_inputs = []
        events = getattr(session_obj, 'events', []) or getattr(session_obj, 'history', []) or []
        for event in events:
            if getattr(event, 'author', None) == 'user':
                content = getattr(event, 'content', None)
                if content and hasattr(content, 'parts') and content.parts:
                    for part in content.parts:
                        if hasattr(part, 'text') and part.text and part.text != "__START_SESSION__":
                            user_inputs.append(part.text)
            elif hasattr(event, 'message') and event.message and hasattr(event.message, 'parts'):
                for part in event.message.parts:
                    if hasattr(part, 'text') and part.text and part.text != "__START_SESSION__":
                        user_inputs.append(part.text)
                        
        if not user_inputs:
            return
            
        transcript = "\n".join(f"- {msg}" for msg in user_inputs)
        
        # 1. Closed-loop Firestore Update
        try:
            prompt = (
                "You are a clinical summarizer. Review the following patient inputs from a session. "
                "Write a very concise, precise clinical log entry using appropriate medical jargon. "
                "Focus only on new symptoms, medical requests, or scheduled follow-ups. "
                "If it was just a casual greeting with no medical info, reply with 'NO_MEDICAL_INFO'.\n\n"
                f"Patient Inputs:\n{transcript}"
            )
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: genai_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[prompt]
                )
            )
            
            summary = response.text.strip()
            if summary != "NO_MEDICAL_INFO" and summary:
                doc_ref = db_client.collection('patients').document(patient_id)
                new_entry = {
                    "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
                    "notes": summary
                }
                await loop.run_in_executor(
                    None,
                    lambda: doc_ref.update({"history": firestore.ArrayUnion([new_entry])})
                )
                logging.info(f"[{user_id}:{session_id}] Closed-loop memory saved to Firestore for patient '{patient_id}'.")
        except Exception as fs_err:
            logging.warning(f"[{user_id}:{session_id}] Firestore closed-loop memory update warning: {fs_err}")
            summary = "Patient clinical update"

        # 2. STREAM TELEMETRY TO BIGQUERY & BROADCAST TO WEBSOCKET CONSOLES
        try:
            _creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            if _creds_path and not os.path.exists(_creds_path):
                os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

            telemetry_prompt = (
                "Analyze this patient transcript and return JSON ONLY with exact keys:\n"
                "- 'symptom_cluster': string, exactly one of ['Respiratory', 'Gastrointestinal', 'Cardiac', 'Neurological', 'Skin/Allergy']\n"
                "- 'severity': string, exactly one of ['Low', 'Medium', 'High']\n"
                "- 'region': string, district name (default to 'North District')\n"
                "- 'notes_summary': concise symptom complaint\n\n"
                f"Transcript:\n{transcript}"
            )
            telemetry_res = await loop.run_in_executor(
                None,
                lambda: genai_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[telemetry_prompt],
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
            )
            telemetry_data = json.loads(telemetry_res.text)
            
            bq_record = {
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                "region": telemetry_data.get("region", "North District"),
                "symptom_cluster": telemetry_data.get("symptom_cluster", "Respiratory"),
                "severity": telemetry_data.get("severity", "Medium"),
                "patient_age": 74,
                "is_emergency": telemetry_data.get("severity") == "High",
                "notes_summary": telemetry_data.get("notes_summary", summary)
            }
            
            logging.info(
                f"⚡ [TELEMETRY BRIDGE] Extracted patient telemetry: "
                f"{bq_record['region']} | {bq_record['symptom_cluster']} | {bq_record['severity']}"
            )
            
            # 3. Broadcast to active WebSocket connections for Live Console Logging IMMEDIATELY
            telemetry_event = {
                "type": "telemetry_stream",
                "data": bq_record
            }
            for ws in list(active_websockets):
                try:
                    await ws.send_text(json.dumps(telemetry_event))
                except Exception as ws_err:
                    logging.warning(f"Error broadcasting telemetry over WebSocket: {ws_err}")

            # 4. Stream row into BigQuery dataset
            try:
                bq_dataset = os.getenv("BIGQUERY_DATASET", "ema_grid")
                bq_table_ref = bigquery.Client(project=PROJECT_ID).dataset(bq_dataset).table("symptom_reports")
                insert_errs = bigquery.Client(project=PROJECT_ID).insert_rows_json(bq_table_ref, [bq_record])
                if insert_errs:
                    logging.error(f"BigQuery Telemetry Stream insert warning: {insert_errs}")
                else:
                    logging.info(f"Successfully inserted telemetry row to BigQuery `{bq_dataset}.symptom_reports`.")
            except Exception as bq_insert_err:
                logging.error(f"BigQuery Telemetry insert exception: {bq_insert_err}")

        except Exception as bq_err:
            logging.error(f"Error extracting telemetry: {bq_err}", exc_info=True)

    except Exception as e:
        logging.error(f"[{user_id}:{session_id}] Error saving session summary: {e}", exc_info=True)



# --- 5a. WATCHDOG & LIFESPAN (defined before app for constructor injection) ---

async def calendar_watchdog():
    """Background task: polls Google Calendar every 60 s and writes
    upcoming-event notifications to Firestore."""
    logging.info("Starting Calendar Watchdog...")
    from googleapiclient.discovery import build
    loop = asyncio.get_running_loop()
    service = await loop.run_in_executor(
        None,
        lambda: build('calendar', 'v3', credentials=credentials)
    )
    notified_events: set = set()
    while True:
        try:
            now = datetime.datetime.now(datetime.UTC).isoformat().replace(
                '+00:00', 'Z'
            )
            in_one_hour = (
                datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
            ).isoformat().replace('+00:00', 'Z')
            events_result = service.events().list(
                calendarId=CALENDAR_ID,
                timeMin=now,
                timeMax=in_one_hour,
                singleEvents=True,
                orderBy='startTime',
            ).execute()
            for event in events_result.get('items', []):
                event_id = event.get('id')
                if event_id not in notified_events:
                    db_client.collection('notifications').add({
                        "title": "Upcoming Appointment",
                        "message": f"Reminder: '{event.get('summary')}' is coming up soon.",
                        "time": event.get('start', {}).get('dateTime'),
                        "created_at": datetime.datetime.now(datetime.UTC),
                        "status": "unread",
                    })
                    notified_events.add(event_id)
        except Exception as e:
            from googleapiclient.errors import HttpError
            if isinstance(e, HttpError) and e.resp.status == 404:
                logging.warning(
                    f"Calendar Watchdog: Calendar ID '{CALENDAR_ID}' not found."
                )
            else:
                logging.error(f"Watchdog Error: {e}")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: starts the calendar watchdog on startup."""
    watchdog_task = asyncio.create_task(calendar_watchdog())
    yield
    watchdog_task.cancel()
    try:
        await watchdog_task
    except asyncio.CancelledError:
        pass


# --- 5b. FASTAPI APPLICATION ---

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 5. WEBSOCKET ENDPOINT ---

@app.websocket("/ws/{user_id}/{session_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str, session_id: str):
    await websocket.accept()
    active_websockets.add(websocket)
    logging.info(f"[{user_id}:{session_id}] WebSocket accepted (Turn-based flow).")

    # Ensure session exists in the runner's session service
    session = await agent_runner.session_service.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    if not session:
        await agent_runner.session_service.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)

    # State for current turn
    audio_buffer = bytearray()
    pending_images = []
    tts_enabled = True # Defaults to True until the client syncs it

    def _strip_markdown_for_tts(text: str) -> str:
        """Remove markdown formatting and URLs so TTS reads natural prose."""
        import re
        text = re.sub(r'```[\s\S]*?```', '', text)
        text = re.sub(r'`([^`]*)`', r'\1', text)
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'https?://[^\s<>\[\](){}"\']+', '', text)
        text = re.sub(r'\(\s*\)', '', text)
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
        text = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', text)
        text = re.sub(r'~~([^~]+)~~', r'\1', text)
        text = re.sub(r'^>\s?', '', text, flags=re.MULTILINE)
        text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*(\d+)\.\s+', r'\1. ', text, flags=re.MULTILINE)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'  +', ' ', text)
        return text.strip()

    async def _send_tts_audio(text: str):
        if not tts_enabled:
            logging.info(f"[{user_id}:{session_id}] TTS is disabled by user. Skipping voice generation.")
            return

        try:
            clean_text = _strip_markdown_for_tts(text)
            logging.info(f"[{user_id}:{session_id}] Generating voice for response...")
            audio_bytes = await generate_voice_response(clean_text)
            if audio_bytes and websocket.client_state.name == "CONNECTED":
                audio_event = {
                    "content": {
                        "parts": [{
                            "inlineData": {
                                "mimeType": "audio/pcm;rate=24000",
                                "data": base64.b64encode(audio_bytes).decode()
                            }
                        }]
                    }
                }
                await websocket.send_text(json.dumps(audio_event))
        except Exception as e:
            logging.error(f"[{user_id}:{session_id}] TTS background task error: {e}", exc_info=True)

    async def process_turn(content_parts, state_delta=None):
        turn_complete_sent = False
        try:
            final_text = ""

            async for event in agent_runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=types.Content(parts=content_parts),
                state_delta=state_delta
            ):
                await websocket.send_text(
                    event.model_dump_json(exclude_none=True, by_alias=True)
                )

                if getattr(event, 'turn_complete', False):
                    turn_complete_sent = True

                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text:
                            final_text += part.text
            if state_delta and "LATEST_IMAGE_BASE64" in state_delta:
                try:
                    session_obj = await agent_runner.session_service.get_session(
                        app_name=APP_NAME, user_id=user_id, session_id=session_id
                    )
                    if session_obj and hasattr(session_obj, 'state'):
                        session_obj.state.pop("LATEST_IMAGE_BASE64", None)
                        session_obj.state.pop("LATEST_IMAGE_MIME", None)
                except Exception:
                    pass  
            if final_text:
                asyncio.create_task(_send_tts_audio(final_text))
                # Trigger live telemetry streaming to BigQuery & WebSocket broadcast immediately upon turn completion
                asyncio.create_task(_save_session_summary(user_id, session_id))

        except Exception as e:
            logging.error(f"[{user_id}:{session_id}] Turn processing error: {e}", exc_info=True)
            error_msg = {"type": "error", "error": {"message": str(e)}}
            await websocket.send_text(json.dumps(error_msg))
        finally:
            if not turn_complete_sent:
                await websocket.send_text(json.dumps({"turnComplete": True}))

    try:
        while True:
            data = await websocket.receive()
            if "bytes" in data:
                audio_buffer.extend(data["bytes"])
            elif "text" in data:
                msg = json.loads(data["text"])
                if "tts_preference" in msg:
                    tts_enabled = msg["tts_preference"]
                    logging.info(f"[{user_id}:{session_id}] TTS preference updated: {'Enabled' if tts_enabled else 'Disabled'}")
                    continue

                msg_type = msg.get("type")
                if msg_type == "text":
                    text_val = msg.get("text", "")
                    logging.info(f"[{user_id}:{session_id}] Received text turn: {text_val[:50]}...")
                    if text_val == "__START_SESSION__":
                        text_val = "Hello! I am Ahmad. Please introduce yourself as EMA and ask me how I am feeling today."
                    
                    parts = []
                    turn_state_delta = None
                    image_base64 = msg.get("image")
                    if image_base64:
                        mime_type = msg.get("mimeType", "image/jpeg")
                        image_data = base64.b64decode(image_base64)
                        turn_state_delta = {
                            "LATEST_IMAGE_BASE64": image_base64,
                            "LATEST_IMAGE_MIME": mime_type,
                        }
                        parts.append(types.Part(inline_data=types.Blob(
                            mime_type=mime_type, 
                            data=image_data
                        )))
                        
                    parts.append(types.Part(text=text_val))
                    if pending_images:
                        parts.extend(pending_images)
                        pending_images = []
                    
                    await process_turn(parts, state_delta=turn_state_delta)
                
                elif msg_type == "image":
                    image_data_base64 = msg["data"]
                    image_data = base64.b64decode(image_data_base64)
                    mime_type = msg.get("mimeType", "image/jpeg")
                    image_state_delta = {
                        "LATEST_IMAGE_BASE64": image_data_base64,
                        "LATEST_IMAGE_MIME": mime_type
                    }
                    image_part = types.Part(inline_data=types.Blob(
                        mime_type=mime_type, 
                        data=image_data
                    ))
                    await process_turn([image_part], state_delta=image_state_delta)
                
                elif msg_type == "audio_stop":
                    if audio_buffer:
                        await websocket.send_text(json.dumps({
                            "inputTranscription": {"text": "_TRANSCRIBING_", "finished": False}
                        }))
                        transcription = await transcribe_audio(bytes(audio_buffer))
                        audio_buffer.clear()
                        if transcription.strip():
                            await websocket.send_text(json.dumps({
                                "inputTranscription": {"text": transcription, "finished": True}
                            }))
                            parts = []
                            if pending_images:
                                parts.extend(pending_images)
                                pending_images = []
                            parts.append(types.Part(text=transcription))
                            await process_turn(parts)
                        else:
                            await websocket.send_text(json.dumps({
                                "inputTranscription": {"text": "(Unintelligible)", "finished": True}
                            }))
                    else:
                        logging.warning(f"[{user_id}:{session_id}] Audio stop received but buffer is empty.")

    except Exception as e:
        logging.info(f"[{user_id}:{session_id}] WebSocket disconnected or error: {e}")
    finally:
        active_websockets.discard(websocket)
        asyncio.create_task(_save_session_summary(user_id, session_id))


@app.websocket("/ws/grid/{user_id}/{session_id}")
async def websocket_grid_endpoint(websocket: WebSocket, user_id: str, session_id: str):
    await websocket.accept()
    active_websockets.add(websocket)
    logging.info(f"[Grid:{user_id}:{session_id}] WebSocket accepted.")

    session = await grid_runner.session_service.get_session(app_name=GRID_APP_NAME, user_id=user_id, session_id=session_id)
    if not session:
        await grid_runner.session_service.create_session(app_name=GRID_APP_NAME, user_id=user_id, session_id=session_id)

    async def process_turn(content_parts):
        turn_complete_sent = False
        try:
            async for event in grid_runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=types.Content(parts=content_parts)
            ):
                await websocket.send_text(
                    event.model_dump_json(exclude_none=True, by_alias=True)
                )
                if getattr(event, 'turn_complete', False):
                    turn_complete_sent = True
        except Exception as e:
            logging.error(f"[Grid:{user_id}:{session_id}] Turn processing error: {e}", exc_info=True)
            error_msg = {"type": "error", "error": {"message": str(e)}}
            await websocket.send_text(json.dumps(error_msg))
        finally:
            if not turn_complete_sent:
                await websocket.send_text(json.dumps({"turnComplete": True}))

    try:
        while True:
            data = await websocket.receive()
            if "text" in data:
                msg = json.loads(data["text"])
                msg_type = msg.get("type")
                if msg_type == "text":
                    text_val = msg.get("text", "")
                    logging.info(f"[Grid:{user_id}:{session_id}] Received text turn: {text_val[:50]}...")
                    if text_val == "__START_SESSION__":
                        text_val = "Welcome me and ask how you can help optimize staffing and track outbreaks today."
                    await process_turn([types.Part(text=text_val)])
    except Exception as e:
        logging.info(f"[Grid:{user_id}:{session_id}] WebSocket disconnected or error: {e}")
    finally:
        active_websockets.discard(websocket)


from google.cloud import bigquery
@app.get("/api/grid/dashboard")
async def get_grid_dashboard():
    try:
        _creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if _creds_path and not os.path.exists(_creds_path):
            os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
            
        client = bigquery.Client(project=PROJECT_ID)
        dataset = os.getenv("BIGQUERY_DATASET", "ema_grid")
        
        # 1. Symptom Telemetry
        query = f"""
        SELECT region, symptom_cluster, COUNT(*) as cases, MAX(timestamp) as last_report
        FROM `{PROJECT_ID}.{dataset}.symptom_reports`
        WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
        GROUP BY region, symptom_cluster
        ORDER BY cases DESC
        """
        rows = list(client.query(query).result())
        telemetry = [{
            "region": r.region,
            "symptom_cluster": r.symptom_cluster,
            "cases": r.cases,
            "last_report": r.last_report.isoformat() if r.last_report else None
        } for r in rows]

        # 2. Medical Supplies Inventory
        supplies_query = f"""
        SELECT region, item_name, current_stock, daily_burn_rate, days_of_supply, supply_status
        FROM `{PROJECT_ID}.{dataset}.medical_supplies`
        ORDER BY current_stock ASC
        """
        supplies_rows = list(client.query(supplies_query).result())
        supplies = [{
            "region": r.region,
            "item_name": r.item_name,
            "current_stock": r.current_stock,
            "daily_burn_rate": r.daily_burn_rate,
            "days_of_supply": r.days_of_supply,
            "supply_status": r.supply_status
        } for r in supplies_rows]

        # 3. Hospital Capacity & Beds
        hospital_query = f"""
        SELECT region, facility_name, total_beds, occupied_beds, icu_beds_total, icu_beds_occupied, ventilators_available, occupancy_rate_pct
        FROM `{PROJECT_ID}.{dataset}.hospital_capacity`
        ORDER BY occupancy_rate_pct DESC
        """
        hospital_rows = list(client.query(hospital_query).result())
        hospitals = [{
            "region": r.region,
            "facility_name": r.facility_name,
            "total_beds": r.total_beds,
            "occupied_beds": r.occupied_beds,
            "icu_beds_total": r.icu_beds_total,
            "icu_beds_occupied": r.icu_beds_occupied,
            "ventilators_available": r.ventilators_available,
            "occupancy_rate_pct": r.occupancy_rate_pct
        } for r in hospital_rows]
            
        # Calculate staffing status based on cases
        staffing_alerts = []
        region_cases = {}
        for r in telemetry:
            region_cases[r["region"]] = region_cases.get(r["region"], 0) + r["cases"]
            
        for region, cases in region_cases.items():
            if cases > 150:
                staffing_alerts.append({
                    "region": region,
                    "status": "CRITICAL",
                    "message": f"High outbreak load ({cases} cases). Recommend deploying emergency nursing staff."
                })
            elif cases > 80:
                staffing_alerts.append({
                    "region": region,
                    "status": "WARNING",
                    "message": f"Moderate load ({cases} cases). Monitor workforce closely."
                })
            else:
                staffing_alerts.append({
                    "region": region,
                    "status": "STABLE",
                    "message": f"Normal load ({cases} cases). Staffing is sufficient."
                })
                
        return {
            "telemetry": telemetry,
            "supplies": supplies,
            "hospitals": hospitals,
            "staffing_alerts": staffing_alerts
        }
    except Exception as e:
        logging.error(f"Error serving dashboard telemetry: {e}")
        return {"telemetry": [], "supplies": [], "hospitals": [], "staffing_alerts": []}



# --- 6. HEALTH CHECK & NOTIFICATIONS API ---

@app.get("/health")
async def health_check():
    """Health check endpoint for Cloud Run startup probe."""
    return {"status": "ok", "service": APP_NAME}


@app.get("/notifications")
async def get_notifications():
    """Returns unread notifications written by the calendar watchdog.

    The frontend polls this every 10 seconds and marks notifications read
    by calling DELETE /notifications/{doc_id}.
    """
    try:
        docs = db_client.collection('notifications') \
            .where(filter=firestore.FieldFilter('status', '==', 'unread')) \
            .order_by('created_at', direction=firestore.Query.DESCENDING) \
            .limit(10) \
            .stream()
        notifications = [
            {"id": doc.id, **doc.to_dict()} for doc in docs
        ]
        # Convert datetime objects to ISO strings for JSON serialisation
        for n in notifications:
            if hasattr(n.get('created_at'), 'isoformat'):
                n['created_at'] = n['created_at'].isoformat()
        return {"notifications": notifications}
    except Exception as e:
        logging.error(f"Notifications fetch error: {e}")
        return {"notifications": []}


@app.delete("/notifications/{doc_id}")
async def dismiss_notification(doc_id: str):
    """Marks a notification as read (dismissed by the user)."""
    try:
        db_client.collection('notifications').document(doc_id).update(
            {"status": "read"}
        )
        return {"status": "ok"}
    except Exception as e:
        logging.error(f"Notification dismiss error: {e}")
        return {"status": "error", "message": str(e)}


# --- 7. STATIC FILES & SPA ---

app.mount("/static", StaticFiles(directory="ui"), name="static")

@app.get("/{full_path:path}")
async def serve_spa(request: Request, full_path: str):
    file_path = os.path.join("ui", full_path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    return FileResponse("ui/index.html")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)

