# Massage Booking System API Documentation

## Overview

The Massage Booking System API is a comprehensive backend service that automates the entire booking process for a mobile massage business. It integrates WhatsApp for client communication, YClients for calendar management, and provides automated notifications to therapists and drivers.

## Base URL

```
http://localhost:3000
```

## Authentication

Currently, the API uses basic authentication. In production, implement JWT tokens or API keys.

## API Endpoints

### Health Check

#### GET /health
Check if the API is running.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00.000Z",
  "uptime": 3600,
  "version": "1.0.0"
}
```

### WhatsApp Integration

#### POST /api/whatsapp/webhook
Receive incoming WhatsApp messages and process them for booking information.

**Request Body:**
```json
{
  "object": "whatsapp_business_account",
  "entry": [
    {
      "id": "123456789",
      "changes": [
        {
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {
              "display_phone_number": "+1234567890",
              "phone_number_id": "987654321"
            },
            "messages": [
              {
                "from": "+1234567890",
                "id": "msg_123",
                "timestamp": "1234567890",
                "text": {
                  "body": "Hi, I'd like to book a Swedish massage for tomorrow at 2 PM at my home"
                }
              }
            ]
          }
        }
      ]
    }
  ]
}
```

**Response:**
```json
{
  "success": true,
  "processed": 1,
  "results": [
    {
      "status": "processed",
      "phone": "+1234567890",
      "message": "Hi, I'd like to book a Swedish massage for tomorrow at 2 PM at my home",
      "bookingData": {
        "clientName": null,
        "service": "swedish massage",
        "date": "2024-01-16",
        "time": "14:00",
        "location": "Client Home",
        "phone": "+1234567890",
        "confidence": 0.8
      }
    }
  ]
}
```

#### POST /api/whatsapp/send
Send a WhatsApp message to a client.

**Request Body:**
```json
{
  "phone": "+1234567890",
  "message": "Your booking has been confirmed!"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "messageId": "msg_123456789",
    "status": "sent",
    "timestamp": "2024-01-15T10:30:00.000Z",
    "recipient": "+1234567890"
  }
}
```

### Booking Management

#### GET /api/booking
Get all bookings with optional filters.

**Query Parameters:**
- `status` - Filter by booking status (confirmed, cancelled, completed)
- `clientId` - Filter by client ID
- `date` - Filter by date (YYYY-MM-DD)
- `therapistId` - Filter by therapist ID

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "clientId": 1,
      "clientName": "John Doe",
      "clientPhone": "+1234567890",
      "service": "Swedish Massage",
      "date": "2024-01-15",
      "time": "14:00",
      "duration": 60,
      "location": "123 Main St, City",
      "therapistId": 1,
      "therapistName": "Sarah Johnson",
      "driverId": 1,
      "driverName": "Alex Rodriguez",
      "status": "confirmed",
      "paymentStatus": "pending",
      "price": 100.00,
      "createdAt": "2024-01-15T10:30:00.000Z"
    }
  ],
  "count": 1
}
```

#### POST /api/booking
Create a new booking.

**Request Body:**
```json
{
  "clientName": "Jane Smith",
  "phone": "+1234567890",
  "service": "Swedish Massage",
  "date": "2024-01-16",
  "time": "15:00",
  "location": "456 Oak St, City",
  "notes": "First-time client"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "id": 2,
    "clientId": 2,
    "clientName": "Jane Smith",
    "clientPhone": "+1234567890",
    "service": "Swedish Massage",
    "date": "2024-01-16",
    "time": "15:00",
    "duration": 60,
    "location": "456 Oak St, City",
    "therapistId": 1,
    "therapistName": "Sarah Johnson",
    "driverId": 2,
    "driverName": "Emma Wilson",
    "status": "confirmed",
    "paymentStatus": "pending",
    "price": 80.00,
    "createdAt": "2024-01-15T10:30:00.000Z"
  },
  "message": "Booking created successfully"
}
```

#### GET /api/booking/:id
Get a specific booking by ID.

**Response:**
```json
{
  "success": true,
  "data": {
    "id": 1,
    "clientId": 1,
    "clientName": "John Doe",
    "clientPhone": "+1234567890",
    "service": "Swedish Massage",
    "date": "2024-01-15",
    "time": "14:00",
    "duration": 60,
    "location": "123 Main St, City",
    "therapistId": 1,
    "therapistName": "Sarah Johnson",
    "driverId": 1,
    "driverName": "Alex Rodriguez",
    "status": "confirmed",
    "paymentStatus": "pending",
    "price": 100.00,
    "createdAt": "2024-01-15T10:30:00.000Z"
  }
}
```

