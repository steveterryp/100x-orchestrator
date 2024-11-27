from flask import Flask, render_template, request, jsonify, send_from_directory
from orchestrator import initialiseCodingAgent, main_loop, load_tasks, save_tasks
import os
import threading
import json
from pathlib import Path
import datetime

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/tasks/tasks.json')
def serve_tasks_json():
    """Serve the tasks.json file"""
    return send_from_directory('tasks', 'tasks.json')

@app.route('/agents')
def agent_view():
    """Render the agent view with all agent details."""
    tasks_data = load_tasks()
    agents = tasks_data.get('agents', {})
    
    # Calculate time until next check
    now = datetime.datetime.now()
    next_check = now + datetime.timedelta(seconds=300)  # 5 minutes from now
    time_until_next_check = int((next_check - now).total_seconds())
    
    # Enrich agent data with more details
    for agent_id, agent in list(agents.items()):  # Use list() to allow modification during iteration
        # Ensure workspace exists, use a default if not
        if 'workspace' not in agent:
            agent['workspace'] = os.path.join('workspaces', agent_id)
            # Update tasks_data to persist the workspace
            tasks_data['agents'][agent_id]['workspace'] = agent['workspace']
        
        # Safely load prompt file
        try:
            prompt_file = Path(agent['workspace']) / 'config' / 'prompt.txt'
            if prompt_file.exists():
                with open(prompt_file, 'r') as f:
                    prompt_data = json.load(f)
                    agent['prompt_details'] = prompt_data
            else:
                agent['prompt_details'] = {}
        except (FileNotFoundError, json.JSONDecodeError):
            agent['prompt_details'] = {}
        
        # Calculate workspace files
        try:
            workspace = Path(agent['workspace'])
            agent['files'] = [str(f) for f in workspace.glob('**/*') if f.is_file()]
        except Exception:
            agent['files'] = []
    
    # Save updated tasks data to persist workspace paths
    save_tasks(tasks_data)
    
    return render_template('agent_view.html', 
                           agents=agents, 
                           time_until_next_check=time_until_next_check)

@app.route('/create_agent', methods=['POST'])
def create_agent():
    try:
        data = request.get_json()
        repo_url = data.get('repo_url')
        tasks = data.get('tasks', [])
        
        if not repo_url or not tasks:
            return jsonify({'error': 'Repository URL and tasks are required'}), 400
        
        # Ensure tasks is a list
        if isinstance(tasks, str):
            tasks = [tasks]
        
        # Load existing tasks
        tasks_data = load_tasks()
        
        # Initialize agents for each task
        created_agents = []
        for task_description in tasks:
            # Set environment variable for repo URL
            os.environ['REPOSITORY_URL'] = repo_url
            
            # Initialize agent
            agent_id = initialiseCodingAgent(repo_url, task_description)
            
            if agent_id:
                created_agents.append(agent_id)
                # Add task to tasks list if not already present
                if task_description not in tasks_data['tasks']:
                    tasks_data['tasks'].append(task_description)
        
        # Update tasks.json with repo URL and agents
        tasks_data['repo_url'] = repo_url
        tasks_data['agents'] = tasks_data.get('agents', {})
        for agent_id in created_agents:
            tasks_data['agents'][agent_id] = {
                'task': tasks_data['tasks'][-1],  # Last added task
                'repo_url': repo_url,
                'workspace': os.path.join('workspaces', agent_id)  # Add workspace path
            }
        
        # Save updated tasks
        save_tasks(tasks_data)
        
        # Start main loop in a separate thread if not already running
        def check_and_start_main_loop():
            # Check if main loop thread is already running
            for thread in threading.enumerate():
                if thread.name == 'OrchestratorMainLoop':
                    return
            
            # Start main loop if not running
            thread = threading.Thread(target=main_loop, name='OrchestratorMainLoop')
            thread.daemon = True
            thread.start()
        
        check_and_start_main_loop()
        
        if created_agents:
            return jsonify({
                'success': True,
                'agent_ids': created_agents,
                'message': f'Agents {", ".join(created_agents)} created successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to create any agents'
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    app.run(debug=True)
