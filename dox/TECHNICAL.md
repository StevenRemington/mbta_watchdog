# 📘 Technical Documentation

## Overview

The **MBTA Watchdog** is an asynchronous, modular monitoring system designed to track train status on the MBTA Framingham/Worcester Line. It follows a **Modular Monolith** architecture with a producer-consumer model. A central monitoring loop fetches telemetry, persists it to a relational SQLite database, and triggers downstream events including real-time Discord alerts, historical "Receipt" analysis, and automated form submission.

---

## System Architecture

The application is orchestrated by a central **asyncio event loop** in `main.py`. By injecting `src/` into the system path, the project uses **Absolute Imports**, ensuring a clean separation of concerns across the following sub-packages:

1. **Data Ingestion (`src/api/`):** Manages external communication with the MBTA v3 API.
2. **Persistence Layer (`src/database/`):** Encapsulates SQLite schema and query logic.
3. **Analysis Engine (`src/utils/reporter.py`):** Performs historical performance audits.
4. **Interface Layer (`src/interfaces/`):** Handles Discord gateway interactions and proactive alerts.

---

## Component Details

### 1. The Monitor (`src/api/monitor.py`)

* **Mechanism:** Utilizes `aiohttp` for non-blocking GET requests.
* **Data Normalization:** Flattens complex JSON-API relationships into records containing `train_id`, `status`, `delay_minutes`, and `station`.
* **Direction Mapping:** Translates binary `direction_id` values (0/1) into human-readable `OUT` (Outbound) or `IN` (Inbound).

### 2. The Database Manager (`src/database/database.py`)

* **Storage Engine:** SQLite 3.
* **Professional Pathing:** Uses `pathlib` within `Config` to ensure the database is always stored in the `root/data/` directory regardless of the execution context.
* **Optimization:** * **B-Tree Indexes:** `idx_log_time` and `idx_train_id` ensure that historical "Receipt" lookups remain  even as the database grows to thousands of rows.
* **Auto-Migration:** Includes `ALTER TABLE` logic to handle schema updates (e.g., adding `direction`) without manual intervention.

### 3. The Reporter (`src/utils/reporter.py`)

* **The "Receipt Keeper":** Unlike standard monitors, this component performs a **look-back analysis**. It queries the database for the last 7 days of performance for a specific `train_id`.
* **Logic:** Aggregates unique daily failures. If a train is currently late, it appends a 🧾 **HISTORY** block to the report, citing specific dates of past failures to provide a stronger basis for customer service complaints.

### 4. The Discord Bot (`src/discord/bot.py`)

* **Interface:** A `discord.Client` implementation using a **Command Dispatcher** pattern.
* **Proactive Alerts:** Monitors the telemetry stream for `CANCELED` status or delays exceeding `MAJOR_DELAY_THRESHOLD` (20m), pushing automated embeds to a designated alert channel.

---

## Data Flow & Pathing

The project utilizes a **src-layout** where `main.py` serves as the entry point at the root.

1. **Tick:** The main loop triggers `MBTAMonitor.fetch_data()`.
2. **Ingest:** Data is passed to `DatabaseManager.insert_data()`.
3. **Analyze:** The `Reporter` evaluates the current state against historical database records.
4. **Draft:** A dynamic email draft is written to `data/current_email_draft.txt`.
5. **Alert:** If a major incident is detected, the `WatchdogBot` pushes a notification to Discord.
6. **IoT Sync:** Telemetry metrics are pushed to ThingSpeak for remote dashboard visualization.

---

## Deployment & Path Management

| Feature | Implementation |
| --- | --- |
| **Imports** | Absolute Imports (e.g., `from database.database import DatabaseManager`). |
| **Pathing** | OS-agnostic `pathlib` integration via `src/utils/config.py`. |
| **Concurrency** | Single-threaded `asyncio`. No blocking `time.sleep()` calls allowed. |
| **Logging** | Streams to both console and `logs/app.log`. |

---

## External Dependencies

| Library | Purpose |
| --- | --- |
| **`aiohttp`** | High-performance async HTTP requests. |
| **`pandas`** | SQL-to-DataFrame bridging and data manipulation. |
| **`discord.py`** | WebSocket connection to Discord's Real-time Gateway. |
| **`python-dotenv`** | Decouples sensitive API keys from the source code. |