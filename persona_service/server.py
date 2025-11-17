#!/usr/bin/env python3
"""
HTTP server for persona extraction and reply generation.
"""

from flask import Flask, request, jsonify

try:
    from .persona import extract_persona, generate_reply
except ImportError:
    from persona import extract_persona, generate_reply

app = Flask(__name__)


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"})


@app.route('/extract', methods=['POST'])
def extract():
    """Extract persona profile from chat logs."""
    data = request.get_json()
    if not data or 'chat_logs' not in data:
        return jsonify({"error": "Missing 'chat_logs' in request body"}), 400
    
    chat_logs = data['chat_logs']
    try:
        persona = extract_persona(chat_logs)
        return jsonify({"persona": persona})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/generate', methods=['POST'])
def generate():
    """Generate a reply based on persona and recent messages."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing request body"}), 400
    
    if 'persona' not in data:
        return jsonify({"error": "Missing 'persona' in request body"}), 400
    if 'recent_messages' not in data:
        return jsonify({"error": "Missing 'recent_messages' in request body"}), 400
    
    persona = data['persona']
    recent_messages = data['recent_messages']
    
    try:
        reply = generate_reply(persona, recent_messages)
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)

