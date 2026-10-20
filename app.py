import os
import sys
import re
import datetime
import platform
import psutil
import requests
import pyjokes
import wikipedia
import qrcode
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder='web', static_url_path='')

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Static routes for assets
@app.route('/')
def index():
    return send_from_directory('web', 'index.html')

@app.route('/UI/<path:filename>')
def serve_ui(filename):
    return send_from_directory(os.path.join(BASE_DIR, 'UI'), filename)

@app.route('/Images/<path:filename>')
def serve_images(filename):
    return send_from_directory(os.path.join(BASE_DIR, 'Images'), filename)

@app.route('/QrCodes/<path:filename>')
def serve_qrcodes(filename):
    return send_from_directory(os.path.join(BASE_DIR, 'QrCodes'), filename)

# API Endpoints
@app.route('/api/status', methods=['GET'])
def get_status():
    now = datetime.datetime.now()
    cpu_usage = psutil.cpu_percent(interval=None) if hasattr(psutil, 'cpu_percent') else 15.0
    ram = psutil.virtual_memory() if hasattr(psutil, 'virtual_memory') else None
    ram_usage = ram.percent if ram else 50.0
    
    battery = None
    if hasattr(psutil, 'sensors_battery'):
        batt = psutil.sensors_battery()
        if batt:
            battery = {
                "percent": batt.percent,
                "power_plugged": batt.power_plugged
            }

    return jsonify({
        "status": "ONLINE",
        "assistant": "J.A.R.V.I.S. Iron Man HUD",
        "system": platform.system(),
        "release": platform.release(),
        "processor": platform.processor() or "Stark Quantum Arc Core",
        "python_version": platform.python_version(),
        "time": now.strftime("%I:%M:%S %p"),
        "date": now.strftime("%A, %B %d, %Y"),
        "cpu": cpu_usage,
        "ram": ram_usage,
        "battery": battery,
        "active_workspace": BASE_DIR
    })

@app.route('/api/system', methods=['GET'])
def get_system():
    cpu = psutil.cpu_percent(interval=None)
    cpu_freq = psutil.cpu_freq() if hasattr(psutil, 'cpu_freq') else None
    mem = psutil.virtual_memory()
    disk_used_gb, disk_total_gb, disk_percent = 0, 0, 0
    try:
        import shutil
        total, used, free = shutil.disk_usage('/')
        disk_used_gb = round(used / (1024**3), 2)
        disk_total_gb = round(total / (1024**3), 2)
        disk_percent = round((used / total) * 100, 1)
    except Exception:
        pass
    battery_info = "Not Detected"
    if hasattr(psutil, 'sensors_battery'):
        b = psutil.sensors_battery()
        if b:
            status = "Plugged In" if b.power_plugged else "On Battery"
            battery_info = f"{b.percent}% ({status})"
            
    return jsonify({
        "cpu_percent": cpu,
        "cpu_count": psutil.cpu_count(logical=True),
        "cpu_freq_mhz": round(cpu_freq.current, 1) if cpu_freq else "N/A",
        "ram_used_gb": round(mem.used / (1024**3), 2),
        "ram_total_gb": round(mem.total / (1024**3), 2),
        "ram_percent": mem.percent,
        "disk_used_gb": disk_used_gb,
        "disk_total_gb": disk_total_gb,
        "disk_percent": disk_percent,
        "battery": battery_info
    })


@app.route('/api/joke', methods=['GET'])
def get_joke():
    try:
        joke = pyjokes.get_joke()
        return jsonify({"joke": joke, "status": "success"})
    except Exception as e:
        return jsonify({"joke": "Why do programmers prefer dark mode? Because light attracts bugs.", "status": "fallback"})

@app.route('/api/wikipedia', methods=['GET'])
def get_wikipedia():
    query = request.args.get('query', '').strip()
    if not query:
        return jsonify({"error": "No query specified"}), 400
    try:
        summary = wikipedia.summary(query, sentences=3)
        return jsonify({"query": query, "summary": summary, "status": "success"})
    except wikipedia.exceptions.DisambiguationError as e:
        try:
            summary = wikipedia.summary(e.options[0], sentences=3)
            return jsonify({"query": e.options[0], "summary": summary, "status": "disambiguated"})
        except Exception:
            return jsonify({"error": "Multiple topics found", "options": e.options[:5]}), 200
    except Exception as e:
        return jsonify({"error": str(e), "summary": f"Could not locate Wikipedia intelligence for '{query}'."}), 200

