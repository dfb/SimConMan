'''
Defines all the SimConnect messages (both the sending messages and their responses) along
with functions for converting from raw data to messages. Messages are defined by the sender,
e.g. a client message is not a message *to* a client but a message *from* a client.
'''

import struct

classMap = {} # (fromAgent ('s' or 'c'), msgCode) --> class for this message

class BaseStruct:
    '''base class for app-specific struct subclasses'''
    members = [] # list of (name, StructValue), populated by MakeStruct
    @classmethod
    def FromBytes(cls, buffer, offset=0):
        '''creates an object from a buffer. Returns (newObj, bytesConsumedFromBuffer)'''
        obj = cls()
        totalConsumed = 0
        for name, sv in cls.members:
            v, consumed = sv.FromBytes(buffer, offset, obj)
            offset += consumed
            totalConsumed += consumed
            setattr(obj, name, v)
        return obj, totalConsumed

    def ToBytes(self):
        '''converts the object instance into a bytearray and returns it'''
        # In order to support structs that have variable length array members, we first
        # have to update any array fields
        for name, sv in self.members:
            if isinstance(sv, Array) and sv.countField is not None:
                theArray = getattr(self, name)
                setattr(self, sv.countField, len(theArray))

        ret = bytearray()
        for name, sv in self.members:
            v = getattr(self, name)
            more = sv.ToBytes(v)
            ret.extend(more)
        return ret

    def __repr__(self):
        items = []
        for name, sv in self.members:
            v = getattr(self, name)
            items.append('%s: %r' % (name, v))
        items = ', '.join(items)
        return '<%s: %s>' % (self.__class__.__name__, items)

    def __init__(self, **kwargs):
        for k,v in kwargs.items():
            setattr(self, k, v)

class Array(BaseStruct):
    '''A Struct member whose value is an array of objects instead of an individual object.
    formatOrStructClass - a struct module format code (e.g. "L") or a Struct subclass
    countOrField - a hardcoded number (for fixed-len arrays) or a field name that stores the count'''
    def __init__(self, formatOrStructClass, countOrField):
        self.structValue = StructValue(formatOrStructClass)
        if type(countOrField) is str:
            self.count = None
            self.countField = countOrField
        else:
            self.count = countOrField
            self.countField = None

    def FromBytes(self, buffer, offset, intoObj):
        ret = []
        count = self.count
        if count is None:
            count = getattr(intoObj, self.countField)

        totalConsumed = 0
        for i in range(count):
            v, consumed = self.structValue.FromBytes(buffer, offset)
            offset += consumed
            totalConsumed += consumed
            ret.append(v)
        return ret, totalConsumed

    def ToBytes(self, value):
        assert 0, value

class Remaining(BaseStruct):
    '''A special-case struct member to capture any variable length data that is on the end of the message,
    but that does not have a field defining its length (rather, the message header implies its length).'''
    def FromBytes(self, buffer, offset):
        return b'', 0 # the lower level code will set it as intoObj.[some field]
    def ToBytes(self, value):
        return value

class StructValue:
    '''Used internally, encapsulates the handling of struct member values'''
    def __init__(self, formatOrStructClass):
        self.format = None
        self.size = None
        self.structClass = None
        if isinstance(formatOrStructClass, Array) or isinstance(formatOrStructClass, Remaining):
            self.structClass = formatOrStructClass
        elif type(formatOrStructClass) is type and issubclass(formatOrStructClass, BaseStruct):
            self.structClass = formatOrStructClass
        else:
            self.format = formatOrStructClass
            self.size = struct.calcsize(self.format)

    def FromBytes(self, buffer, offset, intoObj=None):
        if self.structClass is not None:
            if isinstance(self.structClass, Array):
                return self.structClass.FromBytes(buffer, offset, intoObj)
            return self.structClass.FromBytes(buffer, offset)
        assert len(buffer) >= offset + self.size
        v = struct.unpack_from('<' + self.format, buffer, offset)[0] # for now we always assume little endian
        if self.format.endswith('s'):
            # auto decode and null-strip strings
            v = v.split(b'\x00', 1)[0].decode('latin-1')
        return v, self.size

    def ToBytes(self, value):
        if self.format:
            if self.format.endswith('s'):
                # encode and null-pad
                finalLen = int(self.format[:-1])
                value = value.encode('latin-1')
                value = value + (b'\x00' * (finalLen - len(value)))
            return struct.pack('<' + self.format, value)
        if isinstance(value, BaseStruct):
            return value.ToBytes()
        if type(self.structClass) is Array:
            ret = bytearray()
            for v in value:
                ret.extend(self.structClass.structValue.ToBytes(v))
            return ret
        if type(self.structClass) is Remaining:
            return value
        assert 0, 'No idea what to do with ' + repr(value)

