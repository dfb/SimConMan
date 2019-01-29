'''
SimConnect proxy server
'''

import sys, socket, time, traceback, threading
import connection

class GV:
    keepRunning = True

class ConnectionHandler:
    nextID = 0
    @staticmethod
    def Create(sock, destIP, destPort):
        c = ConnectionHandler(sock, destIP, destPort)
        t = threading.Thread(target=c.Handle)
        t.daemon = True
        t.start()
        return c

    def __init__(self, sock, destIP, destPort):
        self.handlerID = ConnectionHandler.nextID
        ConnectionHandler.nextID += 1
        self.client = connection.ClientConnection(sock)
        self.serverIP = destIP
        self.serverPort = destPort

    def Handle(self):
        # connect to the server
        serverSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        serverSock.connect((self.serverIP, self.serverPort))
        print('connected to server at', self.serverIP, self.serverPort)
        server = connection.ServerConnection(serverSock)
        try:
            while GV.keepRunning:
                didWork = False

                # Grab messages from the client and send to the server
                toServer = self.client.Recv()
                if toServer is not None:
                    didWork = True
                    print('[%s]' % self.handlerID, toServer)
                    server.Send(toServer)

                # And vice versa
                toClient = server.Recv()
                if toClient is not None:
                    didWork = True
                    print('[%s]' % self.handlerID, toClient)
                    self.client.Send(toClient)

                # don't spin
                if not didWork:
                    time.sleep(0.05)
        except connection.Closed as e:
            print('Connection closed', e)

def Proxy(srcPort, destIP, destPort):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('', srcPort))
    server.listen(10)
    server.setblocking(0)
    print('Listening on port', srcPort)
    while 1:
        try:
            q,v = server.accept()
            print('Accepting connection')
            ConnectionHandler.Create(q, destIP, destPort)
        except BlockingIOError:
            try:
                time.sleep(0.25)
            except KeyboardInterrupt:
                break
        except KeyboardInterrupt:
            break
        except:
            traceback.print_exc()
    print('Shutting down')
    GV.keepRunning = False
    server.close()

if __name__ == '__main__':
    srcPort = 10000
    destPort = 12500
    Proxy(srcPort, '127.0.0.1', destPort)

