from datetime import datetime,timezone
from types import SimpleNamespace
from app.worker import schedule_window


def test_live_schedule_after_two_week_pause_uses_current_time_once():
    current=datetime(2026,10,29,17,tzinfo=timezone.utc)
    schedule=SimpleNamespace(dataset_id=None,next_run=datetime(2026,10,15,6,tzinfo=timezone.utc),hour=9,minute=0)
    control,next_run=schedule_window(schedule,current)
    assert control==current
    assert next_run==datetime(2026,10,30,6,tzinfo=timezone.utc)


def test_next_run_uses_moscow_calendar_after_midnight():
    current=datetime(2026,10,29,22,tzinfo=timezone.utc)
    schedule=SimpleNamespace(dataset_id=None,next_run=current,hour=9,minute=0)
    assert schedule_window(schedule,current)[1]==datetime(2026,10,30,6,tzinfo=timezone.utc)


def test_explicit_dataset_keeps_its_historical_control_time():
    current=datetime(2026,10,29,17,tzinfo=timezone.utc)
    original=datetime(2026,10,15,6,tzinfo=timezone.utc)
    schedule=SimpleNamespace(dataset_id='organizer',next_run=original,hour=9,minute=0)
    control,next_run=schedule_window(schedule,current)
    assert control==original and next_run>current
