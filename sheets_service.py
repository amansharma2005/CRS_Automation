"""
Google Sheets Integration Service
=================================
Handles writing extracted document details to Google Sheets via:
1. Google Apps Script Web App URL (no oauth credentials required on server)
2. Google Sheets API Service Account (using gspread if credentials.json is provided)
"""

import os
import logging
import httpx
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Lazy imports for gspread to avoid startup crash if libraries are missing
gspread_available = False
try:
    import gspread
    from google.oauth2.service_account import Credentials
    gspread_available = True
except ImportError:
    pass

class GoogleSheetsService:
    """Service to export data to Google Sheets."""

    @classmethod
    async def export_to_sheets(
        cls, 
        data: Dict[str, Any], 
        webapp_url: Optional[str] = None, 
        spreadsheet_id: Optional[str] = None,
        sheet_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Main entry point for sheet export.
        Tries Service Account if configured, otherwise falls back to Web App URL.
        """
        # 1. Try Service Account if spreadsheet_id and credentials exist
        creds_path = os.getenv("GOOGLE_SHEETS_CREDS_PATH", "google_sheets_credentials.json")
        if not spreadsheet_id:
            spreadsheet_id = os.getenv("GOOGLE_SPREADSHEET_ID")
            
        # Auto-detect service account credentials in current directory
        if not os.path.exists(creds_path) and not os.getenv("GOOGLE_SHEETS_CREDS_JSON"):
            for file in os.listdir("."):
                if file.endswith(".json") and file != "package.json":
                    try:
                        import json
                        with open(file, "r") as f:
                            info = json.load(f)
                            if info.get("type") == "service_account" and "project_id" in info:
                                creds_path = file
                                logger.info(f"Auto-detected service account credentials file: {creds_path}")
                                break
                    except Exception:
                        pass

        if gspread_available and spreadsheet_id and (os.path.exists(creds_path) or os.getenv("GOOGLE_SHEETS_CREDS_JSON")):
            try:
                logger.info(f"Using Google Service Account ({creds_path}) for export...")
                return await cls._export_via_service_account(data, spreadsheet_id, sheet_name, creds_path)
            except Exception as e:
                logger.error(f"Service account export failed: {e}. Falling back to Web App URL...")

        # 2. Try Web App URL
        if not webapp_url:
            webapp_url = os.getenv("GOOGLE_SHEETS_WEBAPP_URL")

        if webapp_url:
            logger.info("Using Web App URL for export...")
            return await cls._export_via_webapp(data, webapp_url)
            
        raise ValueError(
            "Google Sheets is not configured. Provide GOOGLE_SHEETS_WEBAPP_URL in .env, "
            "or set GOOGLE_SPREADSHEET_ID and place google_sheets_credentials.json in the project root."
        )

    @classmethod
    async def _export_via_webapp(cls, data: Dict[str, Any], webapp_url: str) -> Dict[str, Any]:
        """Send data to Google Apps Script web app endpoint."""
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.post(webapp_url, json=data)
            resp.raise_for_status()
            
            # Apps script web apps can return HTML or redirect. If it returns JSON, parse it.
            try:
                result = resp.json()
                if result.get("status") == "error":
                    raise Exception(result.get("message", "Unknown Apps Script error"))
                return {"status": "success", "method": "webapp", "details": result}
            except ValueError:
                # If it didn't return JSON but completed with 200, assume success
                if resp.status_code == 200:
                    return {"status": "success", "method": "webapp", "details": "Row added (raw response)"}
                raise Exception(f"Failed to parse webapp response: {resp.text[:200]}")

    @classmethod
    async def _export_via_service_account(
        cls, 
        data: Dict[str, Any], 
        spreadsheet_id: str, 
        sheet_name: Optional[str] = None,
        creds_path: str = "google_sheets_credentials.json"
    ) -> Dict[str, Any]:
        """Export using gspread and service account (non-blocking)."""
        import asyncio
        return await asyncio.to_thread(
            cls._sync_export_via_service_account,
            data,
            spreadsheet_id,
            sheet_name,
            creds_path
        )

    @classmethod
    def _sync_export_via_service_account(
        cls, 
        data: Dict[str, Any], 
        spreadsheet_id: str, 
        sheet_name: Optional[str] = None,
        creds_path: str = "google_sheets_credentials.json"
    ) -> Dict[str, Any]:
        """Export using gspread and service account (blocking implementation)."""
        if not gspread_available:
            raise ImportError("gspread and google-auth are required for service account export")

        # Load credentials
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        creds_json = os.getenv("GOOGLE_SHEETS_CREDS_JSON")
        if creds_json:
            import json
            creds_data = json.loads(creds_json)
            creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
        else:
            creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
            
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(spreadsheet_id)
        
        # Select worksheet
        if sheet_name:
            try:
                worksheet = sh.worksheet(sheet_name)
            except gspread.WorksheetNotFound:
                num_cols = "21" if sheet_name == "CRS Extracted Data" else "20"
                worksheet = sh.add_worksheet(title=sheet_name, rows="1000", cols=num_cols)
        else:
            worksheet = sh.get_worksheet(0)

        # Check if headers exist
        headers = worksheet.row_values(1)
        if sheet_name == "CRS Extracted Data":
            expected_headers = [
                "Timestamp", "CRS Number", "Company Name", "Client Code", "CRS Serial Number", "CRS Date", 
                "Dispatch Date", "Offer Number", "Offer Date", "Proforma Invoice", "Invoice Date", 
                "Blower Model", "Capacity", "Pressure", "Motor Power (KW)", "Motor Power (HP)", 
                "Blower Speed (RPM)", "Motor Speed (RPM)", "Max Speed (RPM)", "Power Consumption (BHP)", 
                "Flow Direction"
            ]
            format_range = "A1:U1"
        else:
            expected_headers = [
                "Timestamp", "Company Name", "Client Code", "CRS Serial Number", "CRS Date", 
                "Dispatch Date", "Offer Number", "Offer Date", "Proforma Invoice", "Invoice Date", 
                "Blower Model", "Capacity", "Pressure", "Motor Power (KW)", "Motor Power (HP)", 
                "Blower Speed (RPM)", "Motor Speed (RPM)", "Max Speed (RPM)", "Power Consumption (BHP)", 
                "Flow Direction"
            ]
            format_range = "A1:T1"
        
        if not headers or len(headers) == 0:
            worksheet.append_row(expected_headers)
            worksheet.format(format_range, {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.95, "green": 0.95, "blue": 0.95}})

        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Map values
        if sheet_name == "CRS Extracted Data":
            row_value = [
                timestamp,
                data.get("crs_number") or "",
                data.get("company_name") or "",
                data.get("client_code") or "",
                data.get("crs_serial_number") or "",
                data.get("crs_date") or "",
                data.get("dispatch_date") or "",
                data.get("offer_number") or "",
                data.get("offer_date") or "",
                data.get("proforma_invoice") or "",
                data.get("invoice_date") or "",
                data.get("blower_model") or "",
                data.get("capacity") or "",
                data.get("pressure") or "",
                data.get("motor_power_kw") or "",
                data.get("motor_power_hp") or "",
                data.get("speed_rpm") or "",
                data.get("motor_rating_speed_rpm") or data.get("motor_speed_rpm") or "",
                data.get("max_speed_rpm") or "",
                data.get("power_consumption_bhp") or "",
                data.get("flow_direction") or ""
            ]
        else:
            row_value = [
                timestamp,
                data.get("company_name") or "",
                data.get("client_code") or "",
                data.get("crs_serial_number") or "",
                data.get("crs_date") or "",
                data.get("dispatch_date") or "",
                data.get("offer_number") or "",
                data.get("offer_date") or "",
                data.get("proforma_invoice") or "",
                data.get("invoice_date") or "",
                data.get("blower_model") or "",
                data.get("capacity") or "",
                data.get("pressure") or "",
                data.get("motor_power_kw") or "",
                data.get("motor_power_hp") or "",
                data.get("speed_rpm") or "",
                data.get("motor_rating_speed_rpm") or data.get("motor_speed_rpm") or "",
                data.get("max_speed_rpm") or "",
                data.get("power_consumption_bhp") or "",
                data.get("flow_direction") or ""
            ]
        
        worksheet.append_row(row_value)
        return {"status": "success", "method": "service_account"}

    @classmethod
    async def get_drive_link_by_crs(
        cls,
        crs_number: str,
        spreadsheet_id: Optional[str] = None
    ) -> str:
        """
        Search the 'FMS' sheet for the given crs_number in Column B.
        Returns the drive link from Column F of that row.
        """
        import asyncio
        return await asyncio.to_thread(
            cls._sync_get_drive_link_by_crs,
            crs_number,
            spreadsheet_id
        )

    @classmethod
    def _sync_get_drive_link_by_crs(
        cls,
        crs_number: str,
        spreadsheet_id: Optional[str] = None
    ) -> str:
        """
        Synchronous search implementation for the 'FMS' sheet.
        """
        if not gspread_available:
            raise ImportError("gspread and google-auth are required for Google Sheets integration")

        # Get credentials path
        creds_path = os.getenv("GOOGLE_SHEETS_CREDS_PATH", "google_sheets_credentials.json")
        if not spreadsheet_id:
            spreadsheet_id = os.getenv("GOOGLE_SPREADSHEET_ID")
            
        if not os.path.exists(creds_path) and not os.getenv("GOOGLE_SHEETS_CREDS_JSON"):
            for file in os.listdir("."):
                if file.endswith(".json") and file != "package.json":
                    try:
                        import json
                        with open(file, "r") as f:
                            info = json.load(f)
                            if info.get("type") == "service_account" and "project_id" in info:
                                creds_path = file
                                break
                    except Exception:
                        pass

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        creds_json = os.getenv("GOOGLE_SHEETS_CREDS_JSON")
        if creds_json:
            import json
            creds_data = json.loads(creds_json)
            creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
        else:
            creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
            
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(spreadsheet_id)
        
        try:
            worksheet = sh.worksheet("FMS")
        except gspread.WorksheetNotFound:
            raise ValueError("Worksheet 'FMS' not found in spreadsheet.")

        # Fetch all values to perform search
        all_rows = worksheet.get_all_values()
        
        target_crs = str(crs_number).strip().lower()
        if not target_crs:
            raise ValueError("CRS Number cannot be empty.")

        # Row 7 is header (index 6). Rows below (index 7+) contain data
        # B column is index 1, F column is index 5
        for row in all_rows[7:]:
            if len(row) > 1:
                row_crs = str(row[1]).strip().lower()
                if row_crs == target_crs:
                    if len(row) > 5 and row[5]:
                        return row[5].strip()
                    else:
                        raise ValueError(f"CRS Number '{crs_number}' found but Column F (Image of CRS) is empty.")

        raise ValueError(f"CRS Number '{crs_number}' not found in column B of 'FMS' sheet.")
