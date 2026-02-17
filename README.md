# 🚆 MBTA Watchdog (Enterprise Edition)

A production-grade, asynchronous Python application that monitors the **MBTA Framingham/Worcester Commuter Rail Line** in real-time. It uses a local SQLite database for high-performance logging, detects service disruptions, generates data-backed complaint emails ("Receipts"), and automates the submission process via Selenium.

---

## 🌟 Key Features

### 1. Real-Time Monitoring & Storage
* **Live Tracking:** Fetches train data (Location, Status, Delay, Direction) every 2 minutes.
* **SQLite Backend:** Replaced CSV with a high-performance `mbta_logs.db` database, capable of storing years of history without slowing down.
* **Smart Indexing:** Instant lookups for specific trains or time windows.

### 2. The "Receipt Keeper" (Historical Context)
* **Pattern Detection:** The bot doesn't just say a train is late; it checks the last 7 days of history.
* **Contextual Emails:** Automatically injects lines like: *"Train 508 has failed 4 times in the last week (02/12, 02/14, 02/15)."*
* **Smart Drafting:** Generates a formal complaint email if delays > 5 mins, or a "Green/All Clear" report if service is nominal.

### 3. Advanced Discord Bot
* **Push Alerts:** Proactively messages a channel if a train is **Canceled** or **Delayed > 20 mins**.
* **Mobile Friendly:** `!copy` command provides one-tap text blocks for filing complaints on your phone.
* **Desktop Automation:** `!launch` command remotely opens a Chrome browser on the host machine and **auto-fills** the MBTA Customer Support form (including time/date dropdowns).

### 4. IoT & Dashboard
* **ThingSpeak Integration:** Pushes metrics (Late Count, Max Delay) to a cloud dashboard for visualization.

---

## 📂 Project Structure

```text
mbta_watchdog/
├── data/               # SQLite database & auto-generated drafts
├── logs/               # Application runtime logs
├── src/                # Modular Source Code
│   ├── api/            # MBTA API monitoring & data ingestion
│   ├── discord/        # Bot logic, commands, and alert systems
│   ├── database/       # SQLite schema & persistence logic
│   └── utils/          # Config, Logger, and Reporting helpers
├── main.py             # Application Orchestrator
├── requirements.txt    # Project dependencies
└── .env                # Private Secrets (Ignored by Git)
```

---

## 🚀 Installation

### 1. Clone & Setup

```bash
git clone [https://github.com/yourusername/mbta_watchdog.git](https://github.com/yourusername/mbta_watchdog.git)
cd mbta_watchdog

# Optional: Create virtual env
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

```

### 2. Install Dependencies

```bash
pip install -r requirements.txt

```

### 3. Configure Secrets

Create a `.env` file in the root directory:

```ini
# .env
DISCORD_TOKEN=your_bot_token_here
THINGSPEAK_API_KEY=your_write_key
MBTA_API_KEY=your_mbta_key (Optional)
DISCORD_ALERT_CHANNEL_ID=123456789012345678  # Channel ID for Red Alerts

```

### 4. (Optional) Migrate Old Data

If you have an old `mbta_worcester_log.csv` file, move it to the `data/` folder and run:

```bash
python migrate_csv_to_db.py

```

---

## ⚙️ Usage

### Start the Watchdog

```bash
python main.py

```

The system will initialize the database, start the monitoring loop, and log the bot into Discord.

### Discord Commands

| Command | Description |
| --- | --- |
| **`!list`** | Live board of active trains (ID, Direction, Status, Delay). |
| **`!status`** | Shows the current generated email draft (Complaint or All Clear). |
| **`!status <ID>`** | Detailed history for a specific train (e.g., `!status 508`). |
| **`!copy`** | **Mobile:** Sends the complaint text in a copy-paste friendly format + Link. |
| **`!launch`** | **Desktop:** Opens Chrome on the host machine and auto-fills the MBTA form. |
| **`!help`** | Shows the help menu. |

---

## 🛠️ Configuration (`config.py`)

You can tune the sensitivity of the watchdog:

* **`POLL_INTERVAL_SECONDS`**: Frequency of checks (Default: `120s`).
* **`DELAY_THRESHOLD`**: Minutes before a train is marked "Yellow/Late" (Default: `5m`).
* **`MAJOR_DELAY_THRESHOLD`**: Minutes before a "Red Alert" is sent to Discord (Default: `20m`).

---

## 📝 License

MIT License.