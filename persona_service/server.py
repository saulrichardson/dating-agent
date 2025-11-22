#!/usr/bin/env python3
"""
HTTP server for persona extraction.

Extracts messaging style from chat logs and provides it to Automation Service via Context Service.
"""

from flask import Flask, request, jsonify

try:
    from .persona import extract_persona
except ImportError:
    from persona import extract_persona

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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081, debug=True)

