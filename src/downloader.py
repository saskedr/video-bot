import os
import re
import subprocess
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
    elif "youtube.com" in url_lower or "youtu.be" in url_lower or "youtube.com/shorts" in url_lower:
        return "youtube"
    return None


def extract_url(text):
    url_pattern = r'https?://[^\s<>\"\']+|www\.[^\s<>\"\']+'
    match = re.search(url_pattern, text)
    return match.group(0) if match else None


def download_video(url, compress=False):
    ensure_videos_dir()

    platform = detect_platform(url)
    if not platform:
        return None, None, "Поддерживаются только ссылки с TikTok, Instagram и YouTube."

    output_template = os.path.join(VIDEOS_DIR, "%(id)s.%(ext)s")

    ydl_opts = {
        "outtmpl": output_template,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 3,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                return None, platform, "Не удалось найти видео по этой ссылке."

            filename = ydl.prepare_filename(info)
            if not filename.endswith(".mp4"):
                base = os.path.splitext(filename)[0]
                filename = base + ".mp4"

            if not os.path.exists(filename):
                for f in os.listdir(VIDEOS_DIR):
                    if f.startswith(info.get("id", "")) and f.endswith(".mp4"):
                        filename = os.path.join(VIDEOS_DIR, f)
                        break

            if not os.path.exists(filename):
                return None, platform, "Не удалось найти скачанный файл."

            file_size = os.path.getsize(filename)

            if compress and file_size > MAX_FILE_SIZE:
                compressed_filename = compress_video(filename)
                if compressed_filename and os.path.exists(compressed_filename):
                    os.remove(filename)
                    compressed_size = os.path.getsize(compressed_filename)
                    if compressed_size > MAX_FILE_SIZE:
                        os.remove(compressed_filename)
                        return None, platform, "Даже после сжатия файл слишком большой для отправки в Telegram (>50 МБ)."
                    return compressed_filename, platform, None
                else:
                    return filename, platform, "Не удалось сжать видео."

            return filename, platform, None

    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        if "Video unavailable" in error_msg or "not available" in error_msg:
            return None, platform, "Видео недоступно или было удалено."
        elif "Private video" in error_msg:
            return None, platform, "Это приватное видео, доступ к нему ограничен."
        elif "Login required" in error_msg or "login" in error_msg.lower():
            return None, platform, "Для скачивания этого видео требуется авторизация."
        return None, platform, f"Ошибка при скачивании: видео не найдено или недоступно."
    except Exception as e:
        return None, platform, f"Произошла непредвиденная ошибка при скачивании."


def compress_video(input_path):
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


def cleanup_file(filepath):
    try:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass
