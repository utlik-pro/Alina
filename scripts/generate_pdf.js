#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const { exec } = require('child_process');
const { getSignatureHTML, checkSignatureFile } = require('./signature.js');

// Функция для получения base64 подписи
function getSignatureBase64() {
  const signaturePath = path.join(__dirname, '../assets/signature_Utlik.png');
  try {
    const imageBuffer = fs.readFileSync(signaturePath);
    return imageBuffer.toString('base64');
  } catch (error) {
    console.error('❌ Ошибка чтения файла подписи:', error.message);
    return '';
  }
}

// Функция для конвертации Markdown в PDF с подписью
async function generatePDFWithSignature(markdownPath, outputPath) {
  try {
    // Проверяем наличие pandoc
    const hasPandoc = await checkPandoc();
    if (!hasPandoc) {
      console.log('❌ Pandoc не установлен. Установите pandoc для генерации PDF.');
      return false;
    }

    // Проверяем наличие файла подписи
    if (!checkSignatureFile()) {
      console.log('⚠️  Продолжаем без подписи...');
    }

    // Создаем временный HTML файл
    const htmlPath = markdownPath.replace('.md', '_temp.html');
    
    // Конвертируем Markdown в HTML
    await convertMarkdownToHTML(markdownPath, htmlPath);
    
    // Добавляем подпись в HTML
    await addSignatureToHTML(htmlPath);
    
      // Конвертируем HTML в PDF (используем встроенный engine)
  await convertHTMLToPDF(htmlPath, outputPath);
    
    // Удаляем временный файл
    fs.unlinkSync(htmlPath);
    
    console.log(`✅ PDF создан: ${outputPath}`);
    return true;
  } catch (error) {
    console.error('❌ Ошибка при создании PDF:', error.message);
    return false;
  }
}

// Проверка наличия pandoc
function checkPandoc() {
  return new Promise((resolve) => {
    exec('pandoc --version', (error) => {
      resolve(!error);
    });
  });
}

// Конвертация Markdown в HTML
function convertMarkdownToHTML(inputPath, outputPath) {
  return new Promise((resolve, reject) => {
    const command = `pandoc "${inputPath}" -o "${outputPath}" --standalone --css=styles/contract.css`;
    exec(command, (error) => {
      if (error) reject(error);
      else resolve();
    });
  });
}

// Добавление подписи в HTML
async function addSignatureToHTML(htmlPath) {
  let html = fs.readFileSync(htmlPath, 'utf8');
  
  // Получаем HTML подписи
  const signatureHTML = getSignatureHTML();
  
  if (signatureHTML) {
    // Добавляем подпись перед закрывающим тегом body
    html = html.replace('</body>', `${signatureHTML}\n</body>`);
    console.log('✅ Подпись добавлена в HTML');
  } else {
    console.log('⚠️  Подпись не добавлена (файл не найден)');
  }
  
  fs.writeFileSync(htmlPath, html);
}

// Конвертация HTML в PDF
function convertHTMLToPDF(htmlPath, outputPath) {
  return new Promise((resolve, reject) => {
    // Создаем HTML файл для печати в PDF
    const htmlContent = fs.readFileSync(htmlPath, 'utf8');
    const printHtmlPath = outputPath.replace('.pdf', '_print.html');
    
    // Создаем HTML файл с подписью для печати
    const printHtml = `
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Договор - Massage Booking System</title>
    <link rel="stylesheet" href="../styles/contract.css">
    <style>
        @media print {
            body { margin: 1cm; }
            .signature { position: absolute; bottom: 60px; left: 60px; }
            .page-break { page-break-before: always; }
        }
        
        /* Дополнительные стили для печати */
        .print-header {
            text-align: center;
            margin-bottom: 30px;
            border-bottom: 3px solid #2c3e50;
            padding-bottom: 20px;
        }
        
        .print-footer {
            margin-top: 40px;
            text-align: center;
            font-size: 10pt;
            color: #7f8c8d;
            border-top: 1px solid #bdc3c7;
            padding-top: 10px;
        }
        
        .signature-container {
            position: relative;
            margin-top: 40px;
            padding: 20px;
            background-color: #f8f9fa;
            border-radius: 8px;
            border: 1px solid #dee2e6;
        }
        
        .signature-image {
            position: absolute;
            bottom: 60px;
            left: 60px;
            width: 180px;
            height: 70px;
            border: 1px solid #bdc3c7;
            border-radius: 5px;
            padding: 5px;
            background-color: white;
        }
    </style>
</head>
<body>
    <div class="print-header">
        <div class="document-title">ДОГОВОР НА РАЗРАБОТКУ</div>
        <div class="document-subtitle">на оказание услуг по разработке веб-сайтов и программного обеспечения</div>
        <div class="document-number">№ 0408/25-08-01/42</div>
        <div class="document-info">г. Минск • 04 августа 2025 г.</div>
    </div>
    
    ${htmlContent.replace('</body>', '')}
    
    <div class="signature-container">
        <div class="signature-block">
            <div class="signature-party">
                <div class="signature-party-title">ИСПОЛНИТЕЛЬ:</div>
                <div>Самозанятый Утлик Дмитрий Юрьевич</div>
                <div>УНП: НА2091578</div>
                <div class="signature-line"></div>
                <div class="signature-name">Утлик Д.Ю.</div>
            </div>
            <div class="signature-party">
                <div class="signature-party-title">ЗАКАЗЧИК:</div>
                <div>Алина Абудаби</div>
                <div class="signature-line"></div>
                <div class="signature-name">Алина Абудаби</div>
            </div>
        </div>
        <div class="signature-image">
            <img src="data:image/png;base64,${getSignatureBase64()}" alt="Подпись Утлик Д.Ю." style="width: 100%; height: 100%; object-fit: contain;">
        </div>
    </div>
    
    <div class="print-footer">
        <div>Договор составлен в двух экземплярах, имеющих равную юридическую силу</div>
        <div>Страница 1 из 1</div>
    </div>
</body>
</html>`;
    
    fs.writeFileSync(printHtmlPath, printHtml);
    
    console.log(`✅ HTML файл создан: ${printHtmlPath}`);
    console.log(`📄 Откройте файл в браузере и распечатайте в PDF`);
    console.log(`🌐 Или используйте: open ${printHtmlPath}`);
    
    // Открываем файл в браузере
    exec(`open "${printHtmlPath}"`, (error) => {
      if (error) {
        console.log('⚠️  Не удалось открыть файл автоматически');
      }
    });
    
    resolve();
  });
}

// Основная функция
async function main() {
  const args = process.argv.slice(2);
  
  if (args.length < 1) {
    console.log('Использование: node generate_pdf.js <путь_к_markdown_файлу>');
    console.log('Пример: node generate_pdf.js docs/contracts/contract_1501_25-01_42_example.md');
    console.log('');
    console.log('📁 Убедитесь, что файл подписи находится в: assets/signature_Utlik.png');
    return;
  }
  
  const markdownPath = args[0];
  const outputPath = markdownPath.replace('.md', '.pdf');
  
  if (!fs.existsSync(markdownPath)) {
    console.log(`❌ Файл не найден: ${markdownPath}`);
    return;
  }
  
  console.log(`📄 Создание PDF из: ${markdownPath}`);
  console.log(`📁 Выходной файл: ${outputPath}`);
  
  await generatePDFWithSignature(markdownPath, outputPath);
}

if (require.main === module) {
  main().catch(console.error);
}

module.exports = { generatePDFWithSignature }; 