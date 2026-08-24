# Local Video Intelligence workspace

Status: initial local implementation shipped; advanced correction and export workflows remain a roadmap
Branch: `main`

## North star

OhIc should let a person drop in any video and turn it into a private, searchable world:

- generate accurate, editable subtitles;
- find and track every important person or object through time;
- let the user name subjects and teach OhIc which appearances belong together;
- remember those identities locally across approved videos;
- answer natural-language questions with clickable visual evidence; and
- turn answers into actions such as seeking, clipping, following, reframing, blurring, or exporting.

The three capabilities are one system, not separate utilities. Subtitles describe what was said,
tracking records who and what was present, and the vision-language model reasons over both plus
selected frames. Every claim should point back to evidence in the video.

## Product principles

1. **Local means local.** Video, audio, names, embeddings, chats, and indexes stay on the device.
   Network access is limited to explicit model downloads.
2. **Evidence before eloquence.** Answers cite exact timestamp ranges and expose the frames,
   transcript, OCR, tracks, or events used to produce them.
3. **The user names people.** OhIc may maintain anonymous subjects such as `Person 03`, but it must
   never invent or externally look up a real identity.
4. **Corrections are first-class data.** Rename, merge, split, reject, and reassign operations must
   update the index and improve later matching.
5. **Analysis is resumable.** Every stage is checkpointed, independently repeatable, and visible in
   the queue. Enhancement and intelligence jobs share resource planning but not checkpoints.
6. **Automation proposes; people authorize.** Chat can prepare a destructive or privacy-sensitive
   operation, but exports, redactions, identity deletion, and bulk changes require confirmation.
7. **Useful on modest hardware.** A transcript-first mode must work without a VLM. Larger models
   and dense tracking are optional quality tiers.

## The experience

### Entry point

After import, the existing source workspace gains an **Understand video** action beside enhancement.
It opens an analysis recipe rather than immediately downloading every model.

Analysis recipe:

| Capability | Default | Controls |
| --- | --- | --- |
| Subtitles | On | language auto-detect, translate, word timing, speaker separation |
| Scenes and keyframes | On | fast/normal/detailed sampling |
| People | On | detect, track, face detail, remember approved identities |
| Objects | Suggested | common objects, custom text prompts, selected-object tracking |
| On-screen text | On | languages, minimum duration, subtitle-text exclusion |
| Ask this video | On when supported | compact/balanced/deep local VLM |

Before starting, the panel estimates processing time, model-download size, index size, and peak
memory. The recipe can be saved as a preset for folders or batch queues.

### Workspace layout

