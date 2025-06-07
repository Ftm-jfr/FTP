import os
import socket
import ssl
from pathlib import Path

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 2121
BUFFER_SIZE = 1024

BASE_DIR = Path(r"C:\Users\F\PycharmProjects\FTP")
DOWNLOAD_DIR = BASE_DIR / "Downloads"  # Path to the download directory

CA_CERT = 'cert.pem'

BASE_DIR.mkdir(exist_ok=True)
DOWNLOAD_DIR.mkdir(exist_ok=True)


class FTPClient:
    def __init__(self, host, port):
        self.data_socket = None
        self.host = host
        self.port = port
        self.control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # Data connection configuration using SSL protocol
        self.context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        self.context.load_verify_locations(cafile=CA_CERT)
        self.context.check_hostname = False
        self.context.verify_mode = ssl.CERT_OPTIONAL

        # connect to server
        self.control_socket = self.context.wrap_socket(self.control_socket, server_hostname=SERVER_HOST)
        self.control_socket.connect((self.host, self.port))

        # checking user logged in
        self.authenticated = False

    def control_connection(self, command):
        """Send command to the server and return the server's response."""
        self.control_socket.send(command.encode())
        response = self.control_socket.recv(BUFFER_SIZE).decode()
        print(f"Server response: {response}")
        return response

    def data_connection(self, port):
        """Establish a data connection to the server."""
        self.data_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.data_socket.connect((SERVER_HOST, port))
        self.data_socket = self.context.wrap_socket(self.data_socket, server_hostname=SERVER_HOST)

    def list_files(self, path=" "):
        """Request the list of files from the server."""
        print(f"Requesting list of files from {path}")
        self.control_socket.send(f"LIST {path}".encode())

        # Wait for the server's response to enter passive mode
        response = self.control_socket.recv(BUFFER_SIZE).decode()
        print(f"Server response: {response}")

        if response.startswith("227"):
            print("Entering Passive Mode, waiting for data connection...")
            # Extract the port from the PASV response
            parts = response.split("(")[1].split(")")[0].split(",")
            port = int(parts[4]) * 256 + int(parts[5])  # Extract the port
            self.data_connection(port)  # Establish data connection

            # Receive the file list from the data connection
            file_list = ""
            while True:
                data = self.data_socket.recv(BUFFER_SIZE)  # Use self.data_socket.recv() here
                if not data:
                    break
                file_list += data.decode()

            # Print file list
            print("Received file list:")
            print(file_list)

            # Close the data connection
            self.data_socket.close()

            # Wait for server's final response
            response = self.control_socket.recv(BUFFER_SIZE).decode()
            print(f"Server response: {response}")
        else:
            print(f"Error receiving file list: {response}")

    def store_file(self, file_path, destination_path):
        """Upload a file to the server."""
        file_name = file_path.split("\\")[-1]
        # Send command to server
        file_path = BASE_DIR / file_path
        if file_path.is_file():
            response = self.control_connection(f"STOR {file_name} {destination_path}")
        else:
            print("File not found")
            return

        if response.startswith("227"):
            # Extract port
            parts = response.split("(")[1].split(")")[0].split(",")
            port = int(parts[4]) * 256 + int(parts[5])

            # Data connection
            self.data_connection(port)
            response = self.control_socket.recv(BUFFER_SIZE).decode()
            print(response)

            if response.startswith("150"):
                try:
                    # opening file and start uploading

                    with open(file_path, "rb") as f:
                        while chunk := f.read(BUFFER_SIZE):
                            self.data_socket.send(chunk)

                    print(f"File uploaded successfully.")

                except FileNotFoundError:
                    print(f"Error: File not found.")
                    self.control_socket.send("550".encode())

                except Exception as e:
                    print(f"Error during file upload: {e}")
                    self.control_socket.send("550".encode())

                finally:
                    # closing data connection
                    self.data_socket.close()
                    print("Data connection closed.")

                # final server response
                response = self.control_socket.recv(BUFFER_SIZE).decode()
                print(f"Server response: {response}")
        else:
            print(f"Error: {response}")

    def remove_directory(self, directory_path):
        """Send the RMD command to the server to remove a directory."""
        response = self.control_connection(f"RMD {directory_path}")
        print(response)

    def retrieve_file(self, file_path):
        """Retrieve a file from the server and save it in the download directory."""
        file_name = file_path.split("\\")[-1]
        response = self.control_connection(f"RETR {file_path}")

        if response.startswith("227"):
            # Extract the port from the PASV response
            parts = response.split("(")[1].split(")")[0].split(",")
            port = int(parts[4]) * 256 + int(parts[5])

            # Establish a data connection
            self.data_connection(port)

            # Receive the file
            response = self.control_socket.recv(BUFFER_SIZE).decode()
            print(f"Server response: {response}")

            if response.startswith("150"):
                # Construct the full path to save the file
                destination_path = DOWNLOAD_DIR / file_name
                print(f"Downloading to: {destination_path}")

                with open(destination_path, "wb") as f:
                    while True:
                        data = self.data_socket.recv(BUFFER_SIZE)
                        if not data:
                            break
                        f.write(data)

                # Close the data connection
                self.data_socket.close()

                # Wait for final response
                response = self.control_socket.recv(BUFFER_SIZE).decode()
                print(f"Server response: {response}")

                if response.startswith("226"):
                    print(f"File '{file_path}' downloaded successfully to {destination_path}")
                else:
                    print(f"Unexpected response after transfer: {response}")
            else:
                print("Error: File transfer could not be started.")
        else:
            print(f"Error: {response}")

    def delete_file(self, file_path):
        self.control_socket.send(f"DELE {file_path}".encode())
        response = self.control_socket.recv(BUFFER_SIZE).decode()
        print(response)

    def quit(self):
        """Send the QUIT command to the server and close the connection."""
        self.control_connection("QUIT")
        self.control_socket.close()

    def make_directory(self, directory_path):
        self.control_socket.send(f"MKD {directory_path}".encode())
        response = self.control_socket.recv(BUFFER_SIZE).decode()
        print(response)

    def cdup(self):
        self.control_socket.send("CDUP".encode())
        print(self.control_socket.recv(BUFFER_SIZE).decode())

    def pwd(self):
        self.control_socket.send("PWD".encode())
        print(self.control_socket.recv(BUFFER_SIZE).decode())

    def cwd(self, new_path):
        self.control_socket.send(f"CWD {new_path}".encode())
        print(self.control_socket.recv(BUFFER_SIZE).decode())

    def user(self, usrnme):
        self.control_socket.send(f"USER {usrnme}".encode())
        response = self.control_socket.recv(BUFFER_SIZE).decode()

        print(response)
        if response.startswith("331"):
            password = input("PASS ")
            self.control_socket.send(f"PASS {password}".encode())
            response = self.control_socket.recv(BUFFER_SIZE).decode()
            print(response)
            if response.startswith("230"):
                response = self.control_socket.recv(BUFFER_SIZE).decode()
                print(response)
                self.authenticated = True


