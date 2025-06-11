import sys
import os
import threading
import socket
import sqlite3
import shutil
from datetime import datetime, timedelta
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                            QPushButton, QListWidget, QTextEdit, QLabel, QTabWidget, QFrame,
                            QAction, QMenuBar, QDialog, QFormLayout, QLineEdit, QComboBox,
                            QMessageBox, QInputDialog)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPalette, QColor, QFont

def adapt_datetime(dt):
    return dt.isoformat()
sqlite3.register_adapter(datetime, adapt_datetime)

def parse_datetime(s):
    return datetime.fromisoformat(s)
sqlite3.register_converter("DATETIME", parse_datetime)

SERVER_FILES_DIR = 'server_files'
os.makedirs(SERVER_FILES_DIR, exist_ok=True)

def init_db():
    with sqlite3.connect('file_transfer.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS downloads
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      file_name TEXT NOT NULL,
                      client_address TEXT,
                      timestamp DATETIME NOT NULL,
                      user_id TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS files
                     (file_name TEXT PRIMARY KEY,
                      upload_date DATETIME NOT NULL,
                      user_id TEXT,
                      is_private INTEGER DEFAULT 0,
                      size INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (username TEXT PRIMARY KEY,
                      password TEXT NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS file_shares
                     (file_name TEXT,
                      shared_with_user TEXT,
                      PRIMARY KEY (file_name, shared_with_user),
                      FOREIGN KEY (file_name) REFERENCES files(file_name))''')
        conn.commit()

class ServerThread(QThread):
    log_message = pyqtSignal(str)
    file_list_updated = pyqtSignal(list)
    stats_updated = pyqtSignal(dict)
    user_list_updated = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.server_socket = None
        self.running = False
        self.host = socket.gethostname()
        self.port = 1253
        self.active_connections = 0
        init_db()

    def list_server_files(self, user_id):
        try:
            with sqlite3.connect('file_transfer.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT file_name FROM files 
                    WHERE is_private = 0 OR user_id = ? 
                    OR file_name IN (SELECT file_name FROM file_shares WHERE shared_with_user = ?)
                """, (user_id, user_id))
                files = [row[0] for row in cursor.fetchall()]
            return files
        except Exception as e:
            self.log_message.emit(f"Error listing files: {str(e)}")
            return []

    def get_public_and_private_files(self, user_id):
        try:
            with sqlite3.connect('file_transfer.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT file_name FROM files WHERE is_private = 0")
                public_files = [row[0] for row in cursor.fetchall()]
                cursor.execute("""
                    SELECT file_name FROM files WHERE is_private = 1 AND user_id = ?
                    UNION
                    SELECT file_name FROM file_shares WHERE shared_with_user = ?
                """, (user_id, user_id))
                private_files = [row[0] for row in cursor.fetchall()]
            return public_files, private_files
        except Exception as e:
            self.log_message.emit(f"Error listing files: {str(e)}")
            return [], []

    def search_files(self, user_id, query):
        try:
            with sqlite3.connect('file_transfer.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT file_name FROM files 
                    WHERE (is_private = 0 OR user_id = ? OR file_name IN (SELECT file_name FROM file_shares WHERE shared_with_user = ?))
                    AND file_name LIKE ?
                """, (user_id, user_id, f"%{query}%"))
                files = [row[0] for row in cursor.fetchall()]
                public_files = [f for f in files if not self.is_private_file(f, user_id)]
                private_files = [f for f in files if self.is_private_file(f, user_id)]
            return public_files, private_files
        except Exception as e:
            self.log_message.emit(f"Error searching files: {str(e)}")
            return [], []

    def is_private_file(self, file_name, user_id):
        try:
            with sqlite3.connect('file_transfer.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT is_private, user_id FROM files WHERE file_name = ?", (file_name,))
                result = cursor.fetchone()
                if result:
                    is_private, owner = result
                    return is_private == 1 and owner == user_id
                return False
        except Exception as e:
            self.log_message.emit(f"Error checking file privacy: {str(e)}")
            return False

    def get_stats(self, timeframe='month'):
        stats = {
            'downloads': 0,
            'total_days_with_downloads': 0,
            'total_files': 0,
            'total_storage_gb': 0.0,
            'files_per_user': {},
            'downloads_per_user': {},
            'active_connections': self.active_connections
        }
        
        try:
            with sqlite3.connect('file_transfer.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                cursor = conn.cursor()
                
                if timeframe == 'day':
                    start_date = datetime.now() - timedelta(days=1)
                elif timeframe == 'week':
                    start_date = datetime.now() - timedelta(days=7)
                elif timeframe == 'year':
                    start_date = datetime.now() - timedelta(days=365)
                else:  # month
                    start_date = datetime.now() - timedelta(days=30)
                
                cursor.execute("SELECT COUNT(*) FROM downloads WHERE timestamp >= ?", (start_date,))
                stats['downloads'] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(DISTINCT DATE(timestamp)) FROM downloads")
                stats['total_days_with_downloads'] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*), SUM(size) FROM files")
                result = cursor.fetchone()
                stats['total_files'] = result[0] or 0
                stats['total_storage_gb'] = (result[1] or 0) / (1024**3)
                
                cursor.execute("SELECT user_id, COUNT(*) FROM files GROUP BY user_id")
                stats['files_per_user'] = dict(cursor.fetchall() or [])
                
                cursor.execute("SELECT user_id, COUNT(*) FROM downloads WHERE timestamp >= ? GROUP BY user_id", (start_date,))
                stats['downloads_per_user'] = dict(cursor.fetchall() or [])
                
        except sqlite3.Error as e:
            self.log_message.emit(f"Database error getting stats: {str(e)}")
            
        return stats

    def get_users(self):
        try:
            with sqlite3.connect('file_transfer.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT username FROM users")
                users = [row[0] for row in cursor.fetchall()]
            return users
        except Exception as e:
            self.log_message.emit(f"Error listing users: {str(e)}")
            return []

    def send_file_to_client(self, client_socket, file_name, client_address, user_id, offset=0):
        file_path = os.path.join(SERVER_FILES_DIR, file_name)
        
        if not os.path.exists(file_path):
            client_socket.send(f"Error: File '{file_name}' not found.".encode('utf-8'))
            return
            
        try:
            with sqlite3.connect('file_transfer.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT is_private, user_id FROM files WHERE file_name = ?
                """, (file_name,))
                result = cursor.fetchone()
                
                has_access = False
                if result:
                    if result[0] == 0:  # Public file
                        has_access = True
                    elif result[1] == user_id:  # Owner
                        has_access = True
                    else:  # Check shares
                        cursor.execute("SELECT 1 FROM file_shares WHERE file_name = ? AND shared_with_user = ?", 
                                     (file_name, user_id))
                        if cursor.fetchone():
                            has_access = True
                
                if has_access:
                    if os.path.isdir(file_path):
                        zip_path = file_path + '.zip'
                        shutil.make_archive(file_path, 'zip', file_path)
                        file_size = os.path.getsize(zip_path)
                        client_socket.send(f"FILE_SIZE:{file_size}:ZIP".encode('utf-8'))
                        
                        with open(zip_path, 'rb') as f:
                            f.seek(offset)
                            while True:
                                data = f.read(1024)
                                if not data:
                                    break
                                client_socket.sendall(data)
                        os.remove(zip_path)
                    else:
                        file_size = os.path.getsize(file_path)
                        client_socket.send(f"FILE_SIZE:{file_size}".encode('utf-8'))
                        
                        with open(file_path, 'rb') as f:
                            f.seek(offset)
                            while True:
                                data = f.read(1024)
                                if not data:
                                    break
                                client_socket.sendall(data)
                    
                    self.log_message.emit(f"Sent '{file_name}' to {client_address}")
                    
                    conn.execute("INSERT INTO downloads (file_name, client_address, timestamp, user_id) VALUES (?, ?, ?, ?)",
                               (file_name, str(client_address), datetime.now(), user_id))
                    
                    self.stats_updated.emit(self.get_stats())
                else:
                    client_socket.send(f"Error: Access denied for file '{file_name}'".encode('utf-8'))
                    
        except Exception as e:
            self.log_message.emit(f"Error sending file '{file_name}': {str(e)}")
            try:
                client_socket.send(f"Error: {str(e)}".encode('utf-8'))
            except:
                pass

    def receive_file_from_client(self, client_socket, file_name, file_size, client_address, user_id, is_private, is_folder):
        file_path = os.path.join(SERVER_FILES_DIR, file_name)
        
        try:
            if is_folder:
                zip_path = file_path + '.zip'
                received_size = 0
                with open(zip_path, 'wb') as f:
                    while received_size < file_size:
                        data = client_socket.recv(1024)
                        if not data:
                            break
                        f.write(data)
                        received_size += len(data)
                
                if received_size == file_size:
                    os.makedirs(file_path, exist_ok=True)
                    shutil.unpack_archive(zip_path, file_path, 'zip')
                    os.remove(zip_path)
                    for root, _, files in os.walk(file_path):
                        for fname in files:
                            rel_path = os.path.relpath(os.path.join(root, fname), SERVER_FILES_DIR)
                            with sqlite3.connect('file_transfer.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                                conn.execute("INSERT OR REPLACE INTO files (file_name, upload_date, user_id, is_private, size) VALUES (?, ?, ?, ?, ?)",
                                           (rel_path, datetime.now(), user_id, is_private, os.path.getsize(os.path.join(root, fname))))
                else:
                    raise Exception("Incomplete folder transfer")
            else:
                received_size = 0
                with open(file_path, 'wb') as f:
                    while received_size < file_size:
                        data = client_socket.recv(1024)
                        if not data:
                            break
                        f.write(data)
                        received_size += len(data)
                
                if received_size != file_size:
                    raise Exception("Incomplete file transfer")
            
            client_socket.send(f"File '{file_name}' uploaded successfully.".encode('utf-8'))
            self.log_message.emit(f"Received '{file_name}' from {client_address}")
            
            if not is_folder:
                with sqlite3.connect('file_transfer.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                    conn.execute("INSERT OR REPLACE INTO files (file_name, upload_date, user_id, is_private, size) VALUES (?, ?, ?, ?, ?)",
                               (file_name, datetime.now(), user_id, is_private, file_size))
            
            self.file_list_updated.emit(self.list_server_files(user_id))
            self.stats_updated.emit(self.get_stats())
                
        except Exception as e:
            self.log_message.emit(f"Error receiving file '{file_name}': {str(e)}")
            if os.path.exists(file_path):
                if os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                else:
                    os.remove(file_path)
            try:
                client_socket.send(f"Error: {str(e)}".encode('utf-8'))
            except:
                pass

    def handle_client_connection(self, client_socket, client_address):
        self.active_connections += 1
        self.log_message.emit(f"[ACTIVE CONNECTIONS] {self.active_connections}")
        self.log_message.emit(f"New connection from {client_address}")
        
        user_id = None
        
        try:
            while self.running:
                try:
                    data = client_socket.recv(1024).decode('utf-8', errors='ignore')
                    if not data:
                        break
                        
                    self.log_message.emit(f"Received from {client_address}: {data[:100]}...")
                    
                    if data.startswith("LOGIN:"):
                        user_id = self.handle_login(client_socket, data[6:], client_address)
                    elif data.startswith("LOGOUT:"):
                        user_id = self.handle_logout(client_socket, client_address)
                    elif data.startswith("LIST:"):
                        self.handle_list_request(client_socket, user_id)
                    elif data.startswith("DOWNLOAD:"):
                        self.handle_download(client_socket, data[9:], client_address, user_id)
                    elif data.startswith("DOWNLOAD_RESUME:"):
                        self.handle_download_resume(client_socket, data[15:], client_address, user_id)
                    elif data.startswith("UPLOAD:"):
                        self.handle_upload(client_socket, data[7:], client_address, user_id)
                    elif data.startswith("SHARE:"):
                        self.handle_share(client_socket, data[6:], user_id)
                    elif data.startswith("CHANGE_PASSWORD:"):
                        self.handle_password_change(client_socket, data[15:], user_id)
                    elif data.startswith("DELETE_ACCOUNT:"):
                        self.handle_delete_account(client_socket, data[14:], client_address)
                    elif data.startswith("SEARCH:"):
                        self.handle_search(client_socket, data[7:], user_id)
                    elif data.startswith("DELETE_FILE:"):
                        self.handle_delete_file(client_socket, data[12:], user_id)
                    else:
                        client_socket.send(f"Unknown command: {data[:100]}".encode('utf-8'))
                        
                except ConnectionResetError:
                    self.log_message.emit(f"Connection reset by {client_address}")
                    break
                except Exception as e:
                    self.log_message.emit(f"Error with {client_address}: {str(e)}")
                    try:
                        client_socket.send(f"Error: {str(e)}".encode('utf-8'))
                    except:
                        break
                        
        finally:
            client_socket.close()
            self.active_connections -= 1
            self.log_message.emit(f"Connection closed with {client_address}")
            self.log_message.emit(f"[ACTIVE CONNECTIONS] {self.active_connections}")

    def handle_login(self, client_socket, data, client_address):
        parts = data.split(':')
        if len(parts) != 2:
            client_socket.send("Error: Invalid format. Use 'username:password'".encode('utf-8'))
            return None
            
        username, password = parts
        user_id = None
        
        try:
            with sqlite3.connect('file_transfer.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT password FROM users WHERE username = ?", (username,))
                result = cursor.fetchone()
                
            if result and result[0] == password:
                user_id = username
                client_socket.send("Login successful.".encode('utf-8'))
                self.log_message.emit(f"User '{username}' logged in from {client_address}")
                
                public_files, private_files = self.get_public_and_private_files(user_id)
                response = f"PUBLIC:{','.join(public_files)}|PRIVATE:{','.join(private_files)}"
                client_socket.sendall(response.encode('utf-8'))
            else:
                client_socket.send("Error: Invalid username or password.".encode('utf-8'))
                
        except Exception as e:
            client_socket.send(f"Error: {str(e)}".encode('utf-8'))
            
        return user_id

    def handle_logout(self, client_socket, client_address):
        client_socket.send("Logout successful.".encode('utf-8'))
        self.log_message.emit(f"User logged out from {client_address}")
        return None

    def handle_list_request(self, client_socket, user_id):
        if not user_id:
            client_socket.send("Error: Authentication required.".encode('utf-8'))
            return
        public_files, private_files = self.get_public_and_private_files(user_id)
        response = f"PUBLIC:{','.join(public_files)}|PRIVATE:{','.join(private_files)}"
        client_socket.sendall(response.encode('utf-8'))

    def handle_download(self, client_socket, data, client_address, user_id):
        if not user_id:
            client_socket.send("Error: Authentication required.".encode('utf-8'))
            return
            
        file_name = data.strip()
        self.send_file_to_client(client_socket, file_name, client_address, user_id)

    def handle_download_resume(self, client_socket, data, client_address, user_id):
        if not user_id:
            client_socket.send("Error: Authentication required.".encode('utf-8'))
            return
            
        parts = data.split(':')
        if len(parts) != 2:
            client_socket.send("Error: Invalid format. Use 'filename:offset'".encode('utf-8'))
            return
            
        file_name, offset = parts
        offset = int(offset)
        self.send_file_to_client(client_socket, file_name, client_address, user_id, offset)

    def handle_upload(self, client_socket, data, client_address, user_id):
        if not user_id:
            client_socket.send("Error: Authentication required.".encode('utf-8'))
            return
            
        parts = data.split(':')
        if len(parts) != 4:
            client_socket.send("Error: Invalid format. Use 'filename:size:is_private:is_folder'".encode('utf-8'))
            return
            
        file_name = parts[0].strip()
        try:
            file_size = int(parts[1].strip())
            is_private = int(parts[2].strip())
            is_folder = int(parts[3].strip())
        except ValueError:
            client_socket.send("Error: Invalid file size, privacy, or folder setting.".encode('utf-8'))
            return
            
        self.receive_file_from_client(client_socket, file_name, file_size, client_address, user_id, is_private, is_folder)
        
        public_files, private_files = self.get_public_and_private_files(user_id)
        response = f"PUBLIC:{','.join(public_files)}|PRIVATE:{','.join(private_files)}"
        client_socket.sendall(response.encode('utf-8'))

    def handle_share(self, client_socket, data, user_id):
        if not user_id:
            client_socket.send("Error: Authentication required.".encode('utf-8'))
            return
            
        parts = data.split(':')
        if len(parts) != 2:
            client_socket.send("Error: Invalid format. Use 'file_name:target_user'".encode('utf-8'))
            return
            
        file_name, target_user = parts
        
        try:
            with sqlite3.connect('file_transfer.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id FROM files WHERE file_name = ? AND is_private = 1", (file_name,))
                if cursor.fetchone()[0] != user_id:
                    client_socket.send("Error: You can only share your private files.".encode('utf-8'))
                    return
                    
                cursor.execute("SELECT 1 FROM users WHERE username = ?", (target_user,))
                if not cursor.fetchone():
                    client_socket.send("Error: Target user does not exist.".encode('utf-8'))
                    return
                    
                conn.execute("INSERT INTO file_shares (file_name, shared_with_user) VALUES (?, ?)",
                           (file_name, target_user))
                client_socket.send(f"File '{file_name}' shared with '{target_user}'.".encode('utf-8'))
                self.log_message.emit(f"User '{user_id}' shared '{file_name}' with '{target_user}'")
        except sqlite3.IntegrityError:
            client_socket.send("Error: File already shared with this user.".encode('utf-8'))
        except Exception as e:
            client_socket.send(f"Error: {str(e)}".encode('utf-8'))

    def handle_password_change(self, client_socket, data, user_id):
        if not user_id:
            client_socket.send("Error: Authentication required.".encode('utf-8'))
            return
            
        new_password = data.strip()
        try:
            with sqlite3.connect('file_transfer.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                conn.execute("UPDATE users SET password = ? WHERE username = ?", (new_password, user_id))
                conn.commit()
                client_socket.send("Password updated successfully.".encode('utf-8'))
                self.log_message.emit(f"User '{user_id}' updated password")
        except Exception as e:
            client_socket.send(f"Error: {str(e)}".encode('utf-8'))

    def handle_delete_account(self, client_socket, data, client_address):
        if not data:
            client_socket.send("Error: Username required.".encode('utf-8'))
            return
            
        username = data.strip()
        try:
            with sqlite3.connect('file_transfer.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM users WHERE username = ?", (username,))
                if not cursor.fetchone():
                    client_socket.send("Error: User does not exist.".encode('utf-8'))
                    return
                
                conn.execute("DELETE FROM file_shares WHERE file_name IN (SELECT file_name FROM files WHERE user_id = ?)", (username,))
                conn.execute("DELETE FROM files WHERE user_id = ?", (username,))
                conn.execute("DELETE FROM downloads WHERE user_id = ?", (username,))
                conn.execute("DELETE FROM users WHERE username = ?", (username,))
                conn.commit()
                
                client_socket.send("Account deleted successfully.".encode('utf-8'))
                self.log_message.emit(f"User '{username}' deleted account from {client_address}")
                self.user_list_updated.emit(self.get_users())
        except Exception as e:
            client_socket.send(f"Error: {str(e)}".encode('utf-8'))
            self.log_message.emit(f"Error deleting account '{username}': {str(e)}")

    def handle_search(self, client_socket, data, user_id):
        if not user_id:
            client_socket.send("Error: Authentication required.".encode('utf-8'))
            return
        query = data.strip()
        public_files, private_files = self.search_files(user_id, query)
        response = f"PUBLIC:{','.join(public_files)}|PRIVATE:{','.join(private_files)}"
        client_socket.sendall(response.encode('utf-8'))

    def handle_delete_file(self, client_socket, data, user_id):
        if not user_id:
            client_socket.send("Error: Authentication required.".encode('utf-8'))
            return
            
        file_name = data.strip()
        try:
            with sqlite3.connect('file_transfer.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id FROM files WHERE file_name = ?", (file_name,))
                result = cursor.fetchone()
                if not result or result[0] != user_id:
                    client_socket.send(f"Error: You can only delete files you uploaded ('{file_name}').".encode('utf-8'))
                    return
                
                file_path = os.path.join(SERVER_FILES_DIR, file_name)
                if os.path.exists(file_path):
                    if os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                    else:
                        os.remove(file_path)
                
                conn.execute("DELETE FROM files WHERE file_name = ?", (file_name,))
                conn.execute("DELETE FROM file_shares WHERE file_name = ?", (file_name,))
                conn.commit()
                
                client_socket.send(f"File '{file_name}' deleted successfully.".encode('utf-8'))
                self.log_message.emit(f"User '{user_id}' deleted file '{file_name}'")
                self.file_list_updated.emit(self.list_server_files(user_id))
        except Exception as e:
            client_socket.send(f"Error: {str(e)}".encode('utf-8'))
            self.log_message.emit(f"Error deleting file '{file_name}': {str(e)}")

    def run(self):
        if os.geteuid() == 0:
            self.log_message.emit("Warning: Running as root is not recommended. Consider running as a regular user to avoid GUI issues.")
        
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.running = True
            self.log_message.emit(f"Server started on {self.host}:{self.port}")
            self.file_list_updated.emit(self.list_server_files(None))
            self.stats_updated.emit(self.get_stats())
            self.user_list_updated.emit(self.get_users())
            
            while self.running:
                try:
                    self.server_socket.settimeout(1)
                    client_socket, client_address = self.server_socket.accept()
                    threading.Thread(
                        target=self.handle_client_connection,
                        args=(client_socket, client_address),
                        daemon=True
                    ).start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        self.log_message.emit(f"Server accept error: {str(e)}")
                        
        except Exception as e:
            self.log_message.emit(f"Server error: {str(e)}")
        finally:
            self.stop()

    def stop(self):
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        self.log_message.emit("Server stopped.")

class UserDialog(QDialog):
    def __init__(self, parent=None, dark_mode=False):
        super().__init__(parent)
        self.dark_mode = dark_mode
        self.setWindowTitle("Manage User")
        self.init_ui()
        self.apply_theme()

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

class ServerGUI(QMainWindow):
    stats_updated = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("File Transfer Server")
        self.setGeometry(100, 100, 900, 600)
        self.server_thread = None
        self.dark_mode = True
        self.init_ui()
        self.apply_theme()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Control buttons
        control_frame = QFrame()
        control_frame.setFrameShape(QFrame.StyledPanel)
        control_layout = QHBoxLayout(control_frame)
        control_layout.setContentsMargins(10, 10, 10, 10)
        
        self.start_btn = QPushButton("Start Server")
        self.start_btn.clicked.connect(self.start_server)
        self.start_btn.setFixedHeight(40)
        
        self.stop_btn = QPushButton("Stop Server")
        self.stop_btn.clicked.connect(self.stop_server)
        self.stop_btn.setFixedHeight(40)
        self.stop_btn.setEnabled(False)
        
        self.theme_btn = QPushButton("Light Mode")
        self.theme_btn.clicked.connect(self.toggle_theme)
        self.theme_btn.setFixedHeight(40)
        
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        control_layout.addWidget(self.theme_btn)
        layout.addWidget(control_frame)

        # Tabs
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # Files Tab
        files_tab = QWidget()
        files_layout = QVBoxLayout(files_tab)
        files_layout.setContentsMargins(10, 10, 10, 10)
        
        files_label = QLabel("Server Files:")
        files_label.setStyleSheet("font-weight: bold;")
        
        self.file_list = QListWidget()
        self.file_list.itemSelectionChanged.connect(lambda: self.highlight_button(self.file_list))
        
        files_layout.addWidget(files_label)
        files_layout.addWidget(self.file_list)
        tabs.addTab(files_tab, "Files")

        # Statistics Tab
        stats_tab = QWidget()
        stats_layout = QVBoxLayout(stats_tab)
        stats_layout.setContentsMargins(10, 10, 10, 10)
        
        stats_label = QLabel("Statistics:")
        stats_label.setStyleSheet("font-weight: bold;")
        
        timeframe_layout = QHBoxLayout()
        timeframe_label = QLabel("Timeframe:")
        self.timeframe_combo = QComboBox()
        self.timeframe_combo.addItems(["Day", "Week", "Month", "Year"])
        self.timeframe_combo.currentTextChanged.connect(self.update_stats_timeframe)
        timeframe_layout.addWidget(timeframe_label)
        timeframe_layout.addWidget(self.timeframe_combo)
        timeframe_layout.addStretch()
        
        self.stats_display = QTextEdit()
        self.stats_display.setReadOnly(True)
        
        stats_layout.addWidget(stats_label)
        stats_layout.addLayout(timeframe_layout)
        stats_layout.addWidget(self.stats_display)
        tabs.addTab(stats_tab, "Statistics")

        # User Management Tab
        users_tab = QWidget()
        users_layout = QVBoxLayout(users_tab)
        users_layout.setContentsMargins(10, 10, 10, 10)
        
        users_label = QLabel("Users:")
        users_label.setStyleSheet("font-weight: bold;")
        
        user_btn_layout = QHBoxLayout()
        add_user_btn = QPushButton("Add User")
        add_user_btn.clicked.connect(self.add_user)
        delete_user_btn = QPushButton("Delete User")
        delete_user_btn.clicked.connect(self.delete_user)
        user_btn_layout.addWidget(add_user_btn)
        user_btn_layout.addWidget(delete_user_btn)
        
        self.user_list = QListWidget()
        self.user_list.itemSelectionChanged.connect(lambda: self.highlight_button(self.user_list))
        
        users_layout.addWidget(users_label)
        users_layout.addLayout(user_btn_layout)
        users_layout.addWidget(self.user_list)
        tabs.addTab(users_tab, "Users")

        # Log Display
        log_frame = QFrame()
        log_frame.setFrameShape(QFrame.StyledPanel)
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(10, 10, 10, 15)
        
        log_label = QLabel("Server Logs:")
        log_label.setStyleSheet("font-weight: bold;")
        
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        
        log_layout.addWidget(log_label)
        log_layout.addWidget(self.log_display)
        layout.addWidget(log_frame)

    def apply_theme(self):
        palette = QPalette()
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

    def highlight_button(self, list_widget):
        for btn in [self.start_btn, self.stop_btn, self.theme_btn]:
            btn.setChecked(False)
        if list_widget.selectedItems():
            btn = self.sender()
            if btn:
                btn.setChecked(True)

    def start_server(self):
        if not self.server_thread or not self.server_thread.isRunning():
            self.server_thread = ServerThread()
            self.server_thread.log_message.connect(self.append_log)
            self.server_thread.file_list_updated.connect(self.update_file_list)
            self.server_thread.stats_updated.connect(self.update_stats)
            self.server_thread.user_list_updated.connect(self.update_user_list)
            self.server_thread.start()
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)

    def stop_server(self):
        if self.server_thread and self.server_thread.isRunning():
            self.server_thread.stop()
            self.server_thread.wait()
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.file_list.clear()
            self.stats_display.clear()
            self.user_list.clear()

    def update_file_list(self, files):
        self.file_list.clear()
        self.file_list.addItems(files)

    def update_stats_timeframe(self, timeframe):
        if self.server_thread and self.server_thread.isRunning():
            stats = self.server_thread.get_stats(timeframe.lower())
            self.update_stats(stats)

    def update_stats(self, stats):
        text = (
            f"Downloads (last {self.timeframe_combo.currentText().lower()}): {stats['downloads']}\n"
            f"Total Days with Downloads: {stats['total_days_with_downloads']}\n"
            f"Total Files: {stats['total_files']}\n"
            f"Total Storage: {stats['total_storage_gb']:.2f} GB\n"
            f"Files per User: {stats['files_per_user']}\n"
            f"Downloads per User: {stats['downloads_per_user']}\n"
            f"Active Connections: {stats['active_connections']}"
        )
        self.stats_display.setText(text)

    def update_user_list(self, users):
        self.user_list.clear()
        self.user_list.addItems(users)

    def add_user(self):
        dialog = UserDialog(self, dark_mode=self.dark_mode)
        if dialog.exec_():
            username, password = dialog.get_credentials()
            if username and password:
                try:
                    if self.server_thread and self.server_thread.isRunning():
                        with sqlite3.connect('file_transfer.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                            conn.execute("INSERT INTO users (username, password) VALUES (?, ?)",
                                       (username, password))
                        self.server_thread.user_list_updated.emit(self.server_thread.get_users())
                        self.append_log(f"Added user '{username}'")
                    else:
                        raise Exception("Server not running")
                except sqlite3.IntegrityError:
                    QMessageBox.critical(self, "Error", "Username already exists.")
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to add user: {str(e)}")

    def delete_user(self):
        selected = self.user_list.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Warning", "Please select a user to delete.")
            return
        username = selected[0].text()
        reply = QMessageBox.question(self, "Confirm", f"Delete user '{username}'?",
                                   QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                if self.server_thread and self.server_thread.isRunning():
                    with sqlite3.connect('file_transfer.db', detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                        conn.execute("DELETE FROM users WHERE username = ?", (username,))
                        conn.execute("DELETE FROM file_shares WHERE file_name IN (SELECT file_name FROM files WHERE user_id = ?)", (username,))
                        conn.execute("DELETE FROM files WHERE user_id = ?", (username,))
                        conn.execute("DELETE FROM downloads WHERE user_id = ?", (username,))
                        conn.commit()
                    self.server_thread.user_list_updated.emit(self.server_thread.get_users())
                    self.append_log(f"Deleted user '{username}'")
                else:
                    raise Exception("Server not running")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete user: {str(e)}")

    def append_log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_display.append(f"[{timestamp}] {message}")

    def closeEvent(self, event):
        if self.server_thread and self.server_thread.isRunning():
            self.server_thread.stop()
            self.server_thread.wait()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    font = QFont()
    font.setFamily("Segoe UI" if sys.platform == "win32" else "Arial")
    font.setPointSize(10)
    app.setFont(font)
    
    window = ServerGUI()
    window.show()
    sys.exit(app.exec_())