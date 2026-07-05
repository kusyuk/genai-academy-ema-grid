import os
import logging
from typing import Optional
from google.cloud import bigquery
from google.adk.tools.tool_context import ToolContext

# --- CONFIGURATION ---
PROJECT_ID = os.getenv("PROJECT_ID")
DATASET_ID = os.getenv("BIGQUERY_DATASET", "ema_grid")
TABLE_ID = "symptom_reports"

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
    """Executes a SELECT SQL query against the BigQuery symptom_reports table to retrieve regional health trends.
    
    Args:
        sql_query: The SQL SELECT statement to run. Must only contain SELECT statements and target the symptom_reports table.
    """
    logging.info(f"Grid Tool: Executing SQL query: {sql_query}")
    
    # Simple safety check to only allow SELECT queries and prevent SQL injections/modifications
    query_upper = sql_query.upper().strip()
    if not query_upper.startswith("SELECT"):
        return "Error: Only SELECT queries are permitted for safety reasons."
    
    forbidden_keywords = ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE", "MERGE"]
    for keyword in forbidden_keywords:
        if keyword in query_upper:
            return f"Error: Forbidden keyword '{keyword}' found in the query."
            
    # Resolve the table reference to ensure it queries the correct project/dataset
    full_table_path = f"`{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`"
    
    # If the LLM writes a generic query, we replace the table reference to point to our specific BQ table
    if "SYMPTOM_REPORTS" in query_upper:
        # Replace occurrences of symptom_reports, `symptom_reports`, or dataset.symptom_reports
        import re
        sql_query = re.sub(
            r'[`"\'\w\d\-_\.]*symptom_reports[`"\'\w\d\-_\.]*',
            full_table_path,
            sql_query,
            flags=re.IGNORECASE
        )

    try:
        client = get_bq_client()
        query_job = client.query(sql_query)
        results = query_job.result()
        
        # Format the results as markdown table
        schema = [field.name for field in results.schema]
        rows = list(results)
        
        if not rows:
            return "Query executed successfully, but returned 0 results."
            
        markdown_lines = []
        # Header
        markdown_lines.append("| " + " | ".join(schema) + " |")
        markdown_lines.append("| " + " | ".join(["---"] * len(schema)) + " |")
        
        # Rows (limit to top 30 to avoid blowing context windows)
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
    """Returns a high-level summary of active cases, outbreak hotspots, and staffing status from the BigQuery data."""
    sql = f"""
    SELECT 
        region, 
        symptom_cluster, 
        COUNT(*) as cases_count,
        MAX(timestamp) as last_reported
    FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    GROUP BY region, symptom_cluster
    ORDER BY cases_count DESC
    LIMIT 10
    """
    try:
        client = get_bq_client()
        query_job = client.query(sql)
        rows = list(query_job.result())
        
        if not rows:
            return "No symptom cases reported in the last 7 days."
            
        summary = "### Recent Outbreak Hotspots (Last 7 Days):\n\n"
        summary += "| Region | Symptom | Case Count | Last Reported |\n"
        summary += "| --- | --- | --- | --- |\n"
        for row in rows:
            summary += f"| {row.region} | {row.symptom_cluster} | {row.cases_count} | {row.last_reported} |\n"
            
        return summary
    except Exception as e:
        logging.error(f"Error getting grid summary: {e}")
        return f"Failed to retrieve summary: {str(e)}"
