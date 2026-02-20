import os
import asyncio
import logging
from telebot.async_telebot import AsyncTeleBot
from telebot import apihelper
from dotenv import load_dotenv

from database import init_db, register_user, log_download, update_download_status, get_user_stats
from downloader import extract_url, detect_platform, download_video, compress_video, cleanup_file, MAX_FILE_SIZE

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
SOCKS5_HOST = os.getenv("SOCKS5_HOST", "")
SOCKS5_PORT = os.getenv("SOCKS5_PORT", "")
SOCKS5_USERNAME = os.getenv("SOCKS5_USERNAME", "")
SOCKS5_PASSWORD = os.getenv("SOCKS5_PASSWORD", "")
MTPROTO_HOST = os.getenv("MTPROTO_HOST", "")
MTPROTO_PORT = os.getenv("MTPROTO_PORT", "")
MTPROTO_SECRET = os.getenv("MTPROTO_SECRET", "")

PROXY_MODE_SOCKS5 = "socks5"
PROXY_MODE_MTPROTO = "mtproto"
PROXY_MODE_DIRECT = "direct"

current_proxy_mode = None


def build_socks5_proxy():
    if not SOCKS5_HOST or not SOCKS5_PORT:
        return None
    if SOCKS5_USERNAME and SOCKS5_PASSWORD:
        return f"socks5://{SOCKS5_USERNAME}:{SOCKS5_PASSWORD}@{SOCKS5_HOST}:{SOCKS5_PORT}"
    return f"socks5://{SOCKS5_HOST}:{SOCKS5_PORT}"


def build_mtproto_proxy():
    if not MTPROTO_HOST or not MTPROTO_PORT:
        return None
    if MTPROTO_SECRET:
        return f"https://{MTPROTO_HOST}:{MTPROTO_PORT}/{MTPROTO_SECRET}"
    return f"https://{MTPROTO_HOST}:{MTPROTO_PORT}"


def set_proxy(mode):
    global current_proxy_mode
    if mode == PROXY_MODE_SOCKS5:
        proxy_url = build_socks5_proxy()
        if proxy_url:
            apihelper.proxy = {"https": proxy_url, "http": proxy_url}
            current_proxy_mode = PROXY_MODE_SOCKS5
            logger.info("Proxy: SOCKS5")
            return True
    elif mode == PROXY_MODE_MTPROTO:
        proxy_url = build_mtproto_proxy()
        if proxy_url:
            apihelper.proxy = {"https": proxy_url, "http": proxy_url}
            current_proxy_mode = PROXY_MODE_MTPROTO
            logger.info("Proxy: MTProto")
            return True
    elif mode == PROXY_MODE_DIRECT:
        apihelper.proxy = None
        current_proxy_mode = PROXY_MODE_DIRECT
        logger.info("Proxy: Direct")
        return True
    return False


def get_proxy_chain():
    chain = []
    if build_socks5_proxy():
        chain.append(PROXY_MODE_SOCKS5)
    if build_mtproto_proxy():
        chain.append(PROXY_MODE_MTPROTO)
    chain.append(PROXY_MODE_DIRECT)
    return chain


async def test_connection(bot_instance):
    try:
        await bot_instance.get_me()
        return True
    except Exception as e:
        logger.warning(f"Connection test failed ({current_proxy_mode}): {e}")
        return False


async def connect_with_fallback(bot_instance):
    chain = get_proxy_chain()
    logger.info(f"Proxy chain: {' -> '.join(chain)}")

    for mode in chain:
        if set_proxy(mode):
            if await test_connection(bot_instance):
                logger.info(f"Connected: {mode}")
                return mode
            logger.warning(f"Failed: {mode}")

    logger.error("All connection methods failed")
    return None


async def send_with_fallback(func, *args, **kwargs):
    chain = get_proxy_chain()
    current_idx = 0
    if current_proxy_mode in chain:
        current_idx = chain.index(current_proxy_mode)

    ordered_chain = chain[current_idx:] + chain[:current_idx]

    last_error = None
    for mode in ordered_chain:
        try:
            set_proxy(mode)
            return await func(*args, **kwargs)
        except Exception as e:
            last_error = e
            logger.warning(f"Send failed via {mode}: {e}")
            continue

    if last_error:
        raise last_error


bot = AsyncTeleBot(TOKEN)
pending_compress = {}
init_db()


async def safe_send_message(chat_id, text, **kwargs):
    return await send_with_fallback(bot.send_message, chat_id, text, **kwargs)


async def safe_edit_message(text, chat_id, message_id, **kwargs):
    return await send_with_fallback(bot.edit_message_text, text, chat_id, message_id, **kwargs)


async def safe_send_video(chat_id, video, **kwargs):
    return await send_with_fallback(bot.send_video, chat_id, video, **kwargs)


