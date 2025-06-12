import socket
import os
import sys
import time
import shutil
import threading
import queue
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QPushButton, QListWidget, QLineEdit, QLabel, QFileDialog, QMessageBox,
                            QDialog, QFormLayout, QProgressBar, QFrame, QAction, QMenuBar, QCheckBox,
                            QTabWidget, QInputDialog, QLineEdit as QLineEditBase)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QPalette, QColor, QFont
from tqdm import tqdm

class FileTransferThread(QThread):
    update_status = pyqtSignal(str)
    update_file_list = pyqtSignal(list, list)  # public_files, private_files
    error_occurred = pyqtSignal(str)
    login_status = pyqtSignal(bool)
    transfer_progress = pyqtSignal(str, int, int)  # filename, current, total
    notify = pyqtSignal(str)  # For notifications

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
        self.download_dir = 'downloads'
        self.host = socket.gethostname()
        self.port = 1253
        self.is_logged_in = False
        self.current_file_size = 0
        self.enable_notifications = True
        self.download_tasks = {}  # {filename: (file, offset, total)}
        self.paused_downloads = set()

    def set_action(self, action, file_names=None, file_paths=None, username=None, password=None, 
                  is_private=False, new_password=None):
        self.action = action
        self.file_names = file_names if file_names else []
        self.file_paths = file_paths if file_paths else []
        self.username = username
        self.password = password
        self.is_private = is_private
        self.new_password = new_password

    def set_notifications(self, enabled):
        self.enable_notifications = enabled

    def connect_to_server(self):
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.connect((self.host, self.port))
            self.running = True
            self.update_status.emit("Connected to server.")
            
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
            
            try:
                mode = 'wb' if offset == 0 else 'ab'
                with open(file_path, mode) as f:
                    with tqdm(total=file_size, unit='B', unit_scale=True, desc=file_name) as pbar:
                        while received_size < file_size:
                            if file_name in self.paused_downloads:
                                self.download_tasks[file_name] = (f, received_size, file_size)
                                return
                            data = self.client_socket.recv(1024)
                            if not data:
                                break
                            f.write(data)
                            received_size += len(data)
                            pbar.update(len(data))
                            self.transfer_progress.emit(file_name, received_size, file_size)
                            
                del self.download_tasks[file_name]
                if is_zip:
                    shutil.unpack_archive(file_path, os.path.join(self.download_dir, file_name), 'zip')
                    os.remove(file_path)
                
                self.update_status.emit(f"Downloaded '{file_name}' to '{self.download_dir}'")
                if self.enable_notifications:
                    self.notify.emit(f"Download complete: {file_name}")
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
            with tqdm(total=total, unit='B', unit_scale=True, desc=file_name, initial=offset) as pbar:
                while offset < total:
                    if file_name in self.paused_downloads:
                        self.download_tasks[file_name] = (f, offset, total)
                        return
                    data = self.client_socket.recv(1024)
                    if not data:
                        break
                    f.write(data)
                    offset += len(data)
                    pbar.update(len(data))
                    self.transfer_progress.emit(file_name, offset, total)
                
            del self.download_tasks[file_name]
            self.update_status.emit(f"Resumed and completed '{file_name}'")
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
            
            if is_folder:
                zip_path = file_path + '.zip'
                shutil.make_archive(file_path, 'zip', file_path)
                file_size = os.path.getsize(zip_path)
            else:
                if not os.path.isfile(file_path):
                    self.error_occurred.emit(f"File '{file_path}' not found.")
                    continue
                file_size = os.path.getsize(file_path)
            
            self.current_file_size = file_size
            is_private = 1 if self.is_private else 0
            is_folder_flag = 1 if is_folder else 0
            self.client_socket.send(f"UPLOAD:{file_name}:{file_size}:{is_private}:{is_folder_flag}".encode('utf-8'))
            
            try:
                source_path = zip_path if is_folder else file_path
                with open(source_path, 'rb') as f:
                    with tqdm(total=file_size, unit='B', unit_scale=True, desc=file_name) as pbar:
                        bytes_sent = 0
                        while True:
                            data = f.read(1024)
                            if not data:
                                break
                            self.client_socket.sendall(data)
                            bytes_sent += len(data)
                            pbar.update(len(data))
                            self.transfer_progress.emit(file_name, bytes_sent, file_size)
                        
                if is_folder:
                    os.remove(zip_path)
                
                response = self.client_socket.recv(1024).decode('utf-8')
                self.update_status.emit(response)
                if self.enable_notifications:
                    self.notify.emit(f"Upload complete: {file_name}")
                
                self.handle_list_request()
            except Exception as e:
                self.error_occurred.emit(f"Error uploading file: {str(e)}")

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

