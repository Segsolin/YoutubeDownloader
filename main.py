import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
import json
import time
from pathlib import Path
from pytube import YouTube
from pytube.exceptions import AgeRestrictedError, VideoUnavailable
from moviepy.editor import VideoFileClip
import customtkinter as ctk
from PIL import Image, ImageTk
import requests
from io import BytesIO
from collections import deque
import re
import urllib.error
from urllib.parse import urlparse, parse_qs

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
    
    def add_download(self, url, options):
        download_id = f"{url}_{time.time()}"
        self.download_queue.append({
            'id': download_id,
            'url': url,
            'options': options,
            'status': 'queued',
            'progress': 0
        })
        self.save_state()
        return download_id
    
    def start_download(self, download_id):
        for item in list(self.download_queue):
            if item['id'] == download_id:
                item['status'] = 'downloading'
                # Move to active downloads
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
        # Check active downloads
        if download_id in self.active_downloads:
            del self.active_downloads[download_id]
            self.save_state()
            return True
        
        # Check queue
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
        
        # Configure styles
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")
        
        self.setup_ui()
        self.update_download_list()
        
        # Start download manager thread
        self.running = True
        self.download_thread = threading.Thread(target=self.download_manager_worker, daemon=True)
        self.download_thread.start()
        
    def setup_ui(self):
        # Create tabs
        self.tab_view = ctk.CTkTabview(self.root)
        self.tab_view.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Download tab
        self.download_tab = self.tab_view.add("Download")
        self.queue_tab = self.tab_view.add("Download Queue")
        self.history_tab = self.tab_view.add("History")
        
        self.setup_download_tab()
        self.setup_queue_tab()
        self.setup_history_tab()
        
    def setup_download_tab(self):
        # Main frame
        main_frame = ctk.CTkFrame(self.download_tab)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Title
        title_label = ctk.CTkLabel(main_frame, text="YouTube Downloader", 
                                  font=ctk.CTkFont(size=20, weight="bold"))
        title_label.pack(pady=20)
        
        # URL input
        url_frame = ctk.CTkFrame(main_frame)
        url_frame.pack(fill="x", padx=20, pady=10)
        
        ctk.CTkLabel(url_frame, text="YouTube URL:").pack(anchor="w")
        self.url_entry = ctk.CTkEntry(url_frame, placeholder_text="Enter YouTube video URL", height=40)
        self.url_entry.pack(fill="x", pady=5)
        self.url_entry.bind("<Return>", lambda e: self.preview_video())
        
        # Preview frame
        self.preview_frame = ctk.CTkFrame(main_frame)
        self.preview_frame.pack(fill="x", padx=20, pady=10)
        
        # Download options
        options_frame = ctk.CTkFrame(main_frame)
        options_frame.pack(fill="x", padx=20, pady=10)
        
        ctk.CTkLabel(options_frame, text="Download Options:").pack(anchor="w")
        
        # Format selection
        format_frame = ctk.CTkFrame(options_frame)
        format_frame.pack(fill="x", pady=5)
        
        self.format_var = ctk.StringVar(value="video")
        ctk.CTkRadioButton(format_frame, text="Video (MP4)", variable=self.format_var, 
                          value="video").pack(side="left", padx=10)
        ctk.CTkRadioButton(format_frame, text="Audio (MP3)", variable=self.format_var, 
                          value="audio").pack(side="left", padx=10)
        
        # Quality selection
        quality_frame = ctk.CTkFrame(options_frame)
        quality_frame.pack(fill="x", pady=5)
        
        ctk.CTkLabel(quality_frame, text="Quality:").pack(side="left")
        self.quality_var = ctk.StringVar(value="highest")
        quality_combo = ctk.CTkComboBox(quality_frame, variable=self.quality_var,
                                       values=["highest", "720p", "480p", "360p", "lowest"])
        quality_combo.pack(side="left", padx=10)
        
        # Download location
        location_frame = ctk.CTkFrame(options_frame)
        location_frame.pack(fill="x", pady=5)
        
        ctk.CTkLabel(location_frame, text="Download Location:").pack(anchor="w")
        
        loc_subframe = ctk.CTkFrame(location_frame)
        loc_subframe.pack(fill="x", pady=5)
        
        self.location_var = ctk.StringVar(value=os.path.expanduser("~/Downloads"))
        self.location_entry = ctk.CTkEntry(loc_subframe, textvariable=self.location_var)
        self.location_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        ctk.CTkButton(loc_subframe, text="Browse", width=80, 
                     command=self.browse_location).pack(side="right")
        
        # Buttons frame
        buttons_frame = ctk.CTkFrame(main_frame)
        buttons_frame.pack(fill="x", padx=20, pady=20)
        
        self.download_btn = ctk.CTkButton(buttons_frame, text="Add to Queue", 
                                         command=self.add_to_queue, height=40)
        self.download_btn.pack(side="left", padx=10)
        
        self.preview_btn = ctk.CTkButton(buttons_frame, text="Preview", 
                                        command=self.preview_video, height=40)
        self.preview_btn.pack(side="left", padx=10)
        
        # Status label
        self.status_label = ctk.CTkLabel(main_frame, text="Ready")
        self.status_label.pack(pady=10)
        
    def setup_queue_tab(self):
        # Queue frame
        queue_frame = ctk.CTkFrame(self.queue_tab)
        queue_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Title
        title_label = ctk.CTkLabel(queue_frame, text="Download Queue", 
                                  font=ctk.CTkFont(size=16, weight="bold"))
        title_label.pack(pady=10)
        
        # Queue list with scrollbar
        tree_frame = ctk.CTkFrame(queue_frame)
        tree_frame.pack(fill="both", expand=True, pady=10)
        
        # Create treeview with scrollbar
        tree_scroll = ttk.Scrollbar(tree_frame)
        tree_scroll.pack(side="right", fill="y")
        
        self.queue_tree = ttk.Treeview(tree_frame, columns=("status", "progress", "actions"), 
                                      show="headings", height=10, yscrollcommand=tree_scroll.set)
        tree_scroll.config(command=self.queue_tree.yview)
        
        self.queue_tree.heading("#0", text="Title")
        self.queue_tree.heading("status", text="Status")
        self.queue_tree.heading("progress", text="Progress")
        self.queue_tree.heading("actions", text="Actions")
        
        self.queue_tree.column("#0", width=300)
        self.queue_tree.column("status", width=100)
        self.queue_tree.column("progress", width=100)
        self.queue_tree.column("actions", width=150)
        
        self.queue_tree.pack(fill="both", expand=True)
        
        # Bind click event
        self.queue_tree.bind("<Button-1>", self.on_tree_click)
        
        # Control buttons
        control_frame = ctk.CTkFrame(queue_frame)
        control_frame.pack(fill="x", pady=10)
        
        ctk.CTkButton(control_frame, text="Start All", command=self.start_all_downloads).pack(side="left", padx=5)
        ctk.CTkButton(control_frame, text="Pause All", command=self.pause_all_downloads).pack(side="left", padx=5)
        ctk.CTkButton(control_frame, text="Clear Completed", command=self.clear_completed).pack(side="left", padx=5)
        
    def setup_history_tab(self):
        # History frame
        history_frame = ctk.CTkFrame(self.history_tab)
        history_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Title
        title_label = ctk.CTkLabel(history_frame, text="Download History", 
                                  font=ctk.CTkFont(size=16, weight="bold"))
        title_label.pack(pady=10)
        
        # History list with scrollbar
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
        
        # Control buttons
        control_frame = ctk.CTkFrame(history_frame)
        control_frame.pack(fill="x", pady=10)
        
        ctk.CTkButton(control_frame, text="Clear History", command=self.clear_history).pack(side="left", padx=5)
        ctk.CTkButton(control_frame, text="Open Download Folder", command=self.open_download_folder).pack(side="right", padx=5)
    
    def browse_location(self):
        directory = filedialog.askdirectory()
        if directory:
            self.location_var.set(directory)
    
    def clean_youtube_url(self, url):
        """Clean YouTube URL by removing unnecessary parameters"""
        try:
            # Parse the URL
            parsed_url = urlparse(url)
            
            # Extract video ID from query parameters
            query_params = parse_qs(parsed_url.query)
            video_id = query_params.get('v', [None])[0]
            
            # If we found a video ID, reconstruct a clean URL
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"
            
            # If it's a youtu.be short URL
            if parsed_url.netloc == 'youtu.be':
                video_id = parsed_url.path[1:]  # Remove the leading slash
                return f"https://www.youtube.com/watch?v={video_id}"
                
            # If we can't extract a clean URL, return the original
            return url
            
        except Exception as e:
            print(f"Error cleaning URL: {e}")
            return url
    
    def get_video_info(self, url):
        try:
            # Clean the URL first
            clean_url = self.clean_youtube_url(url)
            
            # Extract video ID for better thumbnail handling
            video_id = self.extract_video_id(clean_url)
            if not video_id:
                raise ValueError("Invalid YouTube URL")
                
            # Use bypass for age-restricted content
            yt = YouTube(clean_url, use_oauth=False, allow_oauth_cache=True)
            return yt, video_id
        except AgeRestrictedError:
            # Try with OAuth for age-restricted content
            try:
                yt = YouTube(clean_url, use_oauth=True, allow_oauth_cache=True)
                return yt, video_id
            except Exception as e:
                messagebox.showerror("Error", f"Age-restricted content. Please try with OAuth: {str(e)}")
                return None, None
        except VideoUnavailable:
            messagebox.showerror("Error", "The video is unavailable")
            return None, None
        except Exception as e:
            messagebox.showerror("Error", f"Failed to get video info: {str(e)}")
            return None, None
    
    def extract_video_id(self, url):
        # Extract YouTube video ID from URL
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
            self.update_preview(yt, video_id)
    
    def update_preview(self, yt, video_id):
        # Clear previous preview
        for widget in self.preview_frame.winfo_children():
            widget.destroy()
        
        try:
            # Get thumbnail using video ID (more reliable)
            # Try different thumbnail qualities with error handling
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
            
            # Create preview frame
            preview_container = ctk.CTkFrame(self.preview_frame)
            preview_container.pack(fill="x", pady=5)
            
            # Thumbnail
            thumbnail_label = ctk.CTkLabel(preview_container, image=photo, text="")
            thumbnail_label.image = photo  # Keep a reference
            thumbnail_label.pack(side="left", padx=10)
            
            # Video info
            info_frame = ctk.CTkFrame(preview_container)
            info_frame.pack(side="left", fill="both", expand=True, padx=10)
            
            title = yt.title
            if len(title) > 50:
                title = title[:47] + "..."
                
            ctk.CTkLabel(info_frame, text=title, 
                        font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=2)
            ctk.CTkLabel(info_frame, text=f"Duration: {yt.length//60}:{yt.length%60:02d}").pack(anchor="w", pady=2)
            ctk.CTkLabel(info_frame, text=f"Views: {yt.views:,}").pack(anchor="w", pady=2)
            
        except Exception as e:
            error_label = ctk.CTkLabel(self.preview_frame, text=f"Preview unavailable: {str(e)}", text_color="red")
            error_label.pack(pady=10)
            print(f"Preview error: {e}")
    
    def add_to_queue(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a YouTube URL")
            return
        
        # Clean the URL first
        clean_url = self.clean_youtube_url(url)
        
        # Validate URL
        video_id = self.extract_video_id(clean_url)
        if not video_id:
            messagebox.showerror("Error", "Invalid YouTube URL")
            return
        
        options = {
            'format': self.format_var.get(),
            'quality': self.quality_var.get(),
            'location': self.location_var.get()
        }
        
        download_id = download_manager.add_download(clean_url, options)
        self.update_download_list()
        self.status_label.configure(text="Download added to queue!")
        
        # Auto-start download if less than 3 active
        if len(download_manager.active_downloads) < 3:
            self.start_download(download_id)
    
    def start_download(self, download_id):
        item = download_manager.start_download(download_id)
        if item:
            self.status_label.configure(text=f"Starting download: {item['url'][:30]}...")
            self.update_download_list()
    
    def on_tree_click(self, event):
        # Handle clicks on the treeview
        region = self.queue_tree.identify("region", event.x, event.y)
        if region == "cell":
            column = self.queue_tree.identify_column(event.x)
            item = self.queue_tree.identify_row(event.y)
            
            if item and column == "#4":  # Actions column
                values = self.queue_tree.item(item, "values")
                if values and "Start" in values[2]:
                    self.start_download(item)
                elif values and "Pause" in values[2]:
                    download_manager.pause_download(item)
                    self.update_download_list()
                elif values and "Resume" in values[2]:
                    download_manager.resume_download(item)
                    self.update_download_list()
                elif values and "Remove" in values[2]:
                    download_manager.remove_download(item)
                    self.update_download_list()
    
    def update_download_list(self):
        # Clear current tree
        for item in self.queue_tree.get_children():
            self.queue_tree.delete(item)
        
        # Add active downloads
        for download_id, item in download_manager.active_downloads.items():
            title = item['url'][:40] + "..." if len(item['url']) > 40 else item['url']
            self.queue_tree.insert("", "end", iid=download_id, text=title,
                                 values=(item['status'], f"{item.get('progress', 0)}%", 
                                         "Pause | Remove"))
        
        # Add queued downloads
        for item in download_manager.download_queue:
            title = item['url'][:40] + "..." if len(item['url']) > 40 else item['url']
            action = "Resume | Remove" if item['status'] == 'paused' else "Start | Remove"
            self.queue_tree.insert("", "end", iid=item['id'], text=title,
                                 values=(item['status'], "0%", action))
        
        # Update history tab
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        
        for item in download_manager.download_history:
            title = item['url'][:50] + "..." if len(item['url']) > 50 else item['url']
            self.history_tree.insert("", "end", text=title,
                                   values=(item['options']['format'], 
                                           time.strftime('%Y-%m-%d %H:%M', 
                                                         time.localtime(item.get('completed_at', time.time())))))
    
    def start_all_downloads(self):
        # Start all queued downloads (up to 3 simultaneous downloads)
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
        # Remove completed items from history
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
    
    def download_manager_worker(self):
        """Background thread to process downloads"""
        while self.running:
            try:
                # Process active downloads
                for download_id, item in list(download_manager.active_downloads.items()):
                    if item['status'] == 'downloading':
                        self.process_download(download_id)
                
                time.sleep(2)  # Check every 2 seconds
            except Exception as e:
                print(f"Download manager error: {e}")
                time.sleep(5)
    
    def process_download(self, download_id):
        """Process a single download"""
        item = download_manager.active_downloads.get(download_id)
        if not item or item['status'] != 'downloading':
            return
            
        try:
            self.status_label.configure(text=f"Downloading: {item['url'][:30]}...")
            
            # Clean the URL before processing
            clean_url = self.clean_youtube_url(item['url'])
            
            # Try with different parameters for problematic videos
            try:
                yt = YouTube(clean_url, 
                            use_oauth=False,
                            allow_oauth_cache=True,
                            on_progress_callback=lambda stream, chunk, bytes_remaining: 
                            self.on_progress(download_id, stream, chunk, bytes_remaining))
            except AgeRestrictedError:
                yt = YouTube(clean_url, 
                            use_oauth=True,
                            allow_oauth_cache=True,
                            on_progress_callback=lambda stream, chunk, bytes_remaining: 
                            self.on_progress(download_id, stream, chunk, bytes_remaining))
            
            download_path = item['options']['location']
            format_type = item['options']['format']
            
            if format_type == "video":
                # Try different stream options
                stream = None
                
                # First try progressive streams
                if item['options']['quality'] == "highest":
                    stream = yt.streams.filter(progressive=True, file_extension='mp4').get_highest_resolution()
                elif item['options']['quality'] == "lowest":
                    stream = yt.streams.filter(progressive=True, file_extension='mp4').get_lowest_resolution()
                else:
                    stream = yt.streams.filter(progressive=True, res=item['options']['quality'], file_extension='mp4').first()
                
                # If no progressive stream found, try adaptive
                if not stream:
                    if item['options']['quality'] == "highest":
                        stream = yt.streams.filter(adaptive=True, file_extension='mp4').order_by('resolution').desc().first()
                    elif item['options']['quality'] == "lowest":
                        stream = yt.streams.filter(adaptive=True, file_extension='mp4').order_by('resolution').first()
                    else:
                        stream = yt.streams.filter(adaptive=True, res=item['options']['quality'], file_extension='mp4').first()
                
                if not stream:
                    raise Exception("No suitable video stream found")
                
                output_file = stream.download(output_path=download_path)
                
            else:
                # Download audio
                stream = yt.streams.filter(only_audio=True).first()
                if not stream:
                    raise Exception("No audio stream found")
                
                # Download as MP4 first
                temp_file = stream.download(output_path=download_path)
                
                # Convert to MP3
                video_clip = VideoFileClip(temp_file)
                mp3_file = os.path.splitext(temp_file)[0] + ".mp3"
                video_clip.audio.write_audiofile(mp3_file)
                video_clip.close()
                
                # Remove temporary MP4 file
                os.remove(temp_file)
                output_file = mp3_file
            
            # Mark as completed
            download_manager.complete_download(download_id, output_file)
            self.status_label.configure(text=f"Download completed: {os.path.basename(output_file)}")
            
        except AgeRestrictedError:
            error_msg = "Age-restricted content. Please try again with OAuth authentication."
            print(f"Download error: {error_msg}")
            if download_id in download_manager.active_downloads:
                download_manager.active_downloads[download_id]['status'] = 'error'
            self.status_label.configure(text=error_msg)
            
        except Exception as e:
            error_msg = f"Download failed: {str(e)}"
            print(f"Download error: {e}")
            if download_id in download_manager.active_downloads:
                download_manager.active_downloads[download_id]['status'] = 'error'
            self.status_label.configure(text=error_msg)
        
        finally:
            self.update_download_list()
    
    def on_progress(self, download_id, stream, chunk, bytes_remaining):
        """Update progress for a download"""
        if download_id in download_manager.active_downloads:
            total_size = stream.filesize
            bytes_downloaded = total_size - bytes_remaining
            percentage = (bytes_downloaded / total_size) * 100
            
            download_manager.active_downloads[download_id]['progress'] = int(percentage)
            self.update_download_list()
    
    def __del__(self):
        self.running = False

def main():
    root = ctk.CTk()
    app = YouTubeDownloader(root)
    root.mainloop()

if __name__ == "__main__":
    main()