#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const readline = require('readline');

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout
});

// Функция для получения ввода от пользователя
function question(prompt) {
  return new Promise((resolve) => {
    rl.question(prompt, resolve);
  });
}

// Функция для генерации номера договора
function generateContractNumber() {
  const today = new Date();
  const day = today.getDate().toString().padStart(2, '0');
  const month = (today.getMonth() + 1).toString().padStart(2, '0');
  const year = today.getFullYear().toString().slice(-2); // Берем только последние 2 цифры года
  
  const dateStr = `${day}${month}`; // ДДММ
  const yearMonth = `${year}-${month}`; // ГГ-ММ
  
  const contractsDir = path.join(__dirname, '../docs/contracts');
  
  if (!fs.existsSync(contractsDir)) {
    return `${dateStr}/${yearMonth}-01/42`;
  }
  
  // Ищем существующие договоры за сегодня
  const files = fs.readdirSync(contractsDir)
    .filter(file => file.startsWith('contract_') && file.endsWith('.md'))
    .map(file => {
      const match = file.match(new RegExp(`contract_${dateStr}/${yearMonth}-(\\d{2})/42`));
      return match ? parseInt(match[1]) : null;
    })
    .filter(Boolean);
  
  const contractNumber = files.length === 0 ? 1 : Math.max(...files) + 1;
  const contractNumberStr = contractNumber.toString().padStart(2, '0');
  
  return `${dateStr}/${yearMonth}-${contractNumberStr}/42`;
}

// Функция для создания договора
async function createContract() {
  console.log('🤝 Создание нового договора\n');
  
  // Получаем данные от пользователя
  const contractNumber = generateContractNumber();
  const clientName = await question('📝 Наименование заказчика: ');
  const clientAddress = await question('📍 Адрес заказчика: ');
  const clientPhone = await question('📞 Телефон заказчика: ');
  const clientEmail = await question('📧 Email заказчика: ');
  const clientUNP = await question('🏢 УНП заказчика (если есть): ') || '[УНП - если есть]';
  
  const projectName = await question('🎯 Название проекта: ');
  const projectDescription = await question('📋 Краткое описание проекта: ');
  const totalCost = await question('💰 Общая стоимость (в рублях): ');
  const totalDays = await question('⏰ Срок выполнения (в днях): ');
  
  const prepaymentPercent = await question('💳 Процент предоплаты (например, 100): ') || '100';
  const prepaymentDays = await question('📅 Срок предоплаты (в днях): ') || '3';
  
  // Читаем шаблон
  const templatePath = path.join(__dirname, '../docs/contracts/contract_template.md');
  let template = fs.readFileSync(templatePath, 'utf8');
  
  // Заменяем плейсхолдеры
  const today = new Date();
  const dateStr = today.getDate().toString().padStart(2, '0');
  const monthStr = (today.getMonth() + 1).toString().padStart(2, '0');
  const yearStr = today.getFullYear();
  
  template = template
    .replace(/ДОГОВОР № ____\/____-____\/42/g, `ДОГОВОР № ${contractNumber}`)
    .replace(/«___» ___________ 2025 г\./g, `«${dateStr}» ${getMonthName(today.getMonth())} ${yearStr} г.`)
    .replace(/\[НАИМЕНОВАНИЕ КОМПАНИИ\/ФИО\]/g, clientName)
    .replace(/\[АДРЕС\]/g, clientAddress)
    .replace(/\[ТЕЛЕФОН\]/g, clientPhone)
    .replace(/\[EMAIL\]/g, clientEmail)
    .replace(/\[УНП - если есть\]/g, clientUNP)
    .replace(/___ календарных дней/g, `${totalDays} календарных дней`)
    .replace(/___ долларов США.*сумма прописью\)/g, `${totalCost} долларов США (${numberToWords(totalCost)})`)
    .replace(/___% от общей стоимости \(___ долларов США\) - в течение ___ дней/g, `${prepaymentPercent}% от общей стоимости (${totalCost} долларов США) - в течение ${prepaymentDays} дней`)
    .replace(/\[НАЗВАНИЕ ПРОЕКТА\]/g, projectName)
    .replace(/\[ДАТА СОЗДАНИЯ ТЗ\]/g, `${dateStr}.${monthStr}.${yearStr}`)
    .replace(/\[Краткое описание проекта и его целей\]/g, projectDescription);
  
  // Создаем имя файла
  const fileName = `contract_${contractNumber.replace(/\//g, '_')}_${clientName.replace(/[^a-zA-Zа-яА-Я0-9]/g, '_')}.md`;
  const filePath = path.join(__dirname, '../docs/contracts', fileName);
  
  // Создаем директорию если её нет
  const contractsDir = path.join(__dirname, '../docs/contracts');
  if (!fs.existsSync(contractsDir)) {
    fs.mkdirSync(contractsDir, { recursive: true });
  }
  
  // Записываем файл
  fs.writeFileSync(filePath, template, 'utf8');
  
  console.log('\n✅ Договор успешно создан!');
  console.log(`📄 Файл: ${fileName}`);
  console.log(`📁 Путь: ${filePath}`);
  console.log('\n📋 Что нужно сделать дальше:');
  console.log('1. Заполнить реквизиты исполнителя (адрес, телефон, email, банковские реквизиты)');
  console.log('2. Детализировать техническое задание');
  console.log('3. Согласовать с заказчиком');
  console.log('4. Подписать договор');
  
  rl.close();
}

// Вспомогательные функции
function getMonthName(month) {
  const months = [
    'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'
  ];
  return months[month];
}

function numberToWords(num) {
  const ones = ['', 'один', 'два', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять'];
  const teens = ['десять', 'одиннадцать', 'двенадцать', 'тринадцать', 'четырнадцать', 'пятнадцать', 'шестнадцать', 'семнадцать', 'восемнадцать', 'девятнадцать'];
  const tens = ['', '', 'двадцать', 'тридцать', 'сорок', 'пятьдесят', 'шестьдесят', 'семьдесят', 'восемьдесят', 'девяносто'];
  
  if (num === 0) return 'ноль';
  if (num < 10) return ones[num];
  if (num < 20) return teens[num - 10];
  if (num < 100) {
    const ten = Math.floor(num / 10);
    const one = num % 10;
    return tens[ten] + (one > 0 ? ' ' + ones[one] : '');
  }
  if (num < 1000) {
    const hundred = Math.floor(num / 100);
    const remainder = num % 100;
    let result = '';
    if (hundred === 1) result = 'сто';
    else if (hundred === 2) result = 'двести';
    else if (hundred === 3) result = 'триста';
    else if (hundred === 4) result = 'четыреста';
    else if (hundred === 5) result = 'пятьсот';
    else if (hundred === 6) result = 'шестьсот';
    else if (hundred === 7) result = 'семьсот';
    else if (hundred === 8) result = 'восемьсот';
    else if (hundred === 9) result = 'девятьсот';
    if (remainder > 0) result += ' ' + numberToWords(remainder);
    return result;
  }
  
  // Для больших чисел возвращаем упрощенный вариант
  return num.toString();
}

// Запускаем скрипт
if (require.main === module) {
  createContract().catch(console.error);
}

module.exports = { createContract, generateContractNumber }; 