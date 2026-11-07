"""
Review report generation -- a timestamped summary of what was analysed and what
the reviewer changed, as a multi-sheet Excel workbook (openpyxl, already a dep).

    build_report_xlsx(ific) -> (bytes, generated_at_iso)

Sheets:
  Summary          - publication + provenance + counts (auto vs effective)
  Flagged (ALERT)  - the satellites currently flagged (after overrides)
  Reviewer changes - every label override: auto -> override, with timestamp
  Full shortlist   - the whole ranked list with the effective label
"""

import io
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

APP_DB = Path(__file__).resolve().parent / "app.db"


def _q(sql, params=()):
    con = sqlite3.connect(APP_DB)
    try:
        return pd.read_sql(sql, con, params=params)
    finally:
        con.close()


def build_report_xlsx(ific):
    ific = int(ific)
    gen = datetime.now(timezone.utc).isoformat(timespec="seconds")
    pub = _q("SELECT * FROM publications WHERE ific_no=?", (ific,)).iloc[0]
    sl = _q("SELECT * FROM shortlist WHERE ific_no=?", (ific,))
    try:
        ov = _q("SELECT sat_ntc_id, label, ts FROM review_overrides WHERE ific_no=?", (ific,))
    except Exception:
        ov = pd.DataFrame(columns=["sat_ntc_id", "label", "ts"])
    ovd = dict(zip(ov.sat_ntc_id, ov.label))
    sl["effective_label"] = [ovd.get(int(n), rs)
                             for n, rs in zip(sl.sat_ntc_id, sl.review_status)]

    n_auto = int((sl.review_status == "ALERT").sum())
    n_eff = int((sl.effective_label == "ALERT").sum())
    summary = pd.DataFrame({"field": [
        "Report generated (UTC)", "Publication", "Service", "Country",
        "IFIC processed (UTC)", "Notices in IFIC", "Shortlisted",
        "ALERTs (auto)", "ALERTs (after review)", "Reviewer overrides"],
        "value": [gen, f"IFIC {ific}", pub.service_type, pub.country,
                  pub.processed_at, int(pub.n_notices), int(pub.n_shortlist),
                  n_auto, n_eff, len(ov)]})

    flagged = (sl[sl.effective_label == "ALERT"]
               [["sat_ntc_id", "sat_name", "adm", "is_gso", "worst_margin_db",
                 "alert_stations", "n_bands", "review_status", "effective_label"]]
               .sort_values("worst_margin_db", ascending=False))

    changes = ov.merge(sl[["sat_ntc_id", "sat_name", "review_status"]],
                       on="sat_ntc_id", how="left")
    if len(changes):
        changes = changes.rename(columns={"review_status": "auto_label",
                                          "label": "reviewer_label",
                                          "ts": "changed_at_utc"})
        changes = changes[["sat_ntc_id", "sat_name", "auto_label",
                           "reviewer_label", "changed_at_utc"]]
    else:
        changes = pd.DataFrame({"note": ["No reviewer overrides for this IFIC."]})

    full = sl[["sat_ntc_id", "sat_name", "adm", "is_gso", "review_status",
               "effective_label", "worst_margin_db", "alert_stations", "n_bands"]]

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        summary.to_excel(w, sheet_name="Summary", index=False)
        flagged.to_excel(w, sheet_name="Flagged (ALERT)", index=False)
        changes.to_excel(w, sheet_name="Reviewer changes", index=False)
        full.to_excel(w, sheet_name="Full shortlist", index=False)
        for ws in w.book.worksheets:          # bold headers + autosize-ish
            for c in ws[1]:
                c.font = c.font.copy(bold=True)
            for col in ws.columns:
                width = max((len(str(c.value)) for c in col if c.value), default=10)
                ws.column_dimensions[col[0].column_letter].width = min(width + 2, 48)
    return buf.getvalue(), gen
