const express = require('express');
const router = express.Router();
const logger = require('../utils/logger');

// Mock subscription data - in production, this would be a database
let subscriptions = [
  {
    id: 1,
    clientId: 1,
    packageName: 'Premium Massage Package',
    totalSessions: 10,
    usedSessions: 3,
    remainingSessions: 7,
    price: 500.00,
    validFrom: '2024-01-01',
    validUntil: '2024-12-31',
    status: 'active',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString()
  }
];

// Mock subscription packages
const subscriptionPackages = [
  {
    id: 1,
    name: 'Basic Package',
    sessions: 5,
    price: 250.00,
    validityDays: 90,
    description: '5 massage sessions valid for 3 months'
  },
  {
    id: 2,
    name: 'Premium Package',
    sessions: 10,
    price: 450.00,
    validityDays: 180,
    description: '10 massage sessions valid for 6 months'
  },
  {
    id: 3,
    name: 'VIP Package',
    sessions: 20,
    price: 800.00,
    validityDays: 365,
    description: '20 massage sessions valid for 1 year'
  }
];

// Calculate remaining sessions
const calculateRemainingSessions = (total, used) => {
  return Math.max(0, total - used);
};

// Check if subscription is valid
const isSubscriptionValid = (subscription) => {
  const now = new Date();
  const validUntil = new Date(subscription.validUntil);
  return subscription.status === 'active' && now <= validUntil && subscription.remainingSessions > 0;
};

// GET /api/subscription - Get all subscriptions
router.get('/', (req, res) => {
  try {
    const { clientId, status } = req.query;
    let filteredSubscriptions = [...subscriptions];

    if (clientId) {
      filteredSubscriptions = filteredSubscriptions.filter(sub => sub.clientId === parseInt(clientId));
    }

    if (status) {
      filteredSubscriptions = filteredSubscriptions.filter(sub => sub.status === status);
    }

    logger.info(`Retrieved ${filteredSubscriptions.length} subscriptions`);
    res.json({
      success: true,
      data: filteredSubscriptions,
      count: filteredSubscriptions.length
    });
  } catch (error) {
    logger.error('Error retrieving subscriptions:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to retrieve subscriptions'
    });
  }
});

// GET /api/subscription/packages - Get available subscription packages
router.get('/packages', (req, res) => {
  try {
    logger.info('Retrieved subscription packages');
    res.json({
      success: true,
      data: subscriptionPackages
    });
  } catch (error) {
    logger.error('Error retrieving subscription packages:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to retrieve subscription packages'
    });
  }
});

// GET /api/subscription/:id - Get subscription by ID
router.get('/:id', (req, res) => {
  try {
    const subscriptionId = parseInt(req.params.id);
    const subscription = subscriptions.find(s => s.id === subscriptionId);

    if (!subscription) {
      return res.status(404).json({
        success: false,
        error: 'Subscription not found'
      });
    }

    logger.info(`Retrieved subscription ${subscriptionId}`);
    res.json({
      success: true,
      data: subscription
    });
  } catch (error) {
    logger.error('Error retrieving subscription:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to retrieve subscription'
    });
  }
});

// POST /api/subscription - Create new subscription
router.post('/', (req, res) => {
  try {
    const { clientId, packageId, paymentMethod = 'cash' } = req.body;

    if (!clientId || !packageId) {
      return res.status(400).json({
        success: false,
        error: 'Client ID and package ID are required'
      });
    }

    const package = subscriptionPackages.find(p => p.id === parseInt(packageId));
    if (!package) {
      return res.status(400).json({
        success: false,
        error: 'Invalid package ID'
      });
    }

    const validFrom = new Date();
    const validUntil = new Date();
    validUntil.setDate(validUntil.getDate() + package.validityDays);

    const newSubscription = {
      id: subscriptions.length + 1,
      clientId: parseInt(clientId),
      packageName: package.name,
      totalSessions: package.sessions,
      usedSessions: 0,
      remainingSessions: package.sessions,
      price: package.price,
      validFrom: validFrom.toISOString().split('T')[0],
      validUntil: validUntil.toISOString().split('T')[0],
      status: 'active',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };

    subscriptions.push(newSubscription);

    logger.info(`Created subscription ${newSubscription.id} for client ${clientId}`);
    res.status(201).json({
      success: true,
      data: newSubscription,
      message: 'Subscription created successfully'
    });
  } catch (error) {
    logger.error('Error creating subscription:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to create subscription'
    });
  }
});

