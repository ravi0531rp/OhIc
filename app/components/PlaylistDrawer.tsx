"use client";
/* Playlist thumbnails are third-party YouTube images. */
/* eslint-disable @next/next/no-img-element */

import { useState } from "react";
import type { PlaylistRecord } from "../lib/types";
import { FilmIcon, PlaylistIcon, StopIcon, XIcon } from "./Icons";

type Props = {
  playlists: PlaylistRecord[];
  open: boolean;
  onClose: () => void;
  onCancel: (playlist: PlaylistRecord) => void;
  onDelete: (playlist: PlaylistRecord) => void;
  onOpenResult: (jobId: string) => void;
};

const ACTIVE = ["queued", "running"];

export function PlaylistDrawer({ playlists, open, onClose, onCancel, onDelete, onOpenResult }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = playlists.find((playlist) => playlist.id === selectedId) ?? playlists[0];
  const completed = selected?.items.filter((item) => item.status === "complete").length ?? 0;

  return (
    <>
      <button className={`drawer-scrim ${open ? "visible" : ""}`} aria-label="Close playlists" onClick={onClose} />
      <aside className={`history-drawer playlist-drawer ${open ? "open" : ""}`} aria-hidden={!open}>
        <div className="drawer-heading">
          <div><span className="eyebrow">Persistent batch workspace</span><h2>Playlists</h2></div>
          <button className="icon-button" aria-label="Close playlists" onClick={onClose}><XIcon size={18} /></button>
        </div>
        {playlists.length === 0 ? (
          <div className="playlist-empty"><PlaylistIcon size={28} /><strong>No playlists yet</strong><span>Paste a YouTube playlist and choose the videos you want to enhance.</span></div>
        ) : (
          <div className="playlist-library">
            <div className="playlist-projects" aria-label="Saved playlists">
              {playlists.map((playlist) => (
                <button className={playlist.id === selected?.id ? "active" : ""} key={playlist.id} onClick={() => setSelectedId(playlist.id)}>
                  {playlist.thumbnail ? <img alt="" src={playlist.thumbnail} /> : <PlaylistIcon size={18} />}
                  <span><strong>{playlist.title}</strong><small>{playlist.items.length} videos · {playlist.status}</small></span>
                  <i style={{ width: `${playlist.progress}%` }} />
                </button>
              ))}
            </div>
            {selected && (
              <section className="playlist-detail">
                <header>
                  <div><span className={`playlist-state ${selected.status}`}>{selected.status}</span><h3>{selected.title}</h3><p>{completed} of {selected.items.length} complete · {selected.preset} quality</p></div>
                  {ACTIVE.includes(selected.status) ? <button className="playlist-stop" onClick={() => onCancel(selected)}><StopIcon size={12} /> Stop batch</button> : <button className="playlist-remove" onClick={() => { if (window.confirm("Remove this playlist project? Enhanced videos will stay in Storage.")) onDelete(selected); }}><XIcon size={12} /> Remove</button>}
                </header>
                <div className="playlist-overall"><span style={{ width: `${selected.progress}%` }} /></div>
                <div className="playlist-items">
                  {selected.items.map((item) => (
                    <article key={item.id}>
                      {item.thumbnail ? <img alt="" src={item.thumbnail} /> : <span className="playlist-item-fallback"><FilmIcon size={16} /></span>}
                      <div className="playlist-item-copy">
                        <strong>{item.position}. {item.title}</strong>
                        <small className={item.status}>{item.error ?? item.stage}</small>
                        <div><i style={{ width: `${item.progress}%` }} /></div>
                      </div>
                      {item.status === "complete" && item.job_id ? (
                        <button onClick={() => onOpenResult(item.job_id!)}>Open</button>
                      ) : <span className={`playlist-dot ${item.status}`} />}
                    </article>
                  ))}
                </div>
              </section>
            )}
          </div>
        )}
      </aside>
    </>
  );
}
