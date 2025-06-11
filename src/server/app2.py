import socket
import os
import sys
import time
import shutil
import threading
import queue
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QListWidget, QLineEdit, QLabel, QFileDialog, QMessageBox,
                             QDialog, QFormLayout, QProgressBar, QFrame, QCheckBox,
                             QTabWidget, QInputDialog, QStatusBar, QStyle)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QPalette, QColor, QFont, QIcon, QPainter, QBrush

# --- Modern Stylesheet (QSS) ---
STYLESHEET = """
QWidget {{
    font-family: 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', sans-serif;
    font-size: 10pt;
    color: {text_primary};
}}

QMainWindow, QDialog {{
    background-color: {background};
}}

QFrame#mainFrame, QFrame#dropFrame {{
    background-color: {content_bg};
    border-radius: 8px;
}}

QLabel#titleLabel {{
    font-size: 14pt;
    font-weight: bold;
}}

QPushButton {{
    background-color: {accent};
    color: #FFFFFF;
    border: none;
    padding: 10px 16px;
    border-radius: 6px;
    font-weight: 500;
}}
QPushButton:hover {{ background-color: {accent_hover}; }}
QPushButton:pressed {{ background-color: {accent_pressed}; }}
QPushButton:disabled {{
    background-color: {button_disabled};
    color: {text_disabled};
}}

QLineEdit, QListWidget {{
    background-color: {input_bg};
    border: 1px solid {border_color};
    border-radius: 6px;
    padding: 8px;
}}
QListWidget::item:selected {{
    background-color: {accent};
    color: #FFFFFF;
}}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent;
    border: none;
    padding: 8px 16px;
    color: {text_secondary};
    font-weight: 500;
}}
QTabBar::tab:selected, QTabBar::tab:hover {{
    color: {accent};
    border-bottom: 2px solid {accent};
}}

QProgressBar {{
    border: 1px solid {border_color};
    border-radius: 8px;
    text-align: center;
    background-color: {input_bg};
    height: 16px;
}}
QProgressBar::chunk {{
    background-color: {accent};
    border-radius: 7px;
}}
"""

LIGHT_THEME = {
    "background": "#F0F2F5", "content_bg": "#FFFFFF", "text_primary": "#1C1E21",
    "text_secondary": "#65676B", "text_disabled": "#BCC0C4",
    "accent": "#0866FF", "accent_hover": "#1877F2", "accent_pressed": "#3085F4",
    "button_disabled": "#E4E6EB", "input_bg": "#F0F2F5", "border_color": "#CED0D4",
}

DARK_THEME = {
    "background": "#18191A", "content_bg": "#242526", "text_primary": "#E4E6EB",
    "text_secondary": "#B0B3B8", "text_disabled": "#4E4F50",
    "accent": "#2E89FF", "accent_hover": "#4595FF", "accent_pressed": "#5DA7FF",
    "button_disabled": "#3A3B3C", "input_bg": "#3A3B3C", "border_color": "#47494A",
}


