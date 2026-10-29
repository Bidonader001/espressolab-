# EspressoLab Attendance

Rule-based attendance for EspressoLab. The application reads logs that ZKTeco terminals already stored, keeps those punches, calculates sessions from shift rules, and exports reports. There is no face recognition, no machine learning, and no language-model API. Payroll is not included.

## Run locally

Python 3.12 or newer and Node 20 or newer.

```text
py -m pip install -r backend/requirements.txt
cd backend
py -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```text
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173. On a fresh database the first administrator is `admin` with the password from `ADMIN_PASSWORD`, or `change-me-now` when no `.env` exists. A banner stays on every page until that password is changed in Settings.

Copy `.env.example` to `.env` in this directory. SQLite is the default database file at `data/espressolab.db`. Keep that file outside OneDrive and other synced folders, because sync clients lock it while the API writes. Set `DATABASE_URL` to move it, or use PostgreSQL with a `postgresql+psycopg://` URL.

## Devices and synchronization

Register a terminal on Devices with its IP or hostname, port (usually 4370), and protocol:

- `tcp` or `udp` uses pyzk. The API process must be able to route to that address.
- `push` is ZKTeco ADMS. Point the terminal at `/iclock/cdata`. An unknown serial number is rejected and nothing is imported.
- `agent` is for a branch network. Run `agent/branch_agent.py` on a computer that can reach the terminal. It pulls logs and posts them with the token from Settings.
- `simulator` is a labeled development adapter. A successful simulator test is not evidence that a physical terminal works.

What a sync does:

1. Reads the terminal's attendance log and user list. It never clears the log, deletes users, or changes device settings.
2. Saves only punches that are not stored yet. Identity is device, user id, timestamp, and punch type.
3. Creates an employee for every user id on the terminal, using the name stored on the machine. Terminals label unnamed users `NN-435`. That label is replaced the next time a real name arrives, and a name typed into the app is never overwritten.
4. Recalculates attendance only for people who received new punches. A sync with nothing new recalculates no one.
5. Records the run (fetched, inserted, skipped, errors) in Sync history. A failed run keeps everything imported before it and shows the real error.

The scheduler starts a sync once the device interval has passed since the last attempt. A terminal that keeps failing is retried every ten minutes at most.

User ids are matched by their text across terminals. Two different people who share the id `12` on two terminals become one employee. Give each branch its own id range, or map one of them to a different employee on the device page.

### How hours are calculated

Terminals do not reliably say whether a punch is an entry or an exit, so punches are paired in time order. Stored punches are never changed. Sessions are rebuilt from them.

1. A repeat tap within 2 minutes of the previous counted tap is ignored. Terminals often record one tap twice, seconds apart. The ignored record stays stored. Setting: "Ignore repeat taps within".
2. If someone taps again with the same in/out flag within 30 minutes of the last counted tap, the later tap is ignored (check-in at 09:05, check-in again at 09:07, check-out at 17:14 is one day from 09:05 to 17:14). The flag is only a hint for this. Some terminals label punches by time of day, so it never decides who is arriving. Setting: "Treat a second check-in or check-out as a re-tap within". Use 0 to turn it off.
3. A punch opens a session and the next punch closes it. If the next punch is more than 12 hours later, the session stays open (a missing check-out) and the next punch starts a new one, so one forgotten punch cannot flip every later pair. Setting: "Longest single session".
4. A session can cross midnight and belongs to the day of its check-in.
5. Working time is check-out minus check-in, measured in whole minutes (30 seconds and over round up) and shown as hours:minutes, so 09:46:28 to 17:29:53 is `7:43`, not `7.72`. A day is the sum of its sessions, and a person's total is the sum of the daily rows, so every total reconciles with the rows above it. A lunch break between two sessions is not counted. Excel files hold a real duration (formatted `[h]:mm`) that sums correctly. The API also carries `hours` as a decimal and `hours_minutes` as the exact minute count.
6. A day with an unclosed session is `Incomplete`. It shows no check-out and no hours, even when part of the day has a closed session, and it adds nothing to the person's total. Only complete days are counted. Incomplete means a check-in without a check-out. Every report lists these days in amber with "No check-out" in the check-out cell, and the employee summary has an "Incomplete days" column so they can be found and fixed.

