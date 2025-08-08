const logger = require('../utils/logger');
const whatsappService = require('./whatsappService');

// Mock booking data - in production, this would be a database
let bookings = [
  {
    id: 1,
    clientId: 1,
    clientName: 'John Doe',
    clientPhone: '+1234567890',
    service: 'Swedish Massage',
    date: '2024-01-15',
    time: '14:00',
    duration: 60,
    location: '123 Main St, City',
    therapistId: 1,
    therapistName: 'Sarah Johnson',
    driverId: 1,
    driverName: 'Alex Rodriguez',
    status: 'confirmed',
    paymentStatus: 'pending',
    subscriptionId: null,
    price: 100.00,
    notes: 'First-time client',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString()
  }
];

// Mock clients data
let clients = [
  {
    id: 1,
    name: 'John Doe',
    phone: '+1234567890',
    email: 'john@example.com',
    address: '123 Main St, City',
    preferences: ['Swedish Massage'],
    subscriptionId: 1,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString()
  }
];

class BookingService {
  constructor() {
    this.services = {
      'swedish massage': { price: 80, duration: 60 },
      'deep tissue massage': { price: 100, duration: 60 },
      'sports massage': { price: 90, duration: 60 },
      'thai massage': { price: 85, duration: 60 },
      'hot stone massage': { price: 120, duration: 90 },
      'aromatherapy massage': { price: 95, duration: 60 },
      'couples massage': { price: 150, duration: 90 },
      'prenatal massage': { price: 110, duration: 60 },
      'general massage': { price: 80, duration: 60 }
    };
  }

  // Create a new booking
  async createBooking(bookingData) {
    try {
      logger.info('Creating new booking:', bookingData);

      // Validate booking data
      const validation = this.validateBookingData(bookingData);
      if (!validation.isValid) {
        throw new Error(`Invalid booking data: ${validation.errors.join(', ')}`);
      }

      // Check for conflicts
      const conflicts = await this.checkBookingConflicts(bookingData);
      if (conflicts.length > 0) {
        throw new Error(`Booking conflicts found: ${conflicts.map(c => c.reason).join(', ')}`);
      }

      // Get or create client
      const client = await this.getOrCreateClient(bookingData);

      // Calculate price and duration
      const serviceInfo = this.services[bookingData.service.toLowerCase()] || this.services['general massage'];
      const price = serviceInfo.price;
      const duration = serviceInfo.duration;

      // Assign therapist and driver
      const therapist = await this.assignTherapist(bookingData.service, bookingData.date, bookingData.time);
      const driver = await this.assignDriver(bookingData.date, bookingData.time);

      // Create booking
      const booking = {
        id: bookings.length + 1,
        clientId: client.id,
        clientName: client.name,
        clientPhone: client.phone,
        service: bookingData.service,
        date: bookingData.date,
        time: bookingData.time,
        duration,
        location: bookingData.location,
        therapistId: therapist.id,
        therapistName: therapist.name,
        driverId: driver.id,
        driverName: driver.name,
        status: 'confirmed',
        paymentStatus: 'pending',
        subscriptionId: bookingData.subscriptionId || null,
        price,
        notes: bookingData.notes || '',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
      };

      bookings.push(booking);

      // Send confirmation messages
      await this.sendBookingConfirmations(booking);

      logger.info(`Created booking ${booking.id} for client ${client.name}`);
      return booking;
    } catch (error) {
      logger.error('Error creating booking:', error);
      throw error;
    }
  }

  // Validate booking data
  validateBookingData(bookingData) {
    const errors = [];
    const required = ['clientName', 'service', 'date', 'time', 'location'];

    for (const field of required) {
      if (!bookingData[field]) {
        errors.push(`${field} is required`);
      }
    }

    // Validate date
    if (bookingData.date) {
      const bookingDate = new Date(bookingData.date);
      const today = new Date();
      today.setHours(0, 0, 0, 0);

      if (bookingDate < today) {
        errors.push('Booking date cannot be in the past');
      }
    }

    // Validate time
    if (bookingData.time) {
      const timeRegex = /^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$/;
      if (!timeRegex.test(bookingData.time)) {
        errors.push('Invalid time format (HH:MM)');
      }
    }

    // Validate service
    if (bookingData.service && !this.services[bookingData.service.toLowerCase()]) {
      errors.push('Invalid service type');
    }

    return {
      isValid: errors.length === 0,
      errors
    };
  }

