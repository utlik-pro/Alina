const logger = require('../utils/logger');

// Mock WhatsApp Business API integration
class WhatsAppService {
  constructor() {
    this.webhookSecret = process.env.WHATSAPP_WEBHOOK_SECRET;
    this.accessToken = process.env.WHATSAPP_ACCESS_TOKEN;
    this.phoneNumberId = process.env.WHATSAPP_PHONE_NUMBER_ID;
  }

  // Extract booking information from WhatsApp message
  async extractBookingData(message) {
    try {
      logger.info('Extracting booking data from message:', message);

      // In production, this would use NLP/AI to extract structured data
      // For now, we'll use regex patterns to extract common booking information
      
      const bookingData = {
        clientName: this.extractClientName(message),
        service: this.extractService(message),
        date: this.extractDate(message),
        time: this.extractTime(message),
        location: this.extractLocation(message),
        phone: this.extractPhone(message),
        confidence: 0.8 // Confidence score for extraction
      };

      logger.info('Extracted booking data:', bookingData);
      return bookingData;
    } catch (error) {
      logger.error('Error extracting booking data:', error);
      throw error;
    }
  }

  // Extract client name from message
  extractClientName(message) {
    // Common patterns for names
    const namePatterns = [
      /(?:my name is|i'm|i am|call me)\s+([A-Za-z\s]+)/i,
      /(?:name:?\s*)([A-Za-z\s]+)/i,
      /(?:client:?\s*)([A-Za-z\s]+)/i
    ];

    for (const pattern of namePatterns) {
      const match = message.match(pattern);
      if (match && match[1]) {
        return match[1].trim();
      }
    }

    return null;
  }

  // Extract service type from message
  extractService(message) {
    const services = [
      'swedish massage',
      'deep tissue massage',
      'sports massage',
      'thai massage',
      'hot stone massage',
      'aromatherapy massage',
      'couples massage',
      'prenatal massage'
    ];

    const lowerMessage = message.toLowerCase();
    for (const service of services) {
      if (lowerMessage.includes(service)) {
        return service;
      }
    }

    return 'general massage'; // Default service
  }

  // Extract date from message
  extractDate(message) {
    const datePatterns = [
      /(?:on|for|date:?\s*)(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})/i,
      /(?:on|for|date:?\s*)(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{2,4})/i,
      /(?:tomorrow|today|next week)/i
    ];

    for (const pattern of datePatterns) {
      const match = message.match(pattern);
      if (match && match[1]) {
        return this.parseDate(match[1]);
      }
    }

    // Handle relative dates
    if (message.toLowerCase().includes('tomorrow')) {
      const tomorrow = new Date();
      tomorrow.setDate(tomorrow.getDate() + 1);
      return tomorrow.toISOString().split('T')[0];
    }

    if (message.toLowerCase().includes('today')) {
      return new Date().toISOString().split('T')[0];
    }

    return null;
  }

  // Extract time from message
  extractTime(message) {
    const timePatterns = [
      /(?:at|time:?\s*)(\d{1,2}:\d{2}\s*(?:am|pm)?)/i,
      /(?:at|time:?\s*)(\d{1,2}\s*(?:am|pm))/i,
      /(?:morning|afternoon|evening|night)/i
    ];

    for (const pattern of timePatterns) {
      const match = message.match(pattern);
      if (match && match[1]) {
        return this.parseTime(match[1]);
      }
    }

    // Handle relative times
    const lowerMessage = message.toLowerCase();
    if (lowerMessage.includes('morning')) return '09:00';
    if (lowerMessage.includes('afternoon')) return '14:00';
    if (lowerMessage.includes('evening')) return '18:00';
    if (lowerMessage.includes('night')) return '20:00';

    return null;
  }

  // Extract location from message
  extractLocation(message) {
    const locationPatterns = [
      /(?:at|location:?\s*|address:?\s*)([A-Za-z0-9\s,.-]+)/i,
      /(?:home|office|hotel|apartment)/i
    ];

    for (const pattern of locationPatterns) {
      const match = message.match(pattern);
      if (match && match[1]) {
        return match[1].trim();
      }
    }

    // Handle common location keywords
    const lowerMessage = message.toLowerCase();
    if (lowerMessage.includes('home')) return 'Client Home';
    if (lowerMessage.includes('office')) return 'Client Office';
    if (lowerMessage.includes('hotel')) return 'Hotel';
    if (lowerMessage.includes('apartment')) return 'Apartment';

    return 'To be confirmed';
  }

