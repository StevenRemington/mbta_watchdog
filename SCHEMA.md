# 🗄️ Database Schema Documentation

## Overview
The application uses **SQLite** for data storage. The database file is located at `data/mbta_logs.db`.



[Image of relational database schema diagram]


## Tables

### `train_logs`
This is the primary time-series table containing all train movements.

| Column | Type | Description |
| :--- | :--- | :--- |
| **`id`** | `INTEGER (PK)` | Auto-incrementing unique identifier. |
| **`log_time`** | `TIMESTAMP` | The exact UTC time the data was recorded. |
| **`train_id`** | `TEXT` | The MBTA Train Number (e.g., "508", "512"). |
| **`direction`** | `TEXT` | "IN" (Inbound) or "OUT" (Outbound). Derived from API `direction_id`. |
| **`status`** | `TEXT` | Current status (e.g., "Moving To", "At Stop", "LATE", "CANCELED"). |
| **`delay_minutes`** | `INTEGER` | The delay in minutes relative to the schedule. |
| **`station`** | `TEXT` | The name of the station the train is currently at or approaching. |

## Indexes
Indexes are critical for the performance of the "Receipt Keeper" and History functions.

* **`idx_log_time`**:
    * **Target:** `log_time`
    * **Purpose:** speeds up queries for "Recent History" (e.g., `SELECT * WHERE log_time > NOW() - 60m`).
* **`idx_train_id`**:
    * **Target:** `train_id`
    * **Purpose:** Speeds up "Receipt" generation (e.g., `SELECT * WHERE train_id = '508'`).

## Query Patterns

### 1. Recent Activity (Dashboard/Discord List)
Used to generate the live board of trains.
```sql
SELECT * FROM train_logs 
WHERE log_time >= datetime('now', '-30 minutes');
```


### 2. The "Receipt"

Used to find how many times a specific train failed in the last week.

```sql
SELECT date(log_time) as log_date, MAX(delay_minutes) as max_delay, status
FROM train_logs
WHERE train_id = ? AND log_time >= datetime('now', '-7 days')
GROUP BY log_date;
```

### 3. Pruning

```sql
DELETE FROM train_logs 
WHERE log_time < datetime('now', '-90 days');
```
