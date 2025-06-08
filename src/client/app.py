import socket
import os
import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QPushButton, QListWidget, QLineEdit, QLabel, QFileDialog, QMessageBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

class FileTransferThread(QThread):
    status_signal = pyqtSignal(str)
    file_list_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    def __init__(self, action, file_name=None, file_path=None):
        super().__init__()
        self.action = action
        self.file_name = file_name
        self.file_path = file_path
        self.download_dir = 'downloads'
        self.host = socket.gethostname()
        self.port = 1253

    def run(self):
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            client_socket.connect((self.host, self.port))
            received_data = client_socket.recv(4096).decode('utf-8')
            self.file_list_signal.emit(received_data)

            if self.action == 'download' and self.file_name:
                client_socket.send(f"DOWNLOAD:{self.file_name}".encode('utf-8'))
                response = client_socket.recv(1024).decode('utf-8')
                if response.startswith("Error:"):
                    self.error_signal.emit(response)
                    return
                if response.startswith("FILE_SIZE:"):
                    file_size = int(response[10:])
                    if not os.path.exists(self.download_dir):
                        os.makedirs(self.download_dir)
                    file_path = os.path.join(self.download_dir, self.file_name)
                    received_size = 0
                    with open(file_path, 'wb') as f:
                        while received_size < file_size:
                            data = client_socket.recv(1024)
                            if not data:
                                break
                            f.write(data)
                            received_size += len(data)
                    self.status_signal.emit(f"File '{self.file_name}' downloaded successfully to '{self.download_dir}' directory.")

            elif self.action == 'upload' and self.file_path:
                file_name = os.path.basename(self.file_path)
                file_size = os.path.getsize(self.file_path)
                client_socket.send(f"UPLOAD:{file_name}:{file_size}".encode('utf-8'))
                with open(self.file_path, 'rb') as f:
                    while True:
                        data = f.read(1024)
                        if not data:
                            break
                        client_socket.sendall(data)
                response = client_socket.recv(1024).decode('utf-8')
                self.status_signal.emit(response)

        except ConnectionRefusedError:
            self.error_signal.emit(f"Connection refused. Make sure the server is running on {self.host}:{self.port}")
        except Exception as e:
            self.error_signal.emit(f"An error occurred: {e}")
        finally:
            client_socket.close()
            self.status_signal.emit("Connection closed.")

class ClientGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("File Transfer Client")
        self.setGeometry(100, 100, 600, 400)
        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout()

        self.file_list = QListWidget()
        layout.addWidget(QLabel("Files on Server:"))
        layout.addWidget(self.file_list)

        button_layout = QHBoxLayout()
        self.download_btn = QPushButton("Download Selected File")
        self.download_btn.clicked.connect(self.download_file)
        self.upload_btn = QPushButton("Upload File")
        self.upload_btn.clicked.connect(self.upload_file)
        button_layout.addWidget(self.download_btn)
        button_layout.addWidget(self.upload_btn)
        layout.addLayout(button_layout)

        self.status_label = QLabel("Status: Ready")
        layout.addWidget(self.status_label)

        central_widget.setLayout(layout)
        self.load_file_list()

    def load_file_list(self):
        self.thread = FileTransferThread(action='list')
        self.thread.file_list_signal.connect(self.update_file_list)
        self.thread.error_signal.connect(self.show_error)
        self.thread.status_signal.connect(self.update_status)
        self.thread.start()

    def update_file_list(self, file_list):
        self.file_list.clear()
        if file_list.startswith("Error:") or file_list.startswith("No files"):
            self.file_list.addItem(file_list)
        else:
            files = file_list.split('\n')[1:]  # Skip "Files on server:" line
            for file in files:
                self.file_list.addItem(file.strip('- '))

    def download_file(self):
        selected_items = self.file_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Warning", "Please select a file to download.")
            return
        file_name = selected_items[0].text()
        self.thread = FileTransferThread(action='download', file_name=file_name)
        self.thread.status_signal.connect(self.update_status)
        self.thread.error_signal.connect(self.show_error)
        self.thread.start()

    def upload_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select File to Upload")
        if file_path:
            self.thread = FileTransferThread(action='upload', file_path=file_path)
            self.thread.status_signal.connect(self.update_status)
            self.thread.error_signal.connect(self.show_error)
            self.thread.start()

    def update_status(self, message):
        self.status_label.setText(f"Status: {message}")

    def show_error(self, message):
        QMessageBox.critical(self, "Error", message)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ClientGUI()
    window.show()
    sys.exit(app.exec_())