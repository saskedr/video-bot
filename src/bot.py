import os
import asyncio
import logging
from telebot.async_telebot import AsyncTeleBot
from telebot import apihelper, types
from dotenv import load_dotenv

from database import init_db, register_user, log_download, update_download_status, get_user_stats
from downloader import (
    extract_url, detect_platform, download_video, compress_video,
    cleanup_file, MAX_FILE_SIZE, get_progress_text, active_progress
)

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


def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(types.KeyboardButton("📊 статистика"), types.KeyboardButton("❓ помощь"))
    return markup


def get_compress_keyboard():
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("👍 сжать", callback_data="compress_yes"),
        types.InlineKeyboardButton("👎 не надо", callback_data="compress_no"),
    )
    return markup


async def safe_send_message(chat_id, text, **kwargs):
    return await send_with_fallback(bot.send_message, chat_id, text, **kwargs)


async def safe_edit_message(text, chat_id, message_id, **kwargs):
    try:
        return await send_with_fallback(bot.edit_message_text, text, chat_id, message_id, **kwargs)
    except Exception:
        pass


async def safe_send_video(chat_id, video, **kwargs):
    return await send_with_fallback(bot.send_video, chat_id, video, **kwargs)


async def update_progress(chat_id, message_id, user_id, platform, done_event):
    last_text = ""
    while not done_event.is_set():
        text = get_progress_text(user_id, platform)
        if text and text != last_text:
            await safe_edit_message(text, chat_id, message_id)
            last_text = text
        await asyncio.sleep(2)


@bot.message_handler(commands=["start"])
async def cmd_start(message):
    user = message.from_user
    register_user(user.id, user.username, user.first_name, user.last_name)
    name = user.first_name or "друг"
    await safe_send_message(
        message.chat.id,
        f"йо, {name}! 👋\n\n"
        f"кидай ссылку на видео и я скачаю в лучшем качестве:\n\n"
        f"🎬 YouTube (и Shorts тоже)\n"
        f"🎵 TikTok\n"
        f"📸 Instagram\n\n"
        f"просто кидай ссылку, остальное сам разберу 😎",
        reply_markup=get_main_keyboard()
    )


@bot.message_handler(func=lambda m: m.text == "❓ помощь")
async def btn_help(message):
    await safe_send_message(
        message.chat.id,
        "всё просто — кидаешь ссылку, я качаю 🤙\n\n"
        "что умею:\n"
        "🎬 YouTube — обычные видео и Shorts\n"
        "🎵 TikTok — любые видео\n"
        "📸 Instagram — Reels и посты\n\n"
        "если видос больше 50 МБ, предложу сжать.\n"
        "качаю в лучшем качестве, не переживай 💪",
        reply_markup=get_main_keyboard()
    )


@bot.message_handler(func=lambda m: m.text == "📊 статистика")
async def btn_stats(message):
    stats = get_user_stats(message.from_user.id)
    total = stats["total"] or 0
    success = stats["success"] or 0
    errors = stats["errors"] or 0

    if total == 0:
        text = "ты ещё ничего не скачивал 🤷\nкидай ссылку, начнём!"
    elif errors == 0:
        text = (
            f"твоя стата 📊\n\n"
            f"всего: {total}\n"
            f"успешно: {success} ✅\n\n"
            f"ни одной ошибки, красавчик 🔥"
        )
    else:
        text = (
            f"твоя стата 📊\n\n"
            f"всего: {total}\n"
            f"успешно: {success} ✅\n"
            f"не вышло: {errors} ❌"
        )

    await safe_send_message(message.chat.id, text, reply_markup=get_main_keyboard())