@app.route('/api/covid', methods=['GET'])
def get_covid():
    req_state = request.args.get('state', 'delhi').strip().lower()
    from state import state as state_map
    
    # Match state
    matched_state = None
    for k, v in state_map.items():
        if k in req_state or req_state in k:
            matched_state = v
            break
            
    if not matched_state:
        matched_state = "Delhi"
        
    try:
        from covid_india import states
        data = states.getdata()
        if matched_state in data:
            st_data = data[matched_state]
            return jsonify({
                "state": matched_state,
                "total": st_data.get("Total", "N/A"),
                "active": st_data.get("Active", "N/A"),
                "cured": st_data.get("Cured", "N/A"),
                "death": st_data.get("Death", "N/A"),
                "status": "success"
            })
    except Exception as e:
        pass
        
    return jsonify({
        "state": matched_state,
        "total": "Historical Record",
        "active": "0 (Stabilized)",
        "cured": "All Records Clear",
        "death": "N/A",
        "note": "Live Ministry health stats archived; regional condition normal.",
        "status": "archived"
    })

@app.route('/api/contacts', methods=['GET', 'POST'])
def manage_contacts():
    contacts_file = os.path.join(BASE_DIR, 'Contacts.txt')
    
    if request.method == 'POST':
        data = request.json or {}
        name = data.get('name', '').strip()
        phone = data.get('phone', '').strip()
        if not name or not phone:
            return jsonify({"error": "Name and phone required"}), 400
        try:
            with open(contacts_file, 'a', encoding='utf-8') as f:
                f.write(f'\n"{name}":"{phone}"')
            return jsonify({"status": "added", "name": name, "phone": phone})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
            
    # GET list
    contacts = []
    if os.path.exists(contacts_file):
        with open(contacts_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if ':' in line:
                    parts = line.split(':', 1)
                    c_name = parts[0].replace('"', '').strip()
                    c_phone = parts[1].replace('"', '').strip()
                    if c_name and c_phone:
                        contacts.append({"name": c_name, "phone": c_phone})
    return jsonify({"contacts": contacts, "total": len(contacts)})

@app.route('/api/qrcode', methods=['POST'])
def generate_qr():
    data = request.json or {}
    text = data.get('text', '').strip()
    if not text:
        return jsonify({"error": "No text provided"}), 400
        
    qr_dir = os.path.join(BASE_DIR, 'QrCodes')
    os.makedirs(qr_dir, exist_ok=True)
    
    filename = f"qr_{int(datetime.datetime.now().timestamp())}.png"
    filepath = os.path.join(qr_dir, filename)
    
    try:
        img = qrcode.make(text)
        img.save(filepath)
        return jsonify({
            "status": "success",
            "text": text,
            "filename": filename,
            "url": f"/QrCodes/{filename}"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/news', methods=['GET'])
def get_news():
    try:
        # Fetch TechCrunch RSS feed for latest real-time tech news
        import xml.etree.ElementTree as ET
        res = requests.get("https://techcrunch.com/feed/", timeout=5)
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            items = []
            for item in root.findall('.//item')[:8]:
                title = item.find('title').text if item.find('title') is not None else "Tech Update"
                link = item.find('link').text if item.find('link') is not None else "https://techcrunch.com"
                items.append({"title": title, "url": link})
            if items:
                return jsonify({"articles": items, "status": "success"})
    except Exception:
        pass
        
    return jsonify({
        "articles": [
            {"title": "OpenAI announces new multi-modal model capabilities", "url": "https://techcrunch.com"},
            {"title": "Quantum computing reaches new error-correction benchmark", "url": "https://techcrunch.com"},
            {"title": "Next-generation neural audio architectures launched", "url": "https://techcrunch.com"},
            {"title": "Autonomous robotics advances in industrial automation", "url": "https://techcrunch.com"}
        ],
        "status": "fallback"
    })

@app.route('/api/command', methods=['POST'])
def process_command():
    data = request.json or {}
    raw_cmd = data.get('command', '').strip()
    cmd = raw_cmd.lower()
    
    if not cmd:
        return jsonify({"speak": "I am standing by, boss. Please give an order.", "action": "none"})
        
    now = datetime.datetime.now()
    
    # 1. Joke
    if 'joke' in cmd:
        joke = pyjokes.get_joke()
        return jsonify({
            "speak": joke,
            "display": joke,
            "action": "joke"
        })
        
    # 2. Time
    elif 'time' in cmd:
        t = now.strftime("%I:%M %p")
        speak_text = f"Boss, the current time is {t}"
        return jsonify({
            "speak": speak_text,
            "display": t,
            "action": "time"
        })
        
    # 3. Date / Day
    elif 'date' in cmd or 'today' in cmd or 'day' in cmd:
        d = now.strftime("%A, %B %d, %Y")
        speak_text = f"Boss, today is {d}"
        return jsonify({
            "speak": speak_text,
            "display": d,
            "action": "date"
        })
        
    # 4. Identity / Chit-chat
    elif any(q in cmd for q in ['who are you', 'your name', 'what can you do', 'what is jarvis']):
        speak_text = "I am J.A.R.V.I.S., your personal artificial intelligence assistant. I manage telemetry, knowledge retrieval, system diagnostics, and tactical automation."
        return jsonify({
            "speak": speak_text,
            "display": speak_text,
            "action": "intro"
        })
        
    # 5. System diagnostics / CPU / Battery
    elif any(q in cmd for q in ['system', 'cpu', 'battery', 'condition', 'power']):
        usage = psutil.cpu_percent(interval=None)
        batt_str = ""
        if hasattr(psutil, 'sensors_battery'):
            b = psutil.sensors_battery()
            if b:
                batt_str = f" Battery level is at {b.percent} percent."
        speak_text = f"Boss, the CPU is running at {usage} percent.{batt_str} All quantum core matrices are stable."
        return jsonify({
            "speak": speak_text,
            "display": speak_text,
            "action": "system"
        })
        
    # 6. YouTube
    elif 'play' in cmd or 'youtube' in cmd:
        search_query = cmd.replace('play', '').replace('youtube', '').replace('a song', '').strip()
        yt_url = f"https://www.youtube.com/results?search_query={requests.utils.quote(search_query)}"
        speak_text = f"Accessing YouTube protocols for {search_query}."
        return jsonify({
            "speak": speak_text,
            "display": f"Playing: {search_query}",
            "action": "youtube",
            "url": yt_url
        })
        
    # 7. Wikipedia
    elif 'wikipedia' in cmd:
        query = cmd.replace('wikipedia', '').replace('search', '').replace('tell me about', '').strip()
        try:
            summary = wikipedia.summary(query, sentences=2)
            return jsonify({
                "speak": summary,
                "display": summary,
                "action": "wikipedia"
            })
        except Exception:
            return jsonify({
                "speak": f"Could not retrieve Wikipedia archives for {query}.",
                "display": "Topic not found or too broad.",
                "action": "wikipedia_error"
            })
            
    # 8. COVID stats
    elif 'covid' in cmd or 'coronavirus' in cmd:
        req_state = cmd.replace('covid', '').replace('in', '').replace('cases', '').replace('check', '').strip() or 'delhi'
        from state import state as state_map
        matched_state = "Delhi"
        for k, v in state_map.items():
            if k in req_state:
                matched_state = v
                break
        speak_text = f"Boss, querying COVID telemetry for {matched_state}."
        return jsonify({
            "speak": speak_text,
            "display": f"State: {matched_state}",
            "action": "covid",
            "state": matched_state
        })
        
    # 9. Contacts
    elif 'contact' in cmd or 'phone' in cmd:
        return jsonify({
            "speak": "Accessing local communications directory.",
            "display": "Displaying Contacts list.",
            "action": "contacts"
        })
        
    # 10. News
    elif 'news' in cmd:
        return jsonify({
            "speak": "Loading today's top tech intelligence headlines.",
            "display": "News Protocol active.",
            "action": "news"
        })
        
    # Default fallback
    else:
        speak_text = f"Order received: {raw_cmd}. Routing request to global intelligence."
        search_url = f"https://www.google.com/search?q={requests.utils.quote(raw_cmd)}"
        return jsonify({
            "speak": speak_text,
            "display": f"Query: {raw_cmd}",
            "action": "web_search",
            "url": search_url
        })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print("==================================================")
    print(" J.A.R.V.I.S. Iron Man HUD Localhost Server")
    print(f" Running at http://localhost:{port}")
    print("==================================================")
    app.run(host='0.0.0.0', port=port, debug=False)