The intelligence workspace has four coordinated regions:

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Video title             Analysis 78%   Enhance   Export Intelligence        │
├────────────────────────────────────────────────┬─────────────────────────────┤
│                                                │ Ask | Subjects | Transcript │
│                 VIDEO PLAYER                   │                             │
│     masks, boxes, names, trails, OCR regions   │ contextual right dock       │
│                                                │                             │
├────────────────────────────────────────────────┴─────────────────────────────┤
│ Intelligence timeline: scenes · speech · subjects · objects · events · OCR   │
└──────────────────────────────────────────────────────────────────────────────┘
```

The player remains the source of truth. Clicking a citation, subtitle, subject appearance, event,
or chat answer seeks the same player and temporarily emphasizes the relevant evidence.

### Player overlay controls

The overlay toolbar is intentionally compact:

- **Overlay:** off, names, boxes, masks, motion trails, confidence;
- **Show:** everyone, tagged, selected, uncertain, hidden;
- **Follow:** center selected subject while watching;
- **Compare:** original versus enhanced while keeping tracks synchronized;
- **Correct:** add/remove point, redraw mask, split identity at this frame;
- **Snapshot:** save the current appearance as an identity example; and
- **Privacy preview:** show the exact blur, mask, crop, or removal result before export.

Hovering a visible person or object reveals its subject card. Clicking selects it everywhere.
Shift-click selects multiple subjects. Dragging a box on empty space creates a manual subject and
asks the tracker to propagate it forwards and backwards.

## Ask this video

### Chat surface

The **Ask** tab behaves like a research assistant attached to one video, not a generic chatbot.
The composer always shows its scope:

- whole video;
- current scene;
- selected timeline range;
- one or more selected subjects; or
- this video plus approved identity memory.

Suggested questions are derived from the available index, for example:

- “Who is speaking when the blue car arrives?”
- “When does Maya first appear after the meeting begins?”
- “Summarize the disagreement and show the three strongest moments.”
- “What text appears on the whiteboard before it is erased?”
- “Does Person 04 ever carry the red bag?”
- “Find every scene where Ravi and Maya are visible together.”
- “What changed between the first and second demonstration?”

### Evidence-grounded answers

Every answer contains:

1. a short response;
2. timestamp citation chips such as `02:14–02:27`;
3. an expandable evidence strip of keyframes, transcript lines, OCR, and subject tracks;
4. an evidence coverage indicator—not a fabricated probability; and
5. **Play evidence**, **Make clip**, and **Ask about this moment** actions.

If evidence is insufficient, OhIc says what it could not establish and offers a targeted deeper
scan. It must not answer a precise question about an unindexed range from transcript similarity
alone.

### Conversational actions

Chat can assemble operations as reversible drafts:

- “Make a two-minute reel of every answer given by Maya.”
- “Blur everyone except the two tagged presenters.”
- “Create a vertical follow-cam cut of the person in the red jacket.”
- “Export the moments where the package changes hands.”
- “Add subtitles, label each approved speaker, and keep them as a soft MKV track.”
- “Track every laptop and show when each one leaves the frame.”

The response first shows an operation card with range count, output duration, subjects, confidence
gaps, and estimated processing time. Nothing is rendered until the user confirms it.

### Retrieval flow

The VLM should not repeatedly ingest an entire multi-hour video. A local retrieval planner uses the
question to gather a small evidence packet:

1. search transcript, subtitle translations, OCR, scene captions, subjects, and events;
2. expand promising timestamps to neighbouring shots;
3. retrieve representative frames plus crops of referenced subjects or objects;
4. ask the local VLM to reason over that evidence packet;
5. validate that answer citations correspond to supplied evidence; and
6. optionally run a denser targeted scan if the first pass is inconclusive.

This makes queries fast, reduces hallucination pressure, and lets a compact local model reason over
long videos.

## Subjects and tracking

### Subject board

The **Subjects** tab groups anonymous tracks into subject cards:

```text
● Maya                 Person · approved identity
  17 appearances       00:13–42:08       91% timeline coverage
  [Follow] [Appearances] [Edit identity] [•••]

● Person 04            Person · needs review
  6 appearances        possible match with Maya
  [Name] [Merge] [Keep separate]
