"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { api, mediaUrl } from "../lib/api";
import type {
  ChatSession,
  IdentityRecord,
  ProStatus,
  SubjectRecord,
  VideoAnalysis,
  VideoRecord,
} from "../lib/types";
import { SparkIcon, XIcon } from "./Icons";

type ProIntelligenceWorkspaceProps = {
  video: VideoRecord | null;
  onClose: () => void;
  onChooseSource: () => void;
  onEnhance: () => void;
  onSelectAnalysis: (analysis: VideoAnalysis) => void;
  onError: (message: string) => void;
};

const TERMINAL = new Set(["ready", "failed", "cancelled"]);

export function ProIntelligenceWorkspace({
  video,
  onClose,
  onChooseSource,
  onEnhance,
  onSelectAnalysis,
  onError,
}: ProIntelligenceWorkspaceProps) {
  const [status, setStatus] = useState<ProStatus | null>(null);
  const [analysis, setAnalysis] = useState<VideoAnalysis | null>(null);
  const [analyses, setAnalyses] = useState<VideoAnalysis[]>([]);
  const [identities, setIdentities] = useState<IdentityRecord[]>([]);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [tab, setTab] = useState<"ask" | "subjects" | "transcript">("ask");
  const [currentTime, setCurrentTime] = useState(0);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [names, setNames] = useState<Record<string, string>>({});
  const [transcriptQuery, setTranscriptQuery] = useState("");
  const [transcriptionEngine, setTranscriptionEngine] = useState<"whisper_multilingual" | "tara_hinglish">("whisper_multilingual");
  const [transcriptLanguage, setTranscriptLanguage] = useState("");
  const [trackObjects, setTrackObjects] = useState(true);
  const player = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    void Promise.all([api.proStatus(), api.analyses(), api.identities()])
      .then(([nextStatus, nextAnalyses, nextIdentities]) => {
        setStatus(nextStatus);
        setAnalyses(nextAnalyses);
        setIdentities(nextIdentities);
      })
      .catch((error) => onError(error instanceof Error ? error.message : "Pro could not load."));
  }, [onError]);

  useEffect(() => {
    if (status?.state !== "installing") return;
    const timer = window.setInterval(() => {
      void api.proStatus().then(setStatus).catch(() => undefined);
    }, 900);
    return () => window.clearInterval(timer);
  }, [status?.state]);

  useEffect(() => {
    if (!video) return;
    void api.videoAnalysis(video.id).then((record) => {
      setAnalysis(record);
      if (record?.status === "ready") {
        void api.chatHistory(record.id).then(setSession).catch(() => undefined);
      } else {
        setSession(null);
      }
    }).catch((error) => onError(error instanceof Error ? error.message : "Analysis could not load."));
  }, [onError, video]);

  useEffect(() => {
    if (!analysis || TERMINAL.has(analysis.status)) return;
    const timer = window.setInterval(() => {
      void api.analysis(analysis.id).then((next) => {
        setAnalysis(next);
        setAnalyses((current) => [next, ...current.filter((item) => item.id !== next.id)]);
      }).catch(() => undefined);
    }, 800);
    return () => window.clearInterval(timer);
  }, [analysis]);

  const activeSubjects = useMemo(() => {
    if (!analysis) return [];
    return analysis.subjects.flatMap((subject) => {
      const appearance = subject.appearances.find(
        (item) => currentTime >= item.start && currentTime <= item.end,
      );
      return appearance ? [{ subject, appearance }] : [];
    });
  }, [analysis, currentTime]);

  const transcript = useMemo(() => {
    const query = transcriptQuery.trim().toLowerCase();
    if (!analysis || !query) return analysis?.transcript_segments ?? [];
    return analysis.transcript_segments.filter((segment) => segment.text.toLowerCase().includes(query));
  }, [analysis, transcriptQuery]);

  const install = async () => {
    try {
      setStatus(await api.installPro());
    } catch (error) {
      onError(error instanceof Error ? error.message : "Pro setup could not start.");
    }
  };

  const startAnalysis = async () => {
    if (!video) return;
    try {
      const record = await api.createAnalysis({
        video_id: video.id,
        transcribe: true,
        track_people: true,
        track_objects: trackObjects,
        transcript_language: transcriptionEngine === "whisper_multilingual" ? transcriptLanguage || undefined : undefined,
        transcription_engine: transcriptionEngine,
      });
      setAnalysis(record);
      setAnalyses((current) => [record, ...current.filter((item) => item.id !== record.id)]);
    } catch (error) {
      onError(error instanceof Error ? error.message : "Video analysis could not start.");
    }
  };

  const seek = (seconds: number) => {
    if (!player.current) return;
    player.current.currentTime = seconds;
    player.current.play().catch(() => undefined);
  };

  const ask = async (event: FormEvent) => {
    event.preventDefault();
    if (!analysis || !question.trim() || asking) return;
    const value = question.trim();
    setQuestion("");
    setAsking(true);
    const optimistic = {
      id: `pending-${Date.now()}`,
      role: "user" as const,
      content: value,
      citations: [],
      tool_calls: [],
      created_at: new Date().toISOString(),
    };
    setSession((current) => ({
      id: current?.id ?? "pending",
      analysis_id: analysis.id,
      messages: [...(current?.messages ?? []), optimistic],
      created_at: current?.created_at ?? new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }));
    try {
      const response = await api.askVideo(analysis.id, {
        question: value,
        session_id: session?.id === "pending" ? undefined : session?.id,
        current_time: currentTime,
      });
      setSession(response.session);
    } catch (error) {
      onError(error instanceof Error ? error.message : "The local video assistant could not answer.");
      setSession((current) => current ? { ...current, messages: current.messages.filter((item) => item.id !== optimistic.id) } : null);
      setQuestion(value);
    } finally {
      setAsking(false);
    }
  };

  const tag = async (subject: SubjectRecord, identityId?: string) => {
    if (!analysis) return;
    const name = names[subject.id]?.trim();
    if (!identityId && !name) return;
    try {
      const updated = await api.tagSubject(
        analysis.id,
        subject.id,
        identityId ? { identity_id: identityId } : { name },
      );
      setAnalysis(updated);
      setNames((current) => ({ ...current, [subject.id]: "" }));
      setIdentities(await api.identities());
    } catch (error) {
      onError(error instanceof Error ? error.message : "This subject could not be tagged.");
    }
  };

  if (!status) {
    return <main className="pro-shell pro-loading">Opening the local intelligence workspace…</main>;
  }

  if (status.state !== "ready") {
    return (
      <main className="pro-shell pro-onboarding">
        <header className="pro-header">
          <div><span className="pro-kicker"><SparkIcon size={15} /> Optional local intelligence</span><h1>Understand every frame.</h1></div>
          <button className="icon-button" onClick={onClose} aria-label="Close Pro"><XIcon size={20} /></button>
        </header>
        <section className="pro-setup-card">
          <div className="pro-orbit"><SparkIcon size={34} /></div>
          <span className="pro-badge">PRO · ON DEVICE</span>
          <h2>Subtitles, people tracking, and video chat</h2>
          <p>Download one private intelligence bundle when you want it. Videos, identities, transcripts, and questions stay on this computer.</p>
          <div className="pro-model-grid">
            <ModelLine label="Video reasoning" value={status.qwen_model.includes("2B") ? "Qwen3-VL 2B · portable" : "Qwen3-VL 4B · 4-bit"} detail={status.qwen_model} />
            <ModelLine label="Audio transcription" value="Whisper multilingual + Tara Hinglish" detail={`${status.whisper_model} · ${status.hinglish_model}`} />
            <ModelLine label="Subject tracking" value={status.detector_model} detail="Modern object detection with persistent local tracks" />
          </div>
          {status.state === "installing" ? (
            <div className="pro-install-progress">
              <div><strong>{status.stage}</strong><span>{Math.round(status.progress)}%</span></div>
              <i><b style={{ width: `${status.progress}%` }} /></i>
              <p>{status.detail}</p>
            </div>
          ) : (
            <>
              {status.error && <p className="pro-setup-error">{status.error}</p>}
              <button className="pro-primary" onClick={() => void install()}>
                {status.state === "error" ? "Try setup again" : `Download Pro · ${formatBytes(status.estimated_download_bytes)}`}
              </button>
              <small>Nothing is downloaded until you choose this button. Partial downloads resume safely.</small>
            </>
          )}
          <p className="pro-platform">Optimized for {status.platform}</p>
        </section>
      </main>
    );
  }

  if (!video) {
    return (
      <main className="pro-shell">
        <header className="pro-header">
          <div><span className="pro-kicker"><SparkIcon size={15} /> Pro Intelligence</span><h1>Your private video memory</h1></div>
          <button className="icon-button" onClick={onClose} aria-label="Close Pro"><XIcon size={20} /></button>
        </header>
        <section className="pro-library">
          <div className="pro-empty-source"><h2>Choose a video to understand</h2><p>Upload one, bring in a permitted YouTube source, or reopen an analyzed video below.</p><button className="pro-primary" onClick={onChooseSource}>Choose a source</button></div>
          {analyses.length > 0 && <><h3>Persistent analyses</h3><div className="pro-analysis-list">{analyses.map((item) => <button key={item.id} onClick={() => onSelectAnalysis(item)}><span>{item.status === "ready" ? "Ready" : item.stage}</span><strong>{item.video_name ?? item.video_id.slice(0, 12)}</strong><small>{item.transcript_segments.length} transcript parts · {item.subjects.length} subjects</small></button>)}</div></>}
        </section>
      </main>
    );
  }

  return (
    <main className="pro-shell pro-workspace">
      <header className="pro-header">
        <div><span className="pro-kicker"><SparkIcon size={15} /> Pro Intelligence</span><h1>{video.title ?? video.original_name}</h1></div>
        <div className="pro-header-actions"><button className="pro-handoff" onClick={onEnhance}>Enhance this video</button><button onClick={() => void api.unloadPro()}>Release AI memory</button><button className="icon-button" onClick={onClose} aria-label="Close Pro"><XIcon size={20} /></button></div>
      </header>

      {!analysis ? (
        <section className="pro-start-card"><div className="pro-orbit"><SparkIcon size={30} /></div><h2>Make this video searchable</h2><p>Choose the local models used for speech and visual indexing. Your original remains untouched.</p><div className="analysis-recipe"><label>Transcription model<select value={transcriptionEngine} onChange={(event) => setTranscriptionEngine(event.target.value as typeof transcriptionEngine)}><option value="whisper_multilingual">Whisper large-v3 turbo · multilingual</option><option value="tara_hinglish">Tara · Hindi + English code-switching</option></select></label>{transcriptionEngine === "whisper_multilingual" && <label>Spoken language<select value={transcriptLanguage} onChange={(event) => setTranscriptLanguage(event.target.value)}><option value="">Auto-detect</option><option value="en">English</option><option value="hi">Hindi</option><option value="es">Spanish</option><option value="fr">French</option><option value="de">German</option><option value="ja">Japanese</option><option value="ko">Korean</option><option value="zh">Chinese</option><option value="ar">Arabic</option><option value="pt">Portuguese</option><option value="ru">Russian</option></select></label>}<label className="analysis-check"><input type="checkbox" checked={trackObjects} onChange={(event) => setTrackObjects(event.target.checked)} /> Detect and track common objects as well as people</label></div><button className="pro-primary" onClick={() => void startAnalysis()}>Analyze this video</button></section>
      ) : analysis.status !== "ready" ? (
        <section className="pro-start-card"><span className="pro-badge">ANALYZING LOCALLY</span><h2>{analysis.stage}</h2><div className="pro-install-progress"><div><strong>{video.original_name}</strong><span>{Math.round(analysis.progress)}%</span></div><i><b style={{ width: `${analysis.progress}%` }} /></i></div>{analysis.error && <p className="pro-setup-error">{analysis.error}</p>}{!TERMINAL.has(analysis.status) && <button className="pro-secondary danger" onClick={() => void api.cancelAnalysis(analysis.id).then(setAnalysis)}>Cancel analysis</button>}{["failed", "cancelled"].includes(analysis.status) && <button className="pro-primary" onClick={() => void startAnalysis()}>Analyze again</button>}</section>
      ) : (
        <div className="pro-studio">
          <section className="pro-player-column">
            {analysis.warnings.length > 0 && <div className="analysis-warning">{analysis.warnings.join(" · ")}</div>}
            <div className="pro-video-stage">
              <video ref={player} controls crossOrigin="anonymous" src={mediaUrl(video.playback_url)} onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}>
                <track default kind="captions" srcLang={analysis.transcript_language ?? "en"} label="OhIc captions" src={mediaUrl(analysis.subtitle_url)} />
              </video>
              <div className="subject-overlay" aria-hidden>{activeSubjects.map(({ subject, appearance }) => <div key={subject.id} className="subject-box" style={{ left: `${appearance.box.x * 100}%`, top: `${appearance.box.y * 100}%`, width: `${appearance.box.width * 100}%`, height: `${appearance.box.height * 100}%`, borderColor: subject.color }}><span style={{ background: subject.color }}>{subject.label}</span></div>)}</div>
            </div>
            <IntelligenceTimeline analysis={analysis} duration={video.metadata.duration} currentTime={currentTime} onSeek={seek} />
          </section>
          <aside className="pro-dock">
            <div className="pro-tabs">{(["ask", "subjects", "transcript"] as const).map((value) => <button key={value} className={tab === value ? "active" : ""} onClick={() => setTab(value)}>{value === "ask" ? "Ask" : value === "subjects" ? `Subjects ${analysis.subjects.length}` : "Transcript"}</button>)}</div>
            {tab === "ask" && <AskPanel session={session} question={question} asking={asking} onQuestion={setQuestion} onSubmit={ask} onSeek={seek} />}
            {tab === "subjects" && <SubjectsPanel subjects={analysis.subjects} identities={identities} names={names} onName={(id, value) => setNames((current) => ({ ...current, [id]: value }))} onTag={tag} onSeek={seek} />}
            {tab === "transcript" && <TranscriptPanel segments={transcript} query={transcriptQuery} onQuery={setTranscriptQuery} onSeek={seek} />}
          </aside>
        </div>
      )}
    </main>
  );
}

