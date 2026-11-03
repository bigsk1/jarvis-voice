(function () {
    'use strict';
    const destination = window.JarvisUINavigation?.loginDestination(new URLSearchParams(location.search).get('redirect')) || '/';
    const error = document.getElementById('loginError');
    function remember(token, seconds) {
        localStorage.setItem('jarvis_auth_token', token);
        document.cookie = `jarvis_auth=${token}; path=/; max-age=${seconds}; SameSite=Lax`;
        location.assign(destination);
    }
    const cookie = document.cookie.split(';').map(value => value.trim()).find(value => value.startsWith('jarvis_auth='));
    const existing = cookie ? decodeURIComponent(cookie.slice('jarvis_auth='.length)) : localStorage.getItem('jarvis_auth_token');
    if (existing) fetch('/api/auth/verify', {headers: {Authorization: 'Bearer ' + existing}})
        .then(response => response.json()).then(data => {
            if (data.ok) remember(existing, data.expires_at ? Math.max(1, data.expires_at - Math.floor(Date.now() / 1000)) : 30 * 86400);
        }).catch(() => {});
    document.getElementById('loginForm').addEventListener('submit', async event => {
        event.preventDefault(); error.hidden = true; const button = document.getElementById('loginButton'); button.disabled = true;
        try {
            const response = await fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({password: document.getElementById('password').value})});
            const data = await response.json();
            if (!response.ok || !data.ok || !data.token) throw new Error(data.error || 'Sign-in failed.');
            remember(data.token, (data.expires_in_days || 30) * 86400);
        } catch (failure) { error.textContent = failure.message; error.hidden = false; }
        finally { button.disabled = false; }
    });
})();
