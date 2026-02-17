# 📘 Technical Documentation

## Overview
The **MBTA Watchdog** is an asynchronous, event-driven monitoring system designed to track train status on the MBTA Framingham/Worcester Line. It operates on a producer-consumer model where a central monitoring loop fetches data, persists it to a relational database, and triggers downstream events (alerts, reporting, dashboard updates).

## System Architecture

The application is structured around a central **asyncio event loop** located in `main.py`. This loop orchestrates the following components:

1.  **Data Ingestion (Monitor):** Polls the MBTA v3 API.
2.  **Persistence Layer (Database):** Stores raw telemetry in SQLite.
3.  **Analysis Engine (Reporter):** Evaluates performance against historical baselines.
4.  **Presentation Layer (Bot/ThingSpeak):** Interfaces with Discord and IoT dashboards.



---

## Component Details

### 1. The Monitor (`monitor.py`)
* **Role:** The "Producer".
* **Mechanism:** Uses `aiohttp` to perform non-blocking GET requests to the MBTA API.
* **Data Normalization:** Converts the complex JSON-API response (nested relationships) into a flat dictionary structure suitable for relational storage.
* **Direction Logic:** Maps API `direction_id` (0/1) to human-readable "OUT" (Outbound) or "IN" (Inbound).

### 2. The Database Manager (`database.py`)
* **Role:** The "Storage Engine".
* **Technology:** SQLite (chosen for zero-config, serverless reliability).
* **Optimization:**
    * **WAL Mode:** (Implicit via library defaults) allows concurrent reads while writing.
    * **Indexes:** `idx_log_time` and `idx_train_id` reduce query complexity from $O(N)$ to $O(log N)$.
* **Schema Evolution:** Includes migration logic (`ALTER TABLE`) to handle schema changes (e.g., adding the `direction` column) without data loss.

### 3. The Reporter (`reporter.py`)
* **Role:** The "Analyst".
* **Logic:**
    * **Contextual Analysis:** Unlike simple monitors that only see "now", the Reporter queries the DB for the last 7 days of data for specific Train IDs.
    * **Receipt Generation:** If a train is late, it aggregates previous failures into a text summary ("Receipt") to strengthen the complaint.
    * **Cloud Sync:** Pushes metrics to ThingSpeak using a REST API.

### 4. The Discord Bot (`bot.py`)
* **Role:** The "Interface".
* **Pattern:** Command Dispatcher.
* **Concurrency:** Runs on the same event loop as the Monitor using `asyncio.create_task`, ensuring the bot remains responsive even while data is being fetched or analyzed.
* **Automation:** Contains logic to spawn a subprocess (`subprocess.Popen`) to execute `auto_fill_smart.py` on the host machine.

---

## Data Flow

1.  **Tick (0s):** `main.py` wakes up.
2.  **Fetch:** `MBTAMonitor` requests data from MBTA.
3.  **Persist:** Data is written to `mbta_logs.db`.
4.  **Alert Check:**
    * System checks if any active train exceeds `MAJOR_DELAY_THRESHOLD` (20m) or status is `CANCELED`.
    * If true + not previously alerted: `WatchdogBot.send_alert()` is awaited.
5.  **Report:** `Reporter` generates a summary of the last 60 minutes.
6.  **Sleep:** Loop sleeps for `POLL_INTERVAL_SECONDS` (120s).

---

## External Dependencies

| Library | Purpose |
| :--- | :--- |
| **`aiohttp`** | Async HTTP requests (API polling & Webhooks). |
| **`discord.py`** | Interaction with Discord Gateway. |
| **`pandas`** | Data manipulation and SQL interfacing. |
| **`selenium`** | Browser automation for form submission. |
| **`python-dotenv`** | Environment variable management. |

---

## Deployment Considerations

* **Concurrency:** The application is single-threaded but asynchronous. Blocking operations (like `time.sleep` or heavy calculation) must be avoided in the main loop.
* **Database Locking:** SQLite allows one writer at a time. The synchronous nature of `sqlite3` in Python is mitigated by the low write frequency (once every 2 minutes).
* **Resilience:** Network failures in `monitor.py` are caught and logged, preventing the main loop from crashing.