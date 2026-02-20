import os
import telebot
from telebot import apihelper
from dotenv import load_dotenv

from database import init_db, register_user, log_download, update_download_status, get_user_stats
from downloader import extract_url, detect_platform, download_video, cleanup_file, MAX_FILE_SIZE

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
SOCKS5_HOST = os.getenv("SOCKS5_HOST", "")
SOCKS5_PORT = os.getenv("SOCKS5_PORT", "")
SOCKS5_USERNAME = os.getenv("SOCKS5_USERNAME", "")
SOCKS5_PASSWORD = os.getenv("SOCKS5_PASSWORD", "")

if SOCKS5_HOST and SOCKS5_PORT:
    proxy_url = f"socks5://{SOCKS5_USERNAME}:{SOCKS5_PASSWORD}@{SOCKS5_HOST}:{SOCKS5_PORT}"
    apihelper.proxy = {"https": proxy_url, "http": proxy_url}

bot = telebot.TeleBot(TOKEN)

pending_compress = {}

init_db()


@bot.message_handler(commands=["start"])
def cmd_start(message):
    user = message.from_user
    register_user(user.id, user.username, user.first_name, user.last_name)
    bot.send_message(
        message.chat.id,
        "Привет! Я бот для скачивания видео.\n\n"
        "Отправь мне ссылку на видео с:\n"
        "• YouTube (включая Shorts)\n"
        "• TikTok\n"
        "• Instagram\n\n"
        "Я скачаю видео в лучшем качестве и отправлю тебе!\n\n"
        "Команды:\n"
        "/stats — твоя статистика скачиваний\n"
        "/help — помощь"
    )


@bot.message_handler(commands=["help"])
def cmd_help(message):
    bot.send_message(
        message.chat.id,
        "Просто отправь мне ссылку на видео с YouTube, TikTok или Instagram, "
        "и я скачаю его для тебя в лучшем качестве.\n\n"
        "Поддерживаемые платформы:\n"
        "• YouTube — обычные видео и Shorts\n"
        "• TikTok — видео\n"
        "• Instagram — Reels и посты с видео\n\n"
        "Если видео больше 50 МБ, я предложу сжать его."
    )


@bot.message_handler(commands=["stats"])
def cmd_stats(message):
    stats = get_user_stats(message.from_user.id)
    bot.send_message(
        message.chat.id,
        f"📊 Твоя статистика:\n\n"
        f"Всего запросов: {stats['total']}\n"
        f"Успешных: {stats['success']}\n"
        f"Ошибок: {stats['errors']}"
    )


@bot.message_handler(func=lambda m: m.text and m.from_user.id in pending_compress)
def handle_compress_response(message):
    if message.from_user.id not in pending_compress:
        return

    data = pending_compress.pop(message.from_user.id)
    text = message.text.strip().lower()

    if text in ["да", "yes", "ок", "ok", "давай", "сжать", "сжимай"]:
        msg = bot.send_message(message.chat.id, "⏳ Сжимаю видео, подожди...")

        filepath, platform, error = download_video(data["url"], compress=True)

        if error:
            cleanup_file(filepath)
            update_download_status(data["download_id"], "error")
            bot.edit_message_text(f"❌ {error}", message.chat.id, msg.message_id)
            return

        if filepath:
            file_size = os.path.getsize(filepath)
            try:
                with open(filepath, "rb") as video_file:
                    bot.send_video(message.chat.id, video_file, supports_streaming=True)
                update_download_status(data["download_id"], "success", file_size, compressed=True)
                bot.edit_message_text("✅ Готово! Видео сжато и отправлено.", message.chat.id, msg.message_id)
            except Exception:
                update_download_status(data["download_id"], "error")
                bot.edit_message_text("❌ Не удалось отправить видео.", message.chat.id, msg.message_id)
            finally:
                cleanup_file(filepath)
    else:
        update_download_status(data["download_id"], "cancelled")
        bot.send_message(message.chat.id, "Хорошо, скачивание отменено.")


@bot.message_handler(func=lambda m: m.text is not None)
def handle_message(message):
    user = message.from_user
    register_user(user.id, user.username, user.first_name, user.last_name)

    url = extract_url(message.text)
    if not url:
        bot.send_message(
            message.chat.id,
            "Отправь мне ссылку на видео с YouTube, TikTok или Instagram."
        )
        return

    platform = detect_platform(url)
    if not platform:
        bot.send_message(
            message.chat.id,
            "Поддерживаются только ссылки с YouTube, TikTok и Instagram."
        )
        return

    platform_names = {"youtube": "YouTube", "tiktok": "TikTok", "instagram": "Instagram"}
    msg = bot.send_message(
        message.chat.id,
        f"⏳ Скачиваю видео с {platform_names.get(platform, platform)}..."
    )

    download_id = log_download(user.id, url, platform)
    filepath, _, error = download_video(url)

    if error:
        cleanup_file(filepath)
        update_download_status(download_id, "error")
        bot.edit_message_text(f"❌ {error}", message.chat.id, msg.message_id)
        return

    if not filepath or not os.path.exists(filepath):
        update_download_status(download_id, "error")
        bot.edit_message_text("❌ Не удалось скачать видео.", message.chat.id, msg.message_id)
        return

    file_size = os.path.getsize(filepath)

    if file_size > MAX_FILE_SIZE:
        cleanup_file(filepath)
        pending_compress[user.id] = {"url": url, "download_id": download_id}
        bot.edit_message_text(
            f"⚠️ Видео слишком большое ({file_size // (1024*1024)} МБ), "
            f"лимит Telegram — 50 МБ.\n\n"
            f"Хочешь, чтобы я попробовал сжать видео? (да/нет)",
            message.chat.id,
            msg.message_id
        )
        return

    try:
        with open(filepath, "rb") as video_file:
            bot.send_video(message.chat.id, video_file, supports_streaming=True)
        update_download_status(download_id, "success", file_size)
        bot.edit_message_text("✅ Готово!", message.chat.id, msg.message_id)
    except Exception:
        update_download_status(download_id, "error")
        bot.edit_message_text("❌ Не удалось отправить видео.", message.chat.id, msg.message_id)
    finally:
        cleanup_file(filepath)


if __name__ == "__main__":
    if not TOKEN:
        print("ОШИБКА: Установите TELEGRAM_BOT_TOKEN в Secrets")
        exit(1)
    print("Бот запущен...")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
