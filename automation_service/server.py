#!/usr/bin/env python3
"""
HTTP server for automation service.
"""

from flask import Flask, request, jsonify
import os
import threading

try:
    from .browser import save_auth_state, test_chat_flow, extract_chat_history
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from automation_service.browser import save_auth_state, test_chat_flow, extract_chat_history

app = Flask(__name__)


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"})


@app.route('/auth/save', methods=['POST'])
def save_auth():
    """Save authentication state (runs in background)."""
    def run_save():
        save_auth_state()
    
    thread = threading.Thread(target=run_save)
    thread.daemon = True
    thread.start()
    
    return jsonify({
        "status": "started",
        "message": "Authentication save process started. Check logs for progress."
    })


@app.route('/chat/test', methods=['POST'])
def test_chat():
    """Test chat flow (runs in background)."""
    def run_test():
        test_chat_flow()
    
    thread = threading.Thread(target=run_test)
    thread.daemon = True
    thread.start()
    
    return jsonify({
        "status": "started",
        "message": "Chat flow test started. Check logs for progress."
    })


@app.route('/chat/extract', methods=['POST'])
def extract_chat():
    """Extract chat history and upload persona."""
    data = request.get_json() or {}
    user_id = data.get('user_id', 'default')
    
    def run_extract():
        try:
            extract_chat_history(user_id=user_id)
        except Exception as e:
            print(f"Error in extract: {e}")
    
    thread = threading.Thread(target=run_extract)
    thread.daemon = True
    thread.start()
    
    return jsonify({
        "status": "started",
        "user_id": user_id,
        "message": "Chat history extraction started. Check logs for progress."
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8082, debug=True)

