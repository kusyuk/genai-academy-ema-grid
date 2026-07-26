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
SUPPLIES_TABLE_ID = "medical_supplies"
HOSPITAL_TABLE_ID = "hospital_capacity"

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

    # 2. Create symptom_reports Table
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
    
    client.delete_table(table_ref, not_found_ok=True)
    table = bigquery.Table(table_ref, schema=schema)
    client.create_table(table, timeout=30)
    logging.info(f"Created table {PROJECT_ID}.{DATASET_ID}.{TABLE_ID}")

    # 3. Create medical_supplies Table
    supplies_table_ref = dataset_ref.table(SUPPLIES_TABLE_ID)
    supplies_schema = [
        bigquery.SchemaField("region", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("item_name", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("current_stock", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("daily_burn_rate", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("reorder_threshold", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("days_of_supply", "FLOAT", mode="REQUIRED"),
        bigquery.SchemaField("supply_status", "STRING", mode="REQUIRED"),
    ]
    client.delete_table(supplies_table_ref, not_found_ok=True)
    supplies_table = bigquery.Table(supplies_table_ref, schema=supplies_schema)
    client.create_table(supplies_table, timeout=30)
    logging.info(f"Created table {PROJECT_ID}.{DATASET_ID}.{SUPPLIES_TABLE_ID}")

    # 4. Create hospital_capacity Table
    hospital_table_ref = dataset_ref.table(HOSPITAL_TABLE_ID)
    hospital_schema = [
        bigquery.SchemaField("region", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("facility_name", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("total_beds", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("occupied_beds", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("icu_beds_total", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("icu_beds_occupied", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("ventilators_total", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("ventilators_available", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("occupancy_rate_pct", "FLOAT", mode="REQUIRED"),
    ]
    client.delete_table(hospital_table_ref, not_found_ok=True)
    hospital_table = bigquery.Table(hospital_table_ref, schema=hospital_schema)
    client.create_table(hospital_table, timeout=30)
    logging.info(f"Created table {PROJECT_ID}.{DATASET_ID}.{HOSPITAL_TABLE_ID}")

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
        
    # Generate an "outbreak spike" in the last 7 days: Respiratory in North District
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

def generate_medical_supplies_data():
    items = ["Oxygen Cylinders", "Ventilators", "N95 Mask Boxes", "Antiviral Therapy Packs", "PPE Kits"]
    regions_config = {
        "North District": {
            "Oxygen Cylinders": (18, 25, "CRITICAL_SHORTAGE"),
            "Ventilators": (4, 3, "LOW"),
            "N95 Mask Boxes": (45, 30, "LOW"),
            "Antiviral Therapy Packs": (20, 25, "CRITICAL_SHORTAGE"),
            "PPE Kits": (110, 50, "ADEQUATE"),
        },
        "West Side": {
            "Oxygen Cylinders": (320, 15, "SURPLUS"),
            "Ventilators": (28, 2, "SURPLUS"),
            "N95 Mask Boxes": (450, 20, "SURPLUS"),
            "Antiviral Therapy Packs": (210, 10, "SURPLUS"),
            "PPE Kits": (600, 30, "SURPLUS"),
        },
        "South District": {
            "Oxygen Cylinders": (150, 12, "ADEQUATE"),
            "Ventilators": (12, 2, "ADEQUATE"),
            "N95 Mask Boxes": (200, 15, "ADEQUATE"),
            "Antiviral Therapy Packs": (95, 8, "ADEQUATE"),
            "PPE Kits": (350, 20, "ADEQUATE"),
        },
        "East Valley": {
            "Oxygen Cylinders": (65, 18, "LOW"),
            "Ventilators": (8, 2, "ADEQUATE"),
            "N95 Mask Boxes": (120, 22, "LOW"),
            "Antiviral Therapy Packs": (50, 12, "LOW"),
            "PPE Kits": (220, 25, "ADEQUATE"),
        },
        "Central Hub": {
            "Oxygen Cylinders": (280, 20, "SURPLUS"),
            "Ventilators": (22, 3, "SURPLUS"),
            "N95 Mask Boxes": (500, 25, "SURPLUS"),
            "Antiviral Therapy Packs": (180, 15, "SURPLUS"),
            "PPE Kits": (550, 35, "SURPLUS"),
        }
    }
    
    rows = []
    for region, item_map in regions_config.items():
        for item_name, (stock, burn_rate, status) in item_map.items():
            reorder_threshold = burn_rate * 5
            days_remaining = round(stock / max(burn_rate, 1), 1)
            rows.append({
                "region": region,
                "item_name": item_name,
                "current_stock": stock,
                "daily_burn_rate": burn_rate,
                "reorder_threshold": reorder_threshold,
                "days_of_supply": days_remaining,
                "supply_status": status
            })
    return rows

def generate_hospital_capacity_data():
    facilities = [
        {"region": "North District", "name": "North General Hospital", "total": 350, "occ": 332, "icu_tot": 40, "icu_occ": 38, "vent_tot": 30, "vent_avail": 2},
        {"region": "North District", "name": "St. Jude Medical Center", "total": 200, "occ": 194, "icu_tot": 25, "icu_occ": 24, "vent_tot": 18, "vent_avail": 1},
        {"region": "West Side", "name": "Westside Regional Hospital", "total": 400, "occ": 210, "icu_tot": 50, "icu_occ": 22, "vent_tot": 35, "vent_avail": 20},
        {"region": "South District", "name": "Southside Memorial Hospital", "total": 280, "occ": 190, "icu_tot": 30, "icu_occ": 18, "vent_tot": 20, "vent_avail": 8},
        {"region": "East Valley", "name": "Valley Community Hospital", "total": 220, "occ": 175, "icu_tot": 25, "icu_occ": 20, "vent_tot": 15, "vent_avail": 4},
        {"region": "Central Hub", "name": "Central Metropolitan Medical", "total": 500, "occ": 320, "icu_tot": 60, "icu_occ": 35, "vent_tot": 45, "vent_avail": 18},
    ]
    rows = []
    for f in facilities:
        occ_pct = round((f["occ"] / f["total"]) * 100, 1)
        rows.append({
            "region": f["region"],
            "facility_name": f["name"],
            "total_beds": f["total"],
            "occupied_beds": f["occ"],
            "icu_beds_total": f["icu_tot"],
            "icu_beds_occupied": f["icu_occ"],
            "ventilators_total": f["vent_tot"],
            "ventilators_available": f["vent_avail"],
            "occupancy_rate_pct": occ_pct
        })
    return rows

def main():
    logging.info("Starting BigQuery environment setup...")
    client = get_bigquery_client()
    setup_bigquery_resources(client)
    
    logging.info("Generating mock patient symptom telemetry...")
    symptom_data = generate_dummy_data()
    
    logging.info(f"Uploading {len(symptom_data)} symptom records to BigQuery...")
    table_ref = client.dataset(DATASET_ID).table(TABLE_ID)
    chunk_size = 500
    for i in range(0, len(symptom_data), chunk_size):
        chunk = symptom_data[i:i+chunk_size]
        errors = client.insert_rows_json(table_ref, chunk)
        if errors:
            logging.error(f"Failed to insert symptom chunk starting at {i}: {errors}")
            return

    logging.info("Generating and uploading medical supplies data...")
    supplies_data = generate_medical_supplies_data()
    supplies_ref = client.dataset(DATASET_ID).table(SUPPLIES_TABLE_ID)
    errors = client.insert_rows_json(supplies_ref, supplies_data)
    if errors:
        logging.error(f"Failed to insert medical supplies: {errors}")
        return

    logging.info("Generating and uploading hospital capacity data...")
    hospital_data = generate_hospital_capacity_data()
    hospital_ref = client.dataset(DATASET_ID).table(HOSPITAL_TABLE_ID)
    errors = client.insert_rows_json(hospital_ref, hospital_data)
    if errors:
        logging.error(f"Failed to insert hospital capacity: {errors}")
        return

    logging.info("BigQuery environment setup and multi-table mock data generation complete!")

if __name__ == "__main__":
    main()
