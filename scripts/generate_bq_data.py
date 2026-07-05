import os
import random
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from google.cloud import bigquery
from google.api_core.exceptions import Conflict

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Load environment variables
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
DATASET_ID = os.getenv("BIGQUERY_DATASET", "ema_grid")
TABLE_ID = "symptom_reports"

if not PROJECT_ID:
    raise ValueError("PROJECT_ID is not set in environment or .env file.")

def get_bigquery_client():
    return bigquery.Client(project=PROJECT_ID)

def setup_bigquery_resources(client):
    dataset_ref = bigquery.DatasetReference(PROJECT_ID, DATASET_ID)
    
    # 1. Create Dataset if not exists
    try:
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = "US"  # BigQuery multi-region default
        dataset = client.create_dataset(dataset, timeout=30)
        logging.info(f"Created dataset {PROJECT_ID}.{DATASET_ID}")
    except Conflict:
        logging.info(f"Dataset {PROJECT_ID}.{DATASET_ID} already exists.")
    except Exception as e:
        logging.error(f"Error creating dataset: {e}")
        raise

    # 2. Create Table
    table_ref = dataset_ref.table(TABLE_ID)
    schema = [
        bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("region", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("symptom_cluster", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("severity", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("patient_age", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("is_emergency", "BOOLEAN", mode="REQUIRED"),
        bigquery.SchemaField("notes_summary", "STRING", mode="NULLABLE"),
    ]
    
    # Delete the table first if it exists to refresh schema
    try:
        client.delete_table(table_ref, not_found_ok=True)
        logging.info(f"Deleted old table {PROJECT_ID}.{DATASET_ID}.{TABLE_ID} to refresh schema.")
    except Exception as e:
        logging.warning(f"Could not delete old table: {e}")
        
    try:
        table = bigquery.Table(table_ref, schema=schema)
        table = client.create_table(table, timeout=30)
        logging.info(f"Created table {PROJECT_ID}.{DATASET_ID}.{TABLE_ID}")
    except Exception as e:
        logging.error(f"Error creating table: {e}")
        raise

def get_notes_and_emergency(symptom_cluster, severity):
    is_emergency = severity == "High"
    
    notes_options = {
        "Respiratory": {
            "Low": ["Mild seasonal congestion", "Slight dry tickle in throat", "Routine inhaler checkup"],
            "Medium": ["Persistent productive cough", "Mild wheezing, stable", "Low-grade fever and congestion"],
            "High": ["Acute shortness of breath", "Severe chest congestion with high fever", "Respiratory distress"]
        },
        "Gastrointestinal": {
            "Low": ["Mild bloating after meals", "Slight nausea, resolved", "Routine dietary consultation"],
            "Medium": ["Moderate abdominal cramps", "Loose stools for 2 days", "Mild nausea and vomiting"],
            "High": ["Severe abdominal pain with vomiting", "Acute dehydration from diarrhea", "Suspected food poisoning, high pain"]
        },
        "Cardiac": {
            "Low": ["Routine blood pressure monitoring", "Mild fatigue, stable pulse", "Annual cardiac wellness review"],
            "Medium": ["Occasional mild palpitations", "Slight ankle swelling", "Controlled hypertension review"],
            "High": ["Severe crushing chest pain", "Acute shortness of breath with racing pulse", "Suspected myocardial infarction"]
        },
        "Neurological": {
            "Low": ["Mild tension headache", "Routine memory review", "Slight dizziness after standing"],
            "Medium": ["Moderate migraine headache", "Persistent mild vertigo", "Controlled tremor monitoring"],
            "High": ["Sudden numbness in left arm", "Acute slurred speech and confusion", "Severe headache with loss of balance"]
        },
        "Skin/Allergy": {
            "Low": ["Mild dry skin patch", "Slight redness from soap", "Routine eczema review"],
            "Medium": ["Moderate localized hives", "Itchy skin rash, stable", "Mild allergic reaction to pollen"],
            "High": ["Severe anaphylactic rash", "Widespread painful hives", "Allergic reaction with facial swelling"]
        }
    }
    
    cluster_notes = notes_options.get(symptom_cluster, {})
    severity_notes = cluster_notes.get(severity, ["General symptoms reported"])
    return random.choice(severity_notes), is_emergency

def generate_dummy_data():
    regions = ["North District", "South District", "East Valley", "West Side", "Central Hub"]
    symptom_clusters = ["Respiratory", "Gastrointestinal", "Cardiac", "Neurological", "Skin/Allergy"]
    severities = ["Low", "Medium", "High"]
    
    rows = []
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    # Generate baseline data (random spread)
    for _ in range(800):
        random_days = random.random() * 30
        ts = start_date + timedelta(days=random_days)
        reg = random.choice(regions)
        sym = random.choice(symptom_clusters)
        sev = random.choice(severities)
        age = random.randint(60, 95)
        notes, is_em = get_notes_and_emergency(sym, sev)
        
        rows.append({
            "timestamp": ts.isoformat(),
            "region": reg,
            "symptom_cluster": sym,
            "severity": sev,
            "patient_age": age,
            "is_emergency": is_em,
            "notes_summary": notes
        })
        
    # Generate an "outbreak spike" in the last 7 days
    # Spike: Respiratory, High Severity, in North District
    spike_start = end_date - timedelta(days=7)
    for _ in range(250):
        random_days = random.random() * 7
        ts = spike_start + timedelta(days=random_days)
        reg = "North District"
        sym = "Respiratory"
        sev = random.choice(["Medium", "High", "High"])
        age = random.randint(65, 90)
        notes, is_em = get_notes_and_emergency(sym, sev)
        
        rows.append({
            "timestamp": ts.isoformat(),
            "region": reg,
            "symptom_cluster": sym,
            "severity": sev,
            "patient_age": age,
            "is_emergency": is_em,
            "notes_summary": notes
        })
        
    # Generate another smaller spike: Gastrointestinal in East Valley in last 10 days
    spike2_start = end_date - timedelta(days=10)
    for _ in range(80):
        random_days = random.random() * 10
        ts = spike2_start + timedelta(days=random_days)
        reg = "East Valley"
        sym = "Gastrointestinal"
        sev = random.choice(["Low", "Medium", "High"])
        age = random.randint(60, 85)
        notes, is_em = get_notes_and_emergency(sym, sev)
        
        rows.append({
            "timestamp": ts.isoformat(),
            "region": reg,
            "symptom_cluster": sym,
            "severity": sev,
            "patient_age": age,
            "is_emergency": is_em,
            "notes_summary": notes
        })
        
    return rows

def main():
    logging.info("Starting BigQuery environment setup...")
    client = get_bigquery_client()
    setup_bigquery_resources(client)
    
    logging.info("Generating mock patient symptom telemetry...")
    data = generate_dummy_data()
    
    logging.info(f"Uploading {len(data)} records to BigQuery...")
    table_ref = client.dataset(DATASET_ID).table(TABLE_ID)
    
    # We load the rows in chunks of 500 to be safe
    chunk_size = 500
    for i in range(0, len(data), chunk_size):
        chunk = data[i:i+chunk_size]
        errors = client.insert_rows_json(table_ref, chunk)
        if errors:
            logging.error(f"Failed to insert chunk starting at {i}: {errors}")
            return
        logging.info(f"Uploaded chunk {i//chunk_size + 1}...")

    logging.info("BigQuery environment setup and mock data generation complete!")

if __name__ == "__main__":
    main()
