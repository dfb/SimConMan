'''
SimConnect proxy server
'''

from . utils import *
import sys, socket, time, threading
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
        self.client = sock
        self.serverIP = destIP
        self.serverPort = destPort

    def Handle(self):
        # connect to the server
        serverSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        serverSock.connect((self.serverIP, self.serverPort))
        serverSock.setblocking(0)
        log('connected to server at', self.serverIP, self.serverPort)
        clientSock = self.client
        clientSock.setblocking(0)
        toServer = []
        toClient = []
        try:
            while GV.keepRunning:
                sent = 0
                recv = 0

                # grab data from the client
                try:
                    more = clientSock.recv(4096)
                    if more:
                        toServer.append(more)
                        recv += len(more)
                except BlockingIOError:
                    pass

                # grab data from the server
                try:
                    more = serverSock.recv(4096)
                    if more:
                        toClient.append(more)
                        recv += len(more)
                except BlockingIOError:
                    pass

                # send to the server
                if toServer:
                    next = toServer.pop(0)
                    try:
                        numSent = serverSock.send(next)
                        sent += numSent
                        if numSent < len(next):
                            toServer.insert(0, next[numSent:])
                    except BlockingIOError:
                        pass

                # send to the client
                if toClient:
                    next = toClient.pop(0)
                    try:
                        numSent = clientSock.send(next)
                        sent += numSent
                        if numSent < len(next):
                            toClient.insert(0, next[numSent:])
                    except BlockingIOError:
                        pass

                # don't spin
                if sent == 0 and recv == 0:
                    time.sleep(0.05)
                else:
                    log('sent:', sent, 'recv:', recv)
        except connection.Closed as e:
            log('Connection closed', e)

def Proxy(srcPort, destIP, destPort):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('', srcPort))
    server.listen(10)
    server.setblocking(0)
    log('Listening on port', srcPort)
    while 1:
        try:
            q,v = server.accept()
            log('Accepting connection')
            ConnectionHandler.Create(q, destIP, destPort)
        except BlockingIOError:
            try:
                time.sleep(0.25)
            except KeyboardInterrupt:
                break
        except KeyboardInterrupt:
            break
        except:
            logTB()
    log('Shutting down')
    GV.keepRunning = False
    server.close()

if __name__ == '__main__':
    srcPort = 10000
    destPort = 12500
    Proxy(srcPort, '127.0.0.1', destPort)
