import socket
import os
import sys
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QPushButton, QListWidget, QLineEdit, QLabel, QFileDialog, QMessageBox,
                            QDialog, QFormLayout, QProgressBar, QFrame, QAction, QMenuBar, QCheckBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPalette, QColor, QFont

class FileTransferThread(QThread):
    update_status = pyqtSignal(str)
    update_file_list = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    login_status = pyqtSignal(bool)
    transfer_progress = pyqtSignal(str, int, int)  # filename, current, total

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
        self.download_dir = 'downloads'
        self.host = socket.gethostname()
        self.port = 1253
        self.is_logged_in = False
        self.current_file_size = 0

    def set_action(self, action, file_names=None, file_paths=None, username=None, password=None, is_private=False):
        self.action = action
        self.file_names = file_names if file_names else []
        self.file_paths = file_paths if file_paths else []
        self.username = username
        self.password = password
        self.is_private = is_private

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
                elif self.action == 'register':
                    self.handle_registration()
                elif self.action == 'login':
                    self.handle_login()
                elif self.action == 'logout':
                    self.handle_logout()
                elif self.action == 'download' and self.is_logged_in and self.file_names:
                    self.handle_download()
                elif self.action == 'upload' and self.is_logged_in and self.file_paths:
                    self.handle_upload()
                
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
        self.update_file_list.emit(received_data)

    def handle_registration(self):
        self.client_socket.send(f"REGISTER:{self.username}:{self.password}".encode('utf-8'))
        response = self.client_socket.recv(1024).decode('utf-8')
        if response.startswith("Error:"):
            self.error_occurred.emit(response)
        else:
            self.update_status.emit(response)

    def handle_login(self):
        self.client_socket.send(f"LOGIN:{self.username}:{self.password}".encode('utf-8'))
        response = self.client_socket.recv(1024).decode('utf-8')
        
        if response == "Login successful.":
            self.is_logged_in = True
            self.login_status.emit(True)
            self.update_status.emit(response)
            file_list_data = self.client_socket.recv(4096).decode('utf-8')
            self.update_file_list.emit(file_list_data)
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
        file_names_str = ','.join(self.file_names)
        self.client_socket.send(f"DOWNLOAD:{file_names_str}".encode('utf-8'))
        
        for file_name in self.file_names:
            response = self.client_socket.recv(1024).decode('utf-8')
            if response.startswith("Error:"):
                self.error_occurred.emit(response)
                continue
                
            if response.startswith("FILE_SIZE:"):
                file_size = int(response[10:])
                self.current_file_size = file_size
                
                if not os.path.exists(self.download_dir):
                    os.makedirs(self.download_dir)
                    
                file_path = os.path.join(self.download_dir, file_name)
                received_size = 0
                
                try:
                    with open(file_path, 'wb') as f:
                        while received_size < file_size:
                            data = self.client_socket.recv(1024)
                            if not data:
                                break
                            f.write(data)
                            received_size += len(data)
                            self.transfer_progress.emit(file_name, received_size, file_size)
                            
                    self.update_status.emit(f"Downloaded '{file_name}' to '{self.download_dir}'")
                except Exception as e:
                    self.error_occurred.emit(f"Error saving file: {str(e)}")
                    if os.path.exists(file_path):
                        os.remove(file_path)

    def handle_upload(self):
        for file_path in self.file_paths:
            if not os.path.isfile(file_path):
                self.error_occurred.emit(f"File '{file_path}' not found.")
                continue
                
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            self.current_file_size = file_size
            
            is_private = 1 if self.is_private else 0
            self.client_socket.send(f"UPLOAD:{file_name}:{file_size}:{is_private}".encode('utf-8'))
            
            try:
                with open(file_path, 'rb') as f:
                    bytes_sent = 0
                    while True:
                        data = f.read(1024)
                        if not data:
                            break
                        self.client_socket.sendall(data)
                        bytes_sent += len(data)
                        self.transfer_progress.emit(file_name, bytes_sent, file_size)
                        
                response = self.client_socket.recv(1024).decode('utf-8')
                self.update_status.emit(response)
                
                file_list_data = self.client_socket.recv(4096).decode('utf-8')
                self.update_file_list.emit(file_list_data)
            except Exception as e:
                self.error_occurred.emit(f"Error uploading file: {str(e)}")

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

class LoginDialog(QDialog):
    def __init__(self, parent=None, is_register=False, dark_mode=False):
        super().__init__(parent)
        self.is_register = is_register
        self.dark_mode = dark_mode
        self.setWindowTitle("Register" if is_register else "Login")
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
            palette.setColor(QPalette.Window, QColor("#1E293B"))
            palette.setColor(QPalette.WindowText, QColor("#F0F2F5"))
            palette.setColor(QPalette.Base, QColor("#1E293B"))
            palette.setColor(QPalette.Text, QColor("#F0F2F5"))
            palette.setColor(QPalette.Button, QColor("#38BDF8"))
            palette.setColor(QPalette.ButtonText, QColor("#F0F2F5"))
        else:
            palette.setColor(QPalette.Window, QColor("#F7F9FC"))
            palette.setColor(QPalette.WindowText, QColor("#212529"))
            palette.setColor(QPalette.Base, QColor("#FFFFFF"))
            palette.setColor(QPalette.Text, QColor("#212529"))
            palette.setColor(QPalette.Button, QColor("#38BDF8"))
            palette.setColor(QPalette.ButtonText, QColor("#FFFFFF"))
        self.setPalette(palette)

    def get_credentials(self):
        return self.username_input.text().strip(), self.password_input.text().strip()

