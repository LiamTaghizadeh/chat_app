import socket
import threading
import json
from datetime import datetime

class ChatServer:
    def __init__(self, host='localhost', port=12345):
        self.host = host
        self.port = port
        self.clients = []
        self.nicknames = []
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
    def start_server(self):
        """Start the chat server"""
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen()
            print(f"🚀 Server started on {self.host}:{self.port}")
            print("📡 Waiting for connections...")
            
            while True:
                client_socket, address = self.server_socket.accept()
                print(f"🔗 New connection from {address}")
                
                # Start a new thread for each client
                thread = threading.Thread(target=self.handle_client, args=(client_socket,))
                thread.daemon = True
                thread.start()
                
        except Exception as e:
            print(f"❌ Server error: {e}")
        finally:
            self.server_socket.close()
    
    def broadcast(self, message, sender_socket=None):
        """Send message to all connected clients except sender"""
        message_data = json.dumps(message)
        for client in self.clients:
            if client != sender_socket:
                try:
                    client.send(message_data.encode('utf-8'))
                except:
                    self.remove_client(client)
    
    def handle_client(self, client_socket):
        """Handle individual client connections"""
        try:
            # Request nickname
            client_socket.send("NICK".encode('utf-8'))
            nickname = client_socket.recv(1024).decode('utf-8')
            
            self.nicknames.append(nickname)
            self.clients.append(client_socket)
            
            # Notify all clients about new user
            join_message = {
                'type': 'system',
                'content': f'{nickname} joined the chat!',
                'timestamp': datetime.now().strftime('%H:%M:%S'),
                'users_online': len(self.clients)
            }
            self.broadcast(join_message)
            
            print(f"✅ {nickname} connected. Users online: {len(self.clients)}")
            
            while True:
                try:
                    message = client_socket.recv(1024).decode('utf-8')
                    if message:
                        message_data = json.loads(message)
                        self.broadcast(message_data, client_socket)
                    else:
                        raise ConnectionError("Client disconnected")
                except:
                    break
                    
        except Exception as e:
            print(f"⚠️ Client error: {e}")
        finally:
            self.remove_client(client_socket, nickname)
    
    def remove_client(self, client_socket, nickname=None):
        """Remove client from the server"""
        if client_socket in self.clients:
            index = self.clients.index(client_socket)
            self.clients.remove(client_socket)
            if nickname and nickname in self.nicknames:
                self.nicknames.remove(nickname)
            
            if nickname:
                leave_message = {
                    'type': 'system',
                    'content': f'{nickname} left the chat.',
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                    'users_online': len(self.clients)
                }
                self.broadcast(leave_message)
                print(f"👋 {nickname} disconnected. Users online: {len(self.clients)}")

if __name__ == "__main__":
    server = ChatServer()
    server.start_server()
