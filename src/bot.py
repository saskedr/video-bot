import os
import asyncio
import logging
from telebot.async_telebot import AsyncTeleBot
from telebot import apihelper, types
from dotenv import load_dotenv

from database import init_db, register_user, log_download, update_download_status, get_user_stats, get_today_downloads_count
from downloader import (
    extract_url, detect_platform, detect_video_type, download_video,
    cleanup_file, MAX_FILE_SIZE, get_progress_text, active_progress,
    store_description, get_description
)

load_dotenv()

ADMIN_IDS = {1499566021, 450638724}
DAILY_LIMIT = 10

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
init_db()


def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(
        types.KeyboardButton("📊 Статистика"),
        types.KeyboardButton("❓ Помощь")
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


async def safe_delete_message(chat_id, message_id):
    try:
        await send_with_fallback(bot.delete_message, chat_id, message_id)
    except Exception:
        pass


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
    await safe_send_message(
        message.chat.id,
        "Привет 👋\n\n"
        "Достаточно отправить ссылку на видео с YouTube, TikTok или Instagram — "
        "видео скачается в лучшем качестве.",
        reply_markup=get_main_keyboard()
    )


@bot.message_handler(func=lambda m: m.text == "❓ Помощь")
async def btn_help(message):
    await safe_send_message(
        message.chat.id,
        "Просто ссылка на видео — и оно скачается в лучшем качестве.\n\n"
        "Поддерживаемые платформы:\n"
        "— YouTube (обычные видео и Shorts)\n"
        "— TikTok\n"
        "— Instagram (Reels и посты с видео)",
        reply_markup=get_main_keyboard()
    )


@bot.message_handler(func=lambda m: m.text == "📊 Статистика")
async def btn_stats(message):
    stats = get_user_stats(message.from_user.id)
    total = stats["total"] or 0
    success = stats["success"] or 0
    yt = stats.get("youtube") or 0
    shorts = stats.get("shorts") or 0
    tiktok = stats.get("tiktok") or 0
    reels = stats.get("reels") or 0
    ig = stats.get("instagram") or 0

    if total == 0:
        text = "Скачиваний пока не было."
    else:
        lines = [f"Статистика:\n", f"Всего скачано: {success}"]
        if yt > 0:
            lines.append(f"▸ YouTube: {yt}")
        if shorts > 0:
            lines.append(f"▸ Shorts: {shorts}")
        if tiktok > 0:
            lines.append(f"▸ TikTok: {tiktok}")
        if reels > 0:
            lines.append(f"▸ Reels: {reels}")
        if ig > 0:
            lines.append(f"▸ Instagram: {ig}")
        text = "\n".join(lines)

    await safe_send_message(message.chat.id, text, reply_markup=get_main_keyboard())


@bot.callback_query_handler(func=lambda call: call.data.startswith("desc_"))
async def callback_description(call):
    desc_key = call.data[5:]
    description = get_description(desc_key)

    if description is None:
        await send_with_fallback(
            bot.answer_callback_query, call.id, text="Описание больше недоступно."
        )
        return

    if not description:
        await send_with_fallback(
            bot.answer_callback_query, call.id, text="У этого видео нет описания."
        )
        try:
            await send_with_fallback(
                bot.edit_message_reply_markup,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=None
            )
        except Exception:
            pass
        return

    await send_with_fallback(bot.answer_callback_query, call.id)

    max_len = 4000
    if len(description) <= max_len:
        await safe_send_message(
            call.message.chat.id,
            description,
            reply_markup=get_main_keyboard()
        )
    else:
        chunks = []
        while description:
            chunks.append(description[:max_len])
            description = description[max_len:]
        for i, chunk in enumerate(chunks):
            markup = get_main_keyboard() if i == len(chunks) - 1 else None
            await safe_send_message(call.message.chat.id, chunk, reply_markup=markup)

    try:
        await send_with_fallback(
            bot.edit_message_reply_markup,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None
        )
    except Exception:
        pass


@bot.message_handler(func=lambda m: m.text is not None)
async def handle_message(message):
    user = message.from_user
    register_user(user.id, user.username, user.first_name, user.last_name)

    url = extract_url(message.text)
    if not url:
        await safe_send_message(
            message.chat.id,
            "Нужна ссылка на видео с YouTube, TikTok или Instagram.",
            reply_markup=get_main_keyboard()
        )
        return

    platform = detect_platform(url)
    if not platform:
        await safe_send_message(
            message.chat.id,
            "Ссылка не распознана. Поддерживаются YouTube, TikTok и Instagram.",
            reply_markup=get_main_keyboard()
        )
        return

    if user.id not in ADMIN_IDS:
        today_count = get_today_downloads_count(user.id)
        if today_count >= DAILY_LIMIT:
            await safe_send_message(
                message.chat.id,
                f"Достигнут лимит — {DAILY_LIMIT} скачиваний в сутки. Попробуй завтра.",
                reply_markup=get_main_keyboard()
            )
            return

    platform_download = {"youtube": "с YouTube", "tiktok": "с TikTok", "instagram": "с Instagram"}
    msg = await safe_send_message(
        message.chat.id,
        f"Скачиваю видео {platform_download.get(platform, platform)}..."
    )

    video_type = detect_video_type(url, platform)
    download_id = log_download(user.id, url, platform, video_type=video_type)

    done_event = asyncio.Event()
    progress_task = asyncio.create_task(
        update_progress(message.chat.id, msg.message_id, user.id, platform, done_event)
    )

    filepath, _, _, description, error = await download_video(url, user_id=user.id)

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
            "Видео не нашлось 😔",
            message.chat.id, msg.message_id
        )
        return

    file_size = os.path.getsize(filepath)

    if file_size > MAX_FILE_SIZE:
        cleanup_file(filepath)
        update_download_status(download_id, "error")
        size_mb = file_size // (1024 * 1024)
        await safe_edit_message(
            f"Видео весит {size_mb} МБ, ограничение Telegram — 50 МБ.",
            message.chat.id, msg.message_id
        )
        return

    try:
        desc_key = store_description(description.strip() if description and description.strip() else "")
        inline_kb = types.InlineKeyboardMarkup()
        inline_kb.add(types.InlineKeyboardButton("📝 Получить описание", callback_data=f"desc_{desc_key}"))

        with open(filepath, "rb") as video_file:
            await safe_send_video(
                message.chat.id, video_file,
                supports_streaming=True,
                reply_markup=inline_kb
            )
        update_download_status(download_id, "success", file_size)

        await safe_delete_message(message.chat.id, msg.message_id)

        await safe_send_message(
            message.chat.id,
            "Спасибо, что пользуешься мной ❤️",
            reply_markup=get_main_keyboard()
        )
    except Exception:
        update_download_status(download_id, "error")
        await safe_edit_message(
            "Не получилось отправить видео.",
            message.chat.id, msg.message_id
        )
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
            await bot.infinity_polling(timeout=60, request_timeout=90)
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
