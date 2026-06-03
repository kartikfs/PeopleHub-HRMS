"""
Fireflies AI GraphQL Client

Free-tier fields: id, title, date, duration, host_email, participants,
  meeting_attendees, summary, sentences.
Paywalled (pro+): audio_url, video_url, analytics.
"""
import os
from gql import gql, Client
from gql.transport.aiohttp import AIOHTTPTransport
from typing import List, Dict, Any, Optional


_TRANSCRIPTS_QUERY = gql("""
    query GetTranscripts($limit: Int, $skip: Int) {
        transcripts(limit: $limit, skip: $skip) {
            id
            title
            date
            duration
            host_email
            participants
            meeting_attendees {
                name
                email
            }
            summary {
                action_items
                overview
                bullet_gist
                topics_discussed
                keywords
                meeting_type
            }
        }
    }
""")

_TRANSCRIPT_QUERY = gql("""
    query GetTranscript($id: String!) {
        transcript(id: $id) {
            id
            title
            date
            duration
            host_email
            participants
            meeting_attendees {
                name
                email
            }
            summary {
                action_items
                overview
                bullet_gist
                topics_discussed
                keywords
                meeting_type
            }
            sentences {
                speaker_name
                text
                start_time
                end_time
                ai_filters {
                    task
                    pricing
                    metric
                    question
                    sentiment
                }
            }
        }
    }
""")

_USER_QUERY = gql("""
    query GetUser {
        user {
            name
            email
        }
    }
""")


class FirefliesClient:
    def __init__(self):
        self.api_key = os.environ.get("FIREFLIES_API_KEY")
        self.graphql_url = os.environ.get("FIREFLIES_GRAPHQL_URL", "https://api.fireflies.ai/graphql")

        transport = AIOHTTPTransport(
            url=self.graphql_url,
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        self.client = Client(transport=transport, fetch_schema_from_transport=False)

    async def get_transcripts(self, limit: int = 50, skip: int = 0) -> List[Dict[str, Any]]:
        """Get list of transcripts (free-tier compatible)."""
        limit = min(limit, 50)
        try:
            async with self.client as session:
                result = await session.execute(
                    _TRANSCRIPTS_QUERY,
                    variable_values={"limit": limit, "skip": skip}
                )
                return result.get("transcripts") or []
        except Exception as e:
            print(f"Fireflies API Error - get_transcripts: {e}")
            return []

    async def get_transcript(self, transcript_id: str) -> Optional[Dict[str, Any]]:
        """Get single transcript with full sentences."""
        try:
            async with self.client as session:
                result = await session.execute(
                    _TRANSCRIPT_QUERY,
                    variable_values={"id": transcript_id}
                )
                return result.get("transcript")
        except Exception as e:
            print(f"Fireflies API Error - get_transcript: {e}")
            return None

    async def get_user_info(self) -> Optional[Dict[str, Any]]:
        """Get current user info."""
        try:
            async with self.client as session:
                result = await session.execute(_USER_QUERY)
                return result.get("user")
        except Exception as e:
            print(f"Fireflies API Error - get_user_info: {e}")
            return None