// POST /api/subscription/:id/use-session - Use a session from subscription
router.post('/:id/use-session', (req, res) => {
  try {
    const subscriptionId = parseInt(req.params.id);
    const { bookingId } = req.body;

    const subscription = subscriptions.find(s => s.id === subscriptionId);
    if (!subscription) {
      return res.status(404).json({
        success: false,
        error: 'Subscription not found'
      });
    }

    if (!isSubscriptionValid(subscription)) {
      return res.status(400).json({
        success: false,
        error: 'Subscription is not valid or has no remaining sessions'
      });
    }

    subscription.usedSessions += 1;
    subscription.remainingSessions = calculateRemainingSessions(subscription.totalSessions, subscription.usedSessions);
    subscription.updatedAt = new Date().toISOString();

    // Check if subscription is running low (less than 3 sessions remaining)
    const isLowOnSessions = subscription.remainingSessions <= 3;

    logger.info(`Used session from subscription ${subscriptionId}, ${subscription.remainingSessions} remaining`);
    res.json({
      success: true,
      data: subscription,
      message: 'Session used successfully',
      alert: isLowOnSessions ? `Only ${subscription.remainingSessions} sessions remaining` : null
    });
  } catch (error) {
    logger.error('Error using subscription session:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to use subscription session'
    });
  }
});

// PUT /api/subscription/:id/status - Update subscription status
router.put('/:id/status', (req, res) => {
  try {
    const subscriptionId = parseInt(req.params.id);
    const { status } = req.body;

    if (!status || !['active', 'paused', 'cancelled', 'expired'].includes(status)) {
      return res.status(400).json({
        success: false,
        error: 'Valid status is required (active, paused, cancelled, expired)'
      });
    }

    const subscription = subscriptions.find(s => s.id === subscriptionId);
    if (!subscription) {
      return res.status(404).json({
        success: false,
        error: 'Subscription not found'
      });
    }

    subscription.status = status;
    subscription.updatedAt = new Date().toISOString();

    logger.info(`Updated subscription ${subscriptionId} status to ${status}`);
    res.json({
      success: true,
      data: subscription,
      message: 'Subscription status updated successfully'
    });
  } catch (error) {
    logger.error('Error updating subscription status:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to update subscription status'
    });
  }
});

// GET /api/subscription/alerts/low-sessions - Get subscriptions with low sessions
router.get('/alerts/low-sessions', (req, res) => {
  try {
    const lowSessionSubscriptions = subscriptions.filter(sub => 
      sub.status === 'active' && sub.remainingSessions <= 3
    );

    logger.info(`Found ${lowSessionSubscriptions.length} subscriptions with low sessions`);
    res.json({
      success: true,
      data: lowSessionSubscriptions,
      count: lowSessionSubscriptions.length
    });
  } catch (error) {
    logger.error('Error retrieving low session alerts:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to retrieve low session alerts'
    });
  }
});

// GET /api/subscription/alerts/expiring - Get subscriptions expiring soon
router.get('/alerts/expiring', (req, res) => {
  try {
    const thirtyDaysFromNow = new Date();
    thirtyDaysFromNow.setDate(thirtyDaysFromNow.getDate() + 30);

    const expiringSubscriptions = subscriptions.filter(sub => {
      const validUntil = new Date(sub.validUntil);
      return sub.status === 'active' && validUntil <= thirtyDaysFromNow;
    });

    logger.info(`Found ${expiringSubscriptions.length} subscriptions expiring soon`);
    res.json({
      success: true,
      data: expiringSubscriptions,
      count: expiringSubscriptions.length
    });
  } catch (error) {
    logger.error('Error retrieving expiring subscriptions:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to retrieve expiring subscriptions'
    });
  }
});

// GET /api/subscription/stats/overview - Get subscription statistics
router.get('/stats/overview', (req, res) => {
  try {
    const totalSubscriptions = subscriptions.length;
    const activeSubscriptions = subscriptions.filter(s => s.status === 'active');
    const totalSessions = activeSubscriptions.reduce((sum, s) => sum + s.totalSessions, 0);
    const usedSessions = activeSubscriptions.reduce((sum, s) => sum + s.usedSessions, 0);
    const remainingSessions = activeSubscriptions.reduce((sum, s) => sum + s.remainingSessions, 0);

    res.json({
      success: true,
      data: {
        totalSubscriptions,
        activeSubscriptions: activeSubscriptions.length,
        totalSessions,
        usedSessions,
        remainingSessions,
        utilizationRate: totalSessions > 0 ? Math.round((usedSessions / totalSessions) * 100) : 0
      }
    });
  } catch (error) {
    logger.error('Error retrieving subscription stats:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to retrieve subscription statistics'
    });
  }
});

module.exports = router; 