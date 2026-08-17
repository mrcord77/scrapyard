"""Deposit Shield — itemized dispute letter generator (product-specific glue).

GET /letter/{tenancy_id} -> a ready-to-send dispute letter: every contested
deduction answered with the paired move-in/move-out evidence for that room,
plus the statutory return deadline math.
"""
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from scrapyard.database.db_session import get_db
from scrapyard.models.routes import current_user_id
from scrapyard.models import models as M

router = APIRouter()

def _money(cents):
    return f"${(cents or 0)/100:,.2f}"

def _dt(v):
    return str(v)[:10] if v else "—"

@router.get("/letter/{tenancy_id}", response_class=PlainTextResponse)
def dispute_letter(tenancy_id: int, db: Session = Depends(get_db),
                   uid: int = Depends(current_user_id)):
    t = db.get(M.Tenancy, tenancy_id)
    if not t or t.user_id != uid:
        raise HTTPException(404, "tenancy not found")
    deductions = db.query(M.Deduction).filter_by(tenancy_id=tenancy_id, user_id=uid).all()
    shots = db.query(M.EvidenceShot).filter_by(tenancy_id=tenancy_id, user_id=uid).all()
    contested = [d for d in deductions if d.status == "contested"]
    total = sum(d.amount_cents or 0 for d in contested)
    deadline = ""
    if t.move_out and t.return_deadline_days:
        due = t.move_out + timedelta(days=t.return_deadline_days)
        deadline = (f"Under the applicable statute, an itemized statement and any refund were "
                    f"due within {t.return_deadline_days} days of my {_dt(t.move_out)} move-out — "
                    f"that is, by {_dt(due)}.")

    by_room = {}
    for s in shots:
        by_room.setdefault((s.room or "").lower(), []).append(s)

    L = [f"To: {t.landlord}",
         f"Re: Security deposit for {t.address}", "",
         "I am writing to formally dispute the following deductions from my "
         f"security deposit of {_money(t.deposit_cents)}.", ""]
    if deadline:
        L += [deadline, ""]
    for i, d in enumerate(contested, 1):
        L += [f"{i}. Deduction of {_money(d.amount_cents)} — \"{d.landlord_reason}\""]
        room_key = next((r for r in by_room if r and r in (d.landlord_reason or "").lower()), None)
        room_shots = by_room.get(room_key, [])
        ins = [s for s in room_shots if s.phase == "move_in"]
        outs = [s for s in room_shots if s.phase == "move_out"]
        if ins or outs:
            L.append("   My timestamped condition evidence for this item:")
            for s in ins:
                L.append(f"     - MOVE-IN  {_dt(s.taken_at)} [{s.room}] {s.condition_note} (photo: {s.photo_ref})")
            for s in outs:
                L.append(f"     - MOVE-OUT {_dt(s.taken_at)} [{s.room}] {s.condition_note} (photo: {s.photo_ref})")
        else:
            L.append("   No itemized proof accompanied this deduction, as required for it to be withheld.")
        L.append("")
    L += [f"Total disputed: {_money(total)}.",
          "",
          "I request return of the disputed amount within 14 days. My records — "
          f"{len(shots)} timestamped condition photos with notes, kept from move-in day — "
          "are preserved on a tamper-evident log and will accompany any small-claims filing.",
          "",
          "Sincerely,", "Tenant of record"]
    return "\n".join(L)
