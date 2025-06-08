import socket
import time
import os

def start_client():
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    host = socket.gethostname()
    port = 1253
    download_dir = 'downloads'
    is_logged_in = False
    username = None

    try:
        client_socket.connect((host, port))
        print(f"Connected to server at {host}:{port}")

        while True:
            if not is_logged_in:
                action = input("Enter action (register/login/quit): ").lower()
                if action == 'quit':
                    break
                elif action in ['register', 'login']:
                    username = input("Enter username: ")
                    password = input("Enter password: ")
                    client_socket.send(f"{action.upper()}:{username}:{password}".encode('utf-8'))
                    response = client_socket.recv(1024).decode('utf-8')
                    print(response)
                    if response == "Login successful." and action == 'login':
                        is_logged_in = True
                        received_data = client_socket.recv(4096).decode('utf-8')
                        print(f"\n--- Files on Server ---\n{received_data}\n-----------------------")
                    elif response == "Registration successful." and action == 'register':
                        print("Please login to continue.")
                    continue
                else:
                    print("Invalid action. Please register or login.")
                    continue

            action = input("Enter action (download/upload/list/logout/quit): ").lower()
            if action == 'quit':
                break
            elif action == 'logout':
                client_socket.send("LOGOUT:".encode('utf-8'))
                response = client_socket.recv(1024).decode('utf-8')
                print(response)
                is_logged_in = False
                username = None
                continue
            elif action == 'list':
                received_data = client_socket.recv(4096).decode('utf-8')
                print(f"\n--- Files on Server ---\n{received_data}\n-----------------------")
                client_socket.send("LIST:".encode('utf-8'))
                continue

            if action == 'download':
                file_names = input("Enter file names to download (comma-separated): ").split(',')
                file_names = [name.strip() for name in file_names if name.strip()]
                if not file_names:
                    print("No files specified.")
                    continue
                client_socket.send(f"DOWNLOAD:{','.join(file_names)}".encode('utf-8'))
                for file_name in file_names:
                    response = client_socket.recv(1024).decode('utf-8')
                    if response.startswith("Error:"):
                        print(response)
                        continue
                    if response.startswith("FILE_SIZE:"):
                        file_size = int(response[10:])
                        if not os.path.exists(download_dir):
                            os.makedirs(download_dir)
                        file_path = os.path.join(download_dir, file_name)
                        received_size = 0

                        with open(file_path, 'wb') as f:
                            while received_size < file_size:
                                data = client_socket.recv(1024)
                                if not data:
                                    break
                                f.write(data)
                                received_size += len(data)
                        print(f"File '{file_name}' downloaded to '{download_dir}'.")

            elif action == 'upload':
                file_paths = input("Enter file paths to upload (comma-separated): ").split(',')
                file_paths = [path.strip() for path in file_paths if path.strip()]
                for file_path in file_paths:
                    if not os.path.isfile(file_path):
                        print(f"Error: File '{file_path}' not found.")
                        continue
                    file_name = os.path.basename(file_path)
                    file_size = os.path.getsize(file_path)
                    client_socket.send(f"UPLOAD:{file_name}:{file_size}".encode('utf-8'))
                    with open(file_path, 'rb') as f:
                        while True:
                            data = f.read(1024)
                            if not data:
                                break
                            client_socket.sendall(data)
                    response = client_socket.recv(1024).decode('utf-8')
                    print(response)
                    client_socket.send("LIST:".encode('utf-8'))

            else:
                print("Invalid action.")

    except ConnectionRefusedError:
        print(f"Error: Connection refused. Ensure server is running on {host}:{port}")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        client_socket.close()
        print("\nClient connection closed.")

def list_client_files():
    entries = os.listdir()
    print("\n--------Files on client-----------")
    for files in entries:
        print(files)
    print("------------------------------------------")

if __name__ == "__main__":
    list_client_files()
    start_client()