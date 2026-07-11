"""Check #3 — area / emirate routing.

Each master serves exactly one emirate; a cross-emirate booking is a 90-minute
wrong-city drive and a missed appointment. The agent stamps the intended area
into every record comment ("Area: abu_dhabi"). This check compares that stamp to
the emirate the assigned master ACTUALLY serves on that date (marker-aware, so a
floating master like Lyudmila validates by her daily marker, not her name tag).

Record-level, async (needs live staff/marker data). Agent bookings only.
"""

from __future__ import annotations

import re
from typing import Dict, List

from ..findings import Finding, FAIL, OK
from ..loader import phone_key
from ..parsing import record_iso_date
from .manual_override import is_agent_booking, _ADMIN_STAFF

_AREA_STAMP = re.compile(r"Area:\s*([a-z_]+)", re.I)


async def check_records(records: List[Dict], svc) -> List[Finding]:
    findings: List[Finding] = []
    for r in records:
        if not is_agent_booking(r):
            continue
        m = _AREA_STAMP.search(r.get("comment") or "")
        if not m:
            continue
        intended = m.group(1).lower()
        staff = r.get("staff") or {}
        staff_name = staff.get("name") or ""
        staff_id = staff.get("id")
        # Parked on the admin column → no real master assigned yet, area N/A.
        if _ADMIN_STAFF.search(staff_name) or not staff_id:
            continue
        the_date = record_iso_date(r)
        try:
            actual = await svc.staff_area_of(staff_id, date=the_date)
        except Exception:
            actual = None
        if actual is None:
            continue  # couldn't resolve — don't guess
        phone = phone_key((r.get("client") or {}).get("phone"))
        ev = {"yclients_id": r.get("id"), "date": r.get("date"),
              "staff": staff_name, "intended_area": intended, "actual_area": actual}
        if actual != intended:
            findings.append(Finding(
                pipeline="area_routing", severity=FAIL, confidence=0.85,
                summary=f"CROSS-EMIRATE booking: client area '{intended}' but master "
                        f"'{staff_name}' serves '{actual}' on {the_date}.",
                phone=phone, evidence=ev,
            ))
        else:
            findings.append(Finding(
                pipeline="area_routing", severity=OK, confidence=0.9,
                summary=f"Master matches client emirate ({intended}).",
                phone=phone, evidence=ev,
            ))
    return findings
