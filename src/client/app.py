import socket
import os
import sys
import time
import shutil
import threading
import queue
import hashlib
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QPushButton, QListWidget, QLineEdit, QLabel, QFileDialog, QMessageBox,
                            QDialog, QFormLayout, QProgressBar, QFrame, QAction, QMenuBar, QCheckBox,
                            QTabWidget, QInputDialog, QLineEdit as QLineEditBase, QGraphicsDropShadowEffect,
                            QStatusBar, QSizeGrip)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QPoint, QPropertyAnimation
from PyQt5.QtGui import QPalette, QColor, QFont, QIcon, QCursor
from tqdm import tqdm

class FileTransferThread(QThread):
    update_status = pyqtSignal(str)
    update_file_list = pyqtSignal(list, list)  # public_files, private_files
    error_occurred = pyqtSignal(str)
    login_status = pyqtSignal(bool)
    transfer_progress = pyqtSignal(str, int, int, float)  # filename, current, total, speed
    notify = pyqtSignal(str)  # For notifications
    display_name_received = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.client_socket = None
        self.running = False
        self.action = None
        self.file_names = []
        self.file_paths = []
        self.is_private = False
        self.username = None
        self.password = None
        self.new_password = None
        self.display_name = None
        self.download_dir = 'downloads'
        self.host = None
        self.port = 1253  # Default port
        self.is_logged_in = False
        self.current_file_size = 0
        self.enable_notifications = True
        self.download_tasks = {}  # {filename: (file, offset, total)}
        self.paused_downloads = set()
        self.last_transfer_update = 0
        self.last_bytes_transferred = 0
        self.transfer_speed = 0.0

    def set_action(self, action, file_names=None, file_paths=None, username=None, password=None, 
                  is_private=False, new_password=None, display_name=None):
        self.action = action
        self.file_names = file_names if file_names else []
        self.file_paths = file_paths if file_paths else []
        self.username = username
        self.password = password
        self.is_private = is_private
        self.new_password = new_password
        self.display_name = display_name

    def set_notifications(self, enabled):
        self.enable_notifications = enabled

    def connect_to_server(self):
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.connect((self.host, self.port))
            self.running = True
            self.update_status.emit("Connected to server.")
            
            # Test connection
            self.client_socket.settimeout(2.0)
            try:
                self.client_socket.recv(1024)
            except socket.timeout:
                pass
            self.client_socket.settimeout(None)
            return True
        except Exception as e:
            self.error_occurred.emit(f"Connection error: {str(e)}")
            return False

    def calculate_speed(self, bytes_transferred):
        now = time.time()
        if self.last_transfer_update > 0:
            time_diff = now - self.last_transfer_update
            if time_diff > 0:
                bytes_diff = bytes_transferred - self.last_bytes_transferred
                self.transfer_speed = (bytes_diff / (1024 * 1024)) / time_diff  # MB/s
        self.last_transfer_update = now
        self.last_bytes_transferred = bytes_transferred
        return self.transfer_speed

    def run(self):
        if not self.connect_to_server():
            return
            
        while self.running:
            try:
                if self.action == 'list' and self.is_logged_in:
                    self.handle_list_request()
                elif self.action == 'login':
                    self.handle_login()
                elif self.action == 'logout':
                    self.handle_logout()
                elif self.action == 'download' and self.is_logged_in and self.file_names:
                    self.handle_download()
                elif self.action == 'upload' and self.is_logged_in and self.file_paths:
                    self.handle_upload()
                elif self.action == 'share' and self.is_logged_in:
                    self.handle_share()
                elif self.action == 'change_password' and self.is_logged_in:
                    self.handle_password_change()
                elif self.action == 'delete_account' and self.is_logged_in:
                    self.handle_delete_account()
                elif self.action == 'search' and self.is_logged_in:
                    self.handle_search()
                elif self.action == 'delete_file' and self.is_logged_in:
                    self.handle_delete_file()
                elif self.action == 'get_display_name' and self.is_logged_in:
                    self.handle_get_display_name()
                elif self.action == 'update_display_name' and self.is_logged_in:
                    self.handle_update_display_name()
                
                self.action = None
                while self.running and not self.action:
                    QThread.msleep(50)
                    
            except ConnectionResetError as e:
                self.error_occurred.emit(f"Connection lost: {str(e)}")
                self.running = False
            except Exception as e:
                self.error_occurred.emit(f"Unexpected error: {str(e)}")
                self.running = False

        self.cleanup_connection()

    def handle_list_request(self):
        self.client_socket.send("LIST:".encode('utf-8'))
        received_data = self.client_socket.recv(4096).decode('utf-8')
        
        public_files = []
        private_files = []
        
        if not received_data.startswith("Error:"):
            parts = received_data.split('|')
            for part in parts:
                if part.startswith("PUBLIC:"):
                    public_files = part.replace("PUBLIC:", "").split(',')
                elif part.startswith("PRIVATE:"):
                    private_files = part.replace("PRIVATE:", "").split(',')
            public_files = [f for f in public_files if f]
            private_files = [f for f in private_files if f]
        
        self.update_file_list.emit(public_files, private_files)

    def handle_login(self):
        self.client_socket.send(f"LOGIN:{self.username}:{self.password}".encode('utf-8'))
        response = self.client_socket.recv(1024).decode('utf-8')
        
        if response == "Login successful.":
            self.is_logged_in = True
            self.login_status.emit(True)
            self.update_status.emit(response)
            self.handle_list_request()
            self.handle_get_display_name()  # Get display name after login
        else:
            self.error_occurred.emit(response)
            self.login_status.emit(False)

    def handle_logout(self):
        self.client_socket.send("LOGOUT:".encode('utf-8'))
        response = self.client_socket.recv(1024).decode('utf-8')
        self.is_logged_in = False
        self.update_status.emit(response)
        self.login_status.emit(False)
        self.running = False

    def handle_download(self):
        for file_name in self.file_names:
            if file_name in self.paused_downloads:
                self.resume_download(file_name)
            else:
                self.start_download(file_name)

    def start_download(self, file_name):
        if file_name in self.download_tasks:
            return  # Already downloading or paused
        
        self.client_socket.send(f"DOWNLOAD:{file_name}".encode('utf-8'))
        response = self.client_socket.recv(1024).decode('utf-8')
        
        if response.startswith("Error:"):
            self.error_occurred.emit(response)
            return
            
        is_zip = False
        if response.startswith("FILE_SIZE:"):
            parts = response.split(':')
            file_size = int(parts[1])
            offset = 0
            if len(parts) > 2 and parts[2] == 'ZIP':
                is_zip = True
                
            if not os.path.exists(self.download_dir):
                os.makedirs(self.download_dir)
                
            file_path = os.path.join(self.download_dir, file_name + ('.zip' if is_zip else ''))
            received_size = 0
            start_time = time.time()
            self.last_transfer_update = start_time
            self.last_bytes_transferred = 0
            
            try:
                mode = 'wb' if offset == 0 else 'ab'
                with open(file_path, mode) as f:
                    while received_size < file_size:
                        if file_name in self.paused_downloads:
                            self.download_tasks[file_name] = (f, received_size, file_size)
                            return
                        data = self.client_socket.recv(min(4096, file_size - received_size))
                        if not data:  # Check for connection closure
                            raise ConnectionError("Connection closed by server")
                        f.write(data)
                        received_size += len(data)
                        speed = self.calculate_speed(received_size)
                        self.transfer_progress.emit(file_name, received_size, file_size, speed)
                    
                transfer_time = time.time() - start_time
                speed = (file_size / (1024 * 1024)) / transfer_time if transfer_time > 0 else 0  # MB/s
                
                del self.download_tasks[file_name]
                if is_zip:
                    shutil.unpack_archive(file_path, os.path.join(self.download_dir, file_name), 'zip')
                    os.remove(file_path)
                
                self.update_status.emit(f"Downloaded '{file_name}' to '{self.download_dir}' (Speed: {speed:.2f} MB/s)")
                if self.enable_notifications:
                    self.notify.emit(f"Download complete: {file_name}")
            except ConnectionError as e:
                self.error_occurred.emit(f"Download failed: {str(e)}. Connection lost.")
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                self.error_occurred.emit(f"Error saving file: {str(e)}")
                if os.path.exists(file_path):
                    os.remove(file_path)

    def resume_download(self, file_name):
        if file_name not in self.download_tasks:
            return
        
        f, offset, total = self.download_tasks[file_name]
        self.client_socket.send(f"DOWNLOAD_RESUME:{file_name}:{offset}".encode('utf-8'))
        response = self.client_socket.recv(1024).decode('utf-8')
        
        if response.startswith("Error:"):
            self.error_occurred.emit(response)
            return
            
        try:
            start_time = time.time()
            self.last_transfer_update = start_time
            self.last_bytes_transferred = offset
            
            with tqdm(total=total, unit='B', unit_scale=True, desc=file_name, initial=offset) as pbar:
                while offset < total:
                    if file_name in self.paused_downloads:
                        self.download_tasks[file_name] = (f, offset, total)
                        return
                    data = self.client_socket.recv(min(4096, total - offset))
                    if not data:
                        break
                    f.write(data)
                    offset += len(data)
                    speed = self.calculate_speed(offset)
                    pbar.update(len(data))
                    self.transfer_progress.emit(file_name, offset, total, speed)
                
            transfer_time = time.time() - start_time
            speed = ((total - self.download_tasks[file_name][1]) / (1024 * 1024)) / transfer_time if transfer_time > 0 else 0  # MB/s
            
            del self.download_tasks[file_name]
            self.update_status.emit(f"Resumed and completed '{file_name}' (Speed: {speed:.2f} MB/s)")
            if self.enable_notifications:
                self.notify.emit(f"Download resumed and complete: {file_name}")
        except Exception as e:
            self.error_occurred.emit(f"Error resuming file: {str(e)}")

    def pause_download(self, file_name):
        self.paused_downloads.add(file_name)
        if file_name in self.download_tasks:
            del self.download_tasks[file_name]

    def handle_upload(self):
        for file_path in self.file_paths:
            is_folder = os.path.isdir(file_path)
            file_name = os.path.basename(file_path)
            
            try:
                if is_folder:
                    # Create temp zip file
                    temp_zip = file_path + '.temp.zip'
                    shutil.make_archive(file_path, 'zip', file_path)
                    os.rename(file_path + '.zip', temp_zip)
                    file_size = os.path.getsize(temp_zip)
                else:
                    if not os.path.isfile(file_path):
                        self.error_occurred.emit(f"File '{file_path}' not found.")
                        continue
                    file_size = os.path.getsize(file_path)
                
                self.current_file_size = file_size
                is_private = 1 if self.is_private else 0
                is_folder_flag = 1 if is_folder else 0
                
                # Send metadata first
                self.client_socket.send(f"UPLOAD:{file_name}:{file_size}:{is_private}:{is_folder_flag}".encode('utf-8'))
                
                try:
                    source_path = temp_zip if is_folder else file_path
                    start_time = time.time()
                    self.last_transfer_update = start_time
                    self.last_bytes_transferred = 0
                    
                    with open(source_path, 'rb') as f:
                        bytes_sent = 0
                        while bytes_sent < file_size:
                            chunk = f.read(min(4096, file_size - bytes_sent))
                            if not chunk:
                                break
                            self.client_socket.sendall(chunk)
                            bytes_sent += len(chunk)
                            speed = self.calculate_speed(bytes_sent)
                            self.transfer_progress.emit(file_name, bytes_sent, file_size, speed)
                    
                    # Verify complete transfer
                    if bytes_sent != file_size:
                        raise Exception(f"Upload incomplete. Sent {bytes_sent} of {file_size} bytes")
                    
                    transfer_time = time.time() - start_time
                    speed = (file_size / (1024 * 1024)) / transfer_time if transfer_time > 0 else 0  # MB/s
                    
                    # Clean up temp files
                    if is_folder and os.path.exists(temp_zip):
                        os.remove(temp_zip)
                    
                    # Get server response
                    response = self.client_socket.recv(1024).decode('utf-8')
                    self.update_status.emit(f"{response} (Speed: {speed:.2f} MB/s)")
                    if self.enable_notifications:
                        self.notify.emit(f"Upload complete: {file_name}")
                    
                    self.handle_list_request()
                except Exception as e:
                    self.error_occurred.emit(f"Error uploading file: {str(e)}")
                    # Clean up temp files on error
                    if is_folder and os.path.exists(temp_zip):
                        os.remove(temp_zip)
            except Exception as e:
                self.error_occurred.emit(f"Error preparing upload: {str(e)}")

    def handle_share(self):
        file_name, target_user = self.file_names
        self.client_socket.send(f"SHARE:{file_name}:{target_user}".encode('utf-8'))
        response = self.client_socket.recv(1024).decode('utf-8')
        self.update_status.emit(response)
        if self.enable_notifications:
            self.notify.emit(response)

    def handle_password_change(self):
        self.client_socket.send(f"CHANGE_PASSWORD:{self.new_password}".encode('utf-8'))
        response = self.client_socket.recv(1024).decode('utf-8')
        if response == "Password updated successfully.":
            self.password = self.new_password
        self.update_status.emit(response)

    def handle_delete_account(self):
        self.client_socket.send(f"DELETE_ACCOUNT:{self.username}".encode('utf-8'))
        response = self.client_socket.recv(1024).decode('utf-8')
        if response == "Account deleted successfully.":
            self.is_logged_in = False
            self.login_status.emit(False)
            self.running = False
        self.update_status.emit(response)

    def handle_search(self):
        search_query = ':'.join(self.file_names)  # Assuming file_names contains the search term
        self.client_socket.send(f"SEARCH:{search_query}".encode('utf-8'))
        received_data = self.client_socket.recv(4096).decode('utf-8')
        
        public_files = []
        private_files = []
        
        if not received_data.startswith("Error:"):
            parts = received_data.split('|')
            for part in parts:
                if part.startswith("PUBLIC:"):
                    public_files = part.replace("PUBLIC:", "").split(',')
                elif part.startswith("PRIVATE:"):
                    private_files = part.replace("PRIVATE:", "").split(',')
            public_files = [f for f in public_files if f]
            private_files = [f for f in private_files if f]
        
        self.update_file_list.emit(public_files, private_files)

    def handle_delete_file(self):
        for file_name in self.file_names:
            self.client_socket.send(f"DELETE_FILE:{file_name}".encode('utf-8'))
            response = self.client_socket.recv(1024).decode('utf-8')
            self.update_status.emit(response)
            if response == f"File '{file_name}' deleted successfully.":
                self.handle_list_request()

    def handle_get_display_name(self):
        self.client_socket.send(f"GET_DISPLAY_NAME:{self.username}".encode('utf-8'))
        response = self.client_socket.recv(1024).decode('utf-8')
        self.display_name = response
        self.display_name_received.emit(response)

    def handle_update_display_name(self):
        self.client_socket.send(f"UPDATE_DISPLAY_NAME:{self.display_name}".encode('utf-8'))
        response = self.client_socket.recv(1024).decode('utf-8')
        self.update_status.emit(response)
        if response == "Display name updated successfully.":
            self.handle_get_display_name()

    def cleanup_connection(self):
        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass
        self.update_status.emit("Disconnected from server.")

    def stop(self):
        self.running = False
        self.action = None