class LoginDialog(QDialog):
    def __init__(self, parent=None, dark_mode=False):
        super().__init__(parent)
        self.dark_mode = dark_mode
        self.setWindowTitle("Login")
        self.setMinimumWidth(300)
        self.init_ui()
        self.apply_theme()

    def init_ui(self):
        layout = QFormLayout()
        
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Enter username")
        
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Enter password")
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

    def apply_theme(self):
        palette = self.palette()
        if self.dark_mode:
            palette.setColor(QPalette.Window, QColor("#1E1E2F"))
            palette.setColor(QPalette.WindowText, QColor("#E0E0E0"))
            palette.setColor(QPalette.Base, QColor("#1E1E2F"))
            palette.setColor(QPalette.Text, QColor("#E0E0E0"))
            palette.setColor(QPalette.Button, QColor("#4A90E2"))
            palette.setColor(QPalette.ButtonText, QColor("#FFFFFF"))
        else:
            palette.setColor(QPalette.Window, QColor("#F5F7FA"))
            palette.setColor(QPalette.WindowText, QColor("#2C3E50"))
            palette.setColor(QPalette.Base, QColor("#F5F7FA"))
            palette.setColor(QPalette.Text, QColor("#2C3E50"))
            palette.setColor(QPalette.Button, QColor("#2E7D32"))
            palette.setColor(QPalette.ButtonText, QColor("#FFFFFF"))
        self.setPalette(palette)

    def get_credentials(self):
        return self.username_input.text().strip(), self.password_input.text().strip()

