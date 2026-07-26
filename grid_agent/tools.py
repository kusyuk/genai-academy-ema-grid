import os
import logging
import re
from typing import Optional
from google.cloud import bigquery
from google.adk.tools.tool_context import ToolContext

# --- CONFIGURATION ---
PROJECT_ID = os.getenv("PROJECT_ID")
DATASET_ID = os.getenv("BIGQUERY_DATASET", "ema_grid")
TABLE_ID = "symptom_reports"
SUPPLIES_TABLE_ID = "medical_supplies"
HOSPITAL_TABLE_ID = "hospital_capacity"

# --- INITIALIZATION ---
def get_bq_client():
    # Clears GOOGLE_APPLICATION_CREDENTIALS if the file does not exist,
    # allowing the SDK to fall back to Application Default Credentials.
    _creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if _creds_path and not os.path.exists(_creds_path):
        os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
    return bigquery.Client(project=PROJECT_ID)

# --- TOOLS ---

async def execute_grid_query(
    tool_context: ToolContext,
    sql_query: str,
) -> str:
    """Executes a SELECT SQL query against BigQuery tables (symptom_reports, medical_supplies, hospital_capacity).
    
    Args:
        sql_query: The SQL SELECT statement to run. Target symptom_reports, medical_supplies, or hospital_capacity.
    """
    logging.info(f"Grid Tool: Executing SQL query: {sql_query}")
    
    query_upper = sql_query.upper().strip()
    if not query_upper.startswith("SELECT"):
        return "Error: Only SELECT queries are permitted for safety reasons."
    
    forbidden_keywords = ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE", "MERGE"]
    for keyword in forbidden_keywords:
        if keyword in query_upper:
            return f"Error: Forbidden keyword '{keyword}' found in the query."
            
    # Table path mapping
    t_symptoms = f"`{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`"
    t_supplies = f"`{PROJECT_ID}.{DATASET_ID}.{SUPPLIES_TABLE_ID}`"
    t_hospitals = f"`{PROJECT_ID}.{DATASET_ID}.{HOSPITAL_TABLE_ID}`"
    
    sql_query = re.sub(r'[`"\'\w\d\-_\.]*symptom_reports[`"\'\w\d\-_\.]*', t_symptoms, sql_query, flags=re.IGNORECASE)
    sql_query = re.sub(r'[`"\'\w\d\-_\.]*medical_supplies[`"\'\w\d\-_\.]*', t_supplies, sql_query, flags=re.IGNORECASE)
    sql_query = re.sub(r'[`"\'\w\d\-_\.]*hospital_capacity[`"\'\w\d\-_\.]*', t_hospitals, sql_query, flags=re.IGNORECASE)
    
    # Sanitize invalid timestamp literals like 'now' or "now"
    sql_query = re.sub(r"['\"]now['\"]", "CURRENT_TIMESTAMP()", sql_query, flags=re.IGNORECASE)

    try:
        client = get_bq_client()
        query_job = client.query(sql_query)
        results = query_job.result()
        
        schema = [field.name for field in results.schema]
        rows = list(results)
        
        if not rows:
            return "Query executed successfully, but returned 0 results."
            
        markdown_lines = []
        markdown_lines.append("| " + " | ".join(schema) + " |")
        markdown_lines.append("| " + " | ".join(["---"] * len(schema)) + " |")
        
        for row in rows[:30]:
            row_values = []
            for field in schema:
                val = row.get(field)
                if isinstance(val, bytes):
                    row_values.append(val.decode())
                else:
                    row_values.append(str(val))
            markdown_lines.append("| " + " | ".join(row_values) + " |")
            
        if len(rows) > 30:
            markdown_lines.append(f"\n*Showing top 30 of {len(rows)} results.*")
            
        return "\n".join(markdown_lines)
        
    except Exception as e:
        logging.error(f"Error executing BigQuery query: {e}")
        return f"Failed to execute query. Error: {str(e)}"


