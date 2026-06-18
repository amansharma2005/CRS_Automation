import os
import sys
import gspread
import traceback
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1JQVH8_rhO5XCWivIk5G0GIkVAQ6ID-AwwSqDi4UPceE"
CREDS_FILE = "tc-automation-499705-c2c985ebd608.json"

expected_headers = [
    "Timestamp", "Company Name", "Client Code", "CRS Serial Number", "CRS Date", 
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
        
        # Get the first sheet
        worksheet = sh.get_worksheet(0)
        print(f"Connected to sheet: '{sh.title}' -> worksheet: '{worksheet.title}'")

        # Clear existing content (or check first)
        try:
            existing_headers = worksheet.row_values(1)
        except Exception:
            existing_headers = []

        if not existing_headers:
            print("Sheet is empty. Writing headers...")
            worksheet.append_row(expected_headers)
            worksheet.format("A1:T1", {
                "textFormat": {"bold": True},
                "backgroundColor": {"red": 0.95, "green": 0.95, "blue": 0.95}
            })
            print("Headers written successfully!")
        else:
            print(f"Headers already exist: {existing_headers}")
            print("Updating headers to match exact schema...")
            worksheet.update(range_name="A1:T1", values=[expected_headers])
            worksheet.format("A1:T1", {
                "textFormat": {"bold": True},
                "backgroundColor": {"red": 0.95, "green": 0.95, "blue": 0.95}
            })
            print("Headers updated successfully!")

    except Exception as e:
        print("\n[!] Error during execution:")
        traceback.print_exc()

if __name__ == "__main__":
    main()
