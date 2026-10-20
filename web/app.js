// J.A.R.V.I.S. Iron Man HUD Controller

let recognition = null;
let isListening = false;
let synth = window.speechSynthesis;

document.addEventListener('DOMContentLoaded', () => {
    initVoiceRecognition();
    fetchSystemStatus();
    setInterval(fetchSystemStatus, 2000);

    // Keyboard shortcut: Spacebar to toggle voice when input not focused
    window.addEventListener('keydown', (e) => {
        if (e.code === 'Space' && document.activeElement !== document.getElementById('commandInput') && document.activeElement !== document.getElementById('qrInput')) {
            e.preventDefault();
            toggleVoiceListening();
        }
    });
});

// Update Telemetry & Status
async function fetchSystemStatus() {
    try {
        const res = await fetch('/api/status');
        if (!res.ok) return;
        const data = await res.json();

        // Update Date & Time
        document.getElementById('hudDate').textContent = data.date || '--';
        document.getElementById('hudTime').textContent = data.time || '--';

        // Update CPU & RAM
        const cpu = Math.round(data.cpu || 0);
        const ram = Math.round(data.ram || 0);
        document.getElementById('cpuVal').textContent = `${cpu}%`;
        document.getElementById('cpuBar').style.width = `${cpu}%`;
        document.getElementById('ramVal').textContent = `${ram}%`;
        document.getElementById('ramBar').style.width = `${ram}%`;

        // Update Battery / Arc Reactor
        if (data.battery) {
            const battP = data.battery.percent;
            const plug = data.battery.power_plugged ? '⚡ Charging' : 'On Arc Core';
            document.getElementById('batteryVal').textContent = `${battP}% (${plug})`;
            document.getElementById('batteryBar').style.width = `${battP}%`;
        } else {
            document.getElementById('batteryVal').textContent = '100% (STABLE CORE)';
            document.getElementById('batteryBar').style.width = '100%';
        }

        // Update Platform Info
        if (data.system) {
            document.getElementById('platformVal').textContent = `${data.system} ${data.release || ''}`;
        }
        if (data.processor) {
            document.getElementById('procVal').textContent = data.processor.substring(0, 24);
        }

    } catch (err) {
        console.warn('Status poll warning:', err);
    }
}

// Log message to HUD Terminal
function logTerminal(message, type = 'system') {
    const logBox = document.getElementById('terminalLog');
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    
    let prefix = '[SYS]';
    if (type === 'user') prefix = '[COMMAND]';
    if (type === 'jarvis') prefix = '[JARVIS]';

    entry.textContent = `${prefix} ${message}`;
    logBox.appendChild(entry);
    logBox.scrollTop = logBox.scrollHeight;
}

// Speak out response using Web SpeechSynthesis
function jarvisSpeak(text) {
    if (!synth) return;
    synth.cancel(); // cancel any active speech
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.05;
    utterance.pitch = 0.95;

    // Pick deep male or authoritative synth voice if available
    const voices = synth.getVoices();
    const jarvisVoice = voices.find(v => v.name.includes('David') || v.name.includes('George') || v.name.includes('Male') || v.lang.startsWith('en'));
    if (jarvisVoice) {
        utterance.voice = jarvisVoice;
    }

    synth.speak(utterance);
}

// Speech Recognition Init
function initVoiceRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        document.getElementById('listenerStatus').textContent = 'WEB SPEECH API NOT SUPPORTED';
        return;
    }

    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';

    recognition.onstart = () => {
        isListening = true;
        document.getElementById('micBtn').classList.add('listening');
        document.getElementById('listenerStatus').textContent = 'LISTENING FOR AUDIO INPUT...';
        document.getElementById('voiceIndicator').textContent = 'AUDIO SENSORS ACTIVE...';
    };

    recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        logTerminal(transcript, 'user');
        executeCommand(transcript);
    };

    recognition.onerror = (event) => {
        console.warn('Recognition error:', event.error);
        stopListeningState();
    };

    recognition.onend = () => {
        stopListeningState();
    };
}

function stopListeningState() {
    isListening = false;
    document.getElementById('micBtn').classList.remove('listening');
    document.getElementById('listenerStatus').textContent = 'VOICE ENGINE READY';
    document.getElementById('voiceIndicator').textContent = 'CLICK TO ENGAGE SPEECH';
}

function toggleVoiceListening() {
    if (!recognition) {
        logTerminal('Web Speech Recognition is not supported on this browser. Please use text input or Chrome/Edge.', 'system');
        return;
    }

    if (isListening) {
        recognition.stop();
        stopListeningState();
    } else {
        try {
            recognition.start();
        } catch (e) {
            console.error('Recognition start error:', e);
        }
    }
}

// Handle Form Submission
function handleCommandSubmit(e) {
    e.preventDefault();
    const input = document.getElementById('commandInput');
    const command = input.value.trim();
    if (!command) return;

    logTerminal(command, 'user');
    input.value = '';
    executeCommand(command);
}

