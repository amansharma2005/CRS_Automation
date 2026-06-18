import os
import gspread
from google.oauth2.service_account import Credentials

CREDS_FILE = "tc-automation-499705-c2c985ebd608.json"

def main():
    if not os.path.exists(CREDS_FILE):
        print("Creds not found")
        return
        
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    
    print("Listing accessible spreadsheets...")
    try:
        files = gc.list_spreadsheet_files()
        print(f"Found {len(files)} files:")
        for f in files:
            print(f"  - Title: {f.get('name')}, ID: {f.get('id')}")
    except Exception as e:
        print(f"Error listing files: {e}")

if __name__ == "__main__":
    main()
