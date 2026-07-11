"""Check #6 — manual override of an agent booking.

The strongest ground truth we have: if a human admin had to touch a record the
agent created, the agent got something wrong (or incomplete). Detected purely
from record metadata — no parsing of free-text needed:
  - last_change_date noticeably after create_date, OR
  - the record sits on the АДМИНИСТРАТОРЫ column (parked for manual handling)

Operates over records (not episodes): agent bookings are identified by the
comment stamp the agent writes ("WhatsApp (Wappi) bot booking #N").
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional

from ..findings import Finding, FLAG_HUMAN, OK
from ..loader import phone_key

_BOT_STAMP = re.compile(r"whatsapp \(wappi\) bot booking", re.I)
_ADMIN_STAFF = re.compile(r"администратор|лист ожидания", re.I)
# change later than this many seconds after creation counts as a human edit
_EDIT_THRESHOLD_S = 180


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip().replace("Z", "+00:00")
    # YClients gives "2026-07-10T16:40:20+0300" (no colon in tz) or with colon
    m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})([+-]\d{2}):?(\d{2})?", s)
    if m:
        tz = m.group(2) + (m.group(3) or "00")
        try:
            return datetime.strptime(m.group(1) + tz, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            return None
    return None


def is_agent_booking(rec: Dict) -> bool:
    return bool(_BOT_STAMP.search(rec.get("comment") or ""))


def check_records(records: List[Dict]) -> List[Finding]:
    findings: List[Finding] = []
    for r in records:
        if not is_agent_booking(r):
            continue
        phone = phone_key((r.get("client") or {}).get("phone"))
        staff = (r.get("staff") or {}).get("name") or ""
        created = _parse_dt(r.get("create_date"))
        changed = _parse_dt(r.get("last_change_date"))
        edited = bool(created and changed and (changed - created).total_seconds() > _EDIT_THRESHOLD_S)
        on_admin = bool(_ADMIN_STAFF.search(staff))
        ev = {
            "yclients_id": r.get("id"),
            "date": r.get("date"),
            "staff": staff,
            "create_date": r.get("create_date"),
            "last_change_date": r.get("last_change_date"),
            "comment": (r.get("comment") or "")[:160],
        }
        if edited or on_admin:
            reasons = []
            if edited:
                dt = int((changed - created).total_seconds())
                reasons.append(f"admin edited the record {dt}s after the agent created it")
            if on_admin:
                reasons.append(f"record parked on '{staff}' (manual-handling column)")
            findings.append(Finding(
                pipeline="manual_override", severity=FLAG_HUMAN, confidence=0.7,
                summary="Agent booking required human touch: " + "; ".join(reasons) + ".",
                phone=phone, episode_ts=None, evidence=ev,
            ))
        else:
            findings.append(Finding(
                pipeline="manual_override", severity=OK, confidence=0.9,
                summary="Agent booking stands untouched by admins.",
                phone=phone, evidence=ev,
            ))
    return findings
