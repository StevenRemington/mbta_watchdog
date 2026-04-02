import sys
import uvicorn
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

# 1. Resolve path to root from 'services/' subdirectory
# Path(__file__).resolve().parent.parent gets you to the root 'mbta-watchdog/' folder
ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_PATH = str(ROOT_DIR / "src")

if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

# 2. Now import your shared database singleton
from database.database import DatabaseManager

app = FastAPI()
db = DatabaseManager()

@app.get("/", response_class=HTMLResponse)
async def home():
    # Fetch the last 60 minutes of train activity from your DB
    df = db.get_recent_logs(minutes=60)
    
    # Sort to show newest first
    if not df.empty:
        df = df.sort_values('LogTime', ascending=False)

    # Build a simple HTML table
    rows = ""
    for _, row in df.iterrows():
        status_color = "red" if row['Status'] in ["LATE", "CANCELED"] else "green"
        rows += f"""
        <tr>
            <td>{row['Train']}</td>
            <td>{row['Direction']}</td>
            <td style="color: {status_color}; font-weight: bold;">{row['Status']}</td>
            <td>{row['DelayMinutes']} min</td>
            <td>{row['Station']}</td>
        </tr>
        """

    return f"""
    <html>
        <head>
            <title>Software Spren - MBTA Live</title>
            <style>
                body {{ font-family: sans-serif; padding: 20px; background: #f4f4f9; }}
                table {{ width: 100%; border-collapse: collapse; background: white; }}
                th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                th {{ background-color: #2c3e50; color: white; }}
                tr:nth-child(even) {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            <h1>Worcester Line Live Watchdog</h1>
            <p>Real-time tracking via Raspberry Pi in Natick.</p>
            <table>
                <tr><th>Train</th><th>Dir</th><th>Status</th><th>Delay</th><th>Last Location</th></tr>
                {rows if rows else "<tr><td colspan='5'>No active trains detected.</td></tr>"}
            </table>
        </body>
    </html>
    """

if __name__ == "__main__":
    # Start the server on port 8000 for the Pangolin tunnel
    uvicorn.run(app, host="0.0.0.0", port=8000)