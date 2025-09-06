import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
import json
import time
from pathlib import Path
import customtkinter as ctk
from PIL import Image, ImageTk
import requests
from io import BytesIO
from collections import deque
import re
from urllib.parse import urlparse, parse_qs
from yt_dlp import YoutubeDL
import shutil
import vlc

# Global download manager
class DownloadManager:
    def __init__(self):
        self.active_downloads = {}
        self.download_queue = deque()
        self.download_history = []
        self.load_state()
        
    def save_state(self):
        state = {
            'queue': list(self.download_queue),
            'history': self.download_history[-50:]  # Keep last 50 items
        }
        with open('download_state.json', 'w') as f:
            json.dump(state, f)
    
    def load_state(self):
        try:
            with open('download_state.json', 'r') as f:
                state = json.load(f)
                self.download_queue = deque(state.get('queue', []))
                self.download_history = state.get('history', [])
        except FileNotFoundError:
            pass
    
    def add_download(self, url, options, title=None):
        download_id = f"{url}_{time.time()}"
        self.download_queue.append({
            'id': download_id,
            'url': url,
            'options': options,
            'status': 'queued',
            'progress': 0,
            'title': title
        })
        self.save_state()
        return download_id
    
    def start_download(self, download_id):
        for item in list(self.download_queue):
            if item['id'] == download_id:
                item['status'] = 'downloading'
                self.active_downloads[download_id] = item
                self.download_queue.remove(item)
                self.save_state()
                return item
        return None
    
    def pause_download(self, download_id):
        if download_id in self.active_downloads:
            self.active_downloads[download_id]['status'] = 'paused'
            self.download_queue.appendleft(self.active_downloads[download_id])
            del self.active_downloads[download_id]
            self.save_state()
            return True
        return False
    
    def resume_download(self, download_id):
        for item in list(self.download_queue):
            if item['id'] == download_id and item['status'] == 'paused':
                item['status'] = 'queued'
                self.save_state()
                return self.start_download(download_id)
        return None
    
    def complete_download(self, download_id, file_path):
        if download_id in self.active_downloads:
            item = self.active_downloads[download_id]
            item['status'] = 'completed'
            item['file_path'] = file_path
            item['completed_at'] = time.time()
            self.download_history.append(item)
            del self.active_downloads[download_id]
            self.save_state()
            return True
        return False
    
    def remove_download(self, download_id):
        if download_id in self.active_downloads:
            del self.active_downloads[download_id]
            self.save_state()
            return True
        for item in list(self.download_queue):
            if item['id'] == download_id:
                self.download_queue.remove(item)
                self.save_state()
                return True
        return False

# Global download manager instance
download_manager = DownloadManager()

