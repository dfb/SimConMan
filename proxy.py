'''
SimConnect proxy server
'''

import sys, socket, time, traceback, threading, pickle
from simconnect import connection

class GV:
    keepRunning = True

class ConnectionHandler:
    nextID = 0
    @staticmethod
    def Create(sock, destIP, destPort, record):
        c = ConnectionHandler(sock, destIP, destPort, record)
        t = threading.Thread(target=c.Handle)
        t.daemon = True
        t.start()
        return c

    def __init__(self, sock, destIP, destPort, record):
        self.handlerID = ConnectionHandler.nextID
        ConnectionHandler.nextID += 1
        self.record = record
        self.client = connection.ClientConnection(sock)
        self.serverIP = destIP
        self.serverPort = destPort

    def Handle(self):
        # connect to the server
        startTime = time.time()
        serverSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        serverSock.connect((self.serverIP, self.serverPort))
        print('connected to server at', self.serverIP, self.serverPort)
        server = connection.ServerConnection(serverSock)
        if self.record:
            outF = open('proxyconn-%d.log' % self.handlerID, 'wb')
        try:
            while GV.keepRunning:
                didWork = False
                relTime = int((time.time() - startTime) * 1000)

                # Grab messages from the client and send to the server
                toServer = self.client.Recv()
                if toServer is not None:
                    didWork = True
                    print('[%s, %d]' % (self.handlerID, relTime), toServer)
                    if self.record:
                        pickle.dump((time.time(), self.handlerID, toServer), outF)
                    server.Send(toServer)

                # And vice versa
                toClient = server.Recv()
                if toClient is not None:
                    didWork = True
                    print('[%s, %d]' % (self.handlerID, relTime), toClient)
                    if self.record:
                        pickle.dump((time.time(), self.handlerID, toClient), outF)
                    self.client.Send(toClient)

                # don't spin
                if not didWork:
                    time.sleep(0.05)
        except connection.Closed as e:
            print('Connection closed', e)

        if self.record:
            outF.close()

def Proxy(srcPort, destIP, destPort, record):
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
            ConnectionHandler.Create(q, destIP, destPort, record)
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
    Proxy(srcPort, '127.0.0.1', destPort, True)