def MakeStruct(klassName, **kwargs):
    '''creates and returns a new BaseStruct subclass (also adds it to globals()) with the given members'''
    members = []
    for k,v in kwargs.items(): # as of py3.6, kwargs preserves ordering
        members.append((k, StructValue(v)))
    klass = type(klassName, (BaseStruct,), dict(members=members))
    globals()[klassName] = klass
    return klass

clientHeaderFormat = '<LLLL'
clientHeaderSize = struct.calcsize(clientHeaderFormat)
def ClientMessageFromBuffer(buffer):
    '''Given some raw data (in e.g. a bytearray), extracts one message from it if possible, returning
    (thatMessage, numberOfBytesConsumed). If there isn't enough data for a message, returns
    (None, 0). Used by the Connection class.'''
    if len(buffer) < clientHeaderSize:
        # Don't even have enough to read a header yet
        return None, 0

    messageSize, protocol, code, counter = struct.unpack(clientHeaderFormat, buffer[:clientHeaderSize])
    if len(buffer) < messageSize:
        # We have some data, but not a full message
        return None, 0

    code = code & 0x0FFFFFFF # some high bits set for some reason
    klass = classMap[('c', code)]
    msg, consumed = klass.FromBytes(buffer, clientHeaderSize)
    msg._protocol = protocol
    msg._counter = counter
    remaining = messageSize - clientHeaderSize - consumed
    assert remaining >= 0, (remaining, msg, messageSize, clientHeaderSize, consumed)
    if remaining > 0:
        # look for a Remaining member parameter and use its name to set the data on the object
        name, sv = klass.members[-1]
        assert isinstance(sv, Remaining), '%d bytes remain for %s, expected a Remaining parameter' % (remaining, msg)
        setattr(msg, name, buffer[clientHeaderSize+consumed:messageSize])
    return msg, messageSize

serverHeaderFormat = '<LLL'
serverHeaderSize = struct.calcsize(serverHeaderFormat)
def ServerMessageFromBuffer(buffer):
    if len(buffer) < serverHeaderSize:
        # Don't even have enough to read a header yet
        return None, 0

    messageSize, protocol, code = struct.unpack(serverHeaderFormat, buffer[:serverHeaderSize])
    if len(buffer) < messageSize:
        # We have some data, but not a full message
        return None, 0

    code = code & 0x0FFFFFFF # some high bits set for some reason
    klass = classMap[('s', code)]
    msg, consumed = klass.FromBytes(buffer, serverHeaderSize)
    msg._protocol = protocol
    remaining = messageSize - serverHeaderSize - consumed
    assert remaining >= 0, (remaining, msg, messageSize, serverHeaderSize, consumed)
    if remaining > 0:
        # look for a Remaining member parameter and use its name to set the data on the object
        name, sv = klass.members[-1]
        assert isinstance(sv.structClass, Remaining), '%d bytes remain for %s, expected a Remaining parameter' % (remaining, msg)
        setattr(msg, name, buffer[serverHeaderSize+consumed:messageSize])
    return msg, messageSize

def ClientMessage(code, klassName, **kwargs):
    klass = MakeStruct(klassName, **kwargs)
    klass.code = code
    klass.fromAgent = 'c'
    classMap[('c', code)] = klass
    return klass

