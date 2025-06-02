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

def send_file(client_socket, file_name):
    try:
        file_path = os.path.join(dir_path, file_name)
        if not os.path.isfile(file_path):
            client_socket.send(f"Error: File '{file_name}' not found on server.".encode('utf-8'))
            return
        
        file_size = os.path.getsize(file_path)
        client_socket.send(f"FILE_SIZE:{file_size}".encode('utf-8'))
        
        with open(file_path, 'rb') as f:
            while True:
                data = f.read(1024)
                if not data:
                    break
                client_socket.sendall(data)
        print(f"File '{file_name}' sent successfully.")
    except Exception as e:
        client_socket.send(f"Error sending file: {e}".encode('utf-8'))

def receive_file(client_socket, file_name, file_size):
    try:
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)
        
        file_path = os.path.join(dir_path, file_name)
        received_size = 0
        with open(file_path, 'wb') as f:
            while received_size < file_size:
                data = client_socket.recv(1024)
                if not data:
                    break
                f.write(data)
                received_size += len(data)
        client_socket.send(f"File '{file_name}' uploaded successfully.".encode('utf-8'))
        print(f"File '{file_name}' received successfully.")
    except Exception as e:
        client_socket.send(f"Error receiving file: {e}".encode('utf-8'))

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
            
            if data.startswith("DOWNLOAD:"):
                file_name = data[9:].strip()
                send_file(client_socket, file_name)
            elif data.startswith("UPLOAD:"):
                parts = data[7:].split(':')
                file_name = parts[0].strip()
                file_size = int(parts[1].strip())
                receive_file(client_socket, file_name, file_size)
            else:
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