class FileTransferThread(QThread):
    update_status = pyqtSignal(str)
    update_file_list = pyqtSignal(list, list)
    error_occurred = pyqtSignal(str)
    login_status_changed = pyqtSignal(bool, str) # success, username
    transfer_progress = pyqtSignal(str, int, int)
    notification = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.client_socket = None
        self.running = False
        self.command_queue = queue.Queue()
        self.host = '127.0.0.1'
        self.port = 1253
        self.download_dir = 'downloads'
        self.is_logged_in = False
        self.enable_notifications = True

    def queue_action(self, action, **kwargs):
        kwargs['action'] = action
        self.command_queue.put(kwargs)

    def run(self):
        self.running = True
        while self.running:
            try:
                cmd = self.command_queue.get(timeout=0.1)
                action = cmd.pop('action')

                if action == 'stop':
                    if self.is_logged_in: self.handle_logout()
                    self.running = False
                    continue
                
                if not self.client_socket and action not in ['connect', 'stop']:
                    self.error_occurred.emit("Not connected. Please connect via Settings.")
                    continue

                if action == 'connect': self.connect_to_server()
                elif action == 'disconnect': self.disconnect_from_server()
                elif action == 'login': self.handle_login(**cmd)
                elif self.is_logged_in:
                    if action == 'list': self.handle_list_request()
                    elif action == 'logout': self.handle_logout()
                    elif action == 'download': self.handle_download(**cmd)
                    elif action == 'upload': self.handle_upload(**cmd)
                    elif action == 'share': self.handle_share(**cmd)
                    elif action == 'change_password': self.handle_password_change(**cmd)
                else:
                    self.error_occurred.emit("You must be logged in to perform this action.")

            except queue.Empty:
                continue
            except Exception as e:
                self.error_occurred.emit(f"Thread Error: {e}")
                self.cleanup_connection()

        self.cleanup_connection()

    def connect_to_server(self):
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.settimeout(5)
            self.client_socket.connect((self.host, self.port))
            self.client_socket.settimeout(None)
            self.update_status.emit(f"Connected to {self.host}:{self.port}")
        except Exception as e:
            self.error_occurred.emit(f"Connection error: {e}")
            self.client_socket = None

    def disconnect_from_server(self):
        if self.is_logged_in: self.handle_logout()
        self.cleanup_connection()
        self.update_status.emit("Disconnected")

    def handle_login(self, username, password):
        # SECURITY WARNING: Passwords should be hashed. Plaintext is insecure.
        try:
            self.client_socket.send(f"LOGIN:{username}:{password}".encode('utf-8'))
            response = self.client_socket.recv(1024).decode('utf-8')
            if response == "Login successful.":
                self.is_logged_in = True
                self.login_status_changed.emit(True, username)
                self.handle_list_request()
            else:
                self.error_occurred.emit(response)
                self.login_status_changed.emit(False, "")
        except (ConnectionResetError, BrokenPipeError, AttributeError) as e:
            self.error_occurred.emit(f"Connection lost: {e}")
            self.cleanup_connection()

    def handle_logout(self):
        if self.client_socket and self.is_logged_in:
            try:
                self.client_socket.send("LOGOUT:".encode('utf-8'))
                self.client_socket.recv(1024)
            except (ConnectionResetError, BrokenPipeError):
                pass
            finally:
                self.is_logged_in = False
                self.login_status_changed.emit(False, "")
    
    def handle_list_request(self):
        self.client_socket.send("LIST:".encode('utf-8'))
        data = self.client_socket.recv(8192).decode('utf-8')
        public = [f for f in data.split('|')[0].replace("PUBLIC:", "").split(',') if f]
        private = [f for f in data.split('|')[1].replace("PRIVATE:", "").split(',') if f]
        self.update_file_list.emit(public, private)

    def handle_download(self, file_names):
        if not os.path.exists(self.download_dir): os.makedirs(self.download_dir)
        for name in file_names:
            self.client_socket.send(f"DOWNLOAD:{name}".encode('utf-8'))
            resp = self.client_socket.recv(1024).decode('utf-8')
            if resp.startswith("Error:"):
                self.error_occurred.emit(f"Server error for {name}: {resp}")
                continue
            if resp.startswith("FILE_SIZE:"):
                parts, size = resp.split(':'), int(resp.split(':')[1])
                is_zip = len(parts) > 2 and parts[2] == 'ZIP'
                path = os.path.join(self.download_dir, name + ('.zip' if is_zip else ''))
                recvd = 0
                try:
                    with open(path, 'wb') as f:
                        while recvd < size:
                            chunk = self.client_socket.recv(4096)
                            if not chunk: break
                            f.write(chunk)
                            recvd += len(chunk)
                            self.transfer_progress.emit(name, recvd, size)
                    if is_zip:
                        shutil.unpack_archive(path, os.path.join(self.download_dir, name), 'zip')
                        os.remove(path)
                    if self.enable_notifications: self.notification.emit(f"Downloaded: {name}")
                except Exception as e:
                    self.error_occurred.emit(f"Download of {name} failed: {e}")

    def handle_upload(self, file_paths, is_private):
        for path in file_paths:
            is_folder, name = os.path.isdir(path), os.path.basename(path)
            src = shutil.make_archive(os.path.join(self.download_dir, name), 'zip', path) if is_folder else path
            try:
                size = os.path.getsize(src)
                self.client_socket.send(f"UPLOAD:{name}:{size}:{1 if is_private else 0}:{1 if is_folder else 0}".encode('utf-8'))
                with open(src, 'rb') as f:
                    sent = 0
                    while chunk := f.read(4096):
                        self.client_socket.sendall(chunk)
                        sent += len(chunk)
                        self.transfer_progress.emit(name, sent, size)
                resp = self.client_socket.recv(1024).decode('utf-8')
                if not resp.startswith("Error"):
                    if self.enable_notifications: self.notification.emit(f"Uploaded: {name}")
                    self.handle_list_request()
                else: self.error_occurred.emit(resp)
            except Exception as e:
                self.error_occurred.emit(f"Upload of {name} failed: {e}")
            finally:
                if is_folder: os.remove(src)

    def handle_share(self, file_name, target_user):
        self.client_socket.send(f"SHARE:{file_name}:{target_user}".encode('utf-8'))
        self.notification.emit(self.client_socket.recv(1024).decode('utf-8'))

    def handle_password_change(self, new_password):
        self.client_socket.send(f"CHANGE_PASSWORD:{new_password}".encode('utf-8'))
        self.notification.emit(self.client_socket.recv(1024).decode('utf-8'))

    def cleanup_connection(self):
        if self.client_socket:
            self.client_socket.close()
            self.client_socket = None
        if self.is_logged_in:
            self.is_logged_in = False
            self.login_status_changed.emit(False, "")


