const express = require('express');
const router = express.Router();
const logger = require('../utils/logger');

// Mock payment data - in production, this would be a database
let payments = [
  {
    id: 1,
    bookingId: 1,
    amount: 100.00,
    vatAmount: 5.00,
    totalAmount: 105.00,
    status: 'pending',
    paymentMethod: 'cash',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString()
  }
];

// Calculate VAT (5% as per requirements)
const calculateVAT = (amount) => {
  return Math.round((amount * 0.05) * 100) / 100;
};

// Calculate total amount with VAT
const calculateTotal = (amount) => {
  const vat = calculateVAT(amount);
  return Math.round((amount + vat) * 100) / 100;
};

// GET /api/payment - Get all payments
router.get('/', (req, res) => {
  try {
    const { status, bookingId } = req.query;
    let filteredPayments = [...payments];

    if (status) {
      filteredPayments = filteredPayments.filter(payment => payment.status === status);
    }

    if (bookingId) {
      filteredPayments = filteredPayments.filter(payment => payment.bookingId === parseInt(bookingId));
    }

    logger.info(`Retrieved ${filteredPayments.length} payments`);
    res.json({
      success: true,
      data: filteredPayments,
      count: filteredPayments.length
    });
  } catch (error) {
    logger.error('Error retrieving payments:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to retrieve payments'
    });
  }
});

// GET /api/payment/:id - Get payment by ID
router.get('/:id', (req, res) => {
  try {
    const paymentId = parseInt(req.params.id);
    const payment = payments.find(p => p.id === paymentId);

    if (!payment) {
      return res.status(404).json({
        success: false,
        error: 'Payment not found'
      });
    }

    logger.info(`Retrieved payment ${paymentId}`);
    res.json({
      success: true,
      data: payment
    });
  } catch (error) {
    logger.error('Error retrieving payment:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to retrieve payment'
    });
  }
});

// POST /api/payment - Create new payment
router.post('/', (req, res) => {
  try {
    const { bookingId, amount, paymentMethod = 'cash' } = req.body;

    if (!bookingId || !amount) {
      return res.status(400).json({
        success: false,
        error: 'Booking ID and amount are required'
      });
    }

    const vatAmount = calculateVAT(amount);
    const totalAmount = calculateTotal(amount);

    const newPayment = {
      id: payments.length + 1,
      bookingId: parseInt(bookingId),
      amount: parseFloat(amount),
      vatAmount,
      totalAmount,
      status: 'pending',
      paymentMethod,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };

    payments.push(newPayment);

    logger.info(`Created payment ${newPayment.id} for booking ${bookingId}`);
    res.status(201).json({
      success: true,
      data: newPayment,
      message: 'Payment created successfully'
    });
  } catch (error) {
    logger.error('Error creating payment:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to create payment'
    });
  }
});

// PUT /api/payment/:id/status - Update payment status
router.put('/:id/status', (req, res) => {
  try {
    const paymentId = parseInt(req.params.id);
    const { status } = req.body;

    if (!status || !['pending', 'paid', 'failed', 'refunded'].includes(status)) {
      return res.status(400).json({
        success: false,
        error: 'Valid status is required (pending, paid, failed, refunded)'
      });
    }

    const payment = payments.find(p => p.id === paymentId);
    if (!payment) {
      return res.status(404).json({
        success: false,
        error: 'Payment not found'
      });
    }

    payment.status = status;
    payment.updatedAt = new Date().toISOString();

    logger.info(`Updated payment ${paymentId} status to ${status}`);
    res.json({
      success: true,
      data: payment,
      message: 'Payment status updated successfully'
    });
  } catch (error) {
    logger.error('Error updating payment status:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to update payment status'
    });
  }
});

// POST /api/payment/calculate - Calculate payment with VAT
router.post('/calculate', (req, res) => {
  try {
    const { amount } = req.body;

    if (!amount || isNaN(amount)) {
      return res.status(400).json({
        success: false,
        error: 'Valid amount is required'
      });
    }

    const vatAmount = calculateVAT(amount);
    const totalAmount = calculateTotal(amount);

    res.json({
      success: true,
      data: {
        originalAmount: parseFloat(amount),
        vatAmount,
        totalAmount,
        vatRate: '5%'
      }
    });
  } catch (error) {
    logger.error('Error calculating payment:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to calculate payment'
    });
  }
});

// GET /api/payment/stats - Get payment statistics
router.get('/stats/overview', (req, res) => {
  try {
    const totalPayments = payments.length;
    const paidPayments = payments.filter(p => p.status === 'paid');
    const pendingPayments = payments.filter(p => p.status === 'pending');
    
    const totalRevenue = paidPayments.reduce((sum, p) => sum + p.totalAmount, 0);
    const totalVAT = paidPayments.reduce((sum, p) => sum + p.vatAmount, 0);

    res.json({
      success: true,
      data: {
        totalPayments,
        paidPayments: paidPayments.length,
        pendingPayments: pendingPayments.length,
        totalRevenue,
        totalVAT,
        averagePayment: totalPayments > 0 ? Math.round((totalRevenue / totalPayments) * 100) / 100 : 0
      }
    });
  } catch (error) {
    logger.error('Error retrieving payment stats:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to retrieve payment statistics'
    });
  }
});

module.exports = router; 