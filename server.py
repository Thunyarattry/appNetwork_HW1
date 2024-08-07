import asyncio
import websockets
import json
import os

clients = []
games = {}  # Dictionary to keep track of games
users_file = 'users.json'

# Load users from file
def load_users():
    if os.path.exists(users_file):
        with open(users_file, 'r') as file:
            return json.load(file)
    return {}

# Save users to file
def save_users(users):
    with open(users_file, 'w') as file:
        json.dump(users, file, indent=4)  # Added indent for readability

users = load_users()

async def register(websocket):
    clients.append(websocket)
    print(f"New client connected. Total clients: {len(clients)}")

async def unregister(websocket):
    clients.remove(websocket)
    print(f"Client disconnected. Total clients: {len(clients)}")
    
    # Remove the player from any ongoing game
    for game_id, game in list(games.items()):
        if websocket in game['players']:
            username = game['player_usernames'][game['players'].index(websocket)]
            game['players'].remove(websocket)
            game['player_usernames'].remove(username)
            print(f"Player '{username}' left game {game_id}. Remaining players: {len(game['players'])}")
            if len(game['players']) == 0:
                print(f"Game {game_id} ended as there are no players left.")
                del games[game_id]
            break

async def handle_client(websocket, path):
    await register(websocket)
    try:
        async for message in websocket:
            data = json.loads(message)
            if data['type'] == 'register':
                await handle_register(websocket, data)
            elif data['type'] == 'login':
                await handle_login(websocket, data)
            elif data['type'] == 'join':
                await handle_join(websocket, data)
            elif data['type'] == 'move':
                await handle_move(websocket, data)
    finally:
        await unregister(websocket)

async def handle_register(websocket, data):
    username = data['username']
    password = data['password']
    
    if username in users:
        await websocket.send(json.dumps({'type': 'register', 'status': 'Username already exists.'}))
        print(f"Registration failed: Username already exists for {username}")
    else:
        users[username] = password
        save_users(users)
        await websocket.send(json.dumps({'type': 'register', 'status': 'Registration successful.'}))
        print(f"User registered: {username}")

async def handle_login(websocket, data):
    username = data['username']
    password = data['password']
    
    if username in users and users[username] == password:
        await websocket.send(json.dumps({'type': 'login', 'status': 'Login successful.', 'username': username}))
        print(f"User logged in: {username}")
    else:
        await websocket.send(json.dumps({'type': 'login', 'status': 'Invalid username or password.'}))
        print(f"Login failed: Invalid credentials for {username}")

async def handle_join(websocket, data):
    if 'game_id' in data:
        game_id = data['game_id']
        if game_id in games:
            if len(games[game_id]['players']) < 2:
                games[game_id]['players'].append(websocket)
                username = data['username']
                games[game_id]['player_usernames'].append(username)
                print(f"Player '{username}' joined game {game_id}. Total players: {len(games[game_id]['players'])}")
                # Notify both players
                for player in games[game_id]['players']:
                    await player.send(json.dumps({'type': 'status', 'status': 'Game started!'}))
                print(f"Game {game_id} started.")
            else:
                await websocket.send(json.dumps({'type': 'status', 'status': 'Game already started or full.'}))
                print(f"Attempted to join a full or already started game {game_id}.")
        else:
            # Create a new game if needed
            games[game_id] = {'players': [websocket], 'moves': {}, 'scores': {0: 0, 1: 0}, 'rounds': 0, 'current_round': 1, 'player_usernames': [data['username']]}
            await websocket.send(json.dumps({'type': 'status', 'status': 'Waiting for an opponent.'}))
            print(f"New game {game_id} created. Waiting for an opponent.")

async def handle_move(websocket, data):
    game_id = data['game_id']
    if game_id in games and websocket in games[game_id]['players']:
        games[game_id]['moves'][websocket] = data['move']
        print(f"Player in game {game_id} made a move: {data['move']}")
        
        # Check if both players have made their moves
        if len(games[game_id]['moves']) == 2:
            moves = games[game_id]['moves']
            player_list = list(moves.keys())
            usernames = games[game_id]['player_usernames']
            player1, player2 = player_list[0], player_list[1]
            username1, username2 = usernames[0], usernames[1]
            move1, move2 = moves[player1], moves[player2]
            
            # Determine winner
            result = determine_winner(move1, move2)
            result_message = {
                'type': 'result',
                'player1': {
                    'username': username1,
                    'move': move1,
                    'result': result['player1'],
                },
                'player2': {
                    'username': username2,
                    'move': move2,
                    'result': result['player2'],
                },
                'result': result['game'],
                'round': games[game_id]['current_round']
            }

            # Update scores
            if result['player1'] == 'Win':
                games[game_id]['scores'][0] += 1
            elif result['player2'] == 'Win':
                games[game_id]['scores'][1] += 1

            # Notify both players
            for player in games[game_id]['players']:
                await player.send(json.dumps(result_message))
                await player.send(json.dumps({
                    'type': 'score',
                    'scores': {
                        games[game_id]['player_usernames'][0]: games[game_id]['scores'][0],
                        games[game_id]['player_usernames'][1]: games[game_id]['scores'][1]
                    },
                    'rounds': games[game_id]['rounds'],
                    'current_round': games[game_id]['current_round']
                }))
            
            print(f"Game {game_id} result sent to players: {result_message}")

            # Check if any player has won 2 rounds
            if games[game_id]['scores'][0] >= 2 or games[game_id]['scores'][1] >= 2:
                winner = games[game_id]['player_usernames'][0] if games[game_id]['scores'][0] > games[game_id]['scores'][1] else games[game_id]['player_usernames'][1]
                end_message = {
                    'type': 'final_result',
                    'winner': f'{winner} wins the game',
                    'scores': {
                        games[game_id]['player_usernames'][0]: games[game_id]['scores'][0],
                        games[game_id]['player_usernames'][1]: games[game_id]['scores'][1]
                    }
                }
                for player in games[game_id]['players']:
                    await player.send(json.dumps(end_message))
                print(f"Game {game_id} ended. Final result: {end_message}")
                del games[game_id]
            else:
                # Prepare for the next round
                games[game_id]['moves'] = {}
                games[game_id]['current_round'] += 1
                games[game_id]['rounds'] += 1

def determine_winner(move1, move2):
    if move1 == move2:
        return {'player1': 'Draw', 'player2': 'Draw', 'game': 'Draw'}
    elif (move1 == 'rock' and move2 == 'scissors') or \
         (move1 == 'scissors' and move2 == 'paper') or \
         (move1 == 'paper' and move2 == 'rock'):
        return {'player1': 'Win', 'player2': 'Lose', 'game': 'Player 1 wins'}
    else:
        return {'player1': 'Lose', 'player2': 'Win', 'game': 'Player 2 wins'}

start_server = websockets.serve(handle_client, 'localhost', 8080)

asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()
