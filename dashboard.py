from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from src.database.database import DatabaseManager
import uvicorn

app = FastAPI()
db = DatabaseManager()

@app.get("/", response_class=HTMLResponse)
async def home():
    # Pull live data from the shared SQLite DB
    df = db.get_recent_logs(minutes=60)
    # Generate your HTML table here...
    return "<h1>Live MBTA Board</h1>" # (Simplified)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)