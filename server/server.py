import os
import threading
import socket

dir_path = 'files'

def list_server_files_for_client():
    try:
        entries = os.listdir(dir_path)
        if not entries:
            return "No files found in the server's 'files' directory."
        
        file_list = "Files on server:\n"
        for entry in entries:
            file_list += f"- {entry}\n"
        return file_list.strip()
    except FileNotFoundError:
        return f"Error: Server directory not found: {dir_path}. Please create a 'files' directory."
    except Exception as e:
        return f"Error listing files: {e}"

def handle_client(client_socket, client_address):
    print(f"[ACTIVE CONNECTIONS] {threading.active_count() - 1}")

    try:
        print(f"Connection established with {client_address}")

        files_to_send = list_server_files_for_client()
        client_socket.sendall(files_to_send.encode('utf-8'))
        print(f"Sent file list to {client_address}")

        while True:
            data = client_socket.recv(1024).decode('utf-8')
            if not data:
                break
            print(f"Received from {client_address}: {data}")
            
            response = f"Server received: '{data}'"
            client_socket.send(response.encode('utf-8'))

    except ConnectionResetError:
        print(f"Client {client_address} forcefully closed the connection.")
    except BrokenPipeError:
        print(f"Client {client_address} disconnected abruptly.")
    except Exception as e:
        print(f"Error handling client {client_address}: {e}")
    finally:
        client_socket.close()
        print(f"Connection with {client_address} closed.")

def start_server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    host = socket.gethostname()
    port = 1253
    
    server_socket.bind((host, port))
    server_socket.listen(5)

    print(f"Server started....\nListening on {host}:{port}")
    print(f"Files currently in server's '{dir_path}' directory:")
    print(list_server_files_for_client())

    while True:
        client_socket, client_address = server_socket.accept()
        client_handler = threading.Thread(target=handle_client, args=(client_socket, client_address))
        client_handler.start()

if __name__ == "__main__":
    start_server()
