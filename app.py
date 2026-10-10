import os
import json
import subprocess
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'bro-net-ultra-security-2026'

# --- CONFIGURACIÓN DE RUTAS Y CARPETAS ---
# Usamos la carpeta temporal /tmp obligatoria de los servidores en la nube para evitar errores de escritura
UPLOAD_FOLDER = '/tmp/uploads/'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Inicialización limpia de Sockets compatible con el entorno virtual de Vercel
socketio = SocketIO(app, cors_allowed_origins="*")

USER_DB = '/tmp/users.json'
MSG_DB = '/tmp/messages.json'

online_users = {}

def load_data(path, default=[]):
    if not os.path.exists(path):
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(default, f)
        except Exception:
            return default
        return default
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_data(path, data):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass

# --- RUTAS HTTP ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    u_name = data.get('username')
    email = data.get('email', "")
    pwd = data.get('password')
    
    users = load_data(USER_DB)
    user_found = next((u for u in users if u['username'] == u_name or u['email'] == u_name), None)
    
    if user_found:
        if user_found['password'] == pwd:
            return jsonify({"status": "ok", "user": user_found})
        return jsonify({"status": "error", "msg": "Contraseña incorrecta"}), 401
    else:
        if not email.lower().endswith("@gmail.com"):
            return jsonify({"status": "error", "msg": "Se requiere un correo @gmail.com para el registro"}), 400
        if any(u['username'] == u_name for u in users):
            return jsonify({"status": "error", "msg": "Ese nombre de usuario ya está en uso"}), 400
        
        new_user = {
            "username": u_name,
            "email": email,
            "password": pwd,
            "bio": "Arquitecto en BroNet",
            "pic": "/static/logo.png"
        }
        users.append(new_user)
        save_data(USER_DB, users)
        return jsonify({"status": "ok", "user": new_user})

@app.route('/update_profile', methods=['POST'])
def update_profile():
    u_name = request.form.get('username')
    bio = request.form.get('bio')
    users = load_data(USER_DB)
    
    for u in users:
        if u['username'] == u_name:
            u['bio'] = bio
            if 'file' in request.files:
                file = request.files['file']
                filename = secure_filename(f"profile_{u_name}_{file.filename}")
                path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(path)
                
                try:
                    result = subprocess.run(['clamscan', path], capture_output=True, text=True)
                    if "Infected files: 0" not in result.stdout:
                        os.remove(path)
                        return jsonify({"status": "error", "msg": "¡PELIGRO! Archivo desintegrado por contener un virus."}), 400
                except FileNotFoundError:
                    pass
                
                u['pic'] = f"/static/uploads/{filename}"
                
            save_data(USER_DB, users)
            return jsonify({"status": "ok", "user": u})
            
    return jsonify({"status": "error", "msg": "Usuario no encontrado"}), 404

@app.route('/upload_audio', methods=['POST'])
def upload_audio():
    if 'audio' not in request.files:
        return jsonify({"status": "error", "msg": "No se recibió archivo de audio"}), 400
    file = request.files['audio']
    filename = secure_filename(file.filename)
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(path)
    return jsonify({"status": "ok", "url": f"/static/uploads/{filename}"})

@app.route('/upload_brol', methods=['POST'])
def upload_brol():
    if 'file' not in request.files:
        return jsonify({"status": "error", "msg": "Sin archivo de video"}), 400
    file = request.files['file']
    filename = secure_filename(f"brol_{file.filename}")
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(path)
    return jsonify({"status": "ok", "msg": "¡Brol publicado con éxito!"})

@app.route('/get_brols', methods=['GET'])
def get_brols():
    try:
        videos = [
            {"title": f.split('_')[-1], "url": f"/static/uploads/{f}"}
            for f in os.listdir(app.config['UPLOAD_FOLDER'])
            if f.startswith('brol_') and f.endswith(('.mp4', '.mov', '.webm'))
        ]
        return jsonify(videos)
    except Exception:
        return jsonify([])

@app.route('/get_users', methods=['GET'])
def get_users():
    users = load_data(USER_DB)
    active_names = list(online_users.values())
    return jsonify([
        {
            "username": u['username'],
            "online": u['username'] in active_names,
            "pic": u['pic'],
            "bio": u.get('bio', '')
        } for u in users
    ])

@app.route('/get_history', methods=['POST'])
def get_history():
    data = request.json
    room = f"room_{min(data['user'], data['target'])}_{max(data['user'], data['target'])}"
    msgs = load_data(MSG_DB)
    return jsonify([m for m in msgs if m['room'] == room])

# --- INTERFACES DE CONEXIÓN PARA MANEJAR EVENTOS ---
@socketio.on('set_identity')
def set_identity(data):
    online_users[request.sid] = data['user']
    emit('status_update', list(online_users.values()), broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in online_users:
        del online_users[request.sid]
        emit('status_update', list(online_users.values()), broadcast=True)

@socketio.on('typing')
def handle_typing(data):
    room = f"room_{min(data['user'], data['target'])}_{max(data['user'], data['target'])}"
    emit('is_typing', {"user": data['user']}, room=room, include_self=False)

@socketio.on('join_private')
def on_join(data):
    room = f"room_{min(data['user'], data['target'])}_{max(data['user'], data['target'])}"
    join_room(room)

@socketio.on('send_msg')
def on_msg(data):
    room = f"room_{min(data['user'], data['target'])}_{max(data['user'], data['target'])}"
    msgs = load_data(MSG_DB)
    new_m = {"room": room, "user": data['user'], "msg": data['msg']}
    msgs.append(new_m)
    save_data(MSG_DB, msgs)
    emit('new_msg', new_m, room=room)

# Exponemos la aplicación nativa para que Vercel la invoque como WSGI ejecutable
def handler(environ, start_response):
    return app(environ, start_response)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    socketio.run(app, host='0.0.0.0', port=port)
