import uvicorn
import os
import sys
from dotenv import load_dotenv

# Ensure project root is in python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load .env before reading any config so HOST/PORT/RELOAD can be overridden
# without touching this file.
load_dotenv()

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
RELOAD = os.getenv("RELOAD", "true").lower() in ("1", "true", "yes")

if __name__ == "__main__":
    print("Starting QuantumPredict FastAPI Server...")
    print(f"Dashboard will be available at: http://localhost:{PORT}")

    # Run the server
    uvicorn.run("backend.main:app", host=HOST, port=PORT, reload=RELOAD)