@bot.callback_query_handler(func=lambda call: call.data.startswith("compress_"))
async def handle_compress_callback(call):
    user_id = call.from_user.id
    if user_id not in pending_compress:
        await bot.answer_callback_query(call.id, "запрос устарел 🤷")
        return

    data = pending_compress.pop(user_id)
    await bot.answer_callback_query(call.id)

    if call.data == "compress_yes":
        await safe_edit_message(
            "⚡ сжимаю видео, подожди...",
            call.message.chat.id, call.message.message_id
        )

        original_filepath = data.get("filepath")

        if not original_filepath or not os.path.exists(original_filepath):
            filepath, _, error = await download_video(data["url"], user_id=user_id, compress=True)
            if error:
                cleanup_file(filepath)
                update_download_status(data["download_id"], "error")
                await safe_edit_message(error, call.message.chat.id, call.message.message_id)
                return
        else:
            filepath = await compress_video(original_filepath)
            cleanup_file(original_filepath)
            if not filepath or not os.path.exists(filepath):
                update_download_status(data["download_id"], "error")
                await safe_edit_message(
                    "не получилось сжать 😕",
                    call.message.chat.id, call.message.message_id
                )
                return
            compressed_size = os.path.getsize(filepath)
            if compressed_size > MAX_FILE_SIZE:
                cleanup_file(filepath)
                update_download_status(data["download_id"], "error")
                await safe_edit_message(
                    "даже после сжатия слишком тяжёлый для тг (>50 МБ) 😔",
                    call.message.chat.id, call.message.message_id
                )
                return

        if filepath and os.path.exists(filepath):
            file_size = os.path.getsize(filepath)
            try:
                with open(filepath, "rb") as video_file:
                    await safe_send_video(call.message.chat.id, video_file, supports_streaming=True)
                update_download_status(data["download_id"], "success", file_size, compressed=True)
                await safe_edit_message(
                    "сжал и отправил ✅",
                    call.message.chat.id, call.message.message_id
                )
            except Exception:
                update_download_status(data["download_id"], "error")
                await safe_edit_message(
                    "не смог отправить видео 😕",
                    call.message.chat.id, call.message.message_id
                )
            finally:
                cleanup_file(filepath)
        else:
            update_download_status(data["download_id"], "error")
            await safe_edit_message(
                "не получилось сжать 😕",
                call.message.chat.id, call.message.message_id
            )
    else:
        update_download_status(data["download_id"], "cancelled")
        cleanup_file(data.get("filepath"))
        await safe_edit_message(
            "ок, отменил 👌",
            call.message.chat.id, call.message.message_id
        )


@bot.message_handler(func=lambda m: m.text is not None)
async def handle_message(message):
    user = message.from_user
    register_user(user.id, user.username, user.first_name, user.last_name)

    url = extract_url(message.text)
    if not url:
        await safe_send_message(
            message.chat.id,
            "кинь ссылку на видео с YouTube, TikTok или Instagram 🔗",
            reply_markup=get_main_keyboard()
        )
        return

    platform = detect_platform(url)
    if not platform:
        await safe_send_message(
            message.chat.id,
            "я пока умею только YouTube, TikTok и Instagram 🙅",
            reply_markup=get_main_keyboard()
        )
        return

    platform_names = {"youtube": "YouTube", "tiktok": "TikTok", "instagram": "Instagram"}
    msg = await safe_send_message(
        message.chat.id,
        f"🔍 ищу видео на {platform_names.get(platform, platform)}..."
    )

    download_id = log_download(user.id, url, platform)

    done_event = asyncio.Event()
    progress_task = asyncio.create_task(
        update_progress(message.chat.id, msg.message_id, user.id, platform, done_event)
    )

    filepath, _, error = await download_video(url, user_id=user.id)

    done_event.set()
    try:
        await progress_task
    except Exception:
        pass

    if error:
        cleanup_file(filepath)
        update_download_status(download_id, "error")
        await safe_edit_message(error, message.chat.id, msg.message_id)
        return

    if not filepath or not os.path.exists(filepath):
        update_download_status(download_id, "error")
        await safe_edit_message(
            "не получилось скачать 😕",
            message.chat.id, msg.message_id
        )
        return

    file_size = os.path.getsize(filepath)

    if file_size > MAX_FILE_SIZE:
        pending_compress[user.id] = {"url": url, "download_id": download_id, "filepath": filepath}
        await safe_edit_message(
            f"видос весит {file_size // (1024*1024)} МБ, "
            f"а лимит тг — 50 МБ 😬\n\n"
            f"сжать?",
            message.chat.id,
            msg.message_id,
            reply_markup=get_compress_keyboard()
        )
        return

    await safe_edit_message("📤 отправляю...", message.chat.id, msg.message_id)

    try:
        with open(filepath, "rb") as video_file:
            await safe_send_video(message.chat.id, video_file, supports_streaming=True)
        update_download_status(download_id, "success", file_size)
        await safe_edit_message("готово ✅", message.chat.id, msg.message_id)
    except Exception:
        update_download_status(download_id, "error")
        await safe_edit_message("не смог отправить видео 😕", message.chat.id, msg.message_id)
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
        print("ОШИБКА: Не удалось подключиться к Telegram API")
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
