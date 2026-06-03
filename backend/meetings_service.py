"""
Meetings Service - Handles sync, deduplication, and data management
"""
import asyncio
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import pytz
from dateutil import parser
from motor.motor_asyncio import AsyncIOMotorDatabase

from attio_client import AttioClient
from fireflies_client import FirefliesClient
from meetings_models import (
    Meeting, MeetingParticipant, MeetingSentiment, 
    SpeakerAnalytics, ActionItem, TranscriptLine,
    MeetingTranscript, MeetingSyncStatus
)

class MeetingsService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.attio = AttioClient()
        self.fireflies = FirefliesClient()
        self.timezone = pytz.timezone(os.environ.get("MEETINGS_TIMEZONE", "Asia/Kolkata"))
    
    def _deduplicate_meetings(
        self, 
        meeting1: Dict[str, Any], 
        meeting2: Dict[str, Any]
    ) -> bool:
        """
        Check if two meetings are duplicates based on:
        - Timestamp within 15 minutes
        - At least one overlapping participant email
        """
        try:
            time1 = parser.parse(meeting1["start_time"])
            time2 = parser.parse(meeting2["start_time"])
            time_diff = abs((time1 - time2).total_seconds() / 60)
            
            if time_diff > 15:
                return False
            
            # Check for overlapping participants
            emails1 = {p["email"].lower() for p in meeting1.get("participants", []) if p.get("email")}
            emails2 = {p["email"].lower() for p in meeting2.get("participants", []) if p.get("email")}
            
            return len(emails1 & emails2) > 0
        except Exception as e:
            print(f"Deduplication error: {e}")
            return False
    
    async def _process_attio_meeting(self, meeting_data: Dict[str, Any]) -> Meeting:
        """Convert Attio meeting data to Meeting model.

        Actual Attio GET /v2/meetings response shape:
          id: { workspace_id, meeting_id }
          title: str
          start: { datetime, timezone }
          end:   { datetime, timezone }
          participants[]: { email_address, status, is_organizer }
          linked_records[]: { object_slug, record_id, ... }
        """
        # id is nested: { "workspace_id": "...", "meeting_id": "..." }
        id_obj = meeting_data.get("id") or {}
        if isinstance(id_obj, dict):
            meeting_id = id_obj.get("meeting_id") or id_obj.get("workspace_id") or "unknown"
        else:
            meeting_id = str(id_obj) or meeting_data.get("meeting_id", "unknown")

        # timestamps
        start_block = meeting_data.get("start") or {}
        end_block = meeting_data.get("end") or {}
        start_iso = start_block.get("datetime") or meeting_data.get("start_at") or meeting_data.get("started_at") or ""
        end_iso = end_block.get("datetime") or meeting_data.get("end_at") or meeting_data.get("ended_at")

        duration = None
        if start_iso and end_iso:
            try:
                start = parser.parse(start_iso)
                end = parser.parse(end_iso)
                duration = int((end - start).total_seconds() / 60)
            except Exception:
                pass

        # participants: email_address field (not email)
        participants = []
        for p in meeting_data.get("participants", []):
            email = (
                p.get("email_address")
                or p.get("email")
                or ""
            )
            name = p.get("name") or p.get("display_name") or email
            role = "organizer" if p.get("is_organizer") else p.get("status")
            participants.append(MeetingParticipant(name=name, email=email, role=role))

        # linked companies/contacts from linked_records
        linked_companies = []
        linked_contacts = []
        for rec in meeting_data.get("linked_records", []):
            slug = rec.get("object_slug", "")
            rec_id = rec.get("record_id", "")
            if slug == "companies":
                linked_companies.append(rec_id)
            elif slug in ("people", "contacts"):
                linked_contacts.append(rec_id)

        recording_ids = meeting_data.get("call_recording_ids", [])
        has_rec = len(recording_ids) > 0

        return Meeting(
            id=f"attio_{meeting_id}",
            source="attio",
            attio_id=str(meeting_id),
            title=meeting_data.get("title", "Untitled Meeting"),
            start_time=start_iso,
            end_time=end_iso,
            duration_minutes=duration,
            participants=participants,
            has_recording=has_rec,
            has_transcript=has_rec,
            linked_companies=linked_companies,
            linked_contacts=linked_contacts,
            raw_data=meeting_data
        )
    
    @staticmethod
    def _ff_date_to_iso(date_val) -> Optional[str]:
        """Fireflies returns date as Unix milliseconds (int). Convert to ISO string."""
        if date_val is None:
            return None
        try:
            if isinstance(date_val, (int, float)):
                # Unix ms → datetime
                return datetime.utcfromtimestamp(date_val / 1000).isoformat() + "Z"
            # Already a string — try parsing as-is
            return parser.parse(str(date_val)).isoformat()
        except Exception:
            return None

    async def _process_fireflies_meeting(self, transcript_data: Dict[str, Any]) -> Meeting:
        """Convert Fireflies transcript data to Meeting model.

        Actual Fireflies field shapes:
          date: Unix milliseconds (int)
          duration: float minutes
          participants: List[str] of emails (when meeting_attendees is null)
          meeting_attendees: List[{name, email}] or null
        """
        # Build participant list from meeting_attendees first, fall back to participants emails
        participants = []
        attendees = transcript_data.get("meeting_attendees") or []
        if attendees:
            for a in attendees:
                participants.append(MeetingParticipant(
                    name=a.get("name") or a.get("email") or "",
                    email=a.get("email") or ""
                ))
        else:
            for email in (transcript_data.get("participants") or []):
                if isinstance(email, str):
                    participants.append(MeetingParticipant(name=email, email=email))

        # date: Unix ms → ISO
        start_iso = self._ff_date_to_iso(transcript_data.get("date"))

        # duration: Fireflies returns float minutes
        raw_duration = transcript_data.get("duration")
        duration_minutes = int(round(raw_duration)) if raw_duration is not None else None

        summary = transcript_data.get("summary") or {}
        _ai = summary.get("action_items") or []
        if isinstance(_ai, list):
            action_items_count = len(_ai)
        else:
            action_items_count = len([l for l in str(_ai).split("\n") if l.strip() and not l.strip().startswith("**")])

        sentiment = None
        analytics = transcript_data.get("analytics") or {}
        if analytics.get("sentiments"):
            sent = analytics["sentiments"]
            sentiment = MeetingSentiment(
                positive=sent.get("positive_pct") or sent.get("positive") or 0.0,
                negative=sent.get("negative_pct") or sent.get("negative") or 0.0,
                neutral=sent.get("neutral_pct") or sent.get("neutral") or 0.0
            )

        # Remap speaker fields: duration_pct → talk_time_percentage
        speakers_raw = analytics.get("speakers") or []
        for spk in speakers_raw:
            if "duration_pct" in spk and "talk_time_percentage" not in spk:
                spk["talk_time_percentage"] = spk["duration_pct"]

        return Meeting(
            id=f"fireflies_{transcript_data['id']}",
            source="fireflies",
            fireflies_id=transcript_data["id"],
            title=transcript_data.get("title") or "Untitled Meeting",
            start_time=start_iso or "",
            duration_minutes=duration_minutes,
            participants=participants,
            host_email=transcript_data.get("host_email"),
            summary=summary.get("overview"),
            topics=summary.get("topics_discussed") or [],
            keywords=summary.get("keywords") or [],
            has_recording=bool(transcript_data.get("audio_url") or transcript_data.get("video_url")),
            has_video=bool(transcript_data.get("video_url")),
            has_audio=bool(transcript_data.get("audio_url")),
            has_transcript=True,
            action_items_count=action_items_count,
            sentiment=sentiment,
            audio_url=transcript_data.get("audio_url"),
            video_url=transcript_data.get("video_url"),
            meeting_type=summary.get("meeting_type"),
            raw_data=transcript_data
        )
    
    async def sync_meetings(self, lookback_days: int = 90) -> Dict[str, Any]:
        """
        Sync meetings from Attio and Fireflies
        - Fetches meetings from last N days
        - Deduplicates and merges
        - Stores in MongoDB
        """
        try:
            # Update sync status
            await self.db.meetings_sync_status.update_one(
                {"_id": "main"},
                {"$set": {
                    "is_syncing": True,
                    "sync_started_at": datetime.utcnow().isoformat()
                }},
                upsert=True
            )
            
            # Calculate date range
            end_date = datetime.now(self.timezone)
            start_date = end_date - timedelta(days=lookback_days)
            
            # Fetch from Attio (cursor-based pagination, not offset)
            print(f"Fetching Attio meetings from {start_date} to {end_date}")
            attio_meetings = []
            cursor = None

            while True:
                result = await self.attio.search_meetings(
                    starts_after=start_date.isoformat(),
                    starts_before=end_date.isoformat(),
                    limit=100,
                    cursor=cursor,
                )
                meetings_data = result.get("data") or []
                attio_meetings.extend(meetings_data)
                cursor = result.get("next_cursor")
                print(f"  Attio: +{len(meetings_data)} (total {len(attio_meetings)}, more={bool(cursor)})")
                if not cursor or len(meetings_data) == 0:
                    break

            print(f"Fetched {len(attio_meetings)} Attio meetings total")
            
            # Fetch from Fireflies
            print("Fetching Fireflies transcripts")
            fireflies_transcripts = []
            skip = 0
            batch_size = 50  # Fireflies API max

            while True:
                batch = await self.fireflies.get_transcripts(limit=batch_size, skip=skip)
                if not batch:
                    break
                # No date filtering — include ALL transcripts (Fireflies usually has < 200)
                fireflies_transcripts.extend(batch)
                if len(batch) < batch_size:
                    break
                skip += batch_size
            
            print(f"Fetched {len(fireflies_transcripts)} Fireflies transcripts")
            
            # Process and deduplicate
            processed_attio = []
            for meeting in attio_meetings:
                processed = await self._process_attio_meeting(meeting)
                processed_attio.append(processed.model_dump())
            
            processed_fireflies = []
            for transcript in fireflies_transcripts:
                processed = await self._process_fireflies_meeting(transcript)
                processed_fireflies.append(processed.model_dump())
            
            # Deduplicate
            merged_meetings = []
            matched_fireflies = set()
            
            for attio_meeting in processed_attio:
                # Look for matching Fireflies meeting
                match_found = False
                for i, ff_meeting in enumerate(processed_fireflies):
                    if i in matched_fireflies:
                        continue
                    
                    if self._deduplicate_meetings(attio_meeting, ff_meeting):
                        # Merge the two
                        merged = attio_meeting.copy()
                        merged["source"] = "both"
                        merged["fireflies_id"] = ff_meeting["fireflies_id"]
                        merged["summary"] = ff_meeting.get("summary")
                        merged["topics"] = ff_meeting.get("topics", [])
                        merged["keywords"] = ff_meeting.get("keywords", [])
                        merged["sentiment"] = ff_meeting.get("sentiment")
                        merged["action_items_count"] = ff_meeting.get("action_items_count", 0)
                        merged["audio_url"] = ff_meeting.get("audio_url")
                        merged["video_url"] = ff_meeting.get("video_url")
                        merged["has_video"] = ff_meeting.get("has_video", False)
                        merged["has_audio"] = ff_meeting.get("has_audio", False)
                        
                        merged_meetings.append(merged)
                        matched_fireflies.add(i)
                        match_found = True
                        break
                
                if not match_found:
                    merged_meetings.append(attio_meeting)
            
            # Add unmatched Fireflies meetings
            for i, ff_meeting in enumerate(processed_fireflies):
                if i not in matched_fireflies:
                    merged_meetings.append(ff_meeting)
            
            # Upsert meetings to MongoDB
            for meeting in merged_meetings:
                await self.db.meetings_cache.update_one(
                    {"id": meeting["id"]},
                    {"$set": meeting},
                    upsert=True
                )

            # ── BULK TRANSCRIPT IMPORT ──────────────────────────────────────

            # 1. Fireflies: store summary + transcript_url as transcript content
            #    (sentences are empty on free plan, but summary IS the transcript value)
            print("Importing Fireflies transcripts...")
            ff_transcript_count = 0
            for ff_raw in fireflies_transcripts:
                meeting_id = f"fireflies_{ff_raw['id']}"
                summary = ff_raw.get("summary") or {}
                overview = summary.get("overview") or ""
                # bullet_gist and action_items can be str OR list depending on plan/account
                _bg_raw = summary.get("bullet_gist") or []
                bullet_gist = _bg_raw if isinstance(_bg_raw, list) else [l for l in str(_bg_raw).split("\n") if l.strip()]
                _ai_raw = summary.get("action_items") or []
                action_items_list = _ai_raw if isinstance(_ai_raw, list) else [l for l in str(_ai_raw).split("\n") if l.strip()]
                _topics_raw = summary.get("topics_discussed") or []
                topics = _topics_raw if isinstance(_topics_raw, list) else [l for l in str(_topics_raw).split("\n") if l.strip()]
                _kw_raw = summary.get("keywords") or []
                keywords = _kw_raw if isinstance(_kw_raw, list) else [l for l in str(_kw_raw).split(",") if l.strip()]
                transcript_url = ff_raw.get("transcript_url") or f"https://app.fireflies.ai/view/{ff_raw['id']}"

                import re as _re2

                def _clean_md(text: str) -> str:
                    """Strip markdown formatting from a string."""
                    text = _re2.sub(r'\*\*(.+?)\*\*', r'\1', text)
                    text = _re2.sub(r'\*(.+?)\*', r'\1', text)
                    text = text.strip("- •*#").strip()
                    return text

                # Build transcript lines: summary → key points → action items
                lines = []
                if overview:
                    lines.append({
                        "speaker": "Summary",
                        "text": _clean_md(overview),
                        "start_time": 0,
                        "end_time": 0,
                        "ai_filters": None
                    })
                for b in bullet_gist:
                    clean_b = _clean_md(str(b))
                    if len(clean_b) > 3:
                        lines.append({
                            "speaker": "Key Point",
                            "text": clean_b,
                            "start_time": 0,
                            "end_time": 0,
                            "ai_filters": None
                        })
                for item in action_items_list:
                    clean_item = _clean_md(str(item))
                    if len(clean_item) > 5:
                        lines.append({
                            "speaker": "Action Item",
                            "text": clean_item,
                            "start_time": 0,
                            "end_time": 0,
                            "ai_filters": {"task": clean_item}
                        })

                # The meeting may be stored under its Fireflies ID OR merged under an Attio ID.
                # Find the actual cache ID to update.
                cache_meeting = (
                    await self.db.meetings_cache.find_one({"id": meeting_id}, {"_id": 0, "id": 1})
                    or await self.db.meetings_cache.find_one({"fireflies_id": ff_raw["id"]}, {"_id": 0, "id": 1})
                )
                cache_id = cache_meeting["id"] if cache_meeting else meeting_id

                # Update meeting record with summary fields
                update_fields: Dict[str, Any] = {
                    "transcript_url": transcript_url,
                    "has_transcript": bool(lines),
                }
                if overview:
                    update_fields["summary"] = overview
                if topics:
                    update_fields["topics"] = topics
                if keywords:
                    update_fields["keywords"] = keywords
                if action_items_list:
                    update_fields["action_items_count"] = len(action_items_list)

                await self.db.meetings_cache.update_one(
                    {"id": cache_id},
                    {"$set": update_fields},
                    upsert=False
                )

                # Store transcript under the actual cache ID
                if lines:
                    transcript_doc = {
                        "meeting_id": cache_id,
                        "source": "fireflies",
                        "lines": lines,
                        "transcript_url": transcript_url,
                        "fetched_at": datetime.utcnow().isoformat()
                    }
                    await self.db.meeting_transcripts.update_one(
                        {"meeting_id": cache_id},
                        {"$set": transcript_doc},
                        upsert=True
                    )
                    ff_transcript_count += 1

            print(f"Stored {ff_transcript_count} Fireflies transcripts")

            # 2. Attio: parse notes — each note contains Fireflies-synced content
            #    (summary, key insights, action items with timestamps)
            print("Importing Attio note transcripts...")
            attio_notes_result = await self.attio.get_notes(limit=50)
            attio_notes = attio_notes_result.get("data") or []
            attio_transcript_count = 0

            import re as _re

            for note in attio_notes:
                content_md = note.get("content_markdown") or ""
                content_plain = note.get("content_plaintext") or ""
                if not content_plain.strip():
                    continue

                # Extract Fireflies transcript ID from note
                ff_ids_in_note = _re.findall(r'fireflies\.ai/view/([A-Z0-9]+)', content_plain)
                ff_id_ref = ff_ids_in_note[0] if ff_ids_in_note else None

                # Extract meeting title from note title: "Meeting: <title> (YYYY-MM-DD)"
                title_match = _re.match(r'Meeting:\s*(.+?)\s*\(\d{4}-\d{2}-\d{2}\)', note.get("title", ""))
                note_title = title_match.group(1).strip() if title_match else note.get("title", "")

                # Parse sections from markdown
                lines = []
                current_section = "Note"
                for raw_line in content_plain.split("\n"):
                    line = raw_line.strip()
                    if not line:
                        continue
                    # Detect section headers
                    if line in ("Summary", "Key Insights", "Action Items", "Speakers"):
                        current_section = line
                        continue
                    # Skip metadata lines (Date:, Duration:, Transcript:)
                    if _re.match(r'^(Date|Duration|Transcript|Fireflies meeting sync)[:：]', line):
                        continue
                    # Clean up markdown bold markers
                    clean = _re.sub(r'\*\*(.+?)\*\*', r'\1', line).strip("- •").strip()
                    if not clean:
                        continue

                    ai_filters = None
                    if current_section == "Action Items":
                        ai_filters = {"task": clean}
                    elif current_section == "Key Insights":
                        ai_filters = {"metric": clean}

                    lines.append({
                        "speaker": current_section,
                        "text": clean,
                        "start_time": 0,
                        "end_time": 0,
                        "ai_filters": ai_filters
                    })

                if not lines:
                    continue

                # Extract summary paragraph (first substantial line after "Summary" header)
                summary_text = ""
                in_summary = False
                for raw_line in content_plain.split("\n"):
                    l = raw_line.strip()
                    if l == "Summary":
                        in_summary = True
                        continue
                    if in_summary and l and not _re.match(r'^(Key Insights|Action Items|Speakers)', l):
                        summary_text = l
                        break
                    if in_summary and _re.match(r'^(Key Insights|Action Items|Speakers)', l):
                        break

                # Try to find the matching Attio meeting by title similarity
                # Search by title substring
                matching_meeting = None
                if note_title:
                    matching_meeting = await self.db.meetings_cache.find_one(
                        {"source": {"$in": ["attio", "both"]},
                         "title": {"$regex": _re.escape(note_title[:30]), "$options": "i"}},
                        {"_id": 0, "id": 1}
                    )

                # If Fireflies ID referenced, also try matching by fireflies_id
                if not matching_meeting and ff_id_ref:
                    matching_meeting = await self.db.meetings_cache.find_one(
                        {"fireflies_id": ff_id_ref},
                        {"_id": 0, "id": 1}
                    )

                # Use note ID as fallback meeting_id
                if matching_meeting:
                    target_meeting_id = matching_meeting["id"]
                elif ff_id_ref:
                    target_meeting_id = f"fireflies_{ff_id_ref}"
                else:
                    note_id = (note.get("id") or {})
                    note_id_str = note_id.get("note_id") if isinstance(note_id, dict) else str(note_id)
                    target_meeting_id = f"attio_note_{note_id_str}"

                # Update meeting summary and transcript flag if we found a match
                if matching_meeting:
                    upd: Dict[str, Any] = {"has_transcript": True}
                    if summary_text:
                        upd["summary"] = summary_text
                    await self.db.meetings_cache.update_one(
                        {"id": target_meeting_id},
                        {"$set": upd}
                    )

                # Store transcript
                transcript_doc = {
                    "meeting_id": target_meeting_id,
                    "source": "attio_notes",
                    "lines": lines,
                    "raw_note": content_plain[:5000],
                    "fetched_at": datetime.utcnow().isoformat()
                }
                await self.db.meeting_transcripts.update_one(
                    {"meeting_id": target_meeting_id},
                    {"$set": transcript_doc},
                    upsert=True
                )
                attio_transcript_count += 1

            print(f"Stored {attio_transcript_count} Attio note transcripts")

            # 3. Extract and store action items from both sources
            employees = await self.db.employees.find({}, {"_id": 0, "email": 1, "first_name": 1, "last_name": 1}).to_list(1000)

            # From Fireflies
            for ff_meeting in processed_fireflies:
                if ff_meeting.get("raw_data") and ff_meeting["raw_data"].get("summary"):
                    action_items = ff_meeting["raw_data"]["summary"].get("action_items") or []
                    if isinstance(action_items, list):
                        for i, item_text in enumerate(action_items):
                            assigned_to = None
                            assigned_to_name = None
                            for emp in employees:
                                if emp["email"].lower() in item_text.lower():
                                    assigned_to = emp["email"]
                                    assigned_to_name = f"{emp.get('first_name', '')} {emp.get('last_name', '')}".strip()
                                    break
                            action_item = ActionItem(
                                id=f"{ff_meeting['id']}_action_{i}",
                                text=item_text,
                                meeting_id=ff_meeting["id"],
                                meeting_title=ff_meeting["title"],
                                assigned_to=assigned_to,
                                assigned_to_name=assigned_to_name,
                                source="fireflies",
                                created_at=datetime.utcnow().isoformat()
                            )
                            await self.db.meeting_action_items.update_one(
                                {"id": action_item.id},
                                {"$set": action_item.model_dump()},
                                upsert=True
                            )

            # From Attio notes (extract action items with timestamps)
            for note in attio_notes:
                content_plain = note.get("content_plaintext") or ""
                if "Action Items" not in content_plain:
                    continue
                # Find meeting_id this note maps to
                ff_ids_in_note = _re.findall(r'fireflies\.ai/view/([A-Z0-9]+)', content_plain)
                ff_id_ref = ff_ids_in_note[0] if ff_ids_in_note else None
                title_match = _re.match(r'Meeting:\s*(.+?)\s*\(\d{4}-\d{2}-\d{2}\)', note.get("title", ""))
                note_title = title_match.group(1).strip() if title_match else ""
                matching_meeting = None
                if note_title:
                    matching_meeting = await self.db.meetings_cache.find_one(
                        {"title": {"$regex": _re.escape(note_title[:30]), "$options": "i"}},
                        {"_id": 0, "id": 1, "title": 1}
                    )
                meeting_id_for_items = matching_meeting["id"] if matching_meeting else (f"fireflies_{ff_id_ref}" if ff_id_ref else None)
                meeting_title_for_items = matching_meeting.get("title", note_title) if matching_meeting else note_title
                if not meeting_id_for_items:
                    continue
                # Extract action items section
                in_ai = False
                ai_idx = 0
                for line in content_plain.split("\n"):
                    l = line.strip()
                    if l == "Action Items":
                        in_ai = True
                        continue
                    if in_ai and _re.match(r'^(Speakers|Key Insights|Summary)$', l):
                        break
                    if in_ai and l and not _re.match(r'^[A-Z][a-z]+ [A-Z][a-z]+$', l):
                        clean = l.strip("- •").strip()
                        # Strip trailing timestamp like "(16:45)"
                        clean = _re.sub(r'\s*\(\d+:\d+\)\s*$', '', clean).strip()
                        if len(clean) > 10:
                            item_id = f"attio_note_{ff_id_ref or note_title[:20]}_{ai_idx}"
                            action_item = ActionItem(
                                id=item_id,
                                text=clean,
                                meeting_id=meeting_id_for_items,
                                meeting_title=meeting_title_for_items,
                                source="attio_notes",
                                created_at=datetime.utcnow().isoformat()
                            )
                            await self.db.meeting_action_items.update_one(
                                {"id": item_id},
                                {"$set": action_item.model_dump()},
                                upsert=True
                            )
                            ai_idx += 1
            
            # Update sync status
            await self.db.meetings_sync_status.update_one(
                {"_id": "main"},
                {"$set": {
                    "last_sync_attio": datetime.utcnow().isoformat(),
                    "last_sync_fireflies": datetime.utcnow().isoformat(),
                    "total_meetings": len(merged_meetings),
                    "attio_count": len(processed_attio),
                    "fireflies_count": len(processed_fireflies),
                    "deduplicated_count": len(matched_fireflies),
                    "ff_transcripts_imported": ff_transcript_count,
                    "attio_transcripts_imported": attio_transcript_count,
                    "is_syncing": False
                }},
                upsert=True
            )

            return {
                "success": True,
                "total_meetings": len(merged_meetings),
                "attio_count": len(processed_attio),
                "fireflies_count": len(processed_fireflies),
                "deduplicated_count": len(matched_fireflies),
                "ff_transcripts": ff_transcript_count,
                "attio_transcripts": attio_transcript_count,
            }
            
        except Exception as e:
            print(f"Sync error: {e}")
            await self.db.meetings_sync_status.update_one(
                {"_id": "main"},
                {"$set": {"is_syncing": False}},
                upsert=True
            )
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_transcript(self, meeting_id: str) -> Optional[MeetingTranscript]:
        """Return transcript — from cache (bulk import) or on-demand fetch."""
        # Check cache first (populated during sync)
        cached = await self.db.meeting_transcripts.find_one({"meeting_id": meeting_id}, {"_id": 0})
        if cached:
            lines_raw = cached.get("lines") or []
            lines = [TranscriptLine(**l) for l in lines_raw]
            if lines:
                return MeetingTranscript(
                    meeting_id=meeting_id,
                    source=cached.get("source", "unknown"),
                    lines=lines
                )
        
        # Determine source and fetch
        meeting = await self.db.meetings_cache.find_one({"id": meeting_id}, {"_id": 0})
        if not meeting:
            return None
        
        transcript_lines = []
        source = None
        
        # Try Fireflies first (has AI highlights)
        if meeting.get("fireflies_id"):
            transcript_data = await self.fireflies.get_transcript(meeting["fireflies_id"])
            if transcript_data and transcript_data.get("sentences"):
                source = "fireflies"
                for sentence in transcript_data["sentences"]:
                    transcript_lines.append(TranscriptLine(
                        speaker=sentence.get("speaker_name", "Unknown"),
                        text=sentence.get("text", ""),
                        start_time=sentence.get("start_time", 0),
                        end_time=sentence.get("end_time", 0),
                        ai_filters=sentence.get("ai_filters")
                    ))
        
        # Fallback to Attio
        if not transcript_lines and meeting.get("attio_id"):
            # Get first recording ID
            raw_data = meeting.get("raw_data", {})
            recording_ids = raw_data.get("call_recording_ids", [])
            if recording_ids:
                transcript_data = await self.attio.get_meeting_transcript(
                    meeting["attio_id"],
                    recording_ids[0]
                )
                if transcript_data and transcript_data.get("transcript"):
                    source = "attio"
                    for line in transcript_data["transcript"]:
                        transcript_lines.append(TranscriptLine(
                            speaker=line.get("speaker", "Unknown"),
                            text=line.get("text", ""),
                            start_time=line.get("start", 0),
                            end_time=line.get("end", 0)
                        ))
        
        if not transcript_lines:
            return None
        
        # Cache transcript
        transcript = MeetingTranscript(
            meeting_id=meeting_id,
            source=source,
            lines=transcript_lines
        )
        
        await self.db.meeting_transcripts.insert_one(transcript.model_dump())
        
        return transcript
