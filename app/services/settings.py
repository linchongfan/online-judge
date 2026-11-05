from sqlalchemy.orm import Session

from app.models import SystemSetting

DEFAULTS = {"submissions_enabled": True, "global_queue_limit": 1000}


def get_setting(db: Session, key: str):
    row = db.get(SystemSetting, key)
    return row.value if row is not None else DEFAULTS[key]


def set_setting(db: Session, key: str, value) -> SystemSetting:
    if key not in DEFAULTS:
        raise KeyError(key)
    row = db.get(SystemSetting, key)
    if row is None:
        row = SystemSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    return row
