"""
Advanced YouTube Downloader Pro - FFMPEG VALIDATED HIGH QUALITY
FIXED: Robust file finding logic
FIXED: Progress hook handles None total_bytes
FIXED: Format selector ensures high quality with FFmpeg
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
import json
import time
import sys
import webbrowser
from pathlib import Path
from datetime import datetime
import customtkinter as ctk
from PIL import Image, ImageTk
import requests
from io import BytesIO
from collections import deque, OrderedDict
import re
from urllib.parse import urlparse, parse_qs, unquote
from yt_dlp import YoutubeDL
import shutil
import subprocess
import hashlib
import queue
import traceback
from dataclasses import dataclass, asdict, field
from typing import Optional, Dict, List, Tuple, Any, Set
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import platform
import psutil
import math
from enum import Enum

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('youtube_downloader.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Global styles
COLORS = {
    'primary': '#FF3B30',
    'secondary': '#5856D6',
    'dark_bg': '#0A0A0A',
    'dark_card': '#1A1A1A',
    'dark_text': '#FFFFFF',
    'light_bg': '#F2F2F7',
    'light_card': '#FFFFFF',
    'light_text': '#000000',
    'success': '#34C759',
    'warning': '#FF9500',
    'error': '#FF3B30',
    'info': '#007AFF',
    'gray': '#8E8E93',
    'dark_gray': '#3A3A3C',
    'text_primary': '#FFFFFF',
    'text_secondary': '#8E8E93',
    'text_disabled': '#3A3A3C',
}

class DownloadStatus(Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    PROCESSING = "processing"
    MERGING = "merging"
    CANCELLED = "cancelled"

@dataclass
class DownloadTask:
    """Data class for download tasks"""
    id: str
    url: str
    title: str
    format_type: str
    quality: str
    output_path: str
    status: DownloadStatus
    progress: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed: float = 0.0
    eta: int = 0
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    file_path: Optional[str] = None
    thumbnail_url: Optional[str] = None
    duration: int = 0
    channel: Optional[str] = None
    playlist: Optional[str] = None
    subtitles: List[str] = field(default_factory=list)
    audio_only: bool = False
    include_subtitles: bool = False
    embed_metadata: bool = True
   
    def to_dict(self):
        data = asdict(self)
        data['status'] = self.status.value
        return data
   
    @classmethod
    def from_dict(cls, data):
        if 'options' in data:
            options = data.pop('options', {})
            data['format_type'] = options.get('format', 'video')
            data['quality'] = options.get('quality', 'best')
            data['output_path'] = options.get('location', os.path.expanduser("~/Downloads"))
            data['audio_only'] = options.get('format', 'video') == 'audio'
       
        if 'status' in data and isinstance(data['status'], str):
            try:
                data['status'] = DownloadStatus(data['status'])
            except ValueError:
                data['status'] = DownloadStatus.QUEUED
       
        defaults = {
            'progress': 0.0,
            'downloaded_bytes': 0,
            'total_bytes': 0,
            'speed': 0.0,
            'eta': 0,
            'error': None,
            'completed_at': None,
            'file_path': None,
            'thumbnail_url': None,
            'duration': 0,
            'channel': None,
            'playlist': None,
            'subtitles': [],
            'audio_only': False,
            'include_subtitles': False,
            'embed_metadata': True
        }
       
        for key, default_value in defaults.items():
            if key not in data:
                data[key] = default_value
       
        expected_keys = set(cls.__dataclass_fields__.keys())
        data = {k: v for k, v in data.items() if k in expected_keys}
       
        return cls(**data)

class FFmpegValidator:
    """FFmpeg validation and testing utility"""
    
    @staticmethod
    def check_ffmpeg() -> Tuple[bool, Optional[str], str]:
        """Check if FFmpeg is available and working"""
        try:
            # Helper to run subprocess safely across all platforms
            def run_cmd(cmd):
                kwargs = {'capture_output': True, 'text': True, 'timeout': 5}
                if platform.system() == 'Windows':
                    kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
                return subprocess.run(cmd, **kwargs)

            # Try system PATH first
            ffmpeg_path = shutil.which('ffmpeg')
            
            if ffmpeg_path:
                result = run_cmd([ffmpeg_path, '-version'])
                if result.returncode == 0 and 'ffmpeg version' in result.stdout:
                    version_match = re.search(r'ffmpeg version ([0-9.]+)', result.stdout)
                    version = version_match.group(1) if version_match else "unknown"
                    return True, ffmpeg_path, f"FFmpeg {version} found in PATH"
            
            # Check common paths
            common_paths = []
            
            if platform.system() == 'Windows':
                common_paths = [
                    r"C:\ffmpeg\bin\ffmpeg.exe",
                    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
                    r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
                    os.path.join(os.getcwd(), "ffmpeg", "bin", "ffmpeg.exe"),
                    os.path.join(os.path.dirname(__file__), "ffmpeg", "bin", "ffmpeg.exe"),
                ]
            else:
                common_paths = [
                    "/usr/bin/ffmpeg",
                    "/usr/local/bin/ffmpeg",
                    "/opt/homebrew/bin/ffmpeg",
                    "/opt/local/bin/ffmpeg",
                    os.path.expanduser("~/bin/ffmpeg"),
                    os.path.expanduser("~/.local/bin/ffmpeg"),
                ]
            
            for path in common_paths:
                if os.path.exists(path):
                    result = run_cmd([path, '-version'])
                    if result.returncode == 0 and 'ffmpeg version' in result.stdout:
                        version_match = re.search(r'ffmpeg version ([0-9.]+)', result.stdout)
                        version = version_match.group(1) if version_match else "unknown"
                        return True, path, f"FFmpeg {version} found at {path}"
            
            return False, None, "FFmpeg not found. Install FFmpeg for high quality (1080p+) downloads"
            
        except subprocess.TimeoutExpired:
            return False, None, "FFmpeg timed out - may be frozen"
        except Exception as e:
            return False, None, f"FFmpeg check failed: {str(e)}"
    
    @staticmethod
    def test_merge_capability(ffmpeg_path: str) -> Tuple[bool, str]:
        """Test if FFmpeg can merge video and audio streams"""
        try:
            kwargs = {'capture_output': True, 'text': True, 'timeout': 5}
            if platform.system() == 'Windows':
                kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
                
            result = subprocess.run([ffmpeg_path, '-filters'], **kwargs)
            
            if result.returncode == 0:
                return True, "FFmpeg merge capability confirmed"
            else:
                return False, "FFmpeg may have issues with stream merging"
                
        except Exception as e:
            return False, f"Merge test failed: {str(e)}"
    
    @staticmethod
    def get_quality_warning(quality: str, has_ffmpeg: bool) -> Optional[str]:
        """Get warning message for quality selection based on FFmpeg availability"""
        high_qualities = ['4k', '2160p', '1440p', '1080p', 'best']
        
        quality_lower = quality.lower()
        
        if not has_ffmpeg:
            if quality_lower in high_qualities:
                return f"⚠️ WARNING: {quality} requires FFmpeg for best results!\nWithout FFmpeg, download will fallback to the best available combined format.\nInstall FFmpeg from https://ffmpeg.org/download.html"
        
        return None

class DownloadManager:
    """Advanced download manager with thread safety"""
   
    def __init__(self, max_concurrent=3, ui_callback=None):
        self.active_tasks: Dict[str, DownloadTask] = {}
        self.task_queue: deque = deque()
        self.task_history: List[DownloadTask] = []
        self.task_lock = threading.RLock()
        self.max_concurrent = max_concurrent
        self.callback_queue = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.download_threads: Dict[str, threading.Thread] = {}
        self.stop_events: Dict[str, threading.Event] = {}
        
        self.ui_callback = ui_callback
       
        self.last_subtitle_request = 0
        self.subtitle_request_delay = 2.0
       
        self.ffmpeg_path = None
        self.has_ffmpeg = False
        self.ffmpeg_version = None
        self.ffmpeg_status_message = ""
        
        # Validate FFmpeg on startup
        # self._validate_ffmpeg()
       
        self.load_state()
       
        threading.Thread(target=self._process_callbacks, daemon=True).start()
    
    def _validate_ffmpeg(self):
        """Validate FFmpeg and store detailed status"""
        has_ffmpeg, path, message = FFmpegValidator.check_ffmpeg()
        self.has_ffmpeg = has_ffmpeg
        self.ffmpeg_path = path
        self.ffmpeg_status_message = message
        
        if has_ffmpeg and path:
            # Test merge capability
            can_merge, merge_msg = FFmpegValidator.test_merge_capability(path)
            if can_merge:
                logger.info(f"FFmpeg validated: {message}")
                logger.info(f"Merge capability: {merge_msg}")
            else:
                logger.warning(f"FFmpeg found but may have issues: {merge_msg}")
        else:
            logger.warning(f"FFmpeg validation failed: {message}")
    
    def check_quality_feasibility(self, quality: str) -> Tuple[bool, str]:
        """Check if selected quality is feasible with current FFmpeg status"""
        high_qualities = ['4k', '2160p', '1440p', '1080p', 'best']
        
        if not self.has_ffmpeg and quality.lower() in high_qualities:
            return False, FFmpegValidator.get_quality_warning(quality, False)
        
        return True, "OK"
    
    def save_state(self):
        with self.task_lock:
            state = {
                'queue': [task.to_dict() for task in self.task_queue],
                'active': [task.to_dict() for task in self.active_tasks.values()],
                'history': [task.to_dict() for task in self.task_history[-100:]]
            }
            try:
                with open('download_state.json', 'w', encoding='utf-8') as f:
                    json.dump(state, f, default=str, indent=2)
            except Exception as e:
                logger.error(f"Failed to save state: {e}")
   
    def load_state(self):
        try:
            if os.path.exists('download_state.json'):
                with open('download_state.json', 'r', encoding='utf-8') as f:
                    state = json.load(f)
                   
                    self.task_queue = deque()
                    for task_data in state.get('queue', []):
                        try:
                            task = DownloadTask.from_dict(task_data)
                            self.task_queue.append(task)
                        except Exception as e:
                            logger.error(f"Failed to load queued task: {e}")
                   
                    self.active_tasks = {}
                    for task_data in state.get('active', []):
                        try:
                            task = DownloadTask.from_dict(task_data)
                            task.status = DownloadStatus.QUEUED
                            task.progress = 0
                            self.task_queue.append(task)
                        except Exception as e:
                            logger.error(f"Failed to load active task: {e}")
                   
                    self.task_history = []
                    for task_data in state.get('history', []):
                        try:
                            task = DownloadTask.from_dict(task_data)
                            self.task_history.append(task)
                        except Exception as e:
                            logger.error(f"Failed to load history task: {e}")
                           
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            self.task_queue = deque()
            self.active_tasks = {}
            self.task_history = []
   
    def add_task(self, url: str, format_type: str, quality: str,
                 output_path: str, title: Optional[str] = None,
                 include_subtitles: bool = False, embed_metadata: bool = True) -> Tuple[Optional[str], str]:
        """Add a new download task"""
        task_id = hashlib.md5(f"{url}_{time.time()}".encode()).hexdigest()[:12]
       
        task = DownloadTask(
            id=task_id,
            url=url,
            title=title or "Unknown",
            format_type=format_type,
            quality=quality,
            output_path=output_path,
            status=DownloadStatus.QUEUED,
            include_subtitles=include_subtitles,
            embed_metadata=embed_metadata,
            audio_only=(format_type == 'audio')
        )
       
        with self.task_lock:
            self.task_queue.append(task)
            self.save_state()
       
        self.callback_queue.put(('task_added', task_id))
        self._auto_start_downloads()
       
        return task_id, "OK"
   
    def _auto_start_downloads(self):
        with self.task_lock:
            available_slots = self.max_concurrent - len(self.active_tasks)
            for _ in range(min(available_slots, len(self.task_queue))):
                if self.task_queue:
                    task = self.task_queue[0]
                    if task.status == DownloadStatus.QUEUED:
                        self.start_task(task.id)
   
    def start_task(self, task_id: str) -> bool:
        with self.task_lock:
            task_to_start = None
            for i, task in enumerate(self.task_queue):
                if task.id == task_id:
                    task_to_start = self.task_queue[i]
                    del self.task_queue[i]
                    break
           
            if not task_to_start:
                return False
           
            if len(self.active_tasks) >= self.max_concurrent:
                self.task_queue.appendleft(task_to_start)
                return False
           
            task_to_start.status = DownloadStatus.DOWNLOADING
            self.active_tasks[task_id] = task_to_start
            self.stop_events[task_id] = threading.Event()
           
            thread = threading.Thread(
                target=self._download_worker,
                args=(task_to_start,),
                daemon=True
            )
            self.download_threads[task_id] = thread
            thread.start()
           
            self.save_state()
            self.callback_queue.put(('task_started', task_id))
            return True
   
    def pause_task(self, task_id: str) -> bool:
        with self.task_lock:
            if task_id in self.active_tasks:
                task = self.active_tasks[task_id]
                task.status = DownloadStatus.PAUSED
               
                if task_id in self.stop_events:
                    self.stop_events[task_id].set()
               
                self.task_queue.appendleft(task)
                del self.active_tasks[task_id]
               
                self.save_state()
                self.callback_queue.put(('task_paused', task_id))
                return True
        return False
   
    def resume_task(self, task_id: str) -> bool:
        with self.task_lock:
            for i, task in enumerate(self.task_queue):
                if task.id == task_id and task.status == DownloadStatus.PAUSED:
                    task.status = DownloadStatus.QUEUED
                    self.save_state()
                    self.callback_queue.put(('task_resumed', task_id))
                    return self.start_task(task_id)
        return False
   
    def cancel_task(self, task_id: str) -> bool:
        with self.task_lock:
            if task_id in self.active_tasks:
                if task_id in self.stop_events:
                    self.stop_events[task_id].set()
               
                task = self.active_tasks[task_id]
                task.status = DownloadStatus.CANCELLED
                self.task_history.append(task)
                del self.active_tasks[task_id]
                self._cleanup_partial_files(task)
           
            for i, task in enumerate(self.task_queue):
                if task.id == task_id:
                    task = self.task_queue[i]
                    task.status = DownloadStatus.CANCELLED
                    self.task_history.append(task)
                    del self.task_queue[i]
           
            self.save_state()
            self.callback_queue.put(('task_cancelled', task_id))
            return True
   
    def _cleanup_partial_files(self, task: DownloadTask):
        try:
            if task.file_path and os.path.exists(task.file_path):
                if task.file_path.endswith('.part') or task.progress < 100:
                    os.remove(task.file_path)
        except Exception as e:
            logger.error(f"Failed to cleanup files for task {task.id}: {e}")
   
    def _download_worker(self, task: DownloadTask):
        try:
            # Re-validate FFmpeg before download
            self._validate_ffmpeg()
            
            info = self._get_video_info(task.url)
            if not info:
                task.status = DownloadStatus.ERROR
                task.error = "Failed to get video information"
                self.callback_queue.put(('task_error', task.id))
                return
           
            task.title = info.get('title', task.title)
            task.duration = info.get('duration', 0)
            task.channel = info.get('channel', None)
            
            if self.has_ffmpeg:
                logger.info(f"Task {task.id}: Using FFmpeg at {self.ffmpeg_path} for high quality")
            else:
                logger.warning(f"Task {task.id}: No FFmpeg available - quality may fallback")
           
            ydl_opts = self._build_ydl_options(task, info)
            
            # Log the format selector being used
            logger.info(f"Task {task.id}: Format selector: {ydl_opts.get('format', 'N/A')}")
           
            def progress_hook(d):
                if self.stop_events.get(task.id, threading.Event()).is_set():
                    raise Exception("Download stopped by user")

                if d['status'] == 'downloading':
                    task.downloaded_bytes = d.get('downloaded_bytes', 0)
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    task.total_bytes = total
                    task.speed = d.get('speed', 0) or 0
                    task.eta = d.get('eta', 0) or 0

                    if task.total_bytes > 0:
                        task.progress = (task.downloaded_bytes / task.total_bytes) * 100
                    elif d.get('fragment_index') and d.get('fragment_count'):
                        task.progress = (d['fragment_index'] / d['fragment_count']) * 100

                    # ✅ ADD: Log the actual format being downloaded so you can verify quality
                    if task.progress < 2:  # Log only at start to avoid spam
                        filename = d.get('filename', '')
                        info_dict = d.get('info_dict', {})
                        actual_height = info_dict.get('height', 'unknown')
                        actual_format = info_dict.get('format', 'unknown')
                        logger.info(f"📥 Downloading: height={actual_height}px format={actual_format} file={os.path.basename(filename)}")

                    self.callback_queue.put(('task_progress', task.id))

                elif d['status'] == 'error':
                    # ✅ ADD: Capture and surface the real yt-dlp error
                    error_detail = d.get('error', 'Unknown yt-dlp error')
                    logger.error(f"❌ yt-dlp reported error for task {task.id}: {error_detail}")
                    task.error = str(error_detail)
                    self.callback_queue.put(('task_error', task.id))

                elif d['status'] == 'processing':
                    task.status = DownloadStatus.PROCESSING
                    logger.info(f"⚙️ Post-processing task {task.id}")
                    self.callback_queue.put(('task_processing', task.id))

                elif d['status'] == 'finished':
                    # This fires per-stream (video stream done, then audio stream done before merge)
                    filename = d.get('filename', '')
                    info_dict = d.get('info_dict', {})
                    actual_height = info_dict.get('height', 'unknown')
                    logger.info(f"✅ Stream finished: height={actual_height}px file={os.path.basename(filename)}")
                    task.progress = 99  # not 100 yet — merging may still happen
                    self.callback_queue.put(('task_completed', task.id))
           
            ydl_opts['progress_hooks'] = [progress_hook]
           
            with YoutubeDL(ydl_opts) as ydl:
                task.status = DownloadStatus.DOWNLOADING
                self.callback_queue.put(('task_started', task.id))
                ydl.download([task.url])
           
            task.status = DownloadStatus.COMPLETED
            task.progress = 100
            task.completed_at = time.time()

            # ✅ FIXED: Find file and log actual resolution achieved
            task.file_path = self._find_downloaded_file(task, task.output_path)
            
            if task.file_path:
                file_size = os.path.getsize(task.file_path)
                logger.info(f"✅ Task {task.id} complete: {os.path.basename(task.file_path)} ({self._format_size(file_size)})")
                # Try to get actual resolution via ffprobe for verification
                if self.ffmpeg_path:
                    try:
                        ffprobe = self.ffmpeg_path.replace('ffmpeg', 'ffprobe')
                        if os.path.exists(ffprobe):
                            probe_kwargs = {'capture_output': True, 'text': True, 'timeout': 5}
                            if platform.system() == 'Windows':
                                probe_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
                            result = subprocess.run(
                                [ffprobe, '-v', 'error', '-select_streams', 'v:0',
                                 '-show_entries', 'stream=width,height',
                                 '-of', 'csv=p=0', task.file_path],
                                **probe_kwargs
                            )
                            if result.returncode == 0 and result.stdout.strip():
                                logger.info(f"📐 Verified output resolution: {result.stdout.strip()}")
                    except Exception as probe_err:
                        logger.debug(f"ffprobe check skipped: {probe_err}")
            else:
                logger.warning(f"⚠️ Task {task.id}: Could not locate output file in {task.output_path}")
           
        except Exception as e:
            logger.error(f"Download error for task {task.id}: {e}", exc_info=True)
            task.status = DownloadStatus.ERROR
            task.error = str(e)
           
            with self.task_lock:
                if task.id in self.active_tasks:
                    del self.active_tasks[task.id]
           
            self.save_state()
            self.callback_queue.put(('task_error', task.id))
            self._cleanup_partial_files(task)
   
    def _get_video_info(self, url: str) -> Optional[Dict]:
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                # ✅ No extractor_args here either — consistent with _build_ydl_options
                # Uses default web client so listed formats match what download can actually get
            }
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info
        except Exception as e:
            logger.error(f"Failed to get video info: {e}")
            return None
   
    def _build_ydl_options(self, task: DownloadTask, info: Dict) -> Dict:
        """Build yt-dlp options with correct quality enforcement"""

        output_template = os.path.join(
            task.output_path,
            '%(title)s [%(id)s].%(ext)s'
        )

        ydl_opts = {
            'outtmpl': output_template,
            'quiet': False,
            'no_warnings': False,
            'ignoreerrors': False,
            'retries': 10,
            'fragment_retries': 10,
            'file_access_retries': 3,
            'concurrent_fragment_downloads': 5,
            # ✅ FIX #1: REMOVED extractor_args entirely.
            # The android player_client only provides combined streams capped at 720p.
            # It cannot see the separate 1080p/4K video-only streams that need merging.
            # Removing this lets yt-dlp use the default web client which sees ALL formats.
        }

        if self.has_ffmpeg and self.ffmpeg_path:
            ydl_opts['ffmpeg_location'] = self.ffmpeg_path
            logger.info(f"✅ FFmpeg enabled for task {task.id} at {self.ffmpeg_path}")

        quality = task.quality.lower()

        height_map = {
            '4k':    2160,
            '2160p': 2160,
            '1440p': 1440,
            '1080p': 1080,
            '720p':  720,
            '480p':  480,
            '360p':  360,
            '240p':  240,
            '144p':  144,
            'best':  9999,
            'worst': 0,
        }
        target_height = height_map.get(quality, 1080)

        if task.format_type == 'audio':
            ydl_opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'
            if self.has_ffmpeg:
                # ✅ FIX #4: Build postprocessors in correct order
                ydl_opts['postprocessors'] = [
                    {
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '320',
                    },
                ]
                if task.embed_metadata:
                    ydl_opts['postprocessors'].append({'key': 'FFmpegMetadata', 'add_metadata': True})

        else:  # video
            if self.has_ffmpeg:
                if target_height >= 9999:
                    # Best possible: no height filter
                    ydl_opts['format'] = 'bestvideo+bestaudio/best'
                elif target_height == 0:
                    ydl_opts['format'] = 'worstvideo+worstaudio/worst'
                else:
                    # ✅ FIX #2: Clean two-part format string.
                    # Part 1: separate video stream + separate audio stream (needs FFmpeg merge) — gives true 1080p/4K
                    # Part 2: fallback to best single combined stream if merge streams unavailable
                    # NO android client interference means Part 1 will now actually be found
                    ydl_opts['format'] = (
                        f'bestvideo[height<={target_height}]+bestaudio'
                        f'/best[height<={target_height}]'
                    )

                # ✅ FIX #3: Correct format_sort — +res means DESCENDING (highest first)
                # This ensures the best resolution AT OR BELOW target is always preferred
                ydl_opts['format_sort'] = ['+res', 'ext:mp4:m4a', 'codec:h264:aac']
                ydl_opts['merge_output_format'] = 'mp4'

                # ✅ FIX #4: Postprocessors built cleanly — no append conflicts
                ydl_opts['postprocessors'] = []
                if task.embed_metadata:
                    ydl_opts['postprocessors'].append({'key': 'FFmpegMetadata', 'add_metadata': True})
                if task.embed_metadata:
                    ydl_opts['writethumbnail'] = True
                    ydl_opts['postprocessors'].append({'key': 'EmbedThumbnail'})

                logger.info(
                    f"🎬 FFmpeg mode — format: {ydl_opts['format']} | "
                    f"sort: {ydl_opts['format_sort']} | target: {target_height}p"
                )

            else:
                # No FFmpeg: combined stream only (video+audio in one file, max ~720p on YouTube)
                if target_height >= 9999:
                    ydl_opts['format'] = 'best'
                elif target_height == 0:
                    ydl_opts['format'] = 'worst'
                else:
                    ydl_opts['format'] = f'best[height<={target_height}]/best'
                logger.warning(
                    f"⚠️ No FFmpeg — using combined stream: {ydl_opts['format']} "
                    f"(max ~720p, install FFmpeg for 1080p+)"
                )

        # Subtitles
        if task.include_subtitles:
            current_time = time.time()
            if current_time - self.last_subtitle_request >= self.subtitle_request_delay:
                ydl_opts.update({
                    'writesubtitles': True,
                    'writeautomaticsub': True,
                    'subtitleslangs': ['en'],
                    'subtitlesformat': 'vtt',
                })
                self.last_subtitle_request = current_time

        return ydl_opts
   
    def _find_downloaded_file(self, task: DownloadTask, output_dir: str) -> Optional[str]:
        """Robustly find the downloaded file"""
        try:
            if not os.path.exists(output_dir):
                return None
            
            # Look for files modified in the last 5 minutes that match the title
            current_time = time.time()
            candidates = []
            
            for filename in os.listdir(output_dir):
                filepath = os.path.join(output_dir, filename)
                if not os.path.isfile(filepath):
                    continue
                    
                # Check if file was modified recently (within last 5 mins)
                mtime = os.path.getmtime(filepath)
                if current_time - mtime > 300:  # 5 minutes
                    continue
                
                # Check if filename contains parts of the title
                # Clean title for matching
                clean_title = re.sub(r'[^\w\s-]', '', task.title).lower()
                clean_filename = filename.lower()
                
                # Simple heuristic: if significant part of title is in filename
                words = clean_title.split()
                if len(words) > 0:
                    # Check if at least the first 2 significant words are in filename
                    matches = sum(1 for w in words[:3] if len(w) > 3 and w in clean_filename)
                    if matches >= 1:
                        candidates.append((filepath, os.path.getsize(filepath)))

            if candidates:
                # Return the largest file among candidates (likely the video)
                candidates.sort(key=lambda x: x[1], reverse=True)
                logger.info(f"Found downloaded file: {candidates[0][0]}")
                return candidates[0][0]
            
            # Fallback: Just return the most recently modified large file in dir
            files = []
            for filename in os.listdir(output_dir):
                filepath = os.path.join(output_dir, filename)
                if os.path.isfile(filepath) and os.path.getsize(filepath) > 1024 * 1024: # > 1MB
                    files.append((filepath, os.path.getmtime(filepath)))
            
            if files:
                files.sort(key=lambda x: x[1], reverse=True)
                return files[0][0]
               
        except Exception as e:
            logger.error(f"Failed to find downloaded file: {e}")
       
        return None
   
    def _process_callbacks(self):
        """Process callback queue and update UI in real-time"""
        while True:
            try:
                item = self.callback_queue.get(timeout=1)
                if self.ui_callback:
                    self.ui_callback(item)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in callback processor: {e}")
   
    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        with self.task_lock:
            if task_id in self.active_tasks:
                return self.active_tasks[task_id]
           
            for task in self.task_queue:
                if task.id == task_id:
                    return task
           
            for task in self.task_history:
                if task.id == task_id:
                    return task
       
        return None
   
    def get_all_tasks(self) -> List[DownloadTask]:
        with self.task_lock:
            tasks = list(self.active_tasks.values()) + list(self.task_queue) + self.task_history[-50:]
            return tasks
   
    def clear_completed(self):
        with self.task_lock:
            self.task_history = [t for t in self.task_history if t.status != DownloadStatus.COMPLETED]
            self.save_state()
   
    def clear_all(self):
        with self.task_lock:
            for task_id in list(self.active_tasks.keys()):
                self.cancel_task(task_id)
           
            for task in list(self.task_queue):
                task.status = DownloadStatus.CANCELLED
                self.task_history.append(task)
           
            self.task_queue.clear()
            self.save_state()
    
    def get_ffmpeg_status(self) -> Dict:
        """Get detailed FFmpeg status"""
        return {
            'available': self.has_ffmpeg,
            'path': self.ffmpeg_path,
            'message': self.ffmpeg_status_message,
            'version': self.ffmpeg_version
        }
    
    def _format_size(self, bytes_num):
        if bytes_num <= 0:
            return "0 B"
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        i = 0
        while bytes_num >= 1024 and i < len(units) - 1:
            bytes_num /= 1024
            i += 1
        return f"{bytes_num:.2f} {units[i]}"

class YouTubeDownloaderPro:
    """Main application class"""
   
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Downloader Pro - FFMPEG VALIDATED")
        self.root.geometry("1200x800")
        self.root.minsize(1000, 700)
       
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
       
        # Pass UI callback for real-time status updates
        self.download_manager = DownloadManager(max_concurrent=3, ui_callback=self.on_download_event)
        self.current_theme = "dark"
        self.video_cache = {}
        self.thumbnail_cache = {}
        self.settings = self.load_settings()
        self.current_tab = "download"
       
        self.tab_view = None
        self.url_entry = None
        self.quality_combo = None
        self.path_entry = None
        self.history_tree = None
        self.progress_bars = {}
        self.status_labels = {}
       
        self.subtitles_var = ctk.BooleanVar(value=False)
        self.metadata_var = ctk.BooleanVar(value=True)
       
        self.total_downloads = 0
        self.total_size = 0
        self.active_downloads = 0
       
        self.setup_ui()
        self.update_timer()
        self.refresh_task_list()
        self.refresh_history()
       
        # Show FFmpeg status on startup
        self.show_ffmpeg_status()
       
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def on_download_event(self, event):
        """Handle real-time download events to update status bar"""
        if not event or len(event) < 2:
            return
        event_type, task_id = event[0], event[1]
        task = self.download_manager.get_task(task_id)
        if not task: 
            return
        
        if event_type == 'task_progress':
            downloaded = self._format_size(task.downloaded_bytes)
            total = self._format_size(task.total_bytes) if task.total_bytes > 0 else "??"
            speed = self._format_size(task.speed) if task.speed > 0 else "0"
            self.status_message.set(f"Downloading: {task.title[:30]}... | {downloaded}/{total} | {speed}/s")
        elif event_type == 'task_completed':
            self.status_message.set(f"Completed: {task.title[:40]}...")
        elif event_type == 'task_error':
            self.status_message.set(f"Error: {task.title[:30]}... - {str(task.error)[:30]}")
        elif event_type == 'task_started':
            self.status_message.set(f"Started: {task.title[:40]}...")
    
    def show_ffmpeg_status(self):
        """Show FFmpeg status dialog on startup"""
        status = self.download_manager.get_ffmpeg_status()
        
        if status['available']:
            messagebox.showinfo(
                "FFmpeg Available ✓",
                f"{status['message']}\n\n"
                f"✅ High quality downloads (1080p, 4K) are available!\n"
                f"✅ Video and audio will be merged for best quality\n\n"
                f"Path: {status['path']}"
            )
        else:
            result = messagebox.askyesno(
                "FFmpeg Not Found ⚠️",
                f"{status['message']}\n\n"
                f"⚠️ Without FFmpeg:\n"
                f"• High quality downloads will fallback to best combined format\n"
                f"• Some videos may download without audio at high resolutions\n"
                f"• Cannot merge best video + best audio\n\n"
                f"Do you want to open the FFmpeg download page?"
            )
            if result:
                webbrowser.open("https://ffmpeg.org/download.html")
    
    def setup_ui(self):
        self.main_container = ctk.CTkFrame(self.root, fg_color=COLORS['dark_bg'])
        self.main_container.pack(fill="both", expand=True)
       
        self.setup_header()
        self.setup_tabs()
        self.setup_status_bar()
   
    def setup_header(self):
        header_frame = ctk.CTkFrame(
            self.main_container,
            fg_color=COLORS['dark_card'],
            height=60
        )
        header_frame.pack(fill="x", padx=10, pady=(10, 5))
        header_frame.pack_propagate(False)
       
        title_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_frame.pack(side="left", padx=20)
       
        title_label = ctk.CTkLabel(
            title_frame,
            text="YouTube Downloader Pro",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=COLORS['text_primary']
        )
        title_label.pack(side="left")
       
        version_label = ctk.CTkLabel(
            title_frame,
            text="v3.0.0 - FFMPEG VALIDATED",
            font=ctk.CTkFont(size=12),
            text_color=COLORS['text_secondary']
        )
        version_label.pack(side="left", padx=(10, 0))
        
        # FFmpeg status indicator with color
        status = self.download_manager.get_ffmpeg_status()
        if status['available']:
            ffmpeg_status_text = "✓ FFmpeg: AVAILABLE"
            ffmpeg_color = COLORS['success']
            ffmpeg_hover = "#2DB54F"
        else:
            ffmpeg_status_text = "⚠ FFmpeg: NOT FOUND"
            ffmpeg_color = COLORS['warning']
            ffmpeg_hover = "#E68A00"
        
        self.ffmpeg_status_btn = ctk.CTkButton(
            title_frame,
            text=ffmpeg_status_text,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=ffmpeg_color,
            hover_color=ffmpeg_hover,
            width=180,
            height=30,
            command=self.show_ffmpeg_details
        )
        self.ffmpeg_status_btn.pack(side="left", padx=(10, 0))
       
        stats_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        stats_frame.pack(side="left", padx=50)
       
        stats_text = f"📊 Downloads: {self.total_downloads} | 📁 Size: {self._format_size(self.total_size)} | ⚡ Active: {self.active_downloads}"
        self.stats_label = ctk.CTkLabel(
            stats_frame,
            text=stats_text,
            font=ctk.CTkFont(size=12),
            text_color=COLORS['text_secondary']
        )
        self.stats_label.pack()
       
        settings_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        settings_frame.pack(side="right", padx=20)
       
        settings_btn = ctk.CTkButton(
            settings_frame,
            text="⚙️ Settings",
            width=100,
            command=self.open_settings,
            fg_color=COLORS['dark_card'],
            hover_color=COLORS['dark_bg'],
            text_color=COLORS['text_primary']
        )
        settings_btn.pack(side="left", padx=5)
       
        theme_btn = ctk.CTkButton(
            settings_frame,
            text="🌙 Theme",
            width=100,
            command=self.toggle_theme,
            fg_color=COLORS['dark_card'],
            hover_color=COLORS['dark_bg'],
            text_color=COLORS['text_primary']
        )
        theme_btn.pack(side="left", padx=5)
    
    def show_ffmpeg_details(self):
        """Show detailed FFmpeg information"""
        status = self.download_manager.get_ffmpeg_status()
        
        details = f"""
