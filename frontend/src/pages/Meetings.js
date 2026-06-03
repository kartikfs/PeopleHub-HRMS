import { useState, useEffect, useCallback, useRef } from "react";
import axios from "axios";
import { toast } from "sonner";
import { API } from "@/App";
import {
  Video, Mic, FileText, Users, Clock, Calendar, Search,
  RefreshCw, ChevronDown, X, CheckSquare, Square,
  TrendingUp, MessageSquare, Tag, AlertCircle, Wifi, WifiOff,
  Filter, ExternalLink, ChevronRight, BarChart2, Activity
} from "lucide-react";

// ─── helpers ─────────────────────────────────────────────────────────────────

function getAuthHeaders() {
  const token = localStorage.getItem("admin_token");
  return { Authorization: `Bearer ${token}` };
}

function fmtDuration(mins) {
  if (!mins) return "–";
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function fmtDate(iso) {
  if (!iso) return "–";
  try {
    return new Date(iso).toLocaleDateString("en-IN", {
      day: "numeric", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit"
    });
  } catch { return iso; }
}

function relativeDate(iso) {
  if (!iso) return "";
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const days = Math.floor(diff / 86400000);
    if (days === 0) return "Today";
    if (days === 1) return "Yesterday";
    if (days < 7) return `${days}d ago`;
    if (days < 30) return `${Math.floor(days / 7)}w ago`;
    if (days < 365) return `${Math.floor(days / 30)}mo ago`;
    return `${Math.floor(days / 365)}y ago`;
  } catch { return ""; }
}

// ─── source badge ─────────────────────────────────────────────────────────────

function SourceBadge({ source }) {
  if (source === "attio") return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700">
      <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
      Attio
    </span>
  );
  if (source === "fireflies") return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">
      <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
      Fireflies
    </span>
  );
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-700">
      <span className="w-1.5 h-1.5 rounded-full bg-purple-500" />
      Both
    </span>
  );
}

// ─── sentiment bar ────────────────────────────────────────────────────────────

function SentimentBar({ sentiment }) {
  if (!sentiment) return null;
  const { positive = 0, negative = 0, neutral = 0 } = sentiment;
  return (
    <div className="flex rounded overflow-hidden h-1.5 w-full">
      <div className="bg-green-400" style={{ width: `${positive}%` }} />
      <div className="bg-gray-300" style={{ width: `${neutral}%` }} />
      <div className="bg-red-400" style={{ width: `${negative}%` }} />
    </div>
  );
}

// ─── meeting card ─────────────────────────────────────────────────────────────

