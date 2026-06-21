"""Schemas for the Calendar agent."""

from datetime import datetime
from pydantic import BaseModel


class CalendarEvents(BaseModel):
    calendarname: str = "khoiduong2913@gmail.com"
    fromdate: str
    todate: str
    query: str


class CalendarRequest(BaseModel):
    calendarName: str = "khoiduong2913@gmail.com"
    """Google Calendar id. The user's email addresses their primary calendar;
    'primary' also works. (Not a macOS calendar name.)"""
    title: str = ""
    id: str = ""
    start: datetime | None = None
    end: datetime | None = None
    description: str = ""
    attendees: list[str] = []
    """Email addresses to invite. Adding attendees sends Google Calendar
    invitations (external notification), so it's treated as data egress."""


class CalendarResult(BaseModel):
    success: bool
    message: str
    title: str = ""
    start: datetime = None
    event_id: str = ""
