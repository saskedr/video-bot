# Telegram Video Downloader Bot

## Overview
Telegram bot that downloads videos from TikTok, Instagram, and YouTube (including Shorts) and sends them to users. Uses SOCKS5 proxy to connect to Telegram API.

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
  bot.py          - Main bot file with handlers
  database.py     - SQLite database module (users, downloads)
  downloader.py   - Video download module (yt-dlp)
```

## Features
- Download videos from YouTube (regular + Shorts), TikTok, Instagram
- Best quality download via yt-dlp
- SOCKS5 proxy support
- SQLite logging of all downloads and users
- File size check (50MB Telegram limit)
- Video compression option via ffmpeg if file too large
- User statistics (/stats command)

## Required Secrets
- TELEGRAM_BOT_TOKEN - Bot token from @BotFather
- SOCKS5_HOST - SOCKS5 proxy host
- SOCKS5_PORT - SOCKS5 proxy port
- SOCKS5_USERNAME - SOCKS5 proxy username
- SOCKS5_PASSWORD - SOCKS5 proxy password

## Running
The bot runs via `python src/bot.py` and uses infinity_polling.
