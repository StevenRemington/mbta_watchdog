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
├── .env                  # API Keys (Do NOT commit this)
├── requirements.txt      # Dependencies
├── main.py               # Orchestrator (Runs Monitor + Bot)
├── database.py           # SQLite Database Manager
├── monitor.py            # MBTA API Data Fetcher
├── bot.py                # Discord Bot & Command Dispatcher
├── reporter.py           # Email Logic & History Analysis
├── auto_fill_smart.py    # Selenium Browser Automation Script
├── config.py             # Configuration Loader
├── logger.py             # Logging Utility
└── data/                 # Folder for Database & Logs
    └── mbta_logs.db      # The SQLite Database (Auto-created)