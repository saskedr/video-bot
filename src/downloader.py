import os
import re
import asyncio
import time
import yt_dlp

VIDEOS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "videos")
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

active_progress = {}


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


def _make_progress_hook(user_id):
    def hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            speed = d.get("speed") or 0
            eta = d.get("eta") or 0

            if total > 0:
                percent = min(downloaded / total * 100, 100)
            else:
                percent = 0

            active_progress[user_id] = {
                "percent": percent,
                "downloaded": downloaded,
                "total": total,
                "speed": speed,
                "eta": eta,
                "status": "downloading",
                "updated_at": time.time(),
            }
        elif d["status"] == "finished":
            active_progress[user_id] = {
                "percent": 100,
                "downloaded": 0,
                "total": 0,
                "speed": 0,
                "eta": 0,
                "status": "processing",
                "updated_at": time.time(),
            }
    return hook


def format_size(bytes_val):
    if bytes_val < 1024:
        return f"{bytes_val} Б"
    elif bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f} КБ"
    else:
        return f"{bytes_val / (1024 * 1024):.1f} МБ"


def format_speed(speed):
    if not speed or speed == 0:
        return "..."
    if speed < 1024:
        return f"{speed:.0f} Б/с"
    elif speed < 1024 * 1024:
        return f"{speed / 1024:.0f} КБ/с"
    else:
        return f"{speed / (1024 * 1024):.1f} МБ/с"


def format_eta(eta):
    if not eta or eta == 0:
        return "..."
    if eta < 60:
        return f"{int(eta)}с"
    return f"{int(eta // 60)}м {int(eta % 60)}с"


def build_progress_bar(percent, width=10):
    filled = int(width * percent / 100)
    empty = width - filled
    bar = "█" * filled + "░" * empty
    return bar


def get_progress_text(user_id, platform):
    platform_names = {"youtube": "YouTube", "tiktok": "TikTok", "instagram": "Instagram"}
    p = active_progress.get(user_id)
    if not p:
        return f"Ищу видео на {platform_names.get(platform, platform)}..."

    if p["status"] == "processing":
        return f"Почти готово, обрабатываю..."

    percent = p["percent"]
    bar = build_progress_bar(percent)
    speed_str = format_speed(p["speed"])
    eta_str = format_eta(p["eta"])

    lines = [f"Скачиваю видео\n{bar} {percent:.0f}%"]
    if p["total"] > 0:
        lines.append(f"{format_size(p['downloaded'])} / {format_size(p['total'])}")
    lines.append(f"{speed_str} · ~{eta_str}")

    return "\n".join(lines)


def _download_sync(url, platform, user_id=None, compress=False):
    ensure_videos_dir()
    output_template = os.path.join(VIDEOS_DIR, "%(id)s.%(ext)s")

    ydl_opts = _get_base_opts()
    ydl_opts["outtmpl"] = output_template
    ydl_opts.update(_get_platform_opts(platform))

    if user_id:
        ydl_opts["progress_hooks"] = [_make_progress_hook(user_id)]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                return None, "Видео не нашлось 😔"

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
                return None, "Видео не нашлось 😔"

            file_size = os.path.getsize(filename)

            if compress and file_size > MAX_FILE_SIZE:
                compressed_filename = _compress_sync(input_path=filename)
                if compressed_filename and os.path.exists(compressed_filename):
                    os.remove(filename)
                    compressed_size = os.path.getsize(compressed_filename)
                    if compressed_size > MAX_FILE_SIZE:
                        os.remove(compressed_filename)
                        return None, "Видео слишком большое даже после сжатия."
                    return compressed_filename, None
                else:
                    return filename, "Не получилось сжать видео."

            return filename, None

    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        if "Video unavailable" in error_msg or "not available" in error_msg:
            return None, "Видео недоступно или удалено."
        elif "Private video" in error_msg:
            return None, "Приватное видео, доступ ограничен."
        elif "Login required" in error_msg or "login" in error_msg.lower():
            return None, "Для скачивания нужна авторизация."
        elif "geo" in error_msg.lower() or "country" in error_msg.lower():
            return None, "Видео недоступно в этом регионе."
        return None, "Видео не нашлось 😔"
    except Exception:
        return None, "Видео не нашлось 😔"
    finally:
        if user_id and user_id in active_progress:
            del active_progress[user_id]


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


async def download_video(url, user_id=None, compress=False):
    platform = detect_platform(url)
    if not platform:
        return None, None, "Ссылка не распознана."

    loop = asyncio.get_event_loop()
    filepath, error = await loop.run_in_executor(None, _download_sync, url, platform, user_id, compress)
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
