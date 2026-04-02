# MBTA Watchdog: System Administration Guide

This guide covers the management and monitoring of the **MBTA Watchdog** services on your Raspberry Pi. Following the transition to a **Hybrid Architecture**, the system is split into three independent `systemd` units to ensure maximum uptime and fault isolation.

---

## 🏗️ Service Architecture

The system is comprised of three distinct services that communicate via a shared SQLite database:

1.  **`mbta-monitor.service` (The Producer)**: Polls the MBTA API every 120 seconds and commits live telemetry to `data/mbta_logs.db`.
2.  **`mbta-bots.service` (The Consumer)**: Watches the database for new logs to trigger Discord alerts and social media posts.
3.  **`mbta-dashboard.service` (The Web UI)**: Serves the live Worcester Line board at `softwarespren.com` on port 8000.

---

## ⚙️ General Administration

### Service Management
Use these commands to manage the lifecycle of the watchdog services:

| Action | Command |
| :--- | :--- |
| **Start All** | `sudo systemctl start mbta-monitor mbta-bots mbta-dashboard` |
| **Stop All** | `sudo systemctl stop mbta-monitor mbta-bots mbta-dashboard` |
| **Restart All** | `sudo systemctl restart mbta-monitor mbta-bots mbta-dashboard` |
| **Enable on Boot** | `sudo systemctl enable mbta-monitor mbta-bots mbta-dashboard` |
| **Reload Config** | `sudo systemctl daemon-reload` (Run this after editing `.service` files) |

---

## 🔍 Monitoring & Health Checks

### 1. Checking Service Status
To see if a service is currently active and healthy, run:
```bash
sudo systemctl status mbta-monitor
```
* **Active (running)**: The service is healthy.
* **Inactive (dead)**: The service is stopped.
* **Failed**: The service crashed; check the logs for the traceback.

### 2. Viewing Live Logs
`journalctl` is the primary tool for debugging. Use the `-f` flag to follow logs in real-time:

* **Monitor Logs**: `sudo journalctl -u mbta-monitor -f` (Check here for MBTA API connectivity issues).
* **Bot Logs**: `sudo journalctl -u mbta-bots -f` (Check here for Discord/Bluesky/Twitter API errors).
* **Dashboard Logs**: `sudo journalctl -u mbta-dashboard -f` (Check here for web traffic and tunnel requests).

### 3. Database Health
Since all services rely on the `mbta_logs.db`, ensure the file is receiving updates:
```bash
ls -lh data/mbta_logs.db
```
*If the timestamp on the file isn't updating every 2 minutes, the `mbta-monitor` service may be stalled.*

---

## 🛠️ Troubleshooting

### Virtual Environment (venv) Issues
All services must run using the Python interpreter located within your virtual environment to access dependencies like `pandas` and `discord.py`.
* **Correct Path**: `/home/softwarespren/mbta_watchdog/venv/bin/python3`.
* **Error**: `ModuleNotFoundError` usually means the `ExecStart` path in your `.service` file is pointing to the system Python instead of the `venv`.

### Permissions
* **Database Access**: Ensure the user `softwarespren` has read/write permissions for the `data/` directory.
* **Port 8000**: If the dashboard fails to start, verify no other process (like an old Python test script) is "squatting" on port 8000.

### Environment Variables
If bots fail to log in, verify that your `.env` file contains all necessary tokens and that it is located in the project root. The `Config` class loads these values automatically on startup.