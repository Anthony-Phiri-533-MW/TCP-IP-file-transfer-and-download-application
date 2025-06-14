# File Transfer Application

## Overview

The File Transfer Application is a client-server system for secure file sharing, built with Python and PyQt5. It allows users to upload, download, share, and manage files with support for public and private access, folder synchronization, and a user-friendly GUI. The server manages file storage and user accounts using a SQLite database, while the client provides an intuitive interface for file operations.

---

## Features

### Client Features

- Login with username and password  
- Upload/download files and folders  
- Public and private file sharing  
- Search files by name  
- Folder synchronization for automatic uploads  
- Drag-and-drop file uploads  
- Pause downloads (resume not supported)  
- Settings for:
  - Dark/light theme  
  - Notifications  
  - Password changes  
  - Display name updates  
- Real-time transfer progress and speed display

### Server Features

- Manage user accounts (add/delete)  
- Monitor server files and statistics (downloads, storage, etc.)  
- Real-time logging of server activities  
- Support for multiple concurrent client connections

---

## Requirements

- **Python**: 3.8+  
- **Dependencies**: `PyQt5`, `watchdog`, `tqdm`  
- **Operating Systems**: Windows, macOS, or Linux  
- **Network**: Local or internet connection

---

## Installation

1. **Install Python**  
   Download and install Python 3.8+ from [python.org](https://www.python.org/).

2. **Install Dependencies**  
   ```bash
   pip install PyQt5 watchdog tqdm
   ```

3. **Download the Project**  
   Clone or download the repository containing `client.py` and `server.py`.

4. **Directory Setup**  
   Ensure `client.py` and `server.py` are in a dedicated project folder.  
   The server will create:
   - `server_files/` directory for file storage  
   - `file_transfer.db` SQLite database on first run

---

## Usage

### Running the Server

```bash
python server.py
```

- In the Server GUI:
  - Click **Start Server** to listen on `0.0.0.0:1253`  
  - Use the **Users** tab to add users (username, password, optional display name)  
  - Monitor files, statistics, and logs via their respective tabs  
  - Click **Stop Server** to shut down

### Running the Client

```bash
python client.py
```

- On the login screen, enter:
  - **Server IP** (e.g., `127.0.0.1` for local)  
  - **Port** (default: `1253`)  
  - **Username** and **password** (provided by the server admin)  
- Click **Login** to access the main interface

- Use the interface to:
  - Upload files/folders (drag-and-drop or **Upload Files/Folders** button)  
  - Download selected files  
  - Share private files with other users  
  - Delete files you uploaded  
  - Search files  
  - Configure settings (theme, sync folder, notifications, etc.)  
- Click **Logout** to exit

---

## Project Structure

```
project-folder/
├── client.py                # Client application GUI
├── server.py                # Server application GUI
├── server_files/            # Server-side file storage (auto-created)
├── file_transfer.db         # SQLite database (auto-created)
└── downloads/               # Client-side downloads (auto-created)
```

---

## Database Schema

- **users**: Stores `username`, `password`, `display_name`  
- **files**: Metadata - `name`, `upload_date`, `user_id`, `privacy`, `size`, `checksum`  
- **downloads**: Tracks `file_name`, `client_address`, `timestamp`, `user_id`, `speed`  
- **file_shares**: File sharing info - `file_name`, `shared_with_user`

---

## Security Notes

> ⚠️ This version is for demonstration and testing purposes only.

- Passwords are stored in **plaintext** (not secure – consider hashing in production)  
- File transfers are **unencrypted** (add SSL/TLS for security)  
- Private files are accessible only to owners and explicitly shared users

---

## Limitations

- No resume support for interrupted downloads  
- No file versioning or conflict resolution for synchronized folders  
- Limited error recovery for network issues

---

## Contributing

1. Fork the repository  
2. Create a feature branch  
   ```bash
   git checkout -b feature-name
   ```
3. Commit your changes  
   ```bash
   git commit -m "Add feature"
   ```
4. Push to your fork  
   ```bash
   git push origin feature-name
   ```
5. Open a pull request

---

## Troubleshooting

- **Connection Issues**: Ensure the server is running and the IP/port are correct  
- **Login Errors**: Verify credentials with the server admin  
- **Upload/Download Failures**: Check network and server logs  
- **Sync Issues**: Confirm the sync folder exists and has write permissions

---

## License

This project is licensed under the **MIT License**. See the [LICENSE](./LICENSE) file for details.

---

## Contact

For support or inquiries, contact the server administrator or [open an issue](../../issues) in the repository.
