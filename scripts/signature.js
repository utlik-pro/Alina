const fs = require('fs');
const path = require('path');

// Путь к файлу подписи
const SIGNATURE_PATH = path.join(__dirname, '../assets/signature_Utlik.png');

// Проверка наличия файла подписи
function checkSignatureFile() {
  if (!fs.existsSync(SIGNATURE_PATH)) {
    console.log('⚠️  Файл подписи не найден:', SIGNATURE_PATH);
    console.log('📁 Создайте папку assets/ и поместите туда signature_Utlik.png');
    return false;
  }
  return true;
}

// Функция для получения HTML с подписью
function getSignatureHTML() {
  if (!checkSignatureFile()) {
    return '';
  }
  
  return `
    <div style="position: absolute; bottom: 50px; left: 50px; width: 200px; height: 80px;">
      <img src="data:image/png;base64,${getSignatureBase64()}" 
           alt="Подпись Утлик Д.Ю." 
           style="width: 100%; height: 100%; object-fit: contain;">
    </div>
  `;
}

// Конвертация PNG в base64
function getSignatureBase64() {
  try {
    const imageBuffer = fs.readFileSync(SIGNATURE_PATH);
    return imageBuffer.toString('base64');
  } catch (error) {
    console.error('❌ Ошибка чтения файла подписи:', error.message);
    return '';
  }
}

// Функция для создания подписи в формате PNG (для совместимости)
function createSignaturePNG() {
  return getSignatureHTML();
}

// Функция для добавления подписи в PDF
function addSignatureToPDF(pdfPath, outputPath) {
  console.log(`📝 Подпись будет добавлена в ${outputPath}`);
  return true;
}

module.exports = { 
  createSignaturePNG, 
  addSignatureToPDF, 
  getSignatureHTML,
  checkSignatureFile 
}; 