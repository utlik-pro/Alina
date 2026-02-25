"""Тестовый скрипт для проверки ответов бота"""
import sys
sys.path.insert(0, '.')

# Симуляция того, что бот должен ответить
test_prompt = """
Клиент спрашивает: "I want body massage"

Что должен ответить бот согласно инструкциям?
"""

# Извлекаем пример из промпта
with open('agents/booking_agent.py', 'r') as f:
    content = f.read()
    
    # Находим пример ответа
    if '- Body massage: "Body massage different techniques:' in content:
        start = content.find('- Body massage: "Body massage different techniques:')
        end = content.find('Which duration would you like?"', start) + 32
        example = content[start:end]
        
        print("=== ПРИМЕР ОТВЕТА БОТА (из промпта) ===")
        print(example)
        print()
        
        # Проверяем наличие VAT
        if '+ 5% VAT' in example or '+ VAT' in example:
            print("❌ ОШИБКА: В примере ответа есть упоминание VAT!")
        else:
            print("✅ ПРАВИЛЬНО: В примере ответа НЕТ упоминания VAT")
            
        # Показываем что должно быть в ответе
        print("\n=== ЧТО КЛИЕНТ ДОЛЖЕН УВИДЕТЬ ===")
        print("Body massage different techniques:")
        print("  - 60 min: 350 AED")
        print("  - 90 min: 460 AED")
        print("  Which duration would you like?")