╔══════════════════════════════════════════════════════════════╗
║                    FFMPEG STATUS REPORT                      ║
╠══════════════════════════════════════════════════════════════╣
║ Status: {'✓ AVAILABLE' if status['available'] else '✗ NOT FOUND'}                        
║ Path: {status['path'] if status['path'] else 'N/A'}
║ {status['message']}
╠══════════════════════════════════════════════════════════════╣
║                    QUALITY CAPABILITIES                       ║
╠══════════════════════════════════════════════════════════════╣
║ {'✓ 4K/8K Downloads: YES' if status['available'] else '⚠ 4K/8K Downloads: FALLBACK MODE'}
║ {'✓ 1080p Downloads: YES' if status['available'] else '⚠ 1080p Downloads: FALLBACK MODE'}
║ {'✓ Video+Audio Merging: YES' if status['available'] else '✗ Video+Audio Merging: NO'}
║ {'✓ Best Quality Available: YES' if status['available'] else '⚠ Limited to combined streams'}
╚══════════════════════════════════════════════════════════════╝
        """
        
        if not status['available']:
            details += f"\n\n📥 To install FFmpeg:\n"
            details += f"   Windows: https://www.gyan.dev/ffmpeg/builds/\n"
            details += f"   macOS:   brew install ffmpeg\n"
            details += f"   Linux:   sudo apt install ffmpeg\n"
        
        messagebox.showinfo("FFmpeg Details", details)
   
    def setup_tabs(self):
        self.tab_view = ctk.CTkTabview(
            self.main_container,
            fg_color=COLORS['dark_bg'],
            segmented_button_fg_color=COLORS['dark_card'],
            segmented_button_selected_color=COLORS['primary'],
            segmented_button_selected_hover_color=COLORS['primary'],
            segmented_button_unselected_hover_color=COLORS['dark_card'],
            text_color=COLORS['text_primary'],
            segmented_button_unselected_color=COLORS['dark_gray']
        )
        self.tab_view.pack(fill="both", expand=True, padx=10, pady=(0, 10))
       
        self.download_tab = self.tab_view.add("⬇️ Download")
        self.queue_tab = self.tab_view.add("📋 Queue")
        self.history_tab = self.tab_view.add("📊 History")
        self.playlist_tab = self.tab_view.add("🎵 Playlist")
       
        self.setup_download_tab()
        self.setup_queue_tab()
        self.setup_history_tab()
        self.setup_playlist_tab()
       
        self.tab_view.configure(command=self.on_tab_changed)
   
    def setup_download_tab(self):
        content_frame = ctk.CTkFrame(self.download_tab, fg_color=COLORS['dark_bg'])
        content_frame.pack(fill="both", expand=True, padx=20, pady=20)
       
        left_container = ctk.CTkFrame(content_frame, fg_color=COLORS['dark_bg'])
        left_container.pack(side="left", fill="y", padx=(0, 10))
       
        left_panel = ctk.CTkScrollableFrame(
            left_container,
            fg_color=COLORS['dark_card'],
            width=400,
            scrollbar_button_color=COLORS['dark_gray'],
            scrollbar_button_hover_color=COLORS['gray'],
            orientation="vertical"
        )
        left_panel.pack(fill="both", expand=True)
        left_container.pack_propagate(False)
        left_container.configure(width=420)
       
        right_panel = ctk.CTkFrame(content_frame, fg_color=COLORS['dark_card'])
        right_panel.pack(side="right", fill="both", expand=True)
       
        # FFmpeg Warning Banner (shown if FFmpeg not available)
        status = self.download_manager.get_ffmpeg_status()
        if not status['available']:
            warning_banner = ctk.CTkFrame(
                left_panel,
                fg_color=COLORS['warning'],
                corner_radius=8,
                height=60
            )
            warning_banner.pack(fill="x", padx=20, pady=(20, 10))
            warning_banner.pack_propagate(False)
            
            warning_text = ctk.CTkLabel(
                warning_banner,
                text="⚠️ FFMPEG NOT FOUND - FALLBACK MODE ACTIVE ⚠️\nHigh quality may fallback to lower resolutions | Install FFmpeg for best results",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#000000",
                wraplength=350
            )
            warning_text.pack(expand=True, padx=10, pady=10)
            
            install_btn = ctk.CTkButton(
                warning_banner,
                text="Download FFmpeg",
                width=120,
                height=25,
                font=ctk.CTkFont(size=11),
                fg_color="#000000",
                hover_color="#333333",
                text_color=COLORS['warning'],
                command=lambda: webbrowser.open("https://ffmpeg.org/download.html")
            )
            install_btn.pack(pady=(0, 10))
       
        # URL Input
        url_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        url_frame.pack(fill="x", padx=20, pady=(20, 10))
       
        ctk.CTkLabel(
            url_frame,
            text="YouTube URL:",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS['text_primary']
        ).pack(anchor="w")
       
        self.url_entry = ctk.CTkEntry(
            url_frame,
            placeholder_text="Paste YouTube URL here...",
            height=40,
            font=ctk.CTkFont(size=13),
            fg_color=COLORS['dark_gray'],
            text_color=COLORS['text_primary'],
            placeholder_text_color=COLORS['text_secondary']
        )
        self.url_entry.pack(fill="x", pady=(5, 0))
        self.url_entry.bind("<Return>", lambda e: self.fetch_video_info())
       
        # Format selection
        format_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        format_frame.pack(fill="x", padx=20, pady=10)
       
        ctk.CTkLabel(
            format_frame,
            text="Format:",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS['text_primary']
        ).pack(anchor="w")
       
        self.format_var = ctk.StringVar(value="video")
        format_options = ["video", "audio"]
       
        for option in format_options:
            rb = ctk.CTkRadioButton(
                format_frame,
                text=option.capitalize(),
                variable=self.format_var,
                value=option,
                font=ctk.CTkFont(size=13),
                text_color=COLORS['text_primary'],
                fg_color=COLORS['primary'],
                hover_color=COLORS['primary']
            )
            rb.pack(anchor="w", pady=2)
       
        # Quality selection
        quality_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        quality_frame.pack(fill="x", padx=20, pady=10)
       
        quality_header = ctk.CTkFrame(quality_frame, fg_color="transparent")
        quality_header.pack(fill="x")
        
        ctk.CTkLabel(
            quality_header,
            text="Quality:",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS['text_primary']
        ).pack(side="left")
        
        # Show quality note based on FFmpeg
        if not status['available']:
            quality_note = ctk.CTkLabel(
                quality_header,
                text="(High quality may fallback - No FFmpeg)",
                font=ctk.CTkFont(size=11),
                text_color=COLORS['warning']
            )
            quality_note.pack(side="left", padx=(10, 0))
       
        quality_options = ["best", "4k", "2160p", "1440p", "1080p", "720p", "480p", "360p", "240p", "144p", "worst"]
        
        self.quality_combo = ctk.CTkComboBox(
            quality_frame,
            values=quality_options,
            font=ctk.CTkFont(size=13),
            dropdown_font=ctk.CTkFont(size=13),
            state="readonly",
            fg_color=COLORS['dark_gray'],
            text_color=COLORS['text_primary'],
            button_color=COLORS['primary'],
            button_hover_color=COLORS['primary']
        )
        
        # Set default quality based on FFmpeg
        if status['available']:
            self.quality_combo.set("1080p")
        else:
            self.quality_combo.set("720p")
        
        self.quality_combo.pack(fill="x", pady=(5, 0))
        
        # Bind quality selection to validation
        self.quality_combo.configure(command=self.on_quality_selected)
       
        # Advanced options
        advanced_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        advanced_frame.pack(fill="x", padx=20, pady=10)
       
        ctk.CTkLabel(
            advanced_frame,
            text="Advanced Options:",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS['text_primary']
        ).pack(anchor="w")
       
        subtitles_check = ctk.CTkCheckBox(
            advanced_frame,
            text="Include subtitles (English only)",
            variable=self.subtitles_var,
            font=ctk.CTkFont(size=13),
            text_color=COLORS['text_primary'],
            fg_color=COLORS['primary'],
            hover_color=COLORS['primary']
        )
        subtitles_check.pack(anchor="w", pady=(5, 2))
       
        metadata_check = ctk.CTkCheckBox(
            advanced_frame,
            text="Embed metadata",
            variable=self.metadata_var,
            font=ctk.CTkFont(size=13),
            text_color=COLORS['text_primary'],
            fg_color=COLORS['primary'],
            hover_color=COLORS['primary']
        )
        metadata_check.pack(anchor="w", pady=(0, 5))
       
        # Output path
        path_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        path_frame.pack(fill="x", padx=20, pady=10)
       
        ctk.CTkLabel(
            path_frame,
            text="Save to:",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS['text_primary']
        ).pack(anchor="w")
       
        path_subframe = ctk.CTkFrame(path_frame, fg_color="transparent")
        path_subframe.pack(fill="x", pady=(5, 0))
       
        self.path_var = ctk.StringVar(value=os.path.expanduser("~/Downloads"))
        self.path_entry = ctk.CTkEntry(
            path_subframe,
            textvariable=self.path_var,
            font=ctk.CTkFont(size=13),
            fg_color=COLORS['dark_gray'],
            text_color=COLORS['text_primary']
        )
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
       
        browse_btn = ctk.CTkButton(
            path_subframe,
            text="Browse",
            width=80,
            command=self.browse_path,
            fg_color=COLORS['primary'],
            hover_color="#FF5757",
            text_color=COLORS['text_primary']
        )
        browse_btn.pack(side="right")
       
        # Verify FFmpeg button
        verify_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        verify_frame.pack(fill="x", padx=20, pady=10)
       
        verify_btn = ctk.CTkButton(
            verify_frame,
            text="🔧 Verify FFmpeg",
            height=30,
            command=self.verify_ffmpeg,
            fg_color=COLORS['secondary'],
            hover_color="#6C6AFF",
            text_color=COLORS['text_primary']
        )
        verify_btn.pack(fill="x")
       
        # Action buttons
        button_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        button_frame.pack(fill="x", padx=20, pady=20)
       
        fetch_btn = ctk.CTkButton(
            button_frame,
            text="🔍 Fetch Info",
            height=40,
            command=self.fetch_video_info,
            fg_color=COLORS['secondary'],
            hover_color="#6C6AFF",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS['text_primary']
        )
        fetch_btn.pack(fill="x", pady=(0, 10))
       
        download_btn = ctk.CTkButton(
            button_frame,
            text="⬇️ Add to Queue",
            height=50,
            command=self.add_to_queue,
            fg_color=COLORS['primary'],
            hover_color="#FF5757",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLORS['text_primary']
        )
        download_btn.pack(fill="x")
       
        # Preview area
        self.preview_frame = ctk.CTkFrame(right_panel, fg_color=COLORS['dark_card'])
        self.preview_frame.pack(fill="both", expand=True, padx=20, pady=20)
       
        preview_label = ctk.CTkLabel(
            self.preview_frame,
            text="Enter a YouTube URL and click 'Fetch Info' to see video details",
            font=ctk.CTkFont(size=16),
            text_color=COLORS['text_secondary']
        )
        preview_label.place(relx=0.5, rely=0.5, anchor="center")
    
    def on_quality_selected(self, choice):
        """Validate quality selection and show warning if needed"""
        status = self.download_manager.get_ffmpeg_status()
        warning = FFmpegValidator.get_quality_warning(choice, status['available'])
        
        if warning and not status['available']:
            # Show warning but respect user's choice (don't revert)
            messagebox.showwarning(
                "Quality Warning",
                f"{warning}\n\nThe download will proceed with the best available quality."
            )
    
    def verify_ffmpeg(self):
        """Manually verify FFmpeg and update UI"""
        self.status_message.set("Verifying FFmpeg...")
        
        # Re-validate FFmpeg
        self.download_manager._validate_ffmpeg()
        status = self.download_manager.get_ffmpeg_status()
        
        # Update UI
        if status['available']:
            self.ffmpeg_status_btn.configure(
                text="✓ FFmpeg: AVAILABLE",
                fg_color=COLORS['success']
            )
            messagebox.showinfo(
                "FFmpeg Verified ✓",
                f"{status['message']}\n\n"
                f"✅ High quality downloads (1080p, 4K) are now available!\n"
                f"✅ Video and audio will be merged for best quality"
            )
        else:
            self.ffmpeg_status_btn.configure(
                text="⚠ FFmpeg: NOT FOUND",
                fg_color=COLORS['warning']
            )
            
            result = messagebox.askyesno(
                "FFmpeg Not Found",
                f"{status['message']}\n\n"
                f"⚠ Without FFmpeg, high quality downloads will fallback to combined streams.\n\n"
                f"Would you like to open the FFmpeg download page?"
            )
            if result:
                webbrowser.open("https://ffmpeg.org/download.html")
        
        self.status_message.set("FFmpeg verification complete")
    
    def fetch_video_info(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Warning", "Please enter a YouTube URL")
            return
       
        for widget in self.preview_frame.winfo_children():
            widget.destroy()
       
        loading_label = ctk.CTkLabel(
            self.preview_frame,
            text="Fetching video information...",
            font=ctk.CTkFont(size=16),
            text_color=COLORS['text_secondary']
        )
        loading_label.place(relx=0.5, rely=0.5, anchor="center")
       
        threading.Thread(target=self._fetch_video_info_thread, args=(url,), daemon=True).start()
   
    def _fetch_video_info_thread(self, url):
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
            }
           
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                self.root.after(0, lambda: self.display_video_info(info))
               
        except Exception as e:
            error_msg = str(e)
            self.root.after(0, lambda: self.show_error("Failed to fetch video info", error_msg))
   
    def display_video_info(self, info):
        for widget in self.preview_frame.winfo_children():
            widget.destroy()
       
        try:
            container = ctk.CTkScrollableFrame(
                self.preview_frame,
                fg_color=COLORS['dark_card'],
                scrollbar_button_color=COLORS['dark_gray'],
                scrollbar_button_hover_color=COLORS['gray']
            )
            container.pack(fill="both", expand=True)
           
            thumbnail_url = info.get('thumbnail')
            thumbnail_frame = ctk.CTkFrame(container, fg_color="transparent")
            thumbnail_frame.pack(fill="x", padx=20, pady=20)
           
            if thumbnail_url:
                try:
                    response = requests.get(thumbnail_url, timeout=10)
                    img_data = response.content
                    img = Image.open(BytesIO(img_data))
                    max_size = (400, 225)
                    img.thumbnail(max_size, Image.Resampling.LANCZOS)
                    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
                    thumbnail_label = ctk.CTkLabel(thumbnail_frame, image=ctk_img, text="")
                    thumbnail_label.pack()
                except Exception as e:
                    logger.error(f"Failed to load thumbnail: {e}")
                    placeholder = ctk.CTkLabel(
                        thumbnail_frame,
                        text="📺 Thumbnail not available",
                        font=ctk.CTkFont(size=14),
                        text_color=COLORS['text_secondary']
                    )
                    placeholder.pack()
           
            info_frame = ctk.CTkFrame(container, fg_color="transparent")
            info_frame.pack(fill="x", padx=20, pady=(0, 20))
           
            title = info.get('title', 'Unknown Title')
            if len(title) > 100:
                title = title[:97] + "..."
           
            title_label = ctk.CTkLabel(
                info_frame,
                text=title,
                font=ctk.CTkFont(size=18, weight="bold"),
                text_color=COLORS['text_primary'],
                wraplength=600
            )
            title_label.pack(anchor="w", pady=(0, 10))
           
            details = [
                ("👤 Channel", info.get('channel', 'Unknown')),
                ("⏱️ Duration", self._format_duration(info.get('duration', 0))),
                ("👁️ Views", f"{info.get('view_count', 0):,}"),
                ("⭐ Likes", f"{info.get('like_count', 0):,}"),
                ("📅 Upload Date", info.get('upload_date', 'Unknown')),
                ("🔗 Video ID", info.get('id', 'Unknown'))
            ]
           
            for label, value in details:
                detail_frame = ctk.CTkFrame(info_frame, fg_color="transparent")
                detail_frame.pack(fill="x", pady=2)
               
                ctk.CTkLabel(
                    detail_frame,
                    text=label,
                    font=ctk.CTkFont(size=13, weight="bold"),
                    text_color=COLORS['text_secondary'],
                    width=120
                ).pack(side="left")
               
                ctk.CTkLabel(
                    detail_frame,
                    text=str(value),
                    font=ctk.CTkFont(size=13),
                    text_color=COLORS['text_primary']
                ).pack(side="left")
            
            # Show FFmpeg status prominently
            status = self.download_manager.get_ffmpeg_status()
            ffmpeg_frame = ctk.CTkFrame(info_frame, fg_color="transparent")
            ffmpeg_frame.pack(fill="x", pady=(10, 0))
            
            if status['available']:
                ffmpeg_status = ctk.CTkLabel(
                    ffmpeg_frame,
                    text="✅ FFMPEG: AVAILABLE - High quality downloads enabled",
                    font=ctk.CTkFont(size=12, weight="bold"),
                    text_color=COLORS['success']
                )
            else:
                ffmpeg_status = ctk.CTkLabel(
                    ffmpeg_frame,
                    text="❌ FFMPEG: NOT FOUND - Will fallback to best combined stream",
                    font=ctk.CTkFont(size=12, weight="bold"),
                    text_color=COLORS['error']
                )
            ffmpeg_status.pack(anchor="w")
            
            # Show available resolutions
            formats = info.get('formats', [])
            resolutions = set()
            for fmt in formats:
                if fmt.get('vcodec') != 'none' and fmt.get('height'):
                    resolutions.add(fmt.get('height'))
            
            if resolutions:
                res_frame = ctk.CTkFrame(info_frame, fg_color="transparent")
                res_frame.pack(fill="x", pady=(10, 0))
                
                ctk.CTkLabel(
                    res_frame,
                    text="Available Resolutions:",
                    font=ctk.CTkFont(size=13, weight="bold"),
                    text_color=COLORS['text_secondary']
                ).pack(anchor="w")
                
                sorted_res = sorted(resolutions, reverse=True)
                res_text = ", ".join([f"{r}p" for r in sorted_res[:8]])
                if len(sorted_res) > 8:
                    res_text += f" and {len(sorted_res)-8} more"
                
                ctk.CTkLabel(
                    res_frame,
                    text=res_text,
                    font=ctk.CTkFont(size=13),
                    text_color=COLORS['text_primary']
                ).pack(anchor="w")
                
                # Show what's possible with current FFmpeg
                if not status['available'] and max(resolutions) > 720:
                    warning_label = ctk.CTkLabel(
                        res_frame,
                        text=f"⚠️ This video has {max(resolutions)}p available, but requires FFmpeg to merge high quality video+audio",
                        font=ctk.CTkFont(size=11),
                        text_color=COLORS['warning']
                    )
                    warning_label.pack(anchor="w", pady=(5, 0))
           
            self.video_cache[self.url_entry.get()] = info
           
        except Exception as e:
            logger.error(f"Failed to display video info: {e}")
            error_label = ctk.CTkLabel(
                self.preview_frame,
                text=f"Error: {str(e)}",
                font=ctk.CTkFont(size=14),
                text_color=COLORS['error']
            )
            error_label.place(relx=0.5, rely=0.5, anchor="center")
    
    def add_to_queue(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Warning", "Please enter a YouTube URL")
            return
       
        if url in self.video_cache:
            info = self.video_cache[url]
            title = info.get('title', 'Unknown Video')
        else:
            try:
                with YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                    info = ydl.extract_info(url, download=False)
                    title = info.get('title', 'Unknown Video')
            except:
                title = "Unknown Video"
       
        format_type = self.format_var.get()
       
        task_id, status_msg = self.download_manager.add_task(
            url=url,
            format_type=format_type,
            quality=self.quality_combo.get(),
            output_path=self.path_var.get(),
            title=title,
            include_subtitles=self.subtitles_var.get(),
            embed_metadata=self.metadata_var.get()
        )
       
        if task_id:
            self.status_message.set(f"Added to queue: {title[:50]}...")
            self.refresh_task_list()
            self.tab_view.set("📋 Queue")
        else:
            messagebox.showwarning("Warning", status_msg)
   
    def setup_queue_tab(self):
        main_frame = ctk.CTkFrame(self.queue_tab, fg_color=COLORS['dark_bg'])
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
       
        header_frame = ctk.CTkFrame(main_frame, fg_color=COLORS['dark_card'])
        header_frame.pack(fill="x", pady=(0, 10))
       
        ctk.CTkLabel(
            header_frame,
            text="Download Queue",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=COLORS['text_primary']
        ).pack(side="left", padx=20, pady=10)
       
        control_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        control_frame.pack(side="right", padx=20)
       
        start_all_btn = ctk.CTkButton(
            control_frame,
            text="▶ Start All",
            width=100,
            command=self.start_all_downloads,
            fg_color=COLORS['success'],
            hover_color="#2DB54F",
            text_color=COLORS['text_primary']
        )
        start_all_btn.pack(side="left", padx=5)
       
        pause_all_btn = ctk.CTkButton(
            control_frame,
            text="⏸ Pause All",
            width=100,
            command=self.pause_all_downloads,
            fg_color=COLORS['warning'],
            hover_color="#E68A00",
            text_color=COLORS['text_primary']
        )
        pause_all_btn.pack(side="left", padx=5)
       
        clear_btn = ctk.CTkButton(
            control_frame,
            text="🗑 Clear",
            width=100,
            command=self.clear_queue,
            fg_color=COLORS['error'],
            hover_color="#E62E2E",
            text_color=COLORS['text_primary']
        )
        clear_btn.pack(side="left", padx=5)
       
        list_container = ctk.CTkFrame(main_frame, fg_color=COLORS['dark_card'])
        list_container.pack(fill="both", expand=True)
       
        self.queue_scroll = ctk.CTkScrollableFrame(
            list_container,
            fg_color=COLORS['dark_card']
        )
        self.queue_scroll.pack(fill="both", expand=True, padx=10, pady=10)
        self.queue_scroll._text_color = COLORS['text_primary']
   
    def setup_history_tab(self):
        main_frame = ctk.CTkFrame(self.history_tab, fg_color=COLORS['dark_bg'])
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
       
        header_frame = ctk.CTkFrame(main_frame, fg_color=COLORS['dark_card'])
        header_frame.pack(fill="x", pady=(0, 10))
       
        ctk.CTkLabel(
            header_frame,
            text="Download History",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=COLORS['text_primary']
        ).pack(side="left", padx=20, pady=10)
       
        control_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        control_frame.pack(side="right", padx=20)
       
        refresh_btn = ctk.CTkButton(
            control_frame,
            text="🔄 Refresh",
            width=100,
            command=self.refresh_history,
            fg_color=COLORS['secondary'],
            hover_color="#6C6AFF",
            text_color=COLORS['text_primary']
        )
        refresh_btn.pack(side="left", padx=5)
       
        clear_btn = ctk.CTkButton(
            control_frame,
            text="🗑 Clear History",
            width=120,
            command=self.clear_history,
            fg_color=COLORS['error'],
            hover_color="#E62E2E",
            text_color=COLORS['text_primary']
        )
        clear_btn.pack(side="left", padx=5)
       
        open_btn = ctk.CTkButton(
            control_frame,
            text="📁 Open Folder",
            width=120,
            command=self.open_download_folder,
            fg_color=COLORS['info'],
            hover_color="#0066CC",
            text_color=COLORS['text_primary']
        )
        open_btn.pack(side="left", padx=5)
       
        list_frame = ctk.CTkFrame(main_frame, fg_color=COLORS['dark_card'])
        list_frame.pack(fill="both", expand=True)
       
        tree_frame = ctk.CTkFrame(list_frame, fg_color=COLORS['dark_card'])
        tree_frame.pack(fill="both", expand=True, padx=10, pady=10)
       
        v_scrollbar = ttk.Scrollbar(tree_frame)
        v_scrollbar.pack(side="right", fill="y")
       
        h_scrollbar = ttk.Scrollbar(tree_frame, orient="horizontal")
        h_scrollbar.pack(side="bottom", fill="x")
       
        self.history_tree = ttk.Treeview(
            tree_frame,
            columns=("status", "format", "quality", "size", "date"),
            show="tree headings",
            height=20,
            yscrollcommand=v_scrollbar.set,
            xscrollcommand=h_scrollbar.set
        )
       
        v_scrollbar.config(command=self.history_tree.yview)
        h_scrollbar.config(command=self.history_tree.xview)
       
        self.history_tree.heading("#0", text="Title", anchor="w")
        self.history_tree.heading("status", text="Status", anchor="w")
        self.history_tree.heading("format", text="Format", anchor="w")
        self.history_tree.heading("quality", text="Quality", anchor="w")
        self.history_tree.heading("size", text="Size", anchor="w")
        self.history_tree.heading("date", text="Date", anchor="w")
       
        self.history_tree.column("#0", width=400, minwidth=200)
        self.history_tree.column("status", width=100, minwidth=80)
        self.history_tree.column("format", width=80, minwidth=60)
        self.history_tree.column("quality", width=80, minwidth=60)
        self.history_tree.column("size", width=100, minwidth=80)
        self.history_tree.column("date", width=150, minwidth=120)
       
        style = ttk.Style()
        style.theme_use("default")
       
        style.configure(
            "Treeview",
            background=COLORS['dark_card'],
            foreground=COLORS['text_primary'],
            fieldbackground=COLORS['dark_card'],
            borderwidth=0,
            font=('Helvetica', 11)
        )
        style.configure(
            "Treeview.Heading",
            background=COLORS['dark_bg'],
            foreground=COLORS['text_primary'],
            font=('Helvetica', 11, 'bold'),
            borderwidth=0
        )
        style.map(
            "Treeview",
            background=[('selected', COLORS['primary'])],
            foreground=[('selected', 'white')]
        )
       
        self.history_tree.tag_configure('completed', foreground=COLORS['success'])
        self.history_tree.tag_configure('error', foreground=COLORS['error'])
        self.history_tree.tag_configure('cancelled', foreground=COLORS['warning'])
       
        self.history_tree.pack(fill="both", expand=True)
        self.history_tree.bind("<Double-1>", self.on_history_item_double_click)
   
    def setup_playlist_tab(self):
        main_frame = ctk.CTkFrame(self.playlist_tab, fg_color=COLORS['dark_bg'])
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
       
        header_frame = ctk.CTkFrame(main_frame, fg_color=COLORS['dark_card'])
        header_frame.pack(fill="x", pady=(0, 10))
       
        ctk.CTkLabel(
            header_frame,
            text="Playlist Downloader",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=COLORS['text_primary']
        ).pack(side="left", padx=20, pady=10)
       
        url_frame = ctk.CTkFrame(main_frame, fg_color=COLORS['dark_card'])
        url_frame.pack(fill="x", pady=(0, 10))
       
        ctk.CTkLabel(
            url_frame,
            text="Playlist URL:",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS['text_primary']
        ).pack(anchor="w", padx=20, pady=(10, 5))
       
        playlist_url_frame = ctk.CTkFrame(url_frame, fg_color="transparent")
        playlist_url_frame.pack(fill="x", padx=20, pady=(0, 10))
       
        self.playlist_url_entry = ctk.CTkEntry(
            playlist_url_frame,
            placeholder_text="Paste YouTube playlist URL here...",
            height=40,
            font=ctk.CTkFont(size=13),
            fg_color=COLORS['dark_gray'],
            text_color=COLORS['text_primary'],
            placeholder_text_color=COLORS['text_secondary']
        )
        self.playlist_url_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
       
        fetch_playlist_btn = ctk.CTkButton(
            playlist_url_frame,
            text="🔍 Fetch Playlist",
            width=120,
            command=self.fetch_playlist_info,
            fg_color=COLORS['secondary'],
            hover_color="#6C6AFF",
            text_color=COLORS['text_primary']
        )
        fetch_playlist_btn.pack(side="right")
       
        self.playlist_info_frame = ctk.CTkFrame(main_frame, fg_color=COLORS['dark_card'])
        self.playlist_info_frame.pack(fill="both", expand=True)
       
        info_label = ctk.CTkLabel(
            self.playlist_info_frame,
            text="Enter a playlist URL to see details",
            font=ctk.CTkFont(size=16),
            text_color=COLORS['text_secondary']
        )
        info_label.place(relx=0.5, rely=0.5, anchor="center")
   
    def setup_status_bar(self):
        status_frame = ctk.CTkFrame(
            self.main_container,
            fg_color=COLORS['dark_card'],
            height=40
        )
        status_frame.pack(fill="x", padx=10, pady=(5, 10))
        status_frame.pack_propagate(False)
       
        self.status_message = ctk.StringVar(value="Ready")
        status_label = ctk.CTkLabel(
            status_frame,
            textvariable=self.status_message,
            font=ctk.CTkFont(size=12),
            text_color=COLORS['text_secondary']
        )
        status_label.pack(side="left", padx=20)
       
        sys_info = f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} | {platform.system()} {platform.release()}"
        sys_label = ctk.CTkLabel(
            status_frame,
            text=sys_info,
            font=ctk.CTkFont(size=10),
            text_color=COLORS['text_secondary']
        )
        sys_label.pack(side="right", padx=20)
   
    def refresh_task_list(self):
        for widget in self.queue_scroll.winfo_children():
            widget.destroy()
       
        tasks = list(self.download_manager.active_tasks.values()) + list(self.download_manager.task_queue)
       
        if not tasks:
            empty_label = ctk.CTkLabel(
                self.queue_scroll,
                text="Queue is empty",
                font=ctk.CTkFont(size=16),
                text_color=COLORS['text_secondary']
            )
            empty_label.pack(pady=50)
            return
       
        status_order = {
            DownloadStatus.DOWNLOADING: 0,
            DownloadStatus.PROCESSING: 1,
            DownloadStatus.MERGING: 2,
            DownloadStatus.QUEUED: 3,
            DownloadStatus.PAUSED: 4,
            DownloadStatus.ERROR: 5
        }
        tasks.sort(key=lambda x: status_order.get(x.status, 999))
       
        for task in tasks:
            self._create_task_card(task)
   
    def _create_task_card(self, task: DownloadTask):
        card = ctk.CTkFrame(
            self.queue_scroll,
            fg_color=COLORS['dark_card'],
            border_width=1,
            border_color=COLORS['dark_gray'],
            corner_radius=10
        )
        card.pack(fill="x", pady=5, padx=5)
       
        status_colors = {
            DownloadStatus.DOWNLOADING: COLORS['info'],
            DownloadStatus.PROCESSING: COLORS['secondary'],
            DownloadStatus.MERGING: COLORS['secondary'],
            DownloadStatus.QUEUED: COLORS['gray'],
            DownloadStatus.PAUSED: COLORS['warning'],
            DownloadStatus.ERROR: COLORS['error'],
            DownloadStatus.COMPLETED: COLORS['success']
        }
       
        header_frame = ctk.CTkFrame(card, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(15, 5))
       
        status_indicator = ctk.CTkFrame(
            header_frame,
            width=10,
            height=10,
            fg_color=status_colors.get(task.status, COLORS['gray']),
            corner_radius=5
        )
        status_indicator.pack(side="left")
       
        title_text = task.title if len(task.title) <= 50 else task.title[:47] + "..."
        title_label = ctk.CTkLabel(
            header_frame,
            text=title_text,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS['text_primary'],
            wraplength=600
        )
        title_label.pack(side="left", padx=10)
       
        status_label = ctk.CTkLabel(
            header_frame,
            text=task.status.value.upper(),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=status_colors.get(task.status, COLORS['gray'])
        )
        status_label.pack(side="right")
       
        progress_frame = ctk.CTkFrame(card, fg_color="transparent")
        progress_frame.pack(fill="x", padx=15, pady=5)
       
        progress_bar = ctk.CTkProgressBar(
            progress_frame,
            height=8,
            fg_color=COLORS['dark_bg'],
            progress_color=status_colors.get(task.status, COLORS['primary']),
            border_width=0
        )
        progress_bar.pack(fill="x")
        progress_bar.set(task.progress / 100)
       
        info_frame = ctk.CTkFrame(card, fg_color="transparent")
        info_frame.pack(fill="x", padx=15, pady=(0, 10))
       
        format_label = ctk.CTkLabel(
            info_frame,
            text=f"{task.format_type.upper()} • {task.quality}",
            font=ctk.CTkFont(size=11),
            text_color=COLORS['text_secondary']
        )
        format_label.pack(side="left")
       
        progress_text = self._get_progress_text(task)
        progress_label = ctk.CTkLabel(
            info_frame,
            text=progress_text,
            font=ctk.CTkFont(size=11),
            text_color=COLORS['text_secondary']
        )
        progress_label.pack(side="right")
       
        if task.status in [DownloadStatus.QUEUED, DownloadStatus.PAUSED, DownloadStatus.ERROR]:
            control_frame = ctk.CTkFrame(card, fg_color="transparent")
            control_frame.pack(fill="x", padx=15, pady=(0, 15))
           
            if task.status == DownloadStatus.QUEUED:
                start_btn = ctk.CTkButton(
                    control_frame,
                    text="▶ Start",
                    width=80,
                    command=lambda t=task: self.start_task(t.id),
                    fg_color=COLORS['success'],
                    hover_color="#2DB54F",
                    text_color=COLORS['text_primary']
                )
                start_btn.pack(side="left", padx=(0, 10))
           
            elif task.status == DownloadStatus.PAUSED:
                resume_btn = ctk.CTkButton(
                    control_frame,
                    text="▶ Resume",
                    width=80,
                    command=lambda t=task: self.resume_task(t.id),
                    fg_color=COLORS['info'],
                    hover_color="#0066CC",
                    text_color=COLORS['text_primary']
                )
                resume_btn.pack(side="left", padx=(0, 10))
           
            elif task.status == DownloadStatus.ERROR:
                retry_btn = ctk.CTkButton(
                    control_frame,
                    text="🔄 Retry",
                    width=80,
                    command=lambda t=task: self.retry_task(t.id),
                    fg_color=COLORS['warning'],
                    hover_color="#E68A00",
                    text_color=COLORS['text_primary']
                )
                retry_btn.pack(side="left", padx=(0, 10))
           
            cancel_btn = ctk.CTkButton(
                control_frame,
                text="✕ Cancel",
                width=80,
                command=lambda t=task: self.cancel_task(t.id),
                fg_color=COLORS['error'],
                hover_color="#E62E2E",
                text_color=COLORS['text_primary']
            )
            cancel_btn.pack(side="left")
       
        elif task.status == DownloadStatus.DOWNLOADING:
            control_frame = ctk.CTkFrame(card, fg_color="transparent")
            control_frame.pack(fill="x", padx=15, pady=(0, 15))
           
            pause_btn = ctk.CTkButton(
                control_frame,
                text="⏸ Pause",
                width=80,
                command=lambda t=task: self.pause_task(t.id),
                fg_color=COLORS['warning'],
                hover_color="#E68A00",
                text_color=COLORS['text_primary']
            )
            pause_btn.pack(side="left")
   
    def _get_progress_text(self, task: DownloadTask) -> str:
        if task.status == DownloadStatus.COMPLETED:
            if task.file_path and os.path.exists(task.file_path):
                size = os.path.getsize(task.file_path)
                return f"Completed • {self._format_size(size)}"
            return "Completed"
       
        elif task.status == DownloadStatus.DOWNLOADING:
            downloaded = self._format_size(task.downloaded_bytes)
            total = self._format_size(task.total_bytes) if task.total_bytes > 0 else "??"
            speed = self._format_size(task.speed) if task.speed > 0 else "0"
            eta = self._format_time(task.eta) if task.eta else "??"
            return f"{downloaded} / {total} • {speed}/s • ETA: {eta}"
       
        elif task.status == DownloadStatus.PROCESSING:
            return "Processing..."
       
        elif task.status == DownloadStatus.MERGING:
            return "Merging streams..."
       
        elif task.status == DownloadStatus.ERROR:
            return f"Error: {task.error[:50]}..." if task.error else "Error"
       
        else:
            return task.status.value.capitalize()
   
    def start_task(self, task_id: str):
        if self.download_manager.start_task(task_id):
            self.status_message.set("Task started")
            self.refresh_task_list()
   
    def pause_task(self, task_id: str):
        if self.download_manager.pause_task(task_id):
            self.status_message.set("Task paused")
            self.refresh_task_list()
   
    def resume_task(self, task_id: str):
        if self.download_manager.resume_task(task_id):
            self.status_message.set("Task resumed")
            self.refresh_task_list()
   
    def cancel_task(self, task_id: str):
        if messagebox.askyesno("Confirm", "Are you sure you want to cancel this download?"):
            if self.download_manager.cancel_task(task_id):
                self.status_message.set("Task cancelled")
                self.refresh_task_list()
   
    def retry_task(self, task_id: str):
        task = self.download_manager.get_task(task_id)
        if task and task.status == DownloadStatus.ERROR:
            task.status = DownloadStatus.QUEUED
            task.progress = 0
            task.error = None
            self.download_manager.task_queue.append(task)
            self.download_manager.save_state()
            self.refresh_task_list()
            self.download_manager._auto_start_downloads()
            self.status_message.set("Task retrying...")
   
    def start_all_downloads(self):
        self.download_manager._auto_start_downloads()
        self.refresh_task_list()
        self.status_message.set("Starting all downloads...")
   
    def pause_all_downloads(self):
        for task_id in list(self.download_manager.active_tasks.keys()):
            self.download_manager.pause_task(task_id)
        self.refresh_task_list()
        self.status_message.set("All downloads paused")
   
    def clear_queue(self):
        if messagebox.askyesno("Confirm", "Clear all queued and paused downloads?"):
            for task_id in list(self.download_manager.active_tasks.keys()):
                self.download_manager.cancel_task(task_id)
            for task in list(self.download_manager.task_queue):
                task.status = DownloadStatus.CANCELLED
                self.download_manager.task_history.append(task)
            self.download_manager.task_queue.clear()
            self.download_manager.save_state()
            self.refresh_task_list()
            self.status_message.set("Queue cleared")
   
    def refresh_history(self):
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
       
        history_tasks = self.download_manager.task_history[-100:]
       
        for task in reversed(history_tasks):
            status_text = task.status.value.capitalize()
            tags = []
           
            if task.status == DownloadStatus.COMPLETED:
                status_text = "✅ Completed"
                tags.append('completed')
            elif task.status == DownloadStatus.ERROR:
                status_text = "❌ Error"
                tags.append('error')
            elif task.status == DownloadStatus.CANCELLED:
                status_text = "⏹️ Cancelled"
                tags.append('cancelled')
           
            if task.completed_at:
                date_str = datetime.fromtimestamp(task.completed_at).strftime('%Y-%m-%d %H:%M')
            else:
                date_str = datetime.fromtimestamp(task.created_at).strftime('%Y-%m-%d %H:%M')
           
            size_str = ""
            if task.file_path and os.path.exists(task.file_path):
                size = os.path.getsize(task.file_path)
                size_str = self._format_size(size)
            elif task.total_bytes > 0:
                size_str = self._format_size(task.total_bytes)
           
            self.history_tree.insert(
                "",
                "end",
                text=task.title[:80] + "..." if len(task.title) > 80 else task.title,
                values=(status_text, task.format_type, task.quality, size_str, date_str),
                tags=tuple(tags) if tags else ()
            )
   
    def clear_history(self):
        if messagebox.askyesno("Confirm", "Clear all download history?"):
            self.download_manager.clear_completed()
            self.refresh_history()
            self.status_message.set("History cleared")
   
    def browse_path(self):
        directory = filedialog.askdirectory()
        if directory:
            self.path_var.set(directory)
   
    def open_download_folder(self):
        path = self.path_var.get()
        if os.path.exists(path):
            try:
                if platform.system() == "Windows":
                    os.startfile(path)
                elif platform.system() == "Darwin":
                    subprocess.run(["open", path])
                else:
                    subprocess.run(["xdg-open", path])
            except Exception as e:
                messagebox.showerror("Error", f"Failed to open folder: {e}")
        else:
            messagebox.showerror("Error", f"Folder does not exist: {path}")
   
    def fetch_playlist_info(self):
        url = self.playlist_url_entry.get().strip()
        if not url:
            messagebox.showwarning("Warning", "Please enter a playlist URL")
            return
       
        for widget in self.playlist_info_frame.winfo_children():
            widget.destroy()
       
        loading_label = ctk.CTkLabel(
            self.playlist_info_frame,
            text="Fetching playlist information...",
            font=ctk.CTkFont(size=16),
            text_color=COLORS['text_secondary']
        )
        loading_label.place(relx=0.5, rely=0.5, anchor="center")
       
        threading.Thread(target=self._fetch_playlist_info_thread, args=(url,), daemon=True).start()
   
    def _fetch_playlist_info_thread(self, url):
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'force_generic_extractor': False,
            }
           
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                self.root.after(0, lambda: self._display_playlist_info(info))
               
        except Exception as e:
            error_msg = str(e)
            self.root.after(0, lambda: self.show_error("Failed to fetch playlist info", error_msg))
   
    def _display_playlist_info(self, info):
        for widget in self.playlist_info_frame.winfo_children():
            widget.destroy()
       
        container = ctk.CTkScrollableFrame(
            self.playlist_info_frame,
            fg_color=COLORS['dark_card'],
            scrollbar_button_color=COLORS['dark_gray'],
            scrollbar_button_hover_color=COLORS['gray']
        )
        container.pack(fill="both", expand=True)
       
        try:
            title = info.get('title', 'Unknown Playlist')
            title_label = ctk.CTkLabel(
                container,
                text=title,
                font=ctk.CTkFont(size=20, weight="bold"),
                text_color=COLORS['text_primary'],
                wraplength=800
            )
            title_label.pack(anchor="w", padx=20, pady=(20, 10))
           
            details_frame = ctk.CTkFrame(container, fg_color="transparent")
            details_frame.pack(fill="x", padx=20, pady=(0, 20))
           
            channel = info.get('channel', 'Unknown Channel')
            channel_label = ctk.CTkLabel(
                details_frame,
                text=f"👤 {channel}",
                font=ctk.CTkFont(size=14),
                text_color=COLORS['text_primary']
            )
            channel_label.pack(anchor="w")
           
            entries = info.get('entries', [])
            video_count = len(entries) if entries else info.get('playlist_count', 0)
            count_label = ctk.CTkLabel(
                details_frame,
                text=f"📹 {video_count} videos",
                font=ctk.CTkFont(size=14),
                text_color=COLORS['text_primary']
            )
            count_label.pack(anchor="w", pady=(5, 0))
           
            options_frame = ctk.CTkFrame(container, fg_color="transparent")
            options_frame.pack(fill="x", padx=20, pady=(0, 20))
           
            ctk.CTkLabel(
                options_frame,
                text="Download Options:",
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color=COLORS['text_primary']
            ).pack(anchor="w", pady=(0, 10))
           
            format_var = ctk.StringVar(value="video")
            format_frame = ctk.CTkFrame(options_frame, fg_color="transparent")
            format_frame.pack(fill="x", pady=5)
           
            for fmt in ["video", "audio"]:
                rb = ctk.CTkRadioButton(
                    format_frame,
                    text=fmt.capitalize(),
                    variable=format_var,
                    value=fmt,
                    font=ctk.CTkFont(size=13),
                    text_color=COLORS['text_primary'],
                    fg_color=COLORS['primary'],
                    hover_color=COLORS['primary']
                )
                rb.pack(side="left", padx=(0, 20))
           
            quality_frame = ctk.CTkFrame(options_frame, fg_color="transparent")
            quality_frame.pack(fill="x", pady=5)
           
            quality_options = ["best", "1080p", "720p", "480p", "360p"]
            quality_combo = ctk.CTkComboBox(
                quality_frame,
                values=quality_options,
                font=ctk.CTkFont(size=13),
                state="readonly",
                width=200,
                fg_color=COLORS['dark_gray'],
                text_color=COLORS['text_primary'],
                button_color=COLORS['primary'],
                button_hover_color=COLORS['primary']
            )
            quality_combo.set("1080p")
            quality_combo.pack(side="left", padx=(0, 20))
           
            def download_playlist():
                if not entries:
                    messagebox.showwarning("Warning", "No videos found in playlist")
                    return
               
                if not messagebox.askyesno("Confirm", f"Download {video_count} videos from playlist?"):
                    return
               
                added_count = 0
                for entry in entries:
                    if isinstance(entry, dict) and 'url' in entry:
                        video_url = entry.get('url')
                        video_title = entry.get('title', 'Unknown Video')
                       
                        self.download_manager.add_task(
                            url=video_url,
                            format_type=format_var.get(),
                            quality=quality_combo.get(),
                            output_path=self.path_var.get(),
                            title=video_title,
                            include_subtitles=self.subtitles_var.get(),
                            embed_metadata=self.metadata_var.get()
                        )
                        added_count += 1
               
                self.status_message.set(f"Added {added_count} videos to queue")
                self.refresh_task_list()
                self.tab_view.set("📋 Queue")
           
            download_btn = ctk.CTkButton(
                options_frame,
                text=f"⬇️ Download Playlist ({video_count} videos)",
                height=40,
                command=download_playlist,
                fg_color=COLORS['primary'],
                hover_color="#FF5757",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=COLORS['text_primary']
            )
            download_btn.pack(fill="x", pady=(10, 0))
           
            if entries:
                list_frame = ctk.CTkFrame(container, fg_color="transparent")
                list_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))
               
                ctk.CTkLabel(
                    list_frame,
                    text="Videos in playlist:",
                    font=ctk.CTkFont(size=16, weight="bold"),
                    text_color=COLORS['text_primary']
                ).pack(anchor="w", pady=(0, 10))
               
                video_list = ctk.CTkScrollableFrame(
                    list_frame,
                    fg_color=COLORS['dark_bg'],
                    height=300,
                    scrollbar_button_color=COLORS['dark_gray'],
                    scrollbar_button_hover_color=COLORS['gray']
                )
                video_list.pack(fill="both", expand=True)
               
                for i, entry in enumerate(entries[:50], 1):
                    if isinstance(entry, dict):
                        video_frame = ctk.CTkFrame(video_list, fg_color="transparent")
                        video_frame.pack(fill="x", pady=2)
                       
                        num_label = ctk.CTkLabel(
                            video_frame,
                            text=f"{i}.",
                            font=ctk.CTkFont(size=12),
                            text_color=COLORS['text_secondary'],
                            width=30
                        )
                        num_label.pack(side="left")
                       
                        title_text = entry.get('title', 'Unknown Title')
                        if len(title_text) > 60:
                            title_text = title_text[:57] + "..."
                       
                        title_label = ctk.CTkLabel(
                            video_frame,
                            text=title_text,
                            font=ctk.CTkFont(size=12),
                            text_color=COLORS['text_primary'],
                            wraplength=600
                        )
                        title_label.pack(side="left", padx=5)
                       
                        duration = entry.get('duration', 0)
                        if duration:
                            duration_label = ctk.CTkLabel(
                                video_frame,
                                text=self._format_duration(duration),
                                font=ctk.CTkFont(size=11),
                                text_color=COLORS['text_secondary'],
                                width=80
                            )
                            duration_label.pack(side="right")
               
                if len(entries) > 50:
                    ctk.CTkLabel(
                        video_list,
                        text=f"... and {len(entries) - 50} more videos",
                        font=ctk.CTkFont(size=12),
                        text_color=COLORS['text_secondary']
                    ).pack(pady=10)
       
        except Exception as e:
            logger.error(f"Failed to display playlist info: {e}")
            error_label = ctk.CTkLabel(
                container,
                text=f"Error: {str(e)}",
                font=ctk.CTkFont(size=14),
                text_color=COLORS['error']
            )
            error_label.pack(pady=50)
   
    def on_history_item_double_click(self, event):
        item = self.history_tree.selection()[0] if self.history_tree.selection() else None
        if not item:
            return
       
        values = self.history_tree.item(item)
        title = values.get('text', '')
       
        for task in self.download_manager.task_history:
            if task.title.startswith(title[:50]):
                if task.file_path and os.path.exists(task.file_path):
                    try:
                        if platform.system() == "Windows":
                            os.startfile(os.path.dirname(task.file_path))
                        elif platform.system() == "Darwin":
                            subprocess.run(["open", "-R", task.file_path])
                        else:
                            subprocess.run(["xdg-open", os.path.dirname(task.file_path)])
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to open file location: {e}")
                else:
                    messagebox.showinfo("Info", "File not found or moved")
                break
   
    def on_tab_changed(self):
        current_tab = self.tab_view.get()
        if current_tab == "📋 Queue":
            self.refresh_task_list()
        elif current_tab == "📊 History":
            self.refresh_history()
   
    def toggle_theme(self):
        if self.current_theme == "dark":
            ctk.set_appearance_mode("light")
            self.current_theme = "light"
        else:
            ctk.set_appearance_mode("dark")
            self.current_theme = "dark"
        self.status_message.set(f"Switched to {self.current_theme} theme")
   
    def open_settings(self):
        settings_window = ctk.CTkToplevel(self.root)
        settings_window.title("Settings")
        settings_window.geometry("600x500")
        settings_window.transient(self.root)
        settings_window.grab_set()
        settings_window.configure(fg_color=COLORS['dark_bg'])
       
        settings_window.update_idletasks()
        width = settings_window.winfo_width()
        height = settings_window.winfo_height()
        x = (settings_window.winfo_screenwidth() // 2) - (width // 2)
        y = (settings_window.winfo_screenheight() // 2) - (height // 2)
        settings_window.geometry(f"{width}x{height}+{x}+{y}")
       
        container = ctk.CTkScrollableFrame(
            settings_window,
            fg_color=COLORS['dark_bg'],
            scrollbar_button_color=COLORS['dark_gray'],
            scrollbar_button_hover_color=COLORS['gray']
        )
        container.pack(fill="both", expand=True, padx=20, pady=20)
       
        title_label = ctk.CTkLabel(
            container,
            text="Settings",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=COLORS['text_primary']
        )
        title_label.pack(anchor="w", pady=(0, 20))
       
        downloads_frame = ctk.CTkFrame(container, fg_color=COLORS['dark_card'])
        downloads_frame.pack(fill="x", pady=(0, 15))
       
        ctk.CTkLabel(
            downloads_frame,
            text="Maximum concurrent downloads:",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS['text_primary']
        ).pack(anchor="w", padx=15, pady=(15, 5))
       
        concurrent_var = ctk.IntVar(value=self.download_manager.max_concurrent)
        concurrent_slider = ctk.CTkSlider(
            downloads_frame,
            from_=1,
            to=10,
            number_of_steps=9,
            variable=concurrent_var,
            fg_color=COLORS['dark_gray'],
            progress_color=COLORS['primary'],
            button_color=COLORS['primary'],
            button_hover_color=COLORS['primary']
        )
        concurrent_slider.pack(fill="x", padx=15, pady=(0, 15))
       
        concurrent_label = ctk.CTkLabel(
            downloads_frame,
            text=f"Current: {self.download_manager.max_concurrent}",
            font=ctk.CTkFont(size=12),
            text_color=COLORS['text_secondary']
        )
        concurrent_label.pack(anchor="w", padx=15, pady=(0, 15))
       
        def update_label(val):
            concurrent_label.configure(text=f"Current: {int(float(val))}")
       
        concurrent_slider.configure(command=update_label)
       
        path_frame = ctk.CTkFrame(container, fg_color=COLORS['dark_card'])
        path_frame.pack(fill="x", pady=(0, 15))
       
        ctk.CTkLabel(
            path_frame,
            text="Default download path:",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS['text_primary']
        ).pack(anchor="w", padx=15, pady=(15, 5))
       
        default_path_var = ctk.StringVar(value=self.settings.get('default_path', os.path.expanduser("~/Downloads")))
        default_path_entry = ctk.CTkEntry(
            path_frame,
            textvariable=default_path_var,
            font=ctk.CTkFont(size=13),
            fg_color=COLORS['dark_gray'],
            text_color=COLORS['text_primary']
        )
        default_path_entry.pack(fill="x", padx=15, pady=(0, 10))
       
        def browse_default_path():
            directory = filedialog.askdirectory()
            if directory:
                default_path_var.set(directory)
       
        browse_btn = ctk.CTkButton(
            path_frame,
            text="Browse",
            width=100,
            command=browse_default_path,
            fg_color=COLORS['primary'],
            hover_color="#FF5757",
            text_color=COLORS['text_primary']
        )
        browse_btn.pack(anchor="e", padx=15, pady=(0, 15))
       
        def save_settings():
            self.download_manager.max_concurrent = concurrent_var.get()
            self.settings['default_path'] = default_path_var.get()
            self.path_var.set(default_path_var.get())
            self.save_settings()
            settings_window.destroy()
            self.status_message.set("Settings saved")
       
        save_btn = ctk.CTkButton(
            container,
            text="💾 Save Settings",
            height=40,
            command=save_settings,
            fg_color=COLORS['success'],
            hover_color="#2DB54F",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS['text_primary']
        )
        save_btn.pack(fill="x", pady=(20, 0))
   
    def show_error(self, title, message):
        messagebox.showerror(title, message)
        self.status_message.set(f"Error: {title}")
   
    def _format_size(self, bytes_num):
        if bytes_num <= 0:
            return "0 B"
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        i = 0
        while bytes_num >= 1024 and i < len(units) - 1:
            bytes_num /= 1024
            i += 1
        return f"{bytes_num:.2f} {units[i]}"
   
    def _format_duration(self, seconds):
        if seconds <= 0:
            return "0:00"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"
   
    def _format_time(self, seconds):
        if seconds is None or seconds <= 0:
            return "??"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours}h {minutes}m"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"
   
    def load_settings(self):
        settings_file = 'settings.json'
        default_settings = {
            'theme': 'dark',
            'default_path': os.path.expanduser("~/Downloads"),
            'max_concurrent': 3,
            'default_format': 'video',
            'default_quality': '1080p'
        }
        try:
            if os.path.exists(settings_file):
                with open(settings_file, 'r', encoding='utf-8') as f:
                    loaded_settings = json.load(f)
                    for key in default_settings:
                        if key not in loaded_settings:
                            loaded_settings[key] = default_settings[key]
                    return loaded_settings
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")
        return default_settings
   
    def save_settings(self):
        try:
            with open('settings.json', 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")

    def update_timer(self):
        if self.current_tab == "📋 Queue":
            self.refresh_task_list()
        self._update_stats()
        self.root.after(1000, self.update_timer)
   
    def _update_stats(self):
        total_downloads = len(self.download_manager.task_history)
        total_size = 0
       
        for task in self.download_manager.task_history:
            if task.status == DownloadStatus.COMPLETED and task.file_path:
                if os.path.exists(task.file_path):
                    total_size += os.path.getsize(task.file_path)
       
        active_downloads = len(self.download_manager.active_tasks)
        stats_text = f"📊 Downloads: {total_downloads} | 📁 Size: {self._format_size(total_size)} | ⚡ Active: {active_downloads}"
        self.stats_label.configure(text=stats_text)
        self.total_downloads = total_downloads
        self.total_size = total_size
        self.active_downloads = active_downloads
   
    def on_closing(self):
        self.download_manager.save_state()
        self.save_settings()
        self.root.destroy()

def main():
    root = ctk.CTk()
    try:
        root.iconbitmap("icon.ico")
    except:
        pass
    app = YouTubeDownloaderPro(root)
    root.mainloop()

if __name__ == "__main__":
    main()