"""
Attio CRM API Client

Notes on this workspace:
- Attio Notetaker (call recording feature) is NOT enabled — meetings are calendar events only
- No call_recording_ids on any meeting — that field doesn't exist in the response
- Pagination is cursor-based (not offset): use pagination.next_cursor
- Notes endpoint works and contains Fireflies-synced content
"""
import httpx
import os
from typing import List, Dict, Any, Optional


class AttioClient:
    def __init__(self):
        self.api_key = os.environ.get("ATTIO_API_KEY")
        self.base_url = os.environ.get("ATTIO_BASE_URL", "https://api.attio.com/v2")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def search_meetings(
        self,
        starts_after: Optional[str] = None,
        starts_before: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
        # legacy offset param kept for signature compat but ignored
        offset: int = 0,
    ) -> Dict[str, Any]:
        """List meetings from Attio CRM (GET /v2/meetings, cursor-based pagination)."""
        url = f"{self.base_url}/meetings"
        params: Dict[str, Any] = {"limit": limit}
        if starts_after:
            params["starts_after"] = starts_after
        if starts_before:
            params["starts_before"] = starts_before
        if cursor:
            params["cursor"] = cursor

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(url, params=params, headers=self.headers)
                response.raise_for_status()
                data = response.json()
                # Normalise: expose next_cursor at top level for the sync loop
                pagination = data.get("pagination") or {}
                data["next_cursor"] = pagination.get("next_cursor")
                data["has_more"] = bool(data["next_cursor"])
                return data
            except httpx.HTTPStatusError as e:
                print(f"Attio API Error - search_meetings: {e.response.status_code} {e.response.text[:300]}")
                return {"data": [], "has_more": False, "next_cursor": None}
            except httpx.HTTPError as e:
                print(f"Attio API Error - search_meetings: {e}")
                return {"data": [], "has_more": False, "next_cursor": None}

    async def get_notes(self, limit: int = 50) -> Dict[str, Any]:
        """Get notes (contains Fireflies-synced meeting content)."""
        url = f"{self.base_url}/notes"
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(url, params={"limit": limit}, headers=self.headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                print(f"Attio API Error - get_notes: {e}")
                return {"data": []}

    async def create_task(
        self,
        title: str,
        description: Optional[str] = None,
        due_date: Optional[str] = None,
        assignee: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Create a task in Attio."""
        url = f"{self.base_url}/tasks"
        payload: Dict[str, Any] = {"title": title}
        if description:
            payload["description"] = description
        if due_date:
            payload["due_date"] = due_date
        if assignee:
            payload["assignee"] = assignee

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(url, json=payload, headers=self.headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                print(f"Attio API Error - create_task: {e}")
                return None

    # ── kept for backward compat but these endpoints don't exist in this workspace ──

    async def search_call_recordings(self, **kwargs) -> Dict[str, Any]:
        return {"data": []}

    async def get_meeting_transcript(self, meeting_id: str, recording_id: str) -> Optional[Dict[str, Any]]:
        return None

    async def semantic_search_recordings(self, query: str, limit: int = 20) -> Dict[str, Any]:
        return {"results": []}
