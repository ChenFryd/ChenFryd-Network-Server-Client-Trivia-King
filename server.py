import concurrent.futures
import os
import signal
import socket
import threading
import random
import time
import struct
import sys
from Color import Color
import triviaQuestions

UDP_PORT = 13117
MAGIC_COOKIE = 0xabcddcba
OFFER_MESSAGE_TYPE = 0x2
CONNECT_TIMEOUT = 10
BUFFER_SIZE = 1024
MIN_AMOUNT_OF_PLAYERS = 2
FORMAT = 'utf-8'

class TriviaServer:
    def __init__(self, times_created_input):
        signal.signal(signal.SIGINT, self.quit)
        signal.signal(signal.SIGTERM, self.quit)
        self.teams = {}
        self.server_name = "The Office Trivia"
        self.tcp_port = None
        self.tcp_socket = None
        self.lock = threading.Lock()
        self.winner = None
        self.player_Data = {}
        self.times_created = times_created_input
        self.ip = self.get_local_ip()

    def get_question(self):
        """
        get a random question.
        :return: a tuple, first item is the question, the second is the answer.
        """
        return random.choice(triviaQuestions.trivia_questions)

    def get_local_ip(self):
        """
        get the local ip address of the server
        :return:
        """
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80)) #connect to google
            ip_address = s.getsockname()[0]
            s.close()
            return ip_address
        except Exception as e:
            print(Color.colorize(str(e), 'red'))
        raise Exception("You are not connected to the internet")

    def start_udp_server(self):
        """
        '!': Specifies network byte order (big-endian) for all the following data types.
        'I': This format character indicates an unsigned integer (L for long in some systems). It packs the MAGIC_COOKIE value into 4 bytes.
        'B': This format character indicates an unsigned char (1 byte). It packs the OFFER_MESSAGE_TYPE value into 1 byte.
        '32s': This format character indicates a string of 32 bytes. It packs the server name into 32 bytes.
        'H': This format character indicates an unsigned short integer (S for short in some systems). It packs the TCP_PORT value into 2 bytes.
        """

        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            packet = struct.pack('!IB32sH', MAGIC_COOKIE, OFFER_MESSAGE_TYPE, self.server_name.encode(FORMAT),
                                 self.tcp_port)
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            udp_socket.bind((self.ip, UDP_PORT))

            start_time = time.time()
            while time.time() - start_time < CONNECT_TIMEOUT:
                udp_socket.sendto(packet, ('<broadcast>', UDP_PORT))
                time.sleep(1)
        finally:
            udp_socket.close()

    def start_tcp_server(self):
        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            tcp_socket.bind((self.ip, 0))  # assign port 0 in order to let the OS choose a free port
            _, port = tcp_socket.getsockname()
            tcp_socket.listen()
            print(Color.colorize(f'Server started, listening on IP address {self.ip}', 'green'))
            self.tcp_socket = tcp_socket
            self.tcp_port = port
        except Exception as e:
            print(e)
            tcp_socket.close()

    def connect_to_clients(self):
        start_time = time.time()
        counter = 0
        while time.time() - start_time < CONNECT_TIMEOUT:
            try:
                self.tcp_socket.settimeout(CONNECT_TIMEOUT - (time.time() - start_time))
                conn, _ = self.tcp_socket.accept()

                team_name = conn.recv(BUFFER_SIZE).decode(FORMAT)[:-1] #remove the \n
                print(Color.colorize(f'Team: {team_name}', 'green'))
                self.teams[team_name + "_" + str(counter)] = conn
                counter += 1
            except Exception as exc:
                if str(exc) != 'timed out':
                    print(Color.colorize(str(exc), 'red'))
            finally:
                time.sleep(0.1)

        self.tcp_socket.settimeout(None)

    def start_game(self):
        """
        1. first get a random question and its answer
        2. send game start message to clients
        3. send the question to clients
        4. collect answers from clients with concurrency and wait until all the clients answered
        5. send the winner to clients
        """
        question, answer = self.get_question()
        self.send_game_start_message()
        self.send_question(question)
        with concurrent.futures.ThreadPoolExecutor() as executor:
            for player_name, client_conn in self.teams.items():
                executor.submit(self.collect_answers, client_conn, player_name, answer)
            executor.shutdown(wait=True)  # wait for all the threads to finish before continuing with the main thread
        self.send_winner()
        self.game_over()
        self.statistics()

    def send_game_start_message(self):
        message = f"Welcome to the {self.server_name} server\n"
        for i, (player_name, _) in enumerate(self.teams.items()):
            message += f"Player {i}: {player_name[:-2]}\n"  # -2 to remove the counter
        self.send_message(message)

    def send_question(self, question):
        """
        send the question to clients
        """
        message = f"True or false: {question}"
        self.send_message(message)

    def send_message(self, message):
        """
        send a message to all the clients
        :param message:
        """
        for _, client_conn in self.teams.items():
            client_conn.sendall(message.encode(FORMAT))
        print(message)

    def collect_answers(self, client_conn, player_name, correct_answer):
        try:
            client_conn.settimeout(CONNECT_TIMEOUT)
            answer = client_conn.recv(BUFFER_SIZE).decode(FORMAT)
            if answer.lower() in ['y', 't', '1']:
                answer = True
            elif answer.lower() in ['n', 'f', '0']:
                answer = False
            else:
                answer = None
            with self.lock:  # prevent race conditions
                self.player_Data[player_name] = (correct_answer, answer, time.time())
            if answer == correct_answer:
                with self.lock:  # prevent race conditions
                    if self.winner is None:
                        self.winner = player_name
        except Exception as e:
            if str(e) != 'timed out':
                print(Color.colorize(e, "red"))

    def send_winner(self):
        if self.winner is not None:
            winner = self.winner[:-2]  # remove the counter
            message = f"{winner} is correct! {winner} wins!\n"
        else:
            message = "No correct answers. Starting a new round.\n"
        self.send_message(message)

    def game_over(self):
        message = "Game over!\n"
        if self.winner:  # if there is a winner
            message += "Congratulations to the winner: " + self.winner[:-2] + "\n"
        self.send_message(message)

    def statistics(self):
        message = "Statistics about this game:\n"
        message += f"The amount of time server restarted: {str(self.times_created)}\n"
        first_answering_player = self.statistical_get_first_answering_player()  # Call the new function here
        if first_answering_player:
            message += f"{first_answering_player} answered first!\n"
        else:
            message += "No players answered.\n"
        message += f"The number of times players gave an incorrect answer: {str(self.statistical_get_wrong_answers_count())}\n"
        message += f"The name of the player with the longest name is: {self.statistical_get_longest_player_name()}\n"
        self.send_message(message)

    def statistical_get_longest_player_name(self):
        """
          This function finds the player with the longest name among the connected teams.

          Returns:
              A string containing the name of the player with the longest name,
              or None if there are no connected teams.
          """
        if not self.teams:
            return None
        longest_name = max(self.teams.keys(), key=len)
        return longest_name[:-2]  # Remove the counter from the team name

    def statistical_get_wrong_answers_count(self):
        """
        This function calculates the number of players who answered the question incorrectly.

        Returns:
          An integer representing the number of players with wrong answers.
        """
        wrong_answers = 0
        if not self.player_Data:
            return wrong_answers
        # Access the correct answer from the first element in the tuple stored in player_Data
        correct_answer = list(self.player_Data.values())[0][0]
        for player_name, (_, player_answer, _) in self.player_Data.items():
            if player_answer != correct_answer:
                wrong_answers += 1
        return wrong_answers

    def statistical_get_first_answering_player(self):
        """
        This function finds the player who sent their answer first based on the timestamps stored in player_Data.

        Returns:
            A string containing the name of the player who answered first, or None if no players answered.
        """
        if not self.player_Data:
            return None
        # Get the player name and timestamp of the first answer based on the minimum time value
        first_answer_info = min(self.player_Data.items(), key=lambda x: x[1][2])
        if first_answer_info:
            return first_answer_info[0][:-2]  # Return the player name from the first answer info tuple
        else:
            return None

    def quit(self,sig, frame):
        if os.name == 'nt':
            os.system('cls')
        elif os.name == 'posix':
            os.system('reset')
        for conn in self.teams.values():
            conn.close()
        if self.tcp_socket:
            self.tcp_socket.close()
        print('Goodbye!')
        sys.exit(0)

def main():
    server_creation_count = 0
    while True:
        server_creation_count += 1  #for statistics
        server = TriviaServer(server_creation_count)
        try:
            server.start_tcp_server()  # start the tcp server,m
            udp_thread = threading.Thread(target=server.start_udp_server)
            udp_thread.start()
            server.connect_to_clients()
            if len(server.teams) < MIN_AMOUNT_OF_PLAYERS:
                print(Color.colorize("Not enough players, waiting for more players to join", "red"))
                continue
            udp_thread.join()
            server.start_game()
            print("Game over, sending out offer requests...")

        except Exception as excep:
            print(Color.colorize(str(excep), "red"))
        finally:
            for conn in server.teams.values():
                conn.close()
            if server.tcp_socket:
                server.tcp_socket.close()

if __name__ == "__main__":
    main()