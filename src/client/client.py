import socket
import time
import os

def start_client():
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    host = socket.gethostname()
    port = 1253
    download_dir = 'downloads'

    list_client_files()
    try:
        client_socket.connect((host, port))
        print(f"Connected to server at {host}:{port}")

        received_data = client_socket.recv(4096).decode('utf-8')
        print(f"\n--- Files on Server ---\n{received_data}\n-----------------------")

        action = input("Enter action (download/upload/quit): ").lower()
        if action == 'quit':
            return

        if action == 'download':
            file_name = input("Enter the name of the file to download: ")
            client_socket.send(f"DOWNLOAD:{file_name}".encode('utf-8'))

            response = client_socket.recv(1024).decode('utf-8')
            if response.startswith("Error:"):
                print(response)
                return

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
                print(f"File '{file_name}' downloaded successfully to '{download_dir}' directory.")

        elif action == 'upload':
            file_path = input("Enter the path of the file to upload: ")
            if not os.path.isfile(file_path):
                print(f"Error: File '{file_path}' not found.")
                return
            
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

        message = "Hello from the client!"
        print(f"\nSending: '{message}' to server")
        client_socket.send(message.encode('utf-8'))

        time.sleep(0.1)
        server_response = client_socket.recv(1024).decode('utf-8')
        print(f"Received response from server: '{server_response}'")

    except ConnectionRefusedError:
        print(f"Error: Connection refused. Make sure the server is running on {host}:{port}")
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
    start_client()