class YouTubeDownloader:
    def __init__(self, root):
        self.root = root
        self.root.title("Advanced YouTube Downloader")
        self.root.geometry("900x750")
        self.root.resizable(True, True)
        
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")
        
        self.download_frames = {}
        self.status_labels = {}
        self.progress_bars = {}
        self.progress_labels = {}
        self.control_buttons = {}
        self.vlc_instance = vlc.Instance()
        self.player = None
        self.is_playing = False
        self.loading_label = None
        self.loading_frames = []
        self.current_frame = 0
        self.animation_running = False
        
        self.setup_ui()
        self.update_download_list()
        
    def setup_ui(self):
        self.tab_view = ctk.CTkTabview(self.root)
        self.tab_view.configure(fg_color="#000000", text_color="#FFFFFF")
        self.tab_view.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.download_tab = self.tab_view.add("Download")
        self.queue_tab = self.tab_view.add("Download Queue")
        self.history_tab = self.tab_view.add("History")
        
        self.setup_download_tab()
        self.setup_queue_tab()
        self.setup_history_tab()
        
    def setup_download_tab(self):
        main_frame = ctk.CTkFrame(self.download_tab)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        title_label = ctk.CTkLabel(main_frame, text="YouTube Downloader", 
                                  font=ctk.CTkFont(size=20, weight="bold"))
        title_label.pack(pady=20)
        
        url_frame = ctk.CTkFrame(main_frame)
        url_frame.pack(fill="x", padx=20, pady=10)
        
        ctk.CTkLabel(url_frame, text="YouTube URL:").pack(anchor="w")
        self.url_entry = ctk.CTkEntry(url_frame, placeholder_text="Enter YouTube video URL", height=40)
        self.url_entry.pack(fill="x", pady=5)
        self.url_entry.bind("<Return>", lambda e: self.preview_video())
        
        self.preview_frame = ctk.CTkFrame(main_frame)
        self.preview_frame.pack(fill="x", padx=20, pady=10)
        
        options_frame = ctk.CTkFrame(main_frame)
        options_frame.pack(fill="x", padx=20, pady=10)
        
        ctk.CTkLabel(options_frame, text="Download Options:").pack(anchor="w")
        
        format_frame = ctk.CTkFrame(options_frame)
        format_frame.pack(fill="x", pady=5)
        
        self.format_var = ctk.StringVar(value="video")
        ctk.CTkRadioButton(format_frame, text="Video (MP4)", variable=self.format_var, 
                          value="video").pack(side="left", padx=10)
        ctk.CTkRadioButton(format_frame, text="Audio (MP3)", variable=self.format_var, 
                          value="audio").pack(side="left", padx=10)
        
        quality_frame = ctk.CTkFrame(options_frame)
        quality_frame.pack(fill="x", pady=5)
        
        ctk.CTkLabel(quality_frame, text="Quality:").pack(side="left")
        self.quality_var = ctk.StringVar(value="highest")
        quality_combo = ctk.CTkComboBox(quality_frame, variable=self.quality_var,
                                       values=["highest", "2160p", "1440p", "1080p", "720p", "480p", "360p", "lowest"])
        quality_combo.pack(side="left", padx=10)
        
        location_frame = ctk.CTkFrame(options_frame)
        location_frame.pack(fill="x", pady=5)
        
        ctk.CTkLabel(location_frame, text="Download Location:").pack(anchor="w")
        
        loc_subframe = ctk.CTkFrame(location_frame)
        loc_subframe.pack(fill="x", pady=5)
        
        self.location_var = ctk.StringVar(value=os.path.expanduser("~/Downloads"))
        self.location_entry = ctk.CTkEntry(loc_subframe, textvariable=self.location_var)
        self.location_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        ctk.CTkButton(loc_subframe, text="Browse", width=80, fg_color="#FF9866", 
                      hover_color="#FFAB80", text_color="#000000", font=ctk.CTkFont(weight="bold")).pack(side="right")
        
        buttons_frame = ctk.CTkFrame(main_frame)
        buttons_frame.pack(fill="x", padx=20, pady=20)
        
        self.download_btn = ctk.CTkButton(buttons_frame, text="Add to Queue", 
                                         command=self.add_to_queue, height=40, fg_color="#FF9866", 
                                         hover_color="#FFAB80", text_color="#000000", font=ctk.CTkFont(weight="bold"))
        self.download_btn.pack(side="left", padx=10)
        
        self.preview_btn = ctk.CTkButton(buttons_frame, text="Preview", 
                                        command=self.preview_video, height=40, fg_color="#FF9866", 
                                        hover_color="#FFAB80", text_color="#000000", font=ctk.CTkFont(weight="bold"))
        self.preview_btn.pack(side="left", padx=10)
        
        self.status_label = ctk.CTkLabel(main_frame, text="Ready")
        self.status_label.pack(pady=10)
        
    def setup_queue_tab(self):
        queue_frame = ctk.CTkFrame(self.queue_tab)
        queue_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        title_label = ctk.CTkLabel(queue_frame, text="Download Queue", 
                                  font=ctk.CTkFont(size=16, weight="bold"))
        title_label.pack(pady=10)
        
        self.queue_scroll = ctk.CTkScrollableFrame(queue_frame)
        self.queue_scroll.pack(fill="both", expand=True, pady=10)
        
        control_frame = ctk.CTkFrame(queue_frame)
        control_frame.pack(fill="x", pady=10)
        
        ctk.CTkButton(control_frame, text="Start All", command=self.start_all_downloads, 
                      fg_color="#FF9866", hover_color="#FFAB80", text_color="#000000", 
                      font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)
        ctk.CTkButton(control_frame, text="Pause All", command=self.pause_all_downloads, 
                      fg_color="#FF9866", hover_color="#FFAB80", text_color="#000000", 
                      font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)
        ctk.CTkButton(control_frame, text="Clear Completed", command=self.clear_completed, 
                      fg_color="#FF9866", hover_color="#FFAB80", text_color="#000000", 
                      font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)
        
    def setup_history_tab(self):
        history_frame = ctk.CTkFrame(self.history_tab)
        history_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        title_label = ctk.CTkLabel(history_frame, text="Download History", 
                                  font=ctk.CTkFont(size=16, weight="bold"))
        title_label.pack(pady=10)
        
        tree_frame = ctk.CTkFrame(history_frame)
        tree_frame.pack(fill="both", expand=True, pady=10)
        
        tree_scroll = ttk.Scrollbar(tree_frame)
        tree_scroll.pack(side="right", fill="y")
        
        self.history_tree = ttk.Treeview(tree_frame, columns=("format", "date"), 
                                        show="headings", height=15, yscrollcommand=tree_scroll.set)
        tree_scroll.config(command=self.history_tree.yview)
        
        self.history_tree.heading("#0", text="Title")
        self.history_tree.heading("format", text="Format")
        self.history_tree.heading("date", text="Date")
        
        self.history_tree.column("#0", width=400)
        self.history_tree.column("format", width=100)
        self.history_tree.column("date", width=150)
        
        self.history_tree.pack(fill="both", expand=True)
        
        control_frame = ctk.CTkFrame(history_frame)
        control_frame.pack(fill="x", pady=10)
        
        ctk.CTkButton(control_frame, text="Clear History", command=self.clear_history, 
                      fg_color="#FF9866", hover_color="#FFAB80", text_color="#000000", 
                      font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)
        ctk.CTkButton(control_frame, text="Open Download Folder", command=self.open_download_folder, 
                      fg_color="#FF9866", hover_color="#FFAB80", text_color="#000000", 
                      font=ctk.CTkFont(weight="bold")).pack(side="right", padx=5)
    
    def load_animation(self):
        try:
            gif_path = os.path.join(os.path.dirname(__file__), "loading.gif")
            gif = Image.open(gif_path)
            self.loading_frames = []
            try:
                while True:
                    frame = gif.copy()
                    frame = frame.resize((64, 64), Image.Resampling.LANCZOS)
                    self.loading_frames.append(ImageTk.PhotoImage(frame))
                    gif.seek(len(self.loading_frames))
            except EOFError:
                pass
        except FileNotFoundError:
            print("Loading GIF not found. Please ensure 'loading.gif' is in the project directory.")
            self.loading_frames = []
    
    def start_loading_animation(self):
        if self.loading_frames and not self.animation_running:
            self.animation_running = True
            self.loading_label = ctk.CTkLabel(self.video_frame, image=self.loading_frames[0], text="")
            self.loading_label.place(relx=0.5, rely=0.5, anchor="center")
            self.animate_loading()
    
    def animate_loading(self):
        if self.animation_running and self.loading_frames:
            self.current_frame = (self.current_frame + 1) % len(self.loading_frames)
            self.loading_label.configure(image=self.loading_frames[self.current_frame])
            self.root.after(100, self.animate_loading)
    
    def stop_loading_animation(self):
        self.animation_running = False
        if self.loading_label:
            self.loading_label.destroy()
            self.loading_label = None
    
    def browse_location(self):
        directory = filedialog.askdirectory()
        if directory:
            self.location_var.set(directory)
    
    def clean_youtube_url(self, url):
        try:
            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            video_id = query_params.get('v', [None])[0]
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"
            if parsed_url.netloc == 'youtu.be':
                video_id = parsed_url.path[1:]
                return f"https://www.youtube.com/watch?v={video_id}"
            return url
        except Exception as e:
            print(f"Error cleaning URL: {e}")
            return url
    
    def get_video_info(self, url):
        try:
            clean_url = self.clean_youtube_url(url)
            video_id = self.extract_video_id(clean_url)
            if not video_id:
                raise ValueError("Invalid YouTube URL")
            ydl_opts = {
                'noplaylist': True,
                'quiet': True,
            }
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(clean_url, download=False)
            class VideoInfo:
                def __init__(self, info):
                    self.title = info.get('title', 'Unknown Title')
                    self.length = int(info.get('duration', 0))
                    self.views = int(info.get('view_count', 0))
            yt = VideoInfo(info)
            return yt, video_id
        except Exception as e:
            messagebox.showerror("Error", f"Failed to get video info: {str(e)}")
            return None, None
    
    def extract_video_id(self, url):
        patterns = [
            r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
            r'(?:embed\/)([0-9A-Za-z_-]{11})',
            r'(?:shorts\/)([0-9A-Za-z_-]{11})',
            r'youtu\.be\/([0-9A-Za-z_-]{11})'
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    
    def preview_video(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a YouTube URL")
            return
        yt, video_id = self.get_video_info(url)
        if yt and video_id:
            self.update_preview(yt, video_id, url)
            self.start_loading_animation()
    
    def update_preview(self, yt, video_id, url):
        for widget in self.preview_frame.winfo_children():
            widget.destroy()
        try:
            thumbnail_options = [
                f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
                f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
                f"https://i.ytimg.com/vi/{video_id}/default.jpg"
            ]
            img_data = None
            for thumb_url in thumbnail_options:
                try:
                    response = requests.get(thumb_url, timeout=10)
                    if response.status_code == 200:
                        img_data = response.content
                        break
                except:
                    continue
            if not img_data:
                raise Exception("Could not retrieve thumbnail")
            img = Image.open(BytesIO(img_data))
            img = img.resize((160, 90), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            preview_container = ctk.CTkFrame(self.preview_frame)
            preview_container.pack(fill="x", pady=5)
            thumbnail_label = ctk.CTkLabel(preview_container, image=photo, text="")
            thumbnail_label.image = photo
            thumbnail_label.pack(side="left", padx=10)
            info_frame = ctk.CTkFrame(preview_container)
            info_frame.pack(side="left", fill="both", expand=True, padx=10)
            title = yt.title
            if len(title) > 50:
                title = title[:47] + "..."
            ctk.CTkLabel(info_frame, text=title, 
                        font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=2)
            ctk.CTkLabel(info_frame, text=f"Duration: {yt.length//60}:{yt.length%60:02d}").pack(anchor="w", pady=2)
            ctk.CTkLabel(info_frame, text=f"Views: {yt.views:,}").pack(anchor="w", pady=2)
            
            # Add Play Video button
            play_button = ctk.CTkButton(info_frame, text="Play Video", 
                                      command=lambda: self.play_video(url), 
                                      fg_color="#FF9866", hover_color="#FFAB80", text_color="#000000", 
                                      font=ctk.CTkFont(weight="bold"))
            play_button.pack(anchor="w", pady=5)
            
            # Video streaming frame
            video_container = ctk.CTkFrame(preview_container)
            video_container.pack(side="right", padx=10)
            self.video_frame = ctk.CTkFrame(video_container, width=320, height=180)
            self.video_frame.pack(pady=5)
            
            # Player control buttons (icon-only, centered, black with white icons, larger size)
            control_frame = ctk.CTkFrame(video_container)
            control_frame.pack(fill="x", pady=5)
            center_frame = ctk.CTkFrame(control_frame)
            center_frame.pack(fill="x", expand=True)
            self.play_pause_btn = ctk.CTkButton(center_frame, text="▶", command=self.toggle_play_pause, 
                                               width=50, height=50, fg_color="#000000", hover_color="#333333", 
                                               text_color="#FFFFFF", font=ctk.CTkFont(size=20))
            self.play_pause_btn.pack(side="left", padx=10)
            ctk.CTkButton(center_frame, text="⏹", command=self.stop_video, 
                          width=50, height=50, fg_color="#000000", hover_color="#333333", 
                          text_color="#FFFFFF", font=ctk.CTkFont(size=20)).pack(side="left", padx=10)
            ctk.CTkButton(center_frame, text="⛶", command=self.toggle_fullscreen, 
                          width=50, height=50, fg_color="#000000", hover_color="#333333", 
                          text_color="#FFFFFF", font=ctk.CTkFont(size=20)).pack(side="left", padx=10)
            
            # Load animation frames
            self.load_animation()
            
        except Exception as e:
            error_label = ctk.CTkLabel(self.preview_frame, text=f"Preview unavailable: {str(e)}", text_color="red")
            error_label.pack(pady=10)
            print(f"Preview error: {e}")
            self.stop_loading_animation()
    
    def play_video(self, url):
        try:
            self.start_loading_animation()
            if self.player:
                self.player.stop()
            stream_url = self.get_stream_url(url)
            media = self.vlc_instance.media_new(stream_url)
            self.player = self.vlc_instance.media_player_new()
            self.player.set_media(media)
            self.player.set_hwnd(self.video_frame.winfo_id())  # Windows
            # For macOS/Linux, use set_xwindow instead of set_hwnd
            # if os.name != 'nt':
            #     self.player.set_xwindow(self.video_frame.winfo_id())
            
            # Set up event manager to detect when video starts playing
            event_manager = self.player.event_manager()
            event_manager.event_attach(vlc.EventType.MediaPlayerPlaying, 
                                    lambda event: self.root.after(0, self.stop_loading_animation))
            event_manager.event_attach(vlc.EventType.MediaPlayerEncounteredError, 
                                    lambda event: self.root.after(0, self.on_playback_error))
            
            self.player.play()
            self.is_playing = True
            self.play_pause_btn.configure(text="⏸")
        except Exception as e:
            self.stop_loading_animation()
            messagebox.showerror("Error", f"Failed to play video: {str(e)}")
    
    def on_playback_error(self):
        self.stop_loading_animation()
        messagebox.showerror("Error", "Failed to play video: Playback error")
    
    def toggle_play_pause(self):
        if self.player:
            if self.is_playing:
                self.player.pause()
                self.play_pause_btn.configure(text="▶")
                self.is_playing = False
            else:
                self.start_loading_animation()
                self.player.play()
                self.play_pause_btn.configure(text="⏸")
                self.is_playing = True
    
    def stop_video(self):
        if self.player:
            self.player.stop()
            self.is_playing = False
            self.play_pause_btn.configure(text="▶")
            self.stop_loading_animation()
    
    def toggle_fullscreen(self):
        if self.player:
            self.player.toggle_fullscreen()
    
    def get_stream_url(self, url):
        ydl_opts = {
            'format': 'best',
            'quiet': True
        }
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info['url']
    
    def add_to_queue(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a YouTube URL")
            return
        clean_url = self.clean_youtube_url(url)
        yt, video_id = self.get_video_info(clean_url)
        if not yt:
            return
        options = {
            'format': self.format_var.get(),
            'quality': self.quality_var.get(),
            'location': self.location_var.get()
        }
        download_id = download_manager.add_download(clean_url, options, title=yt.title)
        self.update_download_list()
        self.status_label.configure(text="Download added to queue!")
        if len(download_manager.active_downloads) < 3:
            self.start_download(download_id)
    
    def start_download(self, download_id):
        item = download_manager.start_download(download_id)
        if item:
            self.status_label.configure(text=f"Starting download: {item['url'][:30]}...")
            self.update_download_list()
            threading.Thread(target=self.process_download, args=(download_id,), daemon=True).start()
    
    def restart_download(self, download_id):
        if download_id in self.active_downloads:
            item = self.active_downloads[download_id]
            item['status'] = 'downloading'
            item['progress'] = 0
            item.pop('downloaded_bytes', None)
            item.pop('total_bytes', None)
            item.pop('speed', None)
            item.pop('eta', None)
            download_manager.save_state()
            threading.Thread(target=self.process_download, args=(download_id,), daemon=True).start()
            self.update_download_list()
    
    def update_download_list(self):
        current_ids = set(download_manager.active_downloads.keys()) | {item['id'] for item in download_manager.download_queue}
        
        for did in list(self.download_frames.keys()):
            if did not in current_ids:
                self.download_frames[did].destroy()
                del self.download_frames[did]
                del self.status_labels[did]
                del self.progress_bars[did]
                del self.progress_labels[did]
                del self.control_buttons[did]
        
        items = list(download_manager.active_downloads.values()) + list(download_manager.download_queue)
        
        for item in items:
            did = item['id']
            status = item['status']
            disp_title = item.get('title', item['url'][:40] + "..." if len(item['url']) > 40 else item['url'])
            progress = item.get('progress', 0)
            
            downloaded_mb = item.get('downloaded_bytes', 0) / (1024 * 1024)
            total_mb = item.get('total_bytes', 0) / (1024 * 1024)
            speed_kbps = item.get('speed', 0) / 1024 if item.get('speed') else 0
            eta = item.get('eta')
            
            progress_text = f"{progress}% {downloaded_mb:.2f}MB of {total_mb:.2f}MB" if total_mb > 0 else f"{progress}%"
            if speed_kbps > 0:
                progress_text += f" at {speed_kbps:.2f}KiB/s"
            if eta is not None:
                h = eta // 3600
                m = (eta % 3600) // 60
                s = eta % 60
                eta_str = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
                progress_text += f" in {eta_str}"
            
            if did not in self.download_frames:
                item_frame = ctk.CTkFrame(self.queue_scroll)
                item_frame.pack(fill="x", pady=5)
                
                title_label = ctk.CTkLabel(item_frame, text=disp_title, width=300, anchor="w")
                title_label.pack(side="left", padx=5)
                
                self.status_labels[did] = ctk.CTkLabel(item_frame, text=status, width=100)
                self.status_labels[did].pack(side="left", padx=5)
                
                progress_frame = ctk.CTkFrame(item_frame, width=300)
                progress_frame.pack(side="left", padx=5)
                
                self.progress_bars[did] = ctk.CTkProgressBar(progress_frame, width=250)
                self.progress_bars[did].pack(side="top")
                
                self.progress_labels[did] = ctk.CTkLabel(progress_frame, text=progress_text)
                self.progress_labels[did].pack(side="top")
                
                self.control_buttons[did] = ctk.CTkButton(item_frame, width=80, fg_color="#FF9866", 
                                                         hover_color="#FFAB80", text_color="#000000", 
                                                         font=ctk.CTkFont(weight="bold"))
                self.control_buttons[did].pack(side="left", padx=5)
                
                remove_btn = ctk.CTkButton(item_frame, text="Remove", width=80, 
                                           command=lambda d=did: (download_manager.remove_download(d), self.update_download_list()),
                                           fg_color="#FF9866", hover_color="#FFAB80", text_color="#000000", 
                                           font=ctk.CTkFont(weight="bold"))
                remove_btn.pack(side="left", padx=5)
                
                self.download_frames[did] = item_frame
            
            self.status_labels[did].configure(text=status)
            self.progress_bars[did].set(progress / 100)
            self.progress_labels[did].configure(text=progress_text)
            
            if status == 'downloading':
                self.control_buttons[did].configure(text="Pause", command=lambda d=did: (download_manager.pause_download(d), self.update_download_list()))
            elif status == 'queued':
                self.control_buttons[did].configure(text="Start", command=lambda d=did: self.start_download(d))
            elif status == 'paused':
                self.control_buttons[did].configure(text="Resume", command=lambda d=did: (download_manager.resume_download(d), self.update_download_list()))
            elif status == 'error':
                self.control_buttons[did].configure(text="Restart", command=lambda d=did: self.restart_download(d))
        
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        for item in download_manager.download_history:
            disp_title = item.get('title', item['url'][:50] + "..." if len(item['url']) > 50 else item['url'])
            self.history_tree.insert("", "end", text=disp_title,
                                     values=(item['options']['format'], 
                                             time.strftime('%Y-%m-%d %H:%M', 
                                                           time.localtime(item.get('completed_at', time.time())))))
    
    def start_all_downloads(self):
        count = 0
        for item in list(download_manager.download_queue):
            if count >= 3 - len(download_manager.active_downloads):
                break
            if item['status'] == 'queued':
                self.start_download(item['id'])
                count += 1
        self.update_download_list()
    
    def pause_all_downloads(self):
        for download_id in list(download_manager.active_downloads.keys()):
            download_manager.pause_download(download_id)
        self.update_download_list()
        self.status_label.configure(text="All downloads paused")
    
    def clear_completed(self):
        download_manager.download_history = [
            item for item in download_manager.download_history 
            if item.get('status') != 'completed'
        ]
        download_manager.save_state()
        self.update_download_list()
        self.status_label.configure(text="Completed downloads cleared")
    
    def clear_history(self):
        download_manager.download_history = []
        download_manager.save_state()
        self.update_download_list()
        self.status_label.configure(text="History cleared")
    
    def open_download_folder(self):
        path = self.location_var.get()
        if os.path.exists(path):
            os.startfile(path)
    
    def check_ffmpeg(self):
        return shutil.which("ffmpeg") is not None
    
    def process_download(self, download_id):
        item = download_manager.active_downloads.get(download_id)
        if not item or item['status'] != 'downloading':
            return
        try:
            self.root.after(0, lambda: self.status_label.configure(text=f"Downloading: {item['url'][:30]}..."))
            clean_url = self.clean_youtube_url(item['url'])
            download_path = item['options']['location']
            format_type = item['options']['format']
            quality = item['options']['quality']
            
            ydl_opts = {
                'outtmpl': f"{download_path}/%(title)s.%(ext)s",
                'progress_hooks': [lambda d: self.on_progress(download_id, d)],
                'noplaylist': True,
            }
            
            ffmpeg_available = self.check_ffmpeg()
            
            if format_type == "video":
                if ffmpeg_available:
                    if quality == "highest":
                        ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]'
                    elif quality == "lowest":
                        ydl_opts['format'] = 'worstvideo[ext=mp4]+worstaudio[ext=m4a]/worst[ext=mp4]'
                    else:
                        height = quality[:-1]
                        ydl_opts['format'] = f'bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={height}][ext=mp4]'
                else:
                    if quality == "highest":
                        ydl_opts['format'] = 'best[ext=mp4]'
                    elif quality == "lowest":
                        ydl_opts['format'] = 'worst[ext=mp4]'
                    else:
                        height = quality[:-1]
                        ydl_opts['format'] = f'best[height<={height}][ext=mp4]'
                    self.root.after(0, lambda: self.status_label.configure(
                        text="Warning: ffmpeg not found. Using single stream format, quality may be limited.",
                        text_color="yellow"))
            else:
                ydl_opts['format'] = 'bestaudio'
                if ffmpeg_available:
                    ydl_opts['postprocessors'] = [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }]
                else:
                    ydl_opts['format'] = 'bestaudio[ext=m4a]'
                    self.root.after(0, lambda: self.status_label.configure(
                        text="Warning: ffmpeg not found. Downloading as M4A instead of MP3.",
                        text_color="yellow"))
            
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(clean_url, download=True)
                if 'title' in info and not item.get('title'):
                    item['title'] = info['title']
                output_file = ydl.prepare_filename(info)
            
            download_manager.complete_download(download_id, output_file)
            self.root.after(0, lambda: self.status_label.configure(text=f"Download completed: {os.path.basename(output_file)}"))
        except Exception as e:
            if "Download interrupted" in str(e):
                print("Download paused")
            else:
                error_msg = f"Download failed: {str(e)}"
                if "ffmpeg is not installed" in str(e):
                    error_msg = "Download failed: ffmpeg is required for MP3 conversion or video/audio merging. Please install ffmpeg."
                print(error_msg)
                if download_id in self.active_downloads:
                    self.active_downloads[download_id]['status'] = 'error'
                self.root.after(0, lambda: self.status_label.configure(text=error_msg, text_color="red"))
        finally:
            self.root.after(0, self.update_download_list)
    
    def on_progress(self, download_id, data):
        item = download_manager.active_downloads.get(download_id)
        if item and data['status'] == 'downloading':
            if 'total_bytes' in data and data['total_bytes'] > 0 and 'downloaded_bytes' in data:
                percentage = (data['downloaded_bytes'] / data['total_bytes']) * 100
                item['progress'] = int(percentage)
            elif 'total_bytes_estimate' in data and 'downloaded_bytes' in data:
                percentage = (data['downloaded_bytes'] / data['total_bytes_estimate']) * 100
                item['progress'] = int(percentage)
            item['downloaded_bytes'] = data.get('downloaded_bytes', 0)
            item['total_bytes'] = data.get('total_bytes', data.get('total_bytes_estimate', 0))
            item['speed'] = data.get('speed')
            item['eta'] = data.get('eta')
            if item['status'] != 'downloading':
                raise Exception("Download interrupted")
            self.root.after(0, self.update_download_list)

def main():
    root = ctk.CTk()
    app = YouTubeDownloader(root)
    root.mainloop()

if __name__ == "__main__":
    main()