function MeetingCard({ meeting, onClick }) {
  return (
    <div
      onClick={() => onClick(meeting)}
      className="bg-white border border-gray-200 rounded-xl p-4 hover:shadow-md hover:border-blue-200 cursor-pointer transition-all duration-150 group"
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-gray-900 text-sm truncate group-hover:text-blue-700">
            {meeting.title || "Untitled Meeting"}
          </h3>
          <p className="text-xs text-gray-500 mt-0.5">{fmtDate(meeting.start_time)}</p>
        </div>
        <SourceBadge source={meeting.source} />
      </div>

      {meeting.summary && (
        <p className="text-xs text-gray-600 line-clamp-2 mb-3">{meeting.summary}</p>
      )}

      <div className="flex items-center gap-3 text-xs text-gray-500 flex-wrap">
        {meeting.duration_minutes && (
          <span className="flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {fmtDuration(meeting.duration_minutes)}
          </span>
        )}
        {meeting.participants?.length > 0 && (
          <span className="flex items-center gap-1">
            <Users className="w-3 h-3" />
            {meeting.participants.length}
          </span>
        )}
        {meeting.has_recording && (
          <span className="flex items-center gap-1 text-blue-600">
            <Mic className="w-3 h-3" />
            Recording
          </span>
        )}
        {meeting.has_video && (
          <span className="flex items-center gap-1 text-purple-600">
            <Video className="w-3 h-3" />
            Video
          </span>
        )}
        {meeting.action_items_count > 0 && (
          <span className="flex items-center gap-1 text-amber-600">
            <CheckSquare className="w-3 h-3" />
            {meeting.action_items_count} actions
          </span>
        )}
        <span className="ml-auto text-gray-400">{relativeDate(meeting.start_time)}</span>
      </div>

      {meeting.sentiment && <div className="mt-2"><SentimentBar sentiment={meeting.sentiment} /></div>}

      {meeting.topics?.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {meeting.topics.slice(0, 3).map((t, i) => (
            <span key={i} className="px-1.5 py-0.5 bg-gray-100 text-gray-600 text-xs rounded">
              {t}
            </span>
          ))}
          {meeting.topics.length > 3 && (
            <span className="px-1.5 py-0.5 bg-gray-100 text-gray-500 text-xs rounded">
              +{meeting.topics.length - 3}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// ─── transcript line ──────────────────────────────────────────────────────────

function TranscriptLine({ line }) {
  const { ai_filters } = line;
  const tags = [];
  if (ai_filters?.task) tags.push({ label: "Task", cls: "bg-amber-100 text-amber-700" });
  if (ai_filters?.pricing) tags.push({ label: "Pricing", cls: "bg-green-100 text-green-700" });
  if (ai_filters?.question) tags.push({ label: "Question", cls: "bg-blue-100 text-blue-700" });
  if (ai_filters?.metric) tags.push({ label: "Metric", cls: "bg-purple-100 text-purple-700" });

  return (
    <div className={`flex gap-3 py-2 px-2 rounded-lg ${tags.length > 0 ? "bg-amber-50/50 border-l-2 border-amber-300" : ""}`}>
      <div className="w-28 shrink-0 text-right">
        <span className="text-xs font-semibold text-blue-700 bg-blue-50 px-1.5 py-0.5 rounded">
          {line.speaker || "Unknown"}
        </span>
        <p className="text-xs text-gray-400 mt-0.5">{Math.floor((line.start_time || 0) / 60)}:{String(Math.floor((line.start_time || 0) % 60)).padStart(2, "0")}</p>
      </div>
      <div className="flex-1">
        <p className="text-sm text-gray-800">{line.text}</p>
        {tags.length > 0 && (
          <div className="flex gap-1 mt-1">
            {tags.map((t, i) => (
              <span key={i} className={`text-xs px-1.5 py-0.5 rounded ${t.cls}`}>{t.label}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── detail drawer ────────────────────────────────────────────────────────────

function MeetingDetailDrawer({ meeting, onClose }) {
  const [transcript, setTranscript] = useState(null);
  const [loadingTranscript, setLoadingTranscript] = useState(false);
  const [activeSection, setActiveSection] = useState("overview");

  useEffect(() => {
    if (!meeting) return;
    setTranscript(null);
    setActiveSection("overview");
  }, [meeting?.id]);

  const fetchTranscript = async () => {
    setLoadingTranscript(true);
    try {
      const { data } = await axios.get(`${API}/meetings/${meeting.id}/transcript`, {
        headers: getAuthHeaders()
      });
      setTranscript(data);
    } catch (e) {
      toast.error("Transcript not available for this meeting");
    } finally {
      setLoadingTranscript(false);
    }
  };

  if (!meeting) return null;

  const summary = meeting.raw_data?.summary || {};
  const analytics = meeting.raw_data?.analytics || {};
  const speakers = analytics.speakers || [];
  const sentiment = meeting.sentiment || analytics.sentiments;
  const actionItems = summary.action_items || [];
  const bulletGist = summary.bullet_gist || [];

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative w-full max-w-2xl bg-white shadow-2xl flex flex-col h-full overflow-hidden">
        {/* Header */}
        <div className="border-b border-gray-200 p-5 flex items-start justify-between">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <SourceBadge source={meeting.source} />
              {meeting.meeting_type && (
                <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full">
                  {meeting.meeting_type}
                </span>
              )}
            </div>
            <h2 className="text-lg font-bold text-gray-900 truncate">{meeting.title || "Untitled Meeting"}</h2>
            <p className="text-sm text-gray-500 mt-0.5">{fmtDate(meeting.start_time)}</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-gray-100 rounded-lg ml-3">
            <X className="w-5 h-5 text-gray-500" />
          </button>
        </div>

        {/* Quick stats */}
        <div className="grid grid-cols-3 gap-px bg-gray-200 border-b border-gray-200">
          {[
            { label: "Duration", value: fmtDuration(meeting.duration_minutes), icon: Clock },
            { label: "Participants", value: meeting.participants?.length || 0, icon: Users },
            { label: "Action Items", value: meeting.action_items_count || 0, icon: CheckSquare },
          ].map(({ label, value, icon: Icon }) => (
            <div key={label} className="bg-white p-3 text-center">
              <Icon className="w-4 h-4 text-gray-400 mx-auto mb-0.5" />
              <p className="text-lg font-bold text-gray-900">{value}</p>
              <p className="text-xs text-gray-500">{label}</p>
            </div>
          ))}
        </div>

        {/* Tab bar */}
        <div className="flex border-b border-gray-200 px-4 gap-1">
          {["overview", "transcript", ...(speakers.length > 0 ? ["analytics"] : [])].map(tab => (
            <button
              key={tab}
              onClick={() => { setActiveSection(tab); if (tab === "transcript" && !transcript) fetchTranscript(); }}
              className={`px-3 py-2.5 text-sm font-medium capitalize border-b-2 -mb-px transition-colors ${
                activeSection === tab
                  ? "border-blue-600 text-blue-700"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">

          {/* ── Overview ── */}
          {activeSection === "overview" && (
            <>
              {meeting.summary && (
                <div>
                  <h4 className="text-sm font-semibold text-gray-700 mb-2">Summary</h4>
                  <p className="text-sm text-gray-600 leading-relaxed">{meeting.summary}</p>
                </div>
              )}

              {bulletGist.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold text-gray-700 mb-2">Key Points</h4>
                  <ul className="space-y-1">
                    {bulletGist.map((b, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-gray-600">
                        <ChevronRight className="w-3.5 h-3.5 text-blue-400 mt-0.5 shrink-0" />
                        {b}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {actionItems.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold text-gray-700 mb-2">Action Items</h4>
                  <ul className="space-y-1.5">
                    {actionItems.map((item, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-gray-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                        <CheckSquare className="w-4 h-4 text-amber-600 mt-0.5 shrink-0" />
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {meeting.topics?.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold text-gray-700 mb-2">Topics</h4>
                  <div className="flex flex-wrap gap-2">
                    {meeting.topics.map((t, i) => (
                      <span key={i} className="px-2 py-1 bg-blue-50 text-blue-700 text-xs rounded-full">{t}</span>
                    ))}
                  </div>
                </div>
              )}

              {meeting.participants?.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold text-gray-700 mb-2">Participants</h4>
                  <div className="space-y-1.5">
                    {meeting.participants.map((p, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-400 to-indigo-500 flex items-center justify-center text-white text-xs font-semibold shrink-0">
                          {(p.name || p.email || "?").charAt(0).toUpperCase()}
                        </div>
                        <div>
                          <p className="text-sm font-medium text-gray-800">{p.name || "Unknown"}</p>
                          {p.email && <p className="text-xs text-gray-500">{p.email}</p>}
                        </div>
                        {p.role && <span className="ml-auto text-xs text-gray-400">{p.role}</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {sentiment && (
                <div>
                  <h4 className="text-sm font-semibold text-gray-700 mb-2">Sentiment</h4>
                  <div className="flex gap-4 text-sm mb-2">
                    <span className="text-green-600">😊 {sentiment.positive?.toFixed(0)}% positive</span>
                    <span className="text-gray-500">😐 {sentiment.neutral?.toFixed(0)}% neutral</span>
                    <span className="text-red-600">😟 {sentiment.negative?.toFixed(0)}% negative</span>
                  </div>
                  <div className="flex rounded overflow-hidden h-2.5">
                    <div className="bg-green-400 transition-all" style={{ width: `${sentiment.positive || 0}%` }} />
                    <div className="bg-gray-300 transition-all" style={{ width: `${sentiment.neutral || 0}%` }} />
                    <div className="bg-red-400 transition-all" style={{ width: `${sentiment.negative || 0}%` }} />
                  </div>
                </div>
              )}

              {(meeting.audio_url || meeting.video_url) && (
                <div>
                  <h4 className="text-sm font-semibold text-gray-700 mb-2">Recording</h4>
                  <div className="flex gap-2">
                    {meeting.audio_url && (
                      <a href={meeting.audio_url} target="_blank" rel="noopener noreferrer"
                        className="flex items-center gap-2 px-3 py-2 bg-blue-50 text-blue-700 text-sm rounded-lg hover:bg-blue-100">
                        <Mic className="w-4 h-4" /> Audio <ExternalLink className="w-3 h-3" />
                      </a>
                    )}
                    {meeting.video_url && (
                      <a href={meeting.video_url} target="_blank" rel="noopener noreferrer"
                        className="flex items-center gap-2 px-3 py-2 bg-purple-50 text-purple-700 text-sm rounded-lg hover:bg-purple-100">
                        <Video className="w-4 h-4" /> Video <ExternalLink className="w-3 h-3" />
                      </a>
                    )}
                  </div>
                </div>
              )}
            </>
          )}

          {/* ── Transcript ── */}
          {activeSection === "transcript" && (
            <div>
              {loadingTranscript && (
                <div className="text-center py-10">
                  <RefreshCw className="w-6 h-6 animate-spin text-blue-600 mx-auto mb-2" />
                  <p className="text-sm text-gray-500">Loading transcript…</p>
                </div>
              )}
              {!loadingTranscript && !transcript && (
                <div className="text-center py-10">
                  <FileText className="w-8 h-8 text-gray-300 mx-auto mb-3" />
                  <p className="text-sm text-gray-500 mb-3">Transcript not loaded</p>
                  <button onClick={fetchTranscript}
                    className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">
                    Load Transcript
                  </button>
                </div>
              )}
              {transcript && transcript.lines?.length > 0 && (
                <div className="space-y-1">
                  {transcript.lines.map((line, i) => <TranscriptLine key={i} line={line} />)}
                </div>
              )}
              {transcript && transcript.lines?.length === 0 && (
                <p className="text-center text-sm text-gray-500 py-10">No transcript lines available.</p>
              )}
            </div>
          )}

          {/* ── Analytics ── */}
          {activeSection === "analytics" && speakers.length > 0 && (
            <div className="space-y-5">
              <div>
                <h4 className="text-sm font-semibold text-gray-700 mb-3">Speaker Breakdown</h4>
                <div className="space-y-3">
                  {speakers.map((spk, i) => (
                    <div key={i}>
                      <div className="flex items-center justify-between text-sm mb-1">
                        <span className="font-medium text-gray-800">{spk.name}</span>
                        <span className="text-gray-500">{spk.talk_time?.toFixed(0) || 0}%</span>
                      </div>
                      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-blue-400 to-indigo-500 rounded-full"
                          style={{ width: `${Math.min(spk.talk_time || 0, 100)}%` }}
                        />
                      </div>
                      <div className="flex gap-4 text-xs text-gray-500 mt-0.5">
                        {spk.words_per_minute && <span>{spk.words_per_minute} WPM</span>}
                        {spk.filler_words != null && <span>{spk.filler_words} filler words</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              {sentiment && (
                <div>
                  <h4 className="text-sm font-semibold text-gray-700 mb-3">Meeting Sentiment</h4>
                  <div className="flex gap-4 text-sm mb-2">
                    <span className="text-green-600">😊 {sentiment.positive?.toFixed(0)}%</span>
                    <span className="text-gray-500">😐 {sentiment.neutral?.toFixed(0)}%</span>
                    <span className="text-red-600">😟 {sentiment.negative?.toFixed(0)}%</span>
                  </div>
                  <div className="flex rounded-full overflow-hidden h-4">
                    <div className="bg-green-400" style={{ width: `${sentiment.positive || 0}%` }} />
                    <div className="bg-gray-200" style={{ width: `${sentiment.neutral || 0}%` }} />
                    <div className="bg-red-400" style={{ width: `${sentiment.negative || 0}%` }} />
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── filters bar ──────────────────────────────────────────────────────────────

function FiltersBar({ filters, onChange }) {
  return (
    <div className="flex flex-wrap gap-2 items-center">
      <div className="relative">
        <Calendar className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
        <input type="date" value={filters.start_date || ""} onChange={e => onChange("start_date", e.target.value)}
          className="pl-8 pr-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </div>
      <span className="text-gray-400 text-sm">to</span>
      <input type="date" value={filters.end_date || ""} onChange={e => onChange("end_date", e.target.value)}
        className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />

      {/* presets */}
      {[7, 30, 90].map(d => (
        <button key={d} onClick={() => {
          const now = new Date();
          const from = new Date(now - d * 86400000);
          onChange("start_date", from.toISOString().split("T")[0]);
          onChange("end_date", now.toISOString().split("T")[0]);
        }} className="px-2.5 py-1.5 text-xs font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 rounded-lg">
          {d}d
        </button>
      ))}

      <select value={filters.sort_by || "start_time"}
        onChange={e => onChange("sort_by", e.target.value)}
        className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
        <option value="start_time">Sort: Date</option>
        <option value="duration_minutes">Sort: Duration</option>
      </select>

      {/* active filters clear */}
      {(filters.start_date || filters.end_date || filters.keyword || filters.participant_email) && (
        <button onClick={() => onChange("_clear", true)}
          className="flex items-center gap-1 px-2.5 py-1.5 text-xs text-red-600 bg-red-50 hover:bg-red-100 rounded-lg">
          <X className="w-3 h-3" /> Clear
        </button>
      )}
    </div>
  );
}

// ─── sync status bar ──────────────────────────────────────────────────────────

function SyncStatusBar({ status, onSync }) {
  const [syncing, setSyncing] = useState(false);

  const handleSync = async () => {
    setSyncing(true);
    try {
      await axios.post(`${API}/meetings/sync`, null, {
        headers: getAuthHeaders(), params: { lookback_days: 90 }
      });
      toast.success("Sync started. Check back in a moment.");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Sync failed");
    } finally {
      setSyncing(false);
      onSync();
    }
  };

  return (
    <div className="flex items-center gap-3 text-xs text-gray-500 bg-gray-50 border border-gray-200 rounded-lg px-3 py-2">
      {status?.is_syncing ? (
        <><RefreshCw className="w-3.5 h-3.5 animate-spin text-blue-600" /><span className="text-blue-600">Syncing…</span></>
      ) : (
        <><Activity className="w-3.5 h-3.5 text-green-500" /><span>{status?.total_meetings || 0} meetings cached</span></>
      )}
      {status?.last_sync_attio && (
        <span>Last sync: {relativeDate(status.last_sync_attio)}</span>
      )}
      <span className="text-blue-500 font-medium">{status?.attio_count || 0} Attio · {status?.fireflies_count || 0} Fireflies</span>
      <button onClick={handleSync} disabled={syncing || status?.is_syncing}
        className="ml-auto flex items-center gap-1 px-2.5 py-1 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
        <RefreshCw className={`w-3 h-3 ${syncing ? "animate-spin" : ""}`} />
        Sync Now
      </button>
    </div>
  );
}

// ─── connection test panel ────────────────────────────────────────────────────

function ConnectionTestPanel() {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const test = async () => {
    setLoading(true);
    try {
      const { data } = await axios.get(`${API}/meetings/connection-test`, {
        headers: getAuthHeaders()
      });
      setResult(data);
    } catch (e) {
      setResult({ error: e.response?.data?.detail || e.message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
          <Wifi className="w-4 h-4 text-blue-600" /> API Connection Status
        </h3>
        <button onClick={test} disabled={loading}
          className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
          {loading ? "Testing…" : "Test Connections"}
        </button>
      </div>
      {result && (
        <div className="space-y-2 text-xs">
          {["attio", "fireflies"].map(src => {
            const r = result[src] || {};
            const ok = r.status === "connected";
            return (
              <div key={src} className={`flex items-start gap-2 p-2 rounded-lg ${ok ? "bg-green-50 border border-green-200" : "bg-red-50 border border-red-200"}`}>
                {ok ? <Wifi className="w-4 h-4 text-green-600 shrink-0 mt-0.5" /> : <WifiOff className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />}
                <div>
                  <span className={`font-semibold capitalize ${ok ? "text-green-700" : "text-red-700"}`}>{src}</span>
                  {ok && r.user && <p className="text-gray-500 mt-0.5">User: {r.user.name} ({r.user.email}) · {r.user.workspace_name}</p>}
                  {!ok && r.error && <p className="text-red-600 mt-0.5 break-all">{r.error}</p>}
                  {ok && r.response_keys && <p className="text-gray-500 mt-0.5">Response keys: {r.response_keys.join(", ")}</p>}
                  {ok && r.sample && <p className="text-gray-400 mt-0.5 truncate">{r.sample.substring(0, 200)}</p>}
                </div>
              </div>
            );
          })}
          {result.error && <p className="text-red-600">{result.error}</p>}
        </div>
      )}
    </div>
  );
}

// ─── main page ────────────────────────────────────────────────────────────────

export default function Meetings() {
  const [activeTab, setActiveTab] = useState("all");
  const [meetings, setMeetings] = useState([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const LIMIT = 30;

  const [syncStatus, setSyncStatus] = useState(null);
  const [selectedMeeting, setSelectedMeeting] = useState(null);
  const [showConnectionTest, setShowConnectionTest] = useState(false);

  const [filters, setFilters] = useState({
    start_date: "", end_date: "", keyword: "", participant_email: "",
    has_recording: false, has_action_items: false, sort_by: "start_time", sort_order: "desc"
  });
  const [searchQuery, setSearchQuery] = useState("");

  const endpointMap = {
    all: "/meetings",
    attio: "/meetings/attio",
    fireflies: "/meetings/fireflies",
    "action-items": "/meetings/action-items"
  };

  const fetchSyncStatus = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/meetings/sync-status`, { headers: getAuthHeaders() });
      setSyncStatus(data);
    } catch {}
  }, []);

  const fetchMeetings = useCallback(async (resetOffset = true) => {
    setLoading(true);
    const currentOffset = resetOffset ? 0 : offset;
    if (resetOffset) setOffset(0);

    try {
      if (activeTab === "action-items") {
        const { data } = await axios.get(`${API}/meetings/action-items`, {
          headers: getAuthHeaders(),
          params: { limit: LIMIT, offset: currentOffset }
        });
        setMeetings(data.action_items || []);
        setTotal(data.total || 0);
        return;
      }

      const params = {
        limit: LIMIT, offset: currentOffset,
        sort_by: filters.sort_by, sort_order: filters.sort_order
      };
      if (filters.start_date) params.start_date = filters.start_date;
      if (filters.end_date) params.end_date = filters.end_date;
      if (filters.keyword) params.keyword = filters.keyword;
      if (filters.participant_email) params.participant_email = filters.participant_email;
      if (filters.has_recording) params.has_recording = true;
      if (filters.has_action_items) params.has_action_items = true;

      const endpoint = endpointMap[activeTab] || "/meetings";
      const { data } = await axios.get(`${API}${endpoint}`, {
        headers: getAuthHeaders(), params
      });
      setMeetings(data.meetings || []);
      setTotal(data.total || 0);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to load meetings");
    } finally {
      setLoading(false);
    }
  }, [activeTab, filters, offset]);

  useEffect(() => { fetchSyncStatus(); }, []);
  useEffect(() => { fetchMeetings(true); }, [activeTab, filters]);

  const handleFilterChange = (key, value) => {
    if (key === "_clear") {
      setFilters(f => ({ ...f, start_date: "", end_date: "", keyword: "", participant_email: "" }));
    } else {
      setFilters(f => ({ ...f, [key]: value }));
    }
  };

  const handleSearch = async (q) => {
    if (!q.trim()) { fetchMeetings(true); return; }
    setLoading(true);
    try {
      const { data } = await axios.get(`${API}/meetings/search`, {
        headers: getAuthHeaders(), params: { q, limit: 30 }
      });
      setMeetings(data.results || []);
      setTotal(data.count || 0);
    } catch (e) {
      toast.error("Search failed");
    } finally {
      setLoading(false);
    }
  };

  const tabs = [
    { key: "all", label: "All Meetings", icon: Calendar },
    { key: "attio", label: "Attio", icon: BarChart2 },
    { key: "fireflies", label: "Fireflies", icon: Activity },
    { key: "action-items", label: "Action Items", icon: CheckSquare },
  ];

  return (
    <div className="space-y-5">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Meetings & Recordings</h1>
          <p className="text-sm text-gray-500 mt-0.5">Unified hub from Attio CRM and Fireflies AI</p>
        </div>
        <button
          onClick={() => setShowConnectionTest(!showConnectionTest)}
          className="text-xs px-3 py-2 border border-gray-200 rounded-lg text-gray-600 hover:bg-gray-50 flex items-center gap-1.5"
        >
          <Wifi className="w-3.5 h-3.5" />
          {showConnectionTest ? "Hide" : "Test API"}
        </button>
      </div>

      {/* Connection test (collapsible) */}
      {showConnectionTest && <ConnectionTestPanel />}

      {/* Sync status bar */}
      <SyncStatusBar status={syncStatus} onSync={fetchSyncStatus} />

      {/* Global search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
        <input
          type="text"
          placeholder="Search meetings, participants, topics… (Cmd+K)"
          value={searchQuery}
          onChange={e => { setSearchQuery(e.target.value); if (!e.target.value) fetchMeetings(true); }}
          onKeyDown={e => e.key === "Enter" && handleSearch(searchQuery)}
          className="w-full pl-9 pr-4 py-2.5 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white shadow-sm"
        />
        {searchQuery && (
          <button onClick={() => { setSearchQuery(""); fetchMeetings(true); }}
            className="absolute right-3 top-1/2 -translate-y-1/2">
            <X className="w-4 h-4 text-gray-400 hover:text-gray-600" />
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200">
        {tabs.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
              activeTab === key
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Filters (not for action-items tab) */}
      {activeTab !== "action-items" && (
        <div className="space-y-2">
          <FiltersBar filters={filters} onChange={handleFilterChange} />
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="Participant email…"
              value={filters.participant_email}
              onChange={e => handleFilterChange("participant_email", e.target.value)}
              className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 w-52"
            />
            <label className="flex items-center gap-1.5 text-sm text-gray-600 cursor-pointer">
              <input type="checkbox" checked={filters.has_recording}
                onChange={e => handleFilterChange("has_recording", e.target.checked)}
                className="rounded" />
              Has recording
            </label>
            <label className="flex items-center gap-1.5 text-sm text-gray-600 cursor-pointer">
              <input type="checkbox" checked={filters.has_action_items}
                onChange={e => handleFilterChange("has_action_items", e.target.checked)}
                className="rounded" />
              Has action items
            </label>
          </div>
        </div>
      )}

      {/* Results count */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">
          {loading ? "Loading…" : `${total} result${total !== 1 ? "s" : ""}`}
        </p>
        {total > LIMIT && (
          <div className="flex gap-2">
            <button disabled={offset === 0}
              onClick={() => { setOffset(Math.max(0, offset - LIMIT)); fetchMeetings(false); }}
              className="px-3 py-1.5 text-xs border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50">
              ← Prev
            </button>
            <span className="px-3 py-1.5 text-xs text-gray-500">
              {Math.floor(offset / LIMIT) + 1} / {Math.ceil(total / LIMIT)}
            </span>
            <button disabled={offset + LIMIT >= total}
              onClick={() => { setOffset(offset + LIMIT); fetchMeetings(false); }}
              className="px-3 py-1.5 text-xs border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50">
              Next →
            </button>
          </div>
        )}
      </div>

      {/* Content */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="bg-white border border-gray-200 rounded-xl p-4 animate-pulse">
              <div className="h-4 bg-gray-200 rounded w-3/4 mb-2" />
              <div className="h-3 bg-gray-100 rounded w-1/2 mb-3" />
              <div className="h-3 bg-gray-100 rounded w-full mb-1" />
              <div className="h-3 bg-gray-100 rounded w-5/6" />
            </div>
          ))}
        </div>
      ) : activeTab === "action-items" ? (
        meetings.length === 0 ? (
          <div className="text-center py-16">
            <CheckSquare className="w-10 h-10 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-500">No action items found. Sync meetings to extract them.</p>
          </div>
        ) : (
          <div className="bg-white border border-gray-200 rounded-xl divide-y divide-gray-100">
            {meetings.map((item, i) => (
              <ActionItemRow key={item.id || i} item={item} onUpdate={fetchMeetings} />
            ))}
          </div>
        )
      ) : meetings.length === 0 ? (
        <div className="text-center py-16">
          <Calendar className="w-10 h-10 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500 mb-2">No meetings found.</p>
          <p className="text-sm text-gray-400">
            Use the "Sync Now" button to fetch meetings from Attio and Fireflies.
            <br />Click "Test API" above to verify your API keys are working.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {meetings.map((m, i) => (
            <MeetingCard key={m.id || i} meeting={m} onClick={setSelectedMeeting} />
          ))}
        </div>
      )}

      {/* Detail drawer */}
      {selectedMeeting && (
        <MeetingDetailDrawer meeting={selectedMeeting} onClose={() => setSelectedMeeting(null)} />
      )}
    </div>
  );
}

// ─── action item row ──────────────────────────────────────────────────────────

function ActionItemRow({ item, onUpdate }) {
  const [updating, setUpdating] = useState(false);

  const toggle = async () => {
    setUpdating(true);
    const newStatus = item.status === "open" ? "done" : "open";
    try {
      await axios.patch(`${API}/meetings/action-items/${item.id}`, null, {
        headers: getAuthHeaders(), params: { status: newStatus }
      });
      toast.success(`Marked as ${newStatus}`);
      onUpdate();
    } catch {
      toast.error("Update failed");
    } finally {
      setUpdating(false);
    }
  };

  return (
    <div className="flex items-start gap-3 p-4 hover:bg-gray-50">
      <button onClick={toggle} disabled={updating} className="shrink-0 mt-0.5">
        {item.status === "done"
          ? <CheckSquare className="w-5 h-5 text-green-600" />
          : <Square className="w-5 h-5 text-gray-400" />}
      </button>
      <div className="flex-1 min-w-0">
        <p className={`text-sm ${item.status === "done" ? "line-through text-gray-400" : "text-gray-800"}`}>
          {item.text}
        </p>
        <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
          <span className="flex items-center gap-1"><MessageSquare className="w-3 h-3" />{item.meeting_title || "–"}</span>
          {item.assigned_to && <span>→ {item.assigned_to_name || item.assigned_to}</span>}
          {item.created_at && <span>{relativeDate(item.created_at)}</span>}
        </div>
      </div>
      <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${
        item.status === "done" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"
      }`}>
        {item.status}
      </span>
    </div>
  );
}
