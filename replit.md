# Telegram Video Downloader Bot

## Overview
Telegram bot that downloads videos from TikTok, Instagram, and YouTube (including Shorts) and sends them to users. Uses cascading proxy fallback for Telegram API connection. Video downloading works directly without proxy.

## Stack
- Python 3.11
- pyTelegramBotAPI (telebot)
- yt-dlp for video downloading
- python-dotenv for config
- SQLite3 for database
- ffmpeg for video compression
- PySocks for SOCKS5 proxy

## Project Structure
```
src/
  bot.py          - Main bot file with handlers, proxy fallback logic
  database.py     - SQLite database module (users, downloads)
  downloader.py   - Video download module (yt-dlp), platform-specific configs
```

## Architecture
- **Proxy for Telegram only**: SOCKS5/MTProto proxy is used ONLY for Telegram Bot API calls (sending messages, videos). Video downloading via yt-dlp goes directly without proxy.
- **Proxy fallback chain**: 1) SOCKS5 -> 2) MTProto -> 3) Direct connection. If current method fails, automatically tries next.
- **Platform-specific download configs**: Each platform (YouTube, TikTok, Instagram) has tailored yt-dlp settings (headers, format, user-agent).

## Features
- Download videos from YouTube (regular + Shorts), TikTok, Instagram
- Best quality download via yt-dlp with geo_bypass
- Cascading proxy: SOCKS5 -> MTProto -> Direct
- Auto-reconnect on connection failure
- SQLite logging of all downloads and users
- File size check (50MB Telegram limit)
- Video compression option via ffmpeg if file too large
- User statistics (/stats command)

## Required Secrets
- TELEGRAM_BOT_TOKEN - Bot token from @BotFather
- SOCKS5_HOST - SOCKS5 proxy host
- SOCKS5_PORT - SOCKS5 proxy port
- SOCKS5_USERNAME - SOCKS5 proxy username (optional)
- SOCKS5_PASSWORD - SOCKS5 proxy password (optional)
- MTPROTO_HOST - MTProto proxy host (optional)
- MTPROTO_PORT - MTProto proxy port (optional)
- MTPROTO_SECRET - MTProto proxy secret (optional)

## Running
The bot runs via `python src/bot.py` and uses infinity_polling with auto-reconnect.
