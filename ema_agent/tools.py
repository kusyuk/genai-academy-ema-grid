import asyncio
import os
import base64
import datetime
import logging
from typing import Optional
import google.auth
from google import genai
from google.genai import types
from google.cloud import firestore
from googleapiclient.discovery import build
from google.adk.tools.tool_context import ToolContext
from langchain_community.tools import WikipediaQueryRun
from langchain_community.utilities import WikipediaAPIWrapper
from google.adk.tools.langchain_tool import LangchainTool

# ---------------------------------------------------------------------------
# Gen AI Academy APAC Edition: Protoype Submission
# • Muhammad Ku Sukry bin Muhammad Mustafa (kusyuk@gmail.com)
#
# Project Summary: EMA - Elderly Medical Assistant, a Multi-agent 
# AI-driven Elderly Medical Assistant for Elderly patients who struggle to understand complex medical jargon
# with capabilities to schedule appointment, tasks, reminder, and more
# ---------------------------------------------------------------------------

# --- CONFIGURATION ---
PROJECT_ID = os.getenv("PROJECT_ID")
LOCATION = os.getenv("LOCATION", "us-central1")
CALENDAR_ID = os.getenv("CALENDAR_ID", "primary")
DOCUMENT_ID = os.getenv("DOCUMENT_ID")
VISION_MODEL = "gemini-2.5-flash"

# --- SCOPES ---
SCOPES = [
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/tasks',
    'https://www.googleapis.com/auth/keep',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/cloud-platform'
]

# --- INITIALIZATION ---
credentials, _ = google.auth.default(scopes=SCOPES)
db_client = firestore.Client(project=PROJECT_ID, database="ema-hackathon")
genai_client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

# --- TOOLS ---

async def process_medical_note(
    tool_context: ToolContext,
    image_base64: Optional[str] = None,
    mime_type: str = "image/jpeg",
):
    """Parses a physical medical note from an image.

    If image_base64 is not provided, looks for the latest image in session
    context (set by main.py via state_delta).
    """
    prompt = (
        "Analyze this medical note for an elderly patient. "
        "Extract the following accurately:\n"
        "- Doctor/Clinic Name\n"
        "- Date of Visit\n"
        "- Main Diagnosis or Reason for Visit\n"
        "- Medications (Name, Dosage, Frequency)\n"
        "- Follow-up instructions (e.g., next appointment, tests)\n\n"
        "Be extremely accurate with dosages. "
        "Return the findings in a warm, helpful summary."
    )
    try:
        if not image_base64:
            image_base64 = tool_context.state.get("LATEST_IMAGE_BASE64")
            mime_type = tool_context.state.get("LATEST_IMAGE_MIME", "image/jpeg")

        if not image_base64:
            return (
                "I'm sorry, I don't see the image of the note. "
                "Could you please try showing it to me again?"
            )

        image_bytes = base64.b64decode(image_base64)
        logging.info(
            f"Vision Tool: Sending image ({len(image_bytes)} bytes, "
            f"{mime_type}) to {VISION_MODEL}..."
        )
        loop = asyncio.get_event_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: genai_client.models.generate_content(
                    model=VISION_MODEL,
                    contents=[
                        types.Part.from_bytes(
                            data=image_bytes, mime_type=mime_type
                        ),
                        prompt,
                    ],
                ),
            ),
            timeout=60,
        )
        logging.info("Vision Tool: Response received successfully.")
        extraction = response.text

        tool_context.state["LAST_VISION_EXTRACTION"] = extraction

        patient_id = tool_context.state.get("PATIENT_ID")
        if patient_id:
            doc_ref = db_client.collection('patients').document(patient_id)
            doc_ref.update({"digitized_notes": firestore.ArrayUnion([{
                "date": datetime.date.today().isoformat(),
                "content": extraction,
                "type": "vision_extraction",
            }])})

        return (
            f"I've carefully analyzed that note for us. "
            f"Here is what I found:\n\n{extraction}"
        )
    except asyncio.TimeoutError:
        logging.error("Vision Tool Error: Timed out after 60s.")
        return (
            "I'm sorry, it's taking a bit too long to read that note. "
            "Could you try again in a moment? Sometimes a clearer photo "
            "helps me work faster."
        )
    except Exception as e:
        logging.error(f"Vision Tool Error: {e}", exc_info=True)
        return (
            f"I had a little trouble reading that image clearly: {e}. "
            "Could you try taking another photo, perhaps with a bit more light?"
        )

def save_consultation_context(tool_context: ToolContext, patient_id: str, transcript: str):
    """Caches patient ID and transcript in context state."""
    tool_context.state["PATIENT_ID"] = patient_id
    tool_context.state["TRANSCRIPT"] = transcript
    return f"Context for {patient_id} cached."