# Example usage
if __name__ == "__main__":
    client = FTPClient(SERVER_HOST, SERVER_PORT)
    print(client.control_socket.recv(BUFFER_SIZE).decode())
    while not client.authenticated:
        # Login
        username = input("USER ")
        client.user(username)

    option = None
    while not option == "QUIT":
        option = input()
        if option == "PWD":
            client.pwd()
        elif option.startswith("CWD"):
            if len(option.split(" ")) > 1:
                client.cwd(option.split(" ")[1])
        elif option.startswith("LIST"):
            if len(option.split(" ")) > 1:
                client.list_files(option.split(" ")[1])
            else:
                client.list_files(" ")
        elif option.startswith("RETR"):
            if len(option.split(" ")) > 1:
                client.retrieve_file(option.split(" ")[1])
        elif option.startswith("STOR"):
            if len(option.split(" ")) > 2:
                client.store_file(option.split(" ")[1], option.split(" ")[2])
        elif option.startswith("DELE"):
            if len(option.split(" ")) > 1:
                client.delete_file(option.split(" ")[1])
        elif option.startswith("MKD"):
            if len(option.split(" ")) > 1:
                client.make_directory(option.split(" ")[1])
        elif option.startswith("RMD"):
            if len(option.split(" ")) > 1:
                client.remove_directory(option.split(" ")[1])
        elif option == "CDUP":
            client.cdup()
        else:
            print("Invalid command.Please try again.")

    client.quit()