  // Extract phone number from message
  extractPhone(message) {
    const phonePatterns = [
      /(\+?\d{1,3}[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{4})/,
      /(?:phone:?\s*|tel:?\s*)(\+?\d{1,3}[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{4})/i
    ];

    for (const pattern of phonePatterns) {
      const match = message.match(pattern);
      if (match && match[1]) {
        return match[1].replace(/[-.\s]/g, '');
      }
    }

    return null;
  }

  // Parse date string to ISO format
  parseDate(dateString) {
    try {
      const date = new Date(dateString);
      if (isNaN(date.getTime())) {
        return null;
      }
      return date.toISOString().split('T')[0];
    } catch (error) {
      logger.error('Error parsing date:', error);
      return null;
    }
  }

  // Parse time string to 24-hour format
  parseTime(timeString) {
    try {
      const time = timeString.toLowerCase().trim();
      
      // Handle 12-hour format
      if (time.includes('am') || time.includes('pm')) {
        const [timePart, period] = time.split(/(am|pm)/);
        let [hours, minutes] = timePart.split(':').map(Number);
        
        if (period === 'pm' && hours !== 12) {
          hours += 12;
        } else if (period === 'am' && hours === 12) {
          hours = 0;
        }
        
        return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
      }
      
      // Handle 24-hour format
      if (time.includes(':')) {
        const [hours, minutes] = time.split(':').map(Number);
        return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
      }
      
      return null;
    } catch (error) {
      logger.error('Error parsing time:', error);
      return null;
    }
  }

  // Send WhatsApp message
  async sendMessage(phoneNumber, message) {
    try {
      logger.info(`Sending WhatsApp message to ${phoneNumber}`);

      // In production, this would make an actual API call to WhatsApp Business API
      const response = await this.makeWhatsAppAPICall(phoneNumber, message);

      logger.info('WhatsApp message sent successfully');
      return response;
    } catch (error) {
      logger.error('Error sending WhatsApp message:', error);
      throw error;
    }
  }

  // Mock WhatsApp Business API call
  async makeWhatsAppAPICall(phoneNumber, message) {
    // Simulate API call delay
    await new Promise(resolve => setTimeout(resolve, 1000));

    // Simulate API response
    return {
      messageId: `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      status: 'sent',
      timestamp: new Date().toISOString(),
      recipient: phoneNumber
    };
  }

  // Send booking confirmation message
  async sendBookingConfirmation(phoneNumber, bookingData) {
    const message = `✅ Booking Confirmed!

📅 Date: ${bookingData.date}
⏰ Time: ${bookingData.time}
📍 Location: ${bookingData.location}
💆 Service: ${bookingData.service}

Your massage therapist will arrive 10 minutes before the scheduled time. Please ensure someone is available to let them in.

For any changes, please contact us at least 2 hours in advance.

Thank you for choosing our service! 🙏`;

    return await this.sendMessage(phoneNumber, message);
  }

  // Send booking reminder
  async sendBookingReminder(phoneNumber, bookingData) {
    const message = `⏰ Booking Reminder!

Your massage is scheduled for today at ${bookingData.time}.

📍 Location: ${bookingData.location}
💆 Service: ${bookingData.service}

Your therapist will arrive 10 minutes before the scheduled time.

Please ensure you're ready and available. Thank you! 🙏`;

    return await this.sendMessage(phoneNumber, message);
  }

  // Send payment confirmation
  async sendPaymentConfirmation(phoneNumber, paymentData) {
    const message = `💳 Payment Confirmed!

Booking ID: ${paymentData.bookingId}
Amount: $${paymentData.amount}
VAT: $${paymentData.vatAmount}
Total: $${paymentData.totalAmount}
Payment Method: ${paymentData.paymentMethod}

Thank you for your payment! Your booking is now confirmed. 🙏`;

    return await this.sendMessage(phoneNumber, message);
  }

  // Send subscription alert
  async sendSubscriptionAlert(phoneNumber, subscriptionData) {
    const message = `📦 Subscription Alert!

Package: ${subscriptionData.packageName}
Remaining Sessions: ${subscriptionData.remainingSessions}

Your subscription is running low on sessions. Consider renewing to continue enjoying our services!

Contact us to renew your package. 🙏`;

    return await this.sendMessage(phoneNumber, message);
  }

  // Validate webhook signature
  validateWebhookSignature(signature, body) {
    // In production, this would validate the webhook signature
    // to ensure the request is from WhatsApp
    logger.info('Validating webhook signature');
    return true; // Mock validation
  }

  // Process incoming webhook
  async processWebhook(body) {
    try {
      logger.info('Processing WhatsApp webhook');

      const entry = body.entry?.[0];
      if (!entry) {
        throw new Error('Invalid webhook format');
      }

      const changes = entry.changes?.[0];
      if (!changes || changes.value?.object !== 'whatsapp_business_account') {
        throw new Error('Invalid webhook object');
      }

      const messages = changes.value.messages;
      if (!messages || messages.length === 0) {
        return { processed: 0, message: 'No messages to process' };
      }

      const results = [];
      for (const message of messages) {
        const result = await this.processMessage(message);
        results.push(result);
      }

      logger.info(`Processed ${results.length} messages`);
      return {
        processed: results.length,
        results
      };
    } catch (error) {
      logger.error('Error processing webhook:', error);
      throw error;
    }
  }

  // Process individual message
  async processMessage(message) {
    try {
      const { from, text, timestamp } = message;
      
      if (!text) {
        return { status: 'skipped', reason: 'No text content' };
      }

      // Extract booking data from message
      const bookingData = await this.extractBookingData(text.body);
      
      // Add phone number to booking data
      bookingData.phone = from;

      return {
        status: 'processed',
        phone: from,
        message: text.body,
        bookingData,
        timestamp
      };
    } catch (error) {
      logger.error('Error processing message:', error);
      return {
        status: 'error',
        error: error.message
      };
    }
  }
}

module.exports = new WhatsAppService(); 