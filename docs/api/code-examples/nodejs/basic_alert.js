#!/usr/bin/env node
/**
 * Basic Jarvis Alert - Node.js Example
 * Send a simple alert to Jarvis API
 * 
 * Install: npm install axios
 */

const axios = require('axios');

// Jarvis API endpoint
const JARVIS_API = 'http://localhost:8880/api/alerts';

async function sendAlert(title, description, severity = 'medium', source = 'nodejs-app') {
    const payload = {
        title,
        description,
        severity,
        source
    };
    
    try {
        const response = await axios.post(JARVIS_API, payload, { timeout: 10000 });
        return response.data;
    } catch (error) {
        console.error('Failed to send alert:', error.message);
        return null;
    }
}

// Example usage
(async () => {
    const result = await sendAlert(
        'Test Alert from Node.js',
        'This is a test alert',
        'medium'
    );
    
    if (result && result.ok) {
        console.log(`✅ Alert sent successfully! ID: ${result.alert_id}`);
    } else {
        console.log('❌ Failed to send alert');
    }
})();

