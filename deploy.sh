#!/bin/bash

echo "🔄 Начинаю деплой..."

# Переходим в папку проекта
cd /home/botuser/video-bot

# Переключаемся на пользователя botuser для git операций
sudo -u botuser bash << EOF
echo "📥 Pulling latest code..."
cd /home/botuser/video-bot
git pull origin main

echo "📦 Updating dependencies..."
source venv/bin/activate
pip install -r requirements.txt
EOF

# Перезапускаем сервис (от root)
echo "🔄 Restarting bot service..."
systemctl restart video-bot

echo "✅ Деплой завершен!"
systemctl status video-bot --no-pager
