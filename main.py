"""
Audiobookshelf (ABS) Snippet Sidecar
Backend app for the bookmarks you create on ABS Mobile app.
Extracts audio clips via ffmpeg, transcribes speech with faster-whisper,
and manages per-user bookmarks and snippets under {username}/bookmarks.
"""

import os
import re
import json
import subprocess
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

import requests
from fastapi import FastAPI, Request, Header, HTTPException, Depends, Query, Response
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("abs-sidecar")

# Configuration from Environment
ABS_SERVER_URL = os.environ.get("ABS_SERVER_URL", "http://localhost:13378").rstrip("/")
VOLUME_DIR = os.environ.get("VOLUME_DIR", os.environ.get("SNIPPETS_DIR", "/data")).rstrip("/")
SNIPPETS_DIR = VOLUME_DIR  # Kept for backward compatibility
WHISPER_MODEL_NAME = os.environ.get("WHISPER_MODEL", "base.en")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")

# Ensure main volume directory exists
os.makedirs(VOLUME_DIR, exist_ok=True)

# Templates
templates = Jinja2Templates(directory="templates")

# FastAPI App
app = FastAPI(
    title="Audiobookshelf Bookmarks Extractor",
    description="Backend app for the bookmarks you create on ABS Mobile app.",
    version="1.0"
)

# Enable CORS so native mobile apps (Kotlin Android), WebViews, and external clients can call endpoints directly
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global faster-whisper model cache (lazy-loaded)
_whisper_model = None

# Global Vosk model cache (lazy-loaded backup engine)
VOSK_MODEL_PATH = os.environ.get("VOSK_MODEL_PATH", "/app/vosk-model")
VOSK_MODEL_NAME = os.environ.get("VOSK_MODEL_NAME", "vosk-model-small-en-us-0.15")
_vosk_model = None


def get_whisper_model():
    """Lazy-load the faster-whisper model to optimize startup time and memory."""
    global _whisper_model
    if _whisper_model is None:
        logger.info(f"Loading faster-whisper model '{WHISPER_MODEL_NAME}' on {WHISPER_DEVICE} ({WHISPER_COMPUTE_TYPE})...")
        try:
            from faster_whisper import WhisperModel
            _whisper_model = WhisperModel(
                WHISPER_MODEL_NAME,
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE_TYPE
            )
            logger.info("faster-whisper model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load faster-whisper model: {e}")
            raise e
    return _whisper_model


def get_vosk_model():
    """Lazy-load the Vosk speech recognition model as a backup engine."""
    global _vosk_model
    if _vosk_model is None:
        try:
            from vosk import Model
            if os.path.exists(VOSK_MODEL_PATH):
                logger.info(f"Loading Vosk model from directory: {VOSK_MODEL_PATH}")
                _vosk_model = Model(VOSK_MODEL_PATH)
            else:
                logger.info(f"Loading Vosk model by name: {VOSK_MODEL_NAME}")
                _vosk_model = Model(model_name=VOSK_MODEL_NAME)
            logger.info("Vosk backup model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Vosk model: {e}")
            raise e
    return _vosk_model