class SyncHandler(FileSystemEventHandler):
    # This class remains largely the same but would integrate with the command queue
    def __init__(self, queue): self.queue = queue
    def on_created(self, event):
        if not event.is_directory: self.queue.put(('upload', event.src_path))
    def on_modified(self, event):
        if not event.is_directory: self.queue.put(('upload', event.src_path))


class NotificationWidget(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.animation = QPropertyAnimation(self, b"windowOpacity", self)
        self.animation.setDuration(300)
        self.animation.setEasingCurve(QEasingCurve.InOutQuad)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide_notification)
        self.setMinimumSize(250, 50)
        self.setStyleSheet("background-color: rgba(0,0,0,180); color: white; border-radius: 8px; padding: 10px; font-weight: 500;")
        self.setAlignment(Qt.AlignCenter)

    def show_notification(self, message):
        self.setText(message)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.show()
        self.animation.start()
        self.timer.start(3000)

    def hide_notification(self):
        self.animation.setStartValue(1.0)
        self.animation.setEndValue(0.0)
        self.animation.finished.connect(self.hide)
        self.animation.start()


class ClientGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Modern File Client")
        self.setGeometry(100, 100, 850, 650)
        self.dark_mode = False
        self.is_logged_in = False
        self.sync_observer = None
        self.sync_queue = queue.Queue() # For folder sync
        self.host, self.port = '127.0.0.1', 1253

        self.notification_widget = NotificationWidget(self)
        
        self.init_ui()
        self.apply_theme()
        
        # Setup and start the single worker thread
        self.thread = FileTransferThread()
        self.thread.update_status.connect(self.statusBar().showMessage)
        self.thread.error_occurred.connect(lambda msg: QMessageBox.critical(self, "Error", msg))
        self.thread.login_status_changed.connect(self.handle_login_status)
        self.thread.update_file_list.connect(self.update_file_list)
        self.thread.transfer_progress.connect(self.update_progress)
        self.thread.notification.connect(self.show_notification)
        self.thread.start()

        self.setAcceptDrops(True)

    def init_ui(self):
        # Central Widget and Main Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # Top bar for controls
        top_bar = QHBoxLayout()
        self.login_btn = QPushButton("Login")
        self.login_btn.clicked.connect(self.show_login_dialog)
        self.logout_btn = QPushButton("Logout")
        self.logout_btn.clicked.connect(lambda: self.thread.queue_action('logout'))
        
        self.theme_btn = QPushButton()
        self.theme_btn.clicked.connect(self.toggle_theme)

        self.settings_btn = QPushButton()
        self.settings_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.settings_btn.clicked.connect(self.show_settings_dialog)
        
        top_bar.addWidget(QLabel("<b>FileShare</b>"))
        top_bar.addStretch()
        top_bar.addWidget(self.login_btn)
        top_bar.addWidget(self.logout_btn)
        top_bar.addWidget(self.theme_btn)
        top_bar.addWidget(self.settings_btn)
        main_layout.addLayout(top_bar)
        
        # Main content frame
        content_frame = QFrame()
        content_frame.setObjectName("mainFrame")
        content_layout = QVBoxLayout(content_frame)
        main_layout.addWidget(content_frame, 1) # Add stretch factor

        # Tabs for file lists
        tabs = QTabWidget()
        self.public_list = QListWidget()
        self.public_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.private_list = QListWidget()
        self.private_list.setSelectionMode(QListWidget.ExtendedSelection)
        tabs.addTab(self.public_list, "Public Files")
        tabs.addTab(self.private_list, "Private Files")
        content_layout.addWidget(tabs)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setVisible(False)
        content_layout.addWidget(self.progress_bar)
        
        # Bottom action bar
        action_bar = QHBoxLayout()
        self.private_upload_check = QCheckBox("Upload as Private")
        self.upload_btn = QPushButton("Upload")
        self.upload_btn.setIcon(self.style().standardIcon(QStyle.SP_ArrowUp))
        self.upload_btn.clicked.connect(self.upload_files)
        self.download_btn = QPushButton("Download")
        self.download_btn.setIcon(self.style().standardIcon(QStyle.SP_ArrowDown))
        self.download_btn.clicked.connect(self.download_files)
        self.refresh_btn = QPushButton()
        self.refresh_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.refresh_btn.clicked.connect(lambda: self.thread.queue_action('list'))
        self.share_btn = QPushButton("Share")
        self.share_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogYesButton))
        self.share_btn.clicked.connect(self.share_file)
        
        action_bar.addWidget(self.private_upload_check)
        action_bar.addStretch()
        action_bar.addWidget(self.upload_btn)
        action_bar.addWidget(self.download_btn)
        action_bar.addWidget(self.refresh_btn)
        action_bar.addWidget(self.share_btn)
        content_layout.addLayout(action_bar)

        self.setStatusBar(QStatusBar())
        self.handle_login_status(False, "") # Initial UI state

    def apply_theme(self):
        theme = DARK_THEME if self.dark_mode else LIGHT_THEME
        self.setStyleSheet(STYLESHEET.format(**theme))
        self.theme_btn.setIcon(self.style().standardIcon(QStyle.SP_DesktopIcon if self.dark_mode else QStyle.SP_ComputerIcon))

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self.apply_theme()

    def handle_login_status(self, success, username):
        self.is_logged_in = success
        self.login_btn.setVisible(not success)
        self.logout_btn.setVisible(success)
        
        # Enable/disable all action buttons
        for btn in [self.upload_btn, self.download_btn, self.refresh_btn, self.share_btn, self.settings_btn]:
            btn.setEnabled(success)

        if success:
            self.statusBar().showMessage(f"Logged in as: {username}", 5000)
        else:
            self.statusBar().showMessage("Logged out. Please log in to begin.")
            self.public_list.clear()
            self.private_list.clear()

    def show_login_dialog(self):
        # Implementation of a login dialog would go here
        # For simplicity, using QInputDialog
        username, ok1 = QInputDialog.getText(self, "Login", "Username:")
        if ok1 and username:
            password, ok2 = QInputDialog.getText(self, "Login", "Password:", QLineEdit.Password)
            if ok2 and password:
                self.thread.queue_action('login', username=username, password=password)

    def show_settings_dialog(self):
        # A proper QDialog should be used here. This is a simplified example.
        host, ok1 = QInputDialog.getText(self, "Settings", "Host:", text=self.host)
        if ok1:
            port, ok2 = QInputDialog.getText(self, "Settings", "Port:", text=str(self.port))
            if ok2:
                self.host, self.port = host, int(port)
                self.thread.host, self.thread.port = self.host, self.port
                self.statusBar().showMessage(f"Settings updated. Now using {self.host}:{self.port}. Reconnecting...")
                self.thread.queue_action('connect')
                
    def update_file_list(self, public_files, private_files):
        self.public_list.clear()
        self.private_list.clear()
        if public_files: self.public_list.addItems(public_files)
        else: self.public_list.addItem("No public files.")
        if private_files: self.private_list.addItems(private_files)
        else: self.private_list.addItem("No private files.")
        
    def download_files(self):
        selected_public = [item.text() for item in self.public_list.selectedItems()]
        selected_private = [item.text() for item in self.private_list.selectedItems()]
        files_to_download = selected_public + selected_private
        if files_to_download:
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            self.thread.queue_action('download', file_names=files_to_download)
        else:
            self.show_notification("Please select files to download.")

    def upload_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select Files/Folders to Upload", "", "All Files (*)")
        if paths:
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            self.thread.queue_action('upload', file_paths=paths, is_private=self.private_upload_check.isChecked())
            
    def share_file(self):
        selected = self.private_list.selectedItems()
        if not selected:
            self.show_notification("Select a private file to share.")
            return
        file_name = selected[0].text()
        user, ok = QInputDialog.getText(self, "Share File", f"Share '{file_name}' with user:")
        if ok and user:
            self.thread.queue_action('share', file_name=file_name, target_user=user)

    def update_progress(self, filename, current, total):
        if total > 0:
            progress = int((current / total) * 100)
            self.progress_bar.setFormat(f"{filename}: {progress}%")
            self.progress_bar.setValue(progress)
            if progress >= 100:
                QTimer.singleShot(1000, lambda: self.progress_bar.setVisible(False))
                
    def show_notification(self, message):
        self.notification_widget.show_notification(message)
        # Position it at the bottom-center of the main window
        pos = self.mapToGlobal(self.rect().bottomLeft())
        x = pos.x() + (self.width() - self.notification_widget.width()) / 2
        y = pos.y() - self.notification_widget.height() - 15 # 15px margin
        self.notification_widget.move(int(x), int(y))

    def dragEnterEvent(self, event):
        if self.is_logged_in and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        if paths:
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            self.thread.queue_action('upload', file_paths=paths, is_private=self.private_upload_check.isChecked())

    def closeEvent(self, event):
        self.thread.queue_action('stop') # Signal thread to stop
        self.thread.wait(2000) # Wait up to 2 seconds for clean shutdown
        if self.sync_observer:
            self.sync_observer.stop()
            self.sync_observer.join()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    client = ClientGUI()
    client.show()
    sys.exit(app.exec_())