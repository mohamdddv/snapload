from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
import yt_dlp

app = FastAPI()

# إعداد CORS للسماح للواجهة بالاتصال بالخادم
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # استبدل "*" بالمصدر الخاص بالواجهة إن أردت الأمان
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# موديل البيانات المتوقعة من الواجهة
class VideoRequest(BaseModel):
    url: HttpUrl  # يتأكد أن الرابط URL صالح

@app.post("/extract-video")
async def extract_video(req: VideoRequest):
    video_url = req.url

    ydl_opts = {
        "format": "best",
        "quiet": True,
        "no_warnings": True,
        # لو عندك ملف cookies استخدمه هكذا:
        # "cookiefile": "cookies.txt",
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(str(video_url), download=False)
        # أعد فقط البيانات التي تحتاجها للواجهة (مثل العنوان، الوصف، والصيغ المتاحة)
        formats = []
        for f in info.get("formats", []):
            formats.append({
                "format_id": f.get("format_id"),
                "ext": f.get("ext"),
                "resolution": f.get("resolution") or f.get("height"),
                "filesize": f.get("filesize"),
                "url": f.get("url"),
            })

        return {
            "title": info.get("title"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "formats": formats,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
