from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import yt_dlp
import logging
import requests
import urllib.parse
from typing import List, Optional

app = FastAPI(title="YouTube Video Downloader API")

# إعداد CORS للسماح بالطلبات من أي مصدر
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# إعداد اللوقينج (التسجيل)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class YouTubeURL(BaseModel):
    url: str

class QualityOption(BaseModel):
    quality: str
    format_id: str
    ext: str
    filesize: Optional[int] = None
    filesize_approx: Optional[int] = None
    height: Optional[int] = None
    width: Optional[int] = None
    fps: Optional[int] = None
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    url: str

class VideoInfo(BaseModel):
    title: str
    duration: str
    thumbnail: Optional[str] = None
    uploader: Optional[str] = None
    view_count: Optional[int] = None
    upload_date: Optional[str] = None
    description: Optional[str] = None
    quality_options: List[QualityOption]

def format_filesize(size_bytes):
    if not size_bytes:
        return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"

def get_quality_label(fmt):
    height = fmt.get('height')
    fps = fmt.get('fps')
    ext = fmt.get('ext', 'mp4')
    filesize = fmt.get('filesize') or fmt.get('filesize_approx')

    if not height:
        if fmt.get('acodec') and fmt.get('acodec') != 'none':
            abr = fmt.get('abr', 128)
            return f"Audio Only ({abr}kbps {ext.upper()})"
        return f"Unknown Quality ({ext.upper()})"

    quality_str = f"{height}p"
    if fps and fps > 30:
        quality_str += f"{fps}"
    if filesize:
        size_str = format_filesize(filesize)
        return f"{quality_str} ({ext.upper()}) - {size_str}"
    return f"{quality_str} ({ext.upper()})"

@app.post("/extract-video", response_model=VideoInfo)
async def extract_video_info(youtube_url: YouTubeURL):
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extractaudio': False,
            'listformats': True,
            'cookiefile': 'cookies.txt',  # تأكد أن هذا الملف موجود وبتنسيق Netscape
            'extractor_args': {
                'youtubetab': {'skip': 'authcheck'}
            }
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url.url, download=False)
            formats = info.get('formats', [])
            
            quality_options = []
            seen_qualities = set()
            sorted_formats = sorted(formats, key=lambda x: (
                x.get('height', 0) or 0,
                x.get('filesize', 0) or x.get('filesize_approx', 0) or 0
            ), reverse=True)
            
            for fmt in sorted_formats:
                if not fmt.get('url') or not fmt.get('url', '').startswith('http'):
                    continue
                if (fmt.get('url', '').endswith('.m3u8') or 
                    fmt.get('url', '').endswith('.mpd') or 
                    'manifest' in fmt.get('url', '').lower()):
                    continue
                if (fmt.get('vcodec') == 'none' and fmt.get('acodec') == 'none'):
                    continue
                
                height = fmt.get('height', 0)
                ext = fmt.get('ext', 'mp4')
                fps = fmt.get('fps', 30)
                
                if height:
                    quality_id = f"{height}p_{ext}"
                    if fps and fps > 30:
                        quality_id += f"_{fps}fps"
                else:
                    abr = fmt.get('abr', 128)
                    quality_id = f"audio_{abr}kbps_{ext}"
                
                if quality_id in seen_qualities:
                    continue
                
                seen_qualities.add(quality_id)
                
                quality_option = QualityOption(
                    quality=get_quality_label(fmt),
                    format_id=fmt.get('format_id', ''),
                    ext=ext,
                    filesize=fmt.get('filesize'),
                    filesize_approx=fmt.get('filesize_approx'),
                    height=height,
                    width=fmt.get('width'),
                    fps=fps,
                    vcodec=fmt.get('vcodec'),
                    acodec=fmt.get('acodec'),
                    url=fmt['url']
                )
                
                quality_options.append(quality_option)
                
                if len(quality_options) >= 15:
                    break
            
            if not quality_options:
                raise HTTPException(status_code=400, detail="No compatible video formats found")
            
            duration = info.get('duration', 0)
            duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "Unknown"
            upload_date = info.get('upload_date')
            formatted_date = None
            if upload_date:
                try:
                    formatted_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
                except:
                    formatted_date = upload_date
            
            return VideoInfo(
                title=info.get('title', 'Unknown Title'),
                duration=duration_str,
                thumbnail=info.get('thumbnail'),
                uploader=info.get('uploader'),
                view_count=info.get('view_count'),
                upload_date=formatted_date,
                description=info.get('description', '')[:200] + "..." if info.get('description') else None,
                quality_options=quality_options
            )

    except Exception as e:
        logger.error(f"Error extracting video: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error extracting video: {str(e)}")

@app.get("/")
async def root():
    return {"message": "YouTube Video Downloader API is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
