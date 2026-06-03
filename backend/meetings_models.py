"""
Models for Meetings & Recordings Hub
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class MeetingParticipant(BaseModel):
    name: str
    email: str
    role: Optional[str] = None

class ActionItem(BaseModel):
    id: str
    text: str
    meeting_id: str
    meeting_title: str
    assigned_to: Optional[str] = None  # email
    assigned_to_name: Optional[str] = None
    status: str = "open"  # open, done
    source: str  # fireflies
    created_at: str
    
class MeetingSentiment(BaseModel):
    positive: float = 0.0
    negative: float = 0.0
    neutral: float = 0.0

class SpeakerAnalytics(BaseModel):
    name: str
    email: Optional[str] = None
    talk_time_percentage: float = 0.0
    words_per_minute: Optional[int] = None
    filler_words: Optional[int] = None

class Meeting(BaseModel):
    id: str
    source: str  # attio, fireflies, both
    attio_id: Optional[str] = None
    fireflies_id: Optional[str] = None
    title: str
    start_time: str
    end_time: Optional[str] = None
    duration_minutes: Optional[int] = None
    participants: List[MeetingParticipant] = []
    host_email: Optional[str] = None
    summary: Optional[str] = None
    topics: List[str] = []
    keywords: List[str] = []
    has_recording: bool = False
    has_video: bool = False
    has_audio: bool = False
    has_transcript: bool = False
    action_items_count: int = 0
    sentiment: Optional[MeetingSentiment] = None
    audio_url: Optional[str] = None
    video_url: Optional[str] = None
    meeting_type: Optional[str] = None
    linked_companies: List[str] = []
    linked_contacts: List[str] = []
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    raw_data: Optional[Dict[str, Any]] = None

class TranscriptLine(BaseModel):
    speaker: str
    text: str
    start_time: float
    end_time: float
    ai_filters: Optional[Dict[str, Any]] = None  # For Fireflies AI highlights

class MeetingTranscript(BaseModel):
    meeting_id: str
    source: str  # attio, fireflies, attio_notes
    lines: List[TranscriptLine] = []
    transcript_url: Optional[str] = None
    raw_note: Optional[str] = None
    fetched_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class MeetingSyncStatus(BaseModel):
    last_sync_attio: Optional[str] = None
    last_sync_fireflies: Optional[str] = None
    total_meetings: int = 0
    attio_count: int = 0
    fireflies_count: int = 0
    deduplicated_count: int = 0
    is_syncing: bool = False
    sync_started_at: Optional[str] = None

class MeetingFilters(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    participant_email: Optional[str] = None
    participant_name: Optional[str] = None
    keyword: Optional[str] = None
    source: Optional[str] = None  # attio, fireflies, both
    has_recording: Optional[bool] = None
    has_action_items: Optional[bool] = None
    has_video: Optional[bool] = None
    sentiment: Optional[str] = None  # positive, negative, neutral
    host_email: Optional[str] = None
    linked_company: Optional[str] = None
    sort_by: str = "date"  # date, duration
    sort_order: str = "desc"  # asc, desc
    limit: int = 50
    offset: int = 0
