import os
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1RjFiqdW_sAHsOGtgJnbTWxrFo7Hk1RbuJNrle9uMqfY"
CREDS_FILE = "tc-automation-499705-c2c985ebd608.json"

def main():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet("FMS")
    
    # Get rows 6, 7, 8, 9, 10
    rows = ws.get_values("A6:G12")
    for idx, row in enumerate(rows):
        print(f"Row {idx+6}: {row}")

if __name__ == "__main__":
    main()
