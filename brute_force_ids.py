import os
import gspread
from google.oauth2.service_account import Credentials

CREDS_FILE = "tc-automation-499705-c2c985ebd608.json"

# Base pattern: 1JQVH8_[r/R][h/H][o/O]5XCW[i/I/1/l]V[l/L/1/I]k5G0G[l/L/1/I]kVAQ6[i/I/1/l]D-AwwSqDi4UPcxE
# Let's generate candidates:
o_variants = ["O", "o"]
i_variants = ["i", "I", "1", "l"]
l_variants = ["l", "L", "1", "I"]

candidates = []
for o in o_variants:
    for i1 in i_variants:
        for l1 in l_variants:
            for l2 in l_variants:
                for i2 in i_variants:
                    sid = f"1JQVH8_rh{o}5XCW{i1}V{l1}k5G0G{l2}kVAQ6{i2}D-AwwSqDi4UPcxE"
                    candidates.append(sid)

def main():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    
    print(f"Testing {len(candidates)} spreadsheet ID candidates...")
    for i, spreadsheet_id in enumerate(candidates):
        try:
            sh = gc.open_by_key(spreadsheet_id)
            print(f"🎉 FOUND SUCCESS AT INDEX {i}!")
            print(f"Spreadsheet ID: {spreadsheet_id}")
            print(f"Title: {sh.title}")
            return
        except Exception:
            pass
    print("All combinations failed. The spreadsheet might not be shared with this service account yet, or the Sheets API is not enabled.")

if __name__ == "__main__":
    main()
