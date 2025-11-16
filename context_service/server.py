#!/usr/bin/env python3
"""
Minimal HTTP server for context storage service.
"""

from flask import Flask, request, jsonify

try:
    from .storage import ContextStorage
except ImportError:
    from storage import ContextStorage

app = Flask(__name__)
storage = ContextStorage()


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"})


@app.route('/context/<user_id>/<match_id>', methods=['GET'])
def get_context(user_id: str, match_id: str):
    """Get context for a user-match pair."""
    context = storage.get_context(user_id, match_id)
    if context is None:
        return jsonify({"error": "Context not found"}), 404
    return jsonify({"user_id": user_id, "match_id": match_id, "context": context})


@app.route('/context/<user_id>/<match_id>', methods=['POST', 'PUT'])
def set_context(user_id: str, match_id: str):
    """Set context for a user-match pair."""
    data = request.get_json()
    if not data or 'context' not in data:
        return jsonify({"error": "Missing 'context' in request body"}), 400
    
    context = data['context']
    storage.set_context(user_id, match_id, context)
    return jsonify({
        "user_id": user_id,
        "match_id": match_id,
        "status": "saved"
    })


@app.route('/context/<user_id>/<match_id>', methods=['DELETE'])
def delete_context(user_id: str, match_id: str):
    """Delete context for a user-match pair."""
    storage.delete_context(user_id, match_id)
    return jsonify({
        "user_id": user_id,
        "match_id": match_id,
        "status": "deleted"
    })


@app.route('/context/<user_id>', methods=['GET'])
def get_all_user_contexts(user_id: str):
    """Get all contexts for a user."""
    contexts = storage.get_all_contexts(user_id)
    return jsonify({
        "user_id": user_id,
        "contexts": contexts
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