// Execute Command against Backend
async function executeCommand(cmd) {
    document.getElementById('listenerStatus').textContent = 'PROCESSING TACTICAL ORDER...';
    try {
        const res = await fetch('/api/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: cmd })
        });
        const data = await res.json();

        if (data.speak) {
            logTerminal(data.speak, 'jarvis');
            jarvisSpeak(data.speak);
        }

        // Action handlers
        if (data.action === 'joke') {
            displayIntelCard('PROGRAMMING JOKE', `<p style="font-size: 1.1rem; color: #fff;">"${data.display}"</p>`);
        } else if (data.action === 'time' || data.action === 'date') {
            displayIntelCard('CHRONOMETRIC DATA', `<h2 style="color: var(--cyan);">${data.display}</h2>`);
        } else if (data.action === 'youtube' && data.url) {
            displayIntelCard('MEDIA PROTOCOL', `<p>${data.display}</p><a href="${data.url}" target="_blank" style="color: var(--cyan); text-decoration: underline;">Launch YouTube Stream</a>`);
            window.open(data.url, '_blank');
        } else if (data.action === 'wikipedia') {
            displayIntelCard('WIKIPEDIA ARCHIVE', `<p style="line-height: 1.5;">${data.display}</p>`);
        } else if (data.action === 'covid') {
            requestCovid(data.state || 'delhi');
        } else if (data.action === 'contacts') {
            requestContacts();
        } else if (data.action === 'news') {
            requestNews();
        } else if (data.action === 'web_search' && data.url) {
            displayIntelCard('SEARCH MATRIX', `<p>Accessing online neural grid: <a href="${data.url}" target="_blank" style="color: var(--cyan);">${data.display}</a></p>`);
        }

    } catch (err) {
        logTerminal(`Command execution failed: ${err.message}`, 'system');
    } finally {
        document.getElementById('listenerStatus').textContent = 'VOICE ENGINE READY';
    }
}

// Display Dynamic Card in Right Panel
function displayIntelCard(title, htmlContent) {
    const viewport = document.getElementById('intelViewport');
    viewport.innerHTML = `
        <div class="intel-card active-card">
            <h3 class="card-title">${title}</h3>
            <div class="card-body">${htmlContent}</div>
        </div>
    `;
}

// Quick Actions
async function requestJoke() {
    logTerminal('Requesting programming joke protocol...', 'system');
    try {
        const res = await fetch('/api/joke');
        const data = await res.json();
        logTerminal(data.joke, 'jarvis');
        jarvisSpeak(data.joke);
        displayIntelCard('STARK HUMOR ARCHIVE', `<p style="font-size: 1.05rem; color: #fff; line-height: 1.5;">"${data.joke}"</p>`);
    } catch (e) {
        logTerminal('Failed to load joke protocol', 'system');
    }
}

async function requestNews() {
    logTerminal('Downloading top tech intelligence headlines...', 'system');
    try {
        const res = await fetch('/api/news');
        const data = await res.json();
        let listHtml = '<ul style="list-style: none; display: flex; flex-direction: column; gap: 8px;">';
        data.articles.forEach(art => {
            listHtml += `<li><a href="${art.url}" target="_blank" style="color: var(--cyan); text-decoration: none; font-size: 0.88rem;">⚡ ${art.title}</a></li>`;
        });
        listHtml += '</ul>';
        displayIntelCard('LIVE TECH INTEL', listHtml);
        logTerminal('Loaded latest headlines into tactical intel viewport.', 'jarvis');
        jarvisSpeak('Top intelligence headlines loaded on your dashboard.');
    } catch (e) {
        logTerminal('News retrieval offline', 'system');
    }
}

async function requestCovid(stateName = 'Delhi') {
    logTerminal(`Checking health & COVID-19 statistics for ${stateName}...`, 'system');
    try {
        const res = await fetch(`/api/covid?state=${encodeURIComponent(stateName)}`);
        const data = await res.json();
        
        const html = `
            <div class="data-row"><span class="label">REGION:</span><span class="val cyan">${data.state}</span></div>
            <div class="data-row"><span class="label">ACTIVE CASES:</span><span class="val">${data.active}</span></div>
            <div class="data-row"><span class="label">TOTAL CASES:</span><span class="val">${data.total}</span></div>
            <div class="data-row"><span class="label">RECOVERIES:</span><span class="val" style="color: #00ff88;">${data.cured}</span></div>
            <div class="data-row"><span class="label">STATUS:</span><span class="val">${data.note || 'Regional database synchronized.'}</span></div>
        `;
        displayIntelCard('REGIONAL HEALTH METRICS', html);
        const speakText = `In ${data.state}, active cases are ${data.active}. System status stable.`;
        logTerminal(speakText, 'jarvis');
        jarvisSpeak(speakText);
    } catch (e) {
        logTerminal('Health statistics feed unavailable', 'system');
    }
}

async function requestContacts() {
    logTerminal('Reading communications directory from Contacts.txt...', 'system');
    try {
        const res = await fetch('/api/contacts');
        const data = await res.json();
        let html = `<p style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 8px;">TOTAL CONTACTS STORED: ${data.total}</p>`;
        html += '<div style="max-height: 180px; overflow-y: auto; display: flex; flex-direction: column; gap: 4px;">';
        data.contacts.forEach(c => {
            html += `<div class="data-row"><span class="label">${c.name.toUpperCase()}:</span><span class="val cyan">${c.phone}</span></div>`;
        });
        html += '</div>';
        displayIntelCard('COMMUNICATIONS DIRECTORY', html);
        logTerminal(`Loaded ${data.total} contacts from database.`, 'jarvis');
        jarvisSpeak(`Communications directory loaded. Found ${data.total} contacts.`);
    } catch (e) {
        logTerminal('Failed to read contacts database', 'system');
    }
}

async function generateQR() {
    const input = document.getElementById('qrInput');
    const text = input.value.trim();
    if (!text) return;

    logTerminal(`Synthesizing QR matrix for data: ${text}`, 'system');
    try {
        const res = await fetch('/api/qrcode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text })
        });
        const data = await res.json();
        if (data.url) {
            document.getElementById('qrPreview').innerHTML = `<img src="${data.url}" alt="QR Matrix">`;
            logTerminal(`QR matrix generated: ${data.filename}`, 'jarvis');
            jarvisSpeak('QR matrix successfully synthesized.');
        }
    } catch (e) {
        logTerminal('QR matrix synthesis failed', 'system');
    }
}
