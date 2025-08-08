const express = require('express');
const router = express.Router();
const logger = require('../utils/logger');

// Health check endpoint
router.get('/', async (req, res) => {
  try {
    const healthCheck = {
      status: 'OK',
      timestamp: new Date().toISOString(),
      uptime: process.uptime(),
      environment: process.env.NODE_ENV || 'development',
      version: process.env.npm_package_version || '1.0.0',
      services: {
        database: 'OK', // TODO: Add actual database health check
        redis: 'OK',    // TODO: Add actual Redis health check
        whatsapp: 'OK', // TODO: Add actual WhatsApp API health check
        yclients: 'OK'  // TODO: Add actual YClients API health check
      }
    };

    logger.info('Health check requested', { ip: req.ip });
    
    res.status(200).json(healthCheck);
  } catch (error) {
    logger.error('Health check failed:', error);
    res.status(503).json({
      status: 'ERROR',
      timestamp: new Date().toISOString(),
      error: error.message
    });
  }
});

// Detailed health check
router.get('/detailed', async (req, res) => {
  try {
    const detailedHealth = {
      status: 'OK',
      timestamp: new Date().toISOString(),
      uptime: process.uptime(),
      memory: process.memoryUsage(),
      cpu: process.cpuUsage(),
      environment: process.env.NODE_ENV || 'development',
      version: process.env.npm_package_version || '1.0.0',
      services: {
        database: {
          status: 'OK',
          responseTime: '0ms' // TODO: Add actual database ping
        },
        redis: {
          status: 'OK',
          responseTime: '0ms' // TODO: Add actual Redis ping
        },
        whatsapp: {
          status: 'OK',
          responseTime: '0ms' // TODO: Add actual WhatsApp API ping
        },
        yclients: {
          status: 'OK',
          responseTime: '0ms' // TODO: Add actual YClients API ping
        }
      }
    };

    logger.info('Detailed health check requested', { ip: req.ip });
    
    res.status(200).json(detailedHealth);
  } catch (error) {
    logger.error('Detailed health check failed:', error);
    res.status(503).json({
      status: 'ERROR',
      timestamp: new Date().toISOString(),
      error: error.message
    });
  }
});

module.exports = router; 