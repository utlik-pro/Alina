#!/bin/bash
# Проверка статуса бота и анализ логов

echo ""
echo "🔍 =============================================="
echo "   Crystal Lab Bot - Status Check"
echo "   Version: 2.2 (Buffering + New Prices)"
echo "================================================"
echo ""

# 1. Проверка запущен ли бот
echo "📊 1. Проверка процесса бота..."
BOT_PID=$(ps aux | grep "python.*bot.py" | grep -v grep | awk '{print $2}')

if [ -z "$BOT_PID" ]; then
    echo "   ❌ БОТ НЕ ЗАПУЩЕН!"
    echo "   Запустите: cd /Users/admin/Alina/massage-booking-bot && .venv/bin/python bot.py > bot.log 2>&1 &"
    exit 1
else
    echo "   ✅ Бот запущен (PID: $BOT_PID)"
fi

# 2. Проверка логов на ошибки
echo ""
echo "🔍 2. Проверка ошибок в логах (последние 100 строк)..."
ERROR_COUNT=$(tail -100 bot.log | grep -c "ERROR")
TRACEBACK_COUNT=$(tail -100 bot.log | grep -c "Traceback")

if [ "$ERROR_COUNT" -gt 0 ] || [ "$TRACEBACK_COUNT" -gt 0 ]; then
    echo "   ⚠️  Найдено ошибок: $ERROR_COUNT, трейсбеков: $TRACEBACK_COUNT"
    echo "   Последние ошибки:"
    tail -100 bot.log | grep -A 3 "ERROR" | tail -10
else
    echo "   ✅ Ошибок не обнаружено"
fi

# 3. Проверка буферизации
echo ""
echo "🔍 3. Проверка работы буферизации..."
BUFFER_COUNT=$(grep -c "добавлено в буфер" bot.log)
PROCESS_COUNT=$(grep -c "обработка.*накопленных сообщений" bot.log)

if [ "$BUFFER_COUNT" -gt 0 ]; then
    echo "   ✅ Буферизация работает ($BUFFER_COUNT сообщений в буфере)"
    echo "   ✅ Обработано групп: $PROCESS_COUNT"

    # Показать последние примеры
    echo ""
    echo "   Последние буферизованные сообщения:"
    grep "обработка.*накопленных сообщений" bot.log | tail -3
else
    echo "   ⚠️  Буферизация еще не использовалась (нет тестовых сообщений)"
fi

# 4. Проверка новых цен
echo ""
echo "🔍 4. Проверка новых цен в логах..."

# Russian gelish
RUSSIAN_PRICE=$(grep "Russian gelish manicure" bot.log | grep "200.0 AED" | tail -1)
if [ ! -z "$RUSSIAN_PRICE" ]; then
    echo "   ✅ Russian gelish manicure: 200 AED (новая цена)"
else
    OLD_PRICE=$(grep "Manicure" bot.log | grep "80.0 AED" | tail -1)
    if [ ! -z "$OLD_PRICE" ]; then
        echo "   ❌ Обнаружена старая цена Manicure: 80 AED!"
    else
        echo "   ⚠️  Manicure еще не бронировался"
    fi
fi

# Deep cleansing
DEEP_CLEANSING=$(grep "Deep facial cleansing" bot.log | grep "420.0 AED" | tail -1)
if [ ! -z "$DEEP_CLEANSING" ]; then
    echo "   ✅ Deep facial cleansing: 420 AED, 90 min (новая цена)"
else
    OLD_DEEP=$(grep "Deep face cleansing" bot.log | grep "250.0 AED" | tail -1)
    if [ ! -z "$OLD_DEEP" ]; then
        echo "   ❌ Обнаружена старая цена Deep cleansing: 250 AED!"
    else
        echo "   ⚠️  Deep cleansing еще не бронировался"
    fi
fi

# 5. Статистика бронирований
echo ""
echo "🔍 5. Статистика бронирований..."
TOTAL_BOOKINGS=$(grep -c "Created booking" bot.log)
TODAY_BOOKINGS=$(grep "Created booking" bot.log | grep "2025-11-05" | wc -l | xargs)

echo "   📊 Всего бронирований: $TOTAL_BOOKINGS"
echo "   📊 Сегодня (05.11.2025): $TODAY_BOOKINGS"

if [ "$TODAY_BOOKINGS" -gt 0 ]; then
    echo ""
    echo "   Последние 3 бронирования:"
    grep "Created booking" bot.log | tail -3
fi

# 6. Проверка уведомлений
echo ""
echo "🔍 6. Проверка уведомлений администраторам..."
NOTIFICATIONS=$(grep -c "Notifications enabled" bot.log)

if [ "$NOTIFICATIONS" -gt 0 ]; then
    GROUP_ID=$(grep "Notifications enabled for group" bot.log | tail -1 | awk -F': ' '{print $2}')
    echo "   ✅ Уведомления включены (Group ID: $GROUP_ID)"
else
    echo "   ❌ Уведомления не настроены"
fi

# 7. Время работы бота
echo ""
echo "🔍 7. Время работы бота..."
START_TIME=$(grep "🤖 Crystal Lab Booking Bot запущен!" bot.log | tail -1 | awk '{print $1, $2}')
if [ ! -z "$START_TIME" ]; then
    echo "   🕐 Последний запуск: $START_TIME"
fi

# 8. Модель GPT
echo ""
echo "🔍 8. Конфигурация AI..."
MODEL=$(grep "Модель:" bot.log | tail -1 | awk -F': ' '{print $2}')
if [ ! -z "$MODEL" ]; then
    echo "   🤖 Модель: $MODEL"
fi

# Финальная сводка
echo ""
echo "================================================"
echo "✅ ИТОГОВАЯ СВОДКА:"
echo "================================================"

ISSUES=0

if [ -z "$BOT_PID" ]; then
    echo "❌ Бот не запущен"
    ISSUES=$((ISSUES + 1))
else
    echo "✅ Бот работает (PID: $BOT_PID)"
fi

if [ "$ERROR_COUNT" -gt 0 ] || [ "$TRACEBACK_COUNT" -gt 0 ]; then
    echo "⚠️  Есть ошибки в логах ($ERROR_COUNT errors, $TRACEBACK_COUNT tracebacks)"
    ISSUES=$((ISSUES + 1))
else
    echo "✅ Нет ошибок в логах"
fi

if [ "$BUFFER_COUNT" -gt 0 ]; then
    echo "✅ Буферизация работает ($PROCESS_COUNT обработано)"
else
    echo "⚠️  Буферизация не тестировалась"
fi

if [ ! -z "$RUSSIAN_PRICE" ]; then
    echo "✅ Новые цены применены"
else
    echo "⚠️  Новые цены не проверены"
fi

echo ""
if [ "$ISSUES" -eq 0 ]; then
    echo "🎉 ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ!"
else
    echo "⚠️  Обнаружено проблем: $ISSUES"
    echo "   Проверьте детали выше"
fi

echo ""
echo "================================================"
echo ""