@bot.message_handler(commands=["start"])
async def cmd_start(message):
    user = message.from_user
    register_user(user.id, user.username, user.first_name, user.last_name)
    await safe_send_message(
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
async def cmd_help(message):
    await safe_send_message(
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
async def cmd_stats(message):
    stats = get_user_stats(message.from_user.id)
    await safe_send_message(
        message.chat.id,
        f"Твоя статистика:\n\n"
        f"Всего запросов: {stats['total']}\n"
        f"Успешных: {stats['success']}\n"
        f"Ошибок: {stats['errors']}"
    )


@bot.message_handler(func=lambda m: m.text and m.from_user.id in pending_compress)
async def handle_compress_response(message):
    if message.from_user.id not in pending_compress:
        return

    data = pending_compress.pop(message.from_user.id)
    text = message.text.strip().lower()

    if text in ["да", "yes", "ок", "ok", "давай", "сжать", "сжимай"]:
        msg = await safe_send_message(message.chat.id, "Сжимаю видео, подожди...")

        original_filepath = data.get("filepath")

        if not original_filepath or not os.path.exists(original_filepath):
            filepath, _, error = await download_video(data["url"], compress=True)
            if error:
                cleanup_file(filepath)
                update_download_status(data["download_id"], "error")
                await safe_edit_message(f"Ошибка: {error}", message.chat.id, msg.message_id)
                return
        else:
            filepath = await compress_video(original_filepath)
            cleanup_file(original_filepath)
            if not filepath or not os.path.exists(filepath):
                update_download_status(data["download_id"], "error")
                await safe_edit_message("Не удалось сжать видео.", message.chat.id, msg.message_id)
                return
            compressed_size = os.path.getsize(filepath)
            if compressed_size > MAX_FILE_SIZE:
                cleanup_file(filepath)
                update_download_status(data["download_id"], "error")
                await safe_edit_message(
                    "Даже после сжатия файл слишком большой для отправки в Telegram (>50 МБ).",
                    message.chat.id, msg.message_id
                )
                return

        if filepath and os.path.exists(filepath):
            file_size = os.path.getsize(filepath)
            try:
                with open(filepath, "rb") as video_file:
                    await safe_send_video(message.chat.id, video_file, supports_streaming=True)
                update_download_status(data["download_id"], "success", file_size, compressed=True)
                await safe_edit_message("Готово! Видео сжато и отправлено.", message.chat.id, msg.message_id)
            except Exception:
                update_download_status(data["download_id"], "error")
                await safe_edit_message("Не удалось отправить видео.", message.chat.id, msg.message_id)
            finally:
                cleanup_file(filepath)
        else:
            update_download_status(data["download_id"], "error")
            await safe_edit_message("Не удалось сжать видео.", message.chat.id, msg.message_id)
    else:
        update_download_status(data["download_id"], "cancelled")
        cleanup_file(data.get("filepath"))
        await safe_send_message(message.chat.id, "Хорошо, скачивание отменено.")


@bot.message_handler(func=lambda m: m.text is not None)
async def handle_message(message):
    user = message.from_user
    register_user(user.id, user.username, user.first_name, user.last_name)

    url = extract_url(message.text)
    if not url:
        await safe_send_message(
            message.chat.id,
            "Отправь мне ссылку на видео с YouTube, TikTok или Instagram."
        )
        return

    platform = detect_platform(url)
    if not platform:
        await safe_send_message(
            message.chat.id,
            "Поддерживаются только ссылки с YouTube, TikTok и Instagram."
        )
        return

    platform_names = {"youtube": "YouTube", "tiktok": "TikTok", "instagram": "Instagram"}
    msg = await safe_send_message(
        message.chat.id,
        f"Скачиваю видео с {platform_names.get(platform, platform)}..."
    )

    download_id = log_download(user.id, url, platform)
    filepath, _, error = await download_video(url)

    if error:
        cleanup_file(filepath)
        update_download_status(download_id, "error")
        await safe_edit_message(f"Ошибка: {error}", message.chat.id, msg.message_id)
        return

    if not filepath or not os.path.exists(filepath):
        update_download_status(download_id, "error")
        await safe_edit_message("Не удалось скачать видео.", message.chat.id, msg.message_id)
        return

    file_size = os.path.getsize(filepath)

    if file_size > MAX_FILE_SIZE:
        pending_compress[user.id] = {"url": url, "download_id": download_id, "filepath": filepath}
        await safe_edit_message(
            f"Видео слишком большое ({file_size // (1024*1024)} МБ), "
            f"лимит Telegram — 50 МБ.\n\n"
            f"Хочешь, чтобы я попробовал сжать видео? (да/нет)",
            message.chat.id,
            msg.message_id
        )
        return

    try:
        with open(filepath, "rb") as video_file:
            await safe_send_video(message.chat.id, video_file, supports_streaming=True)
        update_download_status(download_id, "success", file_size)
        await safe_edit_message("Готово!", message.chat.id, msg.message_id)
    except Exception:
        update_download_status(download_id, "error")
        await safe_edit_message("Не удалось отправить видео.", message.chat.id, msg.message_id)
    finally:
        cleanup_file(filepath)


async def main():
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        print("ОШИБКА: Установите TELEGRAM_BOT_TOKEN в Secrets")
        return

    mode = await connect_with_fallback(bot)
    if not mode:
        logger.error("Could not connect to Telegram API")
        print("ОШИБКА: Не удалось подключиться к Telegram API ни одним способом")
        return

    logger.info(f"Bot started, mode: {mode}")
    print(f"Бот запущен (режим: {mode})")

    while True:
        try:
            await bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            new_mode = await connect_with_fallback(bot)
            if new_mode:
                logger.info(f"Reconnected: {new_mode}")
                await asyncio.sleep(5)
            else:
                logger.error("Reconnection failed, retrying in 30s...")
                await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main())
