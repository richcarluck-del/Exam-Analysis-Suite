import subprocess
import json
import shlex
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/execute', methods=['POST'])
def execute_command():
    data = request.get_json()
    if not data or 'command' not in data:
        return jsonify({'error': 'Invalid request. Missing \'command\' key.'}), 400

    command_str = data['command']
    print(f"--- Received command: {command_str}", flush=True)

    try:
        # Use shlex to safely split the command string into arguments
        args = shlex.split(command_str)
        print(f"--- Executing args: {args}", flush=True)

        # Execute the command
        result = subprocess.run(
            args, 
            capture_output=True, 
            text=True, 
            encoding='utf-8'
        )

        response_data = {
            'returncode': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr
        }
        print(f"--- Command finished with return code: {result.returncode}", flush=True)
        print(f"--- stdout: {result.stdout}", flush=True)
        print(f"--- stderr: {result.stderr}", flush=True)
        
        return jsonify(response_data)

    except Exception as e:
        error_message = f"Failed to execute command: {str(e)}"
        print(f"--- EXCEPTION: {error_message}", flush=True)
        return jsonify({
            'returncode': -1,
            'stdout': '',
            'stderr': error_message
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
