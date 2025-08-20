import socket
import threading
import json
import customtkinter as ctk
from datetime import datetime
from tkinter import messagebox

class ChatClient:
    def __init__(self):
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.nickname = ""
        self.connected = False
        
        # Setup GUI
        self.setup_gui()
    
    def setup_gui(self):
        """Setup the graphical user interface"""
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        self.root = ctk.CTk()
        self.root.title("Local Chat App")
        self.root.geometry("600x500")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Login Frame
        self.login_frame = ctk.CTkFrame(self.root)
        self.login_frame.pack(pady=20, padx=20, fill="both", expand=True)
        
        ctk.CTkLabel(self.login_frame, text="Chat Login", font=("Arial", 20)).pack(pady=12)
        
        self.nickname_entry = ctk.CTkEntry(self.login_frame, placeholder_text="Enter your nickname")
        self.nickname_entry.pack(pady=12, padx=10)
        self.nickname_entry.bind("<Return>", lambda e: self.connect_to_server())
        
        self.server_entry = ctk.CTkEntry(self.login_frame, placeholder_text="Server (localhost)")
        self.server_entry.pack(pady=12, padx=10)
        self.server_entry.insert(0, "localhost")
        
        self.port_entry = ctk.CTkEntry(self.login_frame, placeholder_text="Port (12345)")
        self.port_entry.pack(pady=12, padx=10)
        self.port_entry.insert(0, "12345")
        
        self.connect_btn = ctk.CTkButton(self.login_frame, text="Connect", command=self.connect_to_server)
        self.connect_btn.pack(pady=12)
        
        # Chat Frame (initially hidden)
        self.chat_frame = ctk.CTkFrame(self.root)
        
        # Chat display area
        self.chat_display = ctk.CTkTextbox(self.chat_frame, state="disabled", height=300)
        self.chat_display.pack(pady=10, padx=10, fill="both", expand=True)
        
        # Message input area
        input_frame = ctk.CTkFrame(self.chat_frame)
        input_frame.pack(pady=10, padx=10, fill="x")
        
        self.message_entry = ctk.CTkEntry(input_frame, placeholder_text="Type your message...")
        self.message_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.message_entry.bind("<Return>", lambda e: self.send_message())
        
        self.send_btn = ctk.CTkButton(input_frame, text="Send", command=self.send_message)
        self.send_btn.pack(side="right")
        
        # Users online label
        self.users_label = ctk.CTkLabel(self.chat_frame, text="Users online: 0")
        self.users_label.pack(pady=5)
    
    def connect_to_server(self):
        """Connect to the chat server"""
        try:
            self.nickname = self.nickname_entry.get().strip()
            server = self.server_entry.get().strip() or "localhost"
            port = int(self.port_entry.get().strip() or "12345")
            
            if not self.nickname:
                messagebox.showerror("Error", "Please enter a nickname")
                return
            
            self.client_socket.connect((server, port))
            self.connected = True
            
            # Handle nickname request from server
            response = self.client_socket.recv(1024).decode('utf-8')
            if response == "NICK":
                self.client_socket.send(self.nickname.encode('utf-8'))
            
            # Switch to chat frame
            self.login_frame.pack_forget()
            self.chat_frame.pack(pady=20, padx=20, fill="both", expand=True)
            
            # Start receiving messages in a separate thread
            receive_thread = threading.Thread(target=self.receive_messages)
            receive_thread.daemon = True
            receive_thread.start()
            
            self.add_message("system", "Connected to server!", datetime.now().strftime('%H:%M:%S'))
            
        except Exception as e:
            messagebox.showerror("Connection Error", f"Failed to connect: {e}")
    
    def receive_messages(self):
        """Receive messages from server"""
        while self.connected:
            try:
                message = self.client_socket.recv(1024).decode('utf-8')
                if message:
                    message_data = json.loads(message)
                    self.handle_received_message(message_data)
            except:
                if self.connected:
                    self.add_message("system", "Disconnected from server", datetime.now().strftime('%H:%M:%S'))
                    self.connected = False
                break
    
    def handle_received_message(self, message_data):
        """Handle received message based on type"""
        if message_data['type'] == 'system':
            self.add_message("system", message_data['content'], message_data['timestamp'])
            if 'users_online' in message_data:
                self.users_label.configure(text=f"Users online: {message_data['users_online']}")
        elif message_data['type'] == 'message':
            self.add_message(message_data['sender'], message_data['content'], message_data['timestamp'])
    
    def send_message(self):
        """Send message to server"""
        message = self.message_entry.get().strip()
        if message and self.connected:
            message_data = {
                'type': 'message',
                'sender': self.nickname,
                'content': message,
                'timestamp': datetime.now().strftime('%H:%M:%S')
            }
            try:
                self.client_socket.send(json.dumps(message_data).encode('utf-8'))
                self.message_entry.delete(0, 'end')
            except:
                self.add_message("system", "Failed to send message", datetime.now().strftime('%H:%M:%S'))
    
    def add_message(self, sender, content, timestamp):
        """Add message to chat display"""
        self.chat_display.configure(state="normal")
        
        if sender == "system":
            self.chat_display.insert("end", f"[{timestamp}] {content}\n", "system")
        else:
            if sender == self.nickname:
                self.chat_display.insert("end", f"[{timestamp}] You: {content}\n", "self")
            else:
                self.chat_display.insert("end", f"[{timestamp}] {sender}: {content}\n", "other")
        
        self.chat_display.configure(state="disabled")
        self.chat_display.see("end")
    
    def on_closing(self):
        """Handle window closing"""
        if self.connected:
            self.client_socket.close()
        self.root.destroy()
    
    def run(self):
        """Start the client application"""
        # Configure text tags for different message types
        self.chat_display.tag_config("system", foreground="gray")
        self.chat_display.tag_config("self", foreground="light blue")
        self.chat_display.tag_config("other", foreground="white")
        
        self.root.mainloop()

if __name__ == "__main__":
    client = ChatClient()
    client.run()