  // Check for booking conflicts
  async checkBookingConflicts(bookingData) {
    const conflicts = [];
    const bookingDate = new Date(bookingData.date);
    const bookingTime = bookingData.time;

    // Check for existing bookings on the same date/time
    const existingBookings = bookings.filter(booking => {
      const existingDate = new Date(booking.date);
      return existingDate.toDateString() === bookingDate.toDateString() &&
             booking.time === bookingTime &&
             booking.status !== 'cancelled';
    });

    if (existingBookings.length > 0) {
      conflicts.push({
        type: 'time_conflict',
        reason: 'Time slot already booked',
        existingBookings
      });
    }

    // Check therapist availability
    const therapistConflicts = await this.checkTherapistConflicts(bookingData);
    conflicts.push(...therapistConflicts);

    // Check driver availability
    const driverConflicts = await this.checkDriverConflicts(bookingData);
    conflicts.push(...driverConflicts);

    return conflicts;
  }

  // Check therapist conflicts
  async checkTherapistConflicts(bookingData) {
    // Mock implementation - in production, this would check actual therapist schedules
    return [];
  }

  // Check driver conflicts
  async checkDriverConflicts(bookingData) {
    // Mock implementation - in production, this would check actual driver schedules
    return [];
  }

  // Get or create client
  async getOrCreateClient(bookingData) {
    // Try to find existing client by phone
    let client = clients.find(c => c.phone === bookingData.phone);

    if (!client) {
      // Create new client
      client = {
        id: clients.length + 1,
        name: bookingData.clientName,
        phone: bookingData.phone,
        email: bookingData.email || null,
        address: bookingData.location,
        preferences: [bookingData.service],
        subscriptionId: null,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
      };

      clients.push(client);
      logger.info(`Created new client ${client.id}: ${client.name}`);
    } else {
      // Update existing client preferences
      if (!client.preferences.includes(bookingData.service)) {
        client.preferences.push(bookingData.service);
      }
      client.updatedAt = new Date().toISOString();
    }

    return client;
  }

  // Assign therapist
  async assignTherapist(service, date, time) {
    // Mock therapist assignment - in production, this would check availability
    const availableTherapists = [
      { id: 1, name: 'Sarah Johnson', specialties: ['Swedish Massage', 'Deep Tissue'] },
      { id: 2, name: 'Mike Chen', specialties: ['Sports Massage', 'Thai Massage'] }
    ];

    // Find therapist with matching specialty
    const therapist = availableTherapists.find(t => 
      t.specialties.some(specialty => 
        specialty.toLowerCase().includes(service.toLowerCase())
      )
    ) || availableTherapists[0];

    return therapist;
  }

  // Assign driver
  async assignDriver(date, time) {
    // Mock driver assignment - in production, this would check availability
    const availableDrivers = [
      { id: 1, name: 'Alex Rodriguez', vehicle: 'Toyota Camry' },
      { id: 2, name: 'Emma Wilson', vehicle: 'Honda Civic' }
    ];

    // Simple round-robin assignment
    const driverIndex = bookings.length % availableDrivers.length;
    return availableDrivers[driverIndex];
  }

  // Send booking confirmations
  async sendBookingConfirmations(booking) {
    try {
      // Send confirmation to client
      await whatsappService.sendBookingConfirmation(booking.clientPhone, {
        date: booking.date,
        time: booking.time,
        location: booking.location,
        service: booking.service
      });

      // Send notification to therapist
      // This would be handled by the notification service
      logger.info(`Sent booking confirmations for booking ${booking.id}`);
    } catch (error) {
      logger.error('Error sending booking confirmations:', error);
      // Don't throw error - booking is still created
    }
  }

  // Get booking by ID
  async getBooking(id) {
    const booking = bookings.find(b => b.id === parseInt(id));
    if (!booking) {
      throw new Error('Booking not found');
    }
    return booking;
  }

