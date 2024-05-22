import os
import signal
import socket
import threading
import sys
import struct
import time
from enum import Enum
from Color import Color
import select

UDP_PORT = 13117
MAGIC_COOKIE = 0xabcddcba
OFFER_MESSAGE_TYPE = 0x2
BUFFER_SIZE = 1024
UDP_STRUCT = '!IB32sH'
FORMAT = 'utf-8'

class TriviaClient:
    def __init__(self):
        signal.signal(signal.SIGINT, self.quit)
        signal.signal(signal.SIGTERM, self.quit)
        self.flag = False
        self.player_name = "Dwight" #player name should be hard-coded
        self.server_ip_address = None
        self.server_tcp_port = None
        self.tcp_socket = None
        self.server_name = None

    def quit(self,sig, frame):
        if os.name == 'nt':
            os.system('cls')
        elif os.name == 'posix':
            os.system('reset')
        if self.tcp_socket:
            self.tcp_socket.close()
        print(Color.colorize('Goodbye!', "white"))
        sys.exit(0)

    def start_udp_listener(self):
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) #, socket.IPPROTO_UDP
        # Use SO_REUSEADDR on Windows
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp_socket.bind(('', UDP_PORT))
        print("Client started, listening for offer requests...")

        while not self.server_ip_address:
            try:
                data, addr = udp_socket.recvfrom(BUFFER_SIZE)
                self.handle_udp_message(data, addr)
            except Exception as e:
                print(Color.colorize(str(e),'red'))
        udp_socket.close()

    def handle_udp_message(self, data, addr):
        magic_cookie, message_type, server_name, tcp_port = struct.unpack(UDP_STRUCT, data)

        if magic_cookie == MAGIC_COOKIE and message_type == OFFER_MESSAGE_TYPE:
            self.server_ip_address = addr[0] #get only the ip, no need UDP port
            self.server_tcp_port = tcp_port
            self.server_name = server_name.decode(FORMAT).replace('\x00', '') #trim the null bytes from the server name

    def connect_to_server(self):
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        print(f"Received offer from server {self.server_name} at address {self.server_ip_address}, attempting to connect...")
        client_socket.connect((self.server_ip_address, self.server_tcp_port))
        client_socket.sendall((self.player_name+"\n").encode(FORMAT))
        self.tcp_socket = client_socket


    def send_messages(self):
        """
        This function is responsible for sending the key presses to the server
        becuase input() is blocking, we use msvcrt.kbhit() to check if a key was pressed
        each platform uses different libraries to get the key press
        :return:
        """
        if os.name == 'nt': #we are at windows
            import msvcrt
            while self.flag: #in order to check the time limit has not expired or no need to
                if msvcrt.kbhit():
                    key = msvcrt.getche()
                    print() #move to the next line
                    self.tcp_socket.sendall(key)
                    break
                time.sleep(0.4)
        elif os.name == 'posix': #we are at linux
            try:
                import getch
            except ImportError:
                print("This program requires the getch module")
                sys.exit(1)
            key = getch.getche()
            print()
            self.tcp_socket.sendall(key)

    def play(self):
        send_message_thread = threading.Thread(target=self.send_messages, daemon=True)
        try:
            while True: #no busy waiting becuase it will stop when the server closes the connection
                ready, _, _ = select.select([self.tcp_socket], [], [])  # 1 second timeout
                if ready:
                    data = self.tcp_socket.recv(BUFFER_SIZE)
                    if data and not self.flag: #first time we get data
                        self.flag = True
                        send_message_thread.start()
                    elif not data:
                        break
                    decode_data = data.decode(FORMAT)
                    print(decode_data)
        except Exception as e:
            if str(e) == "[WinError 10054] An existing connection was forcibly closed by the remote host":
                pass #game over, server closed the connection
            else:
                print(Color.colorize('Disconnected from server', Color.cyan))
                print(Color.colorize(str(e), "red"))
        finally:
            if self.flag:
                self.flag = False
                send_message_thread.join()

def main():
    client = TriviaClient()
    while True:
        try:
            client.start_udp_listener()
            client.connect_to_server()
            if not client.tcp_socket:
                continue
            client.play()
        except Exception as e:
            if str(e).startswith("[WinError 10061] No connection could be made"):
                pass #could not make a connection to the server
            else:
                print(Color.colorize(str(e), "red"))
        finally:
            if client.tcp_socket:
                client.tcp_socket.close()
            client.server_ip_address = None #reset the server ip address
            client.flag = False #reset the flag for the next game for the write input

if __name__ == "__main__":
    main()