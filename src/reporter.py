import os
import logging
from decimal import Decimal
from typing import Optional, List, Dict, Any
import pandas as pd

from src.domain.models import AuditResult, AuditStatus

logger = logging.getLogger(__name__)


class AuditReporter:
    REQUIRED_COLUMNS = [
        "Invoice_ID",
        "Property",
        "Unit",
        "Status",
        "Calculated_BillBack",
        "AppFolio_BillBack",
        "Variance",
        "Notes"
    ]

    def __init__(self, output_path: str):
        self.output_path = os.path.abspath(output_path)
        self.results: List[Dict[str, Any]] = []

        os.makedirs(self.output_path, exist_ok=True)
        logger.info("AuditReporter initialized at %s", self.output_path)

    def add_audit_result(self, result: AuditResult) -> None:
        """Registra un objeto AuditResult directamente en el reportero."""
        req = result.request
        inv_amount = req.invoice.amount
        af_paid = req.accounting.appfolio_amount_paid
        variance = inv_amount - af_paid

        status_str = result.status.name

        # Mapeo de estados para la lógica de reporte existente
        if result.status == AuditStatus.BILLABLE:
            if abs(variance) > Decimal("0.05") and af_paid > Decimal("0.00"):
                status_str = "VARIANCE_DETECTED"
            else:
                status_str = "BILL_BACK_GENERATED"
        elif result.status == AuditStatus.ILLEGAL_GL:
            status_str = "ILLEGAL_CHARGE_ATTEMPT"
        elif result.status == AuditStatus.VACANT:
            status_str = "VACANT_OR_NO_MATCH"

        self.results.append({
            "Invoice_ID": str(req.invoice.invoice_id),
            "Property": str(req.property.property_name),
            "Unit": str(req.property.unit_name),
            "Status": status_str,
            "Calculated_BillBack": float(result.calculated_bill_back),
            "AppFolio_BillBack": float(af_paid),
            "Variance": float(variance),
            "Notes": result.notes
        })

    def save_report(self, filename: str) -> str:
        if not filename.lower().endswith(".xlsx"):
            raise ValueError("Filename must end with .xlsx")

        safe_filename = os.path.basename(filename)
        full_path = os.path.join(self.output_path, safe_filename)

        df_all = pd.DataFrame(self.results)
        if df_all.empty:
            df_all = pd.DataFrame(columns=self.REQUIRED_COLUMNS)
        else:
            for col in self.REQUIRED_COLUMNS:
                if col not in df_all.columns:
                    df_all[col] = None
            df_all = df_all[self.REQUIRED_COLUMNS]

        action_required = df_all[
            df_all["Status"].str.contains("MISSING|VARIANCE_DETECTED|ILLEGAL", na=False)
        ]

        with pd.ExcelWriter(full_path, engine="xlsxwriter") as writer:
            action_required.to_excel(writer, sheet_name="Action_Items", index=False)
            df_all.to_excel(writer, sheet_name="Full_Audit_Trail", index=False)

            workbook = writer.book
            fmt_red = workbook.add_format({"bg_color": "#FFC7CE", "font_color": "#9C0006"})
            fmt_yellow = workbook.add_format({"bg_color": "#FFEB9C", "font_color": "#9C6500"})

            worksheet = writer.sheets["Action_Items"]
            row_count = max(len(action_required) + 1, 2)

            worksheet.conditional_format(f"D2:D{row_count}", {"type": "text", "criteria": "containing", "value": "VARIANCE", "format": fmt_red})
            worksheet.conditional_format(f"D2:D{row_count}", {"type": "text", "criteria": "containing", "value": "MISSING", "format": fmt_yellow})

        return full_path

    def generate_email_summary(self, output_filename="Email_Summary.txt"):
        if not self.results: 
            return None

        df = pd.DataFrame(self.results)
        bill_backs = df[df['Calculated_BillBack'] > 0.0]

        email_text = "Subject: AURA Audit - Pending Tenant Bill-Backs\n\n"
        email_text += "Hi team,\n\nWe have processed the latest batch of utility invoices and calculated the correct prorated amounts to be billed back to the tenants.\n\n"
        email_text += "### 🟢 Action Required: Pending Tenant Bill-Backs\n"
        email_text += "Please generate the following charges in AppFolio based on the tenants' occupied days:\n\n"

        if not bill_backs.empty:
            for _, row in bill_backs.iterrows():
                notes = str(row.get('Notes', ''))
                tenant_info = notes if "Inquilino:" in notes else "Tenant: Unknown"

                email_text += f"* **{row['Property']} - {row['Unit']}** (Inv: {row['Invoice_ID']})\n"
                email_text += f"    * **{tenant_info}**\n"
                email_text += f"    * **Amount to Bill:** ${row['Calculated_BillBack']:.2f} *(Total Invoice: ${row['Variance']:.2f})*\n"
        else:
            email_text += "*No pending bill-backs detected in this run.*\n"

        email_text += "\nNote: Vacant units and common areas have been logged for compliance and are available in the full Excel report. Let me know once these bill-backs have been entered into AppFolio.\n\nBest regards,\n\nAURA Audit System"

        output_path = os.path.join(self.output_path, output_filename)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(email_text)

        return output_path
