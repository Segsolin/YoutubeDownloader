"""
Advanced YouTube Downloader Pro - COMPLETELY FIXED VERSION
FIXED: Now properly downloads high-quality videos with correct format selection
UPDATED: Scrollable sidebar for better usability
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
# Global styles - Updated for better contrast
COLORS = {
    'primary': '#FF3B30', # Red accent (Televrz style)
    'secondary': '#5856D6', # Blue accent
    'dark_bg': '#0A0A0A', # Darker background for better contrast
    'dark_card': '#1A1A1A', # Darker card
    'dark_text': '#FFFFFF', # Pure white text
    'light_bg': '#F2F2F7',
    'light_card': '#FFFFFF',
    'light_text': '#000000',
    'success': '#34C759',
    'warning': '#FF9500',
    'error': '#FF3B30',
    'info': '#007AFF',
    'gray': '#8E8E93',
    'dark_gray': '#3A3A3C', # Darker gray for borders
    'text_primary': '#FFFFFF', # Primary text color
    'text_secondary': '#8E8E93', # Secondary text color
    'text_disabled': '#3A3A3C', # Disabled text color
}
FONTS = {
    'h1': ('Helvetica', 24, 'bold'),
    'h2': ('Helvetica', 18, 'bold'),
    'h3': ('Helvetica', 16, 'bold'),
    'body': ('Helvetica', 14),
    'caption': ('Helvetica', 12),
    'mono': ('Courier', 12)
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
    format_type: str # video, audio, playlist
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
   
    # Added fields to replace 'options' parameter
    audio_only: bool = False
    include_subtitles: bool = False
    embed_metadata: bool = True
   
    def to_dict(self):
        """Convert to dictionary for serialization"""
        data = asdict(self)
        # Convert enum to string
        data['status'] = self.status.value
        return data
   
    @classmethod
    def from_dict(cls, data):
        """Create DownloadTask from dictionary"""
        # Handle old format with 'options' key
        if 'options' in data:
            options = data.pop('options', {})
            # Map old options to new fields
            data['format_type'] = options.get('format', 'video')
            data['quality'] = options.get('quality', 'best')
            data['output_path'] = options.get('location', os.path.expanduser("~/Downloads"))
            # Additional mappings
            data['audio_only'] = options.get('format', 'video') == 'audio'
       
        # Convert status string to enum
        if 'status' in data and isinstance(data['status'], str):
            try:
                data['status'] = DownloadStatus(data['status'])
            except ValueError:
                data['status'] = DownloadStatus.QUEUED
       
        # Handle missing fields with defaults
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
       
        # Remove any unexpected keys
        expected_keys = set(cls.__dataclass_fields__.keys())
        data = {k: v for k, v in data.items() if k in expected_keys}
       
        return cls(**data)
class DownloadManager:
    """Advanced download manager with thread safety"""
   
    def __init__(self, max_concurrent=3):
        self.active_tasks: Dict[str, DownloadTask] = {}
        self.task_queue: deque = deque()
        self.task_history: List[DownloadTask] = []
        self.task_lock = threading.RLock()
        self.max_concurrent = max_concurrent
        self.callback_queue = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.download_threads: Dict[str, threading.Thread] = {}
        self.stop_events: Dict[str, threading.Event] = {}
       
        # Rate limiting for subtitle requests
        self.last_subtitle_request = 0
        self.subtitle_request_delay = 2.0 # 2 seconds between subtitle requests
       
        # FFmpeg status
        self.ffmpeg_path = None
        self.has_ffmpeg = False
       
        # Load state
        self.load_state()
       
        # Check for FFmpeg
        self._check_ffmpeg()
       
        # Start callback processor
        threading.Thread(target=self._process_callbacks, daemon=True).start()
   
    def save_state(self):
        """Save download state to file"""
        with self.task_lock:
            state = {
                'queue': [task.to_dict() for task in self.task_queue],
                'active': [task.to_dict() for task in self.active_tasks.values()],
                'history': [task.to_dict() for task in self.task_history[-100:]] # Keep last 100
            }
            try:
                with open('download_state.json', 'w', encoding='utf-8') as f:
                    json.dump(state, f, default=str, indent=2)
            except Exception as e:
                logger.error(f"Failed to save state: {e}")
   
    def load_state(self):
        """Load download state from file"""
        try:
            if os.path.exists('download_state.json'):
                with open('download_state.json', 'r', encoding='utf-8') as f:
                    state = json.load(f)
                   
                    # Load queue - with better error handling
                    self.task_queue = deque()
                    queue_data = state.get('queue', [])
                    logger.info(f"Loading {len(queue_data)} queued tasks")
                   
                    for task_data in queue_data:
                        try:
                            task = DownloadTask.from_dict(task_data)
                            self.task_queue.append(task)
                        except Exception as e:
                            logger.error(f"Failed to load queued task: {e}")
                            logger.debug(f"Problematic task data: {task_data}")
                   
                    # Load active tasks (reset to queued)
                    self.active_tasks = {}
                    active_data = state.get('active', [])
                    logger.info(f"Loading {len(active_data)} active tasks")
                   
                    for task_data in active_data:
                        try:
                            task = DownloadTask.from_dict(task_data)
                            task.status = DownloadStatus.QUEUED
                            task.progress = 0
                            self.task_queue.append(task)
                        except Exception as e:
                            logger.error(f"Failed to load active task: {e}")
                            logger.debug(f"Problematic task data: {task_data}")
                   
                    # Load history
                    self.task_history = []
                    history_data = state.get('history', [])
                    logger.info(f"Loading {len(history_data)} history tasks")
                   
                    for task_data in history_data:
                        try:
                            task = DownloadTask.from_dict(task_data)
                            self.task_history.append(task)
                        except Exception as e:
                            logger.error(f"Failed to load history task: {e}")
                            logger.debug(f"Problematic task data: {task_data}")
                   
                    logger.info(f"State loaded: {len(self.task_queue)} queued, {len(self.task_history)} history")
                           
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            # Initialize with empty data
            self.task_queue = deque()
            self.active_tasks = {}
            self.task_history = []
   
    def _check_ffmpeg(self):
        """Check for FFmpeg and update status"""
        self.ffmpeg_path = self._find_ffmpeg()
        self.has_ffmpeg = self.ffmpeg_path is not None
        if self.has_ffmpeg:
            logger.info(f"FFmpeg found at: {self.ffmpeg_path}")
        else:
            logger.warning("FFmpeg not found - high quality downloads limited")
   
    def add_task(self, url: str, format_type: str, quality: str,
                 output_path: str, title: Optional[str] = None,
                 include_subtitles: bool = False, embed_metadata: bool = True) -> str:
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
       
        # Trigger callback
        self.callback_queue.put(('task_added', task_id))
       
        # Auto-start if possible
        self._auto_start_downloads()
       
        return task_id
   
    def _auto_start_downloads(self):
        """Automatically start downloads if slots available"""
        with self.task_lock:
            available_slots = self.max_concurrent - len(self.active_tasks)
            for _ in range(min(available_slots, len(self.task_queue))):
                if self.task_queue:
                    task = self.task_queue[0]
                    if task.status == DownloadStatus.QUEUED:
                        self.start_task(task.id)
   
    def start_task(self, task_id: str) -> bool:
        """Start a download task"""
        with self.task_lock:
            # Find task in queue
            task_to_start = None
            for i, task in enumerate(self.task_queue):
                if task.id == task_id:
                    task_to_start = self.task_queue[i]
                    del self.task_queue[i]
                    break
           
            if not task_to_start:
                return False
           
            # Check if we have available slots
            if len(self.active_tasks) >= self.max_concurrent:
                self.task_queue.appendleft(task_to_start)
                return False
           
            # Update task status
            task_to_start.status = DownloadStatus.DOWNLOADING
            self.active_tasks[task_id] = task_to_start
           
            # Create stop event for this task
            self.stop_events[task_id] = threading.Event()
           
            # Start download thread
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
        """Pause a download task"""
        with self.task_lock:
            if task_id in self.active_tasks:
                task = self.active_tasks[task_id]
                task.status = DownloadStatus.PAUSED
               
                # Signal stop event
                if task_id in self.stop_events:
                    self.stop_events[task_id].set()
               
                # Move back to front of queue
                self.task_queue.appendleft(task)
                del self.active_tasks[task_id]
               
                self.save_state()
                self.callback_queue.put(('task_paused', task_id))
                return True
        return False
   
    def resume_task(self, task_id: str) -> bool:
        """Resume a paused task"""
        with self.task_lock:
            # Find task in queue
            for i, task in enumerate(self.task_queue):
                if task.id == task_id and task.status == DownloadStatus.PAUSED:
                    task.status = DownloadStatus.QUEUED
                    self.save_state()
                    self.callback_queue.put(('task_resumed', task_id))
                    return self.start_task(task_id)
        return False
   
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task completely"""
        with self.task_lock:
            # Check active tasks
            if task_id in self.active_tasks:
                # Signal stop event
                if task_id in self.stop_events:
                    self.stop_events[task_id].set()
               
                task = self.active_tasks[task_id]
                task.status = DownloadStatus.CANCELLED
                self.task_history.append(task)
                del self.active_tasks[task_id]
               
                # Cleanup partial files
                self._cleanup_partial_files(task)
           
            # Check queue
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
        """Clean up partially downloaded files"""
        try:
            if task.file_path and os.path.exists(task.file_path):
                # Check if file is incomplete (e.g., .part file)
                if task.file_path.endswith('.part') or task.progress < 100:
                    os.remove(task.file_path)
        except Exception as e:
            logger.error(f"Failed to cleanup files for task {task.id}: {e}")
   
    def _download_worker(self, task: DownloadTask):
        """Worker thread for downloading - FIXED VERSION"""
        try:
            # Get stream info first
            info = self._get_video_info(task.url)
            if not info:
                task.status = DownloadStatus.ERROR
                task.error = "Failed to get video information"
                self.callback_queue.put(('task_error', task.id))
                return
           
            # Update task with info
            task.title = info.get('title', task.title)
            task.duration = info.get('duration', 0)
            task.channel = info.get('channel', None)
           
            # Log available formats for debugging
            formats = info.get('formats', [])
            logger.info(f"Task {task.id}: Requested quality: {task.quality}")
            logger.info(f"Task {task.id}: Available formats: {len(formats)}")
           
            # Log some format details for debugging
            video_formats = [f for f in formats if f.get('vcodec') != 'none']
            audio_formats = [f for f in formats if f.get('acodec') != 'none']
           
            logger.info(f"Task {task.id}: Video formats: {len(video_formats)}")
            logger.info(f"Task {task.id}: Audio formats: {len(audio_formats)}")
           
            # Log resolutions for debugging
            resolutions = set()
            for fmt in video_formats:
                height = fmt.get('height')
                if height:
                    resolutions.add(height)
           
            logger.info(f"Task {task.id}: Available resolutions: {sorted(resolutions, reverse=True)}")
           
            # Set up download options - USE THE NEW SIMPLIFIED METHOD
            ydl_opts = self._build_ydl_options_simple(task, info)
           
            # Log the format selector being used
            logger.info(f"Task {task.id}: Using format selector: {ydl_opts.get('format')}")
           
            # Progress hook
            def progress_hook(d):
                if self.stop_events.get(task.id, threading.Event()).is_set():
                    raise Exception("Download stopped by user")
               
                if d['status'] == 'downloading':
                    task.downloaded_bytes = d.get('downloaded_bytes', 0)
                    task.total_bytes = d.get('total_bytes', d.get('total_bytes_estimate', 0))
                    task.speed = d.get('speed', 0)
                    task.eta = d.get('eta', 0)
                   
                    if task.total_bytes > 0:
                        task.progress = (task.downloaded_bytes / task.total_bytes) * 100
                    elif d.get('fragment_index') and d.get('fragment_count'):
                        task.progress = (d['fragment_index'] / d['fragment_count']) * 100
                   
                    self.callback_queue.put(('task_progress', task.id))
               
                elif d['status'] == 'processing':
                    task.status = DownloadStatus.PROCESSING
                    self.callback_queue.put(('task_processing', task.id))
               
                elif d['status'] == 'merging':
                    task.status = DownloadStatus.MERGING
                    self.callback_queue.put(('task_merging', task.id))
           
            ydl_opts['progress_hooks'] = [progress_hook]
           
            # Perform download with retry logic
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    with YoutubeDL(ydl_opts) as ydl:
                        task.status = DownloadStatus.DOWNLOADING
                        self.callback_queue.put(('task_started', task.id))
                       
                        # Log what yt-dlp will download
                        logger.info(f"Task {task.id}: Attempt {attempt + 1} - Downloading with format: {ydl_opts['format']}")
                       
                        try:
                            ydl.download([task.url])
                            break # Success, break out of retry loop
                           
                        except Exception as e:
                            error_msg = str(e)
                            logger.warning(f"Task {task.id}: Download attempt {attempt + 1} failed: {error_msg}")
                           
                            # Handle specific errors
                            if "HTTP Error 429" in error_msg and "subtitles" in error_msg:
                                logger.warning(f"Task {task.id}: Subtitle rate limited, retrying without subtitles")
                                ydl_opts.pop('writesubtitles', None)
                                ydl_opts.pop('writeautomaticsub', None)
                                ydl_opts.pop('subtitleslangs', None)
                                continue
                           
                            elif "format is not available" in error_msg.lower() or "requested format" in error_msg.lower():
                                logger.warning(f"Task {task.id}: Format not available, trying fallback")
                                # Try simpler format
                                ydl_opts['format'] = 'best'
                                continue
                           
                            elif attempt < max_retries - 1:
                                # Wait before retry
                                time.sleep(2)
                                continue
                            else:
                                raise
               
                except Exception as e:
                    if attempt < max_retries - 1:
                        continue
                    else:
                        raise
           
            # Mark as completed
            task.status = DownloadStatus.COMPLETED
            task.progress = 100
            task.completed_at = time.time()
           
            # Find the actual file
            task.file_path = self._find_downloaded_file(task, ydl_opts['outtmpl'])
           
            if task.file_path:
                file_size = os.path.getsize(task.file_path)
                logger.info(f"Task {task.id}: Download completed. File: {task.file_path}, Size: {file_size} bytes")
            else:
                logger.warning(f"Task {task.id}: Download completed but file not found")
           
            # Move to history
            with self.task_lock:
                self.task_history.append(task)
                if task.id in self.active_tasks:
                    del self.active_tasks[task.id]
           
            self.save_state()
            self.callback_queue.put(('task_completed', task.id))
           
            # Start next download if queue not empty
            self._auto_start_downloads()
           
        except Exception as e:
            logger.error(f"Download error for task {task.id}: {e}", exc_info=True)
            task.status = DownloadStatus.ERROR
            task.error = str(e)
           
            with self.task_lock:
                if task.id in self.active_tasks:
                    del self.active_tasks[task.id]
           
            self.save_state()
            self.callback_queue.put(('task_error', task.id))
           
            # Cleanup on error
            self._cleanup_partial_files(task)
   
    def _get_video_info(self, url: str) -> Optional[Dict]:
        """Get video information using yt-dlp"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'force_generic_extractor': False,
            }
           
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info
               
        except Exception as e:
            logger.error(f"Failed to get video info: {e}")
            return None
   
    def _build_ydl_options_simple(self, task: DownloadTask, info: Dict) -> Dict:
        """Build yt-dlp options - SIMPLIFIED AND FIXED VERSION"""
        # Create output template
        output_template = os.path.join(
            task.output_path,
            '%(title)s [%(id)s].%(ext)s'
        )
       
        # Base options
        ydl_opts = {
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': False,
            'retries': 10,
            'fragment_retries': 10,
            'file_access_retries': 3,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'player_skip': ['configs', 'js'],
                }
            },
            'concurrent_fragment_downloads': 4,
            'throttledratelimit': 1000000,
            'buffersize': 1024 * 1024,
            'http_chunk_size': 10485760,
        }
       
        # Set ffmpeg location if available
        if self.has_ffmpeg and self.ffmpeg_path:
            ydl_opts['ffmpeg_location'] = self.ffmpeg_path
       
        # SIMPLIFIED AND EFFECTIVE FORMAT SELECTION
        if task.format_type == 'audio':
            # For audio, use simple format selection
            ydl_opts['format'] = 'bestaudio'
            if self.has_ffmpeg:
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '320',
                }]
        else:
            # For video, use different strategies based on quality
            quality = task.quality.lower()
           
            if quality == 'best':
                # For "best", let yt-dlp choose the best available
                if self.has_ffmpeg:
                    ydl_opts['format'] = 'bestvideo+bestaudio/best'
                else:
                    ydl_opts['format'] = 'best[ext=mp4]/best'
           
            elif quality == 'worst':
                # For "worst", get the worst quality
                ydl_opts['format'] = 'worst'
           
            else:
                # For specific resolutions
                # Map quality strings to heights
                quality_map = {
                    '8k': 4320,
                    '4k': 2160,
                    '1440p': 1440,
                    '1080p': 1080,
                    '720p': 720,
                    '480p': 480,
                    '360p': 360,
                    '240p': 240,
                    '144p': 144,
                }
               
                height = quality_map.get(quality, 1080)
               
                if self.has_ffmpeg:
                    # With ffmpeg, we can merge separate streams
                    ydl_opts['format'] = f'bestvideo[height<={height}]+bestaudio/best[height<={height}]/best'
                else:
                    # Without ffmpeg, need single stream
                    ydl_opts['format'] = f'best[height<={height}][ext=mp4]/best[height<={height}]'
       
        # Post-processor for merging if we have separate streams
        if self.has_ffmpeg and task.format_type == 'video' and '+bestaudio' in ydl_opts.get('format', ''):
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }]
            ydl_opts['merge_output_format'] = 'mp4'
       
        # Add subtitles if requested
        if task.include_subtitles:
            current_time = time.time()
            if current_time - self.last_subtitle_request >= self.subtitle_request_delay:
                ydl_opts['writesubtitles'] = True
                ydl_opts['writeautomaticsub'] = True
                ydl_opts['subtitleslangs'] = ['en']
                self.last_subtitle_request = current_time
       
        # Add metadata if requested
        if task.embed_metadata:
            ydl_opts['writethumbnail'] = True
            ydl_opts['embedthumbnail'] = True
            if task.include_subtitles:
                ydl_opts['embedsubtitles'] = True
            ydl_opts['addmetadata'] = True
       
        return ydl_opts
   
    def _build_ydl_options_advanced(self, task: DownloadTask, info: Dict) -> Dict:
        """Alternative advanced method for format selection"""
        output_template = os.path.join(
            task.output_path,
            '%(title)s [%(id)s].%(ext)s'
        )
       
        ydl_opts = {
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': False,
            'retries': 10,
            'fragment_retries': 10,
            'file_access_retries': 3,
            'concurrent_fragment_downloads': 4,
        }
       
        # Set ffmpeg location if available
        if self.has_ffmpeg and self.ffmpeg_path:
            ydl_opts['ffmpeg_location'] = self.ffmpeg_path
       
        # SIMPLE BUT EFFECTIVE format selection
        if task.format_type == 'audio':
            ydl_opts['format'] = 'bestaudio'
            if self.has_ffmpeg:
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '320',
                }]
        else:
            # Try different strategies based on what works
            quality = task.quality.lower()
           
            if quality == 'best':
                # Strategy 1: Let yt-dlp decide
                if self.has_ffmpeg:
                    # Try merging streams
                    ydl_opts['format'] = 'bv*[vcodec^=avc1]+ba/b[vcodec^=avc1] / bv*+ba/b'
                else:
                    # Single stream
                    ydl_opts['format'] = 'best[ext=mp4]'
           
            elif quality == 'worst':
                ydl_opts['format'] = 'worst'
           
            else:
                # For specific quality
                height_map = {
                    '8k': 4320, '4k': 2160, '1440p': 1440, '1080p': 1080,
                    '720p': 720, '480p': 480, '360p': 360, '240p': 240, '144p': 144
                }
               
                height = height_map.get(quality, 1080)
               
                if self.has_ffmpeg:
                    # Try multiple strategies
                    format_selectors = [
                        f'bv*[height<={height}][vcodec^=avc1]+ba/b[height<={height}]',
                        f'bv*[height<={height}]+ba/b[height<={height}]',
                        f'bestvideo[height<={height}]+bestaudio/best[height<={height}]',
                    ]
                    ydl_opts['format'] = '/'.join(format_selectors)
                else:
                    ydl_opts['format'] = f'best[height<={height}][ext=mp4]'
       
        # Add post-processor if we're merging
        if self.has_ffmpeg and task.format_type == 'video' and ('+' in ydl_opts.get('format', '') or 'bv' in ydl_opts.get('format', '')):
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }]
            ydl_opts['merge_output_format'] = 'mp4'
       
        return ydl_opts
   
    def _find_ffmpeg(self) -> Optional[str]:
        """Find ffmpeg executable"""
        try:
            # Try system PATH first
            ffmpeg_path = shutil.which('ffmpeg')
            if ffmpeg_path:
                # Test ffmpeg
                try:
                    result = subprocess.run(
                        [ffmpeg_path, '-version'],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == 'Windows' else 0
                    )
                    if result.returncode == 0 and 'ffmpeg version' in result.stdout:
                        logger.info(f"Found FFmpeg in PATH: {ffmpeg_path}")
                        return ffmpeg_path
                except:
                    pass
           
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
               
                # Also check PATH environment variable explicitly
                path_dirs = os.environ.get('PATH', '').split(';')
                for path_dir in path_dirs:
                    if path_dir.strip():
                        ffmpeg_exe = os.path.join(path_dir, "ffmpeg.exe")
                        if os.path.exists(ffmpeg_exe):
                            common_paths.append(ffmpeg_exe)
           
            else: # Linux/macOS
                common_paths = [
                    "/usr/bin/ffmpeg",
                    "/usr/local/bin/ffmpeg",
                    "/opt/homebrew/bin/ffmpeg",
                    "/opt/local/bin/ffmpeg",
                    "/bin/ffmpeg",
                    "/sbin/ffmpeg",
                    os.path.expanduser("~/bin/ffmpeg"),
                    os.path.expanduser("~/.local/bin/ffmpeg"),
                    os.path.join(os.getcwd(), "ffmpeg", "bin", "ffmpeg"),
                    os.path.join(os.path.dirname(__file__), "ffmpeg", "bin", "ffmpeg"),
                ]
               
                # Check PATH environment variable
                path_dirs = os.environ.get('PATH', '').split(':')
                for path_dir in path_dirs:
                    if path_dir.strip():
                        ffmpeg_path = os.path.join(path_dir, "ffmpeg")
                        if os.path.exists(ffmpeg_path):
                            common_paths.append(ffmpeg_path)
           
            # Remove duplicates while preserving order
            common_paths = list(dict.fromkeys(common_paths))
           
            for path in common_paths:
                if os.path.exists(path):
                    try:
                        # Test if it's actually ffmpeg
                        result = subprocess.run(
                            [path, '-version'],
                            capture_output=True,
                            text=True,
                            timeout=5,
                            creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == 'Windows' else 0
                        )
                        if result.returncode == 0 and 'ffmpeg version' in result.stdout:
                            logger.info(f"Found FFmpeg at: {path}")
                            return path
                    except Exception as e:
                        logger.debug(f"Failed to test FFmpeg at {path}: {e}")
                        continue
           
            return None
                       
        except Exception as e:
            logger.error(f"Error finding ffmpeg: {e}")
            return None
   
    def _find_downloaded_file(self, task: DownloadTask, output_template: str) -> Optional[str]:
        """Find the actual downloaded file"""
        try:
            # Extract base filename from template
            base_dir = os.path.dirname(output_template)
            if not os.path.exists(base_dir):
                base_dir = task.output_path
           
            # Look for files matching the pattern
            pattern = re.compile(rf".*{re.escape(task.title)}.*\.(mp4|mkv|webm|mp3|m4a|ogg|flac)$", re.IGNORECASE)
           
            for filename in os.listdir(base_dir):
                if pattern.match(filename):
                    filepath = os.path.join(base_dir, filename)
                    # Check if file is reasonably sized (> 100KB)
                    if os.path.getsize(filepath) > 100 * 1024:
                        return filepath
           
            # Try to find by modification time
            files = []
            for filename in os.listdir(base_dir):
                filepath = os.path.join(base_dir, filename)
                if os.path.isfile(filepath) and os.path.getsize(filepath) > 100 * 1024:
                    files.append((filepath, os.path.getmtime(filepath)))
           
            if files:
                # Get most recently modified file
                files.sort(key=lambda x: x[1], reverse=True)
                return files[0][0]
               
        except Exception as e:
            logger.error(f"Failed to find downloaded file: {e}")
       
        return None
   
    def _process_callbacks(self):
        """Process callback queue (runs in separate thread)"""
        while True:
            try:
                callback_type, task_id = self.callback_queue.get(timeout=1)
                # This would typically update UI, but we handle it in the main app
                pass
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in callback processor: {e}")
   
    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        """Get task by ID"""
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
        """Get all tasks (active + queued + recent history)"""
        with self.task_lock:
            tasks = list(self.active_tasks.values()) + list(self.task_queue) + self.task_history[-50:]
            return tasks
   
    def clear_completed(self):
        """Clear completed tasks from history"""
        with self.task_lock:
            # Keep only non-completed in history
            self.task_history = [t for t in self.task_history if t.status != DownloadStatus.COMPLETED]
            self.save_state()
   
    def clear_all(self):
        """Clear all tasks"""
        with self.task_lock:
            # Stop all active downloads
            for task_id in list(self.active_tasks.keys()):
                self.cancel_task(task_id)
           
            # Clear queue
            for task in list(self.task_queue):
                task.status = DownloadStatus.CANCELLED
                self.task_history.append(task)
           
            self.task_queue.clear()
            self.save_state()
class YouTubeDownloaderPro:
    """Main application class with Televrz-inspired UI"""
   
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Downloader Pro - FIXED")
        self.root.geometry("1200x800")
        self.root.minsize(1000, 700)
       
        # Set theme
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
       
        # Initialize components
        self.download_manager = DownloadManager(max_concurrent=3)
        self.current_theme = "dark"
        self.video_cache = {}
        self.thumbnail_cache = {}
        self.settings = self.load_settings()
        self.current_tab = "download"
       
        # UI elements
        self.tab_view = None
        self.url_entry = None
        self.format_combo = None
        self.quality_combo = None
        self.path_entry = None
        self.task_listbox = None
        self.history_tree = None
        self.progress_bars = {}
        self.status_labels = {}
        self.control_buttons = {}
       
        # New UI options
        self.subtitles_var = ctk.BooleanVar(value=False)
        self.metadata_var = ctk.BooleanVar(value=True)
       
        # Stats
        self.total_downloads = 0
        self.total_size = 0
        self.active_downloads = 0
       
        # Setup UI
        self.setup_ui()
       
        # Start update timer
        self.update_timer()
       
        # Load initial data
        self.refresh_task_list()
        self.refresh_history()
       
        # Bind close event
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
   
    def setup_ui(self):
        """Setup the main user interface"""
        # Main container
        self.main_container = ctk.CTkFrame(self.root, fg_color=COLORS['dark_bg'])
        self.main_container.pack(fill="both", expand=True)
       
        # Header
        self.setup_header()
       
        # Main content area with tabs
        self.setup_tabs()
       
        # Status bar
        self.setup_status_bar()
   
    def setup_header(self):
        """Setup application header"""
        header_frame = ctk.CTkFrame(
            self.main_container,
            fg_color=COLORS['dark_card'],
            height=60
        )
        header_frame.pack(fill="x", padx=10, pady=(10, 5))
        header_frame.pack_propagate(False)
       
        # Logo/Title
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
            text="v2.0.0",
            font=ctk.CTkFont(size=12),
            text_color=COLORS['text_secondary']
        )
        version_label.pack(side="left", padx=(10, 0))
       
        # FFmpeg status
        if self.download_manager.has_ffmpeg:
            ffmpeg_label = ctk.CTkLabel(
                title_frame,
                text="✓ FFmpeg",
                font=ctk.CTkFont(size=10),
                text_color=COLORS['success']
            )
            ffmpeg_label.pack(side="left", padx=(10, 0))
        else:
            ffmpeg_label = ctk.CTkLabel(
                title_frame,
                text="⚠ No FFmpeg",
                font=ctk.CTkFont(size=10),
                text_color=COLORS['warning']
            )
            ffmpeg_label.pack(side="left", padx=(10, 0))
       
        # Stats frame
        stats_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        stats_frame.pack(side="left", padx=50)
       
        stats_text = f"📊 Downloads: {self.total_downloads} | 📁 Size: {self.format_size(self.total_size)} | ⚡ Active: {self.active_downloads}"
        self.stats_label = ctk.CTkLabel(
            stats_frame,
            text=stats_text,
            font=ctk.CTkFont(size=12),
            text_color=COLORS['text_secondary']
        )
        self.stats_label.pack()
       
        # Settings button
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
   
    def setup_tabs(self):
        """Setup main tabs"""
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
       
        # Create tabs
        self.download_tab = self.tab_view.add("⬇️ Download")
        self.queue_tab = self.tab_view.add("📋 Queue")
        self.history_tab = self.tab_view.add("📊 History")
        self.playlist_tab = self.tab_view.add("🎵 Playlist")
       
        # Setup each tab
        self.setup_download_tab()
        self.setup_queue_tab()
        self.setup_history_tab()
        self.setup_playlist_tab()
       
        # Bind tab change event
        self.tab_view.configure(command=self.on_tab_changed)
   
    def setup_download_tab(self):
        """Setup download tab"""
        # Main content frame
        content_frame = ctk.CTkFrame(self.download_tab, fg_color=COLORS['dark_bg'])
        content_frame.pack(fill="both", expand=True, padx=20, pady=20)
       
        # Create a scrollable left panel
        left_container = ctk.CTkFrame(content_frame, fg_color=COLORS['dark_bg'])
        left_container.pack(side="left", fill="y", padx=(0, 10))
       
        # Add a scrollable frame inside the container
        left_panel = ctk.CTkScrollableFrame(
            left_container,
            fg_color=COLORS['dark_card'],
            width=400,
            scrollbar_button_color=COLORS['dark_gray'],
            scrollbar_button_hover_color=COLORS['gray'],
            orientation="vertical"
        )
        left_panel.pack(fill="both", expand=True)
       
        # Make the container have a fixed width
        left_container.pack_propagate(False)
        left_container.configure(width=420) # Width + scrollbar width
       
        # Right panel - Preview
        right_panel = ctk.CTkFrame(content_frame, fg_color=COLORS['dark_card'])
        right_panel.pack(side="right", fill="both", expand=True)
       
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
       
        # Quality selection - SIMPLIFIED
        quality_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        quality_frame.pack(fill="x", padx=20, pady=10)
       
        ctk.CTkLabel(
            quality_frame,
            text="Quality:",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS['text_primary']
        ).pack(anchor="w")
       
        quality_options = ["best", "1080p", "720p", "480p", "360p", "worst"]
       
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
        self.quality_combo.set("1080p")
        self.quality_combo.pack(fill="x", pady=(5, 0))
       
        # Advanced options
        advanced_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        advanced_frame.pack(fill="x", padx=20, pady=10)
       
        ctk.CTkLabel(
            advanced_frame,
            text="Advanced Options:",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS['text_primary']
        ).pack(anchor="w")
       
        # Subtitles option
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
       
        # Metadata option
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
       
        # Test download button
        test_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        test_frame.pack(fill="x", padx=20, pady=10)
       
        test_btn = ctk.CTkButton(
            test_frame,
            text="🧪 Test Quality",
            height=30,
            command=self.test_quality,
            fg_color=COLORS['secondary'],
            hover_color="#6C6AFF",
            text_color=COLORS['text_primary']
        )
        test_btn.pack(fill="x")
       
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
       
        # Preview area in right panel
        self.preview_frame = ctk.CTkFrame(right_panel, fg_color=COLORS['dark_card'])
        self.preview_frame.pack(fill="both", expand=True, padx=20, pady=20)
       
        # Initial preview message
        preview_label = ctk.CTkLabel(
            self.preview_frame,
            text="Enter a YouTube URL and click 'Fetch Info' to see video details",
            font=ctk.CTkFont(size=16),
            text_color=COLORS['text_secondary']
        )
        preview_label.place(relx=0.5, rely=0.5, anchor="center")
   
    def setup_queue_tab(self):
        """Setup queue tab"""
        # Main frame
        main_frame = ctk.CTkFrame(self.queue_tab, fg_color=COLORS['dark_bg'])
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
       
        # Header with controls
        header_frame = ctk.CTkFrame(main_frame, fg_color=COLORS['dark_card'])
        header_frame.pack(fill="x", pady=(0, 10))
       
        ctk.CTkLabel(
            header_frame,
            text="Download Queue",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=COLORS['text_primary']
        ).pack(side="left", padx=20, pady=10)
       
        # Control buttons
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
       
        # Queue list container
        list_container = ctk.CTkFrame(main_frame, fg_color=COLORS['dark_card'])
        list_container.pack(fill="both", expand=True)
       
        # Scrollable frame for queue items
        self.queue_scroll = ctk.CTkScrollableFrame(
            list_container,
            fg_color=COLORS['dark_card']
        )
        self.queue_scroll.pack(fill="both", expand=True, padx=10, pady=10)
       
        # Configure scrollable frame text color
        self.queue_scroll._text_color = COLORS['text_primary']
   
    def setup_history_tab(self):
        """Setup history tab"""
        # Main frame
        main_frame = ctk.CTkFrame(self.history_tab, fg_color=COLORS['dark_bg'])
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
       
        # Header
        header_frame = ctk.CTkFrame(main_frame, fg_color=COLORS['dark_card'])
        header_frame.pack(fill="x", pady=(0, 10))
       
        ctk.CTkLabel(
            header_frame,
            text="Download History",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=COLORS['text_primary']
        ).pack(side="left", padx=20, pady=10)
       
        # Control buttons
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
       
        # History list
        list_frame = ctk.CTkFrame(main_frame, fg_color=COLORS['dark_card'])
        list_frame.pack(fill="both", expand=True)
       
        # Create treeview with scrollbars
        tree_frame = ctk.CTkFrame(list_frame, fg_color=COLORS['dark_card'])
        tree_frame.pack(fill="both", expand=True, padx=10, pady=10)
       
        # Vertical scrollbar
        v_scrollbar = ttk.Scrollbar(tree_frame)
        v_scrollbar.pack(side="right", fill="y")
       
        # Horizontal scrollbar
        h_scrollbar = ttk.Scrollbar(tree_frame, orient="horizontal")
        h_scrollbar.pack(side="bottom", fill="x")
       
        # Create treeview
        self.history_tree = ttk.Treeview(
            tree_frame,
            columns=("status", "format", "quality", "size", "date"),
            show="tree headings",
            height=20,
            yscrollcommand=v_scrollbar.set,
            xscrollcommand=h_scrollbar.set
        )
       
        # Configure scrollbars
        v_scrollbar.config(command=self.history_tree.yview)
        h_scrollbar.config(command=self.history_tree.xview)
       
        # Define columns
        self.history_tree.heading("#0", text="Title", anchor="w")
        self.history_tree.heading("status", text="Status", anchor="w")
        self.history_tree.heading("format", text="Format", anchor="w")
        self.history_tree.heading("quality", text="Quality", anchor="w")
        self.history_tree.heading("size", text="Size", anchor="w")
        self.history_tree.heading("date", text="Date", anchor="w")
       
        # Column widths
        self.history_tree.column("#0", width=400, minwidth=200)
        self.history_tree.column("status", width=100, minwidth=80)
        self.history_tree.column("format", width=80, minwidth=60)
        self.history_tree.column("quality", width=80, minwidth=60)
        self.history_tree.column("size", width=100, minwidth=80)
        self.history_tree.column("date", width=150, minwidth=120)
       
        # Style the treeview
        style = ttk.Style()
        style.theme_use("default")
       
        # Configure Treeview colors for dark theme
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
       
        # Configure treeview tags for different statuses
        self.history_tree.tag_configure('completed', foreground=COLORS['success'])
        self.history_tree.tag_configure('error', foreground=COLORS['error'])
        self.history_tree.tag_configure('cancelled', foreground=COLORS['warning'])
       
        # Pack treeview
        self.history_tree.pack(fill="both", expand=True)
       
        # Bind double-click event
        self.history_tree.bind("<Double-1>", self.on_history_item_double_click)
   
    def setup_playlist_tab(self):
        """Setup playlist tab"""
        main_frame = ctk.CTkFrame(self.playlist_tab, fg_color=COLORS['dark_bg'])
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
       
        # Header
        header_frame = ctk.CTkFrame(main_frame, fg_color=COLORS['dark_card'])
        header_frame.pack(fill="x", pady=(0, 10))
       
        ctk.CTkLabel(
            header_frame,
            text="Playlist Downloader",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=COLORS['text_primary']
        ).pack(side="left", padx=20, pady=10)
       
        # Playlist URL input
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
       
        # Playlist info display
        self.playlist_info_frame = ctk.CTkFrame(main_frame, fg_color=COLORS['dark_card'])
        self.playlist_info_frame.pack(fill="both", expand=True)
       
        # Initial message
        info_label = ctk.CTkLabel(
            self.playlist_info_frame,
            text="Enter a playlist URL to see details",
            font=ctk.CTkFont(size=16),
            text_color=COLORS['text_secondary']
        )
        info_label.place(relx=0.5, rely=0.5, anchor="center")
   
    def setup_status_bar(self):
        """Setup status bar at bottom"""
        status_frame = ctk.CTkFrame(
            self.main_container,
            fg_color=COLORS['dark_card'],
            height=40
        )
        status_frame.pack(fill="x", padx=10, pady=(5, 10))
        status_frame.pack_propagate(False)
       
        # Status message
        self.status_message = ctk.StringVar(value="Ready")
        status_label = ctk.CTkLabel(
            status_frame,
            textvariable=self.status_message,
            font=ctk.CTkFont(size=12),
            text_color=COLORS['text_secondary']
        )
        status_label.pack(side="left", padx=20)
       
        # System info
        sys_info = f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} | {platform.system()} {platform.release()}"
        sys_label = ctk.CTkLabel(
            status_frame,
            text=sys_info,
            font=ctk.CTkFont(size=10),
            text_color=COLORS['text_secondary']
        )
        sys_label.pack(side="right", padx=20)
   
    def test_quality(self):
        """Test the quality selection logic"""
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Warning", "Please enter a YouTube URL first")
            return
       
        # Create a test task
        test_task = DownloadTask(
            id="test",
            url=url,
            title="Test",
            format_type=self.format_var.get(),
            quality=self.quality_combo.get(),
            output_path=self.path_var.get(),
            status=DownloadStatus.QUEUED
        )
       
        # Get video info
        info = self.download_manager._get_video_info(url)
        if not info:
            messagebox.showerror("Error", "Could not get video info")
            return
       
        # Build options using the new method
        ydl_opts = self.download_manager._build_ydl_options_simple(test_task, info)
       
        # Show the format selector being used
        format_selector = ydl_opts.get('format', 'Not set')
       
        # Get available formats
        formats = info.get('formats', [])
        resolutions = set()
        for fmt in formats:
            if fmt.get('vcodec') != 'none':
                height = fmt.get('height')
                if height:
                    resolutions.add(height)
       
        message = f"""
        Quality Test Results:
       
        Requested Quality: {test_task.quality}
        Format Selector: {format_selector}
        FFmpeg Available: {self.download_manager.has_ffmpeg}
       
        Available Resolutions: {sorted(resolutions, reverse=True)}
       
        The format selector above will be used for downloads.
        If you're getting low quality, try:
        1. Use 'best' instead of specific resolution
        2. Make sure FFmpeg is properly installed
        3. Check the log file for detailed info
        """
       
        messagebox.showinfo("Quality Test", message)
   
    def fetch_video_info(self):
        """Fetch video information from URL"""
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Warning", "Please enter a YouTube URL")
            return
       
        # Clear preview frame
        for widget in self.preview_frame.winfo_children():
            widget.destroy()
       
        # Show loading
        loading_label = ctk.CTkLabel(
            self.preview_frame,
            text="Fetching video information...",
            font=ctk.CTkFont(size=16),
            text_color=COLORS['text_secondary']
        )
        loading_label.place(relx=0.5, rely=0.5, anchor="center")
       
        # Fetch in thread
        threading.Thread(target=self._fetch_video_info_thread, args=(url,), daemon=True).start()
   
    def _fetch_video_info_thread(self, url):
        """Thread for fetching video info"""
        try:
            # Get video info using yt-dlp
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
            }
           
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
               
                # Update UI in main thread
                self.root.after(0, lambda: self.display_video_info(info))
               
        except Exception as e:
            error_msg = str(e)
            self.root.after(0, lambda: self.show_error("Failed to fetch video info", error_msg))
   
    def display_video_info(self, info):
        """Display video information in preview"""
        # Clear preview frame
        for widget in self.preview_frame.winfo_children():
            widget.destroy()
       
        try:
            # Create main container
            container = ctk.CTkScrollableFrame(
                self.preview_frame,
                fg_color=COLORS['dark_card'],
                scrollbar_button_color=COLORS['dark_gray'],
                scrollbar_button_hover_color=COLORS['gray']
            )
            container.pack(fill="both", expand=True)
           
            # Thumbnail
            thumbnail_url = info.get('thumbnail')
            thumbnail_frame = ctk.CTkFrame(container, fg_color="transparent")
            thumbnail_frame.pack(fill="x", padx=20, pady=20)
           
            if thumbnail_url:
                try:
                    response = requests.get(thumbnail_url, timeout=10)
                    img_data = response.content
                    img = Image.open(BytesIO(img_data))
                   
                    # Resize to reasonable dimensions
                    max_size = (400, 225)
                    img.thumbnail(max_size, Image.Resampling.LANCZOS)
                   
                    # Convert to CTkImage
                    ctk_img = ctk.CTkImage(
                        light_image=img,
                        dark_image=img,
                        size=img.size
                    )
                   
                    thumbnail_label = ctk.CTkLabel(
                        thumbnail_frame,
                        image=ctk_img,
                        text=""
                    )
                    thumbnail_label.pack()
                   
                except Exception as e:
                    logger.error(f"Failed to load thumbnail: {e}")
                    # Show placeholder
                    placeholder = ctk.CTkLabel(
                        thumbnail_frame,
                        text="📺 Thumbnail not available",
                        font=ctk.CTkFont(size=14),
                        text_color=COLORS['text_secondary']
                    )
                    placeholder.pack()
           
            # Video info
            info_frame = ctk.CTkFrame(container, fg_color="transparent")
            info_frame.pack(fill="x", padx=20, pady=(0, 20))
           
            # Title
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
           
            # Details grid
            details = [
                ("👤 Channel", info.get('channel', 'Unknown')),
                ("⏱️ Duration", self.format_duration(info.get('duration', 0))),
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
           
            # Available formats
            formats = info.get('formats', [])
            if formats:
                format_frame = ctk.CTkFrame(container, fg_color="transparent")
                format_frame.pack(fill="x", padx=20, pady=(10, 20))
               
                ctk.CTkLabel(
                    format_frame,
                    text="Available Formats:",
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color=COLORS['text_primary']
                ).pack(anchor="w", pady=(0, 10))
               
                # Group formats by quality
                video_formats = []
                audio_formats = []
               
                for fmt in formats:
                    if fmt.get('vcodec') != 'none':
                        video_formats.append(fmt)
                    if fmt.get('acodec') != 'none':
                        audio_formats.append(fmt)
               
                # Show video formats
                if video_formats:
                    video_frame = ctk.CTkFrame(format_frame, fg_color="transparent")
                    video_frame.pack(fill="x", pady=(0, 10))
                   
                    ctk.CTkLabel(
                        video_frame,
                        text="Video:",
                        font=ctk.CTkFont(size=12, weight="bold"),
                        text_color=COLORS['text_secondary']
                    ).pack(anchor="w")
                   
                    # Get unique resolutions
                    resolutions = set()
                    for fmt in video_formats:
                        height = fmt.get('height')
                        if height:
                            resolutions.add(height)
                   
                    resolutions = sorted(resolutions, reverse=True)
                    resolutions_text = ", ".join([f"{p}p" for p in resolutions[:5]])
                    if len(resolutions) > 5:
                        resolutions_text += f" and {len(resolutions)-5} more"
                   
                    ctk.CTkLabel(
                        video_frame,
                        text=resolutions_text,
                        font=ctk.CTkFont(size=12),
                        text_color=COLORS['text_primary']
                    ).pack(anchor="w")
               
                # Show audio formats
                if audio_formats:
                    audio_frame = ctk.CTkFrame(format_frame, fg_color="transparent")
                    audio_frame.pack(fill="x")
                   
                    ctk.CTkLabel(
                        audio_frame,
                        text="Audio:",
                        font=ctk.CTkFont(size=12, weight="bold"),
                        text_color=COLORS['text_secondary']
                    ).pack(anchor="w")
                   
                    # Get audio codecs
                    codecs = set()
                    for fmt in audio_formats:
                        acodec = fmt.get('acodec')
                        if acodec and acodec != 'none':
                            codecs.add(acodec.split('.')[0])
                   
                    codecs_text = ", ".join(sorted(codecs))
                    ctk.CTkLabel(
                        audio_frame,
                        text=codecs_text,
                        font=ctk.CTkFont(size=12),
                        text_color=COLORS['text_primary']
                    ).pack(anchor="w")
           
            # Cache the info
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
        """Add current video to download queue"""
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Warning", "Please enter a YouTube URL")
            return
       
        # Get video info from cache or fetch
        if url in self.video_cache:
            info = self.video_cache[url]
            title = info.get('title', 'Unknown Video')
        else:
            # Fetch quickly
            try:
                with YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                    info = ydl.extract_info(url, download=False)
                    title = info.get('title', 'Unknown Video')
            except:
                title = "Unknown Video"
       
        # Get format type
        format_type = self.format_var.get()
       
        # Add to queue using new method
        task_id = self.download_manager.add_task(
            url=url,
            format_type=format_type,
            quality=self.quality_combo.get(),
            output_path=self.path_var.get(),
            title=title,
            include_subtitles=self.subtitles_var.get(),
            embed_metadata=self.metadata_var.get()
        )
       
        # Show success message
        self.status_message.set(f"Added to queue: {title[:50]}...")
       
        # Refresh queue display
        self.refresh_task_list()
       
        # Switch to queue tab
        self.tab_view.set("📋 Queue")
   
    def refresh_task_list(self):
        """Refresh the download queue display"""
        # Clear current display
        for widget in self.queue_scroll.winfo_children():
            widget.destroy()
       
        # Get all active and queued tasks
        tasks = list(self.download_manager.active_tasks.values()) + list(self.download_manager.task_queue)
       
        if not tasks:
            # Show empty message
            empty_label = ctk.CTkLabel(
                self.queue_scroll,
                text="Queue is empty",
                font=ctk.CTkFont(size=16),
                text_color=COLORS['text_secondary']
            )
            empty_label.pack(pady=50)
            return
       
        # Sort tasks: downloading first, then queued, then paused
        status_order = {
            DownloadStatus.DOWNLOADING: 0,
            DownloadStatus.PROCESSING: 1,
            DownloadStatus.MERGING: 2,
            DownloadStatus.QUEUED: 3,
            DownloadStatus.PAUSED: 4,
            DownloadStatus.ERROR: 5
        }
        tasks.sort(key=lambda x: status_order.get(x.status, 999))
       
        # Create task cards
        for task in tasks:
            self.create_task_card(task)
   
    def create_task_card(self, task: DownloadTask):
        """Create a task card for display"""
        card = ctk.CTkFrame(
            self.queue_scroll,
            fg_color=COLORS['dark_card'],
            border_width=1,
            border_color=COLORS['dark_gray'],
            corner_radius=10
        )
        card.pack(fill="x", pady=5, padx=5)
       
        # Status color
        status_colors = {
            DownloadStatus.DOWNLOADING: COLORS['info'],
            DownloadStatus.PROCESSING: COLORS['secondary'],
            DownloadStatus.MERGING: COLORS['secondary'],
            DownloadStatus.QUEUED: COLORS['gray'],
            DownloadStatus.PAUSED: COLORS['warning'],
            DownloadStatus.ERROR: COLORS['error'],
            DownloadStatus.COMPLETED: COLORS['success']
        }
       
        # Card header
        header_frame = ctk.CTkFrame(card, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(15, 5))
       
        # Status indicator
        status_indicator = ctk.CTkFrame(
            header_frame,
            width=10,
            height=10,
            fg_color=status_colors.get(task.status, COLORS['gray']),
            corner_radius=5
        )
        status_indicator.pack(side="left")
       
        # Title
        title_text = task.title if len(task.title) <= 50 else task.title[:47] + "..."
        title_label = ctk.CTkLabel(
            header_frame,
            text=title_text,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS['text_primary'],
            wraplength=600
        )
        title_label.pack(side="left", padx=10)
       
        # Status label
        status_label = ctk.CTkLabel(
            header_frame,
            text=task.status.value.upper(),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=status_colors.get(task.status, COLORS['gray'])
        )
        status_label.pack(side="right")
       
        # Progress bar
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
       
        # Progress info
        info_frame = ctk.CTkFrame(card, fg_color="transparent")
        info_frame.pack(fill="x", padx=15, pady=(0, 10))
       
        # Format and quality
        format_label = ctk.CTkLabel(
            info_frame,
            text=f"{task.format_type.upper()} • {task.quality}",
            font=ctk.CTkFont(size=11),
            text_color=COLORS['text_secondary']
        )
        format_label.pack(side="left")
       
        # Progress text
        progress_text = self.get_progress_text(task)
        progress_label = ctk.CTkLabel(
            info_frame,
            text=progress_text,
            font=ctk.CTkFont(size=11),
            text_color=COLORS['text_secondary']
        )
        progress_label.pack(side="right")
       
        # Control buttons
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
           
            # Cancel button
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
   
    def get_progress_text(self, task: DownloadTask) -> str:
        """Get formatted progress text for a task"""
        if task.status == DownloadStatus.COMPLETED:
            if task.file_path:
                size = os.path.getsize(task.file_path) if os.path.exists(task.file_path) else task.total_bytes
                return f"Completed • {self.format_size(size)}"
            return "Completed"
       
        elif task.status == DownloadStatus.DOWNLOADING:
            downloaded = self.format_size(task.downloaded_bytes)
            total = self.format_size(task.total_bytes) if task.total_bytes > 0 else "??"
            speed = self.format_size(task.speed) if task.speed > 0 else "0"
            eta = self.format_time(task.eta) if task.eta else "??"
           
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
        """Start a specific task"""
        success = self.download_manager.start_task(task_id)
        if success:
            self.status_message.set("Task started")
            self.refresh_task_list()
   
    def pause_task(self, task_id: str):
        """Pause a specific task"""
        success = self.download_manager.pause_task(task_id)
        if success:
            self.status_message.set("Task paused")
            self.refresh_task_list()
   
    def resume_task(self, task_id: str):
        """Resume a specific task"""
        success = self.download_manager.resume_task(task_id)
        if success:
            self.status_message.set("Task resumed")
            self.refresh_task_list()
   
    def cancel_task(self, task_id: str):
        """Cancel a specific task"""
        if messagebox.askyesno("Confirm", "Are you sure you want to cancel this download?"):
            success = self.download_manager.cancel_task(task_id)
            if success:
                self.status_message.set("Task cancelled")
                self.refresh_task_list()
   
    def retry_task(self, task_id: str):
        """Retry a failed task"""
        task = self.download_manager.get_task(task_id)
        if task and task.status == DownloadStatus.ERROR:
            # Reset task status
            task.status = DownloadStatus.QUEUED
            task.progress = 0
            task.error = None
           
            # Add to queue
            self.download_manager.task_queue.append(task)
            self.download_manager.save_state()
           
            # Refresh and start
            self.refresh_task_list()
            self.download_manager._auto_start_downloads()
           
            self.status_message.set("Task retrying...")
   
    def start_all_downloads(self):
        """Start all queued downloads"""
        # Start downloads until max concurrent reached
        self.download_manager._auto_start_downloads()
        self.refresh_task_list()
        self.status_message.set("Starting all downloads...")
   
    def pause_all_downloads(self):
        """Pause all active downloads"""
        # Pause all active tasks
        for task_id in list(self.download_manager.active_tasks.keys()):
            self.download_manager.pause_task(task_id)
       
        self.refresh_task_list()
        self.status_message.set("All downloads paused")
   
    def clear_queue(self):
        """Clear the download queue"""
        if messagebox.askyesno("Confirm", "Clear all queued and paused downloads?"):
            # Cancel all active
            for task_id in list(self.download_manager.active_tasks.keys()):
                self.download_manager.cancel_task(task_id)
           
            # Clear queue
            for task in list(self.download_manager.task_queue):
                task.status = DownloadStatus.CANCELLED
                self.download_manager.task_history.append(task)
           
            self.download_manager.task_queue.clear()
            self.download_manager.save_state()
           
            self.refresh_task_list()
            self.status_message.set("Queue cleared")
   
    def refresh_history(self):
        """Refresh download history display"""
        # Clear current items
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
       
        # Get history tasks
        history_tasks = self.download_manager.task_history[-100:] # Last 100
       
        # Add to treeview
        for task in reversed(history_tasks): # Show newest first
            # Format values
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
           
            # Format date
            if task.completed_at:
                date_str = datetime.fromtimestamp(task.completed_at).strftime('%Y-%m-%d %H:%M')
            else:
                date_str = datetime.fromtimestamp(task.created_at).strftime('%Y-%m-%d %H:%M')
           
            # Get file size
            size_str = ""
            if task.file_path and os.path.exists(task.file_path):
                size = os.path.getsize(task.file_path)
                size_str = self.format_size(size)
            elif task.total_bytes > 0:
                size_str = self.format_size(task.total_bytes)
           
            # Insert into tree
            self.history_tree.insert(
                "",
                "end",
                text=task.title[:80] + "..." if len(task.title) > 80 else task.title,
                values=(
                    status_text,
                    task.format_type,
                    task.quality,
                    size_str,
                    date_str
                ),
                tags=tuple(tags) if tags else ()
            )
   
    def clear_history(self):
        """Clear download history"""
        if messagebox.askyesno("Confirm", "Clear all download history?"):
            self.download_manager.clear_completed()
            self.refresh_history()
            self.status_message.set("History cleared")
   
    def browse_path(self):
        """Browse for download path"""
        directory = filedialog.askdirectory()
        if directory:
            self.path_var.set(directory)
   
    def open_download_folder(self):
        """Open download folder in file explorer"""
        path = self.path_var.get()
        if os.path.exists(path):
            try:
                if platform.system() == "Windows":
                    os.startfile(path)
                elif platform.system() == "Darwin": # macOS
                    subprocess.run(["open", path])
                else: # Linux
                    subprocess.run(["xdg-open", path])
            except Exception as e:
                messagebox.showerror("Error", f"Failed to open folder: {e}")
        else:
            messagebox.showerror("Error", f"Folder does not exist: {path}")
   
    def fetch_playlist_info(self):
        """Fetch playlist information"""
        url = self.playlist_url_entry.get().strip()
        if not url:
            messagebox.showwarning("Warning", "Please enter a playlist URL")
            return
       
        # Clear info frame
        for widget in self.playlist_info_frame.winfo_children():
            widget.destroy()
       
        # Show loading
        loading_label = ctk.CTkLabel(
            self.playlist_info_frame,
            text="Fetching playlist information...",
            font=ctk.CTkFont(size=16),
            text_color=COLORS['text_secondary']
        )
        loading_label.place(relx=0.5, rely=0.5, anchor="center")
       
        # Fetch in thread
        threading.Thread(target=self._fetch_playlist_info_thread, args=(url,), daemon=True).start()
   
    def _fetch_playlist_info_thread(self, url):
        """Thread for fetching playlist info"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'force_generic_extractor': False,
            }
           
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
               
                # Update UI in main thread
                self.root.after(0, lambda: self.display_playlist_info(info))
               
        except Exception as e:
            error_msg = str(e)
            self.root.after(0, lambda: self.show_error("Failed to fetch playlist info", error_msg))
   
    def display_playlist_info(self, info):
        """Display playlist information"""
        # Clear info frame
        for widget in self.playlist_info_frame.winfo_children():
            widget.destroy()
       
        # Create scrollable container
        container = ctk.CTkScrollableFrame(
            self.playlist_info_frame,
            fg_color=COLORS['dark_card'],
            scrollbar_button_color=COLORS['dark_gray'],
            scrollbar_button_hover_color=COLORS['gray']
        )
        container.pack(fill="both", expand=True)
       
        try:
            # Playlist title
            title = info.get('title', 'Unknown Playlist')
            title_label = ctk.CTkLabel(
                container,
                text=title,
                font=ctk.CTkFont(size=20, weight="bold"),
                text_color=COLORS['text_primary'],
                wraplength=800
            )
            title_label.pack(anchor="w", padx=20, pady=(20, 10))
           
            # Playlist details
            details_frame = ctk.CTkFrame(container, fg_color="transparent")
            details_frame.pack(fill="x", padx=20, pady=(0, 20))
           
            # Channel
            channel = info.get('channel', 'Unknown Channel')
            channel_label = ctk.CTkLabel(
                details_frame,
                text=f"👤 {channel}",
                font=ctk.CTkFont(size=14),
                text_color=COLORS['text_primary']
            )
            channel_label.pack(anchor="w")
           
            # Video count
            entries = info.get('entries', [])
            video_count = len(entries) if entries else info.get('playlist_count', 0)
            count_label = ctk.CTkLabel(
                details_frame,
                text=f"📹 {video_count} videos",
                font=ctk.CTkFont(size=14),
                text_color=COLORS['text_primary']
            )
            count_label.pack(anchor="w", pady=(5, 0))
           
            # Download options
            options_frame = ctk.CTkFrame(container, fg_color="transparent")
            options_frame.pack(fill="x", padx=20, pady=(0, 20))
           
            ctk.CTkLabel(
                options_frame,
                text="Download Options:",
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color=COLORS['text_primary']
            ).pack(anchor="w", pady=(0, 10))
           
            # Format selection for playlist
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
           
            # Quality selection
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
           
            # Download button
            def download_playlist():
                if not entries:
                    messagebox.showwarning("Warning", "No videos found in playlist")
                    return
               
                # Ask for confirmation
                if not messagebox.askyesno("Confirm", f"Download {video_count} videos from playlist?"):
                    return
               
                # Add each video to queue
                added_count = 0
                for entry in entries:
                    if isinstance(entry, dict) and 'url' in entry:
                        video_url = entry.get('url')
                        video_title = entry.get('title', 'Unknown Video')
                       
                        task_id = self.download_manager.add_task(
                            url=video_url,
                            format_type=format_var.get(),
                            quality=quality_combo.get(),
                            output_path=self.path_var.get(),
                            title=video_title,
                            include_subtitles=self.subtitles_var.get(),
                            embed_metadata=self.metadata_var.get()
                        )
                       
                        if task_id:
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
           
            # Video list
            if entries:
                list_frame = ctk.CTkFrame(container, fg_color="transparent")
                list_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))
               
                ctk.CTkLabel(
                    list_frame,
                    text="Videos in playlist:",
                    font=ctk.CTkFont(size=16, weight="bold"),
                    text_color=COLORS['text_primary']
                ).pack(anchor="w", pady=(0, 10))
               
                # Create scrollable list
                video_list = ctk.CTkScrollableFrame(
                    list_frame,
                    fg_color=COLORS['dark_bg'],
                    height=300,
                    scrollbar_button_color=COLORS['dark_gray'],
                    scrollbar_button_hover_color=COLORS['gray']
                )
                video_list.pack(fill="both", expand=True)
               
                # Add videos
                for i, entry in enumerate(entries[:50], 1): # Show first 50
                    if isinstance(entry, dict):
                        video_frame = ctk.CTkFrame(video_list, fg_color="transparent")
                        video_frame.pack(fill="x", pady=2)
                       
                        # Number
                        num_label = ctk.CTkLabel(
                            video_frame,
                            text=f"{i}.",
                            font=ctk.CTkFont(size=12),
                            text_color=COLORS['text_secondary'],
                            width=30
                        )
                        num_label.pack(side="left")
                       
                        # Title
                        title = entry.get('title', 'Unknown Title')
                        if len(title) > 60:
                            title = title[:57] + "..."
                       
                        title_label = ctk.CTkLabel(
                            video_frame,
                            text=title,
                            font=ctk.CTkFont(size=12),
                            text_color=COLORS['text_primary'],
                            wraplength=600
                        )
                        title_label.pack(side="left", padx=5)
                       
                        # Duration
                        duration = entry.get('duration', 0)
                        if duration:
                            duration_label = ctk.CTkLabel(
                                video_frame,
                                text=self.format_duration(duration),
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
        """Handle double-click on history item"""
        item = self.history_tree.selection()[0]
        values = self.history_tree.item(item)
       
        # Get the title from the tree item
        title = values.get('text', '')
       
        # Find the task in history
        for task in self.download_manager.task_history:
            if task.title.startswith(title[:50]): # Match by title prefix
                if task.file_path and os.path.exists(task.file_path):
                    # Open file location
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
        """Handle tab change event"""
        current_tab = self.tab_view.get()
       
        if current_tab == "📋 Queue":
            self.refresh_task_list()
        elif current_tab == "📊 History":
            self.refresh_history()
   
    def toggle_theme(self):
        """Toggle between dark and light themes"""
        if self.current_theme == "dark":
            ctk.set_appearance_mode("light")
            self.current_theme = "light"
            # Update colors for light mode
            global COLORS
            COLORS = {
                'primary': '#FF3B30',
                'secondary': '#5856D6',
                'dark_bg': '#F2F2F7',
                'dark_card': '#FFFFFF',
                'dark_text': '#000000',
                'light_bg': '#F2F2F7',
                'light_card': '#FFFFFF',
                'light_text': '#000000',
                'success': '#34C759',
                'warning': '#FF9500',
                'error': '#FF3B30',
                'info': '#007AFF',
                'gray': '#8E8E93',
                'dark_gray': '#C7C7CC',
                'text_primary': '#000000',
                'text_secondary': '#8E8E93',
                'text_disabled': '#C7C7CC',
            }
        else:
            ctk.set_appearance_mode("dark")
            self.current_theme = "dark"
            # Reset to dark colors
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
       
        # Recreate UI with new theme
        self.status_message.set(f"Switched to {self.current_theme} theme")
        # Note: In a full implementation, you would update all widget colors here
        # For simplicity, we're just changing the appearance mode
   
    def open_settings(self):
        """Open settings dialog"""
        settings_window = ctk.CTkToplevel(self.root)
        settings_window.title("Settings")
        settings_window.geometry("600x500")
        settings_window.transient(self.root)
        settings_window.grab_set()
       
        # Set colors for settings window
        settings_window.configure(fg_color=COLORS['dark_bg'])
       
        # Center the window
        settings_window.update_idletasks()
        width = settings_window.winfo_width()
        height = settings_window.winfo_height()
        x = (settings_window.winfo_screenwidth() // 2) - (width // 2)
        y = (settings_window.winfo_screenheight() // 2) - (height // 2)
        settings_window.geometry(f"{width}x{height}+{x}+{y}")
       
        # Settings content
        container = ctk.CTkScrollableFrame(
            settings_window,
            fg_color=COLORS['dark_bg'],
            scrollbar_button_color=COLORS['dark_gray'],
            scrollbar_button_hover_color=COLORS['gray']
        )
        container.pack(fill="both", expand=True, padx=20, pady=20)
       
        # Title
        title_label = ctk.CTkLabel(
            container,
            text="Settings",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=COLORS['text_primary']
        )
        title_label.pack(anchor="w", pady=(0, 20))
       
        # Concurrent downloads
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
            command=lambda v: self.update_concurrent_downloads(int(float(v))),
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
       
        # Default download path
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
       
        # Save button
        def save_settings():
            # Update concurrent downloads
            self.download_manager.max_concurrent = concurrent_var.get()
           
            # Update default path
            self.settings['default_path'] = default_path_var.get()
            self.path_var.set(default_path_var.get())
           
            # Save settings
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
   
    def update_concurrent_downloads(self, value):
        """Update maximum concurrent downloads"""
        self.download_manager.max_concurrent = value
   
    def show_error(self, title, message):
        """Show error message"""
        messagebox.showerror(title, message)
        self.status_message.set(f"Error: {title}")
   
    def format_size(self, bytes_num):
        """Format bytes to human readable size"""
        if bytes_num <= 0:
            return "0 B"
       
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        i = 0
        while bytes_num >= 1024 and i < len(units) - 1:
            bytes_num /= 1024
            i += 1
       
        return f"{bytes_num:.2f} {units[i]}"
   
    def format_duration(self, seconds):
        """Format seconds to human readable duration"""
        if seconds <= 0:
            return "0:00"
       
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
       
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"
   
    def format_time(self, seconds):
        """Format seconds to human readable time (for ETA)"""
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
        """Load application settings"""
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
                    # Merge with defaults
                    for key in default_settings:
                        if key not in loaded_settings:
                            loaded_settings[key] = default_settings[key]
                    return loaded_settings
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")
       
        return default_settings
   
    def save_settings(self):
        """Save application settings"""
        try:
            with open('settings.json', 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")

    def update_timer(self):
        """Update timer for UI refreshes"""
        # Refresh task list periodically
        if self.current_tab == "📋 Queue":
            self.refresh_task_list()
       
        # Update stats
        self.update_stats()
       
        # Schedule next update
        self.root.after(1000, self.update_timer)
   
    def update_stats(self):
        """Update statistics display"""
        total_downloads = len(self.download_manager.task_history)
        total_size = 0
       
        # Calculate total size from completed downloads
        for task in self.download_manager.task_history:
            if task.status == DownloadStatus.COMPLETED and task.file_path:
                if os.path.exists(task.file_path):
                    total_size += os.path.getsize(task.file_path)
       
        active_downloads = len(self.download_manager.active_tasks)
       
        # Update stats label
        stats_text = f"📊 Downloads: {total_downloads} | 📁 Size: {self.format_size(total_size)} | ⚡ Active: {active_downloads}"
        self.stats_label.configure(text=stats_text)
       
        # Store for later use
        self.total_downloads = total_downloads
        self.total_size = total_size
        self.active_downloads = active_downloads
   
    def on_closing(self):
        """Handle application closing"""
        # Save state
        self.download_manager.save_state()
        self.save_settings()
       
        # Close application
        self.root.destroy()


def main():
    """Main entry point"""
    # Create root window
    root = ctk.CTk()
   
    # Set window icon (if available)
    try:
        root.iconbitmap("icon.ico")  # Windows
    except:
        pass
   
    # Create application
    app = YouTubeDownloaderPro(root)
   
    # Start main loop
    root.mainloop()


if __name__ == "__main__":
    main()