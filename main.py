from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import yt_dlp
import requests
import urllib.parse

app = FastAPI()

# السماح للفرونتند بالتواصل مع الباكند
origins = [
    "*"  # للأغراض التجريبية، مستحسن تضيق النطاق في الإنتاج
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class VideoExtractRequest(BaseModel):
    video_url: str
    cookies_file: str = None  # مسار ملف الكوكيز إن وجد

@app.post("/extract-video")
async def extract_video(data: VideoExtractRequest):
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'no_warnings': True,
        'format': 'best',
    }

    if data.cookies_file:
        ydl_opts['cookiefile'] = data.cookies_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(data.video_url, download=False)
            formats = info.get('formats', [])
            # نهيئ قائمة صيغ الفيديو مع التفاصيل المطلوبة
            video_formats = []
            for f in formats:
                if f.get('url') and f.get('ext') and f.get('format_note'):
                    video_formats.append({
                        'format_id': f.get('format_id'),
                        'ext': f.get('ext'),
                        'resolution': f.get('resolution') or f.get('format_note'),
                        'filesize': f.get('filesize') or f.get('filesize_approx'),
                        'url': f.get('url'),
                    })

            return {
                'title': info.get('title'),
                'thumbnail': info.get('thumbnail'),
                'duration': info.get('duration'),
                'formats': video_formats,
            }

    except Exception as e:
        print(f"Error extracting video: {e}")
        raise HTTPException(status_code=400, detail=f"Error extracting video: {str(e)}")

@app.get("/download-proxy")
async def download_video_proxy(video_url: str = Query(...), filename: str = Query(...)):
    try:
        decoded_video_url = urllib.parse.unquote(video_url)
        decoded_filename = urllib.parse.unquote(filename)

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'identity',
            'Range': 'bytes=0-',
            'Referer': 'https://www.youtube.com'
        }

        response = requests.get(decoded_video_url, stream=True, headers=headers, timeout=20)

        if response.status_code not in [200, 206]:
            raise HTTPException(status_code=400, detail=f"Failed to fetch video: HTTP {response.status_code}")

        content_type = response.headers.get('content-type', 'video/mp4')
        content_length = response.headers.get('content-length')

        def generate():
            try:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            except Exception as e:
                print(f"Streaming error: {e}")
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
        print(f"Download proxy error: {e}")
        raise HTTPException(status_code=400, detail=f"Download failed: {str(e)}")


@app.get("/")
async def root():
    return {"message": "SnapLoad API is running"}