#### PUT /api/booking/:id
Update a booking.

**Request Body:**
```json
{
  "status": "completed",
  "notes": "Client was very satisfied"
}
```

#### DELETE /api/booking/:id
Cancel a booking.

**Response:**
```json
{
  "success": true,
  "data": {
    "id": 1,
    "status": "cancelled",
    "cancellationReason": "Client request"
  },
  "message": "Booking cancelled successfully"
}
```

### Payment Management

#### GET /api/payment
Get all payments with optional filters.

**Query Parameters:**
- `status` - Filter by payment status (pending, paid, failed, refunded)
- `bookingId` - Filter by booking ID

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "bookingId": 1,
      "amount": 100.00,
      "vatAmount": 5.00,
      "totalAmount": 105.00,
      "status": "paid",
      "paymentMethod": "cash",
      "createdAt": "2024-01-15T10:30:00.000Z"
    }
  ],
  "count": 1
}
```

#### POST /api/payment
Create a new payment.

**Request Body:**
```json
{
  "bookingId": 1,
  "amount": 100.00,
  "paymentMethod": "cash"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "id": 2,
    "bookingId": 1,
    "amount": 100.00,
    "vatAmount": 5.00,
    "totalAmount": 105.00,
    "status": "pending",
    "paymentMethod": "cash",
    "createdAt": "2024-01-15T10:30:00.000Z"
  },
  "message": "Payment created successfully"
}
```

#### POST /api/payment/calculate
Calculate payment with VAT.

**Request Body:**
```json
{
  "amount": 100.00
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "originalAmount": 100.00,
    "vatAmount": 5.00,
    "totalAmount": 105.00,
    "vatRate": "5%"
  }
}
```

#### PUT /api/payment/:id/status
Update payment status.

**Request Body:**
```json
{
  "status": "paid"
}
```

### Subscription Management

#### GET /api/subscription
Get all subscriptions with optional filters.

**Query Parameters:**
- `clientId` - Filter by client ID
- `status` - Filter by subscription status (active, paused, cancelled, expired)

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "clientId": 1,
      "packageName": "Premium Massage Package",
      "totalSessions": 10,
      "usedSessions": 3,
      "remainingSessions": 7,
      "price": 500.00,
      "validFrom": "2024-01-01",
      "validUntil": "2024-12-31",
      "status": "active",
      "createdAt": "2024-01-01T00:00:00.000Z"
    }
  ],
  "count": 1
}
```

#### GET /api/subscription/packages
Get available subscription packages.

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "name": "Basic Package",
      "sessions": 5,
      "price": 250.00,
      "validityDays": 90,
      "description": "5 massage sessions valid for 3 months"
    },
    {
      "id": 2,
      "name": "Premium Package",
      "sessions": 10,
      "price": 450.00,
      "validityDays": 180,
      "description": "10 massage sessions valid for 6 months"
    }
  ]
}
```

#### POST /api/subscription
Create a new subscription.

**Request Body:**
```json
{
  "clientId": 1,
  "packageId": 2,
  "paymentMethod": "cash"
}
```

#### POST /api/subscription/:id/use-session
Use a session from a subscription.

**Request Body:**
```json
{
  "bookingId": 1
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "id": 1,
    "usedSessions": 4,
    "remainingSessions": 6
  },
  "message": "Session used successfully",
  "alert": "Only 6 sessions remaining"
}
```

#### GET /api/subscription/alerts/low-sessions
Get subscriptions with low sessions (≤3 remaining).

#### GET /api/subscription/alerts/expiring
Get subscriptions expiring within 30 days.

### Notification System

#### GET /api/notification
Get all notifications with optional filters.

**Query Parameters:**
- `type` - Filter by notification type
- `recipientType` - Filter by recipient type (therapist, driver)
- `status` - Filter by notification status

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "type": "booking_confirmation",
      "recipientType": "therapist",
      "recipientId": 1,
      "recipientPhone": "+1234567890",
      "message": "New booking confirmed for tomorrow at 2 PM",
      "status": "sent",
      "bookingId": 1,
      "createdAt": "2024-01-15T10:30:00.000Z"
    }
  ],
  "count": 1
}
```

#### POST /api/notification/send
Send a notification to a single recipient.

**Request Body:**
```json
{
  "type": "booking_confirmation",
  "recipientType": "therapist",
  "recipientId": 1,
  "bookingId": 1,
  "data": {
    "clientName": "John Doe",
    "service": "Swedish Massage",
    "date": "2024-01-16",
    "time": "14:00",
    "location": "123 Main St"
  }
}
```

