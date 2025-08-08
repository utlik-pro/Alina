const express = require('express');
const router = express.Router();
const { asyncHandler } = require('../utils/errorHandler');
const logger = require('../utils/logger');

// WhatsApp webhook for receiving messages
router.post('/webhook', asyncHandler(async (req, res) => {
  const { body } = req;
  
  logger.info('WhatsApp webhook received:', {
    body: body,
    headers: req.headers
  });

  try {
    // Verify webhook signature (implement based on WhatsApp Business API docs)
    // TODO: Add webhook verification
    
    // Process incoming message
    if (body.entry && body.entry[0] && body.entry[0].changes) {
      const changes = body.entry[0].changes;
      
      for (const change of changes) {
        if (change.value && change.value.messages) {
          for (const message of change.value.messages) {
            await processWhatsAppMessage(message);
          }
        }
      }
    }

    res.status(200).json({ status: 'OK' });
  } catch (error) {
    logger.error('Error processing WhatsApp webhook:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
}));

// Send message via WhatsApp
router.post('/send', asyncHandler(async (req, res) => {
  const { phoneNumber, message, templateName, templateParams } = req.body;
  
  logger.info('Sending WhatsApp message:', {
    phoneNumber,
    templateName,
    templateParams
  });

  try {
    // TODO: Implement WhatsApp Business API message sending
    const result = await sendWhatsAppMessage({
      phoneNumber,
      message,
      templateName,
      templateParams
    });

    res.json({
      success: true,
      messageId: result.messageId,
      timestamp: new Date().toISOString()
    });
  } catch (error) {
    logger.error('Error sending WhatsApp message:', error);
    res.status(500).json({ error: 'Failed to send message' });
  }
}));

// Get message templates
router.get('/templates', asyncHandler(async (req, res) => {
  try {
    // TODO: Implement WhatsApp Business API template retrieval
    const templates = await getWhatsAppTemplates();
    
    res.json({
      success: true,
      templates
    });
  } catch (error) {
    logger.error('Error fetching WhatsApp templates:', error);
    res.status(500).json({ error: 'Failed to fetch templates' });
  }
}));

// Process incoming WhatsApp message
async function processWhatsAppMessage(message) {
  const { from, text, location, timestamp } = message;
  
  logger.info('Processing WhatsApp message:', {
    from,
    text: text?.body,
    hasLocation: !!location,
    timestamp
  });

  try {
    // Extract booking information from message
    const bookingData = await extractBookingData(message);
    
    if (bookingData) {
      // Create booking in system
      await createBooking(bookingData);
      
      // Send confirmation message
      await sendConfirmationMessage(from, bookingData);
    }
  } catch (error) {
    logger.error('Error processing WhatsApp message:', error);
    // Send error message to user
    await sendErrorMessage(from);
  }
}

// Extract booking data from WhatsApp message
async function extractBookingData(message) {
  const { text, location } = message;
  
  if (!text?.body) {
    return null;
  }

  // TODO: Implement AI/NLP processing for message parsing
  // This should extract: client name, service type, date/time, location
  
  const bookingData = {
    clientName: '', // Extract from message
    serviceType: '', // Extract from message
    dateTime: '', // Extract from message
    location: location || '', // Extract from message or location object
    phoneNumber: message.from,
    source: 'whatsapp',
    rawMessage: text.body
  };

  return bookingData;
}

// Send WhatsApp message
async function sendWhatsAppMessage({ phoneNumber, message, templateName, templateParams }) {
  // TODO: Implement WhatsApp Business API integration
  logger.info('Sending WhatsApp message:', {
    phoneNumber,
    templateName,
    templateParams
  });

  // Mock implementation
  return {
    messageId: `msg_${Date.now()}`,
    status: 'sent'
  };
}

// Get WhatsApp templates
async function getWhatsAppTemplates() {
  // TODO: Implement WhatsApp Business API template retrieval
  return [
    {
      name: 'booking_confirmation',
      language: 'en',
      status: 'APPROVED'
    },
    {
      name: 'appointment_reminder',
      language: 'en',
      status: 'APPROVED'
    }
  ];
}

// Create booking in system
async function createBooking(bookingData) {
  // TODO: Implement booking creation logic
  logger.info('Creating booking:', bookingData);
}

// Send confirmation message
async function sendConfirmationMessage(phoneNumber, bookingData) {
  // TODO: Implement confirmation message sending
  logger.info('Sending confirmation message:', { phoneNumber, bookingData });
}

// Send error message
async function sendErrorMessage(phoneNumber) {
  // TODO: Implement error message sending
  logger.info('Sending error message:', { phoneNumber });
}

module.exports = router; 