function ModelLine({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>;
}

function AskPanel({ session, question, asking, onQuestion, onSubmit, onSeek }: { session: ChatSession | null; question: string; asking: boolean; onQuestion: (value: string) => void; onSubmit: (event: FormEvent) => void; onSeek: (time: number) => void }) {
  return <div className="pro-panel ask-panel"><div className="chat-scroll">{!session?.messages.length && <div className="chat-welcome"><SparkIcon size={24} /><h3>Ask this video</h3><p>Try “What is explained at 12:30?”, “When does Alex appear?”, or “Summarize the opening.” Every answer searches both transcript and video evidence and remembers this conversation.</p></div>}{session?.messages.map((message) => <article key={message.id} className={`chat-message ${message.role}`}><span>{message.role === "assistant" ? "OhIc" : "You"}</span><p>{message.content}</p>{message.citations.length > 0 && <div className="citation-row">{message.citations.map((citation, index) => <button key={`${citation.kind}-${citation.start}-${index}`} onClick={() => onSeek(citation.start)}>{citation.label}</button>)}</div>}{message.tool_calls.length > 0 && <details><summary>{message.tool_calls.length} local tools used</summary>{message.tool_calls.map((tool) => <small key={tool.name}>{tool.name} · {tool.result_count} results</small>)}</details>}</article>)}{asking && <div className="chat-thinking"><i /><i /><i /> Inspecting transcript and video evidence</div>}</div><form className="chat-composer" onSubmit={onSubmit}><textarea value={question} onChange={(event) => onQuestion(event.target.value)} placeholder="Ask about a moment, person, or idea…" rows={3} /><button className="pro-primary" disabled={!question.trim() || asking}>Ask locally</button></form></div>;
}

function SubjectsPanel({ subjects, identities, names, onName, onTag, onSeek }: { subjects: SubjectRecord[]; identities: IdentityRecord[]; names: Record<string, string>; onName: (id: string, value: string) => void; onTag: (subject: SubjectRecord, identityId?: string) => void; onSeek: (time: number) => void }) {
  /* eslint-disable-next-line @next/next/no-img-element -- image is served by the private local API */
  return <div className="pro-panel subject-panel">{subjects.length === 0 ? <div className="panel-empty"><h3>No confident subject tracks</h3><p>Low light, animation, or distant subjects can limit automatic detection. The transcript and video chat still work.</p></div> : subjects.map((subject) => <article className="subject-card" key={subject.id}>{subject.thumbnail_url ? <img src={mediaUrl(subject.thumbnail_url)} alt="Tracked subject" /> : <div className="subject-placeholder" />}<div><strong>{subject.label}</strong><span>{subject.kind} · {subject.appearances.length} tracked moments</span></div><div className="subject-times">{subject.appearances.slice(0, 5).map((item) => <button key={item.start} onClick={() => onSeek(item.start)}>{formatTime(item.start)}</button>)}</div>{subject.kind === "person" && <><select value={subject.identity_id ?? ""} onChange={(event) => event.target.value && void onTag(subject, event.target.value)}><option value="">Link a remembered person…</option>{identities.map((identity) => <option key={identity.id} value={identity.id}>{identity.name}</option>)}</select><div className="subject-name"><input value={names[subject.id] ?? ""} onChange={(event) => onName(subject.id, event.target.value)} placeholder="Or name this person" /><button onClick={() => void onTag(subject)}>Remember</button></div></>}</article>)}</div>;
}

function TranscriptPanel({ segments, query, onQuery, onSeek }: { segments: VideoAnalysis["transcript_segments"]; query: string; onQuery: (value: string) => void; onSeek: (time: number) => void }) {
  return <div className="pro-panel transcript-panel"><input className="transcript-search" value={query} onChange={(event) => onQuery(event.target.value)} placeholder="Search spoken words…" />{segments.map((segment) => <button key={segment.id} onClick={() => onSeek(segment.start)}><time>{formatTime(segment.start)}</time><span>{segment.text}</span></button>)}{segments.length === 0 && <div className="panel-empty"><p>No transcript matches that search.</p></div>}</div>;
}

function IntelligenceTimeline({ analysis, duration, currentTime, onSeek }: { analysis: VideoAnalysis; duration: number; currentTime: number; onSeek: (time: number) => void }) {
  return <div className="intelligence-timeline"><div className="timeline-heading"><span>Intelligence timeline</span><strong>{formatTime(currentTime)} / {formatTime(duration)}</strong></div><button type="button" aria-label="Seek through intelligence timeline" className="timeline-track" onClick={(event) => { const rect = event.currentTarget.getBoundingClientRect(); onSeek(((event.clientX - rect.left) / rect.width) * duration); }}><i className="timeline-playhead" style={{ left: `${Math.min(100, currentTime / Math.max(duration, 0.1) * 100)}%` }} />{analysis.subjects.flatMap((subject, subjectIndex) => subject.appearances.map((item, index) => <i key={`${subject.id}-${index}`} className="timeline-appearance" style={{ left: `${item.start / duration * 100}%`, width: `${Math.max(.25, (item.end - item.start) / duration * 100)}%`, top: `${8 + subjectIndex * 4}px`, background: subject.color }} />))}{analysis.transcript_segments.map((item) => <i key={item.id} className="timeline-speech" style={{ left: `${item.start / duration * 100}%`, width: `${Math.max(.2, (item.end - item.start) / duration * 100)}%` }} />)}</button><div className="timeline-legend"><span><i className="speech-dot" /> Speech</span><span><i className="person-dot" /> Tracked people</span><span>{analysis.keyframes.length} visual anchors</span></div></div>;
}

function formatTime(seconds: number) {
  const value = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const rest = value % 60;
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}` : `${minutes}:${String(rest).padStart(2, "0")}`;
}

function formatBytes(bytes: number) {
  return `${(bytes / 1_000_000_000).toFixed(1)} GB`;
}