#### POST /api/notification/bulk-send
Send notifications to multiple recipients.

**Request Body:**
```json
{
  "type": "booking_confirmation",
  "recipientType": "therapist",
  "recipientIds": [1, 2],
  "bookingId": 1,
  "data": {
    "clientName": "John Doe",
    "service": "Swedish Massage",
    "date": "2024-01-16",
    "time": "14:00",
    "location": "123 Main St"
  }
}
```

#### GET /api/notification/recipients/therapists
Get available therapists.

#### GET /api/notification/recipients/drivers
Get available drivers.

### YClients Integration

#### GET /api/yclients/appointments
Get appointments from YClients.

**Query Parameters:**
- `date` - Filter by date (YYYY-MM-DD)
- `status` - Filter by appointment status

#### POST /api/yclients/appointments
Create an appointment in YClients.

**Request Body:**
```json
{
  "clientId": 1,
  "serviceId": 1,
  "date": "2024-01-16",
  "time": "14:00",
  "duration": 60,
  "therapistId": 1
}
```

#### GET /api/yclients/clients
Get clients from YClients.

#### POST /api/yclients/clients
Create a client in YClients.

#### GET /api/yclients/services
Get services from YClients.

## Error Responses

All endpoints return consistent error responses:

```json
{
  "success": false,
  "error": "Error message description"
}
```

Common HTTP status codes:
- `200` - Success
- `201` - Created
- `400` - Bad Request
- `404` - Not Found
- `500` - Internal Server Error

## Environment Variables

Create a `.env` file with the following variables:

```env
# Server Configuration
PORT=3000
NODE_ENV=development

# WhatsApp Business API
WHATSAPP_ACCESS_TOKEN=your_whatsapp_access_token
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
WHATSAPP_WEBHOOK_SECRET=your_webhook_secret

# YClients API
YCLIENTS_API_KEY=your_yclients_api_key
YCLIENTS_COMPANY_ID=your_company_id

# Database (for production)
DATABASE_URL=postgresql://username:password@localhost:5432/massage_booking

# Redis (for caching and sessions)
REDIS_URL=redis://localhost:6379

# Security
JWT_SECRET=your_jwt_secret
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:3001
```

## Getting Started

1. **Install dependencies:**
   ```bash
   npm install
   ```

2. **Set up environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your actual values
   ```

3. **Start the server:**
   ```bash
   npm start
   ```

4. **Test the API:**
   ```bash
   curl http://localhost:3000/health
   ```

## WhatsApp Integration Setup

1. **Set up WhatsApp Business API:**
   - Create a Meta Developer account
   - Set up a WhatsApp Business app
   - Configure webhook URL: `https://your-domain.com/api/whatsapp/webhook`
   - Add webhook verification token

2. **Configure webhook:**
   - The webhook will receive incoming messages
   - Messages are automatically processed for booking information
   - Extracted data is used to create bookings

## YClients Integration Setup

1. **Get API credentials:**
   - Contact YClients for API access
   - Obtain API key and company ID

2. **Configure integration:**
   - Bookings created in the system are synced to YClients
   - Calendar entries are automatically created
   - Client information is synchronized

## Features

### Automated Data Extraction
- Extracts client name, service, date/time, and location from WhatsApp messages
- Uses regex patterns and NLP techniques
- Confidence scoring for extraction accuracy

### Payment Processing
- Automatic 5% VAT calculation
- Multiple payment methods support
- Payment status tracking

### Subscription Management
- Package-based subscriptions
- Session tracking and deduction
- Low session alerts
- Expiration notifications

### Notification System
- WhatsApp notifications to therapists and drivers
- Booking confirmations and reminders
- Payment confirmations
- Subscription alerts

### Integration Features
- WhatsApp Business API integration
- YClients calendar synchronization
- Automated booking creation
- Real-time status updates

## Development

### Project Structure
```
src/
├── api/           # API routes
├── services/      # Business logic
├── utils/         # Utilities and middleware
└── index.js       # Main server file
```

### Adding New Features
1. Create service in `src/services/`
2. Add API routes in `src/api/`
3. Update main server file
4. Add tests
5. Update documentation

### Testing
```bash
npm test
```

## Production Deployment

1. **Set up database:**
   - PostgreSQL for main data
   - Redis for caching and sessions

2. **Configure environment:**
   - Set `NODE_ENV=production`
   - Configure all API keys
   - Set up SSL certificates

3. **Deploy:**
   - Use PM2 or similar process manager
   - Set up reverse proxy (nginx)
   - Configure monitoring and logging

## Support

For technical support or questions about the API, please refer to the project documentation or contact the development team. 