  // Get all bookings with filters
  async getBookings(filters = {}) {
    let filteredBookings = [...bookings];

    if (filters.status) {
      filteredBookings = filteredBookings.filter(b => b.status === filters.status);
    }

    if (filters.clientId) {
      filteredBookings = filteredBookings.filter(b => b.clientId === parseInt(filters.clientId));
    }

    if (filters.date) {
      filteredBookings = filteredBookings.filter(b => b.date === filters.date);
    }

    if (filters.therapistId) {
      filteredBookings = filteredBookings.filter(b => b.therapistId === parseInt(filters.therapistId));
    }

    return filteredBookings;
  }

  // Update booking
  async updateBooking(id, updateData) {
    const booking = await this.getBooking(id);
    
    // Update allowed fields
    const allowedFields = ['status', 'paymentStatus', 'notes', 'location', 'time'];
    for (const field of allowedFields) {
      if (updateData[field] !== undefined) {
        booking[field] = updateData[field];
      }
    }

    booking.updatedAt = new Date().toISOString();

    logger.info(`Updated booking ${id}`);
    return booking;
  }

  // Cancel booking
  async cancelBooking(id, reason = 'Client request') {
    const booking = await this.getBooking(id);
    
    if (booking.status === 'cancelled') {
      throw new Error('Booking is already cancelled');
    }

    booking.status = 'cancelled';
    booking.cancellationReason = reason;
    booking.updatedAt = new Date().toISOString();

    // Send cancellation notifications
    await this.sendCancellationNotifications(booking);

    logger.info(`Cancelled booking ${id}: ${reason}`);
    return booking;
  }

  // Send cancellation notifications
  async sendCancellationNotifications(booking) {
    try {
      // Send cancellation message to client
      await whatsappService.sendMessage(booking.clientPhone, 
        `❌ Booking Cancelled\n\nYour booking for ${booking.date} at ${booking.time} has been cancelled.\n\nReason: ${booking.cancellationReason}\n\nPlease contact us to reschedule.`
      );

      logger.info(`Sent cancellation notifications for booking ${booking.id}`);
    } catch (error) {
      logger.error('Error sending cancellation notifications:', error);
    }
  }

  // Get booking statistics
  async getBookingStats() {
    const totalBookings = bookings.length;
    const confirmedBookings = bookings.filter(b => b.status === 'confirmed');
    const cancelledBookings = bookings.filter(b => b.status === 'cancelled');
    const completedBookings = bookings.filter(b => b.status === 'completed');

    const totalRevenue = confirmedBookings.reduce((sum, b) => sum + b.price, 0);
    const averageBookingValue = totalBookings > 0 ? totalRevenue / totalBookings : 0;

    return {
      totalBookings,
      confirmedBookings: confirmedBookings.length,
      cancelledBookings: cancelledBookings.length,
      completedBookings: completedBookings.length,
      totalRevenue,
      averageBookingValue: Math.round(averageBookingValue * 100) / 100,
      cancellationRate: totalBookings > 0 ? Math.round((cancelledBookings.length / totalBookings) * 100) : 0
    };
  }

  // Get upcoming bookings
  async getUpcomingBookings(days = 7) {
    const today = new Date();
    const futureDate = new Date();
    futureDate.setDate(today.getDate() + days);

    return bookings.filter(booking => {
      const bookingDate = new Date(booking.date);
      return bookingDate >= today && 
             bookingDate <= futureDate && 
             booking.status === 'confirmed';
    }).sort((a, b) => new Date(a.date) - new Date(b.date));
  }

  // Process booking from WhatsApp message
  async processWhatsAppBooking(whatsappData) {
    try {
      logger.info('Processing WhatsApp booking:', whatsappData);

      const bookingData = {
        clientName: whatsappData.bookingData.clientName,
        phone: whatsappData.phone,
        service: whatsappData.bookingData.service,
        date: whatsappData.bookingData.date,
        time: whatsappData.bookingData.time,
        location: whatsappData.bookingData.location,
        source: 'whatsapp',
        confidence: whatsappData.bookingData.confidence
      };

      // If confidence is low, flag for manual review
      if (bookingData.confidence < 0.7) {
        bookingData.status = 'pending_review';
        bookingData.notes = 'Low confidence extraction - requires manual review';
      }

      const booking = await this.createBooking(bookingData);
      
      logger.info(`Processed WhatsApp booking ${booking.id}`);
      return booking;
    } catch (error) {
      logger.error('Error processing WhatsApp booking:', error);
      throw error;
    }
  }
}

module.exports = new BookingService(); 