```

Cards support:

- rename or assign an existing local identity;
- set type: person, animal, vehicle, product, prop, or custom;
- choose overlay color and display name;
- follow, solo, hide, blur, pixelate, highlight, crop, or remove from exports;
- merge multiple anonymous tracks;
- split a wrong track from a chosen timestamp;
- declare “these are different subjects” as a negative identity example;
- associate a diarized speaker with a visible subject;
- restrict memory to this video, a folder, or the whole local library; and
- forget the identity and delete all derived embeddings.

### Multiple subjects and occlusion

Tracks are not identities. One identity may contain several track fragments caused by cuts,
occlusion, clothing changes, or leaving and re-entering. OhIc keeps this distinction visible:

- a **track** is continuous visual evidence inside a scene or window;
- a **subject** groups track fragments believed to depict the same entity in one video; and
- an **identity** is a user-approved memory that may span videos.

Solid timeline segments are high-confidence propagation. Dotted segments are re-identification
links. A small gap marker indicates an occlusion. The UI never silently merges ambiguous people;
it creates a review suggestion.

### Tracking modes

| Mode | Behaviour | Intended use |
| --- | --- | --- |
| Quick people | sparse detections and boxes | chat indexing and long videos |
| Balanced subjects | boxes plus periodic masks and re-identification | default |
| Precision masks | dense masks with correction frames | blur/removal and reframing |
| Manual target | click or box one arbitrary subject | unusual objects |
| Prompted discovery | “every red bag” or “all bicycles” | open-vocabulary tracking |

Scene boundaries reset propagation state. Identity matching may reconnect fragments across cuts, but
only above a conservative threshold or after user approval.

### Identity memory vault

The local **Identity vault** contains no scraped names. A user creates an identity by naming a
subject or selecting **Remember this person**.

Each identity stores encrypted local metadata and derived examples:

- user-assigned name, aliases, color, and notes;
- representative face/person crops approved by the user;
- visual embeddings and optional voice embeddings;
- negative examples that must not match;
- source video IDs and timestamps for every example;
- scope and matching threshold; and
- a correction history so a bad merge can be reversed.

Memory scopes are **this video**, **this folder/project**, **entire library**, and **ask every time**.
Deleting an identity removes its embeddings, chat references, aliases, and cached crops while leaving
anonymous per-video tracks intact unless the user chooses full derived-data deletion.

## Automatic subtitles

### Subtitle pipeline

1. Extract or normalize audio with FFmpeg.
2. Detect speech regions locally.
3. Transcribe with word-level timestamps and language confidence.
4. Optionally separate speakers.
5. Reconcile speaker turns with visible tracked subjects when evidence overlaps.
6. Apply punctuation and line-breaking rules without changing words.
7. Index segments for search and chat.

The transcript editor is synchronized with the player. Editing a word updates search immediately;
changing timing or a speaker link invalidates only the affected index entries.

### Subtitle controls

- source language: auto or explicit;
- transcription model: compact, balanced, accurate;
- original plus translated subtitle tracks;
- speaker labels: off, anonymous, or approved names;
- maximum characters per line and reading speed;
- retain filler words and sound cues;
- profanity display policy without changing the stored transcript;
- export SRT, WebVTT, JSON, or MKV soft track;
- burn-in style preview; and
- regenerate only a selected range.

Speaker diarization and identity are separate. A voice is `Speaker 02` until the user links it to a
person or approves a high-confidence audio-visual suggestion.

## Intelligence timeline

The bottom timeline has collapsible lanes:

- scenes and shot boundaries;
- transcript and speakers;
- each selected subject's appearances;
- object tracks and handoffs;
- OCR spans;
- inferred events;
- bookmarks, corrections, and chat evidence; and
- enhancement/checkpoint availability.

Users can lasso a time range, filter by subjects, or ask a question directly from the selection.
Zooming changes representation from video-level summaries to frame-level masks without loading all
observations into the browser.

## Wild extensions unlocked by the shared index

### Follow-cam director

Choose a person or object and export a stabilized horizontal, square, or vertical cut that follows
it. Composition rules use face direction, motion, other tagged people, and subtitle-safe areas rather
than blindly centring a box.

### Handoff graph

OhIc can model interactions such as one subject giving an object to another. Asking “who had the
keys last?” produces a timestamped chain of custody with uncertainty gaps.

### Search by demonstration

Pause on an object, draw over it, and ask “find every object like this.” The selected crop becomes a
temporary visual query across the video or approved library.

### Automatic character cut

Create a personal cut containing every appearance, spoken line, or interaction involving selected
subjects. The editor shows excluded uncertain matches before rendering.

### Conversational privacy editor

Commands such as “blur every face except approved interviewees, including reflections” generate a
mask-review queue and then a reversible export recipe.

### Video facts, not just summaries

The index can answer measurable questions: screen time per subject, speaking time, co-occurrence,
entrances/exits, object dwell time, repeated text, scene count, and where evidence is missing.

## Local architecture

```text
source media
   ├── scene/keyframe sampler ───────────────┐
   ├── audio → ASR → speaker turns ─────────┤
   ├── frames → OCR ─────────────────────────┤
   ├── detections → masks → track fragments ┤
   └── subject crops → embeddings ───────────┤
                                             ▼
                                SQLite evidence graph
                                + local vector index
                                             │
                         question → retrieval planner
                                             │
                           evidence packet → local VLM
                                             │
                              cited answer / action draft