async def get_grid_summary(
    tool_context: ToolContext,
) -> str:
    """Returns a high-level summary of active outbreak hotspots, critical supply shortages, and hospital bed pressure."""
    sql_hotspots = f"""
    SELECT region, symptom_cluster, COUNT(*) as cases_count
    FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    GROUP BY region, symptom_cluster
    ORDER BY cases_count DESC LIMIT 5
    """
    
    sql_supplies = f"""
    SELECT region, item_name, current_stock, days_of_supply, supply_status
    FROM `{PROJECT_ID}.{DATASET_ID}.{SUPPLIES_TABLE_ID}`
    WHERE supply_status IN ('CRITICAL_SHORTAGE', 'LOW')
    ORDER BY days_of_supply ASC LIMIT 5
    """

    try:
        client = get_bq_client()
        hotspots = list(client.query(sql_hotspots).result())
        supplies = list(client.query(sql_supplies).result())
        
        summary = "### 🚨 Recent Outbreak Hotspots (Last 7 Days):\n\n"
        summary += "| Region | Symptom | Case Count |\n| --- | --- | --- |\n"
        for r in hotspots:
            summary += f"| {r.region} | {r.symptom_cluster} | {r.cases_count} |\n"
            
        summary += "\n### 📦 Critical Supply Shortages:\n\n"
        summary += "| Region | Supply Item | Current Stock | Days Left | Status |\n| --- | --- | --- | --- | --- |\n"
        for s in supplies:
            summary += f"| {s.region} | {s.item_name} | {s.current_stock} | {s.days_of_supply}d | **{s.supply_status}** |\n"
            
        return summary
    except Exception as e:
        logging.error(f"Error getting grid summary: {e}")
        return f"Failed to retrieve summary: {str(e)}"


async def recommend_supply_transfer(
    tool_context: ToolContext,
    target_region: str,
    item_name: str,
) -> str:
    """Calculates and recommends an inter-region supply transfer from a surplus region to a region with critical shortages.
    
    Args:
        target_region: The region needing supply reinforcement (e.g. 'North District').
        item_name: The medical item (e.g. 'Oxygen Cylinders', 'Ventilators', 'N95 Mask Boxes', 'Antiviral Therapy Packs').
    """
    sql = f"""
    SELECT region, current_stock, daily_burn_rate, days_of_supply, supply_status
    FROM `{PROJECT_ID}.{DATASET_ID}.{SUPPLIES_TABLE_ID}`
    WHERE LOWER(item_name) LIKE LOWER('%{item_name}%')
    ORDER BY current_stock DESC
    """
    try:
        client = get_bq_client()
        rows = list(client.query(sql).result())
        if not rows:
            return f"No medical supply data found for '{item_name}'."
            
        target_row = next((r for r in rows if target_region.lower() in r.region.lower()), None)
        surplus_row = next((r for r in rows if r.supply_status == "SURPLUS" and r.region.lower() != target_region.lower()), None)
        if not surplus_row:
            surplus_row = sorted(rows, key=lambda x: x.current_stock, reverse=True)[0]
            
        if not target_row:
            return f"Region '{target_region}' not found in medical supplies database."
            
        recommended_transfer = min(int(surplus_row.current_stock * 0.4), max(50, target_row.daily_burn_rate * 5))
        
        plan = f"### 🚚 Recommended Inter-Region Logistics Plan:\n\n"
        plan += f"- **Target Deficit Region**: {target_row.region} (Current Stock: {target_row.current_stock} units, Status: `{target_row.supply_status}`)\n"
        plan += f"- **Recommended Donor Region**: {surplus_row.region} (Current Stock: {surplus_row.current_stock} units, Status: `{surplus_row.supply_status}`)\n"
        plan += f"- **Item**: {item_name}\n"
        plan += f"- **Transfer Quantity**: **{recommended_transfer} units**\n\n"
        plan += f"**Post-Transfer Projections:**\n"
        plan += f"- **{target_row.region}**: New Stock = `{target_row.current_stock + recommended_transfer}` units (Sufficient for ~{round((target_row.current_stock + recommended_transfer)/max(target_row.daily_burn_rate, 1), 1)} days)\n"
        plan += f"- **{surplus_row.region}**: Remaining Stock = `{surplus_row.current_stock - recommended_transfer}` units (Retains `{surplus_row.supply_status}` buffer)\n"
        return plan
    except Exception as e:
        logging.error(f"Error calculating supply transfer: {e}")
        return f"Failed to compute supply transfer recommendation: {str(e)}"

