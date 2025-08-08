const express = require('express');
const router = express.Router();
const logger = require('../utils/logger');

// Mock notification data - in production, this would be a database
let notifications = [
  {
    id: 1,
    type: 'booking_confirmation',
    recipientType: 'therapist',
    recipientId: 1,
    recipientPhone: '+1234567890',
    message: 'New booking confirmed for tomorrow at 2 PM',
    status: 'sent',
    bookingId: 1,
    createdAt: new Date().toISOString(),
    sentAt: new Date().toISOString()
  }
];

// Mock therapists and drivers data
const therapists = [
  {
    id: 1,
    name: 'Sarah Johnson',
    phone: '+1234567890',
    specialties: ['Swedish Massage', 'Deep Tissue'],
    status: 'available'
  },
  {
    id: 2,
    name: 'Mike Chen',
    phone: '+1234567891',
    specialties: ['Sports Massage', 'Thai Massage'],
    status: 'available'
  }
];

const drivers = [
  {
    id: 1,
    name: 'Alex Rodriguez',
    phone: '+1234567892',
    vehicle: 'Toyota Camry',
    status: 'available'
  },
  {
    id: 2,
    name: 'Emma Wilson',
    phone: '+1234567893',
    vehicle: 'Honda Civic',
    status: 'available'
  }
];

// Generate notification message based on type and data
const generateMessage = (type, data) => {
  switch (type) {
    case 'booking_confirmation':
      return `New booking confirmed!\n\nClient: ${data.clientName}\nService: ${data.service}\nDate: ${data.date}\nTime: ${data.time}\nLocation: ${data.location}\n\nPlease confirm your availability.`;
    
    case 'booking_reminder':
      return `Booking reminder!\n\nYou have a booking in 1 hour:\nClient: ${data.clientName}\nService: ${data.service}\nLocation: ${data.location}\n\nPlease ensure you're on time.`;
    
    case 'driver_assignment':
      return `Driver assignment for booking!\n\nClient: ${data.clientName}\nPickup time: ${data.pickupTime}\nLocation: ${data.location}\n\nPlease confirm pickup.`;
    
    case 'payment_received':
      return `Payment received!\n\nBooking: ${data.bookingId}\nAmount: $${data.amount}\nPayment method: ${data.paymentMethod}\n\nThank you for your service.`;
    
    case 'subscription_alert':
      return `Subscription alert!\n\nClient: ${data.clientName}\nPackage: ${data.packageName}\nRemaining sessions: ${data.remainingSessions}\n\nPlease remind client to renew.`;
    
    default:
      return 'You have a new notification.';
  }
};

