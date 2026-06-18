import os
import gspread
from google.oauth2.service_account import Credentials

CREDS_FILE = "tc-automation-499705-c2c985ebd608.json"

candidate_ids = [
    "1JQVH8_rhO5XCWiVlk5G0GlkVAQ6ID-AwwSqDi4UPcxE", # starts with 1
    "lJQVH8_rhO5XCWiVlk5G0GlkVAQ6ID-AwwSqDi4UPcxE", # starts with lowercase L
    "IJQVH8_rhO5XCWiVlk5G0GlkVAQ6ID-AwwSqDi4UPcxE", # starts with uppercase I
]

def main():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    
    for spreadsheet_id in candidate_ids:
        print(f"Trying spreadsheet ID: {spreadsheet_id}")
        try:
            sh = gc.open_by_key(spreadsheet_id)
            print(f"🎉 SUCCESS! Found sheet: {sh.title}")
            return
        except Exception as e:
            print(f"Failed: {e}")

if __name__ == "__main__":
    main()