def ServerMessage(code, klassName, **kwargs):
    klass = MakeStruct(klassName, **kwargs)
    klass.code = code
    klass.fromAgent = 's'
    classMap[('s', code)] = klass
    return klass

def MessageToBytes(msg):
    b = msg.ToBytes()
    if msg.fromAgent == 'c':
        size = clientHeaderSize + len(b)
        code = msg.code | 0xF0000000 # not sure why we have to set these bits but ...
        return struct.pack(clientHeaderFormat, size, msg._protocol, code, msg._counter) + b
    else:
        size = serverHeaderSize + len(b)
        return struct.pack(serverHeaderFormat, size, msg._protocol, msg.code) + b

# ----------------------------------------------------------------------------------------------
# Client messages
# ----------------------------------------------------------------------------------------------

ClientMessage(0x01, 'COpen', appName='256s', _ignore='L', _ignore2='B', simID='3s',
              version=Array('L', 2), build=Array('L', 2))
ClientMessage(0x04, 'CMapClientEventToSimEvent', eventID='L', eventName='256s')
ClientMessage(0x05, 'CTransmitClientEvent', objectID='L', eventID='L', data='L', groupID='L', flags='L')
ClientMessage(0x07, 'CAddClientEventToNotificationGroup', groupID='L', eventID='L', maskable='L')
ClientMessage(0x09, 'CSetNotificationGroupPriority', groupID='L', priority='L')
ClientMessage(0x0c, 'CAddToDataDefinition', dataDefinitionID='L', datumName='256s', unitsName='256s',
              dataType='L', epsilon='f', datumID='L')
ClientMessage(0x0e, 'CRequestDataOnSimObject', requestID='L', definitionID='L', objectID='L',
              period='L', flags='L', origin='L', interval='L', limit='L')
ClientMessage(0x0f, 'CRequestDataOnSimObjectType', requestID='L', definitionID='L', radiusMeters='L', type='L')
ClientMessage(0x11, 'CMapInputEventToClientEvent', groupID='L', definition='256s', downID='L',
              downValue='L', upID='L', upValue='L', maskable='L')
ClientMessage(0x12, 'CSetInputGroupPriority', groupID='L', priority='L')
ClientMessage(0x15, 'CSetInputGroupState', groupID='L', state='L')
ClientMessage(0x17, 'CSubscribeToSystemEvent', clientEventID='L', eventName='256s')
ClientMessage(0x35, 'CRequestSystemState', requestID='L', stateName='256s')
ClientMessage(0xb9, 'CRequestJoystickDeviceInfo', requestID='L')

# ----------------------------------------------------------------------------------------------
# Server messages
# ----------------------------------------------------------------------------------------------

ServerMessage(0x01, 'SException', exception='L', sendID='L', index='L')
ServerMessage(0x02, 'SOpen', appName='256s', appVer=Array('L', 2), appBuild=Array('L', 2),
                             scVer=Array('L', 2), scBuild=Array('L', 2), _ignore='L', _ignore2='L')
ServerMessage(0x03, 'SQuit')
ServerMessage(0x04, 'SEvent', groupID='L', eventID='L', data='i', flags='L')
ServerMessage(0x08, 'SSimObjectData', requestID='L', objectID='L', definitionID='L', flags='L',
              entryNumber='L', outOf='L', defineCount='L', data=Remaining())
ServerMessage(0x09, 'SSimObjectDataByType', requestID='L', objectID='L', definitionID='L', flags='L',
              entryNumber='L', outOf='L', defineCount='L', data=Remaining())
ServerMessage(0x0f, 'SSystemState', requestID='L', dataInteger='L', dataFloat='f', dataString='260s')
MakeStruct('JoystickDeviceInfo', name='128s', number='L')
ServerMessage(0x40, 'SJoystickDeviceInfo', requestID='L', count='L', joysticks=Array(JoystickDeviceInfo, 'count'))

