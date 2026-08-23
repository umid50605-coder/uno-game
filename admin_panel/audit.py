"""
admin_panel/audit.py — har bir o'zgartiruvchi/o'chiruvchi admin amalini
admin.db ichidagi audit jurnaliga yozib qo'yadigan yordamchi funksiya.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from admin_panel.admin_db import AdminAuditLog


def log_action(
    admin_db: Session,
    *,
    admin_username: str,
    ip_address: str,
    action: str,
    target: str,
    detail: str = "",
) -> None:
    """Amalni audit jurnaliga yozadi. Bu chaqiruv hech qachon asosiy
    amalni to'xtatmasligi kerak — shuning uchun xato bo'lsa ham asosiy
    tranzaksiyaga ta'sir qilmasligi uchun alohida commit qilinadi."""
    entry = AdminAuditLog(
        admin_username=admin_username,
        ip_address=ip_address,
        action=action,
        target=target,
        detail=detail[:1024],
    )
    admin_db.add(entry)
    admin_db.commit()