```

### Proposed persistence

| Table | Purpose |
| --- | --- |
| `video_analyses` | versioned analysis recipe, stage checkpoints, model versions |
| `scenes` | shot boundaries, keyframes, scene descriptions |
| `transcript_segments` | words, speaker, language, confidence, edits |
| `ocr_spans` | text, polygon, start/end, normalized content |
| `track_fragments` | subject-local continuous spans and summary geometry |
| `track_observations` | chunked/compressed boxes, masks, visibility, confidence |
| `subjects` | per-video grouping, type, name, review state |
| `identities` | user-approved local memory and scope |
| `identity_examples` | positive/negative crops, voice samples, provenance |
| `events` | typed relationships between subjects, objects, text, and time |
| `evidence_embeddings` | model-versioned vectors for transcript, frames, and crops |
| `chat_sessions` | video/range/subject scope and model settings |
| `chat_messages` | prompts, cited evidence IDs, answers, action drafts |

Dense masks should not be stored as one SQLite row per frame. Store chunked RLE mask packs in the
analysis artifact directory and reference them from SQLite. Short searchable metadata remains in the
database. Embeddings can begin as normalized float16 BLOBs with brute-force cosine search, adding an
optional HNSW index only when library scale requires it.

### API families

```text
POST   /api/videos/{id}/analysis
GET    /api/analyses/{id}
POST   /api/analyses/{id}/{pause,resume,cancel}
GET    /api/videos/{id}/transcript
PATCH  /api/transcript/{segment_id}
GET    /api/videos/{id}/subjects
POST   /api/videos/{id}/subjects/from-point
PATCH  /api/subjects/{id}
POST   /api/subjects/{id}/{merge,split,retrack}
GET    /api/subjects/{id}/appearances
GET    /api/identities
POST   /api/identities
POST   /api/identities/{id}/examples
DELETE /api/identities/{id}
POST   /api/videos/{id}/chat/sessions
POST   /api/chat/sessions/{id}/messages
POST   /api/chat/messages/{id}/actions
GET    /api/videos/{id}/intelligence-timeline
```

Long analysis, tracking correction, and chat generation use SSE progress/events and the existing
durable job conventions. Every derived record includes a pipeline version so model upgrades can
invalidate only affected stages.

## Candidate local model stack

This is a shortlist for prototyping, not a final dependency decision.

### Speech

**whisper.cpp** is the strongest cross-platform baseline: CPU-only operation plus Metal, CUDA,
Vulkan, ROCm, and OpenVINO paths, VAD support, quantization, and a small integration surface. It can
run entirely offline after the model is downloaded.

Source: <https://github.com/ggml-org/whisper.cpp>

Speaker diarization should be optional. `pyannote.audio` runs locally and its code is MIT, but the
Community-1 model requires accepting conditions and obtaining a Hugging Face token before it can be
stored for offline use. That makes it unsuitable as an invisible default dependency; OhIc should
offer it as an explicit model installation or evaluate a token-free alternative.

Source: <https://github.com/pyannote/pyannote-audio>

### Detection, masks, and tracking

**SAM 2** can accept user points, boxes, or masks and propagate multiple object masks through video.
Its code and checkpoints are Apache 2.0, making it a promising precision/manual tracking engine.

Source: <https://github.com/facebookresearch/sam2>

**Grounding DINO** is an Apache-licensed open-vocabulary detector candidate for text prompts such as
“red backpack” and can seed SAM 2 masks. Checkpoint terms still need a release audit before shipping.

Source: <https://github.com/IDEA-Research/GroundingDINO>

**CoTracker3** is technically attractive for point trajectories and long-video online windows, but
its repository is CC BY-NC 4.0. It may be used only for isolated research evaluation unless a
commercially compatible license is obtained. It must not become a shipped OhIc dependency under the
current terms.

Source: <https://github.com/facebookresearch/co-tracker>

### OCR

**PaddleOCR** provides multilingual, locally deployable OCR with compact models and several inference
backends. A small mobile recognition configuration is suitable for periodic keyframes; denser OCR
can be targeted around question evidence.

Source: <https://github.com/PaddlePaddle/PaddleOCR>

### Vision-language reasoning

**Qwen3-VL** has Apache-licensed 2B, 4B, and 8B variants and capabilities directly relevant to video,
OCR, grounding, and timestamp alignment. The 2B/4B Instruct variants are candidates for compact and
balanced profiles; quantized runtime compatibility must be benchmarked on MPS, CUDA, and CPU.

Source: <https://github.com/QwenLM/Qwen3-VL>

**llama.cpp** provides a compact local server and documented multimodal support, including a
pre-quantized Qwen2.5-VL 3B path. It is a useful fallback runtime while Qwen3-VL quantized support is
validated across platforms.

Source: <https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md>

No model is approved merely because its code repository is permissively licensed. Checkpoint,
training-data, redistribution, and acceptable-use terms require separate entries in OhIc's model
registry.

## Resource profiles

| Profile | Intended hardware | Initial behaviour |
| --- | --- | --- |
| Transcript | CPU-capable | ASR, scenes, subtitle search; no VLM required |
| Compact | approximately 8 GB available | sparse subjects, OCR, 2B quantized VLM |
| Balanced | approximately 16 GB available | masks on keyframes, identity suggestions, 4B VLM |
| Deep | 24 GB+ or strong CUDA | dense masks, prompted discovery, larger VLM evidence packets |

Only one heavyweight model should be resident by default. The resource manager schedules ASR,
tracking, enhancement, and VLM stages, unloads idle models, and exposes why a stage is waiting.
Analysis can proceed while the user watches, but playback and active enhancement keep priority.

## Privacy and safety controls

- Bind every API to loopback, matching the existing local-only security boundary.
- Encrypt the optional identity vault with a user-controlled local key.
- Never transmit frames, embeddings, names, audio, or prompts to a remote inference endpoint.
- Never infer or invent a real-world name, protected trait, criminality, emotion, or intent.
- Treat age, ethnicity, health, and similar sensitive classifications as unsupported.
- Show a persistent “local model” indicator in chat with the loaded model and evidence scope.
- Make **Forget identity**, **Delete analysis**, and **Delete all intelligence data** explicit and
  auditable.
- Require confirmation before redaction exports, identity-wide changes, or chat-generated edits.
- Provide an analysis manifest containing model versions, settings, user corrections, and hashes.

## Phased implementation

### Phase 1 — searchable subtitles

- durable analysis job and schema;
- audio extraction, local ASR, word timestamps;
- synchronized transcript editor;
- SRT/WebVTT export and soft subtitle mux;
- transcript search with clickable timestamps; and
- analysis progress/history restoration.

This delivers immediate consumer value without waiting for tracking or a VLM.

### Phase 2 — manual subject tracking

- click/box a person or arbitrary object;
- SAM 2 forward/backward propagation in scene-bounded windows;
- overlay and subject timeline;
- correction points, split, retrack, blur, and follow-crop export; and
- chunked mask storage.

Manual prompting avoids premature auto-detection and identity complexity while proving the UX.

### Phase 3 — automatic people and identity memory

- permissively licensed person detector;
- per-scene track fragments and conservative cross-cut grouping;
- subject board, merge/split, names, local identity vault;
- approved cross-video matching and negative examples; and
- optional speaker-to-visible-person association.

### Phase 4 — evidence index and Ask

- scenes, keyframes, OCR, transcript and subject retrieval;
- local vector search;
- compact VLM runtime and model manager;
- cited chat answers, evidence playback, targeted rescans; and
- persistent scoped chat sessions.

### Phase 5 — conversational editing

- action-plan schema and confirmation UI;
- clip/reel, privacy mask, follow-cam, and subtitle operations;
- event/handoff graph;
- batch intelligence presets; and
- cross-video queries over explicitly approved library scope.

## Acceptance bar

The feature is not complete when a model can produce a plausible answer. It is complete when:

- every answer citation seeks to the claimed evidence;
- subtitle edits survive restarts and re-index correctly;
- a tracked subject can leave, re-enter, be corrected, and export with frame-accurate masks;
- identity merges and deletions are reversible and local;
- analysis resumes after process termination;
- no network request occurs during inference after explicit model installation;
- low-memory mode remains useful with subtitles and search only; and
- model and checkpoint licenses are documented before distribution.

## Immediate prototype decision

Build Phase 1 first, while constructing one thin end-to-end tracking spike in parallel inside the
same branch:

1. transcribe a short local clip and render timestamp-synchronized subtitles;
2. click one person, propagate a SAM 2 mask across a scene, and display its timeline segment; and
3. index five keyframes plus transcript segments, then answer one question with mandatory clickable
   evidence.

That vertical slice tests the shared data contracts and workspace interaction before committing to
automatic identity matching or a large model dependency.
