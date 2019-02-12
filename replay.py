'''
Replays recordings saved from the proxy server - simulating the server side of the connection
SimConnect proxy server
'''

import sys, socket, time, traceback, threading, pickle
from simconnect import connection, message

class GV:
    keepRunning = True

class ConnectionHandler:
    nextID = 0
    @staticmethod
    def Create(sock, serverPort, msgs):
        c = ConnectionHandler(sock, serverPort, msgs)
        t = threading.Thread(target=c.Handle)
        t.daemon = True
        t.start()
        return c

    def __init__(self, sock, serverPort, msgs):
        self.handlerID = ConnectionHandler.nextID
        ConnectionHandler.nextID += 1
        self.serverPort = serverPort
        self.msgs = msgs # list of S and C messages for this connection
        self.client = connection.ClientConnection(sock)

    def Handle(self):
        # connect to the server
        if self.serverPort is not None:
            serverSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            serverSock.connect(('127.0.0.1', self.serverPort))
            print('connected to server at', self.serverPort)
            server = connection.ServerConnection(serverSock)

        ourStartTime = time.time()
        fileStartTime = self.msgs[0][0]
        timeOffset = ourStartTime - fileStartTime # add timeOffset to a recorded message to get the time at which we should be sending it back
        timeOffset += 1 # delay them a little since we aren't actually responding to the messages we're getting
        try:
            while GV.keepRunning:
                didWork = False

                # Grab any messages from the server that are waiting
                if self.serverPort is not None:
                    inMsg = server.Recv()
                    if inMsg is not None:
                        print('[%d]' % self.handlerID, '(from server)', inMsg)
                        didWork = True

                # Grab any messages from the client that are waiting
                inMsg = self.client.Recv()
                if inMsg is not None:
                    print('[%d]' % self.handlerID, '(from client)', inMsg)
                    didWork = True

                # Process all queued messages
                if self.msgs:
                    # Peek at next msg - if it's a client msg, log it and toss it
                    msgTS, msgHandlerID, msg = self.msgs[0]
                    relTime = int((msgTS - fileStartTime) * 1000)
                    assert msgHandlerID == self.handlerID, (self.handlerID, msgHandlerID)
                    playTime = msgTS + timeOffset + 0.25 # plus a little to make sure it comes after the corresponding client msg
                    if time.time() >= playTime:
                        self.msgs.pop(0)
                        didWork = True
                        print('[%d,%d]' % (self.handlerID, relTime), '(from recording)', msg)
                        if msg.__class__.__name__[0] == 'C':
                            # send the msg from the recording to the server
                            if self.serverPort is not None:
                                server.Send(msg)
                        else:
                            assert msg.__class__.__name__[0] == 'S', msg
                            # send the msg from the recording to the client
                            self.client.Send(msg)

                # don't spin
                if not didWork:
                    time.sleep(0.05)
        except connection.Closed as e:
            print('Connection closed', e)

def ListenForConnections(clientPort, serverPort, msgLists):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('', clientPort))
    server.listen(10)
    server.setblocking(0)
    print('Listening on port', clientPort)
    while 1:
        try:
            q,v = server.accept()
            print('Accepting connection')
            ConnectionHandler.Create(q, serverPort, msgLists.pop(0))
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

def LoadMsgs(filename):
    '''loads pickled messages from a proxy log. Returns a list of (timestamp, connNum, msg)'''
    msgs = []
    with open(filename, 'rb') as f:
        while 1:
            try:
                msgs.append(pickle.load(f))
            except EOFError:
                break
    return msgs

dataDefNames = {} # (connID, defID, datumID) --> datum name

import struct
def Hex(s):
    s = ['%02X' % x for x in s]
    return ' '.join(s)

def Moar(connID, msg):
    ret = ''
    if msg.flags & 2:
        data = msg.data[:]
        for i in range(msg.defineCount):
            datumID = struct.unpack('<L', data[:4])[0]
            data = data[4:]
            ret += '\n        %d:' % datumID + ' ' + Hex(data[:4])
            ret += ' :' + str(dataDefNames.get((connID, msg.definitionID, datumID)))
            data = data[4:]
    return ret

def Dump(msgs, filename):
    with open(filename, 'wt') as f:
        start = msgs[0][0]
        for ts, connID, msg in msgs:
            if isinstance(msg, message.CAddToDataDefinition):
                dataDefNames[(connID, msg.dataDefinitionID, msg.datumID)] = msg.datumName
            diffMS = int((ts-start) * 1000)
            extra = ''
            if isinstance(msg, message.SSimObjectData):
                extra = Moar(connID, msg)
            f.write('[%06d,%d,%s] %r%s\n' % (diffMS, connID, getattr(msg, '_counter', 0),msg, extra))

if __name__ == '__main__':
    if 1:
        msgs = sorted(LoadMsgs('proxyconn-0.log') + LoadMsgs('proxyconn-1.log') + LoadMsgs('proxyconn-2.log'), key=lambda x:x[:2])
        Dump(msgs, 'taxiing.log')
    else:
        msgs = []
        for i in range(3):
            msgs.append(LoadMsgs('proxyconn-%d.log' % i))
        #ListenForConnections(10000, 12500, msgs)
        ListenForConnections(10000, None, msgs) # None means don't send to the server