class SettingsDialog(QDialog):
    def __init__(self, parent=None, dark_mode=False):
        super().__init__(parent)
        self.dark_mode = dark_mode
        self.setWindowTitle("Settings")
        self.setMinimumWidth(400)
        self.init_ui()
        self.apply_theme()

    def init_ui(self):
        layout = QFormLayout()
        
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Enter new password")
        self.password_input.setEchoMode(QLineEdit.Password)
        
        self.sync_folder_input = QLineEdit()
        self.sync_folder_input.setPlaceholderText("Select sync folder")
        self.sync_folder_input.setReadOnly(True)
        sync_btn = QPushButton("Browse")
        sync_btn.clicked.connect(self.select_sync_folder)
        
        self.notify_check = QCheckBox("Enable notifications for transfers and shares")
        self.notify_check.setChecked(True)
        
        self.delete_account_btn = QPushButton("Delete My Account")
        self.delete_account_btn.clicked.connect(self.delete_account)
        
        layout.addRow("New Password:", self.password_input)
        layout.addRow("Sync Folder:", self.sync_folder_input)
        layout.addRow("", sync_btn)
        layout.addRow("Notifications:", self.notify_check)
        layout.addRow("", self.delete_account_btn)
        
        buttons = QHBoxLayout()
        ok_btn = QPushButton("Save")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(ok_btn)
        buttons.addWidget(cancel_btn)
        
        layout.addRow(buttons)
        self.setLayout(layout)

    def apply_theme(self):
        palette = self.palette()
        if self.dark_mode:
            palette.setColor(QPalette.Window, QColor("#1E1E2F"))
            palette.setColor(QPalette.WindowText, QColor("#E0E0E0"))
            palette.setColor(QPalette.Base, QColor("#1E1E2F"))
            palette.setColor(QPalette.Text, QColor("#E0E0E0"))
            palette.setColor(QPalette.Button, QColor("#4A90E2"))
            palette.setColor(QPalette.ButtonText, QColor("#FFFFFF"))
        else:
            palette.setColor(QPalette.Window, QColor("#F5F7FA"))
            palette.setColor(QPalette.WindowText, QColor("#2C3E50"))
            palette.setColor(QPalette.Base, QColor("#F5F7FA"))
            palette.setColor(QPalette.Text, QColor("#2C3E50"))
            palette.setColor(QPalette.Button, QColor("#2E7D32"))
            palette.setColor(QPalette.ButtonText, QColor("#FFFFFF"))
        self.setPalette(palette)

    def select_sync_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Sync Folder")
        if folder:
            self.sync_folder_input.setText(folder)

    def delete_account(self):
        reply = QMessageBox.question(self, "Confirm", "Are you sure you want to delete your account? This action cannot be undone.",
                                   QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.accept()

    def get_settings(self):
        return {
            'password': self.password_input.text().strip(),
            'sync_folder': self.sync_folder_input.text().strip(),
            'notifications': self.notify_check.isChecked(),
            'delete_account': self.delete_account_btn.isEnabled() and self.delete_account_btn.text() == "Delete My Account"
        }

class ClientGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("File Transfer Client")
        self.setGeometry(100, 100, 800, 600)
        self.is_logged_in = False
        self.username = None
        self.thread = None
        self.dark_mode = True
        self.sync_observer = None
        self.sync_queue = queue.Queue()
        self.sync_folder = None
        self.init_ui()
        self.apply_theme()
        self.setAcceptDrops(True)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Account controls
        account_frame = QFrame()
        account_frame.setFrameShape(QFrame.StyledPanel)
        account_layout = QHBoxLayout(account_frame)
        account_layout.setContentsMargins(10, 10, 10, 10)
        
        self.login_btn = QPushButton("Login")
        self.login_btn.clicked.connect(self.show_login_dialog)
        self.login_btn.setFixedHeight(40)
        
        self.logout_btn = QPushButton("Logout")
        self.logout_btn.clicked.connect(self.logout)
        self.logout_btn.setFixedHeight(40)
        self.logout_btn.setEnabled(False)
        
        self.theme_btn = QPushButton("Light Mode")
        self.theme_btn.clicked.connect(self.toggle_theme)
        self.theme_btn.setFixedHeight(40)
        
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.clicked.connect(self.show_settings_dialog)
        self.settings_btn.setFixedHeight(40)
        self.settings_btn.setEnabled(False)
        
        account_layout.addWidget(self.login_btn)
        account_layout.addWidget(self.logout_btn)
        account_layout.addWidget(self.theme_btn)
        account_layout.addWidget(self.settings_btn)
        layout.addWidget(account_frame)

        # Status label
        self.status_label = QLabel("Status: Ready to connect")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        # Progress bar
        self.progress_label = QLabel("Transfer Progress:")
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(8)
        layout.addWidget(self.progress_bar)

        # Tabs
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # Files Tab
        files_tab = QWidget()
        files_layout = QVBoxLayout(files_tab)
        files_layout.setContentsMargins(10, 10, 10, 10)

        # Search bar
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search files...")
        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self.search_files)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(search_btn)
        files_layout.addLayout(search_layout)

        # Public files
        public_frame = QFrame()
        public_layout = QVBoxLayout(public_frame)
        public_label = QLabel("Public Files: (Drag and drop here to upload public files)")
        public_label.setStyleSheet("font-weight: bold;")
        self.public_file_list = QListWidget()
        self.public_file_list.setSelectionMode(QListWidget.MultiSelection)
        self.public_file_list.setAcceptDrops(True)
        public_layout.addWidget(public_label)
        public_layout.addWidget(self.public_file_list)

        # Private files
        private_frame = QFrame()
        private_layout = QVBoxLayout(private_frame)
        private_label = QLabel("Private Files: (Drag and drop here to upload private files)")
        private_label.setStyleSheet("font-weight: bold;")
        self.private_file_list = QListWidget()
        self.private_file_list.setSelectionMode(QListWidget.MultiSelection)
        self.private_file_list.setAcceptDrops(True)
        self.share_btn = QPushButton("Share Private File")
        self.share_btn.clicked.connect(self.share_file)
        self.share_btn.setEnabled(False)
        private_layout.addWidget(private_label)
        private_layout.addWidget(self.private_file_list)
        private_layout.addWidget(self.share_btn)

        files_layout.addWidget(public_frame)
        files_layout.addWidget(private_frame)
        tabs.addTab(files_tab, "Files")

        # Action buttons
        button_frame = QFrame()
        button_frame.setFrameShape(QFrame.StyledPanel)
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(10, 10, 10, 10)
        
        self.download_btn = QPushButton("Download Selected")
        self.download_btn.clicked.connect(self.download_files)
        self.download_btn.setEnabled(False)
        self.download_btn.setFixedHeight(40)
        
        self.pause_btn = QPushButton("Pause Download")
        self.pause_btn.clicked.connect(self.pause_download)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setFixedHeight(40)
        
        self.upload_btn = QPushButton("Upload Files/Folders")
        self.upload_btn.clicked.connect(self.upload_files)
        self.upload_btn.setEnabled(False)
        self.upload_btn.setFixedHeight(40)
        
        self.delete_btn = QPushButton("Delete Selected")
        self.delete_btn.clicked.connect(self.delete_files)
        self.delete_btn.setEnabled(False)
        self.delete_btn.setFixedHeight(40)
        
        self.refresh_btn = QPushButton("Refresh List")
        self.refresh_btn.clicked.connect(self.refresh_file_list)
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setFixedHeight(40)
        
        button_layout.addWidget(self.download_btn)
        button_layout.addWidget(self.pause_btn)
        button_layout.addWidget(self.upload_btn)
        button_layout.addWidget(self.delete_btn)
        button_layout.addWidget(self.refresh_btn)
        layout.addWidget(button_frame)

    def apply_theme(self):
        palette = self.palette()
        if self.dark_mode:
            palette.setColor(QPalette.Window, QColor("#1E1E2F"))
            palette.setColor(QPalette.WindowText, QColor("#E0E0E0"))
            palette.setColor(QPalette.Base, QColor("#1E1E2F"))
            palette.setColor(QPalette.Text, QColor("#E0E0E0"))
            palette.setColor(QPalette.Button, QColor("#4A90E2"))
            palette.setColor(QPalette.ButtonText, QColor("#FFFFFF"))
            palette.setColor(QPalette.Highlight, QColor("#FF6B6B"))
            palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
            self.theme_btn.setText("Light Mode")
        else:
            palette.setColor(QPalette.Window, QColor("#F5F7FA"))
            palette.setColor(QPalette.WindowText, QColor("#2C3E50"))
            palette.setColor(QPalette.Base, QColor("#F5F7FA"))
            palette.setColor(QPalette.Text, QColor("#2C3E50"))
            palette.setColor(QPalette.Button, QColor("#2E7D32"))
            palette.setColor(QPalette.ButtonText, QColor("#FFFFFF"))
            palette.setColor(QPalette.Highlight, QColor("#4CAF50"))
            palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
            self.theme_btn.setText("Dark Mode")
        self.setPalette(palette)

        style = """
        QFrame {
            border-radius: 8px;
        }
        QPushButton {
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 500;
        }
        QPushButton:enabled:hover {
            background-color: palette(highlight);
            color: palette(highlightedtext);
        }
        QPushButton:checked {
            background-color: palette(highlight);
            color: palette(highlightedtext);
        }
        QListWidget, QTextEdit {
            border-radius: 6px;
            padding: 8px;
        }
        QTabWidget::pane {
            border-radius: 6px;
        }
        QComboBox {
            border-radius: 6px;
            padding: 4px;
        }
        """
        self.setStyleSheet(style)

        for widget in self.findChildren(QWidget):
            widget.setPalette(palette)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self.apply_theme()

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
            self.progress_bar.setValue(0)
            self.thread.set_action('upload', file_paths=files, is_private=is_private)

    def show_login_dialog(self):
        dialog = LoginDialog(self, dark_mode=self.dark_mode)
        if dialog.exec_():
            username, password = dialog.get_credentials()
            if username and password:
                self.start_transfer_thread()
                self.thread.set_action('login', username=username, password=password)

    def show_settings_dialog(self):
        dialog = SettingsDialog(self, dark_mode=self.dark_mode)
        if dialog.exec_():
            settings = dialog.get_settings()
            if settings['password']:
                self.start_transfer_thread()
                self.thread.set_action('change_password', new_password=settings['password'])
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

    def start_transfer_thread(self):
        if not self.thread or not self.thread.isRunning():
            self.thread = FileTransferThread()
            self.thread.update_status.connect(self.update_status)
            self.thread.error_occurred.connect(self.show_error)
            self.thread.login_status.connect(self.handle_login_status)
            self.thread.update_file_list.connect(self.update_file_list)
            self.thread.transfer_progress.connect(self.update_progress)
            self.thread.notify.connect(self.show_notification)
            self.thread.start()

    def handle_login_status(self, success):
        if success:
            self.is_logged_in = True
            self.username = self.thread.username
            self.login_btn.setEnabled(False)
            self.logout_btn.setEnabled(True)
            self.download_btn.setEnabled(True)
            self.upload_btn.setEnabled(True)
            self.refresh_btn.setEnabled(True)
            self.settings_btn.setEnabled(True)
            self.share_btn.setEnabled(True)
            self.delete_btn.setEnabled(True)
            self.pause_btn.setEnabled(True)
            self.update_status(f"Logged in as {self.username}")
        else:
            self.is_logged_in = False
            self.username = None
            if self.thread:
                self.thread.stop()

    def logout(self):
        if self.thread and self.thread.isRunning():
            self.thread.set_action('logout')
            self.is_logged_in = False
            self.username = None
            self.login_btn.setEnabled(True)
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
        self.status_label.setText(f"Status: {message}")

    def update_progress(self, filename, current, total):
        if total > 0:
            progress = int((current / total) * 100)
            self.progress_label.setText(f"Transfer Progress: {filename} ({current:,}/{total:,} bytes)")
            self.progress_bar.setValue(progress)
            if progress >= 100:
                self.progress_bar.setVisible(False)
                self.progress_label.setVisible(False)

    def show_error(self, message):
        QMessageBox.critical(self, "Error", message)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

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