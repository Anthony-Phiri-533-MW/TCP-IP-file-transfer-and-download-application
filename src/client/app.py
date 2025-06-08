import socket
import os
import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QPushButton, QListWidget, QLineEdit, QLabel, QFileDialog, QMessageBox,
                            QDialog, QFormLayout)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

class FileTransferThread(QThread):
    status_signal = pyqtSignal(str)
    file_list_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    login_signal = pyqtSignal(bool)

    def __init__(self, action, file_names=None, file_paths=None, username=None, password=None):
        super().__init__()
        self.action = action
        self.file_names = file_names if file_names else []
        self.file_paths = file_paths if file_paths else []
        self.username = username
        self.password = password
        self.download_dir = 'downloads'
        self.host = socket.gethostname()
        self.port = 1253
        self.is_logged_in = False

    def run(self):
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            client_socket.connect((self.host, self.port))
            received_data = client_socket.recv(4096).decode('utf-8')
            if self.action != 'register' and self.action != 'login':
                self.file_list_signal.emit(received_data)

            if self.action == 'register':
                client_socket.send(f"REGISTER:{self.username}:{self.password}".encode('utf-8'))
                response = client_socket.recv(1024).decode('utf-8')
                if response.startswith("Error:"):
                    self.error_signal.emit(response)
                else:
                    self.status_signal.emit(response)
                return

            elif self.action == 'login':
                client_socket.send(f"LOGIN:{self.username}:{self.password}".encode('utf-8'))
                response = client_socket.recv(1024).decode('utf-8')
                if response == "Login successful.":
                    self.is_logged_in = True
                    self.login_signal.emit(True)
                    self.status_signal.emit(response)
                else:
                    self.error_signal.emit(response)
                    self.login_signal.emit(False)
                return

            if not self.is_logged_in and self.action in ['download', 'upload']:
                self.error_signal.emit("Please log in first.")
                return

            if self.action == 'download' and self.file_names:
                file_names_str = ','.join(self.file_names)
                client_socket.send(f"DOWNLOAD:{file_names_str}".encode('utf-8'))
                for file_name in self.file_names:
                    response = client_socket.recv(1024).decode('utf-8')
                    if response.startswith("Error:"):
                        self.error_signal.emit(response)
                        continue
                    if response.startswith("FILE_SIZE:"):
                        file_size = int(response[10:])
                        if not os.path.exists(self.download_dir):
                            os.makedirs(self.download_dir)
                        file_path = os.path.join(self.download_dir, file_name)
                        received_size = 0
                        with open(file_path, 'wb') as f:
                            while received_size < file_size:
                                data = client_socket.recv(1024)
                                if not data:
                                    break
                                f.write(data)
                                received_size += len(data)
                        self.status_signal.emit(f"File '{file_name}' downloaded to '{self.download_dir}'.")

            elif self.action == 'upload' and self.file_paths:
                for file_path in self.file_paths:
                    if not os.path.isfile(file_path):
                        self.error_signal.emit(f"File '{file_path}' not found.")
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
                    self.status_signal.emit(response)

        except ConnectionRefusedError:
            self.error_signal.emit(f"Connection refused. Ensure server is running on {self.host}:{self.port}")
        except Exception as e:
            self.error_signal.emit(f"An error occurred: {e}")
        finally:
            client_socket.close()
            if self.action not in ['register', 'login']:
                self.status_signal.emit("Connection closed.")

class LoginDialog(QDialog):
    def __init__(self, parent=None, is_register=False):
        super().__init__(parent)
        self.is_register = is_register
        self.setWindowTitle("Register" if is_register else "Login")
        self.init_ui()

    def init_ui(self):
        layout = QFormLayout()
        self.username_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        layout.addRow("Username:", self.username_input)
        layout.addRow("Password:", self.password_input)
        buttons = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(ok_btn)
        buttons.addWidget(cancel_btn)
        layout.addRow(buttons)
        self.setLayout(layout)

    def get_credentials(self):
        return self.username_input.text(), self.password_input.text()

class ClientGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("File Transfer Client")
        self.setGeometry(100, 100, 600, 400)
        self.is_logged_in = False
        self.username = None
        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout()

        # Account controls
        account_layout = QHBoxLayout()
        self.login_btn = QPushButton("Login")
        self.login_btn.clicked.connect(self.show_login_dialog)
        self.register_btn = QPushButton("Register")
        self.register_btn.clicked.connect(self.show_register_dialog)
        self.logout_btn = QPushButton("Logout")
        self.logout_btn.clicked.connect(self.logout)
        self.logout_btn.setEnabled(False)
        account_layout.addWidget(self.login_btn)
        account_layout.addWidget(self.register_btn)
        account_layout.addWidget(self.logout_btn)
        layout.addLayout(account_layout)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.MultiSelection)
        layout.addWidget(QLabel("Files on Server:"))
        layout.addWidget(self.file_list)

        button_layout = QHBoxLayout()
        self.download_btn = QPushButton("Download Selected Files")
        self.download_btn.clicked.connect(self.download_files)
        self.download_btn.setEnabled(False)
        self.upload_btn = QPushButton("Upload Files")
        self.upload_btn.clicked.connect(self.upload_files)
        self.upload_btn.setEnabled(False)
        button_layout.addWidget(self.download_btn)
        button_layout.addWidget(self.upload_btn)
        layout.addLayout(button_layout)

        self.status_label = QLabel("Status: Ready")
        layout.addWidget(self.status_label)

        central_widget.setLayout(layout)

    def show_login_dialog(self):
        dialog = LoginDialog(self)
        if dialog.exec_():
            username, password = dialog.get_credentials()
            if username and password:
                self.thread = FileTransferThread(action='login', username=username, password=password)
                self.thread.status_signal.connect(self.update_status)
                self.thread.error_signal.connect(self.show_error)
                self.thread.login_signal.connect(self.handle_login)
                self.thread.start()

    def show_register_dialog(self):
        dialog = LoginDialog(self, is_register=True)
        if dialog.exec_():
            username, password = dialog.get_credentials()
            if username and password:
                self.thread = FileTransferThread(action='register', username=username, password=password)
                self.thread.status_signal.connect(self.update_status)
                self.thread.error_signal.connect(self.show_error)
                self.thread.start()

    def handle_login(self, success):
        if success:
            self.is_logged_in = True
            self.username = self.thread.username
            self.login_btn.setEnabled(False)
            self.register_btn.setEnabled(False)
            self.logout_btn.setEnabled(True)
            self.download_btn.setEnabled(True)
            self.upload_btn.setEnabled(True)
            self.load_file_list()
        else:
            self.is_logged_in = False
            self.username = None

    def logout(self):
        self.is_logged_in = False
        self.username = None
        self.login_btn.setEnabled(True)
        self.register_btn.setEnabled(True)
        self.logout_btn.setEnabled(False)
        self.download_btn.setEnabled(False)
        self.upload_btn.setEnabled(False)
        self.file_list.clear()
        self.status_label.setText("Status: Logged out")

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
            files = file_list.split('\n')[1:]
            for file in files:
                self.file_list.addItem(file.strip('- '))

    def download_files(self):
        selected_items = self.file_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Warning", "Please select files to download.")
            return
        file_names = [item.text() for item in selected_items]
        self.thread = FileTransferThread(action='download', file_names=file_names)
        self.thread.status_signal.connect(self.update_status)
        self.thread.error_signal.connect(self.show_error)
        self.thread.start()

    def upload_files(self):
        file_paths, _ = QFileDialog.getOpenFileNames(self, "Select Files to Upload")
        if file_paths:
            self.thread = FileTransferThread(action='upload', file_paths=file_paths)
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