def transcribe_with_vosk(audio_file_path: str) -> str:
    """
    Transcribe audio with Vosk backup engine.
    Uses ffmpeg to create a temporary 16kHz mono PCM WAV and feeds to KaldiRecognizer.
    """
    import wave
    from vosk import KaldiRecognizer

    vosk_model = get_vosk_model()
    wav_path = audio_file_path + ".vosk_temp.wav"
    try:
        cmd = [
            "ffmpeg", "-y", "-i", audio_file_path,
            "-ar", "16000", "-ac", "1", "-f", "wav", wav_path
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        rec = KaldiRecognizer(vosk_model, 16000)
        rec.SetWords(True)

        results = []
        with wave.open(wav_path, "rb") as wf:
            while True:
                data = wf.readframes(4000)
                if len(data) == 0:
                    break
                if rec.AcceptWaveform(data):
                    part = json.loads(rec.Result())
                    if part.get("text"):
                        results.append(part["text"])
            final = json.loads(rec.FinalResult())
            if final.get("text"):
                results.append(final["text"])

        return " ".join(results).strip()
    finally:
        if os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except Exception:
                pass


def sanitize_filename(name: str) -> str:
    """Sanitize strings for filesystem directory and file names."""
    if not name:
        return "untitled"
    clean = re.sub(r'[\\/*?:"<>|]', "_", name)
    clean = clean.strip(" .")
    return clean or "untitled"


def validate_abs_token(token: str) -> Dict[str, Any]:
    """
    Validate the Bearer token with Audiobookshelf via GET {ABS_SERVER_URL}/api/me.
    Returns user dict with id and username.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization token")

    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        url = f"{ABS_SERVER_URL}/api/me"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"ABS token validation failed with status {resp.status_code}")
            raise HTTPException(status_code=401, detail="Invalid or expired Audiobookshelf Bearer token")

        data = resp.json()
        user_info = data.get("user") if isinstance(data.get("user"), dict) else data

        user_id = user_info.get("id")
        username = user_info.get("username") or user_info.get("name") or "abs_user"

        if not user_id:
            raise HTTPException(status_code=401, detail="Failed to retrieve user ID from Audiobookshelf response")

        return {
            "id": str(user_id),
            "username": str(username),
            "raw_token": token,
            "mediaProgress": user_info.get("mediaProgress") or []
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"Error communicating with Audiobookshelf at {ABS_SERVER_URL}: {e}")
        raise HTTPException(status_code=502, detail=f"Cannot connect to Audiobookshelf server at {ABS_SERVER_URL}: {str(e)}")


async def extract_token_flexible(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_abs_token: Optional[str] = Header(None, alias="X-ABS-Token"),
    token: Optional[str] = Query(None),
    api_key: Optional[str] = Query(None, alias="apiKey")
) -> str:
    """
    Flexible token extractor callable by:
    - Native Android Kotlin app (Authorization: Bearer <TOKEN> or X-ABS-Token header)
    - Browser query parameter (?token=<TOKEN> or ?apiKey=<TOKEN>)
    - Request body / cookies
    """
    # 1. Authorization header
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        elif len(parts) == 1:
            return parts[0].strip()

    # 2. X-ABS-Token header
    if x_abs_token:
        return x_abs_token.strip()

    # 3. Query params
    if token:
        return token.strip()
    if api_key:
        return api_key.strip()

    # 4. JSON body if available
    try:
        body = await request.json()
        if isinstance(body, dict):
            body_token = body.get("token") or body.get("abs_token") or body.get("apiKey")
            if body_token:
                return str(body_token).strip()
    except Exception:
        pass

    # 5. Cookie
    cookie_token = request.cookies.get("abs_token")
    if cookie_token:
        return cookie_token.strip()

    raise HTTPException(status_code=401, detail="Authorization token required (via Bearer header, X-ABS-Token, or ?token= query parameter)")


class SnippetRequest(BaseModel):
    """
    Flexible request payload for audio extraction and transcription.
    Accepts snake_case and camelCase parameters for compatibility with Android Kotlin and Web clients.
    """
    duration: Optional[int] = 60
    start_time: Optional[float] = None
    startTime: Optional[float] = None
    offset: Optional[float] = None
    bookmark_id: Optional[str] = None
    bookmarkId: Optional[str] = None
    library_item_id: Optional[str] = None
    libraryItemId: Optional[str] = None
    title: Optional[str] = None
    token: Optional[str] = None


def format_bookmarked_duration(seconds: float) -> str:
    """Format duration into HH:MM:SS (SSSS seconds) format."""
    total_sec = int(round(seconds))
    hrs = total_sec // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    return f"{hrs:02d}:{mins:02d}:{secs:02d} ({total_sec} seconds)"


def resolve_audio_target(token: str, req: Optional[SnippetRequest] = None, user_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Resolve the target audio file, timestamp, and book metadata.
    Handles:
    1. Direct bookmark extraction (if bookmark_id or bookmarkId is provided)
    2. Explicit offset or libraryItemId
    3. Active listening sessions from GET /api/me/listening-sessions
    4. Fallback to latest mediaProgress from GET /api/me if listening session has timed out
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    target_lib_item_id = req.library_item_id or req.libraryItemId if req else None
    target_offset = req.start_time or req.startTime or req.offset if req else None
    target_bookmark_id = req.bookmark_id or req.bookmarkId if req else None

    # Option A: Bookmark ID specified (e.g. created on ABS Mobile App)
    if target_bookmark_id:
        try:
            b_url = f"{ABS_SERVER_URL}/api/me/bookmarks"
            b_resp = requests.get(b_url, headers=headers, timeout=10)
            if b_resp.status_code == 200:
                b_data = b_resp.json()
                b_list = b_data.get("bookmarks") if isinstance(b_data, dict) else (b_data if isinstance(b_data, list) else [])
                found_b = next((b for b in b_list if b.get("id") == target_bookmark_id or str(b.get("time")) == str(target_bookmark_id)), None)
                if found_b:
                    target_lib_item_id = found_b.get("libraryItemId") or target_lib_item_id
                    target_offset = float(found_b.get("time") or 0.0)
        except Exception as b_err:
            logger.warning(f"Error querying bookmarks for target_bookmark_id: {b_err}")

    # Option B: Check active listening sessions
    current_time = None
    library_item_id = target_lib_item_id
    file_path = None
    book_title = "Unknown Book"
    subtitle = ""
    author = "Unknown Author"
    chapter_name = "Unknown Chapter"

    try:
        sessions_url = f"{ABS_SERVER_URL}/api/me/listening-sessions"
        resp = requests.get(sessions_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            sessions_data = resp.json()
            sessions = []
            if isinstance(sessions_data, dict):
                sessions = sessions_data.get("sessions") or sessions_data.get("items") or []
            elif isinstance(sessions_data, list):
                sessions = sessions_data

            if sessions:
                active_session = sessions[0]
                if not library_item_id:
                    library_item_id = active_session.get("libraryItemId")
                if target_offset is None:
                    current_time = float(active_session.get("currentTime") or 0.0)

                media_meta = (
                    active_session.get("mediaMetadata")
                    or active_session.get("media", {}).get("metadata", {})
                    or {}
                )
                display_title = active_session.get("displayTitle")
                book_title = media_meta.get("title") or display_title or book_title
                subtitle = media_meta.get("subtitle") or ""

                author_val = (
                    media_meta.get("author")
                    or media_meta.get("authorName")
                    or media_meta.get("authors")
                    or author
                )
                author = ", ".join(author_val) if isinstance(author_val, list) else str(author_val)

                # Chapters
                chapters = active_session.get("chapters") or active_session.get("media", {}).get("chapters") or []
                c_time = target_offset if target_offset is not None else (current_time or 0.0)
                for ch in chapters:
                    start = float(ch.get("start") or 0.0)
                    end = float(ch.get("end") or 0.0)
                    if start <= c_time <= end:
                        chapter_name = ch.get("title") or ch.get("name") or chapter_name
                        break

                # File path from session
                audio_track = active_session.get("audioTrack") or {}
                if isinstance(audio_track, dict):
                    file_path = audio_track.get("metadata", {}).get("path") or audio_track.get("path")
                if not file_path:
                    file_path = active_session.get("filePath") or active_session.get("path")
    except Exception as e:
        logger.warning(f"Failed to query active listening sessions: {e}")

    # Option C: Fallback to mediaProgress if no active session
    if not library_item_id or (target_offset is None and current_time is None):
        progress_list = user_info.get("mediaProgress", []) if user_info else []
        if not progress_list:
            try:
                me_res = requests.get(f"{ABS_SERVER_URL}/api/me", headers=headers, timeout=10)
                if me_res.status_code == 200:
                    me_data = me_res.json()
                    user_d = me_data.get("user", {}) if isinstance(me_data.get("user"), dict) else me_data
                    progress_list = user_d.get("mediaProgress", [])
            except Exception:
                pass

        if progress_list:
            progress_list.sort(key=lambda x: x.get("lastUpdate") or 0, reverse=True)
            latest = progress_list[0]
            if not library_item_id:
                library_item_id = latest.get("libraryItemId")
            if target_offset is None and current_time is None:
                current_time = float(latest.get("currentTime") or 0.0)

    # Use explicit offset if provided
    if target_offset is not None:
        current_time = float(target_offset)

    if current_time is None:
        current_time = 0.0

    if not library_item_id:
        raise HTTPException(
            status_code=404,
            detail="No active listening session or recent audiobook found on Audiobookshelf. Start playing an audiobook first or specify library_item_id."
        )

    # Resolve book item details and audio file path
    item_url = f"{ABS_SERVER_URL}/api/items/{library_item_id}?expanded=1"
    try:
        item_resp = requests.get(item_url, headers=headers, timeout=10)
        if item_resp.status_code == 200:
            item_data = item_resp.json()
            media = item_data.get("media", {})
            meta = media.get("metadata", {})

            if book_title == "Unknown Book":
                book_title = meta.get("title") or item_data.get("title") or book_title
            if not subtitle:
                subtitle = meta.get("subtitle") or ""
            if author == "Unknown Author":
                author_val = meta.get("authorName") or meta.get("author") or meta.get("authors")
                if author_val:
                    author = ", ".join(author_val) if isinstance(author_val, list) else str(author_val)

            # Match chapter if still unknown
            if chapter_name == "Unknown Chapter":
                chapters = media.get("chapters") or []
                for ch in chapters:
                    start = float(ch.get("start") or 0.0)
                    end = float(ch.get("end") or 0.0)
                    if start <= current_time <= end:
                        chapter_name = ch.get("title") or ch.get("name") or chapter_name
                        break

            # Find matching audio file
            audio_files = media.get("audioFiles") or media.get("tracks") or []
            if audio_files:
                selected_file = audio_files[0]
                for af in audio_files:
                    af_meta = af.get("metadata") or {}
                    af_start = float(af.get("startOffset") or 0.0)
                    af_dur = float(af.get("duration") or af_meta.get("duration") or 0.0)
                    if af_dur > 0 and af_start <= current_time <= (af_start + af_dur):
                        selected_file = af
                        break

                meta_path = selected_file.get("metadata", {}).get("path")
                direct_path = selected_file.get("path")
                meta_fn = selected_file.get("metadata", {}).get("filename") or selected_file.get("filename")
                media_path = media.get("path") or item_data.get("path")

                resolved_file_path = meta_path or direct_path
                if not resolved_file_path and media_path and meta_fn:
                    resolved_file_path = f"{media_path.rstrip('/')}/{meta_fn}"
                if not resolved_file_path:
                    resolved_file_path = media_path or file_path

                file_path = resolved_file_path or file_path
    except Exception as e:
        logger.warning(f"Failed to fetch item details for {library_item_id}: {e}")

    if not file_path:
        raise HTTPException(
            status_code=404,
            detail=f"Could not determine source audio file path for library item '{library_item_id}'. Ensure the audio library is mounted."
        )

    return {
        "libraryItemId": library_item_id,
        "currentTime": current_time,
        "file_path": file_path,
        "book_title": book_title,
        "subtitle": subtitle,
        "author": author,
        "chapter_name": chapter_name
    }


def parse_frontmatter(content: str) -> Dict[str, Any]:
    """Parse YAML frontmatter from a Markdown file string."""
    data = {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            raw_frontmatter = parts[1]
            body = parts[2].strip()
            for line in raw_frontmatter.strip().split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    val = v.strip().strip('"').strip("'")
                    data[k.strip()] = val
    data["body"] = body
    return data


# --- API Routes (Callable by Native Android Kotlin App, Web App, and external tools) ---

@app.post("/api/snippet")
@app.post("/api/extract")
@app.post("/api/bookmark/extract")
async def create_snippet_or_bookmark(
    request: Request,
    payload: Optional[SnippetRequest] = None,
    raw_token: str = Depends(extract_token_flexible)
):
    """
    Extracts an audio snippet and transcribes it.
    Can be called by:
    - Native Android Kotlin App (via button press when creating/syncing a bookmark)
    - Web Dashboard
    - Automation webhooks or curl

    Creates a dedicated folder under the main volume folder:
    /data/{username}/bookmarks/{book_title}/
    """
    # 1. Authenticate user against ABS server
    user = validate_abs_token(raw_token)
    user_id = user["id"]
    username = user["username"]
    safe_username = sanitize_filename(username)

    # 2. Resolve target session & offset
    session_state = resolve_audio_target(raw_token, payload, user)
    current_time = session_state["currentTime"]
    file_path = session_state["file_path"]
    book_title = session_state["book_title"]
    subtitle = session_state.get("subtitle") or ""
    author = session_state["author"]
    chapter_name = session_state["chapter_name"]
    library_item_id = session_state["libraryItemId"]

    # Combine book title and sub-title if available
    if subtitle and subtitle.strip() and subtitle.strip().lower() not in book_title.lower():
        full_book_title = f"{book_title}: {subtitle.strip()}"
    else:
        full_book_title = book_title

    # 3. Parameters
    duration = payload.duration if payload and payload.duration else 60
    custom_start = (payload.start_time or payload.startTime or payload.offset) if payload else None
    start_time = float(custom_start) if custom_start is not None else max(0.0, current_time - 30.0)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 4. User-Specific Volume Folder Structure:
    # {VOLUME_DIR}/{username}/bookmarks/{safe_book_title}/
    safe_book_title = sanitize_filename(book_title)
    output_dir = os.path.join(VOLUME_DIR, safe_username, "bookmarks", safe_book_title)
    os.makedirs(output_dir, exist_ok=True)

    output_mp3 = os.path.join(output_dir, f"{timestamp}.mp3")
    output_md = os.path.join(output_dir, f"{timestamp}.md")
    output_json = os.path.join(output_dir, f"{timestamp}.json")

    # 5. ffmpeg Subprocess Call
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(start_time),
        "-i", file_path,
        "-t", str(duration),
        "-c", "copy",
        output_mp3
    ]

    logger.info(f"Executing ffmpeg: {' '.join(ffmpeg_cmd)}")
    try:
        proc = subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)

        # If -c copy fails (e.g., input audio is AAC/m4b and output is .mp3), fallback to mp3 re-encoding
        if proc.returncode != 0 or not os.path.exists(output_mp3) or os.path.getsize(output_mp3) == 0:
            logger.warning(f"ffmpeg -c copy failed (code {proc.returncode}). Retrying with mp3 re-encoding...")
            fallback_cmd = [
                "ffmpeg",
                "-y",
                "-ss", str(start_time),
                "-i", file_path,
                "-t", str(duration),
                "-vn",
                "-c:a", "libmp3lame",
                "-q:a", "2",
                output_mp3
            ]
            proc2 = subprocess.run(fallback_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            if proc2.returncode != 0:
                logger.error(f"ffmpeg fallback failed: {proc2.stderr}")
                raise HTTPException(
                    status_code=500,
                    detail=f"ffmpeg audio extraction failed: {proc2.stderr[-300:] if proc2.stderr else 'Unknown error'}"
                )
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="ffmpeg is not installed or not found on the host system PATH")

    # 6. Transcription (faster-whisper primary with Vosk backup)
    transcript_body = ""
    engine_used = "faster-whisper"
    try:
        whisper = get_whisper_model()
        logger.info(f"Transcribing {output_mp3} with faster-whisper ({WHISPER_MODEL_NAME})...")
        segments, _ = whisper.transcribe(output_mp3, beam_size=5)
        text_segments = [segment.text.strip() for segment in segments]
        transcript_body = " ".join(text_segments).strip()
        logger.info(f"Transcription complete: {len(transcript_body)} characters")
    except Exception as whisper_err:
        logger.warning(f"faster-whisper transcription failed ({whisper_err}). Attempting Vosk backup...")
        try:
            transcript_body = transcribe_with_vosk(output_mp3)
            engine_used = "vosk"
            logger.info(f"Vosk backup transcription complete: {len(transcript_body)} characters")
        except Exception as vosk_err:
            logger.error(f"Transcription failed on both engines: Whisper ({whisper_err}), Vosk ({vosk_err})")
            transcript_body = f"[Transcription failed: Whisper ({str(whisper_err)}); Vosk ({str(vosk_err)})]"
            engine_used = "failed"

    # 7. Format Metadata Header & Write Markdown file with YAML frontmatter
    # Metadata included at start of text:
    # - date / time (of bookmarking)
    # - book title: sub-title (if any)
    # - author(s) name
    # - bookmarked duration in HH:MM:SS (SSSS seconds) format
    # - snippet length
    # - Chapter number/name (if available)
    # - transcribed text
    formatted_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bookmarked_duration_formatted = format_bookmarked_duration(current_time)
    snippet_length_formatted = f"{int(round(duration))} seconds"
    chapter_display = chapter_name if (chapter_name and chapter_name != "Unknown Chapter") else "N/A"

    meta_header = (
        f"- Date / Time: {formatted_datetime}\n"
        f"- Book Title: {full_book_title}\n"
        f"- Author(s): {author}\n"
        f"- Bookmarked Duration: {bookmarked_duration_formatted}\n"
        f"- Snippet Length: {snippet_length_formatted}\n"
        f"- Chapter: {chapter_display}"
    )
    full_transcript = f"{meta_header}\n\n{transcript_body}"

    md_content = f"""---
title: "{full_book_title}"
author: "{author}"
chapter: "{chapter_display}"
timestamp: "{timestamp}"
date_time: "{formatted_datetime}"
current_time: {current_time}
bookmarked_duration: "{bookmarked_duration_formatted}"
start_time: {start_time}
duration: {duration}
snippet_length: "{snippet_length_formatted}"
library_item_id: "{library_item_id}"
user_id: "{user_id}"
username: "{username}"
transcription_engine: "{engine_used}"
---

# {full_book_title}

{meta_header}

---

## Transcribed Text

{transcript_body}
"""
    with open(output_md, "w", encoding="utf-8") as f:
        f.write(md_content)

    # 8. Write JSON metadata file for Android app sync and quick indexing
    meta_content = {
        "id": f"{safe_book_title}-{timestamp}",
        "book_title": full_book_title,
        "author": author,
        "chapter": chapter_display,
        "timestamp": timestamp,
        "date_time": formatted_datetime,
        "start_time": start_time,
        "current_time": current_time,
        "bookmarked_duration": bookmarked_duration_formatted,
        "duration": duration,
        "snippet_length": snippet_length_formatted,
        "library_item_id": library_item_id,
        "user_id": user_id,
        "username": username,
        "transcript": full_transcript,
        "raw_transcript": transcript_body,
        "audio_url": f"/bookmarks/{safe_username}/{safe_book_title}/{timestamp}.mp3",
        "md_url": f"/bookmarks/{safe_username}/{safe_book_title}/{timestamp}.md",
        "created_at": formatted_datetime,
        "transcription_engine": engine_used
    }
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(meta_content, f, indent=2)

    return {
        "status": "success",
        "message": "Bookmark audio extracted and transcribed successfully",
        "user": {
            "id": user_id,
            "username": username,
            "folder": f"{safe_username}/bookmarks"
        },
        "snippet": {
            "id": f"{safe_book_title}-{timestamp}",
            "book_title": full_book_title,
            "author": author,
            "chapter": chapter_display,
            "timestamp": timestamp,
            "date_time": formatted_datetime,
            "start_time": start_time,
            "current_time": current_time,
            "bookmarked_duration": bookmarked_duration_formatted,
            "duration": duration,
            "snippet_length": snippet_length_formatted,
            "mp3_file": output_mp3,
            "md_file": output_md,
            "transcript": full_transcript,
            "raw_transcript": transcript_body,
            "audio_url": f"/bookmarks/{safe_username}/{safe_book_title}/{timestamp}.mp3",
            "md_url": f"/bookmarks/{safe_username}/{safe_book_title}/{timestamp}.md"
        }
    }


@app.get("/api/user/bookmarks")
@app.get("/api/snippets")
async def get_user_bookmarks(
    raw_token: str = Depends(extract_token_flexible)
):
    """
    JSON API endpoint callable by the Native Android Kotlin app and Web UI.
    Returns all bookmarks, clips, and transcripts belonging strictly to the authenticated user.
    """
    user = validate_abs_token(raw_token)
    username = user["username"]
    safe_username = sanitize_filename(username)
    user_id = user["id"]

    user_bookmarks_dir = os.path.join(VOLUME_DIR, safe_username, "bookmarks")
    bookmarks = []

    # Read from {username}/bookmarks/{book_title}/*
    if os.path.isdir(user_bookmarks_dir):
        for book_dir in sorted(os.listdir(user_bookmarks_dir)):
            full_book_path = os.path.join(user_bookmarks_dir, book_dir)
            if not os.path.isdir(full_book_path):
                continue

            for fname in sorted(os.listdir(full_book_path), reverse=True):
                if fname.endswith(".md"):
                    base_name = fname[:-3]
                    md_path = os.path.join(full_book_path, fname)
                    mp3_path = os.path.join(full_book_path, f"{base_name}.mp3")
                    json_path = os.path.join(full_book_path, f"{base_name}.json")

                    metadata = {}
                    if os.path.exists(json_path):
                        try:
                            with open(json_path, "r", encoding="utf-8") as jf:
                                metadata = json.load(jf)
                        except Exception:
                            pass

                    if not metadata:
                        try:
                            with open(md_path, "r", encoding="utf-8") as f:
                                raw_md = f.read()
                            parsed = parse_frontmatter(raw_md)
                            metadata = {
                                "book_title": parsed.get("title") or book_dir.replace("_", " "),
                                "author": parsed.get("author") or "Unknown Author",
                                "chapter": parsed.get("chapter") or "",
                                "start_time": float(parsed.get("start_time") or 0.0),
                                "duration": int(parsed.get("duration") or 60),
                                "transcript": parsed.get("body", "").split("## Transcript", 1)[-1].strip()
                            }
                        except Exception:
                            metadata = {"book_title": book_dir, "transcript": ""}

                    has_mp3 = os.path.exists(mp3_path)
                    transcript_text = metadata.get("transcript", "")
                    if transcript_text and "- Date / Time:" not in transcript_text and "Date / Time:" not in transcript_text:
                        date_str = metadata.get("date_time") or metadata.get("created_at") or base_name
                        cur_t = metadata.get("current_time", metadata.get("start_time", 0.0))
                        b_dur = metadata.get("bookmarked_duration") or format_bookmarked_duration(cur_t)
                        s_len = metadata.get("snippet_length") or f"{metadata.get('duration', 60)} seconds"
                        ch_str = metadata.get("chapter") or "N/A"
                        header = (
                            f"- Date / Time: {date_str}\n"
                            f"- Book Title: {metadata.get('book_title') or book_dir}\n"
                            f"- Author(s): {metadata.get('author') or 'Unknown Author'}\n"
                            f"- Bookmarked Duration: {b_dur}\n"
                            f"- Snippet Length: {s_len}\n"
                            f"- Chapter: {ch_str}\n\n"
                        )
                        transcript_text = f"{header}{transcript_text}"

                    bookmarks.append({
                        "id": f"{book_dir}-{base_name}",
                        "book_title": metadata.get("book_title") or book_dir,
                        "author": metadata.get("author") or "Unknown Author",
                        "chapter": metadata.get("chapter") or "",
                        "timestamp": base_name,
                        "start_time": metadata.get("start_time", 0.0),
                        "duration": metadata.get("duration", 60),
                        "transcript": transcript_text,
                        "audio_url": f"/bookmarks/{safe_username}/{book_dir}/{base_name}.mp3" if has_mp3 else None,
                        "md_url": f"/bookmarks/{safe_username}/{book_dir}/{fname}",
                        "username": username,
                        "created_at": metadata.get("created_at") or base_name
                    })

    # Backward compatibility: check legacy /data/{user_id}/ folder if empty
    if len(bookmarks) == 0:
        legacy_dir = os.path.join(VOLUME_DIR, user_id)
        if os.path.isdir(legacy_dir):
            for book_dir in sorted(os.listdir(legacy_dir)):
                full_book_path = os.path.join(legacy_dir, book_dir)
                if not os.path.isdir(full_book_path):
                    continue
                for fname in sorted(os.listdir(full_book_path), reverse=True):
                    if fname.endswith(".md"):
                        base_name = fname[:-3]
                        md_path = os.path.join(full_book_path, fname)
                        mp3_path = os.path.join(full_book_path, f"{base_name}.mp3")
                        try:
                            with open(md_path, "r", encoding="utf-8") as f:
                                raw_md = f.read()
                            parsed = parse_frontmatter(raw_md)
                            t_body = parsed.get("body", "").split("## Transcript", 1)[-1].strip()
                        except Exception:
                            parsed = {}
                            t_body = ""

                        if t_body and "- Date / Time:" not in t_body and "Date / Time:" not in t_body:
                            cur_t = float(parsed.get("start_time") or 0.0)
                            b_dur = format_bookmarked_duration(cur_t)
                            s_len = f"{int(parsed.get('duration') or 60)} seconds"
                            ch_str = parsed.get("chapter") or "N/A"
                            header = (
                                f"- Date / Time: {parsed.get('timestamp') or base_name}\n"
                                f"- Book Title: {parsed.get('title') or book_dir}\n"
                                f"- Author(s): {parsed.get('author') or 'Unknown Author'}\n"
                                f"- Bookmarked Duration: {b_dur}\n"
                                f"- Snippet Length: {s_len}\n"
                                f"- Chapter: {ch_str}\n\n"
                            )
                            t_body = f"{header}{t_body}"

                        has_mp3 = os.path.exists(mp3_path)
                        bookmarks.append({
                            "id": f"{book_dir}-{base_name}",
                            "book_title": parsed.get("title") or book_dir,
                            "author": parsed.get("author") or "Unknown Author",
                            "chapter": parsed.get("chapter") or "",
                            "timestamp": base_name,
                            "start_time": float(parsed.get("start_time") or 0.0),
                            "duration": int(parsed.get("duration") or 60),
                            "transcript": t_body,
                            "audio_url": f"/snippets/{user_id}/{book_dir}/{base_name}.mp3" if has_mp3 else None,
                            "md_url": f"/snippets/{user_id}/{book_dir}/{fname}",
                            "username": username,
                            "created_at": base_name
                        })

    return {
        "status": "success",
        "username": username,
        "count": len(bookmarks),
        "bookmarks": bookmarks
    }


# --- Static Audio & Markdown File Serving ---

@app.get("/bookmarks/{username}/{book_title}/{filename}")
@app.get("/snippets/{username}/{book_title}/{filename}")
async def serve_bookmark_file(username: str, book_title: str, filename: str):
    """
    Serves the generated MP3 audio clip or Markdown transcript.
    Supports HTTP Range requests so mobile players (Android Kotlin ExoPlayer/MediaPlayer) can stream audio smoothly.
    """
    safe_username = sanitize_filename(username)
    safe_book_title = sanitize_filename(book_title)
    safe_filename = os.path.basename(filename)

    # Primary location: {VOLUME_DIR}/{username}/bookmarks/{book_title}/{filename}
    file_path = os.path.join(VOLUME_DIR, safe_username, "bookmarks", safe_book_title, safe_filename)

    # Fallback 1: {VOLUME_DIR}/{username}/{book_title}/{filename}
    if not os.path.isfile(file_path):
        file_path = os.path.join(VOLUME_DIR, safe_username, safe_book_title, safe_filename)

    # Fallback 2: {VOLUME_DIR}/snippets/{username}/{book_title}/{filename}
    if not os.path.isfile(file_path):
        file_path = os.path.join(VOLUME_DIR, "snippets", safe_username, safe_book_title, safe_filename)

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Requested audio or transcript file was not found")

    media_type = "audio/mpeg" if safe_filename.endswith(".mp3") else ("application/json" if safe_filename.endswith(".json") else "text/markdown")
    response = FileResponse(
        file_path,
        media_type=media_type,
        filename=safe_filename
    )
    response.headers["Accept-Ranges"] = "bytes"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


# --- Embedded Web Dashboard ---

@app.get("/", response_class=HTMLResponse)
async def web_dashboard(
    request: Request,
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None)
):
    """
    Expose GET / serving HTML dashboard for the authenticated user,
    listing all bookmarks in their {username}/bookmarks directory.
    """
    auth_token = None
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            auth_token = parts[1]
        elif len(parts) == 1:
            auth_token = parts[0]

    if not auth_token and token:
        auth_token = token
    if not auth_token:
        auth_token = request.cookies.get("abs_token")

    user = None
    error_msg = None

    if auth_token:
        try:
            user = validate_abs_token(auth_token)
        except HTTPException as e:
            error_msg = e.detail
            auth_token = None

    snippets = []
    if user:
        safe_username = sanitize_filename(user["username"])
        user_bookmarks_dir = os.path.join(VOLUME_DIR, safe_username, "bookmarks")

        # Fallback to user_id folder if bookmarks dir does not yet exist
        scan_dir = user_bookmarks_dir if os.path.isdir(user_bookmarks_dir) else os.path.join(VOLUME_DIR, user["id"])

        if os.path.isdir(scan_dir):
            for book_dir in sorted(os.listdir(scan_dir)):
                full_book_path = os.path.join(scan_dir, book_dir)
                if not os.path.isdir(full_book_path):
                    continue

                for fname in sorted(os.listdir(full_book_path), reverse=True):
                    if fname.endswith(".md"):
                        base_name = fname[:-3]
                        md_path = os.path.join(full_book_path, fname)
                        mp3_path = os.path.join(full_book_path, f"{base_name}.mp3")

                        try:
                            with open(md_path, "r", encoding="utf-8") as f:
                                raw_md = f.read()
                            parsed = parse_frontmatter(raw_md)
                        except Exception:
                            parsed = {"body": ""}

                        created_time = base_name
                        try:
                            mtime = os.path.getmtime(md_path)
                            created_time = datetime.fromtimestamp(mtime).strftime("%b %d, %Y %I:%M %p")
                        except Exception:
                            pass

                        transcript_text = parsed.get("body", "")
                        if "## Transcript" in transcript_text:
                            transcript_text = transcript_text.split("## Transcript", 1)[1].strip()

                        has_mp3 = os.path.exists(mp3_path)
                        snippets.append({
                            "title": parsed.get("title") or book_dir.replace("_", " "),
                            "author": parsed.get("author") or "Unknown Author",
                            "chapter": parsed.get("chapter") or "",
                            "timestamp": parsed.get("timestamp") or base_name,
                            "created_at_str": created_time,
                            "duration": parsed.get("duration", "60"),
                            "transcript": transcript_text,
                            "audio_url": f"/bookmarks/{safe_username}/{book_dir}/{base_name}.mp3" if has_mp3 else None,
                            "md_url": f"/bookmarks/{safe_username}/{book_dir}/{fname}"
                        })

    response = templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user": user,
            "token": auth_token or "",
            "abs_server_url": ABS_SERVER_URL,
            "snippets": snippets,
            "error": error_msg
        }
    )

    if user and auth_token and not request.cookies.get("abs_token"):
        response.set_cookie(key="abs_token", value=auth_token, httponly=True, samesite="lax", max_age=86400 * 30)

    return response


@app.get("/logout")
async def logout():
    """Clear session cookie and redirect to home."""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key="abs_token")
    return response


@app.get("/api/health")
async def health_check():
    """Health check endpoint providing configuration and system status."""
    return {
        "status": "healthy",
        "service": "Audiobookshelf Bookmarks Extractor",
        "tagline": "Backend app for the bookmarks you create on ABS Mobile app.",
        "abs_server_url": ABS_SERVER_URL,
        "volume_dir": VOLUME_DIR,
        "whisper_model": WHISPER_MODEL_NAME,
        "whisper_device": WHISPER_DEVICE,
        "time": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "13379"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
