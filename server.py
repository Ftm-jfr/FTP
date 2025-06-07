import os
import shutil
import socket
import ssl
from pathlib import Path
import threading
from datetime import datetime

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 2121
BUFFER_SIZE = 1024

# Server Root directory
BASE_DIR = Path(r"/.")
BASE_DIR.mkdir(exist_ok=True)

file_lock = threading.Lock()

CERT_FILE = 'cert.pem'
KEY_FILE = 'private.key'

user_data = {
    "admin": {"password": "admin123", "role": "admin"},
    "user1": {"password": "user123", "role": "user_lvl1"},
    "user2": {"password": "user456", "role": "user_lvl2"},
    "user3": {"password": "user789", "role": "user_lvl3"},
}


class FTPServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.control_socket.bind((self.host, self.port))
        self.control_socket.listen(5)
        print(f"Server started at {self.host}:{self.port}")

        # SSL configuration
        self.context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        self.context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)
        self.context.check_hostname = False
        self.context.verify_mode = ssl.CERT_NONE  # disable checkin client certification

    def find_free_port(self):
        """Find a free port for data connection."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((SERVER_HOST, 0))  # Bind to a free port
            return s.getsockname()[1]  # Return the port number

    def format_file_info(self, file_path):
        """Format file information (name, size, permissions, creation date)."""
        stats = os.stat(file_path)
        file_size = stats.st_size
        permissions = oct(stats.st_mode)[-3:]
        creation_time = datetime.fromtimestamp(stats.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
        file_name = file_path.name
        return f"{file_name}\t\t{file_size} bytes\t\tPermissions: {permissions}\t\tCreated: {creation_time}"

    def handle_list(self, control_socket, path=" "):
        """Handle the LIST command to list files with detailed information."""
        port = self.find_free_port()

        # Create the data connection
        data_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        data_socket = self.context.wrap_socket(data_socket, server_side=True)
        data_socket.bind((SERVER_HOST, port))
        data_socket.listen(1)

        # Send Passive Mode response with the free port
        control_socket.send(f"227 Entering Passive Mode (127,0,0,1,{port // 256},{port % 256})\r\n".encode())

        # Wait for the client to connect to the data port
        data_conn, _ = data_socket.accept()
        direction = BASE_DIR / path

        if direction.is_dir():
            file_details = []
            for item in os.listdir(direction):
                item_path = direction / item
                file_details.append(self.format_file_info(item_path))

            # Send to the client
            if file_details:
                data_conn.send("\r\n".join(file_details).encode())
            else:
                data_conn.send(b"No files found.\r\n")
        else:
            print("Couldn't find this path")

        # Close the data connection
        data_conn.close()
        control_socket.send(b"226 Transfer complete.\r\n")
        data_socket.close()

    def handle_client(self, control_socket, client_address):
        print(f"Connection from {client_address}")
        control_socket.send(b"220 FTP Server Ready\r\n")
        authenticated = False
        current_user = None

        while True:
            command = control_socket.recv(BUFFER_SIZE).decode()
            print(f"Received command: {command}")

            if command.startswith("USER"):
                username = command.split(" ")[1]
                if username in user_data:
                    current_user = username
                    control_socket.send(b"331 Username accepted, please enter your password.\r\n")
                else:
                    control_socket.send(b"530 Invalid username. Please try again.\r\n")
            elif command.startswith("PASS"):
                if current_user:
                    password = command.split(" ", 1)[1].strip()
                    user_info = user_data[current_user]
                    if user_info["password"] == password:
                        control_socket.send(b"230 Login successful.\r\n")
                        role = user_info["role"]
                        control_socket.send(f"250 You are logged in as {current_user} with role {role}.\r\n".encode())
                        authenticated = True
                    else:
                        control_socket.send(b"530 Invalid password. Please try again.\r\n")
                else:
                    control_socket.send(b"530 Please enter a valid username first.\r\n")
            elif command.startswith("LIST"):
                if authenticated:
                    self.handle_list(control_socket, command.split(" ")[1])
                else:
                    control_socket.send(b"530 Not logged in.\r\n")
            elif command.startswith("RETR"):
                user_info = user_data[current_user]
                role = user_info["role"]
                if authenticated:
                    if role != "user_lvl3":
                        self.handle_retrieve(control_socket, command.split(" ")[1])
                    else:
                        control_socket.send(b"530 Not allowed.\r\n")
                else:
                    control_socket.send(b"530 Not logged in.\r\n")
            elif command.startswith("DELE"):
                user_info = user_data[current_user]
                role = user_info["role"]
                if authenticated:
                    if role == "admin":
                        self.handle_delete(control_socket, command.split(" ")[1])
                    else:
                        control_socket.send(b"530 Not allowed.\r\n")
                else:
                    control_socket.send(b"530 Not logged in.\r\n")
            elif command.startswith("MKD"):
                user_info = user_data[current_user]
                role = user_info["role"]
                if authenticated:
                    if role != "user_lvl3" and role != "user_lvl2":
                        self.handle_make_directory(control_socket, command.split(" ")[1])
                    else:
                        control_socket.send(b"530 Not allowed.\r\n")
                else:
                    control_socket.send(b"530 Not logged in.\r\n")
            elif command.startswith("CDUP"):
                if authenticated:
                    self.handle_cdup(control_socket)
                else:
                    control_socket.send(b"530 Not logged in.\r\n")
            elif command.startswith("PWD"):
                if authenticated:
                    self.handle_pwd(control_socket)
                else:
                    control_socket.send(b"530 Not logged in.\r\n")
            elif command.startswith("STOR"):
                user_info = user_data[current_user]
                role = user_info["role"]
                if authenticated:
                    if role != "user_lvl3" and role != "user_lvl2":
                        self.handle_store(control_socket, command.split(" ")[1], command.split(" ")[2])
                    else:
                        control_socket.send(b"530 Not allowed.\r\n")
                else:
                    control_socket.send(b"530 Not logged in.\r\n")
            elif command.startswith("RMD"):
                user_info = user_data[current_user]
                role = user_info["role"]
                if authenticated:
                    if role == "admin":
                        self.handle_remove_directory(control_socket, command.split(" ")[1])
                    else:
                        control_socket.send(b"530 Not allowed.\r\n")
                else:
                    control_socket.send(b"530 Not logged in.\r\n")
            elif command.startswith("CWD"):
                if authenticated:
                    self.handle_cwd(control_socket, command.split(" ", 1)[1])
                else:
                    control_socket.send(b"530 Not logged in.\r\n")
            elif command.startswith("QUIT"):
                self.handle_quit(control_socket, client_address)
                break

        control_socket.close()

    def start(self):
        """Start the FTP server and handle multiple client connections."""
        while True:
            client_socket, client_address = self.control_socket.accept()
            client_socket = self.context.wrap_socket(client_socket, server_side=True)
            client_thread = threading.Thread(target=self.handle_client, args=(client_socket, client_address))
            client_thread.start()

    def handle_delete(self, control_socket, file_path):
        """Handle the DELE command to delete a file."""
        # Resolve the full file path
        file_full_path = BASE_DIR / file_path

        with file_lock:
            # Check if file exist
            if file_full_path.exists() and file_full_path.is_file():
                try:
                    os.remove(file_full_path)  # Delete the file
                    control_socket.send(b"250 File deleted successfully.\r\n")
                except Exception as e:
                    control_socket.send(f"550 Access denied: {str(e)}\r\n".encode())
            else:
                control_socket.send(b"550 File not found.\r\n")

    def handle_make_directory(self, control_socket, directory_path):
        """Handle the MKD command to make directory."""
        # Resolve the directory path
        full_path = BASE_DIR / directory_path

        try:
            os.mkdir(full_path)
            control_socket.send("257 Directory created successfully".encode())
        except Exception as e:
            control_socket.send(f"550 Access denied: {str(e)}\r\n".encode())

    def handle_store(self, control_socket, file_name, file_path="Uploads"):
        """Handle the STOR command to receive and store a file from the client."""
        # Resolve the upload directory
        upload_dir = BASE_DIR / file_path
        upload_dir.mkdir(exist_ok=True)  # Ensure the directory exists
        # Construct the full file path
        file_path = upload_dir / file_name

        # Find a free port for data transfer
        port = self.find_free_port()

        # Set up the data connection
        data_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        data_socket = self.context.wrap_socket(data_socket, server_side=True)
        data_socket.bind((SERVER_HOST, port))
        data_socket.listen(1)

        # Send Passive Mode response with the free port
        control_socket.send(f"227 Entering Passive Mode (127,0,0,1,{port // 256},{port % 256})\r\n".encode())

        # Wait for the client to connect to the data port
        data_conn, _ = data_socket.accept()

        # Send status code 150 to indicate transfer start
        control_socket.send(b"150 Opening data connection.\r\n")

        # Open the file for writing and receive data
        with file_lock:
            with open(file_path, "wb") as f:
                while True:
                    data = data_conn.recv(BUFFER_SIZE)
                    if not data:
                        break
                    f.write(data)

        # Close the data connection
        data_conn.close()
        data_socket.close()

        # Send status code 226 to indicate successful transfer
        control_socket.send(b"226 Transfer complete.\r\n")

    def handle_retrieve(self, control_socket, file_path):
        """Handle the RETR command to send a file to the client."""
        # Resolve the file path
        file_full_path = BASE_DIR / file_path

        if file_full_path.exists() and file_full_path.is_file():
            # Find free port
            port = self.find_free_port()

            # Send Passive Mode response with the free port
            control_socket.send(f"227 Entering Passive Mode (127,0,0,1,{port // 256},{port % 256})\r\n".encode())

            # Data connection using SSL protocol
            data_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            data_socket.bind((SERVER_HOST, port))
            data_socket.listen(1)
            data_socket = self.context.wrap_socket(data_socket, server_side=True)

            # waiting for client connection
            data_conn, _ = data_socket.accept()

            control_socket.send(b"150 Opening data connection.\r\n")

            # opening file and sending
            with file_lock:
                with open(file_full_path, "rb") as f:
                    while chunk := f.read(BUFFER_SIZE):
                        data_conn.send(chunk)

            # closing data connection
            data_conn.close()
            data_socket.close()

            control_socket.send(b"226 Transfer complete.\r\n")
        else:
            control_socket.send(b"550 File not found.\r\n")

    def handle_pwd(self, control_socket):
        """Handle the PWD command to return the current directory."""
        try:
            # Retrieve the current directory
            current_directory = str(BASE_DIR).replace("\\", "/")
            response = f'257 "{current_directory}" is the current directory.\r\n'
            control_socket.send(response.encode())
        except Exception as e:
            control_socket.send(f"550 Error retrieving directory: {str(e)}\r\n".encode())

    def handle_cdup(self, control_socket):
        """Handle the CDUP command to change to the parent directory."""
        global BASE_DIR
        try:
            # check if we are already in root
            if BASE_DIR == BASE_DIR.root:
                control_socket.send(b"550 Already at root directory.\r\n")
                return

            # find parent
            parent_dir = BASE_DIR.parent

            if parent_dir.resolve() in BASE_DIR.resolve().parents:
                BASE_DIR = parent_dir
                control_socket.send(b"250 Successfully changed to parent directory.\r\n")
            else:
                control_socket.send(b"550 Cannot move to parent directory.\r\n")
        except Exception as e:
            control_socket.send(f"550 Error: {str(e)}\r\n".encode())

    def handle_cwd(self, control_socket, directory_path):
        """Handle the CWD command to change the current working directory."""
        global BASE_DIR
        try:
            # new path
            new_dir = Path(directory_path).resolve()

            # check for existence of path
            if new_dir.exists() and new_dir.is_dir():
                BASE_DIR = new_dir
                control_socket.send(f"250 Directory successfully changed to {new_dir}.\r\n".encode())
            else:
                control_socket.send(b"550 Directory does not exist or is not accessible.\r\n")
        except Exception as e:
            control_socket.send(f"550 Error: {str(e)}\r\n".encode())

    def handle_remove_directory(self, control_socket, directory_path):
        """Handle the RMD command to remove a directory."""
        # Resolve the full directory path
        dir_full_path = BASE_DIR / directory_path.strip("/")

        # Check if directory exists and remove it
        with file_lock:
            if dir_full_path.exists() and dir_full_path.is_dir():
                try:
                    shutil.rmtree(dir_full_path)  # Remove the directory
                    control_socket.send(b"250 Directory deleted successfully.\r\n")
                except Exception as e:
                    control_socket.send(f"550 Cannot delete directory: {str(e)}\r\n".encode())
            else:
                control_socket.send(b"550 Directory not found or cannot be deleted.\r\n")

    def handle_quit(self, control_socket, client_address):
        """Handle the QUIT command to disconnect the client."""
        try:
            control_socket.send(b"221 Goodbye.\r\n")
        except Exception as e:
            print(f"Error while handling QUIT: {e}")
        finally:
            control_socket.close()
            print(f"Connection closed with client{client_address}.")


# Start the FTP Server
ftp_server = FTPServer(SERVER_HOST, SERVER_PORT)
ftp_server.start()
