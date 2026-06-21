"""Schemas for the Calendar agent."""

from datetime import datetime
from pydantic import BaseModel


class CalendarEvents(BaseModel):
    calendarname: str = "primary"
    fromdate: str
    todate: str
    query: str


class CalendarRequest(BaseModel):
    calendarName: str = "primary"
    """Google Calendar id. 'primary' targets the authenticated user's own primary
    calendar (the safe default). A specific calendar id / email also works if the
    user has access. (Not a macOS calendar name.)"""
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