class SyncHandler(FileSystemEventHandler):
    def __init__(self, queue):
        self.queue = queue

    def on_created(self, event):
        if not event.is_directory:
            self.queue.put(('upload', event.src_path))

    def on_modified(self, event):
        if not event.is_directory:
            self.queue.put(('upload', event.src_path))

class LoginScreen(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("File Transfer Client - Login")
        self.setFixedSize(400, 350)
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #f5f7fa;
            }
            QLabel {
                color: #333333;
            }
            QLineEdit {
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 8px;
                background-color: white;
                color: #333333;
            }
            QPushButton {
                background-color: #4a6fa5;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #3a5a8f;
            }
        """)

        layout = QVBoxLayout()
        
        header = QLabel("File Transfer Client")
        header.setStyleSheet("font-size: 20px; font-weight: bold; margin-bottom: 20px;")
        layout.addWidget(header)
        
        form_layout = QFormLayout()
        
        self.server_ip_input = QLineEdit()
        self.server_ip_input.setPlaceholderText("Server IP (e.g., 127.0.0.1)")
        
        self.server_port_input = QLineEdit()
        self.server_port_input.setPlaceholderText("Port (e.g., 1253)")
        self.server_port_input.setText("1253")
        
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username")
        
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.Password)
        
        form_layout.addRow("Server IP:", self.server_ip_input)
        form_layout.addRow("Port:", self.server_port_input)
        form_layout.addRow("Username:", self.username_input)
        form_layout.addRow("Password:", self.password_input)
        
        buttons = QHBoxLayout()
        login_btn = QPushButton("Login")
        login_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Exit")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(login_btn)
        buttons.addWidget(cancel_btn)
        
        layout.addLayout(form_layout)
        layout.addLayout(buttons)
        self.setLayout(layout)

    def get_credentials(self):
        server_ip = self.server_ip_input.text().strip()
        server_port = self.server_port_input.text().strip()
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()
        return (server_ip, server_port, username, password)

class SettingsDialog(QDialog):
    def __init__(self, parent, dark_mode=False):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setFixedSize(400, 300)
        self.dark_mode = dark_mode
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #f5f7fa;
            }
            QLabel {
                color: #333333;
            }
            QLineEdit {
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 8px;
                background-color: white;
                color: #333333;
            }
            QPushButton {
                background-color: #4a6fa5;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #3a5a8f;
            }
            QCheckBox {
                color: #333333;
                padding: 5px;
            }
        """)

        layout = QVBoxLayout()

        # Theme toggle
        self.theme_cb = QCheckBox("Enable Dark Mode")
        self.theme_cb.setChecked(self.dark_mode)
        layout.addWidget(self.theme_cb)

        # Password change
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("New Password")
        self.password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(QLabel("Change Password:"))
        layout.addWidget(self.password_input)

        # Sync folder
        self.sync_input = QLineEdit()
        self.sync_input.setPlaceholderText("Sync Folder Path")
        self.sync_btn = QPushButton("Browse")
        self.sync_btn.clicked.connect(self.browse_folder)
        sync_layout = QHBoxLayout()
        sync_layout.addWidget(self.sync_input)
        sync_layout.addWidget(self.sync_btn)
        layout.addWidget(QLabel("Sync Folder:"))
        layout.addLayout(sync_layout)

        # Notifications
        self.notify_cb = QCheckBox("Enable Notifications")
        self.notify_cb.setChecked(True)
        layout.addWidget(self.notify_cb)

        # Delete account
        self.delete_cb = QCheckBox("Delete Account")
        layout.addWidget(self.delete_cb)

        # Display name
        self.display_name_input = QLineEdit()
        self.display_name_input.setPlaceholderText("New Display Name")
        layout.addWidget(QLabel("Change Display Name:"))
        layout.addWidget(self.display_name_input)

        # Buttons
        buttons = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

        self.setLayout(layout)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Sync Folder")
        if folder:
            self.sync_input.setText(folder)

    def get_settings(self):
        return {
            'dark_mode': self.theme_cb.isChecked(),
            'password': self.password_input.text().strip() if self.password_input.text().strip() else None,
            'sync_folder': self.sync_input.text().strip() if self.sync_input.text().strip() else None,
            'notifications': self.notify_cb.isChecked(),
            'delete_account': self.delete_cb.isChecked(),
            'display_name': self.display_name_input.text().strip() if self.display_name_input.text().strip() else None
        }

class ClientGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("File Transfer Client")
        self.setGeometry(100, 100, 900, 700)
        self.is_logged_in = False
        self.username = None
        self.display_name = None
        self.thread = None
        self.sync_observer = None
        self.sync_queue = queue.Queue()
        self.sync_folder = None
        self.dark_mode = False
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f7fa;
            }
            QFrame {
                background-color: white;
                border-radius: 8px;
                border: 1px solid #e0e0e0;
            }
            QPushButton {
                background-color: #4a6fa5;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #3a5a8f;
            }
            QPushButton:pressed {
                background-color: #2a4a7f;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
            QListWidget, QTextEdit, QLineEdit {
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 8px;
                background-color: white;
                color: #333333;
            }
            QTabWidget::pane {
                border: 1px solid #e0e0e0;
                border-radius: 8px;
            }
            QTabBar::tab {
                padding: 8px 16px;
                background-color: #e0e0e0;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background-color: white;
                border-bottom: 2px solid #4a6fa5;
            }
            QLabel {
                color: #333333;
            }
            QProgressBar {
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                text-align: center;
                background-color: white;
            }
            QProgressBar::chunk {
                background-color: #4a6fa5;
                border-radius: 4px;
            }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(15)

        # Header
        self.header_label = QLabel("File Transfer Client")
        self.header_label.setStyleSheet("font-size: 20px; font-weight: bold;")
        self.main_layout.addWidget(self.header_label)

        # Status label
        self.status_label = QLabel("Status: Ready")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.main_layout.addWidget(self.status_label)

        # Status bar
        self.statusBar().showMessage("Ready")
        self.statusBar().setStyleSheet("""
            QStatusBar {
                border-top: 1px solid palette(mid);
            }
        """)

        # Show login screen first
        self.show_login_screen()

    def show_login_screen(self):
        login = LoginScreen()
        if login.exec_() == QDialog.Accepted:
            server_ip, server_port, username, password = login.get_credentials()
            if username and password and server_ip and server_port:
                try:
                    port = int(server_port)  # Convert port to integer
                    self.start_transfer_thread(server_ip, port)
                    self.thread.set_action('login', username=username, password=password)
                except ValueError:
                    QMessageBox.warning(self, "Error", "Invalid port number")
                    self.show_login_screen()
            else:
                QMessageBox.warning(self, "Error", "Server IP, port, username, and password are required")
                self.show_login_screen()
        else:
            self.close()

    def show_main_ui(self):
        # Clear existing widgets from main_layout, preserving header and status label
        while self.main_layout.count() > 2:  # Keep header and status label
            item = self.main_layout.takeAt(2)
            if item.widget():
                item.widget().setParent(None)

        # Account controls
        account_frame = QFrame()
        account_layout = QHBoxLayout(account_frame)
        
        self.logout_btn = QPushButton("Logout")
        self.logout_btn.clicked.connect(self.logout)
        self.logout_btn.setFixedHeight(40)
        self.logout_btn.setEnabled(False)
        
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.clicked.connect(self.show_settings_dialog)
        self.settings_btn.setFixedHeight(40)
        self.settings_btn.setEnabled(False)
        
        account_layout.addWidget(self.logout_btn)
        account_layout.addWidget(self.settings_btn)
        account_layout.addStretch()
        self.main_layout.addWidget(account_frame)

        # Progress bar
        self.progress_label = QLabel("Transfer Progress:")
        self.progress_label.setVisible(False)
        self.main_layout.addWidget(self.progress_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(8)
        self.main_layout.addWidget(self.progress_bar)
        
        self.speed_label = QLabel("Speed: 0.00 MB/s")
        self.speed_label.setVisible(False)
        self.speed_label.setAlignment(Qt.AlignRight)
        self.main_layout.addWidget(self.speed_label)

        # Tabs
        tabs = QTabWidget()
        self.main_layout.addWidget(tabs)

        # Files Tab
        files_tab = QWidget()
        files_layout = QVBoxLayout(files_tab)

        # Search bar
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search files...")
        self.search_input.returnPressed.connect(self.search_files)
        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self.search_files)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(search_btn)
        files_layout.addLayout(search_layout)

        # Public files
        public_frame = QFrame()
        public_layout = QVBoxLayout(public_frame)
        public_label = QLabel("Public Files")
        public_label.setStyleSheet("font-weight: bold;")
        self.public_file_list = QListWidget()
        self.public_file_list.setSelectionMode(QListWidget.ExtendedSelection)
        public_layout.addWidget(public_label)
        public_layout.addWidget(self.public_file_list)
        files_layout.addWidget(public_frame)

        # Private files
        private_frame = QFrame()
        private_layout = QVBoxLayout(private_frame)
        private_label = QLabel("Private Files")
        private_label.setStyleSheet("font-weight: bold;")
        self.private_file_list = QListWidget()
        self.private_file_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.share_btn = QPushButton("Share Private File")
        self.share_btn.clicked.connect(self.share_file)
        self.share_btn.setEnabled(False)
        private_layout.addWidget(private_label)
        private_layout.addWidget(self.private_file_list)
        private_layout.addWidget(self.share_btn)
        files_layout.addWidget(private_frame)

        files_layout.addStretch()
        tabs.addTab(files_tab, "Files")

        # Action buttons
        button_frame = QFrame()
        button_layout = QHBoxLayout(button_frame)
        
        self.download_btn = QPushButton("Download Selected")
        self.download_btn.clicked.connect(self.download_files)
        self.download_btn.setFixedHeight(40)
        self.download_btn.setEnabled(False)
        
        self.pause_btn = QPushButton("Pause Download")
        self.pause_btn.clicked.connect(self.pause_download)
        self.pause_btn.setFixedHeight(40)
        self.pause_btn.setEnabled(False)
        
        self.upload_btn = QPushButton("Upload Files/Folders")
        self.upload_btn.clicked.connect(self.upload_files)
        self.upload_btn.setFixedHeight(40)
        self.upload_btn.setEnabled(False)
        
        self.delete_btn = QPushButton("Delete Selected")
        self.delete_btn.clicked.connect(self.delete_files)
        self.delete_btn.setFixedHeight(40)
        self.delete_btn.setEnabled(False)
        
        self.refresh_btn = QPushButton("Refresh List")
        self.refresh_btn.clicked.connect(self.refresh_file_list)
        self.refresh_btn.setFixedHeight(40)
        self.refresh_btn.setEnabled(False)
        
        button_layout.addWidget(self.download_btn)
        button_layout.addWidget(self.pause_btn)
        button_layout.addWidget(self.upload_btn)
        button_layout.addWidget(self.delete_btn)
        button_layout.addWidget(self.refresh_btn)
        self.main_layout.addWidget(button_frame)

        self.header_label.setText(f"Welcome, {self.display_name or self.username}")

    def apply_theme(self):
        palette = QPalette()
        if self.dark_mode:
            palette.setColor(QPalette.Window, QColor("#121212"))
            palette.setColor(QPalette.WindowText, QColor("#E0E0E0"))
            palette.setColor(QPalette.Base, QColor("#1E1E1E"))
            palette.setColor(QPalette.AlternateBase, QColor("#2D2D2D"))
            palette.setColor(QPalette.Text, QColor("#FFFFFF"))
            palette.setColor(QPalette.Button, QColor("#333333"))
            palette.setColor(QPalette.ButtonText, QColor("#FFFFFF"))
            palette.setColor(QPalette.Highlight, QColor("#BB86FC"))
            palette.setColor(QPalette.HighlightedText, QColor("#000000"))
            palette.setColor(QPalette.ToolTipBase, QColor("#BB86FC"))
            palette.setColor(QPalette.ToolTipText, QColor("#000000"))
        else:
            palette.setColor(QPalette.Window, QColor("#F5F5F5"))
            palette.setColor(QPalette.WindowText, QColor("#212121"))
            palette.setColor(QPalette.Base, QColor("#FFFFFF"))
            palette.setColor(QPalette.AlternateBase, QColor("#F5F5F5"))
            palette.setColor(QPalette.Text, QColor("#212121"))
            palette.setColor(QPalette.Button, QColor("#E0E0E0"))
            palette.setColor(QPalette.ButtonText, QColor("#212121"))
            palette.setColor(QPalette.Highlight, QColor("#6200EE"))
            palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
            palette.setColor(QPalette.ToolTipBase, QColor("#FFFFFF"))
            palette.setColor(QPalette.ToolTipText, QColor("#212121"))
        
        self.setPalette(palette)
        
        style = """
        QWidget {
            font-family: 'Segoe UI', Arial, sans-serif;
        }
        QMainWindow {
            background-color: palette(window);
        }
        QFrame {
            border-radius: 8px;
            background-color: palette(base);
        }
        QPushButton {
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 500;
            min-width: 80px;
            border: 1px solid palette(button);
        }
        QPushButton:hover {
            background-color: palette(highlight);
            color: palette(highlightedtext);
        }
        QPushButton:pressed {
            background-color: palette(highlight);
            color: palette(highlightedtext);
        }
        QPushButton:disabled {
            color: palette(windowText);
            background-color: palette(window);
        }
        QListWidget, QTextEdit, QLineEdit {
            border-radius: 6px;
            padding: 8px;
            border: 1px solid palette(mid);
            background-color: palette(base);
        }
        QTabWidget::pane {
            border-radius: 6px;
            border: 1px solid palette(mid);
        }
        QTabBar::tab {
            padding: 8px 16px;
            border-radius: 4px;
            margin-right: 4px;
        }
        QTabBar::tab:selected {
            background-color: palette(highlight);
            color: palette(highlightedtext);
        }
        QProgressBar {
            border-radius: 4px;
            border: 1px solid palette(mid);
            text-align: center;
        }
        QProgressBar::chunk {
            background-color: palette(highlight);
            border-radius: 4px;
        }
        QLabel {
            font-weight: 500;
        }
        """
        self.setStyleSheet(style)

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self.apply_theme()

    def toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and event.y() < 40:
            self.drag_pos = event.globalPos()
            event.accept()

    def mouseMoveEvent(self, event):
        if hasattr(self, 'drag_pos'):
            self.move(self.pos() + event.globalPos() - self.drag_pos)
            self.drag_pos = event.globalPos()
            event.accept()

    def mouseReleaseEvent(self, event):
        if hasattr(self, 'drag_pos'):
            del self.drag_pos

    def dragEnterEvent(self, event):
        if self.is_logged_in and event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not self.is_logged_in:
            return
            
        files = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if files:
            is_private = self.private_file_list.underMouse()
            self.start_transfer_thread()
            self.progress_bar.setVisible(True)
            self.progress_label.setVisible(True)
            self.speed_label.setVisible(True)
            self.progress_bar.setValue(0)
            self.thread.set_action('upload', file_paths=files, is_private=is_private)

    def show_settings_dialog(self):
        dialog = SettingsDialog(self, dark_mode=self.dark_mode)
        if dialog.exec_():
            settings = dialog.get_settings()
            if settings['dark_mode'] != self.dark_mode:
                self.toggle_theme()
            if settings['password'] or settings['display_name']:
                self.start_transfer_thread()
                if settings['password']:
                    self.thread.set_action('change_password', new_password=settings['password'])
                if settings['display_name']:
                    self.thread.set_action('update_display_name', display_name=settings['display_name'])
            if settings['sync_folder']:
                self.start_folder_sync(settings['sync_folder'])
            if settings['delete_account']:
                self.start_transfer_thread()
                self.thread.set_action('delete_account')
            if self.thread:
                self.thread.set_notifications(settings['notifications'])

    def start_folder_sync(self, folder):
        if self.sync_observer:
            self.sync_observer.stop()
            self.sync_observer.join()
        
        if os.path.isdir(folder):
            self.sync_folder = folder
            event_handler = SyncHandler(self.sync_queue)
            self.sync_observer = Observer()
            self.sync_observer.schedule(event_handler, folder, recursive=False)
            self.sync_observer.start()
            
            threading.Thread(target=self.process_sync_queue, daemon=True).start()
            self.update_status(f"Started syncing folder: {folder}")
        else:
            QMessageBox.critical(self, "Error", "Invalid sync folder.")

    def process_sync_queue(self):
        while self.is_logged_in:
            try:
                action, path = self.sync_queue.get(timeout=1)
                if action == 'upload' and self.thread and self.thread.isRunning():
                    self.thread.set_action('upload', file_paths=[path], is_private=True)
            except queue.Empty:
                continue

    def start_transfer_thread(self, server_ip=None, port=1253):
        if not self.thread or not self.thread.isRunning():
            self.thread = FileTransferThread()
            if server_ip:
                self.thread.host = server_ip
            if port:
                self.thread.port = port
            self.thread.update_status.connect(self.update_status)
            self.thread.error_occurred.connect(self.show_error)
            self.thread.login_status.connect(self.handle_login_status)
            self.thread.update_file_list.connect(self.update_file_list)
            self.thread.transfer_progress.connect(self.update_progress)
            self.thread.notify.connect(self.show_notification)
            self.thread.display_name_received.connect(self.update_display_name)
            self.thread.start()

    def handle_login_status(self, success):
        if success:
            self.is_logged_in = True
            self.username = self.thread.username
            self.show_main_ui()
            self.logout_btn.setEnabled(True)
            self.download_btn.setEnabled(True)
            self.upload_btn.setEnabled(True)
            self.refresh_btn.setEnabled(True)
            self.settings_btn.setEnabled(True)
            self.share_btn.setEnabled(True)
            self.delete_btn.setEnabled(True)
            self.pause_btn.setEnabled(True)
            self.update_status(f"Logged in as {self.username}")
            self.setWindowTitle(f"File Transfer Client - {self.display_name or self.username}")
        else:
            self.is_logged_in = False
            self.username = None
            self.display_name = None
            if self.thread:
                self.thread.stop()

    def update_display_name(self, display_name):
        self.display_name = display_name
        self.setWindowTitle(f"File Transfer Client - {self.display_name or self.username}")

    def logout(self):
        if self.thread and self.thread.isRunning():
            self.thread.set_action('logout')
            self.is_logged_in = False
            self.username = None
            self.display_name = None
            self.logout_btn.setEnabled(False)
            self.download_btn.setEnabled(False)
            self.upload_btn.setEnabled(False)
            self.refresh_btn.setEnabled(False)
            self.settings_btn.setEnabled(False)
            self.share_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.public_file_list.clear()
            self.private_file_list.clear()
            self.progress_bar.setVisible(False)
            self.progress_label.setVisible(False)
            self.speed_label.setVisible(False)
            self.setWindowTitle("File Transfer Client")
            if self.sync_observer:
                self.sync_observer.stop()
                self.sync_observer.join()
                self.sync_observer = None

    def refresh_file_list(self):
        if self.thread and self.thread.isRunning():
            self.thread.set_action('list')

    def update_file_list(self, public_files, private_files):
        self.public_file_list.clear()
        self.private_file_list.clear()
        
        if not public_files:
            self.public_file_list.addItem("No public files available")
        else:
            self.public_file_list.addItems(public_files)
            
        if not private_files:
            self.private_file_list.addItem("No private files available")
        else:
            self.private_file_list.addItems(private_files)

    def search_files(self):
        search_query = self.search_input.text().strip()
        if search_query and self.thread and self.thread.isRunning():
            self.thread.set_action('search', file_names=[search_query])

    def download_files(self):
        selected_public = self.public_file_list.selectedItems()
        selected_private = self.private_file_list.selectedItems()
        selected_items = selected_public + selected_private
        
        if not selected_items:
            QMessageBox.warning(self, "Warning", "Please select files to download.")
            return
            
        file_names = [item.text() for item in selected_items if item.text() not in ["No public files available", "No private files available"]]
        if file_names and self.thread and self.thread.isRunning():
            self.progress_bar.setVisible(True)
            self.progress_label.setVisible(True)
            self.speed_label.setVisible(True)
            self.progress_bar.setValue(0)
            self.thread.set_action('download', file_names=file_names)

    def pause_download(self):
        selected_public = self.public_file_list.selectedItems()
        selected_private = self.private_file_list.selectedItems()
        selected_items = selected_public + selected_private
        
        if not selected_items:
            QMessageBox.warning(self, "Warning", "Please select a file to pause.")
            return
            
        file_names = [item.text() for item in selected_items if item.text() not in ["No public files available", "No private files available"]]
        for file_name in file_names:
            if self.thread and self.thread.isRunning():
                self.thread.pause_download(file_name)
                self.update_status(f"Paused download of '{file_name}'")

    def upload_files(self):
        dialog = QFileDialog(self)
        dialog.setFileMode(QFileDialog.ExistingFiles | QFileDialog.Directory)
        if dialog.exec_():
            file_paths = dialog.selectedFiles()
            if file_paths:
                is_private, ok = QInputDialog.getItem(self, "Privacy", "Upload as private?", ["Yes", "No"], 0, False)
                if ok:
                    is_private = (is_private == "Yes")
                    if self.thread and self.thread.isRunning():
                        self.progress_bar.setVisible(True)
                        self.progress_label.setVisible(True)
                        self.speed_label.setVisible(True)
                        self.progress_bar.setValue(0)
                        self.thread.set_action('upload', file_paths=file_paths, is_private=is_private)

    def delete_files(self):
        selected_public = self.public_file_list.selectedItems()
        selected_private = self.private_file_list.selectedItems()
        selected_items = selected_public + selected_private
        
        if not selected_items:
            QMessageBox.warning(self, "Warning", "Please select files to delete.")
            return
            
        file_names = [item.text() for item in selected_items if item.text() not in ["No public files available", "No private files available"]]
        if file_names and self.thread and self.thread.isRunning():
            reply = QMessageBox.question(self, "Confirm", f"Are you sure you want to delete {len(file_names)} file(s)?",
                                       QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.thread.set_action('delete_file', file_names=file_names)

    def share_file(self):
        selected = self.private_file_list.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Warning", "Please select a private file to share.")
            return
        file_name = selected[0].text()
        target_user, ok = QInputDialog.getText(self, "Share File", "Enter username to share with:")
        if ok and target_user:
            if self.thread and self.thread.isRunning():
                self.thread.set_action('share', file_names=[file_name, target_user])

    def update_status(self, message):
        if self.status_label:
            self.status_label.setText(f"Status: {message}")

    def update_progress(self, filename, current, total, speed):
        if total > 0:
            progress = int((current / total) * 100)
            self.progress_label.setText(f"Transfer Progress: {filename} ({current:,}/{total:,} bytes)")
            self.speed_label.setText(f"Speed: {speed:.2f} MB/s")
            self.progress_bar.setValue(progress)
            if progress >= 100:
                self.progress_bar.setVisible(False)
                self.progress_label.setVisible(False)
                self.speed_label.setVisible(False)

    def show_error(self, message):
        QMessageBox.critical(self, "Error", message)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self.speed_label.setVisible(False)

    def show_notification(self, message):
        QMessageBox.information(self, "Notification", message)

    def closeEvent(self, event):
        if self.thread and self.thread.isRunning():
            if self.is_logged_in:
                self.thread.set_action('logout')
            else:
                self.thread.stop()
            self.thread.wait()
        if self.sync_observer:
            self.sync_observer.stop()
            self.sync_observer.join()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    font = QFont()
    font.setFamily("Segoe UI" if sys.platform == "win32" else "Arial")
    font.setPointSize(10)
    app.setFont(font)
    
    window = ClientGUI()
    window.show()
    sys.exit(app.exec_())