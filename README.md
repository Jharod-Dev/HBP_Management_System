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