Days off (Friday and Saturday with the default Sun-Thu week, or each person's own working days) are listed in light blue as `Weekend` rows in the daily and monthly reports. They are never counted as absences. If someone punched on a day off, the day is a normal row with its date highlighted.

Reports follow the branch of the terminal. Every session belongs to the branch of the device that recorded its check-in (set the branch on the device), falling back to the employee's own branch when the device has none. The Branch column shows that per day, the branch filter lists only people who punched there with only the sessions recorded there, and a person's summary row, absent days, working days and grace period use the branch where most of their days were worked. A day worked at another branch is never marked absent. Changing a device's branch applies to reports immediately.

Branch working hours (from and to) are no longer in the Branches form. The Branches form clears them when saved. Hours come from a shift, the branch's default shift, or the company hours.

On the Branches page, each branch has a working-days picker (unticked days are days off, none ticked means the company days), its own shifts inside the branch form (the + Add shift button adds a line for each set of working hours, the ✕ removes one, and everything is saved with the branch) and an optional default shift. The default shift applies to that branch's employees who have no shift of their own and decides when they count as late. Changing a shift or the default recalculates the people it applies to from the stored punches.

On the Reports page, Preview shows the rows a download would contain (same rows, columns, hours text and totals, 100 per page, highlighted by status), and Preview as PDF shows the real PDF page by page before you download it. On the Employees page, tick employees (or "Select all N that match") and use Make active / Make inactive. Inactive people are left out of reports unless "Inactive employees: Included" is chosen, and their history is never touched. `POST /api/v1/employees/bulk-status` does the same from a script.

A working day with no check-in and no check-out at all is listed as an `Absent` row in the daily and monthly reports, and the summary's absence count equals the number of those rows. Holidays and approved leave are not absent: add a holiday (Settings) and that date stops producing Absent rows.

Changing either setting recalculates all attendance from the stored punches. The same happens once at startup after an upgrade that changes these rules.

### Branches on separate networks

A cloud server cannot open a connection to a private address such as `192.168.1.50`. Choose one:

- Run `agent/branch_agent.py` on a PC inside each branch. It pulls locally and posts to the central API over HTTPS. This needs no inbound firewall rule.
- Join the server and the branches with a VPN, then use the terminals' private IPs with the `tcp` protocol.
- Use `push` when the terminals can reach the server on their own.

## Exports and BunkerAtt

Reports use the same attendance calculation as the dashboard. Compared with BunkerAtt `core/exports.py` on the October 2026 fixture in `backend/tests/test_bunkeratt_compare.py`:

- CSV header and every cell matched.
- Excel sheet `Attendance Details` matched the header row and the first seven columns of every data row: Employee ID, Name, Date, Check-in, Check-out, Hours, Status.
- Employee Summary matched through Total hours.

Two layout choices differ from BunkerAtt on purpose. Rows are ordered by name, then date, where BunkerAtt orders by date. Dates carry the day name, as in `28/10/2026 Wed`, where BunkerAtt writes `28/10/2026`. The comparison test applies those two changes to BunkerAtt's output before it compares cells.

These files do not include BunkerAtt's Base salary, Net pay, or Face enrollment columns. The workbook title and download name use `EspressoLab Attendance` / `EspressoLabAttendance_…` rather than `Bunker Attendance`. PDF text and workbook bytes were not compared.

`source=device` limits an export to people who came from a terminal. The device page's export button uses the latest month stored for that terminal.

## Production deployment

Set `ENVIRONMENT=production`. The API then refuses to start until all of these are true:

- `SECRET_KEY` is random and at least 32 characters.
- `FERNET_KEY` is set, so stored device keys survive a `SECRET_KEY` change.
- `ADMIN_PASSWORD` is not a published default.
- `ALLOW_SIMULATOR=0`.
- `CORS_ORIGINS` lists the real site address.

With Docker:

```text
copy .env.example .env      (then fill in every REQUIRED value)
docker compose up --build -d
```

The compose file starts PostgreSQL (not published on the host) and the API on port 8000, with health checks on both. Put a reverse proxy with HTTPS in front of port 8000. The image and compose file have not been built or run on this machine, and PostgreSQL has not been exercised against the full test suite. Run the checklist below on the target server before the first real sync.

Monitoring: `GET /api/v1/health` reports the process is up. `GET /api/v1/health/ready` also checks the database and returns 503 when it cannot answer.

Backups: Settings has a backup action. With SQLite it copies the database file, which includes password hashes, so store it like a secret. With PostgreSQL use `pg_dump` on a schedule.

### First-day checklist

1. Sign in, change the administrator password, and create named accounts. Roles are admin, supervisor (operations), and viewer (read and export).
2. Add one terminal, press Test connection, then Sync now. Confirm the punch count and date range on its device page match the terminal's own report.
3. Check Branches: working days, grace minutes, each branch's shifts, holidays and approved leave (there is no separate Rules and shifts page; the old address redirects here). Changing a rule recalculates sessions and keeps every stored punch.
4. Download one monthly export and compare a few employees with the terminal.

## Security

Passwords are hashed with bcrypt, sessions use signed tokens that expire after `TOKEN_HOURS`, repeated failed sign-ins lock the account for a while, and every route checks the role on the server. Device communication keys are encrypted at rest and never returned by the API. Responses carry `nosniff`, frame denial, and a content security policy, and API responses are not cached. Account, device, rule, and export actions are written to the audit log.

## Tests

```text
cd backend
py -m pytest -q
```

## Layout

- `backend/app` FastAPI service, calculation rules, exports, ZK adapters.
- `frontend` React and TypeScript web app, built into `frontend/dist` and served by the API.
- `agent` branch agent for terminals the server cannot reach.