// Send WhatsApp message (mock implementation)
const sendWhatsAppMessage = async (phone, message) => {
  // In production, this would integrate with WhatsApp Business API
  logger.info(`Sending WhatsApp message to ${phone}: ${message}`);
  
  // Simulate API call delay
  await new Promise(resolve => setTimeout(resolve, 1000));
  
  // Simulate success (90% success rate)
  const success = Math.random() > 0.1;
  
  if (!success) {
    throw new Error('Failed to send WhatsApp message');
  }
  
  return {
    messageId: `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
    status: 'sent',
    timestamp: new Date().toISOString()
  };
};

// GET /api/notification - Get all notifications
router.get('/', (req, res) => {
  try {
    const { type, recipientType, status } = req.query;
    let filteredNotifications = [...notifications];

    if (type) {
      filteredNotifications = filteredNotifications.filter(n => n.type === type);
    }

    if (recipientType) {
      filteredNotifications = filteredNotifications.filter(n => n.recipientType === recipientType);
    }

    if (status) {
      filteredNotifications = filteredNotifications.filter(n => n.status === status);
    }

    logger.info(`Retrieved ${filteredNotifications.length} notifications`);
    res.json({
      success: true,
      data: filteredNotifications,
      count: filteredNotifications.length
    });
  } catch (error) {
    logger.error('Error retrieving notifications:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to retrieve notifications'
    });
  }
});

// GET /api/notification/:id - Get notification by ID
router.get('/:id', (req, res) => {
  try {
    const notificationId = parseInt(req.params.id);
    const notification = notifications.find(n => n.id === notificationId);

    if (!notification) {
      return res.status(404).json({
        success: false,
        error: 'Notification not found'
      });
    }

    logger.info(`Retrieved notification ${notificationId}`);
    res.json({
      success: true,
      data: notification
    });
  } catch (error) {
    logger.error('Error retrieving notification:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to retrieve notification'
    });
  }
});

// POST /api/notification/send - Send notification
router.post('/send', async (req, res) => {
  try {
    const { type, recipientType, recipientId, bookingId, data } = req.body;

    if (!type || !recipientType || !recipientId) {
      return res.status(400).json({
        success: false,
        error: 'Type, recipient type, and recipient ID are required'
      });
    }

    // Find recipient based on type
    let recipient;
    if (recipientType === 'therapist') {
      recipient = therapists.find(t => t.id === parseInt(recipientId));
    } else if (recipientType === 'driver') {
      recipient = drivers.find(d => d.id === parseInt(recipientId));
    }

    if (!recipient) {
      return res.status(404).json({
        success: false,
        error: 'Recipient not found'
      });
    }

    // Generate message
    const message = generateMessage(type, data || {});

    // Create notification record
    const notification = {
      id: notifications.length + 1,
      type,
      recipientType,
      recipientId: parseInt(recipientId),
      recipientPhone: recipient.phone,
      message,
      status: 'pending',
      bookingId: bookingId ? parseInt(bookingId) : null,
      createdAt: new Date().toISOString()
    };

    notifications.push(notification);

    // Send WhatsApp message
    try {
      const result = await sendWhatsAppMessage(recipient.phone, message);
      
      notification.status = 'sent';
      notification.sentAt = result.timestamp;
      notification.messageId = result.messageId;

      logger.info(`Sent notification ${notification.id} to ${recipient.name}`);
      res.status(201).json({
        success: true,
        data: notification,
        message: 'Notification sent successfully'
      });
    } catch (error) {
      notification.status = 'failed';
      notification.error = error.message;
      
      logger.error(`Failed to send notification ${notification.id}:`, error);
      res.status(500).json({
        success: false,
        error: 'Failed to send notification',
        data: notification
      });
    }
  } catch (error) {
    logger.error('Error sending notification:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to send notification'
    });
  }
});

// POST /api/notification/bulk-send - Send notifications to multiple recipients
router.post('/bulk-send', async (req, res) => {
  try {
    const { type, recipientType, recipientIds, bookingId, data } = req.body;

    if (!type || !recipientType || !recipientIds || !Array.isArray(recipientIds)) {
      return res.status(400).json({
        success: false,
        error: 'Type, recipient type, and recipient IDs array are required'
      });
    }

    const results = [];
    const message = generateMessage(type, data || {});

    for (const recipientId of recipientIds) {
      // Find recipient
      let recipient;
      if (recipientType === 'therapist') {
        recipient = therapists.find(t => t.id === parseInt(recipientId));
      } else if (recipientType === 'driver') {
        recipient = drivers.find(d => d.id === parseInt(recipientId));
      }

      if (!recipient) {
        results.push({
          recipientId,
          success: false,
          error: 'Recipient not found'
        });
        continue;
      }

      // Create notification record
      const notification = {
        id: notifications.length + 1,
        type,
        recipientType,
        recipientId: parseInt(recipientId),
        recipientPhone: recipient.phone,
        message,
        status: 'pending',
        bookingId: bookingId ? parseInt(bookingId) : null,
        createdAt: new Date().toISOString()
      };

      notifications.push(notification);

      // Send WhatsApp message
      try {
        const result = await sendWhatsAppMessage(recipient.phone, message);
        
        notification.status = 'sent';
        notification.sentAt = result.timestamp;
        notification.messageId = result.messageId;

        results.push({
          recipientId,
          success: true,
          notificationId: notification.id
        });
      } catch (error) {
        notification.status = 'failed';
        notification.error = error.message;
        
        results.push({
          recipientId,
          success: false,
          error: error.message
        });
      }
    }

    const successCount = results.filter(r => r.success).length;
    logger.info(`Bulk notification sent: ${successCount}/${recipientIds.length} successful`);
    
    res.json({
      success: true,
      data: results,
      summary: {
        total: recipientIds.length,
        successful: successCount,
        failed: recipientIds.length - successCount
      }
    });
  } catch (error) {
    logger.error('Error sending bulk notifications:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to send bulk notifications'
    });
  }
});

// GET /api/notification/recipients/therapists - Get available therapists
router.get('/recipients/therapists', (req, res) => {
  try {
    logger.info('Retrieved available therapists');
    res.json({
      success: true,
      data: therapists
    });
  } catch (error) {
    logger.error('Error retrieving therapists:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to retrieve therapists'
    });
  }
});

// GET /api/notification/recipients/drivers - Get available drivers
router.get('/recipients/drivers', (req, res) => {
  try {
    logger.info('Retrieved available drivers');
    res.json({
      success: true,
      data: drivers
    });
  } catch (error) {
    logger.error('Error retrieving drivers:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to retrieve drivers'
    });
  }
});

// PUT /api/notification/:id/status - Update notification status
router.put('/:id/status', (req, res) => {
  try {
    const notificationId = parseInt(req.params.id);
    const { status } = req.body;

    if (!status || !['pending', 'sent', 'failed', 'delivered', 'read'].includes(status)) {
      return res.status(400).json({
        success: false,
        error: 'Valid status is required (pending, sent, failed, delivered, read)'
      });
    }

    const notification = notifications.find(n => n.id === notificationId);
    if (!notification) {
      return res.status(404).json({
        success: false,
        error: 'Notification not found'
      });
    }

    notification.status = status;
    notification.updatedAt = new Date().toISOString();

    logger.info(`Updated notification ${notificationId} status to ${status}`);
    res.json({
      success: true,
      data: notification,
      message: 'Notification status updated successfully'
    });
  } catch (error) {
    logger.error('Error updating notification status:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to update notification status'
    });
  }
});

// GET /api/notification/stats/overview - Get notification statistics
router.get('/stats/overview', (req, res) => {
  try {
    const totalNotifications = notifications.length;
    const sentNotifications = notifications.filter(n => n.status === 'sent');
    const failedNotifications = notifications.filter(n => n.status === 'failed');
    const pendingNotifications = notifications.filter(n => n.status === 'pending');

    const therapistNotifications = notifications.filter(n => n.recipientType === 'therapist');
    const driverNotifications = notifications.filter(n => n.recipientType === 'driver');

    res.json({
      success: true,
      data: {
        totalNotifications,
        sentNotifications: sentNotifications.length,
        failedNotifications: failedNotifications.length,
        pendingNotifications: pendingNotifications.length,
        successRate: totalNotifications > 0 ? Math.round((sentNotifications.length / totalNotifications) * 100) : 0,
        therapistNotifications: therapistNotifications.length,
        driverNotifications: driverNotifications.length
      }
    });
  } catch (error) {
    logger.error('Error retrieving notification stats:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to retrieve notification statistics'
    });
  }
});

module.exports = router; 