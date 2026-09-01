"""
API REST pour contrôler la Creality V4.2.2 via USB
"""

import os
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
import sys
sys.path.insert(0, '/home/pi/horaltscanner/firmware')
from raspberry_pi.creality_controller import CrealityV422

WEB_DIR = os.path.join(os.path.dirname(__file__), '..', 'web')

app = Flask(__name__, static_folder=WEB_DIR, static_url_path='')
CORS(app)

# Instance Creality
printer = CrealityV422()

@app.route('/')
def index():
    """Serve the web UI"""
    return send_from_directory(WEB_DIR, 'index.html')


@app.before_request
def connect_printer():
    """Vérifier la connexion pour les routes API"""
    if not request.path.startswith('/api/'):
        return
    if not printer.connected:
        if not printer.connect():
            return jsonify({"error": "Imprimante non connectée"}), 503

@app.route('/api/status', methods=['GET'])
def status():
    """État de l'imprimante"""
    temps = printer.get_temps()
    return jsonify({
        "connected": printer.connected,
        "temperatures": temps,
        "port": printer.port
    })

@app.route('/api/home', methods=['POST'])
def home():
    """Homing"""
    printer.home()
    return jsonify({"status": "Homing en cours"})

@app.route('/api/move', methods=['POST'])
def move():
    """Déplacer à une position"""
    data = request.json
    x = data.get('x', 50)
    y = data.get('y', 50)
    z = data.get('z', 10)
    speed = data.get('speed', 3000)
    
    printer.move_to(x, y, z, speed)
    return jsonify({"status": f"Déplacement vers X={x} Y={y} Z={z}"})

@app.route('/api/extrude', methods=['POST'])
def extrude():
    """Extruder"""
    data = request.json
    length = data.get('length', 10)
    speed = data.get('speed', 100)
    
    printer.extrude(length, speed)
    return jsonify({"status": f"Extrusion {length}mm"})

@app.route('/api/temp/nozzle', methods=['POST'])
def set_nozzle_temp():
    """Chauffer la buse"""
    data = request.json
    temp = data.get('temp', 200)
    printer.set_temp_nozzle(temp)
    return jsonify({"status": f"Buse: {temp}°C"})

@app.route('/api/temp/bed', methods=['POST'])
def set_bed_temp():
    """Chauffer le lit"""
    data = request.json
    temp = data.get('temp', 60)
    printer.set_temp_bed(temp)
    return jsonify({"status": f"Lit: {temp}°C"})

@app.route('/api/disconnect', methods=['POST'])
def disconnect():
    """Déconnecter"""
    printer.disconnect()
    return jsonify({"status": "Déconnecté"})

@app.route('/health', methods=['GET'])
def health():
    """Health check"""
    return jsonify({"status": "ok"})

@app.route('/api/print', methods=['POST'])
def receive_gcode():
    """Receive a G-code file and send it to the printer (like Cura)"""
    if 'gcode' not in request.files:
        return jsonify({"success": False, "error": "No G-code file provided"}), 400

    file = request.files['gcode']
    if not file or file.filename == '':
        return jsonify({"success": False, "error": "Empty file"}), 400

    try:
        filename = secure_filename(file.filename)
        if not filename:
            return jsonify({"success": False, "error": "Invalid filename"}), 400
        save_path = os.path.join('/tmp', filename)
        file.save(save_path)
        print(f"📤 G-code received: {filename}")
        file_size = os.path.getsize(save_path)
        return jsonify({
            "success": True,
            "message": f"File {filename} sent to printer",
            "file": filename,
            "size": file_size
        })
    except Exception as e:
        print(f"Error saving G-code: {e}")
        return jsonify({"success": False, "message": "Failed to process uploaded file"}), 500


if __name__ == '__main__':
    try:
        print("🚀 API Creality V4.2.2 démarrée")
        print("📍 http://horaltscanner:5000")
        app.run(host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        print("\n✓ Arrêt")
        printer.disconnect()
