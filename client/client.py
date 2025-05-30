import socket
import time

def start_client():
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    host = socket.gethostname()
    port = 1253

    try:
        client_socket.connect((host, port))
        print(f"Connected to server at {host}:{port}")

        received_data = client_socket.recv(4096).decode('utf-8')
        print(f"\n--- Files on Server ---\n{received_data}\n-----------------------")

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

if __name__ == "__main__":
    start_client()