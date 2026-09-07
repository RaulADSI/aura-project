import pandas as pd
import os
import logging
from typing import Optional, List, Dict, Any

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

    # RECORD APPEND (Sin filtros, guardamos TODO para el Excel)
    def add_record(
        self,
        invoice_id: str,
        property_name: str,
        unit: str,
        status: str,
        expected: Optional[float],
        actual: Optional[float],
        diff: Optional[float],
        notes: str = ""
    ) -> None:

        safe_diff = self._safe_float(diff)
        current_status = str(status).upper()
        
        # Consider a variance greater than $0.05 to be an actionable discrepancy
        if current_status == "BILL_BACK_GENERATED" and safe_diff is not None and abs(safe_diff) > 0.05:
            actual_paid = self._safe_float(actual)
            if actual_paid is not None and actual_paid > 0:
                current_status = "VARIANCE_DETECTED"

        self.results.append({
            "Invoice_ID": str(invoice_id) if invoice_id else "",
            "Property": str(property_name) if property_name else "",
            "Unit": str(unit) if unit else "",
            "Status": current_status,
            "Calculated_BillBack": self._safe_float(expected),
            "AppFolio_BillBack": self._safe_float(actual),
            "Variance": safe_diff,
            "Notes": str(notes) if notes else ""
        })

    # SAVE REPORT (Genera el Excel completo con todas las pestañas)
    def save_report(self, filename: str) -> str:

        if not filename.lower().endswith(".xlsx"):
            raise ValueError("Filename must end with .xlsx")

        safe_filename = os.path.basename(filename)
        full_path = os.path.join(self.output_path, safe_filename)

        logger.info("Generating audit report: %s", full_path)

        df_all = pd.DataFrame(self.results)

        if df_all.empty:
            df_all = pd.DataFrame(columns=self.REQUIRED_COLUMNS)
        else:
            # Ensure schema consistency
            for col in self.REQUIRED_COLUMNS:
                if col not in df_all.columns:
                    df_all[col] = None

            df_all = df_all[self.REQUIRED_COLUMNS]

        # Action-required items para la primera pestaña
        action_required = df_all[
            df_all["Status"].str.contains(
                "MISSING|VARIANCE_DETECTED|ILLEGAL",
                na=False
            )
        ]

        try:
            with pd.ExcelWriter(full_path, engine="xlsxwriter") as writer:
                action_required.to_excel(
                    writer,
                    sheet_name="Action_Items",
                    index=False
                )

                df_all.to_excel(
                    writer,
                    sheet_name="Full_Audit_Trail",
                    index=False
                )

                workbook = writer.book

                fmt_red = workbook.add_format({
                    "bg_color": "#FFC7CE",
                    "font_color": "#9C0006"
                })

                fmt_yellow = workbook.add_format({
                    "bg_color": "#FFEB9C",
                    "font_color": "#9C6500"
                })

                worksheet = writer.sheets["Action_Items"]

                row_count = max(len(action_required) + 1, 2)

                worksheet.conditional_format(
                    f"D2:D{row_count}",
                    {
                        "type": "text",
                        "criteria": "containing",
                        "value": "VARIANCE",
                        "format": fmt_red
                    }
                )

                worksheet.conditional_format(
                    f"D2:D{row_count}",
                    {
                        "type": "text",
                        "criteria": "containing",
                        "value": "MISSING",
                        "format": fmt_yellow
                    }
                )

        except Exception as e:
            logger.critical("Failed to generate Excel report: %s", e, exc_info=True)
            raise

        logger.info("Report successfully generated.")
        return full_path

    # INTERNAL UTILITIES
    @staticmethod
    def _safe_float(value: Optional[float]) -> Optional[float]:
        try:
            return round(float(value), 2) if value is not None else None
        except Exception:
            return None
    
    def generate_email_summary(self, output_filename="Email_Summary.txt"):
        """Genera un reporte de texto enfocado ÚNICAMENTE en los cobros (Bill-Backs)."""
        if not self.results: 
            return None

        df = pd.DataFrame(self.results)
        
        # --- FILTRO DEL CORREO: Solo capturamos filas que tengan un monto a cobrar ---
        bill_backs = df[df['Calculated_BillBack'] > 0.0]

        email_text = "Subject: AURA Audit - Pending Tenant Bill-Backs\n\n"
        email_text += "Hi team,\n\nWe have processed the latest batch of utility invoices and calculated the correct prorated amounts to be billed back to the tenants.\n\n"

        # --- ÚNICA SECCIÓN: COBROS ---
        email_text += "### 🟢 Action Required: Pending Tenant Bill-Backs\n"
        email_text += "Please generate the following charges in AppFolio based on the tenants' occupied days:\n\n"
        
        if not bill_backs.empty:
            for _, row in bill_backs.iterrows():
                notes = str(row.get('Notes', ''))
                tenant_info = notes.split("(IA")[0].strip() if "Tenant:" in notes else "Tenant: Unknown"
                
                email_text += f"* **{row['Property']} - {row['Unit']}** (Inv: {row['Invoice_ID']})\n"
                email_text += f"    * **{tenant_info}**\n"
                email_text += f"    * **Amount to Bill:** ${row['Calculated_BillBack']:.2f} *(Total Invoice: ${row['Variance']:.2f})*\n"
        else:
            email_text += "*No pending bill-backs detected in this run.*\n"

        email_text += "\nNote: Vacant units and common areas have been logged for compliance and are available in the full Excel report. Let me know once these bill-backs have been entered into AppFolio.\n\nBest regards,\n\nAURA Audit System"

        # Guardar en archivo de texto
        output_path = os.path.join(self.output_path, output_filename)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(email_text)
            
        return output_path