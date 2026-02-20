import os
import re
import asyncio
import yt_dlp

VIDEOS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "videos")
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


def ensure_videos_dir():
    os.makedirs(VIDEOS_DIR, exist_ok=True)


def detect_platform(url):
    url_lower = url.lower()
    if "tiktok.com" in url_lower or "vm.tiktok.com" in url_lower:
        return "tiktok"
    elif "instagram.com" in url_lower or "instagr.am" in url_lower:
        return "instagram"
    elif "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    return None


def extract_url(text):
    url_pattern = r'https?://[^\s<>\"\']+|www\.[^\s<>\"\']+'
    match = re.search(url_pattern, text)
    return match.group(0) if match else None


def _get_base_opts():
    return {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
        "file_access_retries": 3,
        "noproxy": True,
        "nocheckcertificate": True,
        "prefer_insecure": False,
        "geo_bypass": True,
        "geo_bypass_country": "US",
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Sec-Fetch-Mode": "navigate",
        },
    }


def _get_platform_opts(platform):
    opts = {}
    if platform == "youtube":
        opts["format"] = "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        opts["merge_output_format"] = "mp4"
    elif platform == "tiktok":
        opts["format"] = "best[ext=mp4]/best"
        opts["merge_output_format"] = "mp4"
        opts["http_headers"] = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://www.tiktok.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    elif platform == "instagram":
        opts["format"] = "best[ext=mp4]/best"
        opts["merge_output_format"] = "mp4"
        opts["http_headers"] = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    return opts


def _download_sync(url, platform, compress=False):
    ensure_videos_dir()
    output_template = os.path.join(VIDEOS_DIR, "%(id)s.%(ext)s")

    ydl_opts = _get_base_opts()
    ydl_opts["outtmpl"] = output_template
    ydl_opts.update(_get_platform_opts(platform))

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                return None, "Не удалось найти видео по этой ссылке."

            filename = ydl.prepare_filename(info)
            if not filename.endswith(".mp4"):
                base = os.path.splitext(filename)[0]
                filename = base + ".mp4"

            if not os.path.exists(filename):
                video_id = info.get("id", "")
                for f in os.listdir(VIDEOS_DIR):
                    if video_id and f.startswith(video_id) and f.endswith(".mp4"):
                        filename = os.path.join(VIDEOS_DIR, f)
                        break

            if not os.path.exists(filename):
                return None, "Не удалось найти скачанный файл."

            file_size = os.path.getsize(filename)

            if compress and file_size > MAX_FILE_SIZE:
                compressed_filename = _compress_sync(filename)
                if compressed_filename and os.path.exists(compressed_filename):
                    os.remove(filename)
                    compressed_size = os.path.getsize(compressed_filename)
                    if compressed_size > MAX_FILE_SIZE:
                        os.remove(compressed_filename)
                        return None, "Даже после сжатия файл слишком большой для отправки в Telegram (>50 МБ)."
                    return compressed_filename, None
                else:
                    return filename, "Не удалось сжать видео."

            return filename, None

    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        if "Video unavailable" in error_msg or "not available" in error_msg:
            return None, "Видео недоступно или было удалено."
        elif "Private video" in error_msg:
            return None, "Это приватное видео, доступ к нему ограничен."
        elif "Login required" in error_msg or "login" in error_msg.lower():
            return None, "Для скачивания этого видео требуется авторизация."
        elif "geo" in error_msg.lower() or "country" in error_msg.lower():
            return None, "Видео недоступно в данном регионе."
        return None, "Ошибка при скачивании: видео не найдено или недоступно."
    except Exception:
        return None, "Произошла непредвиденная ошибка при скачивании."


def _compress_sync(input_path):
    import subprocess
    output_path = input_path.replace(".mp4", "_compressed.mp4")
    try:
        cmd = [
            "ffmpeg", "-i", input_path,
            "-vcodec", "libx264",
            "-crf", "28",
            "-preset", "fast",
            "-acodec", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-y",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode == 0 and os.path.exists(output_path):
            return output_path
        return None
    except subprocess.TimeoutExpired:
        if os.path.exists(output_path):
            os.remove(output_path)
        return None
    except Exception:
        return None


async def download_video(url, compress=False):
    platform = detect_platform(url)
    if not platform:
        return None, None, "Поддерживаются только ссылки с TikTok, Instagram и YouTube."

    loop = asyncio.get_event_loop()
    filepath, error = await loop.run_in_executor(None, _download_sync, url, platform, compress)
    return filepath, platform, error


async def compress_video(input_path):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _compress_sync, input_path)


def cleanup_file(filepath):
    try:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass
