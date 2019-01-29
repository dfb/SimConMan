'''
low level SimConnect connection interface - bridges between higher level messages and
actual data transmission over the wire

TODO: instead of constantly hammering the socket, use select() to determine if it's
time to do a read or write.
'''

from . import message

class Closed(Exception): pass

def ClientConnection(sock): return Connection(Connection.CT_Client, sock)
def ServerConnection(sock): return Connection(Connection.CT_Server, sock)

# Server and client message handling is largely identical - but not quite - so use a common
# class for both types
class Connection:
    CT_Client, CT_Server = range(2) # type of agent on the other end of this connection
    def __init__(self, type, sock, maxPacketSize=4096):
        self.type = type # one of CT_*
        if type == self.CT_Client:
            self.FromBufferFunc = message.ClientMessageFromBuffer
        else:
            self.FromBufferFunc = message.ServerMessageFromBuffer
        sock.setblocking(False)
        self.sock = sock
        self.maxPacketSize = maxPacketSize
        self.alive = True # False once the socket has closed
        self.readBuffer = bytearray(maxPacketSize) # slab of mem to read data into to avoid reallocs
        self.readView = memoryview(self.readBuffer) # for sock.recv_into support
        self.outBytes = bytearray() # raw bytes from messages that we are waiting to send
        self.inBytes = bytearray() # raw packet data waiting to be converted into messages
        self.inMessages = [] # full-formed messages waiting to be returned to the caller

    def Send(self, msg):
        '''Enqueues a message to be sent. Doesn't actually send the data though - you have to
        call Recv to actually run the message pump.'''
        self.outBytes.extend(message.MessageToBytes(msg))

    def Recv(self):
        '''pumps data in both directions as needed, and then returns the next available message
        that has been read. It is assumed that the owner of the connection calls this often in a
        loop of some sort.'''
        if self.alive:
            # Try to send some pending data if needed
            if len(self.outBytes) > 0:
                try:
                    numSent = self.sock.send(self.outBytes[:self.maxPacketSize])
                    self.outBytes = self.outBytes[numSent:]
                except BlockingIOError:
                    pass # no data can be written right now

            # See if we can read any additional data
            try:
                numRead = self.sock.recv_into(self.readView, self.maxPacketSize)
                if numRead > 0:
                    self.inBytes.extend(self.readView[:numRead])
            except BlockingIOError:
                pass # no data to be read right now
            except ConnectionResetError:
                self.alive = False

        # See if we can assemble any read data into whole messages
        msg, numConsumed = self.FromBufferFunc(self.inBytes)
        if msg is not None:
            self.inMessages.append(msg)
            raw = self.inBytes[:numConsumed]
            enc = message.MessageToBytes(msg)
            if raw != enc:
                print('MSG:', msg)
                print('RAW:', raw)
                print('ENC:', enc)
                assert 0, 'ENCODING FAILURE'
            self.inBytes = self.inBytes[numConsumed:]

        # Finally, return a message if we have one ready
        try:
            return self.inMessages.pop(0)
        except IndexError:
            # No pending messages
            if not self.alive:
                raise Closed(self)
            return None

