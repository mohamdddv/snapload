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

# السماح بطلبات من أي مصدر (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# إعداد اللوقينج
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# نموذج استقبال رابط الفيديو
class YouTubeURL(BaseModel):
    url: str

# نموذج خيارات الجودة
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

# نموذج معلومات الفيديو كاملة
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
    """تحويل الحجم من بايت إلى صيغة مقروءة"""
    if not size_bytes:
        return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"

def get_quality_label(fmt):
    """إنشاء تسمية جودة سهلة القراءة"""
    height = fmt.get('height')
    fps = fmt.get('fps')
    ext = fmt.get('ext', 'mp4')
    filesize = fmt.get('filesize') or fmt.get('filesize_approx')

    if not height:
        # صوت فقط
        if fmt.get('acodec') and fmt.get('acodec') != 'none':
            abr = fmt.get('abr', 128)
            return f"Audio Only ({abr}kbps {ext.upper()})"
        return f"Unknown Quality ({ext.upper()})"

    quality_str = f"{height}p"
    if fps and fps > 30:
        quality_str += f"{fps}fps"

    if filesize:
        size_str = format_filesize(filesize)
        return f"{quality_str} ({ext.upper()}) - {size_str}"

    return f"{quality_str} ({ext.upper()})"

@app.get("/download-proxy")
async def download_video_proxy(video_url: str, filename: str):
    """
    تحميل الفيديو عبر بروكسي مع دعم ترويسة Content-Disposition لدعم UTF-8 في اسم الملف
    """
    try:
        logger.info(f"Proxy download requested for: {video_url[:100]}...")
        logger.info(f"Filename: {filename}")

        decoded_video_url = urllib.parse.unquote(video_url)
        decoded_filename = urllib.parse.unquote(filename)

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'identity',
            'Range': 'bytes=0-'
        }

        response = requests.get(decoded_video_url, stream=True, headers=headers)

        if response.status_code not in [200, 206]:
            logger.error(f"Failed to fetch video: {response.status_code}")
            raise HTTPException(status_code=400, detail=f"Failed to fetch video: {response.status_code}")

        content_type = response.headers.get('content-type', 'video/mp4')
        content_length = response.headers.get('content-length')

        logger.info(f"Content type: {content_type}, Content length: {content_length}")

        def generate():
            try:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            except Exception as e:
                logger.error(f"Error streaming content: {e}")
                raise

        safe_filename = urllib.parse.quote(decoded_filename)
        content_disposition = f"attachment; filename*=UTF-8''{safe_filename}"

        response_headers = {
            'Content-Disposition': content_disposition,
            'Content-Type': content_type,
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Expose-Headers': 'Content-Disposition',
            'Cache-Control': 'no-cache'
        }

        if content_length:
            response_headers['Content-Length'] = content_length

        return StreamingResponse(
            generate(),
            media_type=content_type,
            headers=response_headers
        )

    except Exception as e:
        logger.error(f"Error in proxy download: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Download failed: {str(e)}")

@app.post("/extract-video", response_model=VideoInfo)
async def extract_video_info(youtube_url: YouTubeURL):
    """
    استخراج معلومات الفيديو مع جميع خيارات الجودة المتاحة
    """
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'cookiefile': 'cookies.txt',  # ملف الكوكيز بتنسيق Netscape
            'extractor_args': {
                'youtubetab': {'skip': 'authcheck'}  # لتخطي فحص التوثيق على بعض قوائم التشغيل
            },
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
            },
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url.url, download=False)
            formats = info.get('formats', [])

            quality_options = []
            seen_qualities = set()

            # فرز الصيغ حسب الجودة (الارتفاع) ثم الحجم
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

@app.get("/download-format")
async def download_format(format_url: str, title: str, ext: str = "mp4"):
    """
    إنشاء رابط تحميل مباشر لتنسيق معين عبر البروكسي
    """
    try:
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
        filename = f"{safe_title}.{ext}"

        encoded_url = urllib.parse.quote(format_url, safe='')
        encoded_filename = urllib.parse.quote(filename, safe='')

        proxy_url = f"http://localhost:8000/download-proxy?video_url={encoded_url}&filename={encoded_filename}"

        return {"download_url": proxy_url, "filename": filename}

    except Exception as e:
        logger.error(f"Error creating download link: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error creating download link: {str(e)}")

@app.get("/")
async def root():
    return {"message": "YouTube Video Downloader API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
