"""
Audiobookshelf (ABS) Snippet Sidecar
Backend app for the bookmarks you create on ABS Mobile app.
Extracts audio clips via ffmpeg, transcribes speech with faster-whisper,
and manages per-user bookmarks and snippets under {username}/bookmarks.
"""

import os
import sys
import re
import json
import shutil
import asyncio
import subprocess
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

try:
    import httpx
except ImportError:
    httpx = None

try:
    import websockets
except ImportError:
    websockets = None

import requests
from starlette.websockets import WebSocket, WebSocketDisconnect
from fastapi import FastAPI, Request, Header, HTTPException, Depends, Query, Response
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Configure logging (stream to sys.stdout so standard INFO logs are routed to pm2 out.log)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
logger = logging.getLogger("abs-sidecar")

# Base directory of the repository (resolves safely regardless of execution directory)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

# Automatically load settings from .env file if present in base directory
env_file = os.path.join(BASE_DIR, ".env")
if os.path.exists(env_file):
    try:
        with open(env_file, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    _k = _k.strip()
                    _v = _v.strip().strip('"').strip("'")
                    if _k not in os.environ:
                        os.environ[_k] = _v
    except Exception as _e:
        logger.warning(f"Could not parse .env file: {_e}")

# Configuration from Environment
ABS_TARGET_SERVER = (
    os.environ.get("ABS_TARGET_SERVER")
    or os.environ.get("ABS_INTERNAL_URL")
    or os.environ.get("ABS_SERVER_URL")
    or "http://localhost:13378"
).rstrip("/")
ABS_SERVER_URL = ABS_TARGET_SERVER  # Maintained for backwards compatibility

# Primary VOLUME_DIR with fallback to Pi and Docker default locations
VOLUME_DIR = (
    os.environ.get("VOLUME_DIR")
    or os.environ.get("SNIPPETS_DIR")
    or ("/srv/ssd/Appdata/local/advplyr-bookshelf/bookmarks" if os.path.isdir("/srv/ssd/Appdata/local/advplyr-bookshelf/bookmarks") else "/data")
).rstrip("/")
SNIPPETS_DIR = VOLUME_DIR  # Kept for backward compatibility
WHISPER_MODEL_NAME = os.environ.get("WHISPER_MODEL", "base.en")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
SNIPPET_DURATION = int(os.environ.get("SNIPPET_DURATION", "60"))
SNIPPET_PRE_ROLL = float(os.environ.get("SNIPPET_PRE_ROLL", "30.0"))
AUDIOBOOKS_PATH = os.environ.get("AUDIOBOOKS_PATH", "").strip().rstrip("/")
PATH_MAPPINGS = os.environ.get("PATH_MAPPINGS", "").strip()

# Ensure main volume directory exists
try:
    os.makedirs(VOLUME_DIR, exist_ok=True)
except Exception as _e:
    logger.warning(f"Could not create VOLUME_DIR {VOLUME_DIR}: {_e}")


def get_candidate_volume_dirs() -> List[str]:
    """
    Returns an ordered list of candidate directories where user bookmarks may reside.
    Ensures seamless discovery across Raspberry Pi, Docker, and customized mount paths.
    """
    dirs = []
    if VOLUME_DIR and VOLUME_DIR not in dirs:
        dirs.append(VOLUME_DIR)
    for p in [
        "/srv/ssd/Appdata/local/advplyr-bookshelf/bookmarks",
        "/srv/ssd/Bookshelf/advplyr-bookshelf/bookmarks",
        "/srv/ssd/Appdata/local/Audiobookshelf-Bookmarks-Extractor/bookmarks",
        "/srv/ssd/Appdata/local/advplyr-bookshelf",
        "/srv/ssd/Bookshelf",
        "/data",
        "/bookmarks"
    ]:
        if p not in dirs:
            dirs.append(p)
    return dirs


def map_container_path_to_host(container_path: str, book_title: Optional[str] = None) -> str:
    """
    Translates an Audiobookshelf Docker container path (e.g. /audiobooks/... or /summaries/...)
    to the real host filesystem path when running the sidecar outside Docker (e.g. via PM2 or systemd).

    Resolves paths in order:
    1. Direct host path existence check.
    2. Explicit PATH_MAPPINGS (comma-separated 'container:host', e.g. '/audiobooks:/srv/ssd/Bookshelf/Audiobooks,/summaries:/srv/ssd/Bookshelf/Summaries').
    3. AUDIOBOOKS_PATH environment variable (e.g. '/srv/ssd/Bookshelf/Audiobooks').
    4. Auto-discovery from VOLUME_DIR ancestors and common media/storage root folders.
    5. Filename match under candidate libraries.
    """
    if not container_path:
        return container_path

    # 1. Direct host existence
    if os.path.exists(container_path):
        return container_path

    # 2. Build mapping table from PATH_MAPPINGS & AUDIOBOOKS_PATH
    mappings: Dict[str, str] = {}
    if PATH_MAPPINGS:
        for pair in PATH_MAPPINGS.split(","):
            if ":" in pair:
                c_p, h_p = pair.split(":", 1)
                mappings[c_p.strip().rstrip("/")] = h_p.strip().rstrip("/")

    if AUDIOBOOKS_PATH and "/audiobooks" not in mappings:
        mappings["/audiobooks"] = AUDIOBOOKS_PATH

    for c_prefix, h_prefix in mappings.items():
        if container_path == c_prefix or container_path.startswith(c_prefix + "/"):
            mapped = h_prefix + container_path[len(c_prefix):]
            if os.path.exists(mapped):
                logger.info(f"Mapped container path '{container_path}' -> '{mapped}' (via PATH_MAPPINGS)")
                return mapped

    # 3. Intelligent auto-discovery from VOLUME_DIR and host directory structure
    candidate_roots = []
    if AUDIOBOOKS_PATH:
        candidate_roots.append(AUDIOBOOKS_PATH)

    # Derive ancestor directories from VOLUME_DIR (e.g. /srv/ssd/Bookshelf/advplyr-bookshelf/bookmarks -> /srv/ssd/Bookshelf)
    v_dir = os.path.abspath(VOLUME_DIR)
    curr = v_dir
    for _ in range(4):
        curr = os.path.dirname(curr)
        if curr and curr != "/":
            candidate_roots.append(curr)

    candidate_roots.extend([
        "/srv/ssd/Bookshelf",
        "/srv/ssd/Bookshelf/Audiobooks",
        "/srv/ssd/Bookshelf/Summaries",
        "/srv/ssd",
        "/srv",
        "/mnt",
        "/media",
        "/volume1",
        "/data"
    ])

    clean_subpath = container_path.lstrip("/")
    parts = clean_subpath.split("/", 1)
    first_part = parts[0] if parts else ""
    remaining_subpath = parts[1] if len(parts) > 1 else clean_subpath

    container_prefixes = ["audiobooks", "summaries", "podcasts", "books", "calibre", "ebooks", "media"]

    for root in candidate_roots:
        if not os.path.isdir(root):
            continue

        # Option A: root + container subpath (e.g. /srv/ssd/Bookshelf + Audiobooks/...)
        test_a = os.path.join(root, clean_subpath)
        if os.path.exists(test_a):
            logger.info(f"Auto-discovered audio file at '{test_a}' (matched clean subpath)")
            return test_a

        # Option B: root + capitalized/varied prefix (e.g. /srv/ssd/Bookshelf + /Audiobooks/The Spike/...)
        if first_part.lower() in container_prefixes:
            for variant in [first_part, first_part.capitalize(), first_part.lower(), "Audiobooks", "Summaries"]:
                test_b = os.path.join(root, variant, remaining_subpath)
                if os.path.exists(test_b):
                    logger.info(f"Auto-discovered audio file at '{test_b}' (matched folder '{variant}')")
                    return test_b

        # Option C: root + remaining_subpath directly (if root is already the audiobooks folder)
        test_c = os.path.join(root, remaining_subpath)
        if os.path.exists(test_c):
            logger.info(f"Auto-discovered audio file at '{test_c}'")
            return test_c

    # 4. Search by filename inside candidate library roots
    filename = os.path.basename(container_path)
    if filename:
        for search_base in [AUDIOBOOKS_PATH, "/srv/ssd/Bookshelf/Audiobooks", "/srv/ssd/Bookshelf/Summaries", "/srv/ssd/Bookshelf"]:
            if search_base and os.path.isdir(search_base):
                for dirpath, _, filenames in os.walk(search_base):
                    if filename in filenames:
                        found = os.path.join(dirpath, filename)
                        logger.info(f"Found audio file by filename search: '{found}'")
                        return found

    # Fallback: if AUDIOBOOKS_PATH is set and container path starts with /audiobooks/, return mapped path
    if AUDIOBOOKS_PATH and container_path.startswith("/audiobooks/"):
        return AUDIOBOOKS_PATH + container_path[len("/audiobooks"):]

    return container_path


# Templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# FastAPI App
app = FastAPI(
    title="Audiobookshelf Bookmarks Extractor & Transparent Proxy",
    description="Backend app for the bookmarks you create on ABS Mobile app (Transparent Audiobookshelf v1.5 Proxy).",
    version="1.5"
)

# Global session cache so background workers and bookmark extractors have access to authenticated credentials
_last_authenticated_session: Dict[str, Any] = {
    "token": None,
    "user": None,
    "time": None
}

@app.on_event("startup")
async def startup_event():
    """Pre-warm Whisper model asynchronously on server startup to avoid first-request download lag."""
    def _warmup():
        try:
            get_whisper_model()
        except Exception as e:
            logger.warning(f"Whisper background pre-warm encountered: {e}")
    asyncio.create_task(asyncio.to_thread(_warmup))

# Enable CORS so native mobile apps (iOS / Android), WebViews, and external clients can call endpoints directly
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


def get_ffmpeg_bin() -> str:
    """
    Finds the ffmpeg executable across system PATH, standard Unix paths,
    or optional portable Python binary (handles restricted PM2/service PATH).
    """
    # 1. System PATH
    bin_path = shutil.which("ffmpeg")
    if bin_path:
        return bin_path

    # 2. Standard Linux/macOS binary paths
    common_paths = [
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/bin/ffmpeg",
        "/opt/homebrew/bin/ffmpeg",
        "/snap/bin/ffmpeg",
        os.path.join(BASE_DIR, "bin", "ffmpeg"),
        os.path.join(os.path.expanduser("~"), "bin", "ffmpeg"),
    ]
    for p in common_paths:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p

    # 3. Check if imageio_ffmpeg is installed
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except Exception:
        pass

    raise RuntimeError(
        "ffmpeg is not installed or not found on the host system PATH. "
        "Please install ffmpeg on your host system: sudo apt update && sudo apt install -y ffmpeg"
    )


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
        ffmpeg_bin = get_ffmpeg_bin()
        cmd = [
            ffmpeg_bin, "-y", "-i", audio_file_path,
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


_last_known_abs_server: Optional[str] = None

def resolve_abs_server_url(
    req_url: Optional[str] = None,
    header_url: Optional[str] = None,
    query_url: Optional[str] = None
) -> str:
    """
    Dynamically resolve Audiobookshelf server URL.
    The configured ABS_TARGET_SERVER (internal address like http://127.0.0.1:13378)
    is the authoritative upstream target for the sidecar proxy.
    This prevents recursive loops when external clients provide their public URL (e.g. https://abs.example.com).
    """
    # 1. Authoritative internal configuration:
    # If ABS_TARGET_SERVER is configured on this host (e.g. 127.0.0.1, localhost, LAN IP, or Docker service),
    # ALWAYS use it as the upstream target. This ensures the sidecar connects directly to Audiobookshelf
    # on the internal network and never loops back through the external reverse proxy.
    configured = (ABS_TARGET_SERVER or ABS_SERVER_URL or "http://127.0.0.1:13378").strip().rstrip("/")
    if configured and not (configured.startswith("http://") or configured.startswith("https://")):
        configured = f"http://{configured}"

    is_internal = any(
        k in configured.lower()
        for k in ["localhost", "127.0.0.1", "0.0.0.0", "192.168.", "10.", "172.", "audiobookshelf", "host.docker.internal"]
    )
    if is_internal:
        return configured

    # 2. If ABS_TARGET_SERVER was not an internal address, check explicit client parameters
    explicit = req_url or header_url or query_url
    if explicit:
        clean_exp = str(explicit).strip().rstrip("/")
        if clean_exp and not (clean_exp.startswith("http://") or clean_exp.startswith("https://")):
            clean_exp = f"http://{clean_exp}"
        return clean_exp

    return configured or "http://127.0.0.1:13378"


def extract_authors(meta: Any, fallback: str = "Unknown Author") -> str:
    """
    Safely extract author names from Audiobookshelf metadata.
    Handles arrays of author dicts [{'name': '...'}], arrays of strings, single strings, or dicts.
    Prevents '[object Object]' or Python dict dumps in metadata and API responses.
    """
    if not meta:
        return fallback

    if isinstance(meta, str) and meta.strip():
        return meta.strip()

    if isinstance(meta, list):
        names = []
        for item in meta:
            if isinstance(item, str) and item.strip():
                names.append(item.strip())
            elif isinstance(item, dict):
                n = item.get("name") or item.get("author") or item.get("displayName") or item.get("authorName")
                if n and str(n).strip():
                    names.append(str(n).strip())
        if names:
            return ", ".join(names)

    if isinstance(meta, dict):
        an = meta.get("authorName")
        if isinstance(an, str) and an.strip():
            return an.strip()

        authors_field = meta.get("authors")
        if authors_field:
            res = extract_authors(authors_field, fallback="")
            if res:
                return res

        author_field = meta.get("author")
        if author_field:
            res = extract_authors(author_field, fallback="")
            if res:
                return res

        disp = meta.get("displayAuthor")
        if isinstance(disp, str) and disp.strip():
            return disp.strip()

    return fallback


def validate_abs_token(token: str, server_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Validate the Bearer token with Audiobookshelf via GET {target_server}/api/me.
    Uses the dynamically provided server_url if passed, falling back to ABS_SERVER_URL.
    Returns user dict with id and username.
    """
    target_server = resolve_abs_server_url(req_url=server_url)

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
        url = f"{target_server}/api/me"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"ABS token validation failed with status {resp.status_code} at {target_server}")
            raise HTTPException(
                status_code=401,
                detail=f"Invalid or expired Audiobookshelf Bearer token (HTTP {resp.status_code} from {target_server})"
            )

        data = resp.json()
        user_info = data.get("user") if isinstance(data.get("user"), dict) else data

        user_id = user_info.get("id")
        username = user_info.get("username") or user_info.get("name") or "abs_user"

        if not user_id:
            raise HTTPException(status_code=401, detail="Failed to retrieve user ID from Audiobookshelf response")

        res_user = {
            "id": str(user_id),
            "username": str(username),
            "raw_token": token,
            "mediaProgress": user_info.get("mediaProgress") or [],
            "server_url": target_server
        }

        # Cache session globally so background workers can resolve metadata even if headers are absent
        global _last_authenticated_session
        _last_authenticated_session = {
            "token": token,
            "user": res_user,
            "time": datetime.now()
        }

        return res_user
    except requests.exceptions.RequestException as e:
        logger.error(f"Error communicating with Audiobookshelf at {target_server}: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Cannot connect to Audiobookshelf server at {target_server}: {str(e)}"
        )


def extract_token_from_request(request: Request, body_bytes: bytes = b"") -> Optional[str]:
    """
    Extracts authentication token from any possible location:
    Headers, Cookies, Query Params, or Request Body.
    """
    # 1. Authorization header (Bearer or raw token)
    auth = request.headers.get("authorization")
    if auth:
        parts = auth.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        elif len(parts) == 1:
            return parts[0].strip()
        else:
            return auth.strip()

    # 2. Other common custom headers
    for h in ["x-abs-token", "x-token", "x-api-key", "token", "apikey"]:
        val = request.headers.get(h)
        if val:
            return val.strip()

    # 3. Cookies
    for c in ["abs_token", "token", "session", "connect.sid"]:
        val = request.cookies.get(c)
        if val:
            return val.strip()

    # 4. Query params
    for q in ["token", "apiKey", "api_key"]:
        val = request.query_params.get(q)
        if val:
            return val.strip()

    # 5. Body payload
    if body_bytes:
        try:
            body_json = json.loads(body_bytes.decode("utf-8"))
            if isinstance(body_json, dict):
                for k in ["token", "abs_token", "apiKey", "api_key"]:
                    if body_json.get(k):
                        return str(body_json[k]).strip()
        except Exception:
            pass

    return None


async def extract_token_flexible(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_abs_token: Optional[str] = Header(None, alias="X-ABS-Token"),
    token: Optional[str] = Query(None),
    api_key: Optional[str] = Query(None, alias="apiKey")
) -> str:
    """
    Flexible token extractor callable by:
    - Mobile apps and API clients (Authorization: Bearer <TOKEN> or X-ABS-Token header)
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
    Accepts snake_case and camelCase parameters for compatibility with mobile, scripts, and Web clients.
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
    server_url: Optional[str] = None
    serverUrl: Optional[str] = None
    abs_server_url: Optional[str] = None
    absServerUrl: Optional[str] = None


def format_bookmarked_duration(seconds: float) -> str:
    """Format duration into HH:MM:SS (SSSS seconds) format."""
    total_sec = int(round(seconds))
    hrs = total_sec // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    return f"{hrs:02d}:{mins:02d}:{secs:02d} ({total_sec} seconds)"


def resolve_audio_target(
    token: str,
    req: Optional[SnippetRequest] = None,
    user_info: Optional[Dict[str, Any]] = None,
    server_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Resolve the target audio file, timestamp, and book metadata.
    Handles:
    1. Direct bookmark extraction (if bookmark_id or bookmarkId is provided)
    2. Explicit offset or libraryItemId
    3. Active listening sessions from GET /api/me/listening-sessions
    4. Fallback to latest mediaProgress from GET /api/me if listening session has timed out
    """
    target_server = resolve_abs_server_url(
        req_url=server_url or (req.server_url if req else None) or (req.serverUrl if req else None) or (req.abs_server_url if req else None) or (req.absServerUrl if req else None)
    )

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
            b_url = f"{target_server}/api/me/bookmarks"
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
        sessions_url = f"{target_server}/api/me/listening-sessions"
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
                author = extract_authors(media_meta, author)

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
                me_res = requests.get(f"{target_server}/api/me", headers=headers, timeout=10)
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
    item_url = f"{target_server}/api/items/{library_item_id}?expanded=1"
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
                author = extract_authors(meta, author)

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

    # Translate Docker container path (/audiobooks/...) to host system path
    host_file_path = map_container_path_to_host(file_path, book_title=book_title)

    # Derive direct HTTP stream URL as fallback if file is not accessible on local disk
    stream_url = None
    if library_item_id and target_server:
        file_ino = None
        if 'selected_file' in locals() and selected_file:
            file_ino = selected_file.get("ino") or selected_file.get("id")
        if file_ino:
            stream_url = f"{target_server}/api/items/{library_item_id}/file/{file_ino}"
        else:
            stream_url = f"{target_server}/api/items/{library_item_id}/download"

    return {
        "libraryItemId": library_item_id,
        "currentTime": current_time,
        "file_path": host_file_path,
        "raw_container_path": file_path,
        "stream_url": stream_url,
        "book_title": book_title,
        "subtitle": subtitle,
        "author": author,
        "chapter_name": chapter_name,
        "startOffset": af_start if 'af_start' in locals() else 0.0
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


# --- Core Audio Extraction & Transcription Logic (Thread-Safe & Shared) ---

def process_bookmark_extraction(
    library_item_id: Optional[str] = None,
    bookmark_data: Optional[Dict[str, Any]] = None,
    auth_token: Optional[str] = None,
    server_url: Optional[str] = None,
    duration: Optional[int] = None,
    snippet_request: Optional[SnippetRequest] = None,
    user_info: Optional[Dict[str, Any]] = None,
    custom_start: Optional[float] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Core extraction function that handles audio clipping (ffmpeg), speech transcription
    (faster-whisper with Vosk fallback), and snippet metadata generation/storage.

    Called synchronously by manual UI/API endpoints and asynchronously by the
    middleware bookmark interceptor background worker.
    """
    # 1. Resolve auth token and server URL if attached to bookmark data
    if bookmark_data and not auth_token:
        auth_token = bookmark_data.get("_auth_token") or bookmark_data.get("auth_token") or bookmark_data.get("token")
    if bookmark_data and not server_url:
        server_url = bookmark_data.get("_server_url") or bookmark_data.get("server_url")

    target_server = resolve_abs_server_url(req_url=server_url)

    # 2. Authenticate user against ABS server if not already provided
    user = user_info
    if not user and auth_token:
        try:
            user = validate_abs_token(auth_token, server_url=target_server)
        except Exception as e:
            logger.warning(f"Failed to authenticate token during bookmark extraction: {e}")

    # Fallback to cached authenticated session if available
    if not user and _last_authenticated_session.get("user"):
        user = _last_authenticated_session["user"]
        if not auth_token:
            auth_token = _last_authenticated_session.get("token")
        logger.info(f"Using cached authenticated user '{user.get('username')}' for bookmark extraction.")

    if not user:
        # Fallback to username from bookmark data if present
        fallback_username = (
            (bookmark_data.get("username") if bookmark_data else None)
            or (bookmark_data.get("user") if bookmark_data else None)
            or "ravi"
        )
        fallback_id = (bookmark_data.get("userId") if bookmark_data else None) or "default_user"
        user = {
            "id": str(fallback_id),
            "username": str(fallback_username),
            "raw_token": auth_token or ""
        }
        logger.warning(f"Defaulting user to '{fallback_username}' for bookmark extraction.")

    user_id = user["id"]
    username = user["username"]
    safe_username = sanitize_filename(username)

    effective_duration = duration or (snippet_request.duration if snippet_request else None) or SNIPPET_DURATION

    # 3. Build or normalize snippet request
    if snippet_request is None:
        b_id = bookmark_data.get("id") if bookmark_data else None
        b_time = None
        if bookmark_data:
            b_time = bookmark_data.get("time")
            if b_time is None:
                b_time = bookmark_data.get("start_time") or bookmark_data.get("startTime") or bookmark_data.get("offset")

        lib_id = library_item_id or (bookmark_data.get("libraryItemId") if bookmark_data else None)
        snippet_request = SnippetRequest(
            library_item_id=str(lib_id) if lib_id else None,
            start_time=float(b_time) if b_time is not None else None,
            bookmark_id=str(b_id) if b_id else None,
            duration=effective_duration,
            server_url=target_server
        )

    # 4. Resolve target audio file, book metadata, and timestamp
    session_state = resolve_audio_target(
        token=auth_token or user.get("raw_token") or "",
        req=snippet_request,
        user_info=user,
        server_url=target_server
    )
    current_time = session_state["currentTime"]
    file_path = session_state["file_path"]
    stream_url = session_state.get("stream_url")
    book_title = session_state["book_title"]
    subtitle = session_state.get("subtitle") or ""
    author = session_state["author"]
    chapter_name = session_state["chapter_name"]
    resolved_lib_item_id = session_state["libraryItemId"]
    start_offset = float(session_state.get("startOffset") or 0.0)

    # Combine book title and subtitle if applicable
    if subtitle and subtitle.strip() and subtitle.strip().lower() not in book_title.lower():
        full_book_title = f"{book_title}: {subtitle.strip()}"
    else:
        full_book_title = book_title

    # 5. Compute time window
    # For bookmark events, window is centered around the bookmark timestamp (e.g. -30s to +30s)
    if custom_start is not None:
        start_time = float(custom_start)
    elif snippet_request and (snippet_request.start_time is not None or snippet_request.startTime is not None) and not bookmark_data:
        start_time = float(snippet_request.start_time or snippet_request.startTime)
    else:
        file_relative_offset = max(0.0, current_time - start_offset)
        start_time = max(0.0, file_relative_offset - SNIPPET_PRE_ROLL)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 6. User-Specific Volume Folder Structure:
    # {VOLUME_DIR}/{username}/bookmarks/{safe_book_title}/
    safe_book_title = sanitize_filename(book_title)

    # Check candidate volume dirs to find where user's bookmarks already live, or use primary VOLUME_DIR
    target_base = VOLUME_DIR
    target_user_name = safe_username
    found_existing_user_dir = False

    for cand in get_candidate_volume_dirs():
        for u in [safe_username.lower(), safe_username]:
            check_path = os.path.join(cand, u, "bookmarks")
            if os.path.isdir(check_path):
                target_base = cand
                target_user_name = u
                found_existing_user_dir = True
                break
        if found_existing_user_dir:
            break

    output_dir = os.path.join(target_base, target_user_name, "bookmarks", safe_book_title)
    os.makedirs(output_dir, exist_ok=True)

    output_mp3 = os.path.join(output_dir, f"{timestamp}.mp3")
    output_md = os.path.join(output_dir, f"{timestamp}.md")
    output_json = os.path.join(output_dir, f"{timestamp}.json")

    # 7. ffmpeg Subprocess Call
    ffmpeg_bin = get_ffmpeg_bin()
    use_stream = False
    input_target = file_path

    if not os.path.exists(file_path):
        logger.warning(f"Audio file '{file_path}' was not found on local host disk.")
        if stream_url:
            logger.info(f"Fallback: Slicing audio directly from Audiobookshelf HTTP stream: {stream_url}")
            input_target = stream_url
            use_stream = True
        else:
            raise RuntimeError(
                f"Audio file '{file_path}' does not exist on host disk and no stream URL could be resolved. "
                f"Please verify AUDIOBOOKS_PATH or PATH_MAPPINGS in ecosystem.config.cjs."
            )

    if not use_stream:
        is_mp3_source = file_path.lower().endswith(".mp3")
        need_encoding = not is_mp3_source

        if is_mp3_source:
            ffmpeg_cmd = [
                ffmpeg_bin,
                "-y",
                "-ss", str(start_time),
                "-i", file_path,
                "-t", str(effective_duration),
                "-c", "copy",
                output_mp3
            ]
            logger.info(f"Executing ffmpeg (mp3 stream copy): {' '.join(ffmpeg_cmd)}")
            try:
                proc = subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
                if proc.returncode != 0 or not os.path.exists(output_mp3) or os.path.getsize(output_mp3) == 0:
                    logger.info(f"mp3 stream copy unviable (exit {proc.returncode}). Re-encoding with libmp3lame...")
                    need_encoding = True
            except FileNotFoundError:
                raise RuntimeError(
                    "ffmpeg is not installed or not found on the host system PATH. "
                    "Please install ffmpeg on your host system: sudo apt update && sudo apt install -y ffmpeg"
                )

        if need_encoding:
            encode_cmd = [
                ffmpeg_bin,
                "-y",
                "-ss", str(start_time),
                "-i", file_path,
                "-t", str(effective_duration),
                "-vn",
                "-c:a", "libmp3lame",
                "-q:a", "2",
                output_mp3
            ]
            ext = os.path.splitext(file_path)[1]
            logger.info(f"Executing ffmpeg (converting {ext} to mp3): {' '.join(encode_cmd)}")
            try:
                proc2 = subprocess.run(encode_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
                if proc2.returncode != 0:
                    logger.error(f"ffmpeg encoding failed: {proc2.stderr}")
                    raise RuntimeError(
                        f"ffmpeg audio extraction failed: {proc2.stderr[-300:] if proc2.stderr else 'Unknown error'}"
                    )
            except FileNotFoundError:
                raise RuntimeError(
                    "ffmpeg is not installed or not found on the host system PATH. "
                    "Please install ffmpeg on your host system: sudo apt update && sudo apt install -y ffmpeg"
                )
    else:
        # Slicing directly from Audiobookshelf HTTP API stream
        stream_cmd = [
            ffmpeg_bin,
            "-y",
            "-headers", f"Authorization: Bearer {auth_token}\r\n",
            "-ss", str(start_time),
            "-i", input_target,
            "-t", str(effective_duration),
            "-vn",
            "-c:a", "libmp3lame",
            "-q:a", "2",
            output_mp3
        ]
        logger.info(f"Executing ffmpeg over HTTP stream: {' '.join(stream_cmd)}")
        try:
            proc_stream = subprocess.run(stream_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            if proc_stream.returncode != 0 or not os.path.exists(output_mp3) or os.path.getsize(output_mp3) == 0:
                logger.error(f"ffmpeg HTTP stream extraction failed: {proc_stream.stderr}")
                raise RuntimeError(
                    f"Local file '{file_path}' was not found and HTTP streaming failed: {proc_stream.stderr[-300:] if proc_stream.stderr else 'Unknown error'}. "
                    f"Please verify AUDIOBOOKS_PATH in ecosystem.config.cjs."
                )
        except FileNotFoundError:
            raise RuntimeError(
                "ffmpeg is not installed or not found on the host system PATH. "
                "Please install ffmpeg on your host system: sudo apt update && sudo apt install -y ffmpeg"
            )

    # 8. Transcription (faster-whisper primary with Vosk backup)
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

    # 9. Format Metadata Header & Markdown with frontmatter
    formatted_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bookmarked_duration_formatted = format_bookmarked_duration(current_time)
    snippet_length_formatted = f"{int(round(effective_duration))} seconds"
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
duration: {effective_duration}
snippet_length: "{snippet_length_formatted}"
library_item_id: "{resolved_lib_item_id}"
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

    # 10. Write JSON metadata file for indexing
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
        "duration": effective_duration,
        "snippet_length": snippet_length_formatted,
        "library_item_id": resolved_lib_item_id,
        "user_id": user_id,
        "username": username,
        "transcript": full_transcript,
        "raw_transcript": transcript_body,
        "audio_url": f"/bookmarks/{target_user_name}/{safe_book_title}/{timestamp}.mp3",
        "md_url": f"/bookmarks/{target_user_name}/{safe_book_title}/{timestamp}.md",
        "file_path": output_md,
        "mp3_path": output_mp3,
        "json_path": output_json,
        "extraction_method": "intercepted" if bookmark_data else "manual",
        "created_at": formatted_datetime,
        "transcription_engine": engine_used
    }
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(meta_content, f, indent=2)

    logger.info(f"Successfully processed bookmark extraction for '{full_book_title}' [{timestamp}] by user '{username}'")

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
            "duration": effective_duration,
            "snippet_length": snippet_length_formatted,
            "mp3_file": output_mp3,
            "md_file": output_md,
            "transcript": full_transcript,
            "raw_transcript": transcript_body,
            "audio_url": f"/bookmarks/{safe_username}/{safe_book_title}/{timestamp}.mp3",
            "md_url": f"/bookmarks/{safe_username}/{safe_book_title}/{timestamp}.md"
        }
    }


# --- Middleware Interceptor Proxy: Automated Event-Driven Bookmark Capture ---

@app.post("/api/me/item/{library_item_id}/bookmark")
@app.post("/api/me/item/{library_item_id}/bookmark/")
@app.post("/api/me/item/{library_item_id}/bookmark")
@app.post("/api/me/item/{library_item_id}/bookmark/")
@app.post("/api/me/item/{library_item_id}/bookmarks")
@app.post("/api/me/item/{library_item_id}/bookmarks/")
@app.post("/api/items/{library_item_id}/bookmark")
@app.post("/api/items/{library_item_id}/bookmark/")
@app.post("/api/items/{library_item_id}/bookmarks")
@app.post("/api/items/{library_item_id}/bookmarks/")
@app.post("/api/me/items/{library_item_id}/bookmark")
@app.post("/api/me/items/{library_item_id}/bookmark/")
@app.post("/api/me/items/{library_item_id}/bookmarks")
@app.post("/api/me/items/{library_item_id}/bookmarks/")
@app.post("/api/libraries/{library_id}/items/{library_item_id}/bookmark")
@app.post("/api/libraries/{library_id}/items/{library_item_id}/bookmark/")
async def intercept_bookmark_create(library_item_id: str, request: Request, library_id: Optional[str] = None):
    """
    Transparent Middleware Interceptor for Audiobookshelf bookmark creation.
    Forwards bookmark creation requests to the underlying ABS server (ABS_TARGET_SERVER).
    When ABS responds with 200/201, immediately triggers asynchronous background extraction
    and returns the original ABS response without delaying client playback or UI.
    """
    body_bytes = await request.body()
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)

    target_server = resolve_abs_server_url(
        header_url=request.headers.get("X-ABS-Server-Url") or request.headers.get("X-Server-Url"),
        query_url=request.query_params.get("server_url") or request.query_params.get("serverUrl")
    )

    # Extract auth token from incoming request (headers, cookies, query, or body)
    auth_token = extract_token_from_request(request, body_bytes)
    if not auth_token and _last_authenticated_session.get("token"):
        auth_token = _last_authenticated_session["token"]

    target_url = f"{target_server}/api/me/item/{library_item_id}/bookmark"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    print("\n" + "=" * 60, flush=True)
    print(" [!] INTERCEPTED NEW BOOKMARK EVENT! ", flush=True)
    print("=" * 60, flush=True)
    print(f"--> Library Item ID: {library_item_id}", flush=True)
    print(f"--> Forwarding to ABS: {target_url}", flush=True)
    print(f"--> Auth Token Present: {bool(auth_token)}", flush=True)

    abs_response = None
    try:
        if httpx is not None:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                abs_response = await client.post(
                    target_url,
                    content=body_bytes,
                    headers=headers,
                    timeout=15.0
                )
        else:
            def _sync_post():
                return requests.post(target_url, data=body_bytes, headers=headers, timeout=15.0, allow_redirects=True)
            abs_response = await asyncio.to_thread(_sync_post)
    except Exception as e:
        print(f"[!] Failed to forward bookmark request to ABS ({target_url}): {e}", flush=True)
        print("=" * 60 + "\n", flush=True)
        logger.error(f"Failed to forward bookmark request to ABS ({target_url}): {e}")
        return Response(
            content=json.dumps({"detail": f"Failed to connect to ABS server at {target_server}: {str(e)}"}),
            status_code=502,
            media_type="application/json"
        )

    print(f"--> ABS Response Code: {abs_response.status_code}", flush=True)

    # If ABS created the bookmark successfully (200 OK or 201 Created)
    if abs_response.status_code in (200, 201):
        try:
            bookmark_data = abs_response.json()
        except Exception:
            bookmark_data = {}

        # Merge fields from request body if missing in ABS response
        try:
            body_json = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
            if isinstance(body_json, dict):
                for k, v in body_json.items():
                    if k not in bookmark_data or bookmark_data[k] is None:
                        bookmark_data[k] = v
        except Exception:
            pass

        # Attach auth token and server url to bookmark_data for worker task
        if auth_token:
            bookmark_data["_auth_token"] = auth_token
        if target_server:
            bookmark_data["_server_url"] = target_server

        print(f"--> Bookmark Time: {bookmark_data.get('time')}", flush=True)
        print(f"--> Bookmark Title: {bookmark_data.get('title')}", flush=True)
        print("--> Triggering automated audio extraction & transcription in background...", flush=True)
        print("=" * 60 + "\n", flush=True)

        logger.info(f"ABS bookmark created successfully: {bookmark_data}. Spawning background extraction worker...")

        # Asynchronous non-blocking background queue task
        def _safe_background_task():
            try:
                print(f"[*] Worker starting extraction for item '{library_item_id}'...", flush=True)
                res = process_bookmark_extraction(
                    library_item_id=library_item_id,
                    bookmark_data=bookmark_data,
                    auth_token=auth_token,
                    server_url=target_server
                )
                print(f"[✓] Worker finished extraction: {res.get('snippet', {}).get('mp3_file')}", flush=True)
            except Exception as bg_err:
                print(f"[✗] Worker extraction failed: {bg_err}", flush=True)
                logger.error(f"Background extraction failed for bookmark on item '{library_item_id}': {bg_err}", exc_info=True)

        asyncio.create_task(asyncio.to_thread(_safe_background_task))
    else:
        print(f"[!] ABS returned non-success HTTP {abs_response.status_code}: {abs_response.text}", flush=True)
        print("=" * 60 + "\n", flush=True)
        logger.warning(f"ABS returned HTTP {abs_response.status_code} for bookmark creation: {abs_response.text}")

    # Return the native ABS response to client immediately
    excluded_headers = {"content-encoding", "content-length", "transfer-encoding", "connection"}
    resp_headers = {
        k: v for k, v in abs_response.headers.items()
        if k.lower() not in excluded_headers
    }

    return Response(
        content=abs_response.content,
        status_code=abs_response.status_code,
        headers=resp_headers
    )


@app.post("/api/me/bookmark")
@app.post("/api/me/bookmark/")
@app.post("/api/me/bookmarks")
@app.post("/api/me/bookmarks/")
@app.post("/api/bookmarks")
@app.post("/api/bookmarks/")
async def intercept_general_bookmark_create(request: Request):
    """
    Catch-all interceptor for general bookmark endpoints that might pass libraryItemId in body.
    """
    body_bytes = await request.body()
    lib_id = None
    try:
        body_json = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        if isinstance(body_json, dict):
            lib_id = body_json.get("libraryItemId") or body_json.get("library_item_id") or body_json.get("itemId")
    except Exception:
        pass

    if lib_id:
        return await intercept_bookmark_create(library_item_id=str(lib_id), request=request)

    # Otherwise forward directly via catch-all proxy
    return await proxy_catch_all(path=request.url.path.lstrip("/"), request=request)


# --- Manual Trigger & REST API Endpoints (Web App, Scripts, Automation) ---

@app.post("/api/snippet")
@app.post("/api/extract")
@app.post("/api/bookmark/extract")
async def create_snippet_or_bookmark(
    request: Request,
    payload: Optional[SnippetRequest] = None,
    raw_token: str = Depends(extract_token_flexible)
):
    """
    Extracts an audio snippet and transcribes it synchronously upon explicit request.
    Can be called by:
    - Web Dashboard
    - Automation webhooks, scripts, or curl
    """
    server_url = resolve_abs_server_url(
        req_url=(payload.server_url or payload.serverUrl or payload.abs_server_url or payload.absServerUrl) if payload else None,
        header_url=request.headers.get("X-ABS-Server-Url") or request.headers.get("X-Server-Url") or request.headers.get("X-ABS-URL"),
        query_url=request.query_params.get("server_url") or request.query_params.get("serverUrl")
    )
    user = validate_abs_token(raw_token, server_url=server_url)

    custom_start = (payload.start_time or payload.startTime or payload.offset) if payload else None
    duration = payload.duration if payload and payload.duration else SNIPPET_DURATION

    try:
        result = process_bookmark_extraction(
            library_item_id=payload.library_item_id if payload else None,
            auth_token=raw_token,
            server_url=server_url,
            duration=duration,
            snippet_request=payload,
            user_info=user,
            custom_start=float(custom_start) if custom_start is not None else None
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during snippet extraction: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/user/bookmarks")
@app.get("/api/snippets")
async def get_user_bookmarks(
    request: Request,
    raw_token: str = Depends(extract_token_flexible)
):
    """
    JSON API endpoint callable by the Web UI, mobile players, and external scripts.
    Returns all bookmarks, clips, and transcripts belonging strictly to the authenticated user.
    Scans across all candidate volume directories and case variations (e.g. 'ravi' and 'Ravi').
    """
    server_url = resolve_abs_server_url(
        header_url=request.headers.get("X-ABS-Server-Url") or request.headers.get("X-Server-Url") or request.headers.get("X-ABS-URL"),
        query_url=request.query_params.get("server_url") or request.query_params.get("serverUrl")
    )
    user = validate_abs_token(raw_token, server_url=server_url)
    username = user["username"]
    safe_username = sanitize_filename(username)
    user_id = user["id"]

    candidate_roots = get_candidate_volume_dirs()
    user_search_names = list(dict.fromkeys([safe_username, safe_username.lower(), user_id]))
    bookmarks = []
    seen_ids = set()

    # Search each candidate volume directory for user folders
    for root in candidate_roots:
        for u in user_search_names:
            # Possible directory locations:
            # 1. {root}/{u}/bookmarks/{book_dir}
            # 2. {root}/{u}/{book_dir}
            possible_user_dirs = [
                os.path.join(root, u, "bookmarks"),
                os.path.join(root, u)
            ]

            for u_dir in possible_user_dirs:
                if not os.path.isdir(u_dir):
                    continue

                for book_dir in sorted(os.listdir(u_dir)):
                    # Avoid recursing into 'bookmarks' folder itself if scanning root/{u}
                    if book_dir.lower() in ("bookmarks", "snippets"):
                        continue
                    full_book_path = os.path.join(u_dir, book_dir)
                    if not os.path.isdir(full_book_path):
                        continue

                    for fname in sorted(os.listdir(full_book_path), reverse=True):
                        if fname.endswith(".md"):
                            base_name = fname[:-3]
                            item_unique_key = f"{book_dir.lower()}-{base_name}"
                            if item_unique_key in seen_ids:
                                continue

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

                            seen_ids.add(item_unique_key)
                            bookmarks.append({
                                "id": f"{book_dir}-{base_name}",
                                "book_title": metadata.get("book_title") or book_dir,
                                "author": metadata.get("author") or "Unknown Author",
                                "chapter": metadata.get("chapter") or "",
                                "timestamp": base_name,
                                "start_time": metadata.get("start_time", 0.0),
                                "duration": metadata.get("duration", 60),
                                "transcript": transcript_text,
                                "audio_url": f"/bookmarks/{u}/{book_dir}/{base_name}.mp3" if has_mp3 else None,
                                "md_url": f"/bookmarks/{u}/{book_dir}/{fname}",
                                "file_path": md_path,
                                "mp3_path": mp3_path if has_mp3 else None,
                                "username": username,
                                "extraction_method": metadata.get("extraction_method", "intercepted"),
                                "created_at": metadata.get("created_at") or base_name
                            })

    return {
        "status": "success",
        "username": username,
        "count": len(bookmarks),
        "bookmarks": bookmarks
    }


@app.delete("/api/user/bookmarks/{snippet_id:path}")
@app.delete("/api/snippets/{snippet_id:path}")
async def delete_user_bookmark(
    snippet_id: str,
    request: Request,
    raw_token: str = Depends(extract_token_flexible)
):
    """
    Permanently deletes a snippet/bookmark and its associated .mp3, .md, and .json files from the server.
    Scans all candidate volume roots and user folder variants.
    """
    server_url = resolve_abs_server_url(
        header_url=request.headers.get("X-ABS-Server-Url") or request.headers.get("X-Server-Url") or request.headers.get("X-ABS-URL"),
        query_url=request.query_params.get("server_url") or request.query_params.get("serverUrl")
    )
    user = validate_abs_token(raw_token, server_url=server_url)
    username = user["username"]
    safe_username = sanitize_filename(username)
    user_id = user["id"]

    deleted_count = 0
    candidate_roots = get_candidate_volume_dirs()
    user_search_names = list(dict.fromkeys([safe_username, safe_username.lower(), user_id]))

    clean_id = snippet_id.strip().strip("/")
    target_pattern = clean_id[2:] if clean_id.startswith("b-") else clean_id

    for root in candidate_roots:
        for u in user_search_names:
            search_dirs = [
                os.path.join(root, u, "bookmarks"),
                os.path.join(root, u)
            ]
            for base_dir in search_dirs:
                if not os.path.isdir(base_dir):
                    continue
                for book_dir in os.listdir(base_dir):
                    full_book_path = os.path.join(base_dir, book_dir)
                    if not os.path.isdir(full_book_path):
                        continue
                    for fname in os.listdir(full_book_path):
                        base_name = os.path.splitext(fname)[0]
                        full_id = f"{book_dir}-{base_name}"
                        if clean_id in (full_id, base_name, fname) or target_pattern in (base_name, fname):
                            file_to_del = os.path.join(full_book_path, fname)
                            try:
                                os.remove(file_to_del)
                                deleted_count += 1
                                logger.info(f"Deleted bookmark file: {file_to_del}")
                            except Exception as e:
                                logger.warning(f"Could not delete {file_to_del}: {e}")

                    try:
                        if os.path.isdir(full_book_path) and not os.listdir(full_book_path):
                            os.rmdir(full_book_path)
                    except Exception:
                        pass

    return {
        "status": "success",
        "deleted_id": snippet_id,
        "files_removed": deleted_count
    }


# --- Static Audio & Markdown File Serving ---

@app.get("/bookmarks/{username}/{book_title}/{filename}")
@app.get("/snippets/{username}/{book_title}/{filename}")
async def serve_bookmark_file(username: str, book_title: str, filename: str):
    """
    Serves the generated MP3 audio clip, Markdown transcript, or JSON metadata.
    Searches across all candidate volume roots and case variations.
    Supports HTTP Range requests so audio players and web browsers can stream audio smoothly with seeking.
    """
    safe_username = sanitize_filename(username)
    safe_book_title = sanitize_filename(book_title)
    safe_filename = os.path.basename(filename)

    candidate_roots = get_candidate_volume_dirs()
    user_variants = list(dict.fromkeys([safe_username, safe_username.lower(), safe_username.capitalize()]))

    file_path = None
    for root in candidate_roots:
        if not os.path.isdir(root):
            continue
        # Also discover any folder in root matching case-insensitively
        for existing in os.listdir(root):
            if existing.lower() == safe_username.lower() and existing not in user_variants:
                user_variants.append(existing)

        for u in user_variants:
            # 1. Primary: {root}/{u}/bookmarks/{book_title}/{filename}
            p = os.path.join(root, u, "bookmarks", safe_book_title, safe_filename)
            if os.path.isfile(p):
                file_path = p
                break

            # 2. Case-insensitive and space/underscore book folder check under bookmarks/
            bm_parent = os.path.join(root, u, "bookmarks")
            if os.path.isdir(bm_parent):
                for b_sub in os.listdir(bm_parent):
                    sub_norm = b_sub.replace("_", " ").strip().lower()
                    req_norm = safe_book_title.replace("_", " ").strip().lower()
                    if sub_norm == req_norm or b_sub.lower() == safe_book_title.lower():
                        p_sub = os.path.join(bm_parent, b_sub, safe_filename)
                        if os.path.isfile(p_sub):
                            file_path = p_sub
                            break
            if file_path:
                break

            # 3. Direct: {root}/{u}/{book_title}/{filename}
            p = os.path.join(root, u, safe_book_title, safe_filename)
            if os.path.isfile(p):
                file_path = p
                break
            # 3b. Case/space direct check
            u_dir = os.path.join(root, u)
            if os.path.isdir(u_dir):
                for b_sub in os.listdir(u_dir):
                    if b_sub.lower() in ("bookmarks", "snippets"):
                        continue
                    sub_norm = b_sub.replace("_", " ").strip().lower()
                    req_norm = safe_book_title.replace("_", " ").strip().lower()
                    if sub_norm == req_norm or b_sub.lower() == safe_book_title.lower():
                        p_sub = os.path.join(u_dir, b_sub, safe_filename)
                        if os.path.isfile(p_sub):
                            file_path = p_sub
                            break
            if file_path:
                break

            # 4. Snippets fallback: {root}/snippets/{u}/{book_title}/{filename}
            p = os.path.join(root, "snippets", u, safe_book_title, safe_filename)
            if os.path.isfile(p):
                file_path = p
                break
        if file_path:
            break

    if not file_path or not os.path.isfile(file_path):
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


# --- Embedded Web Dashboard & Transparent Proxy Engine ---

async def render_extractor_dashboard(
    request: Request,
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None)
) -> Response:
    """
    Renders the HTML bookmark extractor and audio player dashboard for the authenticated user,
    discovering bookmarks across all candidate volume locations.
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
    if not auth_token and _last_authenticated_session.get("token"):
        auth_token = _last_authenticated_session["token"]

    user = None
    error_msg = None

    server_url = resolve_abs_server_url(
        header_url=request.headers.get("X-ABS-Server-Url") or request.headers.get("X-Server-Url"),
        query_url=request.query_params.get("server_url") or request.query_params.get("serverUrl")
    )

    if auth_token:
        try:
            user = validate_abs_token(auth_token, server_url=server_url)
        except HTTPException as e:
            error_msg = e.detail
            auth_token = None

    snippets = []
    if user:
        safe_username = sanitize_filename(user["username"])
        candidate_roots = get_candidate_volume_dirs()
        user_search_names = list(dict.fromkeys([safe_username, safe_username.lower(), user["id"]]))
        seen_ids = set()

        for root in candidate_roots:
            for u in user_search_names:
                possible_dirs = [
                    os.path.join(root, u, "bookmarks"),
                    os.path.join(root, u)
                ]
                for scan_dir in possible_dirs:
                    if not os.path.isdir(scan_dir):
                        continue

                    for book_dir in sorted(os.listdir(scan_dir)):
                        if book_dir.lower() in ("bookmarks", "snippets"):
                            continue
                        full_book_path = os.path.join(scan_dir, book_dir)
                        if not os.path.isdir(full_book_path):
                            continue

                        for fname in sorted(os.listdir(full_book_path), reverse=True):
                            if fname.endswith(".md"):
                                base_name = fname[:-3]
                                key = f"{book_dir.lower()}-{base_name}"
                                if key in seen_ids:
                                    continue

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
                                seen_ids.add(key)
                                snippets.append({
                                    "title": parsed.get("title") or book_dir.replace("_", " "),
                                    "author": parsed.get("author") or "Unknown Author",
                                    "chapter": parsed.get("chapter") or "",
                                    "timestamp": parsed.get("timestamp") or base_name,
                                    "created_at_str": created_time,
                                    "duration": parsed.get("duration", "60"),
                                    "transcript": transcript_text,
                                    "audio_url": f"/bookmarks/{u}/{book_dir}/{base_name}.mp3" if has_mp3 else None,
                                    "md_url": f"/bookmarks/{u}/{book_dir}/{fname}"
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


@app.get("/extractor", response_class=HTMLResponse)
@app.get("/extractor/", response_class=HTMLResponse)
@app.get("/bookmarks-ui", response_class=HTMLResponse)
@app.get("/sidecar-ui", response_class=HTMLResponse)
async def web_dashboard(
    request: Request,
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None)
):
    """
    Dedicated dashboard view for audio bookmark management and transcription playback.
    """
    return await render_extractor_dashboard(request, token=token, authorization=authorization)


@app.get("/logout")
async def logout():
    """Clear session cookie and redirect to extractor dashboard."""
    response = RedirectResponse(url="/extractor", status_code=303)
    response.delete_cookie(key="abs_token")
    return response


@app.get("/api/health")
async def health_check():
    """Health check endpoint providing configuration, proxy mode, and system status."""
    return {
        "status": "healthy",
        "service": "Audiobookshelf Bookmarks Extractor & Transparent Proxy",
        "tagline": "Transparent sidecar proxy for Audiobookshelf v1.5 with automated bookmark clipping & transcription",
        "architecture_mode": "Option 3: Transparent Proxy & WebSockets (Port 13380)",
        "abs_target_server": ABS_TARGET_SERVER,
        "volume_dir": VOLUME_DIR,
        "candidate_volume_dirs": get_candidate_volume_dirs(),
        "whisper_model": WHISPER_MODEL_NAME,
        "whisper_device": WHISPER_DEVICE,
        "websocket_support": websockets is not None,
        "time": datetime.now().isoformat()
    }


# --- Transparent WebSocket Proxy (Option 3 Support for Socket.IO) ---

@app.websocket("/socket.io/")
@app.websocket("/socket.io/{path:path}")
@app.websocket("/ws")
@app.websocket("/ws/{path:path}")
async def proxy_websocket(websocket: WebSocket, path: str = ""):
    """
    Transparent bidirectional WebSocket reverse proxy for Audiobookshelf Socket.IO connections.
    Allows mobile apps, Web clients, and sync daemons to communicate with full real-time fidelity
    through sidecar port 13380 with zero protocol disruption.
    """
    await websocket.accept()

    target_server = resolve_abs_server_url(
        header_url=websocket.headers.get("X-ABS-Server-Url") or websocket.headers.get("X-Server-Url"),
        query_url=websocket.query_params.get("server_url") or websocket.query_params.get("serverUrl")
    )

    # Convert http(s) URL to ws(s) URL
    ws_target_server = target_server.replace("https://", "wss://").replace("http://", "ws://")
    subpath = path.lstrip("/")

    # Determine base prefix
    base_prefix = "socket.io" if "socket.io" in str(websocket.url.path) else "ws"
    ws_target_url = f"{ws_target_server}/{base_prefix}/{subpath}" if subpath else f"{ws_target_server}/{base_prefix}/"
    if websocket.url.query:
        ws_target_url = f"{ws_target_url}?{websocket.url.query}"

    if websockets is None:
        logger.error("The 'websockets' package is required for WebSocket proxying. Please install: pip install websockets")
        await websocket.close(code=1011, reason="websockets package missing on sidecar")
        return

    # Forward client auth, cookies, and user agent
    forward_headers = {}
    for h in ["cookie", "authorization", "user-agent", "sec-websocket-protocol"]:
        if h in websocket.headers:
            forward_headers[h] = websocket.headers[h]

    try:
        async with websockets.connect(
            ws_target_url,
            extra_headers=forward_headers,
            ping_interval=None,
            max_size=None
        ) as backend_ws:
            async def client_to_server():
                try:
                    while True:
                        msg = await websocket.receive()
                        if "text" in msg and msg["text"] is not None:
                            await backend_ws.send(msg["text"])
                        elif "bytes" in msg and msg["bytes"] is not None:
                            await backend_ws.send(msg["bytes"])
                        elif msg.get("type") == "websocket.disconnect":
                            break
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
                except Exception as ex:
                    logger.debug(f"Client to server WS forwarding closed: {ex}")

            async def server_to_client():
                try:
                    async for message in backend_ws:
                        if isinstance(message, str):
                            await websocket.send_text(message)
                        elif isinstance(message, bytes):
                            await websocket.send_bytes(message)
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
                except Exception as ex:
                    logger.debug(f"Server to client WS forwarding closed: {ex}")

            done, pending = await asyncio.wait(
                [asyncio.create_task(client_to_server()), asyncio.create_task(server_to_client())],
                return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
    except Exception as e:
        logger.warning(f"WebSocket proxy error connecting to {ws_target_url}: {e}")
        try:
            await websocket.close(code=1011, reason=str(e)[:100])
        except Exception:
            pass


# --- Transparent Catch-All Proxy Route for Audiobookshelf (HTTP / REST) ---

@app.api_route("", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@app.api_route("/", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_catch_all(request: Request, path: str = ""):
    """
    Universal transparent reverse proxy. Forwards all unhandled API requests, logins,
    static assets, media playback streams, and web client files to the underlying Audiobookshelf server (ABS_TARGET_SERVER).
    
    If the path is root and user requested the extractor view (?view=extractor) or ABS is unreachable,
    gracefully renders the Bookmarks Extractor Dashboard.
    """
    clean_path = path.lstrip("/")

    # Check if user explicitly requested the Bookmark Extractor Dashboard
    if clean_path in ("", "/") and (
        request.query_params.get("view") in ("extractor", "bookmarks", "sidecar")
        or request.query_params.get("dashboard") == "1"
    ):
        return await render_extractor_dashboard(request)

    target_server = resolve_abs_server_url(
        header_url=request.headers.get("X-ABS-Server-Url") or request.headers.get("X-Server-Url"),
        query_url=request.query_params.get("server_url") or request.query_params.get("serverUrl")
    )
    target_url = f"{target_server}/{clean_path}" if clean_path else f"{target_server}/"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    body_bytes = await request.body()
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)

    # If this request contains auth, update session cache so background workers have credentials
    token_candidate = extract_token_from_request(request, body_bytes)
    if token_candidate and not _last_authenticated_session.get("token"):
        _last_authenticated_session["token"] = token_candidate

    try:
        if httpx is not None:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                abs_resp = await client.request(
                    method=request.method,
                    url=target_url,
                    content=body_bytes if body_bytes else None,
                    headers=headers,
                    timeout=60.0
                )
                excluded_headers = {"content-encoding", "content-length", "transfer-encoding", "connection"}
                resp_headers = {
                    k: v for k, v in abs_resp.headers.items()
                    if k.lower() not in excluded_headers
                }

                # Catch any un-intercepted bookmark creation that passes through proxy_catch_all
                if request.method == "POST" and "bookmark" in clean_path.lower() and abs_resp.status_code in (200, 201):
                    try:
                        logger.info(f"Detected bookmark creation in proxy_catch_all: {clean_path}")
                        b_data = abs_resp.json() if abs_resp.content else {}
                        # Extract library item id from path if present (e.g. items/LIB_ID/bookmark)
                        lib_item_match = re.search(r"items?/([a-zA-Z0-9\-_]+)/bookmark", clean_path, re.IGNORECASE)
                        detected_lib_id = lib_item_match.group(1) if lib_item_match else None
                        
                        def _bg_catchall():
                            try:
                                process_bookmark_extraction(
                                    library_item_id=detected_lib_id,
                                    bookmark_data=b_data,
                                    auth_token=token_candidate or _last_authenticated_session.get("token"),
                                    server_url=target_server
                                )
                            except Exception as ex:
                                logger.error(f"Background extraction failed in proxy_catch_all: {ex}")
                        asyncio.create_task(asyncio.to_thread(_bg_catchall))
                    except Exception:
                        pass

                return Response(
                    content=abs_resp.content,
                    status_code=abs_resp.status_code,
                    headers=resp_headers
                )
        else:
            def _sync_req():
                return requests.request(
                    method=request.method,
                    url=target_url,
                    data=body_bytes if body_bytes else None,
                    headers=headers,
                    timeout=60.0,
                    allow_redirects=True
                )
            abs_resp = await asyncio.to_thread(_sync_req)
            excluded_headers = {"content-encoding", "content-length", "transfer-encoding", "connection"}
            resp_headers = {
                k: v for k, v in abs_resp.headers.items()
                if k.lower() not in excluded_headers
            }
            return Response(
                content=abs_resp.content,
                status_code=abs_resp.status_code,
                headers=resp_headers
            )
    except Exception as e:
        # If requesting root in browser and ABS is not yet reachable, fallback gracefully to Extractor UI
        if clean_path in ("", "/") and request.method == "GET":
            logger.warning(f"Audiobookshelf server at {target_server} unreachable; showing extractor dashboard fallback.")
            return await render_extractor_dashboard(request)

        logger.error(f"Proxy catch-all error: {request.method} {target_url} failed: {e}")
        return Response(
            content=json.dumps({"detail": f"Proxy communication error with ABS server at {target_server}: {str(e)}"}),
            status_code=502,
            media_type="application/json"
        )


if __name__ == "__main__":
    import uvicorn
    # Default sidecar port is 13380 (SIDECAR_PORT is prioritized over PORT so it does not conflict if PORT is set to 13379 for the web dashboard)
    port = int(os.environ.get("SIDECAR_PORT") or os.environ.get("PORT") or "13380")
    # Do not reload by default to avoid watching parent directories (e.g. /home/pi)
    reload_enabled = os.environ.get("RELOAD", "false").lower() in ("true", "1", "yes")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=reload_enabled,
        reload_dirs=[BASE_DIR] if reload_enabled else None,
        app_dir=BASE_DIR
    )
