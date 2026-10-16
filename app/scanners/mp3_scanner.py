import os
import re
from typing import List, Dict, Tuple
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, APIC

class Mp3Scanner:
    def __init__(self, db):
        self.db = db
    
    async def scan(self, dir_path: str, category: str = None):
        """Scan directory for MP3 files"""
        for root, dirs, files in os.walk(dir_path):
            mp3_files = sorted([f for f in files if f.lower().endswith('.mp3')])
            
            if mp3_files:
                # Group MP3 files by directory (assume each directory is one audiobook)
                await self._process_group(root, mp3_files, category)
    
    async def _process_group(self, dir_path: str, mp3_files: List[str], category: str = None):
        """Process a group of MP3 files as one audiobook"""
        # Extract book info from first file
        first_file = os.path.join(dir_path, mp3_files[0])
        book_info = self._extract_metadata(first_file)
        
        # Get total duration
        total_duration = 0
        chapters = []
        
        for i, mp3_file in enumerate(mp3_files, 1):
            file_path = os.path.join(dir_path, mp3_file)
            audio_info = self._get_audio_info(file_path)
            
            if audio_info:
                total_duration += audio_info["duration"]
                chapters.append({
                    "title": self._get_chapter_title(mp3_file, i),
                    "audio_file": file_path,
                    "duration": audio_info["duration"]
                })
        
        # Check if already exists
        if await self.db.book_exists(dir_path):
            return
        
        # Add book
        book_data = {
            "title": book_info["title"],
            "author": book_info["author"],
            "type": "audio",
                "category": category or "默认",
            "file_path": dir_path,
            "file_size": sum(os.path.getsize(os.path.join(dir_path, f)) for f in mp3_files),
            "total_chapters": len(chapters),
            "total_duration": total_duration,
            "cover_path": book_info.get("cover_path")
        }
        
        book_id = await self.db.add_book(book_data)
        if not book_id:
            return
        
        # Add chapters
        for i, chapter in enumerate(chapters, 1):
            chapter_data = {
                "book_id": book_id,
                "chapter_number": i,
                "title": chapter["title"],
                "audio_file": chapter["audio_file"],
                "duration": chapter["duration"]
            }
            await self.db.add_chapter(chapter_data)
        
        print(f"Scanned audio: {book_info['title']} ({len(chapters)} chapters)")
    
    def _extract_metadata(self, file_path: str) -> Dict:
        """Extract metadata from MP3 file"""
        try:
            audio = MP3(file_path, ID3=ID3)
            
            title = ""
            author = ""
            cover_path = None
            
            # Get title
            if audio.tags and 'TIT2' in audio.tags:
                title = str(audio.tags['TIT2'].text[0])
            
            # Get artist
            if audio.tags and 'TPE1' in audio.tags:
                author = str(audio.tags['TPE1'].text[0])
            
            # Extract cover
            if audio.tags and 'APIC:' in audio.tags:
                cover_data = audio.tags['APIC:'].data
                cover_path = file_path + ".cover.jpg"
                with open(cover_path, 'wb') as f:
                    f.write(cover_data)
            
            # Fallback to filename
            if not title:
                title = os.path.splitext(os.path.basename(file_path))[0]
            
            return {
                "title": title,
                "author": author,
                "cover_path": cover_path
            }
            
        except Exception as e:
            print(f"Error extracting metadata from {file_path}: {e}")
            return {
                "title": os.path.splitext(os.path.basename(file_path))[0],
                "author": ""
            }
    
    def _get_audio_info(self, file_path: str) -> Dict:
        """Get audio file info"""
        try:
            audio = MP3(file_path)
            return {
                "duration": int(audio.info.length),
                "bitrate": audio.info.bitrate,
                "sample_rate": audio.info.sample_rate
            }
        except Exception as e:
            print(f"Error getting audio info from {file_path}: {e}")
            return None
    
    def _get_chapter_title(self, filename: str, index: int) -> str:
        """Generate chapter title from filename"""
        # Remove extension
        name = os.path.splitext(filename)[0]
        
        # Try to extract chapter number from filename
        patterns = [
            r'第(\d+)集',
            r'第(\d+)章',
            r'Chapter\s*(\d+)',
            r'(\d+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, name, re.IGNORECASE)
            if match:
                return f"第{match.group(1)}集"
        
        # Fallback to index
        return f"第{index}集"
