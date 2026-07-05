import os
import sys
from dotenv import load_dotenv

# Add project root to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app

load_dotenv()

# Clear credentials path if needed to ensure ADC fallback
_creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if _creds_path and not os.path.exists(_creds_path):
    os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

def test_grid_agent_websocket():
    client = TestClient(app)
    print("Connecting to Grid Agent WebSocket...")
    with client.websocket_connect("/ws/grid/test-user/test-session") as websocket:
        # Start session
        websocket.send_json({"type": "text", "text": "__START_SESSION__"})
        print("Sent __START_SESSION__")
        
        greeting = ""
        while True:
            data = websocket.receive_json()
            if "content" in data and "parts" in data["content"]:
                for part in data["content"]["parts"]:
                    if "text" in part:
                        greeting += part["text"]
            if data.get("turnComplete"):
                break
        print(f"Agent Greeting: {greeting}\n")
        
        # Send query
        query = "analyze recent health trends in the North District"
        print(f"Sending query: '{query}'")
        websocket.send_json({"type": "text", "text": query})
        
        print("Response:")
        response_text = ""
        while True:
            data = websocket.receive_json()
            if "content" in data and "parts" in data["content"]:
                for part in data["content"]["parts"]:
                    if "text" in part:
                        text = part["text"]
                        print(text, end="", flush=True)
                        response_text += text
            if data.get("turnComplete"):
                print("\nTurn Complete!")
                break

        assert len(response_text) > 0, "Response should not be empty"
        print("\nTest passed successfully!")

if __name__ == "__main__":
    test_grid_agent_websocket()
