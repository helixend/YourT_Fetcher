# main.py
from __future__ import annotations

import sys
import copy
import os
import re
import subprocess
import time
import platform
import html
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
from importlib.metadata import version, PackageNotFoundError

import streamlit as st
from yt_dlp import YoutubeDL

# =========================
# Page Config
# =========================
st.set_page_config(
    page_title="YourT Fetcher v3.2 — Clean Color",
    page_icon="🦔",
    layout="centered",
)

def warn_versions():
    try:
        ytdlp_ver = version("yt-dlp")
        st.caption(f"yt-dlp: {ytdlp_ver}")
    except PackageNotFoundError:
        st.warning("yt-dlp is not installed. Install it with: pip install yt-dlp")

    try:
        ejs_ver = version("yt-dlp-ejs")
        st.caption(f"yt-dlp-ejs: {ejs_ver}")
    except PackageNotFoundError:
        st.caption("yt-dlp-ejs: not installed")

    try:
        st_ver = version("streamlit")
        st.caption(f"Streamlit: {st_ver}")
    except PackageNotFoundError:
        st.warning("streamlit is not installed. Install it with: pip install streamlit")

    if sys.version_info < (3, 10):
        st.error("Python 3.10+ is required.")

warn_versions()

# =========================
# Custom CSS
# =========================
st.markdown(
    """
<style>
h1 span.app-title{background:linear-gradient(90deg,#7b5cff,#00d4ff,#ff72e1);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hdr-badge {background-color: #ffcc00; color: #000; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 0.8rem; margin-left: 8px;}
.audio-badge {background-color: #ff4b4b; color: #fff; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 0.8rem; margin-left: 6px;}
.stButton>button{border-radius:10px;padding:.6rem 1.1rem;transition:transform 120ms ease, box-shadow 120ms ease; width: 100%}
.stButton>button:hover{transform:translateY(-1px);box-shadow:0 6px 18px rgba(0,0,0,.25)}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown("<h1>🦔 <span class='app-title'>YourT Fetcher</span></h1>", unsafe_allow_html=True)

# =========================
# Session State
# =========================
if "video_info" not in st.session_state:
    st.session_state.video_info = None
if "last_url" not in st.session_state:
    st.session_state.last_url = ""
if "last_error_line" not in st.session_state:
    st.session_state.last_error_line = ""
if "effective_js_runtime" not in st.session_state:
    st.session_state.effective_js_runtime = None

# =========================
# Helpers
# =========================
def get_default_downloads_dir() -> Path:
    return Path.home() / "Downloads"

def human_bytes(n: Optional[float]) -> str:
    if not n: return "—"
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024: return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} TB"

def get_browser_cookies_option(browser_name: str) -> Dict[str, Any]:
    if not browser_name or browser_name == "None":
        return {}
    return {"cookiesfrombrowser": (browser_name.lower(),)}

def get_auth_options(browser_name: str, cookie_file_raw: str) -> Dict[str, Any]:
    cookie_file = cookie_file_raw.strip()
    if cookie_file:
        cookie_path = Path(cookie_file).expanduser()
        if not cookie_path.exists():
            raise FileNotFoundError(f"Cookie file not found: {cookie_path}")
        return {"cookiefile": str(cookie_path)}
    return get_browser_cookies_option(browser_name)

def get_youtube_clients(prefer_tv: bool, po_token: str = "", has_cookies: bool = False) -> List[str]:
    if has_cookies:
        clients = ["tv", "mweb", "web"] if prefer_tv else ["mweb", "web", "tv"]
    else:
        clients = ["tv", "ios"] if prefer_tv else ["ios", "tv"]

    if po_token.strip():
        for client in ("mweb", "web"):
            if client not in clients:
                clients.append(client)
    return clients

def is_js_runtime_available(js_runtime: str) -> bool:
    return shutil.which(js_runtime) is not None

def apply_ytdlp_debug_and_client_opts(
    opts: Dict[str, Any],
    prefer_tv: bool,
    po_token: str = "",
    has_cookies: bool = False
) -> Dict[str, Any]:
    clients = get_youtube_clients(prefer_tv, po_token, has_cookies=has_cookies)
    yargs = opts.setdefault("extractor_args", {}).setdefault("youtube", {})
    yargs["player_client"] = clients

    if po_token.strip():
        yargs["po_token"] = [po_token.strip()]

    opts.update({
        "verbose": True,
        "quiet": False,
        "no_warnings": False,
        "remote_components": {"ejs:github"},
    })
    return opts

def build_base_opts(
    browser_name: str,
    cookie_file_raw: str,
    prefer_tv: bool,
    po_token: str,
    js_runtime: str
) -> Dict[str, Any]:
    has_auth = bool(cookie_file_raw.strip() or (browser_name and browser_name != "None"))
    opts: Dict[str, Any] = {}
    opts.update(get_auth_options(browser_name, cookie_file_raw))
    apply_ytdlp_debug_and_client_opts(
        opts,
        prefer_tv=prefer_tv,
        po_token=po_token,
        has_cookies=has_auth,
    )
    if is_js_runtime_available(js_runtime):
        opts["js_runtimes"] = {js_runtime: {}}
    return opts

def rebuild_download_opts_without_browser_cookies(
    attempt_opts: Dict[str, Any],
    prefer_tv: bool,
    po_token: str,
    js_runtime: str
) -> Dict[str, Any]:
    retry_keys = (
        "outtmpl",
        "noplaylist",
        "retries",
        "fragment_retries",
        "file_access_retries",
        "continuedl",
        "overwrites",
        "restrictfilenames",
        "progress_hooks",
        "format",
        "merge_output_format",
        "postprocessors",
        "postprocessor_args",
    )
    retry_opts = {
        key: copy.deepcopy(attempt_opts[key])
        for key in retry_keys
        if key in attempt_opts
    }
    retry_opts.update(build_base_opts("None", "", prefer_tv, po_token, js_runtime))
    return retry_opts

def cleanup_partials(save_path: Path, video_id: str):
    if not video_id:
        return

    for ext in ("part", "ytdl"):
        for partial_path in save_path.glob(f"*{video_id}*.{ext}"):
            try:
                partial_path.unlink()
            except Exception:
                pass

def should_retry_download(err_str: str) -> bool:
    retry_markers = (
        "downloaded file is empty",
        "unable to download video data",
        "http error 403",
        "requested format is not available",
        "only images are available for download",
    )
    return any(marker in err_str for marker in retry_markers)

def should_retry_with_alternate_runtime(err_str: str) -> bool:
    retry_markers = (
        "reading 'origin'",
        "signature solving failed",
        "n challenge solving failed",
        "only images are available for download",
        "requested format is not available",
    )
    return any(marker in err_str for marker in retry_markers)

def build_runtime_order(js_runtime: str) -> List[str]:
    ordered: List[str] = []

    preferred = [js_runtime]
    if js_runtime == "deno":
        preferred.append("node")
    elif js_runtime == "node":
        preferred.append("deno")

    for runtime in preferred:
        if runtime not in ordered and is_js_runtime_available(runtime):
            ordered.append(runtime)

    return ordered

def extract_info_with_runtime_fallback(
    url: str,
    opts: Dict[str, Any],
    download: bool,
    js_runtime: str
) -> Tuple[Any, str]:
    last_error: Optional[Exception] = None
    runtime_order = build_runtime_order(js_runtime)

    if not runtime_order:
        raise RuntimeError("No supported JS runtime found in PATH (node/deno).")

    for runtime in runtime_order:
        attempt_opts = copy.deepcopy(opts)
        attempt_opts["js_runtimes"] = {runtime: {}}
        try:
            with YoutubeDL(attempt_opts) as ydl:
                return ydl.extract_info(url, download=download), runtime
        except Exception as e:
            last_error = e
            err_str = str(e).lower()
            if runtime == "deno" and "node" in runtime_order and should_retry_with_alternate_runtime(err_str):
                log_to_console("Deno failed on YouTube challenges, retrying with Node...")
                continue
            if runtime == "node" and "deno" in runtime_order and should_retry_with_alternate_runtime(err_str):
                log_to_console("Node failed on YouTube challenges, retrying with Deno...")
                continue
            raise

    if last_error:
        raise last_error
    raise RuntimeError("yt-dlp extraction failed")

def format_has_video(fmt: Dict[str, Any]) -> bool:
    return str(fmt.get("vcodec") or "none").lower() != "none"

def format_has_audio(fmt: Dict[str, Any]) -> bool:
    return str(fmt.get("acodec") or "none").lower() != "none"

def format_has_stream_url(fmt: Dict[str, Any]) -> bool:
    if fmt.get("url") or fmt.get("manifest_url"):
        return True
    fragments = fmt.get("fragments")
    return isinstance(fragments, list) and len(fragments) > 0

def is_image_only_format(fmt: Dict[str, Any]) -> bool:
    ext = str(fmt.get("ext") or "").lower()
    protocol = str(fmt.get("protocol") or "").lower()
    format_note = str(fmt.get("format_note") or "").lower()
    format_id = str(fmt.get("format_id") or "").lower()

    if ext in {"mhtml", "jpg", "jpeg", "png", "webp", "gif", "avif"}:
        return True
    if protocol == "mhtml" or "storyboard" in format_note or format_id.startswith("sb"):
        return True
    return False

def is_downloadable_media_format(fmt: Dict[str, Any]) -> bool:
    if is_image_only_format(fmt) or not format_has_stream_url(fmt):
        return False
    return format_has_video(fmt) or format_has_audio(fmt)

def get_downloadable_formats(info: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [fmt for fmt in info.get("formats", []) if is_downloadable_media_format(fmt)]

def get_downloadable_video_heights(info: Dict[str, Any]) -> List[int]:
    heights = {
        int(height)
        for fmt in get_downloadable_formats(info)
        for height in [fmt.get("height")]
        if isinstance(height, int) and height > 0 and format_has_video(fmt)
    }
    return sorted(heights, reverse=True)

def _format_quality_key(fmt: Dict[str, Any]) -> Tuple[int, float, float]:
    height = fmt.get("height") if isinstance(fmt.get("height"), int) else 0
    fps = float(fmt.get("fps") or 0)
    bitrate = float(fmt.get("tbr") or fmt.get("vbr") or 0)
    return (height, fps, bitrate)

def _audio_quality_key(fmt: Dict[str, Any]) -> Tuple[int, float, float]:
    channels = fmt.get("audio_channels") if isinstance(fmt.get("audio_channels"), int) else 0
    bitrate = float(fmt.get("abr") or fmt.get("tbr") or 0)
    sample_rate = float(fmt.get("asr") or 0)
    return (channels, bitrate, sample_rate)

def build_video_format_candidates(info: Dict[str, Any], selected_res: int) -> List[str]:
    downloadable_formats = get_downloadable_formats(info)
    video_only = [
        fmt for fmt in downloadable_formats
        if format_has_video(fmt)
        and not format_has_audio(fmt)
        and isinstance(fmt.get("height"), int)
        and fmt["height"] <= selected_res
    ]
    progressive = [
        fmt for fmt in downloadable_formats
        if format_has_video(fmt)
        and format_has_audio(fmt)
        and isinstance(fmt.get("height"), int)
        and fmt["height"] <= selected_res
    ]
    audio_only = [
        fmt for fmt in downloadable_formats
        if format_has_audio(fmt) and not format_has_video(fmt)
    ]

    candidates: List[str] = []
    seen: set[str] = set()

    def add_candidate(expr: Optional[str]):
        if expr and expr not in seen:
            seen.add(expr)
            candidates.append(expr)

    best_audio_id = None
    if audio_only:
        best_audio_id = sorted(audio_only, key=_audio_quality_key, reverse=True)[0].get("format_id")

    for fmt in sorted(video_only, key=_format_quality_key, reverse=True)[:5]:
        format_id = fmt.get("format_id")
        if format_id and best_audio_id:
            add_candidate(f"{format_id}+{best_audio_id}")

    for fmt in sorted(progressive, key=_format_quality_key, reverse=True)[:5]:
        add_candidate(fmt.get("format_id"))

    add_candidate(f"bestvideo*[height<={selected_res}][vcodec!=none]+bestaudio[acodec!=none]/best[height<={selected_res}]")
    add_candidate(f"bestvideo*+bestaudio/best[height<={selected_res}]")
    add_candidate(f"best[height<={selected_res}]/best")
    return candidates

def locate_downloaded_file(
    download_result: Any,
    hook_filename: Optional[str],
    save_path: Path,
    video_id: str
) -> Optional[Path]:
    candidates: List[Path] = []

    def add_candidate(raw_path: Optional[str]):
        if not raw_path:
            return
        candidate = Path(str(raw_path))
        if candidate not in candidates:
            candidates.append(candidate)

    if isinstance(download_result, dict):
        add_candidate(download_result.get('filepath'))
        add_candidate(download_result.get('_filename'))

        for item in (download_result.get('requested_downloads') or []):
            if isinstance(item, dict):
                add_candidate(item.get('filepath'))
                add_candidate(item.get('_filename'))

        for entry in (download_result.get('entries') or []):
            if isinstance(entry, dict):
                add_candidate(entry.get('filepath'))
                add_candidate(entry.get('_filename'))

    add_candidate(hook_filename)

    for candidate in candidates:
        if candidate.exists() and candidate.is_file() and candidate.stat().st_size > 0:
            return candidate

    glob_candidates = sorted(save_path.glob(f"*{video_id}*"), key=os.path.getmtime, reverse=True)
    for candidate in glob_candidates:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate

    return None

def is_hdr_video(info: Dict[str, Any]) -> bool:
    dr = str(info.get("dynamic_range") or "").upper()
    if "HDR" in dr or "HLG" in dr or "PQ" in dr:
        return True

    for fmt in info.get("formats", []):
        transfer = str(
            fmt.get("color_transfer") or fmt.get("transfer_characteristics") or ""
        ).lower()
        if "smpte2084" in transfer or "arib-std-b67" in transfer:
            return True

    return False

def get_max_audio_channels(info: Dict[str, Any]) -> int:
    max_ch = 0
    for f in info.get('formats', []):
        ch = f.get('audio_channels')
        if ch and isinstance(ch, int):
            if ch > max_ch:
                max_ch = ch
    if max_ch == 0:
        fallback_ch = info.get('audio_channels')
        max_ch = fallback_ch if isinstance(fallback_ch, int) and fallback_ch > 0 else 2
    return max_ch

def time_str_to_seconds(time_str: str) -> float:
    try:
        h, m, s = time_str.split(':')
        return int(h) * 3600 + int(m) * 60 + float(s)
    except (ValueError, AttributeError):
        return 0.0

def get_system_capabilities() -> Tuple[bool, bool]:
    is_mac = platform.system() == 'Darwin'
    is_arm = platform.machine() == 'arm64'
    return is_mac, is_arm

def log_to_console(msg: str):
    print(f"[YourT] {msg}", flush=True)

def ensure_ffmpeg():
    if shutil.which("ffmpeg") is None:
        st.error("ffmpeg was not found in PATH. Install ffmpeg and restart the app.")
        st.stop()

# =========================
# FFmpeg Converter (Fix for SDR Colors)
# =========================
def run_ffmpeg_conversion(input_path: Path, output_path: Path, total_duration: float, 
                         progress_bar, status_text, mode: str, use_hardware_accel: bool,
                         is_source_hdr: bool, is_surround: bool, force_stereo: bool = False):
    
    cmd = ['ffmpeg', '-y', '-i', str(input_path)]
    
    # --- VIDEO PROCESSING ---
    if mode == 'apple_hdr':
        # HDR Output
        if use_hardware_accel:
            cmd.extend(['-c:v', 'hevc_videotoolbox', '-allow_sw', '1', '-q:v', '65'])
            log_to_console("Using Hardware HDR Encoder (hevc_videotoolbox)")
        else:
            cmd.extend(['-c:v', 'libx265', '-crf', '22', '-preset', 'fast'])
            log_to_console("Using CPU HDR Encoder (libx265)")
        cmd.extend([
            '-tag:v', 'hvc1',
            '-pix_fmt', 'yuv420p10le',
            '-profile:v', 'main10',
            '-color_primaries', 'bt2020',
            '-colorspace', 'bt2020nc',
            '-color_trc', 'smpte2084',
        ])
        
    elif mode == 'sdr':
        # SDR Output (Standard MP4)
        if use_hardware_accel:
            cmd.extend(['-c:v', 'h264_videotoolbox', '-allow_sw', '1', '-q:v', '65'])
            log_to_console("Using Hardware SDR Encoder (h264_videotoolbox)")
        else:
            cmd.extend(['-c:v', 'libx264', '-crf', '23', '-preset', 'fast'])
            log_to_console("Using CPU SDR Encoder (libx264)")
            
        # --- CRITICAL COLOR FIX LOGIC ---
        if is_source_hdr:
            # Case 1: HDR Source -> SDR Output
            # MUST apply Tone Mapping to fix colors
            log_to_console("Applying HDR->SDR Tone Mapping Filter (zscale+tonemap)")
            filter_chain = (
                "zscale=t=linear:npl=100,"
                "format=gbrpf32le,"
                "zscale=p=bt709,"
                "tonemap=tonemap=hable:desat=0,"
                "zscale=t=bt709:m=bt709:r=tv,"
                "format=yuv420p"
            )
            cmd.extend(['-vf', filter_chain])
            cmd.extend([
                '-colorspace', 'bt709',
                '-color_trc', 'bt709',
                '-color_primaries', 'bt709'
            ])
        else:
            # Case 2: SDR Source -> SDR Output
            # DO NOT apply filter chain (it washes out colors).
            # JUST apply Metadata Tags so QuickTime knows it's BT.709
            log_to_console("SDR Source detected: Skipping filters, enforcing BT.709 tags")
            cmd.extend([
                '-pix_fmt', 'yuv420p',
                '-colorspace', 'bt709',
                '-color_trc', 'bt709',
                '-color_primaries', 'bt709'
            ])
            
        cmd.extend(['-movflags', '+faststart'])

    # --- AUDIO SETTINGS ---
    audio_bitrate = '256k'
    if is_surround and not force_stereo:
        audio_bitrate = '512k'
    cmd.extend(['-c:a', 'aac', '-b:a', audio_bitrate])
    if force_stereo:
        cmd.extend(['-ac', '2'])
        log_to_console("Downmixing audio to Stereo")
    
    cmd.append(str(output_path))
    
    log_to_console(f"Running FFmpeg: {' '.join(cmd)}")
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    time_pattern = re.compile(r'time=(\d{2}:\d{2}:\d{2}\.\d{2})')

    while True:
        line = process.stderr.readline()
        if not line and process.poll() is not None:
            break
        
        if line:
            match = time_pattern.search(line)
            if match:
                current_time_str = match.group(1)
                current_seconds = time_str_to_seconds(current_time_str)
                if total_duration > 0:
                    percent = min(current_seconds / total_duration, 1.0)
                    progress_bar.progress(percent)
                    
                    label = "MP4 (SDR)" if mode == 'sdr' else "HDR (HEVC)"
                    method = "Hardware" if use_hardware_accel else "CPU"
                    status_text.text(f"Converting to {label} [{method}]... {int(percent*100)}%")

    process.wait()
    if process.returncode != 0:
        log_to_console(f"FFmpeg Error Code: {process.returncode}")
        raise Exception(f"FFmpeg conversion failed. Return code: {process.returncode}")
    
    log_to_console("Conversion finished successfully.")

# =========================
# Download Progress Hook
# =========================
class DownloadLogger:
    def __init__(self, progress_bar, status_text):
        self.bar = progress_bar
        self.text = status_text
        self.filename = None

    def hook(self, d):
        if d['status'] == 'downloading':
            try:
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 1
                downloaded = d.get('downloaded_bytes', 0)
                pct = downloaded / total
                self.bar.progress(min(max(pct, 0.0), 1.0))
                speed = d.get('speed')
                self.text.text(f"Downloading... {pct:.1%} | {human_bytes(speed)}/s")
            except Exception:
                pass
        elif d['status'] == 'finished':
            self.bar.progress(1.0)
            self.text.text("Download complete. Starting processing...")
            self.filename = d.get('filename')
            log_to_console(f"Download finished: {d.get('filename')}")

# =========================
# Sidebar
# =========================
with st.sidebar:
    st.header("⚙️ Settings")
    st.subheader("Auth / Cookies")
    browser = st.selectbox(
        "Load cookies from:",
        ["None", "Chrome", "Firefox", "Safari", "Edge", "Brave"],
        index=0
    )
    if browser == "Safari":
        st.caption("⚠️ Safari requires 'Full Disk Access' for Terminal.")
    cookie_file = st.text_input(
        "Cookie file (.txt, optional)",
        value="",
        placeholder="~/Downloads/cookies.txt"
    )
    if cookie_file.strip():
        st.caption("Cookie file has priority over browser cookies.")
        
    st.divider()
    prefer_tv = st.checkbox("Prefer TV client (try higher quality first)", value=True)
    available_runtime_options = [rt for rt in ("deno", "node") if is_js_runtime_available(rt)]
    if not available_runtime_options:
        available_runtime_options = ["deno", "node"]
    js_runtime = st.selectbox(
        "JS runtime",
        available_runtime_options,
        index=0,
        help="If Deno fails on YouTube challenges, try Node.js."
    )
    po_token = st.text_input(
        "PO Token (optional, e.g. mweb.gvs+XXX)",
        value="",
        help="If YouTube is capped at low quality, an mweb/web PO token is often required."
    )
    has_auth = bool(cookie_file.strip() or (browser and browser != "None"))
    st.caption(f"Active YouTube clients: {', '.join(get_youtube_clients(prefer_tv, po_token, has_cookies=has_auth))}")
    if not is_js_runtime_available(js_runtime):
        st.caption(f"{js_runtime} is not available in PATH.")
    if not any(is_js_runtime_available(rt) for rt in ("deno", "node")):
        st.caption("No supported JS runtime was detected in PATH.")
    if st.session_state.effective_js_runtime and st.session_state.effective_js_runtime != js_runtime:
        st.caption(f"Last fallback runtime: {st.session_state.effective_js_runtime}")
    st.divider()
    save_path_str = st.text_input("Save Folder", value=str(get_default_downloads_dir()))
    save_path = Path(save_path_str).expanduser().resolve()
    if st.session_state.last_error_line:
        st.caption(f"Last error: {st.session_state.last_error_line}")

# =========================
# Error Handler
# =========================
def handle_error(e):
    err_raw = str(e)
    err_str = err_raw.lower()
    err_last_line = err_raw.strip().splitlines()[-1] if err_raw.strip() else err_raw
    st.session_state.last_error_line = err_last_line
    log_to_console(f"ERROR: {err_str}")
    if "operation not permitted" in err_str and "cookies" in err_str:
        st.error("🛑 **Permission Denied: macOS blocked access to Safari Cookies.**")
    elif "cookie file not found" in err_str:
        st.error("🛑 Cookie file path is invalid. Please check the file path in sidebar.")
    elif "not a bot" in err_str:
        st.warning("🔒 YouTube requires sign-in. Please select your browser in the sidebar.")
        st.session_state.video_info = None
        st.stop()
    elif "sign in" in err_str:
        st.warning("🔒 YouTube requires sign-in. Please select your browser in the sidebar.")
    elif "downloaded file is empty" in err_str:
        st.error("📦 Downloaded file is empty. Try browser cookies or export cookies.txt and retry.")
    elif "only images are available for download" in err_str or "requested format is not available" in err_str:
        st.error(
            "🎞️ YouTube returned metadata, but the media streams were not exposed. "
            "This is most often caused by the JS challenge solver (yt-dlp-ejs / runtime), "
            "cookies, or a missing PO token."
        )
    else:
        st.error(f"Error: {e}")

# =========================
# Main UI
# =========================
url = st.text_input("Paste YouTube URL", placeholder="https://youtube.com/watch?v=...")
col_act1, col_act2 = st.columns([1, 4])
analyze_clicked = col_act1.button("🔍 Analyze")

if analyze_clicked and url:
    if url != st.session_state.last_url:
        st.session_state.video_info = None
    st.session_state.last_error_line = ""
        
    with st.spinner("Fetching info..."):
        try:
            log_to_console(f"Analyzing URL: {url}")
            ydl_opts = build_base_opts(browser, cookie_file, prefer_tv, po_token, js_runtime)
            info, used_js_runtime = extract_info_with_runtime_fallback(
                url,
                ydl_opts,
                download=False,
                js_runtime=js_runtime,
            )
            st.session_state.effective_js_runtime = used_js_runtime
            if used_js_runtime != js_runtime:
                st.info(f"JS runtime fallback used: {js_runtime} -> {used_js_runtime}")

            info_str = str(info).lower()
            if "sign in to confirm you’re not a bot" in info_str or "sign in to confirm you're not a bot" in info_str:
                st.warning("YouTube requires verification. Use browser cookies or a cookies.txt file.")
            if not get_downloadable_formats(info):
                st.warning(
                    "Metadata was retrieved, but YouTube did not expose downloadable media streams. "
                    "Check yt-dlp-ejs / JS runtime, cookies, and your PO token."
                )
            st.session_state.video_info = info
            st.session_state.last_url = url
            log_to_console("Analysis complete.")
        except Exception as e:
            st.session_state.effective_js_runtime = None
            handle_error(e)
            st.session_state.video_info = None

# =========================
# Display & Logic
# =========================
if st.session_state.video_info:
    info = st.session_state.video_info
    downloadable_formats = get_downloadable_formats(info)
    downloadable_video_heights = get_downloadable_video_heights(info)
    has_downloadable_video = bool(downloadable_video_heights)
    has_downloadable_audio = any(format_has_audio(fmt) for fmt in downloadable_formats)
    mode_options: List[str] = []
    if has_downloadable_video and has_downloadable_audio:
        mode_options.append("Video + Audio")
    if has_downloadable_audio:
        mode_options.append("Audio Only")
    download_disabled = not mode_options
    is_hdr = is_hdr_video(info)
    max_channels = get_max_audio_channels(info)
    is_surround = max_channels > 2
    
    with st.container():
        c1, c2 = st.columns([1, 2])
        with c1:
            st.image(info.get("thumbnail"), use_container_width=True)
        with c2:
            safe_title = html.escape(str(info.get('title') or "Untitled"))
            title_html = f"### {safe_title}"
            if is_hdr: title_html += " <span class='hdr-badge'>HDR</span>"
            if is_surround: title_html += f" <span class='audio-badge'>{max_channels}Ch Audio</span>"
            st.markdown(title_html, unsafe_allow_html=True)
            uploader = info.get('uploader') or "Unknown"
            duration_label = info.get('duration_string') or "—"
            st.caption(f"Channel: {uploader} | Duration: {duration_label}")

    if download_disabled:
        st.warning(
            "No downloadable media streams are available for this analysis. "
            "Try browser cookies or a PO token, then run Analyze again."
        )

    st.divider()
    
    # --- Options ---
    d_col1, d_col2 = st.columns(2)

    with d_col1:
        if mode_options:
            mode = st.radio("Mode", mode_options, index=0)
        else:
            mode = None
            st.caption("No download modes available for the current analysis.")
    
    with d_col2:
        selected_format = "MP3"
        selected_res = downloadable_video_heights[0] if downloadable_video_heights else 720
        use_hardware = False
        conversion_mode = None 
        force_stereo_dl = False 
        
        # ==========================
        # VIDEO MODE UI
        # ==========================
        if mode == "Video + Audio":
            selected_res = st.selectbox("Resolution", downloadable_video_heights, index=0)
            
            # --- HDR LOGIC ---
            if is_hdr:
                c_dr, c_fmt = st.columns(2)
                dr_choice = c_dr.selectbox("Dynamic Range", ["HDR (High Dynamic Range)", "SDR (Standard Range)"])
                
                if "HDR" in dr_choice:
                    format_options = ["Apple HDR (H.265) 🎨", "Original (MKV) 💾"]
                    sel_fmt_str = c_fmt.selectbox("Format", format_options)
                    if "Apple" in sel_fmt_str:
                        conversion_mode = "apple_hdr"
                else:
                    c_fmt.selectbox("Format", ["Standard MP4 (H.264 / Re-encode) 🐇"], disabled=True)
                    conversion_mode = "sdr"
            
            # --- SDR/STANDARD LOGIC ---
            else:
                format_options = ["Best (MKV/WebM) - No Conversion", "Standard MP4 (H.264 / Re-encode)"]
                sel_fmt_str = st.selectbox("Format", format_options)
                
                if "Standard MP4" in sel_fmt_str:
                    conversion_mode = "sdr" # Force re-encode to ensure compatibility
                else:
                    conversion_mode = None # Original

            # --- AUDIO MIX (For Manual Conversions) ---
            if is_surround and conversion_mode in ["apple_hdr", "sdr"]:
                aud_mix = st.radio("Audio Mix", [f"Keep Surround ({max_channels}ch)", "Downmix to Stereo"], horizontal=True)
                if "Downmix" in aud_mix:
                    force_stereo_dl = True
            
            # --- HARDWARE ACCELERATION ---
            if conversion_mode in ["apple_hdr", "sdr"]:
                is_mac, is_arm = get_system_capabilities()
                if is_mac:
                    st.caption("Encoding Engine:")
                    hw_label = "Apple Silicon 🚀" if is_arm else "Apple Hardware ⚡️"
                    enc_choice = st.radio("Engine", [hw_label, "CPU 🐢"], label_visibility="collapsed")
                    if "Apple" in enc_choice: use_hardware = True

        # ==========================
        # AUDIO ONLY MODE UI
        # ==========================
        elif mode == "Audio Only":
            if is_surround:
                st.info(f"Source has {max_channels} channels.")
                audio_type = st.radio("Audio Format", ["Stereo (MP3)", "Surround (M4A)"])
                if "Stereo" in audio_type:
                    selected_format = "MP3"
                    force_stereo_dl = True
                else:
                    selected_format = "M4A"
            else:
                selected_format = "MP3"

    # --- Download Button ---
    if st.button("⬇️ Download Now", type="primary", disabled=download_disabled):
        st.write("---")
        log_to_console("--- Download Started ---")
        st.session_state.last_error_line = ""
        
        step1_text = st.empty()
        prog_bar_dl = st.progress(0)
        step2_text = st.empty()
        prog_bar_conv = st.empty()

        try:
            ensure_ffmpeg()
            save_path.mkdir(parents=True, exist_ok=True)
            dl_logger = DownloadLogger(prog_bar_dl, step1_text)
            preferred_download_runtime = st.session_state.effective_js_runtime or js_runtime

            ydl_opts = {
                'outtmpl': str(save_path / '%(title)s [%(id)s].%(ext)s'),
                'noplaylist': True,
                'retries': 5,
                'fragment_retries': 10,
                'file_access_retries': 3,
                'continuedl': False,
                'overwrites': True,
                'restrictfilenames': True,
                'progress_hooks': [dl_logger.hook],
            }
            ydl_opts.update(build_base_opts(browser, cookie_file, prefer_tv, po_token, preferred_download_runtime))

            needs_manual_conversion = False
            format_candidates: List[str] = []
            
            # --- SETUP DOWNLOAD ---
            if mode == "Audio Only":
                ydl_opts['format'] = 'bestaudio/best'
                if selected_format == "MP3":
                    args = ['-ac', '2'] if is_surround else []
                    ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}]
                    if args:
                        ydl_opts['postprocessor_args'] = args
                elif selected_format == "M4A":
                    ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio','preferredcodec': 'm4a','preferredquality': '320'}]
            
            else: # Video Mode
                format_candidates = build_video_format_candidates(info, selected_res)
                ydl_opts['format'] = format_candidates[0]
                
                if conversion_mode in ["apple_hdr", "sdr"]:
                    ydl_opts['merge_output_format'] = 'mkv'
                    needs_manual_conversion = True
                else:
                    ydl_opts['merge_output_format'] = 'mkv'

            # 1. DOWNLOAD
            download_result = None
            attempts = format_candidates if format_candidates else [ydl_opts['format']]
            last_download_error: Optional[Exception] = None

            for attempt_num, format_expr in enumerate(attempts, start=1):
                attempt_opts = copy.deepcopy(ydl_opts)
                attempt_opts['format'] = format_expr
                log_to_console(f"Starting yt-dlp download (attempt {attempt_num}/{len(attempts)}) with format: {format_expr}")
                try:
                    download_result, used_js_runtime = extract_info_with_runtime_fallback(
                        st.session_state.last_url,
                        attempt_opts,
                        download=True,
                        js_runtime=preferred_download_runtime,
                    )
                    st.session_state.effective_js_runtime = used_js_runtime
                    break
                except Exception as e:
                    last_download_error = e
                    err_text = str(e).lower()

                    if "requested format is not available" in err_text and "cookiesfrombrowser" in attempt_opts:
                        log_to_console("Browser cookies changed format selection. Retrying without browser cookies...")
                        try:
                            no_cookie_opts = rebuild_download_opts_without_browser_cookies(
                                attempt_opts,
                                prefer_tv=prefer_tv,
                                po_token=po_token,
                                js_runtime=preferred_download_runtime,
                            )
                            download_result, used_js_runtime = extract_info_with_runtime_fallback(
                                st.session_state.last_url,
                                no_cookie_opts,
                                download=True,
                                js_runtime=preferred_download_runtime,
                            )
                            st.session_state.effective_js_runtime = used_js_runtime
                            break
                        except Exception as cookie_retry_error:
                            last_download_error = cookie_retry_error
                            err_text = str(cookie_retry_error).lower()

                    if attempt_num < len(attempts) and should_retry_download(err_text):
                        log_to_console("Retrying with fallback format...")
                        continue
                    raise last_download_error

            if download_result is None and last_download_error:
                raise last_download_error
                
            # 2. LOCATE
            downloaded_file = locate_downloaded_file(download_result, dl_logger.filename, save_path, info['id'])
            if not downloaded_file:
                raise FileNotFoundError("Could not locate downloaded file or the file is empty.")
            
            log_to_console(f"File downloaded to: {downloaded_file}")

            # 3. CONVERSION
            if needs_manual_conversion and downloaded_file:
                step1_text.text("Download complete. Starting Converter...")
                
                prog_bar_conv_actual = prog_bar_conv.progress(0)
                step2_text.text(f"Initializing Conversion ({conversion_mode})...")
                
                output_file = downloaded_file.with_suffix(".mp4")
                duration = info.get('duration', 0)
                
                log_to_console(f"Starting conversion: {conversion_mode}, HW: {use_hardware}")
                
                # Pass 'is_hdr' to conversion function
                run_ffmpeg_conversion(
                    downloaded_file, 
                    output_file, 
                    duration, 
                    prog_bar_conv_actual, 
                    step2_text,
                    mode=conversion_mode,
                    use_hardware_accel=use_hardware,
                    is_source_hdr=is_hdr,
                    is_surround=is_surround,
                    force_stereo=force_stereo_dl
                )
                
                try:
                    os.remove(downloaded_file)
                except OSError:
                    pass
                final_file = output_file
            else:
                step2_text.text("Skipping conversion (Original Format selected).")
                final_file = downloaded_file

            # 4. DONE
            prog_bar_dl.progress(1.0)
            if needs_manual_conversion:
                prog_bar_conv.progress(1.0)
                step2_text.text("Processing Complete!")
            
            if not final_file.exists() or final_file.stat().st_size == 0:
                raise RuntimeError("Final output file is missing or empty after processing.")

            step1_text.text("All operations finished.")
            st.success(f"Saved to: {final_file.name}")
            st.balloons()
            log_to_console("All Done!")

        except Exception as e:
            video_id = str(info.get("id") or "") if isinstance(info, dict) else ""
            cleanup_partials(save_path, video_id)
            handle_error(e)
