import os
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1RjFiqdW_sAHsOGtgJnbTWxrFo7Hk1RbuJNrle9uMqfY"
CREDS_FILE = "tc-automation-499705-c2c985ebd608.json"

expected_headers = [
    "Timestamp", "CRS Number", "Company Name", "Client Code", "CRS Serial Number", "CRS Date", 
    "Dispatch Date", "Offer Number", "Offer Date", "Proforma Invoice", "Invoice Date", 
    "Blower Model", "Capacity", "Pressure", "Motor Power (KW)", "Motor Power (HP)", 
    "Blower Speed (RPM)", "Motor Speed (RPM)", "Max Speed (RPM)", "Power Consumption (BHP)", 
    "Flow Direction"
]

def main():
    print(f"Initializing connection to sheet ID: {SPREADSHEET_ID}")
    print(f"Using credentials file: {CREDS_FILE}")

    if not os.path.exists(CREDS_FILE):
        print(f"ERROR: Credentials file {CREDS_FILE} not found in current directory.")
        return

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    try:
        creds = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
        gc = gspread.authorize(creds)
        
        print("Connecting to spreadsheet...")
        sh = gc.open_by_key(SPREADSHEET_ID)
        
        # Select or create the 'CRS Extracted Data' worksheet
        sheet_name = "CRS Extracted Data"
        try:
            worksheet = sh.worksheet(sheet_name)
            print(f"Found existing worksheet: '{sheet_name}'")
        except gspread.WorksheetNotFound:
            print(f"Worksheet '{sheet_name}' not found. Creating it...")
            worksheet = sh.add_worksheet(title=sheet_name, rows="1000", cols="21")
            print(f"Created worksheet: '{sheet_name}'")

        # Write or update headers
        print("Writing headers...")
        worksheet.update(range_name="A1:U1", values=[expected_headers])
        worksheet.format("A1:U1", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.95, "green": 0.95, "blue": 0.95}
        })
        print("Headers written and formatted successfully!")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
