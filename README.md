# Howard's Billiards Place

## Setup

1. Start the standalone MySQL 8 server.
2. Create the `hbp_management_system` database using your MySQL client.
3. Activate the existing virtual environment and install dependencies:

   ```powershell
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

4. Configure `.env` with the database credentials.

## Initialize the database

From the project root, run:

```powershell
python scripts/init_db.py
```

Confirm with `yes` when prompted. This runs `sql/schema.sql` and `sql/seed.sql`;
the schema script drops existing tables.

## Run the application

```powershell
flask --app run run
```

Open `http://127.0.0.1:5000/`. The unknown route
`http://127.0.0.1:5000/doesnotexist` displays the friendly 404 page.

## Create an administrator

```powershell
python scripts/create_admin.py
```

Enter the administrator's name, email, and password when prompted.

## Reservations

Authenticated customers can submit same-day requests for reservable VIP
billiards tables and karaoke booths at `/customer/reservations`. Administrators
review requests at `/admin/reservations`. Requests remain `PENDING` until
approved, and overlapping pending or confirmed reservations are blocked.

Approval and rejection emails are sent only when the `MAIL_*` settings,
including `MAIL_DEFAULT_SENDER`, are configured in `.env`. Email delivery is
performed after the database decision has committed; an email failure does not
undo the decision.

Administrators manage live sessions at `/admin/sessions`. Sessions can be
started for confirmed reservations or walk-ins, extended in 30-minute
increments, and completed manually. A completed unit remains `PREPARING` for
30 seconds based on the server-side `ended_at` timestamp before it becomes
available again.
