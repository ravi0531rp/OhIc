"""Self-contained phone UI served by the token-scoped LAN camera bridge."""
# ruff: noqa: E501


def render_phone_camera_page(token: str) -> str:
    return _PAGE.replace("__OHIC_TOKEN__", token)


_PAGE = r"""<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>OhIc phone camera</title>
  <style>
    body { background:#090b09;color:#eef0eb;font:16px system-ui;margin:0;padding:22px }
    main { margin:auto;max-width:560px }
    video { background:#000;border-radius:18px;width:100% }
    button,.record { background:#d9ff67;border:0;border-radius:10px;box-sizing:border-box;color:#182000;display:block;font-weight:700;margin-top:12px;padding:14px;text-align:center;width:100% }
    button:disabled { opacity:.55 }
    p { color:#929990;line-height:1.5 }
    #status { color:#d9ff67 }
    #fallback { border-top:1px solid #282c27;margin-top:20px;padding-top:8px }
    input { display:none }
  </style>
</head>
<body>
<main>
  <h1>OhIc live camera</h1>
  <p>Stream video and audio directly to the paired computer. Chunks are saved locally before OhIc acknowledges them, so a Wi-Fi interruption can be retried safely.</p>
  <video autoplay muted playsinline hidden></video>
  <canvas hidden></canvas>
  <p id="status">Ready to connect.</p>
  <button id="start">Start live stream</button>
  <button id="stop" hidden disabled>Stop and save the video</button>
  <section id="fallback">
    <p>If this browser blocks live camera access, record with the phone camera and send the finished clip directly.</p>
    <label class="record">Record with phone camera<input id="recording" type="file" accept="video/*" capture="environment"></label>
  </section>
  <script>
    const token = '__OHIC_TOKEN__';
    const video = document.querySelector('video');
    const canvas = document.querySelector('canvas');
    const status = document.querySelector('#status');
    const start = document.querySelector('#start');
    const stop = document.querySelector('#stop');
    const recording = document.querySelector('#recording');
    let mediaStream;
    let recorder;
    let previewTimer;
    let previewBusy = false;
    let sequence = 0;
    let startedAt = 0;
    let uploadQueue = Promise.resolve();
    let uploadError = null;

    const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

    async function uploadChunk(blob, chunkSequence) {
      let lastError;
      for (let attempt = 1; attempt <= 5; attempt += 1) {
        try {
          const elapsed = Math.max(0, Date.now() - startedAt);
          const response = await fetch(`/camera/${token}/chunk`, {
            method: 'POST',
            headers: {
              'Content-Type': blob.type || recorder.mimeType || 'video/webm',
              'X-OhIc-Sequence': String(chunkSequence),
              'X-OhIc-Elapsed-Ms': String(elapsed),
            },
            body: blob,
          });
          if (!response.ok) throw new Error(await response.text());
          status.textContent = `Live · ${chunkSequence + 1} durable chunks sent`;
          return;
        } catch (error) {
          lastError = error;
          status.textContent = `Wi-Fi interrupted · retrying chunk ${chunkSequence + 1}`;
          await delay(400 * attempt);
        }
      }
      throw lastError || new Error('Live chunk upload failed.');
    }

    function queueChunk(blob) {
      if (!blob.size) return;
      const chunkSequence = sequence;
      sequence += 1;
      uploadQueue = uploadQueue
        .then(() => uploadChunk(blob, chunkSequence))
        .catch(error => {
          uploadError = error;
          status.textContent = `Live upload paused: ${error.message}`;
        });
    }

    function sendPreview() {
      if (previewBusy || !video.videoWidth) return;
      previewBusy = true;
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext('2d').drawImage(video, 0, 0);
      canvas.toBlob(async blob => {
        try {
          if (blob) await fetch(`/camera/${token}/frame`, { method:'POST', headers:{'Content-Type':'image/jpeg'}, body:blob });
        } finally {
          previewBusy = false;
        }
      }, 'image/jpeg', .76);
    }

    function supportedMimeType() {
      return [
        'video/webm;codecs=vp8,opus',
        'video/webm',
        'video/mp4',
      ].find(type => window.MediaRecorder?.isTypeSupported(type)) || '';
    }

    async function startLive() {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        status.textContent = 'This QR uses plain HTTP. Enable secure live streaming in OhIc, then scan the refreshed QR. You can also use native recording below.';
        return;
      }
      try {
        start.disabled = true;
        status.textContent = 'Requesting camera…';
        mediaStream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode:{ideal:'environment'}, width:{ideal:1280}, height:{ideal:720} },
          audio: false,
        });
        let audioAvailable = false;
        try {
          const microphone = await navigator.mediaDevices.getUserMedia({ video: false, audio: true });
          microphone.getAudioTracks().forEach(track => mediaStream.addTrack(track));
          audioAvailable = true;
        } catch (_error) {
          status.textContent = 'Microphone unavailable · continuing with video only';
        }
        video.srcObject = mediaStream;
        video.hidden = false;
        const mimeType = supportedMimeType();
        if (!window.MediaRecorder || !mimeType) throw new Error('MediaRecorder is unavailable.');
        recorder = new MediaRecorder(mediaStream, { mimeType, videoBitsPerSecond: 2500000 });
        recorder.ondataavailable = event => queueChunk(event.data);
        recorder.onerror = event => { status.textContent = `Recorder error: ${event.error?.message || 'unknown error'}`; };
        recorder.onstop = async () => {
          await uploadQueue;
          clearInterval(previewTimer);
          mediaStream?.getTracks().forEach(track => track.stop());
          if (uploadError || sequence === 0) {
            status.textContent = uploadError ? `Could not finish: ${uploadError.message}` : 'No video was received.';
            return;
          }
          status.textContent = 'Finalizing the durable stream…';
          const response = await fetch(`/camera/${token}/finish`, { method:'POST' });
          status.textContent = response.ok ? 'Saved. Return to OhIc on your computer.' : await response.text();
        };
        startedAt = Date.now();
        recorder.start(2000);
        previewTimer = setInterval(sendPreview, 500);
        start.hidden = true;
        stop.hidden = false;
        stop.disabled = false;
        status.textContent = audioAvailable
          ? 'Live · recording durable video and audio chunks'
          : 'Live · recording durable video chunks';
      } catch (error) {
        start.disabled = false;
        mediaStream?.getTracks().forEach(track => track.stop());
        status.textContent = `Live camera unavailable: ${error.message}. Use native recording below.`;
      }
    }

    start.onclick = startLive;
    stop.onclick = () => {
      stop.disabled = true;
      status.textContent = 'Sending the final video chunk…';
      recorder?.stop();
    };
    recording.onchange = async () => {
      const file = recording.files?.[0];
      if (!file) return;
      recording.disabled = true;
      status.textContent = `Sending ${file.name || 'phone recording'}…`;
      try {
        const response = await fetch(`/camera/${token}/recording`, {
          method:'POST',
          headers:{'Content-Type':file.type || 'application/octet-stream'},
          body:file,
        });
        status.textContent = response.ok ? 'Sent. OhIc is preparing the video.' : await response.text();
        if (!response.ok) recording.disabled = false;
      } catch (error) {
        status.textContent = `Send failed: ${error.message}`;
        recording.disabled = false;
      }
    };
  </script>
</main>
</body>
</html>
"""