class UploadDialog(QDialog):
    def __init__(self, parent=None, dark_mode=False):
        super().__init__(parent)
        self.dark_mode = dark_mode
        self.setWindowTitle("Upload Files")
        self.setMinimumWidth(300)
        self.init_ui()
        self.apply_theme()

    def init_ui(self):
        layout = QFormLayout()
        
        self.private_check = QCheckBox("Make files private (only visible to you)")
        
        buttons = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(ok_btn)
        buttons.addWidget(cancel_btn)
        
        layout.addRow(self.private_check)
        layout.addRow(buttons)
        self.setLayout(layout)

    def apply_theme(self):
        palette = self.palette()
        if self.dark_mode:
            palette.setColor(QPalette.Window, QColor("#1E293B"))
            palette.setColor(QPalette.WindowText, QColor("#F0F2F5"))
            palette.setColor(QPalette.Base, QColor("#1E293B"))
            palette.setColor(QPalette.Text, QColor("#F0F2F5"))
            palette.setColor(QPalette.Button, QColor("#38BDF8"))
            palette.setColor(QPalette.ButtonText, QColor("#F0F2F5"))
        else:
            palette.setColor(QPalette.Window, QColor("#F7F9FC"))
            palette.setColor(QPalette.WindowText, QColor("#212529"))
            palette.setColor(QPalette.Base, QColor("#FFFFFF"))
            palette.setColor(QPalette.Text, QColor("#212529"))
            palette.setColor(QPalette.Button, QColor("#38BDF8"))
            palette.setColor(QPalette.ButtonText, QColor("#FFFFFF"))
        self.setPalette(palette)

    def is_private(self):
        return self.private_check.isChecked()

class ClientGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("File Transfer Client")
        self.setGeometry(100, 100, 800, 600)
        self.is_logged_in = False
        self.username = None
        self.thread = None
        self.dark_mode = False
        self.init_ui()
        self.apply_theme()
        self.setAcceptDrops(True)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Menu Bar
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        
        theme_action = QAction("Toggle Dark Mode", self)
        theme_action.triggered.connect(self.toggle_theme)
        file_menu.addAction(theme_action)
        
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Account controls
        account_frame = QFrame()
        account_frame.setFrameShape(QFrame.StyledPanel)
        account_layout = QHBoxLayout(account_frame)
        account_layout.setContentsMargins(10, 10, 10, 10)
        
        self.login_btn = QPushButton("Login")
        self.login_btn.clicked.connect(self.show_login_dialog)
        self.login_btn.setFixedHeight(40)
        
        self.register_btn = QPushButton("Register")
        self.register_btn.clicked.connect(self.show_register_dialog)
        self.register_btn.setFixedHeight(40)
        
        self.logout_btn = QPushButton("Logout")
        self.logout_btn.clicked.connect(self.logout)
        self.logout_btn.setFixedHeight(40)
        self.logout_btn.setEnabled(False)
        
        account_layout.addWidget(self.login_btn)
        account_layout.addWidget(self.register_btn)
        account_layout.addWidget(self.logout_btn)
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

        # File list
        file_frame = QFrame()
        file_frame.setFrameShape(QFrame.StyledPanel)
        file_layout = QVBoxLayout(file_frame)
        file_layout.setContentsMargins(10, 10, 10, 10)
        
        file_label = QLabel("Files on Server: (Drag and drop files here to upload)")
        file_label.setStyleSheet("font-weight: bold;")
        
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.MultiSelection)
        self.file_list.setAcceptDrops(True)
        
        file_layout.addWidget(file_label)
        file_layout.addWidget(self.file_list)
        layout.addWidget(file_frame)

        # Action buttons
        button_frame = QFrame()
        button_frame.setFrameShape(QFrame.StyledPanel)
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(10, 10, 10, 10)
        
        self.download_btn = QPushButton("Download Selected")
        self.download_btn.clicked.connect(self.download_files)
        self.download_btn.setEnabled(False)
        self.download_btn.setFixedHeight(40)
        
        self.upload_btn = QPushButton("Upload Files")
        self.upload_btn.clicked.connect(self.upload_files)
        self.upload_btn.setEnabled(False)
        self.upload_btn.setFixedHeight(40)
        
        self.refresh_btn = QPushButton("Refresh List")
        self.refresh_btn.clicked.connect(self.refresh_file_list)
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setFixedHeight(40)
        
        button_layout.addWidget(self.download_btn)
        button_layout.addWidget(self.upload_btn)
        button_layout.addWidget(self.refresh_btn)
        layout.addWidget(button_frame)

    def apply_theme(self):
        palette = self.palette()
        if self.dark_mode:
            palette.setColor(QPalette.Window, QColor("#1E293B"))
            palette.setColor(QPalette.WindowText, QColor("#F0F2F5"))
            palette.setColor(QPalette.Base, QColor("#1E293B"))
            palette.setColor(QPalette.Text, QColor("#F0F2F5"))
            palette.setColor(QPalette.Button, QColor("#38BDF8"))
            palette.setColor(QPalette.ButtonText, QColor("#F0F2F5"))
            palette.setColor(QPalette.Highlight, QColor("#10B981"))
            palette.setColor(QPalette.HighlightedText, QColor("#1E293B"))
        else:
            palette.setColor(QPalette.Window, QColor("#F7F9FC"))
            palette.setColor(QPalette.WindowText, QColor("#212529"))
            palette.setColor(QPalette.Base, QColor("#FFFFFF"))
            palette.setColor(QPalette.Text, QColor("#212529"))
            palette.setColor(QPalette.Button, QColor("#38BDF8"))
            palette.setColor(QPalette.ButtonText, QColor("#FFFFFF"))
            palette.setColor(QPalette.Highlight, QColor("#10B981"))
            palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
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
        QListWidget {
            border-radius: 6px;
            padding: 8px;
        }
        QProgressBar {
            border-radius: 4px;
            text-align: center;
        }
        QProgressBar::chunk {
            border-radius: 4px;
        }
        """
        self.setStyleSheet(style)

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
            dialog = UploadDialog(self, dark_mode=self.dark_mode)
            if dialog.exec_():
                is_private = dialog.is_private()
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

    def show_register_dialog(self):
        dialog = LoginDialog(self, is_register=True, dark_mode=self.dark_mode)
        if dialog.exec_():
            username, password = dialog.get_credentials()
            if username and password:
                self.start_transfer_thread()
                self.thread.set_action('register', username=username, password=password)

    def start_transfer_thread(self):
        if not self.thread or not self.thread.isRunning():
            self.thread = FileTransferThread()
            self.thread.update_status.connect(self.update_status)
            self.thread.error_occurred.connect(self.show_error)
            self.thread.login_status.connect(self.handle_login_status)
            self.thread.update_file_list.connect(self.update_file_list)
            self.thread.transfer_progress.connect(self.update_progress)
            self.thread.start()

    def handle_login_status(self, success):
        if success:
            self.is_logged_in = True
            self.username = self.thread.username
            self.login_btn.setEnabled(False)
            self.register_btn.setEnabled(False)
            self.logout_btn.setEnabled(True)
            self.download_btn.setEnabled(True)
            self.upload_btn.setEnabled(True)
            self.refresh_btn.setEnabled(True)
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
            self.register_btn.setEnabled(True)
            self.logout_btn.setEnabled(False)
            self.download_btn.setEnabled(False)
            self.upload_btn.setEnabled(False)
            self.refresh_btn.setEnabled(False)
            self.file_list.clear()
            self.progress_bar.setVisible(False)
            self.progress_label.setVisible(False)

    def refresh_file_list(self):
        if self.thread and self.thread.isRunning():
            self.thread.set_action('list')

    def update_file_list(self, file_list):
        self.file_list.clear()
        
        if file_list.startswith("Error:"):
            self.show_error(file_list)
        elif file_list.startswith("No files"):
            self.file_list.addItem(file_list)
        elif "Files on server:" in file_list or "Files:" in file_list:
            files = []
            if '\n' in file_list:
                lines = file_list.split('\n')
                for line in lines[1:]:
                    clean_line = line.strip().lstrip('-').strip()
                    if clean_line:
                        files.append(clean_line)
            else:
                clean_line = file_list.split(':')[-1].strip()
                if clean_line:
                    files = [clean_line]
            
            if files:
                self.file_list.addItems(files)
            else:
                self.file_list.addItem("No files found")
        else:
            self.show_error(f"Unexpected server response: {file_list[:100]}...")

    def download_files(self):
        selected_items = self.file_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Warning", "Please select files to download.")
            return
            
        file_names = [item.text() for item in selected_items]
        if self.thread and self.thread.isRunning():
            self.progress_bar.setVisible(True)
            self.progress_label.setVisible(True)
            self.progress_bar.setValue(0)
            self.thread.set_action('download', file_names=file_names)

    def upload_files(self):
        file_paths, _ = QFileDialog.getOpenFileNames(self, "Select Files to Upload")
        if file_paths:
            dialog = UploadDialog(self, dark_mode=self.dark_mode)
            if dialog.exec_():
                is_private = dialog.is_private()
                if self.thread and self.thread.isRunning():
                    self.progress_bar.setVisible(True)
                    self.progress_label.setVisible(True)
                    self.progress_bar.setValue(0)
                    self.thread.set_action('upload', file_paths=file_paths, is_private=is_private)

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

    def closeEvent(self, event):
        if self.thread and self.thread.isRunning():
            if self.is_logged_in:
                self.thread.set_action('logout')
            else:
                self.thread.stop()
            self.thread.wait()
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