def get_patient_history(tool_context: ToolContext, name: str):
    """
    Fetches the patient's record by name (Ahmad/Zaiton).
    Pre-summarizes the past visit details for the agent's immediate context.
    """
    try:
        clean_name = name.split("'")[0].strip().capitalize()
        docs = db_client.collection('patients').where(
            filter=firestore.FieldFilter('name', '==', clean_name)
        ).stream()
        
        found = False
        for d in docs:
            found = True
            data = d.to_dict()
            tool_context.state["PATIENT_ID"] = d.id

            # Extract ALL fields from Firestore
            name_val = data.get('name', clean_name)
            age = data.get('age', 'unknown')
            allergies = data.get('allergies', 'None recorded')
            conditions = data.get('conditions', [])
            doctor = data.get('doctor', 'Not specified')
            medications = data.get('medications', [])
            last_visit = data.get('last_visit')
            history = data.get('history', [])

            # Format conditions list
            if isinstance(conditions, list):
                conditions_str = ', '.join(conditions) if conditions else 'No conditions recorded'
            else:
                conditions_str = str(conditions) if conditions else 'No conditions recorded'

            # Format medications list
            if isinstance(medications, list):
                medications_str = ', '.join(medications) if medications else 'No medications recorded'
            else:
                medications_str = str(medications) if medications else 'No medications recorded'

            # Build full history timeline (all entries, not just last)
            history_timeline = []
            for entry in history:
                date = entry.get('date', 'Unknown date')
                notes = entry.get('notes', 'No details')
                history_timeline.append(f"- {date}: {notes}")
            history_text = (
                '\n'.join(history_timeline)
                if history_timeline
                else 'No history entries yet.'
            )

            # Format last_visit (handles Firestore Timestamp)
            if last_visit:
                if hasattr(last_visit, 'strftime'):
                    last_visit_str = last_visit.strftime('%d %B %Y')
                else:
                    last_visit_str = str(last_visit)
            else:
                last_visit_str = 'No visit recorded'

            return {
                "name": name_val,
                "age": age,
                "allergies": allergies,
                "conditions": conditions_str,
                "doctor": doctor,
                "medications": medications_str,
                "last_visit": last_visit_str,
                "history_timeline": history_text,
                "digitized_notes": data.get('digitized_notes') or [],
            }
        
        if not found:
            return f"I couldn't find any medical records for someone named '{name}'. Could you please tell me if I should be looking for Ahmad or Zaiton? I want to make sure I have the right information to help you."
            
    except Exception as e:
        logging.error(f"Error in get_patient_history: {e}")
        return f"I'm having a little trouble accessing the records for {name} right now. Could you please tell me a bit more about how you've been feeling? I'm still here to listen and help however I can."


async def create_calendar_event(title: str, time: str):
    """Schedules a follow-up appointment in Google Calendar."""
    try:
        if not time.endswith('Z') and '+' not in time and '-' not in time[-6:]:
            time = time + 'Z'
        try:
            dt = datetime.datetime.fromisoformat(time.replace('Z', ''))
            end_time = (dt + datetime.timedelta(minutes=30)).isoformat() + 'Z'
        except Exception:
            end_time = time
        event = {
            'summary': title,
            'start': {'dateTime': time, 'timeZone': 'Asia/Kuala_Lumpur'},
            'end': {'dateTime': end_time, 'timeZone': 'Asia/Kuala_Lumpur'},
        }
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: build('calendar', 'v3', credentials=credentials)
                .events()
                .insert(calendarId=CALENDAR_ID, body=event)
                .execute(),
        )
        return f"Confirmed: {title} is now on your calendar."
    except Exception as e:
        logging.error(f"Failed to schedule calendar: {e}")
        return f"Failed to schedule calendar: {e}"

async def create_google_task(task_name: str):
    """Adds a task to Google Tasks."""
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: build('tasks', 'v1', credentials=credentials)
                .tasks()
                .insert(tasklist='@default', body={'title': f"EMA: {task_name}"})
                .execute(),
        )
        return f"Success: Added '{task_name}' to your task list."
    except Exception as e:
        logging.error(f"Failed to create task: {e}")
        return f"Failed to create task: {e}"

async def save_to_family_journal(summary: str):
    """Appends a heart-centered summary to a shared Google Doc.

    Uses EndOfSegmentLocation to safely append regardless of whether
    the document is empty or already has content — fixes the crash
    caused by endIndex - 1 on empty documents.
    """
    try:
        if not DOCUMENT_ID:
            return "Failed: DOCUMENT_ID environment variable is not set."
        new_text = (
            f"\n\n--- EMA FAMILY JOURNAL: "
            f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} ---\n"
            f"{summary}\n"
        )
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: build('docs', 'v1', credentials=credentials)
                .documents()
                .batchUpdate(
                    documentId=DOCUMENT_ID,
                    body={
                        'requests': [{
                            'insertText': {
                                'endOfSegmentLocation': {'segmentId': ''},
                                'text': new_text,
                            }
                        }]
                    },
                )
                .execute(),
        )
        return "SUCCESS: Update saved to Family Journal."
    except Exception as e:
        logging.error(f"Failed to sync with Journal: {e}")
        return f"Failed to sync with Journal: {e}"

def safe_wikipedia_search(query: str) -> str:
    """
    Search Wikipedia for the given query. 
    Returns a concise summary or a friendly message if no results are found.
    """
    try:
        # Initialize Langchain Wikipedia tool
        wiki = WikipediaQueryRun(
            api_wrapper=WikipediaAPIWrapper(top_k_results=1, doc_content_chars_max=1000)
        )
        result = wiki.run(query)
        if not result or "No good Wikipedia Search Result was found" in result:
            return f"I couldn't find any specific information about '{query}' on Wikipedia. Could you tell me more about it, or is there something else I can look up?"
        return result
    except Exception as e:
        logging.error(f"Wikipedia Tool Error: {str(e)}")
        return f"I encountered a small issue while looking up '{query}'. Let's try again in a moment, or feel free to ask me something else."

# --- LANGCHAIN TOOLS ---
wikipedia_tool = safe_wikipedia_search
